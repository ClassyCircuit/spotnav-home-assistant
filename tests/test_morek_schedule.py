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
    assert morek_schedule._preview(hass, "charger", target)["reason"] == "target_stop_unsupported"


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
