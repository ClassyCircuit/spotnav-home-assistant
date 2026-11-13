"""Actual intent/worker modules; HA, OCPP and simulated ownership are boundaries."""

import asyncio
from datetime import datetime, time, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_worker
from custom_components.spotnav.execution.command_admission import AdmissionResult, CommandAdmission, physical_connector
from .morek_fakes import MemoryOutcomes

NOW = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)
IDENTITY = {"supported": True, "resolved_id": morek_schedule.MOREK_STATION_ID,
            "connector_id": 1, "match_count": 1, "ocpp_version": "1.6"}


class SimulatedAdmission(CommandAdmission):
    """Test-only authorization, with the real connector lock and generation."""

    def __init__(self):
        super().__init__(SimpleNamespace(async_status=AsyncMock(return_value={
            "record_state": "valid", "recorded_owner": "legacy", "transition_state": None,
            "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1, "armed": False,
        })))
        self.entered = None
        self.release = None

    def owned_ticket_current(self, entry_id, connector):
        return True  # Other worker tests deliberately simulate admission.

    async def async_owned_boundary_current(self, entry_id, connector):
        return True

    async def async_execute(self, entry_id, kind, resolve_identity, operation, *, expected_generation=None):
        if kind == "read_only":
            return await super().async_execute(entry_id, kind, resolve_identity, operation)
        assert kind == "owned_profile"
        connector = physical_connector(resolve_identity())
        async with self._lock_for(connector):
            if self.entered:
                self.entered.set()
                await self.release.wait()
            if expected_generation != self.generation(connector):
                return AdmissionResult(False, "stale_generation")
            if physical_connector(resolve_identity()) != connector:
                return AdmissionResult(False, "identity_changed")
            return AdmissionResult(True, "simulated", await operation())


class Planner:
    def __init__(self, snapshot):
        self.current = snapshot
        self.listeners = []
        self.publication_cause = None
        self.async_recalculate = AsyncMock()

    def snapshot(self):
        return self.current

    def snapshot_is_current(self, snapshot):
        return snapshot is self.current and getattr(snapshot, "current", True)

    def morek_plan_blocker(self, snapshot, now):
        return None

    def add_publication_listener(self, listener):
        self.listeners.append(listener)
        listener(self.current)
        return lambda: self.listeners.remove(listener)

    def publish(self, cause=None):
        self.publication_cause = cause
        try:
            for listener in list(self.listeners):
                listener(self.current)
        finally:
            self.publication_cause = None


def setup(monkeypatch, *, active=False, admission=None):
    class Clock:
        now = staticmethod(lambda _: NOW)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_worker, "_COALESCE_SECONDS", 0)
    window = (NOW - timedelta(minutes=1) if active else NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    proposal = SimpleNamespace(has_plan=True, unpriced=False, shown_periods=(window,))
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    planner = Planner(snapshot)
    settings = SimpleNamespace(revision=4, amps=16)
    hass = SimpleNamespace(data={}, async_create_task=asyncio.create_task)
    ledger = MemoryOutcomes()
    disk = SimpleNamespace(async_save=AsyncMock())
    async def record(h, entry_id):
        if entry_id not in h.data.setdefault(morek_schedule._DATA_KEY, {}):
            h.data[morek_schedule._DATA_KEY][entry_id] = ({}, disk, asyncio.Lock())
        data, store, _ = h.data[morek_schedule._DATA_KEY][entry_id]
        return data, store
    point = SimpleNamespace(call=AsyncMock(return_value=SimpleNamespace(status="Accepted")))
    target = SimpleNamespace(connector_id=1)
    state = SimpleNamespace(identity=dict(IDENTITY), settings=settings, planner=planner, point=point,
                            target=target, admission=admission or SimulatedAdmission(), hass=hass)
    monkeypatch.setattr(morek_worker, "controller_for", lambda *_: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda *_: state.identity)
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda *_: point)
    monkeypatch.setattr(morek_worker, "domain_data", lambda *_: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda _: settings)))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda *_: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda _: settings)))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: planner)
    monkeypatch.setattr(morek_worker, "preview_for", lambda *_: planner)
    monkeypatch.setattr(morek_worker, "command_admission", lambda _: state.admission)
    monkeypatch.setattr(morek_schedule, "_state", record)
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda _: ledger)
    monkeypatch.setattr(morek_schedule, "async_call_later", lambda *_: lambda: None)
    state.ledger = ledger
    import sys
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        SetChargingProfile=lambda **kw: SimpleNamespace(payload=kw))))
    state.worker = morek_worker.MorekScheduleWorker(hass, "charger", planner)
    return state


async def drain(worker):
    while worker._task is not None:
        await worker._task


@pytest.mark.asyncio
async def test_clean_start_remains_paused_without_an_automatic_profile_write(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
                      "clean_start": {"version": 1}, "schedule_pause": {"version": 1,
                      "type": "pause_until_resumed", "id": "p", "station_id": IDENTITY["resolved_id"],
                      "connector_id": 1}}
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "paused_until_resume"
    w.point.call.assert_not_awaited()
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    w.settings.pause = SimpleNamespace(admitted=True)
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    assert w.worker.reason == "legacy_pause_active"
    w.point.call.assert_not_awaited()
    w.settings.pause.admitted = False
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.ledger.value["attempt"]["source"] == "worker"
    w.worker.close()


@pytest.mark.asyncio
async def test_clean_start_worker_blocks_linked_regulator(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
                      "clean_start": {"version": 1}, "schedule_pause": {"version": 1,
                      "type": "pause_until_resumed", "id": "p", "station_id": IDENTITY["resolved_id"],
                      "connector_id": 1}}
    monkeypatch.setattr(morek_worker, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target, _start_cap=lambda: 10))
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "protection_conflict_unresolved"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_clean_start_explicit_pause_can_request_held_schedule(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
                      "clean_start": {"version": 1}, "schedule_pause": {"version": 1,
                      "type": "pause_until_resumed", "id": "p", "station_id": IDENTITY["resolved_id"],
                      "connector_id": 1}}
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.ledger.value["attempt"]["source"] == "worker"
    w.worker.close()


@pytest.mark.asyncio
async def test_sync_websocket_recalculates_and_requests_guarded_send(monkeypatch):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    w.planner.async_recalculate = AsyncMock()
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "is_admin", lambda _: True)
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await morek_schedule.websocket_morek_schedule.__wrapped__(w.hass, connection,
        {"id": 1, "api_version": 1, "charger_id": "charger", "action": "recalculate_sync"})
    await drain(w.worker)
    w.planner.async_recalculate.assert_awaited_once()
    connection.send_error.assert_not_called()
    assert connection.send_result.call_args.args[1]["schedule"]["reconciliation"] == "requested"
    assert w.point.call.await_count == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_explicit_sync_resends_acknowledged_plan_but_not_unknown(monkeypatch):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.ledger.value["uncertain"] = True
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert w.point.call.await_count == 2
    assert w.worker.reason == "upload_uncertain"
    w.worker.close()


@pytest.mark.asyncio
async def test_explicit_sync_does_not_override_pause(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
                      "schedule_pause": {"version": 1, "type": "pause_until_resumed", "id": "p",
                                         "station_id": IDENTITY["resolved_id"], "connector_id": 1}}
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert w.point.call.await_count == 0
    assert w.worker.reason == "paused_until_resume"
    w.worker.close()


@pytest.mark.asyncio
async def test_explicit_owned_pause_is_durable_and_worker_requests_held_off(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger")
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(
        async_status=AsyncMock(return_value=status)))
    intent = await morek_schedule.async_record_owned_pause(w.hass, "charger")
    assert intent["type"] == "pause_until_resumed" and w.ledger.value["schedule_pause"] == intent
    assert await morek_schedule.async_record_owned_pause(w.hass, "charger") == intent
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_accepted_unverified"
    assert w.point.call.await_count == 1
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]
    assert [p["limit"] for p in sent["chargingSchedule"]["chargingSchedulePeriod"]] == [0]
    assert w.ledger.value["attempt"]["pause_id"] == intent["id"]
    w.worker.close()
    w.hass.data = {}
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    assert worker.reason == "unchanged"
    assert w.point.call.await_count == 1
    worker.close()


@pytest.mark.asyncio
async def test_legacy_owner_cannot_record_schedule_owned_pause(monkeypatch):
    w = setup(monkeypatch)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (SimpleNamespace(entry_id="charger"), None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    store = SimpleNamespace(async_status=AsyncMock(return_value={"record_state": "valid", "recorded_owner": "legacy"}))
    monkeypatch.setattr(morek_schedule, "ownership_store", Mock(return_value=store))
    with pytest.raises(morek_schedule.ScheduleRefused, match="schedule_owner_unavailable"):
        await morek_schedule.async_record_owned_pause(w.hass, "charger")
    assert w.ledger.value is None
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["conflict", "held_exit", "identity_change", "save_failure"])
async def test_owned_pause_refuses_unsafe_binding_and_save_failure(monkeypatch, change):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    if change == "conflict":
        status["record_state"] = "conflict"
    elif change == "held_exit":
        status.update(recorded_owner="legacy", transition_state="exit_held_unarmed")
    elif change == "identity_change":
        w.identity = {**IDENTITY, "match_count": 2, "reason": "ambiguous_station"}
    else:
        w.ledger.write = AsyncMock(side_effect=OSError("synthetic failure"))
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    with pytest.raises((morek_schedule.ScheduleRefused, OSError)):
        await morek_schedule.async_record_owned_pause(w.hass, "charger")
    assert w.ledger.value is None
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_pause_then_resume_uses_fresh_plan_and_keeps_request(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.planner.current.price_state = "stale"
    intent = await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    assert intent["type"] == "resume_requested" and w.worker.reason == "prices_stale_or_unavailable"
    assert w.point.call.await_count == 1
    w.planner.current.price_state = "ready"
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.ledger.value["schedule_pause"] == intent
    assert w.ledger.value["attempt"]["pause_id"] == intent["id"]
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("charge_now", [False, True])
async def test_settled_resume_recovers_after_restart_and_sends_new_plan(monkeypatch, charge_now):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.worker.close()
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    if charge_now:
        class Clock:
            now = staticmethod(lambda _: NOW)
            fromisoformat = staticmethod(datetime.fromisoformat)
        monkeypatch.setattr(morek_worker, "datetime", Clock)
        w.ledger.value["charge_now"] = {"version": 1, "id": "a" * 32,
            "station_id": IDENTITY["resolved_id"], "connector_id": 1,
            "start": NOW.isoformat(), "end": (NOW + timedelta(hours=1)).isoformat()}
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    assert worker.reason == "upload_accepted_unverified"
    assert w.point.call.await_count == 3
    worker.close()


@pytest.mark.asyncio
async def test_resume_request_survives_restart_without_automatic_dispatch(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    w.worker._available = lambda: False
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    w.worker.close()
    w.hass.data = {}
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    assert w.ledger.value["schedule_pause"]["type"] == "resume_requested"
    assert worker.reason == "resume_requires_confirmation"
    assert w.point.call.await_count == 1
    worker.close()


@pytest.mark.asyncio
async def test_stop_during_dispatched_resume_supersedes_late_ack(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(_request):
        entered.set()
        await release.wait()
        return SimpleNamespace(status="Accepted")
    w.point.call.side_effect = delayed
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        await drain(w.worker)
        hidden = morek_schedule._owned_pause_status(w.ledger.value, {}, False, w.worker, stop_pending=True)
        assert hidden["request"] == "stop_pending" and hidden["ack"] is None
    w.point.call.side_effect = None
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.ledger.value["attempt"]["pause_id"] == w.ledger.value["schedule_pause"]["id"]
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["ledger", "entry_store"])
async def test_stop_during_resume_predispatch_persistence_prevents_send(monkeypatch, boundary):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    _, disk = await morek_schedule._state(w.hass, "charger")
    entered, release = asyncio.Event(), asyncio.Event()
    if boundary == "ledger":
        original = w.ledger.write
        async def blocked(value):
            intent = value.get("schedule_pause") or {}
            attempt = value.get("attempt") or {}
            if intent.get("type") == "resume_requested" and attempt.get("pause_id") == intent.get("id") and not entered.is_set():
                entered.set()
                await release.wait()
            await original(value)
        monkeypatch.setattr(w.ledger, "write", blocked)
    else:
        async def blocked_save(_value):
            entered.set()
            await release.wait()
        disk.async_save.side_effect = blocked_save
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.ledger.value["attempt"]["state"] == "aborted_before_dispatch"
    w.worker.close()


@pytest.mark.asyncio
async def test_manual_api_routes_owned_pause_without_legacy_executor(monkeypatch):
    from custom_components.spotnav.api import manual_action
    from custom_components.spotnav.execution.auto_execution import AutoExecutor
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    controller = MagicMock(ocpp_target=w.target, entry_id="charger")
    monkeypatch.setattr(manual_action, "resolve_charger_request", lambda *_: entry)
    async def owned(action):
        return await morek_schedule.async_maybe_owned_action(w.hass, "charger", action)
    executor = AutoExecutor(w.hass, controller, SimpleNamespace(settings=lambda _: SimpleNamespace(pause=SimpleNamespace(admitted=False))), owned_manual_action=owned)
    monkeypatch.setattr(manual_action, "preview_for", lambda *_: SimpleNamespace(async_manual_action=executor.async_manual_action))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: controller)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    assert await manual_action.async_perform_action(w.hass, "charger", action="stop", choice="until_resumed") == ("stop", "until_resumed")
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.point.call.await_count == 1
    assert await manual_action.async_perform_action(w.hass, "charger", action="resume") == ("resume", None)
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "resume_requested"
    assert w.point.call.await_count == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_offline_direct_physical_pause_persists_without_ocpp(monkeypatch):
    w = setup(monkeypatch)
    w.target.devid = morek_schedule.MOREK_STATION_ID
    w.worker._available = lambda: False
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda *_: {"supported": True, "reason": None,
        "configured_id": morek_schedule.MOREK_STATION_ID, "resolved_id": None, "connector_id": 1,
        "match_count": 0, "ocpp_version": None})
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.worker.reason == "charger_unavailable"
    w.point.call.assert_not_awaited()
    w.worker.close()


def test_offline_alias_binding_requires_one_unambiguous_mapping():
    target = SimpleNamespace(devid="alias", connector_id=1)
    system = SimpleNamespace(cpids={"alias": morek_schedule.MOREK_STATION_ID}, charge_points={})
    hass = SimpleNamespace(data={"ocpp": {"one": system}})
    identity = morek_schedule._intent_identity_status(hass, target)
    assert identity["offline_binding"] == "alias" and morek_schedule._owned_intent_identity_ok(identity)
    hass.data["ocpp"]["two"] = system
    assert not morek_schedule._owned_intent_identity_ok(morek_schedule._intent_identity_status(hass, target))


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["Rejected", "timeout"])
async def test_resume_rejection_and_unknown_do_not_retry(monkeypatch, outcome):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    if outcome == "timeout":
        w.point.call.side_effect = TimeoutError
    else:
        w.point.call.return_value = SimpleNamespace(status=outcome)
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    assert w.worker.reason == ("upload_uncertain" if outcome == "timeout" else "upload_rejected")
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    assert w.ledger.value["schedule_pause"]["type"] == "resume_requested"
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_during_resume_save_invalidates_resume_ticket(monkeypatch):
    from custom_components.spotnav.execution.auto_execution import AutoControlCommitted
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.ledger.write
    async def blocked(value):
        if value.get("schedule_pause", {}).get("type") == "resume_requested":
            entered.set()
            await release.wait()
        await original(value)
    monkeypatch.setattr(w.ledger, "write", blocked)
    task = asyncio.create_task(morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True))
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        with pytest.raises(AutoControlCommitted):
            await task
    w.worker.trigger()
    await drain(w.worker)
    assert w.worker.reason == "resume_requires_confirmation" and w.point.call.await_count == 1
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    w.worker.close()


@pytest.mark.asyncio
async def test_cancelled_resume_save_does_not_authorize_worker(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    entered = asyncio.Event()
    original = w.ledger.write
    async def blocked(value):
        if value.get("schedule_pause", {}).get("type") == "resume_requested":
            entered.set()
            await asyncio.Event().wait()
        await original(value)
    monkeypatch.setattr(w.ledger, "write", blocked)
    task = asyncio.create_task(morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    w.worker.trigger()
    await drain(w.worker)
    assert w.ledger.value["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.worker.resume_ticket is None and w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_reservation_invalidates_queued_worker(monkeypatch):
    """A reserved Stop supersedes queued work before its durable save."""
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        w.admission.release.set()
        await drain(w.worker)
        assert w.point.call.await_count == 0
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["ledger", "entry_store"])
async def test_stop_invalidates_after_worker_persistence_await(monkeypatch, boundary):
    w = setup(monkeypatch)
    _, disk = await morek_schedule._state(w.hass, "charger")
    entered, release = asyncio.Event(), asyncio.Event()
    if boundary == "ledger":
        original = w.ledger.write
        async def blocked(value):
            if not entered.is_set():
                entered.set()
                await release.wait()
            await original(value)
        monkeypatch.setattr(w.ledger, "write", blocked)
    else:
        async def save(_value):
            entered.set()
            await release.wait()
        disk.async_save.side_effect = save
    w.worker.start()
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        await drain(w.worker)
    w.point.call.assert_not_awaited()
    assert w.ledger.value["attempt"]["state"] == "aborted_before_dispatch"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_restart_uses_current_intent_not_cached_profile(monkeypatch, changed):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    old = w.ledger.value["acknowledged"]["fingerprint"]
    w.worker.close()
    if changed:
        start, end = w.planner.current.proposal.shown_periods[0]
        w.planner.current.proposal.shown_periods = ((start, end - timedelta(minutes=10)),)
    # New worker and process-local HA data, but the durable ledger survives.
    w.hass.data = {}
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    assert w.point.call.await_count == 1 + int(changed)
    assert (w.ledger.value["acknowledged"]["fingerprint"] != old) is changed
    worker.close()


@pytest.mark.asyncio
async def test_offline_start_settings_change_and_reconnect_without_browser(monkeypatch):
    w = setup(monkeypatch)
    available = [False]
    w.worker._available = lambda: available[0]
    w.identity = {"supported": False}
    w.worker.start()
    await drain(w.worker)
    w.settings.revision = w.planner.current.settings_revision = 5
    start, end = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end - timedelta(minutes=15)),)
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    token = w.worker.suspend_for_availability_change()
    available[0] = True
    w.identity = dict(IDENTITY)
    w.worker.resume_after_availability_change(token)
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.ledger.value["acknowledged"]["fingerprint"] == w.worker._intent()[1]
    w.worker.close()


@pytest.mark.asyncio
async def test_offline_start_reconnects_with_unchanged_plan_and_alias(monkeypatch):
    w = setup(monkeypatch)
    available = [False]
    w.worker._available = lambda: available[0]
    w.identity = {"supported": False, "connector_id": 1}
    w.worker.start()
    await drain(w.worker)
    token = w.worker.suspend_for_availability_change()
    available[0] = True
    w.identity = {**IDENTITY, "configured_id": "friendly-alias"}
    w.worker.resume_after_availability_change(token)
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_refuses_stale_snapshot_even_if_old_ledger_exists(monkeypatch):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    w.worker.close()
    w.hass.data = {}
    w.settings.revision += 1  # The current settings have no matching publication yet.
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    assert worker.reason == "no_current_plan"
    assert w.point.call.await_count == 1
    worker.close()


@pytest.mark.asyncio
async def test_disconnect_invalidates_queued_work_and_old_reconnect_completion(monkeypatch):
    w = setup(monkeypatch)
    available = [True]
    w.worker._available = lambda: available[0]
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    old = w.worker.suspend_for_availability_change()
    available[0] = False
    w.worker.suspend_for_availability_change()
    w.worker.resume_after_availability_change(old)
    w.admission.release.set()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    assert w.worker.reason == "charger_unavailable"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [
    {"supported": False, "connector_id": 1},
    {**IDENTITY, "match_count": 2, "reason": "ambiguous_station"},
])
async def test_reconnect_unresolved_or_duplicate_identity_never_dispatches(monkeypatch, identity):
    w = setup(monkeypatch)
    w.identity = identity
    w.worker.start()
    await drain(w.worker)
    token = w.worker.suspend_for_availability_change()
    w.worker.resume_after_availability_change(token)
    await drain(w.worker)
    assert w.worker.reason == "identity_unresolved"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_persisted_attempt_blocks_restart_and_reconnect(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    w.worker.close()
    w.hass.data = {}
    w.settings.revision = w.planner.current.settings_revision = 5
    worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    worker.start()
    await drain(worker)
    token = worker.suspend_for_availability_change()
    worker.resume_after_availability_change(token)
    await drain(worker)
    assert worker.reason == "upload_uncertain"
    assert w.ledger.value["uncertain"] is True
    assert w.point.call.await_count == 1
    worker.close()


@pytest.mark.asyncio
async def test_coalesce_deduplicate_and_changed_active_intent(monkeypatch):
    w = setup(monkeypatch, active=True)
    w.worker.start()
    for _ in range(5):
        w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    sent = w.point.call.call_args.args[0].payload["cs_charging_profiles"]
    assert sent["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16
    assert w.worker.reason == "upload_accepted_unverified"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "unchanged"
    start, end = w.planner.current.proposal.shown_periods[0]
    # A routine shortening is preserved through the acknowledged end (Stage 14.2); a later end is a real change.
    w.planner.current.proposal.shown_periods = ((start, end - timedelta(minutes=1)),)
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "unchanged"
    w.planner.current.proposal.shown_periods = ((start, end + timedelta(minutes=10)),)
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_queued_work_rechecks_edit_and_identity(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish()
    w.admission.release.set()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.reason == "upload_accepted_unverified"
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.settings.revision = 6
    w.planner.current.settings_revision = 6
    w.planner.publish()
    await w.admission.entered.wait()
    w.identity = {**IDENTITY, "resolved_id": "different"}
    w.admission.release.set()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "identity_changed"
    w.worker.close()


@pytest.mark.asyncio
async def test_queued_revision_edit_without_new_publication_is_refused(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    w.settings.revision = 5
    w.admission.release.set()
    await drain(w.worker)
    assert w.worker.reason == "no_current_plan"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_definite_rejection_is_not_retried_for_same_intent(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    w.planner.publish()
    await drain(w.worker)
    assert w.worker.reason == "upload_rejected" and w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_plan", "expired", "stale_prices", "unpriced", "invalid", "pending"])
async def test_unavailable_intents_never_send_or_clear(monkeypatch, case):
    w = setup(monkeypatch)
    proposal = w.planner.current.proposal
    if case == "no_plan":
        w.planner.current.proposal = None
    elif case == "expired":
        proposal.shown_periods = ((NOW - timedelta(hours=2), NOW),)
    elif case == "stale_prices":
        w.planner.current.price_state = "stale"
    elif case == "unpriced":
        proposal.unpriced = True
    elif case == "invalid":
        proposal.shown_periods = ((NOW + timedelta(hours=2), NOW + timedelta(hours=1)),)
    else:
        w.planner.current.current = False
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    assert w.worker.reason in {"no_current_plan", "plan_expired", "prices_stale_or_unavailable",
                               "prices_unavailable", "invalid_plan"}
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_upload_blocks_changed_intents_and_reload(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain" and w.point.call.await_count == 1
    w.worker.close()
    w.settings.revision = w.planner.current.settings_revision = 5
    again = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    again.start()
    await drain(again)
    assert again.reason == "upload_uncertain" and w.point.call.await_count == 1
    again.close()


@pytest.mark.asyncio
async def test_real_production_admission_unconditionally_unarmed(monkeypatch):
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": True,
              "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    admission = CommandAdmission(SimpleNamespace(async_status=AsyncMock(return_value=status)))
    w = setup(monkeypatch, admission=admission)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "schedule_mode_unarmed"
    token = w.worker.suspend_for_availability_change()
    w.worker.resume_after_availability_change(token)
    await drain(w.worker)
    assert w.worker.reason == "schedule_mode_unarmed"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_two_workers_serialize_and_share_deduplication(monkeypatch):
    w = setup(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_send(_request):
        entered.set()
        await release.wait()
        return SimpleNamespace(status="Accepted")

    w.point.call.side_effect = slow_send
    other = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    w.worker.start()
    await entered.wait()
    other.start()
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(drain(w.worker), drain(other))
    assert w.point.call.await_count == 1
    assert other.reason == "unchanged"
    w.worker.close()
    other.close()


@pytest.mark.asyncio
async def test_stale_generation_and_cancelled_inflight_fail_closed(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    connector = physical_connector(IDENTITY)
    w.admission._generations[connector] = 1
    w.admission.release.set()
    await drain(w.worker)
    assert w.worker.reason == "stale_generation"
    w.point.call.assert_not_awaited()
    w.admission.entered = None
    entered = asyncio.Event()

    async def waiting(_request):
        entered.set()
        await asyncio.Event().wait()

    w.point.call.side_effect = waiting
    w.planner.publish()
    await entered.wait()
    task = w.worker._task
    w.worker.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    replacement = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    replacement.start()
    await drain(replacement)
    assert replacement.reason == "upload_uncertain" and w.point.call.await_count == 1
    replacement.close()


@pytest.mark.asyncio
async def test_real_planner_publications_drive_worker_without_browser(monkeypatch):
    from .test_stage_13_reactive import _save, _world
    from custom_components.spotnav.vehicles.soc_estimate import SocReader

    world = await _world(monkeypatch)
    w = setup(monkeypatch)
    class Clock:
        now = staticmethod(lambda _: world.request.now)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_worker, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    monkeypatch.setattr(morek_worker, "preview_for", lambda *_: world.controller)
    worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    worker.start()
    await drain(worker)
    assert w.point.call.await_count == 1, worker.reason
    # Settings API and deadline use the real reconciliation and publish path.
    await _save(world, minimum_ready_by_soc=35)
    await drain(worker)
    assert w.point.call.await_count == 2
    local = world.request.now.astimezone(auto_controller_zone(world.request.timezone))
    await _save(world, departure_enabled=True, departure_time=(local + timedelta(hours=1)).strftime("%H:%M"))
    await drain(worker)
    assert w.point.call.await_count == 3
    # An SOC-originated calculation and an actual price subscription event.
    serial = worker._serial
    world.facts[0] = replace(world.facts[0], soc_percent=39)
    reader = object.__new__(SocReader)
    reader._last_notified, reader._notify_next = 25, False
    reader._arrival_cancel, reader._arrival_watched = None, ()
    tasks = []
    reader.set_on_reading(lambda: tasks.append(asyncio.create_task(world.controller.async_recalculate())))
    reader.set_notify_every_reading(lambda: True)
    reader._tell(SimpleNamespace(soc_percent=39))
    await tasks.pop()
    await drain(worker)
    assert worker._serial > serial
    serial = worker._serial
    world.area.today_snapshot.document = replace(world.area.today_snapshot.document, prices=(.05,) * 8)
    published = asyncio.Event()
    remove = world.controller.add_publication_listener(lambda _: published.set())
    published.clear()
    world.listeners[-1](world.area)
    await asyncio.wait_for(published.wait(), timeout=2)
    remove()
    await drain(worker)
    assert worker._serial > serial
    # Even an equal calculation is published to this consumer, but deduplicated on wire.
    count = w.point.call.await_count
    await world.controller.async_recalculate()
    await drain(worker)
    assert w.point.call.await_count == count
    worker.close()


async def real_planner_worker(monkeypatch):
    from .test_stage_13_reactive import _world

    world = await _world(monkeypatch)
    w = setup(monkeypatch)
    class Clock:
        now = staticmethod(lambda _: world.request.now)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_worker, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    monkeypatch.setattr(morek_worker, "preview_for", lambda *_: world.controller)
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    return w, world


async def real_admission_planner_worker(monkeypatch, tmp_path):
    """Use the real planner, ownership, connector gate and disk-backed ledger."""
    import json
    from .test_execution_ownership import FakeHass, FakeStore
    from custom_components.spotnav.execution import command_admission, execution_ownership, morek_outcomes
    from custom_components.spotnav import time_zones

    await time_zones.async_resolve(("Europe/Stockholm",))

    actual_state = morek_schedule._state
    w, world = await real_planner_worker(monkeypatch)
    hass = FakeHass(tmp_path)
    hass.async_create_task = asyncio.create_task
    monkeypatch.setattr(execution_ownership, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    monkeypatch.setattr(morek_schedule, "Store", FakeStore)
    monkeypatch.setattr(morek_schedule, "_state", actual_state)
    monkeypatch.setattr(morek_schedule, "outcomes_for", morek_outcomes.outcomes_for)
    (tmp_path / execution_ownership.STORAGE_KEY).write_text(json.dumps({"version": 1, "data": {
        "schema_version": 1, "records": {"test": {"station_id": IDENTITY["resolved_id"], "connector_id": 1,
            "owner": "morek_schedule", "handover": {"version": 1, "state": "completed", "id": "a" * 32}}}}}), encoding="utf-8")
    (tmp_path / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({"version": 1, "data": {
        "schema": 1, "entry_id": "test", "uncertain": False, "attempt": {"state": "accepted"}}}), encoding="utf-8")
    gate = command_admission.command_admission(hass)
    identity = lambda: w.identity  # noqa: E731
    gate.reserve_lifecycle_barrier("test", identity)
    assert await gate.async_reconfirm_completed("test", identity) == "reconfirmed"
    monkeypatch.setattr(morek_worker, "command_admission", command_admission.command_admission)
    w.hass, w.admission = hass, gate
    w.ledger = morek_outcomes.outcomes_for(hass)
    disk = FakeStore(hass, 1, "entry")
    hass.data[morek_schedule._DATA_KEY] = {"test": ({}, disk, asyncio.Lock())}
    w.worker = morek_worker.MorekScheduleWorker(hass, "test", world.controller)
    return w, world, disk


@pytest.mark.asyncio
async def test_charge_now_real_admission_action_dispatch_and_return(monkeypatch, tmp_path):
    import sys
    from copy import deepcopy
    from custom_components.spotnav import time_zones
    await time_zones.async_resolve(("Europe/Stockholm",))
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.value
    Clock.value = world.request.now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    result = await morek_schedule.async_charge_now_action(w.hass, "test")
    await drain(w.worker)
    assert datetime.fromisoformat(result["intent"]["end"]) == world.request.now + timedelta(hours=1)
    assert w.point.call.await_count == 1, w.worker.reason
    assert (await w.ledger.read())["charge_now"] == result["intent"]
    assert (await w.ledger.read())["attempt"]["state"] == "accepted"
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    data = w.hass.data[morek_schedule._DATA_KEY]["test"][0]
    record = await w.ledger.read()
    assert morek_schedule._verification_current(w.hass, "test", entry, data, record, data["sent_at"])
    for alteration in ("replaced", "canceled", "pause", "connector", "uncertain"):
        stale = deepcopy(record)
        if alteration == "replaced":
            stale["charge_now"]["id"] = "b" * 32
        elif alteration == "canceled":
            stale.pop("charge_now")
        elif alteration == "pause":
            stale["schedule_pause"] = {"id": "new", "type": "pause_until_resumed"}
        elif alteration == "connector":
            stale["charge_now"]["connector_id"] = 2
        else:
            stale["uncertain"] = True
        assert not morek_schedule._verification_current(w.hass, "test", entry, data, stale, data["sent_at"]), alteration
    Clock.value = datetime.fromisoformat(record["charge_now"]["end"])
    assert not morek_schedule._verification_current(w.hass, "test", entry, data, record, data["sent_at"])
    Clock.value = world.request.now
    profile = data["profile"]["chargingSchedule"]
    w.point.call.return_value = SimpleNamespace(status="Accepted", connector_id=1,
        schedule_start=profile["startSchedule"], charging_schedule={**profile, "duration": 172800})
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        GetCompositeSchedule=lambda **kw: SimpleNamespace(payload=kw),
        SetChargingProfile=lambda **kw: SimpleNamespace(payload=kw))))
    readback = await morek_schedule.async_schedule_action(w.hass, "test", "fetch")
    assert readback["verified"] is True
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    previous = await w.ledger.read()
    await morek_schedule.websocket_morek_schedule.__wrapped__(w.hass, connection,
        {"id": 1, "api_version": 1, "charger_id": "test", "action": "status"})
    connection.send_error.assert_not_called()
    status = connection.send_result.call_args.args[1]["schedule"]
    assert status["verification_target"] == "charge_now"
    assert status["charge_now"]["intent"]["id"] == result["intent"]["id"]
    assert await w.ledger.read() == previous
    assert w.point.call.await_count == 2
    w.point.call.return_value = SimpleNamespace(status="Accepted")
    result = await morek_schedule.async_charge_now_action(w.hass, "test", return_to_auto=True)
    assert not morek_schedule._verification_current(w.hass, "test", entry, data, await w.ledger.read(), data["sent_at"])
    await drain(w.worker)
    assert result["intent"] is None
    assert w.point.call.await_count == 3, w.worker.reason
    assert (await w.ledger.read()).get("charge_now") is None
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["ledger", "entry_store", "admission", "dispatch"])
async def test_charge_now_real_admission_stop_races(monkeypatch, tmp_path, boundary):
    w, world, disk = await real_admission_planner_worker(monkeypatch, tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    reached, proceed = asyncio.Event(), asyncio.Event()
    accepted = []
    write = w.ledger.write
    save = disk.async_save
    owned_boundary = w.admission.async_owned_boundary_current
    async def persist(value):
        attempt = value.get("attempt") or {}
        if attempt.get("override_id") and attempt.get("state") == "accepted":
            accepted.append(attempt["id"])
        if boundary == "ledger" and attempt.get("override_id") and attempt.get("state") == "uncertain" and not reached.is_set():
            reached.set()
            await proceed.wait()
        await write(value)
    async def save_entry(value):
        if boundary == "entry_store" and value.get("profile") and not reached.is_set():
            reached.set()
            await proceed.wait()
        await save(value)
    async def call(request):
        if boundary == "dispatch" and not reached.is_set():
            reached.set()
            await proceed.wait()
        return SimpleNamespace(status="Accepted")
    async def check_boundary(*args):
        if boundary == "admission" and not reached.is_set():
            reached.set()
            await proceed.wait()
        return await owned_boundary(*args)
    monkeypatch.setattr(w.ledger, "write", persist)
    monkeypatch.setattr(disk, "async_save", save_entry)
    monkeypatch.setattr(w.admission, "async_owned_boundary_current", check_boundary)
    w.point.call.side_effect = call
    await morek_schedule.async_charge_now_action(w.hass, "test")
    await asyncio.wait_for(reached.wait(), 2)
    stop = asyncio.create_task(morek_schedule.async_record_owned_pause(w.hass, "test"))
    await asyncio.sleep(0)
    proceed.set()
    await asyncio.wait_for(stop, 2)
    await drain(w.worker)
    assert (await w.ledger.read()).get("charge_now") is None
    assert (await w.ledger.read())["schedule_pause"]["type"] == "pause_until_resumed"
    on_calls = [c for c in w.point.call.await_args_list if
                c.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16]
    assert len(on_calls) == (1 if boundary == "dispatch" else 0)
    assert bool(accepted) == (boundary == "dispatch")
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_late_readback_after_stop_is_not_verified(monkeypatch, tmp_path):
    import sys
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    await morek_schedule.async_charge_now_action(w.hass, "test")
    await drain(w.worker)
    data = w.hass.data[morek_schedule._DATA_KEY]["test"][0]
    assert morek_schedule._verification_current(w.hass, "test", entry, data, await w.ledger.read(), data["sent_at"])
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed_read(_):
        reached.set()
        await proceed.wait()
        profile = data["profile"]["chargingSchedule"]
        return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=profile["startSchedule"],
                               charging_schedule={**profile, "duration": 172800})
    w.point.call.side_effect = delayed_read
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        GetCompositeSchedule=lambda **kw: SimpleNamespace(payload=kw))))
    fetch = asyncio.create_task(morek_schedule.async_schedule_action(w.hass, "test", "fetch"))
    await asyncio.wait_for(reached.wait(), 2)
    with w.admission.person_stop_reservation("test", lambda: w.identity):
        proceed.set()
        result = await fetch
        assert result["verified"] is False
    assert (await w.ledger.read()).get("verified") is None
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_real_admission_missing_soc_and_price(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    world.facts[0] = replace(world.facts[0], soc_percent=None)
    world.area.state = "unavailable"
    await morek_schedule.async_charge_now_action(w.hass, "test")
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    assert w.worker.override_degraded is not None
    periods = w.point.call.await_args.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    assert [period["limit"] for period in periods] == [16, 0]
    w.worker.close()


@pytest.mark.asyncio
async def test_held_pause_verification_remains_current_with_real_admission(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: w.admission._store)
    await morek_schedule.async_record_owned_pause(w.hass, "test")
    await drain(w.worker)
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    data = w.hass.data[morek_schedule._DATA_KEY]["test"][0]
    assert morek_schedule._verification_current(w.hass, "test", entry, data, await w.ledger.read(), data["sent_at"])
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_replacement_missing_plan_pause_and_resume(monkeypatch):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.value
    Clock.value = now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    owner = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
             "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value=owner)))
    w.planner.current.in_process = False
    w.settings.pause = SimpleNamespace(admitted=False)
    first = await morek_schedule.async_charge_now_action(w.hass, "charger")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.override_degraded == "no_current_plan"
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]
    assert [p["limit"] for p in sent["chargingSchedule"]["chargingSchedulePeriod"]] == [16, 0]
    Clock.value += timedelta(minutes=10)
    second = await morek_schedule.async_charge_now_action(w.hass, "charger", duration_minutes=30)
    await drain(w.worker)
    assert second["intent"]["id"] != first["intent"]["id"]
    assert datetime.fromisoformat(second["intent"]["end"]) == Clock.value + timedelta(minutes=30)
    await morek_schedule.async_record_owned_pause(w.hass, "charger")
    await drain(w.worker)
    assert w.ledger.value.get("charge_now") is None
    with pytest.raises(morek_schedule.ScheduleRefused, match="resume_auto_first"):
        await morek_schedule.async_charge_now_action(w.hass, "charger")
    await morek_schedule.async_record_owned_pause(w.hass, "charger", resume=True)
    await drain(w.worker)
    assert w.ledger.value.get("charge_now") is None
    assert w.worker.reason == "no_current_plan"
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_rejects_invalid_time_without_writes(monkeypatch):
    w = setup(monkeypatch)
    for kwargs in ({"duration_minutes": 15}, {"duration_minutes": True},
                   {"end_time": "not-a-time"}, {"end_time": "2020-01-01T00:00:00+00:00"},
                   {"duration_minutes": 60, "end_time": "2026-01-01T00:00:00+00:00"}):
        with pytest.raises(morek_schedule.ScheduleRefused):
            await morek_schedule.async_charge_now_action(w.hass, "charger", **kwargs)
    assert not w.ledger.writes
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_charge_now_refuses_unrelated_charger(monkeypatch):
    w = setup(monkeypatch)
    entry = SimpleNamespace(entry_id="other")
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: {**IDENTITY, "resolved_id": "other"})
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    with pytest.raises(morek_schedule.ScheduleRefused, match="identity_unresolved"):
        await morek_schedule.async_charge_now_action(w.hass, "other")
    assert not w.ledger.writes
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [30, 60, 120, 180])
async def test_charge_now_duration_and_custom_end(monkeypatch, minutes):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.value
    Clock.value = now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    w.worker._available = lambda: False
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    owner = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
             "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value=owner)))
    result = await morek_schedule.async_charge_now_action(w.hass, "charger", duration_minutes=minutes)
    assert datetime.fromisoformat(result["intent"]["end"]) == now + timedelta(minutes=minutes)
    Clock.value += timedelta(minutes=5)
    custom = Clock.value + timedelta(minutes=47)
    result = await morek_schedule.async_charge_now_action(w.hass, "charger", end_time=custom.isoformat())
    assert datetime.fromisoformat(result["intent"]["end"]) == custom
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "rejected"])
async def test_charge_now_unknown_or_rejected_not_retried_after_reconnect(monkeypatch, outcome):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    w.planner.current.in_process = False
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
        "charge_now": {"version": 1, "id": "a" * 32, "station_id": IDENTITY["resolved_id"], "connector_id": 1,
                       "start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat()}}
    if outcome == "unknown":
        w.point.call.side_effect = TimeoutError()
    else:
        w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == ("upload_uncertain" if outcome == "unknown" else "upload_rejected")
    assert w.ledger.value["uncertain"] is (outcome == "unknown")
    w.worker.suspend_for_availability_change()
    w.worker.resume_after_availability_change(w.worker._availability_generation)
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_expiry_while_offline_does_not_replay_override(monkeypatch):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.value
    Clock.value = now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    w.planner.current.in_process = False
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
        "charge_now": {"version": 1, "id": "a" * 32, "station_id": IDENTITY["resolved_id"], "connector_id": 1,
                       "start": now.isoformat(), "end": (now + timedelta(minutes=30)).isoformat()}}
    available = [False]
    w.worker._available = lambda: available[0]
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "charger_unavailable" and w.worker._expiry is not None
    w.worker.close()
    Clock.value += timedelta(minutes=31)
    available[0] = True
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner, lambda: available[0])
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "no_current_plan"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_missing_plan_ends_then_auto_can_resume_now(monkeypatch):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.value
    Clock.value = now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    w.planner.current.in_process = False
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
        "charge_now": {"version": 1, "id": "a" * 32, "station_id": IDENTITY["resolved_id"], "connector_id": 1,
                       "start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat()}}
    w.worker.start()
    await drain(w.worker)
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    assert [(row["startPeriod"], row["limit"]) for row in sent] == [(0, 16), (3600, 0)]
    Clock.value += timedelta(hours=1, minutes=1)
    w.planner.current.in_process = True
    w.planner.current.proposal.shown_periods = ((Clock.value - timedelta(minutes=1), Clock.value + timedelta(minutes=30)),)
    w.worker.trigger()
    await drain(w.worker)
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    assert w.point.call.await_count == 2
    assert sent[0]["startPeriod"] == 0 and sent[0]["limit"] == 16
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_restart_and_reconnect_preserve_fixed_end_without_duplicate(monkeypatch):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    w.planner.current.in_process = False
    end = (now + timedelta(hours=1)).isoformat()
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": None,
        "charge_now": {"version": 1, "id": "a" * 32, "station_id": IDENTITY["resolved_id"], "connector_id": 1,
                       "start": now.isoformat(), "end": end}}
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "unchanged"
    generation = w.worker.suspend_for_availability_change()
    w.worker.resume_after_availability_change(generation)
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.ledger.value["charge_now"]["end"] == end
    w.worker.close()


@pytest.mark.asyncio
async def test_charge_now_early_return_to_active_auto_has_no_zero_pulse(monkeypatch):
    w = setup(monkeypatch)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    entry = SimpleNamespace(entry_id="charger", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    owner = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
             "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value=owner)))
    w.planner.current.proposal.shown_periods = ((now - timedelta(minutes=1), now + timedelta(hours=2)),)
    await morek_schedule.async_charge_now_action(w.hass, "charger")
    await drain(w.worker)
    await morek_schedule.async_charge_now_action(w.hass, "charger", return_to_auto=True)
    await drain(w.worker)
    assert w.point.call.await_count == 2
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    assert sent[0]["startPeriod"] == 0 and sent[0]["limit"] == 16
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["ledger", "entry_store"])
@pytest.mark.parametrize("change", ["authority", "state", "document", "coverage", "generation", "source",
                                    "soc", "age", "report", "soc_source", "vehicle", "settings", "connection"])
async def test_real_admission_rechecks_planner_inputs_after_persistence(monkeypatch, tmp_path, boundary, change):
    w, world, disk = await real_admission_planner_worker(monkeypatch, tmp_path)
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = w.ledger.write if boundary == "ledger" else disk.async_save
    async def blocked(value):
        if not reached.is_set():
            reached.set()
            await proceed.wait()
        await original(value)
    monkeypatch.setattr(w.ledger if boundary == "ledger" else disk,
                        "write" if boundary == "ledger" else "async_save", blocked)
    w.worker.start()
    await asyncio.wait_for(reached.wait(), 2)
    if change == "authority":
        world.area.today_authority = "unknown"
    elif change == "state":
        world.area.state = "stale"
    elif change == "document":
        world.area.today_snapshot.document = replace(world.area.today_snapshot.document, prices=(.3,) * 8)
    elif change == "coverage":
        world.area.today_snapshot.document = replace(world.area.today_snapshot.document, intervals=())
    elif change == "generation":
        world.area.generation += 1
    elif change == "source":
        from custom_components.spotnav.pricing.price_source import PriceSource
        from custom_components.spotnav.planning.auto_settings import AreaAutoSettings
        source = PriceSource("price", "charger", world.area.area_id, AreaAutoSettings(area_id=world.area.area_id), None, "new")
        monkeypatch.setattr(world.controller, "_source", lambda: source)
    elif change == "soc":
        world.facts[0] = replace(world.facts[0], soc_percent=30)
    elif change == "age":
        world.facts[0] = replace(world.facts[0], soc_age_s=100000)
    elif change == "report":
        world.facts[0] = replace(world.facts[0], soc_report_at=world.request.now)
    elif change == "soc_source":
        world.facts[0] = replace(world.facts[0], soc_entity_id="sensor.other")
    elif change == "vehicle":
        world.facts[0] = replace(world.facts[0], vehicle_id="other")
    elif change == "settings":
        await world.store.async_update("test", mutate=lambda value: replace(value, minimum_ready_by_soc=35))
    else:
        world.controller._connection_generation += 1
    proceed.set()
    await drain(w.worker)
    if change == "age":
        assert w.point.call.await_count == 1
        w.worker.close()
        return
    assert w.worker.reason in ("price_inputs_changed", "plan_inputs_changed", "vehicle_input_stale", "no_current_plan")
    outcome = await w.ledger.read()
    assert outcome["attempt"]["state"] == "aborted_before_dispatch"
    assert "migration_dispatch_evidence" not in outcome
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_late_ack_never_verifies_during_or_after_stop(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def late_ack(_request):
        reached.set()
        await proceed.wait()
        return SimpleNamespace(status="Accepted")
    w.point.call.side_effect = late_ack
    w.worker.start()
    await asyncio.wait_for(reached.wait(), 2)
    with w.admission.person_stop_reservation("test", lambda: w.identity):
        proceed.set()
        await drain(w.worker)
        data = w.hass.data[morek_schedule._DATA_KEY]["test"][0]
        record = await w.ledger.read()
        assert record["attempt"]["state"] == "accepted"  # historical ACK, not a current confirmation
        assert not morek_schedule._verification_current(w.hass, "test", entry, data, record, data["sent_at"])
    assert not morek_schedule._verification_current(w.hass, "test", entry, data, record, data["sent_at"])
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_fresh_replan_age_and_deduplication(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    world.area.today_authority = "unknown"
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "price_inputs_changed"
    w.point.call.assert_not_awaited()
    world.area.today_authority = "listed"
    world.facts[0] = replace(world.facts[0], soc_age_s=2)
    await world.controller.async_recalculate()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.facts[0] = replace(world.facts[0], soc_age_s=3)
    w.worker.trigger()
    await drain(w.worker)
    assert w.worker.reason == "unchanged" and w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_does_not_retry_unknown_profile_result(monkeypatch, tmp_path):
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    w.point.call.side_effect = TimeoutError()
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain"
    outcome = await w.ledger.read()
    assert outcome["uncertain"] is True and "migration_dispatch_evidence" not in outcome
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.reason == "profile_outcome_unavailable"
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_late_composite_readback_after_stop_is_not_verified(monkeypatch, tmp_path):
    import sys
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return world.request.now
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    morek_schedule._verification_lifecycle(w.hass, "test", entry)
    w.worker.start()
    await drain(w.worker)
    data = w.hass.data[morek_schedule._DATA_KEY]["test"][0]
    record = await w.ledger.read()
    assert morek_schedule._verification_current(w.hass, "test", entry, data, record, data["sent_at"])
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed_read(_request):
        reached.set()
        await proceed.wait()
        profile = data["profile"]["chargingSchedule"]
        return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=profile["startSchedule"],
                               charging_schedule={**profile, "duration": 172800})
    w.point.call.side_effect = delayed_read
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        GetCompositeSchedule=lambda **kw: SimpleNamespace(payload=kw))))
    task = asyncio.create_task(morek_schedule.async_schedule_action(w.hass, "test", "fetch"))
    await asyncio.wait_for(reached.wait(), 2)
    with w.admission.person_stop_reservation("test", lambda: w.identity):
        proceed.set()
        result = await task
    assert not result["verified"]
    assert (await w.ledger.read()).get("verified") is None
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_stop_overtakes_resume_intent_save(monkeypatch, tmp_path):
    from custom_components.spotnav.execution import command_admission, execution_ownership
    from custom_components.spotnav.execution.auto_execution import AutoControlCommitted
    from custom_components.spotnav import time_zones
    await asyncio.to_thread(time_zones.zone, "Europe/Stockholm")
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", command_admission.command_admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", execution_ownership.ownership_store)
    record = await w.ledger.read()
    record["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "old-pause",
                                "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    await w.ledger.write(record)
    original = w.ledger.write
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed(value):
        reached.set()
        await proceed.wait()
        await original(value)
    monkeypatch.setattr(w.ledger, "write", delayed)
    task = asyncio.create_task(morek_schedule.async_record_owned_pause(w.hass, "test", resume=True))
    await asyncio.wait_for(reached.wait(), 2)
    with w.admission.person_stop_reservation("test", lambda: w.identity):
        proceed.set()
        with pytest.raises(AutoControlCommitted):
            await task
    assert w.worker.resume_ticket is None
    assert not w.admission.owned_ticket_current("test", physical_connector(w.identity))
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["manual_kwh", "solar", "hybrid"])
async def test_real_admission_refuses_unsupported_plans(monkeypatch, tmp_path, mode):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    await world.store.async_update("test", mutate=lambda value: replace(
        value, driver="manual_kwh" if mode == "manual_kwh" else value.driver,
        strategy=mode if mode != "manual_kwh" else value.strategy))
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason in ("no_current_plan", "plan_input_provenance_unavailable")
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_real_admission_pending_resume_after_restart_requires_confirmation(monkeypatch, tmp_path):
    w, _, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    record = await w.ledger.read()
    record["schedule_pause"] = {"version": 1, "type": "resume_requested", "id": "old-resume",
                                "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    await w.ledger.write(record)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "resume_requires_confirmation"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_actual_restart_recovers_bound_settled_dispatch_and_sends_fresh_plan(monkeypatch, tmp_path):
    import custom_components.spotnav as integration
    from .test_execution_ownership import FakeHass, FakeStore
    from custom_components.spotnav.execution import command_admission, execution_ownership
    from custom_components.spotnav import time_zones

    if not hasattr(integration, "_async_setup_ownership_metadata"):
        pytest.skip("requires the real integration bootstrap (run with isolated lifecycle runner)")
    await asyncio.to_thread(time_zones.zone, "Europe/Stockholm")

    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    assert await w.admission.async_reconfirm_completed(
        "test", lambda: w.identity, persist_recovery_proof=True) == "reconfirmed"
    w.point.call.assert_not_awaited()
    proof = (await w.ledger.read())["migration_recovery_proof"]
    assert proof["migration_id"] == "a" * 32
    w.worker.close()

    # Fresh process objects, same durable documents; no admin action.
    hass = FakeHass(tmp_path)
    hass.async_create_task = asyncio.create_task
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(executor=None, morek_worker=None),
                            async_on_unload=lambda _: None)
    charger = SimpleNamespace(ocpp_target=w.target, charge_control="switch.charger")
    monkeypatch.setattr(integration, "_identity_status", lambda *_: w.identity)
    monkeypatch.setattr(integration, "async_track_state_change_event", lambda *_: lambda: None)
    release = await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    await release()
    gate = command_admission.command_admission(hass)
    assert isinstance(gate._store, execution_ownership.ExecutionOwnershipStore)
    assert gate.owned_ticket_current("test", physical_connector(w.identity))
    w.point.call.assert_not_awaited()  # recovery itself did not send
    hass.data[morek_schedule._DATA_KEY] = {"test": ({}, FakeStore(hass, 1, "entry-restart"), asyncio.Lock())}
    world.facts[0] = replace(world.facts[0], soc_percent=30)
    await world.controller.async_recalculate()
    worker = morek_worker.MorekScheduleWorker(hass, "test", world.controller)
    worker.start()
    await drain(worker)
    assert worker.reason == "upload_accepted_unverified"
    assert w.point.call.await_count == 1
    worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["state", "authority", "document", "generation", "date", "vehicle", "source"])
async def test_live_inputs_change_without_publication_blocks_worker(monkeypatch, change):
    w, world = await real_planner_worker(monkeypatch)
    if change == "state":
        world.area.state = "stale"
    elif change == "authority":
        world.area.today_authority = "unknown"
    elif change == "document":
        world.area.today_snapshot.document = replace(world.area.today_snapshot.document, prices=(.3,) * 8)
    elif change == "generation":
        world.area.generation += 1
    elif change == "date":
        world.area.today += timedelta(days=1)
    elif change == "vehicle":
        world.facts[0] = replace(world.facts[0], soc_percent=30)
    else:
        from custom_components.spotnav.pricing.price_source import PriceSource
        from custom_components.spotnav.planning.auto_settings import AreaAutoSettings
        source = PriceSource("price", "charger", world.area.area_id, AreaAutoSettings(area_id=world.area.area_id), None, "new")
        monkeypatch.setattr(world.controller, "_source", lambda: source)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason in ("price_inputs_changed", "plan_inputs_changed")
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["ledger", "entry_store"])
async def test_live_source_changes_during_persistence_abort_wire_payload(monkeypatch, boundary):
    w, world = await real_planner_worker(monkeypatch)
    _, disk = await morek_schedule._state(w.hass, "test")
    entered, release = asyncio.Event(), asyncio.Event()
    if boundary == "ledger":
        original = w.ledger.write
        async def blocked(value):
            if value.get("attempt") and not entered.is_set():
                entered.set()
                await release.wait()
            await original(value)
        monkeypatch.setattr(w.ledger, "write", blocked)
    else:
        async def blocked(_value):
            entered.set()
            await release.wait()
        disk.async_save.side_effect = blocked
    w.worker.start()
    await entered.wait()
    world.area.today_authority = "unknown"
    release.set()
    await drain(w.worker)
    assert w.worker.reason == "price_inputs_changed"
    assert w.ledger.value["attempt"]["state"] == "aborted_before_dispatch"
    assert not w.ledger.value["uncertain"]
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_real_plan_coverage_and_fresh_recovery(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    document = world.area.today_snapshot.document
    world.area.today_snapshot.document = replace(document, intervals=())
    await world.controller.async_recalculate()
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "price_coverage_unavailable"
    w.point.call.assert_not_awaited()
    world.area.today_snapshot.document = document
    await world.controller.async_recalculate()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.controller._publish(world.controller.snapshot())
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_pause_ignores_missing_prices_and_resume_preserves_held_limit(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda *_: w.admission)
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda *_: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    world.area.today_authority = "unknown"
    await morek_schedule.async_record_owned_pause(w.hass, "test")
    await drain(w.worker)
    assert w.point.call.await_count == 1
    sent = w.point.call.await_args.args[0].payload["cs_charging_profiles"]
    assert sent["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 0
    await morek_schedule.async_record_owned_pause(w.hass, "test", resume=True)
    await drain(w.worker)
    assert w.worker.reason == "price_inputs_changed"
    assert w.ledger.value["schedule_pause"]["type"] == "resume_requested"
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_unchanged_vehicle_age_does_not_block_reconciliation(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.facts[0] = replace(world.facts[0], soc_age_s=2)
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) is None
    world.facts[0] = replace(world.facts[0], soc_age_s=100000)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_last_known_soc_reconciles_and_new_report_invalidates_then_replans(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    old = world.request.now - timedelta(days=4)
    world.facts[0] = replace(world.facts[0], soc_age_s=4 * 86400, soc_report_at=old, soc_entity_id="sensor.soc")
    world.controller._soc_newest.clear()  # the car's first level of this plug-in (Stage 14.5 order memory)
    await world.controller.async_recalculate()
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) is None
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.facts[0] = replace(world.facts[0], soc_age_s=4 * 86400 + 30)
    w.worker.trigger()
    await drain(w.worker)
    assert w.worker.reason == "unchanged" and w.point.call.await_count == 1
    world.facts[0] = replace(world.facts[0], soc_report_at=world.request.now, soc_age_s=0)
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) == "plan_inputs_changed"
    await world.controller.async_recalculate()
    await drain(w.worker)
    assert w.point.call.await_count == 1  # same intent; a real report does not force a resend
    w.worker.close()


@pytest.mark.asyncio
async def test_preplug_last_known_soc_and_uncapped_estimates_remain_admissible(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    facts = replace(world.facts[0], soc_age_s=86400 * 3, soc_estimated=False)
    world.facts[0] = facts
    world.controller._soc_newest.clear()  # the car's first level of this plug-in (Stage 14.5 order memory)
    await world.controller.async_recalculate()
    old_executor = world.controller._executor
    world.controller._executor = SimpleNamespace(controller=SimpleNamespace(
        plugged_in_for_count=world.request.now - timedelta(hours=1), target_stop_record=None))
    snapshot = replace(world.controller.snapshot(), morek_input_evidence=world.controller._morek_input_evidence(
        world.store.settings("test")))
    assert world.controller.morek_plan_blocker(snapshot, world.request.now) is None
    world.controller._executor = old_executor
    await world.store.async_update("test", mutate=lambda s: replace(s, soft_price_cap=None))
    world.facts[0] = replace(facts, soc_estimated=True)
    world.area.catalogue.market_tz = world.area.catalogue.tz
    world.area.catalogue.publication = SimpleNamespace(tz=world.area.catalogue.tz, local_time=time(13))
    await world.controller.async_recalculate()
    assert world.controller.snapshot().proposal is not None
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) is None
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc),
                                  datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc)])
async def test_utc_interval_coverage_across_dst_and_midnight_with_negative_prices(monkeypatch, start):
    from zoneinfo import ZoneInfo
    from custom_components.spotnav.pricing.relay_contract import PriceInterval

    w, world = await real_planner_worker(monkeypatch)
    # Berlin's repeated 02:00 hour: the two UTC intervals meet despite the clock moving back.
    zone = ZoneInfo("Europe/Berlin")
    rows = tuple(PriceInterval.from_instants(start + timedelta(minutes=30 * i),
                 start + timedelta(minutes=30 * (i + 1)), zone=zone, eur_per_kwh=-.1) for i in range(2))
    doc = replace(world.area.today_snapshot.document, intervals=rows)
    world.area.today_snapshot.document = doc
    snapshot = world.controller.snapshot()
    proposal = replace(snapshot.proposal, periods=((start, start + timedelta(hours=1)),), exact_periods=True)
    snapshot = replace(snapshot, proposal=proposal,
                       morek_price_evidence=world.controller._morek_price_evidence(world.area))
    assert world.controller.morek_plan_blocker(snapshot, start) is None
    world.area.today_snapshot.document = replace(doc, intervals=(rows[0],))
    snapshot = replace(snapshot, morek_price_evidence=world.controller._morek_price_evidence(world.area))
    assert world.controller.morek_plan_blocker(snapshot, start) == "price_coverage_unavailable"
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_tomorrow_window_requires_its_own_authoritative_intervals(monkeypatch):
    from zoneinfo import ZoneInfo
    from custom_components.spotnav.pricing.relay_contract import PriceInterval

    w, world = await real_planner_worker(monkeypatch)
    start = datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc)
    zone = ZoneInfo("Europe/Berlin")
    first = PriceInterval.from_instants(start, start + timedelta(minutes=30), zone=zone, eur_per_kwh=-.1)
    second = PriceInterval.from_instants(first.utc_end, first.utc_end + timedelta(minutes=30), zone=zone, eur_per_kwh=.2)
    doc = world.area.today_snapshot.document
    world.area.today_snapshot.document = replace(doc, intervals=(first,))
    world.area.tomorrow_snapshot.document = replace(doc, intervals=(second,))
    original = world.controller.snapshot()
    snapshot = replace(original, proposal=replace(original.proposal, periods=((start, second.utc_end),), exact_periods=True))
    snapshot = replace(snapshot, morek_price_evidence=world.controller._morek_price_evidence(world.area))
    assert world.controller.morek_plan_blocker(snapshot, start) == "price_coverage_unavailable"
    world.area.state = "ready"
    world.area.tomorrow_state = "ready"
    world.area.tomorrow_authority = "listed"
    snapshot = replace(snapshot, morek_price_evidence=world.controller._morek_price_evidence(world.area))
    assert world.controller.morek_plan_blocker(snapshot, start) is None
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_area_snapshot_authority_change_without_publication(monkeypatch):
    from custom_components.spotnav.pricing.price_refresh import PriceRefreshManager
    from custom_components.spotnav.pricing.price_repository import DaySnapshot

    w, world = await real_planner_worker(monkeypatch)
    old = world.area
    today = DaySnapshot(old.area_id, old.today, "ready", old.today_snapshot.document,
                        None, old.fetched_at, None, None, "listed", False)
    tomorrow = DaySnapshot(old.area_id, old.tomorrow, "unavailable", None,
                           None, None, None, None, "not_listed", False)
    authority = {old.today: "listed", old.tomorrow: "not_listed"}
    repository = SimpleNamespace(day_snapshot=lambda _area, day: today if day == old.today else tomorrow,
                                 file_authority=lambda _area, day: authority[day],
                                 area_entry=lambda _area: old.catalogue)
    manager = object.__new__(PriceRefreshManager)
    manager._now = lambda: world.request.now
    manager._repository = repository
    manager._next_global_attempt = None
    manager._areas = {old.area_id: SimpleNamespace(active=True, area_id=old.area_id, tz=doc_zone(old),
                                                   principal=lambda day: day, generation=1,
                                                   subscriber_count=1)}
    monkeypatch.setattr(world.controller, "_manager", manager)
    await world.controller.async_recalculate()
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) is None
    authority[old.today] = "unknown"
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "price_inputs_changed"
    w.point.call.assert_not_awaited()
    w.worker.close()


def doc_zone(area):
    return area.catalogue.tz


def auto_controller_zone(name):
    from custom_components.spotnav import time_zones
    return time_zones.require_zone(name)


def manual_setup(monkeypatch):
    import sys
    w = setup(monkeypatch)
    w.settings.pause = SimpleNamespace(choice="until_resumed")
    entry = SimpleNamespace(entry_id="charger", async_on_unload=lambda _: None)
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=w.target))
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: w.admission)
    monkeypatch.setattr(morek_schedule, "async_call_later", lambda *_: lambda: None)
    class Clock:
        now = staticmethod(lambda _: NOW)
        fromisoformat = staticmethod(datetime.fromisoformat)
    monkeypatch.setattr(morek_schedule, "datetime", Clock)
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        SetChargingProfile=lambda **kw: SimpleNamespace(action="send", payload=kw),
        GetCompositeSchedule=lambda **kw: SimpleNamespace(action="fetch", payload=kw),
        ClearChargingProfile=lambda **kw: SimpleNamespace(action="clear", payload=kw))))
    return w


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["send", "clear"])
@pytest.mark.parametrize("boundary", ["ledger", "entry_store"])
async def test_manual_profile_stop_during_persistence_aborts_before_dispatch(monkeypatch, action, boundary):
    w = manual_setup(monkeypatch)
    _, disk = await morek_schedule._state(w.hass, "charger")
    entered, release = asyncio.Event(), asyncio.Event()
    if boundary == "ledger":
        original = w.ledger.write
        async def blocked(value):
            if (value.get("attempt") or value.get("removal")) and not entered.is_set():
                entered.set()
                await release.wait()
            await original(value)
        monkeypatch.setattr(w.ledger, "write", blocked)
    else:
        async def blocked(_value):
            entered.set()
            await release.wait()
        disk.async_save.side_effect = blocked
    task = asyncio.create_task(morek_schedule.async_schedule_action(
        w.hass, "charger", action, w.worker._intent()[1] if action == "send" else None,
        confirm_profile_id=42001 if action == "clear" else None))
    await entered.wait()
    with w.admission.person_stop_reservation("charger", lambda: w.identity):
        release.set()
        with pytest.raises(morek_schedule.ScheduleRefused, match="stale_generation"):
            await task
    field = "attempt" if action == "send" else "removal"
    assert w.ledger.value[field]["state"] == "aborted_before_dispatch"
    assert not w.ledger.value["uncertain"]
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_hold_worker_bounded_readback_is_not_measured_stop(monkeypatch):
    w = manual_setup(monkeypatch)
    w.ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "desired": None,
                      "attempt": None, "acknowledged": None, "verified": None, "removal": None,
                      "schedule_pause": {"version": 1, "type": "pause_until_resumed", "id": "pause-a",
                                         "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}}
    callbacks = []
    monkeypatch.setattr(morek_schedule, "async_call_later", lambda _h, _delay, callback: callbacks.append(callback) or (lambda: None))
    async def call(request):
        if request.action == "send":
            return SimpleNamespace(status="Accepted")
        return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=NOW.isoformat(),
                               charging_schedule={"chargingRateUnit": "A", "duration": 7200,
                                                  "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0}]})
    w.point.call.side_effect = call
    w.worker.start()
    await drain(w.worker)
    await callbacks[0](NOW)
    data = w.hass.data[morek_schedule._DATA_KEY]["charger"][0]
    status = morek_schedule._owned_pause_status(w.ledger.value, data["verification"], data["verified"], w.worker)
    assert status["readback"] == "bounded_match" and status["measured"] == "unknown"
    assert status["coverage_end"] == (NOW + timedelta(hours=1)).isoformat()
    w.worker.close()


@pytest.mark.asyncio
async def test_worker_starts_bounded_read_after_releasing_connector(monkeypatch):
    w = manual_setup(monkeypatch)
    callbacks, delays = [], []
    def later(_hass, delay, callback):
        assert not w.admission._lock_for(physical_connector(IDENTITY)).locked()
        callbacks.append(callback)
        delays.append(delay)
        return lambda: None
    monkeypatch.setattr(morek_schedule, "async_call_later", later)
    async def call(request):
        if request.action == "send":
            return SimpleNamespace(status="Accepted")
        return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=NOW.isoformat(),
                               charging_schedule={"chargingRateUnit": "A", "duration": 14400,
                                                  "chargingSchedulePeriod": [
                                                      {"startPeriod": 0, "limit": 0},
                                                      {"startPeriod": 3600, "limit": 16},
                                                      {"startPeriod": 7200, "limit": 0}]})
    w.point.call.side_effect = call
    w.worker.start()
    await drain(w.worker)
    assert delays == [0]
    await callbacks[0](NOW)
    assert w.point.call.await_count == 2
    assert w.ledger.value["verified"]["attempt_id"] == w.ledger.value["attempt"]["id"]
    assert delays == [0]
    w.worker.close()


@pytest.mark.asyncio
async def test_worker_mismatch_checks_are_bounded_and_read_only(monkeypatch):
    w = manual_setup(monkeypatch)
    callbacks, delays, calls = [], [], []
    def later(_hass, delay, callback):
        callbacks.append(callback)
        delays.append(delay)
        return lambda: None
    monkeypatch.setattr(morek_schedule, "async_call_later", later)
    async def call(request):
        calls.append(request.action)
        if request.action == "send":
            return SimpleNamespace(status="Accepted")
        return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=NOW.isoformat(),
                               charging_schedule={"chargingRateUnit": "A", "duration": 14400,
                                                  "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 16}]})
    w.point.call.side_effect = call
    w.worker.start()
    await drain(w.worker)
    for i in range(4):
        await callbacks[i](NOW)
    assert delays == [0, 30, 45, 45]
    assert calls == ["send", "fetch", "fetch", "fetch", "fetch"]
    assert w.ledger.value["verified"] is None
    w.worker.close()


@pytest.mark.asyncio
async def test_manual_and_worker_share_lock_and_persisted_outcomes(monkeypatch):
    w = manual_setup(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def call(request):
        calls.append(request.action)
        if len(calls) == 1:
            # Durable attempt is present before crossing the charger boundary.
            assert w.ledger.value["attempt"]["state"] == "uncertain"
            entered.set()
            await release.wait()
        if request.action == "fetch":
            return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=NOW.isoformat(),
                                   charging_schedule={"chargingRateUnit": "A", "duration": 14400,
                                                      "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 16}]})
        return SimpleNamespace(status="Accepted")

    w.point.call.side_effect = call
    w.worker.start()
    await entered.wait()
    fingerprint = w.worker._intent()[1]
    manual = asyncio.create_task(morek_schedule.async_schedule_action(w.hass, "charger", "send", fingerprint))
    await asyncio.sleep(0)
    assert calls == ["send"]
    release.set()
    await drain(w.worker)
    result = await manual
    assert calls == ["send", "send", "fetch"]
    assert result["outcomes"]["attempt"]["source"] == "manual"
    assert result["outcomes"]["acknowledged"]["fingerprint"] == fingerprint
    assert result["verified"] is False
    w.planner.publish()
    await drain(w.worker)
    assert w.worker.reason == "unchanged" and calls == ["send", "send", "fetch"]
    # Selective removal invalidates the accepted fingerprint; it does not clear
    # any other profile or let a subsequent worker deduplicate against old state.
    result = await morek_schedule.async_schedule_action(w.hass, "charger", "clear", confirm_profile_id=42001)
    assert result["outcomes"]["acknowledged"] is None
    assert calls[-2:] == ["clear", "fetch"]
    w.planner.publish()
    await drain(w.worker)
    assert calls[-1] == "send" and w.worker.reason == "upload_accepted_unverified"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["Rejected", "timeout", "cancel"])
async def test_manual_uncertain_or_rejected_outcome_and_no_automatic_retry(monkeypatch, status):
    w = manual_setup(monkeypatch)
    entered = asyncio.Event()

    async def call(_request):
        assert w.ledger.value["attempt"]["state"] == "uncertain"
        entered.set()
        if status == "timeout":
            raise TimeoutError
        if status == "cancel":
            await asyncio.Event().wait()
        return SimpleNamespace(status=status)

    w.point.call.side_effect = call
    fingerprint = w.worker._intent()[1]
    task = asyncio.create_task(morek_schedule.async_schedule_action(w.hass, "charger", "send", fingerprint))
    await entered.wait()
    if status == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(morek_schedule.ScheduleRefused):
            await task
    assert w.ledger.value["uncertain"] is (status != "Rejected")
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.reason == ("upload_rejected" if status == "Rejected" else "upload_uncertain")
    w.worker.close()


@pytest.mark.asyncio
async def test_edit_during_attempt_persistence_cannot_dispatch(monkeypatch):
    w = manual_setup(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = w.ledger.write

    async def slow_write(value):
        if not entered.is_set():
            await original(value)
            entered.set()
            await release.wait()
        else:
            await original(value)

    w.ledger.write = slow_write
    fingerprint = w.worker._intent()[1]
    send = asyncio.create_task(morek_schedule.async_schedule_action(w.hass, "charger", "send", fingerprint))
    await entered.wait()
    w.settings.pause.choice = "none"
    release.set()
    with pytest.raises(morek_schedule.ScheduleRefused, match="pause_auto_first"):
        await send
    assert w.ledger.value["attempt"]["state"] == "aborted_before_dispatch"
    assert w.ledger.value["uncertain"] is False
    w.point.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_entry_cannot_take_over_connector_evidence(monkeypatch):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    other = morek_worker.MorekScheduleWorker(w.hass, "another", w.planner)
    other.start()
    await drain(other)
    assert other.reason == "outcome_binding_unavailable"
    assert w.point.call.await_count == 1
    w.worker.close()
    other.close()


@pytest.mark.asyncio
async def test_manual_replacement_invalidates_old_worker_fingerprint(monkeypatch):
    w = manual_setup(monkeypatch)

    async def call(request):
        if request.action == "fetch":
            return SimpleNamespace(status="Accepted", connector_id=1, schedule_start=NOW.isoformat(),
                                   charging_schedule={"chargingRateUnit": "A", "duration": 14400,
                                                      "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 16}]})
        return SimpleNamespace(status="Accepted")

    w.point.call.side_effect = call
    w.worker.start()
    await drain(w.worker)
    first = w.planner.current.proposal.shown_periods
    start, end = first[0]
    w.planner.current.proposal.shown_periods = ((start, end - timedelta(minutes=5)),)
    second = w.worker._intent()[1]
    await morek_schedule.async_schedule_action(w.hass, "charger", "send", second)
    assert w.ledger.value["acknowledged"]["fingerprint"] == second
    w.planner.current.proposal.shown_periods = first
    w.planner.publish()
    await drain(w.worker)
    assert w.worker.reason == "upload_accepted_unverified"
    assert w.point.call.await_count == 4  # worker, manual send/read, worker
    w.worker.close()


@pytest.mark.asyncio
async def test_legacy_uncertain_migration_blocks_manual_and_worker(monkeypatch):
    w = manual_setup(monkeypatch)
    data, _ = await morek_schedule._state(w.hass, "charger")
    data.update({"profile": {"legacy": True}, "ack": "unknown"})
    fingerprint = w.worker._intent()[1]
    with pytest.raises(morek_schedule.ScheduleRefused, match="upload_uncertain"):
        await morek_schedule.async_schedule_action(w.hass, "charger", "send", fingerprint)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain"
    w.point.call.assert_not_awaited()
    w.worker.close()
