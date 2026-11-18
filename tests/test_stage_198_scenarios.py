"""Stage 19.8: fast cross-cutting mocked scenarios (11) over the production paths.

Real worker, planner fakes, send path and connector lock (the session coordinator in the composed case); HA, OCPP and
admission are mocked boundaries. Covers pre-wire retry, slow pace across restart, retained-schedule wording, active-window
SOC drift, the reported legacy unknown + Pause + Resume chain across outage/restart, Stop and Pause races, bounded
logs over a long simulated outage, session-start + schedule composition, a slow retry in a window and a wording audit.
Nothing here proves charger behavior, installed behavior or physical charging.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_198_scenarios.py"""

import copy
from datetime import timedelta

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution.command_admission import physical_connector
from custom_components.spotnav.execution.morek_freshness import LinkFacts, judge_event
from .test_morek_worker import NOW, drain, setup


def _boundary(w, ok):
    async def current(entry_id, connector):
        return ok()
    w.admission.async_owned_boundary_current = current


def _limits(w, index=-1):
    profile = w.point.call.await_args_list[index].args[0].payload["cs_charging_profiles"]
    return [(p["startPeriod"], p["limit"]) for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]


async def _restart(monkeypatch, old):
    old.worker.close()
    again = setup(monkeypatch)
    again.ledger.value = copy.deepcopy(old.ledger.value)
    return again


@pytest.mark.asyncio
async def test_pre_wire_failure_retries_across_restart_with_one_send_and_a_stop_that_wins(monkeypatch):
    refuse = {"on": True}
    w = setup(monkeypatch)
    _boundary(w, lambda: not refuse["on"])
    w.worker.start()
    await drain(w.worker)
    # (2) provably not sent: no wire call, no rejection count, latch released, honest result
    w.point.call.assert_not_awaited()
    assert w.worker.reason == "upload_not_sent" and w.ledger.value["uncertain"] is False
    attempt = w.ledger.value["attempt"]
    assert (attempt["dispatch_class"], attempt["state"]) == ("not_sent", "aborted_before_dispatch")
    event = morek_schedule.decision_event(now=NOW, kinds={"recovery"}, last_trigger="recovery",
                                          reason="upload_not_sent", inputs={}, evidence="none", continuity=None,
                                          dispatched=False)
    assert event["action"] == "blocked" and event["stages"]["intent"] == "none"  # never "sent"
    assert event["blocker"]["code"] == "upload_not_sent"
    await w.worker.async_flush_retry_state()
    # restart with the same durable record: still refusing -> still nothing sent
    again = await _restart(monkeypatch, w)
    _boundary(again, lambda: not refuse["on"])
    again.worker.start()
    await drain(again.worker)
    assert again.point.call.await_count == 0 and again.worker.reason == "upload_not_sent"
    # a person Stop races the next automatic evaluation, after the condition cleared: Stop wins, nothing sent
    refuse["on"] = False
    connector = physical_connector(again.identity)
    again.admission._person_stops[connector] = True  # noqa: SLF001
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 0
    again.admission._person_stops.pop(connector)  # noqa: SLF001
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1 and _limits(again)[-1][1] == 0  # one send, final 0 A
    assert again.ledger.value["attempt"]["dispatch_class"] == "resolved"
    for _ in range(3):  # equal schedule afterwards: no repeat
        again.worker.trigger(kind="recovery")
        await drain(again.worker)
    assert again.point.call.await_count == 1
    again.worker.close()


@pytest.mark.asyncio
async def test_slow_pace_survives_restart_and_the_recovery_sends_exactly_once(monkeypatch):
    online = {"on": False}
    w = setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None}  # a record exists
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 2):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.worker.blocker_retry["phase"] == "slow" and w.worker.reason == "charger_unavailable"
    attempts = w.worker.blocker_retry["attempts"]
    await w.worker.async_flush_retry_state()
    again = await _restart(monkeypatch, w)
    again.worker._available = lambda: online["on"]  # noqa: SLF001
    again.worker.start()
    await drain(again.worker)
    assert again.worker.blocker_retry["phase"] == "slow" and again.worker.blocker_retry["attempts"] == attempts
    assert again.point.call.await_count == 0  # the restart alone sends nothing while the blocker holds
    online["on"] = True  # the link returns; the next guarded evaluation sends once
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1 and again.worker.blocker_retry is None
    again.worker.close()


@pytest.mark.asyncio
async def test_offline_with_a_retained_schedule_claims_only_last_known_evidence(monkeypatch):
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    profile = w.point.call.await_args_list[0].args[0].payload["cs_charging_profiles"]
    outcomes = copy.deepcopy(w.ledger.value)
    # (3) the link is gone: the charger is offline, the retained schedule is a record, never a guarantee
    w.worker._available = lambda: False  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "charger_unavailable"
    verification = {"matched": True, "reason": "matched", "coverage_state": "matches"}
    state = morek_schedule._operator_state(  # noqa: SLF001
        {"supported": True}, False, outcomes, verification, True, {"profile": profile}, None)
    assert state == {"state": "offline", "reason": "charger_unavailable"}  # offline outranks an old "verified"
    horizon = morek_schedule.schedule_horizon(profile, "Accepted", verification, NOW)
    assert horizon["physical_charging"] == "unknown" and horizon["ack"] == "accepted"
    assert morek_schedule.decision_blocker("charger_unavailable")["action"] == "wait_for_charger_connection"
    observation = morek_schedule.observation_entry("charger_unavailable", NOW.isoformat())
    assert (observation["evidence"], observation["basis"], observation["who"]) == ("none", "observed", "system")
    old = NOW - timedelta(minutes=10)
    assert judge_event(old, NOW, LinkFacts("down", None, 1))["state"] == "last_known"
    w.worker.close()


@pytest.mark.asyncio
async def test_active_window_soc_drift_during_outage_sends_nothing_then_one_gapless_resend(monkeypatch):
    online = {"on": True}
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.worker.start()
    await drain(w.worker)
    first = _limits(w)
    assert w.point.call.await_count == 1 and first[0] == (0, 16)
    _, end = w.planner.current.proposal.shown_periods[0]
    minute = timedelta(minutes=1)
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    online["on"] = False
    for drift in (1, 2, 3):  # SOC drift inside the 5 min tolerance while the link is down
        w.planner.current.proposal.shown_periods = ((NOW - minute, end + drift * minute),)
        w.planner.publish("soc")
        await drain(w.worker)
    await w.worker.async_flush_retry_state()
    again = await _restart(monkeypatch, w)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    again.planner.current.proposal.shown_periods = w.planner.current.proposal.shown_periods
    again.worker._available = lambda: online["on"]  # noqa: SLF001  (the link is still down across the restart)
    again.worker.start()
    await drain(again.worker)
    online["on"] = True
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    # A recovery after a link return is a strict (non-routine) trigger, so the 3 min drift is compared strictly and
    # sent once, carrying the acknowledged active window (no 0 A gap); drift never sends during the outage itself.
    assert w.point.call.await_count == 1 and again.point.call.await_count == 1
    resent = _limits(again)
    assert resent[0] == (0, 16) and resent[-1][1] == 0 and morek_schedule.acknowledged_profile(again.ledger.value)
    for _ in range(3):
        again.worker.trigger(kind="recovery")
        await drain(again.worker)
    assert again.point.call.await_count == 1  # then equal: no repeat
    again.worker.close()


# ---------------------------------------------------------------- 19.8 closure: the reported legacy chain, composed

from .test_stage_192_recovery import _legacy, _pending  # noqa: E402
from .test_stage_195_provenance import provenance  # noqa: E402


@pytest.mark.asyncio
async def test_legacy_unknown_pause_resume_survives_outage_and_restart_then_one_guarded_send_and_no_drift_resend(monkeypatch):
    """The reported chain end to end (mocked): old ambiguous upload + Pause + authorized Resume -> link down for a long
    outage (many wakes) -> restart while still down -> reconnect -> exactly one guarded replacement on 42001 with the
    active window carried -> restart again -> a sub-5-minute SOC-only drift at reconnect sends nothing."""
    online = {"on": False}
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    provenance(w)
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 4):  # a long outage: bounded work, nothing sent
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "charger_unavailable"
    assert w.ledger.value["uncertain"] is True and "pending_resume" in w.ledger.value  # intent kept, not an ACK
    assert w.ledger.value["acknowledged"] is None
    await w.worker.async_flush_retry_state()
    again = await _restart(monkeypatch, w)  # restart while still offline
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    provenance(again)
    again.planner.current.proposal.shown_periods = w.planner.current.proposal.shown_periods  # same active window
    again.worker._available = lambda: online["on"]  # noqa: SLF001
    again.worker.start()
    await drain(again.worker)
    assert again.point.call.await_count == 0 and "pending_resume" in again.ledger.value
    online["on"] = True  # reconnect: the pending Resume is reconciled without another click
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1, again.worker.reason
    sent = _limits(again)
    assert sent[0] == (0, 16) and sent[-1][1] == 0 and all(limit == 16 for _, limit in sent[:-1])  # no 0 A gap
    record = again.ledger.value
    assert record["uncertain"] is False and record["attempt"]["dispatch_class"] == "resolved"
    assert record["unknown_history"][0]["outcome"] == "unknown"  # the old attempt is never relabelled
    assert record["supersession"]["risk"] == "late_old_frame_not_excluded" and record["verified"] is None
    assert record["acknowledged"]["resume_plan"] is True and record["acknowledged"]["routine"] is False
    assert morek_schedule.acknowledged_profile(record) and "inputs" in record["acknowledged"]
    for _ in range(3):
        again.worker.trigger(kind="recovery")
        await drain(again.worker)
    assert again.point.call.await_count == 1
    # second restart + a 3 min SOC-only drift: provenance proves nothing material changed -> no spurious send
    await again.worker.async_flush_retry_state()
    third = await _restart(monkeypatch, again)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    provenance(third)
    start, end = w.planner.current.proposal.shown_periods[0]
    third.planner.current.proposal.shown_periods = ((start, end + timedelta(minutes=3)),)
    third.worker.start()
    await drain(third.worker)
    third.worker.trigger(kind="control")
    await drain(third.worker)
    third.worker.trigger(kind="recovery")
    await drain(third.worker)
    assert third.point.call.await_count == 0
    third.worker.close()


@pytest.mark.asyncio
async def test_stop_after_resume_while_offline_wins_at_reconnect_and_no_plan_is_sent(monkeypatch):
    online = {"on": False}
    w = setup(monkeypatch)
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    connector = physical_connector(w.identity)
    w.admission._person_stops[connector] = True  # noqa: SLF001  (a person Stop arrives while offline)
    online["on"] = True
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 0  # Stop outranks the pending Resume and the reconnect
    assert w.ledger.value["uncertain"] is True and "unknown_history" not in w.ledger.value  # old attempt untouched
    w.worker.close()


# ---------------------------------------------------------------- 19.8 closure, part 2: outage volume, Pause race, wording

import logging  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from .test_stage_192_recovery import _owner  # noqa: E402


def _advancing_clock(monkeypatch, step=timedelta(minutes=30)):
    """A fake clock for the worker: every `tick()` moves it on, nothing waits."""
    from custom_components.spotnav.execution import morek_worker
    state = {"now": NOW}

    class Clock:
        now = staticmethod(lambda _=None: state["now"])
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    def tick():
        state["now"] += step
    tick.now = lambda: state["now"]
    return tick


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_long_outage_with_a_flapping_link_keeps_logs_observations_and_writes_bounded(monkeypatch, caplog):
    """~8 simulated days of triggers (fake clock, no waiting): the unknown upload + pending Resume waits offline.
    One log line per *changed* decision, a capped observation list and a bounded number of durable writes; then
    the single reconnect still sends exactly one guarded replacement."""
    caplog.set_level(logging.INFO, logger="custom_components.spotnav")
    online = {"on": False}
    w = setup(monkeypatch, active=True)
    tick = _advancing_clock(monkeypatch)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    baseline_writes = len(w.ledger.writes)
    for index in range(400):
        tick()
        w.worker.trigger(kind=("recovery", "control", "settings")[index % 3])
        if index % 7 == 0:
            w.planner.publish("soc")
        await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason == "charger_unavailable"
    lines = [r for r in caplog.records if r.name.startswith("custom_components.spotnav") and r.levelno >= logging.INFO]
    assert len(lines) <= 8, [r.getMessage()[:80] for r in lines]  # not one line per retry
    assert len(w.worker.observations) <= morek_schedule.RETRY_OBSERVATION_CAP
    assert len(w.ledger.writes) - baseline_writes <= 40  # debounced bounded persistence, not a write per trigger
    private = " ".join(r.getMessage() for r in lines)
    assert morek_schedule.MOREK_STATION_ID not in private and "cs_charging_profiles" not in private
    assert w.worker.blocker_retry["phase"] == "slow" and w.ledger.value["uncertain"] is True
    # the stale plan is never sent after ~8 days: it is `plan_expired` until a current plan is published
    assert w.worker.reason in ("plan_expired", "charger_unavailable")
    online["on"] = True
    tick()
    w.planner.current.proposal.shown_periods = ((tick.now() - timedelta(minutes=1), tick.now() + timedelta(hours=2)),)
    w.planner.publish("price")
    await drain(w.worker)
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["uncertain"] is False
    assert w.ledger.value["unknown_history"][0]["outcome"] == "unknown"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_pause_arriving_during_the_outage_invalidates_the_pending_resume_across_restart(monkeypatch):
    """A later Pause (not only a Stop) wins: the durable Resume is deleted, a restart cannot revive it, and after the
    reconnect only the Pause's own 0 A hold is sent - never the plan - exactly once."""
    online = {"on": False}
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    w.worker._available = lambda: online["on"]  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    _owner(monkeypatch, w)
    w.worker._suspended = True  # noqa: SLF001
    await morek_schedule.async_record_owned_pause(w.hass, "charger")  # Pause during the outage
    w.worker._suspended = False  # noqa: SLF001
    assert "pending_resume" not in w.ledger.value and w.point.call.await_count == 0
    await w.worker.async_flush_retry_state()
    again = await _restart(monkeypatch, w)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    again.worker._available = lambda: online["on"]  # noqa: SLF001
    again.worker.start()
    await drain(again.worker)
    assert again.point.call.await_count == 0 and morek_schedule.valid_pending_resume(again.ledger.value) is None
    online["on"] = True
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1 and {limit for _, limit in _limits(again)} == {0}  # the hold only
    assert again.ledger.value["attempt"]["pause_id"] == "p1"
    assert "resume_plan" not in (again.ledger.value["acknowledged"] or {})
    for _ in range(3):
        again.worker.trigger(kind="recovery")
        await drain(again.worker)
    assert again.point.call.await_count == 1
    again.worker.close()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_session_start_and_schedule_recovery_compose_without_crossing_records(monkeypatch):
    """One durable record carrying BOTH an ambiguous session start and an ambiguous schedule upload + Pause + Resume.
    Schedule recovery sends exactly one profile and never touches the session record; the session coordinator then
    starts exactly once on a genuine new plug-in with fresh evidence, never writes a schedule, and never relabels
    the old unknown attempts. Mocked boundaries; neither proves charger ordering, duplication or physical charging."""
    from .test_stage_196_g4_recovery import ready, plug_in, unknown_record
    from .test_stage_196_start_recovery import world as session_world

    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.ledger.value = _legacy(marker="wire_intent", pending_resume=_pending())
    unknown_record(w.ledger)  # an old ambiguous session start sits in the same ledger
    old_start = copy.deepcopy(w.ledger.value["session_start"])
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["uncertain"] is False
    assert w.ledger.value["session_start"] == old_start  # the schedule path never rewrites the session record
    record = copy.deepcopy(w.ledger.value)
    w.worker.close()
    coordinator, point, ledger, _, evidence = session_world(monkeypatch)
    ledger.value = copy.deepcopy(record)
    ready(evidence)
    await plug_in(coordinator)
    assert point.calls == 1  # one guarded start, not a schedule
    start = ledger.value["session_start"]
    assert start["history"][0]["outcome"] == "unknown" and start["recoveries"] == 1
    assert ledger.value["attempt"] == record["attempt"] and ledger.value["acknowledged"] == record["acknowledged"]
    assert ledger.value["unknown_history"] == record["unknown_history"]
    assert coordinator.start_recovery_status()["risk"] == "duplicate_or_delayed_start_not_excluded"
    for _ in range(3):  # routine updates repeat nothing
        coordinator.observe("Preparing", "Preparing")
        coordinator.trigger()
        if coordinator.task is not None:
            await coordinator.task
    assert point.calls == 1


def test_stage_19_wording_never_claims_charging_or_a_known_old_outcome():
    """Audit of the Stage 19 recovery wording (banner strings and status fields) against the evidence classes."""
    import re
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "frontend" / "sidebar" / "recovery-banner.js").read_text("utf8")
    claims = re.compile(r"will charge|guarantee(?!d)|is charging|charging now|(?<!not )\bverified\b|\bsucceed|"
                        r"old (write|upload) (was|has been) (applied|accepted)", re.I)
    for text in re.findall(r"'([^'\n]{12,})'|`([^`\n]{12,})`", source):
        sentence = text[0] or text[1]
        assert not claims.search(sentence), sentence
    record = _legacy(marker="wire_intent", pending_resume=_pending())
    record["supersession"] = {"state": "pending", "risk": "late_old_frame_not_excluded", "since": "t"}
    status = morek_schedule.unknown_recovery_status(record, NOW)
    assert (status["old_outcome"], status["ordering"], status["physical_charging"]) == ("unknown", "unverified", "unknown")
    horizon = morek_schedule.schedule_horizon(
        {"chargingSchedule": {"startSchedule": NOW.isoformat(), "chargingSchedulePeriod": [
            {"startPeriod": 0, "limit": 16}, {"startPeriod": 3600, "limit": 0}]}}, "Accepted",
        {"matched": False, "reason": "not_comparable", "coverage_state": "not_verifiable"}, NOW)
    assert horizon["ack"] == "accepted" and horizon["physical_charging"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_rejected_extension_in_an_active_window_is_retried_slowly_and_carries_the_window(monkeypatch):
    """19.5 gap: a slow retry during a healthy window. The window is never gapped, nothing is sent between paced
    attempts, the retry is one guarded send and an equal schedule afterwards sends nothing."""
    h = timedelta(hours=1)
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    first = w.planner.current.proposal.shown_periods[0]
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.planner.current.proposal.shown_periods = (first, (NOW + 5 * h, NOW + 6 * h))
    w.planner.publish("publication")
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker.reason == "upload_rejected"
    sends = w.point.call.await_count
    for _ in range(5):  # inside the pace: further triggers send nothing
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == sends
    w.point.call.return_value = SimpleNamespace(status="Accepted")
    # the send path stamps attempts with the wall clock, so age the durable attempt past its first pace (no waiting)
    from datetime import datetime, timezone
    w.ledger.value["attempt"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == sends + 1  # exactly one guarded retry
    retried = _limits(w)
    assert retried[0] == (0, 16) and retried[-1][1] == 0, retried  # the window is carried: no 0 A gap
    assert (18000, 16) in retried and w.ledger.value["attempt"]["state"] == "accepted"
    for _ in range(3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.point.call.await_count == sends + 1
    w.worker.close()
