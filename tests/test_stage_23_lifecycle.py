"""Combined ownership/startup/restore regressions; actual modules, mocked HA and charger I/O."""

import ast
import asyncio
from dataclasses import asdict
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
from custom_components.spotnav.execution.auto_execution import AutoExecutor
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
@pytest.mark.parametrize(("owner", "writes"), [("legacy", 2), ("morek_schedule", 0), ("corrupt", 0)])
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
