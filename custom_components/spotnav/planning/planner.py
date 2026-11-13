"""The Auto-price charging planner: pure arithmetic, no Home Assistant in it.

Prices are normalized onto a 15-minute grid of absolute instants, converted to the
area's major unit, taxed (energy tax and transfer fee in the minor unit, then VAT over
the sum), and exactly the needed whole slots are chosen for the lowest total cost: in at most the
configured number of contiguous runs, or, with automatic periods, weighing a start cost per run and
keeping every run at least half an hour long. A need the departure leaves no time
for is planned as best effort: every whole slot up to the departure, marked
[PlanResult.short_of_deadline]. Every failure is a named
[PlanResult.reason]. A slot nobody has published is never filled from another day: the
window ends in `insufficient_price_horizon` and `planning/price_wait.py` decides what next.

Pure: no `hass`, entity, service, timer, storage or network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Final, Literal


from .. import time_zones
from ..pricing.relay_contract import PriceDocument


#: Contract version of the inputs, result and JSON fixtures. Bump when a field changes meaning.
CONTRACT_VERSION: Final = 1

STEP_MINUTES: Final = 15
SLOT_HOURS: Final = STEP_MINUTES / 60

HORIZON_HOURS: Final = 24

#: The farthest a dated departure may lie ahead, in local calendar days (the relay publishes one day
#: ahead, so a longer wait gains nothing). Enforced where a date is written; the planner trusts it.
MAX_DEPARTURE_DAYS_AHEAD: Final = 7

#: Bounds on the number of contiguous runs.
MIN_PERIODS: Final = 1
MAX_PERIODS: Final = 8

#: `max_periods` for automatic periods: no cap, a start cost per run and a shortest run instead.
AUTO_PERIODS: Final = None

#: What one more start costs under automatic periods, as energy at the window's mean effective price.
#: Each start costs something real (the car wakes, contactors close, the onboard charger ramps up, a cold
#: battery is heated again, one more cloud command can fail); a quarter of a kWh is the order of that loss.
#: Relative to the price level, so it means the same in every currency and market. At 11 kW (2.77 kWh a
#: quarter-hour) it bridges a gap quarter-hour up to about 9 % dearer than the slot it replaces, at 3.7 kW
#: up to about 27 %; a peak of twice the price, or of more than one dear quarter-hour, is never bridged.
START_COST_KWH: Final = 0.25

#: The shortest run under automatic periods, in quarter-hours (30 minutes); a need smaller than that is one run.
SHORTEST_BLOCK_SLOTS: Final = 2

#: Most separate charging windows the Morek fixed-time profile can carry (`api/morek_schedule.profile_for`).
MOREK_MAX_BLOCKS: Final = 3

#: Target-SoC slider bounds and its starting value.
DEFAULT_TARGET_SOC_PERCENT: Final = 80
ENERGY_SLIDER_MIN_KWH: Final = 1
ENERGY_SLIDER_MAX_KWH: Final = 100

EUR_RATE: Final = 1.0

#: Why no plan was produced, as a fact about the data. `unsupported_resolution` is not
#: here: `parse_day` refuses it upstream, so it is bad caller input and raises.
PlannerReason = Literal[
    "no_published_prices",
    "insufficient_price_horizon",
    "deadline_too_short",
    "missing_fx_rate",
    "price_policy_unavailable",
    "no_eligible_energy",
]

TargetEnergyReason = Literal["ok", "unknown_capacity", "already_at_target"]

PlannerCode = Literal[
    "invalid_phases",
    "invalid_amps",
    "invalid_voltage",
    "invalid_energy",
    "invalid_consumption",
    "invalid_periods",
    "invalid_departure",
    "invalid_timestamp",
    "invalid_number",
    "invalid_fiscal",
    "area_mismatch",
    "timezone_mismatch",
    "no_documents",
    "invalid_target_soc",
] | PlannerReason


class PlannerInputError(ValueError):
    """A caller's input that cannot be planned against.

    [code] is the program-facing fact; the message is for the log. This boundary does
    not repair a bad caller, because every value here changes what gets charged.
    """

    def __init__(self, code: PlannerCode, message: str) -> None:
        super().__init__(message)
        self.code: PlannerCode = code


def _refuse(code: PlannerCode, message: str) -> None:
    raise PlannerInputError(code, message)


def _finite(value: Any, code: PlannerCode, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _refuse(code, f"{what} must be a number")
    number = float(value)
    if not math.isfinite(number):
        _refuse("invalid_number", f"{what} must be finite")
    return number


def _positive(value: Any, code: PlannerCode, what: str) -> float:
    number = _finite(value, code, what)
    if number <= 0:
        _refuse(code, f"{what} must be positive")
    return number


def _aware(moment: Any, what: str) -> datetime:
    if not isinstance(moment, datetime):
        _refuse("invalid_timestamp", f"{what} must be a datetime")
    if moment.tzinfo is None:
        _refuse("invalid_timestamp", f"{what} must be timezone-aware")
    return moment


#: The days a high-load window applies on, and the last ISO weekday (Monday 1) each takes in.
HIGH_LOAD_DAYS: Final = {"all": 7, "weekdays": 5, "mon_sat": 6}


def high_load_window_problem(days: Any, from_month: Any, to_month: Any, from_hour: Any, to_hour: Any) -> str | None:
    """Why these five fields are not a high-load window, or `None` when they are one.

    `days` is `all`, `weekdays` (Monday to Friday) or `mon_sat`. Months 1 to 12, both included, wrapping over the
    new year (11 to 3 is November to March; equal is one month; 1 to 12 is all year). Whole hours of the area's
    own clock: `from_hour` 0 to 23, `to_hour` 1 to 24; a `from_hour` after `to_hour` wraps over midnight (22 to 6),
    and an equal pair is no window. One rule for the planner and the stored settings, so the two cannot disagree.
    """
    if not isinstance(days, str) or days not in HIGH_LOAD_DAYS:
        return f"days must be one of {sorted(HIGH_LOAD_DAYS)}"
    for name, value, low, high in (
        ("from_month", from_month, 1, 12),
        ("to_month", to_month, 1, 12),
        ("from_hour", from_hour, 0, 23),
        ("to_hour", to_hour, 1, 24),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be a whole number"
        if not low <= value <= high:
            return f"{name} must be between {low} and {high}"
    if from_hour == to_hour:
        return "from_hour and to_hour must differ"
    return None


@dataclass(frozen=True, slots=True)
class HighLoadWindow:
    """The hours a time-of-use grid fee charges its high rate in (and, later, a demand charge counts).

    Whole hours of the area's own clock (`tz`) on some days of the week (`days`) in some months, as
    `high_load_window_problem` states. The hours of a window that wraps over midnight belong to the day they
    start on: 22-06 on weekdays holds Friday night until Saturday 06:00 and not Sunday night, and its morning
    hours take the month of the evening before. Public holidays count as the weekdays they fall on. `tz` is the
    area's zone, set when the fees are resolved for an area; a stored window has none.
    """

    days: str = "weekdays"
    from_month: int = 11
    to_month: int = 3
    from_hour: int = 7
    to_hour: int = 19
    tz: str | None = None

    def validated(self) -> HighLoadWindow:
        """The same window, once it names its zone and its fields are a window."""
        problem = high_load_window_problem(self.days, self.from_month, self.to_month, self.from_hour, self.to_hour)
        if problem is not None:
            _refuse("invalid_fiscal", f"high_load_window: {problem}")
        if not isinstance(self.tz, str) or time_zones.zone(self.tz) is None:
            _refuse("invalid_fiscal", "a high-load window needs the area's time zone")
        return self

    def contains(self, start: datetime) -> bool:
        """Whether the interval starting at this instant lies in the window, on the area's clock.

        Judged at the start: window edges are whole hours and every interval starts on a quarter-hour, so an
        interval is wholly inside or wholly outside. A 23- or 25-hour day needs no case of its own: the hour on
        the clock decides, and a wrapped window's morning hours are tested as the day before's.
        """
        return self.window_day(start) is not None

    def window_day(self, start: datetime) -> date | None:
        """The day (on the area's clock) whose window the interval starting at this instant lies in, or `None`
        when it lies outside the window. A wrapped window's morning hours belong to the day before; every other
        hour to its own date. A demand charge's "different days" are these days (`planning/demand_charge.py`).
        """
        if self.tz is None:
            _refuse("invalid_fiscal", "a high-load window needs the area's time zone")
        local = _aware(start, "start").astimezone(time_zones.require_zone(self.tz))
        hour = local.hour
        day = local.date()
        if self.from_hour < self.to_hour:
            if not self.from_hour <= hour < self.to_hour:
                return None
        elif hour < self.to_hour:
            day -= timedelta(days=1)
        elif hour < self.from_hour:
            return None
        if day.isoweekday() > HIGH_LOAD_DAYS[self.days]:
            return None
        if self.from_month <= self.to_month:
            in_months = self.from_month <= day.month <= self.to_month
        else:
            in_months = day.month >= self.from_month or day.month <= self.to_month
        return day if in_months else None


@dataclass(frozen=True, slots=True)
class FiscalChoice:
    """The fiscal controls, as the caller set them.

    `tax_enabled` with no `tax_minor_per_kwh` is invalid rather than zero: "no tax" and
    "unknown tax" differ and only one is plannable. VAT works the same way.
    """

    tax_enabled: bool = False
    tax_minor_per_kwh: float | None = None
    transfer_enabled: bool = False
    transfer_minor_per_kwh: float | None = None
    vat_enabled: bool = False
    vat_percent: float | None = None
    #: The grid fee's part that is a percentage of the spot price (some operators charge it), before VAT. It
    #: follows the spot price's sign: a negative spot price makes it negative too.
    transfer_percent_enabled: bool = False
    transfer_percent: float | None = None
    #: The grid fee inside the high-load window (a time-of-use tariff): it replaces the transfer fee there.
    transfer_high_enabled: bool = False
    transfer_high_minor_per_kwh: float | None = None
    #: The high-load window, with the area's zone; present exactly while the high-load fee is on.
    high_load_window: HighLoadWindow | None = None

    def validated(self) -> FiscalChoice:
        """The same choice, once every enabled component has a usable value."""
        tax = _component("tax", self.tax_enabled, self.tax_minor_per_kwh)
        transfer = _component("transfer", self.transfer_enabled, self.transfer_minor_per_kwh)
        percent = _component("transfer_percent", self.transfer_percent_enabled, self.transfer_percent)
        high = _component("transfer_high", self.transfer_high_enabled, self.transfer_high_minor_per_kwh)
        window = None if self.high_load_window is None else self.high_load_window.validated()
        if high is not None and window is None:
            _refuse("invalid_fiscal", "the high-load grid fee is on but there is no high-load window")
        if high is None and window is not None:
            # The window prices nothing without the fee, and a window with no fee must not make a start required.
            _refuse("invalid_fiscal", "a high-load window was given without the high-load grid fee")
        # A zero VAT rate is legitimate (NO4); an absent one is not while VAT is on.
        vat: float | None = None
        if self.vat_enabled:
            if self.vat_percent is None:
                _refuse("invalid_fiscal", "VAT is enabled but no rate was given")
            vat = _finite(self.vat_percent, "invalid_fiscal", "vat_percent")
            if vat < 0:
                _refuse("invalid_fiscal", "vat_percent must not be negative")
        return FiscalChoice(
            tax_enabled=self.tax_enabled,
            tax_minor_per_kwh=tax,
            transfer_enabled=self.transfer_enabled,
            transfer_minor_per_kwh=transfer,
            vat_enabled=self.vat_enabled,
            vat_percent=vat,
            transfer_percent_enabled=self.transfer_percent_enabled,
            transfer_percent=percent,
            transfer_high_enabled=self.transfer_high_enabled,
            transfer_high_minor_per_kwh=high,
            high_load_window=window,
        )

    @property
    def needs_start(self) -> bool:
        """Whether a price depends on when the interval is: a high-load window is set."""
        return self.high_load_window is not None


def _component(name: str, enabled: bool, value: float | None) -> float | None:
    """A fee's explicit value, or `None` when the component is switched off.

    A value given while the component is off is validated and then ignored, so a
    component can be switched off without clearing its field.
    """
    if value is None:
        if enabled:
            _refuse("invalid_fiscal", f"{name} is enabled but no value was given")
        return None
    number = _finite(value, "invalid_fiscal", f"{name}_minor_per_kwh")
    if number < 0:
        _refuse("invalid_fiscal", f"{name}_minor_per_kwh must not be negative")
    return number if enabled else None


def effective_minor_per_kwh(local_major_per_kwh: float, fiscal: FiscalChoice, start: datetime | None = None) -> float:
    """The price an interval is planned against, in the area's minor unit.

    The order is not commutative, which is why it lives in one function:
    local major x 100, + energy tax, + transfer fee (the high-load one inside the high-load window),
    + the grid fee's percentage of the spot price (which follows the spot price's sign),
    x (1 + VAT / 100). VAT is last because it applies to the tax and the fees too.

    `start` is the interval's start. It is required while a high-load window is set: without it the fee in
    force is unknown, which is a refusal (`invalid_fiscal`), never the low fee.
    """
    spot_minor = local_major_per_kwh * 100
    minor = spot_minor
    if fiscal.tax_enabled and fiscal.tax_minor_per_kwh is not None:
        minor += fiscal.tax_minor_per_kwh
    transfer = fiscal.transfer_minor_per_kwh if fiscal.transfer_enabled else None
    window = fiscal.high_load_window
    if window is not None:
        if start is None:
            _refuse("invalid_fiscal", "a high-load window is set but the interval's start was not given")
        if fiscal.transfer_high_enabled and window.contains(start):
            transfer = fiscal.transfer_high_minor_per_kwh
    if transfer is not None:
        minor += transfer
    if fiscal.transfer_percent_enabled and fiscal.transfer_percent is not None:
        minor += spot_minor * fiscal.transfer_percent / 100
    if fiscal.vat_enabled and fiscal.vat_percent is not None:
        minor *= 1 + fiscal.vat_percent / 100
    return minor


def price_within_cap(
    local_major_per_kwh: float,
    *,
    cap_major_per_kwh: float,
    basis: str,
    fiscal: FiscalChoice,
    start: datetime,
) -> bool:
    """Compare an already currency-converted published price with a major-unit cap.

    The published price retains any charges included by the source. Configured
    variable cost additionally applies the existing fiscal calculation, whose
    return value is in minor units. Unknown prices must not be passed here.
    """
    price = _finite(local_major_per_kwh, "invalid_number", "local_major_per_kwh")
    cap = _finite(cap_major_per_kwh, "invalid_number", "cap_major_per_kwh")
    if basis == "nord_pool":
        comparison = price
    elif basis == "configured_variable_cost":
        comparison = effective_minor_per_kwh(price, fiscal.validated(), _aware(start, "start")) / 100.0
    else:
        _refuse("invalid_number", "a price cap requires a supported price basis")
    return comparison <= cap


#: The voltage between two phases on a TN network, what the planner assumed before it was a setting.
DEFAULT_VOLTAGE_BETWEEN_PHASES_V: Final = 400.0


def power_kw(amps: int, phases: int, voltage_between_phases_v: float = DEFAULT_VOLTAGE_BETWEEN_PHASES_V) -> float:
    """The power a connector draws: 230 V single phase, or three-phase at the voltage between phases
    (400 V on a TN network, 230 V on an IT network).

    Three-phase uses `sqrt(3)` times that voltage times the line current, not a "230 x 3" shortcut. A
    single-phase charger sees 230 V either way (on an IT network between two phases).
    """
    if phases == 1:
        return 230.0 * amps / 1000.0
    return math.sqrt(3.0) * voltage_between_phases_v * amps / 1000.0


def capped_power_kw(
    amps: int,
    phases: int,
    voltage_between_phases_v: float = DEFAULT_VOLTAGE_BETWEEN_PHASES_V,
    cap_kw: float | None = None,
) -> float:
    """[power_kw], or the power the car is known to really draw at that current when that is lower
    (`planning/learned_power.py`): what a plan counts on. A cap above the connector's power changes nothing."""
    planned = power_kw(amps, phases, voltage_between_phases_v)
    return planned if cap_kw is None else min(planned, cap_kw)


def energy_per_slot_kwh(
    amps: int,
    phases: int,
    voltage_between_phases_v: float = DEFAULT_VOLTAGE_BETWEEN_PHASES_V,
    cap_kw: float | None = None,
) -> float:
    """What one whole 15-minute slot delivers at that power (no more than `cap_kw`, when given)."""
    return capped_power_kw(amps, phases, voltage_between_phases_v, cap_kw) * SLOT_HOURS


#: Decimals the slot count is rounded to before its ceiling (a nanoslot is far below any meter's resolution).
_SLOT_DIGITS: Final = 9


def slots_needed(
    requested_kwh: float,
    amps: int,
    phases: int,
    voltage_between_phases_v: float = DEFAULT_VOLTAGE_BETWEEN_PHASES_V,
    cap_kw: float | None = None,
) -> int:
    """How many whole slots the request needs, and never fewer than one.

    Delivered energy may exceed the request by up to one slot; rounding down would
    deliver less than asked for.
    """
    # Rounded before the ceiling: a need of exactly N slots must not become N + 1 through float noise in the division.
    quotient = round(
        requested_kwh / energy_per_slot_kwh(amps, phases, voltage_between_phases_v, cap_kw), _SLOT_DIGITS
    )
    return max(1, math.ceil(quotient))


@dataclass(frozen=True, slots=True)
class PlanningSlot:
    """One 15-minute slot of published price, on the absolute grid.

    `local_major_per_kwh` is the relay's EUR price times the day document's own rate.
    `source` names the document it came from, for diagnostics only, never arithmetic.
    """

    start: datetime
    local_major_per_kwh: float
    source: str

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=STEP_MINUTES)


@dataclass(frozen=True, slots=True)
class SelectedSlot:
    """One slot the plan chose, with both prices and where the price came from."""

    start: datetime
    end: datetime
    local_major_per_kwh: float
    effective_minor_per_kwh: float
    unpriced: bool
    source: str


def planning_slots(
    documents: tuple[PriceDocument, ...],
    *,
    currency: str,
    timezone: str,
) -> tuple[PlanningSlot, ...]:
    """Every document's prices on one absolute 15-minute grid, deduplicated and time-sorted.

    A 60-minute row becomes four equal slots; an unrepresentable resolution is refused.
    EUR has rate 1, a non-EUR area needs that day's own rate (else refused). When two
    documents cover an instant, the first in the caller's order wins. Sorting is by absolute
    time so DST nights stay correct.
    """
    if not documents:
        _refuse("no_documents", "the planner needs at least one price document")

    by_instant: dict[datetime, PlanningSlot] = {}
    # A display day cut from two market files is priced piece by piece, each with its own file's rate.
    for document in (piece for whole in documents for piece in whole.pieces()):
        resolution = document.resolution_minutes
        if STEP_MINUTES > resolution or resolution % STEP_MINUTES != 0:
            # Unreachable from `parse_day`; a forged document is bad input, not a data state.
            _refuse(
                "unsupported_resolution",
                f"a {resolution}-minute document cannot be represented on a {STEP_MINUTES}-minute grid",
            )
        per_row = resolution // STEP_MINUTES
        rate = _rate_for(document, currency)
        for index, euro in enumerate(document.prices):
            row_start = document.start_instant + timedelta(minutes=resolution) * index
            for step in range(per_row):
                start = row_start + timedelta(minutes=STEP_MINUTES) * step
                if start in by_instant:
                    continue
                by_instant[start] = PlanningSlot(
                    start=start,
                    local_major_per_kwh=euro * rate,
                    source=document.day.isoformat(),
                )
    return tuple(by_instant[start] for start in sorted(by_instant))


def _rate_for(document: PriceDocument, currency: str) -> float:
    """The day's own rate for the area's currency, or 1 for a euro area.

    A missing or unusable rate is a `missing_fx_rate` refusal, not a `KeyError` and
    not another day's number.
    """
    if currency.upper() == "EUR":
        return EUR_RATE
    rate = document.fx_rate(currency)
    if rate is None:
        _refuse(
            "missing_fx_rate",
            f"the {document.day.isoformat()} document has no {currency} rate",
        )
    if not math.isfinite(rate) or rate <= 0:
        _refuse("missing_fx_rate", f"the {document.day.isoformat()} {currency} rate is not usable")
    return rate


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Everything the planner needs, validated, with nothing read from anywhere.

    The identity fields (`area_id`, `timezone`, `currency`, units) are the
    catalogue's, passed in rather than looked up.
    """

    area_id: str
    timezone: str
    currency: str
    major_unit: str
    minor_unit: str
    documents: tuple[PriceDocument, ...]
    now: datetime
    phases: int
    amps: int
    requested_kwh: float
    consumption_kwh_per_10km: float
    fiscal: FiscalChoice = FiscalChoice()
    #: A hard cap on the runs (1 to 8), or `AUTO_PERIODS` (`None`): a start cost per run and a shortest run.
    max_periods: int | None = MIN_PERIODS
    departure: time | None = None
    #: The local date the departure falls on, or `None` for the next occurrence of `departure`. With a
    #: date the deadline is that wall time on that date and the horizon reaches it (up to 7 days), so
    #: intervals after the last published one are unknown, not absent.
    departure_date: date | None = None
    #: Latest instant a selected slot may end at, tighter than the departure or horizon.
    #: Lets `planning/price_wait.py` plan inside the priced part of the window.
    window_end: datetime | None = None
    #: The voltage between two phases (400 V TN, 230 V IT): what three-phase power is figured from.
    voltage_between_phases_v: float = DEFAULT_VOLTAGE_BETWEEN_PHASES_V
    #: The power this car is known to really draw at this current (`planning/learned_power.py`), or `None`:
    #: the plan counts on the lower of it and the current's power (`planned_kw`).
    power_cap_kw: float | None = None
    #: A configured cap must never be silently ignored by any planner entry point.
    soft_price_cap: float | None = None
    cap_price_basis: str | None = None
    #: Resolved wall-energy deficit to the minimum, or None to forbid exceptions.
    minimum_energy_kwh: float | None = None
    #: Partial-horizon policy: earliest meaningful next price re-evaluation.
    partial_recheck_at: datetime | None = None
    #: Also consider the rest of the current published 15-minute interval, starting at `now` (a schedule-owned
    #: charger can start between grid boundaries). Off keeps the whole-slot behaviour from the next boundary.
    include_current_interval: bool = False
    #: A hard limit on separate windows the executor can carry, applied on top of `max_periods`, in
    #: automatic-period mode too. `None` for no executor limit.
    max_blocks: int | None = None

    @property
    def planned_kw(self) -> float:
        """The power the plan counts on: the current's, or the learned power when that is lower."""
        return capped_power_kw(self.amps, self.phases, self.voltage_between_phases_v, self.power_cap_kw)

    def validated(self) -> PlanRequest:
        """The same request, once every field is known to be plannable."""
        if self.phases not in (1, 3):
            _refuse("invalid_phases", "phases must be 1 or 3")
        if isinstance(self.amps, bool) or not isinstance(self.amps, int) or self.amps <= 0:
            _refuse("invalid_amps", "amps must be a positive whole number")
        if self.voltage_between_phases_v not in (230.0, 400.0):
            _refuse("invalid_voltage", "the voltage between phases must be 230 or 400")
        if self.max_periods is not AUTO_PERIODS and not MIN_PERIODS <= _as_int(self.max_periods) <= MAX_PERIODS:
            _refuse("invalid_periods", f"max_periods must be between {MIN_PERIODS} and {MAX_PERIODS}")
        if self.max_blocks is not None and not MIN_PERIODS <= _as_int(self.max_blocks) <= MAX_PERIODS:
            _refuse("invalid_periods", f"max_blocks must be between {MIN_PERIODS} and {MAX_PERIODS}")
        if not isinstance(self.include_current_interval, bool):
            _refuse("invalid_number", "include_current_interval must be a boolean")
        _positive(self.requested_kwh, "invalid_energy", "requested_kwh")
        if self.minimum_energy_kwh is not None:
            minimum = _finite(self.minimum_energy_kwh, "invalid_energy", "minimum_energy_kwh")
            if minimum < 0 or minimum > self.requested_kwh:
                _refuse("invalid_energy", "minimum_energy_kwh must be between zero and requested_kwh")
        _positive(self.consumption_kwh_per_10km, "invalid_consumption", "consumption_kwh_per_10km")
        _aware(self.now, "now")
        if self.window_end is not None:
            _aware(self.window_end, "window_end")
        if self.partial_recheck_at is not None:
            _aware(self.partial_recheck_at, "partial_recheck_at")
        if self.power_cap_kw is not None:
            _positive(self.power_cap_kw, "invalid_number", "power_cap_kw")
        if self.soft_price_cap is not None:
            _finite(self.soft_price_cap, "invalid_number", "soft_price_cap")
            if self.cap_price_basis not in ("nord_pool", "configured_variable_cost"):
                _refuse("invalid_number", "a price cap requires a supported price basis")
        elif self.cap_price_basis is not None and self.cap_price_basis not in ("nord_pool", "configured_variable_cost"):
            _refuse("invalid_number", "unsupported price basis")
        if self.departure is not None:
            if not isinstance(self.departure, time):
                _refuse("invalid_departure", "departure must be a wall time")
            if self.departure.tzinfo is not None:
                _refuse("invalid_departure", "departure must be an area-local wall time, not an instant")
            if not (0 <= self.departure.hour <= 23 and 0 <= self.departure.minute <= 59):
                _refuse("invalid_departure", "departure must be a valid time of day")
        if self.departure_date is not None:
            if self.departure is None:
                _refuse("invalid_departure", "a departure date needs a departure time")
            if not isinstance(self.departure_date, date) or isinstance(self.departure_date, datetime):
                _refuse("invalid_departure", "departure_date must be a calendar date")
        if time_zones.zone(self.timezone) is None:
            _refuse("timezone_mismatch", f"{self.timezone!r} is not a known timezone")
        for document in self.documents:
            if document.area_id != self.area_id:
                _refuse(
                    "area_mismatch",
                    f"a {document.area_id!r} document was given to a {self.area_id!r} plan",
                )
            if document.tz != self.timezone:
                _refuse(
                    "timezone_mismatch",
                    f"a document in {document.tz!r} was given to a plan in {self.timezone!r}",
                )
            if document.unit != "EUR/kWh":
                _refuse("invalid_number", f"a document priced in {document.unit!r} cannot be planned")
        return PlanRequest(
            area_id=self.area_id,
            timezone=self.timezone,
            currency=self.currency,
            major_unit=self.major_unit,
            minor_unit=self.minor_unit,
            documents=self.documents,
            now=self.now,
            phases=self.phases,
            amps=self.amps,
            requested_kwh=float(self.requested_kwh),
            consumption_kwh_per_10km=float(self.consumption_kwh_per_10km),
            fiscal=self.fiscal.validated(),
            max_periods=None if self.max_periods is AUTO_PERIODS else _as_int(self.max_periods),
            departure=self.departure,
            departure_date=self.departure_date,
            window_end=self.window_end,
            voltage_between_phases_v=float(self.voltage_between_phases_v),
            power_cap_kw=None if self.power_cap_kw is None else float(self.power_cap_kw),
            soft_price_cap=None if self.soft_price_cap is None else float(self.soft_price_cap),
            cap_price_basis=self.cap_price_basis,
            minimum_energy_kwh=None if self.minimum_energy_kwh is None else float(self.minimum_energy_kwh),
            partial_recheck_at=self.partial_recheck_at,
            include_current_interval=self.include_current_interval,
            max_blocks=self.max_blocks,
        )


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _refuse("invalid_periods", "max_periods must be a whole number")
    return value


@dataclass(frozen=True, slots=True)
class PlanResult:
    """One plan, or the reason there is none; never `None` and never an exception.

    Every number is in the unit its name says: `estimated_cost` in the major unit,
    `effective_minor_per_kwh` in the minor unit, and `local_major_per_kwh` as the
    relay's price converted with the day's own rate and nothing added.
    """

    version: int
    area_id: str
    timezone: str
    currency: str
    major_unit: str
    minor_unit: str
    now: datetime
    reason: PlannerReason | None
    power_kw: float
    requested_kwh: float
    delivered_kwh: float
    distance_mil: float
    estimated_cost: float
    periods: tuple[tuple[datetime, datetime], ...]
    slots: tuple[SelectedSlot, ...]
    unpriced_slots: int
    priced_slots: int
    unpriced: bool
    slots_needed: int
    #: The candidate range the plan was chosen from; empty only for a refusal.
    horizon: tuple[HorizonInterval, ...] = ()
    #: The need cannot be met by the departure, so this is the best effort: every whole slot from the
    #: first usable one to the departure, `delivered_kwh` below `requested_kwh` (`_window`).
    short_of_deadline: bool = False
    #: What the same energy would cost charged from the first usable slot on, at the same power, in the major
    #: unit: what the plan is compared with ("against charging now"). `None` without a priced plan.
    now_cost: float | None = None
    #: The charge stops once the need is delivered (`ending_at_need`): `delivered_kwh` is the need, and the costs
    #: count the last slot only for the share of it the need takes.
    ends_at_need: bool = False
    #: A cap-aware plan already contains the actual shortened windows.
    exact_periods: bool = False
    #: Remaining requested energy, for capped plans including an empty result.
    policy_shortfall_kwh: float | None = None
    #: None when no minimum deficit was supplied; otherwise the unmet wall energy.
    minimum_shortfall_kwh: float | None = None
    #: Actual above-cap portions of the selected windows and their wall energy.
    exception_periods: tuple[tuple[datetime, datetime], ...] = ()
    exception_kwh: float = 0.0
    #: First missing interval, not a claim that later intervals are priced.
    price_coverage_end: datetime | None = None
    #: Energy of the leading fragment (the rest of the current price interval, `slots[0]`), on top of the
    #: `slots_needed` whole slots; zero for a plan that starts at a grid boundary.
    lead_kwh: float = 0.0
    #: The executor's window limit applied to this plan (`PlanRequest.max_blocks`).
    block_limit: int | None = None
    #: Windows the same request would use without that limit, only when that is more than the limit.
    unrestricted_blocks: int | None = None
    #: Extra estimated cost (major unit) and energy the limit costs against that unrestricted plan; `None` unknown.
    block_limit_extra_cost: float | None = None
    block_limit_shortfall_kwh: float | None = None

    @property
    def block_limit_compromise(self) -> bool:
        """The limit forced a different plan than the request would otherwise choose."""
        return self.unrestricted_blocks is not None

    @property
    def has_plan(self) -> bool:
        return self.reason is None

    @property
    def need_met_at(self) -> datetime | None:
        """When a plan that stops at its need is expected to have delivered it: inside its last slot, by the share
        of that slot the need takes. `None` for a plan that runs its whole slots, or one whose need fills them."""
        if not self.ends_at_need or not self.periods or self.power_kw <= 0:
            return None
        # The whole slots, plus the rest of the current interval when the plan starts in it.
        extra = self.slots_needed * self.power_kw * SLOT_HOURS + self.lead_kwh - self.delivered_kwh
        if extra <= _WHOLE_SLOTS_KWH:
            return None
        return self.periods[-1][1] - timedelta(hours=extra / self.power_kw)

    @property
    def shown_periods(self) -> tuple[tuple[datetime, datetime], ...]:
        """The periods as a person is shown them: the last one ending where the need is expected to be met.
        Legacy plans install whole slots; cap-aware plans already contain exact periods."""
        met = self.need_met_at
        if met is None:
            return self.periods
        return (*self.periods[:-1], (self.periods[-1][0], met))


def first_start_for(documents: tuple[PriceDocument, ...], *, now: datetime, tz: str) -> datetime:
    """The first usable planning instant for `now`, on the grid `calculate_plan` uses.

    Mirrors the start of `calculate_plan` (kept in step by hand). Slots are built with
    `currency="EUR"` because only `start` is read and a real currency could make
    `planning_slots` refuse a document lacking its rate. Requires at least one document.
    """
    slots = planning_slots(documents, currency="EUR", timezone=tz)
    zone = time_zones.require_zone(tz)
    day_offset = slots[0].start.astimezone(zone).utcoffset() or timedelta(0)
    day_zone = timezone(day_offset)
    local_now = now.astimezone(day_zone)
    floored = local_now - timedelta(
        minutes=local_now.minute % STEP_MINUTES, seconds=local_now.second, microseconds=local_now.microsecond
    )
    return floored if floored >= local_now else floored + timedelta(minutes=STEP_MINUTES)


def departure_for(
    documents: tuple[PriceDocument, ...], *, now: datetime, tz: str, departure: time
) -> datetime:
    """`departure` resolved to the instant `calculate_plan` would use for this `now`.

    Composes `first_start_for` with `resolve_departure`; adds no policy of its own.
    """
    first_start = first_start_for(documents, now=now, tz=tz)
    return resolve_departure(now, tz, departure, first_start)


def resolve_departure(now: datetime, tz: str, departure: time, first_start: datetime) -> datetime:
    """The user's departure wall time as an absolute instant, in the area's own zone.

    A real area-local wall time, not a fixed offset (Stockholm's 03:30 on 2026-03-29 is
    01:30Z). It is built on the local date of `now`, or the next local date if not strictly
    after the first usable slot. An ambiguous time takes the earlier occurrence (cannot
    arrive late); a nonexistent one advances to the first valid instant after the gap.
    Compared as UTC instants, never wall datetimes.
    """
    zone = time_zones.require_zone(tz)
    local_now = now.astimezone(zone)
    for day in (local_now.date(), local_now.date() + timedelta(days=1)):
        moment = local_instant(day, departure, zone)
        if _as_utc(moment) > _as_utc(first_start):
            return moment
    # Unreachable for a real time of day; keeps a pathological zone answering.
    return local_instant(local_now.date() + timedelta(days=1), departure, zone)


def _as_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)


def local_instant(day: date, wall: time, zone) -> datetime:
    """One wall time on one local calendar date, resolved to a single instant.

    Real times are told from gap times by a round trip through UTC: if it does not
    return the same wall clock, the time does not exist and the first valid instant
    after the gap is used.
    """
    naive = datetime(day.year, day.month, day.day, wall.hour, wall.minute)
    candidate = naive.replace(tzinfo=zone)
    if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
        # Real; `fold=0` picks the earlier occurrence of an ambiguous time.
        return candidate
    for minutes in range(1, 24 * 60):
        shifted = naive + timedelta(minutes=minutes)
        probe = shifted.replace(tzinfo=zone)
        if probe.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == shifted:
            return probe
    return candidate


@dataclass(frozen=True, slots=True)
class HorizonInterval:
    """One candidate instant of a calculation, as the calculation saw it.

    The same normalized candidates `calculate_plan` chooses from, so a chart drawn
    from these rows and its plan cannot disagree.
    """

    start: datetime
    end: datetime
    utc_start: datetime
    utc_end: datetime
    day: date
    published_major_per_kwh: float
    effective_minor_per_kwh: float
    in_proposal: bool


def _candidates(
    slots: tuple[PlanningSlot, ...],
    *,
    first_start: datetime,
    required_end: datetime,
) -> tuple[list[PlanningSlot], PlannerReason | None]:
    """Every slot the calculation may choose from, always a published one.

    The single place the candidate range is built. A gap ends with
    `insufficient_price_horizon`; never a shorter list or another day's price.
    """
    candidates: list[PlanningSlot] = []
    published = {slot.start: slot for slot in slots}
    time_cursor = first_start
    while time_cursor < required_end:
        actual = published.get(time_cursor)
        if actual is None:
            return ([], "insufficient_price_horizon")
        candidates.append(actual)
        time_cursor += timedelta(minutes=STEP_MINUTES)
    return (candidates, None)


def _horizon(
    candidates: list[PlanningSlot],
    selected: tuple[PlanningSlot, ...],
    *,
    zone: Any,
    fiscal: FiscalChoice,
) -> tuple[HorizonInterval, ...]:
    """The candidate range as an immutable projection of what the calculation saw.

    `in_proposal` marks the instants the plan selected, which is what a chart shades.
    """
    chosen = {slot.start for slot in selected}
    rows: list[HorizonInterval] = []
    for slot in candidates:
        # Build bounds from the instant: wall-clock +15 min is not 15 elapsed minutes across
        # an offset transition, and an autumn repeated hour would fold two rows together.
        utc_start = slot.start.astimezone(timezone.utc)
        utc_end = utc_start + timedelta(minutes=STEP_MINUTES)
        local = utc_start.astimezone(zone)
        rows.append(
            HorizonInterval(
                start=local,
                end=utc_end.astimezone(zone),
                utc_start=utc_start,
                utc_end=utc_end,
                day=local.date(),
                published_major_per_kwh=slot.local_major_per_kwh,
                effective_minor_per_kwh=effective_minor_per_kwh(slot.local_major_per_kwh, fiscal, slot.start),
                in_proposal=slot.start in chosen,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _Window:
    """The geometry of one calculation: where it starts, where it must end, how much it needs."""

    slots: tuple[PlanningSlot, ...]
    zone: Any
    first_start: datetime
    horizon: datetime
    #: Instant the charge must finish by (departure or tighter `window_end`); `None` if neither.
    deadline: datetime | None
    required_end: datetime
    needed: int
    per_slot: float
    #: The need does not fit before the departure: `needed` is every whole slot that does (best effort).
    short: bool = False
    #: The rest of the current price interval, used as the start of the plan (`_window(current=True)`);
    #: `needed` then counts only the whole slots on top of it, and may be zero.
    lead: SelectedSlot | None = None

    @property
    def end(self) -> datetime:
        """The last instant a selected slot may end at."""
        return self.deadline if self.deadline is not None else self.horizon


def _window(request: PlanRequest, *, current: bool = False) -> _Window | PlannerReason:
    """Normalize the prices and lay out the window, or name why there is none.

    Shared by `calculate_plan` and `price_gap` so both agree on which prices a request needs.
    With `current` the rest of the current price interval (see `_lead_interval`) is part of the plan and
    delivers its share of the need first: the whole slots needed, the deadline test and the prices required
    are those of the remainder, and a deadline inside the current interval is a window of that interval alone.
    """
    zone = time_zones.require_zone(request.timezone)
    try:
        slots = planning_slots(request.documents, currency=request.currency, timezone=request.timezone)
    except PlannerInputError as err:
        # A missing rate is a data fact and becomes a reason; everything else is bad input.
        if err.code == "missing_fx_rate":
            return "missing_fx_rate"
        raise
    if not slots:
        return "no_published_prices"

    # Two zones: `zone` is the area's own, for calendar and wall-clock questions.
    # `day_zone` is the fixed offset of the day's first published point, used only to
    # find the next quarter-hour boundary (elapsed-time arithmetic). The departure is
    # resolved separately in `zone` by [resolve_departure].
    day_offset = slots[0].start.astimezone(zone).utcoffset() or timedelta(0)
    day_zone = timezone(day_offset)
    now = request.now.astimezone(day_zone)
    floored = now - timedelta(
        minutes=now.minute % STEP_MINUTES, seconds=now.second, microseconds=now.microsecond
    )
    # A `now` exactly on a boundary is usable.
    first_start = floored if floored >= now else floored + timedelta(minutes=STEP_MINUTES)
    horizon = first_start + timedelta(hours=HORIZON_HOURS)

    per_slot = energy_per_slot_kwh(
        request.amps, request.phases, request.voltage_between_phases_v, request.power_cap_kw
    )

    deadline: datetime | None = None
    if request.departure is not None:
        if request.departure_date is not None:
            deadline = local_instant(request.departure_date, request.departure, zone)
            # A dated departure reaches as far as its deadline, past the 24 hours of a daily one.
            horizon = max(horizon, deadline)
        else:
            # A departure inside the current interval is still ahead when that interval is planned from `now`
            # (the first whole slot would otherwise push it to tomorrow).
            reference = request.now if request.include_current_interval else first_start
            deadline = resolve_departure(request.now, request.timezone, request.departure, reference)
    departure_deadline = deadline
    if request.window_end is not None:
        deadline = request.window_end if deadline is None else min(deadline, request.window_end)

    lead = _lead_interval(request, slots, first_start, deadline) if current else None
    need_kwh = request.requested_kwh
    if lead is not None:
        need_kwh -= (lead.end - lead.start).total_seconds() / 3600 * request.planned_kw
        if need_kwh <= _WHOLE_SLOTS_KWH:
            # The rest of this interval alone delivers the need: no whole slot is required.
            return _Window(
                slots=slots, zone=zone, first_start=first_start, horizon=horizon, deadline=deadline,
                required_end=first_start, needed=0, per_slot=per_slot, lead=lead,
            )
    needed = slots_needed(
        need_kwh, request.amps, request.phases, request.voltage_between_phases_v, request.power_cap_kw
    )
    duration = timedelta(minutes=STEP_MINUTES * needed)
    short = False

    if deadline is None:
        # No deadline: the window ends exactly at the horizon.
        required_end = horizon
        latest_start_exclusive = horizon - duration + timedelta(minutes=STEP_MINUTES)
        if latest_start_exclusive <= first_start:
            # The request cannot fit in the window at all, whatever the prices say.
            return "insufficient_price_horizon"
    else:
        # Deadline: the bound is the latest start, so the last slot may end at the deadline.
        # Absolute time throughout: the deadline is in the area's zone, and wall-clock arithmetic on
        # it would move the latest start by an hour on a clock-change night. The deadline is first
        # brought down to the last slot boundary at or before it, so no slot starting at or after the
        # departure is ever required (a 00:10 departure needs no price for 00:00 of the next day).
        step = timedelta(minutes=STEP_MINUTES)
        last_end = first_start + step * ((deadline.astimezone(timezone.utc) - first_start) // step)
        latest_start_exclusive = min(horizon, last_end - duration + step)
        if latest_start_exclusive <= first_start:
            if departure_deadline is None or deadline != departure_deadline:
                # A caller's own tighter window (the published part, what must be bought before a
                # publication) is a question about that window: it is refused, never shortened.
                return "deadline_too_short"
            # The need cannot be met by the departure. Best effort, the conservative choice: every whole
            # slot from the first usable one up to the departure, so the car leaves with the most energy
            # there was time for. That is one contiguous run, so the period limit can never cut energy
            # here; were it ever to, delivering the most energy wins over the limit.
            fit = (min(last_end, horizon) - first_start) // step
            if fit < 1:
                if lead is None:
                    # Not one whole slot before the departure: nothing can be planned.
                    return "deadline_too_short"
                # Only the rest of the current interval fits before the departure: use all of it.
                return _Window(
                    slots=slots, zone=zone, first_start=first_start, horizon=horizon, deadline=deadline,
                    required_end=first_start, needed=0, per_slot=per_slot, short=True, lead=lead,
                )
            needed = fit
            duration = step * fit
            latest_start_exclusive = first_start + step
            short = True
        # Where the latest possible start's run ends: never past the deadline's last slot boundary, so
        # no price at or after the deadline (or a caller's own `window_end`) is ever required.
        required_end = latest_start_exclusive - step + duration
    return _Window(
        slots=slots,
        zone=zone,
        first_start=first_start,
        horizon=horizon,
        deadline=deadline,
        required_end=required_end,
        needed=needed,
        per_slot=per_slot,
        short=short,
        lead=lead,
    )


@dataclass(frozen=True, slots=True)
class PriceGap:
    """Where a request's window runs out of published prices.

    `known` is the contiguous published slots from the first usable one up to the gap;
    `missing_from` is the first unpublished instant; `deadline` is when the charge must
    finish (departure or 24-hour horizon).
    """

    first_start: datetime
    missing_from: datetime
    deadline: datetime
    known: tuple[PlanningSlot, ...]
    #: The need does not fit before the departure at all (best effort, `_Window.short`).
    short: bool = False
    #: The published rest of the current price interval (`include_current_interval` only): known capacity from
    #: now to the next boundary that `known` (from that boundary) does not list. Never priced from a neighbour.
    current: SelectedSlot | None = None


def price_gap(request: PlanRequest) -> PriceGap | None:
    """The gap in a request's published prices, or `None` when it is fully priced.

    Also `None` when the window cannot be laid out (`calculate_plan` reports why).
    """
    request = request.validated()
    window = _window(request)
    if isinstance(window, str):
        return None
    published = {slot.start: slot for slot in window.slots}
    known: list[PlanningSlot] = []
    cursor = window.first_start
    # Capped plans can use the fractional interval before a non-grid deadline;
    # uncapped plans use only whole slots and retain their existing wait policy.
    end = window.end if request.soft_price_cap is not None else window.required_end
    while cursor < end:
        slot = published.get(cursor)
        if slot is None:
            return PriceGap(
                first_start=window.first_start,
                missing_from=cursor,
                deadline=window.end,
                known=tuple(known),
                short=window.short,
                current=_lead_interval(request, window.slots, window.first_start, window.deadline),
            )
        known.append(slot)
        cursor += timedelta(minutes=STEP_MINUTES)
    return None


def plan_unpriced(request: PlanRequest) -> PlanResult:
    """Charge at once from the first usable slot, at unknown prices.

    Used when prices are unpublished and waiting would miss the deadline (`price_wait`).
    One run of consecutive slots, each flagged unpriced; cost is reported as zero.
    """
    request = request.validated()
    if request.soft_price_cap is not None:
        return _no_plan(request, "price_policy_unavailable")
    window = _window(request)
    if isinstance(window, str):
        return _no_plan(request, window)
    step = timedelta(minutes=STEP_MINUTES)
    count = 0
    while count < window.needed and window.first_start + step * (count + 1) <= window.end:
        count += 1
    if count == 0:
        return _no_plan(request, "deadline_too_short")
    starts = [window.first_start + step * index for index in range(count)]
    delivered = count * window.per_slot
    return PlanResult(
        version=CONTRACT_VERSION,
        area_id=request.area_id,
        timezone=request.timezone,
        currency=request.currency,
        major_unit=request.major_unit,
        minor_unit=request.minor_unit,
        now=request.now,
        reason=None,
        power_kw=request.planned_kw,
        requested_kwh=request.requested_kwh,
        delivered_kwh=delivered,
        distance_mil=delivered / request.consumption_kwh_per_10km,
        estimated_cost=0.0,
        periods=((starts[0], starts[-1] + step),),
        slots=tuple(
            SelectedSlot(
                start=start,
                end=start + step,
                local_major_per_kwh=0.0,
                effective_minor_per_kwh=0.0,
                unpriced=True,
                source=UNPRICED_SOURCE,
            )
            for start in starts
        ),
        unpriced_slots=count,
        priced_slots=0,
        unpriced=True,
        slots_needed=count,
        short_of_deadline=window.short,
    )


#: `SelectedSlot.source` of a slot charged without any published price (`plan_unpriced`).
UNPRICED_SOURCE: Final = "unpriced"


def calculate_plan(request: PlanRequest) -> PlanResult:
    """The whole calculation: normalize, choose, and report, or say why not.

    Each step can end with a named reason rather than a partial answer. What to do about
    `insufficient_price_horizon` is `price_wait`'s decision, not this function's.

    With `max_blocks` the plan never uses more windows than the executor can carry; when the same request
    would otherwise have used more, the result says what the limit cost.
    """
    request = request.validated()
    result = _calculate(request)
    limit = request.max_blocks
    if limit is None or not result.has_plan:
        return result
    free = _calculate(replace(request, max_blocks=None))
    if not free.has_plan or len(free.periods) <= limit:
        return replace(result, block_limit=limit)
    priced = not (result.unpriced or free.unpriced)
    return replace(
        result,
        block_limit=limit,
        unrestricted_blocks=len(free.periods),
        block_limit_extra_cost=max(0.0, result.estimated_cost - free.estimated_cost) if priced else None,
        block_limit_shortfall_kwh=max(0.0, free.delivered_kwh - result.delivered_kwh),
    )


def _effective_limit(request: PlanRequest) -> int | None:
    """The hard run limit: the configured one and the executor's, whichever is tighter; `None` for neither."""
    if request.max_blocks is None:
        return request.max_periods
    if request.max_periods is None:
        return request.max_blocks
    return min(request.max_periods, request.max_blocks)


def _lead_interval(
    request: PlanRequest, slots: tuple[PlanningSlot, ...], first_start: datetime, limit: datetime | None
) -> SelectedSlot | None:
    """What is left of the current published interval, from now to the next grid boundary, or `None`.

    Only when asked for, only inside a published interval (an unpublished current interval is never priced
    from a neighbour) and only up to `limit` (a deadline inside the interval). No minimum length: any time
    that is available is a candidate, and the planner decides whether it is worth using. Elapsed time is not
    counted: the interval starts at `now`. The energy it delivers is proportional to its duration, at the
    price of the whole interval.
    """
    if not request.include_current_interval or first_start <= request.now:
        return None
    end = first_start if limit is None else min(first_start, limit)
    start = request.now.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if end <= start:
        return None
    current_start = first_start - timedelta(minutes=STEP_MINUTES)
    current = next((slot for slot in slots if slot.start == current_start), None)
    if current is None:
        return None
    return SelectedSlot(
        start=start,
        end=end,
        local_major_per_kwh=current.local_major_per_kwh,
        effective_minor_per_kwh=effective_minor_per_kwh(current.local_major_per_kwh, request.fiscal, current.start),
        unpriced=False,
        source=current.source,
    )


def _calculate(request: PlanRequest) -> PlanResult:
    """One calculation of a validated request, without the comparison against an unrestricted plan.

    With `include_current_interval` the whole-slot plan is also calculated with the rest of the current price
    interval as its start, and whichever plan delivers more of the need, or the same for less, is the result.
    """
    if request.soft_price_cap is not None:
        return _calculate_capped(request)
    plain = _whole_slot_plan(request, current=False)
    if not request.include_current_interval:
        return plain
    started = _whole_slot_plan(request, current=True)
    if not started.has_plan or started.lead_kwh <= 0:
        return plain
    if not plain.has_plan:
        # The current interval made a plan possible (a deadline too close, or prices missing further out).
        return started
    rows = plain.horizon or started.horizon
    start_cost = START_COST_KWH * sum(abs(row.effective_minor_per_kwh) for row in rows) / len(rows) if rows else 0.0

    def rank(result: PlanResult) -> tuple[float, float]:
        # As the charge that stops at its need would be: energy first (a best-effort plan may be short of it),
        # then cost, and under automatic periods what each window's start costs.
        trimmed = ending_at_need(result)
        starts = start_cost * len(result.periods) if request.max_periods is AUTO_PERIODS else 0.0
        return -round(min(trimmed.delivered_kwh, request.requested_kwh), _SLOT_DIGITS), round(
            trimmed.estimated_cost + starts / 100, _SLOT_DIGITS
        )

    return started if rank(started) < rank(plain) else plain


def _whole_slot_plan(request: PlanRequest, *, current: bool) -> PlanResult:
    """The whole-slot plan, with the rest of the current price interval as its start when `current`.

    The current interval is one more candidate piece, starting now: the plan may continue it into the next
    slots as one window or stop after it, and when the whole slots are not contiguous with it, it is a window
    of its own, counted in the window limits and the start cost like any other. When a deadline leaves no
    whole slot (or too few for the need) it is used as far as the deadline allows.
    """
    window = _window(request, current=current)
    if isinstance(window, str):
        return _no_plan(request, window)
    if window.needed == 0:
        return _uncapped_result(request, window, _known_slots(window), ())
    candidates, refusal = _candidates(window.slots, first_start=window.first_start, required_end=window.required_end)
    if refusal is not None:
        return _no_plan(request, refusal)
    if len(candidates) < window.needed:
        return _no_plan(request, "insufficient_price_horizon")
    chosen = _choose(
        candidates,
        window.needed,
        window.per_slot,
        request.max_periods,
        request.fiscal,
        latest_end_inclusive=window.end,
        max_runs=request.max_blocks,
        seeded=window.lead is not None,
    )
    if chosen is None:
        return _no_plan(request, "insufficient_price_horizon")
    return _uncapped_result(request, window, candidates, tuple(candidates[index] for index in chosen))


def _known_slots(window: _Window) -> list[PlanningSlot]:
    """The published slots from the first usable one, up to the first gap or the end of the window."""
    published = {slot.start: slot for slot in window.slots}
    known: list[PlanningSlot] = []
    cursor = window.first_start
    while cursor < min(window.horizon, window.end) and cursor in published:
        known.append(published[cursor])
        cursor += timedelta(minutes=STEP_MINUTES)
    return known


def _uncapped_result(
    request: PlanRequest,
    window: _Window,
    candidates: list[PlanningSlot],
    selected: tuple[PlanningSlot, ...],
) -> PlanResult:
    """The whole-slot plan for chosen slots, preceded by the window's lead (the rest of the current interval)."""
    per_slot = window.per_slot
    count = len(selected)
    lead = window.lead
    delivered_kwh: float | None = None
    if lead is not None and window.needed == 0 and not window.short:
        # The rest of this interval alone delivers the need: stop where the need is met.
        hours = request.requested_kwh / request.planned_kw
        lead = replace(lead, end=min(lead.end, lead.start + timedelta(hours=hours)))
        delivered_kwh = request.requested_kwh
    lead_kwh = 0.0 if lead is None else (lead.end - lead.start).total_seconds() / 3600 * request.planned_kw
    lead_price = 0.0 if lead is None else lead.effective_minor_per_kwh
    delivered = count * per_slot + lead_kwh if delivered_kwh is None else delivered_kwh
    cost_minor = lead_kwh * lead_price + sum(
        per_slot * effective_minor_per_kwh(slot.local_major_per_kwh, request.fiscal, slot.start)
        for slot in selected
    )
    # The same energy straight from the first usable slot (now, when the current interval counts), same power.
    now_minor = lead_kwh * lead_price + sum(
        per_slot * effective_minor_per_kwh(slot.local_major_per_kwh, request.fiscal, slot.start)
        for slot in candidates[:count]
    )
    slots = tuple(
        SelectedSlot(
            start=slot.start,
            end=slot.end,
            local_major_per_kwh=slot.local_major_per_kwh,
            effective_minor_per_kwh=effective_minor_per_kwh(slot.local_major_per_kwh, request.fiscal, slot.start),
            unpriced=False,
            source=slot.source,
        )
        for slot in selected
    )
    if lead is not None:
        slots = (lead, *slots)
    return PlanResult(
        version=CONTRACT_VERSION,
        area_id=request.area_id,
        timezone=request.timezone,
        currency=request.currency,
        major_unit=request.major_unit,
        minor_unit=request.minor_unit,
        now=request.now,
        reason=None,
        power_kw=request.planned_kw,
        requested_kwh=request.requested_kwh,
        delivered_kwh=delivered,
        distance_mil=delivered / request.consumption_kwh_per_10km,
        estimated_cost=cost_minor / 100,
        periods=_periods(slots),
        slots=slots,
        unpriced_slots=0,
        priced_slots=len(slots),
        unpriced=False,
        slots_needed=count,
        horizon=_horizon(candidates, selected, zone=window.zone, fiscal=request.fiscal),
        short_of_deadline=window.short,
        now_cost=now_minor / 100,
        lead_kwh=lead_kwh,
    )


def _calculate_capped(request: PlanRequest) -> PlanResult:
    """Select known cheap intervals and, only when necessary, minimum exceptions.

    The search counts full slots plus at most one fractional slot. A fractional
    slot may touch either neighbour; it must not make an excluded gap disappear.
    First maximize delivered energy. When a minimum exception is necessary,
    minimize exception energy, then configured variable cost. Automatic periods
    have no hard run limit in this branch, except the executor's (`max_blocks`). With
    `include_current_interval` the rest of the current published interval is one more
    candidate, starting now, at proportional energy and cost.
    """
    request = replace(request, max_periods=_effective_limit(request))
    try:
        published = planning_slots(request.documents, currency=request.currency, timezone=request.timezone)
    except PlannerInputError as err:
        if err.code == "missing_fx_rate":
            return replace(
                _no_plan(request, "missing_fx_rate"), policy_shortfall_kwh=request.requested_kwh,
                minimum_shortfall_kwh=request.minimum_energy_kwh,
            )
        raise
    if not published:
        return replace(
            _no_plan(request, "no_published_prices"), policy_shortfall_kwh=request.requested_kwh,
            minimum_shortfall_kwh=request.minimum_energy_kwh,
        )

    first = first_start_for(request.documents, now=request.now, tz=request.timezone).astimezone(timezone.utc)
    zone = time_zones.require_zone(request.timezone)
    end = first + timedelta(hours=HORIZON_HOURS)
    if request.departure is not None:
        if request.departure_date is not None:
            departure = local_instant(request.departure_date, request.departure, zone)
            end = departure.astimezone(timezone.utc)
        else:
            reference = request.now if request.include_current_interval else first
            end = min(end, resolve_departure(request.now, request.timezone, request.departure, reference).astimezone(timezone.utc))
    if request.window_end is not None:
        end = min(end, request.window_end.astimezone(timezone.utc))
    candidates = [slot for slot in published if slot.start >= first and slot.start < end]
    lead = _lead_interval(request, published, first, end)
    if not candidates and lead is None:
        return replace(
            _no_plan(request, "insufficient_price_horizon"), policy_shortfall_kwh=request.requested_kwh,
            minimum_shortfall_kwh=request.minimum_energy_kwh,
        )
    assert request.soft_price_cap is not None and request.cap_price_basis is not None
    eligible = [
        slot for slot in candidates
        if price_within_cap(
            slot.local_major_per_kwh, cap_major_per_kwh=request.soft_price_cap,
            basis=request.cap_price_basis, fiscal=request.fiscal, start=slot.start,
        )
    ]
    minimum = request.minimum_energy_kwh
    lead_eligible = lead if lead is not None and _slot_within_cap(request, lead) else None
    if not eligible and lead_eligible is None and not minimum:
        return replace(
            _no_plan(request, "no_eligible_energy"), policy_shortfall_kwh=request.requested_kwh,
            minimum_shortfall_kwh=minimum,
        )

    # Cheap-only is optimized independently only to establish feasibility of
    # the minimum. If it cannot reach the minimum, rerun over *all* known
    # candidates together with one shared period budget and an energy ceiling
    # of the minimum, never the higher target.
    cost, selected = _select_policy_slots(request, eligible, end, request.requested_kwh, lead=lead_eligible)
    cheap_energy = _selected_energy(request, selected)
    if minimum is not None and cheap_energy + 1e-9 < minimum:
        if request.partial_recheck_at is None:
            cost, selected = _select_policy_slots(request, candidates, end, minimum, prefer_cheap=True, lead=lead)
        else:
            from .price_wait import FEASIBILITY_MARGIN, START_LAG

            recheck = min(end, max(request.partial_recheck_at.astimezone(timezone.utc),
                                   request.now.astimezone(timezone.utc) + START_LAG))
            cheap_before = sum(
                max(0.0, (min(slot.end, recheck) - slot.start).total_seconds()) / 3600 * request.planned_kw
                for slot in selected if slot.start < recheck
            )
            capacity_after = max(0.0, (end - recheck).total_seconds()) / 3600 * request.planned_kw * FEASIBILITY_MARGIN
            urgent = min(minimum - cheap_energy, max(0.0, minimum - cheap_before - capacity_after))
            if urgent > 1e-9:
                allowed = [slot for slot in candidates if _slot_within_cap(request, slot) or slot.end <= recheck]
                allowed_lead = lead if lead is not None and (
                    _slot_within_cap(request, lead) or lead.end <= recheck) else None
                alternative = _select_policy_slots(
                    request, allowed, end, cheap_energy + urgent, prefer_cheap=True, lead=allowed_lead)
                exceptions = _selected_energy(request, tuple(slot for slot in alternative[1] if not _slot_within_cap(request, slot)))
                if exceptions <= urgent + 1e-6:
                    cost, selected = alternative
    if not selected:
        return replace(_no_plan(request, "no_eligible_energy"), policy_shortfall_kwh=request.requested_kwh,
                       minimum_shortfall_kwh=minimum)
    delivered = sum((slot.end - slot.start).total_seconds() / 3600 * request.planned_kw for slot in selected)
    shortfall = max(0.0, request.requested_kwh - delivered)
    exceptions = tuple(slot for slot in selected if not _slot_within_cap(request, slot))
    selected_starts = {slot.start for slot in selected}
    horizon_selected = tuple(slot for slot in candidates if any(slot.start <= start < slot.end for start in selected_starts))
    return PlanResult(
        version=CONTRACT_VERSION, area_id=request.area_id, timezone=request.timezone,
        currency=request.currency, major_unit=request.major_unit, minor_unit=request.minor_unit,
        now=request.now, reason=None, power_kw=request.planned_kw, requested_kwh=request.requested_kwh,
        delivered_kwh=delivered, distance_mil=delivered / request.consumption_kwh_per_10km,
        estimated_cost=cost / 100, periods=_periods(selected), slots=selected,
        unpriced_slots=0, priced_slots=len(selected), unpriced=False, slots_needed=len(selected),
        horizon=_horizon(candidates, horizon_selected, zone=zone, fiscal=request.fiscal),
        exact_periods=True, policy_shortfall_kwh=shortfall,
        minimum_shortfall_kwh=None if minimum is None else max(0.0, minimum - delivered),
        exception_periods=_periods(exceptions), exception_kwh=_selected_energy(request, exceptions),
    )


def _slot_within_cap(request: PlanRequest, slot: PlanningSlot | SelectedSlot) -> bool:
    assert request.soft_price_cap is not None and request.cap_price_basis is not None
    return price_within_cap(
        slot.local_major_per_kwh, cap_major_per_kwh=request.soft_price_cap,
        basis=request.cap_price_basis, fiscal=request.fiscal, start=slot.start,
    )


def _selected_energy(request: PlanRequest, slots: tuple[SelectedSlot, ...]) -> float:
    return sum((slot.end - slot.start).total_seconds() / 3600 * request.planned_kw for slot in slots)


def _selection_rank(
    request: PlanRequest, option: tuple[float, tuple[SelectedSlot, ...]], *, prefer_cheap: bool,
) -> tuple:
    cost, selected = option
    exception_energy = _selected_energy(request, tuple(slot for slot in selected if not _slot_within_cap(request, slot)))
    return (
        -round(_selected_energy(request, selected), _SLOT_DIGITS),
        round(exception_energy, _SLOT_DIGITS) if prefer_cheap else 0.0,
        cost, tuple(-s.start.timestamp() for s in reversed(selected)),
    )


def _select_policy_slots(
    request: PlanRequest, eligible: list[PlanningSlot], end: datetime, need_kwh: float, *,
    prefer_cheap: bool = False, lead: SelectedSlot | None = None,
) -> tuple[float, tuple[SelectedSlot, ...]]:
    """Search full slots and optional deadline fragment with a shared run limit.

    `lead` is the rest of the current interval, an optional first piece starting now: either used (from its
    start, up to what the need takes) or not, whichever plan is better.
    """
    tail = eligible[-1] if eligible and eligible[-1].end > end else None
    full_slots = eligible[:-1] if tail is not None else eligible
    options = [_select_cheap_slots(request, full_slots, need_kwh, prefer_cheap=prefer_cheap)]
    variants: list[tuple[SelectedSlot | None, float]] = [(None, need_kwh)]
    if lead is not None:
        lead_kwh = (lead.end - lead.start).total_seconds() / 3600 * request.planned_kw
        used = min(lead_kwh, need_kwh)
        if used > 1e-9:
            piece = lead if used >= lead_kwh - 1e-9 else replace(
                lead, end=lead.start + timedelta(hours=used / request.planned_kw))
            variants.append((piece, need_kwh - used))
            if need_kwh - used <= _WHOLE_SLOTS_KWH:
                # The rest of this interval alone delivers the need.
                options.append((_energy_cost(request, piece), (piece,)))
    for piece, remaining in variants:
        if piece is None:
            if tail is None:
                continue
        elif remaining <= _WHOLE_SLOTS_KWH:
            continue
        else:
            options.append(_select_cheap_slots(
                request, full_slots, remaining, prefer_cheap=prefer_cheap, seed=piece))
        if tail is not None:
            tail_capacity = (end - tail.start).total_seconds() / 3600 * request.planned_kw
            tail_amounts = {min(remaining, tail_capacity)}
            remainder = remaining % (request.planned_kw * SLOT_HOURS)
            if 1e-9 < remainder < tail_capacity:
                tail_amounts.add(remainder)
            for tail_energy in tail_amounts:
                if tail_energy > 0:
                    options.append(_select_cheap_slots(
                        request, full_slots, remaining - tail_energy, tail, tail_energy,
                        prefer_cheap=prefer_cheap, seed=piece,
                    ))
    possible = [option for option in options if option is not None]
    return min(possible, key=lambda option: _selection_rank(request, option, prefer_cheap=prefer_cheap))


def _energy_cost(request: PlanRequest, slot: SelectedSlot) -> float:
    """Minor-unit cost of charging through one selected piece at the planned power."""
    return (slot.end - slot.start).total_seconds() / 3600 * request.planned_kw * slot.effective_minor_per_kwh


def _select_cheap_slots(
    request: PlanRequest, eligible: list[PlanningSlot], need_kwh: float,
    tail: PlanningSlot | None = None, tail_kwh: float = 0.0,
    *, prefer_cheap: bool = False, seed: SelectedSlot | None = None,
) -> tuple[float, tuple[SelectedSlot, ...]] | None:
    """Search whole-grid slots and optionally append the available deadline fragment.

    A `seed` is a piece already chosen before the first slot (the rest of the current interval): it counts as
    the first run, and the slot it touches continues that run instead of starting another.
    """
    per_slot = request.planned_kw * SLOT_HOURS
    quotient = round(need_kwh / per_slot, _SLOT_DIGITS)
    full_target = math.floor(quotient)
    fraction = quotient - full_target
    # Key: full slots, partial used, runs (only when capped), previous end open.
    # Value: minor-unit cost, actual selected slots, run count, exception kWh.
    states: dict[tuple[int, bool, int, bool], tuple[float, tuple[SelectedSlot, ...], int, float]] = {
        (0, False, 0, False): (0.0, (), 0, 0.0)
    }
    if seed is not None:
        seed_energy = (seed.end - seed.start).total_seconds() / 3600 * request.planned_kw
        seed_exception = seed_energy if prefer_cheap and not _slot_within_cap(request, seed) else 0.0
        states = {
            (0, False, 1 if request.max_periods is not None else 0, True): (
                _energy_cost(request, seed), (seed,), 1, seed_exception,
            )
        }
    for slot in eligible:
        next_states: dict[tuple[int, bool, int, bool], tuple[float, tuple[SelectedSlot, ...], int, float]] = {}
        price = effective_minor_per_kwh(slot.local_major_per_kwh, request.fiscal, slot.start)
        above_cap = prefer_cheap and not _slot_within_cap(request, slot)

        def keep(key: tuple[int, bool, int, bool], value: tuple[float, tuple[SelectedSlot, ...], int, float]) -> None:
            old = next_states.get(key)  # noqa: B023 - called within this iteration
            rank = lambda v: (round(v[3], _SLOT_DIGITS), v[0], tuple(-s.start.timestamp() for s in reversed(v[1])))  # noqa: E731
            if old is None or rank(value) < rank(old):
                next_states[key] = value  # noqa: B023

        for (full, partial, _, active), (cost, selected, runs, exception_kwh) in states.items():
            run_key = runs if request.max_periods is not None else 0
            keep((full, partial, run_key, False), (cost, selected, runs, exception_kwh))
            options: list[tuple[datetime, datetime, bool]] = []
            if full < full_target:
                options.append((slot.start, slot.end, False))
            if fraction > 0 and not partial:
                duration = timedelta(hours=SLOT_HOURS * fraction)
                options.append((slot.start, slot.start + duration, True))
                options.append((slot.end - duration, slot.end, True))
            for start, finish, is_partial in options:
                connected = bool(active and selected and selected[-1].end == start)
                new_runs = runs + (0 if connected else 1)
                if request.max_periods is not None and new_runs > request.max_periods:
                    continue
                duration_hours = (finish - start).total_seconds() / 3600
                chosen = SelectedSlot(start, finish, slot.local_major_per_kwh, price, False, slot.source)
                new_key = (
                    full + (not is_partial), partial or is_partial,
                    new_runs if request.max_periods is not None else 0, finish == slot.end,
                )
                energy = duration_hours * request.planned_kw
                keep(new_key, (
                    cost + energy * price, selected + (chosen,), new_runs,
                    exception_kwh + (energy if above_cap else 0.0),
                ))
        states = next_states

    results: list[tuple[float, tuple[SelectedSlot, ...]]] = []
    for cost, selected, runs, _exception_kwh in states.values():
        if tail is not None:
            finish = tail.start + timedelta(hours=tail_kwh / request.planned_kw)
            connected = bool(selected and selected[-1].end == tail.start)
            if request.max_periods is not None and runs + (not connected) > request.max_periods:
                continue
            price = effective_minor_per_kwh(tail.local_major_per_kwh, request.fiscal, tail.start)
            selected += (SelectedSlot(tail.start, finish, tail.local_major_per_kwh, price, False, tail.source),)
            cost += (finish - tail.start).total_seconds() / 3600 * request.planned_kw * price
        results.append((cost, selected))
    if not results:
        return None

    return min(results, key=lambda result: _selection_rank(request, result, prefer_cheap=prefer_cheap))


#: Less than this left over in the last slot is a need that fills its slots exactly (float noise).
_WHOLE_SLOTS_KWH: Final = 1e-6


def ending_at_need(result: PlanResult) -> PlanResult:
    """A plan whose charge stops once its need is delivered, as a kWh need counted with an energy register does.

    The planner buys whole slots, so the last one would deliver more than the need: the stated energy is the need
    itself, and the cost counts every slot whole but the last one in time, which counts only for the share of it
    the need takes (the same for the cost of charging now, whose last slot is the last of the first ones). The
    slots and periods stay whole (what is installed); `need_met_at` says where in the last one the need is met.
    A plan short of its departure, one with no slots, or one whose need fills its slots exactly is unchanged
    beyond the flag.
    """
    if result.exact_periods or not result.has_plan or result.short_of_deadline or not result.slots or result.power_kw <= 0:
        return result
    per_slot = result.power_kw * SLOT_HOURS
    extra = result.delivered_kwh - result.requested_kwh
    if extra <= _WHOLE_SLOTS_KWH or extra >= per_slot:
        return replace(result, ends_at_need=True)
    last = max(result.slots, key=lambda slot: slot.start)
    now_cost = result.now_cost
    if now_cost is not None and 0 < result.slots_needed <= len(result.horizon):
        now_cost -= extra * result.horizon[result.slots_needed - 1].effective_minor_per_kwh / 100
    return replace(
        result,
        delivered_kwh=result.requested_kwh,
        distance_mil=result.distance_mil * result.requested_kwh / result.delivered_kwh,
        estimated_cost=result.estimated_cost - extra * last.effective_minor_per_kwh / 100,
        now_cost=now_cost,
        ends_at_need=True,
    )


def _no_plan(request: PlanRequest, reason: PlannerReason) -> PlanResult:
    """A result that carries the reason and no plan, keeping the identity intact."""
    return PlanResult(
        version=CONTRACT_VERSION,
        area_id=request.area_id,
        timezone=request.timezone,
        currency=request.currency,
        major_unit=request.major_unit,
        minor_unit=request.minor_unit,
        now=request.now,
        reason=reason,
        power_kw=request.planned_kw,
        requested_kwh=request.requested_kwh,
        delivered_kwh=0.0,
        distance_mil=0.0,
        estimated_cost=0.0,
        periods=(),
        slots=(),
        unpriced_slots=0,
        priced_slots=0,
        unpriced=False,
        slots_needed=0,
    )


@dataclass(frozen=True, slots=True)
class _State:
    """One state of the search: what it has chosen, and what that has cost."""

    selected: int
    runs: int
    active: bool
    cost: float
    slots: tuple[int, ...]


def _rank(state: _State) -> tuple[float, tuple[int, ...]]:
    """What a state is compared by: lowest cost, then, among equal costs, the latest slots.

    The indices run from the last chosen slot backwards and negated, so a later slot sorts first.
    """
    return state.cost, tuple(-index for index in reversed(state.slots))


def _choose(
    candidates: list[PlanningSlot],
    needed: int,
    per_slot: float,
    period_cap: int | None,
    fiscal: FiscalChoice,
    latest_end_inclusive: datetime | None,
    *,
    max_runs: int | None = None,
    seeded: bool = False,
) -> tuple[int, ...] | None:
    """Which slots to charge in: exactly `needed` of them, at most `period_cap` runs, or automatic periods.

    `max_runs` is the executor's own limit on runs, on top of `period_cap` and also under automatic periods.
    `seeded` means a run is already open when the first candidate starts (the rest of the current interval
    ends where it starts): it counts as a run, and the first candidate may continue it or end it.
    """
    if period_cap is AUTO_PERIODS:
        return _choose_auto(candidates, needed, per_slot, fiscal, latest_end_inclusive, max_runs, seeded)
    cap = period_cap if max_runs is None else min(period_cap, max_runs)
    return _choose_capped(candidates, needed, per_slot, cap, fiscal, latest_end_inclusive, seeded)


def start_cost_minor(candidates: list[PlanningSlot], fiscal: FiscalChoice) -> float:
    """What one start costs under automatic periods, in the area's minor unit (`START_COST_KWH`).

    The mean is of the magnitudes, so a window of negative prices never makes a start pay.
    """
    if not candidates:
        return 0.0
    level = sum(abs(effective_minor_per_kwh(slot.local_major_per_kwh, fiscal, slot.start)) for slot in candidates)
    return START_COST_KWH * level / len(candidates)


@dataclass(frozen=True, slots=True)
class _AutoState:
    """One state of the automatic search: chosen count, the open run's length (capped at the shortest
    run, 0 when no run is open), the runs started and their cost."""

    selected: int
    length: int
    runs: int
    cost: float
    slots: tuple[int, ...]


def _choose_auto(
    candidates: list[PlanningSlot],
    needed: int,
    per_slot: float,
    fiscal: FiscalChoice,
    latest_end_inclusive: datetime | None,
    max_runs: int | None = None,
    seeded: bool = False,
) -> tuple[int, ...] | None:
    """Automatic periods: exactly `needed` slots for the lowest cost plus `start_cost_minor` per run, every
    run at least `SHORTEST_BLOCK_SLOTS` long (or the whole need, when that is smaller).

    The same dynamic program as `_choose_capped` without a cap on the runs, so the state is the chosen count
    and the open run's length. One contiguous run is always a candidate, so this finds a plan whenever a
    cap of one would. Ties: the objective is compared to a millionth of the minor unit (sums of the same
    prices in another order differ in the last bit), then the latest slots win, as for a number.
    """
    shortest = min(SHORTEST_BLOCK_SLOTS, needed)
    start_cost = start_cost_minor(candidates, fiscal)

    def rank(state: _AutoState) -> tuple[float, tuple[int, ...]]:
        return round(state.cost + start_cost * state.runs, 6), tuple(-index for index in reversed(state.slots))

    # `max_runs` makes the runs started part of the state, so a limit never discards the cheaper plan within it.
    # A seeded run is open and long enough to end (it is not a start of its own that needs a minimum length).
    initial = _AutoState(0, shortest, 1, 0.0, ()) if seeded else _AutoState(0, 0, 0, 0.0, ())
    states: dict[tuple[int, int, int], _AutoState] = {
        (0, initial.length, initial.runs if max_runs is not None else 0): initial
    }
    for index, slot in enumerate(candidates):
        next_states: dict[tuple[int, int, int], _AutoState] = {}
        slot_cost = per_slot * effective_minor_per_kwh(slot.local_major_per_kwh, fiscal, slot.start)

        def keep(state: _AutoState) -> None:
            key = (state.selected, state.length, state.runs if max_runs is not None else 0)
            existing = next_states.get(key)  # noqa: B023 - only called within this iteration
            if existing is None or rank(state) < rank(existing):
                next_states[key] = state  # noqa: B023

        ends_inside_the_window = latest_end_inclusive is None or slot.end <= latest_end_inclusive
        for state in states.values():
            if state.length == 0 or state.length >= shortest:
                # A run may end only once it is long enough.
                keep(_AutoState(state.selected, 0, state.runs, state.cost, state.slots))
            runs = state.runs + (1 if state.length == 0 else 0)
            if ends_inside_the_window and state.selected < needed and (max_runs is None or runs <= max_runs):
                keep(
                    _AutoState(
                        selected=state.selected + 1,
                        length=min(state.length + 1, shortest),
                        runs=runs,
                        cost=state.cost + slot_cost,
                        slots=state.slots + (index,),
                    )
                )
        states = next_states

    best: _AutoState | None = None
    for state in states.values():
        if state.selected != needed or 0 < state.length < shortest:
            continue
        if best is None or rank(state) < rank(best):
            best = state
    return None if best is None else best.slots


def _choose_capped(
    candidates: list[PlanningSlot],
    needed: int,
    per_slot: float,
    period_cap: int,
    fiscal: FiscalChoice,
    latest_end_inclusive: datetime | None,
    seeded: bool = False,
) -> tuple[int, ...] | None:
    """Which slots to charge in: exactly `needed` of them, for the lowest total cost.

    A dynamic program with state (chosen count, runs, previous slot chosen) and transitions
    skip / start a run / continue a run, so plans may be non-contiguous and the period cap
    binds properly (a greedy merge is not equivalent). [latest_end_inclusive] bounds the end
    of any chosen slot; `None` means unbounded. Ties: states compare by `(cost, latest-first)` over
    chronological candidates, so equal costs pick the latest slots (the car sits plugged in, charges
    last and leaves with the freshest charge); no epsilon.
    """
    initial = _State(selected=0, runs=1, active=True, cost=0.0, slots=()) if seeded else _State(
        selected=0, runs=0, active=False, cost=0.0, slots=())
    states: dict[tuple[int, int, bool], _State] = {(initial.selected, initial.runs, initial.active): initial}

    for index, slot in enumerate(candidates):
        next_states: dict[tuple[int, int, bool], _State] = {}
        slot_cost = per_slot * effective_minor_per_kwh(slot.local_major_per_kwh, fiscal, slot.start)

        def keep(state: _State) -> None:
            key = (state.selected, state.runs, state.active)
            existing = next_states.get(key)  # noqa: B023 - only called within this iteration
            if existing is None or _rank(state) < _rank(existing):
                next_states[key] = state  # noqa: B023

        for state in states.values():
            # Skipping is always allowed and ends a run.
            keep(_State(state.selected, state.runs, False, state.cost, state.slots))
            runs = state.runs + (0 if state.active else 1)
            ends_inside_the_window = latest_end_inclusive is None or slot.end <= latest_end_inclusive
            if ends_inside_the_window and state.selected < needed and runs <= period_cap:
                keep(
                    _State(
                        selected=state.selected + 1,
                        runs=runs,
                        active=True,
                        cost=state.cost + slot_cost,
                        slots=state.slots + (index,),
                    )
                )
        states = next_states

    best: _State | None = None
    for state in states.values():
        if state.selected != needed:
            continue
        if best is None or _rank(state) < _rank(best):
            best = state
    return None if best is None else best.slots


def cheapest_slots(
    candidates: list[PlanningSlot],
    needed: int,
    per_slot: float,
    period_cap: int | None,
    fiscal: FiscalChoice,
    latest_end_inclusive: datetime | None,
) -> tuple[PlanningSlot, ...] | None:
    """The cheapest `needed` of these slots in at most `period_cap` runs (or automatic periods, `None`), or
    `None` when none fit.

    The planner's own search over candidates the caller supplies, for readers that must price a
    hypothetical window the same way a real one is priced (see `planning/history_wait.py`).
    """
    chosen = _choose(candidates, needed, per_slot, period_cap, fiscal, latest_end_inclusive)
    return None if chosen is None else tuple(candidates[index] for index in chosen)


def _periods(selected: tuple[PlanningSlot, ...] | tuple[SelectedSlot, ...]) -> tuple[tuple[datetime, datetime], ...]:
    """Contiguous chosen slots merged into half-open `[start, end)` periods.

    Merging is by instant, not local clock label, so clock changes neither join nor split runs.
    """
    periods: list[list[datetime]] = []
    for slot in selected:
        if periods and periods[-1][1] == slot.start:
            periods[-1][1] = slot.end
        else:
            periods.append([slot.start, slot.end])
    return tuple((start, end) for start, end in periods)


@dataclass(frozen=True, slots=True)
class TargetEnergyRequest:
    """What a target state of charge needs, with every source made explicit.

    `capacity_kwh` is resolved by the caller; `None` means unknown, never zero.
    `apply_default_target` is a request, not a default.
    """

    soc_percent: float
    capacity_kwh: float | None
    stored_target_percent: int | None = None
    vehicle_max_percent: float | None = None
    apply_default_target: bool = False
    whole_kwh_input: bool = False


def _target_or_none(request: TargetEnergyRequest) -> int | None:
    """The effective target when it can be worked out, else `None`.

    Used on the unknown-capacity path, where an unresolvable target must not turn the answer into an exception.
    """
    try:
        return effective_target_soc_percent(
            request.stored_target_percent,
            request.vehicle_max_percent,
            apply_default_target=request.apply_default_target,
        )
    except PlannerInputError:
        return None


@dataclass(frozen=True, slots=True)
class TargetEnergyResolution:
    """The energy a target implies: a number, a reason, or both, but never a guess."""

    reason: TargetEnergyReason
    kwh: float | None
    target_percent: int | None
    effective_capacity_kwh: float | None

def effective_target_soc_percent(
    stored_target_percent: int | None,
    vehicle_max_percent: float | None,
    *,
    apply_default_target: bool,
) -> int:
    """The target to work with: the stored one, else the asked-for default, capped.

    A stored value above the vehicle's own limit is clamped here, not rewritten in
    storage, so the choice survives pointing the settings at another car. A vehicle
    with no usable maximum caps nothing.
    """
    ceiling = 100
    if vehicle_max_percent is not None:
        maximum = _finite(vehicle_max_percent, "invalid_target_soc", "vehicle_max_percent")
        ceiling = min(100, max(0, math.floor(maximum)))
    if stored_target_percent is None:
        if not apply_default_target:
            _refuse(
                "invalid_target_soc",
                "no stored target was given and the Android-compatible default was not requested",
            )
        chosen = DEFAULT_TARGET_SOC_PERCENT
    else:
        chosen = _as_int(stored_target_percent)
        if not 0 <= chosen <= 100:
            _refuse("invalid_target_soc", "the stored target must be a percentage")
    return min(chosen, ceiling)


def resolve_target_energy(request: TargetEnergyRequest) -> TargetEnergyResolution:
    """How much energy a target state of charge needs, or why that cannot be said.

    * `unknown_capacity`: `kwh` is `None`, not zero.
    * `already_at_target`: `kwh` is `0.0` and must not become a plan.
    * `ok`: a positive figure; with `whole_kwh_input` rounded up into the 1..100 kWh slider range.
    """
    soc = _finite(request.soc_percent, "invalid_target_soc", "soc_percent")
    # Capacity first: an unknown battery size is a more useful answer than a target complaint.
    capacity = request.capacity_kwh
    usable: float | None = None
    if capacity is not None:
        candidate = _finite(capacity, "invalid_target_soc", "capacity_kwh")
        usable = candidate if candidate > 0 else None
    if usable is None:
        return TargetEnergyResolution(
            "unknown_capacity",
            None,
            _target_or_none(request),
            None,
        )

    target = effective_target_soc_percent(
        request.stored_target_percent,
        request.vehicle_max_percent,
        apply_default_target=request.apply_default_target,
    )

    needed = max(0.0, (target - soc) / 100.0 * usable)
    if needed == 0.0:
        return TargetEnergyResolution("already_at_target", 0.0, target, usable)
    if request.whole_kwh_input:
        needed = float(min(ENERGY_SLIDER_MAX_KWH, max(ENERGY_SLIDER_MIN_KWH, math.ceil(needed))))
    return TargetEnergyResolution("ok", needed, target, usable)


@dataclass(frozen=True, slots=True)
class ChartInterval:
    """One row a chart can draw: a published price, with the two figures beside it.

    `raw_minor_per_kwh` is the converted relay price; `effective_minor_per_kwh` adds the fiscal choice.
    """

    start: datetime
    end: datetime
    utc_start: datetime
    utc_end: datetime
    day: date
    raw_minor_per_kwh: float
    effective_minor_per_kwh: float


def document_rate(document: PriceDocument, currency: str) -> float:
    """The day's own rate for the area's currency, for readers that show a price.

    The same call as `_rate_for`, so the rule has one implementation.
    """
    return _rate_for(document, currency)


def chart_intervals(
    documents: tuple[PriceDocument, ...],
    *,
    currency: str,
    fiscal: FiscalChoice,
) -> tuple[ChartInterval, ...]:
    """Every published interval of these documents, ready to draw, in instant order.

    Rows are the relay's own resolution (including 23- and 25-hour days), never
    re-gridded, and nothing is invented. Two documents pricing the same instant give
    one row, the caller's order winning, as in `planning_slots`.
    """
    rows: dict[datetime, ChartInterval] = {}
    for document in (piece for whole in documents for piece in whole.pieces()):
        rate = document_rate(document, currency)
        for interval in document.intervals:
            if interval.utc_start in rows:
                continue
            local_major = interval.eur_per_kwh * rate
            rows[interval.utc_start] = ChartInterval(
                start=interval.start,
                end=interval.end,
                utc_start=interval.utc_start,
                utc_end=interval.utc_end,
                day=document.day,
                raw_minor_per_kwh=local_major * 100,
                effective_minor_per_kwh=effective_minor_per_kwh(local_major, fiscal, interval.utc_start),
            )
    return tuple(rows[start] for start in sorted(rows))
