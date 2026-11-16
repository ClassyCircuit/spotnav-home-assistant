"""`spotnav/get_price_insights` (API v1, mode `live`): the current price against the trailing baseline, and the
cheapest contiguous window ahead. Stage 7.4a; mode `monthly` is 7.4b's, on this same command.

Read-only and never a request: the answer is computed from what `PriceRepository` already holds in memory
(`day_snapshot`, at most 30 baseline days and today/tomorrow); nothing is fetched, refreshed, backfilled, stored or
written, and no setting, plan, charger or provider is touched. Any signed-in user may read, as the dashboard.
The method is `pricing/price_insights.py`; this module only gathers rows and states the contract.

Request: `{api_version: 1, charger_id, mode: "live", duration_minutes?}`; `duration_minutes` is 15..720 in steps of
15 (default 60), a number of whole minutes (not a boolean or a string).

Prices are the raw published spot in the area's major currency unit per kWh (`basis`), converted with the day's own
usable rate exactly as the dashboard's rows are (`planning.planner.document_rate`); no fee, tax or invented rate. A
day with no usable rate is excluded and counted, never converted. Days are the price area's own calendar (`zone`);
times are UTC instants with the same instants in the area's zone beside them (`*_local`). A held past day is trusted
for its content, not its age; a stale or invalid *current* day is not.

Refusals: `spotnav_unsupported_api_version`, the charger lookup's codes, `spotnav_invalid_insight_request` (mode or
duration), `spotnav_no_price_area`, `spotnav_unknown_price_area`.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Final

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .. import time_zones
from ..planning.planner import PlannerInputError, document_rate
from ..pricing.market_day import display_day_span
from ..pricing.price_insights import (
    BASELINE_DAYS,
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
    MIN_WINDOW_MINUTES,
    WINDOW_STEP_MINUTES,
    DayInput,
    PriceRow,
    live_insights,
)
from ..pricing.price_repository import DaySnapshot, PriceRepository
from ..pricing.price_source import effective_settings
from ..runtime import domain_data
from ..util import aware_iso
from .common import lookup_charger, send_unsupported_version
from .price_days import ERROR_NO_PRICE_AREA, ERROR_UNKNOWN_PRICE_AREA

PRICE_INSIGHTS_API_VERSION: Final = 1
ERROR_INVALID_INSIGHT_REQUEST: Final = "spotnav_invalid_insight_request"


class PriceInsightsRefusal(Exception):
    """A request the answer cannot honour; `code` is its stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _day_input(repository: PriceRepository, area_id: str, tz: str, currency: str, day: date) -> DayInput:
    snapshot = repository.day_snapshot(area_id, day)
    start, end = display_day_span(day, tz)
    if snapshot.document is None:
        return DayInput(day, start, end, None, state=snapshot.state)
    resolutions = {piece.resolution_minutes for piece in snapshot.document.pieces()}
    resolution = next(iter(resolutions)) if len(resolutions) == 1 else None
    try:
        rows = tuple(
            PriceRow(item.utc_start, item.utc_end, item.eur_per_kwh * document_rate(piece, currency))
            for piece in snapshot.document.pieces()
            for item in piece.intervals
        )
    except PlannerInputError:
        return DayInput(day, start, end, (), unusable="no_price_rate", state=snapshot.state,
                        resolution_minutes=resolution)
    return DayInput(day, start, end, rows, state=snapshot.state, resolution_minutes=resolution)


def _providers(snapshots: list[DaySnapshot]) -> list[dict[str, Any]]:
    """How many held market-day files each actual provider supplied (labels as the files carry them)."""
    counts = Counter(
        provider if isinstance(provider, str) else None
        for snapshot in snapshots
        for _day, provider, _fetched, _state in snapshot.provenance
    )
    return [{"provider": provider, "files": count} for provider, count in sorted(counts.items(), key=str)]


def _with_local(value: dict[str, Any] | None, zone: Any, *keys: str) -> None:
    if value is None:
        return
    for key in keys:
        moment = value.get(key)
        if isinstance(moment, str):
            value[f"{key}_local"] = datetime.fromisoformat(moment).astimezone(zone).isoformat()


def insights_answer(
    repository: PriceRepository, area_id: str, tz: str, currency: str, now: datetime, minutes: int
) -> dict[str, Any]:
    """The live answer for one price area at `now` (UTC-aware), computed from memory only."""
    zone = time_zones.require_zone(tz)
    today = now.astimezone(zone).date()
    first = today - timedelta(days=BASELINE_DAYS)
    baseline_days = tuple(
        _day_input(repository, area_id, tz, currency, first + timedelta(days=offset)) for offset in range(BASELINE_DAYS)
    )
    live_dates = (today, today + timedelta(days=1))
    live_days = tuple(_day_input(repository, area_id, tz, currency, day) for day in live_dates)
    answer = live_insights(
        now=now,
        today=today.isoformat(),
        window_minutes=minutes,
        baseline_days=baseline_days,
        live_days=live_days,
        window_from=first,
        window_to=today - timedelta(days=1),
    )
    _with_local(answer["current"]["interval"], zone, "start", "end")
    _with_local(answer["cheapest_window"], zone, "start", "end")
    _with_local(answer["cheapest_window"]["horizon"], zone, "from", "until")
    held = [repository.day_snapshot(area_id, day.day) for day in baseline_days if day.rows is not None]
    live = [repository.day_snapshot(area_id, day) for day in live_dates]
    return {
        **answer,
        "basis": {"kind": "published_spot", "unit": "major_per_kwh", "currency": currency, "fees": "none"},
        "currency": currency,
        "zone": tz,
        "now": now.isoformat(),
        "now_local": now.astimezone(zone).isoformat(),
        "today": today.isoformat(),
        "window_minutes": minutes,
        "provenance": {
            "baseline_providers": _providers(held),
            "live": [
                {"day": snapshot.day.isoformat(), "state": snapshot.state, "source": snapshot.source,
                 "fetched_at": aware_iso(snapshot.fetched_at), "providers": _providers([snapshot])}
                for snapshot in live
                if snapshot.document is not None
            ],
        },
    }


def _minutes_of(msg: dict[str, Any]) -> int:
    minutes = msg.get("duration_minutes", DEFAULT_WINDOW_MINUTES)
    if (
        type(minutes) is not int
        or not MIN_WINDOW_MINUTES <= minutes <= MAX_WINDOW_MINUTES
        or minutes % WINDOW_STEP_MINUTES
    ):
        raise PriceInsightsRefusal(
            ERROR_INVALID_INSIGHT_REQUEST,
            f"duration_minutes must be {MIN_WINDOW_MINUTES}..{MAX_WINDOW_MINUTES} in steps of {WINDOW_STEP_MINUTES}",
        )
    return minutes


def price_insights_answer(hass: HomeAssistant, charger_id: str, msg: dict[str, Any]) -> dict[str, Any]:
    """The answer for one charger's price area (WebSocket), or a `PriceInsightsRefusal`."""
    if msg.get("mode") != "live":
        raise PriceInsightsRefusal(ERROR_INVALID_INSIGHT_REQUEST, "mode must be live")
    minutes = _minutes_of(msg)
    store = domain_data(hass).auto_store
    repository: PriceRepository | None = domain_data(hass).price_repository
    if store is None or repository is None:
        raise PriceInsightsRefusal(ERROR_NO_PRICE_AREA, "No price area is set for this charger")
    area_id = effective_settings(hass, charger_id, store.settings(charger_id)).area_id
    if not area_id:
        raise PriceInsightsRefusal(ERROR_NO_PRICE_AREA, "No price area is set for this charger")
    area = repository.area_entry(area_id)
    if area is None or time_zones.zone(area.tz) is None:
        raise PriceInsightsRefusal(ERROR_UNKNOWN_PRICE_AREA, "The price area is not known")
    answer = insights_answer(repository, area_id, area.tz, area.currency, dt_util.utcnow(), minutes)
    return {
        "api_version": PRICE_INSIGHTS_API_VERSION,
        "charger_id": charger_id,
        "mode": "live",
        "area_id": area_id,
        **answer,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "spotnav/get_price_insights",
        vol.Optional("api_version"): object,
        vol.Optional("charger_id"): object,
        vol.Optional("mode"): object,
        vol.Optional("duration_minutes"): object,
    }
)
@callback
def websocket_get_price_insights(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Live price insights of the charger's area; read-only, from held prices."""
    version = msg.get("api_version")
    if type(version) is not int or version != PRICE_INSIGHTS_API_VERSION:
        send_unsupported_version(connection, msg, PRICE_INSIGHTS_API_VERSION)
        return
    charger, code = lookup_charger(hass, msg.get("charger_id"))
    if charger is None:
        connection.send_error(msg["id"], code, "The charger cannot be read")
        return
    try:
        answer = price_insights_answer(hass, charger.entry_id, msg)
    except PriceInsightsRefusal as refusal:
        connection.send_error(msg["id"], refusal.code, refusal.message)
        return
    connection.send_result(msg["id"], answer)


@callback
def async_setup_price_insights_api(hass: HomeAssistant) -> None:
    """Register the command once for the domain."""
    websocket_api.async_register_command(hass, websocket_get_price_insights)
