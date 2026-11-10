"""Real controller callbacks and adapter write boundaries, with mocked HA/charger I/O."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav.api import morek_schedule, own_mode
from custom_components.spotnav.execution import charger_handback, command_admission, controller as controller_module
from custom_components.spotnav.execution.chargers.adapter import ChargerAdapter
from custom_components.spotnav.execution.chargers.base import PhaseSwitchResult
from custom_components.spotnav.execution.controller import ChargingController, ChargingExecutionError
from custom_components.spotnav.button import manual_actions
from homeassistant.exceptions import HomeAssistantError
from .test_stage_21_ownership import Store, identity, setup


@pytest.mark.parametrize("method", ["_async_hold_stop", "_async_stray_stop", "_async_end_top_off",
                                    "_async_begin_top_off", "_async_window_end_stop",
                                    "_async_person_hold_stop", "async_battery_probe_start"])
def test_real_callbacks_respect_denied_turn(monkeypatch, method):
    controller = ChargingController.__new__(ChargingController)
    executor, _, _, _ = setup(monkeypatch)
    controller._automatic_gate = executor
    controller._lock = asyncio.Lock()
    controller.entry_id = "test"
    controller._recheck = AsyncMock()
    controller._person_hold_stop_locked = AsyncMock()
    controller._shut_down = False
    controller._person_hold_retry_cancel = None
    controller._runner = MagicMock()
    controller._runner.session.hold_stop_pending = True
    controller._runner.session.hold_stop_times = []
    controller.plan = None
    args = ("deadline",) if method == "_async_end_top_off" else (6,) if method == "async_battery_probe_start" else ()
    kwargs = {"clear_schedule": True, "record_completion": True} if method == "_async_window_end_stop" else {}
    result = asyncio.run(getattr(controller, method)(*args, **kwargs))
    assert result is False if method == "async_battery_probe_start" else result is None
    controller._recheck.assert_not_awaited()
    controller._runner.begin.assert_not_called()
    controller._runner.feed.assert_not_called()
    if method == "_async_person_hold_stop":
        assert controller._c7.stop_pending  # retain the person's explicit Stop
        assert controller._person_hold_retry_cancel is None


def test_real_owed_callback_discards_work_without_dispatch(monkeypatch):
    controller = ChargingController.__new__(ChargingController)
    executor, _, _, _ = setup(monkeypatch)
    controller._automatic_gate = executor
    controller._lock = asyncio.Lock()
    controller.entry_id = "test"
    controller._owed_command = False  # _owed_tick removed this before spawning
    controller._owed_current = True
    controller._owed_settling = True
    controller._cancel_owed = MagicMock()
    controller._reschedule_locked = AsyncMock()
    asyncio.run(controller._async_settle_owed(True, True))
    assert not controller._owed_command and not controller._owed_current and not controller._owed_settling
    controller._reschedule_locked.assert_not_awaited()
    controller._cancel_owed.assert_called_once()


def adapter_with_guard(monkeypatch):
    store = Store()
    gate = command_admission.CommandAdmission(store)
    monkeypatch.setattr(command_admission, "command_admission", lambda _hass: gate)
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda _hass, target: target)
    target = identity()
    path = MagicMock(writes_current=False)
    path.async_start = AsyncMock(return_value=True)
    path.async_stop = AsyncMock(return_value=True)
    current = MagicMock()
    current.async_set = AsyncMock(return_value="assigned")
    switch = MagicMock()
    switch.async_set_phases = AsyncMock(return_value=PhaseSwitchResult(True))
    adapter = ChargerAdapter(MagicMock(), platform="ocpp", path=path, current=current,
                             policy=MagicMock(), phase_switch=lambda: switch)
    adapter.write_guard = command_admission.legacy_write_guard(adapter.hass, "a", lambda: target, ocpp=True)
    async def logged(_kind, run, **_kwargs):
        return await run()
    adapter._logged = logged
    return adapter, path, current, switch, store, target


def test_adapter_blocks_ordinary_writes_but_preserves_protection(monkeypatch):
    adapter, path, current, switch, store, _ = adapter_with_guard(monkeypatch)
    async def run():
        assert not await adapter.async_start(16)
        assert not await adapter.async_stop()
        assert await adapter.async_set_current(12, reason="resend") == "ownership_blocked"
        assert not (await adapter.async_set_phases(1)).sent
        path.async_start.assert_not_awaited()
        path.async_stop.assert_not_awaited()
        current.async_set.assert_not_awaited()
        switch.async_set_phases.assert_not_awaited()
        assert await adapter.async_stop(protection=True)
        assert await adapter.async_set_current(6, reason="regulator") == "assigned"
        store.owner = "legacy"
        assert await adapter.async_start(16)
        assert await adapter.async_set_current(10, reason="restore") == "assigned"
        assert (await adapter.async_set_phases(3)).sent
    asyncio.run(run())


@pytest.mark.parametrize("reason", ["session_start", "resend", "setting", "solar", "restore", "handback"])
def test_shared_current_boundary_refuses_each_writer_category(monkeypatch, reason):
    adapter, _, current, _, _, _ = adapter_with_guard(monkeypatch)
    assert asyncio.run(adapter.async_set_current(12, reason=reason)) == "ownership_blocked"
    current.async_set.assert_not_awaited()


def test_unrelated_and_unknown_identity(monkeypatch):
    adapter, path, _, _, _, target = adapter_with_guard(monkeypatch)
    async def run():
        target.update(identity(connector=2))
        assert await adapter.async_start()
        target.update({"match_count": 0, "resolved_id": None})
        assert await adapter.async_start()  # different connector even while station is offline
        target["connector_id"] = 1
        assert not await adapter.async_start()
        assert path.async_start.await_count == 2
    asyncio.run(run())


def test_button_fallback_refuses_before_controller_preparation(monkeypatch):
    adapter, _, _, _, _, _ = adapter_with_guard(monkeypatch)
    controller = SimpleNamespace(adapter=adapter, async_start=AsyncMock(), async_stop=AsyncMock(),
                                 async_follow_schedule=AsyncMock(), async_cancel=AsyncMock())
    async def run():
        for _, action in manual_actions(None, controller):
            with pytest.raises(HomeAssistantError, match="ownership"):
                await action()
        controller.async_start.assert_not_awaited()
        controller.async_stop.assert_not_awaited()
        controller.async_follow_schedule.assert_not_awaited()
        controller.async_cancel.assert_not_awaited()
    asyncio.run(run())


def test_own_mode_api_refuses_conflicting_write(monkeypatch):
    adapter, _, _, _, _, _ = adapter_with_guard(monkeypatch)
    controller = SimpleNamespace(adapter=adapter, charge_control="switch.charge")
    conflict = SimpleNamespace(entity_id="switch.mode", value="on", state="off")
    monkeypatch.setattr(own_mode, "controller_for", lambda *_: controller)
    monkeypatch.setattr(own_mode, "charger_conflicts", lambda *_: [conflict])
    hass = adapter.hass
    hass.services.async_call = AsyncMock()
    entry = SimpleNamespace(entry_id="a", title="charger")
    result = asyncio.run(own_mode.async_fix_own_mode(hass, entry, "switch.mode", "on", source="test"))
    assert result == "legacy_execution_ownership_blocked"
    hass.services.async_call.assert_not_awaited()


def test_direct_controller_refuses_before_start_or_stop_preparation(monkeypatch):
    adapter, path, _, _, _, _ = adapter_with_guard(monkeypatch)
    controller = ChargingController.__new__(ChargingController)
    controller.adapter = adapter
    controller._restore_three_phases_locked = AsyncMock()
    controller._set_own_stop = MagicMock()
    async def run():
        assert not await controller._start_command_locked(manual=True)
        with pytest.raises(ChargingExecutionError) as error:
            await controller._stop_locked(by_person=True)
        assert error.value.code == "legacy_execution_ownership_blocked"
        controller._restore_three_phases_locked.assert_not_awaited()
        controller._set_own_stop.assert_not_called()
        path.async_start.assert_not_awaited()
        path.async_stop.assert_not_awaited()
    asyncio.run(run())


def test_regulator_stop_passes_explicit_protection_classification():
    controller = SimpleNamespace(
        _shut_down=False, _lock=asyncio.Lock(), _log_regulated_stop=MagicMock(),
        _control_on=True, _core_start_pending=lambda: False, _runner=MagicMock(),
        _stop_sent_at=None, _stop_request_locked=AsyncMock(), _core_stop_outcome=lambda _: None,
        _save_memory_soon=MagicMock(), entry_id="test",
    )
    asyncio.run(ChargingController._regulated_stop(controller, "safety_stop"))
    controller._stop_request_locked.assert_awaited_once_with(balancing=True, urgent=True, protection=True)


def test_queued_adapter_write_rechecks_ownership(monkeypatch):
    adapter, path, _, _, store, _ = adapter_with_guard(monkeypatch)
    gate = command_admission.command_admission(adapter.hass)
    connector = command_admission.physical_connector(identity())
    async def run():
        store.owner = "legacy"
        async with gate._lock_for(connector):
            queued = asyncio.create_task(adapter.async_start())
            await asyncio.sleep(0)
            store.owner = "morek_schedule"
        assert not await queued
        path.async_start.assert_not_awaited()
    asyncio.run(run())


def test_real_handback_uses_guard(monkeypatch):
    adapter, path, current, _, _, target = adapter_with_guard(monkeypatch)
    adapter.enabled_state = lambda: False
    adapter.restore_memory = MagicMock()
    adapter.cancel_pending_reads = MagicMock()
    adapter._phase_switch = None
    adapter.current_enabled = True
    current.can_set = True
    current.available.return_value = None
    current.async_present_a = AsyncMock(return_value=None)
    monkeypatch.setattr(charger_handback, "duplicates_of", lambda *_: [])
    monkeypatch.setattr(charger_handback, "_async_saved_record", AsyncMock(return_value={"spotnav_stopped": True,
                        "pre_spotnav_current": {"recorded": True, "amps": 12}}))
    monkeypatch.setattr(charger_handback, "own_stop_from_record", lambda _: True)
    monkeypatch.setattr(charger_handback, "person_paused_in_record", lambda _: False)
    monkeypatch.setattr(charger_handback, "build_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(controller_module, "ocpp_target_of", lambda *_: (target, "stored"))
    entry = SimpleNamespace(entry_id="a", data={"charge_control": "switch.test"})
    assert asyncio.run(charger_handback.async_hand_back_charger(adapter.hass, entry)) == []
    current.async_present_a.assert_awaited_once()
    path.async_start.assert_not_awaited()
    current.async_set.assert_not_awaited()
