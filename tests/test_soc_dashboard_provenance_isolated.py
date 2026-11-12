"""Fast actual SOC reader and dashboard-contract tests, with mocked HA boundaries."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.spotnav.api import dashboard
from custom_components.spotnav.execution import target_stop
from custom_components.spotnav.vehicles.soc_estimate import SocAnchor, SocReader, is_fresh, resolve_soc


NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def test_real_reader_prefers_old_vehicle_report_over_recent_ha_write(monkeypatch):
    state = SimpleNamespace(last_updated=NOW - timedelta(seconds=5))
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: state))
    monkeypatch.setattr(target_stop.dt_util, "utcnow", lambda: NOW)
    monkeypatch.setattr(target_stop, "valid_soc_percent", lambda _: 42.0)
    monkeypatch.setattr(target_stop, "vehicle_report_time", lambda *_: ("sensor.time", NOW - timedelta(minutes=23)))
    reading = target_stop.resolve_soc_reading(hass, vehicle_id="car", entity_id="sensor.soc")
    assert reading.age_s == 1380 and reading.state_age_s == 5
    assert reading.time_basis == "vehicle_timestamp" and not is_fresh(reading)
    monkeypatch.setattr(target_stop, "vehicle_report_time", lambda *_: None)
    assert target_stop.resolve_soc_reading(hass, vehicle_id="car", entity_id="sensor.soc").time_basis == "last_updated"


def test_restored_and_estimated_readings_keep_anchor_age():
    anchor = SocAnchor(42, 100, NOW - timedelta(hours=1), "vehicle", "car", "sensor.energy")
    raw = target_stop.SocReading(42, "vehicle", "sensor.soc", "car", 2, restored=True)
    args = dict(reading=raw, anchor=anchor, capacity_kwh=60, now=NOW, vehicle_id="car",
                register_entity_id="sensor.energy", plugged_in_throughout=True)
    restored = resolve_soc(register_kwh=100, **args).reading
    assert restored.restored and restored.time_basis == "anchor" and restored.age_s == 3600
    assert not is_fresh(restored)
    estimate = resolve_soc(register_kwh=103, **args).reading
    assert estimate.estimated and estimate.restored and estimate.age_s == 3600
    assert estimate.soc_percent > 42


def test_unavailable_sensor_exposes_only_matching_retained_anchor():
    anchor = SocAnchor(42, 100, NOW - timedelta(hours=1), "vehicle", "car", "sensor.energy", time_basis="vehicle_timestamp")
    missing = target_stop.SocReading(None, "vehicle", "sensor.soc", "car", 2)
    fake = SimpleNamespace(_last_reading=missing, _anchor=anchor, _last_vehicle_id="car", _now=lambda: NOW)
    reading = SocReader.last_reported_reading.fget(fake)
    assert reading.soc_percent == 42 and reading.age_s == 3600 and reading.restored
    assert reading.time_basis == "vehicle_timestamp"
    fake._last_vehicle_id = "other"
    assert SocReader.last_reported_reading.fget(fake) is missing


def test_capture_and_serialize_keep_raw_and_effective_separate(monkeypatch):
    raw = target_stop.SocReading(42, "vehicle", "sensor.soc", "car", 1380, time_basis="vehicle_timestamp")
    estimate = target_stop.SocReading(45, "vehicle", "sensor.soc", "car", 1380, estimated=True, time_basis="anchor")
    reader = SimpleNamespace(has_source=lambda _: True, vehicle_max_percent=lambda _: None, read=lambda _: estimate,
                             capacity_kwh=lambda _: 60, vehicle_name=lambda _: "Vehicle", last_raw_reading=raw)
    monkeypatch.setattr(dashboard, "charger_data", lambda *_: SimpleNamespace(soc_reader=reader))
    monkeypatch.setattr(dashboard, "resolve_target_vehicle", lambda *_: ("car", []))
    monkeypatch.setattr(dashboard, "preview_for", lambda *_: None)
    monkeypatch.setattr(dashboard.er, "async_get", lambda _: SimpleNamespace(async_get=lambda _: SimpleNamespace(platform="bavariandata")))
    settings = SimpleNamespace(target=SimpleNamespace(vehicle_id="car", target_percent=80), vehicle_ids=None)
    captured = dashboard.capture_soc(object(), "charger", settings)
    assert dashboard.serialize_soc(captured)["value"] == 45
    observation = dashboard.serialize_soc_observation(captured)
    assert observation == {"time_basis": "anchor", "restored": False, "integration": "bavariandata",
                           "raw_value": 42, "raw_age_s": 1380, "raw_time_basis": "vehicle_timestamp", "raw_source": "vehicle", "raw_retained": False}
    reader.last_raw_reading = target_stop.SocReading(101, "charger", "sensor.other", None, 3)
    assert dashboard.serialize_soc_observation(dashboard.capture_soc(object(), "charger", settings))["raw_value"] is None
    assert dashboard.serialize_soc_observation(None) is None
