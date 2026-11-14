"""Stage 15.4a: guarded schedule repair - confirmation, trigger and budget (gate OFF in every shipped build).

Real checker, worker, `_send_profile_shared` and outcome ledger; OCPP point, HA timers, storage and admission
authorization are the usual mocked boundaries. Nothing here proves charger behaviour or physical charging.
`REPAIR_DISPATCH_ENABLED` stays False; the enabled tests patch it on explicitly.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_154a_repair.py
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_checker, morek_worker
from . import test_stage_153_schedule_check as t153
from .test_morek_worker import IDENTITY, NOW, drain, setup


def real_now():
    return datetime.now(timezone.utc)


def ago(**kw):
    return (real_now() - timedelta(**kw)).isoformat()


# ---- worker / send path -------------------------------------------------------------------------------------

class Repair:
    """A started worker that already sent and had its first (routine) profile accepted."""

    def __init__(self, w):
        self.w = w
        self.flag = {"ok": True}

    @property
    def calls(self):
        return self.w.point.call.await_count

    @property
    def ledger(self):
        return self.w.ledger.value

    def conf(self, attempt_id=None):
        return {"attempt_id": attempt_id or self.ledger["acknowledged"]["id"], "connection_id": 1,
                "readback_at": real_now().isoformat(), "current": lambda: self.flag["ok"],
                "facts": {"current_wrong": True, "diff_in_s": 0.0}}  # 15.4b: a wrong limit repairs at once

    def payload(self, index=-1):
        return self.w.point.call.await_args_list[index].args[0].payload["cs_charging_profiles"]

    async def repair(self, **kw):
        self.w.worker.request_repair(self.conf(**kw))
        await drain(self.w.worker)
        return self.w.worker.reason


async def boot(monkeypatch, *, active=False):
    w = setup(monkeypatch, active=active)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_accepted_unverified" and w.point.call.await_count == 1
    return Repair(w)


def enable(monkeypatch):
    monkeypatch.setattr(morek_schedule, "REPAIR_DISPATCH_ENABLED", True)


def held(payload):
    periods = payload["chargingSchedule"]["chargingSchedulePeriod"]
    return len(periods) == 1 and periods[0]["limit"] == 0


@pytest.fixture(autouse=True)
def gate_off_unless_enabled(monkeypatch):
    """15.4b enabled the shipped gate; these 15.4a tests keep exercising the gated path by patching it off
    (and `enable()` patches it back on). The shipped value is asserted in test_stage_154b_repair_deferral.py."""
    monkeypatch.setattr(morek_schedule, "REPAIR_DISPATCH_ENABLED", False)


@pytest.mark.asyncio
async def test_gate_off_confirmed_mismatch_is_recorded_and_makes_zero_writes(monkeypatch):
    r = await boot(monkeypatch)
    writes = len(r.w.ledger.writes)
    r.w.worker.request_repair(r.conf())
    r.w.worker.request_repair(r.conf())  # a repeat only counts
    await drain(r.w.worker)
    assert r.calls == 1 and len(r.w.ledger.writes) == writes and "repair_attempts" not in r.ledger
    assert r.w.worker._task is None and r.w.worker._repair_request is None
    decision = r.w.worker.decision
    assert decision["result"] == "repair_gated" and decision["blocker"]["code"] == "repair_gated"
    assert decision["trigger"] == "repair" and decision["action"] == "blocked" and decision["repeat"] == 2
    status = morek_schedule.repair_status(r.w.worker, r.ledger)
    assert status["gate_enabled"] is False and status["confirmed"]["state"] == "gated" and not status["needs_person"]
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_direct_repair_trigger_with_the_gate_off_never_bypasses_dedup(monkeypatch):
    r = await boot(monkeypatch)
    r.w.worker._repair_request = r.conf()
    r.w.worker.trigger(kind="repair")
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "unchanged"
    r.w.worker.close()


@pytest.mark.asyncio
async def test_enabled_a_confirmed_mismatch_sends_exactly_one_profile_and_counts_one(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    first = r.ledger["acknowledged"]["id"]
    assert await r.repair() == "upload_accepted_unverified"
    assert r.calls == 2 and r.payload(0) == r.payload(1)  # the same current intent, resent
    assert [e["attempt_id"] for e in r.ledger["repair_attempts"]] == [r.ledger["attempt"]["id"]]
    assert r.ledger["attempt"]["id"] != first and r.ledger["acknowledged"]["id"] == r.ledger["attempt"]["id"]
    decision = r.w.worker.decision
    assert decision["trigger"] == "repair" and decision["action"] == "sent"
    assert r.w.worker.repair_confirmed["state"] == "sent" and r.w.worker._repair_request is None
    # the request was consumed: an ordinary trigger afterwards is plain dedup again, and a stale repeat is refused
    r.w.worker.trigger()
    await drain(r.w.worker)
    assert r.calls == 2 and r.w.worker.reason == "unchanged"
    assert await r.repair(attempt_id=first) == "repair_unconfirmed" and r.calls == 2
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_normal_run_is_deduplicated_exactly_as_before(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    for _ in range(3):
        r.w.worker.trigger()
        await drain(r.w.worker)
    r.w.worker.trigger(kind="recalc")
    await drain(r.w.worker)
    assert r.calls == 1 and r.w.worker.reason == "unchanged" and "repair_attempts" not in r.ledger
    r.w.worker.close()


@pytest.mark.asyncio
async def test_repair_carries_the_active_window_with_no_zero_amp_gap_and_no_price_decision(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch, active=True)
    first = r.payload(0)["chargingSchedule"]
    assert first["chargingSchedulePeriod"][0]["limit"] == 16  # the window is running now
    r.w.worker._price_pending = True  # a pending price decision must neither be consumed nor create a release
    assert await r.repair() == "upload_accepted_unverified"
    second = r.payload(1)["chargingSchedule"]
    assert second["chargingSchedulePeriod"] == first["chargingSchedulePeriod"]
    assert second["startSchedule"] == first["startSchedule"]
    assert r.w.worker._price_pending is True and r.w.worker.continuity["preserved"] is True
    assert r.w.worker.decision["result"] != "price_improvement"
    r.w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", ["uncertain", "rejected"])
async def test_uncertain_and_rejection_cooldown_are_never_bypassed(monkeypatch, seed):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    ack = r.ledger["acknowledged"]["id"]
    if seed == "uncertain":
        r.ledger["uncertain"] = True
        r.ledger["attempt"]["state"] = "uncertain"
        expected = "upload_uncertain"
    else:
        r.ledger["attempt"].update(state="rejected", rejections=1, source="worker", at=real_now().isoformat())
        expected = "upload_rejected"
    writes = len(r.w.ledger.writes)
    assert await r.repair(attempt_id=ack) == expected
    assert r.calls == 1 and len(r.w.ledger.writes) == writes and "repair_attempts" not in r.ledger
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_newer_attempt_or_changed_ack_means_the_confirmation_is_stale(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    r.ledger["attempt"] = {**r.ledger["attempt"], "id": "newer", "state": "accepted"}
    assert await r.repair() == "repair_unconfirmed" and r.calls == 1
    r.w.worker.close()


@pytest.mark.asyncio
async def test_pause_hold_repairs_only_as_a_hold_and_never_becomes_a_run(monkeypatch):
    enable(monkeypatch)
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(
        async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    w.worker.start()
    await drain(w.worker)
    r = Repair(w)
    assert r.calls == 1 and r.ledger["attempt"]["pause_id"] and held(r.payload(0))
    assert await r.repair() == "upload_accepted_unverified" and r.calls == 2
    assert held(r.payload(1))
    assert r.ledger["attempt"]["pause_id"] and len(r.ledger["repair_attempts"]) == 1
    # the pause is gone (resumed) but the confirmation was about the hold: no repair of a different intent
    r.ledger.pop("schedule_pause")
    r.ledger["repair_attempts"] = []
    assert await r.repair() == "repair_unconfirmed" and r.calls == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_repairs_as_its_own_override(monkeypatch):
    enable(monkeypatch)
    w = setup(monkeypatch)

    class Clock:
        now = staticmethod(lambda _: NOW)
        fromisoformat = staticmethod(datetime.fromisoformat)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None, "acknowledged": None,
                      "verified": None, "removal": None, "charge_now": {
                          "version": 1, "id": "a" * 32, "station_id": IDENTITY["resolved_id"], "connector_id": 1,
                          "start": (NOW - timedelta(minutes=5)).isoformat(), "end": (NOW + timedelta(hours=1)).isoformat()}}
    w.worker.start()
    await drain(w.worker)
    r = Repair(w)
    assert r.calls == 1 and r.ledger["attempt"]["override_id"] == "a" * 32
    assert await r.repair() == "upload_accepted_unverified" and r.calls == 2
    assert r.ledger["attempt"]["override_id"] == "a" * 32 and r.payload(0) == r.payload(1)
    assert r.payload(1)["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16
    w.worker.close()


# ---- budget -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("seed", "expected"), [
    ([{"at": "x", "attempt_id": "a"}], "repair_needs_person"),  # malformed date: no repair, a person looks
    ("nope", "repair_needs_person"),
    ([{"at": ago(hours=2)}], "repair_needs_person"),  # entry without an attempt id
    ([{"at": (real_now() + timedelta(hours=3)).isoformat(), "attempt_id": "a"}], "repair_needs_person"),  # future
    ([{"at": ago(hours=1), "attempt_id": "a"}, {"at": ago(minutes=40), "attempt_id": "b"}], "repair_needs_person"),
    ([{"at": ago(minutes=10), "attempt_id": "a"}], "repair_spacing"),
])
async def test_budget_refusals_send_nothing_and_consume_nothing(monkeypatch, seed, expected):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    r.ledger["repair_attempts"] = seed
    before = list(seed) if isinstance(seed, list) else seed
    assert await r.repair() == expected
    assert r.calls == 1 and r.ledger["repair_attempts"] == before
    assert r.w.worker.decision["blocker"]["code"] == expected
    r.w.worker.close()


@pytest.mark.asyncio
async def test_spacing_and_rolling_window_then_cap_hold_across_a_restart(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    # an entry older than 24 h no longer counts and is dropped; one 31 minutes old satisfies the spacing
    r.ledger["repair_attempts"] = [{"at": ago(hours=25), "attempt_id": "old"}, {"at": ago(minutes=31), "attempt_id": "a"}]
    assert await r.repair() == "upload_accepted_unverified" and r.calls == 2
    ids = [e["attempt_id"] for e in r.ledger["repair_attempts"]]
    assert "old" not in ids and len(ids) == 2
    r.w.worker.close()
    # restart: new process-local data and worker, the durable ledger survives; the cap of 2 now holds
    r.w.hass.data = {}
    worker = morek_worker.MorekScheduleWorker(r.w.hass, "charger", r.w.planner)
    worker.request_repair(r.conf())
    await drain(worker)
    assert worker.reason == "repair_needs_person" and r.calls == 2
    assert morek_schedule.repair_status(worker, r.ledger)["needs_person"] is True
    worker.close()
    # a rolling window: the same two entries, now older than 24 h, free the budget again
    r.ledger["repair_attempts"] = [{**e, "at": ago(hours=25)} for e in r.ledger["repair_attempts"]]
    assert morek_schedule.repair_budget(r.ledger, real_now())["state"] == "ok"


def test_old_records_without_the_list_load_unchanged():
    record = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None, "acknowledged": None}
    assert morek_schedule.repair_budget(record, real_now()) == {"state": "ok", "recent": [], "next_at": None}
    assert morek_schedule.repair_budget(None, real_now())["state"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["stop_at_attempt_write", "stop_at_budget_write", "confirmation_lost", "link_lost"])
async def test_races_before_the_wire_send_nothing_and_consume_no_budget(monkeypatch, race):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    ack = r.ledger["acknowledged"]
    original, entered, release = r.w.ledger.write, asyncio.Event(), asyncio.Event()
    target = 1 if race == "stop_at_attempt_write" else 2  # 1: attempt persisted, 2: the budget entry persisted
    count = {"n": 0}

    async def write(value):
        count["n"] += 1
        await original(value)
        if count["n"] == target:
            entered.set()
            await release.wait()

    monkeypatch.setattr(r.w.ledger, "write", write)
    r.w.worker.request_repair(r.conf())
    await entered.wait()
    if race.startswith("stop"):
        with r.w.admission.person_stop_reservation("charger", lambda: r.w.identity):
            release.set()
            await drain(r.w.worker)
    else:
        r.flag["ok"] = False  # a reconnect, new attempt or unload at that await
        release.set()
        await drain(r.w.worker)
    assert r.calls == 1
    assert r.ledger["attempt"]["state"] == "aborted_before_dispatch" and r.ledger["uncertain"] is False
    assert r.ledger["acknowledged"] == ack and r.ledger.get("repair_attempts", []) == []
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_person_stop_active_before_the_request_blocks_the_repair(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    with r.w.admission.person_stop_reservation("charger", lambda: r.w.identity):
        r.w.worker.request_repair(r.conf())
        await drain(r.w.worker)
    assert r.calls == 1 and "repair_attempts" not in r.ledger
    r.w.worker.close()


@pytest.mark.asyncio
async def test_a_wire_run_counts_once_even_when_the_charger_refuses_it(monkeypatch):
    enable(monkeypatch)
    r = await boot(monkeypatch)
    r.w.point.call.return_value = SimpleNamespace(status="Rejected")
    assert await r.repair() == "upload_rejected"
    assert r.calls == 2 and len(r.ledger["repair_attempts"]) == 1
    # the cooldown of the rejected intent now applies to any further repair; nothing more reaches the wire
    assert await r.repair() in ("upload_rejected", "repair_unconfirmed") and r.calls == 2
    r.w.worker.close()


# ---- confirmation (pure) ------------------------------------------------------------------------------------

def obs(at_s, mono, *, attempt="a1", conn=1):
    return {"attempt_id": attempt, "connection_id": conn, "mono": mono,
            "readback_at": (real_now() + timedelta(seconds=at_s)).isoformat()}


def latest_of(o, age=0.0):
    return {**o, "mono_age": age}


def test_confirm_mismatch_needs_a_fresh_latest_and_an_earlier_one_at_least_30s_before():
    first, second = obs(-40, 0.0), obs(0, 40.0)
    assert morek_schedule.confirm_mismatch([first], latest_of(second))
    assert not morek_schedule.confirm_mismatch([], latest_of(second))  # one odd reading
    assert not morek_schedule.confirm_mismatch([obs(-20, 20.0)], latest_of(second))  # under 30 s apart
    assert not morek_schedule.confirm_mismatch([first], latest_of(obs(-45, 40.0)))  # latest not fresh (wall)
    assert not morek_schedule.confirm_mismatch([first], latest_of(second, age=45.0))  # latest not fresh (mono)
    assert not morek_schedule.confirm_mismatch([first], latest_of(obs(60, 100.0)))  # a reading from the future
    # replay: the same readback timestamp twice (or a re-stamped reading) is not two observations
    assert not morek_schedule.confirm_mismatch([{**first, "readback_at": second["readback_at"]}], latest_of(second))
    # clock doubt: wall time says 40 s, the monotonic clock says 5 s (or the reverse)
    assert not morek_schedule.confirm_mismatch([obs(-40, 35.0)], latest_of(second))
    assert not morek_schedule.confirm_mismatch([obs(-5, -35.0)], latest_of(obs(0, 5.0)))
    # a different connection or acknowledged attempt is a different episode
    assert not morek_schedule.confirm_mismatch([obs(-40, 0.0, conn=2)], latest_of(second))
    assert not morek_schedule.confirm_mismatch([obs(-40, 0.0, attempt="a0")], latest_of(second))
    assert not morek_schedule.confirm_mismatch([{"attempt_id": "a1"}], latest_of(second))  # malformed: not confirmation
    assert not morek_schedule.confirm_mismatch([first], {"attempt_id": "a1"})


# ---- checker -> worker (real checker over the 15.3 rig, wall clock skewed with the monotonic one) -----------

class Skew:
    def __init__(self, monkeypatch):
        self.offset = timedelta(0)
        skew = self

        class Meta(type(datetime)):
            def __instancecheck__(cls, obj):
                return isinstance(obj, datetime)

        class FakeDT(datetime, metaclass=Meta):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + skew.offset

        monkeypatch.setattr(morek_schedule, "datetime", FakeDT)
        monkeypatch.setattr(morek_checker, "datetime", FakeDT)
        monkeypatch.setattr(t153, "utcnow", lambda: datetime.now(timezone.utc) + skew.offset)

    def advance(self, rig, seconds):
        self.offset += timedelta(seconds=seconds)
        rig.clock.t += seconds


def checker_rig(monkeypatch, **reply):
    skew = Skew(monkeypatch)
    rig = t153.routine(monkeypatch, differ=True, **reply)
    rig.requests = []
    rig.w.worker.request_repair = lambda c: rig.requests.append(c)
    return skew, rig


@pytest.mark.asyncio
async def test_one_odd_readback_never_requests_a_repair_and_two_under_30s_do_not_either(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    assert rig.checker.status()["class"] == t153.DIFFERS and rig.requests == []
    skew.advance(rig, 20)
    await rig.fire()
    assert rig.checker.status()["class"] == t153.DIFFERS and rig.requests == []
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_two_clean_mismatches_30s_apart_confirm_once_per_readback_and_send_nothing_themselves(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    skew.advance(rig, 31)
    await rig.fire()
    status = rig.checker.status()
    assert status["class"] == morek_schedule.CHECK_CONFIRMED and status["reason"] == "limits_or_transitions_differ"
    assert len(rig.requests) == 1 and rig.requests[0]["attempt_id"] == "a1" and rig.requests[0]["connection_id"] == 1
    assert rig.requests[0]["current"]() is True
    assert [e["class"] for e in status["events"]] == [t153.DIFFERS, morek_schedule.CHECK_CONFIRMED]
    rig.assert_untouched()  # the checker only requested: no send, no ledger or data write
    # the same episode keeps confirming on its rechecks (the worker decides, the gate and budget bound it)
    skew.advance(rig, 61)
    await rig.fire()
    assert len(rig.requests) == 2 and rig.checker.status()["events"][-1]["repeat"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("break_it", ["healthy", "unknown", "link_edge", "other_connection", "link_down", "new_attempt"])
async def test_a_break_between_two_readbacks_means_no_confirmation(monkeypatch, break_it):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    skew.advance(rig, 31)
    if break_it in ("healthy", "unknown"):
        rig.reply.pop("differ")
        if break_it == "unknown":
            rig.reply["raises"] = True
        await rig.fire()
        rig.reply.pop("raises", None)
        rig.reply["differ"] = True
        skew.advance(rig, 31)
        rig.checker.request("link_up")  # a fresh episode: it must observe twice again
        await rig.fire()
    elif break_it == "link_edge":
        rig.checker.request("link_up")
        await rig.fire()
    elif break_it == "other_connection":
        rig.monitor.connection_id = 2  # the binding of an in-flight recheck is the first connection
        await rig.fire()
    elif break_it == "link_down":
        rig.checker.note_link_down()
        rig.monitor.state = "down"
        rig.checker.request("link_up")
        rig.monitor.state = "up"
        await rig.fire()
    else:
        rig.checker.note_new_attempt()
        rig.checker.request("availability_return")
        await rig.fire()
    assert rig.requests == []
    assert rig.checker.status()["class"] != morek_schedule.CHECK_CONFIRMED


@pytest.mark.asyncio
async def test_the_confirmation_token_is_revalidated_against_link_attempt_and_unload(monkeypatch):
    skew, rig = checker_rig(monkeypatch)
    await rig.run()
    skew.advance(rig, 31)
    await rig.fire()
    token = rig.requests[0]["current"]
    assert token() is True
    rig.monitor.connection_id = 2
    assert token() is False  # reconnect to another connection
    rig.monitor.connection_id = 1
    assert token() is True
    rig.monitor.state = "down"
    assert token() is False
    rig.monitor.state = "up"
    # the repair's own attempt (named by its confirmed attempt id) keeps the token; any other attempt drops it
    rig.checker.note_new_attempt(repair="a1")
    assert token() is True
    rig.checker.note_new_attempt()
    assert token() is False
    skew.advance(rig, 31)
    rig.checker.request("link_up")
    await rig.fire()
    assert token() is False  # a new episode never revives an old token
    rig.checker.close()
    assert token() is False


@pytest.mark.asyncio
async def test_real_worker_gate_off_confirmed_by_the_checker_sends_nothing(monkeypatch):
    skew = Skew(monkeypatch)
    rig = t153.routine(monkeypatch, differ=True)
    await rig.run()
    skew.advance(rig, 31)
    await rig.fire()
    assert rig.checker.status()["class"] == morek_schedule.CHECK_CONFIRMED
    worker = rig.w.worker
    assert worker.decision["result"] == "repair_gated" and worker.repair_confirmed["state"] == "gated"
    await drain(worker)
    assert set(rig.kinds) == {"GetCompositeSchedule"}  # not one SetChargingProfile
    rig.assert_untouched()
    worker.close()


@pytest.mark.asyncio
async def test_enabled_the_checker_raises_one_repair_run_for_a_confirmation(monkeypatch):
    enable(monkeypatch)
    skew = Skew(monkeypatch)
    rig = t153.routine(monkeypatch, differ=True)
    seen = []
    rig.w.worker.trigger = lambda *a, **kw: seen.append(kw.get("kind"))
    await rig.run()
    skew.advance(rig, 31)
    await rig.fire()
    assert seen == ["repair"] and rig.w.worker._repair_request["attempt_id"] == "a1"
    assert set(rig.kinds) == {"GetCompositeSchedule"}
    rig.w.worker.close()


def test_status_repair_block_is_additive_and_codes_only():
    worker = SimpleNamespace(repair_confirmed={"state": "gated", "at": "t", "attempt_id": "a1", "result": "repair_gated"})
    status = morek_schedule.repair_status(worker, {"repair_attempts": [{"at": ago(minutes=5), "attempt_id": "a1"}]})
    assert status["gate_enabled"] is False and status["budget"]["state"] == "spacing" and status["budget"]["used"] == 1
    assert morek_schedule.repair_status(None, None)["confirmed"] is None
