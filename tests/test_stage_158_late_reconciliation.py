"""Stage 15.8: late cumulative-register reconciliation of closed session totals.

Real `SessionRecorder`, `SessionStore`, `ChargingEvidenceStore` and `charging_history`; HA's `Store`, loop and the
charger are the usual mocked boundaries (no pytest-homeassistant fixture, so it runs in the isolated runner).
Nothing here shows what the installed charger replays or that energy reached a car.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_158_late_reconciliation.py
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav.sessions import evidence as ev
from custom_components.spotnav.sessions import reconcile as rec
from custom_components.spotnav.sessions import store as store_module
from custom_components.spotnav.sessions.history import charging_history
from custom_components.spotnav.sessions.model import ChargeSession
from custom_components.spotnav.sessions.recorder import SessionFacts, SessionRecorder
from custom_components.spotnav.sessions.store import SessionStore

UTC = timezone.utc
T0 = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)
CHARGER = "morek"
ENTITY = "sensor.morek_energy_register"


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


class Backend:
    def __init__(self, doc=None):
        self.doc, self.func = doc, None

    async def async_load(self):
        return self.doc

    def async_delay_save(self, func, _delay):
        self.func = func

    async def async_save(self, doc):
        self.doc = json.loads(json.dumps(doc))


class Loop:
    def call_later(self, _delay, _func):
        return SimpleNamespace(cancel=lambda: None)


def hass_stub():
    async def run(func, *args):
        return func(*args)

    return SimpleNamespace(
        loop=Loop(), data={}, is_stopping=False, async_add_executor_job=run,
        bus=SimpleNamespace(async_listen_once=lambda *_a, **_k: (lambda: None)),
        async_create_background_task=lambda coro, _name: coro.close(),
    )


@pytest.fixture
def backends(monkeypatch):
    made: dict[str, Backend] = {}
    monkeypatch.setattr(store_module, "Store", lambda _hass, _v, key, **_k: made.setdefault(key, Backend()))
    return made


class Evidence:
    """The real evidence store on an in-memory backend."""

    def __init__(self):
        self.store = ev.ChargingEvidenceStore(SimpleNamespace(data={}), store=Backend(), now=lambda: at(600))

    def reading(self, value, observed, received=None, entity=ENTITY, **kw):
        return self.store.record_sample(
            CHARGER, ev.KIND_REGISTER, value=value, observed_at=at(observed), received_at=at(received or observed),
            entity_id=entity, unit="kWh", source="configured_entity", **kw)


class World:
    def __init__(self, store: SessionStore, evidence: Evidence | None, hass=None):
        self.facts = SessionFacts(
            charging=False, connected=True, register_kwh=100.0, register_integrated=False, estimate_kw=None,
            strategy="cheapest", vehicle_id="car", vehicle_name="Car", solar_share=None, register_entity=ENTITY)
        self.store, self.evidence = store, evidence
        self.recorder = SessionRecorder(
            hass or hass_stub(), CHARGER, store, facts=lambda: self.facts, prices=lambda _now: None,
            consume_cause=lambda: None, now=lambda: self.clock,
            evidence=None if evidence is None else (lambda: evidence.store))
        self.clock = T0

    def at(self, minutes: float, **changes):
        self.clock = at(minutes)
        if changes:
            self.facts = replace(self.facts, **changes)
        self.recorder.evaluate(self.clock)


def charge_and_unplug(world: World, *, delivered: float = 0.103, register: float = 100.0) -> ChargeSession:
    """A session that opened on the register, placed `delivered` kWh and closed at the unplug."""
    world.at(0, charging=True, register_kwh=register)
    world.at(1, charging=True, register_kwh=register + delivered)
    world.at(2, charging=False, connected=False, register_kwh=register + delivered)
    (done,) = world.store.closed_raw(CHARGER)
    return done


def late(world: World) -> dict | None:
    return world.store.closed_raw(CHARGER)[-1].late


async def make(backends):
    store = SessionStore(hass_stub())
    await store.async_load()
    return store


async def test_overnight_20_9_late_rise_is_unassigned_never_a_total(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    done = charge_and_unplug(world)
    assert done.energy_kwh == pytest.approx(0.103)
    before = (done.energy_kwh, done.intervals, done.start, done.end, done.priced(None).cost_minor)
    evidence.reading(120.9, observed=10)  # a later register value with only an entity and a receipt time
    evidence.reading(120.9, observed=11)  # settled: still no proof it belongs to this session
    world.at(12)
    record = late(world)
    assert record["state"] == "uncertain" and record["reason"] == "late_register_unassigned"
    assert record["total_kwh"] is None and record["unplaced_late_kwh"] is None and record["placement"] is None
    assert record["unassigned_register_kwh"] == pytest.approx(20.797)
    assert record["register_open_kwh"] == 100.0 and record["register_close_kwh"] == pytest.approx(100.103)
    assert record["source"]["basis"] == "recorder_close" and record["final"] is False
    now = store.closed_raw(CHARGER)[0]
    # The session energy 14.5 / accounting read, its timeline and its price slices are exactly as they were.
    assert (now.energy_kwh, now.intervals, now.start, now.end, now.priced(None).cost_minor) == before
    assert now.unplaced_late_kwh is None  # nothing a learner could take as certified extra energy
    answer = charging_history(evidence.store, CHARGER, since=at(-30), until=at(60), zone=UTC, now=at(60),
                              sessions=store.closed_raw(CHARGER))
    row = answer["sessions"][0]
    assert row["energy_kwh"] == 0.103 and row["price_slices"] == []
    block = row["reconciliation"]
    assert block["total_kwh"] is None and block["unplaced_late_kwh"] is None and block["state"] == "uncertain"
    assert block["unassigned_register_kwh"] == pytest.approx(20.797)
    assert block["provenance"]["when_delivered"] == "unknown" and "not certified" in block["provenance"]["note"]
    assert answer["observed"]["intervals"] == [] and answer["comparison"]["outside_plan"] == []


async def test_unrecorded_later_car_with_no_next_session_record_is_not_absorbed(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    # Another car charges on the same register; SpotNav opened no session for it (never opened or dropped). It settles with no next record to bound it.
    for minute, value in ((30, 105.0), (60, 118.0), (90, 131.0), (120, 131.0), (150, 131.0)):
        evidence.reading(value, observed=minute)
    world.at(151)
    record = late(world)
    assert record["state"] == "uncertain" and record["total_kwh"] is None and record["unplaced_late_kwh"] is None
    assert record["unassigned_register_kwh"] == pytest.approx(30.897)
    world.at(2 + rec.LATE_WINDOW_S / 60 + 1)
    assert late(world)["final"] is True and late(world)["total_kwh"] is None


async def test_gap_restart_and_link_down_are_not_proof_of_association(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.store.record_gap(CHARGER, ev.KIND_REGISTER, "link_down", received_at=at(5))
    evidence.store.record_capture_start(CHARGER, at(6))
    evidence.reading(120.9, observed=10)
    evidence.reading(120.9, observed=11)
    world.at(12)
    record = late(world)
    assert record["state"] == "uncertain" and record["total_kwh"] is None and record["unplaced_late_kwh"] is None
    assert record["placement_reasons"] == []


async def test_provisional_total_is_withdrawn_when_a_late_rise_conflicts(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    world.at(5)
    first = late(world)
    assert first["state"] == "consistent" and first["total_kwh"] == pytest.approx(0.103) and first["final"] is False
    evidence.reading(120.9, observed=10)
    world.at(11)
    second = late(world)
    assert second["state"] == "uncertain" and second["total_kwh"] is None and second["unplaced_late_kwh"] is None
    assert second["unassigned_register_kwh"] == pytest.approx(20.797)


async def test_recorder_pair_total_with_unplaced_remainder_inside_the_session(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    done = charge_and_unplug(world)
    # The recorder's own close reading is above what it placed (e.g. a restart inside the session).
    wider = replace(done, register_pair={**done.register_pair, "close": 100.5})
    evidence.store.record_gap(CHARGER, ev.KIND_REGISTER, "link_down", received_at=at(1))
    evidence.store.record_gap(CHARGER, ev.KIND_REGISTER, "unreadable", received_at=at(1.5), source="x")
    evidence.store.record_capture_start(CHARGER, at(1.2))
    read = rec.read_evidence(evidence.store, CHARGER, since=at(-1))
    out = rec.reconcile(wider, read, [], at(10))
    assert out["state"] == "reconciled" and out["total_kwh"] == pytest.approx(0.5)
    assert out["unplaced_late_kwh"] == pytest.approx(0.397) and out["placement"] == "unknown"
    assert out["placement_reasons"] == ["restart", "link_down", "gap"] and out["source"]["basis"] == "recorder_close"
    quiet = rec.reconcile(wider, rec.LateEvidence([], [], []), [], at(10))
    assert quiet["placement_reasons"] == ["unattributed"]


async def test_clean_recorder_pair_is_consistent_and_idempotent_across_duplicates_and_restart(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    assert evidence.reading(100.103, observed=10) == ev.ADDED
    world.at(11)
    first = late(world)
    assert first["state"] == "consistent" and first["total_kwh"] == pytest.approx(0.103)
    writes = []
    original = store.set_late
    store.set_late = lambda *a, **k: writes.append(a) or original(*a, **k)
    assert evidence.reading(100.103, observed=10) == ev.DUPLICATE
    for minute in (12, 13, 14):
        world.at(minute)
    assert comparable_of(late(world)) == comparable_of(first) and writes == []
    await store.async_flush()
    reborn = SessionStore(hass_stub())
    await reborn.async_load()
    World(reborn, evidence).at(20)
    assert comparable_of(reborn.closed_raw(CHARGER)[0].late) == comparable_of(first)
    assert reborn.closed_raw(CHARGER)[0].register_pair["open"] == 100.0


def comparable_of(record):
    return rec.comparable(record)


async def test_restart_between_close_and_late_rise_still_reports_it_unassigned(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    await store.async_flush()
    reborn = SessionStore(hass_stub())
    await reborn.async_load()
    evidence.reading(120.9, observed=30)
    World(reborn, evidence).at(32)
    record = reborn.closed_raw(CHARGER)[0].late
    assert record["state"] == "uncertain" and record["total_kwh"] is None
    assert record["unassigned_register_kwh"] == pytest.approx(20.797)
    assert reborn.closed_raw(CHARGER)[0].energy_kwh == pytest.approx(0.103)


async def test_identity_mismatch_and_other_sources_are_never_absorbed(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.reading(500.0, observed=10, entity="sensor.some_other_register")
    evidence.reading(500.0, observed=11, entity="sensor.some_other_register")
    world.at(12)
    record = late(world)
    assert record["state"] == "consistent" and record["unplaced_late_kwh"] == 0.0
    assert "other_source_ignored" in record["quality"] and record["total_kwh"] == pytest.approx(0.103)
    assert record["unassigned_register_kwh"] is None
    # The register itself changing mid-session breaks the pair.
    other = await make(backends)
    swapped = World(other, evidence)
    swapped.at(0, charging=True, register_kwh=100.0)
    swapped.at(1, charging=True, register_kwh=100.3)
    new = {"register_entity": "sensor.replacement_register"}
    swapped.at(2, charging=True, register_kwh=5.0, **new)
    swapped.at(3, charging=True, register_kwh=5.4, **new)
    swapped.at(4, charging=False, connected=False, register_kwh=5.4, **new)
    assert other.closed_raw(CHARGER)[0].late["state"] == "skipped"
    assert other.closed_raw(CHARGER)[0].late["reason"] == "identity"
    assert other.closed_raw(CHARGER)[0].late["unplaced_late_kwh"] is None


async def test_register_reset_inside_the_session_is_skipped_not_energy(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    world.at(0, charging=True, register_kwh=100.0)
    world.at(1, charging=True, register_kwh=100.5)
    world.at(2, charging=True, register_kwh=0.2)  # reset to zero inside the session
    world.at(3, charging=False, connected=False, register_kwh=0.2)
    evidence.reading(40.0, observed=10)
    evidence.reading(40.0, observed=11)
    world.at(12)
    record = late(world)
    assert record["state"] == "skipped" and record["reason"] == "register_reset"
    assert record["total_kwh"] is None and record["unplaced_late_kwh"] is None


async def test_decrease_after_close_stops_the_chain_and_adds_nothing(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.reading(0.2, observed=10)  # reset after the close: another origin
    evidence.reading(35.0, observed=11)  # the next car's energy, counted from the reset
    world.at(12)
    record = late(world)
    assert "decrease_after_close" in record["quality"]
    assert record["state"] == "consistent" and record["total_kwh"] == pytest.approx(0.103)
    assert record["unplaced_late_kwh"] == 0.0 and record["unassigned_register_kwh"] is None


async def test_next_session_bounds_what_is_reported_for_the_earlier_one(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    world.at(20, charging=True, connected=True, register_kwh=100.103)
    evidence.reading(140.0, observed=21)  # the next session's own energy
    evidence.reading(150.0, observed=22)
    world.at(23, charging=True, register_kwh=150.0)
    first = store.closed_raw(CHARGER)[0]
    assert first.late["state"] == "consistent" and first.late["final"] is True
    assert first.late["total_kwh"] == pytest.approx(0.103) and first.late["unassigned_register_kwh"] is None
    assert store.open_raw(CHARGER).energy_kwh == pytest.approx(49.897)  # the next session keeps its own energy


async def test_rise_before_the_next_session_is_unassigned_not_total_and_final(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.reading(120.9, observed=10)
    world.at(11)
    world.at(20, charging=True, connected=True, register_kwh=120.9)
    world.at(23, charging=True, register_kwh=121.0)
    first = store.closed_raw(CHARGER)[0]
    assert first.late["state"] == "uncertain" and first.late["total_kwh"] is None and first.late["final"] is True
    assert first.late["unassigned_register_kwh"] == pytest.approx(20.797)


async def test_final_record_is_not_evaluated_again(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.reading(105.0, observed=10)
    world.at(2 + rec.LATE_WINDOW_S / 60 + 1)
    record = late(world)
    assert record["final"] is True and record["state"] == "uncertain"
    evidence.reading(500.0, observed=2000)
    world.at(2001)
    assert late(world) == record


async def test_samples_outside_the_window_or_with_bad_quality_are_ignored(backends):
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    evidence.reading(120.9, observed=10, received=5)  # observed after it was received: future timestamp
    evidence.reading(130.0, observed=-10)  # before the session began
    evidence.reading(140.0, observed=2 + rec.LATE_WINDOW_S / 60 + 5)  # beyond the window
    world.at(12)
    record = late(world)
    assert record["state"] == "consistent" and record["total_kwh"] == pytest.approx(0.103)
    assert record["quality"] == ["quality_ignored"]


async def test_missing_open_or_close_is_unknown_never_zero(backends):
    store = await make(backends)
    world = World(store, Evidence())
    world.at(0, charging=True, register_kwh=None, estimate_kw=7.0)  # estimated: no register at open
    world.at(5, charging=True, register_kwh=None, estimate_kw=7.0)
    world.at(6, charging=False, connected=False, register_kwh=None, estimate_kw=7.0)
    (done,) = store.closed_raw(CHARGER)
    assert done.register_pair is None and done.late is None
    block = rec.public(done)
    assert block["state"] == "unknown" and block["reason"] == "register_pair_missing" and block["total_kwh"] is None
    # A pair whose open reading was unreadable, and one that never closed.
    real = ChargeSession.from_dict(json.loads(json.dumps(
        {**_record(), "register_pair": {"open": None, "close": None, "entity": ENTITY, "broke": None,
                                        "closed_at": at(2).isoformat()}})))
    assert rec.reconcile(real, rec.LateEvidence([], [], []), [], at(10))["reason"] == "register_open_unknown"
    open_pair = replace(real, register_pair={"open": 1.0, "close": None, "entity": ENTITY, "broke": None,
                                              "closed_at": None})
    assert rec.reconcile(open_pair, rec.LateEvidence([], [], []), [], at(10))["reason"] == "register_close_unknown"
    no_close = replace(real, register_pair={"open": 1.0, "close": None, "entity": ENTITY, "broke": None,
                                             "closed_at": at(2).isoformat()})
    out = rec.reconcile(no_close, rec.LateEvidence([], [], []), [], at(10))
    assert out["state"] == "unknown" and out["reason"] == "register_close_unknown" and out["total_kwh"] is None


async def test_total_below_placed_keeps_placed_and_flags_inconsistent(backends):
    store = await make(backends)
    world = World(store, Evidence())
    done = charge_and_unplug(world)
    inflated = replace(done, energy_kwh=5.0)
    out = rec.reconcile(inflated, rec.LateEvidence([], [], []), [], at(10))
    assert out["state"] == "inconsistent" and out["reason"] == "total_below_placed"
    assert out["total_kwh"] == 5.0 and out["unplaced_late_kwh"] == 0.0


async def test_overlapping_session_makes_the_association_unknown(backends):
    store = await make(backends)
    world = World(store, Evidence())
    done = charge_and_unplug(world)
    clash = replace(done, id="other", start=at(1), end=None)
    out = rec.reconcile(done, rec.LateEvidence([], [], []), [done, clash], at(10))
    assert out["state"] == "unknown" and out["reason"] == "ambiguous_association" and out["total_kwh"] is None


def _record(**more):
    base = ChargeSession(
        id="x", charger_id=CHARGER, start=at(0), end=at(2), energy_kwh=0.103, energy_source="register",
        priced_kwh=0.0, cost_minor=None, reference_cost_minor=None, currency=None, major_unit=None,
        minor_unit=None, started_by="other", strategy=None, vehicle_id=None, vehicle_name=None, solar_kwh=0.0,
        solar_known_kwh=0.0, last_register_kwh=None, last_sample_at=None)
    return {**base.as_dict(), **more}


def test_untrusted_and_older_records_load_and_stay_bounded():
    old = ChargeSession.from_dict(_record())
    assert old is not None and old.register_pair is None and old.late is None and old.unplaced_late_kwh is None
    good_pair = {"open": 1.0, "close": 2.0, "entity": ENTITY, "broke": None, "closed_at": at(2).isoformat()}
    kept = ChargeSession.from_dict(_record(register_pair=good_pair))
    assert kept.register_pair == good_pair and ChargeSession.from_dict(kept.as_dict()) == kept
    for bad in ({"open": "x", "close": 1, "entity": None, "broke": None, "closed_at": None},
                {"open": 1.0}, "junk", {**good_pair, "broke": "invented"}, {**good_pair, "closed_at": "no"},
                {**good_pair, "extra": 1}, {**good_pair, "open": float("nan")}, {**good_pair, "open": -1}):
        loaded = ChargeSession.from_dict(_record(register_pair=bad))
        assert loaded is not None and loaded.register_pair is None and loaded.energy_kwh == 0.103
    world_late = {
        "state": "uncertain", "reason": "late_register_unassigned", "placed_kwh": 0.103, "total_kwh": None,
        "unplaced_late_kwh": None, "placement": None, "placement_reasons": [], "register_open_kwh": 100.0,
        "register_close_kwh": 100.103, "unassigned_register_kwh": 20.797,
        "source": {"basis": "recorder_close", "r": at(2).isoformat(), "entity": ENTITY}, "quality": [],
        "final": False, "evaluated_at": at(12).isoformat()}
    full = ChargeSession.from_dict(_record(register_pair=good_pair, late_reconciliation=world_late))
    assert full.late == world_late and full.unplaced_late_kwh is None
    for patch in ({"state": "bogus"}, {"placement_reasons": ["gap"] * 4}, {"placement_reasons": ["replay"]},
                  {"quality": ["x"]}, {"total_kwh": "20.9"}, {"final": "yes"}, {"source": {"basis": "x"}}, {"unassigned_register_kwh": -1},
                  {"source": {"basis": "evidence_sample", "r": None, "entity": None}},
                  {"reason": "unlisted"}, {"evaluated_at": "never"}):
        bad = ChargeSession.from_dict(_record(register_pair=good_pair, late_reconciliation={**world_late, **patch}))
        assert bad is not None and bad.late is None and bad.energy_kwh == 0.103
    assert ChargeSession.from_dict(_record(late_reconciliation={**world_late, "surplus": 1})).late is None


async def test_reconciliation_never_touches_the_worker_or_the_charger(backends):
    source = open(rec.__file__, encoding="utf-8").read()
    for forbidden in ("morek_worker", "ocpp", "send_profile", "request_repair", "async_call", "async_add_job"):
        assert forbidden not in source
    store = await make(backends)
    evidence = Evidence()
    world = World(store, evidence)
    charge_and_unplug(world)
    snapshot = {k: v for k, v in store.closed_raw(CHARGER)[0].as_dict().items()
                if k not in ("late_reconciliation",)}
    evidence.reading(120.9, observed=10)
    evidence.reading(120.9, observed=11)
    world.at(12)
    assert {k: v for k, v in store.closed_raw(CHARGER)[0].as_dict().items()
            if k not in ("late_reconciliation",)} == snapshot  # only the additive block moved


async def test_recorder_without_evidence_records_the_pair_and_changes_nothing_else(backends):
    store = await make(backends)
    world = World(store, None)
    done = charge_and_unplug(world)
    assert done.late is None and done.register_pair["open"] == 100.0 and done.register_pair["closed_at"] is not None
    assert done.register_pair["close"] == pytest.approx(100.103) and done.energy_kwh == pytest.approx(0.103)
