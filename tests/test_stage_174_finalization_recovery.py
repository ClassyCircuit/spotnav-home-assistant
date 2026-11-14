"""Stage 17.4: a closed charge replans a target plan once, only where its close can change the figure.

Real controller (`_energy_for`, `_progress_adjusted`, `measured_progress`) and, for the send questions, the real
Morek worker; only the charger controller and the session store are stubs. Mocked: nothing here proves deployed
behaviour or physical charging.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.sessions.store import SessionStore
from .test_morek_worker import drain, real_planner_worker
from .test_stage_145_fresh_inputs_recovery import _zones  # noqa: F401  (autouse fixture)
from .test_stage_145_progress_recovery import _charge, _read, _restore_domain_data, _shown, _stale_world, _wire  # noqa: F401


class Store:
    """The session store as the controller reads and listens to it."""

    def __init__(self):
        self.closed, self.open, self.listeners = [], None, []

    def closed_raw(self, _id):
        return tuple(self.closed)

    def open_raw(self, _id):
        return self.open

    def add_listener(self, _id, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def notify(self):
        for listener in list(self.listeners):
            listener()

    def close(self, end, kwh=None):
        item, self.open = self.open, None
        item.end = end
        if kwh is not None:
            item.energy_kwh = kwh
        self.closed.append(item)
        self.notify()


def _open(w, store, *, start, kwh, vehicle="veh-1"):
    item = _charge(start, kwh, vehicle=vehicle)
    item.end = None
    store.open = item
    auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
    return item


async def _world_with_open(monkeypatch, *, start_offset, kwh=1.0, vehicle="veh-1", owned=True):
    """A stale reading (two hours old) and an open charge, calculated once: the state a close then changes."""
    w = await _stale_world(monkeypatch, uncapped=False)
    car = _wire(w, [], owned=owned)
    car.held_off_by_person = False
    store = Store()
    store.add_listener("test", w.controller._on_sessions_changed)  # noqa: SLF001  (what `_arm_charge_watch` does)
    w.store_stub, w.car = store, car
    _open(w, store, start=w.read_at + start_offset, kwh=kwh, vehicle=vehicle)
    w.asked = []
    w.controller.set_reading_asker(lambda vid: w.asked.append(vid) or True)
    w.calcs = []
    real = w.controller.async_recalculate

    async def counted(cause=None):
        w.calcs.append(cause)
        return await real(cause)

    monkeypatch.setattr(w.controller, "async_recalculate", counted)
    w.first = await real()
    return w


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


def _end(w):
    return w.request.now - timedelta(minutes=5)


# ---- finalization that changes the known energy ------------------------------------------------------

def test_close_of_identified_later_session_replans_once_and_the_plan_shrinks(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), kwh=1.0)
        assert not w.first.progress_unknown
        before = _shown(w.first.proposal)
        w.store_stub.notify()  # a sample while open is not a finalization
        await _settle()
        assert w.calcs == []
        w.store_stub.close(_end(w), kwh=3.0)  # the final total is larger than the last open sample
        await _settle()
        assert w.calcs == ["session_finalized"]
        after = w.controller.snapshot()
        assert not after.progress_unknown and _shown(after.proposal) == pytest.approx(before - 2.0, abs=0.01)
        assert w.asked == []  # the figure is known: no reading is needed
        for _ in range(3):  # repeated notifications (late reconciliation, other samples) never loop
            w.store_stub.notify()
        await _settle()
        assert w.calcs == ["session_finalized"] and w.asked == []
    asyncio.run(run())


@pytest.mark.parametrize("vehicle,offset", [("veh-1", timedelta(minutes=-10)), (None, timedelta(minutes=20))])
def test_close_that_cannot_attribute_the_energy_replans_once_and_asks_for_one_reading(monkeypatch, vehicle, offset):
    """A charge straddling the old reading, or with no car, stays unknown after its close: only a newer reading
    clears it. The replan is truthful (flag persists) and the car is asked once through the existing request."""
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=offset, kwh=1.0, vehicle=vehicle)
        assert w.first.progress_unknown
        w.store_stub.close(_end(w), kwh=2.0)
        await _settle()
        assert w.calcs == ["session_finalized"]
        assert w.controller.snapshot().progress_unknown  # not pretended resolved
        assert _shown(w.controller.snapshot().proposal) == pytest.approx(_shown(w.first.proposal))
        assert w.asked == ["veh-1"]
        for _ in range(4):
            w.store_stub.notify()
        await _settle()
        assert w.calcs == ["session_finalized"] and w.asked == ["veh-1"]
        # a newer reading (the existing path) rebases and clears the flag
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now - timedelta(minutes=1))
        assert not (await w.controller.async_recalculate()).progress_unknown
    asyncio.run(run())


def test_a_second_session_closing_is_its_own_trigger_but_the_same_id_is_not(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), kwh=1.0)
        w.store_stub.close(_end(w), kwh=2.0)
        await _settle()
        await w.controller.async_recalculate()  # a later calculation counts nothing open: no watch
        w.calcs.clear()
        w.store_stub.notify()
        await _settle()
        assert w.calcs == []
        second = _open(w, w.store_stub, start=w.read_at + timedelta(minutes=50), kwh=0.5)
        await w.controller.async_recalculate()
        w.calcs.clear()
        w.store_stub.close(_end(w), kwh=1.5)
        await _settle()
        assert w.calcs == ["session_finalized"] and second.id in w.controller._finalized_seen  # noqa: SLF001
    asyncio.run(run())


# ---- nothing to do ---------------------------------------------------------------------------------------

def test_no_counted_open_session_or_not_morek_or_late_reconciliation_causes_nothing(monkeypatch):
    async def run():
        # no open session was counted: a store notification (a late reconciliation) is nothing
        w = await _stale_world(monkeypatch, uncapped=False)
        car = _wire(w, [_charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)])
        car.held_off_by_person = False
        store = Store()
        store.closed = [_charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)]
        auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
        assert (await w.controller.async_recalculate()).progress_unknown
        w.calcs = []
        real = w.controller.async_recalculate
        monkeypatch.setattr(w.controller, "async_recalculate", AsyncMock(side_effect=real))
        store.notify()
        await _settle()
        w.controller.async_recalculate.assert_not_awaited()
        # not Morek-owned: the same close does nothing
        n = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), owned=False)
        n.store_stub.close(_end(n), kwh=3.0)
        await _settle()
        assert n.calcs == [] and n.asked == []
    asyncio.run(run())


def test_restart_loses_nothing_the_flag_comes_from_a_fresh_calculation(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=-10), kwh=1.0)
        w.controller._progress_watch = None  # noqa: SLF001  (a new process knows nothing of the old calculation)
        w.controller._finalized_seen = []  # noqa: SLF001
        w.store_stub.close(_end(w), kwh=2.0)
        await _settle()
        assert w.calcs == []  # nothing armed yet, nothing invented
        assert (await w.controller.async_recalculate()).progress_unknown  # the flag is found again from the store
    asyncio.run(run())


# ---- Pause / Stop / pending attempt win -----------------------------------------------------------------

@pytest.mark.parametrize("hold", ["stop", "pause", "pending"])
def test_pause_stop_and_a_pending_attempt_cause_no_calculation_and_no_ask(monkeypatch, hold):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=-10), kwh=1.0)
        if hold == "stop":
            w.car.held_off_by_person = True
        else:
            w.controller._executor = SimpleNamespace(  # noqa: SLF001
                paused=hold == "pause", pending=object() if hold == "pending" else None)
        w.store_stub.close(_end(w), kwh=2.0)
        await _settle()
        assert w.calcs == [] and w.asked == []
    asyncio.run(run())


def test_a_failing_ask_or_calculation_is_swallowed_and_never_raised(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=-10), kwh=1.0)
        w.controller.set_reading_asker(lambda _v: (_ for _ in ()).throw(RuntimeError("no")))
        w.store_stub.close(_end(w), kwh=2.0)
        await _settle()
        assert w.calcs == ["session_finalized"]
    asyncio.run(run())


# ---- the store fires for close and for the late record ------------------------------------------------

def test_the_real_store_notifies_a_listener_on_close_and_on_a_late_record_without_changing_energy():
    hass = SimpleNamespace(loop=SimpleNamespace(call_later=lambda *_a, **_k: SimpleNamespace(cancel=lambda: None)),
                           async_create_task=lambda *_a, **_k: None)
    store = SessionStore.__new__(SessionStore)
    store._hass, store._listeners = hass, {}  # noqa: SLF001
    heard = []
    store._changed = lambda charger_id, **_k: SessionStore._notify(store, charger_id)  # noqa: SLF001
    store._open, store._closed, store._closing, store._imports = {}, {}, {}, {}  # noqa: SLF001
    store._closed_changed = lambda: None  # noqa: SLF001
    store._prune = lambda _now: None  # noqa: SLF001
    store.add_listener("test", lambda: heard.append(1))
    now = __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    item = _charge(now, 2.0)
    store.close(item, now)
    assert heard == [1]
    assert store.set_late("test", item.id, {"x": 1}) is True
    assert heard == [1, 1]
    assert store.closed_raw("test")[0].energy_kwh == 2.0  # a late record never changes the energy


# ---- real worker: the listener sends nothing; equal schedule sends nothing ---------------------------------

@pytest.mark.asyncio
async def test_finalization_replan_sends_nothing_by_itself_and_an_equal_schedule_is_not_resent(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.read_at = world.request.now - timedelta(hours=2)
    _read(world, world.read_at)
    car = _wire(world, [])
    car.held_off_by_person = False
    store = Store()
    store.add_listener("test", world.controller._on_sessions_changed)  # noqa: SLF001
    auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
    _open(world, store, start=world.read_at + timedelta(minutes=20), kwh=0.0)
    world.controller.set_reading_asker(lambda _v: True)
    await world.controller.async_recalculate()  # the first one flips the lazily loaded learning flag in the evidence
    first = await world.controller.async_recalculate()
    assert first.proposal is not None
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    store.close(world.request.now - timedelta(minutes=5), kwh=0.0)  # final total equals what was counted
    await _settle()
    await drain(w.worker)
    assert world.controller.snapshot().proposal is not None
    assert world.controller._finalized_seen  # noqa: SLF001  (the close did cause the replan)
    assert w.point.call.await_count == 1  # an equal schedule sends nothing
    w.worker.close()


# ---- preview never touches the live watch; a held close is retried on an existing event -------------------

def test_a_preview_neither_erases_nor_writes_the_live_progress_watch(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), kwh=1.0)
        watch = w.controller._progress_watch  # noqa: SLF001
        assert watch is not None
        settings = w.controller._store.settings("test")  # noqa: SLF001
        await w.controller.async_preview(settings)
        assert w.controller._progress_watch is watch  # noqa: SLF001  (a preview does not erase it)
        w.controller._progress_watch = None  # noqa: SLF001
        await w.controller.async_preview(settings)
        assert w.controller._progress_watch is None  # noqa: SLF001  (nor write it)
        w.controller._progress_watch = watch  # noqa: SLF001
        w.store_stub.close(_end(w), kwh=3.0)  # the close after a preview still triggers recovery
        await _settle()
        assert w.calcs == ["session_finalized"]
    asyncio.run(run())


@pytest.mark.parametrize("hold", ["pending", "pause"])
def test_a_close_held_by_a_send_or_pause_replans_once_when_the_hold_ends_and_never_twice(monkeypatch, hold):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), kwh=1.0)
        w.controller._executor = SimpleNamespace(  # noqa: SLF001
            paused=hold == "pause", pending=object() if hold == "pending" else None)
        w.store_stub.close(_end(w), kwh=3.0)
        await _settle()
        assert w.calcs == [] and w.controller._finalize_deferred  # noqa: SLF001
        w.controller._retry_deferred_finalization()  # noqa: SLF001  (still held: nothing, no churn)
        assert w.calcs == []
        w.controller._executor = None  # noqa: SLF001  (settled / resumed)
        await w.controller.async_note_execution_change()
        await _settle()
        assert w.calcs == ["session_finalized"] and w.controller._finalize_deferred is None  # noqa: SLF001
        for _ in range(3):
            await w.controller.async_note_execution_change()
            w.store_stub.notify()
        await _settle()
        assert w.calcs == ["session_finalized"]
    asyncio.run(run())


def test_a_person_stop_keeps_the_close_deferred_without_a_calculation_or_ask(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=-10), kwh=1.0)
        w.car.held_off_by_person = True
        w.store_stub.close(_end(w), kwh=2.0)
        for _ in range(3):
            await w.controller.async_note_execution_change()
        await _settle()
        assert w.calcs == [] and w.asked == []
    asyncio.run(run())


def test_a_calculation_after_the_close_drops_the_deferral_so_the_settlement_adds_none(monkeypatch):
    async def run():
        w = await _world_with_open(monkeypatch, start_offset=timedelta(minutes=20), kwh=1.0)
        w.controller._executor = SimpleNamespace(paused=False, pending=object())  # noqa: SLF001
        w.store_stub.close(_end(w), kwh=3.0)
        w.controller._executor = None  # noqa: SLF001
        await w.controller.async_recalculate()  # an ordinary calculation counts the final energy
        w.calcs.clear()
        await w.controller.async_note_execution_change()
        await _settle()
        assert w.calcs == [] and w.controller._finalize_deferred is None  # noqa: SLF001
    asyncio.run(run())


@pytest.mark.asyncio
async def test_real_worker_close_while_pending_then_settlement_sends_at_most_once_and_correctly(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.read_at = world.request.now - timedelta(hours=2)
    _read(world, world.read_at)
    car = _wire(world, [])
    car.held_off_by_person = False
    store = Store()
    store.add_listener("test", world.controller._on_sessions_changed)  # noqa: SLF001
    auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
    _open(world, store, start=world.read_at + timedelta(minutes=20), kwh=0.0)
    world.controller.set_reading_asker(lambda _v: True)
    await world.controller.async_recalculate()
    assert (await world.controller.async_recalculate()).proposal is not None
    w.worker.start()
    await drain(w.worker)
    sent = w.point.call.await_count
    assert sent == 1
    calcs = []
    real = world.controller.async_recalculate

    async def counted(cause=None):
        calcs.append(cause)
        return await real(cause)

    monkeypatch.setattr(world.controller, "async_recalculate", counted)
    world.controller._executor = SimpleNamespace(paused=False, pending=object())  # noqa: SLF001
    store.close(world.request.now - timedelta(minutes=5), kwh=0.0)
    await _settle()
    await drain(w.worker)
    assert calcs == [] and w.point.call.await_count == sent  # nothing during the pending send
    world.controller._executor = None  # noqa: SLF001  (the send settled)
    await world.controller.async_note_execution_change()
    await _settle()
    await drain(w.worker)
    assert calcs == ["session_finalized"]  # one calculation
    assert w.point.call.await_count == sent  # an equal schedule is not resent; a changed one only once
    await world.controller.async_note_execution_change()
    await _settle()
    assert calcs == ["session_finalized"]
    w.worker.close()
