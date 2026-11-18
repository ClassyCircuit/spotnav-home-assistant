"""Stage 19.2 + 19.9a: convergence after an ambiguous upload, and an actionable Resume while it is unknown.

Real worker, real send path (`_send_profile_shared`), real connector lock/generation; HA, OCPP and (in the first group)
admission are mocked boundaries. The last group uses the REAL `CommandAdmission`/ownership/ledger stores. Nothing
here proves charger behavior: no ordering, replacement or late-response semantics were observed, and a mocked ACK or
readback is never physical charging."""

import copy
from datetime import timedelta, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_worker
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_worker import IDENTITY, NOW, drain, setup

OLD = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()


def _intent(kind="pause_until_resumed", ident="p1"):
    return {"version": 1, "type": kind, "id": ident, "station_id": IDENTITY["resolved_id"], "connector_id": 1}


def _pending(pause_id="p1", ident="r" * 32):
    return {"version": 1, "id": ident, "pause_id": pause_id, "station_id": IDENTITY["resolved_id"],
            "connector_id": 1, "at": OLD}


def _legacy(*, marker=None, intent=_intent(), **extra):
    """The reported record: an old upload of unknown outcome (no 19.1 marker) plus a Pause."""
    attempt = {"id": "o" * 32, "fingerprint": "old", "at": OLD, "state": "uncertain", "source": "worker",
               "pause_id": "p1"}
    if marker:
        attempt["dispatch_class"] = marker
    return {"schema": 1, "entry_id": "charger", "uncertain": True, "attempt": attempt, "acknowledged": None,
            "desired": None, "verified": None, "removal": None, "schedule_pause": intent, **extra}


def _wire(w, index=-1):
    return w.point.call.await_args_list[index].args[0].payload["cs_charging_profiles"]


def _limits(w, index=-1):
    return [(p["startPeriod"], p["limit"]) for p in _wire(w, index)["chargingSchedule"]["chargingSchedulePeriod"]]


def _owner(monkeypatch, w):
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store",
                        lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))


async def _restart(monkeypatch, old):
    old.worker.close()
    again = setup(monkeypatch)
    again.ledger.value = copy.deepcopy(old.ledger.value)
    return again


# ---------------------------------------------------------------------------------- the reported legacy scenario

@pytest.mark.asyncio
async def test_legacy_unknown_plus_pause_resume_sends_a_fresh_schedule_once_and_keeps_history(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(pending_resume=_pending())
    w.worker.start()
    await drain(w.worker)
    # exactly one guarded wire call: a NEW absolute schedule on the one profile id
    assert w.point.call.await_count == 1, w.worker.reason
    profile = _wire(w)
    assert profile["chargingProfileId"] == morek_schedule.PROFILE_ID == 42001
    assert profile["chargingSchedule"]["chargingRateUnit"] == "A" and _limits(w)[-1][1] == 0
    record = w.ledger.value
    assert record["uncertain"] is False and record["attempt"]["state"] == "accepted"
    assert record["attempt"]["id"] != "o" * 32 and record["attempt"]["replaces"] == "o" * 32
    assert record["attempt"]["resolve"] is True and record["attempt"]["dispatch_class"] == "resolved"
    # the old outcome stays historically unknown: not accepted, not failed, not sent
    history = record["unknown_history"]
    assert [(h["attempt_id"], h["outcome"], h["dispatch_class"]) for h in history] == [
        ("o" * 32, "unknown", "legacy_unclassified")]
    assert history[0]["superseded_by"] == record["attempt"]["id"] and "profile" not in history[0]
    # the person's Resume became the current intent in the same durable write; the request is consumed
    assert record["schedule_pause"]["type"] == "resume_requested" and record["schedule_pause"]["id"] == "r" * 32
    assert "pending_resume" not in record and record["resume_authorized"]["id"] == "r" * 32
    assert record["attempt"]["pause_id"] == "r" * 32
    # ACK, readback and charging stay separate; the ordering risk is named, never cleared
    assert record["supersession"]["state"] == "replacement_acknowledged"
    assert record["supersession"]["risk"] == "late_old_frame_not_excluded"
    assert record["verified"] is None and "recovery" not in record
    status = morek_schedule.unknown_recovery_status(record, datetime.now(timezone.utc), w.worker)
    assert (status["state"], status["ordering"], status["physical_charging"], status["old_outcome"]) == (
        "replacement_acknowledged", "unverified", "unknown", "unknown")
    # equal repeats: nothing more is sent
    for _ in range(3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_with_a_pending_resume_recovers_without_another_click(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    w.worker._available = lambda: False  # noqa: SLF001 - the link is down first
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "charger_unavailable"
    assert "pending_resume" in w.ledger.value and w.ledger.value["uncertain"] is True  # nothing lost, nothing sent
    again = await _restart(monkeypatch, w)  # process restart: only the durable record survives
    again.worker.start()
    await drain(again.worker)
    assert again.point.call.await_count == 1 and again.ledger.value["uncertain"] is False
    assert again.ledger.value["unknown_history"][0]["dispatch_class"] == "wire_intent"
    again.worker.close()


@pytest.mark.asyncio
async def test_resume_click_on_an_unknown_record_is_durable_pending_and_the_pause_stays_until_recovery(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy()
    _owner(monkeypatch, w)
    w.worker._suspended = True  # recovery cannot act yet (e.g. initialization): the Pause stays in force
    result = await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    record = w.ledger.value
    assert result["pending"] is True and record["schedule_pause"]["type"] == "pause_until_resumed"
    assert record["pending_resume"]["pause_id"] == "p1" and record["uncertain"] is True
    assert w.point.call.await_count == 0
    status = morek_schedule._owned_pause_status(record, {}, False, w.worker)  # noqa: SLF001
    assert status["request"] == "resume_pending" and status["resume_pending"] is True
    assert status["intent"] == "pause_until_resumed" and status["resume_recoverable"] is False
    # a second click is idempotent (same request id), then recovery acts once
    again = await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    assert again["id"] == result["id"]
    w.worker._suspended = False  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["schedule_pause"]["type"] == "resume_requested"
    w.worker.close()


@pytest.mark.asyncio
async def test_resume_stays_refused_for_a_removal_in_doubt_or_no_pause(monkeypatch):
    w = setup(monkeypatch)
    _owner(monkeypatch, w)
    w.ledger.value = _legacy(removal={"state": "uncertain"})
    with pytest.raises(morek_schedule.ScheduleRefused) as error:
        await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    assert error.value.code == "resume_unavailable" and "pending_resume" not in w.ledger.value
    w.ledger.value = _legacy(intent=None)
    with pytest.raises(morek_schedule.ScheduleRefused):
        await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    assert w.point.call.await_count == 0
    w.worker.close()


# ---------------------------------------------------------------------------------- Stop / Pause races

@pytest.mark.asyncio
async def test_a_later_stop_deletes_the_pending_resume_durably_and_wins(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(pending_resume=_pending())
    _owner(monkeypatch, w)
    w.worker._suspended = True  # noqa: SLF001
    await morek_schedule.async_record_owned_pause(w.hass, "charger")  # a Stop/Pause with the intent unchanged
    assert "pending_resume" not in w.ledger.value and w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert morek_schedule.valid_pending_resume(w.ledger.value) is None
    w.worker._suspended = False  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    # the Pause's own hold is what converges: a 0 A schedule, never a plan, and no Resume
    assert w.point.call.await_count == 1 and {limit for _, limit in _limits(w)} == {0}
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.ledger.value["attempt"]["pause_id"] == "p1" and "resume_authorized" not in w.ledger.value
    w.worker.close()


@pytest.mark.asyncio
async def test_person_stop_reserved_blocks_recovery_and_nothing_is_sent_or_consumed(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(pending_resume=_pending())
    connector = physical_connector(w.identity)
    w.admission._person_stops[connector] = True  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    record = w.ledger.value
    assert "pending_resume" in record and "unknown_history" not in record and "recovery" not in record
    assert record["uncertain"] is True and record["schedule_pause"]["type"] == "pause_until_resumed"
    w.admission._person_stops.pop(connector)  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_arriving_during_the_prewire_write_never_reaches_the_wire(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(pending_resume=_pending())
    connector = physical_connector(w.identity)
    real_write, state = w.ledger.write, {"done": False}

    async def write(value):
        await real_write(value)
        if not state["done"] and value.get("attempt", {}).get("resolve"):
            state["done"] = True
            w.admission._generations[connector] = w.admission._generations.get(connector, 0) + 1  # noqa: SLF001
    w.ledger.write = write
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0, "a Stop that won during the durable write must stop the send"
    record = w.ledger.value
    # nothing reached the wire and no ACK exists, but this replacement proves nothing about the ORIGINAL ambiguous
    # upload: that record is restored whole (never a false settled state), with its Resume still pending and retryable
    assert record["uncertain"] is True and record["acknowledged"] is None
    assert record["attempt"]["id"] == "o" * 32 and record["attempt"]["state"] == "uncertain"
    assert "resolve" not in record["attempt"] and "resolve_prior" not in record["attempt"]
    assert "supersession" not in record and "unknown_history" not in record and "recovery" not in record
    assert record["pending_resume"]["id"] == "r" * 32 and record["schedule_pause"]["type"] == "pause_until_resumed"
    assert "resume_authorized" not in record
    assert morek_schedule.recoverable_ambiguous(record) and morek_schedule.resume_recoverable(record)
    # the Stop's own record then replaces the intent: the next run converges the Stop, never the old Resume
    _owner(monkeypatch, w)
    w.ledger.write = real_write
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and {limit for _, limit in _limits(w)} == {0}
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    w.worker.close()


@pytest.mark.asyncio
async def test_a_resume_click_racing_a_stop_deletes_its_own_pending_request(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy()
    _owner(monkeypatch, w)
    connector = physical_connector(w.identity)
    real_write = w.ledger.write

    async def write(value):
        await real_write(value)
        if value.get("pending_resume"):
            w.admission._person_stops[connector] = True  # noqa: SLF001 - the Stop reserves while the write lands
    w.ledger.write = write
    with pytest.raises(morek_schedule.ScheduleRefused) as error:
        await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    assert error.value.code == "resume_interrupted"
    assert "pending_resume" not in w.ledger.value and w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    w.worker.close()


# ---------------------------------------------------------------------------------- convergence without a click

@pytest.mark.asyncio
async def test_unknown_upload_waits_then_converges_once_and_is_paced_across_failures(monkeypatch):
    w = setup(monkeypatch)
    recent = _legacy(marker="wire_intent", intent=None)
    recent["attempt"].update(at=datetime.now(timezone.utc).isoformat(), pause_id=None)
    w.ledger.value = recent
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "upload_uncertain"  # the first wait
    assert w.worker.recovery_retry is not None and w.worker._recovery_timer is not None  # noqa: SLF001 - a wake exists
    assert morek_schedule.unknown_recovery_status(w.ledger.value, datetime.now(timezone.utc))["state"] == "waiting"
    w.ledger.value["attempt"]["at"] = OLD  # the wait has passed
    w.point.call.side_effect = TimeoutError  # the replacement itself gets no answer
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_uncertain"
    record = w.ledger.value
    assert record["uncertain"] is True and record["recovery"]["attempts"] == 1
    at = datetime.fromisoformat(record["recovery"]["next_at"])
    last = datetime.fromisoformat(record["recovery"]["last_at"])
    assert int((at - last).total_seconds()) == morek_schedule.RECOVERY_DELAYS[1] == 300  # 2 min, then 5 min
    for _ in range(4):  # a burst of triggers: the durable pace holds, nothing is re-sent
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 1
    again = await _restart(monkeypatch, w)  # the pace survives a restart
    again.point.call.side_effect = TimeoutError
    again.worker.start()
    await drain(again.worker)
    assert again.point.call.await_count == 0
    again.ledger.value["recovery"]["next_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1 and again.ledger.value["recovery"]["attempts"] == 2
    assert int((datetime.fromisoformat(again.ledger.value["recovery"]["next_at"])
                - datetime.fromisoformat(again.ledger.value["recovery"]["last_at"])).total_seconds()) == 900
    assert [h["outcome"] for h in again.ledger.value["unknown_history"]] == ["unknown", "unknown"]
    # finally an ACK ends the wait (not the risk)
    again.point.call.side_effect = None
    again.point.call.return_value = SimpleNamespace(status="Accepted")
    again.ledger.value["recovery"]["next_at"] = OLD
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    final = again.ledger.value
    assert final["uncertain"] is False and "recovery" not in final
    assert final["supersession"]["state"] == "replacement_acknowledged"
    assert final["supersession"]["risk"] == "late_old_frame_not_excluded"
    assert len(final["unknown_history"]) == 3 and len(final["unknown_history"]) <= morek_schedule.UNKNOWN_HISTORY_CAP
    again.worker.close()


@pytest.mark.asyncio
async def test_recovery_pace_ceiling_and_bounded_history(monkeypatch):
    assert morek_schedule.RECOVERY_DELAYS == (120, 300, 900, 1800, 3600, 14400)
    assert list(morek_schedule.RECOVERY_DELAYS) == sorted(morek_schedule.RECOVERY_DELAYS)
    assert morek_schedule._recovery_delay(99) == 14400  # noqa: SLF001
    record = {"attempt": {"id": "a", "at": OLD}}
    for index in range(10):
        morek_schedule._archive_unknown(record, {"id": f"id{index}"}, "n", OLD)  # noqa: SLF001
    assert len(record["unknown_history"]) == morek_schedule.UNKNOWN_HISTORY_CAP
    assert record["unknown_history"][-1]["attempt_id"] == "id9" and record["supersession"]["since"] == OLD


@pytest.mark.asyncio
async def test_a_rejected_replacement_is_a_definite_answer_and_uses_the_rejection_pace(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(marker="wire_intent", intent=None, pending_resume=None)
    w.ledger.value.pop("pending_resume")
    w.ledger.value["attempt"]["pause_id"] = None
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    record = w.ledger.value
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_rejected"
    assert record["uncertain"] is False and record["attempt"]["state"] == "rejected"
    assert record["acknowledged"] is None and "recovery" not in record
    assert record["unknown_history"][0]["outcome"] == "unknown"  # the old attempt is not relabelled by the rejection
    assert record["supersession"]["state"] == "pending"  # no ACK: the standing risk record stays pending
    for _ in range(3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 1  # paced by the existing rejection delays, no hammering
    w.worker.close()


@pytest.mark.asyncio
async def test_offline_link_defers_recovery_without_a_burst_and_reconnect_sends_once(monkeypatch):
    online = {"on": False}
    w = setup(monkeypatch)
    w.ledger.value = _legacy(marker="wire_intent", intent=None)
    w.ledger.value["attempt"]["pause_id"] = None
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    for _ in range(4):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "charger_unavailable"
    assert w.ledger.value["uncertain"] is True and "unknown_history" not in w.ledger.value
    online["on"] = True
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["uncertain"] is False
    for _ in range(3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_resolve_carries_the_active_window_with_no_zero_amp_gap(monkeypatch):
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    first = _limits(w)
    assert first[0] == (0, 16)
    # a later write of unknown outcome (e.g. a timed-out equal-purpose upload) leaves the record ambiguous
    record = w.ledger.value
    record["uncertain"] = True
    record["attempt"].update(state="uncertain", dispatch_class="wire_intent", at=OLD, id="u" * 32)
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 2, w.worker.reason
    second = _limits(w)
    assert second[0] == (0, 16) and second[-1][1] == 0  # the allowed window continues; final 0 A only at its end
    assert all(limit == 16 for _, limit in second[:-1])
    assert w.ledger.value["uncertain"] is False and w.ledger.value["unknown_history"][0]["attempt_id"] == "u" * 32
    w.worker.close()


@pytest.mark.asyncio
async def test_not_provable_and_removal_cases_keep_their_existing_behavior(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _legacy(marker="wire_intent", intent=None, removal={"state": "uncertain"})
    w.ledger.value["attempt"]["pause_id"] = None
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "upload_uncertain"  # a removal in doubt never resolves
    assert not morek_schedule.recoverable_ambiguous(w.ledger.value)
    w.worker.close()
    # a manual (person-run) upload never resolves: only the worker's guarded run may
    assert morek_schedule.upload_outcome_class(_legacy(marker="pre_wire"))["class"] == "not_sent_provable"
    assert morek_schedule.recoverable_ambiguous(_legacy(marker="pre_wire")) is False  # 19.1 releases it instead


def test_status_vocabulary_never_claims_the_old_outcome_or_charging():
    record = _legacy(marker="wire_intent", pending_resume=_pending())
    now = datetime.now(timezone.utc)
    status = morek_schedule.unknown_recovery_status(record, now)
    assert status["ambiguous"] is True and status["resume_pending"] is True and status["old_outcome"] == "unknown"
    assert status["ordering"] == "unverified" and status["physical_charging"] == "unknown"
    assert status["state"] == "due"  # a person's Resume waives the first wait
    assert morek_schedule.unknown_recovery_status({"uncertain": False}, now)["state"] == "none"
    pause = morek_schedule._owned_pause_status(_legacy(), {}, False, None)  # noqa: SLF001
    assert pause["resume_recoverable"] is True and pause["resume_pending"] is False
    stopped = morek_schedule._owned_pause_status(_legacy(), {}, False, None, stop_pending=True)  # noqa: SLF001
    assert stopped["resume_recoverable"] is False and stopped["request"] == "stop_pending"
    assert morek_schedule.observation_entry("upload_uncertain", "t")["next"] == "automatic_recheck"


# ---------------------------------------------------------------------------------- REAL admission, ownership, ledger

async def _real_unknown(monkeypatch, tmp_path):
    from .test_morek_worker import real_admission_planner_worker
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)  # noqa: SLF001
    record = _legacy()
    record["entry_id"] = "test"
    await w.ledger.write(record)
    return w, world


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_legacy_unknown_pause_resume_after_restart_sends_without_another_click(monkeypatch, tmp_path):
    from custom_components.spotnav.execution import command_admission, execution_ownership, morek_outcomes
    w, world = await _real_unknown(monkeypatch, tmp_path)
    # Resume is accepted from the UI action path while the record is unknown (real admission, real ledger)
    await morek_schedule.async_record_owned_pause(w.hass, "test", resume=True)
    pending = (await w.ledger.read())["pending_resume"]
    assert pending["pause_id"] == "p1"
    w.worker.close()
    # HA restarts before anything is sent: tickets, in-flight markers and the barrier state are all process-local
    for key in (command_admission._DATA_KEY, execution_ownership._DATA_KEY, morek_outcomes._DATA_KEY,  # noqa: SLF001
                "spotnav_morek_sending"):
        w.hass.data.pop(key, None)
    restarted = command_admission.command_admission(w.hass)
    assert not restarted._completion_tickets  # noqa: SLF001
    identity = lambda: w.identity  # noqa: E731
    revision = restarted.reserve_lifecycle_barrier("test", identity)
    operation = AsyncMock()
    assert not (await restarted.async_execute("test", "owned_profile", identity, operation)).allowed  # no ticket yet
    # the durable pending Resume is the person's authority: restart recovery needs no dispatch evidence for it
    assert await restarted.async_recover_after_restart("test", identity, revision, 0) == "automatic_recovery_ready"
    assert "test" not in restarted._lifecycle_barriers  # noqa: SLF001
    w.point.call.assert_not_awaited()  # authority alone sends nothing
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: restarted)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: restarted._store)  # noqa: SLF001
    monkeypatch.setattr(morek_worker, "command_admission", lambda _: restarted)
    worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    worker.start()
    await drain(worker)
    assert w.point.call.await_count == 1, worker.reason
    final = await morek_outcomes.outcomes_for(w.hass).read()
    assert final["uncertain"] is False and final["attempt"]["dispatch_class"] == "resolved"
    assert final["attempt"]["replaces"] == "o" * 32 and final["unknown_history"][0]["outcome"] == "unknown"
    assert final["schedule_pause"]["type"] == "resume_requested" and "pending_resume" not in final
    assert _wire(w)["chargingProfileId"] == 42001 and _limits(w)[-1][1] == 0
    assert final["supersession"]["risk"] == "late_old_frame_not_excluded"
    worker.close()


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_click_with_no_ticket_regains_authority_and_a_later_stop_still_wins(monkeypatch, tmp_path):
    from custom_components.spotnav.execution import command_admission
    w, world = await _real_unknown(monkeypatch, tmp_path)
    w.admission._completion_tickets.clear()  # noqa: SLF001 - the process lost its send authority
    w.admission.reserve_lifecycle_barrier("test", lambda: w.identity)
    # without a Resume the unsettled record gives the worker no authority: nothing is sent
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    # the click records a durable request and regains authority (owner, identity, generation and Stop re-verified)
    await morek_schedule.async_record_owned_pause(w.hass, "test", resume=True)
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    assert (await w.ledger.read())["attempt"]["dispatch_class"] == "resolved"
    # a person Stop then wins over everything: the hold is what is written, never a plan, and the Resume is gone
    await morek_schedule.async_record_owned_pause(w.hass, "test")
    await drain(w.worker)
    record = await w.ledger.read()
    assert record["schedule_pause"]["type"] == "pause_until_resumed"
    assert "resume_authorized" not in record or record["resume_authorized"]["id"] != record["schedule_pause"]["id"]
    assert {limit for _, limit in _limits(w)} == {0}  # the hold, never a plan
    w.worker.close()
    assert command_admission.command_admission(w.hass) is w.admission


@pytest.mark.allow_loop_io  # the real ledger/ownership stores read their files inline under FakeHass
@pytest.mark.asyncio
async def test_real_admission_ambiguous_without_resume_resolves_in_process_and_a_stop_blocks_it(monkeypatch, tmp_path):
    w, _ = await _real_unknown(monkeypatch, tmp_path)
    record = await w.ledger.read()
    record.pop("schedule_pause")
    record["attempt"].update(dispatch_class="wire_intent", pause_id=None)
    await w.ledger.write(record)
    connector = physical_connector(w.identity)
    w.admission._person_stops[connector] = True  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    w.admission._person_stops.pop(connector)  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    final = await w.ledger.read()
    assert final["uncertain"] is False and final["unknown_history"][0]["dispatch_class"] == "wire_intent"
    w.worker.close()
