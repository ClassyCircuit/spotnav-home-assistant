"""A Morek profile must never silently extend or truncate the planned charging windows."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

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
