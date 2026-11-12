"""Combined ownership/startup/restore regressions; actual modules, mocked HA and charger I/O."""

import ast
import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.spotnav as integration
from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.const import MOREK_STATION_ID
from custom_components.spotnav.execution import charger_handback, command_admission, controller as controller_module
from custom_components.spotnav.execution import execution_ownership
from custom_components.spotnav.execution.chargers.adapter import ChargerAdapter
from custom_components.spotnav.execution.chargers.base import PhaseSwitchResult
from custom_components.spotnav.execution.auto_execution import AutoControlCommitted, AutoControlRefused, AutoExecutor
from custom_components.spotnav.execution.controller import ChargingController, ChargingPlan
from custom_components.spotnav.planning.auto_settings import AutoSettings

from .test_execution_ownership import FakeHass, FakeStore


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_ownership, "Store", FakeStore)
    hass = FakeHass(tmp_path)
    store = execution_ownership.ownership_store(hass)
    gate = command_admission.command_admission(hass)
    target = SimpleNamespace(devid="alias-a", connector_id=1)
    point = SimpleNamespace(_ocpp_version="1.6", status="ok")
    system = SimpleNamespace(cpids={"alias-a": MOREK_STATION_ID, "alias-b": MOREK_STATION_ID},
                             charge_points={MOREK_STATION_ID: point})
    hass.data["ocpp"] = {"one": system}
    monkeypatch.setattr(integration, "async_track_state_change_event", lambda *_: lambda: None)
    entry = SimpleNamespace(entry_id="a", async_on_unload=lambda _: None,
                            async_create_background_task=lambda *_: None)
    return hass, store, gate, target, system, entry


def persist(hass, records):
    (hass.root / execution_ownership.STORAGE_KEY).write_text(json.dumps({
        "version": 1, "data": {"schema_version": 1, "records": records},
    }), encoding="utf-8")


def record(owner="legacy", station=MOREK_STATION_ID, connector=1):
    return {"station_id": station, "connector_id": connector, "owner": owner}


def adapter_for(hass, target, entry_id="a"):
    path = MagicMock(writes_current=False)
    path.async_start = AsyncMock(return_value=True)
    path.async_stop = AsyncMock(return_value=True)
    current = MagicMock()
    current.async_set = AsyncMock(return_value="assigned")
    phase = MagicMock()
    phase.async_set_phases = AsyncMock(return_value=PhaseSwitchResult(True))
    adapter = ChargerAdapter(hass, platform="ocpp", path=path, current=current,
                             policy=MagicMock(), phase_switch=lambda: phase)
    adapter.write_guard = command_admission.legacy_write_guard(hass, entry_id, lambda: target, ocpp=True)

    async def logged(_kind, run, **_kwargs):
        return await run()

    adapter._logged = logged
    return adapter, path, current, phase


async def paused_settings_for_recovery(hass, monkeypatch):
    """Actual settings store, with HA storage mocked on disk."""
    from homeassistant.helpers import storage
    from custom_components.spotnav.planning.auto_settings import AutoSettingsStore, PauseIntent, STORAGE_KEY

    monkeypatch.setattr(storage, "Store", FakeStore)
    settings = AutoSettingsStore(hass, store=FakeStore(hass, 1, STORAGE_KEY))
    settings._loaded = True
    await settings.async_update("a", mutate=lambda value: replace(value, pause=PauseIntent(choice="until_resumed")))
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["requested", "interrupted", "drained_unarmed"])
async def test_recovery_status_and_guarded_abort_after_restart(environment, monkeypatch, marker):
    from custom_components.spotnav.execution import morek_outcomes
    from homeassistant.helpers import storage

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    monkeypatch.setattr(storage, "Store", FakeStore)
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": marker}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    def identity():
        return morek_schedule._identity_status(hass, target)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert gate._recovery_status["a"]["state"] == "entry_" + marker
    assert gate._recovery_status["a"]["activation_allowed"] is False
    assert await gate.async_recover_unarmed("a", identity, settings_store=settings) == "aborted"
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] is None
    assert settings.settings("a").pause.choice == "until_resumed"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_setup_to_real_worker_profile_send(environment, monkeypatch):
    """No simulated CommandAdmission: setup migration then an explicitly triggered worker."""
    import sys
    from homeassistant.helpers import storage
    from custom_components.spotnav.execution import morek_outcomes, morek_worker

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(storage, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    monkeypatch.setattr(morek_schedule, "Store", FakeStore)
    persist(hass, {"a": record()})
    intent = {"version": 1, "type": "pause_until_resumed", "id": "pause-a",
              "station_id": MOREK_STATION_ID, "connector_id": 1}
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}, "schedule_pause": intent}}), encoding="utf-8")
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    entry.runtime_data = SimpleNamespace(executor=AutoExecutor(hass, charger, settings), morek_worker=None)
    release = await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    await release()
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    assert (await gate._store.async_status("a", identity()))["handover_evidence"] == "completed"
    assert "a" not in gate._lifecycle_barriers
    point = SimpleNamespace(call=AsyncMock(return_value=SimpleNamespace(status="Accepted")))
    point.call.assert_not_awaited()
    # Simulate a new process: the disk witness survives, the ticket does not.
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    hass.data["spotnav_command_admission"] = restarted
    hass.data["spotnav_execution_ownership_store"] = restarted._store
    hass.data.pop("spotnav_morek_outcomes", None)
    release = await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    await release()
    assert restarted.owned_ticket_current("a", command_admission.physical_connector(identity()))
    point.call.assert_not_awaited()
    monkeypatch.setattr(morek_worker, "controller_for", lambda *_: charger)
    monkeypatch.setattr(morek_worker, "domain_data", lambda *_: SimpleNamespace(auto_store=settings))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda *_: SimpleNamespace(auto_store=settings))
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda *_: point)
    monkeypatch.setattr(morek_schedule, "_schedule_verification", lambda *_: None)
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        SetChargingProfile=lambda **kw: SimpleNamespace(payload=kw))))
    hass.data[morek_schedule._DATA_KEY] = {"a": ({}, FakeStore(hass, 1, "entry"), asyncio.Lock())}
    worker = morek_worker.MorekScheduleWorker(hass, "a", None)
    await worker._reconcile(0)
    assert worker.reason == "upload_accepted_unverified"
    assert point.call.await_count == 1
    assert point.call.await_args.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 0
    # Restart again with the new settled dispatch evidence. This time the real
    # setup path recovers automatically and preserves the durable Pause.
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    hass.data["spotnav_command_admission"] = restarted
    hass.data["spotnav_execution_ownership_store"] = restarted._store
    hass.data.pop("spotnav_morek_outcomes", None)
    release = await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    await release()
    assert restarted.owned_ticket_current("a", command_admission.physical_connector(identity()))
    assert point.call.await_count == 1  # recovery is read-only
    worker = morek_worker.MorekScheduleWorker(hass, "a", None)
    await worker._reconcile(0)
    assert worker.reason == "unchanged" and point.call.await_count == 1
    assert (await morek_outcomes.outcomes_for(hass).read())["schedule_pause"] == intent
    # An actual durable person Stop invalidates the old generation and carries
    # forward only the authority associated with the newly recorded pause.
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: charger)
    before = restarted._completion_tickets["a"]
    await morek_schedule.async_record_owned_pause(hass, "a")
    after = restarted._completion_tickets["a"]
    assert after[3].revision == before[3].revision + 1
    assert restarted.owned_ticket_current("a", command_admission.physical_connector(identity()))
    # Stop while the next actual worker attempt is persisting: no stale wire call.
    ledger = morek_outcomes.outcomes_for(hass)
    saved = await ledger.read()
    saved["schedule_pause"] = {**intent, "id": "new-pause"}
    await ledger.write(saved)
    entry_store = hass.data[morek_schedule._DATA_KEY]["a"][1]
    original_save = entry_store.async_save
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed_save(data):
        reached.set()
        await proceed.wait()
        await original_save(data)
    monkeypatch.setattr(entry_store, "async_save", delayed_save)
    task = asyncio.create_task(worker._reconcile(0))
    await asyncio.wait_for(reached.wait(), 2)
    with restarted.person_stop_reservation("a", identity):
        proceed.set()
        with pytest.raises(morek_schedule.ScheduleRefused, match="stale_generation"):
            await task
    assert point.call.await_count == 1
    assert (await ledger.read())["attempt"]["state"] == "aborted_before_dispatch"
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner", "expected"), [("legacy", "legacy_unarmed"),
                                                  ("morek_schedule", "morek_owned_unarmed")])
async def test_recovery_status_keeps_valid_owners_unarmed(environment, monkeypatch, owner, expected):
    from custom_components.spotnav.execution import morek_outcomes
    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record(owner)})
    def identity():
        return morek_schedule._identity_status(hass, target)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    status = await gate.async_recovery_status("a", identity)
    assert status["state"] == expected and status["activation_provenance"] == "unverified"
    assert status["activation_allowed"] is False and status["profile_history"] == "missing_not_inventory"
    if owner == "morek_schedule":
        assert status["handover_completion"] == "not_proven_by_owner_record"
    assert await gate.async_recover_unarmed("a", identity) == expected
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "expected"), [("missing", "ownership_missing"),
    ("corrupt", "ownership_malformed"), ("unsupported", "ownership_unsupported_version"),
    ("uncertain", "profile_outcome_uncertain"), ("stale_attempt", "profile_outcome_uncertain"),
    ("duplicate", "ownership_conflict")])
async def test_recovery_status_refuses_untrusted_evidence(environment, monkeypatch, case, expected):
    from custom_components.spotnav.execution import morek_outcomes
    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    path = hass.root / execution_ownership.STORAGE_KEY
    if case == "corrupt":
        path.write_text("{broken", encoding="utf-8")
    elif case == "unsupported":
        path.write_text(json.dumps({"version": 2, "data": {}}), encoding="utf-8")
    elif case != "missing":
        persist(hass, {"a": record(), **({"b": record()} if case == "duplicate" else {})})
    if case in ("uncertain", "stale_attempt"):
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": case == "uncertain",
                                    "attempt": {"state": "sending"} if case == "stale_attempt" else None}}), encoding="utf-8")
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert (await gate.async_recovery_status("a", identity))["state"] == expected
    assert await gate.async_recover_unarmed("a", identity) == expected
    assert (await gate.async_recovery_status("a", identity))["activation_allowed"] is False
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_preserves_interrupted_migration_even_with_paused_settings(environment, monkeypatch):
    from custom_components.spotnav import runtime
    from custom_components.spotnav.execution import morek_outcomes
    from homeassistant.helpers import storage

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    monkeypatch.setattr(storage, "Store", FakeStore)
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "interrupted"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    monkeypatch.setattr(runtime, "domain_data", lambda _: SimpleNamespace(auto_store=settings))
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert gate._recovery_status["a"]["state"] == "entry_interrupted"
    status = await store.async_status("a", morek_schedule._identity_status(hass, target))
    assert status["recorded_owner"] == "legacy" and status["transition_state"] == "interrupted"
    assert settings.settings("a").pause.choice == "until_resumed"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_document_compatibility_never_establishes_activation_provenance(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes
    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert (await gate.async_recovery_status("a", identity))["state"] == "ownership_missing"
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    result = await gate.async_recovery_status("a", identity)
    assert result["state"] == "legacy_unarmed"
    assert result["activation_provenance"] == "unverified" and not result["activation_allowed"]
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    result = await restarted.async_recovery_status("a", identity)
    assert result["state"] == "legacy_unarmed" and not result["activation_allowed"]
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_startup_recovery_is_not_blindly_retried(environment, monkeypatch):
    from custom_components.spotnav import runtime
    from custom_components.spotnav.execution import morek_outcomes
    from homeassistant.helpers import storage

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    monkeypatch.setattr(storage, "Store", FakeStore)
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    monkeypatch.setattr(runtime, "domain_data", lambda _: SimpleNamespace(auto_store=settings))
    store._store.async_save = AsyncMock(side_effect=OSError("synthetic uncertain save"))
    controller = SimpleNamespace(ocpp_target=target, charge_control="switch.charger")
    await integration._async_setup_ownership_metadata(hass, entry, controller)
    assert gate._recovery_status["a"]["state"] == "entry_requested"
    assert await gate.async_recover_unarmed(
        "a", lambda: morek_schedule._identity_status(hass, target), settings_store=settings) == "save_uncertain"
    await integration._async_setup_ownership_metadata(hass, entry, controller)
    store._store.async_save.assert_awaited_once()
    assert gate._recovery_status["a"]["state"] == "ownership_save_failed"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["requested", "interrupted", "drained_unarmed", "exit_held_unarmed"])
async def test_reconnect_preserves_migration_interlocks(environment, monkeypatch, marker):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": marker}}})
    original = (hass.root / execution_ownership.STORAGE_KEY).read_bytes()
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    def create_task(_hass, coroutine, _name):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    await asyncio.gather(*tasks)
    assert (hass.root / execution_ownership.STORAGE_KEY).read_bytes() == original
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert (await store.async_status("a", identity()))["transition_state"] == marker
    write = AsyncMock()
    assert not (await gate.async_execute("a", "legacy_actuator", identity, write)).allowed
    assert not (await gate.async_manual_profile("a", identity, write)).allowed
    assert (await gate.async_execute("a", "owned_profile", identity, write)).reason == "schedule_mode_unarmed"
    write.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnect_callback_closes_writer_admission_before_task_runs(environment, monkeypatch):
    hass, _, gate, target, _, entry = environment
    persist(hass, {"a": record()})
    callbacks, pending = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    entry.async_create_background_task = lambda _h, coro, _name: pending.append(coro)
    real_identity = integration._identity_status
    offline = [True]
    monkeypatch.setattr(integration, "_identity_status", lambda h, t: (
        {"supported": False, "resolved_id": None, "connector_id": 1} if offline[0] else real_identity(h, t)))
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=None)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    offline[0] = False
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    identity = lambda: real_identity(hass, target)  # noqa: E731
    write = AsyncMock()
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "lifecycle_initializing"
    assert (await gate.async_manual_profile("a", identity, write)).reason == "lifecycle_initializing"
    write.assert_not_awaited()
    unrelated, unrelated_path, _, _ = adapter_for(hass, SimpleNamespace(devid="alias-a", connector_id=2))
    assert await unrelated.async_start(16)
    unrelated_path.async_start.assert_awaited_once()
    protected, protected_path, _, _ = adapter_for(hass, target)
    assert await protected.async_stop(protection=True)
    protected_path.async_stop.assert_awaited_once()
    stop = AsyncMock()
    with gate.person_stop_reservation("a", identity):
        assert (await gate.async_execute("a", "person_stop", identity, stop)).allowed
    stop.assert_awaited_once()
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                       "new_state": SimpleNamespace(state="unavailable")}))
    await pending.pop()
    assert (await gate._store.async_status("a", identity()))["transition_state"] is None
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "lifecycle_initializing"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnect_drains_already_admitted_writer(environment, monkeypatch):
    hass, store, gate, target, _, entry = environment
    persist(hass, {"a": record()})
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    def create_task(_h, coro, _name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    real_identity = integration._identity_status
    offline = [True]
    monkeypatch.setattr(integration, "_identity_status", lambda h, t: (
        {"supported": False, "resolved_id": None, "connector_id": 1} if offline[0] else real_identity(h, t)))
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=None)
    offline[0] = False
    identity = lambda: real_identity(hass, target)  # noqa: E731
    entered, release, marker = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def write():
        entered.set()
        await release.wait()
    writer = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, write))
    await entered.wait()
    offline[0] = True
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    offline[0] = False
    original = gate.async_ensure_initialized
    async def track(*args):
        marker.set()
        return await original(*args)
    monkeypatch.setattr(gate, "async_ensure_initialized", track)
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    await marker.wait()
    assert not tasks[0].done()
    release.set()
    assert (await writer).allowed
    await asyncio.gather(*tasks)
    assert (await store.async_status("a", identity()))["transition_state"] == "drained_unarmed"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["none", "identity_returns", "stop", "cancel", "save_failure", "duplicate",
                                  "requested_failure", "drained_failure", "requested_cancel", "drained_cancel"])
async def test_reconnect_migrates_and_releases_after_real_handover(environment, monkeypatch, race):
    from homeassistant.helpers import storage
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(storage, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record()})
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    entry.runtime_data = SimpleNamespace(executor=AutoExecutor(hass, charger, settings), morek_worker=None)
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    def create_task(_h, coro, _name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    real_identity = integration._identity_status
    offline = [True]
    monkeypatch.setattr(integration, "_identity_status", lambda h, t: (
        {"supported": False, "resolved_id": None, "connector_id": 1} if offline[0] else real_identity(h, t)))
    await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    offline[0] = False
    reached, proceed = asyncio.Event(), asyncio.Event()
    original_save = store._store.async_save
    async def delayed_save(data):
        record_now = data["records"]["a"]
        transition = record_now.get("transition", {}).get("state")
        waiting = (record_now["owner"] == "morek_schedule" and not race.startswith(("requested_", "drained_"))) or (
            race.startswith("requested_") and transition == "requested") or (
            race.startswith("drained_") and transition == "drained_unarmed")
        if waiting:
            reached.set()
            await proceed.wait()
            if race in ("save_failure", "requested_failure", "drained_failure"):
                raise OSError("synthetic failure")
        await original_save(data)
    if race != "none":
        monkeypatch.setattr(store._store, "async_save", delayed_save)
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    identity = lambda: real_identity(hass, target)  # noqa: E731
    if race != "none":
        await asyncio.wait_for(reached.wait(), 2)
        if race == "identity_returns":
            target.connector_id = 2
            callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                               "new_state": SimpleNamespace(state="unavailable")}))
            target.connector_id = 1
        if race == "duplicate":
            callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                               "new_state": SimpleNamespace(state="unavailable")}))
            callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                               "new_state": SimpleNamespace(state="off")}))
        if race in ("cancel", "requested_cancel", "drained_cancel"):
            tasks[0].cancel()
        if race == "stop":
            with gate.person_stop_reservation("a", identity):
                proceed.set()
                await asyncio.gather(*tasks)
        else:
            proceed.set()
            await asyncio.gather(*tasks, return_exceptions=race in ("cancel", "requested_cancel", "drained_cancel"))
    else:
        await asyncio.gather(*tasks)
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert not status["armed"]
    if race == "none":
        assert status["recorded_owner"] == "morek_schedule"
        assert status["handover_evidence"] == "completed"
        assert "a" not in gate._lifecycle_barriers
    else:
        assert status["recorded_owner"] == "legacy"
        assert status["transition_state"] in (None, "requested", "drained_unarmed", "interrupted")
        assert "a" in gate._lifecycle_barriers
    op = AsyncMock()
    if race != "none":
        assert not (await gate.async_execute("a", "owned_profile", identity, op)).allowed
    assert not (await gate.async_execute("a", "legacy_actuator", identity, op)).allowed
    assert not (await gate.async_manual_profile("a", identity, op)).allowed
    op.assert_not_awaited()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["current", "supersede", "uncertain", "identity", "stop", "cancel"])
async def test_reconnect_releases_only_current_verified_owned_barrier(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record("morek_schedule")})
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    def create_task(_h, coro, _name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=None)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = gate.async_release_lifecycle_barrier
    async def delayed(*args):
        reached.set()
        await proceed.wait()
        return await original(*args)
    monkeypatch.setattr(gate, "async_release_lifecycle_barrier", delayed)
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    await reached.wait()
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    if case == "supersede":
        callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                           "new_state": SimpleNamespace(state="unavailable")}))
    if case == "uncertain":
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True}}), encoding="utf-8")
    if case == "identity":
        hass.data["ocpp"]["duplicate"] = hass.data["ocpp"]["one"]
    if case == "cancel":
        tasks[0].cancel()
    if case == "stop":
        with gate.person_stop_reservation("a", identity):
            proceed.set()
            await asyncio.gather(*tasks)
    else:
        proceed.set()
        await asyncio.gather(*tasks, return_exceptions=case == "cancel")
    # A legacy owner record without completion is never enough to release.
    assert "a" in gate._lifecycle_barriers
    op = AsyncMock()
    owned = await gate.async_execute("a", "owned_profile", identity, op)
    assert owned.reason == ("identity_unresolved" if case == "identity" else "lifecycle_initializing")
    assert not (await gate.async_execute("a", "legacy_actuator", identity, op)).allowed
    assert not (await gate.async_manual_profile("a", identity, op)).allowed
    op.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "malformed", "held", "interrupted", "uncertain"])
async def test_reconnect_never_releases_untrusted_state(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    if case == "malformed":
        (hass.root / execution_ownership.STORAGE_KEY).write_text("{broken", encoding="utf-8")
    elif case in ("held", "interrupted"):
        marker = "exit_held_unarmed" if case == "held" else "interrupted"
        persist(hass, {"a": {**record(), "transition": {"version": 1, "state": marker}}})
    elif case == "uncertain":
        persist(hass, {"a": record("morek_schedule")})
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True}}), encoding="utf-8")
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    def create_task(_h, coro, _name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=None)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    await asyncio.gather(*tasks)
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    op = AsyncMock()
    assert (await gate.async_execute("a", "legacy_actuator", identity, op)).reason == "lifecycle_initializing"
    assert (await gate.async_manual_profile("a", identity, op)).reason == "lifecycle_initializing"
    op.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconnect_rechecks_new_uncertain_profile_evidence(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record("morek_schedule")})
    callbacks = []
    monkeypatch.setattr(integration, "async_track_state_change_event", lambda _h, _ids, cb: callbacks.append(cb) or (lambda: None))
    tasks = []
    def create_task(_hass, coroutine, _name):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task
    entry.async_create_background_task = create_task
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert gate._recovery_status["a"]["state"] == "morek_owned_unarmed"
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True}}), encoding="utf-8")
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                       "new_state": SimpleNamespace(state="off")}))
    await asyncio.gather(*tasks)
    assert gate._recovery_status["a"]["state"] == "profile_outcome_uncertain"
    hass.station.call.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stop", "identity"])
async def test_recovery_rechecks_stop_and_identity_after_delayed_outcome(environment, monkeypatch, change):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, system, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "interrupted"}}})
    entered, release = asyncio.Event(), asyncio.Event()
    async def read():
        entered.set()
        await release.wait()
        return None
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=read))
    def identity():
        return morek_schedule._identity_status(hass, target)
    task = asyncio.create_task(gate.async_recovery_status("a", identity))
    await entered.wait()
    if change == "stop":
        with gate.person_stop_reservation("a", identity):
            release.set()
            assert (await task)["state"] == "person_stop_or_generation_changed"
    else:
        hass.data["ocpp"]["two"] = system
        release.set()
        assert (await task)["state"] == "identity_changed"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_rejects_stale_generation_while_waiting(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record()})
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    lock = gate._lock_for(connector)
    await lock.acquire()
    task = asyncio.create_task(gate.async_recovery_status("a", identity))
    await asyncio.sleep(0)
    gate._generations[connector] = gate.generation(connector).revision + 1
    lock.release()
    assert (await task)["state"] == "stale_generation"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "allowed"), [
    ("first", True), ("legacy", True), ("morek", False), ("corrupt", False),
    ("missing_binding", False), ("duplicate", False),
])
async def test_startup_metadata_then_restore_and_direct_writers(environment, monkeypatch, state, allowed):
    hass, store, _, target, _, entry = environment
    if state == "legacy":
        persist(hass, {"a": record()})
    elif state == "morek":
        persist(hass, {"a": record("morek_schedule")})
    elif state == "corrupt":
        (hass.root / execution_ownership.STORAGE_KEY).write_text("{broken", encoding="utf-8")
    elif state == "missing_binding":
        persist(hass, {})
    elif state == "duplicate":
        persist(hass, {"a": record(), "b": record()})

    adapter, path, current, phase = adapter_for(hass, target)
    controller = SimpleNamespace(ocpp_target=target, charge_control="switch.charger", adapter=adapter)
    # The same helper is awaited in actual setup before executor start and restore.
    await integration._async_setup_ownership_metadata(hass, entry, controller)
    assert (await adapter.async_start(16)) is allowed
    assert (await adapter.async_stop()) is allowed
    assert (await adapter.async_set_current(12, reason="restore") == "assigned") is allowed
    assert (await adapter.async_set_phases(3)).sent is allowed
    assert path.async_start.await_count == int(allowed)
    assert path.async_stop.await_count == int(allowed)
    assert current.async_set.await_count == int(allowed)
    assert phase.async_set_phases.await_count == int(allowed)
    status = await store.async_status("a", morek_schedule._identity_status(hass, target))
    assert not status["ready"] and not status["armed"] and not status["schedule_mode_available"]
    assert "site_regulation_conflict_unresolved" in status["blockers"]
    # Safety-classified writes remain available, not silently disabled.
    assert await adapter.async_stop(protection=True)
    assert await adapter.async_set_current(6, reason="regulator") == "assigned"


def test_real_setup_installs_guard_and_awaits_metadata_before_executor_and_restore():
    source = ast.parse(Path(integration.__file__).read_text(encoding="utf-8"))
    setup = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_setup_charger_entry")
    text = ast.unparse(setup)
    assert text.index("controller.adapter.write_guard = legacy_write_guard") < text.index("await _async_setup_ownership_metadata")
    assert text.index("await _async_setup_ownership_metadata") < text.index("await executor.async_start()")
    assert text.index("await _async_setup_ownership_metadata") < text.index("await async_restore_execution")


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner", "writes"), [("legacy", 0), ("morek_schedule", 0), ("corrupt", 0)])
async def test_actual_entry_setup_orders_ownership_before_start_and_restore(environment, monkeypatch, owner, writes):
    hass, _, _, target, _, entry = environment
    if owner == "corrupt":
        (hass.root / execution_ownership.STORAGE_KEY).write_text("broken", encoding="utf-8")
    else:
        persist(hass, {"a": record(owner)})
    adapter, path, _, _ = adapter_for(hass, target)
    controller = MagicMock(ocpp_target=target, ocpp_target_source="stored", charge_control="switch.charger",
                           adapter=adapter, plan=None)
    async def dispatch():
        return await adapter.async_start(16)
    controller.async_initialize = AsyncMock(side_effect=dispatch)
    controller.async_shutdown = AsyncMock()
    executor = MagicMock()
    executor.async_start = AsyncMock(side_effect=dispatch)
    executor.async_after_restore = AsyncMock()
    executor.async_shutdown = AsyncMock()
    solar = MagicMock()
    reader = MagicMock(async_load=AsyncMock(), async_shutdown=AsyncMock())
    push = MagicMock(async_load=AsyncMock())
    entry.data = {"charge_control": "switch.charger"}
    monkeypatch.setattr(integration, "_drop_core_ownership_choice", lambda *_: None)
    monkeypatch.setattr(integration, "async_store_detected_register", lambda *_: None)
    monkeypatch.setattr(integration, "charger_power_counted", lambda *_: None)
    monkeypatch.setattr(integration, "SocReader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(integration, "ChargingController", lambda *_args, **_kwargs: controller)
    monkeypatch.setattr(integration, "_async_start_debug_day", AsyncMock())
    monkeypatch.setattr(integration, "domain_data", lambda _: SimpleNamespace(auto_store=MagicMock(), price_refresh=None))
    monkeypatch.setattr(integration, "async_migrate_settings_phases", AsyncMock())
    monkeypatch.setattr(integration, "AutoExecutor", lambda *_args, **_kwargs: executor)
    monkeypatch.setattr(integration, "async_setup_solar_execution", lambda *_: solar)
    monkeypatch.setattr(integration, "ChargerPush", lambda *_: push)
    monkeypatch.setattr(integration, "async_register_charger_webhook", lambda *_: None)

    class StopAfterRestore(Exception):
        pass

    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(side_effect=StopAfterRestore))
    with pytest.raises(StopAfterRestore):
        await integration._async_setup_charger_entry(hass, entry)
    assert executor.async_start.await_count == 1
    assert controller.async_initialize.await_count == 1
    assert executor.async_after_restore.await_count == 1
    assert path.async_start.await_count == writes


@pytest.mark.asyncio
async def test_actual_setup_migrates_before_real_executor_start(environment, monkeypatch):
    from homeassistant.helpers import storage
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(storage, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record()})
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    reader = MagicMock(async_load=AsyncMock(), async_shutdown=AsyncMock())
    entry.data = {"charge_control": "switch.charger"}
    monkeypatch.setattr(integration, "_drop_core_ownership_choice", lambda *_: None)
    monkeypatch.setattr(integration, "async_store_detected_register", lambda *_: None)
    monkeypatch.setattr(integration, "charger_power_counted", lambda *_: None)
    monkeypatch.setattr(integration, "SocReader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(integration, "ChargingController", lambda *_args, **_kwargs: charger)
    monkeypatch.setattr(integration, "_async_start_debug_day", AsyncMock())
    monkeypatch.setattr(integration, "domain_data", lambda _: SimpleNamespace(auto_store=settings, price_refresh=None))
    monkeypatch.setattr(integration, "async_migrate_settings_phases", AsyncMock())

    class BeforeProducer(Exception):
        pass

    async def before_start(executor):
        assert isinstance(executor, AutoExecutor)
        identity = morek_schedule._identity_status(hass, target)
        status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity)
        assert status["recorded_owner"] == "morek_schedule" and not status["armed"]
        operation = AsyncMock()
        assert not (await gate.async_execute("a", "legacy_actuator", lambda: identity, operation)).allowed
        assert not (await gate.async_manual_profile("a", lambda: identity, operation)).allowed
        assert (await gate.async_execute("a", "owned_profile", lambda: identity, operation)).allowed
        operation.assert_awaited_once()
        raise BeforeProducer

    monkeypatch.setattr(AutoExecutor, "async_start", before_start)
    with pytest.raises(BeforeProducer):
        await integration._async_setup_charger_entry(hass, entry)
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_alias_duplicate_queue_and_offline_unrelated(environment):
    hass, store, gate, target, system, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    alias = SimpleNamespace(devid="alias-b", connector_id=1)
    duplicate = SimpleNamespace(entry_id="b", async_on_unload=lambda _: None,
                                async_create_background_task=lambda *_: None)
    adapter, path, _, _ = adapter_for(hass, target)
    connector = command_admission.physical_connector(morek_schedule._identity_status(hass, target))
    async with gate._lock_for(connector):
        pending = asyncio.create_task(adapter.async_start())
        await asyncio.sleep(0)
        # Register the contender as setup does, without waiting on our held lock.
        contender = asyncio.create_task(integration._async_setup_ownership_metadata(
            hass, duplicate, SimpleNamespace(ocpp_target=alias, charge_control="switch.other")))
        await asyncio.sleep(0)
    # The first queued writer may precede discovery of a new duplicate. Once the
    # contender has initialized, all subsequent work is blocked.
    await pending
    await contender
    assert (await store.async_status("a", morek_schedule._identity_status(hass, target)))["record_state"] == "conflict"
    before = path.async_start.await_count
    assert not await adapter.async_start()
    assert path.async_start.await_count == before
    system.charge_points.clear()
    assert not await adapter.async_start()  # alias/old binding is not offline identity proof
    other, other_path, _, _ = adapter_for(hass, SimpleNamespace(devid="unknown", connector_id=2))
    assert await other.async_start()
    other_path.async_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_unrelated_entry_does_not_create_document_or_prevent_first_target_migration(environment):
    hass, store, gate, target, _, entry = environment
    other = SimpleNamespace(devid="other", connector_id=2)
    assert await gate.async_ensure_initialized("other", lambda: morek_schedule._identity_status(hass, other)) == "identity_non_target"
    assert not (hass.root / execution_ownership.STORAGE_KEY).exists()
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert (await store.async_status("a", morek_schedule._identity_status(hass, target)))["recorded_owner"] == "legacy"


@pytest.mark.asyncio
async def test_stale_binding_cannot_be_replaced_by_new_alias(environment):
    hass, store, gate, target, _, _ = environment
    persist(hass, {"old-entry": record("morek_schedule")})
    assert await gate.async_ensure_initialized("new-entry", lambda: morek_schedule._identity_status(hass, target)) == "ownership_conflict"
    assert (await store.async_status("new-entry", morek_schedule._identity_status(hass, target)))["record_state"] == "conflict"
    assert json.loads((hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8"))["data"]["records"] == {
        "old-entry": record("morek_schedule")}


@pytest.mark.asyncio
async def test_queued_write_rechecks_duplicate_discovered_first(environment):
    hass, _, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    alias = SimpleNamespace(devid="alias-b", connector_id=1)
    adapter, path, _, _ = adapter_for(hass, target)
    connector = command_admission.physical_connector(morek_schedule._identity_status(hass, target))
    async with gate._lock_for(connector):
        contender = asyncio.create_task(gate.async_ensure_initialized(
            "b", lambda: morek_schedule._identity_status(hass, alias)))
        await asyncio.sleep(0)
        queued = asyncio.create_task(adapter.async_start())
        await asyncio.sleep(0)
    assert await contender == "ownership_conflict"
    assert not await queued
    path.async_start.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner", "expected"), [
    ("legacy", 1), ("morek_schedule", 0), ("missing_binding", 0), ("corrupt", 0), ("first", 1),
])
async def test_real_controller_restore_rearm_uses_persisted_ownership(environment, monkeypatch, owner, expected):
    hass, _, _, target, _, entry = environment
    if owner == "missing_binding":
        persist(hass, {})
    elif owner == "corrupt":
        (hass.root / execution_ownership.STORAGE_KEY).write_text("broken", encoding="utf-8")
    elif owner != "first":
        persist(hass, {"a": record(owner)})
    adapter, path, _, _ = adapter_for(hass, target)
    now = datetime.now(timezone.utc)
    plan = ChargingPlan(start=(now - timedelta(minutes=5)).isoformat(),
                        end=(now + timedelta(minutes=30)).isoformat(), amps=16,
                        auto_identity="a" * 32, auto_settings_revision=1, auto_price_identity="price")
    saved = {"plan": asdict(plan), "person_stopped": True}
    controller_store = MagicMock(async_load=AsyncMock(return_value=saved))
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: controller_store)
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    await integration._async_setup_ownership_metadata(hass, entry, charger)
    charger._integration_version = AsyncMock(return_value="test")
    charger._runner.coverage.async_load = AsyncMock()
    charger._async_save_quietly = AsyncMock()
    charger._async_arm_progress_listener = MagicMock()
    charger._async_arm_target_listener = MagicMock()
    charger._async_disarm_target_listener = MagicMock()
    async def start_window(**_kwargs):
        await adapter.async_start(16)
        return False
    charger._start_window_locked = AsyncMock(side_effect=start_window)
    timers = []
    def track(_hass, callback, when):
        timers.append((callback, when))
        return lambda: None
    monkeypatch.setattr(controller_module, "async_track_point_in_utc_time", track)
    # Actual integration restore and controller restore run against a stored active plan.
    await integration.async_restore_execution(charger, None, None)
    assert charger.restored and charger.plan is not None
    assert charger._legacy_person_stopped  # restore must not erase a person's Stop
    assert charger._start_window_locked.await_count == expected
    assert path.async_start.await_count == expected
    assert len(timers) == 1  # the future end remains guarded by its normal callback


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner", "person_stop", "starts"), [
    ("legacy", False, 1), ("legacy", True, 0), ("morek_schedule", False, 0),
    ("morek_schedule", True, 0),
])
async def test_handback_uses_same_persisted_owner_and_preserves_person_stop(
    environment, monkeypatch, owner, person_stop, starts
):
    hass, _, _, target, _, entry = environment
    persist(hass, {"a": record(owner)})
    adapter, path, current, _ = adapter_for(hass, target)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    adapter.enabled_state = lambda: False
    adapter.restore_memory = MagicMock()
    adapter.cancel_pending_reads = MagicMock()
    saved = {"spotnav_stopped": True, "person_stopped": person_stop}
    monkeypatch.setattr(charger_handback, "_async_saved_record", AsyncMock(return_value=saved))
    monkeypatch.setattr(charger_handback, "duplicates_of", lambda *_: [])
    monkeypatch.setattr(charger_handback, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    entry.data = {"charge_control": "switch.charger"}
    done = await charger_handback.async_hand_back_charger(hass, entry)
    assert path.async_start.await_count == starts
    assert ("started" in done) == bool(starts)
    current.async_set.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("save_fails", [False, True])
async def test_restart_carries_person_stop_to_real_auto_boundary_under_morek_owner(environment, monkeypatch, save_fails):
    hass, _, gate, target, _, entry = environment
    persist(hass, {"a": record("morek_schedule")})
    adapter, path, _, _ = adapter_for(hass, target)
    saved = {"person_stopped": True}
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock(
        async_load=AsyncMock(return_value=saved)))
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    await integration._async_setup_ownership_metadata(hass, entry, charger)
    charger._integration_version = AsyncMock(return_value="test")
    charger._runner.coverage.async_load = AsyncMock()
    charger._async_save_quietly = AsyncMock()
    charger.async_save_record = AsyncMock()
    charger._async_arm_progress_listener = MagicMock()
    charger.note_person_hold = MagicMock()
    settings = [AutoSettings()]
    settings_store = MagicMock()
    settings_store.settings.side_effect = lambda _: settings[0]

    async def update(_entry, *, mutate):
        if save_fails:
            raise OSError("synthetic save failure")
        settings[0] = mutate(settings[0])

    settings_store.async_update = AsyncMock(side_effect=update)
    executor = AutoExecutor(hass, charger, settings_store, legacy_admission=lambda: command_admission.async_auto_legacy_allowed(
        gate, "a", lambda: morek_schedule._identity_status(hass, target)))
    await executor.async_start()
    await integration.async_restore_execution(charger, executor, None)
    if save_fails:
        assert charger._legacy_person_stopped
        assert charger._store_record()["person_stopped"] is True
        charger.async_save_record.assert_not_awaited()
    else:
        assert executor.pause_intent.manual and executor.pause_intent.action == "stop"
    assert not await executor.async_start_on_plug_in()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_quiesce_blocks_person_stop_but_not_regulator_protection(environment, monkeypatch):
    """Characterize the entry blocker; quiescing must not be wired as an activation path."""
    hass, _, gate, target, _, entry = environment
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    await integration._async_setup_ownership_metadata(hass, entry, charger)
    connector = command_admission.physical_connector(morek_schedule._identity_status(hass, target))
    await gate.async_quiesce_for_reload(connector)

    with pytest.raises(controller_module.ChargingExecutionError, match="ownership"):
        await charger._stop_locked(by_person=True, urgent=True)
    path.async_stop.assert_not_awaited()
    # The existing explicitly classified regulator path remains distinct.
    assert await adapter.async_stop(protection=True)
    path.async_stop.assert_awaited_once()
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_quiesce_refuses_auto_stop_before_intent_is_recorded(environment):
    """The old unwired latch also blocks Stop at Auto, before the controller guard."""
    hass, _, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    controller = MagicMock(entry_id="a")
    controller.async_stop = AsyncMock()
    settings_store = MagicMock()
    settings_store.settings.return_value = AutoSettings()
    settings_store.async_update = AsyncMock()
    executor = AutoExecutor(hass, controller, settings_store, legacy_admission=lambda: command_admission.async_auto_legacy_allowed(
        gate, "a", identity))
    await gate.async_quiesce_for_reload(connector)

    with pytest.raises(AutoControlRefused) as refusal:
        await executor.async_manual_action("stop")
    assert refusal.value.code == "legacy_execution_ownership_blocked"
    settings_store.async_update.assert_not_awaited()
    controller.async_stop.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "stop", "save"])
async def test_coordinated_entry_interrupted_by_auto_stop_while_writer_in_flight(environment, failure):
    hass, _, gate, target, _, entry = environment
    adapter, path, _, _ = adapter_for(hass, target)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    entered, release = asyncio.Event(), asyncio.Event()
    async def in_flight():
        entered.set()
        await release.wait()
    active = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, in_flight))
    await entered.wait()
    queued = asyncio.create_task(adapter.async_start(16))
    await asyncio.sleep(0)
    drain = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await asyncio.sleep(0)
    assert not drain.done()

    controller = MagicMock(entry_id="a", adapter=adapter, known_connected=True)
    adapter.vehicle_connected = lambda: True
    path.async_stop.return_value = failure != "stop"
    async def stop(**_kwargs):
        assert await adapter.async_stop(person_stop=True)
    controller.async_stop = AsyncMock(side_effect=stop)
    settings = [AutoSettings()]
    settings_store = MagicMock()
    settings_store.settings.side_effect = lambda _: settings[0]
    async def update(_entry, *, mutate):
        if failure == "save":
            raise OSError("synthetic save failure")
        settings[0] = mutate(settings[0])
    settings_store.async_update = AsyncMock(side_effect=update)
    async def hold(_entry, *, mutate):
        settings[0] = mutate(settings[0])
    settings_store.async_hold_unsaved = AsyncMock(side_effect=hold)
    executor = AutoExecutor(
        hass, controller, settings_store,
        legacy_admission=lambda: command_admission.async_auto_legacy_allowed(gate, "a", identity),
        person_stop_scope=adapter.person_stop_scope,
        person_stop_admission=lambda: adapter.async_legacy_permitted(person_stop=True),
    )
    executor._runner = MagicMock()
    executor._runner.begin.return_value = SimpleNamespace(early=True)
    executor._notify_change = AsyncMock()
    executor._sync_manual_watch = MagicMock()
    executor._note_manual_stop_sent = MagicMock()
    executor._arm_save_retry = MagicMock()
    executor._core_stop_scope = lambda _connected, scope, **_kw: scope
    stop_task = asyncio.create_task(executor.async_manual_stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    assert gate._entry_draining[connector] == "interrupted"
    release.set()
    assert (await active).allowed  # Already dispatched, not recalled.
    assert not await queued
    assert await drain == "interrupted"
    if failure == "none":
        await asyncio.wait_for(stop_task, 2)
    elif failure == "stop":
        with pytest.raises(AssertionError):
            await asyncio.wait_for(stop_task, 2)
        assert executor._last_error == "pause_stop_failed"
    else:
        with pytest.raises(AutoControlCommitted):
            await asyncio.wait_for(stop_task, 2)
        settings_store.async_hold_unsaved.assert_awaited_once()
    assert settings[0].pause.manual and settings[0].pause.action == "stop"
    controller.async_stop.assert_awaited_once()
    path.async_stop.assert_awaited_once()
    path.async_start.assert_not_awaited()
    assert not await adapter.async_start(16)
    assert (await gate.async_execute("a", "owned_profile", identity, AsyncMock())).reason == "connector_quiescing"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_entry_reservation_identity_failures_and_cancellation(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    with gate.person_stop_reservation("a", identity):
        assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "person_stop_active"
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: True) == "person_stop_active"
    assert await gate.async_begin_unarmed_entry("a", lambda: {}, lambda: False) == "identity_unresolved"
    await gate._lock_for(connector).acquire()
    task = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate._lock_for(connector).release()
    adapter, path, _, _ = adapter_for(hass, target)
    assert not await adapter.async_start()
    assert await adapter.async_stop(protection=True)
    path.async_start.assert_not_awaited()
    write = AsyncMock()
    assert (await gate.async_execute("a", "owned_profile", identity, write)).allowed is False
    write.assert_not_awaited()
    assert (await store.async_status("a", identity()))["recorded_owner"] == "legacy"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinated_stop_reaches_real_controller_and_keeps_other_connector_working(environment, monkeypatch):
    hass, _, gate, target, _, entry = environment
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    await integration._async_setup_ownership_metadata(hass, entry, charger)
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "drained_unarmed"
    path.async_stop.assert_not_awaited()
    adapter.enabled_state = lambda: True
    charger._async_save = AsyncMock()
    charger._notify = MagicMock()
    with adapter.person_stop_scope():
        await charger._stop_locked(by_person=True, urgent=True)
    path.async_stop.assert_awaited_once()
    assert gate._entry_draining[command_admission.physical_connector(identity())] == "interrupted"
    other, other_path, _, _ = adapter_for(hass, SimpleNamespace(devid="unknown", connector_id=2))
    assert await other.async_start()
    other_path.async_start.assert_awaited_once()
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["duplicate", "store_failure"])
async def test_unarmed_entry_refuses_ambiguous_ownership(environment, case):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    if case == "duplicate":
        assert await gate.async_ensure_initialized("b", identity) == "ownership_conflict"
    else:
        store.async_status = AsyncMock(side_effect=OSError("synthetic failure"))
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "ownership_unavailable"
    adapter, path, _, _ = adapter_for(hass, target)
    assert not await adapter.async_start()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_reserved_stop_keeps_entry_interrupted_and_ordinary_writes_closed(environment):
    hass, _, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    await gate._lock_for(connector).acquire()
    drain = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await asyncio.sleep(0)
    adapter, path, _, _ = adapter_for(hass, target)
    async def stop():
        with adapter.person_stop_scope():
            await adapter.async_stop(person_stop=True)
    task = asyncio.create_task(stop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate._lock_for(connector).release()
    assert await drain == "interrupted"
    assert not await adapter.async_start()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action,args", [
    ("send", {"preview_id": "preview"}),
    ("clear", {"confirm_profile_id": 42001}),
])
async def test_restarted_morek_owner_refuses_manual_profile_actions(environment, monkeypatch, action, args):
    hass, _, _, target, _, entry = environment
    persist(hass, {"a": record("morek_schedule")})
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=target))
    operation = AsyncMock()
    monkeypatch.setattr(morek_schedule, "_async_schedule_action_locked", operation)
    with pytest.raises(morek_schedule.ScheduleRefused, match="legacy_not_owner"):
        await morek_schedule.async_schedule_action(hass, "a", action, **args)
    operation.assert_not_awaited()
    hass.station.call.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["requested", "interrupted", "drained_unarmed"])
async def test_durable_transition_blocks_startup_and_manual_profile_actions(environment, monkeypatch, transition):
    hass, _, _, target, _, entry = environment
    saved = {**record(), "transition": {"version": 1, "state": transition}}
    persist(hass, {"a": saved})
    adapter, path, _, _ = adapter_for(hass, target)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert not await adapter.async_start()
    assert not await adapter.async_stop()
    monkeypatch.setattr(morek_schedule, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(morek_schedule, "controller_for", lambda *_: SimpleNamespace(ocpp_target=target))
    operation = AsyncMock()
    monkeypatch.setattr(morek_schedule, "_async_schedule_action_locked", operation)
    for action, args in (("send", {"preview_id": "preview"}), ("clear", {"confirm_profile_id": 42001})):
        with pytest.raises(morek_schedule.ScheduleRefused, match="ownership_unavailable"):
            await morek_schedule.async_schedule_action(hass, "a", action, **args)
    operation.assert_not_awaited()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    with adapter.person_stop_scope():
        assert await adapter.async_stop(person_stop=True)
    path.async_stop.assert_awaited_once()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_entry_persists_before_drain_and_stop_race_is_durable(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    lock = gate._lock_for(connector)
    await lock.acquire()
    task = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await asyncio.sleep(0)
    status = await store.async_status("a", identity())
    assert status["transition_state"] == "requested"
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    assert (await restarted.async_status("a", identity()))["transition_state"] == "requested"
    with gate.person_stop_reservation("a", identity):
        lock.release()
        assert await task == "interrupted"
    assert (await store.async_status("a", identity()))["transition_state"] == "interrupted"
    assert (await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity()))["transition_state"] == "interrupted"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_unarmed_drain_persists_without_active_owner(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "drained_unarmed"
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] == "drained_unarmed"
    assert not status["armed"] and not status["ready"]
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


async def handover_fixture(environment, monkeypatch):
    from homeassistant.helpers import storage
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(storage, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    executor = AutoExecutor(hass, charger, settings,
                            legacy_admission=lambda: command_admission.async_auto_legacy_allowed(gate, "a", identity),
                            person_stop_scope=adapter.person_stop_scope,
                            person_stop_admission=lambda: adapter.async_legacy_permitted(person_stop=True))
    def identity():
        return morek_schedule._identity_status(hass, target)
    await integration._async_setup_ownership_metadata(hass, entry, charger)
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "drained_unarmed"
    return store, gate, identity, executor, adapter, path


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["fail_before", "fail_after", "cancel_before", "cancel_after", "stop_before", "stop_after"])
async def test_completion_save_races_never_issue_ticket(environment, monkeypatch, race):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, _, _ = await handover_fixture(environment, monkeypatch)
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = store._store.async_save

    async def interrupted_save(data):
        completed = data["records"]["a"].get("handover", {}).get("state") == "completed"
        if not completed:
            return await original(data)
        if race.endswith("after"):
            await original(data)
        reached.set()
        await proceed.wait()
        if race.startswith("fail"):
            raise OSError("completion write failed")
        if race.endswith("before"):
            await original(data)

    monkeypatch.setattr(store._store, "async_save", interrupted_save)
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor, require_outcome=True))
    await asyncio.wait_for(reached.wait(), 2)
    if race.startswith("cancel"):
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif race.startswith("stop"):
        with gate.person_stop_reservation("a", identity):
            proceed.set()
            assert await task == "completion_interrupted"
    else:
        proceed.set()
        assert await task == "save_uncertain"
    assert "a" not in gate._completion_tickets
    operation = AsyncMock()
    assert not (await gate.async_execute("a", "owned_profile", identity, operation)).allowed
    operation.assert_not_awaited()
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["handover_evidence"] == ("completed" if race.endswith("after") or race == "stop_before"
                                            else "owner_written_unconfirmed")


@pytest.mark.asyncio
async def test_completed_restart_requires_explicit_reconfirmation(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, _, target, _, _ = environment
    store, gate, identity, executor, _, _ = await handover_fixture(environment, monkeypatch)
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    assert await gate.async_handover_unarmed("a", identity, executor, require_outcome=True) == "handed_over_unarmed"
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    revision = restarted.reserve_lifecycle_barrier("a", identity)
    assert not await restarted.async_release_lifecycle_barrier("a", identity, revision, lambda: True)
    # Model a 2.5.64 completion: no non-profile proof or worker evidence.
    ledger = morek_outcomes.outcomes_for(hass)
    old = await ledger.read()
    old.pop("migration_recovery_proof", None)
    await ledger.write(old)
    assert await restarted.async_reconfirm_completed("a", identity, persist_recovery_proof=True) == "reconfirmed"
    fresh = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    fresh_revision = fresh.reserve_lifecycle_barrier("a", identity)
    assert await fresh.async_recover_after_restart("a", identity, fresh_revision, 0) == "automatic_recovery_ready"
    hass.station.call.assert_not_awaited()
    op = AsyncMock()
    assert (await restarted.async_execute("a", "owned_profile", identity, op)).allowed
    op.assert_awaited_once()
    restarted.reserve_lifecycle_barrier("a", identity)
    assert not (await restarted.async_execute("a", "owned_profile", identity, op)).allowed
    await ledger.write({"schema": 1, "entry_id": "a", "uncertain": True, "attempt": {"state": "uncertain"}})
    assert await restarted.async_reconfirm_completed("a", identity) == "profile_outcome_unavailable"
    assert target.connector_id == 1 and store._records["a"]["handover"]["state"] == "completed"


@pytest.mark.asyncio
async def test_clean_handover_and_possibly_landed_completion_are_restart_indistinguishable(environment, monkeypatch):
    """A disk marker cannot report whether the save's caller saw success or Stop."""
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, _, _ = await handover_fixture(environment, monkeypatch)
    ledger_path = hass.root / "spotnav.morek_schedule.connector_outcomes"
    ledger_path.write_text(json.dumps({"version": 1, "data": {"schema": 1, "entry_id": "a",
        "uncertain": False, "attempt": {"state": "accepted"}}}), encoding="utf-8")
    original = store._store.async_save
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def save_then_fail(data):
        await original(data)
        if data["records"]["a"].get("handover", {}).get("state") == "completed":
            reached.set()
            await proceed.wait()
            raise OSError("write landed but completion was not observed")
    monkeypatch.setattr(store._store, "async_save", save_then_fail)
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor, require_outcome=True))
    await asyncio.wait_for(reached.wait(), 2)
    owner_path = hass.root / execution_ownership.STORAGE_KEY
    landed_owner, landed_ledger = owner_path.read_bytes(), ledger_path.read_bytes()
    with gate.person_stop_reservation("a", identity):
        proceed.set()
        assert await task == "save_uncertain"
    assert owner_path.read_bytes() == landed_owner and ledger_path.read_bytes() == landed_ledger
    # A clean save produces these same durable records; process-local Stop and
    # save-error evidence disappear at restart. Neither record grants recovery.
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    revision = restarted.reserve_lifecycle_barrier("a", identity)
    assert await restarted.async_recover_after_restart("a", identity, revision, 0) == "restart_dispatch_evidence_unavailable"
    op = AsyncMock()
    assert not (await restarted.async_execute("a", "owned_profile", identity, op)).allowed
    op.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["failure", "cancel", "stop", "durable_stop"])
async def test_landed_nonprofile_proof_recovers_after_restart(environment, monkeypatch, race):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, _, _, _, _ = environment
    _, gate, identity, executor, _, _ = await handover_fixture(environment, monkeypatch)
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    ledger = morek_outcomes.outcomes_for(hass)
    original = ledger.store.async_save
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def landed(data):
        await original(data)
        if "migration_recovery_proof" in data:
            reached.set()
            await proceed.wait()
            if race == "failure":
                raise OSError("proof landed before failure")
    monkeypatch.setattr(ledger.store, "async_save", landed)
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor, require_outcome=True))
    await asyncio.wait_for(reached.wait(), 2)
    if race == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif race in ("stop", "durable_stop"):
        with gate.person_stop_reservation("a", identity):
            proceed.set()
            assert await task == "completion_interrupted"
    else:
        proceed.set()
        assert await task == "handover_evidence_unavailable"
    assert "a" not in gate._completion_tickets
    hass.data.pop("spotnav_morek_outcomes", None)
    if race == "durable_stop":
        durable_ledger = morek_outcomes.outcomes_for(hass)
        outcome = await durable_ledger.read()
        outcome["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "new-stop",
                                     "station_id": MOREK_STATION_ID, "connector_id": 1}
        await durable_ledger.write(outcome)
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    revision = restarted.reserve_lifecycle_barrier("a", identity)
    assert await restarted.async_recover_after_restart("a", identity, revision, 0) == "automatic_recovery_ready"
    pause = (await morek_outcomes.outcomes_for(hass).read()).get("schedule_pause")
    assert (pause and pause["id"]) == ("new-stop" if race == "durable_stop" else None)
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "wrong_migration", "wrong_connector", "bad_ack", "uncertain", "valid"])
async def test_automatic_restart_requires_bound_post_dispatch_evidence(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes
    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": {**record("morek_schedule"), "handover": {
        "version": 1, "state": "completed", "id": "a" * 32}}})
    proof = {"version": 1, "migration_id": "a" * 32, "station_id": MOREK_STATION_ID,
             "connector_id": 1, "attempt_id": "b" * 32, "ack": "accepted"}
    if case == "wrong_migration":
        proof["migration_id"] = "c" * 32
    elif case == "wrong_connector":
        proof["connector_id"] = 2
    elif case == "bad_ack":
        proof["ack"] = "unknown"
    outcome = {"schema": 1, "entry_id": "a", "uncertain": case == "uncertain",
               "attempt": {"state": "uncertain" if case == "uncertain" else "accepted"}}
    if case != "missing":
        outcome["migration_dispatch_evidence"] = proof
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": outcome}), encoding="utf-8")
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    revision = gate.reserve_lifecycle_barrier("a", identity)
    result = await gate.async_recover_after_restart("a", identity, revision, 0)
    assert (result == "automatic_recovery_ready") == (case == "valid")
    operation = AsyncMock()
    assert (await gate.async_execute("a", "owned_profile", identity, operation)).allowed == (case == "valid")
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_recovery_refuses_stop_while_ledger_read_waits(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes
    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": {**record("morek_schedule"), "handover": {
        "version": 1, "state": "completed", "id": "a" * 32}}})
    outcome = {"schema": 1, "entry_id": "a", "uncertain": False, "attempt": {"state": "accepted"},
               "migration_dispatch_evidence": {"version": 1, "migration_id": "a" * 32,
                   "station_id": MOREK_STATION_ID, "connector_id": 1, "attempt_id": "b" * 32, "ack": "accepted"}}
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": outcome}), encoding="utf-8")
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    revision = gate.reserve_lifecycle_barrier("a", identity)
    ledger = morek_outcomes.outcomes_for(hass)
    original = ledger.read
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed():
        reached.set()
        await proceed.wait()
        return await original()
    monkeypatch.setattr(ledger, "read", delayed)
    task = asyncio.create_task(gate.async_recover_after_restart("a", identity, revision, 0))
    await asyncio.wait_for(reached.wait(), 2)
    with gate.person_stop_reservation("a", lambda: {"supported": False}):
        proceed.set()
        assert await task == "reconfirmation_interrupted"
    assert "a" not in gate._completion_tickets


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["clean", "stop", "uncertain", "identity_away_back"])
async def test_real_reconnect_only_recovers_prior_current_process_ticket(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, entry = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": {**record("morek_schedule"), "handover": {
        "version": 1, "state": "completed", "id": "a" * 32}}})
    path = hass.root / "spotnav.morek_schedule.connector_outcomes"
    path.write_text(json.dumps({"version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                              "attempt": {"state": "accepted"}}}), encoding="utf-8")
    callbacks, tasks = [], []
    monkeypatch.setattr(integration, "async_track_state_change_event",
                        lambda _h, _ids, callback: callbacks.append(callback) or (lambda: None))
    entry.async_create_background_task = lambda _h, coro, _name: tasks.append(asyncio.create_task(coro))
    entry.runtime_data = SimpleNamespace(executor=None, morek_worker=None)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    assert await gate.async_reconfirm_completed("a", identity) == "reconfirmed"
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                      "new_state": SimpleNamespace(state="unavailable")}))
    if case == "stop":
        with gate.person_stop_reservation("a", identity):
            pass
    elif case == "uncertain":
        path.write_text(json.dumps({"version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True,
                                  "attempt": {"state": "uncertain"}}}), encoding="utf-8")
    elif case == "identity_away_back":
        target.connector_id = 2
    callbacks[0](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                      "new_state": SimpleNamespace(state="off")}))
    target.connector_id = 1
    await asyncio.gather(*tasks)
    connector = command_admission.physical_connector(identity())
    assert gate.owned_ticket_current("a", connector) == (case == "clean")
    operation = AsyncMock()
    result = await gate.async_execute("a", "owned_profile", identity, operation)
    assert result.allowed == (case == "clean")
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["cancel", "stop", "newer_barrier"])
async def test_automatic_reconnect_cannot_publish_stale_ticket(environment, monkeypatch, race):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": {**record("morek_schedule"), "handover": {
        "version": 1, "state": "completed", "id": "a" * 32}}})
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({"version": 1, "data": {
        "schema": 1, "entry_id": "a", "uncertain": False, "attempt": {"state": "accepted"}}}), encoding="utf-8")
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    gate.reserve_lifecycle_barrier("a", identity)
    assert await gate.async_reconfirm_completed("a", identity) == "reconfirmed"
    gate.reserve_lifecycle_barrier("a", identity, reconnect=True)
    revision = gate.reserve_lifecycle_barrier("a", identity, reconnect=True)
    ledger = morek_outcomes.outcomes_for(hass)
    original = ledger.read
    reached, proceed = asyncio.Event(), asyncio.Event()
    async def delayed():
        reached.set()
        await proceed.wait()
        return await original()
    monkeypatch.setattr(ledger, "read", delayed)
    task = asyncio.create_task(gate.async_restore_reconnect("a", identity, revision))
    await asyncio.wait_for(reached.wait(), 2)
    if race == "cancel":
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif race == "stop":
        with gate.person_stop_reservation("a", identity):
            proceed.set()
            assert not await task
    else:
        gate.reserve_lifecycle_barrier("a", identity, reconnect=True)
        proceed.set()
        assert not await task
    connector = command_admission.physical_connector(identity())
    assert not gate.owned_ticket_current("a", connector)
    op = AsyncMock()
    assert not (await gate.async_execute("a", "owned_profile", identity, op)).allowed
    op.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["stop", "cancel", "lifecycle"])
async def test_completion_readback_cannot_restore_stale_ticket(environment, monkeypatch, race):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, _, _ = await handover_fixture(environment, monkeypatch)
    (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
        "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
                                "attempt": {"state": "accepted"}}}), encoding="utf-8")
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = hass.async_add_executor_job

    async def delayed_read(func, *args):
        if args and args[0] == store._store.path:
            raw = json.loads((hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8"))
            if raw["data"]["records"]["a"].get("handover", {}).get("state") == "completed":
                reached.set()
                await proceed.wait()
        return await original(func, *args)

    monkeypatch.setattr(hass, "async_add_executor_job", delayed_read)
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor, require_outcome=True))
    await asyncio.wait_for(reached.wait(), 2)
    if race == "cancel":
        task.cancel()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif race == "stop":
        with gate.person_stop_reservation("a", identity):
            proceed.set()
            assert await task == "completion_interrupted"
    else:
        gate.reserve_lifecycle_barrier("a", identity)
        proceed.set()
        assert await task == "completion_interrupted"
    assert "a" not in gate._completion_tickets
    operation = AsyncMock()
    assert not (await gate.async_execute("a", "owned_profile", identity, operation)).allowed
    operation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["old_owner", "unconfirmed", "held_exit", "missing", "uncertain", "no_ledger"])
async def test_reconfirmation_never_repairs_ambiguous_evidence(environment, monkeypatch, kind):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, _ = environment
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    completed = {"version": 1, "state": "completed", "id": "a" * 32}
    if kind != "missing":
        if kind == "held_exit":
            value = {**record(), "transition": {"version": 1, "state": "exit_held_unarmed"}}
        else:
            value = record("morek_schedule")
            if kind != "old_owner":
                value["handover"] = {**completed, "state": "owner_written_unconfirmed"} if kind == "unconfirmed" else completed
        persist(hass, {"a": value})
    if kind != "no_ledger":
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": kind == "uncertain",
                                    "attempt": {"state": "uncertain" if kind == "uncertain" else "accepted"}}}), encoding="utf-8")
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    assert await gate.async_reconfirm_completed("a", identity) != "reconfirmed"
    assert "a" not in gate._completion_tickets
    operation = AsyncMock()
    assert not (await gate.async_execute("a", "owned_profile", identity, operation)).allowed
    operation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("ledger", ["accepted", "missing", "uncertain"])
async def test_setup_migrates_known_legacy_before_executor_start(environment, monkeypatch, ledger):
    from homeassistant.helpers import storage
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, entry = environment
    monkeypatch.setattr(storage, "Store", FakeStore)
    monkeypatch.setattr(morek_outcomes, "Store", FakeStore)
    persist(hass, {"a": record()})
    if ledger != "missing":
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": ledger == "uncertain",
                                    "attempt": {"state": "uncertain" if ledger == "uncertain" else "accepted"}}}), encoding="utf-8")
    adapter, path, _, _ = adapter_for(hass, target)
    monkeypatch.setattr(controller_module, "Store", lambda *_args, **_kwargs: MagicMock())
    monkeypatch.setattr(controller_module, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    monkeypatch.setattr(controller_module, "energy_register_entity_for", lambda *_: None)
    monkeypatch.setattr(controller_module, "CoreFailureRepairs", MagicMock())
    charger = ChargingController(hass, "a", {"charge_control": "switch.charger"})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    executor = AutoExecutor(hass, charger, settings)
    entry.runtime_data = SimpleNamespace(executor=None)
    await integration._async_setup_ownership_metadata(hass, entry, charger, migrate=True)
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    assert (await store.async_status("a", identity()))["transition_state"] == "drained_unarmed"
    await integration._async_finish_morek_migration(
        hass, entry, SimpleNamespace(ocpp_target=target), executor)
    assert (await store.async_status("a", identity()))["transition_state"] == "drained_unarmed"
    entry.runtime_data.executor = executor
    await integration._async_finish_morek_migration(hass, entry, charger, executor)
    result = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert not result["armed"]
    if ledger == "accepted":
        assert result["recorded_owner"] == "morek_schedule"
        assert gate._recovery_status["a"]["migration_result"] == "handed_over_unarmed"
    else:
        assert result["recorded_owner"] == "legacy" and result["transition_state"] == "drained_unarmed"
        assert gate._recovery_status["a"]["migration_result"] == (
            "profile_history_unavailable" if ledger == "missing" else "profile_outcome_uncertain")
    operation = AsyncMock()
    assert not (await gate.async_execute("a", "owned_profile", identity, operation)).allowed
    assert not (await gate.async_execute("a", "legacy_actuator", identity, operation)).allowed
    assert not (await gate.async_manual_profile("a", identity, operation)).allowed
    operation.assert_not_awaited()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_migration_setup_never_initializes_missing_ownership(environment):
    hass, store, gate, target, _, entry = environment
    entry.runtime_data = SimpleNamespace(executor=None)
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"), migrate=True)
    assert gate._recovery_status["a"]["state"] == "ownership_missing"
    assert store._store.saves == 0
    write = AsyncMock()
    identity = lambda: morek_schedule._identity_status(hass, target)  # noqa: E731
    assert not (await gate.async_execute("a", "legacy_actuator", identity, write)).allowed
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_unarmed_handover_persists_and_excludes_writers(environment, monkeypatch):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    drained = json.loads((hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8"))
    migration = drained["data"]["records"]["a"]["transition"]
    assert migration["version"] == 2 and migration["state"] == "drained_unarmed"
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["recorded_owner"] == "morek_schedule" and not status["armed"]
    assert status["handover_evidence"] == "owner_written_unconfirmed"
    saved = json.loads((hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8"))
    assert saved["data"]["records"]["a"]["handover"]["id"] == migration["id"]
    new_gate = command_admission.CommandAdmission(restarted)
    operation = AsyncMock()
    assert not (await new_gate.async_execute("a", "legacy_actuator", identity, operation)).allowed
    assert not (await new_gate.async_manual_profile("a", identity, operation)).allowed
    assert (await new_gate.async_execute("a", "owned_profile", identity, operation)).reason == "schedule_mode_unarmed"
    operation.assert_not_awaited()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_unarmed_exit_retains_profile_and_durable_interlock(environment, monkeypatch):
    hass, _, _, target, _, entry = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    history = hass.root / "spotnav.morek_schedule.a"
    history.write_text(json.dumps({"version": 1, "data": {"profile": {"final_limit": 0}, "ack": "Accepted"}}), encoding="utf-8")
    evidence = history.read_bytes()
    ledger = hass.root / "spotnav.morek_schedule.connector_outcomes"
    ledger.write_text(json.dumps({"version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": False,
        "attempt": {"state": "accepted"}, "acknowledged": {"retained_final_limit": 0}}}), encoding="utf-8")
    ledger_evidence = ledger.read_bytes()
    assert await gate.async_exit_unarmed_held("a", identity) == "exited_held"
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] == "exit_held_unarmed"
    new_gate = command_admission.CommandAdmission(restarted)
    op = AsyncMock()
    assert not (await new_gate.async_execute("a", "legacy_actuator", identity, op)).allowed
    assert not (await new_gate.async_manual_profile("a", identity, op)).allowed
    assert (await new_gate.async_execute("a", "owned_profile", identity, op)).reason == "schedule_mode_unarmed"
    assert (await new_gate.async_recovery_status("a", identity))["state"] == "legacy_exit_held_unarmed"
    assert await new_gate.async_recover_unarmed("a", identity, settings_store=executor._store) == "legacy_exit_held_unarmed"
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    assert history.read_bytes() == evidence and ledger.read_bytes() == ledger_evidence
    assert executor._store.settings("a").pause.choice == "until_resumed"
    with pytest.raises(AutoControlRefused):
        await executor.async_resume()
    assert not await adapter.async_start()
    op.assert_not_awaited()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_exit_hold_blocks_deletion_handback(environment, monkeypatch):
    hass, _, _, target, _, entry = environment
    _, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    assert await gate.async_exit_unarmed_held("a", identity) == "exited_held"
    adapter.enabled_state = lambda: False
    adapter.restore_memory = MagicMock()
    adapter.cancel_pending_reads = MagicMock()
    monkeypatch.setattr(charger_handback, "_async_saved_record", AsyncMock(return_value={"spotnav_stopped": True}))
    monkeypatch.setattr(charger_handback, "duplicates_of", lambda *_: [])
    monkeypatch.setattr(charger_handback, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    entry.data = {"charge_control": "switch.charger"}
    assert await charger_handback.async_hand_back_charger(hass, entry) == []
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before", "after", "cancel"])
async def test_exit_save_uncertainty_keeps_both_possible_disk_states_interlocked(environment, monkeypatch, failure):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    original = store._store.async_save
    entered = asyncio.Event()
    async def save(data):
        if failure == "after":
            await original(data)
        if failure == "cancel":
            entered.set()
            await asyncio.Event().wait()
        raise OSError("synthetic uncertain exit")
    store._store.async_save = AsyncMock(side_effect=save)
    task = asyncio.create_task(gate.async_exit_unarmed_held("a", identity))
    if failure == "cancel":
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task == "save_uncertain"
    assert await gate.async_exit_unarmed_held("a", identity) == "ownership_unavailable"
    store._store.async_save.assert_awaited_once()
    assert not await adapter.async_start()
    assert (await store.async_status("a", identity()))["record_state"] == "save_failed"
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["recorded_owner"] == ("legacy" if failure == "after" else "morek_schedule")
    if failure == "after":
        assert status["transition_state"] == "exit_held_unarmed"
    assert not (await command_admission.CommandAdmission(restarted).async_execute(
        "a", "legacy_actuator", identity, AsyncMock())).allowed
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_person_stop_during_exit_preserves_intent_without_physical_claim(environment, monkeypatch, phase):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    original = store._store.async_save
    entered, release = asyncio.Event(), asyncio.Event()
    async def save(data):
        if phase == "after":
            await original(data)
        entered.set()
        await release.wait()
        if phase == "before":
            await original(data)
    store._store.async_save = save
    exit_task = asyncio.create_task(gate.async_exit_unarmed_held("a", identity))
    await entered.wait()
    adapter.vehicle_connected = lambda: True
    stop_task = asyncio.create_task(executor.async_manual_stop())
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.wait_for(exit_task, 2) == "exited_held_interrupted"
    with pytest.raises(AutoControlRefused):
        await asyncio.wait_for(stop_task, 2)
    assert executor._store.settings("a").pause.action == "stop"
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] == "exit_held_unarmed"
    path.async_stop.assert_not_awaited()
    assert not await adapter.async_start()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["uncertain", "legacy_unknown", "missing", "corrupt", "duplicate", "ambiguous", "inflight_unknown"])
async def test_unarmed_exit_refuses_untrusted_evidence(environment, monkeypatch, case):
    hass, _, _, _, system, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    if case == "uncertain":
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True}}), encoding="utf-8")
    elif case == "legacy_unknown":
        (hass.root / "spotnav.morek_schedule.a").write_text(json.dumps({
            "version": 1, "data": {"profile": {"id": 1}, "ack": "unknown"}}), encoding="utf-8")
    elif case in ("missing", "corrupt"):
        path_on_disk = hass.root / execution_ownership.STORAGE_KEY
        if case == "missing":
            path_on_disk.unlink()
        else:
            path_on_disk.write_text("{broken", encoding="utf-8")
    elif case == "duplicate":
        assert await gate.async_ensure_initialized("b", identity) == "ownership_conflict"
    elif case == "ambiguous":
        hass.data["ocpp"]["two"] = system
    else:
        gate._uncertain_operations.add(command_admission.physical_connector(identity()))
    assert await gate.async_exit_unarmed_held("a", identity) != "exited_held"
    assert not await adapter.async_start()
    assert await adapter.async_stop(protection=True)
    path.async_start.assert_not_awaited()
    path.async_stop.assert_awaited_once()
    if case not in ("missing", "corrupt", "ambiguous", "duplicate"):
        assert (await store.async_status("a", identity()))["recorded_owner"] == "morek_schedule"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_exit_waits_for_admitted_work_and_rejects_stale_generation(environment, monkeypatch):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    entered, release = asyncio.Event(), asyncio.Event()
    async def read():
        entered.set()
        await release.wait()
    active = asyncio.create_task(gate.async_execute("a", "read_only", identity, read))
    await entered.wait()
    exit_task = asyncio.create_task(gate.async_exit_unarmed_held("a", identity))
    await asyncio.sleep(0)
    assert not exit_task.done()
    connector = command_admission.physical_connector(identity())
    gate._generations[connector] = gate.generation(connector).revision + 1
    release.set()
    assert (await active).allowed
    assert await asyncio.wait_for(exit_task, 2) == "stale_generation"
    assert (await store.async_status("a", identity()))["recorded_owner"] == "morek_schedule"
    other, other_path, _, _ = adapter_for(hass, SimpleNamespace(devid="other", connector_id=2))
    assert await other.async_start()
    other_path.async_start.assert_awaited_once()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_person_stop_reserved_before_exit_prevents_transition(environment, monkeypatch):
    _, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    with adapter.person_stop_scope():
        assert await gate.async_exit_unarmed_held("a", identity) == "person_stop_active"
    assert (await store.async_status("a", identity()))["recorded_owner"] == "morek_schedule"
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_person_stop_recorded_before_exit_remains_intact(environment, monkeypatch):
    hass, _, _, _, _, _ = environment
    _, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    adapter.vehicle_connected = lambda: True
    with pytest.raises(AutoControlRefused):
        await executor.async_manual_stop()
    pause = executor._store.settings("a").pause
    assert pause.action == "stop"
    assert await gate.async_exit_unarmed_held("a", identity) == "exited_held"
    assert executor._store.settings("a").pause == pause
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert status["transition_state"] == "exit_held_unarmed"
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_write", "after_write"])
async def test_stop_during_owner_save_restores_legacy(environment, monkeypatch, phase):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    save = store._store.async_save
    async def save_with_barrier(data):
        if data["records"]["a"]["owner"] == "morek_schedule":
            if phase == "after_write":
                await save(data)
            entered.set()
            await release.wait()
            if phase == "before_write":
                await save(data)
        else:
            await save(data)
    store._store.async_save = save_with_barrier
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor))
    await entered.wait()
    with adapter.person_stop_scope():
        release.set()
        assert await asyncio.wait_for(task, 2) == "interrupted"
        assert await adapter.async_legacy_permitted(person_stop=True)
    status = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] == "interrupted"
    assert not await adapter.async_start()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before", "after", "cancel", "rollback"])
async def test_handover_uncertain_saves_never_retry_or_admit_writes(environment, monkeypatch, failure):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    original = store._store.async_save
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def save(data):
        owner = data["records"]["a"]["owner"]
        calls.append(owner)
        if failure == "rollback" and owner == "morek_schedule":
            await original(data)
            entered.set()
            await release.wait()
            return
        if failure == "rollback" or (failure in ("before", "after", "cancel") and owner == "morek_schedule"):
            if failure == "after":
                await original(data)
            if failure == "cancel":
                entered.set()
                await release.wait()
            raise OSError("synthetic unknown write")
        await original(data)
    store._store.async_save = save
    task = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor))
    if failure in ("cancel", "rollback"):
        await entered.wait()
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with adapter.person_stop_scope():
                release.set()
                assert await asyncio.wait_for(task, 2) == "save_uncertain"
                assert not await adapter.async_legacy_permitted(person_stop=True)
    else:
        assert await task == "save_uncertain"
    assert calls == (["morek_schedule", "legacy"] if failure == "rollback" else ["morek_schedule"])
    assert (await store.async_status("a", identity()))["record_state"] == "save_failed"
    assert not await adapter.async_start()
    state = await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity())
    assert state["recorded_owner"] == ("morek_schedule" if failure in ("after", "rollback") else "legacy")
    if failure in ("after", "rollback"):
        assert state["handover_evidence"] == "owner_written_unconfirmed"
    restarted = command_admission.CommandAdmission(execution_ownership.ExecutionOwnershipStore(hass))
    assert not (await restarted.async_execute("a", "owned_profile", identity, AsyncMock())).allowed
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_after_handover_preserves_intent_without_dispatch(environment, monkeypatch):
    _, _, _, _, _, _ = environment
    _, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    assert await gate.async_handover_unarmed("a", identity, executor) == "handed_over_unarmed"
    adapter.vehicle_connected = lambda: True
    with pytest.raises(AutoControlRefused):
        await executor.async_manual_stop()
    assert executor._store.settings("a").pause.action == "stop"
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_write", "after_write"])
async def test_auto_stop_waits_for_handover_compensation_and_records_intent(environment, monkeypatch, phase):
    from custom_components.spotnav.planning.auto_settings import PauseIntent

    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    await executor._store.async_update("a", mutate=lambda value: replace(value, pause=PauseIntent()))
    adapter.vehicle_connected = lambda: True
    async def stop(**_kwargs):
        assert await adapter.async_stop(person_stop=True)
    executor._controller.async_stop = AsyncMock(side_effect=stop)
    executor._controller.reset_person_hold = MagicMock()
    executor._runner = MagicMock()
    executor._runner.begin.return_value = SimpleNamespace(early=True)
    executor._notify_change = AsyncMock()
    executor._sync_manual_watch = MagicMock()
    executor._note_manual_stop_sent = MagicMock()
    executor._core_stop_scope = lambda _connected, scope, **_kw: scope
    executor._core_connected = lambda **_kw: True
    executor._core_stop_outcome = MagicMock()
    entered, release = asyncio.Event(), asyncio.Event()
    original = store._store.async_save
    async def save(data):
        if data["records"]["a"]["owner"] == "morek_schedule":
            if phase == "after_write":
                await original(data)
            entered.set()
            await release.wait()
            if phase == "before_write":
                await original(data)
        else:
            await original(data)
    store._store.async_save = save
    handover = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor))
    await entered.wait()
    stop_task = asyncio.create_task(executor.async_manual_stop())
    await asyncio.sleep(0)
    assert not stop_task.done()
    release.set()
    assert await asyncio.wait_for(handover, 2) == "interrupted"
    await asyncio.wait_for(stop_task, 2)
    assert executor._store.settings("a").pause.action == "stop"
    assert (await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity()))["recorded_owner"] == "legacy"
    path.async_stop.assert_awaited_once()
    path.async_start.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_before_handover_prevents_owner_save(environment, monkeypatch):
    hass, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    save = AsyncMock(wraps=store._store.async_save)
    store._store.async_save = save
    with adapter.person_stop_scope():
        assert await gate.async_handover_unarmed("a", identity, executor) == "handover_interrupted"
        assert await adapter.async_legacy_permitted(person_stop=True)
    save.assert_not_awaited()
    assert (await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity()))["recorded_owner"] == "legacy"
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["owner", "rollback"])
async def test_uncertain_owner_save_keeps_auto_stop_intent_without_dispatch(environment, monkeypatch, failure):
    _, _, _, _, _, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = store._store.async_save
    async def save(data):
        if data["records"]["a"]["owner"] == "morek_schedule":
            if failure == "rollback":
                await original(data)
            entered.set()
            await release.wait()
            if failure == "rollback":
                return
        raise OSError("unknown outcome")
    store._store.async_save = AsyncMock(side_effect=save)
    handover = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor))
    await entered.wait()
    adapter.vehicle_connected = lambda: True
    stop = asyncio.create_task(executor.async_manual_stop())
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.wait_for(handover, 2) == "save_uncertain"
    with pytest.raises(AutoControlRefused):
        await asyncio.wait_for(stop, 2)
    assert executor._store.settings("a").pause.action == "stop"
    assert store._store.async_save.await_count == (2 if failure == "rollback" else 1)
    path.async_stop.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["duplicate", "ambiguous", "outcome", "unknown_write"])
async def test_handover_refuses_untrusted_evidence(environment, monkeypatch, case):
    hass, _, _, _, system, _ = environment
    store, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    if case == "duplicate":
        assert await gate.async_ensure_initialized("b", identity) == "ownership_conflict"
    elif case == "ambiguous":
        hass.data["ocpp"]["two"] = system
    elif case == "outcome":
        (hass.root / "spotnav.morek_schedule.connector_outcomes").write_text(json.dumps({
            "version": 1, "data": {"schema": 1, "entry_id": "a", "uncertain": True},
        }), encoding="utf-8")
    else:
        gate._uncertain_operations.add(command_admission.physical_connector(identity()))
    result = await gate.async_handover_unarmed("a", identity, executor)
    assert result != "handed_over_unarmed"
    assert not await adapter.async_start()
    assert await adapter.async_stop(protection=True)
    path.async_start.assert_not_awaited()
    path.async_stop.assert_awaited_once()
    assert (await execution_ownership.ExecutionOwnershipStore(hass).async_status(
        "a", morek_schedule._identity_status(hass, executor.controller.ocpp_target)))["recorded_owner"] != "morek_schedule"


@pytest.mark.asyncio
async def test_queued_legacy_work_and_unrelated_connector_during_handover(environment, monkeypatch):
    hass, _, _, _, _, _ = environment
    _, gate, identity, executor, adapter, path = await handover_fixture(environment, monkeypatch)
    connector = command_admission.physical_connector(identity())
    lock = gate._lock_for(connector)
    await lock.acquire()
    queued = asyncio.create_task(adapter.async_start())
    await asyncio.sleep(0)
    handover = asyncio.create_task(gate.async_handover_unarmed("a", identity, executor))
    await asyncio.sleep(0)
    lock.release()
    assert not await asyncio.wait_for(queued, 2)
    assert await asyncio.wait_for(handover, 2) == "handed_over_unarmed"
    other, other_path, _, _ = adapter_for(hass, SimpleNamespace(devid="other", connector_id=2))
    assert await other.async_start()
    assert await adapter.async_stop(protection=True)
    other_path.async_start.assert_awaited_once()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncertain_transition_save_keeps_stop_possible_and_others_blocked(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    store._store.async_save = AsyncMock(side_effect=TimeoutError("unknown outcome"))
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "ownership_unavailable"
    adapter, path, _, _ = adapter_for(hass, target)
    assert not await adapter.async_start()
    with adapter.person_stop_scope():
        assert await adapter.async_stop(person_stop=True)
    path.async_start.assert_not_awaited()
    path.async_stop.assert_awaited_once()
    store._store.async_save.assert_awaited_once()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_during_requested_save_marks_interrupted(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    entered, release = asyncio.Event(), asyncio.Event()
    save = store._store.async_save
    async def delayed(data):
        if data["records"]["a"]["transition"]["state"] == "requested":
            entered.set()
            await release.wait()
        await save(data)
    store._store.async_save = delayed
    task = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await entered.wait()
    with gate.person_stop_reservation("a", identity):
        release.set()
        assert await task == "interrupted"
    assert (await execution_ownership.ExecutionOwnershipStore(hass).async_status("a", identity()))["transition_state"] == "interrupted"
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_during_requested_save_is_not_retried(environment):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    entered = asyncio.Event()
    async def saving(_data):
        entered.set()
        await asyncio.Event().wait()
    store._store.async_save = AsyncMock(side_effect=saving)
    task = asyncio.create_task(gate.async_begin_unarmed_entry("a", identity, lambda: False))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.async_status("a", identity()))["record_state"] == "save_failed"
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "entry_unavailable"
    store._store.async_save.assert_awaited_once()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", [
    {"version": 2, "state": "requested"},
    {"version": 1, "state": "unknown"},
    {"version": 1, "state": "requested", "extra": True},
])
async def test_malformed_transition_is_not_migrated(environment, transition):
    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": transition}})
    original = (hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8")
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "ownership_unavailable"
    assert (await store.async_status("a", identity()))["record_state"] == "malformed"
    assert (hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8") == original
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["requested", "interrupted", "drained_unarmed"])
@pytest.mark.parametrize(("outcome", "expected"), [
    (None, "aborted"),
    ({"entry_id": "a", "uncertain": True}, "profile_outcome_uncertain"),
    ({"entry_id": "a", "uncertain": False, "acknowledged": {"id": "known"}},
     "aborted"),
    ({"entry_id": "a", "uncertain": False}, "aborted"),
])
async def test_abort_recovery_after_restart(environment, monkeypatch, transition, outcome, expected):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, entry = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": transition}}})
    def identity():
        return morek_schedule._identity_status(hass, target)
    ledger = SimpleNamespace(read=AsyncMock(return_value=outcome))
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: ledger)
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    adapter, path, _, _ = adapter_for(hass, target)
    await integration._async_setup_ownership_metadata(hass, entry, SimpleNamespace(
        ocpp_target=target, charge_control="switch.charger"))
    assert await gate.async_abort_unarmed_entry("a", identity, settings_store=settings) == expected
    assert await gate.async_abort_unarmed_entry("a", identity, settings_store=settings) == (
        "no_transition" if expected == "aborted" else expected)
    assert (await store.async_status("a", identity()))["transition_state"] == (
        None if expected == "aborted" else transition)
    assert settings.settings("a").pause.choice == "until_resumed"
    if expected != "aborted":
        assert not await adapter.async_start()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_abort_is_interrupted_by_person_stop_while_reading_evidence(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    def identity():
        return morek_schedule._identity_status(hass, target)
    entered, release = asyncio.Event(), asyncio.Event()
    async def read():
        entered.set()
        await release.wait()
        return {"entry_id": "a", "uncertain": False}
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=read))
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    task = asyncio.create_task(gate.async_abort_unarmed_entry("a", identity, settings_store=settings))
    await entered.wait()
    with gate.person_stop_reservation("a", identity):
        release.set()
        assert await task == "person_stop_or_generation_changed"
    assert (await store.async_status("a", identity()))["transition_state"] == "requested"
    assert (await gate.async_execute("a", "legacy_actuator", identity, AsyncMock())).allowed is False
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_save_that_definitely_did_not_land_leaves_previous_legacy_record(environment, monkeypatch):
    hass, store, gate, target, _, entry = environment
    await integration._async_setup_ownership_metadata(
        hass, entry, SimpleNamespace(ocpp_target=target, charge_control="switch.charger"))
    def identity():
        return morek_schedule._identity_status(hass, target)
    before = (hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8")
    store._store.async_save = AsyncMock(side_effect=OSError("not written by mocked boundary"))
    assert await gate.async_begin_unarmed_entry("a", identity, lambda: False) == "ownership_unavailable"
    assert (hass.root / execution_ownership.STORAGE_KEY).read_text(encoding="utf-8") == before
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] is None
    # The later reader cannot distinguish this from an ordinary legacy document.
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    assert await command_admission.CommandAdmission(restarted).async_abort_unarmed_entry(
        "a", identity, settings_store=settings) == "no_transition"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before", "after", "cancel"])
async def test_abort_save_uncertainty_preserves_pause_and_blocks_in_process(environment, monkeypatch, failure):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    settings_bytes = Path(settings._store.path).read_bytes()
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=AsyncMock(return_value=None)))
    def identity():
        return morek_schedule._identity_status(hass, target)
    saved = store._store.async_save
    started = asyncio.Event()
    async def save(data):
        if failure == "after":
            await saved(data)
        if failure == "cancel":
            started.set()
            await asyncio.Event().wait()
        raise OSError("synthetic write outcome")
    store._store.async_save = AsyncMock(side_effect=save)
    task = asyncio.create_task(gate.async_abort_unarmed_entry("a", identity, settings_store=settings))
    if failure == "cancel":
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task == "save_uncertain"
    assert (await store.async_status("a", identity()))["record_state"] == "save_failed"
    assert not (await gate.async_execute("a", "legacy_actuator", identity, AsyncMock())).allowed
    restarted = execution_ownership.ExecutionOwnershipStore(hass)
    status = await restarted.async_status("a", identity())
    assert status["transition_state"] == (None if failure == "after" else "requested")
    assert Path(settings._store.path).read_bytes() == settings_bytes
    assert settings.settings("a").pause.choice == "until_resumed"
    hass.station.call.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_racing_abort_save_never_clears_pause_or_automatically_dispatches(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=AsyncMock(return_value=None)))
    def identity():
        return morek_schedule._identity_status(hass, target)
    entered, release = asyncio.Event(), asyncio.Event()
    save = store._store.async_save
    async def delay(data):
        entered.set()
        await release.wait()
        await save(data)
    store._store.async_save = delay
    task = asyncio.create_task(gate.async_abort_unarmed_entry("a", identity, settings_store=settings))
    await entered.wait()
    adapter, path, _, _ = adapter_for(hass, target)
    with adapter.person_stop_scope():
        release.set()
        assert await task == "aborted_stop_pending"
        assert await adapter.async_legacy_permitted(person_stop=True)
    assert settings.settings("a").pause.choice == "until_resumed"
    assert (await store.async_status("a", identity()))["transition_state"] is None
    assert not await adapter.async_start()
    path.async_start.assert_not_awaited()
    path.async_stop.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_pause", "unsaved", "uncertain", "identity", "duplicate"])
async def test_abort_refuses_unsafe_evidence(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes

    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    def identity():
        return morek_schedule._identity_status(hass, target)
    if case == "no_pause":
        from custom_components.spotnav.planning.auto_settings import PauseIntent
        await settings.async_update("a", mutate=lambda value: replace(value, pause=PauseIntent()))
    if case == "unsaved":
        settings._unsaved = True
    if case == "duplicate":
        assert await gate.async_ensure_initialized("b", identity) == "ownership_conflict"
    outcome = {"entry_id": "a", "uncertain": case == "uncertain"}
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=AsyncMock(return_value=outcome)))
    resolved = (lambda: {}) if case == "identity" else identity
    result = await gate.async_abort_unarmed_entry("a", resolved, settings_store=settings)
    assert result == {"no_pause": "pause_not_indefinite", "unsaved": "pause_unavailable",
                      "uncertain": "profile_outcome_uncertain", "identity": "identity_unresolved",
                      "duplicate": "ownership_unavailable"}[case]
    if case != "duplicate":
        assert (await store.async_status("a", identity()))["transition_state"] == "requested"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_abort_preserves_legacy_stop_and_known_profile_evidence_across_reload(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes
    from custom_components.spotnav.planning.auto_settings import AutoSettingsStore

    hass, store, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "interrupted"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    old_file = hass.root / "spotnav.morek_schedule.a"
    old_file.write_text(json.dumps({"version": 1, "data": {"profile": {"retained": True}, "ack": "Accepted"}}), encoding="utf-8")
    old_bytes = old_file.read_bytes()
    stop_file = hass.root / "spotnav.a"
    stop_file.write_text('{"version": 1, "data": {"person_stopped": true}}', encoding="utf-8")
    ledger_record = {"entry_id": "a", "uncertain": False, "acknowledged": {"id": "known"}}
    ledger = SimpleNamespace(read=AsyncMock(return_value=ledger_record), write=AsyncMock())
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: ledger)
    def identity():
        return morek_schedule._identity_status(hass, target)
    assert await gate.async_abort_unarmed_entry("a", identity, settings_store=settings) == "aborted"
    reloaded = execution_ownership.ExecutionOwnershipStore(hass)
    status = await reloaded.async_status("a", identity())
    assert status["recorded_owner"] == "legacy" and status["transition_state"] is None
    class ReloadStore(FakeStore):
        async def async_load(self):
            return json.loads(Path(self.path).read_text(encoding="utf-8"))["data"]
    reloaded_settings = AutoSettingsStore(hass, store=ReloadStore(hass, 1, "spotnav_auto_settings"))
    await reloaded_settings.async_load()
    assert reloaded_settings.settings("a").pause.choice == "until_resumed"
    assert json.loads(stop_file.read_text(encoding="utf-8"))["data"]["person_stopped"] is True
    assert old_file.read_bytes() == old_bytes and ledger_record["acknowledged"]["id"] == "known"
    ledger.write.assert_not_awaited()
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_legacy_generation_is_stale_after_abort(environment, monkeypatch):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, _ = environment
    persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    def identity():
        return morek_schedule._identity_status(hass, target)
    connector = command_admission.physical_connector(identity())
    old = gate.generation(connector)
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=AsyncMock(return_value=None)))
    assert await gate.async_abort_unarmed_entry("a", identity, settings_store=settings) == "aborted"
    write = AsyncMock()
    result = await gate.async_execute("a", "legacy_actuator", identity, write, expected_generation=old)
    assert result.reason == "stale_generation"
    write.assert_not_awaited()
    assert (await gate.async_execute("a", "owned_profile", identity, write)).reason == "schedule_mode_unarmed"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "corrupt", "legacy_unknown"])
async def test_abort_refuses_missing_or_ambiguous_durable_evidence(environment, monkeypatch, case):
    from custom_components.spotnav.execution import morek_outcomes

    hass, _, gate, target, _, _ = environment
    ownership_path = hass.root / execution_ownership.STORAGE_KEY
    if case == "corrupt":
        ownership_path.write_text("{broken", encoding="utf-8")
    elif case == "legacy_unknown":
        persist(hass, {"a": {**record(), "transition": {"version": 1, "state": "requested"}}})
        (hass.root / "spotnav.morek_schedule.a").write_text(json.dumps({
            "version": 1, "data": {"profile": {"id": 1}, "ack": "unknown"},
        }), encoding="utf-8")
    settings = await paused_settings_for_recovery(hass, monkeypatch)
    monkeypatch.setattr(morek_outcomes, "outcomes_for", lambda _: SimpleNamespace(read=AsyncMock(return_value=None)))
    def identity():
        return morek_schedule._identity_status(hass, target)
    result = await gate.async_abort_unarmed_entry("a", identity, settings_store=settings)
    assert result == ("profile_outcome_uncertain" if case == "legacy_unknown" else "ownership_unavailable")
    if case == "missing":
        assert not ownership_path.exists()
    if case == "corrupt":
        assert ownership_path.read_text(encoding="utf-8") == "{broken"
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()
