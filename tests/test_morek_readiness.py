"""Read-only Morek readiness uses connector-scoped, fresh observations only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.helpers import entity_registry as er

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


# ------------------------------------------------------------------ Stage 5.7b2 live observations
def _live_hass(monkeypatch, states, energy_entity=None):
    """Mock boundary: status/current by key; energy by the strict lookup answering `energy_entity`."""
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id",
                        lambda _h, _t, key: f"sensor.{key}")
    monkeypatch.setattr(ocpp_identity, "connector_measurand_entity",
                        lambda *_: ocpp_identity.MeasurandLookup(energy_entity, "bound" if energy_entity else "none"))
    monkeypatch.setattr(ocpp_identity, "_classes_allow_register", lambda *_: True)
    return SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=states.get)))


def _sensor(state, ts=NOW, **attributes):
    return SimpleNamespace(state=state, last_updated=ts, last_reported=ts, attributes=attributes)


def _readiness(hass, connector=1, **controller_attrs):
    controller = SimpleNamespace(charge_control="switch.control", **controller_attrs,
                                 ocpp_target=SimpleNamespace(connector_id=connector))
    return morek_schedule._session_readiness(hass, controller, {"supported": True, "match_count": 1}, True, NOW)


def test_live_block_binds_connector_status_current_power_and_energy(monkeypatch):
    states = {"switch.control": _sensor("on"),
              "sensor.status_connector": _sensor("Charging"),
              "sensor.current_import": _sensor("15.5", unit_of_measurement="A"),
              "sensor.configured_power": _sensor("3.5", device_class="power", unit_of_measurement="kW"),
              "sensor.energy": _sensor("12000", unit_of_measurement="Wh")}
    live = _readiness(_live_hass(monkeypatch, states, "sensor.energy"), connector=2,
                      power_entity_id="sensor.configured_power")["live"]
    assert live["connector_id"] == 2
    assert live["status"]["value"] == "Charging" and live["status"]["normalized"] == "charging" and live["status"]["fresh"]
    assert live["current_a"] == {"value": 15.5, "unit": "A", "observed_at": NOW.isoformat(), "fresh": True}
    assert live["power_w"]["value"] == 3500.0 and live["sources"] == {"power": "configured_entity", "energy": "ocpp_registry"}
    assert live["energy_register_kwh"]["value"] == 12.0


def test_live_measured_flag_requires_fresh_flow_not_status(monkeypatch):
    states = {"switch.control": _sensor("on"), "sensor.status_connector": _sensor("Charging")}
    result = _readiness(_live_hass(monkeypatch, states))
    assert result["measurement"] == "unknown" and result["live"]["current_a"] is None
    states["sensor.current_import"] = _sensor("0", unit_of_measurement="A")
    result = _readiness(_live_hass(monkeypatch, states))
    assert result["measurement"] == "measured" and result["live"]["current_a"]["value"] == 0.0  # a real zero
    assert result["transaction"] == "unknown" and result["session_start"]["reason"] == "authorization_path_unimplemented"


def test_live_stale_future_unavailable_and_bad_values_are_never_fresh_or_invented(monkeypatch):
    old = NOW - timedelta(seconds=400)
    states = {"switch.control": _sensor("on"),
              "sensor.current_import": _sensor("10", old),
              "sensor.configured_power": _sensor("unavailable", device_class="power", unit_of_measurement="W"),
              "sensor.energy": _sensor("12", NOW + timedelta(seconds=60), unit_of_measurement="kWh")}
    result = _readiness(_live_hass(monkeypatch, states, "sensor.energy"), power_entity_id="sensor.configured_power")
    assert result["live"]["current_a"]["fresh"] is False and result["measurement"] == "unknown"
    assert result["live"]["power_w"] is None
    assert result["live"]["energy_register_kwh"]["fresh"] is False  # future stamp
    for bad in ("nan", "inf", "-3", "abc"):
        states["sensor.energy"] = _sensor(bad, unit_of_measurement="kWh")
        assert _readiness(_live_hass(monkeypatch, states, "sensor.energy"))["live"]["energy_register_kwh"] is None
    states["sensor.energy"] = _sensor("5", unit_of_measurement="MWh")  # unit unknown: not guessed
    assert _readiness(_live_hass(monkeypatch, states, "sensor.energy"))["live"]["energy_register_kwh"] is None


def test_live_missing_timestamp_and_offline_are_unknown(monkeypatch):
    states = {"switch.control": _sensor("on"), "sensor.current_import": _sensor("8", None)}
    assert _readiness(_live_hass(monkeypatch, states))["live"]["current_a"] is None
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=AssertionError("offline reads nothing"))))
    result = morek_schedule._session_readiness(hass, object(), {"supported": True, "match_count": 1}, False, NOW)
    assert result["live"] is None and result["measurement"] == "unknown"


# ------------------------------------------------------------------ strict connector measurand binding
class _Registry:
    """A registry boundary holding real `RegistryEntry` objects (no HA runtime needed)."""

    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        return next((e.entity_id for e in self.entities.values()
                     if (e.domain, e.platform, e.unique_id) == (domain, platform, unique_id)), None)


_NONE_FIELDS = ("capabilities", "config_entry_id", "config_subentry_id", "created_at", "device_id", "entity_category",
                "has_entity_name", "hidden_by", "id", "object_id_base", "options", "original_device_class",
                "original_icon", "original_name", "suggested_object_id", "supported_features", "translation_key",
                "unit_of_measurement")


def _entry(unique_id, *, platform="ocpp", domain="sensor", disabled=None):
    entity_id = f"{domain}.{unique_id.replace('.', '_')}"
    return er.RegistryEntry(entity_id=entity_id, unique_id=unique_id, platform=platform, disabled_by=disabled,
                            **{f: None for f in _NONE_FIELDS})


def _lookup(monkeypatch, entries, connector, key=ocpp_identity.POWER_ACTIVE_IMPORT_KEY, cpid="cp"):
    registry = _Registry(entries)
    monkeypatch.setattr(er, "async_get", lambda _hass: registry)
    hass = SimpleNamespace(states=SimpleNamespace(get=Mock(return_value=None)))
    return ocpp_identity.connector_measurand_entity(hass, ocpp_identity.OcppConnectorTarget(cpid, connector), key)


def _two_connectors():
    return [_entry("switch.ocpp.cp.conn1.charge_control", domain="switch"),
            _entry("switch.ocpp.cp.conn2.charge_control", domain="switch"),
            _entry("ocpp.cp.conn1.power_active_import.sensor"), _entry("ocpp.cp.conn2.power_active_import.sensor")]


def test_registry_power_is_bound_to_each_connector_separately(monkeypatch):
    entries = _two_connectors() + [_entry("ocpp.cp.power_active_import.sensor")]  # a station-wide flat sensor
    one = _lookup(monkeypatch, entries, 1)
    two = _lookup(monkeypatch, entries, 2)
    assert (one.status, one.entity_id) == ("bound", "sensor.ocpp_cp_conn1_power_active_import_sensor")
    assert (two.status, two.entity_id) == ("bound", "sensor.ocpp_cp_conn2_power_active_import_sensor")


def test_registry_power_never_borrows_another_connector_or_charge_point(monkeypatch):
    entries = [_entry("ocpp.cp.conn2.power_active_import.sensor"), _entry("ocpp.other.conn1.power_active_import.sensor")]
    assert _lookup(monkeypatch, entries, 1).status == "none"


def test_registry_flat_power_counts_only_for_a_single_connector_charge_point(monkeypatch):
    flat = _entry("ocpp.cp.power_active_import.sensor")
    single = [_entry("switch.ocpp.cp.charge_control", domain="switch"), flat]
    assert _lookup(monkeypatch, single, 1).entity_id == flat.entity_id
    assert _lookup(monkeypatch, single, 2).status == "none"
    multi = [_entry("switch.ocpp.cp.conn1.charge_control", domain="switch"), flat]
    assert _lookup(monkeypatch, multi, 1).status == "none"  # flat on a multi-connector station is not connector 1's
    assert _lookup(monkeypatch, [flat], 1).status == "none"  # connector count unknown: no assumption


def test_registry_power_ambiguity_and_absence_answer_no_entity(monkeypatch):
    dup = [_entry("ocpp.cp.conn1.power_active_import.sensor"), _entry("sensor.ocpp.cp.conn1.power_active_import")]
    result = _lookup(monkeypatch, dup, 1)
    assert (result.entity_id, result.status) == (None, "ambiguous")
    assert _lookup(monkeypatch, [], 1) == ocpp_identity.MeasurandLookup(None, "none")


def test_registry_power_ignores_other_measurands_platforms_and_disabled_entities(monkeypatch):
    entries = [_entry("ocpp.cp.conn1.power_offered.sensor"), _entry("ocpp.cp.conn1.power_active_export.sensor"),
               _entry("ocpp.cp.conn1.current_import.sensor"),
               _entry("ocpp.cp.conn1.power_active_import.sensor", platform="other"),
               _entry("sensor.ocpp.cp.conn1.power_active_import", disabled=er.RegistryEntryDisabler.USER)]
    assert _lookup(monkeypatch, entries, 1).status == "none"
    spelled = [_entry("ocpp.cp.conn1.Power.Active.Import.sensor")]  # a dotted spelling still names the measurand
    assert _lookup(monkeypatch, spelled, 1).status == "bound"


def _full_hass(monkeypatch, entries, states):
    registry = _Registry(entries)
    monkeypatch.setattr(er, "async_get", lambda _hass: registry)
    return SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=states.get)))


def _real_readiness(hass, connector=1, **attrs):
    controller = SimpleNamespace(charge_control="switch.control", **attrs,
                                 ocpp_target=ocpp_identity.OcppConnectorTarget("cp", connector))
    return morek_schedule._session_readiness(hass, controller, {"supported": True, "match_count": 1}, True, NOW)


def _power(value, ts=NOW):
    return _sensor(value, ts, device_class="power", unit_of_measurement="W")


def _energy(value):
    return _sensor(value, device_class="energy", state_class="total_increasing", unit_of_measurement="kWh")


def test_live_power_and_energy_come_from_the_registry_bound_connector_only(monkeypatch):
    entries = _two_connectors() + [_entry("ocpp.cp.conn1.energy_active_import_register.sensor"),
                                   _entry("ocpp.cp.conn2.energy_active_import_register.sensor")]
    states = {"switch.control": _sensor("on"),
              "sensor.ocpp_cp_conn1_power_active_import_sensor": _power("1000"),
              "sensor.ocpp_cp_conn2_power_active_import_sensor": _power("0"),
              "sensor.ocpp_cp_conn1_energy_active_import_register_sensor": _energy("11"),
              "sensor.ocpp_cp_conn2_energy_active_import_register_sensor": _energy("22")}
    hass = _full_hass(monkeypatch, entries, states)
    two = _real_readiness(hass, 2)["live"]
    assert two["power_w"]["value"] == 0.0 and two["energy_register_kwh"]["value"] == 22.0  # a real 0, not conn 1's
    assert two["sources"] == {"power": "ocpp_registry", "energy": "ocpp_registry"}
    one = _real_readiness(hass, 1)
    assert one["live"]["power_w"]["value"] == 1000.0 and one["measurement"] == "measured"


def test_live_power_is_null_for_ambiguous_missing_stale_and_wrongly_classed_sources(monkeypatch):
    key = "sensor.ocpp_cp_conn1_power_active_import_sensor"
    base = {"switch.control": _sensor("on")}
    ambiguous = _full_hass(monkeypatch, [_entry("ocpp.cp.conn1.power_active_import.sensor"),
                                         _entry("sensor.ocpp.cp.conn1.power_active_import")],
                           {**base, key: _power("900"), "sensor.sensor_ocpp_cp_conn1_power_active_import": _power("5")})
    result = _real_readiness(ambiguous)
    assert result["live"]["power_w"] is None and result["live"]["sources"]["power"] == "ambiguous"
    assert result["measurement"] == "unknown"
    missing = _full_hass(monkeypatch, [], base)
    assert _real_readiness(missing)["live"]["sources"]["power"] == "none"
    entries = [_entry("ocpp.cp.conn1.power_active_import.sensor")]
    stale = _full_hass(monkeypatch, entries, {**base, key: _power("900", NOW - timedelta(seconds=500))})
    result = _real_readiness(stale)
    assert result["live"]["power_w"]["fresh"] is False and result["measurement"] == "unknown"
    wrong = _full_hass(monkeypatch, entries, {**base, key: _sensor("900", unit_of_measurement="W")})  # no device class
    assert _real_readiness(wrong)["live"]["power_w"] is None


def test_live_status_and_current_do_not_read_another_connector(monkeypatch):
    entries = _two_connectors()
    states = {"switch.control": _sensor("on"), "sensor.cp_connector_1_status_connector": _sensor("Charging"),
              "sensor.cp_connector_1_current_import": _sensor("10", unit_of_measurement="A")}
    live = _real_readiness(_full_hass(monkeypatch, entries, states), 2)["live"]
    assert live["status"] is None and live["current_a"] is None  # connector 2 has no sensors of its own
    live = _real_readiness(_full_hass(monkeypatch, entries, states), 1)["live"]
    assert live["status"]["normalized"] == "charging" and live["current_a"]["value"] == 10.0


def test_live_configured_power_entity_is_preferred_and_labelled(monkeypatch):
    states = {"switch.control": _sensor("on"),
              "sensor.plug": _sensor("2", device_class="power", unit_of_measurement="kW")}
    live = _real_readiness(_full_hass(monkeypatch, _two_connectors(), states), power_entity_id="sensor.plug")["live"]
    assert live["power_w"]["value"] == 2000.0 and live["sources"]["power"] == "configured_entity"
