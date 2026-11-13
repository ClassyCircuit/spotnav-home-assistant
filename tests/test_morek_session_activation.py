"""Plug-in activation: real listener job type, loop semantics, blocker reasons and bounded recovery."""

import asyncio
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from homeassistant.core import HassJob, HassJobType

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution.command_admission import physical_connector

from .test_morek_session import IDENTITY, setup


def loop_checked(coordinator):
    """HA's own rule: tasks may only be created from the event-loop thread."""
    loop_thread = threading.get_ident()

    def create(coro):
        if threading.get_ident() != loop_thread:
            coro.close()
            raise RuntimeError("async_create_task from a non-loop thread")
        return asyncio.create_task(coro)

    coordinator.hass.async_create_task = create
    worker = coordinator.worker
    worker.noted = []

    def note_plug_in():
        worker.noted.append("plug_in")
        coordinator.hass.async_create_task(asyncio.sleep(0))

    worker.note_plug_in = note_plug_in
    worker.note_sensor = lambda: None


def wire(monkeypatch, coordinator):
    import custom_components.spotnav as integration
    from custom_components.spotnav.vehicles import ocpp_identity

    captured = []
    coordinator.hass.states = SimpleNamespace(get=lambda _: None)
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", lambda *_: "sensor.connector")
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: captured.append(cb) or (lambda: None))
    integration._setup_morek_session_observation(coordinator.hass, SimpleNamespace(async_on_unload=lambda _: None),
                                                 coordinator, SimpleNamespace(connector_id=1))
    return captured[0]


async def deliver(callback, old, new):
    """HA's dispatch rule: a loop callback runs inline, anything else runs in the executor."""
    event = SimpleNamespace(data={"old_state": SimpleNamespace(state=old), "new_state": SimpleNamespace(state=new)})
    if HassJob(callback).job_type is HassJobType.Callback:
        callback(event)
    else:
        await asyncio.get_running_loop().run_in_executor(None, callback, event)


async def settle(coordinator):
    for _ in range(50):
        task = coordinator.task
        if task is None or task.done():
            return
        await task


@pytest.mark.asyncio
async def test_production_listener_is_a_loop_callback_and_plugin_starts_once(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    loop_checked(coordinator)
    listener = wire(monkeypatch, coordinator)
    assert HassJob(listener).job_type is HassJobType.Callback
    await deliver(listener, "Available", "Preparing")
    await settle(coordinator)
    assert coordinator.worker.noted == ["plug_in"]
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"


@pytest.mark.asyncio
async def test_undecorated_listener_fails_the_loop_rule_but_cannot_strand_the_connection(monkeypatch):
    """Regression guard: an executor-run observe cannot create tasks; the token must still be settled."""
    coordinator, point, _, _ = setup(monkeypatch)
    loop_checked(coordinator)
    event = SimpleNamespace(data={"old_state": SimpleNamespace(state="Available"),
                                  "new_state": SimpleNamespace(state="Preparing")})

    def undecorated(e):
        coordinator.observe(e.data["old_state"].state, e.data["new_state"].state)

    assert HassJob(undecorated).job_type is HassJobType.Executor
    await asyncio.get_running_loop().run_in_executor(None, undecorated, event)
    assert coordinator.connection is not None
    assert coordinator.observation == "preparing"


@pytest.mark.asyncio
async def test_worker_evidence_failure_cannot_strand_the_connection(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)

    def boom():
        raise RuntimeError("no loop")

    coordinator.worker.note_plug_in = boom
    coordinator.observe("Available", "Preparing")
    assert coordinator.connection is not None
    await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
async def test_prior_ended_session_records_do_not_block_a_new_plugin(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    ledger.value["session_start"] = {"version": 1, "connection": "old", "state": "accepted",
                                     "at": datetime.now(timezone.utc).isoformat(), "attempts": 1}
    ledger.value["session_completed"] = True
    ledger.value["session_unplugged"] = "c" * 32
    coordinator.observe("Charging", "Finishing")
    coordinator.observe("Finishing", "Available")
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"


@pytest.mark.asyncio
async def test_plugin_through_a_flap_is_one_new_connection_and_flaps_do_not_duplicate(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.observe(None, "Available")
    coordinator.observe("Available", "Unavailable")
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    first = ledger.value["session_start"]["connection"]
    assert first != "recovery"
    for _ in range(3):
        coordinator.observe("Preparing", "Unavailable")
        coordinator.observe("Unavailable", "Preparing")
        await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["connection"] == first


@pytest.mark.asyncio
async def test_preparing_flap_retries_a_never_dispatched_start_without_a_new_connection(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.worker._suspended = True
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "worker_suspended"
    connection = coordinator.connection
    coordinator.worker._suspended = False
    coordinator.observe("Preparing", "Unavailable")
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    assert point.calls == 1 and coordinator.connection == connection


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["_suspended", "unavailable"])
async def test_transient_blocker_is_named_and_cleared_by_bounded_timer(monkeypatch, flag):
    monkeypatch.setattr(morek_session, "SESSION_RETRY_DELAYS", (0.01,))
    coordinator, point, _, _ = setup(monkeypatch)
    if flag == "_suspended":
        coordinator.worker._suspended = True
    else:
        coordinator.worker._available = lambda: False
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert coordinator.state == {"state": "blocked",
                                 "reason": "worker_suspended" if flag == "_suspended" else "charger_unavailable"}
    assert point.calls == 0 and coordinator._recheck is not None
    coordinator.worker._suspended = False
    coordinator.worker._available = lambda: True
    for _ in range(100):
        await asyncio.sleep(0.01)
        await settle(coordinator)
        if point.calls:
            break
    assert point.calls == 1
    assert coordinator.state["state"] == "accepted"


@pytest.mark.asyncio
async def test_transient_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(morek_session, "SESSION_RETRY_DELAYS", (0.001,))
    monkeypatch.setattr(morek_session, "SESSION_RETRY_LIMIT", 3)
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.worker._suspended = True
    coordinator.observe("Available", "Preparing")
    await asyncio.sleep(0.2)
    await settle(coordinator)
    assert coordinator._recheck_runs == 3 and coordinator._recheck is None and point.calls == 0


@pytest.mark.asyncio
async def test_person_stop_and_pause_are_named_and_never_retried(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    admission._person_stops[physical_connector(IDENTITY)] = 1
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert coordinator.state["reason"] == "person_stop_active"
    assert coordinator._recheck is None and point.calls == 0
    admission._person_stops.clear()
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.trigger()
    await settle(coordinator)
    assert coordinator.state["reason"] == "paused_until_resume"
    assert coordinator._recheck is None and point.calls == 0


def forbid_intent(coordinator):
    """The session start must never call the worker's plan/intent builder (side effects, plan-quality refusals)."""
    def intent(*_a, **_k):
        raise AssertionError("worker._intent must not be called by the session start")
    coordinator.worker._intent = intent


@pytest.mark.asyncio
async def test_start_ignores_stale_plan_and_never_calls_the_intent_builder(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    forbid_intent(coordinator)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1 and coordinator.state["state"] == "accepted"


@pytest.mark.asyncio
async def test_planner_change_is_a_transient_named_blocker(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    forbid_intent(coordinator)
    coordinator.worker._planner = object()
    monkeypatch.setattr(morek_session, "preview_for", lambda *_: object())
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert coordinator.state["reason"] == "planner_changed" and point.calls == 0
    assert coordinator._recheck is not None
    coordinator.close()


@pytest.mark.asyncio
async def test_matching_planner_does_not_block(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    planner = coordinator.worker._planner = object()
    monkeypatch.setattr(morek_session, "preview_for", lambda *_: planner)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
async def test_uncertain_profile_outcome_blocks_start_and_is_not_retried(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    forbid_intent(coordinator)
    ledger.value["uncertain"] = True
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] in (
        "profile_outcome_uncertain", "profile_outcome_unavailable")  # admission refuses it first
    assert coordinator._recheck is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", "pending"])
async def test_genuine_unknown_start_state_blocks_even_with_stale_inputs(monkeypatch, state):
    coordinator, point, ledger, _ = setup(monkeypatch)
    forbid_intent(coordinator)
    coordinator.worker.reason = "soc_stale"  # stale SOC/prices are plan state; they change nothing here
    ledger.value["session_start"] = {"version": 1, "connection": "old", "state": state,
                                     "at": datetime.now(timezone.utc).isoformat(), "attempts": 1}
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "previous_start_may_have_applied"


@pytest.mark.asyncio
async def test_explicit_stop_and_pause_win_immediately_while_inputs_are_stale(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    forbid_intent(coordinator)
    coordinator.worker.reason = "prices_stale_or_unavailable"
    admission._person_stops[physical_connector(IDENTITY)] = 1
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "person_stop_active"
    admission._person_stops.clear()
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "paused_until_resume"


@pytest.mark.asyncio
async def test_retained_protection_and_identity_gates_still_block(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    forbid_intent(coordinator)
    controller = morek_session.controller_for(None, None)
    controller._start_cap = lambda: None
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "protection_conflict_unresolved"
    del controller._start_cap
    coordinator.worker._identity = lambda: {**IDENTITY, "resolved_id": "other"}
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "identity_unresolved"


@pytest.mark.asyncio
async def test_flap_created_connection_notes_exactly_one_plug_in_recalculation(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    loop_checked(coordinator)
    coordinator.worker.note_sensor = lambda: coordinator.worker.noted.append("sensor")
    coordinator.observe(None, "Available")
    coordinator.observe("Available", "Unavailable")
    coordinator.worker.noted.clear()
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    assert coordinator.worker.noted == ["plug_in"]
    assert coordinator.connection not in (None, "recovery")


@pytest.mark.asyncio
async def test_ambiguous_reconnect_with_existing_connection_is_sensor_not_plug_in(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    loop_checked(coordinator)
    coordinator.worker.note_sensor = lambda: coordinator.worker.noted.append("sensor")
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert coordinator.worker.noted == ["plug_in"]
    coordinator.observe("Preparing", "Unavailable")
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    assert coordinator.worker.noted == ["plug_in", "sensor", "sensor"]
    # restart-style ambiguity: never seen Available, so a recovery connection and no plug-in recalculation
    fresh, _, _, _ = setup(monkeypatch)
    loop_checked(fresh)
    fresh.worker.note_sensor = lambda: fresh.worker.noted.append("sensor")
    fresh.observe("Unavailable", "Preparing")
    await settle(fresh)
    assert "plug_in" not in fresh.worker.noted


@pytest.mark.asyncio
async def test_accepted_without_a_transaction_is_visible_and_never_repeated(monkeypatch):
    monkeypatch.setattr(morek_session, "NO_TRANSACTION_AFTER_S", 0.01)
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    await asyncio.sleep(0.1)
    assert coordinator.state == {"state": "accepted", "reason": "no_transaction_observed"}
    coordinator.trigger()
    await settle(coordinator)
    coordinator.observe("Preparing", "Unavailable")
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
async def test_a_transaction_cancels_the_no_transaction_warning(monkeypatch):
    monkeypatch.setattr(morek_session, "NO_TRANSACTION_AFTER_S", 0.05)
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    coordinator.observe("Preparing", "Charging")
    await asyncio.sleep(0.1)
    assert coordinator.state["state"] == "session_observed"


@pytest.mark.asyncio
async def test_charging_reported_during_the_request_does_not_overwrite_accepted(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    gate, started = asyncio.Event(), asyncio.Event()

    async def slow(connector_id):
        started.set()
        await gate.wait()
        return True

    point.start_transaction = slow
    coordinator.observe("Available", "Preparing")
    await started.wait()
    coordinator.observe("Preparing", "Charging")
    gate.set()
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "accepted"
    assert coordinator.state["reason"] == "request_accepted"


@pytest.mark.asyncio
async def test_stop_arriving_during_the_request_is_reported_and_outcome_kept(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    gate, started = asyncio.Event(), asyncio.Event()

    async def slow(connector_id):
        started.set()
        await gate.wait()
        return True

    point.start_transaction = slow
    coordinator.observe("Available", "Preparing")
    await started.wait()
    admission._person_stops[physical_connector(IDENTITY)] = 1
    gate.set()
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "accepted"
    assert coordinator.state["reason"] == "newer_stop_or_connection_change"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [TimeoutError(), ValueError()])
async def test_unknown_outcome_is_visible_and_survives_flaps_and_restart(monkeypatch, answer):
    coordinator, point, ledger, _ = setup(monkeypatch, answer)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "unknown"
    assert coordinator.state == {"state": "unknown", "reason": "request_unknown"}
    coordinator.observe("Preparing", "Unavailable")
    coordinator.observe("Unavailable", "Preparing")
    await settle(coordinator)
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await settle(restarted)
    assert point.calls == 1 and restarted.state["state"] == "uncertain"


@pytest.mark.asyncio
async def test_pending_request_blocks_a_duplicate(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    ledger.value["session_start"] = {"version": 1, "connection": "old", "state": "pending",
                                     "at": datetime.now(timezone.utc).isoformat(), "attempts": 1}
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "previous_start_may_have_applied"
