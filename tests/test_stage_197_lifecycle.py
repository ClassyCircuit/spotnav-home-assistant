"""Stage 19.7: a switch that goes unavailable while the live OCPP link stays up resumes uploads only."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import custom_components.spotnav as integration
from custom_components.spotnav.execution import execution_ownership
from custom_components.spotnav.execution.command_admission import CommandAdmission
from custom_components.spotnav.execution.morek_worker import MorekScheduleWorker


def unavailable_edge():
    return SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                 "new_state": SimpleNamespace(state="unavailable")})


def available_edge():
    return SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                 "new_state": SimpleNamespace(state="off")})


async def setup(monkeypatch, tmp_path, link):
    class Store:
        def __init__(self, hass, version, key, **kwargs):
            self.path = str(tmp_path / key)

        async def async_save(self, data):
            pass

    async def run_job(fn, *args):
        return fn(*args)

    calls, tasks = [], []

    def create_task(hass, coro, name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(execution_ownership, "Store", Store)
    hass = SimpleNamespace(async_add_executor_job=run_job, services=SimpleNamespace(async_call=AsyncMock()))
    gate = CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    monkeypatch.setattr(integration, "command_admission", lambda _: gate)
    monkeypatch.setattr(integration, "_identity_status", lambda h, t: {"supported": False})
    monkeypatch.setattr(integration, "_morek_upload_link", lambda h, t: link())
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda h, e, cb: calls.append(cb) or (lambda: None))
    entry = SimpleNamespace(entry_id="c", async_on_unload=lambda cb: None, async_create_background_task=create_task)
    events = []

    class Worker:
        def suspend_for_availability_change(self):
            events.append("suspend")
            return 1

        def resume_after_availability_change(self, generation, **kwargs):
            events.append(("resume", generation, kwargs))

    worker = Worker()
    entry.runtime_data = SimpleNamespace(morek_worker=worker)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=object(), charge_control="switch.charger"))
    calls[0].worker = worker
    return calls[0], tasks, events


@pytest.mark.asyncio
async def test_switch_unavailable_with_live_link_resumes_uploads_only(monkeypatch, tmp_path):
    listener, tasks, events = await setup(monkeypatch, tmp_path, lambda: True)
    listener(unavailable_edge())
    await asyncio.gather(*tasks)
    assert events == ["suspend", ("resume", 1, {"switch_available": False})]


@pytest.mark.asyncio
async def test_switch_unavailable_without_link_stays_suspended(monkeypatch, tmp_path):
    listener, tasks, events = await setup(monkeypatch, tmp_path, lambda: False)
    listener(unavailable_edge())
    await asyncio.gather(*tasks)
    assert events == ["suspend"]


@pytest.mark.asyncio
async def test_link_lost_before_release_stays_suspended_until_the_switch_returns(monkeypatch, tmp_path):
    state = {"live": True}
    listener, tasks, events = await setup(monkeypatch, tmp_path, lambda: state["live"])
    listener(unavailable_edge())
    state["live"] = False  # gone between the edge and the release check
    await asyncio.gather(*tasks)
    assert events == ["suspend"]
    listener(available_edge())
    await asyncio.gather(*tasks)
    assert events[-1] == ("resume", 1, {})  # the switch's own return still resumes everything


@pytest.mark.asyncio
async def test_unreadable_link_is_never_permission(monkeypatch, tmp_path):
    def broken():
        raise RuntimeError("boom")

    listener, tasks, events = await setup(monkeypatch, tmp_path, broken)
    listener(unavailable_edge())
    await asyncio.gather(*tasks)
    assert events == ["suspend"]


def test_worker_resume_without_switch_skips_session_and_checker():
    seen = []
    fake = SimpleNamespace(
        _closed=False, _availability_generation=3, _suspended=True, trigger=lambda: seen.append("trigger"),
        session=SimpleNamespace(reconnect=lambda: seen.append("session")),
        checker=SimpleNamespace(request=lambda kind: seen.append(kind)))
    MorekScheduleWorker.resume_after_availability_change(fake, 3, switch_available=False)
    assert fake._suspended is False and seen == ["trigger"]
    fake._suspended = True
    MorekScheduleWorker.resume_after_availability_change(fake, 2, switch_available=False)  # stale generation
    assert fake._suspended is True and seen == ["trigger"]
    MorekScheduleWorker.resume_after_availability_change(fake, 3)
    assert seen == ["trigger", "trigger", "session", "availability_return"]


# ---- link return without a switch event: real monitor, real admission, real ownership/outcome files ----

import json  # noqa: E402

from custom_components.spotnav.api import morek_schedule  # noqa: E402
from custom_components.spotnav.const import MOREK_STATION_ID  # noqa: E402
from custom_components.spotnav.execution import command_admission as admission_module  # noqa: E402
from custom_components.spotnav.execution.morek_link import MorekLinkMonitor  # noqa: E402

from .test_execution_ownership import FakeStore  # noqa: E402
from .test_stage_23_lifecycle import environment, persist, record  # noqa: E402,F401  (fixture reused)

OUTCOMES = "spotnav.morek_schedule.connector_outcomes"


class StubWorker:
    def __init__(self):
        self.events = []
        self.link_monitor = None

    def suspend_for_availability_change(self):
        self.events.append("suspend")
        return self.events.count("suspend")

    def resume_after_availability_change(self, generation, **kwargs):
        self.events.append(("resume", generation, kwargs))


async def owned_setup(environment, monkeypatch, *, uncertain=False, settled=True):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, system, entry = environment
    point = system.charge_points[MOREK_STATION_ID]
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    owner = ({**record("morek_schedule"), "handover": {"version": 1, "state": "completed", "id": "a" * 32}}
             if settled else record())
    persist(hass, {"a": owner})
    ledger = hass.root / OUTCOMES
    ledger.write_text(json.dumps({"version": 1, "data": {
        "schema": 1, "entry_id": "a", "uncertain": False, "attempt": {"state": "accepted"}}}), encoding="utf-8")
    callbacks, tasks, unloads = [], [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    entry.async_create_background_task = lambda _h, coro, _name: tasks.append(asyncio.create_task(coro))
    entry.async_on_unload = unloads.append
    worker = StubWorker()
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=worker)
    monitor = worker.link_monitor = MorekLinkMonitor(
        hass, "a", worker, read=lambda: ("up" if point.status == "ok" else "down", point, None))
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    if settled:
        assert await gate.async_reconfirm_completed("a", identity) == "reconfirmed"
    if uncertain:  # a profile outcome becomes uncertain after the settled owner was confirmed
        ledger.write_text(json.dumps({"version": 1, "data": {
            "schema": 1, "entry_id": "a", "uncertain": True}}), encoding="utf-8")
    monitor.check()  # seed the monitor
    return hass, gate, point, worker, monitor, callbacks, tasks, unloads, identity


async def drain(tasks):
    while pending := [t for t in tasks if not t.done()]:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_link_down_at_edge_then_up_without_switch_event_resumes_once(monkeypatch, tmp_path):
    state = {"live": False}
    listener, tasks, events = await setup(monkeypatch, tmp_path, lambda: state["live"])
    worker = listener.worker
    monitor = worker.link_monitor = MorekLinkMonitor(
        None, "c", worker, read=lambda: ("up" if state["live"] else "down", object(), None))
    monitor.check()
    listener(unavailable_edge())
    await asyncio.gather(*tasks)
    assert events == ["suspend"]
    for _ in range(3):
        monitor.check()  # link still down: nothing happens, nothing is spammed
    await asyncio.gather(*tasks)
    assert events == ["suspend"]
    state["live"] = True  # the OCPP link returns; the switch never produced another event
    monitor.check()
    await asyncio.gather(*tasks)
    assert events == ["suspend", ("resume", 1, {"switch_available": False})]
    for _ in range(3):
        monitor.check()
    await asyncio.gather(*tasks)
    assert events == ["suspend", ("resume", 1, {"switch_available": False})]  # resumed exactly once


@pytest.mark.asyncio
async def test_settled_owner_migrate_mode_releases_when_link_returns(environment, monkeypatch):
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    point.status = "offline"
    monitor.check()
    callbacks[0](unavailable_edge())
    await drain(tasks)
    assert worker.events == ["suspend"] and "a" in gate._lifecycle_barriers  # link down: barrier and suspension stay
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    point.status = "ok"
    monitor.check()
    await drain(tasks)
    assert "a" not in gate._lifecycle_barriers
    assert gate.owned_ticket_current("a", admission_module.physical_connector(identity()))
    assert worker.events == ["suspend", ("resume", 1, {"switch_available": False})]
    monitor.check()
    await drain(tasks)
    assert len(worker.events) == 2
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["legacy_owner", "uncertain_ledger"])
async def test_unsettled_owner_or_uncertain_ledger_never_released_by_the_link(environment, monkeypatch, case):
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(
        environment, monkeypatch, uncertain=case == "uncertain_ledger", settled=case == "uncertain_ledger")
    point.status = "offline"
    monitor.check()
    callbacks[0](unavailable_edge())
    await drain(tasks)
    attempts, original = [], gate.async_release_lifecycle_barrier

    async def counted(*args):
        attempts.append(1)
        return await original(*args)

    monkeypatch.setattr(gate, "async_release_lifecycle_barrier", counted)
    point.status = "ok"
    for _ in range(4):
        monitor.check()  # a stable live link is one attempt, not one per poll
        await drain(tasks)
    assert attempts == [1] and "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    point.status = "offline"
    monitor.check()
    point.status = "ok"
    monitor.check()  # a drop and a return earn one more guarded attempt, still refused
    await drain(tasks)
    assert attempts == [1, 1] and worker.events == ["suspend"]
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["restore", "release"])
async def test_link_drop_during_admission_does_not_resume_until_it_returns(environment, monkeypatch, step):
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    name = "async_restore_reconnect" if step == "restore" else "async_release_lifecycle_barrier"
    original = getattr(gate, name)
    reached, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        reached.set()
        await proceed.wait()
        return await original(*args)

    monkeypatch.setattr(gate, name, delayed)
    callbacks[0](unavailable_edge())  # link live at the edge
    await asyncio.wait_for(reached.wait(), 2)
    point.status = "offline"  # lost while the admission await is in flight
    proceed.set()
    await drain(tasks)
    assert worker.events == ["suspend"]  # no resume on stale evidence
    point.status = "ok"
    monitor.check()
    await drain(tasks)
    assert worker.events == ["suspend", ("resume", 1, {"switch_available": False})]
    assert "a" not in gate._lifecycle_barriers
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_during_admission_blocks_release_and_resume(environment, monkeypatch):
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    original = gate.async_release_lifecycle_barrier
    reached, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        reached.set()
        await proceed.wait()
        return await original(*args)

    monkeypatch.setattr(gate, "async_release_lifecycle_barrier", delayed)
    callbacks[0](unavailable_edge())
    await asyncio.wait_for(reached.wait(), 2)
    with gate.person_stop_reservation("a", identity):
        proceed.set()
        await drain(tasks)
    assert "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    point.status = "offline"
    monitor.check()
    point.status = "ok"
    monitor.check()
    await drain(tasks)
    assert "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_switch_edge_supersedes_the_link_wait_and_stale_generation(environment, monkeypatch):
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    original = gate.async_release_lifecycle_barrier
    reached, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        reached.set()
        await proceed.wait()
        return await original(*args)

    monkeypatch.setattr(gate, "async_release_lifecycle_barrier", delayed)
    callbacks[0](unavailable_edge())
    await asyncio.wait_for(reached.wait(), 2)
    callbacks[0](available_edge())  # a newer edge while the link-driven attempt awaits admission
    proceed.set()
    await drain(tasks)
    resumes = [e for e in worker.events if e != "suspend"]
    assert all(e[1] == 2 and e[2] == {} for e in resumes)  # never the stale generation or an uploads-only resume
    count = len(worker.events)
    point.status = "offline"
    monitor.check()
    point.status = "ok"
    monitor.check()
    await drain(tasks)
    assert len(worker.events) == count  # the superseded wait is gone


@pytest.mark.asyncio
async def test_unload_cancels_the_link_wait(environment, monkeypatch):
    hass, gate, point, worker, monitor, callbacks, tasks, unloads, identity = await owned_setup(environment, monkeypatch)
    point.status = "offline"
    monitor.check()
    callbacks[0](unavailable_edge())
    await drain(tasks)
    for unload in unloads:
        unload()
    point.status = "ok"
    monitor.check()
    await drain(tasks)
    assert worker.events == ["suspend"] and not monitor._listeners


# ---- paced re-evaluation while the link stays up: a transient refusal never strands the suspended worker ----

CLEAR_LEDGER = {"version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False, "attempt": {"state": "accepted"}}}


def fake_clock(monkeypatch, start=1000.0):
    now = {"t": start}
    monkeypatch.setattr(integration, "_link_retry_clock", lambda: now["t"])
    return now


async def counting(gate, monkeypatch):
    """One count per guarded link-driven attempt (the reconfirmation inside it may release internally)."""
    attempts, original = [], gate.async_restore_reconnect

    async def counted(*args):
        attempts.append(1)
        return await original(*args)

    monkeypatch.setattr(gate, "async_restore_reconnect", counted)
    return attempts


@pytest.mark.asyncio
async def test_transient_ledger_refusal_is_retried_slowly_then_released_once(environment, monkeypatch):
    now = fake_clock(monkeypatch)
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    (hass.root / OUTCOMES).write_text("{not json", encoding="utf-8")  # transiently unreadable ledger
    attempts = await counting(gate, monkeypatch)
    callbacks[0](unavailable_edge())  # link live at the edge, ledger unreadable: refused
    await drain(tasks)
    assert attempts == [1] and "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    for _ in range(5):  # stable link, no switch event, polls inside the pacing window: no further attempts
        now["t"] += 10
        monitor.check()
        await drain(tasks)
    assert attempts == [1]
    (hass.root / OUTCOMES).write_text(json.dumps(CLEAR_LEDGER), encoding="utf-8")  # the ledger recovers
    now["t"] += 20  # 70 s after the first attempt
    monitor.check()
    await drain(tasks)
    assert attempts == [1, 1] and "a" not in gate._lifecycle_barriers
    assert worker.events == ["suspend", ("resume", 1, {"switch_available": False})]
    now["t"] += 10_000
    for _ in range(3):
        monitor.check()
        await drain(tasks)
    assert len(worker.events) == 2 and attempts == [1, 1]
    hass.station.call.assert_not_awaited()  # no charger write of any kind


@pytest.mark.asyncio
async def test_retry_pacing_backs_off_and_is_bounded(environment, monkeypatch):
    now = fake_clock(monkeypatch)
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(
        environment, monkeypatch, uncertain=True)
    attempts = await counting(gate, monkeypatch)
    callbacks[0](unavailable_edge())
    await drain(tasks)
    times = [0.0]
    for _ in range(2000):  # 30 s monitor polls for ~16 h of a persistent conflict
        now["t"] += 30
        before = len(attempts)
        monitor.check()
        await drain(tasks)
        if len(attempts) > before:
            times.append(now["t"] - 1000.0)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps[0] >= 60 and gaps == sorted(gaps) and max(gaps) <= 600 + 30  # grows, never denser than 60 s
    assert len(attempts) < 2000 / 10  # nowhere near one per poll
    assert "a" in gate._lifecycle_barriers and worker.events == ["suspend"]  # genuine persistent conflict stays
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_person_stop_is_never_undone_by_the_paced_retry(environment, monkeypatch):
    now = fake_clock(monkeypatch)
    hass, gate, point, worker, monitor, callbacks, tasks, _, identity = await owned_setup(environment, monkeypatch)
    attempts = await counting(gate, monkeypatch)
    with gate.person_stop_reservation("a", identity):  # revokes the completion ticket and bumps the generation
        callbacks[0](unavailable_edge())
        await drain(tasks)
        now["t"] += 100
        monitor.check()
        await drain(tasks)
        assert len(attempts) == 2 and "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    for _ in range(40):  # the Stop is lifted; the revoked authority stays revoked however long the retries run
        now["t"] += 300
        monitor.check()
        await drain(tasks)
    assert "a" in gate._lifecycle_barriers and worker.events == ["suspend"]
    assert not (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_paced_retry_stops_on_new_epoch_and_unload(environment, monkeypatch):
    now = fake_clock(monkeypatch)
    hass, gate, point, worker, monitor, callbacks, tasks, unloads, identity = await owned_setup(
        environment, monkeypatch, uncertain=True)
    attempts = await counting(gate, monkeypatch)
    callbacks[0](unavailable_edge())
    await drain(tasks)
    callbacks[0](available_edge())  # new epoch: the wait is superseded, not re-armed
    await drain(tasks)
    count, resumes = len(attempts), len(worker.events)
    now["t"] += 1000
    monitor.check()
    await drain(tasks)
    assert len(attempts) == count and len(worker.events) == resumes
    callbacks[0](unavailable_edge())  # a fresh wait, then unload
    await drain(tasks)
    count = len(attempts)
    for unload in unloads:
        unload()
    now["t"] += 1000
    monitor.check()
    await drain(tasks)
    assert len(attempts) == count and not monitor._listeners
