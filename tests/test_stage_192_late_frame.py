"""Stage 19.2/19.9a: the late-old-frame guard after a replacement of an ambiguous upload, and the pre-wire-abort audit.

Real worker, real checker, real send path (`_send_profile_shared`), real connector lock/generation and the real
fetch/compare path; OCPP, HA timers, storage and (simulated) admission authorization are the usual mocked boundaries.
The "charger" is a scripted stand-in: a late old frame is simulated by overwriting what it reports. Nothing here proves
firmware ordering, replacement semantics or physical charging.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_192_late_frame.py
"""

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_checker, morek_worker
from custom_components.spotnav.execution.command_admission import physical_connector
from . import test_stage_153_schedule_check as t153
from .test_stage_192_recovery import _legacy, _pending
from .test_morek_worker import drain

SET, GET = "SetChargingProfile", "GetCompositeSchedule"


class Skew:
    """One shared offset for the worker, the send path, the checker and the readback builder."""

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

        for module in (morek_schedule, morek_checker, morek_worker):
            monkeypatch.setattr(module, "datetime", FakeDT)
        monkeypatch.setattr(t153, "utcnow", lambda: datetime.now(timezone.utc) + skew.offset)

    def advance(self, rig, seconds):
        self.offset += timedelta(seconds=seconds)
        rig.clock.t += seconds


class Late:
    """A started worker + checker over a scripted charger, begun from the reported legacy ambiguous record."""

    def __init__(self, monkeypatch, record=None, *, start=True, share=None):
        profile = t153.routine_profile()
        self.rig = rig = t153.Rig(monkeypatch, t153.record_for(profile), profile)
        self.skew = Skew(monkeypatch)  # after the Rig: its setup() pins the worker clock, this replaces that
        self.w = w = rig.w
        real = datetime.now(timezone.utc)
        w.planner.current.proposal.shown_periods = ((real + timedelta(hours=1), real + timedelta(hours=2)),)
        self.charger = None  # the profile the scripted charger last ACKed
        self.differ = False  # True: a late old frame has overridden it, so reads report the wrong limits
        self.sets, self.reads = [], 0
        self.set_status = "Accepted"
        self.offline = False

        async def call(request):
            if request.kind == SET:
                self.sets.append(copy.deepcopy(request.cs_charging_profiles))
                if self.set_status == "Accepted":
                    self.charger = copy.deepcopy(request.cs_charging_profiles)
                    self.differ = False  # the newest accepted frame is the one in force again
                return SimpleNamespace(status=self.set_status)
            if request.kind != GET:
                raise AssertionError("never any other call: " + request.kind)
            self.reads += 1
            if self.offline:
                raise TimeoutError
            return t153.composite(self.charger or self.rig.profile, differ=self.differ)

        w.point.call = AsyncMock(side_effect=call)
        w.ledger.value = copy.deepcopy(record) if record is not None else _legacy(pending_resume=_pending())
        if share is not None:  # a restart: only the durable record carries over
            w.ledger.value = copy.deepcopy(share)
        if start:
            w.worker.start()

    @property
    def ledger(self):
        return self.w.ledger.value

    async def settle(self, rounds=6):
        import asyncio
        for _ in range(rounds):
            await asyncio.sleep(0)
        await drain(self.w.worker)
        while self.rig.checker._task is not None:  # noqa: SLF001
            await self.rig.checker._task  # noqa: SLF001
        for _ in range(rounds):
            await asyncio.sleep(0)

    def timers(self, *, longer_than=0):
        return [t for t in self.rig.live() if t.delay > longer_than]

    async def fire(self, timer):
        timer.cancelled = True
        timer.action(t153.utcnow())
        await self.settle()

    async def fire_newest(self):
        """The newest live CHECK timer (settle/recheck), never the long transition watch."""
        timer = [t for t in self.rig.live() if t.delay < 1000][-1]
        timer.cancelled = True
        timer.action(t153.utcnow())
        await self.settle()

    async def fire_transition(self):
        """Advance to the armed transition watch and fire it exactly as HA would; the check then runs."""
        watch = [t for t in self.timers(longer_than=1000)]
        assert watch, "no transition watch is armed"
        self.skew.advance(self.rig, watch[-1].delay + 1)
        await self.fire(watch[-1])
        await self.fire_newest()  # the settle timer of the requested check -> read #1

    async def confirm(self):
        """After a first differing read: the second one 31 s later confirms it (and raises the worker's request)."""
        self.skew.advance(self.rig, 31)
        await self.fire_newest()


async def replaced(monkeypatch, **kw):
    """The reported scenario, converged: the guarded resolve was sent and ACKed; the risk record stands."""
    late = Late(monkeypatch, **kw)
    await late.settle()
    assert len(late.sets) == 1 and late.ledger["attempt"]["resolve"] is True, late.w.worker.reason
    assert late.ledger["supersession"]["state"] == "replacement_acknowledged"
    # the one-shot post-send verification (30/75/120 s, its own timers are mocked away here) has finished: the
    # checker refuses to read while it is pending
    late.rig.data.update(verified=True, verification={"pending": False, "reason": "matched", "attempts": 1})
    late.w.hass.data.get(morek_schedule._VERIFY_KEY, {}).pop("charger", None)  # noqa: SLF001
    return late


def stop(late):
    late.w.admission._person_stops[physical_connector(late.w.identity)] = True  # noqa: SLF001


# ------------------------------------------------------------------------------ transition check after a late frame

@pytest.mark.asyncio
async def test_old_write_after_the_new_ack_is_found_at_the_next_transition_and_reasserted_once_paced(monkeypatch):
    late = await replaced(monkeypatch)
    first = late.ledger["acknowledged"]["id"]
    assert late.charger == late.sets[0]
    assert late.rig.checker.status()["next_transition_check_at"] is not None  # armed by the accepted replacement
    # the old frame lands AFTER the new ACK (firmware ordering is unobserved): the charger now reports a hold
    late.differ = True
    reads = late.reads
    await late.fire_transition()
    assert late.reads == reads + 1 and late.rig.checker.status()["class"] == morek_schedule.CHECK_DIFFERS
    assert len(late.sets) == 1  # one differing read is never enough
    await late.confirm()
    assert morek_schedule.CHECK_CONFIRMED in [e["class"] for e in late.rig.checker.events]
    await late.settle()
    # exactly one guarded reassert: the SAME current intent, a new attempt, on the one profile id
    assert len(late.sets) == 2 and late.sets[1]["chargingProfileId"] == morek_schedule.PROFILE_ID
    # the window has begun by now, so the same intent is carried as the ACTIVE window: 16 A to its end, no 0 A gap
    assert [p["limit"] for p in late.sets[1]["chargingSchedule"]["chargingSchedulePeriod"]] == [16, 0]
    record = late.ledger
    assert record["acknowledged"]["id"] != first and record["attempt"]["state"] == "accepted"
    assert "repair_attempts" not in record and "repair_escalation" not in record  # the ordinary budget is not used
    reassert = record["supersession"]["reassert"]
    assert reassert["attempts"] == 1 and reassert["attempt_id"] == record["attempt"]["id"] and "prior" not in reassert
    # ACK, readback and the standing risk stay separate labels
    assert record["supersession"]["risk"] == "late_old_frame_not_excluded"
    assert record["supersession"]["state"] == "replacement_acknowledged" and record["verified"] is None
    assert late.w.worker.repair_confirmed["state"] == "sent"
    assert len([k for k in late.rig.kinds if k == "ClearChargingProfile"]) == 0
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
async def test_equivalent_readback_at_the_transition_sends_nothing_writes_nothing_and_rearms_only_one_watch(monkeypatch):
    late = await replaced(monkeypatch)
    writes, sets = len(late.w.ledger.writes), len(late.sets)
    await late.fire_transition()
    assert late.rig.checker.status()["class"] == morek_schedule.CHECK_HEALTHY and late.reads >= 1
    assert len(late.sets) == sets and len(late.w.ledger.writes) == writes
    live = [t for t in late.timers(longer_than=1000)]
    assert len(live) <= 1  # at most the next transition (none left after the last): never a polling loop
    # a link edge adds one coalesced check, not a burst, and still writes nothing
    for _ in range(3):
        late.rig.checker.request("link_up")
    await late.settle()
    await late.fire_newest()
    assert len(late.sets) == sets and len(late.w.ledger.writes) == writes
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
async def test_no_watch_without_the_standing_risk_and_none_after_the_last_transition(monkeypatch):
    # an ordinary accepted routine record (no supersession record) never arms the extra look
    late = Late(monkeypatch, record=t153.record_for(t153.routine_profile()), start=False)
    late.rig.checker.request_transition_watch()
    await late.settle()
    assert late.rig.checker.status()["next_transition_check_at"] is None
    # with the risk standing but the profile already over, nothing is armed either
    record = t153.record_for(t153.routine_profile())
    record["supersession"] = {"version": 1, "state": "replacement_acknowledged", "risk": "late_old_frame_not_excluded"}
    late = Late(monkeypatch, record=record, start=False)
    late.skew.advance(late.rig, 4 * 3600)
    late.rig.checker.request_transition_watch()
    await late.settle()
    assert late.rig.checker.status()["next_transition_check_at"] is None and late.reads == 0


@pytest.mark.asyncio
async def test_repeated_mismatch_is_paced_with_a_ceiling_and_never_locked_by_repair_budget_or_escalation(monkeypatch):
    late = await replaced(monkeypatch)
    # seed the ordinary repair machinery as exhausted AND escalated: the reassert must not depend on either
    late.ledger["repair_attempts"] = [{"at": (datetime.now(timezone.utc)).isoformat(), "attempt_id": "x1"},
                                      {"at": (datetime.now(timezone.utc)).isoformat(), "attempt_id": "x2"}]
    late.ledger["repair_escalation"] = {"at": datetime.now(timezone.utc).isoformat(),
                                        "attempt_id": late.ledger["acknowledged"]["id"]}
    assert morek_schedule.repair_budget(late.ledger, datetime.now(timezone.utc))["state"] == "exhausted"

    def conf():
        return {"attempt_id": late.ledger["acknowledged"]["id"], "connection_id": 1,
                "readback_at": datetime.now(timezone.utc).isoformat() if False else (
                    datetime.now(timezone.utc) + late.skew.offset).isoformat(),
                "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}}

    async def attempt():
        late.w.worker.request_repair(conf())
        await late.settle()
        return late.w.worker.reason

    waits = []
    for expected_sends in range(2, 8):
        before = len(late.sets)
        assert await attempt() == "upload_accepted_unverified", late.w.worker.reason
        assert len(late.sets) == before + 1
        state = late.ledger["supersession"]["reassert"]
        # an immediate repeat is paced: nothing is sent, nothing is consumed, nothing is escalated to a person
        assert await attempt() == "repair_spacing" and len(late.sets) == before + 1
        assert late.ledger["supersession"]["reassert"] == state
        assert late.w.worker.repair_confirmed["result"] == "repair_spacing"
        waits.append(state["attempts"])
        due = datetime.fromisoformat(state["next_at"])
        late.skew.advance(late.rig, (due - (datetime.now(timezone.utc) + late.skew.offset)).total_seconds() + 2)
    assert waits == [1, 2, 3, 4, 5, 6]
    # the pace follows the recovery ladder and stops growing at its ceiling: a 4 h wait, not a lock
    assert late.ledger["supersession"]["reassert"]["attempts"] == 6
    last = late.ledger["supersession"]["reassert"]
    gap = (datetime.fromisoformat(last["next_at"]) - datetime.fromisoformat(last["last_at"])).total_seconds()
    assert gap == pytest.approx(morek_schedule.REASSERT_DELAYS[-1], abs=1)
    assert "repair_attempts" in late.ledger and len(late.ledger["repair_attempts"]) == 2  # untouched
    # 24 h of quiet restarts the pace
    late.skew.advance(late.rig, 25 * 3600)
    assert morek_schedule.reassert_next_at(late.ledger, datetime.now(timezone.utc) + late.skew.offset) is None
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
async def test_without_the_standing_risk_the_ordinary_repair_budget_and_escalation_are_unchanged(monkeypatch):
    late = await replaced(monkeypatch)
    late.ledger.pop("supersession")
    late.ledger["repair_escalation"] = {"at": datetime.now(timezone.utc).isoformat(),
                                        "attempt_id": late.ledger["acknowledged"]["id"]}
    late.w.worker.request_repair({"attempt_id": late.ledger["acknowledged"]["id"], "connection_id": 1,
                                  "readback_at": (datetime.now(timezone.utc) + late.skew.offset).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    assert late.w.worker.reason == "repair_needs_person" and len(late.sets) == 1
    late.w.worker.close()
    late.rig.checker.close()


# ------------------------------------------------------------------------------ reconnect, restart, offline

@pytest.mark.asyncio
async def test_reconnect_check_with_a_late_frame_reasserts_after_confirmation_and_not_before(monkeypatch):
    late = await replaced(monkeypatch)
    late.skew.advance(late.rig, 3700)  # the link was away across the window start
    late.differ = True  # the late frame
    late.rig.checker.note_link_down()
    late.rig.checker.request("link_up")  # the existing reconnect trigger
    await late.fire_newest()
    assert late.rig.checker.status()["class"] == morek_schedule.CHECK_DIFFERS and len(late.sets) == 1
    await late.confirm()
    await late.settle()
    assert len(late.sets) == 2 and late.ledger["supersession"]["reassert"]["attempts"] == 1
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
async def test_restart_equivalent_readback_sends_nothing_and_a_persisted_pace_survives_a_mismatch(monkeypatch):
    late = await replaced(monkeypatch)
    late.differ = True
    await late.fire_transition()
    await late.confirm()
    await late.settle()
    assert len(late.sets) == 2
    durable = copy.deepcopy(late.ledger)
    late.w.worker.close()
    late.rig.checker.close()
    # restart 1: the charger is correct -> no send, nothing written
    again = Late(monkeypatch, record=durable, start=False)
    again.skew.advance(again.rig, 3800)
    again.charger = copy.deepcopy(durable["attempt"]["profile"])
    again.rig.checker.request("startup")
    await again.settle()
    await again.fire_newest()
    assert again.rig.checker.status()["class"] == morek_schedule.CHECK_HEALTHY
    assert again.sets == [] and again.w.ledger.writes == []
    again.w.worker.close()
    again.rig.checker.close()
    # restart 2: still wrong, but the PERSISTED pace is not due yet -> held, nothing sent, ledger untouched
    held = Late(monkeypatch, record=durable, start=False)
    held.skew.advance(held.rig, 3800)
    held.charger = copy.deepcopy(durable["attempt"]["profile"])
    held.w.worker.start()
    await held.settle()
    held.differ = True
    held.rig.checker.request("startup")
    await held.fire_newest()

    await held.confirm()
    await held.settle()
    assert held.sets == [] and held.w.worker.reason == "repair_spacing"
    assert held.ledger["supersession"]["reassert"] == durable["supersession"]["reassert"]
    # once the persisted time passes, the next confirmed mismatch converges
    due = datetime.fromisoformat(durable["supersession"]["reassert"]["next_at"])
    held.skew.advance(held.rig, (due - (datetime.now(timezone.utc) + held.skew.offset)).total_seconds() + 5)
    held.rig.checker.request("link_up")
    await held.fire_newest()
    await held.confirm()
    await held.settle()
    assert len(held.sets) == 1 and held.ledger["supersession"]["reassert"]["attempts"] == 2
    held.w.worker.close()
    held.rig.checker.close()


@pytest.mark.asyncio
async def test_offline_at_the_transition_reads_and_sends_nothing_and_the_next_edge_recovers(monkeypatch):
    late = await replaced(monkeypatch)
    late.differ = True
    late.rig.monitor.state = "down"
    watch = late.timers(longer_than=1000)[-1]
    late.skew.advance(late.rig, watch.delay + 1)
    reads = late.reads
    await late.fire(watch)
    await late.fire_newest()
    assert late.reads == reads and late.rig.checker.status()["reason"] == "link_unproven"
    assert len(late.sets) == 1
    late.rig.monitor.state = "up"  # the link returns: the ordinary reconnect trigger, no burst, one send
    late.rig.checker.request("link_up")
    await late.fire_newest()
    await late.confirm()
    await late.settle()
    assert len(late.sets) == 2
    late.w.worker.close()
    late.rig.checker.close()


# ------------------------------------------------------------------------------ Stop / Pause races

@pytest.mark.asyncio
async def test_person_stop_before_the_confirmed_reassert_sends_nothing_and_consumes_no_pace(monkeypatch):
    late = await replaced(monkeypatch)
    stop(late)
    late.w.worker.request_repair({"attempt_id": late.ledger["acknowledged"]["id"], "connection_id": 1,
                                  "readback_at": (datetime.now(timezone.utc) + late.skew.offset).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    assert len(late.sets) == 1 and "reassert" not in late.ledger["supersession"]
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["after_persistence", "before_dispatch"])
async def test_stop_racing_the_reassert_write_never_reaches_the_wire_and_restores_the_accepted_attempt(monkeypatch, when):
    late = await replaced(monkeypatch)
    accepted = copy.deepcopy(late.ledger["attempt"])
    pace = copy.deepcopy(late.ledger["supersession"])
    connector = physical_connector(late.w.identity)
    real_write, seen = late.w.ledger.write, {"n": 0}

    async def write(value):
        await real_write(value)
        reassert = (value.get("supersession") or {}).get("reassert")
        if reassert and reassert.get("prior"):
            seen["n"] += 1
            # 1st such write = record-first; 2nd = wire-intent marker. A Stop wins during the chosen one.
            if seen["n"] == (1 if when == "after_persistence" else 2):
                late.w.admission._generations[connector] = late.w.admission._generations.get(connector, 0) + 1  # noqa: SLF001

    late.w.ledger.write = write
    late.w.worker.request_repair({"attempt_id": accepted["id"], "connection_id": 1,
                                  "readback_at": (datetime.now(timezone.utc) + late.skew.offset).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    late.w.ledger.write = real_write
    assert len(late.sets) == 1, "a Stop that won before the wire call must stop the reassert"
    # the accepted attempt is back (the checker keeps reading it), the pace was consumed by nothing
    assert late.ledger["attempt"] == accepted and late.ledger["uncertain"] is False
    assert late.ledger["supersession"] == pace
    late.w.worker.close()
    late.rig.checker.close()


@pytest.mark.asyncio
async def test_pause_hold_is_reasserted_as_a_hold_and_a_later_stop_still_wins(monkeypatch):
    late = await replaced(monkeypatch)
    # a person's Pause arrives after the replacement: the hold is the current acknowledged intent
    from .test_stage_192_recovery import _owner
    _owner(monkeypatch, late.w)
    await morek_schedule.async_record_owned_pause(late.w.hass, "charger")
    await late.settle()
    assert len(late.sets) == 2 and {p["limit"] for p in late.sets[1]["chargingSchedule"]["chargingSchedulePeriod"]} == {0}
    late.differ = True  # an old frame overrides the hold
    late.w.worker.request_repair({"attempt_id": late.ledger["acknowledged"]["id"], "connection_id": 1,
                                  "readback_at": (datetime.now(timezone.utc) + late.skew.offset).isoformat(),
                                  "current": lambda: True, "facts": {"current_wrong": True, "diff_in_s": 0.0}})
    await late.settle()
    assert len(late.sets) == 3 and {p["limit"] for p in late.sets[2]["chargingSchedule"]["chargingSchedulePeriod"]} == {0}
    assert late.ledger["schedule_pause"]["type"] == "pause_until_resumed"
    late.w.worker.close()
    late.rig.checker.close()


# ------------------------------------------------------------------------------ _mark_not_sent during resolve

def _resolve_attempt_record(*, with_prior=True, marker=None):
    """A crash right after the record-first write of a resolve attempt (pre-wire marker only)."""
    legacy = _legacy(pending_resume=_pending())
    prior = {"attempt": copy.deepcopy(legacy["attempt"]), "recovery": None, "supersession": None, "history": None,
             "desired": None, "verified": None, "promoted": "r" * 32, "pause": copy.deepcopy(legacy["schedule_pause"]),
             "pending_resume": copy.deepcopy(legacy["pending_resume"]), "resume_interrupted": None}
    record = copy.deepcopy(legacy)
    record["attempt"] = {"fingerprint": "new", "at": datetime.now(timezone.utc).isoformat(), "id": "n" * 32,
                         "state": "uncertain", "source": "worker", "dispatch_class": marker or "pre_wire",
                         "resolve": True, "replaces": "o" * 32, **({"resolve_prior": prior} if with_prior else {})}
    record["unknown_history"] = [{"attempt_id": "o" * 32, "outcome": "unknown", "superseded_by": "n" * 32}]
    record["supersession"] = {"version": 1, "state": "pending", "old_attempt_id": "o" * 32, "attempt_id": "n" * 32,
                              "since": record["attempt"]["at"], "risk": "late_old_frame_not_excluded"}
    record["recovery"] = {"version": 1, "attempts": 1, "last_at": record["attempt"]["at"], "attempt_id": "n" * 32,
                          "next_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    record["schedule_pause"] = {"version": 1, "type": "resume_requested", "id": "r" * 32,
                                "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    record.pop("pending_resume")
    record["resume_authorized"] = {"id": "r" * 32, "at": record["attempt"]["at"], "from": "pending_resume"}
    return record


def test_mark_not_sent_on_a_resolve_restores_the_original_ambiguous_hazard():
    record = _resolve_attempt_record()
    morek_schedule._mark_not_sent(record, "n" * 32, "validation_before_dispatch")
    assert record["uncertain"] is True and record["attempt"]["id"] == "o" * 32 and record["attempt"]["state"] == "uncertain"
    assert all(key not in record for key in ("supersession", "unknown_history", "recovery", "resume_authorized"))
    assert record["schedule_pause"]["type"] == "pause_until_resumed" and record["pending_resume"]["id"] == "r" * 32
    assert morek_schedule.recoverable_ambiguous(record) and morek_schedule.valid_pending_resume(record) is not None
    assert morek_schedule.recovery_due(record, datetime.now(timezone.utc), immediate=True)
    assert morek_schedule.upload_outcome_class(record)["class"] == "ambiguous"


def test_a_later_stop_is_never_overwritten_by_the_restore():
    record = _resolve_attempt_record()
    record["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "s" * 32,
                                "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    record.pop("resume_authorized")
    morek_schedule._mark_not_sent(record, "n" * 32, "validation_after_persistence")
    assert record["schedule_pause"]["id"] == "s" * 32 and "pending_resume" not in record
    assert record["uncertain"] is True and record["attempt"]["id"] == "o" * 32


def test_a_resolve_record_without_a_prior_is_never_released_as_settled():
    record = _resolve_attempt_record(with_prior=False)
    morek_schedule._mark_not_sent(record, "n" * 32, "validation_before_dispatch")
    assert record["uncertain"] is True and morek_schedule.recoverable_ambiguous(record)
    assert "recovery" not in record  # this replacement consumed no pace


def test_an_ordinary_attempt_is_still_released_by_its_proof():
    record = {"uncertain": True, "attempt": {"id": "a" * 32, "state": "uncertain", "dispatch_class": "pre_wire"}}
    morek_schedule._mark_not_sent(record, "a" * 32, "validation_before_dispatch")
    assert record["uncertain"] is False and record["attempt"]["dispatch_class"] == "not_sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["validation_after_persistence", "validation_before_dispatch", "ledger_changed"])
async def test_every_prewire_abort_of_a_live_resolve_keeps_the_hazard_and_a_later_run_converges(monkeypatch, variant):
    w = Late(monkeypatch, start=False)
    connector = physical_connector(w.w.identity)
    real_write, state = w.w.ledger.write, {"n": 0}

    async def write(value):
        await real_write(value)
        if value.get("attempt", {}).get("resolve") and not state["n"] >= 9:
            marker = value["attempt"].get("dispatch_class")
            if variant == "validation_after_persistence" and marker == "pre_wire" and not state["n"]:
                state["n"] = 1
                w.w.admission._generations[connector] = w.w.admission._generations.get(connector, 0) + 1  # noqa: SLF001
            if variant == "validation_before_dispatch" and marker == "wire_intent" and not state["n"]:
                state["n"] = 1
                w.w.admission._generations[connector] = w.w.admission._generations.get(connector, 0) + 1  # noqa: SLF001
            if variant == "ledger_changed" and marker == "pre_wire" and not state["n"]:
                state["n"] = 1
                value_changed = copy.deepcopy(value)
                value_changed["_foreign"] = True
                await real_write(value_changed)

    w.w.ledger.write = write
    w.w.worker.start()
    await w.settle()
    assert w.sets == [], variant
    record = w.ledger
    assert record["uncertain"] is True and record["attempt"]["id"] == "o" * 32, (variant, record["attempt"])
    assert morek_schedule.recoverable_ambiguous(record) or variant == "ledger_changed"
    w.w.ledger.write = real_write
    # retryable: the next trigger resolves it for real, history of the unknown original intact
    w.w.worker.trigger(kind="recovery")
    await w.settle()
    assert len(w.sets) == 1 and w.ledger["uncertain"] is False and w.ledger["attempt"]["resolve"] is True
    assert w.ledger["unknown_history"][-1]["attempt_id"] == "o" * 32
    assert w.ledger["unknown_history"][-1]["outcome"] == "unknown"
    w.w.worker.close()
    w.rig.checker.close()


@pytest.mark.asyncio
async def test_a_crash_after_the_resolve_prewire_write_restores_the_ambiguous_record_on_the_next_read(monkeypatch):
    """Restart: only the durable record exists. The 19.1 read-side proof releases THIS replacement, never the original."""
    w = Late(monkeypatch, record=_resolve_attempt_record(), start=False)
    from custom_components.spotnav.execution import morek_outcomes
    from custom_components.spotnav.execution.command_admission import CommandAdmission
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: w.w.ledger)
    connector = physical_connector(w.w.identity)
    w.w.admission._store._hass = w.w.hass  # noqa: SLF001
    outcome = await CommandAdmission._async_read_outcome_recovering(  # noqa: SLF001
        w.w.admission, "charger", connector)
    assert outcome["uncertain"] is True and outcome["attempt"]["id"] == "o" * 32
    assert "pending_resume" in outcome and "supersession" not in outcome
    w.w.worker.start()
    await w.settle()
    assert len(w.sets) == 1 and w.ledger["uncertain"] is False and w.ledger["supersession"]["state"] == (
        "replacement_acknowledged")
    w.w.worker.close()
    w.rig.checker.close()


@pytest.mark.asyncio
async def test_a_reached_wire_resolve_drops_its_prior_for_every_answer(monkeypatch):
    for status, uncertain in (("Accepted", False), ("Rejected", False), ("Unknown", True)):
        w = Late(monkeypatch, start=False)
        w.set_status = status

        async def call(request, w=w, status=status):
            if request.kind == SET:
                w.sets.append(1)
                if status == "Unknown":
                    raise TimeoutError
                return SimpleNamespace(status=status)
            return t153.composite(morek_schedule.held_off_profile(datetime.now(timezone.utc)))

        w.w.point.call = AsyncMock(side_effect=call)
        w.w.worker.start()
        await w.settle()
        attempt = w.ledger["attempt"]
        assert attempt["resolve"] is True and "resolve_prior" not in attempt, status
        assert w.ledger["uncertain"] is uncertain, status
        assert w.ledger["unknown_history"][-1]["attempt_id"] == "o" * 32
        w.w.worker.close()
        w.rig.checker.close()
