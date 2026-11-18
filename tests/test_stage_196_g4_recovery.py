"""Stage 19.6 group 4: ambiguous session start -> guarded new start on a genuine new plug-in / confirmed reboot.

Real `MorekSessionCoordinator`, real connector admission and the real `_reconcile` (record-first, wire-intent
marker, final pre-wire validation); HA state, OCPP and storage are mocked. The user approved this pragmatic policy:
fresh affirmative Preparing/no-transaction evidence on a *different* token (plug-in or confirmed reboot) permits one
normal guarded start, paced; the old outcome stays `unknown` history. NOT proven: that the charger orders, rejects or
deduplicates a late/duplicate old start, that HA restamps the status/transaction sensors, or any physical charging.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_196_g4_recovery.py
"""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution.command_admission import physical_connector
from .test_morek_session import IDENTITY
from .test_stage_196_start_recovery import prior, settle, world


def ready(evidence):
    evidence.status = ("Preparing", +1)
    evidence.transaction = (False, +1)


async def plug_in(coordinator):
    coordinator.observe("Available", "Preparing")
    await settle(coordinator)


def unknown_record(ledger, **kw):
    ledger.value["session_start"] = prior("unknown", dispatch="wire_intent", **kw)


@pytest.mark.asyncio
@pytest.mark.timeout(20)
@pytest.mark.parametrize("case", ["no_status", "stale_status", "status_before_plug_in", "no_transaction_report",
                                  "stale_transaction", "transaction_before_plug_in", "transaction_present",
                                  "status_not_preparing"])
async def test_missing_or_stale_evidence_sends_nothing_names_the_gap_and_keeps_the_old_record(monkeypatch, case):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    if case == "no_status":
        evidence.status = None
    elif case == "stale_status":
        evidence.status = ("Preparing", +1, False)
    elif case == "status_before_plug_in":
        evidence.status = ("Preparing", -60)
    elif case == "no_transaction_report":
        evidence.transaction = None
    elif case == "stale_transaction":
        evidence.transaction = (False, +1, False)
    elif case == "transaction_before_plug_in":
        evidence.transaction = (False, -60)
    elif case == "transaction_present":
        evidence.transaction = (True, +1)
    else:
        evidence.status = ("Available", +1)
    await plug_in(coordinator)
    assert point.calls == 0
    assert coordinator.state["state"] == "blocked"
    assert ledger.value["session_start"]["connection"] == "old" and "history" not in ledger.value["session_start"]
    status = coordinator.start_recovery_status()
    assert status["class"] == "ambiguous" and status["recovers_on"] == "new_plug_in_or_confirmed_reboot"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_evidence_arriving_later_is_picked_up_by_the_bounded_recheck_and_sends_once(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    evidence.status = ("Preparing", +1)
    evidence.transaction = None  # the transaction sensor has not reported yet
    await plug_in(coordinator)
    assert point.calls == 0
    assert coordinator.state["reason"] == "transaction_unknown"
    assert coordinator._recheck is not None  # never an indefinite silent stop: a bounded re-evaluation is armed
    evidence.transaction = (False, +1)
    coordinator.trigger()  # what the recheck timer fires
    await settle(coordinator)
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_charging_seen_after_plug_in_means_no_new_start(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    evidence.status = ("Preparing", +1)
    evidence.transaction = None
    await plug_in(coordinator)
    ready(evidence)
    coordinator.observe("Preparing", "Charging")  # the late old request (or a person) started a session
    coordinator.observe("Charging", "Preparing")
    await settle(coordinator)
    assert point.calls == 0
    assert coordinator.state["reason"] == "charging_seen_after_plug_in"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
@pytest.mark.parametrize(("age", "recoveries", "sends"), [(30, 0, False), (130, 0, True), (200, 1, False),
                                                             (400, 1, True), (800, 2, False), (1000, 2, True),
                                                             (1700, 3, False), (1900, 3, True),
                                                             (10000, 9, False), (15000, 9, True)])
async def test_attempts_are_paced_from_the_durable_record(monkeypatch, age, recoveries, sends):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger, age=age)
    ledger.value["session_start"]["recoveries"] = recoveries
    ready(evidence)
    await plug_in(coordinator)
    assert point.calls == (1 if sends else 0)
    if sends:
        assert ledger.value["session_start"]["recoveries"] == recoveries + 1
    else:
        assert coordinator.state == {"state": "blocked", "reason": "start_recovery_paced"}
        assert coordinator.start_recovery_status()["next_at"]
        assert coordinator._recheck is not None  # exactly one timer for the remainder, no polling
        assert coordinator._paced_delay > 0


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_the_replacement_that_times_out_is_not_repeated_on_the_same_token_and_a_new_plug_in_is_paced(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch, TimeoutError())
    unknown_record(ledger)
    ready(evidence)
    await plug_in(coordinator)
    assert point.calls == 1 and ledger.value["session_start"]["state"] == "unknown"
    for _ in range(4):  # sensor noise and timers never repeat a request on the same connection
        coordinator.observe("Preparing", "Preparing")
        coordinator.trigger()
        await settle(coordinator)
    assert point.calls == 1
    assert coordinator.state == {"state": "uncertain", "reason": "previous_start_may_have_applied"}
    coordinator.observe("Preparing", "Available")
    coordinator.observe("Available", "Preparing")  # another genuine plug-in a moment later: inside the pace (5 min)
    await settle(coordinator)
    assert point.calls == 1 and coordinator.state["reason"] == "start_recovery_paced"
    ledger.value["session_start"]["at"] = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 2
    start = ledger.value["session_start"]
    assert start["recoveries"] == 2 and len(start["history"]) == 2  # newest first, bounded by START_HISTORY_CAP
    assert all(item["outcome"] == "unknown" for item in start["history"])


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_history_is_bounded(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ledger.value["session_start"]["history"] = [{"state": "unknown", "outcome": "unknown"}] * 9
    ledger.value["session_start"]["recoveries"] = 0
    ready(evidence)
    await plug_in(coordinator)
    assert len(ledger.value["session_start"]["history"]) == morek_session.START_HISTORY_CAP


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_restart_resumes_nothing_by_itself_then_a_genuine_plug_in_recovers(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")  # HA restart with the car already there: not a plug-in, not a reboot
    await settle(restarted)
    for _ in range(3):
        restarted.trigger()
        await settle(restarted)
    assert point.calls == 0
    assert restarted.state == {"state": "uncertain", "reason": "previous_start_may_have_applied"}
    status = restarted.start_recovery_status()
    assert status["who_acts"] == "person" and status["recovers_on"] == "new_plug_in_or_confirmed_reboot"
    restarted.observe("Preparing", "Available")
    restarted.observe("Available", "Preparing")
    await settle(restarted)
    assert point.calls == 1 and ledger.value["session_start"]["state"] == "accepted"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
@pytest.mark.parametrize("token", ["offline", "resume", "unplug"])
async def test_other_tokens_never_supersede(monkeypatch, token):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    coordinator.observation = "preparing"
    coordinator.connection = {"offline": "offline:" + "a" * 32, "resume": "resume:x", "unplug": "unplug:" + "b" * 32}[token]
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "previous_start_may_have_applied"


# ---- Stop / Pause / protection and races at every boundary

@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_stop_during_the_pre_wire_write_sends_nothing_and_keeps_the_old_ambiguity(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    original = ledger.write

    async def stopping(value):
        await original(value)
        if (value.get("session_start") or {}).get("dispatch") == "wire_intent":
            admission._person_stops[physical_connector(IDENTITY)] = 1
    monkeypatch.setattr(ledger, "write", stopping)
    await plug_in(coordinator)
    assert point.calls == 0  # a Stop is never turned into a start
    start = ledger.value["session_start"]
    assert start["state"] == "aborted_before_dispatch" and start["ambiguity_inherited"] is True
    assert morek_session.MorekSessionCoordinator._prior_class(start) == "ambiguous"  # not laundered by the abort
    assert start["history"][0]["outcome"] == "unknown"
    monkeypatch.setattr(ledger, "write", original)
    admission._person_stops.clear()
    coordinator.state = {"state": "waiting", "reason": "waiting_for_vehicle"}
    coordinator.trigger()  # same plug-in token: nothing was sent, so it may be retried once, with fresh evidence
    await settle(coordinator)
    assert point.calls == 1 and ledger.value["session_start"]["state"] == "accepted"
    assert "ambiguity_inherited" not in ledger.value["session_start"]


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_abort_leaves_ambiguity_for_a_restart_without_a_genuine_event(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    original = ledger.write

    async def stopping(value):
        await original(value)
        if (value.get("session_start") or {}).get("dispatch") == "wire_intent":
            admission._person_stops[physical_connector(IDENTITY)] = 1
    monkeypatch.setattr(ledger, "write", stopping)
    await plug_in(coordinator)
    monkeypatch.setattr(ledger, "write", original)
    admission._person_stops.clear()
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await settle(restarted)
    assert point.calls == 0 and restarted.state["reason"] == "previous_start_may_have_applied"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
@pytest.mark.parametrize("change", ["transaction", "charging", "pause_generation"])
async def test_evidence_or_intent_lost_during_the_awaits_aborts_before_dispatch(monkeypatch, change):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    original = ledger.write

    async def changing(value):
        await original(value)
        if (value.get("session_start") or {}).get("dispatch") == "wire_intent":
            if change == "transaction":
                evidence.transaction = (True, +2)
            elif change == "charging":
                coordinator.observation = "charging"
                coordinator._plug_in["active_seen"] = True
            else:  # a Pause/Stop moves the connector generation (the real admission boundary)
                connector = physical_connector(IDENTITY)
                admission._generations[connector] = admission._generations.get(connector, 0) + 1
    monkeypatch.setattr(ledger, "write", changing)
    await plug_in(coordinator)
    assert point.calls == 0
    start = ledger.value["session_start"]
    assert start["state"] == "aborted_before_dispatch" and start["ambiguity_inherited"] is True
    assert morek_session.MorekSessionCoordinator._prior_class(start) == "ambiguous"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_pause_and_stop_block_before_any_write(monkeypatch):
    coordinator, point, ledger, admission, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    await plug_in(coordinator)
    assert point.calls == 0 and coordinator.state["reason"] == "paused_until_resume"
    assert ledger.value["session_start"]["connection"] == "old"
    ledger.value.pop("schedule_pause")
    admission._person_stops[physical_connector(IDENTITY)] = 1
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 0 and ledger.value["session_start"]["connection"] == "old"


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_pause_arriving_after_the_replacement_does_not_send_a_second_start(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    await plug_in(coordinator)
    assert point.calls == 1
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_a_definite_rejection_of_the_replacement_clears_the_inherited_ambiguity_and_retries_on_the_old_path(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch, False)
    unknown_record(ledger)
    ready(evidence)
    await plug_in(coordinator)
    start = ledger.value["session_start"]
    assert point.calls == 1 and start["state"] == "rejected" and "ambiguity_inherited" not in start
    assert morek_session.MorekSessionCoordinator._prior_class(start) == "resolved"
    coordinator.trigger()
    await settle(coordinator)
    assert point.calls == 1 and coordinator.state["reason"] == "retry_cooldown"  # the existing 60 s rule, not a burst


# ---- confirmed reboot goes through the same gate (the plug-in token rules do not apply to it)

@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_a_late_request_after_the_replacement_is_observed_once_and_never_resent(monkeypatch):
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    unknown_record(ledger)
    ready(evidence)
    await plug_in(coordinator)
    evidence.status = ("Charging", +3)
    evidence.transaction = (True, +3)
    coordinator.observe("Preparing", "Charging")
    await settle(coordinator)
    coordinator.observe("Charging", "Preparing")
    await settle(coordinator)
    assert point.calls == 1


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_evidence_is_not_required_when_nothing_is_ambiguous(monkeypatch):
    """The existing normal plug-in start is unchanged: no evidence gate when no earlier request is unresolved."""
    coordinator, point, ledger, _, evidence = world(monkeypatch)
    evidence.status = None
    evidence.transaction = None
    await plug_in(coordinator)
    assert point.calls == 1
    assert "history" not in ledger.value["session_start"]
