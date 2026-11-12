"""Fast actual SOC reader and dashboard-contract tests, with mocked HA boundaries."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.spotnav.api import dashboard
from custom_components.spotnav.execution import target_stop
from custom_components.spotnav.vehicles.soc_estimate import SocAnchor, SocReader, is_fresh, resolve_soc
from custom_components.spotnav.vehicles import soc_estimate


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


def test_soc_watch_notifies_for_new_vehicle_report_not_unchanged_ha_write():
    reader = object.__new__(SocReader)
    report = NOW - timedelta(days=1)
    old = target_stop.SocReading(42, "vehicle", "sensor.soc", "car", 86400,
                                 time_basis="vehicle_timestamp", reported_at=report)
    reader._last_reading = old
    reader._last_signal_reading = old
    reader._anchor = None
    reader._watch_vehicle = "car"
    reader._watched_report_time = "sensor.report_time"
    reader._last_notified = 42
    reader._notify_next = False
    reader._notify_every_reading = lambda: True
    reader._drop_arrival = lambda: None
    calls = []
    reader._on_reading = lambda: calls.append("replan")
    reader._on_source_unavailable = None
    reader._note_source_state = lambda _: None
    current = [old]
    def read(_vehicle):
        reader._last_reading = current[0]
        return current[0]
    reader.read = read
    event = SimpleNamespace(data={"entity_id": "sensor.soc", "old_state": SimpleNamespace(state="42"),
                                  "new_state": SimpleNamespace(state="42")})
    reader._on_source_changed(event)
    assert calls == []
    current[0] = target_stop.SocReading(42, "vehicle", "sensor.soc", "car", 60,
                                      time_basis="vehicle_timestamp", reported_at=NOW - timedelta(minutes=1))
    reader._last_reading = current[0]  # a dashboard read happened before the event
    reader._anchor = SocAnchor(42, 100, current[0].reported_at, "vehicle", "car", "sensor.energy", time_basis="vehicle_timestamp")
    event.data["entity_id"] = "sensor.report_time"
    reader._on_source_changed(event)
    assert calls == ["replan"]
    current[0] = target_stop.SocReading(42, "charger", "sensor.charger", None, 3)
    event.data["entity_id"] = "sensor.soc"
    reader._on_source_changed(event)
    assert calls == ["replan", "replan"]
    reader._on_source_changed(event)
    assert calls == ["replan", "replan"]


def test_watch_subscribes_to_vehicle_report_time_sensor(monkeypatch):
    reader = object.__new__(SocReader)
    reader._closed = False
    reader._hass = object()
    reader._charge_control = lambda: "control"
    reader._watch_vehicle = None
    reader._watched = ()
    reader._watch_cancel = None
    monkeypatch.setattr(soc_estimate, "vehicle_soc_entity_id", lambda *_: "sensor.soc")
    monkeypatch.setattr(soc_estimate, "charger_soc_entity_id", lambda *_: None)
    monkeypatch.setattr(soc_estimate, "report_time_entity_id", lambda *_: "sensor.report_time")
    watched = []
    monkeypatch.setattr(soc_estimate, "async_track_state_change_event", lambda _, ids, cb: watched.extend(ids) or (lambda: None))
    reader.ensure_watch("car")
    assert watched == ["sensor.soc", "sensor.report_time"]
