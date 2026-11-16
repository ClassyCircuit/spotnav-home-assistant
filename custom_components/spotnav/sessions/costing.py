"""The price maths of a session: energy per interval, and a cost made from it when it is read.

A session never stores a finished cost. It stores, per price interval it drew energy in, the energy
(kWh) and the raw spot price as the relay published it (EUR per kWh) with the exchange rate and its
date, plus that day's average spot price (for the savings comparison). The cost is made at read time
(`price_slices`) from the person's *current* fiscal settings: the planner's own `effective_minor_per_kwh`,
so a corrected VAT, tax or grid fee corrects the whole history. A `Slice` carries its interval's start,
so settings that are dated can be applied per interval later.

Energy delivered between two samples is spread evenly over the time between them, so a 15- or
60-minute price boundary inside the span is honoured by the overlap with each interval, and a
23- or 25-hour day needs no special case because every instant here is absolute. Energy outside every
published interval has no slice (it stays in the session's energy, unpriced), never a guess.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Final

from ..planning.planner import document_rate, effective_minor_per_kwh, FiscalChoice, PlannerInputError


@dataclass(frozen=True, slots=True)
class SpotInterval:
    """One published interval, raw: the relay's EUR per kWh, the day's exchange rate for the market's
    currency (1 for euro) and the date that rate is from."""

    utc_start: datetime
    utc_end: datetime
    day: date
    eur_per_kwh: float
    fx: float
    fx_date: date | None


@dataclass(frozen=True, slots=True)
class Slice:
    """The energy a session drew in one price interval, with the raw price that interval had."""

    start: datetime
    end: datetime
    kwh: float
    eur_per_kwh: float
    fx: float
    fx_date: date | None
    #: The interval's day's average spot price (EUR per kWh, weighted by interval length).
    day_avg_eur: float

    def as_row(self) -> list[Any]:
        return [
            int(self.start.timestamp()),
            int(self.end.timestamp()),
            self.kwh,
            self.eur_per_kwh,
            self.fx,
            self.day_avg_eur,
            None if self.fx_date is None else self.fx_date.isoformat(),
        ]

    @classmethod
    def from_row(cls, row: Any) -> Slice | None:
        """A stored row, or `None` when it is not exactly that shape."""
        if not isinstance(row, list) or len(row) != 7:
            return None
        start, end, kwh, eur, fx, average, fx_date = row
        for number in (start, end, kwh, eur, fx, average):
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                return None
        if kwh < 0 or fx <= 0 or end <= start:
            return None
        moment = None
        if fx_date is not None:
            if not isinstance(fx_date, str):
                return None
            try:
                moment = date.fromisoformat(fx_date)
            except ValueError:
                return None
        return cls(
            datetime.fromtimestamp(start, timezone.utc),
            datetime.fromtimestamp(end, timezone.utc),
            float(kwh),
            float(eur),
            float(fx),
            moment,
            float(average),
        )


@dataclass(frozen=True, slots=True)
class Costing:
    """What a set of slices cost: the part that had a price, in the minor unit.

    `reference_cost_minor` prices that same energy at its day's average effective price.
    """

    priced_kwh: float = 0.0
    cost_minor: float = 0.0
    reference_cost_minor: float = 0.0

    def __add__(self, other: Costing) -> Costing:
        return Costing(
            self.priced_kwh + other.priced_kwh,
            self.cost_minor + other.cost_minor,
            self.reference_cost_minor + other.reference_cost_minor,
        )


NO_COST = Costing()


def spot_intervals(documents: Iterable[Any], currency: str) -> tuple[SpotInterval, ...]:
    """Every published interval of these day documents, raw, in instant order.

    Two documents pricing the same instant give one row, the first winning. A document without a usable
    rate for the currency prices nothing (its energy stays unpriced).
    """
    rows: dict[datetime, SpotInterval] = {}
    # A display day cut from two market files carries each file's own rate in its pieces.
    for document in (piece for whole in documents for piece in whole.pieces()):
        try:
            fx = document_rate(document, currency)
        except PlannerInputError:
            continue
        fx_date = None if currency.upper() == "EUR" else document.fx_date
        for interval in document.intervals:
            if interval.utc_start not in rows:
                rows[interval.utc_start] = SpotInterval(
                    interval.utc_start, interval.utc_end, document.day, interval.eur_per_kwh, fx, fx_date
                )
    return tuple(rows[start] for start in sorted(rows))


def day_averages_eur(spot: Sequence[SpotInterval]) -> dict[date, float]:
    """Each published day's average spot price (EUR per kWh), weighted by interval length so a 23- or
    25-hour day and a mixed 15/60-minute day average what the clock says."""
    weighted: dict[date, float] = {}
    seconds: dict[date, float] = {}
    for interval in spot:
        length = (interval.utc_end - interval.utc_start).total_seconds()
        weighted[interval.day] = weighted.get(interval.day, 0.0) + interval.eur_per_kwh * length
        seconds[interval.day] = seconds.get(interval.day, 0.0) + length
    return {day: weighted[day] / seconds[day] for day in weighted if seconds[day] > 0}


class SpotIndex:
    """`spot` made ready for many splits: its intervals in instant order, their starts for a binary search, the
    longest interval's length (how far before an instant an interval holding it may start) and each day's average
    (`day_averages_eur`), all once. A split then visits only the intervals near its span, not every one: an import of
    24 months' hours over 24 months' intervals was quadratic, on the event loop."""

    __slots__ = ("_averages", "_longest", "_spot", "_starts")

    def __init__(self, spot: Sequence[SpotInterval]) -> None:
        self._spot = sorted(spot, key=lambda interval: interval.utc_start)
        self._starts = [interval.utc_start for interval in self._spot]
        self._longest = max((interval.utc_end - interval.utc_start for interval in self._spot), default=None)
        self._averages = day_averages_eur(self._spot)

    def _near(self, start: datetime, end: datetime, *, point: bool) -> Sequence[SpotInterval]:
        """The intervals, in instant order, that may hold `start` (`point`) or overlap `start` to `end`: none starts
        at or before `start` less the longest length (it ends by `start`), none starts at or after `end`
        (after `start` for a point)."""
        if self._longest is None or self._longest.total_seconds() <= 0:
            return ()
        low = bisect_right(self._starts, start - self._longest)
        high = bisect_right(self._starts, start) if point else bisect_left(self._starts, end)
        return self._spot[low:high]

    def split(self, start: datetime, end: datetime, energy_kwh: float) -> list[Slice]:
        """The slices of `energy_kwh` delivered evenly from `start` to `end`, one per interval it touched.

        A span with no length is a point: its energy takes the interval holding that instant.
        """
        if energy_kwh <= 0 or not self._spot:
            return []
        span = (end - start).total_seconds()
        if span <= 0:
            for interval in self._near(start, end, point=True):
                if interval.utc_start <= start < interval.utc_end:
                    return [_slice(interval, energy_kwh, self._averages)]
            return []
        out = []
        for interval in self._near(start, end, point=False):
            overlap = (min(end, interval.utc_end) - max(start, interval.utc_start)).total_seconds()
            if overlap > 0:
                out.append(_slice(interval, energy_kwh * overlap / span, self._averages))
        return out


def split_energy(spot: Sequence[SpotInterval], start: datetime, end: datetime, energy_kwh: float) -> list[Slice]:
    """The slices of `energy_kwh` delivered evenly from `start` to `end`, one per interval it touched
    (`SpotIndex.split`; build the index once where many spans are split over the same intervals)."""
    if energy_kwh <= 0 or not spot:
        return []
    return SpotIndex(spot).split(start, end, energy_kwh)


def _slice(interval: SpotInterval, kwh: float, averages: dict[date, float]) -> Slice:
    return Slice(
        interval.utc_start,
        interval.utc_end,
        kwh,
        interval.eur_per_kwh,
        interval.fx,
        interval.fx_date,
        averages.get(interval.day, interval.eur_per_kwh),
    )


def merge_slices(existing: Sequence[Slice], new: Iterable[Slice]) -> tuple[Slice, ...]:
    """`existing` with `new` added: energy in an interval already held is summed into its slice, so a
    session sampled every minute still holds one slice per interval."""
    by_start = {item.start: item for item in existing}
    for item in new:
        held = by_start.get(item.start)
        by_start[item.start] = item if held is None else Slice(
            held.start, held.end, held.kwh + item.kwh, held.eur_per_kwh, held.fx, held.fx_date, held.day_avg_eur
        )
    return tuple(by_start[start] for start in sorted(by_start))


def subtract_slices(after: Sequence[Slice], before: Sequence[Slice]) -> tuple[Slice, ...]:
    """What `after` drew beyond `before` (the same session's slices at an earlier moment), per interval."""
    held = {item.start: item.kwh for item in before}
    out = []
    for item in after:
        kwh = item.kwh - held.get(item.start, 0.0)
        if kwh > 1e-9:
            out.append(replace(item, kwh=kwh))
    return tuple(out)


def price_slices(slices: Sequence[Slice], fiscal: FiscalChoice | None) -> Costing:
    """What the slices cost with `fiscal` (the person's settings as they are now), in the minor unit.

    With no resolvable fiscal choice nothing is priced: a figure that cannot be known stays absent.
    """
    if fiscal is None:
        return NO_COST
    priced = cost = reference = 0.0
    for item in slices:
        if item.kwh <= 0:
            continue
        priced += item.kwh
        cost += item.kwh * effective_minor_per_kwh(item.eur_per_kwh * item.fx, fiscal, item.start)
        reference += item.kwh * effective_minor_per_kwh(item.day_avg_eur * item.fx, fiscal, item.start)
    return Costing(priced, cost, reference)


# ---- Stage 8.2a: spot-only cost of the energy a session placed ---------------------------------------------------
#
# One pure path for `get_sessions` rows, delivery-day/month summaries and `get_charging_history`. It reads only what
# a session stored (`intervals`: kWh per price interval with the raw price and rate) and never a fee, tax, VAT,
# margin, today's price or the network. Cost = sum(placed kWh x raw spot price x stored rate), in the major unit.
# Whatever cannot be priced from proof stays unknown and is counted, never zero and never dropped.

SPOT_BASIS_RECORDED: Final = "recorded_price_slices"
SPOT_BASIS_RETAINED: Final = "retained_price_intervals"
SPOT_BASIS_UNKNOWN: Final = "unknown"
SPOT_BASIS_MIXED: Final = "mixed"  # an aggregate whose priced energy came from both bases
SPOT_PRICE_BASIS: Final = "raw_published_spot_no_fees_no_taxes"
SPOT_ALLOCATION: Final = "price_interval_overlap_estimate"
_TOLERANCE_KWH: Final = 1e-6


@dataclass(frozen=True, slots=True)
class PlacedSpan:
    """Energy a caller can prove was delivered evenly between two instants, with no recorded price slice. It is
    priced only against retained prices of the same `price_source` (named by the caller, never guessed)."""

    start: datetime
    end: datetime
    kwh: float
    price_source: str | None = None


@dataclass(frozen=True, slots=True)
class RetainedPrice:
    """One retained historical price interval with its provenance (area, source, currency, rate)."""

    utc_start: datetime
    utc_end: datetime
    eur_per_kwh: float
    fx: float
    fx_date: date | None
    area_id: str | None
    currency: str | None
    source: str | None


@dataclass(frozen=True, slots=True)
class SpotPiece:
    """Energy placed in one price interval: `price` (major unit per kWh) is `None` when it could not be trusted."""

    start: datetime
    end: datetime
    kwh: float
    price: float | None
    basis: str
    reason: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class SessionSpot:
    """What one session's stored energy placement says, priced spot-only; see `spot_total` / `SpotAllocation`."""

    session_id: str
    start: datetime
    end: datetime | None
    currency: str | None
    major_unit: str | None
    energy_source: str | None
    energy_kwh: float
    pieces: tuple[SpotPiece, ...]
    #: Energy with no usable time or price interval (session energy minus every valid piece).
    remainder_kwh: float
    #: The receipt-only late energy (`reconciled` only; `None` when unknown): never priced, never in `energy_kwh`.
    unplaced_late_kwh: float | None
    unassigned_register_kwh: float | None
    open: bool
    flags: tuple[str, ...] = ()
    #: The price area the session was priced in (Stage 8.3a: the reference day average must come from the same one).
    area_id: str | None = None


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _rate_reason(currency: str | None, fx: float, fx_date: date | None) -> str | None:
    """Why this rate is not trustworthy for `currency`, or `None`. A euro price needs rate 1; any other currency
    needs the day its rate is from."""
    if not currency:
        return "missing_currency"
    if currency.upper() == "EUR":
        return None if abs(fx - 1.0) < 1e-9 else "untrusted_rate"
    return "untrusted_rate" if fx_date is None else None


def _recorded_pieces(session: Any, currency: str | None) -> tuple[list[SpotPiece], list[str], float]:
    """The session's stored slices as pieces: bad rows skipped and flagged, identical duplicates counted once,
    overlapping/conflicting slices kept as placed but unpriced. Returns (pieces, flags, kWh of the pieces)."""
    flags: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    rows = []
    for item in getattr(session, "intervals", ()) or ():
        try:
            start, end, kwh = item.start, item.end, item.kwh
            eur, fx = item.eur_per_kwh, item.fx
            fx_date = getattr(item, "fx_date", None)
            ok = (
                isinstance(start, datetime) and isinstance(end, datetime) and start.tzinfo is not None
                and end.tzinfo is not None and end > start and _finite(kwh) and kwh >= 0 and _finite(eur)
                and _finite(fx) and fx > 0
            )
        except (AttributeError, TypeError):
            ok = False
        if not ok:
            if "invalid_slices" not in flags:
                flags.append("invalid_slices")
            continue
        if kwh <= 0:
            continue
        key = (start, end, float(kwh), float(eur), float(fx))
        if key in seen:
            if "duplicate_slices" not in flags:
                flags.append("duplicate_slices")
            continue
        seen.add(key)
        rows.append((start, end, float(kwh), float(eur), float(fx), fx_date if isinstance(fx_date, date) else None))
    rows.sort(key=lambda row: (row[0], row[1]))
    conflicting: set[int] = set()
    group: list[int] = []
    group_end = None
    for index, row in enumerate(rows):
        if group and row[0] < group_end:
            group.append(index)
            group_end = max(group_end, row[1])
            continue
        if len(group) > 1:
            conflicting.update(group)
        group, group_end = [index], row[1]
    if len(group) > 1:
        conflicting.update(group)
    if conflicting:
        flags.append("conflicting_slices")
    pieces = []
    for index, (start, end, kwh, eur, fx, fx_date) in enumerate(rows):
        reason = "conflicting_slice" if index in conflicting else _rate_reason(currency, fx, fx_date)
        pieces.append(SpotPiece(start, end, kwh, None if reason else eur * fx, SPOT_BASIS_RECORDED, reason))
    return pieces, flags, sum(piece.kwh for piece in pieces)


def _retained_pieces(
    spans: Sequence[PlacedSpan], retained: Sequence[RetainedPrice], *, area_id: str | None, currency: str | None,
    recorded: Sequence[SpotPiece],
) -> tuple[list[SpotPiece], list[str]]:
    """Price proven-placed spans against retained prices that match area, source, currency and instants. Anything
    without that proof is a placed-but-unpriced piece (never today's price, never another source's)."""
    out: list[SpotPiece] = []
    flags: list[str] = []
    by_start: dict[datetime, list[RetainedPrice]] = {}
    for price in retained:
        by_start.setdefault(price.utc_start, []).append(price)
    if any(len(rows) > 1 for rows in by_start.values()):
        flags.append("conflicting_retained_prices")  # a start with two rows prices nothing
    for span in spans:
        if not (isinstance(span.start, datetime) and isinstance(span.end, datetime) and span.end > span.start
                and _finite(span.kwh) and span.kwh > 0):
            flags.append("invalid_placed_span")
            continue
        total = (span.end - span.start).total_seconds()
        if any(span.start < piece.end and piece.start < span.end for piece in recorded):
            # Already carried by a recorded price slice: pricing it again would count that energy twice.
            out.append(SpotPiece(span.start, span.end, span.kwh, None, SPOT_BASIS_RETAINED, "already_priced_window"))
            continue
        candidates = sorted(
            (rows[0] for rows in by_start.values() if len(rows) == 1
             and rows[0].utc_start < span.end and rows[0].utc_end > span.start),
            key=lambda row: row.utc_start,
        )
        cursor = span.start
        for row in candidates:
            if row.utc_start > cursor:
                out.append(SpotPiece(cursor, row.utc_start, span.kwh * (row.utc_start - cursor).total_seconds() / total,
                                     None, SPOT_BASIS_RETAINED, "no_retained_price"))
            begin, finish = max(row.utc_start, cursor), min(row.utc_end, span.end)
            if finish <= begin:
                continue
            kwh = span.kwh * (finish - begin).total_seconds() / total
            if not area_id or row.area_id != area_id or not span.price_source or row.source != span.price_source:
                reason = "price_provenance_mismatch"
            elif not currency or row.currency is None or row.currency.upper() != currency.upper():
                reason = "currency_mismatch"
            elif not (_finite(row.eur_per_kwh) and _finite(row.fx) and row.fx > 0):
                reason = "untrusted_rate"
            else:
                reason = _rate_reason(currency, row.fx, row.fx_date)
            out.append(SpotPiece(begin, finish, kwh, None if reason else row.eur_per_kwh * row.fx,
                                 SPOT_BASIS_RETAINED, reason, row.source if reason is None else None))
            cursor = finish
        if cursor < span.end:
            out.append(SpotPiece(cursor, span.end, span.kwh * (span.end - cursor).total_seconds() / total,
                                 None, SPOT_BASIS_RETAINED, "no_retained_price"))
    return out, flags


def session_spot(
    session: Any, *, spans: Sequence[PlacedSpan] = (), retained: Sequence[RetainedPrice] = (),
) -> SessionSpot:
    """The spot-only pricing of one session (any `ChargeSession`-like object), from its stored placement alone.

    `spans`/`retained` are optional proven placements and retained prices for energy with no recorded slice; the
    live API has no such placement and passes none. Fee/tax/VAT settings are never read.
    """
    currency = getattr(session, "currency", None) or None
    energy = getattr(session, "energy_kwh", 0.0)
    energy = float(energy) if _finite(energy) and energy > 0 else 0.0
    pieces, flags, placed = _recorded_pieces(session, currency)
    if spans:
        extra, extra_flags = _retained_pieces(
            spans, retained, area_id=getattr(session, "area_id", None), currency=currency, recorded=pieces)
        pieces += extra
        flags += extra_flags
        placed += sum(piece.kwh for piece in extra)
    if placed > energy + max(0.001, 0.001 * energy):
        # More energy placed than the session recorded: neither figure can be trusted, so nothing is priced.
        flags.append("slice_energy_exceeds_session_energy")
        pieces = [replace(piece, price=None, reason="slice_energy_exceeds_session_energy") for piece in pieces]
    remainder = max(0.0, energy - placed)
    if remainder <= _TOLERANCE_KWH:
        remainder = 0.0
    late = getattr(session, "late", None)
    unplaced = unassigned = None
    if isinstance(late, dict):
        if late.get("state") == "reconciled" and _finite(late.get("unplaced_late_kwh")):
            unplaced = max(0.0, float(late["unplaced_late_kwh"]))
        if _finite(late.get("unassigned_register_kwh")):
            unassigned = max(0.0, float(late["unassigned_register_kwh"]))
    end = getattr(session, "end", None)
    return SessionSpot(
        str(getattr(session, "id", "")), session.start, end, currency, getattr(session, "major_unit", None),
        getattr(session, "energy_source", None), energy, tuple(pieces), remainder, unplaced, unassigned,
        end is None, tuple(flags), getattr(session, "area_id", None) or None,
    )


# ---- Stage 8.3a: day-average savings baseline ---------------------------------------------------------------------
#
# The same priced kWh as the actual spot cost, re-priced at its delivery day's duration-weighted full-day raw average
# (no fees/taxes). `ReferenceLookup` answers for (session, local day); `sessions/savings.py` is the live one.

SAVINGS_BASIS: Final = "day_average_price"
SAVINGS_PROOF: Final = "held_price_snapshots_contiguous_full_local_day"
_MAX_EXCLUDED_DAYS: Final = 62


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    """A local day's average raw price in the session's major currency per kWh, or `None` with the reason why not.
    `sources` are the held files' provider labels (`unknown` when a file carries none)."""

    price: float | None
    reason: str | None = None
    sources: tuple[str, ...] = ()


ReferenceLookup = Callable[["SessionSpot", date], ReferenceResult]


@dataclass(slots=True)
class SpotBucket:
    """Running totals of spot-priced energy for one period and one currency."""

    priced_kwh: float = 0.0
    cost: float = 0.0
    recorded_kwh: float = 0.0
    retained_kwh: float = 0.0
    unpriced_kwh: float = 0.0
    unplaced_kwh: float = 0.0
    unallocated_kwh: float = 0.0
    unplaced_ambiguous_kwh: float = 0.0
    estimated_kwh: float = 0.0
    sessions: set[str] = field(default_factory=set)
    open_sessions: set[str] = field(default_factory=set)
    unplaced_unknown: set[str] = field(default_factory=set)
    by_source: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, float] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    price_sources: set[str] = field(default_factory=set)
    major_unit: str | None = None
    latest_start: datetime | None = None
    # Stage 8.3a: the priced energy that has a day-average reference (`comparable`) and what it cost either way.
    comparable_kwh: float = 0.0
    comparable_actual: float = 0.0
    comparable_reference: float = 0.0
    excluded_kwh: float = 0.0
    excluded_reasons: dict[str, float] = field(default_factory=dict)
    excluded_days: set[str] = field(default_factory=set)
    reference_days: set[str] = field(default_factory=set)
    reference_sources: set[str] = field(default_factory=set)

    def touch(self, spot: SessionSpot) -> None:
        self.sessions.add(spot.session_id)
        if spot.open:
            self.open_sessions.add(spot.session_id)
        self.flags.update(spot.flags)
        if spot.major_unit:
            self.major_unit = spot.major_unit
        if self.latest_start is None or spot.start > self.latest_start:
            self.latest_start = spot.start

    def add_piece(self, spot: SessionSpot, piece: SpotPiece, fraction: float) -> None:
        self.touch(spot)
        kwh = piece.kwh * fraction
        if piece.price is None:
            self._unpriced(kwh, piece.reason or "unpriced")
            return
        self.priced_kwh += kwh
        self.cost += kwh * piece.price
        if piece.basis == SPOT_BASIS_RETAINED:
            self.retained_kwh += kwh
            if piece.source:
                self.price_sources.add(piece.source)
        else:
            self.recorded_kwh += kwh
        key = spot.energy_source or "unknown"
        self.by_source[key] = self.by_source.get(key, 0.0) + kwh
        if spot.energy_source == "estimated":
            self.estimated_kwh += kwh

    def add_reference(self, spot: SessionSpot, piece: SpotPiece, day: date, fraction: float,
                      lookup: ReferenceLookup) -> None:
        """Compare the priced part of a piece's day share with that day's average (only priced energy is compared;
        unpriced energy is already counted by `add_piece`). A day without a proven reference excludes the energy."""
        if piece.price is None:
            return
        kwh = piece.kwh * fraction
        ref = lookup(spot, day)
        reason = ref.reason
        if reason is None and (ref.price is None or not _finite(ref.price)):
            reason = "reference_unknown"
        if reason is None and piece.source and ref.sources and piece.source not in ref.sources:
            reason = "price_source_mismatch"
        if reason is not None:
            self.excluded_kwh += kwh
            self.excluded_reasons[reason] = self.excluded_reasons.get(reason, 0.0) + kwh
            self.excluded_days.add(day.isoformat())
            return
        self.comparable_kwh += kwh
        self.comparable_actual += kwh * piece.price
        self.comparable_reference += kwh * ref.price
        self.reference_days.add(day.isoformat())
        self.reference_sources.update(ref.sources or ("unknown",))

    def _unpriced(self, kwh: float, reason: str) -> None:
        self.unpriced_kwh += kwh
        self.reasons[reason] = self.reasons.get(reason, 0.0) + kwh

    def add_floating(self, spot: SessionSpot, *, contained: bool) -> None:
        """The session's energy with no price interval and its late energy have no time: whole-period facts when
        the session lies inside the period, otherwise only possible (never summed) membership."""
        self.touch(spot)
        if spot.remainder_kwh > 0:
            if contained:
                self._unpriced(spot.remainder_kwh, "no_price_slice")
            else:
                self.unallocated_kwh += spot.remainder_kwh
        if spot.unplaced_late_kwh is None:
            self.unplaced_unknown.add(spot.session_id)
        elif spot.unplaced_late_kwh > 0:
            if contained:
                self.unplaced_kwh += spot.unplaced_late_kwh
            else:
                self.unplaced_ambiguous_kwh += spot.unplaced_late_kwh

    def merge(self, other: SpotBucket) -> None:
        for name in ("priced_kwh", "cost", "recorded_kwh", "retained_kwh", "unpriced_kwh", "unplaced_kwh",
                     "unallocated_kwh", "unplaced_ambiguous_kwh", "estimated_kwh", "comparable_kwh",
                     "comparable_actual", "comparable_reference", "excluded_kwh"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.sessions |= other.sessions
        self.open_sessions |= other.open_sessions
        self.unplaced_unknown |= other.unplaced_unknown
        self.flags |= other.flags
        self.price_sources |= other.price_sources
        self.excluded_days |= other.excluded_days
        self.reference_days |= other.reference_days
        self.reference_sources |= other.reference_sources
        for name in ("by_source", "reasons", "excluded_reasons"):
            target = getattr(self, name)
            for key, value in getattr(other, name).items():
                target[key] = target.get(key, 0.0) + value
        self.major_unit = other.major_unit or self.major_unit
        if other.latest_start is not None and (self.latest_start is None or other.latest_start > self.latest_start):
            self.latest_start = other.latest_start

    @property
    def total_kwh(self) -> float:
        return self.priced_kwh + self.unpriced_kwh


def _boundary(day: date, zone: tzinfo) -> datetime:
    """Local midnight of `day` as a UTC instant (the one definition every day edge uses, so edges telescope)."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)


def day_bounds(day: date, zone: tzinfo) -> tuple[datetime, datetime]:
    """The UTC instants of the local day `day` (23, 24 or 25 hours long)."""
    return _boundary(day, zone), _boundary(day + timedelta(days=1), zone)


def _day_shares(piece: SpotPiece, zone: tzinfo) -> list[tuple[date, float]]:
    """The fraction of a piece falling in each local day by elapsed time (sums to 1; one entry for most pieces)."""
    total = (piece.end - piece.start).total_seconds()
    day = piece.start.astimezone(zone).date()
    shares = []
    while True:
        a, b = day_bounds(day, zone)
        if a >= piece.end:
            break
        overlap = (min(b, piece.end) - max(a, piece.start)).total_seconds()
        if overlap > 0:
            shares.append((day, overlap / total))
        day += timedelta(days=1)
    return shares


def _day_window_shares(piece: SpotPiece, zone: tzinfo, since: datetime, until: datetime) -> list[tuple[date, float]]:
    """The fraction of a piece inside `since..until` falling in each local day (sums to its window fraction)."""
    total = (piece.end - piece.start).total_seconds()
    out = []
    for day, _share in _day_shares(piece, zone):
        a, b = day_bounds(day, zone)
        overlap = (min(b, piece.end, until) - max(a, piece.start, since)).total_seconds()
        if overlap > 0:
            out.append((day, overlap / total))
    return out


def _window_fraction(piece: SpotPiece, since: datetime, until: datetime) -> float:
    overlap = (min(until, piece.end) - max(since, piece.start)).total_seconds()
    return max(0.0, overlap / (piece.end - piece.start).total_seconds())


def _inside(spot: SessionSpot, since: datetime, until: datetime) -> bool:
    return spot.end is not None and spot.start >= since and spot.end <= until


def _touches(spot: SessionSpot, since: datetime, until: datetime) -> bool:
    return spot.start < until and (spot.end is None or spot.end > since)


def _currency_key(spot: SessionSpot) -> str | None:
    return spot.currency.upper() if spot.currency else None


def _overlapping_sessions(spots: Sequence[SessionSpot]) -> set[str]:
    """Closed sessions whose spans overlap another's: their energy may have been recorded twice."""
    flagged: set[str] = set()
    latest: SessionSpot | None = None
    for spot in sorted((s for s in spots if s.end is not None), key=lambda s: s.start):
        if latest is not None and spot.start < latest.end:
            flagged.update((spot.session_id, latest.session_id))
        if latest is None or spot.end > latest.end:
            latest = spot
    return flagged


class SpotAllocation:
    """Sessions' spot pieces allocated by actual elapsed overlap to local delivery days and arbitrary windows.

    Every piece is counted once: a day's share is its overlap with that day over its whole length, so the days of
    a midnight-crossing interval (or a 23/25-hour day) add back to the whole. Day, month and history-window totals
    all come from the same shares. Allocation inside a price interval is an estimate (`SPOT_ALLOCATION`).
    """

    def __init__(self, spots: Iterable[SessionSpot], zone: tzinfo, reference: ReferenceLookup | None = None) -> None:
        self.spots = list(spots)
        self.zone = zone
        self.reference = reference
        overlapping = _overlapping_sessions(self.spots)
        if overlapping:
            self.spots = [
                replace(s, flags=s.flags + ("overlapping_sessions",)) if s.session_id in overlapping else s
                for s in self.spots
            ]
        self._days: dict[date, dict[str | None, SpotBucket]] = {}
        for spot in self.spots:
            key = _currency_key(spot)
            for piece in spot.pieces:
                for day, fraction in _day_shares(piece, zone):
                    bucket = self._days.setdefault(day, {}).setdefault(key, SpotBucket())
                    bucket.add_piece(spot, piece, fraction)
                    if reference is not None:
                        bucket.add_reference(spot, piece, day, fraction, reference)

    def _floating(self, buckets: dict[str | None, SpotBucket], since: datetime, until: datetime) -> None:
        for spot in self.spots:
            if _touches(spot, since, until) and (spot.remainder_kwh > 0 or spot.unplaced_late_kwh != 0
                                                 or not spot.pieces):
                buckets.setdefault(_currency_key(spot), SpotBucket()).add_floating(
                    spot, contained=_inside(spot, since, until))

    def delivery_day(self, day: date) -> dict[str | None, SpotBucket]:
        """The day's buckets per currency (merged copies, safe to keep)."""
        out: dict[str | None, SpotBucket] = {}
        for key, bucket in self._days.get(day, {}).items():
            out.setdefault(key, SpotBucket()).merge(bucket)
        self._floating(out, *day_bounds(day, self.zone))
        return out

    def delivery_month(self, first: date, last: date) -> dict[str | None, SpotBucket]:
        """The month's buckets: the sum of its delivery days' placed energy plus energy whose session lies inside
        the month but in no single day."""
        out: dict[str | None, SpotBucket] = {}
        day = first
        while day <= last:
            for key, bucket in self._days.get(day, {}).items():
                out.setdefault(key, SpotBucket()).merge(bucket)
            day += timedelta(days=1)
        self._floating(out, _boundary(first, self.zone), _boundary(last + timedelta(days=1), self.zone))
        return out

    def window(self, since: datetime, until: datetime) -> dict[str | None, SpotBucket]:
        """The same, for any window of absolute instants (a history request)."""
        out: dict[str | None, SpotBucket] = {}
        for spot in self.spots:
            key = _currency_key(spot)
            for piece in spot.pieces:
                fraction = _window_fraction(piece, since, until)
                if fraction > 0:
                    bucket = out.setdefault(key, SpotBucket())
                    bucket.add_piece(spot, piece, fraction)
                    if self.reference is not None:
                        for day, share in _day_window_shares(piece, self.zone, since, until):
                            bucket.add_reference(spot, piece, day, share, self.reference)
        self._floating(out, since, until)
        return out

    def days_touched(self) -> set[date]:
        days = set(self._days)
        for spot in self.spots:
            days.add(spot.start.astimezone(self.zone).date())
            if spot.end is not None:
                days.add(spot.end.astimezone(self.zone).date())
        return days


def spot_total(
    spot: SessionSpot, reference: ReferenceLookup | None = None, zone: tzinfo | None = None
) -> dict[str | None, SpotBucket]:
    """One session's whole spot-priced energy (no period); with `reference` and `zone` also its day-average savings."""
    bucket = SpotBucket()
    for piece in spot.pieces:
        bucket.add_piece(spot, piece, 1.0)
        if reference is not None and zone is not None:
            for day, share in _day_shares(piece, zone):
                bucket.add_reference(spot, piece, day, share, reference)
    bucket.add_floating(spot, contained=True)
    return {_currency_key(spot): bucket}


def _num(value: float) -> float:
    return round(value + 0.0, 4)


def spot_block(
    buckets: dict[str | None, SpotBucket], *, allocation: str | None = None, rows_truncated: bool = False,
    savings: bool = False,
) -> dict[str, Any]:
    """The wire block `spot_cost` for one row or summary: the reporting currency is the most recent session's;
    energy in another or no currency is counted under `currency_exclusions`, never added and never dropped."""
    chosen = None
    latest = None
    for key, bucket in buckets.items():
        if key is not None and bucket.latest_start is not None and (latest is None or bucket.latest_start > latest):
            chosen, latest = key, bucket.latest_start
    main = buckets.get(chosen) if chosen is not None else None
    if main is None:
        main = SpotBucket()
    others = {key: bucket for key, bucket in buckets.items() if bucket is not main}
    exclusions = None
    if others:
        exclusions = {
            "kwh": _num(sum(b.total_kwh for b in others.values())),
            "sessions": len(set().union(*(b.sessions for b in others.values()))),
            "currencies": {key: _num(b.total_kwh) for key, b in sorted(others.items(), key=lambda i: str(i[0]))
                           if key is not None},
            "missing_currency_kwh": _num(others[None].total_kwh) if None in others else 0.0,
        }
    sessions = len(main.sessions.union(*(b.sessions for b in others.values())))
    reasons = set(main.flags)
    if main.unpriced_kwh > _TOLERANCE_KWH:
        reasons.add("unpriced_energy")
    if main.unallocated_kwh > _TOLERANCE_KWH:
        reasons.add("energy_without_placement_overlaps_period")
    if main.unplaced_kwh > _TOLERANCE_KWH or main.unplaced_ambiguous_kwh > _TOLERANCE_KWH:
        reasons.add("unplaced_late_energy_not_priced")
    if exclusions:
        reasons.add("currency_exclusions")
    if main.open_sessions:
        reasons.add("open_session")
    if rows_truncated:
        reasons.add("rows_truncated")
    has_cost = main.priced_kwh > _TOLERANCE_KWH
    if not sessions:
        state = "no_sessions_recorded"
    elif not has_cost:
        state = "none"
    else:
        state = "partial" if reasons else "complete"
    basis = SPOT_BASIS_UNKNOWN
    if has_cost:
        recorded, retained = main.recorded_kwh > _TOLERANCE_KWH, main.retained_kwh > _TOLERANCE_KWH
        basis = (SPOT_BASIS_MIXED if recorded and retained else SPOT_BASIS_RETAINED if retained
                 else SPOT_BASIS_RECORDED)
    known = main.total_kwh
    block: dict[str, Any] = {
        "amount": _num(main.cost) if has_cost else None,
        "currency": chosen,
        "unit": "major",
        "major_unit": main.major_unit,
        "basis": basis,
        "price_basis": SPOT_PRICE_BASIS,
        "price_source": None,
        "price_source_state": "not_recorded" if main.recorded_kwh > 0 else "unknown",
        "price_sources": sorted(main.price_sources),
        "priced_kwh": _num(main.priced_kwh),
        "unpriced_kwh": _num(main.unpriced_kwh),
        "unplaced_kwh": _num(main.unplaced_kwh),
        "unplaced_ambiguous_kwh": _num(main.unplaced_ambiguous_kwh),
        "unplaced_unknown_sessions": len(main.unplaced_unknown),
        "unallocated_kwh": _num(main.unallocated_kwh),
        "estimated_kwh": _num(main.estimated_kwh),
        "energy_sources": {key: _num(value) for key, value in sorted(main.by_source.items())},
        "sessions": sessions,
        "coverage": {
            "state": state,
            "complete": state == "complete",
            "partial": state == "partial",
            "priced_fraction": round(main.priced_kwh / known, 4) if known > _TOLERANCE_KWH else None,
            "reasons": sorted(reasons),
            "unpriced_reasons": {key: _num(value) for key, value in sorted(main.reasons.items())},
        },
        "currency_exclusions": exclusions,
    }
    if allocation is not None:
        block["allocation"] = allocation
    if savings:
        block["savings"] = _savings_block(main, chosen, state, exclusions)
    return block


def _savings_block(main: SpotBucket, currency: str | None, spot_state: str, exclusions: Any) -> dict[str, Any]:
    """Stage 8.3a: reference minus actual spot cost of the COMPARABLE subset only (the block's own actual cost, not
    `spot_cost.amount`, which stays the whole priced total). Percentage = savings / reference, only when the
    reference is positive; aggregates sum amounts first, so the percentage is never a mean of percentages."""
    has = main.comparable_kwh > _TOLERANCE_KWH
    amount = main.comparable_reference - main.comparable_actual
    excluded = main.excluded_kwh if main.excluded_kwh > _TOLERANCE_KWH else 0.0
    if spot_state == "no_sessions_recorded":
        state = spot_state
    elif not has:
        state = "none"
    else:
        state = "complete" if excluded == 0.0 and spot_state == "complete" else "partial"
    known = main.total_kwh
    days = sorted(main.excluded_days)
    return {
        "basis": SAVINGS_BASIS,
        "state": state,
        "estimate": True,
        "currency": currency,
        "unit": "major",
        "amount": _num(amount) if has else None,
        "percentage": round(amount / main.comparable_reference * 100, 2)
        if has and main.comparable_reference > 0 else None,
        "actual_cost": _num(main.comparable_actual) if has else None,
        "reference_cost": _num(main.comparable_reference) if has else None,
        "comparable_kwh": _num(main.comparable_kwh),
        "excluded_kwh": _num(excluded),
        "unpriced_kwh": _num(main.unpriced_kwh),
        "comparable_fraction": round(main.comparable_kwh / known, 4) if known > _TOLERANCE_KWH else None,
        "excluded_reasons": {key: _num(value) for key, value in sorted(main.excluded_reasons.items())},
        "excluded_days": days[:_MAX_EXCLUDED_DAYS],
        "excluded_days_count": len(days),
        "reference_days": len(main.reference_days),
        "reference_price_basis": "duration_weighted_full_local_day_raw_spot_no_fees_no_taxes",
        "reference_proof": SAVINGS_PROOF,
        "reference_sources": sorted(main.reference_sources),
        "reference_source_state": "unknown" if "unknown" in main.reference_sources else "held_provider_labels",
        "currency_exclusions": exclusions,
    }


def placed_days(allocation: SpotAllocation) -> list[date]:
    """The local days that hold placed energy, oldest first."""
    return sorted(allocation._days)


def session_spot_row(session: Any, zone: tzinfo | None = None) -> dict[str, Any]:
    """One session's `spot_cost` block; with `zone`, also the estimate of what each local delivery day received."""
    spot = session_spot(session)
    block = spot_block(spot_total(spot))
    if zone is not None:
        allocation = SpotAllocation([spot], zone)
        block["by_delivery_day"] = [
            {"day": day.isoformat(), "allocation": SPOT_ALLOCATION,
             **{key: value for key, value in spot_block(allocation.delivery_day(day)).items()
                if key in ("amount", "priced_kwh", "unpriced_kwh")}}
            for day in placed_days(allocation)
        ]
    return block
