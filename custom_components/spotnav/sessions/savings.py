"""Stage 8.3a: the day-average reference price of a local delivery day, from prices already held in memory.

`DayAverageReference` is the live `ReferenceLookup` of `sessions/costing.py`. For a session's price area and a Home
Assistant local calendar day it reads `PriceRepository.day_snapshot` (memory only: it never fetches, refreshes or
falls back to another day) for every display day the local day touches, makes the rows with the 7.4a `clean_rows`
rule, and accepts the day only when they cover the whole local span (23/24/25 hours) contiguously. The answer is the
duration-weighted raw spot average in the session's currency (no fees or taxes); anything else is a counted reason,
never an average of a cheap subset. The stored `Slice.day_avg_eur` is deliberately not used: it was computed by the
old path and proves neither a full day nor the local calendar.

Recorded slices never stored their provider, so the reference's source is the held files' own provider labels
(`unknown` when a file carries none); a retained price with a named source must be among them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from .. import time_zones
from ..planning.planner import document_rate, PlannerInputError
from ..pricing.price_insights import clean_rows, PriceRow
from ..pricing.price_repository import PriceRepository
from .costing import day_bounds, ReferenceResult, SessionSpot

_ONE_US = timedelta(microseconds=1)


def full_day_average(rows: tuple[PriceRow, ...], start: datetime, end: datetime) -> tuple[float | None, str | None]:
    """The duration-weighted mean price over `start..end` of clean `rows`, or `(None, reason)` when they do not
    cover that span exactly once, contiguously (rows outside the span are ignored)."""
    inside = [row for row in rows if row.start < end and row.end > start]
    if (
        not inside
        or inside[0].start > start
        or inside[-1].end < end
        or any(a.end != b.start for a, b in zip(inside, inside[1:]))
    ):
        return None, "reference_day_partial"
    weighted = total = 0.0
    for row in inside:
        seconds = (min(row.end, end) - max(row.start, start)).total_seconds()
        weighted += row.price * seconds
        total += seconds
    return (weighted / total, None) if total > 0 else (None, "reference_day_partial")


class DayAverageReference:
    """The reference price per (price area, currency, local day), memoised for the life of one request."""

    def __init__(self, repository: PriceRepository | None, zone: tzinfo) -> None:
        self._repository = repository
        self._zone = zone
        self._cache: dict[tuple[str, str, date], ReferenceResult] = {}

    def __call__(self, spot: SessionSpot, day: date) -> ReferenceResult:
        if not spot.area_id:
            return ReferenceResult(None, "reference_area_unknown")
        if not spot.currency:
            return ReferenceResult(None, "reference_currency_unknown")
        key = (spot.area_id, spot.currency.upper(), day)
        if key not in self._cache:
            self._cache[key] = self._resolve(spot.area_id, spot.currency, day)
        return self._cache[key]

    def _resolve(self, area_id: str, currency: str, day: date) -> ReferenceResult:
        repository = self._repository
        if repository is None:
            return ReferenceResult(None, "reference_prices_unavailable")
        area = repository.area_entry(area_id)
        area_zone = None if area is None else time_zones.zone(area.tz)
        if area is None or area_zone is None:
            return ReferenceResult(None, "reference_area_unknown")
        if area.currency.upper() != currency.upper():
            return ReferenceResult(None, "reference_currency_mismatch")
        start, end = day_bounds(day, self._zone)
        first = start.astimezone(area_zone).date()
        last = (end - _ONE_US).astimezone(area_zone).date()
        rows: list[PriceRow] = []
        labels: set[str] = set()
        current = first
        while current <= last:
            snapshot = repository.day_snapshot(area_id, current)
            if snapshot.document is None:
                return ReferenceResult(None, "reference_day_not_held")
            try:
                for piece in snapshot.document.pieces():
                    rate = document_rate(piece, currency)
                    rows.extend(PriceRow(item.utc_start, item.utc_end, item.eur_per_kwh * rate)
                                for item in piece.intervals)
            except PlannerInputError:
                return ReferenceResult(None, "reference_price_rate_missing")
            labels.update(provider if isinstance(provider, str) and provider else "unknown"
                          for _day, provider, _fetched, _state in snapshot.provenance)
            current += timedelta(days=1)
        cleaned, why = clean_rows(tuple(rows))
        if cleaned is None:
            return ReferenceResult(None, f"reference_day_{why}")
        price, why = full_day_average(cleaned, start, end)
        if price is None:
            return ReferenceResult(None, why)
        return ReferenceResult(price, None, tuple(sorted(labels)) or ("unknown",))
