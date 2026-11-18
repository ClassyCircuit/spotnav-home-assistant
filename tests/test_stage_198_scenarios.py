"""Stage 19.8 (partial): fast cross-cutting mocked scenarios over production behavior that exists today.

Real worker, planner fakes, send path and connector lock; HA, OCPP and admission are mocked boundaries.
NOT covered (19.2 is unresolved, so there is no ambiguous-upload resolution; 19.3 `resolve`, 19.5/19.6/19.7
remaining parts are not implemented): scenario (1) ambiguous upload -> guarded resolution, scenario (4) unknown
session start across a confirmed reboot, and any Stop race against those. Nothing here proves charger behavior,
installed behavior or physical charging."""

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
