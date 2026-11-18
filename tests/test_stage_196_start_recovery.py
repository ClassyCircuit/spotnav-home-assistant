"""Stage 19.6: session start whose outcome is unknown, and evidence-based (never blind) recovery.

Real `MorekSessionCoordinator` through the real connector-admission boundary (the `test_morek_session` harness);
HA state, OCPP and storage are mocked. Nothing here proves the installed OCPP integration restamps its status or
transaction sensors, that the boot counter exists, or any physical charging. Stage 19.2 (ambiguous *schedule*
uploads) is unrelated and stays blocked.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_196_start_recovery.py
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_session import IDENTITY, setup as session_setup


class Evidence:
    """Scripted `_live_measurements`: (value, seconds relative to now) per quantity, or None."""

    def __init__(self):
        self.status = None
        self.transaction = None
        self.changed = None  # seconds relative to now for the transaction's last change

    def __call__(self, hass, controller, now, entities=None):
        def reading(spec, **extra):
            if spec is None:
                return None
            value, offset = spec[0], spec[1]
            stamp = datetime.now(timezone.utc) + timedelta(seconds=offset)
            fresh = spec[2] if len(spec) > 2 else True
            return {"value": value, "observed_at": stamp.isoformat(), "fresh": fresh, **extra}
        extra = {}
        if self.changed is not None:
            extra["changed_at"] = (datetime.now(timezone.utc) + timedelta(seconds=self.changed)).isoformat()
        return {"status": reading(self.status), "transaction": reading(self.transaction, **extra)}


def world(monkeypatch, result=True):
    coordinator, point, ledger, admission = session_setup(monkeypatch, result)
    evidence = Evidence()
    monkeypatch.setattr(morek_schedule, "_live_measurements", evidence)
    return coordinator, point, ledger, admission, evidence


def prior(state, *, connection="old", dispatch=None, age=600, attempts=1):
    value = {"version": 1, "connection": connection, "state": state, "attempts": attempts,
             "at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()}
    if dispatch is not None:
        value["dispatch"] = dispatch
    return value


async def settle(coordinator):
    if coordinator.task is not None:
        await coordinator.task


# ---- pre-dispatch proof (the durable marker advances strictly before the OCPP call)

@pytest.mark.asyncio
async def test_intent_marker_is_durable_before_the_call_and_resolved_after(monkeypatch):
    coordinator, point, ledger, *_ = world(monkeypatch)
    seen = {}
    original = point.start_transaction

    async def spy(connector_id):
        seen["at_call"] = dict(ledger.value["session_start"])
        return await original(connector_id)
    point.start_transaction = spy
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert seen["at_call"]["state"] == "pending" and seen["at_call"]["dispatch"] == "wire_intent"
    assert ledger.value["session_start"]["dispatch"] == "resolved"
    assert point.calls == 1


@pytest.mark.asyncio
async def test_unknown_result_keeps_wire_intent_and_is_ambiguous(monkeypatch):
    coordinator, point, ledger, *_ = world(monkeypatch, TimeoutError())
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    start = ledger.value["session_start"]
    assert start["state"] == "unknown" and start["dispatch"] == "wire_intent"
    assert morek_session.MorekSessionCoordinator._prior_class(start) == "ambiguous"


@pytest.mark.asyncio
async def test_cancelled_before_intent_write_is_released_with_proof_and_started_once(monkeypatch):
    coordinator, point, ledger, *_ = world(monkeypatch)
    original = ledger.write

    async def guarded(value):
        if (value.get("session_start") or {}).get("dispatch") == "wire_intent":
            raise asyncio.CancelledError  # the intent marker never became durable
        await original(value)
    monkeypatch.setattr(ledger, "write", guarded)
    coordinator.observe("Available", "Preparing")
    with pytest.raises(asyncio.CancelledError):
        await coordinator.task
    assert point.calls == 0
    assert ledger.value["session_start"]["state"] == "pending"
    assert ledger.value["session_start"]["dispatch"] == "pre_wire"
    monkeypatch.setattr(ledger, "write", original)
    coordinator.trigger()  # same connection: a proven-undispatched attempt is not counted
    await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"
    assert coordinator.start_recovery_status()["class"] == "proven_not_dispatched"


@pytest.mark.asyncio
async def test_pre_wire_pending_from_an_old_connection_is_released_for_a_new_plug_in(monkeypatch):
    coordinator, point, ledger, *_ = world(monkeypatch)
    ledger.value["session_start"] = prior("pending", dispatch="pre_wire")
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["connection"] == coordinator.connection


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["wire_intent", "legacy_pending", "unknown"])
async def test_wire_intent_legacy_and_unknown_are_never_released_without_evidence(monkeypatch, shape):
    coordinator, point, ledger, *_ = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown" if shape == "unknown" else "pending",
                                          dispatch="wire_intent" if shape == "wire_intent" else None)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0  # 19.6 g4: no fresh post-plug-in evidence, so the plug-in alone starts nothing
    assert coordinator.state == {"state": "blocked", "reason": "waiting_for_post_plug_in_status"}
    assert ledger.value["session_start"]["state"] != "aborted_before_dispatch"
    assert coordinator.start_recovery_status()["who_acts"] == "system"


@pytest.mark.asyncio
async def test_stop_during_intent_write_aborts_before_dispatch_with_nothing_sent(monkeypatch):
    coordinator, point, ledger, admission, _ = world(monkeypatch)
    original = ledger.write

    async def stopping(value):
        await original(value)
        if (value.get("session_start") or {}).get("dispatch") == "wire_intent":
            admission._person_stops[physical_connector(IDENTITY)] = 1
    monkeypatch.setattr(ledger, "write", stopping)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0
    assert ledger.value["session_start"]["state"] == "aborted_before_dispatch"
    assert coordinator.state["state"] == "blocked"


# ---- (a) an affirmative session observation resolves it as observed

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["status", "transaction"])
async def test_unknown_start_is_resolved_by_fresh_session_observation(monkeypatch, kind):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    if kind == "status":
        evidence.status = ("Charging", +1)
        coordinator.observe("Preparing", "Charging")
    else:
        evidence.status = ("Preparing", +1)
        evidence.transaction = (True, +1)
        evidence.changed = -5
        coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    start = ledger.value["session_start"]
    assert start["state"] == "observed" and start["resolution"]["was"] == "unknown"
    assert start["resolution"]["by"] == ("charger_active_status" if kind == "status" else "transaction_present")
    assert point.calls == 0
    assert coordinator.state["state"] == "session_observed"
    assert coordinator.start_recovery_status()["class"] == "resolved"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stale", "before_request", "transaction_older_than_request", "unknown"])
async def test_unfresh_or_earlier_observation_does_not_resolve(monkeypatch, case):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    if case == "stale":
        evidence.status = ("Charging", +1, False)
    elif case == "before_request":
        evidence.status = ("Charging", -3600)
    elif case == "transaction_older_than_request":
        evidence.status = ("Preparing", +1)
        evidence.transaction = (True, +1)
        evidence.changed = -3600  # a transaction id that was already there before the request
    coordinator.observe("Preparing", "Charging")
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "unknown"
    assert point.calls == 0


# ---- an old ambiguous start is NOT superseded by a new plug-in: no ordering proof exists

@pytest.mark.asyncio
async def test_new_plug_in_with_affirmative_no_session_evidence_starts_once_and_keeps_old_as_history(monkeypatch):
    """19.6 g4 (user-approved pragmatic recovery; replaces the earlier 'still blocks' assertion). The old request
    stays `unknown` in history; the device may still deliver it late or duplicate it (unverified, not excluded)."""
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    start = ledger.value["session_start"]
    assert start["state"] == "accepted" and start["connection"] == coordinator.connection
    assert start["history"][0]["connection"] == "old" and start["history"][0]["outcome"] == "unknown"
    assert start["recoveries"] == 1 and "ambiguity_inherited" not in start
    status = coordinator.start_recovery_status()
    assert status["class"] == "ambiguous_superseded" and status["evidence"] == "plug_in"
    assert status["risk"] == "duplicate_or_delayed_start_not_excluded"
    for _ in range(3):  # routine sensor updates and re-evaluations never start again
        coordinator.observe("Preparing", "Preparing")
        coordinator.trigger()
        await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
async def test_old_start_delivered_late_after_replacement_is_observed_not_duplicated(monkeypatch):
    """A late old request that does start a session sends nothing more: the session is only observed."""
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    evidence.status = ("Charging", +2)
    coordinator.observe("Preparing", "Charging")
    await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"
    assert ledger.value["session_start"]["history"][0]["outcome"] == "unknown"


@pytest.mark.asyncio
async def test_unplug_marker_restart_does_not_supersede_either(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    ledger.value["session_unplugged"] = "c" * 32
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observe(None, "Preparing")
    await settle(coordinator)
    assert point.calls == 0
    assert ledger.value["session_start"]["state"] == "unknown"
    assert "session_start_history" not in ledger.value
@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["recovery", "offline", "same_connection"])
async def test_reconnect_recovery_or_same_token_alone_is_unchanged(monkeypatch, token):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observation = "preparing"
    if token == "same_connection":
        coordinator.connection = "same"
        ledger.value["session_start"] = prior("unknown", connection="same", dispatch="wire_intent")
    else:
        coordinator.connection = "recovery" if token == "recovery" else "offline:" + "a" * 32
        ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 0
    assert coordinator.state == {"state": "uncertain", "reason": "previous_start_may_have_applied"}
    assert coordinator.start_recovery_status()["who_acts"] == "person"


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["stop", "pause", "protection"])
async def test_stop_pause_and_protection_win_over_evidence_recovery(monkeypatch, guard):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    if guard == "stop":
        admission._person_stops[physical_connector(IDENTITY)] = 1
    elif guard == "pause":
        ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                          "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    else:
        from types import SimpleNamespace
        monkeypatch.setattr(morek_session, "controller_for", lambda *_: SimpleNamespace(
            ocpp_target=SimpleNamespace(connector_id=1), _start_cap=lambda: None))
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 0
    assert "session_start_history" not in ledger.value
    assert ledger.value["session_start"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_accepted_without_transaction_is_still_not_repeated(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)
    assert point.calls == 1
    for _ in range(3):
        coordinator.observe("Preparing", "Preparing")
        coordinator.trigger()
        await settle(coordinator)
    assert point.calls == 1
    coordinator.close()


@pytest.mark.asyncio
async def test_status_exposes_recovery_class_without_charging_claim(monkeypatch):
    coordinator, *_ = world(monkeypatch)
    assert coordinator.start_recovery_status() == {"class": "none"}


# ---- concurrency: the connector-wide outcome write is serialized by the connector admission lock

CONNECTOR = physical_connector(IDENTITY)


def schedule_lock(coordinator):
    return coordinator.hass.data[morek_schedule._DATA_KEY]["charger"][2]


async def active_edge(coordinator, evidence):
    evidence.status = ("Charging", +1)
    coordinator.observe("Preparing", "Charging")


@pytest.mark.asyncio
async def test_resolution_waits_for_the_connector_admission_lock(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    async with admission._lock_for(CONNECTOR):
        await active_edge(coordinator, evidence)
        for _ in range(5):
            await asyncio.sleep(0)
        assert ledger.value["session_start"]["state"] == "unknown"  # nothing written under only the schedule lock
        assert not schedule_lock(coordinator).locked()  # the schedule lock is taken only inside, never first
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "observed"


@pytest.mark.asyncio
async def test_concurrent_connector_writer_is_not_lost_by_the_resolution(monkeypatch):
    """A Pause-style writer holds the connector lock, reads, awaits and writes the whole record: no lost update."""
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    pause = {"version": 1, "type": "pause_until_resumed", "id": "p",
             "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    held, release = asyncio.Event(), asyncio.Event()

    async def writer():
        async with admission._lock_for(CONNECTOR):
            snapshot = await ledger.read()
            held.set()
            await release.wait()
            snapshot["schedule_pause"] = pause
            await ledger.write(snapshot)
    task = asyncio.create_task(writer())
    await held.wait()
    await active_edge(coordinator, evidence)
    for _ in range(5):
        await asyncio.sleep(0)
    release.set()
    await task
    await settle(coordinator)
    assert ledger.value["schedule_pause"] == pause
    assert ledger.value["session_start"]["state"] == "observed"


@pytest.mark.asyncio
async def test_person_stop_while_waiting_leaves_the_record_untouched_then_resolves_later(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    async with admission._lock_for(CONNECTOR):
        await active_edge(coordinator, evidence)
        await asyncio.sleep(0)
        admission._person_stops[CONNECTOR] = 1  # a Stop begins while the resolution is queued
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "unknown"
    assert coordinator._resolve_pending is True
    admission._person_stops.pop(CONNECTOR)
    coordinator.trigger()
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "observed"


@pytest.mark.asyncio
async def test_record_changed_while_waiting_is_revalidated_not_overwritten(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    async with admission._lock_for(CONNECTOR):
        await active_edge(coordinator, evidence)
        await asyncio.sleep(0)
        ledger.value["session_start"] = prior("accepted", connection="new", dispatch="resolved", age=1)
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "accepted"
    assert ledger.value["session_start"]["connection"] == "new"
    assert coordinator._resolve_pending is False


@pytest.mark.asyncio
async def test_identity_change_while_waiting_leaves_the_record_untouched(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    async with admission._lock_for(CONNECTOR):
        await active_edge(coordinator, evidence)
        await asyncio.sleep(0)
        coordinator.worker._identity = lambda: {**IDENTITY, "connector_id": 2}
    await settle(coordinator)
    assert ledger.value["session_start"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_resolution_and_start_run_do_not_deadlock_and_send_at_most_once(monkeypatch):
    """Both paths take connector lock then schedule lock; a plug-in start racing an active edge completes."""
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("accepted", connection="older", dispatch="resolved")
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)
    coordinator.observe("Available", "Preparing")
    coordinator.observe("Preparing", "Charging")
    evidence.status = ("Charging", +1)
    coordinator.trigger()
    await asyncio.wait_for(settle(coordinator), 5)
    assert point.calls <= 1
    assert not admission._lock_for(CONNECTOR).locked() and not schedule_lock(coordinator).locked()


@pytest.mark.asyncio
async def test_busy_schedule_lock_with_manual_waiting_for_connector_does_not_deadlock(monkeypatch):
    """Real locks: the manual path holds the schedule lock and then asks for the connector lock while an
    observation holds the connector lock. The observation must skip (never wait), the manual write must finish,
    and the skipped observation must be retriggered and resolve without losing the manual update."""
    monkeypatch.setattr(morek_session, "RESOLVE_RETRY_DELAY_S", 0.01)
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent")
    pause = {"version": 1, "type": "pause_until_resumed", "id": "p",
             "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    holding, go = asyncio.Event(), asyncio.Event()
    await morek_schedule._state(coordinator.hass, coordinator.entry_id)  # creates the schedule lock

    async def manual():
        async with schedule_lock(coordinator):
            holding.set()
            await go.wait()
            async with admission._lock_for(CONNECTOR):  # schedule lock first, then the connector lock
                snapshot = await ledger.read()
                snapshot["schedule_pause"] = pause
                await ledger.write(snapshot)
    task = asyncio.create_task(manual())
    await asyncio.wait_for(holding.wait(), 5)
    await active_edge(coordinator, evidence)
    for _ in range(5):
        await asyncio.sleep(0)
    assert ledger.value["session_start"]["state"] == "unknown"  # skipped, not written
    assert not admission._lock_for(CONNECTOR).locked()  # the observation did not keep the connector lock
    go.set()
    await asyncio.wait_for(task, 5)

    async def resolved():
        while ledger.value["session_start"]["state"] != "observed":
            await asyncio.sleep(0.01)
    await asyncio.wait_for(resolved(), 5)
    await settle(coordinator)
    assert ledger.value["schedule_pause"] == pause  # no lost update
    assert not admission._lock_for(CONNECTOR).locked() and not schedule_lock(coordinator).locked()
