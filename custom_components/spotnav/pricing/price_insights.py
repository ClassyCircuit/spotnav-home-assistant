"""Live price insights from published prices: the current interval against a trailing baseline, and the cheapest
contiguous window ahead (Stage 7.4a). Pure: no `hass`, no clock (`now` is an argument), no network, no store.

The caller (`api/price_insights.py`) reads held documents from memory and hands over plain rows, already in the
area's major currency unit per kWh, raw published spot (no fees, no tax, no exchange guess). Everything here is
by absolute instant and by duration, so 23/24/25-hour days and 15-minute/hourly mixes need no resampling and a
shorter interval never counts as an extra vote.

* **Baseline**: the trailing 30 completed local days of the price area. A day is *used* only when it is fully
  held: finite prices, no overlap or conflicting duplicate, rows covering the day's real elapsed span exactly.
  Anything else is excluded with a counted reason (`not_held`, `partial`, `invalid_prices`,
  `conflicting_duplicate`, `overlap`, `no_price_rate`). Fewer than 7 used days: the baseline is `unknown`.
  A past day is never "stale" because it is old: only incomplete or invalid data keeps it out.
* **Percentile** = (seconds strictly cheaper + half the seconds equal) / baseline seconds, as a percentage.
  It describes one interval or window mean against *interval* prices; it never classifies cheap or expensive.
* **Current**: the interval covering `now` in today's trusted rows; missing or untrusted data is `unknown`.
* **Cheapest window**: the contiguous published stretch of the requested length with the lowest duration-weighted
  mean, starting no earlier than `now` (the current interval counts only from now). The mean of a piecewise
  constant price is piecewise linear in the start, so the optimum starts at an interval boundary, or ends at one
  (start = boundary minus length), or sits at the clipped edges of the stretch; exactly those are tried, ties
  go to the earliest. A gap or the end of publication refuses a window. It does not need the baseline.

Monthly statistics (Stage 7.4b, `monthly_insights`): one local month of the price area, from the same day rules.
Only *fully held* days enter the price population; a partial day is counted and its coverage reported on its own,
never mixed in. Fewer than 7 such days: statistics are `unknown` with the coverage that exists. Quantiles are the
lower weighted quantile: the cheapest price whose cumulative time reaches q of the population time (deterministic,
an actual published price, no interpolation). "Negative share" is time strictly below zero. No resampling.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from itertools import accumulate
from typing import Any, Final

BASELINE_DAYS: Final = 30
MIN_BASELINE_DAYS: Final = 7
DEFAULT_WINDOW_MINUTES: Final = 60
MIN_WINDOW_MINUTES: Final = 15
MAX_WINDOW_MINUTES: Final = 720
WINDOW_STEP_MINUTES: Final = 15
#: Prices compare equal at this many decimals (the relay publishes five; conversion adds float noise).
_DECIMALS: Final = 9
_US: Final = timedelta(microseconds=1)
_UTC: Final = timezone.utc

#: Day states whose rows may feed the current interval and the future window. Old is not stale; a failed refresh is.
TRUSTED_STATES: Final = ("ready", "incomplete")

ASSUMPTIONS: Final = (
    "raw_published_spot_no_fees",
    "duration_weighted_by_instant",
    "no_resampling",
    "trailing_completed_local_days",
    "unknown_future_not_available",
    "window_mean_compared_with_interval_prices",
)


@dataclass(frozen=True, slots=True)
class PriceRow:
    """One published interval: absolute instants, price in major currency per kWh."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True, slots=True)
class DayInput:
    """One local day of the price area: its real span, and its rows (`None`: not held).

    `unusable` is the reason a held day cannot be priced (for example `no_price_rate`); `state` is the
    repository's day state, used only for the live days.
    """

    day: date
    span_start: datetime
    span_end: datetime
    rows: tuple[PriceRow, ...] | None
    unusable: str | None = None
    state: str | None = None
    resolution_minutes: int | None = None


def _us(moment: datetime) -> int:
    return (moment.astimezone(_UTC) - datetime(1970, 1, 1, tzinfo=_UTC)) // _US


def _iso(microseconds: int) -> str:
    return (datetime(1970, 1, 1, tzinfo=_UTC) + timedelta(microseconds=microseconds)).isoformat()


def _seconds(microseconds: int) -> float:
    return microseconds / 1_000_000


def _q(value: float) -> float:
    return round(value, _DECIMALS)


def clean_rows(rows: tuple[PriceRow, ...]) -> tuple[tuple[PriceRow, ...] | None, str | None]:
    """Sorted rows with identical duplicates dropped once, or `(None, reason)` for rows that cannot be trusted:
    `invalid_prices` (non-finite price, naive or non-positive interval), `conflicting_duplicate` (one start, two
    different intervals), `overlap`. Nothing is repaired or chosen."""
    parsed: list[tuple[int, int, float]] = []
    for row in rows:
        price = row.price
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or row.start.tzinfo is None
            or row.end.tzinfo is None
        ):
            return None, "invalid_prices"
        start, end = _us(row.start), _us(row.end)
        if end <= start:
            return None, "invalid_prices"
        parsed.append((start, end, _q(float(price))))
    parsed.sort()
    kept: list[tuple[int, int, float]] = []
    for item in parsed:
        if kept and item[0] == kept[-1][0]:
            if item == kept[-1]:
                continue
            return None, "conflicting_duplicate"
        if kept and item[0] < kept[-1][1]:
            return None, "overlap"
        kept.append(item)
    return tuple(
        PriceRow(
            datetime(1970, 1, 1, tzinfo=_UTC) + timedelta(microseconds=start),
            datetime(1970, 1, 1, tzinfo=_UTC) + timedelta(microseconds=end),
            price,
        )
        for start, end, price in kept
    ), None


def _full_day(day: DayInput) -> tuple[tuple[PriceRow, ...] | None, str | None]:
    """The day's clean rows when they cover its real span exactly, else `(None, reason)`."""
    if day.rows is None:
        return None, "not_held"
    if day.unusable:
        return None, day.unusable
    rows, reason = clean_rows(day.rows)
    if rows is None:
        return None, reason
    if (
        not rows
        or _us(rows[0].start) != _us(day.span_start)
        or _us(rows[-1].end) != _us(day.span_end)
        or any(_us(a.end) != _us(b.start) for a, b in zip(rows, rows[1:]))
    ):
        return None, "partial"
    return rows, None


@dataclass(frozen=True, slots=True)
class Baseline:
    """Duration-weighted prices of the used days, ready for percentile questions."""

    summary: dict[str, Any]
    prices: tuple[float, ...] = ()  # sorted
    cumulative: tuple[int, ...] = ()  # microseconds up to and including prices[i]

    @property
    def known(self) -> bool:
        return self.summary["status"] == "known"

    def percentile(self, price: float) -> dict[str, Any]:
        """Where one price sits in the baseline by time; `unknown` with the baseline's reason when it has none."""
        if not self.known:
            return {"status": "unknown", "unknown_reason": "baseline_unknown", "percentile": None}
        value = _q(price)
        total = self.cumulative[-1]
        below = self.cumulative[bisect_left(self.prices, value) - 1] if bisect_left(self.prices, value) else 0
        through = self.cumulative[bisect_right(self.prices, value) - 1] if bisect_right(self.prices, value) else 0
        equal = through - below
        return {
            "status": "known",
            "unknown_reason": None,
            "percentile": round(100 * (below + equal / 2) / total, 2),
            "cheaper_seconds": _seconds(below),
            "equal_seconds": _seconds(equal),
            "baseline_seconds": _seconds(total),
        }


def build_baseline(days: tuple[DayInput, ...], *, window_from: date, window_to: date) -> Baseline:
    """The trailing baseline over `days` (the completed local days the caller selected, oldest first)."""
    reasons: dict[str, int] = {}
    held = used = 0
    expected_us = used_us = 0
    resolutions: set[int] = set()
    weighted: list[tuple[float, int]] = []
    for day in days:
        expected_us += _us(day.span_end) - _us(day.span_start)
        held += day.rows is not None
        rows, reason = _full_day(day)
        if rows is None:
            reasons[reason or "invalid_prices"] = reasons.get(reason or "invalid_prices", 0) + 1
            continue
        used += 1
        for row in rows:
            length = _us(row.end) - _us(row.start)
            weighted.append((row.price, length))
            used_us += length
            resolutions.add(length // 60_000_000)
    known = used >= MIN_BASELINE_DAYS
    summary: dict[str, Any] = {
        "status": "known" if known else "unknown",
        "unknown_reason": None if known else "baseline_too_short",
        "window_from": window_from.isoformat(),
        "window_to": window_to.isoformat(),
        "days_expected": len(days),
        "days_held": held,
        "days_used": used,
        "days_excluded": {"count": len(days) - used, "reasons": dict(sorted(reasons.items()))},
        "minimum_days": MIN_BASELINE_DAYS,
        "seconds_expected": _seconds(expected_us),
        "seconds_used": _seconds(used_us),
        "resolution_minutes": sorted(resolutions),
    }
    if not known:
        return Baseline(summary)
    weighted.sort()
    return Baseline(
        summary,
        tuple(price for price, _ in weighted),
        tuple(accumulate(length for _, length in weighted)),
    )


def live_timeline(days: tuple[DayInput, ...]) -> tuple[tuple[PriceRow, ...], dict[str, str]]:
    """Trusted rows of today/tomorrow in instant order, plus `{day: reason}` for each day left out.

    A day is left out when it is not held, is not in a trusted state (`stale`, `invalid`: a failed refresh, never
    mere age), cannot be priced, or has untrustworthy rows. A day starting before the previous one ends is an
    `overlap` and is left out. Gaps stay gaps."""
    timeline: list[PriceRow] = []
    skipped: dict[str, str] = {}
    for day in days:
        if day.rows is None:
            skipped[day.day.isoformat()] = "not_held"
            continue
        if day.unusable:
            skipped[day.day.isoformat()] = day.unusable
            continue
        if day.state not in TRUSTED_STATES:
            skipped[day.day.isoformat()] = f"day_{day.state or 'untrusted'}"
            continue
        rows, reason = clean_rows(day.rows)
        if rows is None:
            skipped[day.day.isoformat()] = reason or "invalid_prices"
        elif timeline and rows and _us(rows[0].start) < _us(timeline[-1].end):
            skipped[day.day.isoformat()] = "overlap"
        else:
            timeline.extend(rows)
    return tuple(timeline), skipped


def _current(timeline: tuple[PriceRow, ...], skipped: dict[str, str], now: datetime, today: str, baseline: Baseline) -> dict:
    moment = _us(now)
    for row in timeline:
        if _us(row.start) <= moment < _us(row.end):
            return {
                "status": "known",
                "unknown_reason": None,
                "interval": {
                    "start": row.start.isoformat(),
                    "end": row.end.isoformat(),
                    "duration_seconds": _seconds(_us(row.end) - _us(row.start)),
                    "price": row.price,
                    "elapsed_seconds": _seconds(moment - _us(row.start)),
                },
                "comparison": baseline.percentile(row.price),
            }
    reason = skipped.get(today) or "no_current_interval"
    return {"status": "unknown", "unknown_reason": reason, "interval": None,
            "comparison": {"status": "unknown", "unknown_reason": reason, "percentile": None}}


def _best_in_run(run: list[tuple[int, int, float]], length: int) -> tuple[Fraction, int, int] | None:
    """The lowest-cost, earliest window of `length` microseconds inside one contiguous run, or `None`."""
    run_start, run_end = run[0][0], run[-1][1]
    if run_end - run_start < length:
        return None
    starts = [row[0] for row in run]
    ends = [row[1] for row in run]
    prefix = [Fraction(0), *accumulate(Fraction(price) * (end - start) for start, end, price in run)]

    def integral(at: int) -> Fraction:
        index = bisect_right(starts, at) - 1
        if index < 0:
            return Fraction(0)
        if at >= ends[index]:
            return prefix[index + 1]
        return prefix[index] + Fraction(run[index][2]) * (at - starts[index])

    candidates = {run_start, run_end - length}
    for edge in (*starts, *ends):
        candidates.update((edge, edge - length))
    best: tuple[Fraction, int, int] | None = None
    for begin in sorted(c for c in candidates if run_start <= c <= run_end - length):
        cost = integral(begin + length) - integral(begin)
        if best is None or cost < best[0]:
            best = (cost, begin, begin + length)
    return best


def cheapest_window(timeline: tuple[PriceRow, ...], now: datetime, minutes: int, baseline: Baseline) -> dict[str, Any]:
    """The cheapest contiguous published window of `minutes` starting at or after `now`; see the module note."""
    length = minutes * 60_000_000
    base = {"duration_minutes": minutes, "start": None, "end": None, "mean_price": None,
            "comparison": {"status": "unknown", "unknown_reason": "no_window", "percentile": None}}
    moment = _us(now)
    # Rows from now, the current one clipped at now, split into contiguous runs.
    runs: list[list[tuple[int, int, float]]] = []
    for row in timeline:
        start, end = max(_us(row.start), moment), _us(row.end)
        if end <= start:
            continue
        if runs and runs[-1][-1][1] == start:
            runs[-1].append((start, end, row.price))
        else:
            runs.append([(start, end, row.price)])
    if not runs:
        return {**base, "status": "unknown", "unknown_reason": "no_future_prices", "horizon": None}
    horizon = {"from": _iso(runs[0][0][0]), "until": _iso(runs[-1][-1][1]), "runs": len(runs)}
    best: tuple[Fraction, int, int] | None = None  # (cost, start, end); lowest cost, earliest on ties
    for run in runs:
        found = _best_in_run(run, length)
        if found is not None and (best is None or found[0] < best[0]):
            best = found
    if best is None:
        return {**base, "status": "unknown", "unknown_reason": "no_contiguous_window", "horizon": horizon}
    mean = float(best[0] / length)
    return {
        **base,
        "status": "known",
        "unknown_reason": None,
        "start": _iso(best[1]),
        "end": _iso(best[2]),
        "mean_price": mean,
        "comparison": baseline.percentile(mean),
        "horizon": horizon,
    }


def live_insights(
    *,
    now: datetime,
    today: str,
    window_minutes: int,
    baseline_days: tuple[DayInput, ...],
    live_days: tuple[DayInput, ...],
    window_from: date,
    window_to: date,
) -> dict[str, Any]:
    """The pure answer: baseline, current interval and cheapest window, each with its own unknown reason."""
    if now.tzinfo is None:
        raise ValueError("live_insights needs an aware instant")
    baseline = build_baseline(baseline_days, window_from=window_from, window_to=window_to)
    timeline, skipped = live_timeline(live_days)
    current = _current(timeline, skipped, now, today, baseline)
    window = cheapest_window(timeline, now, window_minutes, baseline)
    if window["status"] == "unknown" and window["unknown_reason"] == "no_future_prices" and skipped:
        window["unknown_reason"] = next(iter(skipped.values()))
    live_resolutions = sorted({(_us(row.end) - _us(row.start)) // 60_000_000 for row in timeline})
    return {
        "baseline": baseline.summary,
        "current": current,
        "cheapest_window": window,
        "live_days_skipped": skipped,
        "resolution_minutes": {"baseline": baseline.summary["resolution_minutes"], "live": live_resolutions},
        "assumptions": list(ASSUMPTIONS),
        "unknown_reason": None
        if current["status"] == "known" or window["status"] == "known"
        else current["unknown_reason"],
    }


MONTHLY_ASSUMPTIONS: Final = (
    "raw_published_spot_no_fees",
    "duration_weighted_by_instant",
    "no_resampling",
    "completed_local_days_only",
    "only_fully_held_days_in_population",
    "partial_days_reported_not_averaged",
    "lower_weighted_quantile",
    "negative_share_is_time_strictly_below_zero",
)
QUANTILES: Final = (("p10", 10), ("p50", 50), ("p90", 90))


def _covered_us(rows: tuple[PriceRow, ...] | None, span_start: datetime, span_end: datetime) -> int:
    """Microseconds of a day's clean rows inside the day's span (an unclean day covers nothing we may state)."""
    clean, _reason = clean_rows(rows or ())
    if not clean:
        return 0
    low, high = _us(span_start), _us(span_end)
    return sum(max(0, min(_us(row.end), high) - max(_us(row.start), low)) for row in clean)


def weighted_quantile(prices: tuple[float, ...], cumulative: tuple[int, ...], percent: int) -> float:
    """Lower weighted quantile of ascending `prices` with running `cumulative` time: the first price whose
    cumulative time reaches `percent` % of the total."""
    threshold = -(-percent * cumulative[-1] // 100)
    return prices[bisect_left(cumulative, threshold)]


def monthly_insights(
    *, month: str, days: tuple[DayInput, ...], days_in_month: int, calendar_complete: bool
) -> dict[str, Any]:
    """Statistics of the `days` the caller selected for `month` (all of its days, or its completed days only).

    `days` are distinct local days of the price area, oldest first, possibly none (the month's first day is
    today). Pure: the caller decides which days are expected and states `calendar_complete`."""
    keys = [item.day for item in days]
    if len(set(keys)) != len(keys):
        raise ValueError("monthly_insights needs distinct days")
    reasons: dict[str, int] = {}
    held = complete = partial = 0
    expected_us = valid_us = partial_us = 0
    resolutions: set[int] = set()
    weighted: list[tuple[float, int]] = []
    for day in days:
        expected_us += _us(day.span_end) - _us(day.span_start)
        held += day.rows is not None
        rows, reason = _full_day(day)
        if rows is None:
            reason = reason or "invalid_prices"
            reasons[reason] = reasons.get(reason, 0) + 1
            if reason == "partial":
                partial += 1
                partial_us += _covered_us(day.rows, day.span_start, day.span_end)
            continue
        complete += 1
        for row in rows:
            length = _us(row.end) - _us(row.start)
            weighted.append((row.price, length))
            valid_us += length
            resolutions.add(length // 60_000_000)
    known = complete >= MIN_BASELINE_DAYS and valid_us > 0
    statistics: dict[str, Any] | None = None
    if known:
        weighted.sort()
        prices = tuple(price for price, _ in weighted)
        cumulative = tuple(accumulate(length for _, length in weighted))
        negative = sum(length for price, length in weighted if price < 0)
        statistics = {
            "mean": _q(math.fsum(price * length for price, length in weighted) / valid_us),
            "min": prices[0],
            "max": prices[-1],
            **{name: weighted_quantile(prices, cumulative, percent) for name, percent in QUANTILES},
            "negative_seconds": _seconds(negative),
            "negative_share": round(100 * negative / valid_us, 4),
            "population_seconds": _seconds(valid_us),
        }
    return {
        "month": month,
        "scope": "complete_calendar_month" if calendar_complete else "completed_days_to_date",
        "calendar_complete": calendar_complete,
        "as_of_day": days[-1].day.isoformat() if days else None,
        "days_in_month": days_in_month,
        "days_expected": len(days),
        "days_held": held,
        "days_complete": complete,
        "days_partial": partial,
        "days_excluded": {"count": len(days) - complete, "reasons": dict(sorted(reasons.items()))},
        "minimum_days": MIN_BASELINE_DAYS,
        "coverage": {
            "seconds_expected": _seconds(expected_us),
            "seconds_valid": _seconds(valid_us),
            "seconds_partial": _seconds(partial_us),
            "valid_ratio": round(valid_us / expected_us, 6) if expected_us else None,
        },
        "status": "known" if known else "unknown",
        "unknown_reason": None
        if known
        else ("no_completed_days" if not days else "too_few_complete_days"),
        "statistics": statistics,
        "resolution_minutes": sorted(resolutions),
        # Offered for the UI's month-to-month rule: the month itself meets the minimum. Comparing needs the
        # other month's answer too, with the same currency and basis (carried by every answer).
        "comparable": {"meets_minimum": known, "minimum_days": MIN_BASELINE_DAYS, "days_complete": complete},
        "assumptions": list(MONTHLY_ASSUMPTIONS),
    }
