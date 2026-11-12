"""A Morek profile must never silently extend or truncate the planned charging windows."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, Mock
from .morek_fakes import MemoryOutcomes
import sys
from custom_components.spotnav.api import morek_schedule

from custom_components.spotnav.api.morek_schedule import (
    _charge_point,
    _identity_status,
    ScheduleRefused,
    matches,
    profile_for,
    readback,
)


NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)


def _supported_identity():
    return {"supported": True, "resolved_id": morek_schedule.MOREK_STATION_ID,
            "connector_id": 1, "match_count": 1, "ocpp_version": "1.6"}


def _legacy_ownership():
    return SimpleNamespace(async_status=AsyncMock(return_value={
        "record_state": "valid", "recorded_owner": "legacy", "transition_state": None,
        "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1, "armed": False,
    }))


def test_three_blocks_fit_seven_entries_and_start_paused():
    windows = ((NOW + timedelta(hours=1), NOW + timedelta(hours=1, minutes=30)),
               (NOW + timedelta(hours=5), NOW + timedelta(hours=5, minutes=15)),
               (NOW + timedelta(hours=6), NOW + timedelta(hours=6, minutes=15)))
    profile = profile_for(windows, 16, NOW)
    periods = profile["chargingSchedule"]["chargingSchedulePeriod"]
    assert profile["chargingProfilePurpose"] == "TxDefaultProfile"
    assert [p["limit"] for p in periods] == [0, 16, 0, 16, 0, 16, 0]
    assert [p["startPeriod"] for p in periods] == [0, 3600, 5400, 18000, 18900, 21600, 22500]
    assert all(p["numberPhases"] == 3 for p in periods)


def test_single_zero_profile_is_verified_only_over_bounded_coverage():
    """A match describes one observed hour, not persistent or physical stop."""
    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)
    profile["chargingSchedule"]["chargingSchedulePeriod"] = [{"startPeriod": 0, "limit": 0, "numberPhases": 3}]
    reply = SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(),
                            charging_schedule={"chargingRateUnit": "A", "duration": 7200,
                                               "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0}]})
    actual = readback(reply, NOW)
    result = morek_schedule.compare_schedule(profile, actual)
    assert result["matched"] is True
    assert result["scope"] == "bounded_held_off"
    assert result["coverage_end"] == (NOW + timedelta(hours=1)).isoformat()


def test_owned_pause_status_never_treats_old_ack_or_match_as_physical_stop():
    outcome = {"uncertain": False, "schedule_pause": {"id": "new"},
               "attempt": {"pause_id": "old", "state": "accepted", "ack": "Accepted"}}
    verification = {"scope": "bounded_held_off", "coverage_start": "a", "coverage_end": "b"}
    status = morek_schedule._owned_pause_status(outcome, verification, True, None)
    assert status["ack"] is None and status["readback"] == "unverified" and status["measured"] == "unknown"
    outcome["attempt"]["pause_id"] = "new"
    status = morek_schedule._owned_pause_status(outcome, verification, True, None)
    assert status["ack"] == "Accepted" and status["readback"] == "bounded_match"
    assert status["coverage_end"] == "b" and status["measured"] == "unknown"


@pytest.mark.parametrize(("duration", "periods", "delay", "start_delta", "reason"), [
    (None, [{"startPeriod": 0, "limit": 0}], 0, 0, "coverage_missing"),
    (100, [{"startPeriod": 0, "limit": 0}], 0, 0, "coverage_too_short"),
    (7200, [{"startPeriod": 0, "limit": 16}], 0, 0, "limits_or_transitions_differ"),
    (7200, [{"startPeriod": 0, "limit": 0}, {"startPeriod": 60, "limit": 16}], 0, 0, "limits_or_transitions_differ"),
    (7200, [{"startPeriod": 0, "limit": 0}], 100, 0, "coverage_boundary_ambiguous"),
    (7200, [{"startPeriod": 0, "limit": 0}], 0, 1, "coverage_boundary_ambiguous"),
])
def test_flat_zero_refuses_inadequate_evidence(duration, periods, delay, start_delta, reason):
    schedule = {"chargingRateUnit": "A", "chargingSchedulePeriod": periods}
    if duration is not None:
        schedule["duration"] = duration
    reply = SimpleNamespace(status="Accepted", schedule_start=(NOW + timedelta(seconds=start_delta)).isoformat(),
                            charging_schedule=schedule)
    actual = readback(reply, NOW + timedelta(seconds=delay), requested_at=NOW)
    result = morek_schedule.compare_schedule(morek_schedule.held_off_profile(NOW), actual)
    assert not result["matched"] and result["reason"] == reason


def test_unsafe_plans_are_refused_before_any_upload():
    block = (NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    with pytest.raises(ScheduleRefused, match="too_many_blocks"):
        profile_for(tuple((block[0] + timedelta(hours=i * 2), block[1] + timedelta(hours=i * 2))
                          for i in range(4)), 16, NOW)
    with pytest.raises(ScheduleRefused, match="invalid_plan"):
        profile_for(((NOW, block[1]),), 16, NOW)
    with pytest.raises(ScheduleRefused, match="invalid_current"):
        profile_for((block,), 25, NOW)


def test_composite_uses_reply_schedule_start_and_catches_extra_charging():
    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)

    def reply(periods):
        return SimpleNamespace(status="Accepted", schedule_start=(NOW + timedelta(seconds=4)).isoformat(),
                               charging_schedule={"chargingRateUnit": "A", "chargingSchedulePeriod": periods})

    good = readback(reply([{"startPeriod": 0, "limit": 0}, {"startPeriod": 3596, "limit": 16},
                           {"startPeriod": 7196, "limit": 0}]), NOW)
    assert matches(profile, good)
    repeated = readback(reply([{"startPeriod": 0, "limit": 0}, {"startPeriod": 300, "limit": 0},
                               {"startPeriod": 3596, "limit": 16}, {"startPeriod": 7196, "limit": 0}]), NOW)
    assert matches(profile, repeated)
    wrong = readback(reply([{"startPeriod": 0, "limit": 0}, {"startPeriod": 1800, "limit": 16},
                            {"startPeriod": 7196, "limit": 0}]), NOW)
    assert not matches(profile, wrong)
    extra = readback(reply([{"startPeriod": 0, "limit": 0}, {"startPeriod": 3596, "limit": 16},
                            {"startPeriod": 5396, "limit": 0}, {"startPeriod": 6300, "limit": 16},
                            {"startPeriod": 7196, "limit": 0}]), NOW)
    assert not matches(profile, extra)
    after = readback(reply([{"startPeriod": 0, "limit": 0}, {"startPeriod": 3596, "limit": 16},
                            {"startPeriod": 7196, "limit": 0}, {"startPeriod": 9000, "limit": 16}]), NOW)
    assert not matches(profile, after)
    late = SimpleNamespace(status="Accepted", schedule_start=(NOW + timedelta(hours=1, minutes=10)).isoformat(),
                           charging_schedule={"chargingRateUnit": "A", "chargingSchedulePeriod": [
                               {"startPeriod": 0, "limit": 0}, {"startPeriod": 3000, "limit": 0},
                           ]})
    assert not matches(profile, readback(late, NOW + timedelta(hours=1, minutes=10)))


def test_ocpp_alias_must_resolve_to_the_physical_morek_before_commands():
    from custom_components.spotnav.execution.command_admission import classify_morek_identity
    morek = SimpleNamespace(_ocpp_version="1.6", status="ok")
    system = SimpleNamespace(cpids={"garage": "3020002509120029"},
                             charge_points={"3020002509120029": morek})
    hass = SimpleNamespace(data={"ocpp": {"entry": system}})
    target = SimpleNamespace(devid="garage", connector_id=1)
    assert _identity_status(hass, target)["supported"] is True
    assert classify_morek_identity(_identity_status(hass, target)) == "supported_morek"
    assert _identity_status(hass, target)["resolved_id"] == "3020002509120029"
    assert _charge_point(hass, target) is morek

    system.cpids["garage"] = "other_station"
    system.charge_points["other_station"] = SimpleNamespace(_ocpp_version="1.6", status="ok")
    assert _identity_status(hass, target)["supported"] is False
    assert classify_morek_identity(_identity_status(hass, target)) == "non_target"
    with pytest.raises(ScheduleRefused):
        _charge_point(hass, target)

    system.cpids.clear()
    system.charge_points.clear()
    assert _identity_status(hass, target)["reason"] == "station_not_matched"
    assert classify_morek_identity(_identity_status(hass, target)) == "unresolved"
    assert _identity_status(hass, None)["reason"] == "no_ocpp_target"


@pytest.mark.parametrize(("station", "connector", "version", "duplicates", "classification"), [
    ("3020002509120029", 1, "1.6", False, "supported_morek"),
    ("3020002509120029", 1, "2.0.1", False, "target_unsupported"),
    ("3020002509120029", 1, None, False, "target_unsupported"),
    ("different", 1, "1.6", False, "non_target"),
    ("3020002509120029", 2, "1.6", False, "non_target"),
    ("3020002509120029", 2, "1.6", True, "unresolved"),
])
def test_classification_uses_real_unique_identity(station, connector, version, duplicates, classification):
    from custom_components.spotnav.execution.command_admission import classify_morek_identity
    point = SimpleNamespace(_ocpp_version=version, status="ok")
    system = SimpleNamespace(cpids={"alias": station}, charge_points={station: point})
    systems = {"first": system, **({"second": system} if duplicates else {})}
    result = _identity_status(SimpleNamespace(data={"ocpp": systems}),
                              SimpleNamespace(devid="alias", connector_id=connector))
    assert classify_morek_identity(result) == classification
    if duplicates:
        assert result["reason"] == "ambiguous_station" and result["resolved_id"] is None


@pytest.mark.asyncio
async def test_initializer_refuses_real_unsupported_and_ambiguous_identities():
    from custom_components.spotnav.execution.command_admission import CommandAdmission, classify_morek_identity
    store = SimpleNamespace(_async_ensure_locked_connector=AsyncMock())
    gate = CommandAdmission(store)
    point = SimpleNamespace(_ocpp_version="2.0.1", status="ok")
    system = SimpleNamespace(cpids={"alias": morek_schedule.MOREK_STATION_ID},
                             charge_points={morek_schedule.MOREK_STATION_ID: point})
    hass = SimpleNamespace(data={"ocpp": {"first": system}})
    target = SimpleNamespace(devid="alias", connector_id=1)
    def resolve():
        return _identity_status(hass, target)
    assert await gate.async_ensure_initialized("a", resolve) == "identity_target_unsupported"
    point._ocpp_version = None
    assert await gate.async_ensure_initialized("a", resolve) == "identity_target_unsupported"
    hass.data["ocpp"]["second"] = system
    target.connector_id = 2
    assert await gate.async_ensure_initialized("a", resolve) == "identity_unresolved"
    hass.data["ocpp"].clear()
    target.devid, target.connector_id = morek_schedule.MOREK_STATION_ID, 1
    assert classify_morek_identity(resolve()) == "unresolved"
    assert await gate.async_ensure_initialized("a", resolve) == "identity_unresolved"
    with pytest.raises(ScheduleRefused):
        _charge_point(hass, target)
    store._async_ensure_locked_connector.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_exposes_read_only_unarmed_ownership(monkeypatch):
    target = SimpleNamespace(devid="alias", connector_id=1)
    identity = {"supported": True, "resolved_id": "physical", "connector_id": 1}
    ownership = {"record_state": "valid", "recorded_owner": "legacy", "ready": False, "armed": False}
    store = SimpleNamespace(async_status=AsyncMock(return_value=ownership))
    hass = SimpleNamespace(data={})
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    entry = SimpleNamespace(entry_id="charger", async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda h, e: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda h, e: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda h, t: identity)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda h: store)
    recovery = {"state": "legacy_unarmed", "activation_allowed": False, "activation_provenance": "unverified"}
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: SimpleNamespace(
        _recovery_status={}, _person_stops={}, async_recovery_status=AsyncMock(return_value=recovery)))
    monkeypatch.setattr(morek_schedule, "_state", AsyncMock(return_value=({}, None)))
    monkeypatch.setattr(morek_schedule, "_preview", lambda h, e, t: {})
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda h: MemoryOutcomes())
    monkeypatch.setattr(morek_schedule, "async_schedule_action", AsyncMock())
    await morek_schedule.websocket_morek_schedule.__wrapped__(
        hass, connection, {"id": 1, "api_version": 1, "charger_id": "charger", "action": "status"})
    assert connection.send_result.call_args.args[1]["schedule"]["ownership"] == ownership
    readiness = connection.send_result.call_args.args[1]["schedule"]["readiness"]
    assert readiness["control"] == "unknown"
    assert readiness["vehicle"] == readiness["transaction"] == readiness["measurement"] == "unknown"
    assert ownership["recovery"] == recovery
    store.async_status.assert_awaited_once_with("charger", identity)
    morek_schedule.async_schedule_action.assert_not_awaited()
    connection.send_error.assert_not_called()


@pytest.mark.parametrize(("online", "outcomes", "verification", "verified", "preview", "sending", "expected"), [
    (True, {"uncertain": False}, {}, False, {"reason": "prices_unavailable"}, None, "waiting"),
    (False, {"uncertain": False}, {}, False, {}, None, "offline"),
    (True, {"uncertain": True, "attempt": {"id": "a", "state": "uncertain"}}, {}, False, {}, "a", "sending"),
    (True, {"uncertain": True, "attempt": {"id": "a", "state": "uncertain"}}, {"pending": True}, True, {}, "old", "intervention_needed"),
    (False, {"uncertain": True, "state": "storage_unavailable"}, {}, True, {}, None, "intervention_needed"),
    (True, {"uncertain": False}, {"pending": True}, False, {}, None, "checking"),
    (True, {"uncertain": False}, {"reason": "limits_or_transitions_differ"}, False, {}, None, "mismatch"),
    (True, {"uncertain": False}, {"reason": "matched"}, True, {}, None, "verified"),
    (True, {"uncertain": False}, {"reason": "verification_superseded"}, False, {"profile": {}}, None, "not_ready"),
    (True, {"uncertain": False}, {}, False, {"profile": {"valid": True}}, None, "ready"),
])
def test_operator_state_prioritizes_current_evidence(online, outcomes, verification, verified, preview, sending, expected):
    result = morek_schedule._operator_state({"supported": True}, online, outcomes, verification, verified, preview, sending)
    assert result["state"] == expected


def test_preview_reuses_send_calculation_without_contacting_station(monkeypatch):
    periods = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),)
    proposal = SimpleNamespace(has_plan=True, unpriced=False, periods=periods, shown_periods=periods)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    settings = SimpleNamespace(amps=16, revision=4, pause=SimpleNamespace(choice="until_resumed"))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda hass: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda entry: settings)))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda hass, entry: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    point = SimpleNamespace(_ocpp_version="1.6", status="ok")
    hass = SimpleNamespace(data={"ocpp": {"entry": SimpleNamespace(
        cpids={"garage": "3020002509120029"}, charge_points={"3020002509120029": point})}})
    target = SimpleNamespace(devid="garage", connector_id=1)
    expected = morek_schedule._proposed_profile(hass, "charger", NOW)
    assert [p["limit"] for p in expected["chargingSchedule"]["chargingSchedulePeriod"]] == [0, 16, 0]
    snapshot.last_error_code = "proposal_not_saved"
    with pytest.raises(ScheduleRefused, match="no_current_plan"):
        morek_schedule._proposed_profile(hass, "charger", NOW)
    snapshot.last_error_code = None
    # Pin the clock so the preview and send helper must calculate the exact same wire payload.
    original_datetime = morek_schedule.datetime
    class FrozenDatetime:
        now = staticmethod(lambda tz: NOW)
        fromisoformat = staticmethod(original_datetime.fromisoformat)

    monkeypatch.setattr(morek_schedule, "datetime", FrozenDatetime)
    preview = morek_schedule._preview(hass, "charger", target)
    assert preview["profile"] == expected
    assert preview["reason"] is None
    assert preview["preview_id"] == morek_schedule._preview_id(expected, settings.revision)
    # The profile starts at a new clock instant at Send, but the ON/OFF times stay identical.
    shifted = morek_schedule._proposed_profile(hass, "charger", NOW + timedelta(seconds=10))
    assert morek_schedule._preview_id(shifted, settings.revision) == preview["preview_id"]
    changed = morek_schedule._proposed_profile(hass, "charger", NOW + timedelta(minutes=30))
    assert morek_schedule._preview_id(changed, settings.revision + 1) != preview["preview_id"]
    settings.pause.choice = "none"
    paused = morek_schedule._preview(hass, "charger", target)
    assert paused["profile"] == expected
    assert paused["reason"] == "pause_auto_first"
    settings.pause.choice = "until_resumed"
    proposal.shown_periods = ((periods[0][0], periods[0][0] + timedelta(minutes=15)),)
    shortened = morek_schedule._preview(hass, "charger", target)
    assert shortened["reason"] is None
    assert shortened["profile"]["chargingSchedule"]["chargingSchedulePeriod"][-1] == {
        "startPeriod": 4500, "limit": 0, "numberPhases": 3}
    assert shortened["preview_id"] != preview["preview_id"]


def test_fractional_windows_round_inwards_never_extending_charging():
    profile = profile_for(((NOW + timedelta(seconds=3600.2), NOW + timedelta(seconds=4500.8)),), 16, NOW)
    assert [p["startPeriod"] for p in profile["chargingSchedule"]["chargingSchedulePeriod"]] == [0, 3601, 4500]
    with pytest.raises(ScheduleRefused, match="invalid_plan"):
        profile_for(((NOW + timedelta(seconds=3600.2), NOW + timedelta(seconds=3600.8)),), 16, NOW)


def test_shared_active_intent_preserves_fixed_end_and_fingerprint():
    windows = ((NOW - timedelta(hours=2), NOW - timedelta(hours=1)),
               (NOW - timedelta(minutes=5), NOW + timedelta(minutes=15, microseconds=800000)),
               (NOW + timedelta(hours=1), NOW + timedelta(hours=2)))
    first = profile_for(windows, 16, NOW + timedelta(microseconds=200000), allow_active=True)
    later = profile_for(windows, 16, NOW + timedelta(seconds=30), allow_active=True)
    schedule = first["chargingSchedule"]
    assert schedule["startSchedule"] == (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    assert [(p["startPeriod"], p["limit"]) for p in schedule["chargingSchedulePeriod"]] == [
        (0, 16), (899, 0), (3599, 16), (7199, 0)]
    assert morek_schedule._preview_id(first, 4) == morek_schedule._preview_id(later, 4)
    assert morek_schedule._preview_id(first, 5) != morek_schedule._preview_id(later, 4)
    modified = profile_for(windows, 16, NOW, allow_active=True)
    modified["stackLevel"] = 2
    assert morek_schedule._preview_id(first, 4) != morek_schedule._preview_id(modified, 4)
    modified = profile_for(windows, 16, NOW, allow_active=True)
    modified["chargingSchedule"]["chargingSchedulePeriod"][0]["numberPhases"] = 1
    assert morek_schedule._preview_id(first, 4) != morek_schedule._preview_id(modified, 4)
    actual = {"status": "Accepted", "periods": [{"at": NOW.isoformat(), "amps": 0}]}
    assert morek_schedule.compare_schedule(first, actual)["matched"] is False


def test_expired_invalid_and_subsecond_remaining_windows_are_refused():
    with pytest.raises(ScheduleRefused, match="plan_expired"):
        profile_for(((NOW - timedelta(hours=1), NOW),), 16, NOW, allow_active=True)
    with pytest.raises(ScheduleRefused, match="invalid_plan"):
        profile_for(((NOW - timedelta(hours=2), NOW - timedelta(hours=1)),
                     (NOW - timedelta(hours=3), NOW + timedelta(hours=1))), 16, NOW, allow_active=True)
    with pytest.raises(ScheduleRefused, match="invalid_plan"):
        profile_for(((NOW - timedelta(seconds=1), NOW + timedelta(microseconds=800000)),),
                    16, NOW + timedelta(microseconds=200000), allow_active=True)


@pytest.mark.parametrize(("state", "unpriced", "reason"), [
    (None, False, "prices_unavailable"), ("stale", False, "prices_stale_or_unavailable"),
    ("degraded", False, "prices_stale_or_unavailable"), ("ready", True, "prices_unavailable"),
])
def test_intent_refuses_missing_or_stale_prices(monkeypatch, state, unpriced, reason):
    proposal = SimpleNamespace(has_plan=True, unpriced=unpriced,
                               shown_periods=((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),))
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state=state)
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: SimpleNamespace(amps=16, revision=4))))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda h, e: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    with pytest.raises(ScheduleRefused, match=reason):
        morek_schedule._proposed_profile(None, "charger", NOW)


def test_intent_reports_no_plan_and_expiration_without_profile(monkeypatch):
    proposal = SimpleNamespace(has_plan=True, unpriced=False,
                               shown_periods=((NOW - timedelta(hours=1), NOW),))
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: SimpleNamespace(amps=16, revision=4))))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda h, e: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    with pytest.raises(ScheduleRefused, match="plan_expired"):
        morek_schedule._proposed_profile(None, "charger", NOW)
    snapshot.proposal = None
    with pytest.raises(ScheduleRefused, match="no_current_plan"):
        morek_schedule._proposed_profile(None, "charger", NOW)
    snapshot.price_state = "stale"
    with pytest.raises(ScheduleRefused, match="prices_stale_or_unavailable"):
        morek_schedule._proposed_profile(None, "charger", NOW)


@pytest.mark.asyncio
async def test_manual_active_preview_and_crossing_boundary_refuses_stale_preview(monkeypatch):
    real = morek_schedule._proposed_profile
    h = _send_harness(monkeypatch, ["mismatch"])
    windows = ((NOW + timedelta(seconds=10), NOW + timedelta(minutes=15, seconds=12)),)
    proposal = SimpleNamespace(has_plan=True, unpriced=False, shown_periods=windows)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    settings = SimpleNamespace(amps=16, revision=4, pause=SimpleNamespace(choice="until_resumed"))
    monkeypatch.setattr(morek_schedule, "_proposed_profile", real)
    monkeypatch.setattr(morek_schedule, "preview_for", lambda h, e: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: settings)))
    future = morek_schedule._preview(h.hass, "charger", None)
    h.clock[0] += timedelta(seconds=11)
    with pytest.raises(ScheduleRefused, match="preview_changed"):
        await morek_schedule.async_schedule_action(h.hass, "charger", "send", future["preview_id"])
    assert h.calls == []
    active = morek_schedule._preview(h.hass, "charger", None)
    h.clock[0] += timedelta(seconds=10)
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "send", active["preview_id"])
    assert result["sent"]["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16
    assert h.calls == ["send", "fetch"]
    assert result["verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_status", ["Accepted", "Unknown", "timeout"])
async def test_selective_cleanup_only_names_test_id_and_fetches_afterwards(monkeypatch, reply_status):
    import asyncio

    calls = []

    async def station_call(request):
        calls.append(request)
        if request.action == "clear":
            if reply_status == "timeout":
                raise TimeoutError
            return SimpleNamespace(status=reply_status)
        return SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), connector_id=1,
                               charging_schedule={"chargingRateUnit": "A", "chargingSchedulePeriod": [
                                   {"startPeriod": 0, "limit": 16}]})

    point = SimpleNamespace(call=station_call)
    target = SimpleNamespace(connector_id=1)
    data = {"ack": "Accepted", "profile": profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)}
    store = SimpleNamespace(async_save=AsyncMock())
    hass = SimpleNamespace(data={morek_schedule._DATA_KEY: {"charger": (data, store, asyncio.Lock())}})
    entry = SimpleNamespace(entry_id="charger", async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda h, e: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda h, e: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda h, t: _supported_identity())
    from custom_components.spotnav.execution.command_admission import CommandAdmission
    admission = CommandAdmission(_legacy_ownership())
    monkeypatch.setattr(morek_schedule, "command_admission", lambda h: admission)
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda h: ledger)
    ledger = MemoryOutcomes()
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda h, t: point)
    monkeypatch.setattr(morek_schedule, "_state", AsyncMock(return_value=(data, store)))
    protocol = SimpleNamespace(call=SimpleNamespace(
        ClearChargingProfile=lambda **kw: SimpleNamespace(action="clear", payload=kw),
        GetCompositeSchedule=lambda **kw: SimpleNamespace(action="fetch", payload=kw)))
    monkeypatch.setitem(sys.modules, "ocpp.v16", protocol)
    result = await morek_schedule.async_schedule_action(hass, "charger", "clear", confirm_profile_id=42001)
    assert [request.action for request in calls] == ["clear", "fetch"]
    assert calls[0].payload == {"id": 42001}
    assert calls[1].payload["connector_id"] == 1
    assert result["cleanup"]["status"] == ("unknown" if reply_status == "timeout" else reply_status)
    assert result["verified"] is False
    assert result["effective"]["status"] == "Accepted"
    assert result["sent"] is data["profile"]
    assert store.async_save.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", [None, 0, 42002, True])
async def test_cleanup_refuses_missing_or_wrong_confirmation_before_any_station_access(confirmation):
    with pytest.raises(ScheduleRefused, match="cleanup_confirmation_required"):
        await morek_schedule.async_schedule_action(None, "charger", "clear", confirm_profile_id=confirmation)


def test_readback_preserves_reported_coverage_and_rejects_partial_or_invalid_periods():
    response = SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), charging_schedule={
        "duration": 43200, "chargingRateUnit": "A", "chargingSchedulePeriod": [
            {"startPeriod": 0, "limit": 0}, {"startPeriod": 3600, "limit": 16}]})
    actual = readback(response, NOW)
    assert actual["duration_s"] == 43200
    assert actual["schedule_start"] == NOW.isoformat()
    assert actual["rate_unit"] == "A"
    for invalid in [True, float("nan"), -1]:
        response.charging_schedule["chargingSchedulePeriod"][1]["limit"] = invalid
        assert readback(response, NOW)["periods"] == []
    response.charging_schedule["chargingSchedulePeriod"] = [{"startPeriod": 10, "limit": 0}]
    assert readback(response, NOW)["periods"] == []


def test_verification_requires_reported_duration_and_discloses_drift():
    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)
    actual = readback(SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), charging_schedule={
        "chargingRateUnit": "A", "duration": 14400, "chargingSchedulePeriod": [
            {"startPeriod": 0, "limit": 0}, {"startPeriod": 3657, "limit": 16},
            {"startPeriod": 7257, "limit": 0}]}), NOW)
    comparison = morek_schedule.compare_schedule(profile, actual)
    assert comparison["matched"] is True
    assert comparison["exact"] is False
    assert comparison["max_delta_s"] == 57
    assert comparison["reason"] == "matched_with_drift"
    actual["duration_s"] = None
    assert morek_schedule.compare_schedule(profile, actual)["reason"] == "coverage_missing"
    actual["duration_s"] = 7200
    assert morek_schedule.compare_schedule(profile, actual)["reason"] == "coverage_too_short"
    actual["duration_s"] = 14400
    actual["periods"][1]["at"] = (NOW + timedelta(seconds=3691)).isoformat()
    assert morek_schedule.compare_schedule(profile, actual)["matched"] is False


@pytest.mark.parametrize(("offset", "initial", "drift", "reason"), [
    (0, 0, 0, "matched"),
    (3700, 16, 0, "matched"),
    (3700, 16, 57, "matched_with_drift"),
    (3700, 16, 91, "limits_or_transitions_differ"),
    (3650, 16, 0, "coverage_boundary_ambiguous"),
    (7300, 0, 0, "no_remaining_transitions"),
    (3700, 0, 0, "limits_or_transitions_differ"),
])
def test_remaining_schedule_comparison(offset, initial, drift, reason):
    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)
    start = NOW + timedelta(seconds=offset)
    periods = [{"startPeriod": 0, "limit": initial}, {"startPeriod": 1, "limit": initial}]
    if offset == 0:
        periods += [{"startPeriod": 3600, "limit": 16}]
    if offset < 7200:
        periods += [{"startPeriod": 7200 + drift - offset, "limit": 0}]
    actual = readback(SimpleNamespace(status="Accepted", schedule_start=start.isoformat(), charging_schedule={
        "chargingRateUnit": "A", "duration": 14400, "chargingSchedulePeriod": periods}), start)
    comparison = morek_schedule.compare_schedule(profile, actual)
    assert comparison["reason"] == reason
    assert comparison["scope"] == "remaining"


def test_active_initial_limit_can_verify_remaining_stop():
    profile = profile_for(((NOW - timedelta(hours=1), NOW + timedelta(hours=1)),), 16, NOW, allow_active=True)
    actual = readback(SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), charging_schedule={
        "chargingRateUnit": "A", "duration": 10800, "chargingSchedulePeriod": [
            {"startPeriod": 0, "limit": 16}, {"startPeriod": 3600, "limit": 0}]}), NOW)
    assert morek_schedule.compare_schedule(profile, actual)["reason"] == "matched"


def test_stale_or_expired_composite_coverage_is_not_verified():
    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)
    response = SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), charging_schedule={
        "chargingRateUnit": "A", "duration": 14400, "chargingSchedulePeriod": [
            {"startPeriod": 0, "limit": 0}, {"startPeriod": 3600, "limit": 16},
            {"startPeriod": 7200, "limit": 0}]})
    stale = readback(response, NOW + timedelta(minutes=10))
    assert morek_schedule.compare_schedule(profile, stale)["reason"] == "coverage_stale"
    delayed = readback(response, NOW + timedelta(hours=5), requested_at=NOW)
    assert morek_schedule.compare_schedule(profile, delayed)["reason"] == "coverage_stale"


def _send_harness(monkeypatch, read_results):
    import asyncio
    from collections import deque

    profile = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),), 16, NOW)
    data = {}
    store = SimpleNamespace(async_save=AsyncMock())
    target = SimpleNamespace(connector_id=1)
    callbacks, cancelled, delays, calls, unload, requests = [], [], [], [], [], []
    clock = [NOW]
    results = deque(read_results)

    async def station_call(request):
        calls.append(request.action)
        requests.append(request)
        if request.action != "fetch":
            return SimpleNamespace(status="Accepted")
        result = results.popleft() if results else "mismatch"
        if result == "timeout":
            raise TimeoutError
        periods = [{"startPeriod": 0, "limit": 16}] if result == "mismatch" else [
            {"startPeriod": 0, "limit": 0}, {"startPeriod": 3600, "limit": 16},
            {"startPeriod": 7200, "limit": 0}]
        return SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), connector_id=1,
                               charging_schedule={"duration": 14400, "chargingRateUnit": "A",
                                                  "chargingSchedulePeriod": periods})

    def call_later(hass, delay, callback):
        index = len(callbacks)
        callbacks.append(callback)
        delays.append(delay)
        return lambda: cancelled.append(index)

    class Clock:
        now = staticmethod(lambda tz: clock[0])
        fromisoformat = staticmethod(datetime.fromisoformat)

    point = SimpleNamespace(call=station_call)
    entry = SimpleNamespace(entry_id="charger", async_on_unload=unload.append)
    hass = SimpleNamespace(data={morek_schedule._DATA_KEY: {"charger": (data, store, asyncio.Lock())}})
    settings = SimpleNamespace(pause=SimpleNamespace(choice="until_resumed"), revision=4)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "async_call_later", call_later)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda h, e: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda h, e: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda h, t: _supported_identity())
    from custom_components.spotnav.execution.command_admission import CommandAdmission
    admission = CommandAdmission(_legacy_ownership())
    monkeypatch.setattr(morek_schedule, "command_admission", lambda h: admission)
    ledger = MemoryOutcomes()
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda h: ledger)
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda h, t: point)
    monkeypatch.setattr(morek_schedule, "_state", AsyncMock(return_value=(data, store)))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: settings)))
    monkeypatch.setattr(morek_schedule, "_proposed_profile", lambda h, e, n: profile)
    protocol = SimpleNamespace(call=SimpleNamespace(
        SetChargingProfile=lambda **kw: SimpleNamespace(action="send", payload=kw),
        ClearChargingProfile=lambda **kw: SimpleNamespace(action="clear", payload=kw),
        GetCompositeSchedule=lambda **kw: SimpleNamespace(action="fetch", payload=kw)))
    monkeypatch.setitem(sys.modules, "ocpp.v16", protocol)
    return SimpleNamespace(hass=hass, data=data, callbacks=callbacks, cancelled=cancelled,
                           delays=delays, calls=calls, unload=unload, clock=clock, requests=requests,
                           preview_id=morek_schedule._preview_id(profile, 4), ledger=ledger, store=store, point=point,
                           settings=settings, entry=entry)


@pytest.mark.asyncio
@pytest.mark.parametrize("supersession", ["settings", "intent", "uncertain", "identity", "unload"])
async def test_inflight_readback_cannot_verify_superseded_attempt(monkeypatch, supersession):
    import asyncio

    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = h.point.call
    async def delayed(request):
        entered.set()
        await release.wait()
        return await original(request)
    h.point.call = delayed
    task = asyncio.create_task(h.callbacks[0](NOW))
    await entered.wait()
    if supersession == "settings":
        h.settings.revision += 1
    elif supersession == "intent":
        changed = profile_for(((NOW + timedelta(hours=1), NOW + timedelta(hours=3)),), 16, NOW)
        monkeypatch.setattr(morek_schedule, "_proposed_profile", lambda *_: changed)
    elif supersession == "uncertain":
        h.ledger.value["uncertain"] = True
        h.ledger.value["attempt"]["state"] = "uncertain"
    elif supersession == "identity":
        monkeypatch.setattr(morek_schedule, "_identity_status", lambda *_: {"supported": False})
    else:
        h.unload[0]()
    release.set()
    await task
    assert h.data["verified"] is False
    assert h.ledger.value["verified"] is None


@pytest.mark.asyncio
async def test_status_does_not_expose_old_match_as_current_after_settings_edit(monkeypatch):
    h = _send_harness(monkeypatch, ["matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    assert h.ledger.value["verified"] is not None
    h.settings.revision += 1
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value={})))
    monkeypatch.setattr(morek_schedule, "_preview", lambda *_: {})
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await morek_schedule.websocket_morek_schedule.__wrapped__(
        h.hass, connection, {"id": 1, "api_version": 1, "charger_id": "charger", "action": "status"})
    result = connection.send_result.call_args.args[1]["schedule"]
    assert result["verified"] is False
    assert result["outcomes"]["verified"] is None
    assert result["verification"]["reason"] == "verification_superseded"
    assert h.ledger.value["verified"] is not None  # Historical evidence is retained on disk.


@pytest.mark.asyncio
async def test_status_does_not_present_superseded_pending_mismatch_as_current(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    assert h.data["verification"]["pending"]
    h.settings.revision += 1
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value={})))
    monkeypatch.setattr(morek_schedule, "_preview", lambda *_: {})
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await morek_schedule.websocket_morek_schedule.__wrapped__(
        h.hass, connection, {"id": 1, "api_version": 1, "charger_id": "charger", "action": "status"})
    result = connection.send_result.call_args.args[1]["schedule"]
    assert result["verification"]["reason"] == "verification_superseded"
    assert result["verification"]["pending"] is False
    assert result["operator"]["state"] == "not_ready"


@pytest.mark.asyncio
async def test_settings_change_during_verified_evidence_write_is_discarded(monkeypatch):
    import asyncio

    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    previous_effective = h.data["effective"]
    entered, release = asyncio.Event(), asyncio.Event()
    write = h.ledger.write
    async def delayed(record):
        await write(record)
        if record.get("verified"):
            entered.set()
            await release.wait()
    h.ledger.write = delayed
    task = asyncio.create_task(h.callbacks[0](NOW))
    await entered.wait()
    h.settings.revision += 1
    release.set()
    await task
    assert h.data["verified"] is False
    assert h.ledger.value["verified"] is None
    assert h.data["effective"] is previous_effective


@pytest.mark.asyncio
async def test_settings_change_during_readback_store_save_is_discarded(monkeypatch):
    import asyncio

    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    previous = h.data["effective"]
    entered, release = asyncio.Event(), asyncio.Event()
    async def save(data):
        if data.get("verified"):
            entered.set()
            await release.wait()
    h.store.async_save.side_effect = save
    task = asyncio.create_task(h.callbacks[0](NOW))
    await entered.wait()
    h.settings.revision += 1
    release.set()
    await task
    assert h.data["verified"] is False
    assert h.data["effective"] is previous
    assert h.ledger.value["verified"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["send", "clear"])
async def test_queued_new_profile_action_supersedes_previous_read(monkeypatch, action):
    import asyncio

    h = _send_harness(monkeypatch, ["mismatch", "matched", "mismatch"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = h.point.call
    async def delayed(request):
        if request.action == "fetch" and not entered.is_set():
            entered.set()
            await release.wait()
        return await original(request)
    h.point.call = delayed
    read = asyncio.create_task(h.callbacks[0](NOW))
    await entered.wait()
    old_id = h.data["attempt_id"]
    h.clock[0] += timedelta(seconds=1)
    kwargs = {"confirm_profile_id": 42001} if action == "clear" else {"preview_id": h.preview_id}
    replacement = asyncio.create_task(morek_schedule.async_schedule_action(h.hass, "charger", action, **kwargs))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(read, replacement)
    assert h.data["verified"] is False
    assert h.ledger.value["verified"] is None
    if action == "send":
        assert h.ledger.value["attempt"]["id"] != old_id


@pytest.mark.asyncio
async def test_send_uses_displayed_shortened_blocks_not_whole_slot_ends(monkeypatch):
    real_proposed_profile = morek_schedule._proposed_profile
    h = _send_harness(monkeypatch, ["mismatch"])
    whole = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
             (NOW + timedelta(hours=4), NOW + timedelta(hours=5)))
    shown = (whole[0], (whole[1][0], NOW + timedelta(hours=4, minutes=17, seconds=12.8)))
    proposal = SimpleNamespace(has_plan=True, unpriced=False, periods=whole, shown_periods=shown)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    settings = SimpleNamespace(amps=16, revision=4, pause=SimpleNamespace(choice="until_resumed"))
    monkeypatch.setattr(morek_schedule, "_proposed_profile", real_proposed_profile)
    monkeypatch.setattr(morek_schedule, "preview_for", lambda hass, entry: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda hass: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda entry: settings)))
    preview = morek_schedule._preview(h.hass, "charger", None)
    assert preview["reason"] is None
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "send", preview["preview_id"])
    sent = h.requests[0].payload["cs_charging_profiles"]
    assert sent == preview["profile"] == result["sent"]
    assert [p["startPeriod"] for p in sent["chargingSchedule"]["chargingSchedulePeriod"]] == [
        0, 3600, 7200, 14400, 15432]
    assert [p["limit"] for p in sent["chargingSchedule"]["chargingSchedulePeriod"]] == [0, 16, 0, 16, 0]
    # Changing only the shown end invalidates a preview; no second upload is permitted.
    proposal.shown_periods = (whole[0], (whole[1][0], NOW + timedelta(hours=4, minutes=20)))
    with pytest.raises(ScheduleRefused, match="preview_changed"):
        await morek_schedule.async_schedule_action(h.hass, "charger", "send", preview["preview_id"])
    assert h.calls.count("send") == 1


@pytest.mark.parametrize("case", ["unpriced", "stale", "empty", "expired", "too_many"])
def test_shortened_windows_keep_existing_eligibility_guards(monkeypatch, case):
    periods = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),)
    shown = ((periods[0][0], periods[0][0] + timedelta(minutes=15)),)
    proposal = SimpleNamespace(has_plan=True, unpriced=case == "unpriced", periods=periods, shown_periods=shown)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=3 if case == "stale" else 4,
                               price_state="ready")
    if case == "empty":
        proposal.shown_periods = ()
    elif case == "expired":
        proposal.shown_periods = ((NOW - timedelta(minutes=5), NOW),)
    elif case == "too_many":
        proposal.shown_periods = tuple((shown[0][0] + timedelta(hours=i * 2), shown[0][1] + timedelta(hours=i * 2))
                                      for i in range(4))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: SimpleNamespace(amps=16, revision=4))))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda h, e: SimpleNamespace(
        snapshot=lambda: snapshot, snapshot_is_current=lambda _: True))
    with pytest.raises(ScheduleRefused):
        morek_schedule._proposed_profile(None, "charger", NOW)


@pytest.mark.asyncio
async def test_send_rechecks_delayed_activation_without_resending_or_clearing(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    assert result["verification"]["pending"] is True
    assert result["verified"] is False
    assert h.delays == [30]
    await h.callbacks[0](NOW)
    assert h.data["verified"] is True
    assert h.data["verification"]["pending"] is False
    assert h.calls == ["send", "fetch", "fetch"]


@pytest.mark.asyncio
async def test_immediately_matching_send_does_not_schedule_extra_reads(monkeypatch):
    h = _send_harness(monkeypatch, ["matched"])
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    assert result["verified"] is True
    assert result["verification"]["exact"] is True
    assert result["verification"]["pending"] is False
    assert result["outcomes"]["verified"]["fingerprint"] == h.preview_id
    assert result["outcomes"]["acknowledged"]["fingerprint"] == h.preview_id
    assert h.delays == []
    assert h.calls == ["send", "fetch"]


@pytest.mark.asyncio
async def test_temporary_offline_followup_retries_read_only_after_reconnect(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    online_charge_point = morek_schedule._charge_point

    def offline(hass, target):
        raise ScheduleRefused("morek_offline")

    monkeypatch.setattr(morek_schedule, "_charge_point", offline)
    await h.callbacks[0](NOW)
    assert h.data["verification"]["pending"] is True
    assert h.data["verification"]["reason"] == "readback_unavailable"
    monkeypatch.setattr(morek_schedule, "_charge_point", online_charge_point)
    await h.callbacks[1](NOW)
    assert h.data["verified"] is True
    assert h.calls == ["send", "fetch", "fetch"]


@pytest.mark.asyncio
async def test_followup_reads_stop_after_three_retries_and_keep_mismatch(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "timeout", "mismatch", "mismatch"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    for index in range(3):
        await h.callbacks[index](NOW)
    assert h.delays == [30, 45, 45]
    assert h.data["verification"]["pending"] is False
    assert h.data["verification"]["reason"] == "limits_or_transitions_differ"
    assert h.data["verified"] is False
    assert h.calls.count("send") == 1
    assert h.calls.count("fetch") == 4
    assert "clear" not in h.calls


@pytest.mark.asyncio
async def test_clear_and_unload_cancel_verification_and_stale_callback_does_nothing(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "mismatch"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    await morek_schedule.async_schedule_action(h.hass, "charger", "clear", confirm_profile_id=42001)
    before = list(h.calls)
    await h.callbacks[0](NOW)
    assert h.calls == before
    assert h.cancelled == [0]
    assert h.data["verification"]["pending"] is False

    h = _send_harness(monkeypatch, ["mismatch"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    h.unload[0]()
    await h.callbacks[0](NOW)
    assert h.calls == ["send", "fetch"]
    status = morek_schedule._verification_state(h.hass, "charger", h.data)
    assert status["pending"] is False
    assert status["reason"] == "verification_interrupted"


@pytest.mark.asyncio
async def test_new_send_invalidates_old_verification_without_losing_new_timer(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    old_sent_at = h.data["sent_at"]
    h.clock[0] += timedelta(seconds=1)
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    await h.callbacks[0](NOW)
    assert h.calls == ["send", "fetch", "send", "fetch"]
    with pytest.raises(ScheduleRefused, match="verification_superseded"):
        await morek_schedule.async_schedule_action(h.hass, "charger", "fetch", expected_sent_at=old_sent_at)
    await h.callbacks[1](NOW)
    assert h.data["verified"] is True


@pytest.mark.asyncio
async def test_manual_matching_fetch_cancels_followup_and_restart_does_not_claim_pending(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "fetch")
    assert result["verified"] is True
    assert h.cancelled == [0]
    await h.callbacks[0](NOW)
    assert h.calls == ["send", "fetch", "fetch"]
    h.data["verification"]["pending"] = True
    assert morek_schedule._verification_state(h.hass, "charger", h.data)["pending"] is False


@pytest.mark.asyncio
async def test_refresh_cannot_resolve_or_verify_uncertain_profile_action(monkeypatch):
    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    h.ledger.value["uncertain"] = True
    h.ledger.value["attempt"]["state"] = "uncertain"
    result = await morek_schedule.async_schedule_action(h.hass, "charger", "fetch")
    assert h.calls == ["send", "fetch", "fetch"]
    assert result["verified"] is False
    assert result["verification"]["reason"] == "outcome_uncertain"
    assert result["outcomes"]["uncertain"] is True


@pytest.mark.asyncio
async def test_pending_inflight_read_is_not_interrupted_and_unload_prevents_more_timers(monkeypatch):
    import asyncio

    h = _send_harness(monkeypatch, ["mismatch", "matched"])
    await morek_schedule.async_schedule_action(h.hass, "charger", "send", h.preview_id)
    point = morek_schedule._charge_point(h.hass, None)
    original_call = point.call
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_call(request):
        entered.set()
        await release.wait()
        return await original_call(request)

    point.call = blocked_call
    task = asyncio.create_task(h.callbacks[0](NOW))
    await entered.wait()
    assert morek_schedule._verification_state(h.hass, "charger", h.data)["pending"] is True
    h.unload[0]()
    release.set()
    await task
    assert morek_schedule._verification_state(h.hass, "charger", h.data)["pending"] is False
    assert len(h.callbacks) == 1
