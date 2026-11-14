"""Stage 15.4b: repair deferral for a correct charge, final pre-wire freshness, post-repair escalation, gate ON.

Real checker, worker, `_send_profile_shared` and outcome ledger over the 15.3/15.4a rigs; OCPP point, HA timers,
storage and admission authorization are the usual mocked boundaries. Nothing here proves charger behaviour, what the
installed charger answers to GetCompositeSchedule, or physical (un)interrupted charging.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_154b_repair_deferral.py
"""

import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_checker, morek_worker
from . import test_stage_153_schedule_check as t153
from .test_morek_worker import drain
from .test_stage_154a_repair import boot, checker_rig, enable, real_now

WRONG = {"current_wrong": True, "diff_in_s": 0.0}


def future(seconds):
    return {"current_wrong": False, "diff_in_s": float(seconds)}


def reading(value, *, fresh=True):
    return {"value": value, "unit": "W", "observed_at": real_now().isoformat(), "fresh": fresh}


def flow(monkeypatch, state):
    live = {"charging": {"power_w": reading(3000.0), "current_a": None},
            "idle": {"power_w": reading(0.0), "current_a": None},
            "unknown": {"power_w": reading(3000.0, fresh=False), "current_a": None}}[state]
    monkeypatch.setattr(morek_schedule, "_live_measurements", lambda *a, **k: live)


def conf(r, facts, attempt_id=None):
    out = r.conf(attempt_id)
    out["facts"] = facts
    return out


async def ask(r, facts, attempt_id=None):
    r.w.worker.request_repair(conf(r, facts, attempt_id))
    await drain(r.w.worker)
    return r.w.worker.reason


# ---- gate and pure decisions -----------------------------------------------------------------------------

def test_the_gate_is_enabled_only_with_deferral_freshness_and_escalation_present():
    assert morek_schedule.REPAIR_DISPATCH_ENABLED is True
    assert morek_schedule.REPAIR_DEFER_GAP_S == 600 and morek_schedule.REPAIR_FRESH_S == 30
    for name in ("repair_deferral", "measured_flow", "mismatch_facts", "repaired_ids", "repair_escalated"):
        assert callable(getattr(morek_schedule, name))
    assert callable(morek_checker.MorekScheduleChecker.request_post_repair)


@pytest.mark.parametrize(("facts", "flow_state", "elapsed", "expected"), [
    (future(1200), "charging", 0, "future_difference"),
    (future(1200), "unknown", 0, "future_difference"),  # unknown flow is not permission to interrupt
    (future(600), "charging", 0, None),  # the gap has reached 10 minutes: proceed
    (future(600.5), "charging", 0, "future_difference"),
    (future(700), "charging", 100, None),  # the readback's age counts toward the gap
    (future(1200), "idle", 0, None),  # idle: repair at once
    (WRONG, "charging", 0, None),  # wrong current limit: repair at once
    (WRONG, "unknown", 0, None),
    ({"current_wrong": None, "diff_in_s": None}, "charging", 0, "facts_unknown"),  # missing data is no command
    (None, "unknown", 0, "facts_unknown"),
    ({"current_wrong": False, "diff_in_s": True}, "charging", 0, "facts_unknown"),
    (None, "idle", 0, None),
])
def test_repair_deferral_decision(facts, flow_state, elapsed, expected):
    assert morek_schedule.repair_deferral(facts, flow_state, elapsed) == expected


def test_measured_flow_needs_fresh_measured_readings_and_unknown_is_never_idle():
    f = morek_schedule.measured_flow
    assert f({"power_w": reading(3000.0)}) == "charging"
    assert f({"power_w": reading(0.0)}) == "idle"
    assert f({"power_w": reading(0.0), "current_a": {"value": 9.0, "fresh": True}}) == "charging"  # any flow wins
    assert f({"power_w": reading(3000.0, fresh=False)}) == "unknown"  # stale
    assert f({"power_w": None, "current_a": None}) == "unknown" and f(None) == "unknown"
    assert f({"power_w": {"value": float("nan"), "fresh": True}}) == "unknown"
    assert f({"power_w": {"value": True, "fresh": True}}) == "unknown"


def test_mismatch_facts_split_a_wrong_current_limit_from_a_future_only_difference():
    now = real_now().replace(microsecond=0)
    profile = morek_schedule.profile_for(((now + timedelta(hours=1), now + timedelta(hours=2)),), 16, now)
    reply = t153.composite(profile).charging_schedule
    start = now.isoformat()

    def actual(periods):
        return {"status": "Accepted", "schedule_start": start, "fetched_at": start, "periods": [
            {"at": (now + timedelta(seconds=p["startPeriod"])).isoformat(), "amps": p["limit"]} for p in periods]}

    exact = actual(reply["chargingSchedulePeriod"])
    assert morek_schedule.mismatch_facts(profile, exact) == {"current_wrong": None, "diff_in_s": None}  # no difference: not a fact
    wrong = actual([{"startPeriod": 0, "limit": 16}, *reply["chargingSchedulePeriod"][1:]])
    assert morek_schedule.mismatch_facts(profile, wrong) == {"current_wrong": True, "diff_in_s": 0.0}
    moved = copy.deepcopy(reply["chargingSchedulePeriod"])
    moved[1]["startPeriod"] += 1200  # the start of the window is 20 minutes later than intended
    facts = morek_schedule.mismatch_facts(profile, actual(moved))
    assert facts["current_wrong"] is False and abs(facts["diff_in_s"] - (3600 - 0)) < 5  # earliest differing change
    assert morek_schedule.mismatch_facts(None, exact) == {"current_wrong": None, "diff_in_s": None}
    assert morek_schedule.mismatch_facts(profile, {"periods": "x"}) == {"current_wrong": None, "diff_in_s": None}


# ---- worker deferral / immediate repair ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correct_charging_with_a_distant_future_difference_defers_and_sends_nothing(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "charging")
    r = await boot(monkeypatch)
    writes = len(r.w.ledger.writes)
    assert await ask(r, future(1200)) == "repair_deferred"
    assert r.calls == 1 and len(r.w.ledger.writes) == writes and "repair_attempts" not in r.ledger
    status = r.w.worker.repair_confirmed
    assert status["state"] == "deferred" and status["defer_reason"] == "future_difference"
    assert r.w.worker.decision["result"] == "repair_deferred"
    assert r.w.worker.decision["blocker"]["code"] == "repair_deferred" and r.w.worker._repair_request is None
    # the next recheck, still 11 minutes out, defers again without a send or a new decision line
    assert await ask(r, future(660)) == "repair_deferred" and r.calls == 1
    r.w.worker.close()


@pytest.mark.asyncio
async def test_the_boundary_then_repairs_exactly_once(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "charging")
    r = await boot(monkeypatch)
    assert await ask(r, future(601)) == "repair_deferred" and r.calls == 1
    assert await ask(r, future(600)) == "upload_accepted_unverified" and r.calls == 2
    assert len(r.ledger["repair_attempts"]) == 1
    assert r.payload(0) == r.payload(1)  # wire continuity: the same intent, nothing released
    r.w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "facts"), [("idle", future(5000)), ("charging", WRONG), ("unknown", WRONG),
                                              ("idle", None)])
async def test_idle_or_a_wrong_current_limit_repairs_at_once(monkeypatch, state, facts):
    enable(monkeypatch)
    flow(monkeypatch, state)
    r = await boot(monkeypatch)
    assert await ask(r, facts) == "upload_accepted_unverified" and r.calls == 2
    r.w.worker.close()


@pytest.mark.asyncio
async def test_active_window_deferral_then_repair_carries_the_window_with_no_zero_amp_gap(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "charging")
    r = await boot(monkeypatch, active=True)
    first = r.payload(0)["chargingSchedule"]["chargingSchedulePeriod"]
    assert first[0]["limit"] == 16
    assert await ask(r, future(1200)) == "repair_deferred" and r.calls == 1
    assert await ask(r, future(300)) == "upload_accepted_unverified"
    second = r.payload(1)["chargingSchedule"]["chargingSchedulePeriod"]
    assert second == first and all(p["limit"] != 0 for p in second[:1])
    r.w.worker.close()


@pytest.mark.asyncio
async def test_flow_turning_to_charging_at_the_final_prewire_check_aborts_without_budget(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    calls = {"n": 0}

    def live(*_a, **_k):
        calls["n"] += 1  # idle at the first validation, charging from the second (after the attempt was persisted)
        return {"power_w": reading(0.0 if calls["n"] == 1 else 3000.0), "current_a": None}

    monkeypatch.setattr(morek_schedule, "_live_measurements", live)
    ack = r.ledger["acknowledged"]
    assert await ask(r, future(1200)) == "repair_deferred"
    assert r.calls == 1 and r.ledger["attempt"]["state"] == "aborted_before_dispatch"
    assert r.ledger["acknowledged"] == ack and r.ledger.get("repair_attempts", []) == []
    assert r.w.worker.repair_confirmed["state"] == "deferred"
    r.w.worker.close()


@pytest.mark.asyncio
async def test_unknown_flow_unknown_facts_and_unreadable_flow_never_repair_a_correct_charge(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    flow(monkeypatch, "unknown")
    assert await ask(r, future(1200)) == "repair_deferred"
    assert await ask(r, None) == "repair_deferred"
    monkeypatch.setattr(morek_schedule, "_live_measurements", lambda *a, **k: 1 / 0)  # unreadable: unknown
    assert await ask(r, future(1200)) == "repair_deferred"
    assert r.calls == 1
    r.w.worker.close()


# ---- final pre-wire freshness (real checker token) --------------------------------------------------------

class Ticker:
    def __init__(self, step):
        self.t, self.step = 1000.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def token_for(w, ticker, *, age_s=0.0, facts=WRONG, attempt=None):
    checker = morek_checker.MorekScheduleChecker(w.hass, "charger", w.worker, monotonic=ticker)
    w.worker.link_monitor = SimpleNamespace(state="up", connection_id=1)
    token = {"attempt_id": attempt or w.ledger.value["acknowledged"]["id"], "connection_id": 1,
             "readback_at": (real_now() - timedelta(seconds=age_s)).isoformat(), "mono": ticker.t - age_s,
             "facts": facts}
    checker._confirmation = token
    return checker, {**token, "current": lambda: checker.repair_current(token)}


@pytest.mark.asyncio
async def test_an_expired_confirmation_is_refused_and_never_refreshed(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    _, stale = token_for(r.w, Ticker(0.0), age_s=45.0)
    r.w.worker.request_repair(stale)
    await drain(r.w.worker)
    assert r.w.worker.reason == "repair_unconfirmed" and r.calls == 1 and "repair_attempts" not in r.ledger
    # only a newer confirmation (a new read) can repair
    _, fresh = token_for(r.w, Ticker(0.0), age_s=2.0)
    r.w.worker.request_repair(fresh)
    await drain(r.w.worker)
    assert r.w.worker.reason == "upload_accepted_unverified" and r.calls == 2
    r.w.worker.close()


@pytest.mark.asyncio
async def test_storage_or_lock_delay_that_ages_the_read_past_30s_aborts_before_the_wire(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    ack = r.ledger["acknowledged"]
    # each validation advances the monotonic clock 12 s: ages 12 s, 24 s (ok), then 36 s at the third boundary
    _, token = token_for(r.w, Ticker(12.0))
    r.w.worker.request_repair(token)
    await drain(r.w.worker)
    assert r.w.worker.reason == "repair_unconfirmed" and r.calls == 1
    assert r.ledger["attempt"]["state"] == "aborted_before_dispatch" and r.ledger["acknowledged"] == ack
    assert r.ledger.get("repair_attempts", []) == []
    r.w.worker.close()


@pytest.mark.asyncio
async def test_repair_current_checks_both_clocks_and_connection(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    skew.advance(rig, 31)
    await rig.fire()
    token = rig.requests[0]
    assert token["current"]() is True and token["facts"]["current_wrong"] is True and token["mono"] > 0
    rig.clock.t += 31  # the monotonic clock alone moves on (wall stands still)
    assert token["current"]() is False
    rig.clock.t -= 31
    assert token["current"]() is True
    skew.offset += timedelta(seconds=31)  # the wall clock alone moves on
    assert token["current"]() is False
    skew.offset -= timedelta(seconds=31)
    assert token["current"]() is True
    skew.advance(rig, 29)
    assert token["current"]() is True  # 29 s after the read
    skew.advance(rig, 2)
    assert token["current"]() is False  # 31 s: expired even though the link is up and nothing else changed
    # a newer check produces a NEW token; the old one stays dead
    await rig.fire()
    assert rig.requests[-1] is not token and rig.requests[-1]["current"]() is True and token["current"]() is False


@pytest.mark.asyncio
async def test_check_results_carry_facts_only_for_a_mismatch(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    assert rig.checker._status["class"] == t153.DIFFERS
    healthy = t153.routine(monkeypatch)
    result = await morek_schedule.async_schedule_action(
        healthy.w.hass, "charger", "fetch", check={"current": lambda: True, "attempt_id": None})
    assert result["check"]["class"] == t153.HEALTHY and "facts" not in result["check"]
    differing = t153.routine(monkeypatch, differ=True)
    result = await morek_schedule.async_schedule_action(
        differing.w.hass, "charger", "fetch", check={"current": lambda: True, "attempt_id": None})
    assert result["check"]["class"] == t153.DIFFERS and result["check"]["facts"]["current_wrong"] in (True, False)


# ---- post-repair escalation ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_accepted_repair_asks_for_one_later_read_only_look_and_a_rejected_one_does_not(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    seen = []
    r.w.worker.checker = SimpleNamespace(request_post_repair=lambda: seen.append(1), close=lambda: None)
    assert await ask(r, WRONG) == "upload_accepted_unverified" and seen == [1]
    r.w.point.call.return_value = SimpleNamespace(status="Rejected")
    r.ledger["repair_attempts"] = []
    r.ledger["repair_escalation"] = None
    assert await ask(r, WRONG, r.ledger["acknowledged"]["id"]) in ("upload_rejected", "repair_needs_person")
    assert seen == [1]
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_confirmed_mismatch_of_an_attempt_that_is_itself_a_repair_escalates_and_stops(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "charging")  # even an active correct charge: escalation, not deferral and not a repair
    r = await boot(monkeypatch)
    assert await ask(r, WRONG) == "upload_accepted_unverified" and r.calls == 2
    repaired = r.ledger["acknowledged"]["id"]
    writes = len(r.w.ledger.writes)
    assert await ask(r, future(1200), repaired) == "repair_needs_person"
    assert r.calls == 2 and r.ledger["repair_escalation"]["attempt_id"] == repaired
    assert len(r.w.ledger.writes) == writes + 1 and len(r.ledger["repair_attempts"]) == 1  # one marker, no new write
    assert r.w.worker.decision["blocker"]["code"] == "repair_needs_person"
    assert morek_schedule.repair_status(r.w.worker, r.ledger)["needs_person"] is True
    # no blind loop: more confirmations, even with an open budget and a wrong limit, send nothing and write nothing
    r.ledger["repair_attempts"] = []
    for facts in (WRONG, future(1200), WRONG):
        assert await ask(r, facts, repaired) == "repair_needs_person"
    assert r.calls == 2 and len(r.w.ledger.writes) == writes + 1
    assert "clear" not in str([c.args[0] for c in r.w.point.call.await_args_list]).lower()
    r.w.worker.close()


@pytest.mark.asyncio
async def test_the_escalation_survives_a_restart_and_is_per_attempt(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    assert await ask(r, WRONG) == "upload_accepted_unverified"
    repaired = r.ledger["acknowledged"]["id"]
    assert await ask(r, WRONG, repaired) == "repair_needs_person"
    r.w.worker.close()
    r.w.hass.data = {}  # a restart: only the durable ledger survives
    worker = morek_worker.MorekScheduleWorker(r.w.hass, "charger", r.w.planner)
    worker.request_repair({**r.conf(repaired), "facts": WRONG})
    await drain(worker)
    assert worker.reason == "repair_needs_person" and r.calls == 2
    assert morek_schedule.repair_status(worker, r.ledger)["needs_person"] is True
    worker.close()
    # a later, different acknowledged attempt is not escalated (the marker names the repaired one)
    assert morek_schedule.repair_escalated(r.ledger, repaired) and not morek_schedule.repair_escalated(r.ledger, "other")
    assert not morek_schedule.repair_escalated(r.ledger, None) and not morek_schedule.repair_escalated(None, "x")
    assert morek_schedule.repaired_ids({"repair_attempts": "junk"}) == set()
    assert morek_schedule.repaired_ids({"repair_attempts": [{"attempt_id": "a"}, 3, {"attempt_id": 4}]}) == {"a"}


@pytest.mark.asyncio
async def test_a_rejected_repair_escalates_without_a_second_blind_write_and_unknown_waits(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    original = r.ledger["acknowledged"]["id"]
    r.w.point.call.return_value = SimpleNamespace(status="Rejected")
    assert await ask(r, WRONG) == "upload_rejected" and r.calls == 2
    assert r.ledger["repair_escalation"]["attempt_id"] == original and len(r.ledger["repair_attempts"]) == 1
    assert morek_schedule.repair_status(r.w.worker, r.ledger)["needs_person"] is True
    for _ in range(3):  # the cooldown, then the escalation, hold the wire: nothing more is sent
        assert await ask(r, WRONG, original) in ("upload_rejected", "repair_unconfirmed", "repair_needs_person")
    assert r.calls == 2
    r.w.worker.close()
    # an unknown outcome stays the existing uncertain latch: no repair, no retry
    r2 = await boot(monkeypatch)
    r2.w.point.call.side_effect = TimeoutError
    assert await ask(r2, WRONG) == "upload_uncertain" and r2.calls == 2
    assert await ask(r2, WRONG, original) == "upload_uncertain" and r2.calls == 2
    r2.w.worker.close()


@pytest.mark.asyncio
async def test_post_repair_check_episode_confirms_only_clean_fresh_mismatches(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    rig.checker.request_post_repair()
    assert [t.delay for t in rig.live()] == [morek_checker.POST_REPAIR_DELAY_S]
    # the repair's own verification is still running: wait a bounded number of times, then give up (unknown)
    rig.w.hass.data["spotnav_morek_dispatched"] = {"charger": "a1"}
    rig.data.update(verified=False, verification={"pending": False, "reason": "upload_unconfirmed", "attempts": 0})
    for _ in range(morek_checker.POST_REPAIR_WAIT_LIMIT):
        await rig.fire()
        assert rig.checker.status()["reason"] == "verification_pending" and rig.live()[-1].delay == 60
    await rig.fire()
    assert not rig.live() and rig.requests == [] and rig.reads == 0  # nothing read, nothing requested
    # verification finished: one odd read is not a confirmation, two clean ones 31 s apart are
    rig.data.update(verified=True, verification={"pending": False, "reason": "matched", "attempts": 1})
    rig.checker.request_post_repair()
    await rig.fire()
    assert rig.checker.status()["class"] == t153.DIFFERS and rig.requests == []
    skew.advance(rig, 31)
    await rig.fire()
    assert len(rig.requests) == 1 and rig.requests[0]["facts"] is not None
    rig.assert_untouched()  # still read-only


@pytest.mark.asyncio
async def test_unknown_post_repair_verification_is_not_a_mismatch(monkeypatch):
    skew, rig = checker_rig(monkeypatch, raises=True)
    rig.checker.request_post_repair()
    await rig.fire()
    skew.advance(rig, 31)
    rig.checker.request_post_repair()
    await rig.fire()
    assert rig.checker.status()["class"] == t153.UNKNOWN and rig.requests == []


# ---- the gate cannot send without the guards -------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_on_cannot_send_without_confirmation_freshness_deferral_or_escalation(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "charging")
    r = await boot(monkeypatch)
    # a plain trigger (no confirmation) and a stale/foreign confirmation send nothing
    r.w.worker.trigger(kind="repair")
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "unchanged"
    _, stale = token_for(r.w, Ticker(0.0), age_s=40.0)
    r.w.worker.request_repair({**stale, "facts": WRONG})
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "repair_unconfirmed"
    # a fresh confirmation of a correct charge with a far future difference: deferred
    _, deferred = token_for(r.w, Ticker(0.0), facts=future(3600))
    r.w.worker.request_repair(deferred)
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "repair_deferred"
    # an escalated attempt: refused even with fresh facts
    r.ledger["repair_escalation"] = {"at": real_now().isoformat(), "attempt_id": r.ledger["acknowledged"]["id"]}
    _, escalated = token_for(r.w, Ticker(0.0), facts=WRONG)
    r.w.worker.request_repair(escalated)
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "repair_needs_person"
    r.w.worker.close()


@pytest.mark.asyncio
async def test_stop_racing_a_deferred_or_repairing_run_sends_nothing(monkeypatch):
    enable(monkeypatch)
    flow(monkeypatch, "idle")
    r = await boot(monkeypatch)
    with r.w.admission.person_stop_reservation("charger", lambda: r.w.identity):
        r.w.worker.request_repair(conf(r, WRONG))
        await drain(r.w.worker)
    assert r.calls == 1 and "repair_attempts" not in r.ledger
    r.w.worker.close()
