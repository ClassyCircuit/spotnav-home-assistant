"""Unwired admission is connector-scoped, conservative and cancellation-safe."""

import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.execution.command_admission import CommandAdmission, physical_connector
from custom_components.spotnav.execution import execution_ownership
from custom_components.spotnav.const import MOREK_STATION_ID


def identity(station=MOREK_STATION_ID, connector=1, alias="one"):
    return {"supported": True, "resolved_id": station, "connector_id": connector, "configured_id": alias,
            "match_count": 1, "ocpp_version": "1.6"}


def status(station=MOREK_STATION_ID, connector=1, owner="legacy", state="valid"):
    return {"record_state": state, "recorded_owner": owner, "station_id": station,
            "connector_id": connector, "armed": False, "ready": False}


class StatusStore:
    def __init__(self):
        self.value = status()

    async def async_status(self, entry, resolved):
        return dict(self.value)


@pytest.mark.asyncio
async def test_aliases_serialize_and_different_connectors_run_independently():
    class Store:
        async def async_status(self, entry, resolved):
            return status(resolved["resolved_id"], resolved["connector_id"])

    gate = CommandAdmission(Store())
    entered = asyncio.Event()
    release = asyncio.Event()
    second_entered = asyncio.Event()
    independent_entered = asyncio.Event()

    async def first():
        entered.set()
        await release.wait()
        return "first"

    async def second():
        second_entered.set()

    async def independent():
        independent_entered.set()

    one = asyncio.create_task(gate.async_execute("one", "legacy_actuator", lambda: identity(alias="a"), first))
    await entered.wait()
    two = asyncio.create_task(gate.async_execute("two", "legacy_actuator", lambda: identity(alias="b"), second))
    three = asyncio.create_task(gate.async_execute("three", "legacy_actuator", lambda: identity(connector=2), independent))
    await independent_entered.wait()
    assert not second_entered.is_set()
    assert (await three).allowed
    release.set()
    assert (await one).value == "first"
    assert (await two).allowed and second_entered.is_set()


@pytest.mark.asyncio
async def test_queued_work_rechecks_ownership_and_identity_inside_lock():
    store = StatusStore()
    gate = CommandAdmission(store)
    entered, release = asyncio.Event(), asyncio.Event()
    write = AsyncMock()

    async def first():
        entered.set()
        await release.wait()

    active = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, first))
    await entered.wait()
    queued = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, write))
    await asyncio.sleep(0)  # put the waiter on the held connector lock
    store.value = status(owner="morek_schedule")
    release.set()
    assert (await active).allowed
    answer = await queued
    assert not answer.allowed and answer.reason == "legacy_not_owner"
    write.assert_not_awaited()

    changed = iter((identity(), identity(station="another")))
    result = await gate.async_execute("a", "legacy_actuator", lambda: next(changed), write)
    assert result.reason == "identity_changed"
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "malformed", "unsupported_version", "save_failed", "conflict",
                                   "identity_unresolved", "identity_mismatch", "unknown"])
async def test_ambiguous_state_never_invokes_write(state):
    store = StatusStore()
    store.value = status(state=state)
    gate = CommandAdmission(store)
    write = AsyncMock()
    result = await gate.async_execute("a", "legacy_actuator", identity, write)
    assert not result.allowed and result.reason.startswith("ownership_")
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_metadata_does_not_arm_and_reads_do_not_need_write_admission():
    store = StatusStore()
    gate = CommandAdmission(store)
    write, read = AsyncMock(), AsyncMock(return_value="readback")
    for owner in ("legacy", "morek_schedule"):
        store.value = status(owner=owner)
        result = await gate.async_execute("a", "owned_profile", identity, write)
        assert not result.allowed and result.reason == "schedule_mode_unarmed"
    store.value = status(state="malformed")
    result = await gate.async_execute("a", "read_only", lambda: None, read)
    assert result.allowed and result.reason == "allowed_read_only" and result.value == "readback"
    write.assert_not_awaited()
    read.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolved_read_shares_connector_lock_without_ownership_admission():
    store = StatusStore()
    gate = CommandAdmission(store)
    entered, release, read_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held_write():
        entered.set()
        await release.wait()

    async def read():
        read_entered.set()
        return "readback"

    writer = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, held_write))
    await entered.wait()
    store.value = status(state="malformed")
    reader = asyncio.create_task(gate.async_execute("a", "read_only", identity, read))
    await asyncio.sleep(0)
    assert not read_entered.is_set()
    release.set()
    assert (await writer).allowed
    assert (await reader).value == "readback"


@pytest.mark.asyncio
async def test_cancellation_exceptions_and_generation_release_connector():
    gate = CommandAdmission(StatusStore())
    connector = physical_connector(identity())
    token = gate.generation(connector)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked():
        entered.set()
        await release.wait()

    task = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, blocked))
    await entered.wait()
    waiter = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, AsyncMock()))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    failing = AsyncMock(side_effect=RuntimeError("write error"))
    with pytest.raises(RuntimeError):
        await gate.async_execute("a", "legacy_actuator", identity, failing)
    await gate.async_invalidate(connector)
    write = AsyncMock()
    stale = await gate.async_execute("a", "legacy_actuator", identity, write, expected_generation=token)
    assert not stale.allowed and stale.reason == "stale_generation"
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).allowed
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_quiesce_drains_inflight_and_refuses_queued_and_new_work():
    gate = CommandAdmission(StatusStore())
    connector = physical_connector(identity())
    entered, release = asyncio.Event(), asyncio.Event()
    queued_write = AsyncMock()

    async def dispatched():
        entered.set()
        await release.wait()

    active = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, dispatched))
    await entered.wait()
    queued = asyncio.create_task(gate.async_execute("a", "legacy_actuator", identity, queued_write))
    await asyncio.sleep(0)
    drain = asyncio.create_task(gate.async_quiesce_for_reload(connector))
    await asyncio.sleep(0)
    assert not drain.done()  # An already dispatched operation cannot be recalled.
    release.set()
    assert (await active).allowed
    assert (await queued).reason == "connector_quiescing"
    assert (await drain).revision == 1
    assert (await gate.async_execute("a", "legacy_actuator", identity, queued_write)).reason == "connector_quiescing"
    queued_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_quiesce_remains_closed_without_affecting_other_connector():
    gate = CommandAdmission(StatusStore())
    connector = physical_connector(identity())
    lock = gate._lock_for(connector)
    await lock.acquire()
    task = asyncio.create_task(gate.async_quiesce_for_reload(connector))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    lock.release()
    write = AsyncMock()
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "connector_quiescing"
    # A read remains available and is not classified as an actuator.
    assert (await gate.async_execute("a", "read_only", identity, write)).allowed
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_store_missing_entry_cannot_bypass_other_physical_record(tmp_path, monkeypatch):
    class FakeStore:
        def __init__(self, hass, version, key, **kwargs):
            self.path = str(tmp_path / key)

        async def async_save(self, data):
            Path(self.path).write_text(json.dumps({"version": 1, "data": data}), encoding="utf-8")

    async def run_job(fn, *args):
        return fn(*args)

    monkeypatch.setattr(execution_ownership, "Store", FakeStore)
    store = execution_ownership.ExecutionOwnershipStore(SimpleNamespace(async_add_executor_job=run_job))
    gate = CommandAdmission(store)
    await gate.async_ensure_initialized("original", lambda: identity(alias="first"))
    write = AsyncMock()
    result = await gate.async_execute("new-entry", "legacy_actuator", lambda: identity(alias="second"), write)
    assert not result.allowed and result.reason == "ownership_conflict"
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_and_status_exceptions_fail_closed():
    store = StatusStore()
    gate = CommandAdmission(store)
    write = AsyncMock()
    assert (await gate.async_execute("a", "legacy_actuator", lambda: {}, write)).reason == "identity_unresolved"
    store.async_status = AsyncMock(side_effect=RuntimeError("unavailable"))
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "ownership_unavailable"
    store.async_status = AsyncMock(return_value=status(station="wrong"))
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "ownership_identity_mismatch"
    store.async_status = AsyncMock(return_value={**status(), "armed": True})
    assert (await gate.async_execute("a", "legacy_actuator", identity, write)).reason == "ownership_inconsistent"
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_rechecked_after_awaited_ownership_read():
    current = [identity()]

    class ChangingStore:
        async def async_status(self, entry, resolved):
            current[0] = identity(station="other")
            return status()

    write = AsyncMock()
    result = await CommandAdmission(ChangingStore()).async_execute(
        "a", "legacy_actuator", lambda: current[0], write)
    assert result.reason == "identity_changed" and not result.allowed
    write.assert_not_awaited()


def test_admission_is_reused_at_shared_boundaries_not_profile_writer():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "spotnav"
    imports = set()
    for path in root.rglob("*.py"):
        if path.name == "command_admission.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "command_admission" in node.module:
                imports.add(path.relative_to(root).as_posix())
    assert imports == {"__init__.py", "execution/charger_handback.py", "execution/chargers/adapter.py",
                       "execution/morek_worker.py"}
