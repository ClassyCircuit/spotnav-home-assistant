"""Stage 19.2 review corrections: a refused reassert is retried (paced, persisted), and the next transition look is re-derived
from the durable ledger at startup/reconnect, with a bounded follow-up for closely spaced transitions.

Real worker, real checker, real send path, real fetch/compare; OCPP, HA timers, storage and (simulated) admission are the
usual mocked boundaries. The retry is a paced read-only look followed by the existing confirmed reassert, never a blind
resend. Nothing here proves firmware ordering, replacement semantics or physical charging.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_192_retry_rearm.py
"""

import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_checker
from . import test_stage_153_schedule_check as t153
from .test_stage_192_late_frame import Late, replaced, stop


def watches(late):
    fire = late.rig.checker._async_transition_fire  # noqa: SLF001
    return [t for t in late.rig.live() if t.action == fire]


def checks(late):
    fire = late.rig.checker._async_transition_fire  # noqa: SLF001
    return [t for t in late.rig.live() if t.action != fire]


async def fire_check(late):
    timer = checks(late)[-1]
    timer.cancelled = True
    timer.action(t153.utcnow())
    await late.settle()


async def fire_watch(late):
    timer = watches(late)[-1]
    late.skew.advance(late.rig, timer.delay + 1)
    await late.fire(timer)
    await fire_check(late)  # the settle timer of the requested check -> read #1


async def confirm(late):
    late.skew.advance(late.rig, 31)
    await fire_check(late)
    await late.settle()


def now(late):
    return datetime.now(timezone.utc) + late.skew.offset


def close(late):
    late.w.worker.close()
    late.rig.checker.close()


async def refused_reassert(monkeypatch):
    """The reported gap: the late old frame is found, the guarded reassert is sent and the charger REFUSES it."""
    late = await replaced(monkeypatch)
    late.differ = True
    late.set_status = "Rejected"
    await fire_watch(late)
    assert len(late.sets) == 1  # one differing read never sends
    await confirm(late)
    assert len(late.sets) == 2 and late.w.worker.reason == "upload_rejected", late.w.worker.reason
    return late


# ------------------------------------------------------------------------------ rejection -> paced retry -> success

@pytest.mark.asyncio
async def test_rejected_reassert_is_retried_after_its_persisted_pace_and_converges(monkeypatch):
    late = await refused_reassert(monkeypatch)
    record = late.ledger
    first_ack = record["acknowledged"]["id"]
    assert record["attempt"]["state"] == "rejected" and record["uncertain"] is False
    assert morek_schedule.rejected_reassert_of(record) == first_ack  # the acknowledgement is still in force
    state = record["supersession"]["reassert"]
    due = datetime.fromisoformat(state["next_at"])
    # the retry look is armed at the persisted pace (not earlier), and the worker's own blind retry is not
    await late.settle()
    armed = datetime.fromisoformat(late.rig.checker.status()["next_transition_check_at"])
    assert due <= armed <= due + timedelta(seconds=5)
    assert late.w.worker._retry_timer is None  # noqa: SLF001
    status = morek_schedule.recovery_status(record, now(late))
    assert status["pace"] == "reassert" and status["exhausted"] is False and status["retries_left"] is None
    # a burst of ordinary triggers and a confirmed request before the pace is due send nothing and consume nothing
    for _ in range(3):
        late.w.worker.trigger(kind="recovery")
        await late.settle()
    late.w.worker.request_repair({"attempt_id": first_ack, "connection_id": 1, "readback_at": now(late).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    assert len(late.sets) == 2 and late.w.worker.reason == "repair_spacing"
    assert late.ledger["supersession"]["reassert"] == state
    # at the pace the charger now accepts: one read, one confirmation, exactly one more reassert
    late.set_status = "Accepted"
    reads = late.reads
    await fire_watch(late)
    assert late.reads == reads + 1 and len(late.sets) == 2  # still only a look
    await confirm(late)
    assert len(late.sets) == 3 and late.sets[2]["chargingProfileId"] == morek_schedule.PROFILE_ID
    assert [p["limit"] for p in late.sets[2]["chargingSchedule"]["chargingSchedulePeriod"]][-1] == 0
    record = late.ledger
    assert record["attempt"]["state"] == "accepted" and record["acknowledged"]["id"] != first_ack
    assert record["supersession"]["reassert"]["attempts"] == 2 and morek_schedule.rejected_reassert_of(record) is None
    assert record["supersession"]["risk"] == "late_old_frame_not_excluded" and record["verified"] is None
    assert "repair_attempts" not in record and "repair_escalation" not in record
    assert len([k for k in late.rig.kinds if k == "ClearChargingProfile"]) == 0
    close(late)


@pytest.mark.asyncio
async def test_repeated_refusals_follow_the_ladder_one_look_per_pace_and_no_polling(monkeypatch):
    late = await refused_reassert(monkeypatch)
    sent = [len(late.sets)]
    gaps = []
    for _ in range(4):
        state = late.ledger["supersession"]["reassert"]
        gaps.append((datetime.fromisoformat(state["next_at"]) - datetime.fromisoformat(state["last_at"])).total_seconds())
        await late.settle()
        await fire_watch(late)
        await confirm(late)
        sent.append(len(late.sets))
    assert gaps == pytest.approx(list(morek_schedule.REASSERT_DELAYS[:4]), abs=1)
    assert sent == [2, 3, 4, 5, 6]  # exactly one send per due pace
    assert late.ledger["supersession"]["reassert"]["attempts"] == 5
    # one watch only (the earlier of the next planned change and the retry due at the persisted pace); settling and
    # triggers add no read and no send
    await late.settle()
    assert len(watches(late)) == 1
    reads = late.reads
    for _ in range(3):
        late.w.worker.trigger(kind="recovery")
        await late.settle()
    assert late.reads == reads and len(late.sets) == 6
    close(late)


@pytest.mark.asyncio
async def test_a_look_that_cannot_conclude_waits_for_the_next_trigger_and_never_polls(monkeypatch):
    late = await refused_reassert(monkeypatch)
    late.set_status = "Accepted"
    late.offline = True  # reads fail: the look is Unknown, nothing may be sent
    await late.settle()
    await fire_watch(late)
    await late.settle()
    assert len(late.sets) == 2
    # the same pace state is not looked at again by a timer of its own
    assert [t for t in watches(late) if t.delay < 1000] == []
    # the ordinary reconnect trigger re-derives it from the ledger; with the charger back one read + confirmation sends
    late.offline = False
    late.rig.checker.request("link_up")
    await late.settle()
    await fire_check(late)
    await confirm(late)
    assert len(late.sets) == 3 and late.ledger["supersession"]["reassert"]["attempts"] == 2
    close(late)


# ------------------------------------------------------------------------------ restart with no new events

@pytest.mark.asyncio
async def test_restart_rearms_the_retry_from_the_durable_ledger_with_no_new_event(monkeypatch):
    late = await refused_reassert(monkeypatch)
    durable = copy.deepcopy(late.ledger)
    due = datetime.fromisoformat(durable["supersession"]["reassert"]["next_at"])
    close(late)
    again = Late(monkeypatch, record=durable, start=False)
    again.skew.advance(again.rig, (due - now(again)).total_seconds() - 40)  # restart a little BEFORE the pace is due
    again.charger = copy.deepcopy(durable["acknowledged"]["profile"])
    again.differ = True  # the charger still holds the late frame
    again.set_status = "Accepted"
    # only the startup arming (what `__init__` does); no link edge, no check request, no worker trigger
    again.rig.checker.request_transition_watch()
    await again.settle()
    assert checks(again) == [] and again.reads == 0 and again.sets == []
    status = again.rig.checker.status()
    armed = datetime.fromisoformat(status["next_transition_check_at"])
    assert due <= armed <= due + timedelta(seconds=5)  # never before the persisted pace
    await fire_watch(again)
    assert again.reads == 1 and again.sets == []
    await confirm(again)
    assert len(again.sets) == 1 and again.ledger["supersession"]["reassert"]["attempts"] == 2
    assert again.w.ledger.writes  # the one send's own record-first writes only
    close(again)


@pytest.mark.asyncio
async def test_restart_with_a_correct_charger_sends_and_writes_nothing_and_does_not_poll(monkeypatch):
    late = await refused_reassert(monkeypatch)
    durable = copy.deepcopy(late.ledger)
    due = datetime.fromisoformat(durable["supersession"]["reassert"]["next_at"])
    close(late)
    again = Late(monkeypatch, record=durable, start=False)
    again.skew.advance(again.rig, (due - now(again)).total_seconds() + 5)
    again.charger = copy.deepcopy(durable["acknowledged"]["profile"])
    again.rig.checker.request_transition_watch()
    await again.settle()
    await fire_watch(again)
    assert again.rig.checker.status()["class"] == morek_schedule.CHECK_HEALTHY
    assert again.sets == [] and again.w.ledger.writes == []
    await again.settle()
    assert [t for t in watches(again) if t.delay < 1000] == []  # looked once for this pace state
    close(again)


@pytest.mark.asyncio
async def test_startup_and_reconnect_rearm_the_next_transition_without_a_prior_check_or_send(monkeypatch):
    late = await replaced(monkeypatch)
    durable = copy.deepcopy(late.ledger)
    close(late)
    # HA restart with the risk record on disk and nothing else happening
    again = Late(monkeypatch, record=durable, start=False)
    again.rig.checker.request_transition_watch()
    await again.settle()
    assert again.rig.checker.status()["next_transition_check_at"] is not None and again.reads == 0
    close(again)
    # offline -> online: the edge's own check request re-derives the watch even before that check has run
    offline = Late(monkeypatch, record=durable, start=False)
    offline.rig.monitor.state = "down"
    offline.rig.checker.note_link_down()
    offline.rig.monitor.state = "up"
    offline.rig.checker.request("link_up")
    await offline.settle()
    assert offline.rig.checker.status()["next_transition_check_at"] is not None  # armed before any read happened
    assert offline.reads == 0 and offline.sets == []
    close(offline)


# ------------------------------------------------------------------------------ adjacent transitions

async def adjacent(monkeypatch):
    late = Late(monkeypatch, start=False)
    real = datetime.now(timezone.utc)
    # window A ends 60 s before window B starts: a look after A's end falls inside B's start tolerance
    late.w.planner.current.proposal.shown_periods = (
        (real + timedelta(seconds=3600), real + timedelta(seconds=4200)),
        (real + timedelta(seconds=4260), real + timedelta(seconds=7200)))
    late.w.worker.start()
    await late.settle()
    assert len(late.sets) == 1 and late.ledger["supersession"]["state"] == "replacement_acknowledged"
    late.rig.data.update(verified=True, verification={"pending": False, "reason": "matched", "attempts": 1})
    late.w.hass.data.get(morek_schedule._VERIFY_KEY, {}).pop("charger", None)  # noqa: SLF001
    return late


@pytest.mark.asyncio
async def test_adjacent_transitions_get_a_followup_look_instead_of_being_skipped(monkeypatch):
    late = await adjacent(monkeypatch)
    await fire_watch(late)  # first change + settle: charger fine
    assert late.rig.checker.status()["class"] == morek_schedule.CHECK_HEALTHY
    late.differ = True  # the late old frame lands after window A ended
    assert late.sets and len(late.sets) == 1
    await late.settle()
    # the next watch is at A's end + settle, which lands 60 s after B's start: inconclusive by design
    await fire_watch(late)
    status = late.rig.checker.status()
    assert status["class"] == morek_schedule.CHECK_UNKNOWN and status["reason"] == "coverage_boundary_ambiguous"
    assert len(late.sets) == 1
    await late.settle()
    # without the follow-up the next look would be the plan's last change, hours away
    follow = datetime.fromisoformat(late.rig.checker.status()["next_transition_check_at"])
    assert timedelta(0) < follow - now(late) <= timedelta(seconds=morek_checker.TRANSITION_SETTLE_S + 5)
    await fire_watch(late)  # the follow-up look: now conclusive
    assert late.rig.checker.status()["class"] == morek_schedule.CHECK_DIFFERS
    await confirm(late)
    assert len(late.sets) == 2 and late.ledger["supersession"]["reassert"]["attempts"] == 1
    close(late)


@pytest.mark.asyncio
async def test_followups_are_bounded_when_the_look_stays_inconclusive(monkeypatch):
    late = await adjacent(monkeypatch)
    # a send's verification that never finishes keeps every look inconclusive
    late.w.hass.data.setdefault(morek_schedule._VERIFY_KEY, {})["charger"] = lambda: None  # noqa: SLF001
    fired = 0
    await late.settle()
    for _ in range(12):
        short = [t for t in watches(late) if t.delay < 1000]
        if not short:
            break
        timer = short[-1]
        late.skew.advance(late.rig, timer.delay + 1)
        await late.fire(timer)
        await fire_check(late) if checks(late) else None
        await late.settle()
        fired += 1
    assert fired <= morek_checker.FOLLOWUP_LIMIT + 1
    assert [t for t in watches(late) if t.delay < 1000] == [] and late.sets and len(late.sets) == 1
    close(late)


# ------------------------------------------------------------------------------ Stop / Pause / newer plan races, missing data

@pytest.mark.asyncio
async def test_person_stop_before_the_retry_look_reads_nothing_and_sends_nothing(monkeypatch):
    late = await refused_reassert(monkeypatch)
    stop(late)
    reads = late.reads
    await late.settle()
    await fire_watch(late)
    await late.settle()
    assert late.reads == reads and len(late.sets) == 2
    assert [t for t in watches(late) if t.delay < 1000] == []  # no loop against a Stop
    close(late)


@pytest.mark.asyncio
async def test_pause_before_the_retry_look_is_never_reasserted_over(monkeypatch):
    late = await refused_reassert(monkeypatch)
    late.w.ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p" * 32,
                                             "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    reads = late.reads
    await late.settle()
    await fire_watch(late)
    assert late.rig.checker.status()["reason"] == "intent_changed" and late.reads == reads
    assert len(late.sets) == 2
    close(late)


@pytest.mark.asyncio
async def test_a_newer_accepted_plan_ends_the_retry_and_a_stale_confirmation_is_refused(monkeypatch):
    late = await refused_reassert(monkeypatch)
    old_ack = late.ledger["acknowledged"]["id"]
    # a newer plan was accepted meanwhile (its own attempt and acknowledgement)
    record = late.w.ledger.value
    newer = copy.deepcopy(record["acknowledged"])
    newer.update(id="n" * 32, fingerprint="newer")
    record["acknowledged"] = newer
    record["attempt"] = {**record["attempt"], "id": "n" * 32, "state": "accepted", "fingerprint": "newer"}
    assert morek_schedule.rejected_reassert_of(record) is None
    late.rig.checker.request_transition_watch()
    await late.settle()
    assert [t for t in watches(late) if t.delay < 1000] == []
    # a confirmation of the OLD acknowledgement that was already in flight is refused before the wire
    late.w.worker.request_repair({"attempt_id": old_ack, "connection_id": 1, "readback_at": now(late).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    assert len(late.sets) == 2 and late.w.worker.reason == "repair_unconfirmed"
    close(late)


@pytest.mark.asyncio
async def test_a_rejected_attempt_that_is_not_a_reassert_never_qualifies(monkeypatch):
    late = await replaced(monkeypatch)
    record = late.ledger
    record["attempt"] = {**record["attempt"], "id": "r" * 32, "state": "rejected"}
    assert morek_schedule.rejected_reassert_of(record) is None
    assert morek_schedule.check_candidate(record, now(late))[2] == "newer_attempt"
    record["supersession"]["reassert"] = {"attempt_id": "q" * 32, "attempts": 1}  # names another attempt
    assert morek_schedule.rejected_reassert_of(record) is None
    record["supersession"]["reassert"] = {"attempt_id": "r" * 32, "attempts": 1}
    assert morek_schedule.rejected_reassert_of(record) == record["acknowledged"]["id"]
    record["attempt"]["pause_id"] = "p" * 32  # a different intent kind than the (routine) acknowledgement
    record["acknowledged"]["routine"] = True
    assert morek_schedule.rejected_reassert_of(record) is None
    record["attempt"].pop("pause_id")
    record["uncertain"] = True
    assert morek_schedule.rejected_reassert_of(record) is None
    close(late)


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["next_at_missing", "next_at_garbled", "reassert_not_a_dict", "ledger_unreadable"])
async def test_missing_or_damaged_pace_data_never_blocks_or_crashes(monkeypatch, damage):
    late = await refused_reassert(monkeypatch)
    record = late.w.ledger.value
    if damage == "next_at_missing":
        record["supersession"]["reassert"].pop("next_at")
    elif damage == "next_at_garbled":
        record["supersession"]["reassert"]["next_at"] = "not a time"
    elif damage == "reassert_not_a_dict":
        record["supersession"]["reassert"] = "x"
    else:
        late.w.ledger.read = AsyncMock(side_effect=OSError("unreadable"))
    late.rig.checker.request_transition_watch()
    await late.settle()
    status = late.rig.checker.status()
    if damage in ("next_at_missing", "next_at_garbled"):
        # an unreadable pace limits nothing permanently: due now (one look), the send path still guards the write
        assert status["next_transition_check_at"] is not None
        assert morek_schedule.reassert_next_at(record, now(late)) is None
    elif damage == "reassert_not_a_dict":
        assert [t for t in watches(late) if t.delay < 1000] == []  # no valid refused-reassert state: no retry look
    # (an unreadable ledger changes nothing: the watch already armed stays, no new one is invented, nothing is sent)
    assert len(late.sets) == 2
    close(late)
