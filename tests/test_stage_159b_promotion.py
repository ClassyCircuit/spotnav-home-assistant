"""Stage 15.9b: promotion, quality rules, asymmetric trust and the clamp for Morek captures (mocked; no `hass` fixture,
no HA/charger). Store-level cases use a fake `checker`; the production proof (`AutoPlannerController._prove_capture`) and
the end-to-end promotion at plug-in end run through the real controller with a fake charging controller, session store
and evidence store."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.spotnav.planning import auto_controller, learned_energy
from custom_components.spotnav.planning.auto_controller import LiveVehicleFacts, capped_vehicle_energy
from custom_components.spotnav.planning.learned_energy import (
    Capture,
    LearnedEnergyStore,
    NOTHING_LEARNED,
    ORIGIN_CAPTURE,
    metadata_reason,
)
from tests.test_stage_159a_energy_capture import CAPACITY, CAR, ENTITY, START, FakeStore, World  # noqa: F401

NOW = START + timedelta(days=30)
DEFAULT = CAPACITY / learned_energy.CHARGE_EFFICIENCY / 100.0  # wall kWh per percent at the fixed efficiency
QUALITY = {k: 0 for k in learned_energy._QUALITY_KEYS}  # noqa: SLF001


@pytest.fixture(autouse=True)
def fixtures(monkeypatch):
    FakeStore.saved = None
    monkeypatch.setattr(learned_energy, "Store", FakeStore)
    monkeypatch.setattr(learned_energy.dt_util, "utcnow", lambda: NOW)


def meta(**changes):
    quality = {**QUALITY, "looks": 60, **changes.pop("quality", {})}
    base = {
        "v": 1, "soc_source": "vehicle", "soc_time_basis": "vehicle_timestamp", "soc_start": 20.0, "soc_end": 40.0,
        "register_entity": ENTITY, "register_start_kwh": 1000.0, "register_basis_start": "interpolated",
        "register_basis_end": "interpolated", "capacity_kwh": CAPACITY, "phases": 3, "voltage_v": 400.0,
        "plug_in_basis": "watched", "late_energy": "unknown", "quality": quality,
    }
    base.update(changes)
    return base


def raw_capture(index=0, factor=1.0, *, at=None, ident=None, **changes):
    """A stored capture of 20 points at `factor` x the default wall kWh per percent, ending at `at`."""
    end = at or START + timedelta(days=index)
    kwh = DEFAULT * factor * 20.0
    m = meta(**changes)
    m.setdefault("soc_start_at", (end - timedelta(hours=1)).isoformat())
    m.setdefault("soc_end_at", end.isoformat())
    m.setdefault("register_end_kwh", m["register_start_kwh"] + kwh)
    return {
        "origin": ORIGIN_CAPTURE, "id": ident or f"plug_in:{index}", "kwh": kwh, "delta_percent": 20.0,
        "at": end.isoformat(), "meta": m,
    }


def capture(index=0, factor=1.0, **changes) -> Capture:
    value = Capture.from_stored(raw_capture(index, factor, **changes))
    assert value is not None
    return value


def store_with(factors, *, checker=lambda *_: None, **changes) -> LearnedEnergyStore:
    store = LearnedEnergyStore(MagicMock(), "entry")
    store.checker = checker
    for index, factor in enumerate(factors):
        assert store.put_capture(CAR, capture(index, factor, **changes), CAPACITY)
    return store


def ended(store):
    store.set_capture_open(None)  # a plug-in that ended: promotion happens here
    return store.learned(CAR, CAPACITY, drop=True, morek=True)


# ------------------------------------------------------------------------------------------------ trust and clamp
def test_four_agreeing_lengthen_but_cannot_shorten_five_can_and_are_clamped():
    longer = ended(store_with([1.05] * 3))
    assert longer.trusted and longer.use_kwh_per_percent == pytest.approx(1.05 * DEFAULT) and longer.from_promoted
    four = ended(store_with([0.95] * 4))
    assert not four.trusted and four.use_kwh_per_percent is None  # the default stands
    five = ended(store_with([0.95] * 5))
    assert five.trusted and five.use_kwh_per_percent == pytest.approx(0.95 * DEFAULT)
    # The learned need is the figure's, and the plan's wall energy follows it.
    reason, kwh = learned_energy.target_need(five, soc_percent=30.0, capacity_kwh=CAPACITY, target_percent=80.0)
    assert reason == "ok" and kwh == pytest.approx(0.95 * DEFAULT * 50.0)
    upper = ended(store_with([1.28] * 3))  # an efficiency of 0.70 still fits, but the figure may go up only 25%
    assert upper.trusted and upper.use_kwh_per_percent == pytest.approx(1.25 * DEFAULT)


def test_lower_clamp_is_10_percent_of_the_default(monkeypatch):
    monkeypatch.setattr(learned_energy, "fits", lambda *_: True)  # the bounds would refuse such a figure first
    assert ended(store_with([0.8] * 5)).use_kwh_per_percent == pytest.approx(0.90 * DEFAULT)
    assert not ended(store_with([0.8] * 4)).trusted


def test_one_odd_charge_cannot_move_the_median():
    base = ended(store_with([1.05] * 5))
    odd = ended(store_with([1.05] * 5 + [1.12]))
    assert odd.use_kwh_per_percent == pytest.approx(base.use_kwh_per_percent)
    low = ended(store_with([1.05] * 5 + [0.93]))
    assert low.use_kwh_per_percent == pytest.approx(base.use_kwh_per_percent) and low.trusted
    # Without enough agreement nothing is trusted, whatever the median.
    split = ended(store_with([0.9, 0.97, 1.1, 1.2, 1.27]))
    assert not split.trusted


def test_one_vote_per_plug_in_age_and_last_nine():
    store = store_with([1.05] * 12)
    learned = ended(store)
    assert len(learned.samples) == 9 and learned.promoted == 9
    assert [s.id for s in learned.samples] == [f"plug_in:{i}" for i in range(3, 12)]  # the newest nine
    # Many SOC updates of one plug-in are one capture and one vote (the same id replaces).
    again = store_with([1.05])
    for _ in range(10):
        again.put_capture(CAR, capture(0, 1.05), CAPACITY)
    assert len(again.captures(CAR)) == 1 and ended(again).promoted == 1 and not ended(again).trusted
    # Older than 120 days is not a vote.
    aged = LearnedEnergyStore(MagicMock(), "entry")
    aged.checker = lambda *_: None
    for index in range(3):
        aged.put_capture(CAR, capture(index, 1.05, at=NOW - timedelta(days=121 + index)), CAPACITY)
    assert not ended(aged).trusted
    # A stored duplicate id counts once.
    dup = LearnedEnergyStore(MagicMock(), "entry")
    dup.checker = lambda *_: None
    FakeStore.saved = {"vehicles": {CAR: {"samples": [], "captures": [
        raw_capture(0, 1.05), raw_capture(1, 1.05, ident="plug_in:0"), raw_capture(2, 1.05),
    ]}}}


@pytest.mark.asyncio
async def test_duplicate_stored_ids_are_one_vote_and_malformed_records_are_dropped():
    FakeStore.saved = {"vehicles": {CAR: {"samples": [], "captures": [
        raw_capture(0, 1.05), raw_capture(1, 1.05, ident="plug_in:0"), raw_capture(2, 1.05),
        {**raw_capture(3, 1.05), "origin": "legacy"}, {"origin": ORIGIN_CAPTURE, "id": "x"}, "junk",
        raw_capture(4, 1.05, quality={"looks": "x"}),
    ], "promoted": ["plug_in:0", "plug_in:2", "nothing", 7], "rejected": {"plug_in:0": ["bogus", "gap"], "z": 3},
        "rejection_counts": {"gap": 2, "bogus": 5, "restart": -1}}}}
    store = LearnedEnergyStore(MagicMock(), "entry")
    store.checker = lambda *_: None
    await store.async_load()
    assert len(store.captures(CAR)) == 3 and store.rejection_counts(CAR) == {"gap": 2}
    learned = store.learned(CAR, CAPACITY, drop=True, morek=True)
    assert learned.promoted == 2 and not learned.trusted  # two ids, one vote each: below three


# ---------------------------------------------------------------------------------------------- the quality rules
@pytest.mark.parametrize("changes,reason", [
    ({"soc_time_basis": None}, "missing_metadata"),
    ({"late_energy": None}, "missing_metadata"),
    ({"soc_time_basis": "last_updated"}, "soc_basis"),
    ({"soc_end": 90.5, "register_end_kwh": 1000.0 + DEFAULT * 20.0}, "energy_inconsistent"),
    ({"quality": {"gaps": 1}}, "gap"),
    ({"quality": {"restarts": 1}}, "restart"),
    ({"quality": {"held_looks": 2}}, "held"),
    ({"quality": {"paused_looks": 1}}, "paused"),
    ({"quality": {"unposted_looks": 1}}, "unobserved"),
    ({"quality": {"looks": 1}}, "unobserved"),
    ({"late_energy": "unplaced"}, "late_unplaced"),
    ({"late_energy": "uncertain"}, "late_uncertain"),
    ({"soc_end_at": (NOW + timedelta(hours=2)).isoformat()}, "soc_time"),
    ({"register_end_kwh": 1000.0}, "energy_inconsistent"),
])
def test_capture_metadata_rules_reject_with_a_reason(changes, reason):
    value = Capture.from_stored(raw_capture(0, 1.0, at=NOW - timedelta(hours=1), **changes))
    assert value is not None
    assert metadata_reason(value, CAPACITY, NOW) == reason


def test_unknown_late_snapshot_is_not_proof_but_not_a_rejection_alone():
    value = capture(0, 1.0)
    assert value.meta["late_energy"] == "unknown" and metadata_reason(value, CAPACITY, NOW) is None
    # A good capture-time snapshot is not proof either: the checker decides, and none means nothing is promoted.
    store = store_with([1.0] * 5, checker=None, late_energy="clean")
    assert not ended(store).trusted and store.rejection_counts(CAR) == {"evidence_unavailable": 5}


def test_rise_end_level_and_future_report_rules():
    short = Capture.from_stored({**raw_capture(0, 1.0), "delta_percent": 12.0, "kwh": DEFAULT * 12.0,
                                 "meta": meta(soc_end=32.0, soc_start_at=START.isoformat(),
                                              soc_end_at=START.isoformat(), register_end_kwh=1000.0 + DEFAULT * 12.0)})
    assert short is not None
    assert metadata_reason(short, CAPACITY, NOW) in ("soc_time", "rise_below_15")
    low = Capture.from_stored({**raw_capture(0, 1.0), "delta_percent": 12.0, "kwh": DEFAULT * 12.0,
                               "meta": {**raw_capture(0, 1.0)["meta"], "soc_end": 32.0,
                                        "register_end_kwh": 1000.0 + DEFAULT * 12.0}})
    assert low is not None and metadata_reason(low, CAPACITY, NOW) == "rise_below_15"
    taper = Capture.from_stored({**raw_capture(0, 1.0), "delta_percent": 20.0,
                                 "meta": {**raw_capture(0, 1.0)["meta"], "soc_start": 75.0, "soc_end": 95.0}})
    assert taper is not None and metadata_reason(taper, CAPACITY, NOW) == "soc_above_90"
    future = Capture.from_stored(raw_capture(0, 1.0, at=NOW + timedelta(hours=2)))
    assert future is not None and metadata_reason(future, CAPACITY, NOW) == "soc_future"
    exact = Capture.from_stored({**raw_capture(0, 1.0), "delta_percent": 20.0,
                                 "meta": {**raw_capture(0, 1.0)["meta"], "soc_start": 70.0, "soc_end": 90.0}})
    assert exact is not None and metadata_reason(exact, CAPACITY, NOW) is None  # ending exactly at 90% is allowed


def test_rejections_are_counted_once_per_capture_and_reason_not_per_poll():
    store = store_with([1.0] * 4, quality={"gaps": 1})
    for _ in range(5):
        store.learned(CAR, CAPACITY, drop=True, morek=True)
        ended(store)
    assert store.rejection_counts(CAR) == {"gap": 4}
    assert store.learned(CAR, CAPACITY, morek=True).rejections == {"gap": 4} and store.learned(CAR, CAPACITY, morek=True).promoted == 0
    # A different reason for the same capture is a new count; the old one is not counted again.
    store._cars[CAR].captures = [capture(0, 1.0, quality={"restarts": 1})] + store._cars[CAR].captures[1:]  # noqa: SLF001
    store.evaluate(CAR, CAPACITY)
    assert store.rejection_counts(CAR) == {"gap": 4, "restart": 1}


def test_capacity_or_vehicle_change_and_default_fallback():
    store = store_with([1.0] * 5)
    assert ended(store).trusted
    other_capacity = store.learned(CAR, 70.0, drop=True, morek=True)
    assert not other_capacity.trusted and store.rejection_counts(CAR) == {"capacity_changed": 5}
    assert store.learned("another-car", CAPACITY, drop=True, morek=True) == NOTHING_LEARNED or not store.learned(
        "another-car", CAPACITY, drop=True
    ).trusted
    assert not store.learned(CAR, None, drop=True, morek=True).trusted  # no battery size: nothing to judge against
    # Back to the same battery size: proven again and counted no second time.
    assert store.learned(CAR, CAPACITY, drop=True, morek=True).trusted and store.rejection_counts(CAR) == {"capacity_changed": 5}
    # Nothing captured: exactly the legacy answer.
    empty = LearnedEnergyStore(MagicMock(), "entry")
    assert empty.learned(CAR, CAPACITY, drop=True, morek=True) == learned_energy.learned_from(CAR, [])


# ------------------------------------------------------------------------- promotion only at plug-in end, restart
def test_promotion_only_at_plug_in_end_and_never_changes_the_figure_mid_charge():
    store = store_with([1.05] * 3)
    store.set_capture_open((CAR, "plug_in:2"))  # the third plug-in is still charging
    assert not store.learned(CAR, CAPACITY, drop=True, morek=True).trusted and store.learned(CAR, CAPACITY, morek=True).promoted == 2
    store.set_capture_open((CAR, "plug_in:3"))  # plug-in 2 ended and the next began: promoted now, 3 not counted
    assert store.learned(CAR, CAPACITY, drop=True, morek=True).trusted
    figure = store.learned(CAR, CAPACITY, morek=True).use_kwh_per_percent
    # While plug-in 3 charges, a capture growing for it and a conflicting late record change nothing.
    store.put_capture(CAR, capture(3, 1.3), CAPACITY)
    store.checker = lambda *_: "late_uncertain"
    for _ in range(3):
        assert store.learned(CAR, CAPACITY, drop=True, morek=True).use_kwh_per_percent == pytest.approx(figure)
    # At the next plug-in's end the late record fails closed (the default stands) once, with a counted reason.
    store.set_capture_open(None)
    revoked = store.learned(CAR, CAPACITY, drop=True, morek=True)
    assert not revoked.trusted and store.rejection_counts(CAR)["late_uncertain"] == 3


@pytest.mark.asyncio
async def test_promotion_is_persisted_but_a_late_bad_record_cannot_survive_a_restart():
    store = store_with([1.05] * 3)
    assert ended(store).trusted
    store._save()  # noqa: SLF001
    assert FakeStore.saved["vehicles"][CAR]["promoted"] == ["plug_in:0", "plug_in:1", "plug_in:2"]
    restarted = LearnedEnergyStore(MagicMock(), "entry")
    await restarted.async_load()
    restarted.checker = lambda _v, c, _i: "late_uncertain" if c.id == "plug_in:1" else None
    # The very first read after the restart (not even a planning read) proves again: no unproven figure is believed.
    assert not restarted.learned(CAR, CAPACITY, morek=True).trusted and restarted.learned(CAR, CAPACITY, morek=True).promoted == 2
    # With a good checker, the same file is simply trusted again.
    good = LearnedEnergyStore(MagicMock(), "entry")
    await good.async_load()
    good.checker = lambda *_: None
    assert good.learned(CAR, CAPACITY, morek=True).trusted
    # No checker at all (evidence not set up): fail closed to the default, stored promotion included.
    bare = LearnedEnergyStore(MagicMock(), "entry")
    await bare.async_load()
    assert not bare.learned(CAR, CAPACITY, morek=True).trusted


def test_a_failing_checker_or_evaluation_never_raises_and_nothing_stays_promoted():
    def boom(*_):
        raise RuntimeError("store unavailable")

    store = store_with([1.05] * 3)
    assert ended(store).trusted
    store.checker = boom
    assert not store.learned(CAR, CAPACITY, drop=True, morek=True).trusted
    assert store.rejection_counts(CAR) == {"evidence_unavailable": 3}
    store.checker = lambda *_: "not-a-reason"
    assert not store.learned(CAR, CAPACITY, drop=True, morek=True).trusted


def test_a_regrown_capture_for_a_promoted_plug_in_is_proven_again():
    store = store_with([1.05] * 3)
    assert ended(store).trusted
    store.checker = lambda *_: "late_pending"
    store.put_capture(CAR, capture(0, 1.05), CAPACITY)
    assert "plug_in:0" not in store._cars[CAR].promoted  # noqa: SLF001


# -------------------------------------------------------------------- the minimum-SOC need is never weakened
def test_minimum_soc_need_is_not_shortened_by_a_learned_figure():
    facts = LiveVehicleFacts(
        vehicle_id=CAR, soc_percent=30.0, reported_capacity_kwh=CAPACITY, soc_age_s=10.0, soc_source="vehicle",
        soc_report_at=START, soc_time_basis="vehicle_timestamp",
    )
    default = capped_vehicle_energy(facts, target_percent=80, minimum_percent=50, learned=NOTHING_LEARNED)
    shortening = ended(store_with([0.92] * 5))
    assert shortening.trusted
    learned_result = capped_vehicle_energy(facts, target_percent=80, minimum_percent=50, learned=shortening)
    assert learned_result[0] == "ok" and learned_result[1] == pytest.approx(0.92 * default[1])
    assert learned_result[2] == pytest.approx(default[2])  # the floor stays at the default's need
    lengthening = ended(store_with([1.1] * 3))
    longer = capped_vehicle_energy(facts, target_percent=80, minimum_percent=50, learned=lengthening)
    assert longer[2] == pytest.approx(1.1 * default[2])  # a longer need still lengthens the floor too


# ------------------------------------------------- the production proof against sessions and the evidence store
def late(state="consistent", final=True, **extra):
    return {"state": state, "final": final, "unplaced_late_kwh": 0.0, **extra}


def session(start, end, record, vehicle=CAR):
    return SimpleNamespace(start=start, end=end, late=record, vehicle_id=vehicle, unplaced_late_kwh=(
        record["unplaced_late_kwh"] if record and record.get("state") == "reconciled" else None
    ))


class Evidence:
    def __init__(self, rows, gaps=(), starts=()):
        self.rows, self._gaps, self._starts = list(rows), list(gaps), list(starts)

    def samples(self, _charger, _kind, since=None, until=None):
        return [r for r in self.rows if since <= datetime.fromisoformat(r["t"]) < until]

    def gaps(self, _charger, _kind):
        return list(self._gaps)

    def capture_starts(self, _charger):
        return list(self._starts)


SPAN_START, SPAN_END = NOW - timedelta(hours=2), NOW - timedelta(hours=1)


def live_rows():
    return [{"t": (SPAN_START + timedelta(minutes=m)).isoformat(), "r": (SPAN_START + timedelta(minutes=m, seconds=5)).isoformat(),
             "v": 1000.0 + m, "e": ENTITY} for m in range(0, 60, 5)]


def prover(monkeypatch, sessions, evidence="default"):
    world = World(monkeypatch, session_store=None if sessions is None else SimpleNamespace(all_sessions=lambda _e: sessions))
    world.now = NOW
    monkeypatch.setattr(auto_controller, "evidence_for", lambda _hass: Evidence(live_rows()) if evidence == "default" else evidence)
    value = Capture.from_stored(raw_capture(0, 1.0, at=SPAN_END, soc_start_at=SPAN_START.isoformat(),
                                            soc_end_at=SPAN_END.isoformat()))
    assert value is not None
    return world, value


@pytest.mark.parametrize("sessions,initial,expected", [
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late())], True, None),
    ([session(SPAN_START - timedelta(hours=1), None, late())], True, "late_pending"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late(final=False))], True, "late_pending"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late(final=False))], False, None),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), None)], True, "late_pending"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), None)], False, "late_unknown"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late("uncertain", unplaced_late_kwh=None))],
     False, "late_uncertain"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late("reconciled", unplaced_late_kwh=2.0))],
     True, "late_unplaced"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late("inconsistent"))], False, "late_inconsistent"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late("skipped"))], False, "late_unknown"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late(), vehicle="other")], True, "session_vehicle"),
    ([session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late()),
      session(SPAN_START, SPAN_END, late("uncertain", unplaced_late_kwh=None))], False, "late_uncertain"),
    ([], True, "no_session"),
    ([session(NOW + timedelta(days=1), NOW + timedelta(days=2), late())], True, "no_session"),
    (None, True, "evidence_unavailable"),
])
def test_prove_capture_against_session_records(monkeypatch, sessions, initial, expected):
    world, value = prover(monkeypatch, sessions)
    assert world.planner._prove_capture(CAR, value, initial) == expected  # noqa: SLF001


@pytest.mark.parametrize("evidence,expected", [
    (Evidence(live_rows()), None),
    (Evidence(live_rows(), gaps=[{"r": (SPAN_START + timedelta(minutes=20)).isoformat(), "g": "link_down", "v": None}]), "link_down"),
    (Evidence(live_rows(), gaps=[{"r": (SPAN_START + timedelta(minutes=20)).isoformat(), "g": "unavailable", "v": None}]),
     "evidence_gap"),
    (Evidence(live_rows(), gaps=[{"r": (SPAN_START - timedelta(hours=1)).isoformat(), "g": "link_down", "v": None}]), None),
    (Evidence(live_rows(), starts=[(SPAN_START + timedelta(minutes=30)).isoformat()]), "restart"),
    (Evidence(live_rows(), starts=[(SPAN_END + timedelta(minutes=30)).isoformat()]), None),
    (Evidence([{**live_rows()[0], "r": (SPAN_START + timedelta(hours=1)).isoformat()}]), "replay"),
    (Evidence([{**live_rows()[0], "q": ["out_of_order"]}]), "replay"),
    (Evidence([]), "evidence_unavailable"),
    (None, "evidence_unavailable"),
    # a single row, a missing start or end, a hole or another entity's rows is not coverage of the stretch
    (Evidence(live_rows()[:1]), "evidence_gap"),
    (Evidence(live_rows()[:3]), "evidence_gap"),
    (Evidence(live_rows()[6:]), "evidence_gap"),
    (Evidence(live_rows()[:4] + live_rows()[-1:]), "evidence_gap"),
    (Evidence([{**row, "e": "sensor.other"} for row in live_rows()]), "evidence_unavailable"),
    (Evidence(live_rows(), gaps=[{"r": (SPAN_START + timedelta(minutes=10)).isoformat(),
                                  "r2": (SPAN_START + timedelta(minutes=30)).isoformat(), "g": "unavailable", "v": None}]),
     "evidence_gap"),
])
def test_prove_capture_against_retained_evidence_rows(monkeypatch, evidence, expected):
    world, value = prover(monkeypatch, [session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late())],
                          evidence)
    assert world.planner._prove_capture(CAR, value, True) == expected  # noqa: SLF001
    assert world.planner._prove_capture(CAR, value, False) is None  # noqa: SLF001 - revalidation reads sessions only


def test_prove_capture_wiring_and_expired_evidence(monkeypatch):
    world, value = prover(monkeypatch, [session(SPAN_START - timedelta(hours=1), SPAN_END + timedelta(hours=1), late())])
    world.controller.energy_register_entity_id = "sensor.other"
    assert world.planner._prove_capture(CAR, value, False) == "wiring_changed"  # noqa: SLF001
    world.controller.energy_register_entity_id = ENTITY
    world.phases = 1
    assert world.planner._prove_capture(CAR, value, False) == "wiring_changed"  # noqa: SLF001
    world.phases = 3
    monkeypatch.setattr(auto_controller, "voltage_between_phases_v", lambda *_: 230.0)
    assert world.planner._prove_capture(CAR, value, False) == "wiring_changed"  # noqa: SLF001
    monkeypatch.setattr(auto_controller, "voltage_between_phases_v", lambda *_: 402.0)
    assert world.planner._prove_capture(CAR, value, False) is None  # noqa: SLF001
    world.now = NOW + timedelta(days=4)  # the retained rows no longer cover the stretch
    assert world.planner._prove_capture(CAR, value, True) == "evidence_expired"  # noqa: SLF001


# ----------------------------------------------------------- end to end through the production capture tick
async def charge_one_plug_in(world, index):
    world.plugged = START - timedelta(hours=1) + timedelta(days=index)
    world.controller.plugged_in_for_count = world.controller.plugged_in_since = world.plugged
    world.controller.known_connected = True
    world.soc, world.register = 20.0, 1000.0
    await world.run(100)


@pytest.mark.asyncio
async def test_promotion_wiring_through_the_capture_tick_and_unplug(monkeypatch):
    store = SimpleNamespace(all_sessions=lambda _e: [session(START - timedelta(days=30), START + timedelta(days=30), late())])
    world = World(monkeypatch, session_store=store)
    world.capacity = 70.0  # the car takes 10% more than the default for its battery: the figure may only lengthen
    monkeypatch.setattr(auto_controller, "evidence_for", lambda _hass: SimpleNamespace(
        samples=lambda _c, _k, since=None, until=None: [
            {"t": (since + timedelta(minutes=5 * i)).isoformat(), "r": (since + timedelta(minutes=5 * i)).isoformat(),
             "v": 1.0, "e": ENTITY}
            for i in range(int((until - since).total_seconds() // 300) + 1)
        ],
        gaps=lambda *_: [], capture_starts=lambda *_: [],
    ))
    assert world.les.checker is not None  # production wiring: the controller installed its proof
    original_now = world.planner._now  # noqa: SLF001
    for index in range(3):
        world.now = START + timedelta(days=index)
        await charge_one_plug_in(world, index)
        assert world.les.capture_open is not None
        assert not world.les.learned(CAR, 70.0, morek=True).trusted  # mid-charge: nothing changes, nothing is promoted yet
        world.controller.known_connected = False
        world.planner._arm_capture()  # noqa: SLF001 - an unplug that no tick will report ends the plug-in
        assert world.les.capture_open is None
    assert original_now() >= START
    monkeypatch.setattr(learned_energy.dt_util, "utcnow", lambda: world.now + timedelta(hours=1))
    learned = world.les.learned(CAR, 70.0, drop=True, morek=True)
    assert learned.promoted == 3 and learned.trusted and learned.from_promoted, world.les.rejection_counts(CAR)
    default = 70.0 / learned_energy.CHARGE_EFFICIENCY / 100.0
    assert learned.use_kwh_per_percent == pytest.approx(0.77 / 0.8, rel=0.03) and learned.use_kwh_per_percent > default
    world.recalculate.assert_not_called()  # promotion never replans or sends by itself


@pytest.mark.asyncio
async def test_unproven_capture_after_unplug_leaves_the_default_and_is_counted(monkeypatch):
    world = World(monkeypatch, session_store=SimpleNamespace(all_sessions=lambda _e: []))
    await world.run(100)
    assert world.captures()
    world.controller.known_connected = False
    world.planner._arm_capture()  # noqa: SLF001
    learned = world.les.learned(CAR, CAPACITY, drop=True, morek=True)
    assert not learned.trusted and learned.promoted == 0 and learned.rejections == {"no_session": 1}
    world.planner._arm_capture()  # noqa: SLF001
    world.les.learned(CAR, CAPACITY, drop=True, morek=True)
    assert world.les.rejection_counts(CAR) == {"no_session": 1}  # once per capture and reason
    assert learned.as_dict()["rejections"] == {"no_session": 1} and learned.as_dict()["from_promoted"] is False


# ------------------------------------------- the minimum never exceeds the requested need, whatever the learned figure
@pytest.mark.parametrize("soc,minimum", [(50.0, 80), (79.0, 80), (50.0, 79), (30.0, 78), (50.0, 60)])
def test_minimum_close_to_target_is_protected_and_never_above_the_request(soc, minimum):
    facts = LiveVehicleFacts(
        vehicle_id=CAR, soc_percent=soc, reported_capacity_kwh=CAPACITY, soc_age_s=10.0, soc_source="vehicle",
        soc_report_at=START, soc_time_basis="vehicle_timestamp",
    )
    default = capped_vehicle_energy(facts, target_percent=80, minimum_percent=minimum, learned=NOTHING_LEARNED)
    shortening = ended(store_with([0.90] * 5))
    assert shortening.trusted and shortening.use_kwh_per_percent < DEFAULT
    reason, target_kwh, minimum_kwh = capped_vehicle_energy(
        facts, target_percent=80, minimum_percent=minimum, learned=shortening
    )
    assert reason == "ok" and minimum_kwh == pytest.approx(default[2])  # the default floor is kept, never clipped down
    assert minimum_kwh <= target_kwh  # what PlanRequest.validated demands
    assert target_kwh >= default[1] * (minimum - soc) / (80 - soc) - 1e-9
    if minimum == 80:
        assert target_kwh == pytest.approx(default[1])  # the soft cap still protects the whole need
    longer = capped_vehicle_energy(facts, target_percent=80, minimum_percent=minimum, learned=ended(store_with([1.1] * 3)))
    assert longer[1] == pytest.approx(1.1 * default[1]) and longer[2] == pytest.approx(1.1 * default[2])


# ------------------------------------------------ Morek never reads the legacy samples; non-Morek keeps its own rules
def _legacy(store, factor, count):
    for index in range(count):
        sample = learned_energy.EnergySample(f"legacy:{index}", DEFAULT * factor * 20.0, 20.0, START + timedelta(days=index))
        assert store.put(CAR, sample, CAPACITY)


def test_morek_ignores_legacy_samples_and_needs_five_promoted_to_shorten():
    store = store_with([0.9] * 4)
    _legacy(store, 0.9, 3)  # three trusted legacy samples that shorten the time
    store.set_capture_open(None)
    assert store.learned(CAR, CAPACITY, drop=True).trusted  # non-Morek: the legacy rules are unchanged
    legacy = store.learned(CAR, CAPACITY)
    assert legacy.use_kwh_per_percent == pytest.approx(0.9 * DEFAULT) and legacy.promoted == 0
    morek = store.learned(CAR, CAPACITY, drop=True, morek=True)
    assert not morek.trusted and morek.use_kwh_per_percent is None and morek.promoted == 4 and not morek.samples
    assert capped_vehicle_energy.__name__  # four agreeing promoted votes cannot shorten: the default stands
    assert ended(store_with([0.9] * 5)).trusted  # the fifth (and only then) shortens


def test_morek_without_proof_uses_the_default_whatever_the_legacy_samples_say():
    store = store_with([0.9] * 5, checker=lambda *_: "no_session")
    _legacy(store, 0.9, 5)
    store.set_capture_open(None)
    morek = store.learned(CAR, CAPACITY, drop=True, morek=True)
    assert not morek.trusted and morek.use_kwh_per_percent is None and morek.promoted == 0
    assert store.learned(CAR, CAPACITY, drop=True).trusted  # non-Morek legacy, unchanged


def test_morek_with_only_legacy_samples_is_the_default():
    store = LearnedEnergyStore(MagicMock(), "entry")
    _legacy(store, 1.1, 5)
    assert store.learned(CAR, CAPACITY).trusted
    assert not store.learned(CAR, CAPACITY, morek=True).trusted
