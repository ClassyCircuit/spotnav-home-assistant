"""Stage 15.3: the read-only reconnect/startup schedule check.

Real checker, link monitor, worker, `async_schedule_action(..., "fetch", check=...)` and `compare_schedule`; the OCPP
point, HA timers, storage and admission authorization are the usual mocked boundaries. Nothing here proves what the
installed OCPP integration answers to GetCompositeSchedule or physical behavior.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_153_schedule_check.py
"""

import asyncio
import copy
import logging
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_checker
from custom_components.spotnav.execution.morek_checker import (
    CHECK_MIN_INTERVAL_S, CHECK_RECHECK_LIMIT, CHECK_SETTLE_S, MorekScheduleChecker)
from custom_components.spotnav.execution.morek_link import MorekLinkMonitor
from .test_morek_worker import drain, setup

HEALTHY, UNKNOWN, DIFFERS = morek_schedule.CHECK_HEALTHY, morek_schedule.CHECK_UNKNOWN, morek_schedule.CHECK_DIFFERS


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat()


# ---- builders ----------------------------------------------------------------------------------------------

def routine_profile(now=None):
    now = now or utcnow()
    return morek_schedule.profile_for(((now + timedelta(hours=1), now + timedelta(hours=2)),), 16, now)


def record_for(profile, *, kind="routine", pause_id=None, override_id=None, now=None):
    now = now or utcnow()
    attempt = {"id": "a1", "state": "accepted", "fingerprint": "f1", "profile": profile, "at": iso(now),
               "revision": 4, "source": "worker", "ack": "Accepted"}
    if pause_id:
        attempt["pause_id"] = pause_id
    if override_id:
        attempt["override_id"] = override_id
    record = {"schema": 1, "entry_id": "charger", "desired": None, "attempt": attempt, "verified": None,
              "uncertain": False, "removal": None,
              "acknowledged": {"id": "a1", "fingerprint": "f1", "at": iso(now), "profile": profile, "revision": 4,
                               "routine": kind == "routine"}}
    return record


def pause_record(profile, now=None):
    record = record_for(profile, kind="pause", pause_id="p1", now=now)
    record["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p1",
                                "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    return record


def override_record(now=None):
    now = now or utcnow()
    start, end = now - timedelta(minutes=5), now + timedelta(minutes=30)
    profile = morek_schedule.charge_now_profile(start, end, (), 16, now)
    record = record_for(profile, kind="override", override_id="a" * 32, now=now)
    record["charge_now"] = {"version": 1, "id": "a" * 32, "station_id": morek_schedule.MOREK_STATION_ID,
                            "connector_id": 1, "start": iso(start), "end": iso(end)}
    return record


def composite(profile, *, differ=False, status="Accepted", short=False, connector_id=1):
    """What a charger would report for `profile` from now (absolute change instants, amps)."""
    schedule = profile["chargingSchedule"]
    start = datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00"))
    expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"]) for p in schedule["chargingSchedulePeriod"]]
    cs = utcnow().replace(microsecond=0)
    current = next(limit for at, limit in reversed(expected) if at <= cs) if expected[0][0] <= cs else 0
    if differ:
        current = 16 if current == 0 else 0
    periods = [{"startPeriod": 0, "limit": current}]
    periods += [{"startPeriod": int((at - cs).total_seconds()), "limit": limit} for at, limit in expected if at > cs]
    duration = int((expected[-1][0] + timedelta(hours=1) - cs).total_seconds()) + 60
    if short:
        duration = 600
    return SimpleNamespace(status=status, connector_id=connector_id, schedule_start=iso(cs),
                           charging_schedule={"chargingRateUnit": "A", "duration": duration,
                                              "chargingSchedulePeriod": periods})


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Rig:
    """Real worker, checker and fetch path over mocked OCPP, timers and storage."""

    def __init__(self, monkeypatch, record, profile, **reply):
        self.w = w = setup(monkeypatch)
        self.profile, self.reply = profile, dict(reply)
        w.ledger.value = record
        self.data = {"sent_at": record["acknowledged"]["at"] if record else None, "attempt_id": "a1", "ack": "Accepted",
                     "profile": profile, "verified": True, "effective": None,
                     "verification": {"pending": False, "reason": "matched", "attempts": 1}}
        self.disk = w.hass.data.setdefault(morek_schedule._DATA_KEY, {})  # filled below
        w.hass.data[morek_schedule._DATA_KEY]["charger"] = (self.data, SimpleNamespace(async_save=AsyncMock()),
                                                             asyncio.Lock())
        self.kinds = []
        self.reads = 0

        async def call(request):
            self.kinds.append(request.kind)
            if request.kind != "GetCompositeSchedule":
                raise AssertionError("the checker must send nothing: " + request.kind)
            self.reads += 1
            if self.before_reply is not None:
                await self.before_reply()
            if self.reply.get("raises"):
                raise TimeoutError
            return composite(self.profile, **{k: v for k, v in self.reply.items() if k != "raises"})

        self.before_reply = None
        w.point.call = AsyncMock(side_effect=call)
        entry = SimpleNamespace(entry_id="charger", async_on_unload=lambda _: None,
                                runtime_data=SimpleNamespace(morek_worker=w.worker))
        monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
        monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
        monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
        monkeypatch.setattr(morek_checker, "command_admission", lambda *_: w.admission)
        monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
            SetChargingProfile=lambda **kw: SimpleNamespace(kind="SetChargingProfile", **kw),
            ClearChargingProfile=lambda **kw: SimpleNamespace(kind="ClearChargingProfile", **kw),
            GetCompositeSchedule=lambda **kw: SimpleNamespace(kind="GetCompositeSchedule", **kw))))
        self.timers = []

        def later(_hass, delay, action):
            timer = SimpleNamespace(delay=delay, action=action, cancelled=False)
            timer.cancel = lambda: setattr(timer, "cancelled", True)
            self.timers.append(timer)
            return timer.cancel

        monkeypatch.setattr(morek_checker, "async_call_later", later)
        self.monitor = SimpleNamespace(state="up", connection_id=1)
        w.worker.link_monitor = self.monitor
        self.clock = Clock()
        self.checker = w.worker.checker = MorekScheduleChecker(w.hass, "charger", w.worker, monotonic=self.clock)
        w.hass.data["spotnav_morek_checker"] = {"charger": self.checker}
        self.baseline = (copy.deepcopy(self.data), copy.deepcopy(w.ledger.value))

    def live(self):
        return [t for t in self.timers if not t.cancelled]

    async def fire(self):
        """Run the newest live timer's target exactly as HA would (a plain call on the loop), then wait for the task."""
        timer = self.live()[-1]
        timer.cancelled = True
        timer.action(utcnow())
        while self.checker._task is not None:  # noqa: SLF001
            await self.checker._task  # noqa: SLF001

    async def run(self, trigger="link_up"):
        self.checker.request(trigger)
        await self.fire()
        return self.checker.status()

    def assert_untouched(self):
        assert self.w.ledger.writes == []
        assert self.w.ledger.value == self.baseline[1]
        assert self.data == self.baseline[0]
        self.w.hass.data[morek_schedule._DATA_KEY]["charger"][1].async_save.assert_not_awaited()
        assert set(self.kinds) <= {"GetCompositeSchedule"}


def routine(monkeypatch, **reply):
    profile = routine_profile()
    return Rig(monkeypatch, record_for(profile), profile, **reply)


# ---- classes: zero sends, nothing written ------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "klass", "reason"), [
    ({}, HEALTHY, "matched"),
    ({"differ": True}, DIFFERS, "limits_or_transitions_differ"),
    ({"raises": True}, UNKNOWN, "readback_unavailable"),
    ({"status": "Rejected"}, UNKNOWN, "readback_unavailable"),
    ({"short": True}, UNKNOWN, "coverage_too_short"),
    ({"connector_id": 2}, UNKNOWN, "readback_unavailable"),
])
async def test_every_class_sends_nothing_and_writes_nothing(monkeypatch, reply, klass, reason):
    rig = routine(monkeypatch, **reply)
    status = await rig.run()
    assert (status["class"], status["reason"]) == (klass, reason)
    assert rig.reads == 1 and status["rechecks"] == 0
    assert (status["readback_at"] is not None) == (reply.get("raises") is None and "status" not in reply
                                                    and "connector_id" not in reply)
    rig.assert_untouched()
    assert [bool(t.delay == 30) for t in rig.live()] == ([True] if klass == DIFFERS else [])


@pytest.mark.asyncio
async def test_pause_hold_and_charge_now_own_profile_are_checked(monkeypatch):
    held = morek_schedule.held_off_profile(utcnow() - timedelta(seconds=20))
    rig = Rig(monkeypatch, pause_record(held), held)
    assert (await rig.run())["class"] == HEALTHY
    rig.assert_untouched()
    rig = Rig(monkeypatch, pause_record(held), held, differ=True)
    assert (await rig.run())["class"] == DIFFERS
    rig.assert_untouched()
    now_record = override_record()
    rig = Rig(monkeypatch, now_record, now_record["acknowledged"]["profile"])
    assert (await rig.run())["class"] == HEALTHY
    rig.assert_untouched()


@pytest.mark.parametrize(("change", "reason"), [
    (lambda r: r.update(uncertain=True), "outcome_uncertain"),
    (lambda r: r["attempt"].update(state="rejected", id="a2"), "newer_attempt"),
    (lambda r: r["attempt"].update(state="uncertain", id="a2"), "newer_attempt"),
    (lambda r: r.update(acknowledged=None), "no_acknowledged_intent"),
    (lambda r: r.update(schedule_pause={"id": "p9"}), "intent_changed"),
    (lambda r: r.update(charge_now={"id": "c", "end": iso(utcnow() + timedelta(hours=1))}), "intent_changed"),
])
def test_candidate_refuses_everything_that_is_not_the_latest_settled_acknowledged_intent(change, reason):
    record = record_for(routine_profile())
    change(record)
    assert morek_schedule.check_candidate(record, utcnow())[2] == reason
    assert morek_schedule.check_candidate(record_for(routine_profile()), utcnow())[2] is None


def test_candidate_refuses_pending_upload_verification_and_expired_or_replaced_intents():
    record = record_for(routine_profile())
    assert morek_schedule.check_candidate(record, utcnow(), sending="a2")[2] == "upload_pending"
    assert morek_schedule.check_candidate(record, utcnow(), verification_timer=True)[2] == "verification_pending"
    fresh = {"verified": False, "verification": {"attempts": 0}}
    assert morek_schedule.check_candidate(record, utcnow(), dispatched="a1", data=fresh)[2] == "verification_pending"
    assert morek_schedule.check_candidate(record, utcnow(), dispatched="a1",
                                          data={"verified": True})[2] is None
    old = utcnow() - timedelta(hours=5)
    expired = record_for(morek_schedule.profile_for(((old + timedelta(hours=1), old + timedelta(hours=2)),), 16, old))
    assert morek_schedule.check_candidate(expired, utcnow())[2] == "intent_expired"
    over = override_record(utcnow() - timedelta(hours=2))
    assert morek_schedule.check_candidate(over, utcnow())[2] == "intent_expired"
    assert morek_schedule.check_candidate(None, utcnow())[2] == "no_intent"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    lambda r: r.update(uncertain=True),
    lambda r: r["attempt"].update(state="rejected", id="a2"),
])
async def test_unavailable_coverage_uncertain_pending_and_expired_are_unknown_with_no_read(monkeypatch, change):
    profile = routine_profile()
    record = record_for(profile)
    change(record)
    rig = Rig(monkeypatch, record, profile)
    status = await rig.run()
    assert status["class"] == UNKNOWN and rig.reads == 0
    rig.assert_untouched()
    old = utcnow() - timedelta(hours=5)
    stale = morek_schedule.profile_for(((old + timedelta(hours=1), old + timedelta(hours=2)),), 16, old)
    rig = Rig(monkeypatch, record_for(stale), stale)
    assert (await rig.run())["reason"] == "intent_expired" and rig.reads == 0
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_pending_upload_or_verification_is_never_checked_and_the_newer_attempt_is_untouched(monkeypatch):
    rig = routine(monkeypatch)
    rig.w.hass.data["spotnav_morek_sending"] = {"charger": "a2"}
    assert (await rig.run())["reason"] == "upload_pending" and rig.reads == 0
    rig.w.hass.data["spotnav_morek_sending"] = {}
    rig.w.hass.data[morek_schedule._VERIFY_KEY] = {"charger": object()}
    assert (await rig.run())["reason"] == "verification_pending" and rig.reads == 0
    rig.assert_untouched()
    # a newer attempt (uncertain, verification fields set): the ledger and data stay byte-for-byte as they were
    newer = routine_profile()
    record = record_for(newer)
    record["attempt"] = {**record["attempt"], "id": "a2", "state": "uncertain"}
    record["uncertain"] = True
    record["verified"] = None
    rig = Rig(monkeypatch, record, newer)
    assert (await rig.run())["class"] == UNKNOWN and rig.reads == 0
    rig.assert_untouched()


# ---- triggers, dedupe, flapping, startup --------------------------------------------------------------------

class Wiring:
    """Real monitor over the Rig: its readings are scripted, its edges reach the real checker."""

    def __init__(self, rig):
        self.rig = rig
        self.now = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
        self.point = object()
        self.reading = ("up", self.point, None)
        self.monitor = MorekLinkMonitor(rig.w.hass, "charger", rig.w.worker, read=lambda: self.reading,
                                        now=lambda: self.now)
        rig.w.worker.link_monitor = self.monitor
        self.triggers = []  # the monitor's recovery trigger is recorded; the real reconcile has its own test
        rig.w.worker.trigger = lambda *a, **k: self.triggers.append(k.get("kind"))

    def set(self, state, point="same", boot=None):
        self.reading = (state, self.point if point == "same" else point, boot)

    def poll(self, advance=30):
        self.now += timedelta(seconds=advance)
        self.rig.clock.t += advance
        self.monitor.check()


@pytest.mark.asyncio
async def test_startup_with_the_link_up_seeds_exactly_one_check_and_polling_adds_none(monkeypatch):
    rig = routine(monkeypatch)
    wiring = Wiring(rig)
    wiring.monitor.check()  # seeded up: startup
    assert [t.delay for t in rig.live()] == [CHECK_SETTLE_S]
    await rig.fire()
    assert rig.reads == 1 and rig.checker.status()["class"] == HEALTHY
    for _ in range(6):  # no edge: no periodic OCPP readback, no timer
        wiring.poll()
    assert rig.reads == 1 and rig.live() == []
    assert rig.checker.events[-1]["trigger"] == "startup"
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_startup_with_the_link_down_waits_for_the_link_up_edge(monkeypatch):
    rig = routine(monkeypatch)
    wiring = Wiring(rig)
    wiring.set("down")
    wiring.monitor.check()
    assert rig.live() == [] and rig.reads == 0
    wiring.set("up")
    wiring.poll()
    assert [t.delay for t in rig.live()] == [CHECK_SETTLE_S]
    await rig.fire()
    assert rig.reads == 1 and rig.checker.events[-1]["trigger"] == "link_up"
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_one_reconnect_check_dedupes_burst_edges_and_a_changed_point_object_is_an_edge(monkeypatch):
    rig = routine(monkeypatch)
    wiring = Wiring(rig)
    wiring.monitor.check()
    await rig.fire()
    first = rig.reads
    wiring.set("down")
    wiring.poll(1)
    wiring.set("up")
    wiring.poll(1)
    wiring.set("up", point=object())  # a new connection while up: another edge
    wiring.poll(1)
    assert len(rig.live()) == 1  # three edges within the settle window: one pending check
    await rig.fire()
    assert rig.reads == first + 1 and rig.checker.events[-1]["trigger"] in ("startup", "link_up", "connection_change")
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_flapping_link_is_bounded_to_one_check_per_minimum_interval(monkeypatch):
    rig = routine(monkeypatch)
    wiring = Wiring(rig)
    wiring.monitor.check()
    await rig.fire()
    starts = [rig.clock.t]
    reads = rig.reads
    for _ in range(10):
        wiring.set("down")
        wiring.poll(5)
        wiring.set("up")
        wiring.poll(5)
        # at most one live timer, never earlier than the minimum interval after the last start
        assert len(rig.live()) == 1
        assert rig.live()[0].delay >= CHECK_MIN_INTERVAL_S - (rig.clock.t - starts[0])
    assert rig.reads == reads
    await rig.fire()
    assert rig.reads == reads + 1
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_availability_return_and_boot_signal_request_a_check_without_changing_the_reconcile(monkeypatch):
    rig = routine(monkeypatch)
    worker = rig.w.worker
    triggers = []
    worker.trigger = lambda *a, **k: triggers.append(k.get("kind"))
    generation = worker.suspend_for_availability_change()
    assert rig.live() == []  # a suspension alone checks nothing
    worker.resume_after_availability_change(generation)
    assert [t.delay for t in rig.live()] == [CHECK_SETTLE_S]
    assert triggers == [None, None]  # the existing reconcile triggers (suspend, resume) are unchanged
    await rig.fire()
    assert rig.checker.events[-1]["trigger"] == "availability_return"
    wiring = Wiring(rig)
    wiring.reading = ("up", wiring.point, 1)
    wiring.monitor.check()  # seeds (startup check) and the boot counter
    await rig.fire()
    wiring.reading = ("up", wiring.point, 2)
    wiring.poll()
    assert len(rig.live()) == 1
    assert rig.checker._trigger == "boot"  # noqa: SLF001
    worker.close()


@pytest.mark.asyncio
async def test_the_checker_never_alters_worker_trigger_continuity_decision_or_ledger(monkeypatch):
    rig = routine(monkeypatch)
    worker = rig.w.worker
    worker.last_trigger, worker.continuity = "price", {"preserved": True}
    worker.decision = {"result": "unchanged"}
    worker.trigger = Mock(side_effect=AssertionError("a check never triggers the worker"))
    kinds, serial = set(worker._kinds), worker._serial  # noqa: SLF001
    await rig.run()
    assert (worker.last_trigger, worker.continuity, worker.decision) == ("price", {"preserved": True},
                                                                         {"result": "unchanged"})
    assert (set(worker._kinds), worker._serial) == (kinds, serial)  # noqa: SLF001
    rig.assert_untouched()


# ---- rechecks ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_mismatch_is_rechecked_at_30_60_120_then_300_at_most_twelve_times(monkeypatch):
    rig = routine(monkeypatch, differ=True)
    await rig.run()
    delays = [rig.live()[0].delay]
    for _ in range(CHECK_RECHECK_LIMIT):
        await rig.fire()
        if rig.live():
            delays.append(rig.live()[0].delay)
    assert delays == [30, 60, 120] + [300] * 9
    assert rig.checker.status()["rechecks"] == CHECK_RECHECK_LIMIT and rig.live() == []
    assert rig.reads == 1 + CHECK_RECHECK_LIMIT and rig.checker.status()["class"] == DIFFERS
    rig.assert_untouched()


@pytest.mark.asyncio
async def test_recheck_that_matches_ends_the_episode_and_a_changed_class_is_logged_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=morek_checker.__name__)
    rig = routine(monkeypatch, differ=True)
    await rig.run()
    await rig.fire()  # still differs: a repeat counts, no second line
    rig.reply = {}
    await rig.fire()
    status = rig.checker.status()
    assert status["class"] == HEALTHY and status["rechecks"] == 2 and rig.live() == []
    classes = [event["class"] for event in status["events"]]
    assert classes == [DIFFERS, HEALTHY] and status["events"][0]["repeat"] == 1
    lines = [r.getMessage() for r in caplog.records if "schedule check" in r.getMessage()]
    assert len(lines) == 2 and all("nothing sent" in line for line in lines)
    assert not any(key in str(status) for key in ("profile", "chargingSchedule", "station"))


@pytest.mark.asyncio
async def test_link_edge_new_attempt_and_unload_cancel_the_episode(monkeypatch):
    for stop in ("edge", "attempt", "unload", "down"):
        rig = routine(monkeypatch, differ=True)
        await rig.run()
        assert [t.delay for t in rig.live()] == [30]
        before = rig.reads
        rig.clock.t += 100
        if stop == "edge":
            rig.checker.request("link_up")
            assert [t.delay for t in rig.live()] == [CHECK_SETTLE_S]  # the old recheck is gone, one new check
            assert rig.checker.status()["rechecks"] == 0
        elif stop == "attempt":
            rig.checker.note_new_attempt()
            assert rig.live() == []
            assert (rig.checker.status()["class"], rig.checker.status()["reason"]) == (UNKNOWN, "newer_attempt")
        elif stop == "down":
            rig.checker.note_link_down()
            assert rig.live() == [] and rig.checker.status()["reason"] == "link_down"
        else:
            rig.checker.close()
            assert rig.live() == []
            rig.checker.request("link_up")
            assert rig.live() == []
        assert rig.reads == before
        rig.assert_untouched()


@pytest.mark.asyncio
async def test_a_real_worker_send_ends_the_check_episode(monkeypatch):
    rig = routine(monkeypatch, differ=True)
    await rig.run()
    assert [t.delay for t in rig.live()] == [30]
    rig.w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
                          "acknowledged": None, "verified": None}
    rig.w.worker.trigger(kind="settings")
    await drain(rig.w.worker)
    assert rig.live() == [] and rig.checker.status()["reason"] == "newer_attempt"
    assert "SetChargingProfile" in rig.kinds  # only the worker's own guarded send, never the checker
    rig.w.worker.close()


# ---- races across awaits ----------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["link_edge", "new_attempt", "ledger_changed", "unload", "generation", "link_down_state"])
async def test_stale_results_are_discarded_after_the_read(monkeypatch, race):
    rig = routine(monkeypatch, differ=True)
    async def interfere():
        if race == "link_edge":
            rig.monitor.connection_id = 2
        elif race == "new_attempt":
            rig.checker.note_new_attempt()
        elif race == "ledger_changed":
            rig.w.ledger.value["acknowledged"] = {**rig.w.ledger.value["acknowledged"], "id": "a2"}
            rig.w.ledger.value["attempt"] = {**rig.w.ledger.value["attempt"], "id": "a2"}
        elif race == "unload":
            rig.checker.close()
        elif race == "generation":
            from custom_components.spotnav.execution.command_admission import physical_connector
            rig.w.admission._person_stops[physical_connector(rig.w.identity)] = True
        else:
            rig.monitor.state = "down"

    rig.before_reply = interfere
    rig.checker.request("link_up")
    timer = rig.live()[-1]
    timer.cancelled = True
    timer.action(utcnow())
    task = rig.checker._task  # noqa: SLF001
    if task is not None:
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert rig.reads == 1
    status = rig.checker.status()
    assert status["class"] is None and status["rechecks"] == 0  # nothing differs was published
    assert not any(e["class"] == DIFFERS for e in status["events"])
    assert all(t.cancelled for t in rig.timers[1:]) if race in ("unload", "new_attempt") else True
    assert set(rig.kinds) == {"GetCompositeSchedule"}
    assert rig.w.ledger.writes == []


# ---- timer target, status field ---------------------------------------------------------------------------

def test_timer_target_is_a_callback_job_not_an_executor_job():
    from homeassistant.core import HassJob, HassJobType

    checker = MorekScheduleChecker(SimpleNamespace(), "charger", SimpleNamespace())
    assert HassJob(checker._async_fire).job_type is HassJobType.Callback  # noqa: SLF001


@pytest.mark.asyncio
async def test_status_check_field_is_additive_and_holds_codes_only(monkeypatch):
    rig = routine(monkeypatch)
    assert rig.checker.status() == {"class": None, "at": None, "readback_at": None, "reason": None,
                                    "rechecks": 0, "events": []}
    status = await rig.run()
    assert set(status) == {"class", "at", "readback_at", "reason", "rechecks", "events"}
    assert set(status["events"][0]) == {"at", "last_at", "trigger", "class", "reason", "readback_at", "repeat"}
    assert all(isinstance(value, (str, int, type(None), list)) for value in status.values())
    source = open(morek_schedule.__file__, encoding="utf-8").read()
    assert '"check": checker.status() if checker is not None else None' in source


@pytest.mark.asyncio
async def test_existing_fetch_still_writes_its_verification_while_a_check_does_not(monkeypatch):
    """The unchanged manual/verification fetch keeps its behavior (it publishes `effective`); only `check=` is writeless."""
    rig = routine(monkeypatch)
    rig.data["verified"] = False
    result = await morek_schedule.async_schedule_action(rig.w.hass, "charger", "fetch")
    assert rig.w.ledger.writes  # the old path records its comparison (`verified`); `check=` never does
    with pytest.raises(morek_schedule.ScheduleRefused):
        await morek_schedule.async_schedule_action(rig.w.hass, "charger", "send", "x", check={"current": lambda: True})


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["connection", "epoch", "generation", "link_state"])
async def test_a_result_that_goes_stale_between_the_read_and_its_publication_is_discarded(monkeypatch, race):
    """The checker's own apply-time guard, independent of the guards inside the locked read."""
    rig = routine(monkeypatch, differ=True)
    original = morek_schedule.async_schedule_action

    async def late(*args, **kwargs):
        value = await original(*args, **kwargs)  # the read finished and was current inside the lock
        if race == "connection":
            rig.monitor.connection_id = 9
        elif race == "epoch":
            rig.checker._epoch += 1  # noqa: SLF001
        elif race == "link_state":
            rig.monitor.state = "unknown"
        else:
            from custom_components.spotnav.execution.command_admission import physical_connector
            rig.w.admission._person_stops[physical_connector(rig.w.identity)] = True
        return value

    monkeypatch.setattr(morek_schedule, "async_schedule_action", late)
    await rig.run()
    assert rig.reads == 1 and rig.checker.status()["class"] is None and rig.checker.events == deque() \
        and not [t for t in rig.live() if t.delay == 30]
    rig.assert_untouched()
