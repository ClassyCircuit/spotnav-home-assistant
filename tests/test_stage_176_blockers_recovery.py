"""Stage 17.6: clear blockers (who acts, what ends them) and end-to-end automatic recovery.

One table (`morek_schedule.PLANNING_HOLDS`) names, for every planning hold Stage 17 touches, who acts and which
existing input change ends it. Real controller, real Morek worker and (for prices/FX) the real admission path; HA and
OCPP are the usual mocked boundaries. Nothing here proves physical charging, and nothing is deployed.
"""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.api.morek_schedule import PLANNING_HOLDS, decision_blocker
from custom_components.spotnav.planning import auto_controller, learned_energy
from custom_components.spotnav.planning.auto_controller import LiveVehicleFacts
from custom_components.spotnav.planning.status_compose import QUIET_PLANNING_REASONS
from .test_morek_worker import drain, real_planner_worker
from .test_stage_145_progress_recovery import _charge, _restore_domain_data  # noqa: F401
from .test_stage_159a_energy_capture import FakeStore
from .test_stage_159b_promotion import NOW as LEARN_NOW
from .test_stage_162_safe_dispatch import _world as _price_world
from .test_stage_172_stale_soc import est
from .test_stage_175_fx_freshness import _sek_world, _with_rate

CAR = "veh-1"


@pytest.fixture(autouse=True)
def _zones(monkeypatch):
    from zoneinfo import ZoneInfo
    from custom_components.spotnav import time_zones
    time_zones._remember("Europe/Stockholm", ZoneInfo("Europe/Stockholm"))  # noqa: SLF001
    FakeStore.saved = None
    monkeypatch.setattr(learned_energy, "Store", FakeStore)
    monkeypatch.setattr(learned_energy.dt_util, "utcnow", lambda: LEARN_NOW)


def facts(capacity=60, **kw):
    base = dict(vehicle_id=CAR, soc_percent=25, soc_age_s=5, reported_capacity_kwh=capacity)
    base.update(kw)
    return LiveVehicleFacts(**base)


# ---- the table: who acts, what ends the hold, how it is worded ------------------------------------------------

#: Every hold the roadmap lists. (worker reason that carries it, planner reason) -> (action, who, recovery).
LISTED = {
    "target_soc_unknown": ("no_current_plan", "wait_for_fresh_inputs", "vehicle"),
    "target_soc_stale": ("no_current_plan", "wait_for_fresh_inputs", "vehicle"),
    "target_capacity_unknown": ("no_current_plan", "set_battery_capacity", "person"),
    "missing_fx_rate": ("no_current_plan", "wait_for_exchange_rate", "system"),
    "price_data_stale": ("prices_stale_or_unavailable", "wait_for_prices", "system"),
    "no_prices_yet": ("prices_stale_or_unavailable", "wait_for_prices", "system"),
    "no_published_prices": ("no_current_plan", "wait_for_prices", "system"),
    "plan_inputs_changed": (None, "wait_for_planner", "system"),
    "price_inputs_changed": (None, "wait_for_prices", "system"),
}


@pytest.mark.parametrize("hold", sorted(LISTED))
def test_every_listed_hold_states_who_acts_and_its_existing_recovery(hold):
    worker_reason, action, who = LISTED[hold]
    assert hold in PLANNING_HOLDS
    block = decision_blocker(worker_reason or hold, hold if worker_reason else None)
    assert (block["action"], block["who"]) == (action, who)
    assert block["recovery"] and block["recovery"] == PLANNING_HOLDS[hold][2]
    if worker_reason:  # the generic worker reason stays the code; the planner's own reason is the detail
        assert block["code"] == worker_reason and block["detail"] == hold


def test_generic_no_plan_reasons_without_a_named_cause_stay_as_they_were():
    for reason in ("no_current_plan", "prices_stale_or_unavailable", "planning_unavailable"):
        assert decision_blocker(reason) == {"code": reason, "action": morek_schedule.DECISION_BLOCKERS[reason]}
        assert decision_blocker(reason, "something_new") == decision_blocker(reason)
    # a person's Stop / pause / an uncertain outcome are never re-labelled by a planner reason
    for reason in ("paused_until_resume", "upload_uncertain", "charge_now_active"):
        assert decision_blocker(reason, "target_capacity_unknown") == decision_blocker(reason)


def test_every_hold_is_automatic_except_the_person_setting_and_none_is_quiet_or_failure_worded():
    transient = morek_schedule.TRANSIENT_BLOCKERS
    for hold, (action, who, _recovery) in PLANNING_HOLDS.items():
        assert who in ("system", "vehicle", "person")
        assert action in {"wait_for_fresh_inputs", "set_battery_capacity", "wait_for_exchange_rate",
                          "wait_for_prices", "wait_for_planner"}
    for worker_reason in ("no_current_plan", "prices_stale_or_unavailable", "plan_inputs_changed"):
        assert worker_reason in transient  # re-checked on the existing bounded timer as well as on events
    assert "no_prices_yet" in QUIET_PLANNING_REASONS  # normal life for the status line, never red


# ---- production wiring: hold -> input arrives -> plan -> the worker uploads once -------------------------------

async def _held(w, world, reason, *, uploads=0):
    world.controller._soc_newest.clear()  # noqa: SLF001
    held = await world.controller.async_recalculate()
    assert held.proposal is None or not held.proposal.has_plan, held.reason
    assert held.reason == reason, held.reason
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == uploads  # a hold sends nothing
    return held


async def _recovered(w, world, held):
    """The input arrived: the existing recalculation, then the worker's own compare. Never a manual Send."""
    assert world.controller.morek_plan_blocker(held, world.request.now) is not None  # the old calculation is dead
    world.controller._soc_newest.clear()  # noqa: SLF001
    snap = await world.controller.async_recalculate()
    assert snap.proposal is not None and snap.proposal.has_plan, (snap.state, snap.reason)
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.controller._soc_newest.clear()  # noqa: SLF001
    await world.controller.async_recalculate()  # an unchanged input sends nothing more
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()
    return snap


def _no_plan_blocker(w, held):
    return decision_blocker(w.worker.reason, held.reason)


@pytest.mark.asyncio
async def test_vehicle_level_unknown_recovers_when_the_car_reports(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.facts[0] = facts(soc_percent=None, soc_age_s=None)
    held = await _held(w, world, "target_soc_unknown")
    block = _no_plan_blocker(w, held)
    assert (block["action"], block["who"], block["detail"]) == ("wait_for_fresh_inputs", "vehicle", "target_soc_unknown")
    world.facts[0] = facts()  # the car reported its level
    await _recovered(w, world, held)


@pytest.mark.asyncio
async def test_unmatched_reading_holds_and_recovers_when_the_identity_matches(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    monkeypatch.setattr(world.controller, "_notification_vehicle", lambda: (True, "veh-2"))
    world.facts[0] = est()  # a reading for another car is never used
    held = await _held(w, world, "target_soc_stale")
    assert _no_plan_blocker(w, held)["who"] == "vehicle"
    monkeypatch.setattr(world.controller, "_notification_vehicle", lambda: (True, CAR))
    await _recovered(w, world, held)


@pytest.mark.asyncio
async def test_capacity_unknown_asks_the_person_and_recovers_when_it_is_set(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.facts[0] = facts(capacity=None)
    held = await _held(w, world, "target_capacity_unknown")
    block = _no_plan_blocker(w, held)
    assert (block["action"], block["who"]) == ("set_battery_capacity", "person")
    world.facts[0] = facts(capacity=60)  # the person set the capacity: no Refresh, no Send
    await _recovered(w, world, held)


@pytest.mark.asyncio
async def test_missing_exchange_rate_waits_and_a_rate_arrival_sends_once(monkeypatch, tmp_path):
    w, world, now = await _sek_world(monkeypatch, tmp_path)
    doc = world.area.today_snapshot.document
    world.area.today_snapshot.document = _with_rate(doc, None, None)
    held = await world.controller.async_recalculate()
    assert held.reason == "missing_fx_rate"
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    block = _no_plan_blocker(w, held)
    assert (block["action"], block["who"], block["detail"]) == ("wait_for_exchange_rate", "system", "missing_fx_rate")
    world.area.today_snapshot.document = _with_rate(doc, 11.0, doc.day - timedelta(days=1))
    assert world.controller.morek_price_blocker(held, now) is not None
    fresh = await world.controller.async_recalculate()
    assert fresh.proposal.has_plan, fresh.reason
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    await world.controller.async_recalculate()
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_prices_not_yet_loaded_wait_and_their_arrival_sends_once(monkeypatch, tmp_path):
    w, world, now = await _price_world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="unavailable",
                                       tomorrow_authority="unknown")
    good_doc, good_state = world.area.today_snapshot.document, world.area.state
    world.area.today_snapshot.document = None
    world.area.state = "loading"
    world.area.today_state = "loading"
    held = await world.controller.async_recalculate()
    assert held.reason in ("no_prices_yet", "price_data_stale", "no_published_prices"), held.reason
    assert held.reason in PLANNING_HOLDS
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    block = _no_plan_blocker(w, held)
    assert block["action"] == "wait_for_prices" and block["who"] == "system", (w.worker.reason, block)
    world.area.today_snapshot.document, world.area.state, world.area.today_state = good_doc, good_state, "ready"
    fresh = await world.controller.async_recalculate()
    assert fresh.proposal.has_plan, fresh.reason
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    w.worker.close()


@pytest.mark.asyncio
async def test_changed_inputs_after_a_calculation_are_refused_then_replanned_not_sent_stale(monkeypatch, tmp_path):
    w, world, now = await _price_world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="unavailable",
                                       tomorrow_authority="unknown")
    snap = await world.controller.async_recalculate()
    assert world.controller.morek_plan_blocker(snap, now) is None
    # a published price changed after the calculation: that plan can no longer be sent
    doc = world.area.today_snapshot.document
    prices = list(doc.prices)
    prices[10] = .9
    world.area.today_snapshot.document = replace(doc, prices=tuple(prices), intervals=tuple(
        replace(item, eur_per_kwh=.9) if index == 10 else item for index, item in enumerate(doc.intervals)))
    reason = world.controller.morek_plan_blocker(snap, now)
    assert reason in ("price_inputs_changed", "plan_inputs_changed")
    assert decision_blocker(reason)["who"] == "system" and decision_blocker(reason)["recovery"] == "plan_recalculated"
    # the one existing recovery: recalculation; the new calculation is admitted and sent once
    fresh = await world.controller.async_recalculate()
    assert world.controller.morek_plan_blocker(fresh, now) is None
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    w.worker.close()


# ---- the combined case ---------------------------------------------------------------------------------------

def _wire_sessions(world, sessions):
    car = SimpleNamespace(plugged_in_for_count=world.request.now - timedelta(hours=6), plan=None, charging=False,
                          car_ended_at=None, car_ended_waits_for=lambda **_k: False, held_off_by_person=False,
                          adapter=SimpleNamespace(vehicle_connected=lambda: True))
    world.controller._charger_controller = lambda: car  # noqa: SLF001
    store = SimpleNamespace(closed_raw=lambda _id: tuple(sessions), open_raw=lambda _id: None)
    auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)


@pytest.mark.asyncio
async def test_stale_level_partial_prices_and_unknown_progress_plan_label_send_once_and_survive_restart(
        monkeypatch, tmp_path):
    w, world, now = await _price_world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="unavailable",
                                       tomorrow_authority="unknown")
    monkeypatch.setattr(auto_controller, "resolved_vehicle_id", lambda *_: CAR)
    await world.store.async_update("test", mutate=lambda s: replace(
        s, soft_price_cap=.3, cap_price_basis="nord_pool", minimum_ready_by_soc=40))  # the capped path (17.2)
    read_at = now - timedelta(hours=2)
    # (1) stale level: an estimate that is not trusted (the register reset), so the plan uses its anchor reading;
    # (2) tomorrow's prices unusable: planned from today's published prices only;
    # (3) a closed charge for this car straddles the reading: its energy cannot be attributed.
    world.facts[0] = est(soc_percent=60.0, register_reset=True, soc_age_s=7200, anchor_at=read_at,
                         soc_report_at=read_at)
    _wire_sessions(world, [_charge(read_at - timedelta(minutes=10), 3.0, hours=0.5)])
    world.controller._soc_newest.clear()  # noqa: SLF001
    snap = await world.controller.async_recalculate()
    assert snap.proposal is not None and snap.proposal.has_plan, (snap.state, snap.reason)
    assert snap.price_state == "degraded" and snap.proposal.price_coverage_end is not None  # partial prices
    assert snap.progress_unknown is True  # labelled, never presented as measured and never estimated
    assert snap.projection_soc == 25.0 and not snap.projection_estimated  # the anchor reading, as an actual level
    inputs = morek_schedule._planning_inputs(MagicMock(), "test")  # noqa: SLF001
    assert inputs["progress_unknown"] is True and inputs["soc_estimated"] is False
    assert world.controller.morek_plan_blocker(snap, now) is None  # admissible without a manual action
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    # restart: the controller keeps no flag in memory; a fresh calculation recomputes the same plan and a new worker
    # over the same durable record sends nothing again.
    w.worker.close()
    world.controller._progress_watch = None  # noqa: SLF001
    world.controller._soc_newest.clear()  # noqa: SLF001
    again = await world.controller.async_recalculate()
    assert again.progress_unknown is True and again.proposal.slots == snap.proposal.slots
    from custom_components.spotnav.execution import morek_worker
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    w.worker.close()


@pytest.mark.asyncio
async def test_person_stop_and_pause_stay_blocking_with_a_recovered_plan(monkeypatch, tmp_path):
    """Recovery never overrides the person: while Stop is held the recovered plan is not sent."""
    w, world, now = await _price_world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="unavailable",
                                       tomorrow_authority="unknown")
    from custom_components.spotnav.execution import command_admission
    from custom_components.spotnav.execution.command_admission import physical_connector
    admission = command_admission.command_admission(w.hass)
    snap = await world.controller.async_recalculate()
    assert snap.proposal.has_plan
    connector = physical_connector(w.worker._identity())  # noqa: SLF001
    admission._person_stops[connector] = 1  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    assert w.worker.reason == "stale_generation"
    assert decision_blocker(w.worker.reason, "target_capacity_unknown")["action"] == "retry_after_stop_or_change"
    w.worker.close()
