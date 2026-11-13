"""Stage 9.5: bounded automatic recovery and visible blockers through the real Morek worker and send path.

HA/OCPP/ownership are the usual mocked boundaries (see test_morek_worker). Mocks do not prove deployed behavior
or physical charging; an accepted write here is an acknowledgement only.
"""

from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_worker import IDENTITY, NOW, drain, setup


PRIOR = {"state": "accepted", "pause_id": "p0", "source": "worker", "id": "a0", "fingerprint": "f0",
         "at": NOW.isoformat()}  # the earlier Stop's settled attempt: what an ordinary interrupted Resume follows


def resume_record(w, attempt=PRIOR, **extra):
    pause = {"version": 1, "type": "resume_requested", "id": "r1",
             "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": attempt,
                      "schedule_pause": pause, **extra}
    return pause


# ---- bounded re-evaluation of transient blockers ------------------------------------------------

def test_backoff_schedule_is_bounded_and_codes_are_classified():
    delays = [morek_schedule.blocker_retry_delay(n) for n in range(morek_schedule.BLOCKER_RETRY_LIMIT + 1)]
    assert delays[:5] == [60, 180, 600, 900, 900] and delays[-1] is None and min(delays[:-1]) >= 60
    transient = morek_schedule.TRANSIENT_BLOCKERS
    for code in ("charger_unavailable", "prices_stale_or_unavailable", "target_soc_stale", "vehicle_input_stale"):
        assert code in transient
    for code in ("upload_uncertain", "upload_rejected", "paused_until_resume", "protection_conflict_unresolved",
                 "migration_confirmation_required", "legacy_pause_active", "resume_requires_confirmation"):
        assert code not in transient  # waiting cannot clear these; a person (or their own cooldown) does
    assert all(morek_schedule.decision_blocker(code) for code in transient)


@pytest.mark.asyncio
async def test_offline_charger_is_rechecked_with_backoff_then_sends_once_when_back(monkeypatch):
    w = setup(monkeypatch)
    online = False
    w.worker._available = lambda: online
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "charger_unavailable" and w.worker._blocker_timer is not None  # noqa: SLF001
    assert w.worker.blocker_retry["attempts"] == 0 and w.worker.blocker_retry["next_retry_at"]
    status = morek_schedule.blocker_retry_status(w.worker)
    assert status["code"] == "charger_unavailable" and not status["exhausted"]
    for expected in range(1, morek_schedule.BLOCKER_RETRY_LIMIT + 1):  # what the timer does when it fires
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
        assert w.worker.blocker_retry["attempts"] == expected
    assert w.worker.blocker_retry["exhausted"] and w.worker._blocker_timer is None  # noqa: SLF001
    w.point.call.assert_not_awaited()
    online = True  # an event (reconnect) still re-evaluates after the timed checks stopped
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_accepted_unverified"
    assert w.worker.blocker_retry is None and w.worker._blocker_timer is None  # noqa: SLF001
    w.worker.close()


@pytest.mark.asyncio
async def test_delayed_prices_recover_when_published_and_other_triggers_do_not_reset_the_count(monkeypatch):
    w = setup(monkeypatch)
    good = w.planner.current
    w.planner.current = SimpleNamespace(in_process=True, proposal=None, settings_revision=4, price_state="unavailable")
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "prices_stale_or_unavailable" and w.worker.blocker_retry["attempts"] == 0
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    w.worker.trigger()  # unrelated trigger: still blocked, the backoff must not restart
    await drain(w.worker)
    assert w.worker.blocker_retry["attempts"] == 1
    assert morek_schedule.decision_blocker(w.worker.reason) == {"code": "prices_stale_or_unavailable",
                                                                "action": "wait_for_prices"}
    w.planner.current = good
    w.planner.publish()  # prices arrive: the planner event, not the timer, re-evaluates
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.blocker_retry is None
    w.worker.close()


@pytest.mark.asyncio
async def test_unknown_outcome_is_never_timer_retried_and_no_transient_state_is_shown(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain"
    assert w.worker._blocker_timer is None and w.worker.blocker_retry is None  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_close_cancels_the_blocker_timer(monkeypatch):
    w = setup(monkeypatch)
    w.worker._available = lambda: False
    w.worker.start()
    await drain(w.worker)
    timer = w.worker._blocker_timer  # noqa: SLF001
    assert timer is not None
    w.worker.close()
    assert w.worker._blocker_timer is None and timer.cancelled()  # noqa: SLF001


# ---- interrupted versus settled Resume ----------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_not_dispatched_before_restart_needs_a_fresh_explicit_resume(monkeypatch):
    # A concurrent Stop could have been observed in memory only, so a never-dispatched Resume is NOT auto-recovered.
    for attempt in (PRIOR, {**PRIOR, "pause_id": "r1", "state": "rejected"},
                    {**PRIOR, "pause_id": "r1", "state": "aborted_before_dispatch"}):
        w = setup(monkeypatch)
        resume_record(w, attempt)
        assert not morek_schedule._resume_authorized(w.ledger.value, w.worker, 0)  # noqa: SLF001
        w.worker.start()
        await drain(w.worker)
        assert w.worker.reason == "resume_requires_confirmation"
        w.point.call.assert_not_awaited()
        w.worker.close()


@pytest.mark.asyncio
async def test_unproven_matching_attempts_still_need_confirmation(monkeypatch):
    cases = {
        "unknown write": ({"state": "uncertain", "pause_id": "r1"}, {"uncertain": True}),
        "accepted but unsettled": ({"state": "accepted", "pause_id": "r1", "source": "manual", "id": "a1"}, {}),
    }
    for name, (attempt, extra) in cases.items():
        w = setup(monkeypatch)
        resume_record(w, attempt, **extra)
        assert not morek_schedule._resume_authorized(w.ledger.value, w.worker, 0), name  # noqa: SLF001
        w.worker.start()
        await drain(w.worker)
        assert w.worker.reason == "resume_requires_confirmation", name
        w.point.call.assert_not_awaited()
        w.worker.close()


@pytest.mark.asyncio
async def test_interrupted_resume_waits_for_a_person_stop_and_never_overrides_a_recorded_stop(monkeypatch):
    w = setup(monkeypatch)
    resume_record(w)
    connector = physical_connector(w.identity)
    w.admission._person_stops[connector] = 1  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    w.admission._person_stops.clear()  # noqa: SLF001
    w.worker.resume_interrupted = "r1"  # in this process a Stop pre-empted that Resume
    w.worker.trigger()
    await drain(w.worker)
    assert w.worker.reason == "resume_requires_confirmation"
    w.point.call.assert_not_awaited()
    w.ledger.value["schedule_pause"] = {**w.ledger.value["schedule_pause"], "type": "pause_until_resumed", "id": "p2"}
    w.worker.trigger()  # the Stop's own durable record wins
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    w.worker.close()


def test_recovery_helper_and_unsettled_marker_are_gone():
    assert not hasattr(morek_schedule, "resume_interrupted_recoverable")


@pytest.mark.asyncio
async def test_durably_marked_interrupted_resume_is_not_recovered_and_matching_accepted_is_still_recovered(monkeypatch):
    w = setup(monkeypatch)
    resume_record(w, resume_interrupted="r1")
    assert not morek_schedule._resume_authorized(w.ledger.value, w.worker, 0)  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "resume_requires_confirmation"
    w.point.call.assert_not_awaited()
    w.worker.close()
    w = setup(monkeypatch)  # settled matching accepted Resume is still recovered without confirmation
    resume_record(w, {"state": "accepted", "pause_id": "r1", "source": "worker", "id": "a1", "fingerprint": "x"},
                  acknowledged={"id": "a1", "fingerprint": "x"})
    assert morek_schedule._resume_authorized(w.ledger.value, w.worker, 0)  # noqa: SLF001
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_racing_a_committed_resume_survives_restart_before_the_stop_is_recorded(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from custom_components.spotnav.execution.auto_execution import AutoControlCommitted
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")  # an earlier Stop, sent and settled
    await drain(w.worker)
    sent = w.point.call.await_count
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.ledger.write
    async def blocked(value):
        if value.get("schedule_pause", {}).get("type") == "resume_requested" and not entered.is_set():
            entered.set()
            await release.wait()
        await original(value)
    monkeypatch.setattr(w.ledger, "write", blocked)
    task = asyncio.create_task(morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True))
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):  # Stop observed, not yet recorded
        release.set()
        with pytest.raises(AutoControlCommitted):
            await task
    record = w.ledger.value
    resume_id = record["schedule_pause"]["id"]
    assert record["schedule_pause"]["type"] == "resume_requested" and record["resume_interrupted"] == resume_id
    w.worker.close()
    # "Restart" before the Stop's durable intent exists: a fresh worker has no in-memory mark.
    w.worker.resume_interrupted = None
    w.worker.resume_ticket = None
    assert not morek_schedule._resume_authorized(w.ledger.value, w.worker, 0)  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == sent  # nothing was sent for the superseded Resume
    assert morek_schedule._owned_pause_status(  # noqa: SLF001
        w.ledger.value, {}, False, w.worker)["request"] == "resume_requires_confirmation"
    # A person's new Resume gets a fresh id (not the superseded one) and clears the guard.
    monkeypatch.setattr(w.ledger, "write", original)
    w.admission._person_stops.clear()  # noqa: SLF001
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    assert w.ledger.value["schedule_pause"]["id"] != resume_id and "resume_interrupted" not in w.ledger.value
    w.worker.close()


# ---- crash windows around a Resume racing a Stop -------------------------------------------------------------

async def _resume_harness(monkeypatch):
    from unittest.mock import AsyncMock
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")  # an earlier Stop, sent and settled
    await drain(w.worker)
    return w


@pytest.mark.asyncio
async def test_crash_after_resume_commit_with_unrecorded_stop_needs_a_fresh_resume(monkeypatch):
    """Resume is durable, a Stop was reserved only in memory, the process dies before any further write."""
    w = await _resume_harness(monkeypatch)
    sent = w.point.call.await_count
    original = w.ledger.write

    async def write(value):
        await original(value)
        if value.get("schedule_pause", {}).get("type") == "resume_requested":
            w.admission._person_stops[physical_connector(w.identity)] = 1  # noqa: SLF001  Stop reserved, unrecorded
            monkeypatch.setattr(w.ledger, "write", _dead)  # the process dies before the Stop's marker/intent
    async def _dead(_value):
        raise OSError("simulated crash")
    monkeypatch.setattr(w.ledger, "write", write)
    with pytest.raises(OSError):
        await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    w.admission._person_stops.clear()  # noqa: SLF001
    record = w.ledger.value  # exactly what a restart loads
    resume_id = record["schedule_pause"]["id"]
    assert record["schedule_pause"]["type"] == "resume_requested" and "resume_interrupted" not in record
    w.worker.close()
    w.worker.resume_interrupted = None  # fresh process: no memory of the race
    w.worker.resume_ticket = None
    assert not morek_schedule._resume_authorized(record, w.worker, 0)  # noqa: SLF001
    monkeypatch.setattr(w.ledger, "write", original)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == sent  # nothing is sent for the ambiguous Resume
    assert morek_schedule._owned_pause_status(  # noqa: SLF001
        w.ledger.value, {}, False, w.worker)["request"] == "resume_requires_confirmation"
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)  # explicit fresh Resume
    assert w.worker.resume_ticket[0] == w.ledger.value["schedule_pause"]["id"]  # this process now holds the ticket
    w.worker.close()


@pytest.mark.asyncio
async def test_current_process_ticket_still_continues_an_ordinary_resume(monkeypatch):
    w = await _resume_harness(monkeypatch)
    intent = await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    record = w.ledger.value
    assert record["schedule_pause"]["id"] == intent["id"] and "resume_interrupted" not in record
    assert w.worker.resume_ticket[0] == intent["id"]
    assert morek_schedule._resume_authorized(record, w.worker, w.worker.resume_ticket[1])  # noqa: SLF001
    w.worker.resume_ticket = None  # restart before the Resume's own wire call: nothing proves it is safe
    w.worker.resume_interrupted = None
    assert not morek_schedule._resume_authorized(record, w.worker, 0)  # noqa: SLF001
    w.worker.close()


def test_matching_settled_accepted_recovery_is_preserved_but_recorded_stop_blocks_it():
    worker = SimpleNamespace(resume_ticket=None, resume_interrupted=None)
    pause = {"type": "resume_requested", "id": "r1"}
    settled = {"schedule_pause": pause, "uncertain": False,
               "attempt": {"state": "accepted", "pause_id": "r1", "source": "worker", "id": "a1", "fingerprint": "x"},
               "acknowledged": {"id": "a1", "fingerprint": "x"}}
    assert morek_schedule._resume_authorized(settled, worker, 0)  # noqa: SLF001
    assert not morek_schedule._resume_authorized({**settled, "resume_interrupted": "r1"}, worker, 0)  # noqa: SLF001
    assert not morek_schedule._resume_authorized({**settled, "uncertain": True}, worker, 0)  # noqa: SLF001
