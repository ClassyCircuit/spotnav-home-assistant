"""Read-only Morek readiness uses connector-scoped, fresh observations only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.vehicles import ocpp_identity

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(("raw", "vehicle"), [
    ("Available", "disconnected"), ("Preparing", "connected"),
    ("Charging", "connected"), ("SuspendedEV", "connected"),
    ("Unavailable", "unknown"), ("Faulted", "unknown"),
    ("Rejected", "unknown"), ("unknown", "unknown"),
])
def test_connector_status_is_not_authorization_or_measurement(monkeypatch, raw, vehicle):
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", lambda *_: "sensor.connector")
    state = SimpleNamespace(state=raw, last_updated=NOW)
    states = {"switch.control": SimpleNamespace(state="on"), "sensor.connector": state}
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=states.get)))
    controller = SimpleNamespace(charge_control="switch.control", ocpp_target=object())
    result = morek_schedule._session_readiness(hass, controller, {"supported": True, "match_count": 1}, True, NOW)
    assert result["vehicle"] == vehicle
    assert result["control"] == "available"
    assert result["transaction"] == result["measurement"] == "unknown"
    assert result["session_start"] == {"state": "blocked", "reason": "authorization_path_unimplemented"}
    assert "production_dispatch_unarmed" in result["activation_blockers"]
    assert {"held_exit_has_no_release", "external_writers_unverified",
            "installation_protection_conflict_unresolved", "activation_path_incomplete",
            "first_use_or_lost_state_unverified", "retained_profile_unresolved"} <= set(result["activation_blockers"])


@pytest.mark.parametrize("age", [181, -1, None])
def test_stale_future_and_missing_timestamp_are_unknown(monkeypatch, age):
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", lambda *_: "sensor.connector")
    ts = None if age is None else NOW - timedelta(seconds=age)
    states = {"switch.control": SimpleNamespace(state="on"),
              "sensor.connector": SimpleNamespace(state="Available", last_updated=ts)}
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=states.get)))
    result = morek_schedule._session_readiness(hass, SimpleNamespace(charge_control="switch.control", ocpp_target=object()),
                                                {"supported": True, "match_count": 1}, True, NOW)
    assert result["vehicle"] == "unknown"


def test_offline_unrelated_and_missing_control_never_read_vehicle(monkeypatch):
    sensor = Mock(side_effect=AssertionError("must not resolve a connector"))
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", sensor)
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(return_value=None)))
    controller = SimpleNamespace(charge_control="switch.control", ocpp_target=object())
    for identity, online, expected in [({"supported": False, "match_count": 1}, True, "unknown"),
                                       ({"supported": True, "match_count": 2}, True, "unknown"),
                                       ({"supported": True, "match_count": 0}, False, "unavailable"),
                                       ({"supported": True, "match_count": 1}, False, "unavailable"),
                                       ({"supported": True, "match_count": 1}, True, "unavailable")]:
        result = morek_schedule._session_readiness(hass, controller, identity, online, NOW)
        assert result["control"] == expected and result["vehicle"] == "unknown"
    sensor.assert_not_called()


def test_offline_start_status_does_not_claim_authorization():
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=AssertionError("no state reads"))))
    result = morek_schedule._session_readiness(
        hass, object(), {"supported": True, "match_count": 1}, False, NOW
    )
    assert result["session_start"] == {"state": "offline", "reason": "charger_offline"}
    assert result["transaction"] == result["measurement"] == "unknown"
