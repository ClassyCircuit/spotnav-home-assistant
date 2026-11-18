"""Stage 19.3 + 19.7 remainder: lifecycle / session / storage / ownership blockers are named, paced and observed.

Mocked boundaries only (the real worker, send path and session coordinator; admission is the real class for the
session tests and a refusing stand-in for the worker tests). Nothing here proves charger behavior. Every case counts
the actual wire calls."""

import asyncio
import copy
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution.command_admission import AdmissionResult, physical_connector
from custom_components.spotnav.execution.morek_outcomes import OutcomeUnavailable

from .test_morek_session import IDENTITY, setup as session_setup
from .test_morek_worker import SimulatedAdmission, drain, setup as worker_setup

BANNER = Path(__file__).parent.parent / "frontend" / "sidebar" / "recovery-banner.js"
TRANSIENT_ADMISSION = ("lifecycle_initializing", "connector_quiescing", "ownership_unavailable",
                       "profile_outcome_unavailable")
PERSON_ADMISSION = ("ownership_inconsistent", "legacy_not_owner", "ownership_identity_mismatch",
                    "schedule_mode_unarmed", "retained_profile_exit_held", "ownership_transition")


class RefusingAdmission(SimulatedAdmission):
    """The real connector lock/generation; `refuse` is the reason the owned-profile boundary answers with."""

    refuse: str | None = None

    async def async_execute(self, entry_id, kind, resolve_identity, operation, *, expected_generation=None):
        if kind == "owned_profile" and self.refuse:
            return AdmissionResult(False, self.refuse)
        return await super().async_execute(entry_id, kind, resolve_identity, operation,
                                           expected_generation=expected_generation)


def _worker(monkeypatch, reason):
    admission = RefusingAdmission()
    admission.refuse = reason
    w = worker_setup(monkeypatch, admission=admission)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None}
    return w


# ---- the table: every reason has an action, wording and a recovery class ------------------------------------

def test_every_blocker_reason_has_an_action_and_banner_wording_and_a_recovery_class():
    wording = set(re.findall(r"^\s*(\w+):\s*['`]", BANNER.read_text(encoding="utf8"), re.M))
    reasons = set(TRANSIENT_ADMISSION) | set(PERSON_ADMISSION) | {
        "outcome_storage_uncertain", "outcome_storage_invalid", "outcome_binding_unavailable",
        "schedule_owner_unavailable", "plan_expired", "planner_unavailable", "person_stop_not_reserved",
        "not_morek_connector", "invalid_operation", "upload_not_sent"} | set(morek_session.TRANSIENT_SESSION_BLOCKERS)
    for code in sorted(reasons):
        action = morek_schedule.DECISION_BLOCKERS.get(code)
        assert action and action in wording, (code, action)
        assert morek_schedule.decision_blocker(code)["action"] == action
        entry = morek_schedule.observation_entry(code, "t")
        automatic = code in morek_schedule.TRANSIENT_BLOCKERS or code in morek_schedule.SESSION_OBSERVED_BLOCKERS
        assert entry["next"] == ("automatic_recheck" if automatic else "person_action"), code
        assert entry["who"] in ("system", "person", "vehicle")
    # every action the table can emit is worded (an unworded one would fall into the generic fallback)
    assert set(morek_schedule.DECISION_BLOCKERS.values()) <= wording | {"see_reason"}
    # ownership and identity conflicts are never timer-retried; storage that may heal is
    for code in PERSON_ADMISSION + ("outcome_storage_invalid", "outcome_binding_unavailable", "not_morek_connector"):
        assert code not in morek_schedule.TRANSIENT_BLOCKERS
    for code in TRANSIENT_ADMISSION + ("outcome_storage_uncertain",):
        assert code in morek_schedule.TRANSIENT_BLOCKERS


# ---- worker: transient lifecycle/storage blockers -> paced, persisted, observed once, then exactly one send ---

@pytest.mark.asyncio
@pytest.mark.parametrize("reason", TRANSIENT_ADMISSION)
async def test_transient_admission_blocker_paces_slowly_persists_and_sends_once_when_it_clears(monkeypatch, reason):
    w = _worker(monkeypatch, reason)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == reason and w.worker._blocker_timer is not None  # noqa: SLF001
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 3):  # what the timer does when it fires
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    state = w.worker.blocker_retry
    assert state["code"] == reason and state["phase"] == "slow" and not state["exhausted"]
    assert w.worker._blocker_timer is not None  # noqa: SLF001 - never an indefinite silent stop
    assert w.point.call.await_count == 0
    # one observation however many re-evaluations ran (no per-retry entry or log churn)
    assert [o["code"] for o in w.worker.observations] == [reason]
    assert w.worker.observations[0]["next"] == "automatic_recheck" and w.worker.observations[0]["count"] == 1
    await w.worker.async_flush_retry_state()
    saved = w.ledger.value["retry_state"]
    assert saved["pace"]["phase"] == "slow" and saved["observations"][0]["code"] == reason
    w.worker.close()
    # restart: the same blocker continues at its persisted slow pace, with no burst of sends
    again = _worker(monkeypatch, reason)
    again.ledger.value = copy.deepcopy(w.ledger.value)
    again.worker.start()
    await drain(again.worker)
    assert again.worker.blocker_retry["phase"] == "slow" and again.point.call.await_count == 0
    # the condition clears: one guarded re-evaluation, one send, then the pace is gone
    again.admission.refuse = None
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1 and again.worker.reason == "upload_accepted_unverified"
    assert again.worker.blocker_retry is None
    again.worker.trigger(kind="recovery")
    await drain(again.worker)
    assert again.point.call.await_count == 1  # an equal settled schedule is not sent again
    again.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", PERSON_ADMISSION)
async def test_ownership_and_identity_conflicts_are_person_actionable_never_timer_retried(monkeypatch, reason):
    w = _worker(monkeypatch, reason)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == reason
    assert w.worker._blocker_timer is None and w.worker.blocker_retry is None  # noqa: SLF001
    blocker = morek_schedule.decision_blocker(reason)
    assert blocker["action"] in ("confirm_ownership", "check_charger_identity")
    assert w.worker.observations[-1]["next"] == "person_action" and w.worker.observations[-1]["who"] == "person"
    for _ in range(3):  # a burst of events is the same decision: counted, not re-logged, nothing sent
        w.worker.trigger(kind="routine")
        await drain(w.worker)
    assert w.point.call.await_count == 0 and len(w.worker.observations) == 1
    w.admission.refuse = None  # the person resolved it: the next evaluation sends exactly once
    w.worker.trigger(kind="control")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_unreadable_ledger_is_a_named_storage_blocker_uncertain_is_paced_invalid_is_not(monkeypatch):
    w = worker_setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None}
    real_read = w.ledger.read
    failure = {"code": "outcome_storage_uncertain"}

    async def read():
        if failure["code"]:
            raise OutcomeUnavailable(failure["code"])
        return await real_read()

    w.ledger.read = read
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "outcome_storage_uncertain" and w.worker._blocker_timer is not None  # noqa: SLF001
    assert morek_schedule.decision_blocker(w.worker.reason)["action"] == "wait_for_storage"
    failure["code"] = "outcome_storage_invalid"
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.worker.reason == "outcome_storage_invalid" and w.worker._blocker_timer is None  # noqa: SLF001
    assert morek_schedule.decision_blocker(w.worker.reason)["action"] == "check_storage"
    assert w.point.call.await_count == 0
    failure["code"] = None  # the ledger reads again: one guarded evaluation, one send
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_a_stop_pause_or_newer_pause_still_wins_over_a_paced_re_evaluation(monkeypatch):
    w = _worker(monkeypatch, "lifecycle_initializing")
    w.worker.start()
    await drain(w.worker)
    w.ledger.value.update(clean_start={"version": 1}, schedule_pause={
        "version": 1, "type": "pause_until_resumed", "id": "p", "station_id": IDENTITY["resolved_id"], "connector_id": 1})
    w.admission.refuse = None  # the barrier clears, but a person's Pause is the newer intent
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 0 and w.worker.reason in ("paused_until_resume", "legacy_pause_active")
    w.worker.close()


# ---- session start: the fast phase no longer ends in a silent stop ----------------------------------------------

def _session(monkeypatch, blocker):
    monkeypatch.setattr(morek_session, "SESSION_RETRY_DELAYS", (0.001,))
    monkeypatch.setattr(morek_session, "SESSION_RETRY_LIMIT", 3)
    monkeypatch.setattr(morek_schedule, "SLOW_RETRY_DELAYS", (0.005,))
    coordinator, point, ledger, admission = session_setup(monkeypatch)
    seen = []
    coordinator.worker._observe = seen.append
    connector = physical_connector(IDENTITY)
    if blocker == "lifecycle_initializing":
        admission._lifecycle_barriers["charger"] = connector
        clear = lambda: admission._lifecycle_barriers.clear()  # noqa: E731
    else:  # ownership_unavailable: the ownership file does not read back as valid, so no send is trusted
        from custom_components.spotnav.execution import execution_ownership
        records = admission._store._records
        monkeypatch.setattr(execution_ownership, "_decode", lambda _: ("unreadable", None))
        clear = lambda: monkeypatch.setattr(execution_ownership, "_decode", lambda _: ("valid", records))  # noqa: E731
    return coordinator, point, seen, clear


async def _wait(predicate, rounds=400):
    for _ in range(rounds):
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return False


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["lifecycle_initializing", "ownership_unavailable"])
async def test_session_blocker_continues_after_the_fast_phase_observes_once_and_starts_once(monkeypatch, blocker):
    coordinator, point, seen, clear = _session(monkeypatch, blocker)
    coordinator.observe("Available", "Preparing")
    assert await _wait(lambda: coordinator._recheck_runs > 3 + 3)  # noqa: SLF001 - well past the fast limit
    assert coordinator.state == {"state": "blocked", "reason": blocker}
    assert point.calls == 0 and coordinator._recheck is not None  # noqa: SLF001 - still scheduled
    assert seen == [blocker]  # one observation per changed blocker, not one per re-evaluation
    clear()
    assert await _wait(lambda: point.calls)
    await asyncio.sleep(0.05)
    assert point.calls == 1 and coordinator.state["state"] == "accepted"
    coordinator.close()


@pytest.mark.asyncio
async def test_a_person_stop_is_never_retried_by_the_slow_pace(monkeypatch):
    coordinator, point, _seen, _clear = _session(monkeypatch, "lifecycle_initializing")
    admission = morek_session.command_admission(None)  # the patched, real CommandAdmission
    admission._lifecycle_barriers.clear()
    admission._person_stops[physical_connector(IDENTITY)] = 1
    coordinator.observe("Available", "Preparing")
    await asyncio.sleep(0.05)
    assert coordinator.state["reason"] == "person_stop_active" and coordinator._recheck is None  # noqa: SLF001
    assert point.calls == 0
    coordinator.close()


@pytest.mark.asyncio
async def test_a_busy_resolve_lock_is_retried_fast_then_slow_never_abandoned(monkeypatch):
    monkeypatch.setattr(morek_session, "SESSION_RETRY_LIMIT", 2)
    monkeypatch.setattr(morek_session, "RESOLVE_RETRY_DELAY_S", 0.001)
    monkeypatch.setattr(morek_schedule, "SLOW_RETRY_DELAYS", (0.002,))
    coordinator, _point, _ledger, _admission = session_setup(monkeypatch)
    triggers = []
    coordinator.trigger = lambda: triggers.append(1)
    for _ in range(6):
        coordinator._retry_resolve()  # noqa: SLF001
        assert await _wait(lambda: coordinator._resolve_retry is None and len(triggers) > 0)  # noqa: SLF001
        triggers.clear()
    assert coordinator._resolve_skips == 6  # noqa: SLF001 - the 3rd..6th were slow-pace re-tries, not dropped
    coordinator.close()
