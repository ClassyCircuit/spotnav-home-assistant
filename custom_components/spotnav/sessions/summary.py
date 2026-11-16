"""Sessions summed per local day and per local month, and written as CSV.

A session counts on the local day (and month) it **started**, in Home Assistant's time zone, so a
charge that runs past midnight is one row, not two halves, and a DST night needs no special case:
the zone converts an absolute instant to a date, nothing here adds hours.

Costs are summed only for sessions in the bucket's currency (the most recent session's), so a person
who changed market never sees two currencies added together. The savings are the same priced energy at
the day's average effective price minus what it cost: an estimate, and always labelled one.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
import calendar
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Final

from .costing import (
    day_bounds,
    SPOT_ALLOCATION,
    SPOT_PRICE_BASIS,
    session_spot,
    SpotAllocation,
    spot_block,
)
from .model import ChargeSession

SAVINGS_BASIS: Final = "day_average_price"

CSV_COLUMNS: Final = (
    "start", "end", "energy_kwh", "energy_source", "estimated", "cost", "currency",
    "average_price_minor_per_kwh", "started_by", "strategy", "vehicle", "solar_share",
    "reference_cost", "savings",
)


def local_day(session: ChargeSession, zone: tzinfo) -> date:
    return session.start.astimezone(zone).date()


def summarize_bucket(period: str, sessions: Sequence[ChargeSession]) -> dict[str, Any]:
    """One bucket: totals over these sessions (any order, closed ones)."""
    ordered = sorted(sessions, key=lambda item: item.start)
    currency = next((item.currency for item in reversed(ordered) if item.currency is not None), None)
    energy = float(sum(item.energy_kwh for item in ordered))
    priced = [item for item in ordered if item.currency == currency and item.cost_minor is not None]
    priced_kwh = sum(item.priced_kwh for item in priced)
    cost_minor = sum(item.cost_minor or 0.0 for item in priced)
    reference_minor = sum(item.reference_cost_minor or 0.0 for item in priced)
    solar_kwh = sum(item.solar_kwh for item in ordered)
    solar_known = sum(item.solar_known_kwh for item in ordered)
    has_cost = bool(priced)
    last = ordered[-1] if ordered else None
    return {
        "period": period,
        "sessions": len(ordered),
        "energy_kwh": round(energy, 3),
        "cost": round(cost_minor / 100, 4) if has_cost else None,
        "currency": currency,
        "major_unit": None if last is None else last.major_unit,
        "minor_unit": None if last is None else last.minor_unit,
        "average_price_minor_per_kwh": round(cost_minor / priced_kwh, 3) if has_cost and priced_kwh > 0 else None,
        "solar_share": round(min(1.0, solar_kwh / solar_known), 3) if solar_known > 0 else None,
        "reference_cost": round(reference_minor / 100, 4) if has_cost else None,
        "savings": round((reference_minor - cost_minor) / 100, 4) if has_cost else None,
        "savings_basis": SAVINGS_BASIS,
        "savings_estimate": True,
        "estimated": any(item.estimated for item in ordered),
    }


def cost_figures(session: ChargeSession | None) -> dict[str, Any]:
    """A costed session's cost in the major unit, its currency, its average price per kWh (major unit) and
    the energy that had no published price. Cost, currency and average are `None` when nothing was priced
    (never zero); everything is `None` without a session."""
    if session is None:
        return {"cost": None, "currency": None, "average_price": None, "unpriced_kwh": None}
    cost = session.cost_minor
    average = session.average_price_minor_per_kwh
    if cost is None or average is None:
        return {"cost": None, "currency": None, "average_price": None, "unpriced_kwh": round(session.energy_kwh, 3)}
    return {
        "cost": round(cost / 100, 4),
        "currency": session.currency,
        "average_price": round(average / 100, 4),
        "unpriced_kwh": round(max(session.energy_kwh - session.priced_kwh, 0.0), 3),
    }


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def previous_month(day: date) -> str:
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return f"{year:04d}-{month:02d}"


def summarize(sessions: Iterable[ChargeSession], zone: tzinfo, *, by: str) -> list[dict[str, Any]]:
    """Every day (`by="day"`) or month (`by="month"`) that has a session, newest first."""
    buckets: dict[str, list[ChargeSession]] = {}
    for session in sessions:
        if session.end is None:
            continue
        day = local_day(session, zone)
        key = day.isoformat() if by == "day" else month_key(day)
        buckets.setdefault(key, []).append(session)
    return [summarize_bucket(key, buckets[key]) for key in sorted(buckets, reverse=True)]


def month_summary(sessions: Iterable[ChargeSession], zone: tzinfo, key: str) -> dict[str, Any]:
    """The month `key` (`YYYY-MM`), all zeros when nothing was charged in it."""
    members = [
        session
        for session in sessions
        if session.end is not None and month_key(local_day(session, zone)) == key
    ]
    return summarize_bucket(key, members)


def month_bounds(key: str) -> tuple[date, date]:
    """The first and last local day of the month `key` (`YYYY-MM`, already validated)."""
    year, month = int(key[:4]), int(key[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_sessions(sessions: Iterable[ChargeSession], zone: tzinfo, key: str) -> list[ChargeSession]:
    """The closed sessions that started in the month `key`, newest first."""
    members = [
        session
        for session in sessions
        if session.end is not None and month_key(local_day(session, zone)) == key
    ]
    return sorted(members, key=lambda item: item.start, reverse=True)


def month_days(sessions: Iterable[ChargeSession], zone: tzinfo, key: str) -> list[dict[str, Any]]:
    """One bucket for every day of the month `key`, oldest first, a day with no session as a zero row,
    so a chart has every day."""
    by_day: dict[date, list[ChargeSession]] = {}
    for session in month_sessions(sessions, zone, key):
        by_day.setdefault(local_day(session, zone), []).append(session)
    first, last = month_bounds(key)
    return [
        summarize_bucket(day.isoformat(), by_day.get(day, []))
        for day in (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    ]


def available_months(sessions: Iterable[ChargeSession], zone: tzinfo) -> list[str]:
    """The months that have a closed session, newest first."""
    return sorted({month_key(local_day(s, zone)) for s in sessions if s.end is not None}, reverse=True)


def sessions_summary(sessions: Sequence[ChargeSession], zone: tzinfo, now: datetime) -> dict[str, Any]:
    """The dashboard's additive `sessions_summary` block: this month and last month."""
    today = now.astimezone(zone).date()
    return {
        "this_month": month_summary(sessions, zone, month_key(today)),
        "last_month": month_summary(sessions, zone, previous_month(today)),
    }


def _safe(value: str) -> str:
    """A text cell a spreadsheet will not run as a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def sessions_csv(
    sessions: Iterable[ChargeSession], zone: tzinfo, *, first: date | None, last: date | None
) -> str:
    """The closed sessions that started on a local day in `first..last` (either end open), one row
    each, oldest first. Instants are local time with their offset."""
    rows = sorted(
        (
            session
            for session in sessions
            if session.end is not None
            and (first is None or local_day(session, zone) >= first)
            and (last is None or local_day(session, zone) <= last)
        ),
        key=lambda item: item.start,
    )
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for session in rows:
        record = session.public()
        cells: list[Any] = []
        for column in CSV_COLUMNS:
            if column == "start":
                cells.append(session.start.astimezone(zone).isoformat())
            elif column == "end":
                cells.append("" if session.end is None else session.end.astimezone(zone).isoformat())
            else:
                value = record[column]
                cells.append("" if value is None else _safe(value) if isinstance(value, str) else value)
        writer.writerow(cells)
    return out.getvalue()


# ---- Stage 8.2a: delivery-day accounting (spot-only) --------------------------------------------------------------
#
# A *delivery day* is the Home Assistant local calendar day in which a price interval's energy was delivered. The
# fields above group a whole session on the day it started; these group the energy it placed, by actual elapsed time
# (23/25-hour days included), and are a different thing: never show one as the other. A month is the sum of its
# delivery days. All of it is `SpotAllocation`, the same code `get_charging_history` uses for its window.

DELIVERY_ACCOUNTING: Final = {
    "day": "home_assistant_local_calendar_day",
    "allocation": SPOT_ALLOCATION,
    "price_basis": SPOT_PRICE_BASIS,
    "month": "sum_of_delivery_days",
    "legacy_fields": "this_month, last_month, months, days, month_summary, month_days and sessions group a whole "
                     "session on the local day it started and carry the person's fiscal cost; they are not delivery days",
}


def delivery_allocation(sessions: Iterable[ChargeSession], zone: tzinfo, windows: Sequence[tuple[datetime, datetime]]) -> SpotAllocation:
    """The allocation of the closed sessions that touch any of `windows` (so a read prices only what it shows)."""
    spots = [
        spot
        for spot in (session_spot(item) for item in sessions if item.end is not None)
        if any(spot.start < until and spot.end is not None and spot.end > since for since, until in windows)
    ]
    return SpotAllocation(spots, zone)


def delivery_day_row(allocation: SpotAllocation, day: date) -> dict[str, Any]:
    return {
        "period": day.isoformat(),
        "kind": "delivery_day",
        "spot_cost": spot_block(allocation.delivery_day(day), allocation=SPOT_ALLOCATION),
    }


def delivery_days(allocation: SpotAllocation, first: date, last: date) -> list[dict[str, Any]]:
    """The local days `first..last` that hold any session activity, newest first."""
    days = sorted((d for d in allocation.days_touched() if first <= d <= last), reverse=True)
    return [delivery_day_row(allocation, day) for day in days]


def delivery_month_rows(allocation: SpotAllocation, key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The month `key`'s delivery summary and one delivery row for every day of it (a day with nothing recorded says
    `no_sessions_recorded`, not zero)."""
    first, last = month_bounds(key)
    summary = {
        "period": key,
        "kind": "delivery_month",
        "spot_cost": spot_block(allocation.delivery_month(first, last), allocation=SPOT_ALLOCATION),
    }
    days = [
        delivery_day_row(allocation, first + timedelta(days=offset)) for offset in range((last - first).days + 1)
    ]
    return summary, days


def delivery_windows(today: date, zone: tzinfo, key: str, days_back: int) -> list[tuple[datetime, datetime]]:
    """The two UTC windows a sessions read shows: the last `days_back` local days and the chosen month."""
    first, last = month_bounds(key)
    return [
        (day_bounds(today - timedelta(days=days_back - 1), zone)[0], day_bounds(today, zone)[1]),
        (day_bounds(first, zone)[0], day_bounds(last, zone)[1]),
    ]
