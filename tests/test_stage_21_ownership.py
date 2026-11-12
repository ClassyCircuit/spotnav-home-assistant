"""Isolated Auto boundary tests with real connector admission and mocked hardware."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.const import MOREK_STATION_ID
from custom_components.spotnav.execution.auto_execution import AutoControlRefused
from custom_components.spotnav.execution.command_admission import CommandAdmission, async_auto_legacy_allowed
from custom_components.spotnav.planning.planner import calculate_plan
from .planning import build_request, fixture_payload, parse_documents
from .test_capped_auto_execution_isolated import make_executor
from .test_planner_price_policy_guard import cap_request


def identity(station=MOREK_STATION_ID, connector=1):
    return {"supported": True, "resolved_id": station, "connector_id": connector,
            "match_count": 1, "ocpp_version": "1.6"}


class Store:
    owner = "morek_schedule"

    async def async_status(self, entry, resolved):
        return {"record_state": "valid", "recorded_owner": self.owner, "armed": False,
                "station_id": MOREK_STATION_ID, "connector_id": 1}


def setup(monkeypatch):
    executor, controller, settings = make_executor(monkeypatch)
    store = Store()
    gate = CommandAdmission(store)
    executor._legacy_admission = lambda: async_auto_legacy_allowed(gate, "test", identity)
    return executor, controller, settings, store


def test_owner_blocks_reconcile_and_pending_but_legacy_still_executes(monkeypatch):
    executor, controller, settings, store = setup(monkeypatch)
    snapshot = SimpleNamespace(proposal=None, state="nothing_to_charge")
    async def run():
        await executor.async_reconcile(settings, snapshot, attempt=executor.attempt)
        assert executor.pending is None
        controller.async_end_superseded_plan.assert_not_awaited()
        store.owner = "legacy"
        await executor.async_reconcile(settings, snapshot, attempt=executor.attempt)
        controller.async_end_superseded_plan.assert_awaited_once()
    asyncio.run(run())


def test_owner_blocks_usable_application_before_install(monkeypatch):
    executor, controller, settings, _ = setup(monkeypatch)
    scenario = fixture_payload()["scenarios"][0]
    request = build_request(scenario["request"], parse_documents(scenario["documents"]))
    proposal = calculate_plan(cap_request(request, [.1, .2], need=1))
    snapshot = SimpleNamespace(proposal=proposal, state="proposal_ready", last_error_code=None,
                               area_id="SE4", price_identity="prices", price_revision=None,
                               departure_at=None, room_limited=False)
    asyncio.run(executor.async_reconcile(settings, snapshot, attempt=executor.attempt))
    controller.async_install.assert_not_called()
    controller.async_end_superseded_plan.assert_not_awaited()


@pytest.mark.parametrize("kind", ["start", "stop", "balancing_resume", "person_resume"])
def test_automatic_turn_denies_all_kinds(monkeypatch, kind):
    executor, _, _, _ = setup(monkeypatch)
    async def run():
        async with executor.automatic_turn(kind) as allowed:
            assert not allowed
    asyncio.run(run())


@pytest.mark.parametrize("method,args", [
    ("async_manual_start", ()), ("async_manual_stop", ()), ("async_manual_cancel", ()),
    ("async_manual_follow", ()), ("async_pause", ()), ("async_resume", ()),
    ("async_manual_action", ("start",)), ("async_manual_action", ("stop",)),
    ("async_manual_action", ("stop", "until_resumed")), ("async_manual_action", ("resume",)),
])
def test_manual_refusal_precedes_preparation(monkeypatch, method, args):
    executor, controller, _, _ = setup(monkeypatch)
    attempt = executor.attempt
    with pytest.raises(AutoControlRefused) as error:
        asyncio.run(getattr(executor, method)(*args))
    assert error.value.code == "legacy_execution_ownership_blocked"
    assert executor.attempt == attempt
    executor._store.async_update.assert_not_called()
    controller.async_start.assert_not_called()
    controller.async_stop.assert_not_called()


def test_queued_work_rechecks_after_auto_lock(monkeypatch):
    executor, controller, settings, store = setup(monkeypatch)
    async def run():
        store.owner = "legacy"
        async with executor._lock:
            task = asyncio.create_task(executor.async_reconcile(
                settings, SimpleNamespace(proposal=None), attempt=executor.attempt))
            await asyncio.sleep(0)
            store.owner = "morek_schedule"
        await task
        controller.async_end_superseded_plan.assert_not_awaited()
    asyncio.run(run())


def test_pending_and_clear_callbacks_are_discarded(monkeypatch):
    executor, controller, _, _ = setup(monkeypatch)
    executor._clear_waiting = executor.attempt
    async def run():
        await executor.async_apply_pending()
        await executor.async_clear_superseded_plan()
        assert executor.pending is None and executor._clear_waiting is None
        controller.async_install.assert_not_called()
        controller.async_end_superseded_plan.assert_not_awaited()
    asyncio.run(run())


def test_legacy_automatic_turn_remains_allowed(monkeypatch):
    executor, _, _, store = setup(monkeypatch)
    store.owner = "legacy"
    async def run():
        async with executor.automatic_turn("start") as allowed:
            assert allowed
    asyncio.run(run())


def test_identity_and_connector_isolation():
    store = Store()
    gate = CommandAdmission(store)
    async def run():
        assert not await async_auto_legacy_allowed(gate, "a", identity)
        assert await async_auto_legacy_allowed(gate, "other", lambda: identity(connector=2))
        assert await async_auto_legacy_allowed(gate, "other", lambda: identity(station="other"))
        assert not await async_auto_legacy_allowed(gate, "a", lambda: {"match_count": 0})
        store.owner = "legacy"
        assert await async_auto_legacy_allowed(gate, "a", identity)
    asyncio.run(run())


def test_automatic_paths_return_not_executed(monkeypatch):
    executor, controller, _, _ = setup(monkeypatch)
    async def run():
        for method, args in (("async_start_on_plug_in", ()), ("async_solar_start", (16,)),
                             ("async_solar_stop", ()), ("async_min_soc_start", (16,)),
                             ("async_min_soc_end", ()), ("async_settle_pause", ())):
            assert not await getattr(executor, method)(*args)
        assert not await executor._end_manual_pause_locked("unplugged")
        controller.async_start = AsyncMock()
        controller.async_start.assert_not_awaited()
    asyncio.run(run())
