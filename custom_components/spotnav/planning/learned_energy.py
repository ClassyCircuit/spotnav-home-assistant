"""How much energy from the wall one percent of the car's battery takes, learned from its charges.

A target becomes a wall-energy need as `capacity x (target - level) / 100 / CHARGE_EFFICIENCY`. A battery size
that is off (a degraded pack, net against gross, a guess) or an efficiency far from the fixed one (a cold pack,
one phase, a low current) makes the plan buy too little time or too much. From the energy count and the car's
level before and after a stretch of charging only one number can be seen: wall kWh per percent
(`capacity / efficiency / 100`). That is what is learned here, per car; the planner needs nothing else. No setting.

* **A sample.** A stretch of one plug-in (`ChargingController.plugged_in_at`, kept across a restart, else
  `plugged_in_for_count`) of one identified car (the one the level is read from) between two fresh readings of its
  level from one source (`charger` or `vehicle`): not an estimate and no older than
  `target_stop.SOC_FRESH_MAX_AGE_S` when seen, the later one made after the earlier. The energy is the count the
  need uses (the energy register, or the energy integrated from the charger's power) at the moment each reading
  was made: interpolated between the register's posts while it posts steadily around it
  (`soc_estimate.register_value_at`), or, only while the charger is not charging, the value it held from a look
  before the reading to now. The stretch counts once the level rose at least `MIN_DELTA_PERCENT` points; its
  later end moves on with each fresh reading of the same plug-in, so a charge that spans several windows of a plan
  is one sample. The charger saying the car is unplugged, another plug-in, another car (or none identified),
  another source of the level, a register that went back or a level that fell starts a stretch again. The
  stretch's start is stored, so a restart during a plug-in keeps it.
* **Bounds.** With the car's battery size the sample must mean an efficiency between `MIN_EFFICIENCY` and
  `MAX_EFFICIENCY`; without one, a battery between `MIN_CAPACITY_KWH` and `MAX_CAPACITY_KWH` at
  `CHARGE_EFFICIENCY`. A sample outside is not kept and is counted (`discarded`). Every read counts only the
  samples that fit today's battery size; the need's read drops those that no longer fit for good (and counts
  them), the others only look.
* **Smoothed and trusted.** From the last `MAX_SAMPLES` samples of ended plug-ins (the open plug-in's own, still
  growing, waits until it ends): trusted when at least `TRUST_SAMPLES` of them lie within `TRUST_SPREAD` of their
  median, and then the figure is the median of those that agree, so one odd charge neither moves it nor takes the
  trust away. Until then everything is worked out as before.
* **Used** for a target's need and the dashboard's (`target_need`, `efficiency_for`), and for the level carried
  forward between readings (`SocReader`, given the figure from setup), so a replan from an estimate and the stop
  on one count as the need does.
* **Fed** once a minute by the look at the plan's windows (`AutoPlannerController._check_plan`, the seam the
  learned power and the behind-plan rule use), so only charges of an Auto plan are learned from.
* **Stored** per charger (`spotnav.learned_energy.<entry>`), keyed by car, and read as untrusted: anything
  malformed is dropped, and a file that cannot be read starts empty.
* **Captured** (Stage 15.9a, capture-only). Under Morek schedule ownership a bounded 60 s tick
  (`AutoPlannerController._capture_energy`) feeds `EnergySampler.observe_capture`, which writes stretches as
  `Capture` records (`origin: morek_capture`) with their provenance into the same store, apart from the samples. A
  capture is read by the planner only once promoted (Stage 15.9b); until then it only accrues.
* **Promoted** (Stage 15.9b). When a capture's plug-in has ended (and again at a later safe read, never while that
  car's plug-in is open) every capture is revalidated by `metadata_reason` (what it recorded) and the store's
  `checker` (the retained session and evidence records now; the stored `late_energy` is only a capture-time snapshot).
  A capture lacking proof is not promoted, is counted once per reason (`rejections`) and the default stands. Only
  promoted captures vote, one per plug-in: the last `PROMOTE_MAX_VOTES` ended plug-ins within `CAPTURE_MAX_AGE`, each a
  rise of at least `PROMOTE_MIN_RISE` points ending at most `PROMOTE_MAX_END_PERCENT`. `PROMOTED` figure: trusted
  when `PROMOTE_LENGTHEN_VOTES` votes lie within `TRUST_SPREAD` of their median (the figure is the median of those that
  agree); a figure below the default `capacity / CHARGE_EFFICIENCY / 100` (shorter time) needs
  `PROMOTE_SHORTEN_VOTES` agreeing; the used figure is clamped to `CLAMP_LOWER`..`CLAMP_UPPER` times the default.
  Promotion is persisted and one-way except that a later conflicting record revokes it (failing closed at the next
  safe read or restart). Morek schedule-owned planning (the caller says so: `learned(morek=True)`) uses only a trusted
  promoted figure, else the default: the legacy samples are never read for it. Auto-owned (legacy) learning keeps its
  own rules and ignores captures.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..execution.target_stop import SOC_FRESH_MAX_AGE_S
from ..vehicles.soc_estimate import CHARGE_EFFICIENCY, register_value_at, REGISTER_TOLERANCE_KWH, target_need_kwh

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION: Final = 1
_STORE_PREFIX: Final = f"{DOMAIN}.learned_energy"

#: The least rise of the level (points) a stretch needs to be a sample: whole-percent readings make less too rough.
MIN_DELTA_PERCENT: Final = 10.0
#: The samples kept per car, and how many (all within `TRUST_SPREAD` of their median) before the need uses them.
MAX_SAMPLES: Final = 5
TRUST_SAMPLES: Final = 3
TRUST_SPREAD: Final = 0.10
#: What a sample may mean: an efficiency in this range for the car's battery size, or without one a battery size in
#: this range at `CHARGE_EFFICIENCY`.
MIN_EFFICIENCY: Final = 0.70
MAX_EFFICIENCY: Final = 1.0
MIN_CAPACITY_KWH: Final = 10.0
MAX_CAPACITY_KWH: Final = 200.0
#: The samples stored per car: the last `MAX_SAMPLES` of ended plug-ins and the open one's.
_STORED_SAMPLES: Final = MAX_SAMPLES + 1
#: How far back (s) the register's values are kept (in memory) to read its value when a level was made.
HISTORY_S: Final = 1800.0
#: How long, in seconds, after a write the store waits to save.
SAVE_DELAY_S: Final = 30.0
#: Bounds on what is stored: identifiers, and the count of discarded samples.
_MAX_ID_LEN: Final = 128
_MAX_DISCARDED: Final = 1_000_000
#: Stage 15.9a capture-only records: the tag, the schema version, how many are kept per car and for how long.
ORIGIN_CAPTURE: Final = "morek_capture"
CAPTURE_VERSION: Final = 1
MAX_CAPTURES: Final = 12
CAPTURE_MAX_AGE: Final = timedelta(days=120)
#: Looks further apart than this (s) inside one stretch are counted as a gap in the provenance.
CAPTURE_GAP_S: Final = 150.0
_MAX_COUNT: Final = 1_000_000
#: Stage 15.9b promotion/use rules for captures (the legacy sample path above keeps its own constants): the least
#: rise (points), the ended plug-ins kept as votes (one per plug-in), the most level a stretch may end at (taper), how
#: many agreeing votes lengthen / shorten the time, and how far from the default figure the used one may go.
PROMOTE_MIN_RISE: Final = 15.0
PROMOTE_MAX_VOTES: Final = 9
PROMOTE_MAX_END_PERCENT: Final = 90.0
PROMOTE_LENGTHEN_VOTES: Final = 3
PROMOTE_SHORTEN_VOTES: Final = 5
CLAMP_LOWER: Final = 0.90
CLAMP_UPPER: Final = 1.25
#: What the proof of a capture's energy must agree to (kWh), a report may lead the clock by (s), the battery size a
#: capture may differ from today's by (kWh) and the voltage between phases (V).
_ENERGY_TOLERANCE_KWH: Final = 0.05
_FUTURE_TOLERANCE_S: Final = 60.0
_CAPACITY_TOLERANCE_KWH: Final = 0.05
VOLTAGE_TOLERANCE_V: Final = 5.0
#: Why a capture is not (yet) a promoted vote; each is counted once per capture.
REJECT_REASONS: Final = (
    "missing_metadata", "soc_basis", "soc_time", "soc_future", "rise_below_15", "soc_above_90", "energy_inconsistent",
    "implausible", "capacity_changed", "gap", "restart", "held", "paused", "unobserved", "late_unplaced",
    "late_uncertain", "late_inconsistent", "late_unknown", "late_pending", "no_session", "session_vehicle",
    "wiring_changed", "evidence_unavailable", "evidence_expired", "evidence_gap", "link_down", "replay",
)
_MAX_REJECTED: Final = 2 * MAX_CAPTURES


def fits(kwh_per_percent: float, capacity_kwh: float | None) -> bool:
    """Whether wall kWh per percent is believable for a battery of `capacity_kwh` (or of any size, without one)."""
    if not _finite_positive(kwh_per_percent):
        return False
    if capacity_kwh is None or not _finite_positive(capacity_kwh):
        implied_capacity = kwh_per_percent * 100.0 * CHARGE_EFFICIENCY
        return MIN_CAPACITY_KWH <= implied_capacity <= MAX_CAPACITY_KWH
    efficiency = capacity_kwh / (kwh_per_percent * 100.0)
    return MIN_EFFICIENCY <= efficiency <= MAX_EFFICIENCY


@dataclass(frozen=True, slots=True)
class EnergySample:
    """One stretch: the wall energy it took and the points the level rose, for one plug-in (`id`)."""

    id: str
    kwh: float
    delta_percent: float
    at: datetime

    @property
    def kwh_per_percent(self) -> float:
        return self.kwh / self.delta_percent

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kwh": self.kwh, "delta_percent": self.delta_percent, "at": self.at.isoformat()}

    @staticmethod
    def from_stored(raw: Any) -> EnergySample | None:
        if not isinstance(raw, dict) or "origin" in raw:
            # A tagged record is a capture, never a sample the planner may trust (Stage 15.9a): fail closed.
            return None
        ident, kwh, delta, at = raw.get("id"), raw.get("kwh"), raw.get("delta_percent"), _when(raw.get("at"))
        if not _ident(ident) or at is None or not _finite_positive(kwh) or not _finite(delta):
            return None
        if not MIN_DELTA_PERCENT <= float(delta) <= 100.0:
            return None
        return EnergySample(id=ident, kwh=float(kwh), delta_percent=float(delta), at=at)


@dataclass(frozen=True, slots=True)
class Anchor:
    """A stretch's start: the car, the plug-in, the level and when it was made, and the count then."""

    vehicle_id: str
    session: str
    soc_percent: float
    at: datetime
    kwh: float
    #: Where the level was read (`charger` or `vehicle`, `SocReading.source`): another source starts again.
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "session": self.session,
            "soc_percent": self.soc_percent,
            "at": self.at.isoformat(),
            "kwh": self.kwh,
            "source": self.source,
        }

    @staticmethod
    def from_stored(raw: Any) -> Anchor | None:
        if not isinstance(raw, dict):
            return None
        vehicle, session, soc, kwh = raw.get("vehicle_id"), raw.get("session"), raw.get("soc_percent"), raw.get("kwh")
        at = _when(raw.get("at"))
        if not _ident(vehicle) or not _ident(session) or at is None or not _finite(soc) or not _finite(kwh):
            return None
        if not 0.0 <= float(soc) <= 100.0 or float(kwh) < 0:
            return None
        source = raw.get("source")
        if source is not None and not _ident(source):
            return None
        return Anchor(
            vehicle_id=vehicle, session=session, soc_percent=float(soc), at=at, kwh=float(kwh), source=source
        )


_QUALITY_KEYS: Final = (
    "looks", "gaps", "max_gap_s", "restarts", "not_charging_looks", "held_looks", "paused_looks", "unposted_looks",
)
_ENUMS: Final = {
    "register_basis_start": ("interpolated", "held"),
    "register_basis_end": ("interpolated", "held"),
    "plug_in_basis": ("watched", "found_connected"),
    "soc_time_basis": ("vehicle_timestamp", "last_updated"),
    "late_energy": ("clean", "unplaced", "uncertain", "unknown"),
}
_META_STRINGS: Final = ("soc_source", "register_entity")
_META_NUMBERS: Final = ("soc_start", "soc_end", "register_start_kwh", "register_end_kwh", "capacity_kwh", "voltage_v")
_META_TIMES: Final = ("soc_start_at", "soc_end_at")
#: What Stage 15.9b needs from a capture before it may promote it: a capture lacking any is listed in `missing`.
REQUIRED_META: Final = (
    "soc_source", "soc_time_basis", "soc_start", "soc_end", "soc_start_at", "soc_end_at", "register_entity",
    "register_start_kwh", "register_end_kwh", "register_basis_start", "register_basis_end", "capacity_kwh",
    "phases", "voltage_v", "plug_in_basis", "late_energy",
)


def _clean_quality(raw: Any) -> dict[str, int] | None:
    """The provenance counters, exactly as written: any other shape is not a capture's quality (`None`)."""
    if not isinstance(raw, dict) or set(raw) != set(_QUALITY_KEYS):
        return None
    for key in _QUALITY_KEYS:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_COUNT:
            return None
    return {key: raw[key] for key in _QUALITY_KEYS}


def clean_meta(raw: Any) -> dict[str, Any] | None:
    """A capture's provenance read as untrusted: bounded, typed, unknown keys dropped, `missing` recomputed (never
    taken from the file). `None` (the capture is dropped) when the quality counters are not exactly what this writes."""
    if not isinstance(raw, dict) or raw.get("v") != CAPTURE_VERSION:
        return None
    quality = _clean_quality(raw.get("quality"))
    if quality is None:
        return None
    meta: dict[str, Any] = {"v": CAPTURE_VERSION, "quality": quality}
    for key in _META_STRINGS:
        value = raw.get(key)
        meta[key] = value if _ident(value) else None
    for key in _META_NUMBERS:
        value = raw.get(key)
        meta[key] = float(value) if _finite(value) else None
    for key in _META_TIMES:
        parsed = _when(raw.get(key))
        meta[key] = None if parsed is None else parsed.isoformat()
    phases = raw.get("phases")
    meta["phases"] = phases if isinstance(phases, int) and not isinstance(phases, bool) and 1 <= phases <= 3 else None
    for key, allowed in _ENUMS.items():
        value = raw.get(key)
        meta[key] = value if value in allowed else None
    meta["missing"] = [key for key in REQUIRED_META if meta.get(key) is None]
    return meta


@dataclass(frozen=True, slots=True)
class Capture:
    """One capture-only stretch (Stage 15.9a): what a sample holds, tagged `origin: morek_capture`, plus the provenance
    Stage 15.9b needs to revalidate it. Nothing the planner reads."""

    id: str
    kwh: float
    delta_percent: float
    at: datetime
    meta: dict[str, Any]

    @property
    def kwh_per_percent(self) -> float:
        return self.kwh / self.delta_percent

    def as_dict(self) -> dict[str, Any]:
        return {
            "origin": ORIGIN_CAPTURE, "id": self.id, "kwh": self.kwh, "delta_percent": self.delta_percent,
            "at": self.at.isoformat(), "meta": self.meta,
        }

    @staticmethod
    def from_stored(raw: Any) -> Capture | None:
        if not isinstance(raw, dict) or raw.get("origin") != ORIGIN_CAPTURE:
            return None  # an unknown or missing origin is not a capture: fail closed
        ident, kwh, delta, at = raw.get("id"), raw.get("kwh"), raw.get("delta_percent"), _when(raw.get("at"))
        if not _ident(ident) or at is None or not _finite_positive(kwh) or not _finite(delta):
            return None
        if not MIN_DELTA_PERCENT <= float(delta) <= 100.0:
            return None
        meta = clean_meta(raw.get("meta"))
        if meta is None:
            return None
        return Capture(id=ident, kwh=float(kwh), delta_percent=float(delta), at=at, meta=meta)


@dataclass(frozen=True, slots=True)
class CaptureAnchor:
    """A capture stretch's start: the `Anchor` and what was true there, with the counters of what happened since."""

    anchor: Anchor
    meta: dict[str, Any]

    def identity(self) -> tuple[Any, ...]:
        """What must stay the same for the stretch to go on; any change discards it (starts again)."""
        meta = self.meta
        return (
            self.anchor.vehicle_id, self.anchor.session, self.anchor.source, meta.get("capacity_kwh"),
            meta.get("register_entity"), meta.get("phases"), meta.get("voltage_v"), meta.get("plug_in_basis"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"anchor": self.anchor.as_dict(), "meta": self.meta}

    @staticmethod
    def from_stored(raw: Any) -> CaptureAnchor | None:
        if not isinstance(raw, dict):
            return None
        anchor = Anchor.from_stored(raw.get("anchor"))
        meta = clean_meta(raw.get("meta"))
        last = _when(raw.get("meta", {}).get("last_look_at")) if isinstance(raw.get("meta"), dict) else None
        if anchor is None or meta is None:
            return None
        meta["last_look_at"] = None if last is None else last.isoformat()
        return CaptureAnchor(anchor, meta)


@dataclass(frozen=True, slots=True)
class LearnedEnergy:
    """What is known of one car's wall kWh per percent, as the planner and the diagnostics read it."""

    vehicle_id: str | None
    #: The median of the samples, or `None` with none.
    kwh_per_percent: float | None
    samples: tuple[EnergySample, ...]
    trusted: bool
    discarded: int = 0
    #: The open plug-in's own sample, not counted until the plug-in ends.
    pending: EnergySample | None = None
    #: Stage 15.9b diagnostics (never part of what a plan or the input evidence compares): the promoted captures that
    #: voted, whether the figure comes from them, and the rejected captures counted once per reason.
    promoted: int = field(default=0, compare=False)
    from_promoted: bool = field(default=False, compare=False)
    rejections: dict[str, int] = field(default_factory=dict, compare=False)
    #: Stage 15.11 (display only): how many of the valid votes (samples without the promoted rule) agree within
    #: `TRUST_SPREAD` of their median, and how many are valid for today's battery size. Never compared.
    agreeing: int = field(default=0, compare=False)
    valid: int = field(default=0, compare=False)

    @property
    def use_kwh_per_percent(self) -> float | None:
        """What the need counts on: the learned figure once trusted, else nothing (the battery size and the fixed
        efficiency, as before)."""
        return self.kwh_per_percent if self.trusted else None

    def as_dict(self) -> dict[str, Any]:
        # No car's identity (the diagnostics name none), and the samples keyed oldest first (no lists of data).
        return {
            "for_car": self.vehicle_id is not None,
            "kwh_per_percent": None if self.kwh_per_percent is None else round(self.kwh_per_percent, 4),
            "samples": {
                str(index): {"kwh": round(s.kwh, 3), "delta_percent": round(s.delta_percent, 1), "at": s.at.isoformat()}
                for index, s in enumerate(self.samples, start=1)
            },
            "pending_sample": None if self.pending is None else {
                "kwh": round(self.pending.kwh, 3),
                "delta_percent": round(self.pending.delta_percent, 1),
                "at": self.pending.at.isoformat(),
            },
            "trusted": self.trusted,
            "discarded": self.discarded,
            "promoted": self.promoted,
            "from_promoted": self.from_promoted,
            "rejections": dict(self.rejections),
            "agreeing": self.agreeing,
            "valid": self.valid,
        }


NOTHING_LEARNED: Final = LearnedEnergy(vehicle_id=None, kwh_per_percent=None, samples=(), trusted=False)


def learned_from(
    vehicle_id: str | None, samples: list[EnergySample], discarded: int = 0, open_session: str | None = None
) -> LearnedEnergy:
    """From the last `MAX_SAMPLES` samples of ended plug-ins (the open plug-in's own, still growing, is left out until
    it ends): trusted when at least `TRUST_SAMPLES` of them lie within `TRUST_SPREAD` of their median, and then the
    figure is the median of those that agree, so one odd charge neither moves it nor takes the trust away."""
    pending = next((sample for sample in samples if sample.id == open_session), None) if open_session else None
    kept = [sample for sample in samples if sample is not pending][-MAX_SAMPLES:]
    if not kept:
        return LearnedEnergy(vehicle_id, None, (), False, discarded, pending)
    median = statistics.median(sample.kwh_per_percent for sample in kept)
    agreeing = [
        sample.kwh_per_percent for sample in kept if abs(sample.kwh_per_percent - median) <= TRUST_SPREAD * median
    ]
    trusted = len(agreeing) >= TRUST_SAMPLES
    figure = statistics.median(agreeing) if trusted else median
    return LearnedEnergy(
        vehicle_id, figure, tuple(kept), trusted, discarded, pending, agreeing=len(agreeing), valid=len(kept)
    )


@dataclass(slots=True)
class _Car:
    samples: list[EnergySample]
    discarded: int = 0
    #: The last plug-in whose sample was discarded, so a stretch that stays out of bounds is counted once.
    discarded_session: str | None = None
    #: Stage 15.9a capture-only stretches: apart from `samples`, never read by `learned()`.
    captures: list[Capture] = field(default_factory=list)
    captures_discarded: int = 0
    #: Stage 15.9b: the plug-ins (capture ids) promoted to votes, the reasons seen per rejected capture (counted once
    #: each) and the totals by reason.
    promoted: list[str] = field(default_factory=list)
    rejected: dict[str, list[str]] = field(default_factory=dict)
    rejection_counts: dict[str, int] = field(default_factory=dict)


class LearnedEnergyStore:
    """One charger's learned wall kWh per percent, per car, and the open stretch's start, kept across restarts."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, f"{_STORE_PREFIX}.{entry_id}")
        self._cars: dict[str, _Car] = {}
        self.anchor: Anchor | None = None
        #: The plug-in (car, plug-in) last seen going on: its sample is not counted until it ends.
        self.open: tuple[str, str] | None = None
        #: The capture stretch's own start and open plug-in (Stage 15.9a): never the legacy `anchor`/`open`.
        self.capture_anchor: CaptureAnchor | None = None
        self.capture_open: tuple[str, str] | None = None
        #: Stage 15.9b: how a capture is proven now against the retained records (`checker(vehicle_id, capture,
        #: initial)` returns a `REJECT_REASONS` code, or `None` when proven; `initial` is the first promotion), and the
        #: cars whose stored promotions this process has revalidated.
        self.checker: Callable[[str, Capture, bool], str | None] | None = None
        self._checked: set[str] = set()

    async def async_load(self) -> None:
        """Read what was stored; anything that is not exactly what this writes is dropped. A file that cannot be read
        at all (corrupt, or written by a later version) never stops the charger: it starts with nothing learned."""
        try:
            raw = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - a learned figure is never worth a charger that does not start
            _LOGGER.warning(
                "SpotNav: the learned energy per percent could not be read (%s); learning again", type(err).__name__
            )
            raw = None
        self._cars, self.anchor, self.open = parse_stored(raw)
        self.capture_anchor, self.capture_open = parse_captures(raw, self._cars)
        self._checked = set()  # a stored promotion is believed only after this process proved it again

    @staticmethod
    async def async_remove_stored(hass: HomeAssistant, entry_id: str) -> None:
        """The charger is gone for good: what was learned at it goes too."""
        await Store(hass, _STORE_VERSION, f"{_STORE_PREFIX}.{entry_id}").async_remove()

    async def async_reset(self) -> bool:
        """Stage 15.11, an administrator's explicit reset: forget everything learned at this charger (samples, captures,
        promotions, rejections, stretch starts and open plug-ins), in memory first so nothing is read from it again, then
        the stored file through the store's own removal so it cannot come back after a restart. Returns whether the file
        is gone; when its removal failed the (now empty) state is queued to replace it and the caller says so."""
        self._cars = {}
        self.anchor = None
        self.open = None
        self.capture_anchor = None
        self.capture_open = None
        self._checked = set()
        try:
            await self._store.async_remove()
        except Exception as err:  # noqa: BLE001 - reported to the caller by the False
            _LOGGER.warning("SpotNav: the learned energy file could not be removed (%s)", type(err).__name__)
            self._save()
            return False
        return True

    def learned(
        self, vehicle_id: str | None, capacity_kwh: float | None, *, drop: bool = False, morek: bool = False
    ) -> LearnedEnergy:
        """What is learned for this car, counting only the samples that fit today's battery size; nothing without an
        identified car. With `drop` (the planner's need) those that no longer fit are dropped for good and counted;
        without it (the estimate, the dashboard, the diagnostics) this only looks. With `morek` (Morek schedule-owned
        planning, decided by the caller) only the currently validated promoted captures count, else the default: the
        legacy samples are never read. Without it the legacy samples keep their own rules and captures are ignored."""
        if not vehicle_id:
            return NOTHING_LEARNED
        car = self._cars.get(vehicle_id)
        if car is None:
            return learned_from(vehicle_id, [])
        fitting = [sample for sample in car.samples if fits(sample.kwh_per_percent, capacity_kwh)]
        discarded = min(_MAX_DISCARDED, car.discarded + len(car.samples) - len(fitting))
        if drop and len(fitting) != len(car.samples):
            car.discarded, car.samples = discarded, fitting
            self._save()
        if not morek:
            open_session = self.open[1] if self.open is not None and self.open[0] == vehicle_id else None
            return learned_from(vehicle_id, fitting, discarded, open_session)
        none = learned_from(vehicle_id, [], discarded)
        if not (car.captures or car.promoted or car.rejection_counts):
            return none
        if drop or vehicle_id not in self._checked:
            self._revalidate(vehicle_id, capacity_kwh)
        votes = self._votes(car, vehicle_id)
        counts = dict(car.rejection_counts)
        promoted = _promoted_learned(vehicle_id, votes, capacity_kwh, discarded)
        if promoted is not None:
            return replace(promoted, rejections=counts)
        valid, agreeing = _vote_counts(votes, capacity_kwh)
        return replace(none, promoted=len(votes), rejections=counts, agreeing=agreeing, valid=valid)

    def put(self, vehicle_id: str, sample: EnergySample, capacity_kwh: float | None) -> bool:
        """Keep `sample` as its plug-in's sample (replacing that plug-in's shorter one), or, when it is out of
        bounds, drop that plug-in's sample and count it once. Returns whether it was kept."""
        car = self._cars.setdefault(vehicle_id, _Car(samples=[]))
        others = [kept for kept in car.samples if kept.id != sample.id]
        if not fits(sample.kwh_per_percent, capacity_kwh):
            if car.discarded_session != sample.id:
                car.discarded_session = sample.id
                car.discarded = min(_MAX_DISCARDED, car.discarded + 1)
            car.samples = others
            self._save()
            return False
        if car.discarded_session == sample.id:
            # The stretch came back within bounds as it grew: it was not a bad one after all.
            car.discarded_session = None
            car.discarded = max(0, car.discarded - 1)
        car.samples = [*others, sample][-_STORED_SAMPLES:]
        self._save()
        return True

    def captures(self, vehicle_id: str) -> tuple[Capture, ...]:
        """The capture-only stretches of one car (diagnostics and Stage 15.9b's revalidation; never the planner)."""
        car = self._cars.get(vehicle_id)
        return () if car is None else tuple(car.captures)

    def put_capture(self, vehicle_id: str, capture: Capture, capacity_kwh: float | None) -> bool:
        """Keep `capture` as its plug-in's capture (replacing that plug-in's shorter one), within bounds and retention;
        a stretch out of bounds is not kept and is counted. Touches nothing the planner reads."""
        car = self._cars.setdefault(vehicle_id, _Car(samples=[]))
        others = [kept for kept in car.captures if kept.id != capture.id and kept.at >= capture.at - CAPTURE_MAX_AGE]
        if not fits(capture.kwh_per_percent, capacity_kwh):
            car.captures = others
            car.captures_discarded = min(_MAX_DISCARDED, car.captures_discarded + 1)
            self._save()
            return False
        car.captures = [*others, capture][-MAX_CAPTURES:]
        if capture.id in car.promoted:
            car.promoted = [kept for kept in car.promoted if kept != capture.id]  # changed content: proven again
        self._save()
        return True

    def rejection_counts(self, vehicle_id: str) -> dict[str, int]:
        """The captures not promoted, counted once per capture and reason (for the display of Stage 15.11)."""
        car = self._cars.get(vehicle_id)
        return {} if car is None else dict(car.rejection_counts)

    def _open_id(self, vehicle_id: str) -> str | None:
        return self.capture_open[1] if self.capture_open is not None and self.capture_open[0] == vehicle_id else None

    def _votes(self, car: _Car, vehicle_id: str) -> list[Capture]:
        """The promoted captures of ended plug-ins, one per plug-in, newest `PROMOTE_MAX_VOTES`."""
        open_id, promoted = self._open_id(vehicle_id), set(car.promoted)
        latest: dict[str, Capture] = {}
        for capture in car.captures:
            if capture.id in promoted and capture.id != open_id and (
                capture.id not in latest or capture.at >= latest[capture.id].at
            ):
                latest[capture.id] = capture
        return sorted(latest.values(), key=lambda item: item.at)[-PROMOTE_MAX_VOTES:]

    def _revalidate(self, vehicle_id: str, capacity_kwh: float | None) -> None:
        """A safe read: revalidate while this car's plug-in is closed (a stored promotion also once after a restart), so
        a late conflicting record revokes a promotion at the next planning decision and never mid-charge."""
        if self._open_id(vehicle_id) is not None and vehicle_id in self._checked:
            return
        try:
            self.evaluate(vehicle_id, capacity_kwh)
        except Exception:  # noqa: BLE001 - promotion is a convenience, never worth a plan; nothing stays promoted
            _LOGGER.debug("Revalidating the captures failed", exc_info=True)
            car = self._cars.get(vehicle_id)
            if car is not None and car.promoted:
                car.promoted = []
                self._save()

    def evaluate(self, vehicle_id: str, capacity_kwh: float | None, now: datetime | None = None) -> None:
        """Revalidate every capture of ended plug-ins (`metadata_reason`, then the `checker`): the proven ones are the
        promoted ones (one-way unless a later record conflicts), the others are counted once per reason and never vote."""
        car = self._cars.get(vehicle_id)
        if car is None:
            return
        now = now or dt_util.utcnow()
        open_id = self._open_id(vehicle_id)
        latest: dict[str, Capture] = {}
        for capture in car.captures:
            if capture.id != open_id and (capture.id not in latest or capture.at >= latest[capture.id].at):
                latest[capture.id] = capture
        ended = sorted((c for c in latest.values() if c.at >= now - CAPTURE_MAX_AGE), key=lambda item: item.at)
        was, keep, unavailable = set(car.promoted), [], False
        for capture in ended:
            reason = metadata_reason(capture, capacity_kwh, now)
            if reason is None:
                reason = self._proof(vehicle_id, capture, initial=capture.id not in was)
            if reason is None:
                keep.append(capture.id)
            else:
                unavailable = unavailable or reason == "evidence_unavailable"
                self._reject(car, capture.id, reason)
        changed = keep != car.promoted
        car.promoted = keep
        stored = {capture.id for capture in car.captures}
        for stale in [ident for ident in car.rejected if ident not in stored]:
            del car.rejected[stale]
            changed = True
        if not unavailable:
            self._checked.add(vehicle_id)
        if changed:
            self._save()

    def _proof(self, vehicle_id: str, capture: Capture, *, initial: bool) -> str | None:
        if self.checker is None:
            return "evidence_unavailable"
        try:
            reason = self.checker(vehicle_id, capture, initial)
        except Exception:  # noqa: BLE001 - what cannot be proven is not proven
            return "evidence_unavailable"
        return None if reason is None else reason if reason in REJECT_REASONS else "evidence_unavailable"

    def _reject(self, car: _Car, ident: str, reason: str) -> None:
        seen = car.rejected.setdefault(ident, [])
        if reason in seen:
            return
        if len(car.rejected) > _MAX_REJECTED:
            for old in list(car.rejected)[: len(car.rejected) - _MAX_REJECTED]:
                if old != ident:
                    del car.rejected[old]
        seen.append(reason)
        car.rejection_counts[reason] = min(_MAX_COUNT, car.rejection_counts.get(reason, 0) + 1)
        self._save()

    def set_capture_anchor(self, anchor: CaptureAnchor | None) -> None:
        if anchor != self.capture_anchor:
            self.capture_anchor = anchor
            self._save()

    def set_capture_open(self, plug_in: tuple[str, str] | None) -> None:
        if plug_in != self.capture_open:
            previous = self.capture_open
            self.capture_open = plug_in
            self._save()
            if previous is not None:
                # The previous plug-in ended: its captures are revalidated now and promoted when proven.
                try:
                    self.evaluate(previous[0], None)
                except Exception:  # noqa: BLE001 - never worth the capture tick
                    _LOGGER.debug("Promoting the captures failed", exc_info=True)

    def set_anchor(self, anchor: Anchor | None) -> None:
        if anchor != self.anchor:
            self.anchor = anchor
            self._save()

    def set_open(self, plug_in: tuple[str, str] | None) -> None:
        if plug_in != self.open:
            self.open = plug_in
            self._save()

    def _save(self) -> None:
        self._store.async_delay_save(self._to_store, SAVE_DELAY_S)

    def _to_store(self) -> dict[str, Any]:
        stored: dict[str, Any] = {
            "vehicles": {
                vehicle_id: {
                    "samples": [sample.as_dict() for sample in car.samples],
                    "discarded": car.discarded,
                    "discarded_session": car.discarded_session,
                    **(
                        {
                            "captures": [c.as_dict() for c in car.captures],
                            "captures_discarded": car.captures_discarded,
                            "promoted": list(car.promoted),
                            "rejected": {ident: list(seen) for ident, seen in car.rejected.items()},
                            "rejection_counts": dict(car.rejection_counts),
                        }
                        if car.captures or car.captures_discarded or car.rejection_counts else {}
                    ),
                }
                for vehicle_id, car in self._cars.items()
            },
            "anchor": None if self.anchor is None else self.anchor.as_dict(),
            "open": None if self.open is None else {"vehicle_id": self.open[0], "session": self.open[1]},
        }
        if self.capture_anchor is not None or self.capture_open is not None:
            stored["capture"] = {
                "anchor": None if self.capture_anchor is None else self.capture_anchor.as_dict(),
                "open": None if self.capture_open is None else {
                    "vehicle_id": self.capture_open[0], "session": self.capture_open[1],
                },
            }
        return stored


@dataclass(frozen=True, slots=True)
class SocSeen:
    """The car's level as one look sees it: the percentage, its age (s), whether it is an estimate, and where it was
    read (`charger` or `vehicle`)."""

    soc_percent: float | None
    age_s: float | None
    estimated: bool
    source: str | None = None

    @property
    def fresh(self) -> bool:
        return (
            self.soc_percent is not None
            and not self.estimated
            and self.age_s is not None
            and 0.0 <= self.age_s <= SOC_FRESH_MAX_AGE_S
        )


@dataclass(frozen=True, slots=True)
class CaptureContext:
    """What one capture look knows beyond the level and the count (Stage 15.9a): where the count is read, the wiring,
    how the plug-in is known, whether the charge is held or paused now, when and on what basis the level was reported,
    and how to tell whether energy of a stretch is clean of unplaced late energy (`None`: unknown)."""

    register_entity: str | None
    phases: int | None
    voltage_v: float | None
    plug_in_basis: str | None
    held: bool
    paused: bool
    soc_report_at: datetime | None
    soc_time_basis: str | None
    late_energy: Callable[[datetime, datetime], str] | None = None


class EnergySampler:
    """Turns the once-a-minute looks into samples for the store (see the module docstring)."""

    def __init__(self, store: LearnedEnergyStore) -> None:
        self._store = store
        #: The register's values by when they were posted, and by when they were looked at.
        self._posts: dict[datetime, float] = {}
        self._looks: list[tuple[datetime, float]] = []
        #: Whether this process has made a capture look yet: the first one after a restart marks the stretch.
        self._capture_seen = False

    def reset(self) -> None:
        """Forget the register history and the capture restart mark (Stage 15.11, after the store was reset), so nothing
        looked at before the reset can be paired with a level after it."""
        self._posts = {}
        self._looks = []
        self._capture_seen = False

    def observe(
        self,
        now: datetime,
        *,
        vehicle_id: str | None,
        session: str | None,
        soc: SocSeen,
        register_kwh: float | None,
        register_posted_at: datetime | None,
        capacity_kwh: float | None,
        charging: bool = True,
    ) -> None:
        """One look: what the car's level and the count say now. `session` is `None` with no plug-in known or the
        car unplugged; `charging` says whether the charger charges now (a value the register held is believed only
        while it does not)."""
        self._remember(now, register_kwh, register_posted_at)
        anchor = self._store.anchor
        if not session:
            # Unplugged, or no plug-in known: the stretch ends, and so does the open plug-in.
            self._store.set_anchor(None)
            self._store.set_open(None)
            return
        if not vehicle_id:
            # No car identified: an unidentified car is not one car.
            self._store.set_anchor(None)
            return
        self._store.set_open((vehicle_id, session))
        if anchor is not None and (anchor.vehicle_id, anchor.session, anchor.source) != (
            vehicle_id, session, soc.source,
        ):
            anchor = None  # a plug-out, another car, or the level read elsewhere: the stretch starts again
        if anchor is not None and register_kwh is not None and register_kwh < anchor.kwh - REGISTER_TOLERANCE_KWH:
            anchor = None  # the count went back (a reset, a meter replaced)
        if register_kwh is None or not soc.fresh:
            self._store.set_anchor(anchor)
            return
        assert soc.soc_percent is not None and soc.age_s is not None
        made_at = now - timedelta(seconds=soc.age_s)
        kwh = self._value_at(made_at, now, register_kwh, charging=charging)
        if kwh is None:
            self._store.set_anchor(anchor)
            return
        if anchor is None or soc.soc_percent < anchor.soc_percent or kwh < anchor.kwh - REGISTER_TOLERANCE_KWH:
            self._store.set_anchor(Anchor(vehicle_id, session, soc.soc_percent, made_at, kwh, soc.source))
            return
        self._store.set_anchor(anchor)
        if made_at <= anchor.at:
            return  # the reading the stretch starts from, seen again
        delta = soc.soc_percent - anchor.soc_percent
        energy = kwh - anchor.kwh
        if delta >= MIN_DELTA_PERCENT and energy > 0:
            self._store.put(vehicle_id, EnergySample(session, energy, delta, made_at), capacity_kwh)

    def observe_capture(
        self,
        now: datetime,
        *,
        vehicle_id: str | None,
        session: str | None,
        soc: SocSeen,
        register_kwh: float | None,
        register_posted_at: datetime | None,
        capacity_kwh: float | None,
        charging: bool,
        context: CaptureContext,
    ) -> None:
        """One capture look (Stage 15.9a). Same stretch rules as `observe`, kept apart: its own start in the store, a
        capture written with its provenance, nothing a plan reads. A level counts only at the time the car reported it
        (never when it arrived), from a source whose time is known; a change of car, source, battery size, register,
        wiring or the way the plug-in is known starts the stretch again (the discarded stretch leaves no capture)."""
        resumed = not self._capture_seen
        self._capture_seen = True
        self._remember(now, register_kwh, register_posted_at)
        store = self._store
        if not session:
            store.set_capture_anchor(None)
            store.set_capture_open(None)
            return
        if not vehicle_id:
            store.set_capture_anchor(None)
            return
        store.set_capture_open((vehicle_id, session))
        held = store.capture_anchor
        identity = (
            vehicle_id, session, soc.source, capacity_kwh, context.register_entity, context.phases, context.voltage_v,
            context.plug_in_basis,
        )
        if held is not None and (held.identity() != identity or (
            register_kwh is not None and register_kwh < held.anchor.kwh - REGISTER_TOLERANCE_KWH
        )):
            held = None
        if held is not None:
            held = self._looked(held, now, charging, register_posted_at, context, resumed)
        made_at = self._endpoint_time(now, soc, context)
        if register_kwh is None or context.register_entity is None or not soc.fresh or made_at is None:
            store.set_capture_anchor(held)
            return
        assert soc.soc_percent is not None
        kwh, basis = self._value_and_basis(made_at, now, register_kwh, charging=charging)
        if kwh is None or basis is None:
            store.set_capture_anchor(held)
            return
        if held is None or soc.soc_percent < held.anchor.soc_percent or kwh < held.anchor.kwh - REGISTER_TOLERANCE_KWH:
            store.set_capture_anchor(self._started(
                Anchor(vehicle_id, session, soc.soc_percent, made_at, kwh, soc.source), now, basis, capacity_kwh,
                charging, register_posted_at, context,
            ))
            return
        store.set_capture_anchor(held)
        if made_at <= held.anchor.at:
            return
        delta = soc.soc_percent - held.anchor.soc_percent
        energy = kwh - held.anchor.kwh
        if delta < MIN_DELTA_PERCENT or energy <= 0:
            return
        start = held.meta
        meta: dict[str, Any] = {
            "v": CAPTURE_VERSION,
            "soc_source": soc.source,
            "soc_time_basis": context.soc_time_basis,
            "soc_start": held.anchor.soc_percent,
            "soc_end": soc.soc_percent,
            "soc_start_at": held.anchor.at.isoformat(),
            "soc_end_at": made_at.isoformat(),
            "register_entity": context.register_entity,
            "register_start_kwh": held.anchor.kwh,
            "register_end_kwh": kwh,
            "register_basis_start": start.get("register_basis_start"),
            "register_basis_end": basis,
            "capacity_kwh": capacity_kwh,
            "phases": context.phases,
            "voltage_v": context.voltage_v,
            "plug_in_basis": context.plug_in_basis,
            "late_energy": "unknown",
            "quality": dict(start["quality"]),
        }
        if context.late_energy is not None:
            try:
                meta["late_energy"] = context.late_energy(held.anchor.at, made_at)
            except Exception:  # noqa: BLE001 - unknown is the safe answer, never clean
                meta["late_energy"] = "unknown"
        cleaned = clean_meta(meta)
        if cleaned is None:
            return
        store.put_capture(vehicle_id, Capture(session, energy, delta, made_at, cleaned), capacity_kwh)

    @staticmethod
    def _endpoint_time(now: datetime, soc: SocSeen, context: CaptureContext) -> datetime | None:
        """When the car's level was made: the car's own report time, never the time it arrived. `None` (no endpoint)
        when the report time is not known: a vehicle level stamped only by when Home Assistant wrote it is arrival."""
        if soc.age_s is None:
            return None
        if context.soc_time_basis == "vehicle_timestamp":
            reported = context.soc_report_at
            if reported is None or reported.tzinfo is None or reported > now + timedelta(seconds=60):
                return None
            return reported
        if soc.source == "charger" and context.soc_time_basis in (None, "last_updated"):
            return now - timedelta(seconds=soc.age_s)
        return None

    @staticmethod
    def _counters(meta: dict[str, Any], now: datetime, charging: bool, posted_at: datetime | None,
                  context: CaptureContext, *, resumed: bool = False) -> dict[str, Any]:
        quality = dict(meta["quality"])
        last = _when(meta.get("last_look_at"))
        quality["looks"] = min(_MAX_COUNT, quality["looks"] + 1)
        if last is not None:
            gap = (now - last).total_seconds()
            if gap < 0 or gap > CAPTURE_GAP_S:
                quality["gaps"] = min(_MAX_COUNT, quality["gaps"] + 1)
                quality["max_gap_s"] = min(_MAX_COUNT, max(quality["max_gap_s"], int(abs(gap))))
        if resumed:
            quality["restarts"] = min(_MAX_COUNT, quality["restarts"] + 1)
        for key, hit in (
            ("not_charging_looks", not charging), ("held_looks", context.held), ("paused_looks", context.paused),
            ("unposted_looks", posted_at is None),
        ):
            if hit:
                quality[key] = min(_MAX_COUNT, quality[key] + 1)
        return {**meta, "quality": quality, "last_look_at": now.isoformat()}

    def _looked(self, held: CaptureAnchor, now: datetime, charging: bool, posted_at: datetime | None,
                context: CaptureContext, resumed: bool) -> CaptureAnchor:
        return CaptureAnchor(held.anchor, self._counters(held.meta, now, charging, posted_at, context, resumed=resumed))

    def _started(self, anchor: Anchor, now: datetime, basis: str, capacity_kwh: float | None, charging: bool,
                 posted_at: datetime | None, context: CaptureContext) -> CaptureAnchor:
        quality = dict.fromkeys(_QUALITY_KEYS, 0)
        meta = {
            "v": CAPTURE_VERSION, "quality": quality, "capacity_kwh": capacity_kwh,
            "register_entity": context.register_entity, "phases": context.phases, "voltage_v": context.voltage_v,
            "plug_in_basis": context.plug_in_basis, "register_basis_start": basis, "last_look_at": None,
        }
        return CaptureAnchor(anchor, self._counters(meta, now, charging, posted_at, context))

    def _remember(self, now: datetime, register_kwh: float | None, posted_at: datetime | None) -> None:
        horizon = now - timedelta(seconds=HISTORY_S)
        if register_kwh is not None:
            self._posts[posted_at or now] = register_kwh
            self._looks.append((now, register_kwh))
        self._posts = {at: value for at, value in self._posts.items() if at >= horizon}
        self._looks = [(at, value) for at, value in self._looks if at >= horizon]

    def _value_and_basis(
        self, made_at: datetime, now: datetime, register_kwh: float, *, charging: bool
    ) -> tuple[float | None, str | None]:
        """`_value_at` with how the value was found: `interpolated` between posts, or `held` (not charging)."""
        value = register_value_at(self._posts.items(), made_at, now)
        if value is not None:
            return value, "interpolated"
        held = self._value_at(made_at, now, register_kwh, charging=charging)
        return (None, None) if held is None else (held, "held")

    def _value_at(self, made_at: datetime, now: datetime, register_kwh: float, *, charging: bool) -> float | None:
        """The count when the level was made: interpolated between the register's posts while it posts steadily,
        else, while the charger is not charging, the value it stood at from a look at or before then to now (a
        register that books in chunks while charging would skew it); `None` when neither is known."""
        value = register_value_at(self._posts.items(), made_at, now)
        if value is not None:
            return value
        if charging:
            return None
        before = [kwh for at, kwh in self._looks if at <= made_at]
        if before and abs(before[-1] - register_kwh) <= REGISTER_TOLERANCE_KWH:
            # A count that only rises stood still from that look to now, so it held this value when the level was
            # made.
            return before[-1]
        return None


def parse_stored(raw: Any) -> tuple[dict[str, _Car], Anchor | None, tuple[str, str] | None]:
    """The stored cars, the open stretch's start and the open plug-in that are well formed; anything malformed is
    left out."""
    cars: dict[str, _Car] = {}
    if not isinstance(raw, dict):
        return cars, None, None
    vehicles = raw.get("vehicles")
    if isinstance(vehicles, dict):
        for vehicle_id, item in vehicles.items():
            if not _ident(vehicle_id) or not isinstance(item, dict):
                continue
            stored = item.get("samples")
            if not isinstance(stored, list):
                continue
            samples = [s for s in (EnergySample.from_stored(entry) for entry in stored) if s is not None]
            discarded = item.get("discarded")
            count = int(discarded) if _finite(discarded) and 0 <= discarded <= _MAX_DISCARDED else 0
            session = item.get("discarded_session")
            cars[vehicle_id] = _Car(
                samples=samples[-_STORED_SAMPLES:], discarded=count, discarded_session=session if _ident(session) else None
            )
    stored_open = raw.get("open")
    plug_in = None
    if isinstance(stored_open, dict) and _ident(stored_open.get("vehicle_id")) and _ident(stored_open.get("session")):
        plug_in = (stored_open["vehicle_id"], stored_open["session"])
    return cars, Anchor.from_stored(raw.get("anchor")), plug_in


def parse_captures(
    raw: Any, cars: dict[str, _Car]
) -> tuple[CaptureAnchor | None, tuple[str, str] | None]:
    """Fill each car's captures from what was stored (anything malformed, or tagged otherwise, is dropped), and return
    the capture stretch's start and open plug-in. Separate from `parse_stored`, which the legacy path reads."""
    if not isinstance(raw, dict):
        return None, None
    vehicles = raw.get("vehicles")
    if isinstance(vehicles, dict):
        for vehicle_id, item in vehicles.items():
            car = cars.get(vehicle_id)
            if car is None or not isinstance(item, dict) or not isinstance(item.get("captures"), list):
                continue
            kept = [c for c in (Capture.from_stored(entry) for entry in item["captures"]) if c is not None]
            car.captures = kept[-MAX_CAPTURES:]
            count = item.get("captures_discarded")
            car.captures_discarded = int(count) if _finite(count) and 0 <= count <= _MAX_DISCARDED else 0
            _parse_promotion(car, item)
    block = raw.get("capture")
    if not isinstance(block, dict):
        return None, None
    stored_open = block.get("open")
    plug_in = None
    if isinstance(stored_open, dict) and _ident(stored_open.get("vehicle_id")) and _ident(stored_open.get("session")):
        plug_in = (stored_open["vehicle_id"], stored_open["session"])
    return CaptureAnchor.from_stored(block.get("anchor")), plug_in


def _parse_promotion(car: _Car, item: dict[str, Any]) -> None:
    """The promotion state read as untrusted: promoted ids that are not stored captures, unknown reasons and bad
    counts are dropped (a dropped promotion is simply proven again)."""
    ids = {capture.id for capture in car.captures}
    promoted = item.get("promoted")
    if isinstance(promoted, list):
        car.promoted = list(dict.fromkeys(i for i in promoted if _ident(i) and i in ids))[:MAX_CAPTURES]
    rejected = item.get("rejected")
    if isinstance(rejected, dict):
        for ident, seen in list(rejected.items())[:_MAX_REJECTED]:
            if _ident(ident) and isinstance(seen, list):
                reasons = list(dict.fromkeys(r for r in seen if isinstance(r, str) and r in REJECT_REASONS))
                if reasons:
                    car.rejected[ident] = reasons
    counts = item.get("rejection_counts")
    if isinstance(counts, dict):
        for reason, number in counts.items():
            if reason in REJECT_REASONS and _finite(number) and 0 <= number <= _MAX_COUNT and int(number) == number:
                car.rejection_counts[reason] = int(number)


def metadata_reason(capture: Capture, capacity_kwh: float | None, now: datetime) -> str | None:
    """Why a capture is not a vote by what it recorded alone (`None`: nothing in it forbids it; the retained records
    still decide in the store's `checker`): missing provenance, a level not stamped by the car's own report time, a rise
    under `PROMOTE_MIN_RISE` or an end above `PROMOTE_MAX_END_PERCENT`, implausible energy, a changed battery size, a
    gap, restart, held or paused look, an unobserved register, or a capture-time `unplaced`/`uncertain` late flag. An
    `unknown` flag is not a rejection here (it is only an unevaluated snapshot); the retained session records decide."""
    meta = capture.meta
    if meta.get("missing"):
        return "missing_metadata"
    if meta.get("soc_time_basis") != "vehicle_timestamp":
        return "soc_basis"
    start_at, end_at = _when(meta.get("soc_start_at")), _when(meta.get("soc_end_at"))
    if start_at is None or end_at is None or start_at >= end_at or abs((end_at - capture.at).total_seconds()) > 1.0:
        return "soc_time"
    if end_at > now + timedelta(seconds=_FUTURE_TOLERANCE_S):
        return "soc_future"
    soc_start, soc_end = meta["soc_start"], meta["soc_end"]
    if abs((soc_end - soc_start) - capture.delta_percent) > 0.01:
        return "energy_inconsistent"
    if capture.delta_percent < PROMOTE_MIN_RISE:
        return "rise_below_15"
    if soc_end > PROMOTE_MAX_END_PERCENT:
        return "soc_above_90"
    if not 0 <= soc_start < soc_end <= 100 or abs(
        (meta["register_end_kwh"] - meta["register_start_kwh"]) - capture.kwh
    ) > _ENERGY_TOLERANCE_KWH:
        return "energy_inconsistent"
    if not fits(capture.kwh_per_percent, meta["capacity_kwh"]):
        return "implausible"
    if capacity_kwh is not None and (
        not _finite_positive(capacity_kwh) or abs(capacity_kwh - meta["capacity_kwh"]) > _CAPACITY_TOLERANCE_KWH
    ):
        return "capacity_changed"
    quality = meta["quality"]
    for key, reason in (
        ("gaps", "gap"), ("restarts", "restart"), ("held_looks", "held"), ("paused_looks", "paused"),
        ("unposted_looks", "unobserved"),
    ):
        if quality[key]:
            return reason
    if quality["looks"] < 2:
        return "unobserved"
    late = meta.get("late_energy")
    if late in ("unplaced", "uncertain"):
        return "late_" + late
    return None


def _promoted_learned(
    vehicle_id: str, votes: list[Capture], capacity_kwh: float | None, discarded: int
) -> LearnedEnergy | None:
    """The figure the promoted votes give for a battery of `capacity_kwh`, or `None` (the legacy samples then apply).
    Trusted when `PROMOTE_LENGTHEN_VOTES` votes agree within `TRUST_SPREAD` of their median; a figure under the default
    needs `PROMOTE_SHORTEN_VOTES`; the used figure is clamped to `CLAMP_LOWER`..`CLAMP_UPPER` of the default."""
    if capacity_kwh is None or not _finite_positive(capacity_kwh):
        return None
    votes = _valid_votes(votes, capacity_kwh)
    if len(votes) < PROMOTE_LENGTHEN_VOTES:
        return None
    default = capacity_kwh / CHARGE_EFFICIENCY / 100.0
    median = statistics.median(vote.kwh_per_percent for vote in votes)
    agreeing = [vote.kwh_per_percent for vote in votes if abs(vote.kwh_per_percent - median) <= TRUST_SPREAD * median]
    if len(agreeing) < PROMOTE_LENGTHEN_VOTES:
        return None
    figure = statistics.median(agreeing)
    if figure < default and len(agreeing) < PROMOTE_SHORTEN_VOTES:
        return None  # four agreeing charges may lengthen the time, never shorten it
    figure = min(max(figure, CLAMP_LOWER * default), CLAMP_UPPER * default)
    samples = tuple(EnergySample(vote.id, vote.kwh, vote.delta_percent, vote.at) for vote in votes)
    return LearnedEnergy(
        vehicle_id, figure, samples, True, discarded, None, promoted=len(votes), from_promoted=True,
        agreeing=len(agreeing), valid=len(votes),
    )


def _valid_votes(votes: list[Capture], capacity_kwh: float | None) -> list[Capture]:
    """The promoted votes that fit today's battery size (the only ones that can count)."""
    if capacity_kwh is None or not _finite_positive(capacity_kwh):
        return []
    return [
        vote for vote in votes
        if fits(vote.kwh_per_percent, capacity_kwh)
        and abs(vote.meta["capacity_kwh"] - capacity_kwh) <= _CAPACITY_TOLERANCE_KWH
    ]


def _vote_counts(votes: list[Capture], capacity_kwh: float | None) -> tuple[int, int]:
    """`(valid, agreeing)` for the display: the valid votes, and how many of them lie within `TRUST_SPREAD` of their
    median (an outlier is valid but does not agree)."""
    valid = _valid_votes(votes, capacity_kwh)
    if not valid:
        return 0, 0
    median = statistics.median(vote.kwh_per_percent for vote in valid)
    return len(valid), sum(1 for vote in valid if abs(vote.kwh_per_percent - median) <= TRUST_SPREAD * median)


def with_learned(learned: LearnedEnergy, capacity_kwh: float | None) -> float | None:
    """The battery size the need is worked out with: one that, divided by `CHARGE_EFFICIENCY`, takes the learned wall
    kWh per percent once trusted, else `capacity_kwh` as it is."""
    ratio = learned.use_kwh_per_percent
    return capacity_kwh if ratio is None else ratio * 100.0 * CHARGE_EFFICIENCY


def target_need(
    learned: LearnedEnergy,
    *,
    soc_percent: float,
    capacity_kwh: float | None,
    target_percent: float | None,
    vehicle_max_percent: float | None = None,
) -> tuple[str, float | None]:
    """`(reason, wall kWh)` a target needs: `soc_estimate.target_need_kwh` on the car's learned wall kWh per percent
    once trusted, else on its battery size and `CHARGE_EFFICIENCY`. The one way a target becomes kWh, for the planner
    and the dashboard alike, so they never disagree."""
    return target_need_kwh(
        soc_percent=soc_percent,
        capacity_kwh=with_learned(learned, capacity_kwh),
        target_percent=target_percent,
        vehicle_max_percent=vehicle_max_percent,
    )


def efficiency_for(learned: LearnedEnergy, capacity_kwh: float | None) -> float:
    """The efficiency that, with `capacity_kwh`, gives the learned wall kWh per percent once trusted (what the
    dashboard's `soc.efficiency` states, so the card's `(target - level) x capacity / efficiency` is `target_need`'s
    figure), else `CHARGE_EFFICIENCY`. Within (0, 1] by the bounds; anything else falls back."""
    ratio = learned.use_kwh_per_percent
    if ratio is None or capacity_kwh is None or not _finite_positive(capacity_kwh):
        return CHARGE_EFFICIENCY
    efficiency = capacity_kwh / (ratio * 100.0)
    return efficiency if 0.0 < efficiency <= MAX_EFFICIENCY else CHARGE_EFFICIENCY


def estimate_view(
    learned: LearnedEnergy,
    capacity_kwh: float | None,
    *,
    morek: bool,
    need_kwh: float | None = None,
    default_need_kwh: float | None = None,
) -> dict[str, Any]:
    """The learned-estimate block of Stage 15.11 as the display states it (values only, no wording): whether the figure
    the plan uses is `learned` or the `default`, today's valid and agreeing sample counts (an outlier is valid but does
    not agree), how many agreeing samples lengthen or shorten the time, whether the clamp bounds the figure, and the
    wall energy the target needs with and without it. `effect_minutes` is filled by the caller from the plan's power.
    Display only: nothing here is read by a plan."""
    default = None
    if capacity_kwh is not None and _finite_positive(capacity_kwh):
        default = capacity_kwh / CHARGE_EFFICIENCY / 100.0
    used = learned.use_kwh_per_percent
    clamped = bool(
        morek and used is not None and default is not None and learned.from_promoted
        and (abs(used - CLAMP_LOWER * default) < 1e-9 or abs(used - CLAMP_UPPER * default) < 1e-9)
    )
    lengthen, shorten = (PROMOTE_LENGTHEN_VOTES, PROMOTE_SHORTEN_VOTES) if morek else (TRUST_SAMPLES, TRUST_SAMPLES)
    return {
        "mode": "morek" if morek else "legacy",
        "source": "default" if used is None else "learned",
        "kwh_per_percent": None if used is None else round(used, 4),
        "default_kwh_per_percent": None if default is None else round(default, 4),
        "valid_samples": learned.valid,
        "agreeing_samples": learned.agreeing,
        "needed_to_lengthen": lengthen,
        "needed_to_shorten": shorten,
        "clamped": clamped,
        "need_kwh": None if need_kwh is None or not _finite(need_kwh) else round(need_kwh, 3),
        "default_need_kwh": None if default_need_kwh is None or not _finite(default_need_kwh) else round(default_need_kwh, 3),
        "effect_minutes": None,
        "rejections": {reason: count for reason, count in learned.rejections.items() if reason in REJECT_REASONS and
                       isinstance(count, int) and not isinstance(count, bool) and count > 0},
    }


def _ident(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= _MAX_ID_LEN


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    parsed = dt_util.parse_datetime(value)
    return None if parsed is None or parsed.tzinfo is None else parsed


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0

