"""Opt-in, manual Morek profile experiment through the existing HA OCPP connection.

This deliberately does not enable automatic execution: SpotNav's live controller must be
paused before a profile can be sent. The readback is an effective schedule, not an inventory
of installed profiles. OCPP's internal ChargePoint API is isolated here for easy replacement.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from ..runtime import domain_data, preview_for, controller_for
from .common import is_admin, lookup_charger, send_unsupported_version

API_VERSION = 1
PROFILE_ID = 42001
MOREK_STATION_ID = "3020002509120029"
MAX_PERIODS = 8
MAX_HORIZON = timedelta(hours=48)
_DATA_KEY = "spotnav_morek_schedule"
_LOGGER = logging.getLogger(__name__)


class ScheduleRefused(Exception):
    def __init__(self, code: str):
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ScheduleRefused("invalid_plan")
    return value.astimezone(timezone.utc)


def profile_for(periods: tuple[tuple[datetime, datetime], ...], amps: int, now: datetime) -> dict[str, Any]:
    """One future-only, paused-before/after TxDefaultProfile; never discard a block."""
    requested_at = _utc(now)
    now = requested_at.replace(microsecond=0)
    if not isinstance(amps, int) or isinstance(amps, bool) or not 6 <= amps <= 16:
        raise ScheduleRefused("invalid_current")
    if not periods or len(periods) > 3:
        raise ScheduleRefused("too_many_blocks")
    transitions: list[dict[str, int]] = [{"startPeriod": 0, "limit": 0}]
    previous_end = now
    for start, end in periods:
        start, end = _utc(start), _utc(end)
        if start <= requested_at or start <= previous_end or end <= start or end - now > MAX_HORIZON:
            raise ScheduleRefused("invalid_plan")
        transitions.extend((
            {"startPeriod": int((start - now).total_seconds()), "limit": amps},
            {"startPeriod": int((end - now).total_seconds()), "limit": 0},
        ))
        previous_end = end
    if len(transitions) > MAX_PERIODS or len({p["startPeriod"] for p in transitions}) != len(transitions):
        raise ScheduleRefused("invalid_plan")
    return {
        "chargingProfileId": PROFILE_ID,
        "stackLevel": 1,
        "chargingProfilePurpose": "TxDefaultProfile",
        "chargingProfileKind": "Absolute",
        "chargingSchedule": {
            "startSchedule": now.isoformat().replace("+00:00", "Z"),
            "chargingRateUnit": "A",
            "chargingSchedulePeriod": [dict(period, numberPhases=3) for period in transitions],
        },
    }


def _schedule(response: Any) -> dict[str, Any] | None:
    schedule = getattr(response, "charging_schedule", None)
    return schedule if isinstance(schedule, dict) else None


def _status(response: Any) -> str:
    value = getattr(response, "status", "Unknown")
    return str(getattr(value, "value", value))


def readback(response: Any, now: datetime) -> dict[str, Any]:
    """Decode an OCPP composite answer into absolute UTC current changes."""
    status = _status(response)
    schedule = _schedule(response)
    result: dict[str, Any] = {"status": status, "fetched_at": _utc(now).isoformat(), "periods": []}
    if status.lower() != "accepted" or schedule is None:
        return result
    # OCPP 1.6 GetCompositeSchedule puts scheduleStart on the *reply*, not inside
    # chargingSchedule (SetChargingProfile puts startSchedule inside the request).
    start_text = getattr(response, "schedule_start", None) or schedule.get("startSchedule", schedule.get("start_schedule"))
    unit = schedule.get("chargingRateUnit", schedule.get("charging_rate_unit"))
    raw = schedule.get("chargingSchedulePeriod", schedule.get("charging_schedule_period"))
    try:
        start = _utc(datetime.fromisoformat(start_text.replace("Z", "+00:00")))
        if unit != "A" or not isinstance(raw, list):
            return result
        for period in raw:
            offset = period.get("startPeriod", period.get("start_period"))
            limit = period["limit"]
            if isinstance(offset, bool) or not isinstance(offset, int) or not isinstance(limit, (int, float)):
                return result
            result["periods"].append({"at": (start + timedelta(seconds=offset)).isoformat(), "amps": limit})
        result["periods"].sort(key=lambda item: item["at"])
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        result["periods"] = []
    return result


def matches(profile: dict[str, Any], actual: dict[str, Any], *, tolerance_s: int = 90) -> bool:
    """Compare *effective* changes, including a pause after the last window."""
    if actual["status"].lower() != "accepted" or not actual["periods"]:
        return False
    start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
    expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"])
                for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]
    observed = [(datetime.fromisoformat(p["at"]), p["amps"]) for p in actual["periods"]]
    # Composite schedules may start at the readback instant, within a long 0 A span.
    first = observed[0]
    # A composite response starts at the query time. After a charging window
    # has started we cannot reconstruct its earlier effective limits from it.
    if first[0] > expected[1][0] or first[1] != 0:
        return False
    # GetCompositeSchedule can repeat an identical limit without changing the
    # effective current. Ignore such repeats, not a real extra ON/OFF window.
    changes = []
    current = first[1]
    for at, amps in observed[1:]:
        if at > expected[-1][0] + timedelta(hours=1):
            break
        if amps != current:
            changes.append((at, amps))
            current = amps
    wanted = expected[1:]
    return len(changes) == len(wanted) and all(
        amps == want_amps and abs((at - want_at).total_seconds()) <= tolerance_s
        for (at, amps), (want_at, want_amps) in zip(changes, wanted)
    )


def _charge_point(hass: HomeAssistant, target: Any) -> Any:
    """Use only the one connected OCPP 1.6 charger resolved by SpotNav's connector identity."""
    found = []
    for system in hass.data.get("ocpp", {}).values():
        points = getattr(system, "charge_points", None)
        cpids = getattr(system, "cpids", None)
        if not isinstance(points, dict) or not isinstance(cpids, dict):
            continue
        point = points.get(cpids.get(target.devid, target.devid))
        if point is not None:
            found.append(point)
    if len(found) != 1 or getattr(found[0], "_ocpp_version", None) != "1.6" or getattr(found[0], "status", None) != "ok":
        raise ScheduleRefused("morek_offline")
    return found[0]


async def _state(hass: HomeAssistant, entry_id: str) -> tuple[dict[str, Any], Store]:
    cache = hass.data.setdefault(_DATA_KEY, {})
    data, store, lock = cache.setdefault(
        entry_id, (None, Store(hass, 1, f"{DOMAIN}.morek_schedule.{entry_id}"), asyncio.Lock())
    )
    if data is None:
        async with lock:
            data, store, _ = cache[entry_id]
            if data is None:
                saved = await store.async_load()
                data = saved if isinstance(saved, dict) else {}
                cache[entry_id] = (data, store, lock)
    return data, store


async def async_schedule_action(hass: HomeAssistant, entry_id: str, action: str) -> dict[str, Any]:
    entry, failure = lookup_charger(hass, entry_id)
    if failure is not None or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    controller = controller_for(hass, entry_id)
    target = getattr(controller, "ocpp_target", None)
    if target is None or target.connector_id != 1 or target.charge_point_id != MOREK_STATION_ID:
        raise ScheduleRefused("not_morek_connector")
    await _state(hass, entry_id)
    cache = hass.data[_DATA_KEY]
    data, store, lock = cache[entry_id]
    async with lock:
        cp = _charge_point(hass, target)
        from ocpp.v16 import call as ocpp_call
        now = datetime.now(timezone.utc)
        if action == "send":
            settings = domain_data(hass).auto_store.settings(entry_id)
            if settings.pause.choice != "until_resumed":
                raise ScheduleRefused("pause_auto_first")
            if settings.amps != 16:
                raise ScheduleRefused("current_must_be_16")
            planner = preview_for(hass, entry_id)
            snapshot = planner.snapshot() if planner is not None else None
            proposal = snapshot.proposal if snapshot is not None and snapshot.in_process else None
            if (proposal is None or snapshot.settings_revision != settings.revision
                    or not proposal.has_plan or proposal.unpriced or not proposal.periods):
                raise ScheduleRefused("no_current_plan")
            # Auto normally stops the last whole slot when the energy need is met.
            # A charger profile cannot infer that target; refuse rather than silently
            # charge for longer than the plan the card shows.
            if proposal.shown_periods != proposal.periods:
                raise ScheduleRefused("target_stop_unsupported")
            profile = profile_for(tuple(proposal.periods), settings.amps, now)
            # Record *before* the request: a timeout can still have installed a profile.
            data.update({"sent_at": now.isoformat(), "profile": profile, "ack": "unknown", "verified": False,
                         "effective": None})
            await store.async_save(data)
            try:
                response = await asyncio.wait_for(cp.call(ocpp_call.SetChargingProfile(
                    connector_id=target.connector_id, cs_charging_profiles=profile)), timeout=30)
                data["ack"] = _status(response)
            except Exception:
                data["ack"] = "unknown"
            await store.async_save(data)
            if data["ack"].lower() != "accepted":
                raise ScheduleRefused("upload_not_confirmed")
        elif action != "fetch":
            raise ScheduleRefused("invalid_action")
        query_at = datetime.now(timezone.utc)
        duration = 43200
        profile = data.get("profile")
        if isinstance(profile, dict):
            end = profile["chargingSchedule"]["chargingSchedulePeriod"][-1]["startPeriod"]
            start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
            duration = max(duration, min(172800, int((start + timedelta(seconds=end + 3600) - query_at).total_seconds())))
        try:
            response = await asyncio.wait_for(cp.call(ocpp_call.GetCompositeSchedule(
                connector_id=target.connector_id, duration=duration, charging_rate_unit="A")), timeout=30)
            data["effective"] = readback(response, datetime.now(timezone.utc))
            if getattr(response, "connector_id", target.connector_id) != target.connector_id:
                data["effective"]["status"] = "wrong_connector"
            data["verified"] = False
            if isinstance(profile, dict) and data.get("ack", "").lower() == "accepted" and matches(profile, data["effective"]):
                schedule = _schedule(response)
                reported_duration = schedule.get("duration") if schedule else None
                coverage = reported_duration if isinstance(reported_duration, int) and reported_duration > 0 else duration
                coverage_start = datetime.fromisoformat(data["effective"]["periods"][0]["at"])
                data["verified"] = coverage_start + timedelta(seconds=coverage) >= start + timedelta(seconds=end + 3600)
        except Exception:
            data["effective"] = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(), "periods": []}
            data["verified"] = False
        await store.async_save(data)
        return {"supported": True, "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                "sent": profile, "effective": data.get("effective")}


@websocket_api.websocket_command({vol.Required("type"): "spotnav/morek_schedule", vol.Required("api_version"): int,
                                   vol.Required("charger_id"): str, vol.Required("action"): vol.In(("status", "send", "fetch"))})
@websocket_api.async_response
async def websocket_morek_schedule(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if msg["api_version"] != API_VERSION:
        send_unsupported_version(connection, msg, API_VERSION)
        return
    if msg["action"] != "status" and not is_admin(connection):
        connection.send_error(msg["id"], "spotnav_not_admin", "Administrator required")
        return
    try:
        if msg["action"] == "status":
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            data, _ = await _state(hass, entry.entry_id)
            controller = controller_for(hass, entry.entry_id)
            target = getattr(controller, "ocpp_target", None)
            result = {"supported": target is not None and target.connector_id == 1
                      and target.charge_point_id == MOREK_STATION_ID,
                      "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                      "sent": data.get("profile"), "effective": data.get("effective")}
        else:
            result = await async_schedule_action(hass, msg["charger_id"], msg["action"])
        connection.send_result(msg["id"], {"api_version": API_VERSION, "schedule": result})
    except ScheduleRefused as error:
        connection.send_error(msg["id"], f"spotnav_morek_{error.code}", error.code)
    except Exception:
        _LOGGER.exception("Morek schedule request failed")
        connection.send_error(msg["id"], "spotnav_morek_unavailable", "Morek schedule request failed")


@callback
def async_setup_morek_schedule_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_morek_schedule)
