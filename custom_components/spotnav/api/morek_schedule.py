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
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, MOREK_CONNECTOR_ID, MOREK_STATION_ID
from ..execution.execution_ownership import ownership_store
from ..execution.command_admission import command_admission
from ..execution.morek_outcomes import OutcomeUnavailable, outcomes_for
from ..runtime import domain_data, preview_for, controller_for
from .common import is_admin, lookup_charger, send_unsupported_version

API_VERSION = 1
PROFILE_ID = 42001
MAX_PERIODS = 8
MAX_HORIZON = timedelta(hours=48)
VERIFY_TOLERANCE_S = 90
VERIFY_DELAYS = (30, 45, 45)  # Follow-up reads at approximately 30, 75 and 120 seconds.
_DATA_KEY = "spotnav_morek_schedule"
_VERIFY_KEY = "spotnav_morek_verification"
_LIFECYCLE_KEY = "spotnav_morek_verification_lifecycle"
_LOGGER = logging.getLogger(__name__)


class ScheduleRefused(Exception):
    def __init__(self, code: str):
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ScheduleRefused("invalid_plan")
    return value.astimezone(timezone.utc)


def profile_for(periods: tuple[tuple[datetime, datetime], ...], amps: int, now: datetime, *,
                allow_active: bool = False) -> dict[str, Any]:
    """Build fixed-time limits, optionally continuing an active displayed window."""
    requested_at = _utc(now)
    now = requested_at.replace(microsecond=0)
    if allow_active and requested_at.microsecond:
        now += timedelta(seconds=1)
    if not isinstance(amps, int) or isinstance(amps, bool) or not 6 <= amps <= 16:
        raise ScheduleRefused("invalid_current")
    if not periods:
        raise ScheduleRefused("no_current_plan")
    # Validate the entire original plan before discarding elapsed windows.
    normalized = []
    previous_end = None
    try:
        for start, end in periods:
            start, end = _utc(start), _utc(end)
            if end <= start or (previous_end is not None and start <= previous_end):
                raise ScheduleRefused("invalid_plan")
            normalized.append((start, end))
            previous_end = end
    except (TypeError, ValueError, AttributeError):
        raise ScheduleRefused("invalid_plan") from None
    if allow_active:
        normalized = [(start, end) for start, end in normalized if end > requested_at]
        if not normalized:
            raise ScheduleRefused("plan_expired")
    if len(normalized) > 3:
        raise ScheduleRefused("too_many_blocks")
    active = allow_active and normalized[0][0] <= requested_at
    transitions: list[dict[str, int]] = [{"startPeriod": 0, "limit": amps if active else 0}]
    for index, (start, end) in enumerate(normalized):
        if (not (active and index == 0) and start <= requested_at) or end - now > MAX_HORIZON:
            raise ScheduleRefused("invalid_plan")
        # OCPP offsets are whole seconds: never start before or end after a displayed window.
        start_offset = math.ceil((start - now).total_seconds())
        end_offset = math.floor((end - now).total_seconds())
        if end_offset <= (0 if active and index == 0 else start_offset):
            raise ScheduleRefused("invalid_plan")
        if not (active and index == 0):
            transitions.append({"startPeriod": start_offset, "limit": amps})
        transitions.append({"startPeriod": end_offset, "limit": 0})
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


def readback(response: Any, now: datetime, *, requested_at: datetime | None = None) -> dict[str, Any]:
    """Decode an OCPP composite answer into absolute UTC current changes."""
    status = _status(response)
    schedule = _schedule(response)
    result: dict[str, Any] = {"status": status, "fetched_at": _utc(now).isoformat(),
                              "requested_at": _utc(requested_at or now).isoformat(), "periods": [],
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
    """Compare observable limits without asserting reported coverage."""
    return _compare_remaining(profile, actual, tolerance_s=tolerance_s, require_coverage=False)["matched"]


def _compare_remaining(profile: dict[str, Any] | None, actual: dict[str, Any] | None, *,
                       tolerance_s: int, require_coverage: bool) -> dict[str, Any]:
    """Compare only the remaining observed interval, never a historical session."""
    result: dict[str, Any] = {"matched": False, "exact": False, "reason": "no_sent_profile",
                              "tolerance_s": tolerance_s, "max_delta_s": None,
                              "coverage_start": None, "coverage_end": None, "scope": "remaining"}
    if profile is None:
        return result
    if not actual or actual.get("status", "").lower() != "accepted" or not actual.get("periods"):
        result["reason"] = "readback_unavailable"
        return result
    try:
        schedule = profile["chargingSchedule"]
        start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"])
                    for p in schedule["chargingSchedulePeriod"]]
        observed = [(_utc(datetime.fromisoformat(p["at"])), p["amps"]) for p in actual["periods"]]
        coverage_start = _utc(datetime.fromisoformat(actual["schedule_start"]))
        fetched = _utc(datetime.fromisoformat(actual["fetched_at"]))
        requested = _utc(datetime.fromisoformat(actual["requested_at"]))
        if (fetched < requested or coverage_start < requested - timedelta(seconds=tolerance_s)
                or coverage_start > fetched + timedelta(seconds=tolerance_s)):
            result["reason"] = "coverage_stale"
            return result
        if len(expected) < 2 or observed[0][0] != coverage_start:
            raise ValueError
        if any(a[0] >= b[0] for a, b in zip(observed, observed[1:])):
            raise ValueError
        duration = actual.get("duration_s")
        if type(duration) is not int or duration <= 0:
            if require_coverage:
                result["reason"] = "coverage_missing"
                return result
            coverage_end = expected[-1][0] + timedelta(hours=1)
        else:
            coverage_end = coverage_start + timedelta(seconds=duration)
        boundary = max(coverage_start, fetched, start)
        result.update({"coverage_start": boundary.isoformat(), "coverage_end": coverage_end.isoformat()})
        if coverage_end <= boundary:
            result["reason"] = "coverage_stale"
            return result
        horizon = expected[-1][0] + timedelta(hours=1)
        if coverage_end < horizon:
            result["reason"] = "coverage_too_short"
            return result
        wanted = [(at, amps) for at, amps in expected[1:] if at > boundary]
        if not wanted:
            result["reason"] = "no_remaining_transitions"
            return result
        if any(abs((at - boundary).total_seconds()) <= tolerance_s for at, _ in expected[1:]):
            result["reason"] = "coverage_boundary_ambiguous"
            return result
        expected_limit = next(amps for at, amps in reversed(expected) if at <= boundary)
        current = next(amps for at, amps in reversed(observed) if at <= boundary)
        if current != expected_limit:
            result["reason"] = "limits_or_transitions_differ"
            return result
        changes = []
        for at, amps in observed:
            if at <= boundary:
                continue
            if at > horizon:
                break
            if amps != current:
                changes.append((at, amps))
                current = amps
        if len(changes) != len(wanted):
            result["reason"] = "limits_or_transitions_differ"
            return result
        delta = max(abs((at - want_at).total_seconds()) for (at, _), (want_at, _) in zip(changes, wanted))
        result["max_delta_s"] = delta
        if delta > tolerance_s or any(amps != want_amps for (_, amps), (_, want_amps) in zip(changes, wanted)):
            result["reason"] = "limits_or_transitions_differ"
            return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, StopIteration, ScheduleRefused):
        result["reason"] = "readback_unavailable"
        return result
    result.update({"matched": True, "exact": delta < 1, "reason": "matched" if delta < 1 else "matched_with_drift"})
    return result


def compare_schedule(profile: dict[str, Any] | None, actual: dict[str, Any] | None) -> dict[str, Any]:
    """A match requires reported coverage through one hour beyond the last stop."""
    return _compare_remaining(profile, actual, tolerance_s=VERIFY_TOLERANCE_S, require_coverage=True)


def _cancel_verification(hass: HomeAssistant, entry_id: str) -> None:
    cancel = hass.data.get(_VERIFY_KEY, {}).pop(entry_id, None)
    if cancel is not None:
        cancel()


def _verification_lifecycle(hass: HomeAssistant, entry_id: str, entry: Any) -> dict[str, Any]:
    """One unload token per entry instance, shared by immediate and delayed reads."""
    lifecycles = hass.data.setdefault(_LIFECYCLE_KEY, {})
    token = lifecycles.get(entry_id)
    if token is not None and token["entry"] is entry:
        return token
    token = {"entry": entry, "live": True}
    lifecycles[entry_id] = token
    def unload() -> None:
        token["live"] = False
        if lifecycles.get(entry_id) is token:
            _cancel_verification(hass, entry_id)
            lifecycles.pop(entry_id, None)
    entry.async_on_unload(unload)
    return token


def _schedule_verification(hass: HomeAssistant, entry_id: str, sent_at: str, attempt: int = 0,
                           attempt_id: str | None = None) -> None:
    """Only retry readback, never Set/ClearChargingProfile. No indefinite polling."""
    _cancel_verification(hass, entry_id)

    async def check(_now: datetime) -> None:
        if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not cancel_handle:
            return
        try:
            await async_schedule_action(hass, entry_id, "fetch", expected_sent_at=sent_at,
                                        verification_attempt=attempt, expected_attempt_id=attempt_id,
                                        verification_handle=cancel_handle)
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
                    _schedule_verification(hass, entry_id, sent_at, attempt + 1, attempt_id)
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

    cancel_handle = async_call_later(hass, 0 if attempt < 0 else VERIFY_DELAYS[attempt], check)
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
                "resolved_id": None, "connector_id": None, "match_count": 0, "ocpp_version": None}
    found = _matching_points(hass, target)
    resolved = found[0][0] if len(found) == 1 else (target.devid if not found else None)
    reason = None
    if len(found) > 1:
        reason = "ambiguous_station"
    elif target.connector_id != MOREK_CONNECTOR_ID:
        reason = "wrong_connector"
    elif resolved != MOREK_STATION_ID:
        reason = "station_not_matched"
    elif found and getattr(found[0][1], "_ocpp_version", None) != "1.6":
        reason = "unsupported_ocpp_version"
    return {"supported": reason is None, "reason": reason, "configured_id": target.devid,
            "resolved_id": resolved if len(found) == 1 else None, "connector_id": target.connector_id,
            "match_count": len(found), "ocpp_version": getattr(found[0][1], "_ocpp_version", None)
            if len(found) == 1 else None}


def _charge_point(hass: HomeAssistant, target: Any) -> Any:
    """Use only the one connected OCPP 1.6 physical Morek charger."""
    found = _matching_points(hass, target)
    if len(found) != 1 or found[0][0] != MOREK_STATION_ID:
        raise ScheduleRefused("morek_offline")
    point = found[0][1]
    if getattr(point, "_ocpp_version", None) != "1.6" or getattr(point, "status", None) != "ok":
        raise ScheduleRefused("morek_offline")
    return point


def _session_readiness(hass: HomeAssistant, controller: Any, identity: dict[str, Any], online: bool,
                       now: datetime) -> dict[str, Any]:
    """Read connector observations only; no inference of authorization or physical flow.

    HA state timestamps are conservative evidence of freshness, not a heartbeat: an
    unchanged state may age out even while the charger is connected.
    """
    result: dict[str, Any] = {
        "control": "unknown", "vehicle": "unknown", "transaction": "unknown",
        "measurement": "unknown", "vehicle_observed_at": None,
        "activation_blockers": ["production_dispatch_unarmed", "transaction_authorization_unverified"],
    }
    if not identity.get("supported") or identity.get("match_count") != 1:
        if identity.get("supported") and identity.get("match_count") == 0:
            result["control"] = "unavailable"
        return result
    if not online:
        result["control"] = "unavailable"
        return result
    try:
        control = hass.states.get(controller.charge_control)
        if control is None or str(control.state).lower() in ("unknown", "unavailable"):
            result["control"] = "unavailable"
            return result
        result["control"] = "available"
        from ..execution.charger_connection import normalise_ocpp
        from ..vehicles.ocpp_identity import STATUS_CONNECTOR_KEY, connector_sensor_entity_id

        source = connector_sensor_entity_id(hass, controller.ocpp_target, STATUS_CONNECTOR_KEY)
        observation = hass.states.get(source)
        if observation is None or str(observation.state).lower() in ("unknown", "unavailable"):
            return result
        timestamp = getattr(observation, "last_reported", None) or getattr(observation, "last_updated", None)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            return result
        age = (now - timestamp).total_seconds()
        if age < 0 or age > 180:
            return result
        result["vehicle_observed_at"] = timestamp.isoformat()
        state = normalise_ocpp(str(observation.state))
        if state == "disconnected":
            result["vehicle"] = "disconnected"
        elif state in ("connected", "charging", "paused", "finished"):
            result["vehicle"] = "connected"
    except Exception:  # noqa: BLE001 - unavailable evidence is not an API failure
        # Missing or malformed HA evidence is not permission to assume readiness.
        pass
    return result


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
    """Current fixed-time intent for preview, manual Send and future backend callers.

    Refusal means no proposed action, never permission to clear or release a limit.
    """
    settings = domain_data(hass).auto_store.settings(entry_id)
    if settings.amps != 16:
        raise ScheduleRefused("current_must_be_16")
    planner = preview_for(hass, entry_id)
    snapshot = planner.snapshot() if planner is not None else None
    proposal = snapshot.proposal if snapshot is not None and snapshot.in_process else None
    if proposal is None:
        if snapshot is not None and getattr(snapshot, "price_state", None) in ("stale", "unavailable", "invalid", "loading", "degraded"):
            raise ScheduleRefused("prices_stale_or_unavailable")
        raise ScheduleRefused("no_current_plan")
    if (not planner.snapshot_is_current(snapshot) or snapshot.settings_revision != settings.revision
            or getattr(snapshot, "last_error_code", None) is not None):
        raise ScheduleRefused("no_current_plan")
    price_state = getattr(snapshot, "price_state", None)
    if price_state not in ("ready", "waiting_for_tomorrow"):
        raise ScheduleRefused("prices_unavailable" if price_state is None else "prices_stale_or_unavailable")
    if proposal.unpriced:
        raise ScheduleRefused("prices_unavailable")
    if not proposal.has_plan or not proposal.shown_periods:
        raise ScheduleRefused("no_current_plan")
    # The stored profile is a fixed-time snapshot of exactly what the card shows,
    # including the estimated shorter final block. It does not implement feedback-based energy stopping.
    return profile_for(tuple(proposal.shown_periods), settings.amps, now, allow_active=True)


def _preview_id(profile: dict[str, Any], revision: Any) -> str:
    """Commit to wire attributes and absolute changes, excluding the moving initial timestamp."""
    schedule = profile["chargingSchedule"]
    start = datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00"))
    periods = schedule["chargingSchedulePeriod"]
    transitions = [{**period, "startPeriod": (start + timedelta(seconds=period["startPeriod"])).isoformat()}
                   for period in periods[1:]]
    intent = {key: value for key, value in profile.items() if key != "chargingSchedule"}
    intent["chargingSchedule"] = {key: value for key, value in schedule.items()
                                   if key not in ("startSchedule", "chargingSchedulePeriod")}
    intent["initial"] = {key: value for key, value in periods[0].items() if key != "startPeriod"}
    intent["transitions"] = transitions
    return hashlib.sha256(json.dumps([revision, intent], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _outcome_record(hass: HomeAssistant, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Load or conservatively migrate the old entry-local manual record."""
    record = await outcomes_for(hass).read()
    if record is None:
        cleanup = data.get("cleanup") or {}
        legacy_uncertain = bool((data.get("profile") and str(data.get("ack", "unknown")).lower() not in
                                 ("accepted", "rejected", "notsupported"))
                                or (cleanup and str(cleanup.get("status", "unknown")).lower() not in
                                    ("accepted", "rejected", "notsupported")))
        record = {"schema": 1, "entry_id": entry_id, "desired": None, "attempt": None,
                  "acknowledged": None, "verified": None, "uncertain": legacy_uncertain,
                  "removal": None}
    if record.get("entry_id") != entry_id or type(record.get("uncertain")) is not bool:
        raise ScheduleRefused("outcome_binding_unavailable")
    return record


def _verification_current(hass: HomeAssistant, entry_id: str, entry: Any, data: dict[str, Any],
                          record: dict[str, Any] | None, sent_at: str) -> bool:
    """Fail closed if the accepted attempt, planner, connection or lifecycle changed."""
    try:
        current_entry, failure = lookup_charger(hass, entry_id)
        if failure or current_entry is not entry or not isinstance(record, dict):
            return False
        lifecycle = hass.data.get(_LIFECYCLE_KEY, {}).get(entry_id)
        if lifecycle is None or lifecycle["entry"] is not entry or not lifecycle["live"]:
            return False
        worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
        if worker is not None and (worker._closed or worker._suspended or not worker._available()):
            return False
        target = getattr(controller_for(hass, entry_id), "ocpp_target", None)
        from ..execution.command_admission import classify_morek_identity
        if classify_morek_identity(_identity_status(hass, target)) != "supported_morek":
            return False
        _charge_point(hass, target)
        attempt, ack = record.get("attempt") or {}, record.get("acknowledged") or {}
        fingerprint = attempt.get("fingerprint")
        if (record.get("entry_id") != entry_id or record.get("uncertain") is not False
                or data.get("cleanup") or data.get("sent_at") != sent_at
                or data.get("ack", "").lower() != "accepted"
                or attempt.get("state") != "accepted" or attempt.get("at") != sent_at
                or not fingerprint or ack.get("fingerprint") != fingerprint or ack.get("at") != sent_at
                or not attempt.get("id") or attempt.get("id") != ack.get("id")
                or attempt.get("id") != data.get("attempt_id")):
            return False
        settings = domain_data(hass).auto_store.settings(entry_id)
        if attempt.get("revision") != settings.revision:
            return False
        sent = attempt.get("profile")
        if _preview_id(sent, settings.revision) != fingerprint or sent != data.get("profile"):
            return False
        now = datetime.now(timezone.utc)
        current = _proposed_profile(hass, entry_id, now)
        if ({k: v for k, v in sent.items() if k != "chargingSchedule"}
                != {k: v for k, v in current.items() if k != "chargingSchedule"}):
            return False
        if ({k: v for k, v in sent["chargingSchedule"].items() if k not in ("startSchedule", "chargingSchedulePeriod")}
                != {k: v for k, v in current["chargingSchedule"].items()
                    if k not in ("startSchedule", "chargingSchedulePeriod")}):
            return False
        def remaining(profile):
            schedule = profile["chargingSchedule"]
            start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
            periods = [(start + timedelta(seconds=p["startPeriod"]),
                        {k: v for k, v in p.items() if k != "startPeriod"})
                       for p in schedule["chargingSchedulePeriod"]]
            return periods
        old, new = remaining(sent), remaining(current)
        boundary = max(now, old[0][0], new[0][0])
        def projection(periods):
            return (next(limit for at, limit in reversed(periods) if at <= boundary),
                    [(at, limit) for at, limit in periods if at > boundary])
        return projection(old) == projection(new)
    except Exception:  # noqa: BLE001 - verification must not outlive its evidence
        return False


async def _send_profile_shared(hass: HomeAssistant, entry_id: str, data: dict[str, Any], store: Any,
                               fingerprint: str, validate: Any, *, automatic: bool) -> str:
    """Connector lock held. Record first, revalidate after every pre-dispatch await."""
    ledger = outcomes_for(hass)
    record = await _outcome_record(hass, entry_id, data)
    profile, point, target = validate()
    # This exact wire payload is the one recorded and later dispatched. A
    # revalidation may rebuild an equivalent profile with a later startSchedule.
    wire_profile = profile
    if record["uncertain"]:
        return "upload_uncertain"
    acknowledged = record.get("acknowledged") or {}
    attempt = record.get("attempt") or {}
    if automatic and acknowledged.get("fingerprint") == fingerprint:
        return "unchanged"
    if automatic and attempt.get("state") == "rejected" and attempt.get("fingerprint") == fingerprint:
        return "upload_rejected"
    now = datetime.now(timezone.utc).isoformat()
    attempt_id = uuid4().hex
    revision = domain_data(hass).auto_store.settings(entry_id).revision
    record.update({"desired": {"fingerprint": fingerprint, "profile": profile},
                   "attempt": {"fingerprint": fingerprint, "profile": profile, "at": now, "id": attempt_id,
                               "revision": revision,
                               "source": "worker" if automatic else "manual", "state": "uncertain"},
                   "uncertain": True, "verified": None})
    await ledger.write(record)
    # Recheck after persistence: a settings edit, new calculation, identity or
    # pause change while the disk was busy must never become an obsolete send.
    try:
        profile, point, target = validate()
    except Exception:
        record["attempt"]["state"] = "aborted_before_dispatch"
        record["uncertain"] = False
        await ledger.write(record)
        raise
    _cancel_verification(hass, entry_id)
    data.update({"sent_at": now, "attempt_id": attempt_id, "profile": wire_profile, "ack": "unknown", "verified": False,
                 "effective": None, "cleanup": None,
                 "verification": {"pending": False, "reason": "upload_unconfirmed",
                                  "next_check_at": None, "attempts": 0}})
    await store.async_save(data)
    try:
        profile, point, target = validate()
    except Exception:
        record["attempt"]["state"] = "aborted_before_dispatch"
        record["uncertain"] = False
        await ledger.write(record)
        raise
    from ocpp.v16 import call as ocpp_call
    sending = hass.data.setdefault("spotnav_morek_sending", {})
    sending[entry_id] = attempt_id
    try:
        async with asyncio.timeout(30):
            response = await point.call(ocpp_call.SetChargingProfile(
                connector_id=target.connector_id, cs_charging_profiles=wire_profile))
        ack = _status(response)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - dispatch may have applied
        ack = "unknown"
    finally:
        if sending.get(entry_id) == attempt_id:
            sending.pop(entry_id, None)
    data["ack"] = ack
    state = ack.lower()
    if state == "accepted":
        record.update({"acknowledged": {"fingerprint": fingerprint, "at": now, "id": attempt_id}, "uncertain": False})
        record["attempt"]["state"] = "accepted"
    elif state in ("rejected", "notsupported"):
        record["attempt"]["state"] = "rejected"
        record["uncertain"] = False
    # Unknown, cancellation, or interrupted ACK persistence stays uncertain on disk.
    record["attempt"]["ack"] = ack
    await ledger.write(record)
    await store.async_save(data)
    return "upload_accepted_unverified" if state == "accepted" else (
        "upload_rejected" if state in ("rejected", "notsupported") else "upload_uncertain")


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


def _operator_state(identity: dict[str, Any], online: bool, outcomes: dict[str, Any],
                    verification: dict[str, Any], verified: bool, preview: dict[str, Any],
                    sending_id: str | None) -> dict[str, str | None]:
    """Summarize evidence, never treating an old match or an unknown ACK as success."""
    attempt = outcomes.get("attempt") or {}
    if outcomes.get("uncertain"):
        if sending_id and sending_id == attempt.get("id") and attempt.get("state") == "uncertain":
            return {"state": "sending", "reason": "upload_in_flight"}
        return {"state": "intervention_needed", "reason": outcomes.get("state") or "outcome_uncertain"}
    if not online:
        return {"state": "offline", "reason": "charger_unavailable"}
    if not identity.get("supported"):
        return {"state": "not_ready", "reason": identity.get("reason") or "identity_unresolved"}
    if verification.get("pending"):
        return {"state": "checking", "reason": verification.get("reason")}
    if verified:
        return {"state": "verified", "reason": verification.get("reason")}
    reason = verification.get("reason")
    if reason == "limits_or_transitions_differ":
        return {"state": "mismatch", "reason": reason}
    if reason and reason not in ("cleanup_requested",):
        return {"state": "not_ready", "reason": reason}
    if preview.get("reason") or not preview.get("profile"):
        return {"state": "waiting", "reason": preview.get("reason") or "no_current_plan"}
    return {"state": "ready", "reason": "manual_preview_only"}


async def async_schedule_action(hass: HomeAssistant, entry_id: str, action: str,
                                preview_id: str | None = None, confirm_profile_id: int | None = None, *,
                                expected_sent_at: str | None = None,
                                verification_attempt: int | None = None,
                                expected_attempt_id: str | None = None,
                                verification_handle: Any = None) -> dict[str, Any]:
    """Manual operations share connector serialization without enabling owned mode."""
    if action not in ("send", "fetch", "clear"):
        raise ScheduleRefused("invalid_action")
    if action == "clear" and (type(confirm_profile_id) is not int or confirm_profile_id != PROFILE_ID):
        raise ScheduleRefused("cleanup_confirmation_required")
    if action == "send" and not preview_id:
        raise ScheduleRefused("preview_changed")
    entry, failure = lookup_charger(hass, entry_id)
    if failure or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")

    def identity() -> dict[str, Any]:
        controller = controller_for(hass, entry_id)
        return _identity_status(hass, getattr(controller, "ocpp_target", None))

    async def run() -> dict[str, Any]:
        return await _async_schedule_action_locked(hass, entry_id, action, preview_id, confirm_profile_id,
                                                    expected_sent_at=expected_sent_at,
                                                   verification_attempt=verification_attempt,
                                                   expected_attempt_id=expected_attempt_id,
                                                   verification_handle=verification_handle)

    admission = command_admission(hass)
    if action == "fetch":
        result = await admission.async_execute(entry_id, "read_only", identity, run)
    else:
        result = await admission.async_manual_profile(entry_id, identity, run)
    if not result.allowed:
        raise ScheduleRefused(result.reason)
    return result.value


async def _async_schedule_action_locked(hass: HomeAssistant, entry_id: str, action: str,
                                        preview_id: str | None, confirm_profile_id: int | None, *,
                                        expected_sent_at: str | None,
                                        verification_attempt: int | None, expected_attempt_id: str | None,
                                        verification_handle: Any) -> dict[str, Any]:
    entry, failure = lookup_charger(hass, entry_id)
    if failure is not None or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    lifecycle = _verification_lifecycle(hass, entry_id, entry)
    controller = controller_for(hass, entry_id)
    target = getattr(controller, "ocpp_target", None)
    if not _identity_status(hass, target)["supported"]:
        raise ScheduleRefused("not_morek_connector")
    await _state(hass, entry_id)
    cache = hass.data[_DATA_KEY]
    data, store, lock = cache[entry_id]
    async with lock:
        if expected_sent_at is not None and (data.get("sent_at") != expected_sent_at or data.get("cleanup")
                                             or data.get("verified") or (expected_attempt_id is not None
                                             and data.get("attempt_id") != expected_attempt_id)):
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
            def validate():
                current_controller = controller_for(hass, entry_id)
                current_target = getattr(current_controller, "ocpp_target", None)
                if not _identity_status(hass, current_target)["supported"]:
                    raise ScheduleRefused("not_morek_connector")
                current_settings = domain_data(hass).auto_store.settings(entry_id)
                if current_settings.pause.choice != "until_resumed":
                    raise ScheduleRefused("pause_auto_first")
                current_profile = _proposed_profile(hass, entry_id, datetime.now(timezone.utc))
                if preview_id != _preview_id(current_profile, current_settings.revision):
                    raise ScheduleRefused("preview_changed")
                return current_profile, _charge_point(hass, current_target), current_target

            outcome = await _send_profile_shared(hass, entry_id, data, store, preview_id, validate, automatic=False)
            if outcome == "upload_uncertain":
                raise ScheduleRefused("upload_uncertain")
            if outcome != "upload_accepted_unverified":
                raise ScheduleRefused("upload_not_confirmed")
            profile = data["profile"]
        elif action == "clear":
            _cancel_verification(hass, entry_id)
            ledger = outcomes_for(hass)
            record = await _outcome_record(hass, entry_id, data)
            was_uncertain = record["uncertain"]
            record.update({"acknowledged": None, "verified": None, "uncertain": True,
                           "removal": {"at": now.isoformat(), "state": "uncertain"}})
            await ledger.write(record)
            if not _identity_status(hass, target)["supported"]:
                raise ScheduleRefused("not_morek_connector")
            cp = _charge_point(hass, target)
            # By OCPP 1.6, id alone selects this exact profile. Never send an empty
            # ClearChargingProfile request or use the generic HA clear service.
            data.update({"cleanup": {"requested_at": now.isoformat(), "profile_id": PROFILE_ID,
                                      "status": "unknown"}, "effective": None, "verified": False,
                         "verification": {"pending": False, "reason": "cleanup_requested",
                                          "next_check_at": None, "attempts": 0}})
            await store.async_save(data)
            current_controller = controller_for(hass, entry_id)
            target = getattr(current_controller, "ocpp_target", None)
            if not _identity_status(hass, target)["supported"]:
                raise ScheduleRefused("not_morek_connector")
            cp = _charge_point(hass, target)
            try:
                response = await asyncio.wait_for(cp.call(ocpp_call.ClearChargingProfile(id=PROFILE_ID)), timeout=30)
                data["cleanup"]["status"] = _status(response)
            except Exception:
                # A timeout does not prove the station did not remove the profile.
                data["cleanup"]["status"] = "unknown"
            status = data["cleanup"]["status"].lower()
            if status in ("accepted", "rejected", "notsupported"):
                record["uncertain"] = was_uncertain
                record["removal"]["state"] = status
            record["removal"]["ack"] = data["cleanup"]["status"]
            await ledger.write(record)
            await store.async_save(data)
        query_at = datetime.now(timezone.utc)
        duration = 43200
        profile = data.get("profile")
        if isinstance(profile, dict):
            end = profile["chargingSchedule"]["chargingSchedulePeriod"][-1]["startPeriod"]
            start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
            duration = max(duration, min(172800, int((start + timedelta(seconds=end + 3600) - query_at).total_seconds())))
        worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
        serial = getattr(worker, "_serial", None)
        if expected_sent_at is not None:
            record = await outcomes_for(hass).read()
            if (not lifecycle["live"] or not _verification_current(hass, entry_id, entry, data, record, expected_sent_at)
                    or (expected_attempt_id is not None and data.get("attempt_id") != expected_attempt_id)
                    or (verification_handle is not None
                        and hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not verification_handle)):
                raise ScheduleRefused("verification_superseded")
        try:
            response = await asyncio.wait_for(cp.call(ocpp_call.GetCompositeSchedule(
                connector_id=target.connector_id, duration=duration, charging_rate_unit="A")), timeout=30)
            effective = readback(response, datetime.now(timezone.utc), requested_at=query_at)
            if getattr(response, "connector_id", target.connector_id) != target.connector_id:
                effective["status"] = "wrong_connector"
        except Exception:
            effective = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(), "periods": []}
        if expected_sent_at is not None and (entry_id not in hass.data.get(_VERIFY_KEY, {})
                or (verification_handle is not None and hass.data[_VERIFY_KEY].get(entry_id) is not verification_handle)):
            raise ScheduleRefused("verification_superseded")
        record = await outcomes_for(hass).read()
        sent_at = data.get("sent_at")
        current = bool(sent_at and (worker is None or worker._serial == serial)
                       and _verification_current(hass, entry_id, entry, data, record, sent_at))
        if expected_sent_at is not None and (not current or sent_at != expected_sent_at
                or (expected_attempt_id is not None and data.get("attempt_id") != expected_attempt_id)
                or entry_id not in hass.data.get(_VERIFY_KEY, {})
                or (verification_handle is not None and hass.data[_VERIFY_KEY].get(entry_id) is not verification_handle)):
            raise ScheduleRefused("verification_superseded")
        if not lifecycle["live"]:
            raise ScheduleRefused("verification_superseded")
        comparison = compare_schedule(profile, effective)
        if data.get("cleanup"):
            comparison.update({"matched": False, "exact": False, "reason": "cleanup_requested"})
        elif data.get("ack", "").lower() != "accepted":
            comparison.update({"matched": False, "exact": False, "reason": "upload_unconfirmed"})
        elif not current:
            comparison.update({"matched": False, "exact": False, "reason": "verification_superseded"})
        previous_effective = data.get("effective")
        if record is not None and record.get("entry_id") != entry_id:
            comparison.update({"matched": False, "exact": False, "reason": "outcome_uncertain"})
        elif record is not None:
            if record.get("uncertain"):
                comparison.update({"matched": False, "exact": False, "reason": "outcome_uncertain"})
            acknowledged = record.get("acknowledged") or {}
            if comparison["matched"] and acknowledged.get("fingerprint"):
                record["verified"] = {"fingerprint": acknowledged["fingerprint"],
                                      "attempt_at": sent_at, "attempt_id": acknowledged["id"],
                                      "planner_serial": serial,
                                      "at": datetime.now(timezone.utc).isoformat()}
            else:
                record["verified"] = None
            await outcomes_for(hass).write(record)
            if current and (not lifecycle["live"] or (worker is not None and worker._serial != serial)
                    or not _verification_current(hass, entry_id, entry, data, record, sent_at)
                    or (verification_handle is not None
                        and hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not verification_handle)):
                record["verified"] = None
                await outcomes_for(hass).write(record)
                current = False
                comparison.update({"matched": False, "exact": False, "reason": "verification_superseded"})
        # Publish only after the persistence await and its freshness recheck.
        if current or action == "clear" or profile is None:
            data["effective"] = effective
        data["verified"] = comparison["matched"]
        verification = data.setdefault("verification", {})
        verification.update(comparison)
        verification["checked_at"] = datetime.now(timezone.utc).isoformat()
        if data["verified"] or action == "clear" or comparison["reason"] == "verification_superseded":
            _cancel_verification(hass, entry_id)
            verification.update({"pending": False, "next_check_at": None})
        elif action == "send" or verification_attempt is not None:
            next_attempt = 0 if action == "send" else verification_attempt + 1
            verification["attempts"] = 1 if action == "send" else verification_attempt + 2
            if next_attempt < len(VERIFY_DELAYS):
                _schedule_verification(hass, entry_id, data["sent_at"], next_attempt, data.get("attempt_id"))
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
                     action, data.get("ack"), effective["status"], data["verified"], comparison["reason"])
        await store.async_save(data)
        if current and (not lifecycle["live"] or (worker is not None and worker._serial != serial)
                or not _verification_current(hass, entry_id, entry, data, record, sent_at)):
            _cancel_verification(hass, entry_id)
            data["verified"] = False
            data["effective"] = previous_effective
            verification.update({"matched": False, "exact": False, "reason": "verification_superseded",
                                 "pending": False, "next_check_at": None})
            record["verified"] = None
            await outcomes_for(hass).write(record)
            await store.async_save(data)
        return {"supported": True, "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                "sent": profile, "effective": data.get("effective"), "cleanup": data.get("cleanup"),
                "cleanup_supported": True, "outcomes": record,
                "verification": _verification_state(hass, entry_id, data)}


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
            identity = _identity_status(hass, target)
            ownership = await ownership_store(hass).async_status(entry.entry_id, identity)
            admission = command_admission(hass)
            previous_recovery = admission._recovery_status.get(entry.entry_id, {})
            ownership["recovery"] = await admission.async_recovery_status(
                entry.entry_id, lambda: _identity_status(hass, getattr(controller_for(hass, entry.entry_id), "ocpp_target", None))
            )
            if "recovery_result" in previous_recovery:
                ownership["recovery"]["last_recovery_result"] = previous_recovery["recovery_result"]
                admission._recovery_status[entry.entry_id]["recovery_result"] = previous_recovery["recovery_result"]
            try:
                outcomes = await _outcome_record(hass, entry.entry_id, data)
            except (OutcomeUnavailable, ScheduleRefused):
                outcomes = {"state": "storage_unavailable", "uncertain": True}
            verified_evidence = outcomes.get("verified") or {}
            worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
            verified = bool(data.get("verified") and verified_evidence.get("attempt_id") == data.get("attempt_id")
                            and verified_evidence.get("attempt_at") == data.get("sent_at")
                            and verified_evidence.get("fingerprint") == (outcomes.get("acknowledged") or {}).get("fingerprint")
                            and (worker is None or verified_evidence.get("planner_serial") == worker._serial)
                            and _verification_current(hass, entry.entry_id, entry, data, outcomes, data.get("sent_at")))
            verification = _verification_state(hass, entry.entry_id, data)
            if data.get("verified") and not verified:
                verification.update({"matched": False, "exact": False, "reason": "verification_superseded"})
            compared = verification.get("reason") in (
                "limits_or_transitions_differ", "coverage_missing", "coverage_too_short", "coverage_stale",
                "coverage_boundary_ambiguous", "no_remaining_transitions", "readback_unavailable")
            if (verification.get("pending") or compared) and not _verification_current(
                    hass, entry.entry_id, entry, data, outcomes, data.get("sent_at")):
                verification.update({"pending": False, "next_check_at": None, "reason": "verification_superseded"})
            if not verified and outcomes.get("verified"):
                outcomes = {**outcomes, "verified": None}
            preview = _preview(hass, entry.entry_id, target)
            try:
                _charge_point(hass, target)
                online = worker is None or (not worker._suspended and worker._available() and not worker._closed)
            except ScheduleRefused:
                online = False
            operator = _operator_state(identity, online, outcomes, verification, verified, preview,
                                       hass.data.get("spotnav_morek_sending", {}).get(entry.entry_id))
            result = {**identity,
                      "readiness": _session_readiness(hass, controller, identity, online, datetime.now(timezone.utc)),
                      "ownership": ownership,
                      "outcomes": outcomes,
                      "operator": operator,
                      "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": verified,
                      "sent": data.get("profile"), "effective": data.get("effective"),
                      "preview": preview,
                      "cleanup": data.get("cleanup"), "cleanup_supported": True,
                      "verification": verification}
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
