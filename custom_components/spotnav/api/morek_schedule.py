"""Opt-in, manual Morek profile experiment through the existing HA OCPP connection.

This deliberately does not enable automatic execution: SpotNav's live controller must be
paused before a profile can be sent. The readback is an effective schedule, not an inventory
of installed profiles. OCPP's internal ChargePoint API is isolated here for easy replacement.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN
from ..runtime import domain_data, preview_for, controller_for
from .common import is_admin, lookup_charger, send_unsupported_version

API_VERSION = 1
PROFILE_ID = 42001
MOREK_STATION_ID = "3020002509120029"
MAX_PERIODS = 8
MAX_HORIZON = timedelta(hours=48)
VERIFY_TOLERANCE_S = 90
VERIFY_DELAYS = (30, 45, 45)  # Follow-up reads at approximately 30, 75 and 120 seconds.
_DATA_KEY = "spotnav_morek_schedule"
_VERIFY_KEY = "spotnav_morek_verification"
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
    result: dict[str, Any] = {"status": status, "fetched_at": _utc(now).isoformat(), "periods": [],
                              "schedule_start": None, "duration_s": None, "rate_unit": None}
    if status.lower() != "accepted" or schedule is None:
        return result
    # OCPP 1.6 GetCompositeSchedule puts scheduleStart on the *reply*, not inside
    # chargingSchedule (SetChargingProfile puts startSchedule inside the request).
    start_text = getattr(response, "schedule_start", None) or schedule.get("startSchedule", schedule.get("start_schedule"))
    unit = schedule.get("chargingRateUnit", schedule.get("charging_rate_unit"))
    raw = schedule.get("chargingSchedulePeriod", schedule.get("charging_schedule_period"))
    result["rate_unit"] = unit
    duration = schedule.get("duration")
    if type(duration) is int and duration > 0:
        result["duration_s"] = duration
    try:
        start = _utc(datetime.fromisoformat(start_text.replace("Z", "+00:00")))
        result["schedule_start"] = start.isoformat()
        if unit != "A" or not isinstance(raw, list):
            return result
        decoded = []
        previous_offset = -1
        for period in raw:
            offset = period.get("startPeriod", period.get("start_period"))
            limit = period["limit"]
            if (type(offset) is not int or offset < 0 or offset <= previous_offset
                    or isinstance(limit, bool) or not isinstance(limit, (int, float))
                    or not math.isfinite(limit) or limit < 0):
                return result
            previous_offset = offset
            decoded.append({"at": (start + timedelta(seconds=offset)).isoformat(), "amps": limit})
        if raw and raw[0].get("startPeriod", raw[0].get("start_period")) != 0:
            return result
        result["periods"] = decoded
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        result["periods"] = []
    return result


def matches(profile: dict[str, Any], actual: dict[str, Any], *, tolerance_s: int = VERIFY_TOLERANCE_S) -> bool:
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


def compare_schedule(profile: dict[str, Any] | None, actual: dict[str, Any] | None) -> dict[str, Any]:
    """A matching limit sequence is not verified without the station's reported coverage."""
    result: dict[str, Any] = {"matched": False, "exact": False, "reason": "no_sent_profile",
                              "tolerance_s": VERIFY_TOLERANCE_S, "max_delta_s": None,
                              "coverage_end": None}
    if profile is None:
        return result
    if not actual or actual.get("status", "").lower() != "accepted" or not actual.get("periods"):
        result["reason"] = "readback_unavailable"
        return result
    if not matches(profile, actual):
        result["reason"] = "limits_or_transitions_differ"
        return result
    start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
    expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"])
                for p in profile["chargingSchedule"]["chargingSchedulePeriod"]][1:]
    changes = []
    current = actual["periods"][0]["amps"]
    for period in actual["periods"][1:]:
        at = datetime.fromisoformat(period["at"])
        if at > expected[-1][0] + timedelta(hours=1):
            break
        if period["amps"] != current:
            changes.append((at, period["amps"]))
            current = period["amps"]
    delta = max(abs((at - want_at).total_seconds()) for (at, _), (want_at, _) in zip(changes, expected))
    result["max_delta_s"] = delta
    duration = actual.get("duration_s")
    if type(duration) is not int or duration <= 0 or not actual.get("schedule_start"):
        result["reason"] = "coverage_missing"
        return result
    coverage_end = datetime.fromisoformat(actual["schedule_start"]) + timedelta(seconds=duration)
    result["coverage_end"] = coverage_end.isoformat()
    if coverage_end < expected[-1][0] + timedelta(hours=1):
        result["reason"] = "coverage_too_short"
        return result
    result.update({"matched": True, "exact": delta < 1, "reason": "matched" if delta < 1 else "matched_with_drift"})
    return result


def _cancel_verification(hass: HomeAssistant, entry_id: str) -> None:
    cancel = hass.data.get(_VERIFY_KEY, {}).pop(entry_id, None)
    if cancel is not None:
        cancel()


def _schedule_verification(hass: HomeAssistant, entry_id: str, sent_at: str, attempt: int = 0) -> None:
    """Only retry readback, never Set/ClearChargingProfile. No indefinite polling."""
    _cancel_verification(hass, entry_id)

    async def check(_now: datetime) -> None:
        if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not cancel_handle:
            return
        try:
            await async_schedule_action(hass, entry_id, "fetch", expected_sent_at=sent_at,
                                        verification_attempt=attempt)
        except ScheduleRefused as error:
            # Unload, identity change, or a newer send/clear invalidates the old operation.
            if error.code != "morek_offline":
                if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is cancel_handle:
                    _cancel_verification(hass, entry_id)
                return
            data, store = await _state(hass, entry_id)
            async with hass.data[_DATA_KEY][entry_id][2]:
                if (hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not cancel_handle
                        or data.get("sent_at") != sent_at or data.get("cleanup") or data.get("verified")):
                    return
                data["verified"] = False
                data["effective"] = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(),
                                     "periods": []}
                verification = data.setdefault("verification", {})
                verification.update({"reason": "readback_unavailable", "attempts": attempt + 2,
                                     "checked_at": datetime.now(timezone.utc).isoformat(),
                                     "pending": False, "next_check_at": None})
                if attempt + 1 < len(VERIFY_DELAYS):
                    _schedule_verification(hass, entry_id, sent_at, attempt + 1)
                    verification.update({"pending": True, "next_check_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=VERIFY_DELAYS[attempt + 1])).isoformat()})
                else:
                    _cancel_verification(hass, entry_id)
                    _LOGGER.warning("Morek schedule still unverified after bounded readback checks: offline")
                await store.async_save(data)
        except Exception:
            if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is cancel_handle:
                _cancel_verification(hass, entry_id)
            _LOGGER.exception("Morek readback verification failed")

    cancel_handle = async_call_later(hass, VERIFY_DELAYS[attempt], check)
    hass.data.setdefault(_VERIFY_KEY, {})[entry_id] = cancel_handle


def _verification_state(hass: HomeAssistant, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Persisted pending state cannot claim a timer survived a Home Assistant restart."""
    verification = dict(data.get("verification") or {})
    if verification.get("pending") and entry_id not in hass.data.get(_VERIFY_KEY, {}):
        verification.update({"pending": False, "reason": "verification_interrupted", "next_check_at": None})
    return verification


def _matching_points(hass: HomeAssistant, target: Any) -> list[tuple[str, Any]]:
    """Resolve HA OCPP's configured charger alias to its physical WebSocket station ID."""
    found: list[tuple[str, Any]] = []
    for system in hass.data.get("ocpp", {}).values():
        points = getattr(system, "charge_points", None)
        cpids = getattr(system, "cpids", None)
        if not isinstance(points, dict) or not isinstance(cpids, dict):
            continue
        physical_id = cpids.get(target.devid, target.devid)
        point = points.get(physical_id)
        if point is not None:
            found.append((physical_id, point))
    return found


def _identity_status(hass: HomeAssistant, target: Any) -> dict[str, Any]:
    """Read-only diagnosis; an alias is valid only when HA OCPP maps it to this Morek."""
    if target is None:
        return {"supported": False, "reason": "no_ocpp_target", "configured_id": None,
                "resolved_id": None, "connector_id": None}
    found = _matching_points(hass, target)
    resolved = found[0][0] if len(found) == 1 else (target.devid if not found else None)
    reason = None
    if target.connector_id != 1:
        reason = "wrong_connector"
    elif len(found) > 1:
        reason = "ambiguous_station"
    elif resolved != MOREK_STATION_ID:
        reason = "station_not_matched"
    elif found and getattr(found[0][1], "_ocpp_version", None) != "1.6":
        reason = "unsupported_ocpp_version"
    return {"supported": reason is None, "reason": reason, "configured_id": target.devid,
            "resolved_id": resolved if found else None, "connector_id": target.connector_id}


def _charge_point(hass: HomeAssistant, target: Any) -> Any:
    """Use only the one connected OCPP 1.6 physical Morek charger."""
    found = _matching_points(hass, target)
    if len(found) != 1 or found[0][0] != MOREK_STATION_ID:
        raise ScheduleRefused("morek_offline")
    point = found[0][1]
    if getattr(point, "_ocpp_version", None) != "1.6" or getattr(point, "status", None) != "ok":
        raise ScheduleRefused("morek_offline")
    return point


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


def _proposed_profile(hass: HomeAssistant, entry_id: str, now: datetime) -> dict[str, Any]:
    """One calculation shared by the read-only preview and the actual send."""
    settings = domain_data(hass).auto_store.settings(entry_id)
    if settings.amps != 16:
        raise ScheduleRefused("current_must_be_16")
    planner = preview_for(hass, entry_id)
    snapshot = planner.snapshot() if planner is not None else None
    proposal = snapshot.proposal if snapshot is not None and snapshot.in_process else None
    if (proposal is None or snapshot.settings_revision != settings.revision
            or not proposal.has_plan or proposal.unpriced or not proposal.periods):
        raise ScheduleRefused("no_current_plan")
    if proposal.shown_periods != proposal.periods:
        raise ScheduleRefused("target_stop_unsupported")
    return profile_for(tuple(proposal.periods), settings.amps, now)


def _preview_id(profile: dict[str, Any], revision: Any) -> str:
    """Commit to the absolute ON/OFF transitions and settings revision, not the moving 0 A start."""
    schedule = profile["chargingSchedule"]
    start = datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00"))
    transitions = [(start + timedelta(seconds=period["startPeriod"])).isoformat() + f":{period['limit']}"
                   for period in schedule["chargingSchedulePeriod"][1:]]
    return hashlib.sha256(json.dumps([str(revision), transitions]).encode()).hexdigest()


def _preview(hass: HomeAssistant, entry_id: str, target: Any) -> dict[str, Any]:
    """Describe a proposal without contacting OCPP or changing stored charger state."""
    now = datetime.now(timezone.utc)
    profile = None
    reason = None
    preview_id = None
    try:
        profile = _proposed_profile(hass, entry_id, now)
        settings = domain_data(hass).auto_store.settings(entry_id)
        preview_id = _preview_id(profile, settings.revision)
        if settings.pause.choice != "until_resumed":
            reason = "pause_auto_first"
        elif not _identity_status(hass, target)["supported"]:
            reason = "not_morek_connector"
        else:
            try:
                _charge_point(hass, target)
            except ScheduleRefused as error:
                reason = error.code
    except ScheduleRefused as error:
        reason = error.code
    except Exception:
        # An unavailable planner must not prevent status from reporting charger identity/readback.
        profile = None
        preview_id = None
        reason = "preview_unavailable"
    return {"calculated_at": now.isoformat(), "profile": profile, "reason": reason,
            "preview_id": preview_id}


async def async_schedule_action(hass: HomeAssistant, entry_id: str, action: str,
                                preview_id: str | None = None, confirm_profile_id: int | None = None, *,
                                expected_sent_at: str | None = None,
                                verification_attempt: int | None = None) -> dict[str, Any]:
    if action not in ("send", "fetch", "clear"):
        raise ScheduleRefused("invalid_action")
    if action == "clear" and (type(confirm_profile_id) is not int or confirm_profile_id != PROFILE_ID):
        raise ScheduleRefused("cleanup_confirmation_required")
    if action == "send" and not preview_id:
        raise ScheduleRefused("preview_changed")
    entry, failure = lookup_charger(hass, entry_id)
    if failure is not None or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    controller = controller_for(hass, entry_id)
    target = getattr(controller, "ocpp_target", None)
    if not _identity_status(hass, target)["supported"]:
        raise ScheduleRefused("not_morek_connector")
    await _state(hass, entry_id)
    cache = hass.data[_DATA_KEY]
    data, store, lock = cache[entry_id]
    async with lock:
        if expected_sent_at is not None and (data.get("sent_at") != expected_sent_at or data.get("cleanup")
                                             or data.get("verified")):
            raise ScheduleRefused("verification_superseded")
        if not _identity_status(hass, target)["supported"]:
            raise ScheduleRefused("not_morek_connector")
        cp = _charge_point(hass, target)
        from ocpp.v16 import call as ocpp_call
        now = datetime.now(timezone.utc)
        if action == "send":
            settings = domain_data(hass).auto_store.settings(entry_id)
            if settings.pause.choice != "until_resumed":
                raise ScheduleRefused("pause_auto_first")
            profile = _proposed_profile(hass, entry_id, now)
            if preview_id is None or preview_id != _preview_id(profile, settings.revision):
                raise ScheduleRefused("preview_changed")
            _cancel_verification(hass, entry_id)
            # Record *before* the request: a timeout can still have installed a profile.
            data.update({"sent_at": now.isoformat(), "profile": profile, "ack": "unknown", "verified": False,
                          "effective": None, "cleanup": None,
                          "verification": {"pending": False, "reason": "upload_unconfirmed",
                                           "next_check_at": None, "attempts": 0}})
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
        elif action == "clear":
            _cancel_verification(hass, entry_id)
            # By OCPP 1.6, id alone selects this exact profile. Never send an empty
            # ClearChargingProfile request or use the generic HA clear service.
            data.update({"cleanup": {"requested_at": now.isoformat(), "profile_id": PROFILE_ID,
                                      "status": "unknown"}, "effective": None, "verified": False,
                         "verification": {"pending": False, "reason": "cleanup_requested",
                                          "next_check_at": None, "attempts": 0}})
            await store.async_save(data)
            try:
                response = await asyncio.wait_for(cp.call(ocpp_call.ClearChargingProfile(id=PROFILE_ID)), timeout=30)
                data["cleanup"]["status"] = _status(response)
            except Exception:
                # A timeout does not prove the station did not remove the profile.
                data["cleanup"]["status"] = "unknown"
            await store.async_save(data)
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
        except Exception:
            data["effective"] = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(), "periods": []}
            data["verified"] = False
        if expected_sent_at is not None and entry_id not in hass.data.get(_VERIFY_KEY, {}):
            raise ScheduleRefused("verification_superseded")
        comparison = compare_schedule(profile, data["effective"])
        if data.get("cleanup"):
            comparison.update({"matched": False, "exact": False, "reason": "cleanup_requested"})
        elif data.get("ack", "").lower() != "accepted":
            comparison.update({"matched": False, "exact": False, "reason": "upload_unconfirmed"})
        data["verified"] = comparison["matched"]
        verification = data.setdefault("verification", {})
        verification.update(comparison)
        verification["checked_at"] = datetime.now(timezone.utc).isoformat()
        if data["verified"] or action == "clear":
            _cancel_verification(hass, entry_id)
            verification.update({"pending": False, "next_check_at": None})
        elif action == "send" or verification_attempt is not None:
            next_attempt = 0 if action == "send" else verification_attempt + 1
            verification["attempts"] = 1 if action == "send" else verification_attempt + 2
            if next_attempt < len(VERIFY_DELAYS):
                _schedule_verification(hass, entry_id, data["sent_at"], next_attempt)
                if action == "send":
                    # Entry reload/unload invalidates timers. No hardware commands on unload.
                    entry.async_on_unload(lambda: _cancel_verification(hass, entry_id))
                verification.update({"pending": True, "next_check_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=VERIFY_DELAYS[next_attempt])).isoformat()})
            else:
                _cancel_verification(hass, entry_id)
                verification.update({"pending": False, "next_check_at": None})
                _LOGGER.warning("Morek schedule still unverified after bounded readback checks: %s", comparison["reason"])
        _LOGGER.info("Morek %s: upload=%s readback=%s verified=%s reason=%s",
                     action, data.get("ack"), data["effective"]["status"], data["verified"], comparison["reason"])
        await store.async_save(data)
        return {"supported": True, "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                "sent": profile, "effective": data.get("effective"), "cleanup": data.get("cleanup"),
                "cleanup_supported": True, "verification": _verification_state(hass, entry_id, data)}


@websocket_api.websocket_command({vol.Required("type"): "spotnav/morek_schedule", vol.Required("api_version"): int,
                                   vol.Required("charger_id"): str, vol.Required("action"): vol.In(("status", "send", "fetch", "clear")),
                                   vol.Optional("preview_id"): str, vol.Optional("confirm_profile_id"): int})
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
            result = {**_identity_status(hass, target),
                      "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                      "sent": data.get("profile"), "effective": data.get("effective"),
                      "preview": _preview(hass, entry.entry_id, target),
                      "cleanup": data.get("cleanup"), "cleanup_supported": True,
                      "verification": _verification_state(hass, entry.entry_id, data)}
        else:
            result = await async_schedule_action(hass, msg["charger_id"], msg["action"], msg.get("preview_id"),
                                                 msg.get("confirm_profile_id"))
            controller = controller_for(hass, msg["charger_id"])
            target = getattr(controller, "ocpp_target", None)
            result.update(_identity_status(hass, target))
            result["preview"] = _preview(hass, msg["charger_id"], target)
        connection.send_result(msg["id"], {"api_version": API_VERSION, "schedule": result})
    except ScheduleRefused as error:
        connection.send_error(msg["id"], f"spotnav_morek_{error.code}", error.code)
    except Exception:
        _LOGGER.exception("Morek schedule request failed")
        connection.send_error(msg["id"], "spotnav_morek_unavailable", "Morek schedule request failed")


@callback
def async_setup_morek_schedule_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_morek_schedule)
