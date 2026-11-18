"""Stage 19.3: persisted slow-pace re-evaluation and durable, bounded observations (mocked boundaries only).

The real worker and send path run against the usual fakes. Nothing here proves charger behavior; an ambiguous
(unknown) write is never retried, and 19.2's resolution of one is not implemented."""

import copy
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_worker import NOW, drain, setup


def _record(**extra):
    return {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None, **extra}


def _decision_lines(caplog):
    return [r for r in caplog.records if "Morek schedule decision" in r.getMessage()]


async def _blocked(monkeypatch, record=None):
    w = setup(monkeypatch)
    w.ledger.value = record or _record()
    w.worker._available = lambda: False  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    return w


def test_observation_helpers_are_bounded_whitelisted_and_codes_only():
    entry = morek_schedule.observation_entry("charger_unavailable", "t")
    assert entry["who"] == "system" and entry["next"] == "automatic_recheck" and entry["evidence"] == "none"
    assert entry["basis"] == "observed" and set(entry) == {"code", "evidence", "basis", "who", "next", "count",
                                                           "first_at", "last_at"}
    assert morek_schedule.observation_entry("upload_rejected", "t")["evidence"] == "ack"
    assert morek_schedule.observation_entry("upload_rejected", "t")["next"] == "person_action"
    assert morek_schedule.observation_entry("upload_uncertain", "t")["who"] == "person"
    assert morek_schedule.observation_entry("target_soc_stale", "t")["who"] == "vehicle"
    assert morek_schedule.observation_entry("unchanged", "t") is None
    raw = {"version": 1, "pace": {"code": "nope", "phase": "slow", "attempts": 1},
           "observations": [{"code": "x", "count": 1}] + [
               {"code": "charger_unavailable", "count": 2, "first_at": "a", "last_at": "b", "payload": "secret"}] * 20}
    clean = morek_schedule.sanitize_retry_state(raw)
    assert clean["pace"] is None and len(clean["observations"]) == morek_schedule.RETRY_OBSERVATION_CAP
    assert all("payload" not in item for item in clean["observations"])
    assert morek_schedule.sanitize_retry_state("garbage") == {"pace": None, "observations": []}


@pytest.mark.asyncio
async def test_long_outage_goes_slow_persists_and_continues_after_restart_without_a_burst(monkeypatch):
    w = await _blocked(monkeypatch)
    assert w.worker.blocker_retry["phase"] == "fast"
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 2):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    state = w.worker.blocker_retry
    assert state["phase"] == "slow" and not state["exhausted"] and w.worker._blocker_timer is not None  # noqa: SLF001
    attempts = state["attempts"]
    await w.worker.async_flush_retry_state()
    saved = w.ledger.value["retry_state"]
    assert w.worker.retry_persistence == "ok"
    assert saved["pace"]["attempts"] == attempts and saved["pace"]["phase"] == "slow"
    assert saved["observations"][-1]["code"] == "charger_unavailable" and saved["observations"][-1]["count"] == 1
    w.worker.close()
    # restart: same ledger, new process. The first run evaluates once; the pace is not reset to the fast phase.
    again = setup(monkeypatch)
    again.ledger.value = copy.deepcopy(w.ledger.value)
    again.worker._available = lambda: False  # noqa: SLF001
    again.worker.start()
    await drain(again.worker)
    assert again.worker.blocker_retry["attempts"] == attempts and again.worker.blocker_retry["phase"] == "slow"
    assert again.worker.observations[-1]["code"] == "charger_unavailable"
    assert again.point.call.await_count == 0
    again.worker.close()


@pytest.mark.asyncio
async def test_pace_resets_when_the_blocker_clears_and_a_send_is_one_guarded_run(monkeypatch):
    online = False
    w = await _blocked(monkeypatch)
    w.worker._available = lambda: online  # noqa: SLF001
    for _ in range(3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.worker.blocker_retry["attempts"] == 3
    online = True
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.blocker_retry is None and w.worker._pace is None  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1  # equal schedule: nothing more
    w.worker.close()


@pytest.mark.asyncio
async def test_flapping_blockers_keep_observations_bounded_and_log_once_per_change(monkeypatch, caplog):
    w = setup(monkeypatch)
    w.ledger.value = _record()
    codes = ["charger_unavailable", "prices_stale_or_unavailable", "target_soc_stale", "no_current_plan"]
    caplog.set_level(logging.INFO)
    current = {"code": codes[0]}
    w.planner.morek_plan_blocker = lambda *_: current["code"]
    w.worker.start()
    await drain(w.worker)
    for index in range(60):
        current["code"] = codes[index % 2]  # flap between two blockers
        w.worker.trigger()
        await drain(w.worker)
    assert len(w.worker.observations) <= morek_schedule.RETRY_OBSERVATION_CAP
    by = {item["code"]: item for item in w.worker.observations}
    assert by[codes[0]]["count"] >= 20 and w.point.call.await_count == 0
    # same blocker repeated many times: counted, not logged again
    current["code"] = "target_soc_stale"
    w.worker.trigger()
    await drain(w.worker)
    before = len(_decision_lines(caplog))
    for _ in range(20):
        w.worker.trigger()
        await drain(w.worker)
    assert len(_decision_lines(caplog)) == before
    # many distinct codes cannot grow the list
    for code in ["target_soc_unknown_x", *codes, "worker_unavailable", "invalid_plan", "too_many_blocks",
                 "upload_rejected", "stale_generation", "planner_changed"]:
        w.worker._observe(code)  # noqa: SLF001
    assert len(w.worker.observations) == morek_schedule.RETRY_OBSERVATION_CAP
    w.worker.close()


@pytest.mark.asyncio
async def test_persistence_is_debounced_and_failure_is_visible_not_silent(monkeypatch):
    w = await _blocked(monkeypatch)
    writes = []
    original = w.ledger.write

    async def counting(record):
        writes.append(1)
        await original(record)

    w.ledger.write = counting
    for _ in range(5):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert not writes  # nothing was written per retry (the debounce timer has not fired)
    await w.worker.async_flush_retry_state()
    assert len(writes) == 1
    await w.worker.async_flush_retry_state()
    assert len(writes) == 1  # nothing changed: no second write

    async def failing(record):
        raise OSError("disk")

    w.ledger.write = failing
    w.worker._observe("charger_unavailable")  # noqa: SLF001
    await w.worker.async_flush_retry_state()
    assert w.worker.retry_persistence == "OSError" and w.worker._state_dirty  # noqa: SLF001
    assert morek_schedule.observations_status(w.worker)
    w.worker.close()


@pytest.mark.asyncio
async def test_flush_never_creates_the_record_and_respects_a_foreign_one(monkeypatch):
    w = await _blocked(monkeypatch)
    w.ledger.value = None
    w.worker._mark_state_dirty()  # noqa: SLF001
    await w.worker.async_flush_retry_state()
    assert w.ledger.value is None
    w.ledger.value = _record()
    w.ledger.value["entry_id"] = "other"
    w.worker._mark_state_dirty()  # noqa: SLF001
    await w.worker.async_flush_retry_state()
    assert "retry_state" not in w.ledger.value
    w.worker.close()


@pytest.mark.asyncio
async def test_slow_rejection_retry_obeys_stop_counts_one_decision_and_never_touches_unknown(monkeypatch, caplog):
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    connector = physical_connector(w.identity)
    for expected in (2, 3):
        w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=1)).isoformat()
        w.worker.trigger()
        await drain(w.worker)
        assert w.point.call.await_count == expected
    caplog.set_level(logging.INFO)
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=1)).isoformat()
    w.admission._person_stops[connector] = True  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 3  # a Stop wins over the slow retry; nothing recorded as sent
    w.admission._person_stops.pop(connector)  # noqa: SLF001
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=5)).isoformat()
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 4
    before = len(_decision_lines(caplog))
    w.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=5)).isoformat()
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 5
    assert len(_decision_lines(caplog)) == before  # a further slow re-send is a counted repeat, not another line
    obs = {item["code"]: item for item in w.worker.observations}
    assert obs["upload_rejected"]["who"] == "person" and obs["upload_rejected"]["next"] == "automatic_recheck"
    w.worker.close()
    # an unknown write is never timer-retried
    u = setup(monkeypatch)
    u.point.call.side_effect = TimeoutError
    u.worker.start()
    await drain(u.worker)
    for _ in range(3):
        u.ledger.value["attempt"]["at"] = (NOW - timedelta(hours=9)).isoformat()
        u.worker.trigger(kind="recovery")
        await drain(u.worker)
    assert u.point.call.await_count == 1 and u.worker.blocker_retry is None
    assert u.worker.observations[-1]["code"] == "upload_uncertain"
    assert u.worker.observations[-1]["next"] == "person_action"
    u.worker.close()


# ---- review fixes: connector+schedule guard, re-arm after an active flush, persisted next_at ------------------------

def _record_timers(monkeypatch):
    """Fake clock for the flush timer: record (delay, callback) instead of waiting."""
    import asyncio
    loop = asyncio.get_running_loop()
    timers = []
    real = loop.call_later

    def fake(delay, callback, *args):
        if getattr(callback, "__name__", "") == "_start_flush":
            handle = SimpleNamespace(cancelled=False)
            handle.cancel = lambda: setattr(handle, "cancelled", True)
            timers.append((delay, callback, handle))
            return handle
        return real(delay, callback, *args)

    monkeypatch.setattr(loop, "call_later", fake)
    return timers


def _fire(timers):
    delay, callback, handle = timers.pop(0)
    assert not handle.cancelled
    callback()
    return delay


@pytest.mark.asyncio
async def test_flush_waits_for_the_connector_lock_and_never_clobbers_a_concurrent_uncertain_write(monkeypatch):
    import asyncio
    w = await _blocked(monkeypatch)
    connector = physical_connector(w.identity)
    worker_lock = w.admission._lock_for(connector)  # noqa: SLF001
    await worker_lock.acquire()  # a pending wire / session writer owns the connector
    w.worker._mark_state_dirty()  # noqa: SLF001
    flush = asyncio.ensure_future(w.worker.async_flush_retry_state())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not flush.done() and not w.ledger.writes  # blocked on the connector lock, nothing written
    record = w.ledger.value
    record["uncertain"] = True  # the writer records an uncertain wire under its own guard
    record["attempt"] = {"state": "unknown"}
    await w.ledger.write(record)
    worker_lock.release()
    await asyncio.wait_for(flush, 2)
    saved = w.ledger.value
    assert saved["uncertain"] is True and saved["attempt"] == {"state": "unknown"}
    assert saved["retry_state"]["pace"]["code"] == "charger_unavailable"
    w.worker.close()


@pytest.mark.asyncio
async def test_flush_during_a_pending_wire_and_a_stop_keeps_the_uncertain_result(monkeypatch):
    import asyncio
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.point.call.side_effect = TimeoutError  # the wire result is unknown
    w.ledger.value = _record()
    w.worker.start()
    await asyncio.wait_for(w.admission.entered.wait(), 2)  # dispatch is about to run under the connector lock
    w.worker._observe("charger_unavailable")  # noqa: SLF001
    flush = asyncio.ensure_future(w.worker.async_flush_retry_state())
    for _ in range(5):
        await asyncio.sleep(0)
    assert not flush.done() and "retry_state" not in w.ledger.value
    w.admission.release.set()
    await drain(w.worker)
    await asyncio.wait_for(flush, 2)
    await w.worker.async_flush_retry_state()
    assert w.ledger.value["uncertain"] is True and "retry_state" in w.ledger.value
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_busy_schedule_lock_is_skipped_without_deadlock_even_for_the_reverse_lock_order(monkeypatch):
    import asyncio
    timers = _record_timers(monkeypatch)
    w = await _blocked(monkeypatch)
    connector = physical_connector(w.identity)
    schedule_lock = w.hass.data[morek_schedule._DATA_KEY]["charger"][2]  # noqa: SLF001
    timers.clear()
    w.worker._flush_timer = None  # noqa: SLF001 - the initial debounce timer is not under test
    w.worker._mark_state_dirty()  # noqa: SLF001
    async def manual():  # the manual path: schedule lock first, then the connector lock
        async with schedule_lock:
            await asyncio.sleep(0)
            async with w.admission._lock_for(connector):  # noqa: SLF001
                await asyncio.sleep(0)
    holder = asyncio.ensure_future(manual())
    await asyncio.sleep(0)  # the manual path now holds the schedule lock
    await asyncio.wait_for(w.worker.async_flush_retry_state(), 2)  # skips instead of waiting: no deadlock
    await asyncio.wait_for(holder, 2)
    assert not w.ledger.writes and w.worker._state_dirty and len(timers) == 1  # noqa: SLF001 - re-armed, not lost
    _fire(timers)
    await w.worker._flush_task  # noqa: SLF001
    assert "retry_state" in w.ledger.value and not w.worker._state_dirty  # noqa: SLF001
    w.worker.close()


@pytest.mark.asyncio
async def test_dirty_during_an_active_flush_and_a_failed_flush_both_rearm(monkeypatch):
    import asyncio
    timers = _record_timers(monkeypatch)
    w = await _blocked(monkeypatch)
    timers.clear()
    w.worker._flush_timer = None  # noqa: SLF001
    gate, original = asyncio.Event(), w.ledger.write

    async def slow(record):
        await gate.wait()
        await original(record)

    w.ledger.write = slow
    w.worker._mark_state_dirty()  # noqa: SLF001
    timers.clear()
    w.worker._flush_timer = None  # noqa: SLF001
    task = asyncio.ensure_future(w.worker.async_flush_retry_state())
    for _ in range(5):
        await asyncio.sleep(0)
    w.worker._observe("target_soc_stale")  # noqa: SLF001 - changed while the write is in flight
    assert not timers  # the running flush owns the re-arm
    gate.set()
    await task
    assert w.worker._state_dirty and len(timers) == 1  # noqa: SLF001 - armed once the task is done
    # failure: the retry is slow (not a burst) and a later success clears it
    async def failing(record):
        raise OSError("disk")

    w.ledger.write = failing
    timers.clear()
    _fire([(0, w.worker._start_flush, SimpleNamespace(cancelled=False))])  # noqa: SLF001
    await w.worker._flush_task  # noqa: SLF001
    assert w.worker.retry_persistence == "OSError" and len(timers) == 1
    assert timers[0][0] == morek_worker_retry()
    w.ledger.write = original
    _fire(timers)
    await w.worker._flush_task  # noqa: SLF001
    assert w.worker.retry_persistence == "ok" and not w.worker._state_dirty and not timers  # noqa: SLF001
    assert any(o["code"] == "target_soc_stale" for o in w.ledger.value["retry_state"]["observations"])
    w.worker.close()


def morek_worker_retry():
    from custom_components.spotnav.execution import morek_worker
    return morek_worker._PERSIST_RETRY  # noqa: SLF001


@pytest.mark.asyncio
async def test_restart_keeps_the_persisted_next_check_time_and_never_sends_early(monkeypatch):
    import asyncio
    from custom_components.spotnav.execution import morek_worker
    w = await _blocked(monkeypatch)
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 2):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    await w.worker.async_flush_retry_state()
    saved_next = w.ledger.value["retry_state"]["pace"]["next_at"]
    w.worker.close()
    again = setup(monkeypatch)
    again.ledger.value = copy.deepcopy(w.ledger.value)
    again.worker._available = lambda: False  # noqa: SLF001
    seen = []
    loop = asyncio.get_running_loop()
    real = loop.call_later
    monkeypatch.setattr(loop, "call_later", lambda d, cb, *a: (seen.append(d), real(d, cb, *a))[1])
    again.worker.start()
    await drain(again.worker)
    full = morek_schedule.blocker_retry_delay(again.worker.blocker_retry["attempts"])
    assert again.worker.blocker_retry["phase"] == "slow" and again.point.call.await_count == 0
    # NOW is fixed in these tests: the remaining time equals the persisted one, never more than a full slow step
    assert max(seen[-3:]) <= full
    assert again.worker.blocker_retry["attempts"] == w.worker.blocker_retry["attempts"]
    assert saved_next
    again.worker.close()
