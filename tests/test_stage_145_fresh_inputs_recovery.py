"""Stage 14.5: fresh progress inputs and bounded recovery for the Morek schedule path.

Pure helpers, the real controller capped path (`_world` from the Stage 13 tests) and the real Morek worker
and send path (HA/OCPP/ownership are the usual mocked boundaries). Mocks do not prove deployed behavior or
physical charging.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.planning.auto_controller import (
    LiveVehicleFacts, live_vehicle_facts, soc_reading_order_problem,
)
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_worker import NOW, drain, setup
from .test_stage_13_reactive import _world


@pytest.fixture(autouse=True)
def _zones():
    """Resolve the fixture's zone up front (the loop cannot look zones up; tzdata may be missing from the
    environment's system paths)."""
    from zoneinfo import ZoneInfo
    from custom_components.spotnav import time_zones
    time_zones._remember("Europe/Stockholm", ZoneInfo("Europe/Stockholm"))  # noqa: SLF001


def facts(**kw):
    base = dict(vehicle_id="veh-1", soc_percent=25, soc_age_s=1, reported_capacity_kwh=60)
    base.update(kw)
    return LiveVehicleFacts(**base)


# ---- pure ordering and association ---------------------------------------------------------------

def test_order_future_and_older_reports():
    assert soc_reading_order_problem(facts(soc_report_at=NOW + timedelta(minutes=5)), NOW, None) == "future"
    assert soc_reading_order_problem(facts(soc_report_at=NOW + timedelta(seconds=60)), NOW, None) is None
    newest = NOW - timedelta(minutes=10)
    assert soc_reading_order_problem(facts(soc_report_at=NOW - timedelta(minutes=20)), NOW, newest) == "out_of_order"
    assert soc_reading_order_problem(facts(soc_report_at=NOW - timedelta(minutes=10, seconds=3)), NOW, newest) is None
    assert soc_reading_order_problem(facts(soc_report_at=NOW - timedelta(minutes=5)), NOW, newest) is None
    assert soc_reading_order_problem(facts(soc_age_s=None), NOW, newest) is None


def test_reading_for_another_car_is_not_used(monkeypatch):
    reading = SimpleNamespace(soc_percent=50, vehicle_id="other", source="vehicle", age_s=1, estimated=False,
                              reported_at=None, entity_id=None, time_basis="last_updated",
                              anchor_percent=None, anchor_at=None, delivered_kwh=None, register_reset=False)
    soc = SimpleNamespace(ensure_watch=lambda _: None, read=lambda _: reading, await_reading=lambda _: None,
                          capacity_kwh=lambda _: 60, vehicle_max_percent=lambda _: None)
    monkeypatch.setattr(auto_controller, "resolve_target_vehicle", lambda *_: ("veh-1", None))
    monkeypatch.setattr(auto_controller, "stored_properties", lambda *_: SimpleNamespace(min_percent=None))
    assert live_vehicle_facts(None, soc, "veh-1").soc_percent is None
    reading.vehicle_id = "veh-1"
    assert live_vehicle_facts(None, soc, "veh-1").soc_percent == 50


# ---- controller capped path ----------------------------------------------------------------------

def test_out_of_order_report_does_not_replace_good_plan(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        newer = w.request.now
        w.facts[0] = replace(w.facts[0], soc_report_at=newer)
        good = await w.controller.async_recalculate()
        assert good.proposal is not None
        w.facts[0] = replace(w.facts[0], soc_percent=60, soc_report_at=newer - timedelta(hours=1))
        stale = await w.controller.async_recalculate()
        assert (stale.state, stale.reason) == ("planning_unavailable", "target_soc_stale")
        assert stale.proposal is None
        w.facts[0] = replace(w.facts[0], soc_percent=30, soc_report_at=w.request.now + timedelta(seconds=30))
        assert (await w.controller.async_recalculate()).proposal is not None
    asyncio.run(run())


def test_future_report_and_wrong_vehicle_are_refused(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now + timedelta(hours=2))
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
        w.facts[0] = replace(w.facts[0], soc_report_at=None)
        assert (await w.controller.async_recalculate()).proposal is not None
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (True, "veh-2"))
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (False, None))
        assert (await w.controller.async_recalculate()).proposal is not None
        w.facts[0] = replace(w.facts[0], vehicle_id="")
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
    asyncio.run(run())


def test_measured_energy_since_reading_holds_plan_instead_of_counting_twice(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        seen = []

        def waiting(settings, f, need, *_a, **_k):
            seen.append(need)
            return w.controller._fresh_snapshot(  # noqa: SLF001
                settings, "nothing_to_charge", "waiting_for_vehicle_update", w.request.now)

        monkeypatch.setattr(w.controller, "_vehicle_update_wait", waiting)
        held = await w.controller.async_recalculate()
        assert (held.state, held.reason) == ("nothing_to_charge", "waiting_for_vehicle_update")
        assert held.proposal is None and seen and seen[0] > 0
        monkeypatch.setattr(w.controller, "_vehicle_update_wait", lambda *_a, **_k: None)
        assert (await w.controller.async_recalculate()).proposal is not None
    asyncio.run(run())


def test_estimated_reading_is_not_planned_from(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.facts[0] = replace(w.facts[0], soc_estimated=True)
        snap = await w.controller.async_recalculate()
        assert snap.reason == "target_soc_stale" and snap.proposal is None
    asyncio.run(run())


def test_planning_inputs_label_uncertainty():
    snap = SimpleNamespace(state="planning_unavailable", reason="target_soc_stale", projection_age_s=None,
                           projection_source=None, projection_estimated=False)
    planner = SimpleNamespace(snapshot=lambda: snap)
    morek_schedule.preview_for = lambda *_: planner
    inputs = morek_schedule._planning_inputs(None, "x")  # noqa: SLF001
    assert inputs["uncertain"] is True and inputs["plan_reason"] == "target_soc_stale"
    snap.state, snap.projection_age_s = "ready", 30.0
    assert morek_schedule._planning_inputs(None, "x")["uncertain"] is False  # noqa: SLF001


# ---- bounded recovery ----------------------------------------------------------------------------

def test_rejection_retry_schedule_is_bounded():
    def rec(n):
        return {"uncertain": False, "attempt": {"state": "rejected", "source": "worker", "rejections": n,
                                                "at": NOW.isoformat()}}
    assert morek_schedule.rejection_retry_at(rec(1)) == NOW + timedelta(seconds=300)
    assert morek_schedule.rejection_retry_at(rec(2)) == NOW + timedelta(seconds=900)
    assert morek_schedule.rejection_retry_at(rec(3)) is None
    assert morek_schedule.rejection_retry_at({**rec(1), "uncertain": True}) is None
    manual = rec(1)
    manual["attempt"]["source"] = "manual"
    assert morek_schedule.rejection_retry_at(manual) is None
    status = morek_schedule.recovery_status(rec(3), NOW)
    assert status["exhausted"] and status["next_retry_at"] is None and status["retries_left"] == 0
    status = morek_schedule.recovery_status(rec(1), NOW)
    assert not status["exhausted"] and status["retries_left"] == 2
    ack = {"acknowledged": {"at": (NOW - timedelta(minutes=7)).isoformat()}}
    status = morek_schedule.recovery_status(ack, NOW)
    assert status["accepted_age_s"] == 420 and status["accepted_is"] == "acknowledged_not_measured"
    assert morek_schedule.recovery_status(None, NOW)["accepted_at"] is None


@pytest.mark.asyncio
async def test_definite_rejection_retried_at_most_twice_after_backoff(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_rejected" and w.point.call.await_count == 1
    assert w.ledger.value["attempt"]["rejections"] == 1
    assert w.worker._retry_timer is not None  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_rejected"
    for expected in (2, 3):
        w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=1)).isoformat()
        w.worker.trigger()
        await drain(w.worker)
        assert w.point.call.await_count == expected
        assert w.ledger.value["attempt"]["rejections"] == expected
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=5)).isoformat()
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 3 and w.worker.reason == "upload_rejected"
    assert w.worker._retry_timer is None  # noqa: SLF001
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_write_is_never_retried(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain" and w.point.call.await_count == 1
    assert w.worker._retry_timer is None  # noqa: SLF001
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=5)).isoformat()
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_uncertain"
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_race_blocks_retry_and_acceptance_clears_timer(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    assert w.worker._retry_timer is not None  # noqa: SLF001
    w.point.call.return_value = SimpleNamespace(status="Accepted")
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=1)).isoformat()
    connector = physical_connector(w.identity)
    w.admission._person_stops[connector] = True  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.admission._person_stops.pop(connector)  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker._retry_timer is None  # noqa: SLF001
    w.worker.close()
