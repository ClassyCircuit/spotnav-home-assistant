"""A Morek profile must never silently extend or truncate the planned charging windows."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock
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
    morek = SimpleNamespace(_ocpp_version="1.6", status="ok")
    system = SimpleNamespace(cpids={"garage": "3020002509120029"},
                             charge_points={"3020002509120029": morek})
    hass = SimpleNamespace(data={"ocpp": {"entry": system}})
    target = SimpleNamespace(devid="garage", connector_id=1)
    assert _identity_status(hass, target)["supported"] is True
    assert _identity_status(hass, target)["resolved_id"] == "3020002509120029"
    assert _charge_point(hass, target) is morek

    system.cpids["garage"] = "other_station"
    system.charge_points["other_station"] = SimpleNamespace(_ocpp_version="1.6", status="ok")
    assert _identity_status(hass, target)["supported"] is False
    with pytest.raises(ScheduleRefused):
        _charge_point(hass, target)

    system.cpids.clear()
    system.charge_points.clear()
    assert _identity_status(hass, target)["reason"] == "station_not_matched"
    assert _identity_status(hass, None)["reason"] == "no_ocpp_target"


def test_preview_reuses_send_calculation_without_contacting_station(monkeypatch):
    periods = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),)
    proposal = SimpleNamespace(has_plan=True, unpriced=False, periods=periods, shown_periods=periods)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4)
    settings = SimpleNamespace(amps=16, revision=4, pause=SimpleNamespace(choice="until_resumed"))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda hass: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda entry: settings)))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda hass, entry: SimpleNamespace(snapshot=lambda: snapshot))
    point = SimpleNamespace(_ocpp_version="1.6", status="ok")
    hass = SimpleNamespace(data={"ocpp": {"entry": SimpleNamespace(
        cpids={"garage": "3020002509120029"}, charge_points={"3020002509120029": point})}})
    target = SimpleNamespace(devid="garage", connector_id=1)
    expected = morek_schedule._proposed_profile(hass, "charger", NOW)
    assert [p["limit"] for p in expected["chargingSchedule"]["chargingSchedulePeriod"]] == [0, 16, 0]
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
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda h, e: (SimpleNamespace(entry_id=e), None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda h, e: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda h, t: {"supported": True})
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
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda h, t: {"supported": True})
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
                           preview_id=morek_schedule._preview_id(profile, 4))


@pytest.mark.asyncio
async def test_send_uses_displayed_shortened_blocks_not_whole_slot_ends(monkeypatch):
    real_proposed_profile = morek_schedule._proposed_profile
    h = _send_harness(monkeypatch, ["mismatch"])
    whole = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
             (NOW + timedelta(hours=4), NOW + timedelta(hours=5)))
    shown = (whole[0], (whole[1][0], NOW + timedelta(hours=4, minutes=17, seconds=12.8)))
    proposal = SimpleNamespace(has_plan=True, unpriced=False, periods=whole, shown_periods=shown)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4)
    settings = SimpleNamespace(amps=16, revision=4, pause=SimpleNamespace(choice="until_resumed"))
    monkeypatch.setattr(morek_schedule, "_proposed_profile", real_proposed_profile)
    monkeypatch.setattr(morek_schedule, "preview_for", lambda hass, entry: SimpleNamespace(snapshot=lambda: snapshot))
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


@pytest.mark.parametrize("case", ["unpriced", "stale", "empty", "past", "too_many"])
def test_shortened_windows_keep_existing_eligibility_guards(monkeypatch, case):
    periods = ((NOW + timedelta(hours=1), NOW + timedelta(hours=2)),)
    shown = ((periods[0][0], periods[0][0] + timedelta(minutes=15)),)
    proposal = SimpleNamespace(has_plan=True, unpriced=case == "unpriced", periods=periods, shown_periods=shown)
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=3 if case == "stale" else 4)
    if case == "empty":
        proposal.shown_periods = ()
    elif case == "past":
        proposal.shown_periods = ((NOW - timedelta(minutes=5), NOW + timedelta(minutes=15)),)
    elif case == "too_many":
        proposal.shown_periods = tuple((shown[0][0] + timedelta(hours=i * 2), shown[0][1] + timedelta(hours=i * 2))
                                      for i in range(4))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda h: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda e: SimpleNamespace(amps=16, revision=4))))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda h, e: SimpleNamespace(snapshot=lambda: snapshot))
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
