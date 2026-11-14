"""Stage 17.3: missing-capacity fallback for the capped (soft price cap) target path.

The capped energy resolver, the real controller (with a real `LearnedEnergyStore`, unchanged learner rules), the guarded
admission blocker, the status/dashboard surfaces and the real Morek worker (HA/OCPP are the usual mocked boundaries).
Not deployed or physically verified. A capacity is never guessed: with neither a battery size nor a trusted learned wall
kWh per percent the plan holds as `target_capacity_unknown`.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.spotnav.planning import auto_controller, learned_energy
from custom_components.spotnav.planning.auto_controller import LiveVehicleFacts, capped_vehicle_energy
from custom_components.spotnav.planning.learned_energy import (
    CHARGE_EFFICIENCY, EnergySample, LearnedEnergy, LearnedEnergyStore, NOTHING_LEARNED,
)
from .test_morek_worker import drain, real_planner_worker
from .test_stage_13_reactive import _world
from .test_stage_159a_energy_capture import FakeStore
from .test_stage_159b_promotion import CAPACITY, DEFAULT, NOW, capture

CAR = "veh-1"
RATIO = 0.8  # wall kWh per percent
FIG = 1.05 * DEFAULT  # the wall kWh per percent three agreeing Morek votes give (lengthens: trusted with 3)


@pytest.fixture(autouse=True)
def _zones(monkeypatch):
    from zoneinfo import ZoneInfo
    from custom_components.spotnav import time_zones
    time_zones._remember("Europe/Stockholm", ZoneInfo("Europe/Stockholm"))  # noqa: SLF001
    FakeStore.saved = None
    monkeypatch.setattr(learned_energy, "Store", FakeStore)
    monkeypatch.setattr(learned_energy.dt_util, "utcnow", lambda: NOW)


def facts(capacity=None, **kw):
    base = dict(vehicle_id=CAR, soc_percent=25, soc_age_s=5, reported_capacity_kwh=capacity)
    base.update(kw)
    return LiveVehicleFacts(**base)


def trusted(ratio=RATIO):
    return LearnedEnergy(vehicle_id=CAR, kwh_per_percent=ratio, samples=(), trusted=True)


def legacy_store(ratios, now):
    """A real store holding one legacy sample per ratio (20 points each); non-Morek learning reads these."""
    store = LearnedEnergyStore(MagicMock(), "entry")
    for index, ratio in enumerate(ratios):
        sample = EnergySample(f"legacy:{index}", ratio * 20.0, 20.0, now - timedelta(days=index + 1))
        assert store.put(CAR, sample, None)  # accepted without a battery size: the implied size is believable
    return store


def morek_store(factors, *, checker=lambda *_: None, **changes):
    """A real store holding one promotable capture per factor (x the default wall kWh per percent), ended plug-ins."""
    store = LearnedEnergyStore(MagicMock(), "entry")
    store.checker = checker
    for index, factor in enumerate(factors):
        assert store.put_capture(CAR, capture(index, factor, **changes), CAPACITY)
    store.set_capture_open(None)
    return store


def install(w, monkeypatch, store, *, morek=True):
    """Production wiring: the controller's own `_learned_energy_for` reads the store (the harness stub is removed)."""
    vars(w.controller).pop("_learned_energy_for", None)
    w.controller._learned_energy = store  # noqa: SLF001
    w.controller._morek_learning = lambda: morek  # noqa: SLF001
    monkeypatch.setattr(auto_controller, "resolved_vehicle_id", lambda *_: CAR)


# ---- the capped resolver -------------------------------------------------------------------------------------------

def referenced(ratio=RATIO, reference=60.0):
    return LearnedEnergy(vehicle_id=CAR, kwh_per_percent=ratio, samples=(), trusted=True, reference_capacity_kwh=reference)


def test_trusted_learned_figure_plans_without_capacity_with_the_same_arithmetic():
    kw = dict(target_percent=80, minimum_percent=40)
    known = capped_vehicle_energy(facts(60), learned=trusted(), **kw)
    # With a recorded reference capacity (Morek votes) the plan is the same arithmetic as with a known capacity:
    # wall kWh = points x learned wall kWh per percent, 55 x 0.8 and 15 x 0.8.
    unknown = capped_vehicle_energy(facts(None), learned=referenced(), **kw)
    assert unknown == ("ok", pytest.approx(44.0), pytest.approx(12.0))
    assert known[0] == "ok" and known[1] == pytest.approx(44.0) and known[2] == pytest.approx(12.0)
    # Target semantics are untouched: the car's own limit lowers the target, a minimum above it is refused.
    assert capped_vehicle_energy(facts(None, max_percent=60), learned=referenced(), **kw)[1] == pytest.approx(35 * RATIO)
    assert capped_vehicle_energy(facts(None, max_percent=35), learned=referenced(), **kw)[0] == "minimum_above_target"
    assert capped_vehicle_energy(facts(None, soc_percent=45), learned=referenced(), **kw)[2] == 0  # minimum already met
    assert capped_vehicle_energy(facts(None), learned=trusted(), target_percent=80, minimum_percent=None)[2] is None


def test_minimum_soc_floor_is_never_weakened_without_a_capacity():
    kw = dict(target_percent=80, minimum_percent=40)
    # A learned figure with no capacity and no recorded reference has no default to protect a real minimum-SOC need:
    # it holds (truthfully) instead of silently allowing a smaller minimum energy.
    assert capped_vehicle_energy(facts(None), learned=trusted(), **kw) == ("target_capacity_unknown", None, None)
    assert capped_vehicle_energy(facts(None), learned=trusted(0.1), **kw)[0] == "target_capacity_unknown"
    # ... but when the minimum is already met (nothing to protect) or there is no minimum, the learned figure plans.
    assert capped_vehicle_energy(facts(None, soc_percent=45), learned=trusted(), **kw)[0] == "ok"
    assert capped_vehicle_energy(facts(None), learned=trusted(), target_percent=80, minimum_percent=None)[0] == "ok"
    # With the recorded reference the learned figure may lengthen the minimum, never shorten it below the default's.
    default = capped_vehicle_energy(facts(60), learned=NOTHING_LEARNED, **kw)
    shorter = capped_vehicle_energy(facts(None), learned=referenced(0.5, 60.0), **kw)
    assert shorter[0] == "ok" and shorter[2] == pytest.approx(default[2]) and shorter[1] >= shorter[2]
    longer = capped_vehicle_energy(facts(None), learned=referenced(1.2, 60.0), **kw)
    assert longer[2] == pytest.approx(15 * 1.2)


@pytest.mark.parametrize("learned", [NOTHING_LEARNED, LearnedEnergy(CAR, RATIO, (), False)])
def test_no_capacity_and_no_trusted_figure_holds_without_guessing(learned):
    assert capped_vehicle_energy(facts(None), target_percent=80, minimum_percent=40, learned=learned) == (
        "target_capacity_unknown", None, None)


@pytest.mark.parametrize("bad", [0, -60, float("nan"), float("inf"), True, "60"])
def test_invalid_capacity_is_missing_never_used(bad):
    kw = dict(target_percent=80, minimum_percent=40)
    assert capped_vehicle_energy(facts(bad), learned=NOTHING_LEARNED, **kw)[0] == "target_capacity_unknown"
    assert capped_vehicle_energy(facts(bad), learned=referenced(), **kw)[1] == pytest.approx(44.0)  # learned figure only


def test_known_capacity_behaviour_is_unchanged():
    kw = dict(target_percent=80, minimum_percent=40)
    default = capped_vehicle_energy(facts(60), learned=NOTHING_LEARNED, **kw)
    assert default[1] == pytest.approx(55 * 60 / CHARGE_EFFICIENCY / 100) and default[2] == pytest.approx(15 * 60 / CHARGE_EFFICIENCY / 100)
    shorter = capped_vehicle_energy(facts(60), learned=trusted(0.5), **kw)  # a learned figure never shortens the floor
    assert shorter[2] == pytest.approx(default[2])
    # staleness / missing level still decide before capacity does
    assert capped_vehicle_energy(facts(None, soc_percent=None), learned=trusted(), **kw)[0] == "target_soc_unknown"
    assert capped_vehicle_energy(facts(None, soc_percent=101), learned=trusted(), **kw)[0] == "target_soc_stale"


def test_legacy_learner_rules_are_unchanged_untrusted_data_is_not_used():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert legacy_store([RATIO] * 3, now).learned(CAR, None).trusted
    assert not legacy_store([RATIO] * 2, now).learned(CAR, None).trusted  # two of three needed samples
    assert not legacy_store([0.8, 0.8, 1.6], now).learned(CAR, None).trusted  # only two agree
    assert not legacy_store([RATIO] * 3, now).learned(CAR, None, morek=True).trusted  # Morek never reads legacy samples


def _learn(store, capacity=None, **kw):
    return store.learned(CAR, capacity, drop=True, morek=True, **kw)


def test_morek_votes_stand_on_their_recorded_capacity_without_today_capacity():
    got = _learn(morek_store([1.05] * 3))
    assert got.trusted and got.from_promoted and got.reference_capacity_kwh == CAPACITY
    assert got.use_kwh_per_percent == pytest.approx(1.05 * DEFAULT)
    assert _learn(morek_store([1.05] * 3), CAPACITY).reference_capacity_kwh is None  # today's capacity validates them
    # the same asymmetric rules as with a capacity: 4 agreeing cannot shorten, 5 can, the clamp bounds the figure
    assert not _learn(morek_store([0.95] * 4)).trusted
    five = _learn(morek_store([0.95] * 5))
    assert five.trusted and five.use_kwh_per_percent == pytest.approx(0.95 * DEFAULT)
    assert _learn(morek_store([1.28] * 3)).use_kwh_per_percent == pytest.approx(1.25 * DEFAULT)
    # an invalid capacity is a missing one, not a conflict
    assert _learn(morek_store([1.05] * 3), float("nan")).reference_capacity_kwh == CAPACITY


def test_morek_votes_without_capacity_reject_untrusted_wrong_or_invalid_records():
    assert not _learn(morek_store([1.05] * 2)).trusted  # too few votes
    assert not _learn(morek_store([1.0, 1.05, 1.28])).trusted  # only two agree
    assert not _learn(morek_store([1.05] * 3, checker=lambda *_: "other_vehicle")).trusted  # identity not proven
    assert not _learn(morek_store([1.05] * 3, checker=None)).trusted  # nothing to prove them with
    assert not _learn(morek_store([1.05] * 3, quality={"gaps": 1})).trusted  # a gap in the stretch
    assert not _learn(morek_store([1.05] * 3, late_energy="uncertain")).trusted
    assert not _learn(morek_store([1.05] * 3, soc_time_basis="estimated")).trusted
    open_store = morek_store([1.05] * 3)
    open_store.set_capture_open((CAR, "plug_in:2"))  # the newest plug-in is still charging: two votes only
    assert not _learn(open_store).trusted
    assert not morek_store([1.05] * 3).learned("another-car", None, drop=True, morek=True).trusted
    # votes recorded with different sizes: only those matching the newest one count
    mixed = morek_store([1.05] * 2)
    mixed.put_capture(CAR, capture(2, 1.2, capacity_kwh=CAPACITY + 10), CAPACITY + 10)
    assert not _learn(mixed).trusted
    # a known different battery size refutes the votes for good, also when the size later goes missing again
    store = morek_store([1.05] * 3)
    assert not _learn(store, 70.0).trusted
    assert not _learn(store).trusted and store.rejection_counts(CAR) == {"capacity_changed": 3}
    assert _learn(store, CAPACITY).trusted  # the original size proves them again


# ---- the real controller -------------------------------------------------------------------------------------------

def test_capped_plan_from_learned_figure_labelled_and_recovers_when_capacity_or_figure_arrives(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        now = w.request.now
        c = w.controller
        install(w, monkeypatch, morek_store([]))
        w.facts[0] = facts(None)
        held = await c.async_recalculate()
        assert held.state == "planning_unavailable" and held.reason == "target_capacity_unknown" and held.proposal is None
        # an untrusted figure (two samples) is not used
        install(w, monkeypatch, morek_store([1.05] * 2))
        assert (await c.async_recalculate()).reason == "target_capacity_unknown"
        # a trusted figure arrives: planned from it, labelled, no capacity claimed
        install(w, monkeypatch, morek_store([1.05] * 3))
        c._soc_newest.clear()  # noqa: SLF001
        snap = await c.async_recalculate()
        assert snap.proposal is not None, (snap.state, snap.reason)
        assert snap.proposal.requested_kwh == pytest.approx(55 * FIG)
        assert snap.projection_capacity_unknown is True and snap.projection_kwh_per_percent == pytest.approx(FIG)
        assert snap.projection_soc == 25 and not snap.projection_estimated
        # the labelled state is part of the notification key (a flip is news), and of the decision inputs
        assert snap.meaningful_key() != replace(snap, projection_capacity_unknown=False).meaningful_key()
        # the battery size arrives (stored capacity): planned from it with the unchanged rules, label cleared
        install(w, monkeypatch, morek_store([]))
        w.facts[0] = facts(60)
        c._soc_newest.clear()  # noqa: SLF001
        back = await c.async_recalculate()
        assert back.proposal is not None and back.projection_capacity_unknown is False
        assert back.proposal.requested_kwh == pytest.approx(55 * 60 / CHARGE_EFFICIENCY / 100)
    asyncio.run(run())


def test_identity_and_invalid_level_still_hold_with_a_learned_figure(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        c = w.controller
        install(w, monkeypatch, morek_store([1.05] * 3))
        w.facts[0] = facts(None)
        monkeypatch.setattr(c, "_notification_vehicle", lambda: (True, "veh-2"))  # a reading for another car
        assert (await c.async_recalculate()).reason == "target_soc_stale"
        monkeypatch.setattr(c, "_notification_vehicle", lambda: (True, CAR))
        w.facts[0] = facts(None, soc_percent=None)
        assert (await c.async_recalculate()).reason == "target_soc_unknown"
        w.facts[0] = facts(float("nan"))  # an invalid capacity is a missing one: the learned figure still plans
        c._soc_newest.clear()  # noqa: SLF001
        snap = await c.async_recalculate()
        assert snap.proposal is not None and snap.projection_capacity_unknown is True
        install(w, monkeypatch, morek_store([]))
        assert (await c.async_recalculate()).reason == "target_capacity_unknown"
    asyncio.run(run())


def test_uncapped_target_path_is_unchanged(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        c = w.controller
        install(w, monkeypatch, legacy_store([], w.request.now), morek=False)
        w.facts[0] = facts(None)
        await _save_uncapped(w)
        snap = await c.async_recalculate()
        assert snap.state == "incomplete_settings" and snap.reason == "target_capacity_unknown" and snap.missing == ("capacity",)
        install(w, monkeypatch, legacy_store([RATIO] * 3, w.request.now), morek=False)
        # (the harness's price entry lacks what a full uncapped calculation needs: the energy step is read directly)
        resolved = await c._energy_for(w.store.settings("test"), w.request.now, w.area.catalogue, None)  # noqa: SLF001
        assert resolved.kwh == pytest.approx(44.0) and resolved.kwh_per_percent == pytest.approx(RATIO)
        assert resolved.capacity_kwh is None and resolved.minimum_energy_kwh is None
    asyncio.run(run())


async def _save_uncapped(w):
    await w.store.async_update("test", mutate=lambda s: replace(s, soft_price_cap=None, minimum_ready_by_soc=None))


def test_blocker_and_evidence_follow_the_capacity_and_figure(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        c = w.controller
        install(w, monkeypatch, morek_store([1.05] * 3))
        w.facts[0] = facts(None)
        snap = await c.async_recalculate()
        assert snap.proposal is not None
        assert c.morek_plan_blocker(snap, w.request.now) is None  # no new admission rule: price/identity guards only
        w.facts[0] = facts(60)  # the battery size arrives: the plan's inputs changed, it is recalculated before any send
        assert c.morek_plan_blocker(snap, w.request.now) == "plan_inputs_changed"
        w.facts[0] = facts(None)
        install(w, monkeypatch, morek_store([1.05 * 1.0001] * 3))
        assert c.morek_plan_blocker(snap, w.request.now) != "vehicle_input_unavailable"
    asyncio.run(run())


def test_learning_block_is_consistent_with_the_plan(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        c = w.controller
        install(w, monkeypatch, morek_store([1.05] * 3))
        block = c.learning_estimate(CAR, None, soc_percent=25, target_percent=80, vehicle_max_percent=None, capped=True,
                                    minimum_percent=40)
        assert block["source"] == "learned" and block["need_kwh"] == pytest.approx(55 * FIG, abs=1e-3)
        assert block["default_need_kwh"] is None and block["default_kwh_per_percent"] is None  # nothing invented
        snap = await _recalc(w)
        assert snap.proposal.requested_kwh == pytest.approx(block["need_kwh"], abs=1e-3)
        install(w, monkeypatch, morek_store([]))
        none = c.learning_estimate(CAR, None, soc_percent=25, target_percent=80, vehicle_max_percent=None, capped=True,
                                   minimum_percent=40)
        assert none["need_kwh"] is None and none["source"] == "default"
    asyncio.run(run())


async def _recalc(w):
    w.facts[0] = facts(None)
    w.controller._soc_newest.clear()  # noqa: SLF001
    return await w.controller.async_recalculate()


def test_status_and_inputs_surfaces(monkeypatch):
    from custom_components.spotnav.api import morek_schedule
    from custom_components.spotnav.planning.status_compose import _soc_missing
    from custom_components.spotnav.planning.status_compose import StatusFacts

    async def run():
        w = await _world(monkeypatch)
        install(w, monkeypatch, morek_store([1.05] * 3))
        await _recalc(w)
        monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: w.controller)
        inputs = morek_schedule._planning_inputs(MagicMock(), "test")  # noqa: SLF001
        assert inputs["capacity_unknown"] is True and inputs["soc_estimated"] is False
        install(w, monkeypatch, morek_store([]))
        held = await _recalc(w)
        assert held.reason == "target_capacity_unknown"
        assert morek_schedule._planning_inputs(MagicMock(), "test")["capacity_unknown"] is False  # noqa: SLF001
    asyncio.run(run())
    # the held plan says which fact is missing, so the sentence names who acts (the capacity), not the level
    assert _soc_missing(SimpleNamespace(soc=None), "target_capacity_unknown") == ["capacity"]
    assert _soc_missing(SimpleNamespace(soc=SimpleNamespace(missing=("capacity",))), "target_capacity_unknown") == ["capacity"]
    assert StatusFacts is not None


# ---- the real worker -----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hold_sends_nothing_then_a_trusted_figure_sends_once_and_nothing_resends(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    now = world.request.now
    install(world, monkeypatch, morek_store([]))
    world.facts[0] = facts(None)
    world.controller._soc_newest.clear()  # noqa: SLF001
    held = await world.controller.async_recalculate()
    assert held.reason == "target_capacity_unknown"
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0  # nothing is dispatched while the capacity and figure are both missing
    install(world, monkeypatch, morek_store([1.05] * 3))  # recovery: the existing recalculation round
    world.controller._soc_newest.clear()  # noqa: SLF001
    snap = await world.controller.async_recalculate()
    assert snap.proposal is not None and snap.projection_capacity_unknown is True
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.controller._soc_newest.clear()  # noqa: SLF001
    again = await world.controller.async_recalculate()  # an unchanged input resends nothing
    assert again.proposal is not None
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()
