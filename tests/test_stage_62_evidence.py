"""Stage 6.2: sent-plan versions and genuine measurement capture, kept apart.

Actual evidence store, send path and capture; HA entities, OCPP and storage are the usual mocked boundaries.
Nothing here proves what the installed Morek or BMW exposes, or that a car charged.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_62_evidence.py
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.sessions import evidence as ev
from custom_components.spotnav.vehicles import ocpp_identity
from custom_components.spotnav.api import morek_schedule
from .test_morek_worker import drain, setup

T0 = datetime(2026, 11, 13, 23, 50, tzinfo=timezone.utc)


class MemBackend:
    """HA `Store` boundary: delayed save writes JSON on flush, load returns what was flushed."""

    def __init__(self, doc=None):
        self.doc, self.func = doc, None

    async def async_load(self):
        return self.doc

    def async_delay_save(self, func, _delay):
        self.func = func

    async def async_save(self, doc):
        self.doc = json.loads(json.dumps(doc))

    def flush(self):
        if self.func is not None:
            self.doc = json.loads(json.dumps(self.func()))


def make_store(backend=None, clock=None):
    backend = backend or MemBackend()
    return ev.ChargingEvidenceStore(SimpleNamespace(data={}), store=backend, now=clock or (lambda: T0)), backend


PROFILE = {"chargingProfileId": 1, "chargingSchedule": {"startSchedule": "2026-11-13T22:00:00+00:00",
                                                          "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 16}]}}


# ---- plan versions and command evidence --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_versions_are_immutable_ordered_bounded_and_survive_restart():
    store, backend = make_store()
    await store.async_load()
    first = dict(PROFILE)
    assert store.record_plan("c", plan_id="a1", fingerprint="f1", profile=first, intent_at="x", source="worker",
                             intent="schedule", revision=3) == ev.ADDED
    first["chargingProfileId"] = 999  # the caller's object changing later never changes the kept version
    assert store.record_plan("c", plan_id="a1", fingerprint="OTHER", profile={"x": 1}, intent_at="y", source="manual",
                             intent="schedule") == ev.DUPLICATE
    store.record_plan("c", plan_id="a2", fingerprint="f2", profile={**PROFILE, "chargingProfileId": 2},
                      intent_at="z", source="worker", intent="schedule")
    store.record_event("c", "ack", plan_id="a1", status="accepted")
    stored = store.plan_versions("c")
    assert [p["id"] for p in stored] == ["a1", "a2"] and stored[0]["profile"]["chargingProfileId"] == 1
    assert stored[0]["fingerprint"] == "f1" and stored[0]["revision"] == 3
    stored[0]["profile"]["chargingProfileId"] = 5  # reads are copies
    assert store.plan_version("c", "a1")["profile"]["chargingProfileId"] == 1
    backend.flush()
    again, _ = make_store(backend)
    await again.async_load()  # a restart: the original plan is still the original, the later replan is separate
    assert [p["id"] for p in again.plan_versions("c")] == ["a1", "a2"]
    assert again.plan_version("c", "a1")["profile"]["chargingProfileId"] == 1
    assert [e["status"] for e in again.events("c", plan_id="a1")] == ["accepted"]
    assert again.events("c", plan_id="a2") == []
    again.record_plan("c", plan_id="a3", fingerprint="f3", profile=PROFILE, intent_at="q", source="w", intent="schedule")
    assert again.plan_version("c", "a3")["seq"] > again.plan_version("c", "a2")["seq"]
    for n in range(ev.MAX_PLANS + 10):
        again.record_plan("c", plan_id=f"n{n}", fingerprint="f", profile=PROFILE, intent_at="q", source="w",
                          intent="schedule")
    kept = again.plan_versions("c")
    assert len(kept) == ev.MAX_PLANS and kept[-1]["id"] == f"n{ev.MAX_PLANS + 9}"


@pytest.mark.asyncio
async def test_retention_drops_old_rows_and_unreadable_documents_are_ignored():
    clock = {"now": T0}
    store, backend = make_store(clock=lambda: clock["now"])
    await store.async_load()
    store.record_plan("c", plan_id="old", fingerprint="f", profile=PROFILE, intent_at="q", source="w", intent="schedule")
    store.record_sample("c", ev.KIND_POWER, value=0, observed_at=T0, received_at=T0, unit="W")
    clock["now"] = T0 + timedelta(days=ev.RETENTION_DAYS + 1)
    store.record_plan("c", plan_id="new", fingerprint="f", profile=PROFILE, intent_at="q", source="w", intent="schedule")
    assert [p["id"] for p in store.plan_versions("c")] == ["new"]
    assert store.samples("c", ev.KIND_POWER) == []
    garbage, _ = make_store(MemBackend({"version": 1, "chargers": {"c": {"plans": ["junk", 5], "samples": "no"},
                                                                    7: {}}}))
    await garbage.async_load()
    assert garbage.plan_versions("c") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,status", [(SimpleNamespace(status="Accepted"), "accepted"),
                                          (SimpleNamespace(status="Rejected"), "rejected"),
                                          (TimeoutError("lost"), "unknown")])
async def test_real_send_path_keeps_the_exact_wire_profile_and_ack_but_no_measurement(monkeypatch, reply, status):
    w = setup(monkeypatch)
    store, _ = make_store()
    await store.async_load()
    w.hass.data[ev.DATA_KEY] = store
    w.point.call = AsyncMock(side_effect=[reply] if isinstance(reply, Exception) else None, return_value=reply)
    w.worker.start()
    await drain(w.worker)
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]
    versions = store.plan_versions("charger")
    assert len(versions) == 1 and versions[0]["profile"] == sent
    assert versions[0]["id"] == w.ledger.value["attempt"]["id"] and versions[0]["source"] == "worker"
    assert versions[0]["intent"] == "schedule" and versions[0]["revision"] == 4
    events = store.events("charger", plan_id=versions[0]["id"])
    assert [(e["kind"], e.get("status")) for e in events] == [("dispatch_started", None), ("ack", status)]
    # only a received answer shows the command reached the charger; a lost reply leaves just the pre-call marker
    assert store.dispatch_state("charger", versions[0]["id"]) == (
        ev.DISPATCH_STARTED if status == "unknown" else ev.DISPATCH_ACK_RECEIVED)
    # command evidence is never a measurement, and the capture-side lists stay empty
    assert all(store.samples("charger", kind) == [] and store.gaps("charger", kind) == [] for kind in ev.SAMPLE_KINDS)
    w.worker.close()


@pytest.mark.asyncio
async def test_evidence_failure_never_changes_the_send_outcome(monkeypatch):
    w = setup(monkeypatch)

    class Broken(ev.ChargingEvidenceStore):
        def record_plan(self, *a, **k):
            raise RuntimeError("disk")

        def record_event(self, *a, **k):
            raise RuntimeError("disk")

    w.hass.data[ev.DATA_KEY] = Broken(w.hass, store=MemBackend())
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["attempt"]["state"] == "accepted"
    w.worker.close()


def test_readback_is_kept_as_its_own_event_associated_only_when_established():
    store, _ = make_store()
    effective = {"status": "Accepted", "fetched_at": T0.isoformat(), "requested_at": T0.isoformat(),
                 "periods": [{"at": T0.isoformat(), "amps": 16}] * (ev.MAX_READBACK_PERIODS + 4)}
    store.record_readback("c", effective, plan_id="a1")
    store.record_readback("c", {**effective, "periods": []}, plan_id=None)
    first, second = store.events("c", kinds=["readback"])
    assert first["associated"] is True and first["truncated"] is True and len(first["periods"]) == ev.MAX_READBACK_PERIODS
    assert second["associated"] is False and second["plan_id"] is None
    assert store.record_event("c", "invented", plan_id=None) == ev.REJECTED


# ---- measurement capture through the real connector reader ------------------------------------------------

class World:
    """Fake HA states plus the OCPP identity boundary, read by the real `_live_measurements`."""

    def __init__(self, monkeypatch):
        self.states = {}
        self.hass = SimpleNamespace(data={}, states=SimpleNamespace(get=lambda eid: self.states.get(eid)))
        self.target = SimpleNamespace(connector_id=1, devid="CP")
        self.controller = SimpleNamespace(ocpp_target=self.target, power_entity_id=None)
        self.power = ocpp_identity.MeasurandLookup("sensor.p", "bound")
        ids = {ocpp_identity.STATUS_CONNECTOR_KEY: "sensor.status", ocpp_identity.CURRENT_IMPORT_KEY: "sensor.amps"}
        monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", lambda h, t, key: ids[key])
        monkeypatch.setattr(ocpp_identity, "connector_measurand_entity", lambda h, t, key: (
            self.power if key == ocpp_identity.POWER_ACTIVE_IMPORT_KEY
            else ocpp_identity.MeasurandLookup("sensor.kwh", "bound")))
        monkeypatch.setattr(ocpp_identity, "_classes_allow_register", lambda h, e: True)

    def put(self, entity, value, at, **attributes):
        self.states[entity] = SimpleNamespace(state=str(value), attributes=attributes, last_reported=at, last_updated=at)

    def readings(self, at, *, power=0.0, amps=0.0, kwh=10.0, status="Charging"):
        self.put("sensor.status", status, at)
        self.put("sensor.amps", amps, at, unit_of_measurement="A")
        self.put("sensor.p", power, at, device_class="power", unit_of_measurement="W")
        self.put("sensor.kwh", kwh, at, unit_of_measurement="kWh", device_class="energy", state_class="total_increasing")


def capturer(world, store, clock):
    return ev.MeasurementCapture(world.hass, "c", world.controller, store, now=lambda: clock["now"])


def test_capture_keeps_values_with_provenance_dedupes_and_keeps_a_real_zero(monkeypatch):
    world, clock = World(monkeypatch), {"now": T0}
    store, _ = make_store()
    cap = capturer(world, store, clock)
    world.readings(T0, power=0.0, amps=0.0, kwh=10.0, status="SuspendedEVSE")
    cap.capture(T0)
    cap.capture(T0 + timedelta(seconds=60))  # nothing new was reported: no second observation
    power = store.samples("c", ev.KIND_POWER)
    assert len(power) == 1 and power[0]["v"] == 0.0 and power[0]["u"] == "W"  # a measured zero is a value
    assert power[0]["e"] == "sensor.p" and power[0]["s"] == "ocpp_registry"
    assert power[0]["t"] == T0.isoformat() and power[0]["r"] == T0.isoformat()
    register = store.samples("c", ev.KIND_REGISTER)[0]
    assert register["v"] == 10.0 and register["e"] == "sensor.kwh" and register["u"] == "kWh"
    status = store.samples("c", ev.KIND_STATUS)[0]
    assert status["v"] == "SuspendedEVSE" and status["n"] and ev.KIND_STATUS not in ev.MEASURED_KINDS
    world.readings(T0 + timedelta(seconds=120), power=3600.0, amps=16.0, kwh=10.5)
    cap.capture(T0 + timedelta(seconds=150))
    later = store.samples("c", ev.KIND_POWER)[-1]
    assert later["v"] == 3600.0 and later["t"] == (T0 + timedelta(seconds=120)).isoformat()
    assert later["r"] == (T0 + timedelta(seconds=150)).isoformat()  # observed time and receipt time are both kept


def test_unreadable_sources_become_explicit_gaps_never_zero_or_plan_values(monkeypatch):
    world, clock = World(monkeypatch), {"now": T0}
    store, _ = make_store()
    cap = capturer(world, store, clock)
    world.power = ocpp_identity.MeasurandLookup(None, "ambiguous")  # two candidate power sensors: unknown
    world.readings(T0)
    world.states["sensor.kwh"] = SimpleNamespace(state="unavailable", attributes={"unit_of_measurement": "kWh"},
                                                  last_reported=T0, last_updated=T0)
    cap.capture(T0)
    cap.capture(T0 + timedelta(seconds=60))
    assert store.samples("c", ev.KIND_POWER) == [] and store.samples("c", ev.KIND_REGISTER) == []
    power_gaps, register_gaps = store.gaps("c", ev.KIND_POWER), store.gaps("c", ev.KIND_REGISTER)
    assert len(power_gaps) == 1 and power_gaps[0]["g"] == "ambiguous" and power_gaps[0]["v"] is None
    assert power_gaps[0]["r"] == T0.isoformat() and power_gaps[0]["r2"] == (T0 + timedelta(seconds=60)).isoformat()
    assert len(register_gaps) == 1 and register_gaps[0]["g"] == "unreadable"
    assert len(store.samples("c", ev.KIND_CURRENT)) == 1  # the other sources keep working
    # without a connector nothing can be captured, and nothing is invented
    store2, _ = make_store()
    ev.MeasurementCapture(world.hass, "c", SimpleNamespace(ocpp_target=None), store2, now=lambda: T0).capture(T0)
    assert all(store2.samples("c", kind) == [] for kind in ev.SAMPLE_KINDS)


def test_duplicates_conflicts_order_and_counter_decreases_are_kept_and_flagged():
    store, _ = make_store()
    kw = dict(entity_id="sensor.kwh", unit="kWh", source="ocpp_registry", received_at=T0 + timedelta(days=1))
    at = lambda s: T0 + timedelta(seconds=s)  # noqa: E731
    assert store.record_sample("c", ev.KIND_REGISTER, value=10.0, observed_at=at(0), **kw) == ev.ADDED
    assert store.record_sample("c", ev.KIND_REGISTER, value=10.0, observed_at=at(0), **kw) == ev.DUPLICATE
    assert store.record_sample("c", ev.KIND_REGISTER, value=10.2, observed_at=at(0), **kw) == ev.ADDED
    assert store.record_sample("c", ev.KIND_REGISTER, value=11.0, observed_at=at(600), **kw) == ev.ADDED
    assert store.record_sample("c", ev.KIND_REGISTER, value=10.5, observed_at=at(300), **kw) == ev.ADDED  # late arrival
    assert store.record_sample("c", ev.KIND_REGISTER, value=0.1, observed_at=at(900), **kw) == ev.ADDED  # reset
    assert store.record_sample("c", ev.KIND_REGISTER, value=float("nan"), observed_at=at(1), **kw) == ev.REJECTED
    assert store.record_sample("c", ev.KIND_REGISTER, value=-1, observed_at=at(2), **kw) == ev.REJECTED
    assert store.record_sample("c", ev.KIND_REGISTER, value=1, observed_at=datetime(2026, 1, 1), **kw) == ev.REJECTED
    assert store.record_sample("c", ev.KIND_REGISTER, value=11.1, observed_at=at(9000),
                               **{**kw, "received_at": T0}) == ev.ADDED  # reported after "now": clock drift
    rows = {(r["t"], r["v"]): r.get("q", []) for r in store.samples("c", ev.KIND_REGISTER)}
    assert rows[(at(0).isoformat(), 10.2)] == ["conflicting_duplicate"]
    assert rows[(at(300).isoformat(), 10.5)] == ["out_of_order"]
    assert rows[(at(900).isoformat(), 0.1)] == ["counter_decrease"]
    assert rows[(at(9000).isoformat(), 11.1)] == ["future_timestamp"]
    assert [r["t"] for r in store.samples("c", ev.KIND_REGISTER)] == sorted(r["t"] for r in store.samples("c", ev.KIND_REGISTER))


def test_derive_energy_labels_meter_and_power_estimates_and_keeps_unknowns():
    store, _ = make_store()
    at = lambda s: T0 + timedelta(seconds=s)  # noqa: E731
    for seconds, kwh in ((0, 10.0), (600, 11.0), (1200, 0.2), (1800, 0.7)):
        store.record_sample("c", ev.KIND_REGISTER, value=kwh, observed_at=at(seconds), entity_id="e", unit="kWh", received_at=at(seconds))
    segments = ev.derive_energy(store.samples("c", ev.KIND_REGISTER), ev.KIND_REGISTER)
    assert [(s["basis"], s["kwh"]) for s in segments] == [(ev.BASIS_METER, 1.0), (ev.BASIS_UNKNOWN, None),
                                                          (ev.BASIS_METER, pytest.approx(0.5))]
    assert segments[1]["reason"] == "counter_decrease" and segments[1]["probable_reset"] is True
    for seconds, watts in ((0, 0.0), (60, 7200.0), (120, 7200.0), (2000, 7200.0), (2060, -5.0)):
        store.record_sample("c", ev.KIND_POWER, value=watts, observed_at=at(seconds), entity_id="p", unit="W", received_at=at(seconds))
    power = ev.derive_energy(store.samples("c", ev.KIND_POWER), ev.KIND_POWER)
    assert [s["basis"] for s in power] == [ev.BASIS_POWER, ev.BASIS_POWER, ev.BASIS_UNKNOWN, ev.BASIS_UNKNOWN]
    assert power[0]["kwh"] == pytest.approx(3600 * 60 / 3_600_000) and power[2]["reason"] == "span_too_long"
    assert power[3]["reason"] == "negative_power"  # the 1880 s hole is not bridged either
    assert ev.derive_energy(store.samples("c", ev.KIND_POWER), ev.KIND_CURRENT) == []


@pytest.mark.asyncio
async def test_overnight_across_midnight_and_restart_keeps_original_plan_and_unknown_gap(monkeypatch):
    """Recorded fixtures only: charging outside the plan is measured; a planned block with no flow stays empty."""
    world, clock = World(monkeypatch), {"now": T0}
    store, backend = make_store(clock=lambda: clock["now"])
    await store.async_load()
    store.record_plan("c", plan_id="night", fingerprint="f", profile=PROFILE, intent_at=T0.isoformat(),
                      source="worker", intent="schedule", revision=1)  # window 00:30-01:30 (in the profile's terms)
    cap = capturer(world, store, clock)
    store.record_capture_start("c", T0)
    for minute, kwh, watts in ((0, 20.0, 7000.0), (5, 20.6, 7000.0), (10, 21.2, 7000.0)):  # 23:50-00:00, outside plan
        at = T0 + timedelta(minutes=minute)
        world.readings(at, power=watts, amps=10.0, kwh=kwh)
        cap.capture(at)
    backend.flush()
    # HA is down 00:00-00:40: no capture, so nothing may be invented for that stretch
    reborn, _ = make_store(backend, clock=lambda: T0 + timedelta(minutes=40))
    await reborn.async_load()
    world.readings(T0 + timedelta(minutes=45), power=0.0, amps=0.0, kwh=21.2, status="SuspendedEVSE")  # planned block idle
    cap2 = capturer(world, reborn, {"now": T0 + timedelta(minutes=45)})
    reborn.record_capture_start("c", T0 + timedelta(minutes=40))
    cap2.capture(T0 + timedelta(minutes=45))
    assert reborn.plan_version("c", "night")["profile"] == PROFILE  # later replans do not rewrite history
    assert len(reborn.capture_starts("c")) == 2
    midnight = T0 + timedelta(minutes=10)
    before = reborn.samples("c", ev.KIND_POWER, until=midnight)
    assert [s["v"] for s in before] == [7000.0, 7000.0]  # flow outside any plan window is measured, not hidden
    energy = reborn.energy_segments("c", ev.KIND_REGISTER)
    assert [s["kwh"] for s in energy] == [pytest.approx(0.6), pytest.approx(0.6), 0.0]
    assert [s["coverage"] for s in energy] == ["endpoints_only", "endpoints_only", "unobserved"]
    assert energy[-1]["basis"] == ev.BASIS_METER and energy[-1]["start"] == midnight.isoformat()
    gap_power = reborn.energy_segments("c", ev.KIND_POWER)
    assert gap_power[-1]["basis"] == ev.BASIS_UNKNOWN and gap_power[-1]["kwh"] is None  # not 7 kW, not 0
    assert gap_power[-1]["reason"] == "capture_restart" and "span_too_long" in gap_power[-1]["reasons"]
    assert energy[-1]["coverage"] == "unobserved" and energy[-1]["placement"] == "unknown"  # the restart is kept
    window = reborn.samples("c", ev.KIND_POWER, since=T0 + timedelta(minutes=30), until=T0 + timedelta(minutes=90))
    assert [s["v"] for s in window] == [0.0]  # the planned block shows what was observed: idle at its one reading


# ---- Stage 6.2 review: gaps, restarts, stale sources are never bridged ---------------------------------------

def at(minutes=0, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def tick(world, cap, when, **readings):
    world.readings(when, **readings)
    cap.capture(when)


@pytest.mark.asyncio
async def test_capture_to_restart_to_derivation_never_bridges_gaps_stale_restarts_or_resets(monkeypatch):
    world, clock = World(monkeypatch), {"now": T0}
    store, backend = make_store(clock=lambda: clock["now"])
    await store.async_load()
    cap = capturer(world, store, clock)
    store.record_capture_start("c", T0)
    tick(world, cap, at(0), power=7000.0, kwh=20.0)
    tick(world, cap, at(1), power=7000.0, kwh=20.1)  # observed pair: integrated and a plain meter delta
    # the sources go unreadable for one tick: 2 minutes apart is "close", but a recorded gap sits between
    for entity in ("sensor.p", "sensor.kwh"):
        world.states[entity] = SimpleNamespace(state="unavailable", attributes={}, last_reported=at(2), last_updated=at(2))
    cap.capture(at(2))
    tick(world, cap, at(3), power=7000.0, kwh=20.4)
    # a stale source: HA reads a value last reported long before the tick, then it recovers
    world.readings(at(3, 10), power=7000.0, kwh=20.5)
    cap.capture(at(8))
    tick(world, cap, at(9), power=7000.0, kwh=20.9)
    # a counter reset (HA stayed up), then charging resumes
    tick(world, cap, at(10), power=7000.0, kwh=0.2)
    tick(world, cap, at(11), power=7000.0, kwh=0.4)
    backend.flush()
    # HA restarts: a new store reads the flushed document, capture starts again 6 minutes later
    reborn, _ = make_store(backend, clock=lambda: at(17))
    await reborn.async_load()
    cap2 = capturer(world, reborn, {"now": at(17)})
    reborn.record_capture_start("c", at(17))
    tick(world, cap2, at(17), power=0.0, kwh=0.4, status="SuspendedEVSE")
    tick(world, cap2, at(18), power=0.0, kwh=0.4)
    tick(world, cap2, at(18), power=0.0, kwh=0.4)  # a duplicate delivery: dropped, not a second sample
    power = {s["start"]: s for s in reborn.energy_segments("c", ev.KIND_POWER)}
    assert power[at(0).isoformat()]["basis"] == ev.BASIS_POWER
    assert power[at(0).isoformat()]["kwh"] == pytest.approx(7000 * 60 / 3.6e6)
    assert power[at(1).isoformat()]["reason"] == "recorded_gap" and power[at(1).isoformat()]["kwh"] is None
    assert power[at(3).isoformat()]["basis"] == ev.BASIS_UNKNOWN  # stale / unobserved: not current evidence
    assert "stale_source" in power[at(3).isoformat()]["reasons"]
    assert power[at(11).isoformat()]["reason"] == "capture_restart" and power[at(11).isoformat()]["kwh"] is None
    assert power[at(17).isoformat()]["basis"] == ev.BASIS_POWER and power[at(17).isoformat()]["kwh"] == 0.0
    register = {s["start"]: s for s in reborn.energy_segments("c", ev.KIND_REGISTER)}
    plain = register[at(0).isoformat()]
    assert plain["coverage"] == "endpoints_only" and plain["kwh"] == pytest.approx(0.1)
    across_gap = register[at(1).isoformat()]  # the meter still says how much, but not when
    assert across_gap["basis"] == ev.BASIS_METER and across_gap["kwh"] == pytest.approx(0.3)
    assert across_gap["coverage"] == "unobserved" and across_gap["placement"] == "unknown"
    assert across_gap["reasons"] == ["recorded_gap"]
    stale = register[at(3).isoformat()]
    assert stale["coverage"] == "unobserved" and "stale_source" in stale["reasons"]
    reset = register[at(9, 10).isoformat()] if at(9, 10).isoformat() in register else register[at(9).isoformat()]
    assert reset["basis"] == ev.BASIS_UNKNOWN and reset["reason"] == "counter_decrease" and reset["probable_reset"]
    after_restart = register[at(11).isoformat()]
    assert after_restart["coverage"] == "unobserved" and after_restart["reasons"] == ["capture_restart"]
    assert after_restart["kwh"] == 0.0
    assert len(reborn.samples("c", ev.KIND_REGISTER, since=at(18))) == 1  # the duplicate was dropped


def test_derive_energy_unknowns_source_conflict_future_order_and_outside_the_plan():
    store, _ = make_store()
    kw = dict(unit="kWh", received_at=at(60))
    store.record_sample("c", ev.KIND_REGISTER, value=5.0, observed_at=at(0), entity_id="a", **kw)
    store.record_sample("c", ev.KIND_REGISTER, value=5.5, observed_at=at(5), entity_id="b", **kw)  # source changed
    store.record_sample("c", ev.KIND_REGISTER, value=6.0, observed_at=at(10), entity_id="b", **kw)
    store.record_sample("c", ev.KIND_REGISTER, value=6.2, observed_at=at(10), entity_id="b", **kw)  # conflicting
    store.record_sample("c", ev.KIND_REGISTER, value=7.0, observed_at=at(15), entity_id="b", **kw)
    store.record_sample("c", ev.KIND_REGISTER, value=7.4, observed_at=at(20), entity_id="b", **{**kw, "received_at": at(0)})
    segments = {s["end"]: s for s in store.energy_segments("c", ev.KIND_REGISTER)}
    assert segments[at(5).isoformat()]["reason"] == "source_changed"
    assert segments[at(15).isoformat()]["reason"] == "conflicting_duplicate"  # the pair after the conflict
    assert segments[at(15).isoformat()]["kwh"] is None
    assert segments[at(20).isoformat()]["reason"] == "future_timestamp"
    assert all(s["basis"] == ev.BASIS_UNKNOWN for s in segments.values())
    # no rows, a single row and flow outside any plan window yield no invented segment
    assert ev.derive_energy([], ev.KIND_POWER) == [] and store.energy_segments("c", ev.KIND_POWER) == []
    one = [{"t": at(0).isoformat(), "r": at(0).isoformat(), "v": 5.0}]
    assert ev.derive_energy(one, ev.KIND_REGISTER) == []


@pytest.mark.asyncio
async def test_aborted_before_dispatch_is_distinct_from_started_and_acked(monkeypatch):
    w = setup(monkeypatch)
    store, _ = make_store()
    await store.async_load()
    w.hass.data[ev.DATA_KEY] = store
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.ledger.write

    async def blocked(value):
        if value.get("attempt") and not entered.is_set():
            entered.set()
            await release.wait()
        await original(value)

    monkeypatch.setattr(w.ledger, "write", blocked)
    w.worker.start()
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        await drain(w.worker)
    w.point.call.assert_not_awaited()
    version = store.plan_versions("charger")[0]
    assert version["profile"] and store.dispatch_state("charger", version["id"]) == ev.DISPATCH_ABORTED
    assert [e["kind"] for e in store.events("charger", plan_id=version["id"])] == ["dispatch_aborted"]
    assert store.events("charger")[0]["reason"]
    assert store.dispatch_state("charger", "never-kept") == ev.DISPATCH_UNKNOWN
    w.worker.close()


@pytest.mark.asyncio
async def test_a_store_that_raises_on_every_write_cannot_change_a_send(monkeypatch):
    w = setup(monkeypatch)

    class Hostile(ev.ChargingEvidenceStore):
        def record_plan(self, *a, **k):
            raise OSError("disk")

        def record_event(self, *a, **k):
            raise ValueError("disk full")

    w.hass.data[ev.DATA_KEY] = Hostile(w.hass, store=MemBackend())
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["attempt"]["state"] == "accepted"
    w.worker.close()


def test_retention_bounds_are_honest_about_the_full_rate_window_and_prune_by_count_then_age():
    # 1440 rows/day at the 60 s tick: the count bound is the binding one at full rate
    assert ev.MeasurementCapture.TICK_S == 60
    full_rate_days = ev.MAX_SAMPLES_PER_KIND * ev.MeasurementCapture.TICK_S / 86400
    assert full_rate_days == pytest.approx(3.0) and full_rate_days < ev.RETENTION_DAYS
    now = at(60 * 24 * 10)
    store, _ = make_store(clock=lambda: now)
    for n in range(ev.MAX_SAMPLES_PER_KIND + 25):
        when = now - timedelta(minutes=n)
        store.record_sample("c", ev.KIND_POWER, value=n, observed_at=when, received_at=when)
    rows = store.samples("c", ev.KIND_POWER)
    assert len(rows) <= ev.MAX_SAMPLES_PER_KIND
    assert all((now - ev._parse(r["t"])).days <= ev.RETENTION_DAYS for r in rows)


def _kinds(*items):
    store, _ = make_store()
    for kind, fields in items:
        store.record_event("c", kind, plan_id="p", **fields)
    return store.dispatch_state("c", "p")


def test_dispatch_marker_alone_is_never_reported_as_sent_and_absent_or_conflicting_is_unknown():
    assert not hasattr(ev, "DISPATCH_ON_WIRE") and "dispatched" not in ev.EVENT_KINDS
    assert _kinds(("dispatch_started", {})) == ev.DISPATCH_STARTED  # crash before the call looks exactly like this
    assert _kinds() == ev.DISPATCH_UNKNOWN
    assert _kinds(("dispatch_started", {}), ("ack", {"status": "unknown"})) == ev.DISPATCH_STARTED  # no reply
    assert _kinds(("ack", {"status": "unknown"})) == ev.DISPATCH_UNKNOWN
    assert _kinds(("dispatch_started", {}), ("ack", {"status": "accepted"})) == ev.DISPATCH_ACK_RECEIVED
    assert _kinds(("dispatch_started", {}), ("ack", {"status": "rejected"})) == ev.DISPATCH_ACK_RECEIVED
    assert _kinds(("dispatch_aborted", {"reason": "x"})) == ev.DISPATCH_ABORTED
    assert _kinds(("dispatch_started", {}), ("dispatch_aborted", {"reason": "x"})) == ev.DISPATCH_CONFLICT
    assert _kinds(("dispatch_aborted", {"reason": "x"}), ("ack", {"status": "accepted"})) == ev.DISPATCH_CONFLICT
    assert _kinds(("ack", {"status": "accepted"})) == ev.DISPATCH_CONFLICT  # an answer with no marker is inconsistent


@pytest.mark.asyncio
async def test_crash_before_the_wire_call_leaves_only_a_possibly_dispatched_marker(monkeypatch):
    w = setup(monkeypatch)
    store, backend = make_store()
    await store.async_load()
    w.hass.data[ev.DATA_KEY] = store
    w.point.call = AsyncMock(side_effect=asyncio.CancelledError())  # the process dies at the call
    w.worker.start()
    try:
        await drain(w.worker)
    except asyncio.CancelledError:
        pass
    version = store.plan_versions("charger")[0]
    assert [e["kind"] for e in store.events("charger", plan_id=version["id"])] == ["dispatch_started"]
    backend.flush()
    again, _ = make_store(backend)
    await again.async_load()
    assert again.dispatch_state("charger", version["id"]) == ev.DISPATCH_STARTED != ev.DISPATCH_ACK_RECEIVED
    w.worker.close()


@pytest.mark.asyncio
async def test_real_fetch_readback_is_associated_with_the_acked_version_only(monkeypatch, tmp_path):
    from custom_components.spotnav.execution import morek_worker
    from .test_morek_worker import real_admission_planner_worker
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    store, _ = make_store()
    await store.async_load()
    w.hass.data[ev.DATA_KEY] = store
    await morek_schedule.async_charge_now_action(w.hass, "test")
    await drain(w.worker)
    version = store.plan_versions("test")[0]
    assert store.dispatch_state("test", version["id"]) == ev.DISPATCH_ACK_RECEIVED
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    profile = w.hass.data[morek_schedule._DATA_KEY]["test"][0]["profile"]["chargingSchedule"]
    w.point.call.return_value = SimpleNamespace(status="Accepted", connector_id=1, schedule_start=profile["startSchedule"],
                                                charging_schedule={**profile, "duration": 172800})
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        GetCompositeSchedule=lambda **kw: SimpleNamespace(payload=kw),
        SetChargingProfile=lambda **kw: SimpleNamespace(payload=kw))))
    await morek_schedule.async_schedule_action(w.hass, "test", "fetch")
    reads = store.events("test", kinds=["readback"])
    assert len(reads) == 1 and reads[0]["plan_id"] == version["id"] and reads[0]["associated"] is True
    w.worker.close()
