"""Stage 15.11: the learned-estimate display block, the backend-computed effect, and the administrator's reset (mocked; no
`hass` fixture, no HA/charger). Reuses the 15.9a world (real controller, store and samplers with fakes) and the 15.9b
store helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.spotnav.api import dashboard, morek_schedule
from custom_components.spotnav.planning import learned_energy, learned_power
from custom_components.spotnav.planning.learned_energy import LearnedEnergyStore, NOTHING_LEARNED
from tests.test_stage_159a_energy_capture import CAPACITY, CAR, START, FakeStore, World
from tests.test_stage_159b_promotion import (  # noqa: F401
    DEFAULT, fixtures, store_with,
)


def view(store, *, morek=True, soc=30.0, target=80.0, capacity=CAPACITY):
    learned = store.learned(CAR, capacity, morek=morek)
    kwargs = dict(soc_percent=soc, capacity_kwh=capacity, target_percent=target)
    _, need = learned_energy.target_need(learned, **kwargs)
    _, default_need = learned_energy.target_need(NOTHING_LEARNED, **kwargs)
    return learned_energy.estimate_view(learned, capacity, morek=morek, need_kwh=need, default_need_kwh=default_need)


def fields(block, power_kw=10.0):
    soc = SimpleNamespace(learning=block)
    proposal = SimpleNamespace(power_kw=power_kw)
    return dashboard._learning_fields(SimpleNamespace(soc=soc), proposal).get("learning")  # noqa: SLF001


# ------------------------------------------------------------------------------------------------------ display
def test_default_estimate_when_nothing_is_trusted_has_zero_effect():
    block = view(LearnedEnergyStore(MagicMock(), "entry"))
    assert block["source"] == "default" and block["mode"] == "morek"
    assert block["valid_samples"] == 0 and block["agreeing_samples"] == 0
    assert (block["needed_to_lengthen"], block["needed_to_shorten"]) == (3, 5)
    assert block["kwh_per_percent"] is None and block["default_kwh_per_percent"] == pytest.approx(DEFAULT, abs=1e-4)
    assert fields(block)["effect_minutes"] == 0


def test_learned_lengthening_effect_minutes_come_from_the_backend_need_difference():
    block = view(ended_store([1.05] * 3))
    assert block["source"] == "learned" and block["agreeing_samples"] == 3 and not block["clamped"]
    result = fields(block, power_kw=10.0)
    expected = round(((1.05 - 1.0) * DEFAULT * 50.0) / 10.0 * 60.0)  # 50 points of need, 10 kW
    assert result["effect_minutes"] == expected and expected > 0
    # Unknown power, level or battery: the effect is unknown, never zero.
    assert fields(block, power_kw=None)["effect_minutes"] is None
    assert fields(block, power_kw=0)["effect_minutes"] is None
    assert fields({**block, "need_kwh": None})["effect_minutes"] is None


def ended_store(factors):
    store = store_with(factors)
    store.set_capture_open(None)
    return store


def test_agreeing_count_excludes_outliers_and_shortening_needs_five():
    outlier = view(ended_store([1.05] * 4 + [1.27]))
    assert outlier["valid_samples"] == 5 and outlier["agreeing_samples"] == 4 and outlier["source"] == "learned"
    four_short = view(ended_store([0.95] * 4))
    # Four agreeing shortening charges may not shorten: the default stands, the counts are still stated.
    assert four_short["source"] == "default" and four_short["agreeing_samples"] == 4 and four_short["valid_samples"] == 4
    assert fields(four_short)["effect_minutes"] == 0
    five_short = view(ended_store([0.95] * 5))
    shorter = fields(five_short)
    assert five_short["source"] == "learned" and shorter["effect_minutes"] < 0
    split = view(ended_store([0.9, 0.97, 1.1, 1.2, 1.27]))
    assert split["valid_samples"] == 5 and split["agreeing_samples"] < 3 and split["source"] == "default"


def test_clamp_is_flagged_and_rejection_reasons_are_counted_in_the_block_and_diagnostics():
    clamped = view(ended_store([1.28] * 3))
    assert clamped["clamped"] is True and clamped["kwh_per_percent"] == pytest.approx(1.25 * DEFAULT, abs=1e-4)
    rejected = store_with([1.05] * 3, checker=lambda *_: "late_unknown")
    rejected.set_capture_open(None)
    block = view(rejected)
    assert block["source"] == "default" and block["rejections"] == {"late_unknown": 3}
    learned = rejected.learned(CAR, CAPACITY, morek=True)
    assert learned.as_dict()["rejections"] == {"late_unknown": 3} and "agreeing" in learned.as_dict()


def test_missing_fields_and_old_shapes_never_break_or_invent_precision():
    block = learned_energy.estimate_view(NOTHING_LEARNED, None, morek=True)
    assert block["source"] == "default" and block["default_kwh_per_percent"] is None and block["need_kwh"] is None
    assert fields(block)["effect_minutes"] == 0  # default: nothing learned to change the time
    assert dashboard._learning_fields(SimpleNamespace(soc=None), SimpleNamespace(power_kw=1.0)) == {}  # noqa: SLF001
    assert dashboard._learning_fields(SimpleNamespace(soc=SimpleNamespace(learning=None)), SimpleNamespace(power_kw=1.0)) == {}  # noqa: SLF001
    assert fields({"source": "learned"})["effect_minutes"] is None  # a learned block lacking its needs
    legacy = learned_energy.estimate_view(NOTHING_LEARNED, CAPACITY, morek=False)
    assert legacy["mode"] == "legacy" and legacy["needed_to_lengthen"] == legacy["needed_to_shorten"] == 3


def test_controller_block_uses_the_planners_own_need_and_never_a_foreign_car(monkeypatch):
    world = World(monkeypatch)
    block = world.planner.learning_estimate(CAR, CAPACITY, soc_percent=30.0, target_percent=80.0, vehicle_max_percent=None)
    assert block["source"] == "default" and block["need_kwh"] == block["default_need_kwh"] > 0
    assert world.planner.learning_estimate(None, CAPACITY, soc_percent=30.0, target_percent=80.0, vehicle_max_percent=None) is None
    other = world.planner.learning_estimate("other", CAPACITY, soc_percent=30.0, target_percent=80.0, vehicle_max_percent=None)
    assert other["source"] == "default" and other["valid_samples"] == 0


def _estimate(world, store, **kw):
    learned = store.learned(CAR, CAPACITY, morek=True)
    world.planner.learned_energy = lambda *_a, **_k: learned
    args = dict(soc_percent=50.0, target_percent=80.0, vehicle_max_percent=None, capped=True, minimum_percent=80)
    args.update(kw)
    return world.planner.learning_estimate(CAR, CAPACITY, **args)


def test_minimum_equal_to_target_keeps_the_default_need_and_shows_no_effect(monkeypatch):
    world = World(monkeypatch)
    block = _estimate(world, ended_store([0.90] * 5))
    assert block["source"] == "learned" and block["need_kwh"] == pytest.approx(block["default_need_kwh"])
    assert fields(block)["effect_minutes"] == 0


def test_minimum_near_target_bounds_the_effect_by_the_floor(monkeypatch):
    world = World(monkeypatch)
    store = ended_store([0.90] * 5)
    near = _estimate(world, store, minimum_percent=79)
    assert near["need_kwh"] == pytest.approx(near["default_need_kwh"] * 29 / 30, abs=1e-2)
    unbounded = _estimate(world, store, capped=False)
    assert fields(near)["effect_minutes"] < 0 and fields(near)["effect_minutes"] > fields(unbounded)["effect_minutes"]


def test_ordinary_soc_and_minimum_still_shorten_and_unknown_stays_unknown(monkeypatch):
    world = World(monkeypatch)
    store = ended_store([0.92] * 5)
    block = _estimate(world, store, soc_percent=30.0, minimum_percent=50)
    assert block["need_kwh"] == pytest.approx(0.92 * block["default_need_kwh"], abs=1e-2) and fields(block)["effect_minutes"] < 0
    unknown = _estimate(world, store, soc_percent=None)
    assert unknown["need_kwh"] is None and fields(unknown)["effect_minutes"] is None
    # No planner-usable figure at all (default source) stays 0, never invented.
    assert fields(_estimate(world, LearnedEnergyStore(MagicMock(), "entry")))["effect_minutes"] == 0


def test_manual_energy_plan_never_claims_the_learned_figure_changes_it(monkeypatch):
    world = World(monkeypatch)
    block = _estimate(world, ended_store([0.90] * 5), manual=True)
    assert block["applies"] is False and block["need_kwh"] is None
    assert fields(block)["effect_minutes"] == 0


# -------------------------------------------------------------------------------------------------------- reset
@pytest.mark.asyncio
async def test_reset_clears_every_learned_item_in_memory_and_in_the_file(monkeypatch):
    world = World(monkeypatch, session_store=SimpleNamespace(all_sessions=lambda _e: []))
    await world.run(100)
    store = world.les
    assert store.captures(CAR) and store.capture_anchor is not None and store.capture_open is not None
    store.put(CAR, learned_energy.EnergySample("s", 10.0, 12.0, START), CAPACITY)
    store._save()  # noqa: SLF001
    assert FakeStore.saved and FakeStore.saved["vehicles"]
    world.planner._capture_sampler._posts = {START: 1.0}  # noqa: SLF001
    result = await world.planner.async_reset_learning()
    assert result == {"energy": True, "power": None}
    assert not store._cars and store.anchor is None and store.open is None  # noqa: SLF001
    assert store.capture_anchor is None and store.capture_open is None
    assert store.captures(CAR) == () and store.learned(CAR, CAPACITY, morek=True).promoted == 0
    assert FakeStore.saved is None  # removed through the store's own seam
    assert world.planner._capture_sampler._posts == {} and not world.planner._capture_sampler._capture_seen  # noqa: SLF001
    # A restart finds nothing: the old figures cannot come back.
    restarted = LearnedEnergyStore(MagicMock(), "entry")
    await restarted.async_load()
    assert not restarted._cars and restarted.capture_anchor is None  # noqa: SLF001
    world.recalculate.assert_not_called()  # the controller itself never replans; the API's one evidence round does


@pytest.mark.asyncio
async def test_old_pending_stretch_cannot_resurrect_after_reset(monkeypatch):
    world = World(monkeypatch, session_store=SimpleNamespace(all_sessions=lambda _e: []))
    await world.run(40)  # a stretch in progress, not yet a capture
    old_anchor = world.les.capture_anchor
    assert old_anchor is not None
    await world.planner.async_reset_learning()
    assert world.les.capture_anchor is None
    await world.run(5)
    new_anchor = world.les.capture_anchor
    assert new_anchor is None or new_anchor.anchor.at > old_anchor.anchor.at  # a new stretch starts from now
    assert world.les.captures(CAR) == ()


@pytest.mark.asyncio
async def test_failed_file_removal_is_reported_and_the_memory_is_still_empty(monkeypatch):
    world = World(monkeypatch)
    await world.run(70)
    assert world.les.captures(CAR)

    async def boom(self):
        raise OSError("disk")

    monkeypatch.setattr(FakeStore, "async_remove", boom)
    result = await world.planner.async_reset_learning()
    assert result["energy"] is False
    assert world.les.captures(CAR) == ()
    assert FakeStore.saved is not None and not FakeStore.saved["vehicles"]  # the empty state replaces the old file


@pytest.mark.asyncio
async def test_power_store_reset_forgets_subjects_and_the_sampler_stretch(monkeypatch):
    monkeypatch.setattr(learned_power, "Store", FakeStore)
    FakeStore.saved = None
    power = learned_power.LearnedPowerStore(MagicMock(), "entry")
    wiring = learned_power.Wiring(phases=3, voltage_v=400.0, amps=16)
    power.add("charger", wiring, "plug", 5.0, 30.0)
    assert power.power("charger", wiring, 1.0, 11.0).sessions == 1
    sampler = learned_power.PowerSampler(power)
    sampler._last = object()  # noqa: SLF001
    sampler.reset()
    assert sampler._last is None  # noqa: SLF001
    assert await power.async_reset() is True
    assert power.power("charger", wiring, 1.0, 11.0).sessions == 0 and FakeStore.saved is None


@pytest.mark.asyncio
async def test_reset_never_touches_sessions_or_profiles(monkeypatch):
    sessions = SimpleNamespace(all_sessions=Mock(return_value=[]), clear=Mock(), remove=Mock())
    world = World(monkeypatch, session_store=sessions)
    await world.run(5)
    await world.planner.async_reset_learning()
    sessions.clear.assert_not_called()
    sessions.remove.assert_not_called()


# ---------------------------------------------------------------------------------------------------- the API
def api_setup(monkeypatch, *, admin, planner=None, worker=None, failure=None):
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=worker))
    monkeypatch.setattr(morek_schedule, "is_admin", lambda _c: admin)
    monkeypatch.setattr(morek_schedule, "lookup_charger", Mock(return_value=(None if failure else entry, failure)))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: planner)
    return SimpleNamespace(send_result=Mock(), send_error=Mock())


async def call(connection, action="reset_learning"):
    await morek_schedule.websocket_morek_schedule.__wrapped__(
        SimpleNamespace(data={}), connection, {"id": 1, "api_version": 1, "charger_id": "charger", "action": action})


@pytest.mark.asyncio
async def test_non_admin_is_refused_with_no_lookup_reset_or_replan(monkeypatch):
    planner = SimpleNamespace(async_reset_learning=AsyncMock(), async_recalculate=AsyncMock())
    worker = SimpleNamespace(note_learned_reset=Mock(), _closed=False)
    connection = api_setup(monkeypatch, admin=False, planner=planner, worker=worker)
    await call(connection)
    assert connection.send_error.call_args.args[1] == "spotnav_not_admin"
    planner.async_reset_learning.assert_not_awaited()
    planner.async_recalculate.assert_not_awaited()
    worker.note_learned_reset.assert_not_called()
    morek_schedule.lookup_charger.assert_not_called()


@pytest.mark.asyncio
async def test_admin_reset_resets_once_and_asks_for_one_evidence_round(monkeypatch):
    planner = SimpleNamespace(async_reset_learning=AsyncMock(return_value={"energy": True, "power": True}),
                              async_recalculate=AsyncMock())
    worker = SimpleNamespace(note_learned_reset=Mock(), _closed=False)
    connection = api_setup(monkeypatch, admin=True, planner=planner, worker=worker)
    await call(connection)
    planner.async_reset_learning.assert_awaited_once()
    worker.note_learned_reset.assert_called_once()
    planner.async_recalculate.assert_not_awaited()  # the worker's round recalculates; no second path
    assert connection.send_result.call_args.args[1]["schedule"]["learning_reset"] == {
        "energy": True, "power": True, "replan": "requested"}


@pytest.mark.asyncio
async def test_reset_without_a_worker_replans_once_directly_and_a_partial_failure_is_reported(monkeypatch):
    planner = SimpleNamespace(async_reset_learning=AsyncMock(return_value={"energy": False, "power": True}),
                              async_recalculate=AsyncMock())
    connection = api_setup(monkeypatch, admin=True, planner=planner, worker=None)
    await call(connection)
    planner.async_recalculate.assert_awaited_once_with("learned_reset")
    assert connection.send_result.call_args.args[1]["schedule"]["learning_reset"] == {
        "energy": False, "power": True, "replan": "requested"}


@pytest.mark.asyncio
async def test_reset_refuses_an_unknown_charger_and_a_missing_planner_without_effects(monkeypatch):
    planner = SimpleNamespace(async_reset_learning=AsyncMock(), async_recalculate=AsyncMock())
    connection = api_setup(monkeypatch, admin=True, planner=planner, failure="spotnav_unknown_charger")
    await call(connection)
    assert connection.send_error.call_args.args[1] == "spotnav_morek_spotnav_unknown_charger"
    planner.async_reset_learning.assert_not_awaited()
    connection = api_setup(monkeypatch, admin=True, planner=None)
    await call(connection)
    assert connection.send_error.call_args.args[1] == "spotnav_morek_planner_unavailable"


@pytest.mark.asyncio
async def test_worker_learned_reset_is_one_recalculation_then_one_compared_recalc_trigger():
    from custom_components.spotnav.execution.morek_worker import MorekScheduleWorker as MorekWorker

    worker = MorekWorker.__new__(MorekWorker)
    worker._closed = False  # noqa: SLF001
    worker._evidence = set()  # noqa: SLF001
    worker._evidence_task = None  # noqa: SLF001
    calls = []
    worker._planner = SimpleNamespace(async_recalculate=AsyncMock(side_effect=lambda kind: calls.append(kind)))  # noqa: SLF001
    worker.trigger = Mock()
    created = []
    worker._hass = SimpleNamespace(async_create_task=lambda coro: created.append(coro) or SimpleNamespace(done=lambda: False))  # noqa: SLF001
    worker.note_learned_reset()
    worker.note_learned_reset()  # a repeat before the round runs is the same one round
    assert len(created) == 1
    await created[0]
    assert calls == ["learned_reset"]
    worker.trigger.assert_called_once_with(kind="recalc")
