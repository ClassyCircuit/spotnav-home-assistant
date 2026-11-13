"""Session coordinator through the real connector admission boundary with mocked HA."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution import execution_ownership, morek_outcomes
from custom_components.spotnav.execution.command_admission import CommandAdmission, physical_connector
from .morek_fakes import MemoryOutcomes

IDENTITY = {"supported": True, "resolved_id": morek_schedule.MOREK_STATION_ID,
            "connector_id": 1, "match_count": 1, "ocpp_version": "1.6"}


class Point:
    __module__ = "custom_components.ocpp.ocppv16"

    def __init__(self, result=True):
        self.logger = logging.getLogger("ocpp.test_session")
        self._connection = SimpleNamespace(logger=logging.getLogger("websockets.test_session"))
        self.result = result
        self.calls = 0

    async def start_transaction(self, connector_id):
        self.calls += 1
        logging.getLogger("custom_components.ocpp").info("tag %s", "SENTINEL_PRIVATE_TAG")
        self.logger.info("sent %s", "SENTINEL_PRIVATE_TAG")
        self._connection.logger.debug("frame %s", "SENTINEL_PRIVATE_TAG")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def setup(monkeypatch, result=True):
    hass = SimpleNamespace(data={}, async_create_task=asyncio.create_task)
    ledger = MemoryOutcomes()
    ledger.value = {"schema": 1, "entry_id": "charger", "uncertain": False, "attempt": {"state": "accepted"}}
    connector = physical_connector(IDENTITY)
    handover_id = "a" * 32
    records = {"charger": {"owner": "morek_schedule", "station_id": connector.station_id,
                           "connector_id": connector.connector_id,
                           "handover": {"version": 1, "state": "completed", "id": handover_id}}}
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "handover_evidence": "completed",
              "handover_id": handover_id, "station_id": connector.station_id, "connector_id": 1}
    hass.async_add_executor_job = AsyncMock(return_value=object())
    store = SimpleNamespace(_hass=hass, _lock=asyncio.Lock(), _store=SimpleNamespace(path="unused"),
                            _records=records, _state="valid", _transition_save_uncertain=False,
                            _cancelled_write=False, async_status=AsyncMock(return_value=status))
    admission = CommandAdmission(store)
    admission._completion_tickets["charger"] = (connector, handover_id, 0, admission.generation(connector))
    monkeypatch.setattr(execution_ownership, "_decode", lambda _: ("valid", records))
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: ledger)
    point = Point(result)
    controller = SimpleNamespace(ocpp_target=SimpleNamespace(connector_id=1))
    worker = SimpleNamespace(_hass=hass, _entry_id="charger", _identity=lambda: IDENTITY,
                             _closed=False, _suspended=False, _available=lambda: True,
                             _intent=lambda pause: ({}, "plan"), resume_ticket=None)
    async def state(h, entry):
        return h.data.setdefault(morek_schedule._DATA_KEY, {}).setdefault(entry, ({}, None, asyncio.Lock()))[:2]
    monkeypatch.setattr(morek_schedule, "_state", state)
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda _: ledger)
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda *_: point)
    monkeypatch.setattr(morek_session, "command_admission", lambda _: admission)
    monkeypatch.setattr(morek_session, "controller_for", lambda *_: controller)
    monkeypatch.setattr(morek_session, "domain_data", lambda *_: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda _: SimpleNamespace(pause=SimpleNamespace(admitted=False)))))
    monkeypatch.setattr(morek_session, "_safe_logging", lambda _: True)
    return morek_session.MorekSessionCoordinator(worker), point, ledger, admission


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "state"), [(True, "accepted"), (False, "rejected"),
                                                 (TimeoutError(), "unknown"), (ValueError(), "unknown")])
async def test_plugin_one_request_and_no_secret_logs(monkeypatch, caplog, answer, state):
    coordinator, point, ledger, _ = setup(monkeypatch, answer)
    caplog.set_level(logging.DEBUG)
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == state
    assert "SENTINEL_PRIVATE_TAG" not in caplog.text
    coordinator.observe("Preparing", "Preparing")
    coordinator.trigger()
    await coordinator.task
    assert point.calls == 1


@pytest.mark.asyncio
async def test_unknown_survives_unplug_replug(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch, TimeoutError())
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    coordinator.observe("Preparing", "Available")
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 1
    assert coordinator.state["state"] == "uncertain"


@pytest.mark.asyncio
async def test_pause_blocks_ambiguous_preparing(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.observe(None, "Preparing")
    await coordinator.task
    assert point.calls == 0
    assert coordinator.state["reason"] == "paused_until_resume"


@pytest.mark.asyncio
async def test_initial_preparing_recovery_is_deduplicated_after_restart(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.observe(None, "Preparing")
    await coordinator.task
    assert point.calls == 1
    assert ledger.value["session_start"]["connection"] == "recovery"
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await restarted.task
    assert point.calls == 1
    assert restarted.state["reason"] == "already_requested"


@pytest.mark.asyncio
async def test_reconnect_allows_one_ambiguous_recovery_after_plugin(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    coordinator.offline()
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 2
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 2


@pytest.mark.asyncio
async def test_offline_online_sensor_arrives_later_and_unknown_blocks(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch, TimeoutError())
    coordinator.observe(None, "Preparing")
    await coordinator.task
    coordinator.offline()
    coordinator.observe("Preparing", "Unavailable")
    coordinator.reconnect()
    await coordinator.task
    coordinator.observe("Unavailable", "Preparing")
    await coordinator.task
    assert point.calls == 1
    assert coordinator.state["state"] == "uncertain"


@pytest.mark.asyncio
async def test_multiple_observed_disconnects_create_bounded_opportunities(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.observe(None, "Preparing")
    await coordinator.task
    for expected in (2, 3):
        coordinator.offline()
        coordinator.reconnect()
        await coordinator.task
        assert point.calls == expected
        coordinator.reconnect()
        await coordinator.task
        assert point.calls == expected
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await restarted.task
    assert point.calls == 3
    assert ledger.value["session_start"]["connection"].startswith("offline:")


@pytest.mark.asyncio
async def test_second_genuine_charger_restart_needs_a_new_recovery_generation(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    point.charger_generation = 1
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    point.charger_generation = 2
    coordinator.reconnect()
    await coordinator.task
    point.charger_generation = 3
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 3


@pytest.mark.asyncio
async def test_reported_surviving_session_never_restarts(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.observe(None, "SuspendedEVSE")
    coordinator.offline()
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 0


@pytest.mark.asyncio
async def test_resume_uses_distinct_durable_generation(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    connector = physical_connector(IDENTITY)
    generation = admission.generation(connector)
    ledger.value["schedule_pause"] = {"version": 1, "type": "resume_requested", "id": "p",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.worker.resume_ticket = ("p", generation)
    coordinator.observation = "preparing"
    coordinator.resume("p")
    await coordinator.task
    assert point.calls == 1
    assert ledger.value["session_start"]["connection"] == "resume:p"
    coordinator.resume("p")
    await coordinator.task
    assert point.calls == 1


@pytest.mark.asyncio
async def test_initial_event_through_real_admission(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    connector = physical_connector(IDENTITY)
    handover_id = "a" * 32
    records = {"charger": {"owner": "morek_schedule", "station_id": connector.station_id,
                           "connector_id": connector.connector_id,
                           "handover": {"version": 1, "state": "completed", "id": handover_id}}}
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "handover_evidence": "completed",
              "handover_id": handover_id, "station_id": connector.station_id, "connector_id": 1}
    hass = coordinator.hass
    hass.async_add_executor_job = AsyncMock(return_value=object())
    store = SimpleNamespace(_hass=hass, _lock=asyncio.Lock(), _store=SimpleNamespace(path="unused"),
                            _records=records, _state="valid", _transition_save_uncertain=False,
                            _cancelled_write=False, async_status=AsyncMock(return_value=status))
    admission = CommandAdmission(store)
    admission._completion_tickets["charger"] = (connector, handover_id, 0, admission.generation(connector))
    monkeypatch.setattr(execution_ownership, "_decode", lambda _: ("valid", records))
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: ledger)
    monkeypatch.setattr(morek_session, "command_admission", lambda _: admission)
    coordinator.observe(None, "Preparing")
    await coordinator.task
    assert point.calls == 1
    assert ledger.value["session_start"]["state"] == "accepted"
    coordinator.offline()
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 2
    assert ledger.value["session_start"]["connection"].startswith("offline:")
    coordinator.reconnect()
    await coordinator.task
    assert point.calls == 2
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await restarted.task
    assert point.calls == 2
    assert restarted.state["reason"] == "already_requested"


@pytest.mark.asyncio
async def test_actual_resume_action_notifies_coordinator(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "old",
                                      "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    coordinator.observation = "preparing"
    worker = coordinator.worker
    worker.session = coordinator
    worker.trigger = lambda: None
    controller = SimpleNamespace(ocpp_target=SimpleNamespace(connector_id=1))
    entry = SimpleNamespace(runtime_data=SimpleNamespace(morek_worker=worker))
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": False,
              "transition_state": None, "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: controller)
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: IDENTITY)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: admission)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: SimpleNamespace(async_status=AsyncMock(return_value=status)))
    await morek_schedule.async_record_owned_pause(coordinator.hass, "charger", resume=True)
    await coordinator.task
    assert point.calls == 1
    assert ledger.value["session_start"]["connection"].startswith("resume:")


@pytest.mark.asyncio
async def test_unplug_replug_after_accepted_is_new_connection(monkeypatch):
    coordinator, point, _, _ = setup(monkeypatch)
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    coordinator.observe("Preparing", "Available")
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 2


@pytest.mark.asyncio
async def test_stop_at_persistence_boundary_prevents_request(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    original = ledger.write
    async def stop_before_return(value):
        await original(value)
        connector = physical_connector(IDENTITY)
        admission._person_stops[connector] = 1
    monkeypatch.setattr(ledger, "write", stop_before_return)
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 0
    assert ledger.value["session_start"]["state"] == "aborted_before_dispatch"


@pytest.mark.asyncio
async def test_stop_while_waiting_for_real_admission_prevents_start(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    connector = physical_connector(IDENTITY)
    async with admission._lock_for(connector):
        coordinator.observe("Available", "Preparing")
        await asyncio.sleep(0)
        admission._person_stops[connector] = 1
    await coordinator.task
    assert point.calls == 0
    assert "session_start" not in ledger.value
    assert coordinator.state["reason"] == "stale_generation"


@pytest.mark.asyncio
async def test_production_gate_blocks_sensitive_logging(monkeypatch, caplog):
    actual_gate = morek_session._safe_logging
    coordinator, point, ledger, _ = setup(monkeypatch)
    monkeypatch.setattr(morek_session, "_safe_logging", actual_gate)
    caplog.set_level(logging.INFO, logger="custom_components.ocpp")
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 0
    assert "session_start" not in ledger.value
    assert coordinator.state["reason"] == "ocpp_sensitive_logging_enabled"


@pytest.mark.asyncio
async def test_unsupported_interface_never_dispatches(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    monkeypatch.setattr(morek_session, "_request_loggers", lambda _: None)
    coordinator.observe("Available", "Preparing")
    await coordinator.task
    assert point.calls == 0
    assert "session_start" not in ledger.value
    assert coordinator.state["reason"] == "unsupported_ocpp_logging_or_interface"


@pytest.mark.asyncio
async def test_completion_record_prevents_ambiguous_restart(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.observe("Charging", "Finishing")
    await coordinator.task
    assert ledger.value["session_completed"] is True
    restarted = morek_session.MorekSessionCoordinator(coordinator.worker)
    restarted.observe(None, "Preparing")
    await restarted.task
    assert point.calls == 0
    assert restarted.state["reason"] == "car_completion_reported"
    restarted.offline()
    restarted.reconnect()
    await restarted.task
    assert point.calls == 0


@pytest.mark.asyncio
async def test_completion_event_is_not_lost_to_immediate_preparing(monkeypatch):
    coordinator, point, ledger, _ = setup(monkeypatch)
    coordinator.observe("Charging", "Finishing")
    coordinator.observe("Finishing", "Preparing")
    await coordinator.task
    assert point.calls == 0
    assert ledger.value["session_completed"] is True


@pytest.mark.asyncio
async def test_cancellation_retains_pending_and_does_not_leak(monkeypatch, caplog):
    coordinator, point, ledger, _ = setup(monkeypatch)
    started = asyncio.Event()
    gate = asyncio.Event()
    async def delayed(connector_id):
        point.logger.info("payload idTag=%s", "SENTINEL_PRIVATE_TAG")
        started.set()
        await gate.wait()
        return True
    point.start_transaction = delayed
    caplog.set_level(logging.INFO)
    coordinator.observe("Available", "Preparing")
    await started.wait()
    coordinator.close()
    with pytest.raises(asyncio.CancelledError):
        await coordinator.task
    assert ledger.value["session_start"]["state"] == "pending"
    assert "SENTINEL_PRIVATE_TAG" not in caplog.text


@pytest.mark.asyncio
async def test_late_ack_does_not_override_stop(monkeypatch):
    coordinator, point, ledger, admission = setup(monkeypatch)
    started, gate = asyncio.Event(), asyncio.Event()
    async def delayed(connector_id):
        started.set()
        await gate.wait()
        return True
    point.start_transaction = delayed
    coordinator.observe("Available", "Preparing")
    await started.wait()
    admission._person_stops[physical_connector(IDENTITY)] = 1
    gate.set()
    await coordinator.task
    assert ledger.value["session_start"]["state"] == "accepted"
    assert coordinator.state["reason"] == "newer_stop_or_connection_change"


@pytest.mark.asyncio
async def test_request_filter_keeps_other_task_logs(caplog):
    point = Point()
    caplog.set_level(logging.INFO)
    entered, finish = asyncio.Event(), asyncio.Event()
    async def delayed(connector_id):
        point.logger.info('wire {"idTag":"%s"}', "SENTINEL_PRIVATE_TAG")
        entered.set()
        await finish.wait()
        return True
    point.start_transaction = delayed
    task = asyncio.create_task(morek_session._start(point, 1))
    await entered.wait()
    point.logger.info("other charger diagnostic")
    finish.set()
    assert await task == "accepted"
    assert "SENTINEL_PRIVATE_TAG" not in caplog.text
    assert "other charger diagnostic" in caplog.text


def test_sensitive_logging_runtime_conditions_block():
    point = Point()
    loggers = [logging.getLogger("custom_components.ocpp"), point.logger, point._connection.logger]
    old_levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.WARNING)
        assert morek_session._safe_logging(point)
        point.logger.setLevel(logging.INFO)
        assert not morek_session._safe_logging(point)
        point.logger.setLevel(logging.WARNING)
        point._connection.logger.setLevel(logging.DEBUG)
        assert not morek_session._safe_logging(point)
        point._connection.logger.setLevel(logging.WARNING)
        loggers[0].setLevel(logging.INFO)
        assert not morek_session._safe_logging(point)
    finally:
        for logger, level in zip(loggers, old_levels):
            logger.setLevel(level)


def test_unavailable_switch_does_not_imply_ocpp_disconnected(monkeypatch):
    coordinator, _, _, _ = setup(monkeypatch)
    monkeypatch.setattr(morek_schedule, "_intent_identity_status", lambda *_: IDENTITY)
    coordinator.availability_lost()
    assert not coordinator.offline_observed
    def offline(*_):
        raise morek_schedule.ScheduleRefused("morek_offline")
    monkeypatch.setattr(morek_schedule, "_charge_point", offline)
    coordinator.availability_lost()
    assert coordinator.offline_observed
