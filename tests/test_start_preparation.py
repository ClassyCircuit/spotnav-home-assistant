"""Characterize real controller start preparation and conservative attempt evidence."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.spotnav.const import CONF_CHARGE_CONTROL, CURRENT_CONTROL_CHANGE_CONFIGURATION
from custom_components.spotnav.execution.controller import ChargingController, ChargingPlan
from custom_components.spotnav.core.events import TRIGGER_PLUG_IN


async def make_controller(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    hass.states.async_set("switch.start_test", "off")
    controller = ChargingController(hass, "start_test", {CONF_CHARGE_CONTROL: "switch.start_test"})
    await controller.async_initialize()
    # Exercise the current-preparation branch without contacting an OCPP service.
    controller.current_control = CURRENT_CONTROL_CHANGE_CONFIGURATION
    order = []
    reservations = []
    controller.set_start_cap(lambda: 16, reserve=reservations.append)

    async def phase():
        assert controller._lock.locked()  # noqa: SLF001
        order.append("phase")

    async def current(*args, **kwargs):
        assert controller._lock.locked() and controller._assign_lock.locked()  # noqa: SLF001
        order.append("current")
        return "assigned"

    async def start(amps):
        assert controller._lock.locked() and not controller._assign_lock.locked()  # noqa: SLF001
        order.append("start")
        return True

    monkeypatch.setattr(controller, "_restore_three_phases_locked", phase)
    monkeypatch.setattr(controller, "_assign_current_locked", current)
    monkeypatch.setattr(controller.adapter, "async_start", start)
    return controller, order, reservations


async def test_successful_start_order_and_lock_boundaries(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    controller, order, reservations = await make_controller(hass, monkeypatch)
    try:
        assert await controller.async_start(10) is True
        assert order == ["phase", "current", "start"]
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert attempt.phase_preparation_attempted and attempt.current_preparation_attempted
        assert attempt.start_dispatch == "executed"
        assert attempt.reservation_requested and not attempt.reservation_release_requested
        assert reservations == [10]
    finally:
        await controller.async_shutdown()


async def test_adapter_not_executed_after_possible_preparation(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    controller, order, reservations = await make_controller(hass, monkeypatch)
    monkeypatch.setattr(controller.adapter, "async_start", AsyncMock(return_value=False))
    try:
        assert await controller.async_start(10) is False
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert order == ["phase", "current"]
        assert attempt.current_preparation_attempted and attempt.start_dispatch == "not_executed"
        assert attempt.reservation_requested and attempt.reservation_release_requested
        assert reservations == [10, None]
        assert controller._start_sent_at is None and not controller._start_write_pending  # noqa: SLF001
    finally:
        await controller.async_shutdown()


async def test_preparation_failure_frees_reservation_but_may_have_written(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    controller, order, reservations = await make_controller(hass, monkeypatch)
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(controller.adapter, "async_start", start)
    monkeypatch.setattr(controller, "_async_save", AsyncMock(side_effect=OSError("disk error")))
    try:
        with pytest.raises(OSError):
            await controller.async_start(10)
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert order == ["phase", "current"]
        assert attempt.current_preparation_attempted and attempt.start_dispatch == "not_attempted"
        assert attempt.reservation_requested and attempt.reservation_release_requested
        assert reservations == [10, None]
        assert not controller._start_in_flight  # noqa: SLF001
        start.assert_not_awaited()
    finally:
        await controller.async_shutdown()


async def test_failed_read_only_preparation_can_report_no_physical_attempt(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    controller, _, reservations = await make_controller(hass, monkeypatch)
    monkeypatch.setattr(ChargingController, "phase_switching_option", property(lambda self: True))
    def invalid(_amps):
        raise ValueError("invalid")

    monkeypatch.setattr(controller, "_validate_amps", invalid)
    start = AsyncMock()
    monkeypatch.setattr(controller.adapter, "async_start", start)
    try:
        with pytest.raises(ValueError):
            await controller.async_start(10, cause="solar")
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert not attempt.phase_preparation_attempted and not attempt.current_preparation_attempted
        assert attempt.start_dispatch == "not_attempted" and not attempt.reservation_requested
        assert reservations == []
        start.assert_not_awaited()
    finally:
        await controller.async_shutdown()


async def test_plug_in_start_keeps_existing_retry_for_unexecuted_start(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    controller, _, _ = await make_controller(hass, monkeypatch)
    now = dt_util.utcnow()
    controller.plan = ChargingPlan((now - timedelta(minutes=1)).isoformat(),
                                   (now + timedelta(hours=1)).isoformat(), 10)
    monkeypatch.setattr(controller.adapter, "async_start", AsyncMock(return_value=False))
    try:
        async with controller._lock:  # noqa: SLF001
            assert not await controller._plug_in_start_send({}, TRIGGER_PLUG_IN)  # noqa: SLF001
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert attempt.retry_already_armed and attempt.start_dispatch == "not_executed"
        assert controller.window_start_retry["active"] is True
        assert controller._start_sent_at is None  # noqa: SLF001
    finally:
        await controller.async_shutdown()


@pytest.mark.parametrize("stage", ["phase", "start"])
@pytest.mark.parametrize("failure", ["exception", "cancel"])
async def test_interrupted_preparation_and_dispatch_are_distinguished(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, stage: str, failure: str
):
    controller, order, reservations = await make_controller(hass, monkeypatch)
    entered = asyncio.Event()
    never = asyncio.Event()

    async def interrupt(*args):
        entered.set()
        if failure == "exception":
            raise OSError("unknown outcome")
        await never.wait()

    monkeypatch.setattr(controller if stage == "phase" else controller.adapter,
                        "_restore_three_phases_locked" if stage == "phase" else "async_start", interrupt)
    try:
        task = asyncio.create_task(controller.async_start(10))
        await entered.wait()
        if failure == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else OSError):
            await task
        attempt = controller._last_start_attempt  # noqa: SLF001
        assert attempt.start_dispatch == ("not_attempted" if stage == "phase" else "unknown")
        assert attempt.phase_preparation_attempted
        assert attempt.current_preparation_attempted is (stage == "start")
        assert not controller._start_in_flight  # noqa: SLF001
        if stage == "start":
            assert reservations == [10, None] and attempt.reservation_release_requested
        else:
            assert reservations == [] and not attempt.reservation_requested
    finally:
        await controller.async_shutdown()
