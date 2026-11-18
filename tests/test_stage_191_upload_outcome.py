"""Stage 19.1: provably-not-sent versus ambiguous upload outcomes, through the real worker and send path.

HA, OCPP and connector admission are mocked boundaries; nothing here proves installed or physical behavior."""

import asyncio

import pytest
from unittest.mock import AsyncMock

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_worker
from .test_morek_worker import drain, setup


def _boundary(w, mode, calls):
    async def current(entry_id, connector):
        calls.append(mode)
        if mode == "raise":
            raise RuntimeError("storage")
        if mode == "refuse":
            return False
        if mode == "changed":
            w.ledger.value["other_writer"] = {"kept": True}
        return True
    w.admission.async_owned_boundary_current = current


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,proof", [("changed", "ledger_changed"), ("raise", "durable_check_failed"),
                                        ("refuse", "durable_check_refused")])
async def test_pre_wire_exit_releases_with_proof_and_next_trigger_sends_once(monkeypatch, mode, proof):
    w = setup(monkeypatch)
    _boundary(w, mode, [])
    w.worker.start()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    assert w.worker.reason == "upload_not_sent"
    attempt = w.ledger.value["attempt"]
    assert w.ledger.value["uncertain"] is False
    assert (attempt["state"], attempt["dispatch_class"], attempt["not_sent_proof"]) == (
        "aborted_before_dispatch", "not_sent", proof)
    assert "rejections" not in attempt and morek_schedule.rejection_retry_at(w.ledger.value) is None
    assert w.ledger.value.get("other_writer") == ({"kept": True} if mode == "changed" else None)  # never clobbered
    assert morek_schedule.upload_outcome_class(w.ledger.value) == {
        "class": "not_sent", "proof": proof, "basis": "inferred"}
    _boundary(w, "ok", [])
    w.settings.revision = w.planner.current.settings_revision = 5
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_accepted_unverified"
    assert w.ledger.value["attempt"]["dispatch_class"] == "resolved" and w.ledger.value["uncertain"] is False
    w.worker.close()


@pytest.mark.asyncio
async def test_changed_ledger_with_another_attempt_is_not_cleared(monkeypatch):
    w = setup(monkeypatch)

    async def current(entry_id, connector):
        # Another writer replaced the attempt after ours was persisted.
        w.ledger.value["attempt"] = {**w.ledger.value["attempt"], "id": "someone-else"}
        return True
    w.admission.async_owned_boundary_current = current
    w.worker.start()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    assert w.worker.reason == "upload_uncertain"
    assert w.ledger.value["uncertain"] is True and w.ledger.value["attempt"]["id"] == "someone-else"
    w.worker.close()


@pytest.mark.asyncio
async def test_unrecordable_proof_keeps_latch_then_read_side_proof_releases(monkeypatch):
    w = setup(monkeypatch)
    _boundary(w, "refuse", [])
    original = w.ledger.write
    fail = {"on": False}

    async def write(value):
        if fail["on"] and value.get("attempt", {}).get("dispatch_class") == "not_sent":
            raise OSError("disk")
        await original(value)
    monkeypatch.setattr(w.ledger, "write", write)
    fail["on"] = True
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain" and w.ledger.value["uncertain"] is True
    assert w.ledger.value["attempt"]["dispatch_class"] == "pre_wire"
    fail["on"] = False
    _boundary(w, "ok", [])
    w.settings.revision = w.planner.current.settings_revision = 5
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1  # proof recorded on the next run, then exactly one send
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "exception", "cancel"])
async def test_started_call_is_ambiguous_blocks_and_is_never_retried(monkeypatch, failure):
    w = setup(monkeypatch)
    seen = []

    async def call(request):
        seen.append(w.ledger.value["attempt"]["dispatch_class"])  # the durable marker is already there
        if failure == "timeout":
            raise TimeoutError
        if failure == "exception":
            raise RuntimeError("boom")
        await asyncio.sleep(3600)
    w.point.call.side_effect = call
    w.worker.start()
    await asyncio.sleep(0)
    for _ in range(50):
        if w.point.call.await_count:
            break
        await asyncio.sleep(0)
    if failure == "cancel":
        w.worker._task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await w.worker._task
    else:
        await drain(w.worker)
    assert seen == ["wire_intent"]
    assert w.ledger.value["uncertain"] is True and w.ledger.value["attempt"]["state"] == "uncertain"
    assert morek_schedule.upload_outcome_class(w.ledger.value) == {
        "class": "ambiguous", "proof": None, "basis": None, "reason": "wire_may_have_started"}
    w.worker.close()
    again = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    w.settings.revision = w.planner.current.settings_revision = 5
    again.start()
    await drain(again)
    assert again.reason == "upload_uncertain" and w.point.call.await_count == 1
    again.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant,released", [("pre_wire", True), ("wire_intent", False), ("legacy", False)])
async def test_restart_finds_record_marker(monkeypatch, variant, released):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    w.worker.close()
    assert w.point.call.await_count == 1
    if variant == "legacy":
        del w.ledger.value["attempt"]["dispatch_class"]
    else:
        w.ledger.value["attempt"]["dispatch_class"] = variant  # a crash before / after the intent write
    w.hass.data.pop("spotnav_morek_sending", None)
    w.point.call.side_effect = None
    w.settings.revision = w.planner.current.settings_revision = 5
    again = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    again.start()
    await drain(again)
    if released:
        assert w.point.call.await_count == 2 and again.reason == "upload_accepted_unverified"
        assert w.ledger.value["attempt"]["id"] != w.ledger.writes[0]["attempt"]["id"]
    else:
        assert w.point.call.await_count == 1 and again.reason == "upload_uncertain"
        assert w.ledger.value["uncertain"] is True
    again.close()


@pytest.mark.asyncio
async def test_in_flight_or_removal_doubt_never_releases(monkeypatch):
    record = {"uncertain": True, "attempt": {"id": "a", "state": "uncertain", "dispatch_class": "pre_wire"}}
    assert morek_schedule.upload_outcome_class(record)["class"] == "not_sent_provable"
    assert morek_schedule.upload_outcome_class(record, in_flight=True)["class"] == "ambiguous"
    assert morek_schedule.upload_outcome_class({**record, "removal": {"state": "uncertain"}})["class"] == "ambiguous"
    assert morek_schedule.upload_outcome_class({"uncertain": True, "attempt": None})["class"] == "ambiguous"
    assert morek_schedule.upload_outcome_class(None)["class"] == "none"
    assert morek_schedule.upload_outcome_class({"uncertain": False, "attempt": {"state": "rejected"}})["class"] == "resolved"


def test_not_sent_proof_drops_repair_budget_entry_only_for_that_attempt():
    key = morek_schedule._REPAIR_LIST_KEY
    record = {"uncertain": True, "attempt": {"id": "b", "state": "uncertain", "dispatch_class": "pre_wire"},
              key: [{"attempt_id": "a"}, {"attempt_id": "b"}]}
    morek_schedule._mark_not_sent(record, "b", "validation_before_dispatch")
    assert record[key] == [{"attempt_id": "a"}] and record["uncertain"] is False
    assert "rejections" not in record["attempt"]


@pytest.mark.asyncio
async def test_stop_during_wire_intent_write_never_sends_and_is_not_sent(monkeypatch):
    w = setup(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.ledger.write

    async def blocked(value):
        if (value.get("attempt") or {}).get("dispatch_class") == "wire_intent" and not entered.is_set():
            entered.set()
            await release.wait()
        await original(value)
    monkeypatch.setattr(w.ledger, "write", blocked)
    w.worker.start()
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        await drain(w.worker)
    w.point.call.assert_not_awaited()
    attempt = w.ledger.value["attempt"]
    assert w.ledger.value["uncertain"] is False
    assert (attempt["dispatch_class"], attempt["not_sent_proof"]) == ("not_sent", "validation_before_dispatch")
    w.worker.close()


@pytest.mark.asyncio
async def test_intent_marker_write_failure_stays_blocking_without_a_call(monkeypatch):
    w = setup(monkeypatch)
    original = w.ledger.write

    poisoned = {"on": False}

    async def write(value):  # like the real ledger: a failed write poisons every later one
        if poisoned["on"] or (value.get("attempt") or {}).get("dispatch_class") == "wire_intent":
            poisoned["on"] = True
            raise OSError("disk")
        await original(value)
    monkeypatch.setattr(w.ledger, "write", write)
    w.worker.start()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    assert w.ledger.value["uncertain"] is True  # storage failure: no release is recorded
    w.worker.close()


def test_decision_event_and_blocker_label_not_sent_without_claiming_a_send():
    from datetime import datetime, timezone
    event = morek_schedule.decision_event(now=datetime(2026, 11, 18, tzinfo=timezone.utc), kinds={"publication"},
                                          last_trigger="publication", reason="upload_not_sent", inputs={},
                                          evidence="unknown", continuity=None, dispatched=False)
    assert (event["action"], event["stages"]["intent"], event["stages"]["ack"]) == ("blocked", "none", "not_sent")
    assert event["blocker"]["action"] == "wait_for_next_automatic_attempt"


# --- Stage 19.1 follow-up: the proof is recovered through the REAL admission gate, not a simulated one ----------

async def _cancel_before_wire(w):
    """Real admission + worker; cancel the run inside the pre-wire durable check, leaving a latched pre_wire record."""
    reached = asyncio.Event()
    original = w.admission.async_owned_boundary_current

    async def hang(*args):
        reached.set()
        await asyncio.sleep(3600)
    w.admission.async_owned_boundary_current = hang
    w.worker.start()
    await asyncio.wait_for(reached.wait(), 5)
    w.worker._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await w.worker._task
    w.admission.async_owned_boundary_current = original
    record = await w.ledger.read()
    assert record["uncertain"] is True and record["attempt"]["dispatch_class"] == "pre_wire"
    w.point.call.assert_not_awaited()
    return record


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_recovers_cancelled_pre_wire_attempt_then_guarded_send(monkeypatch, tmp_path):
    from .test_morek_worker import real_admission_planner_worker
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    before = await _cancel_before_wire(w)
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason  # released at admission, then ONE guarded send
    after = await w.ledger.read()
    assert w.worker.reason == "upload_accepted_unverified" and after["uncertain"] is False
    assert after["attempt"]["id"] != before["attempt"]["id"] and after["attempt"]["dispatch_class"] == "resolved"
    w.worker.close()


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_recovers_after_restart_through_reconfirmation_then_sends(monkeypatch, tmp_path):
    from custom_components.spotnav.execution import command_admission, execution_ownership, morek_outcomes
    from .test_morek_worker import real_admission_planner_worker
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    before = await _cancel_before_wire(w)
    w.worker.close()
    ledger = await w.ledger.read()
    ledger["migration_recovery_proof"] = {"version": 1, "migration_id": "a" * 32, "station_id": w.identity["resolved_id"],
                                           "connector_id": 1}  # the durable handover proof (not a send record)
    await w.ledger.write(ledger)
    for key in (command_admission._DATA_KEY, execution_ownership._DATA_KEY, morek_outcomes._DATA_KEY,
                "spotnav_morek_sending"):
        w.hass.data.pop(key, None)  # process restart: tickets, poison flags and in-flight markers are gone
    restarted = command_admission.command_admission(w.hass)
    assert restarted is not w.admission and not restarted._completion_tickets
    identity = lambda: w.identity  # noqa: E731
    revision = restarted.reserve_lifecycle_barrier("test", identity)
    operation = AsyncMock()
    assert not (await restarted.async_execute("test", "owned_profile", identity, operation)).allowed  # no ticket yet
    operation.assert_not_awaited()
    assert await restarted.async_recover_after_restart("test", identity, revision, 0) == "automatic_recovery_ready"
    assert (await morek_outcomes.outcomes_for(w.hass).read())["uncertain"] is False  # released read-side, no send
    w.point.call.assert_not_awaited()
    assert "test" not in restarted._lifecycle_barriers  # reconfirmation released the restart barrier itself
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    final = await morek_outcomes.outcomes_for(w.hass).read()
    assert final["attempt"]["id"] != before["attempt"]["id"] and final["attempt"]["dispatch_class"] == "resolved"
    w.worker.close()


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
@pytest.mark.parametrize("alteration", ["wire_intent", "legacy", "removal_uncertain", "in_flight", "schedule_lock",
                                        "person_stop", "other_entry", "no_attempt"])
async def test_real_admission_never_releases_unprovable_or_concurrent_records(monkeypatch, tmp_path, alteration):
    from .test_morek_worker import real_admission_planner_worker
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    record = await _cancel_before_wire(w)
    record = {**record, "attempt": dict(record["attempt"])}
    if alteration == "wire_intent":
        record["attempt"]["dispatch_class"] = "wire_intent"
    elif alteration == "legacy":
        del record["attempt"]["dispatch_class"]
    elif alteration == "removal_uncertain":
        record["removal"] = {"state": "uncertain"}
    elif alteration == "other_entry":
        record["entry_id"] = "someone-else"
    elif alteration == "no_attempt":
        record["attempt"] = None
    await w.ledger.write(record)
    identity = lambda: w.identity  # noqa: E731
    operation = AsyncMock()
    lock = w.hass.data[morek_schedule._DATA_KEY]["test"][2]
    if alteration == "in_flight":
        w.hass.data["spotnav_morek_sending"] = {"test": "attempt-in-flight"}
    if alteration == "schedule_lock":
        await lock.acquire()
    try:
        if alteration == "person_stop":
            with w.admission.person_stop_reservation("test", identity):
                result = await w.admission.async_execute("test", "owned_profile", identity, operation)
        else:
            result = await w.admission.async_execute("test", "owned_profile", identity, operation)
    finally:
        if alteration == "schedule_lock":
            lock.release()
    assert not result.allowed
    operation.assert_not_awaited()
    w.point.call.assert_not_awaited()
    assert await w.ledger.read() == record  # nothing was rewritten
    w.worker.close()


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_release_loses_to_a_record_changed_between_proof_and_write(monkeypatch, tmp_path):
    from .test_morek_worker import real_admission_planner_worker
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    await _cancel_before_wire(w)
    real_read, reads = w.ledger.read, []

    async def read():
        value = await real_read()
        reads.append(1)
        if len(reads) == 2:  # the release's own re-read: another writer replaced the attempt in between
            value["attempt"] = {**value["attempt"], "id": "someone-else"}
            await w.ledger.write(value)
        return value
    monkeypatch.setattr(w.ledger, "read", read)
    operation = AsyncMock()
    result = await w.admission.async_execute("test", "owned_profile", lambda: w.identity, operation)
    assert not result.allowed and result.reason == "profile_outcome_unavailable"
    operation.assert_not_awaited()
    monkeypatch.setattr(w.ledger, "read", real_read)
    final = await real_read()
    assert final["attempt"]["id"] == "someone-else" and final["uncertain"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_upload_not_sent_has_a_bounded_automatic_reevaluation(monkeypatch):
    assert "upload_not_sent" in morek_schedule.TRANSIENT_BLOCKERS
    w = setup(monkeypatch)
    _boundary(w, "refuse", [])
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_not_sent" and w.worker._blocker_timer is not None
    assert w.worker.blocker_retry["code"] == "upload_not_sent" and w.worker.blocker_retry["exhausted"] is False
    _boundary(w, "ok", [])
    w.worker.trigger(kind="recovery")  # what the timer fires
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_accepted_unverified"
    assert w.worker.blocker_retry is None and w.worker._blocker_timer is None
    w.worker.close()
