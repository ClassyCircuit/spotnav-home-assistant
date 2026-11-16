"""`spotnav/get_price_days` (API v1): which price days the repository holds, and one bounded page of them.

Read-only and never a request: every answer is what `PriceRepository` already holds in memory (`held_days`,
`day_snapshot`, `archive_reachable`); nothing is fetched, refreshed, cached or written, and no file is scanned
(the repository keeps its day files in memory), so the handler runs on the event loop without blocking it.
Any signed-in user may read, as the dashboard. Prices are in the area's major currency unit per kWh, raw
published spot (before fiscal additions), exactly the dashboard's `published_intervals` row shape
(`api/dashboard.py:published_rows`); the card converts to its display unit once.

Request: `{api_version: 1, charger_id, mode: "available" | "range", from?, to?}`; `from`/`to` are display dates
(`YYYY-MM-DD`, inclusive) on the price area's own calendar (`area.tz`, which can differ from Home Assistant's zone).

* `available` -> `{api_version, charger_id, mode, area_id, zone, currency, today, yesterday_reachable,
  days: [{day, state, complete, resolution_minutes, source, fetched_at, interval_count}], oldest, newest}`:
  held display days, newest first, at most `MAX_AVAILABLE_DAYS` (400). A day not held is simply absent.
* `range` -> `{api_version, charger_id, mode, area_id, zone, currency, today, from, to, days: [...]}` with one row
  per requested date, oldest first, at most `MAX_RANGE_DAYS` (8) dates. A held day carries `held: true`, the same
  facts as above, `provenance` (the held market-day files it was cut from) and `intervals` (the rows); a day not
  held carries `held: false`, `intervals: null` and a `reason`: `not_held`, `outside_provider_reach` or
  `not_published` (tomorrow, not out yet). A held day whose rows overlap or are malformed is `intervals: null`
  with `reason: invalid_intervals`, never silently repaired; a held day with no usable exchange rate for the
  area's currency is `intervals: null` with `reason: no_price_rate`.

Refusals: `spotnav_unsupported_api_version`, the charger lookup's codes, `spotnav_no_price_area`,
`spotnav_unknown_price_area`, `spotnav_invalid_range` (mode, malformed or reversed dates, more than 8 days, a date
beyond tomorrow or before the repository keeps files). Nothing here writes.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Final

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .. import time_zones
from ..planning.planner import FiscalChoice, PlannerInputError, chart_intervals
from ..pricing.price_repository import HISTORY_KEEP_DAYS, PriceRepository
from ..pricing.price_source import effective_settings
from ..runtime import domain_data
from ..util import aware_iso
from .common import lookup_charger, send_unsupported_version
from .dashboard import published_rows
from .price_days import ERROR_NO_PRICE_AREA, ERROR_UNKNOWN_PRICE_AREA

PRICE_CALENDAR_API_VERSION: Final = 1
MAX_AVAILABLE_DAYS: Final = 400
MAX_RANGE_DAYS: Final = 8
ERROR_INVALID_RANGE: Final = "spotnav_invalid_range"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PriceCalendarRefusal(Exception):
    """A request the answer cannot honour; `code` is its stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _date_of(value: Any, name: str) -> date:
    if not isinstance(value, str) or not _DATE.match(value):
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, f"{name} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, f"{name} is not a calendar date") from err


def _resolution(snapshot: Any) -> int | None:
    """The one resolution the day's documents share, `None` when its parts disagree."""
    found = {piece.resolution_minutes for piece in snapshot.document.pieces()}
    return next(iter(found)) if len(found) == 1 else None


def _day_facts(snapshot: Any) -> dict[str, Any]:
    return {
        "day": snapshot.day.isoformat(),
        "state": snapshot.state,
        "complete": snapshot.is_complete,
        "resolution_minutes": _resolution(snapshot),
        "source": snapshot.source if isinstance(snapshot.source, str) else None,
        "fetched_at": aware_iso(snapshot.fetched_at),
        "interval_count": snapshot.interval_count,
    }


def _display_candidates(repository: PriceRepository, area_id: str) -> set[date]:
    """Display dates a held market-day file can belong to (the same date, or its neighbours when the calendars differ)."""
    calendars = repository.calendars(area_id)
    candidates: set[date] = set()
    for market_day in repository.held_days(area_id):
        for step in ((0,) if calendars is None else (-1, 0, 1)):
            candidates.add(market_day + timedelta(days=step))
    return candidates


def available_answer(repository: PriceRepository, area_id: str, today: date) -> dict[str, Any]:
    """Held display days, newest first (at most `MAX_AVAILABLE_DAYS`), from memory only."""
    rows = []
    for day in sorted(_display_candidates(repository, area_id), reverse=True):
        snapshot = repository.day_snapshot(area_id, day)
        if snapshot.document is None:
            continue
        rows.append(_day_facts(snapshot))
        if len(rows) >= MAX_AVAILABLE_DAYS:
            break
    return {
        "yesterday_reachable": repository.archive_reachable(area_id, today - timedelta(days=1)),
        "days": rows,
        "oldest": rows[-1]["day"] if rows else None,
        "newest": rows[0]["day"] if rows else None,
    }


def _missing_reason(repository: PriceRepository, area_id: str, day: date, today: date) -> str:
    if day > today:
        return "not_published"
    if day < today and not repository.archive_reachable(area_id, day):
        return "outside_provider_reach"
    return "not_held"


def range_answer(
    repository: PriceRepository, area_id: str, currency: str, today: date, first: date, last: date
) -> dict[str, Any]:
    """One row per requested display date, oldest first; rows are raw published spot, never regridded."""
    if first > last:
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, "from is after to")
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, f"at most {MAX_RANGE_DAYS} days per request")
    if last > today + timedelta(days=1) or first < today - timedelta(days=HISTORY_KEEP_DAYS):
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, "the range is outside the days prices are kept for")
    days = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        snapshot = repository.day_snapshot(area_id, day)
        if snapshot.document is None:
            days.append(
                {"day": day.isoformat(), "held": False, "state": snapshot.state, "complete": False,
                 "resolution_minutes": None, "source": None, "fetched_at": None, "interval_count": None,
                 "provenance": [], "reason": _missing_reason(repository, area_id, day, today), "intervals": None}
            )
            continue
        # The neutral fiscal choice: the row's `raw_price` is the published spot, which fiscal never touches. A day
        # whose own rate for the currency is unusable is held but cannot be priced: unknown, never a guessed rate.
        try:
            rows = published_rows(chart_intervals((snapshot.document,), currency=currency, fiscal=FiscalChoice()))
            reason = None if rows is not None else "invalid_intervals"
        except PlannerInputError:
            rows, reason = None, "no_price_rate"
        days.append(
            {
                **_day_facts(snapshot),
                "held": True,
                "provenance": [
                    {"market_day": file_day.isoformat(), "provider": provider if isinstance(provider, str) else None,
                     "fetched_at": aware_iso(fetched_at), "state": state}
                    for file_day, provider, fetched_at, state in snapshot.provenance
                ],
                "reason": reason,
                "intervals": rows,
            }
        )
    return {"from": first.isoformat(), "to": last.isoformat(), "days": days}


def price_days_answer(hass: HomeAssistant, charger_id: str, msg: dict[str, Any]) -> dict[str, Any]:
    """The answer for one charger's price area (WebSocket), or a `PriceCalendarRefusal`."""
    mode = msg.get("mode")
    if mode not in ("available", "range"):
        raise PriceCalendarRefusal(ERROR_INVALID_RANGE, "mode must be available or range")
    first = last = None
    if mode == "range":
        first, last = _date_of(msg.get("from"), "from"), _date_of(msg.get("to"), "to")
    store = domain_data(hass).auto_store
    repository: PriceRepository | None = domain_data(hass).price_repository
    if store is None or repository is None:
        raise PriceCalendarRefusal(ERROR_NO_PRICE_AREA, "No price area is set for this charger")
    area_id = effective_settings(hass, charger_id, store.settings(charger_id)).area_id
    if not area_id:
        raise PriceCalendarRefusal(ERROR_NO_PRICE_AREA, "No price area is set for this charger")
    area = repository.area_entry(area_id)
    zone = None if area is None else time_zones.zone(area.tz)
    if area is None or zone is None:
        raise PriceCalendarRefusal(ERROR_UNKNOWN_PRICE_AREA, "The price area is not known")
    today = dt_util.utcnow().astimezone(zone).date()
    head = {
        "api_version": PRICE_CALENDAR_API_VERSION,
        "charger_id": charger_id,
        "mode": mode,
        "area_id": area_id,
        "zone": area.tz,
        "currency": area.currency,
        "today": today.isoformat(),
    }
    if mode == "available":
        return {**head, **available_answer(repository, area_id, today)}
    return {**head, **range_answer(repository, area_id, area.currency, today, first, last)}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "spotnav/get_price_days",
        vol.Optional("api_version"): object,
        vol.Optional("charger_id"): object,
        vol.Optional("mode"): object,
        vol.Optional("from"): object,
        vol.Optional("to"): object,
    }
)
@callback
def websocket_get_price_days(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Held price days of the charger's area, or one bounded page of their rows."""
    version = msg.get("api_version")
    if type(version) is not int or version != PRICE_CALENDAR_API_VERSION:
        send_unsupported_version(connection, msg, PRICE_CALENDAR_API_VERSION)
        return
    charger, code = lookup_charger(hass, msg.get("charger_id"))
    if charger is None:
        connection.send_error(msg["id"], code, "The charger cannot be read")
        return
    try:
        answer = price_days_answer(hass, charger.entry_id, msg)
    except PriceCalendarRefusal as refusal:
        connection.send_error(msg["id"], refusal.code, refusal.message)
        return
    connection.send_result(msg["id"], answer)


@callback
def async_setup_price_calendar_api(hass: HomeAssistant) -> None:
    """Register the command once for the domain."""
    websocket_api.async_register_command(hass, websocket_get_price_days)
