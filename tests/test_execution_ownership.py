"""A2.1 metadata is durable, strictly read, and never commands a charger."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.execution import execution_ownership as ownership
from custom_components.spotnav.execution.command_admission import CommandAdmission, classify_morek_identity, physical_connector
from custom_components.spotnav.const import MOREK_STATION_ID


IDENTITY = {"supported": True, "resolved_id": MOREK_STATION_ID, "connector_id": 1,
            "match_count": 1, "ocpp_version": "1.6"}


class FakeStore:
    def __init__(self, hass, version, key, **kwargs):
        self.path = str(hass.root / key)
        self.key = key
        self.saves = 0

    async def async_save(self, data):
        self.saves += 1
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "minor_version": 1, "key": self.key, "data": data}, file)


class FakeHass:
    def __init__(self, root):
        self.root = root
        self.data = {}
        self.services = SimpleNamespace(async_call=AsyncMock())
        self.station = SimpleNamespace(call=AsyncMock())

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


@pytest.fixture
def setup_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ownership, "Store", FakeStore)
    return FakeHass(tmp_path)


def run(awaitable):
    return asyncio.run(awaitable)


def initialize(store, entry_id, identity):
    return run(CommandAdmission(store).async_ensure_initialized(entry_id, lambda: identity))


def test_first_use_is_legacy_persists_and_does_not_touch_other_stores(setup_store):
    hass = setup_store
    auto = hass.root / "spotnav_auto_settings"
    morek = hass.root / "spotnav.morek_schedule.charger"
    auto.write_text('{"pause":"until_resumed"}', encoding="utf-8")
    morek.write_text('{"profile":"retained"}', encoding="utf-8")
    store = ownership.ownership_store(hass)
    missing = run(store.async_status("charger", IDENTITY))
    assert missing["record_state"] == "missing" and missing["recorded_owner"] is None
    assert store._store.saves == 0  # status is read-only
    initialize(store, "charger", IDENTITY)
    status = run(store.async_status("charger", IDENTITY))
    assert status["record_state"] == "valid" and status["recorded_owner"] == "legacy"
    assert (status["station_id"], status["connector_id"]) == (MOREK_STATION_ID, 1)
    assert status["armed"] is status["ready"] is status["schedule_mode_available"] is False
    assert store._store.saves == 1
    reloaded = ownership.ExecutionOwnershipStore(hass)
    assert run(reloaded.async_status("charger", IDENTITY)) == status
    initialize(reloaded, "charger", IDENTITY)
    assert reloaded._store.saves == 0
    assert auto.read_text(encoding="utf-8") == '{"pause":"until_resumed"}'
    assert morek.read_text(encoding="utf-8") == '{"profile":"retained"}'
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_empty_document_does_not_migrate_missing_binding(setup_store):
    path = setup_store.root / ownership.STORAGE_KEY
    original = json.dumps({"version": 1, "data": {"schema_version": 1, "records": {}}})
    path.write_text(original, encoding="utf-8")
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    assert await gate.async_ensure_initialized("charger", lambda: IDENTITY) == "ownership_missing"
    assert (await store.async_status("charger", IDENTITY))["recorded_owner"] is None
    write = AsyncMock()
    result = await gate.async_execute("charger", "legacy_actuator", lambda: IDENTITY, write)
    assert result.reason == "ownership_missing"
    write.assert_not_awaited()
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(("content", "state"), [
    ("{broken", "malformed"),
    ("null", "malformed"),
    (json.dumps({"version": 99, "data": {}}), "unsupported_version"),
    (json.dumps({"version": 1, "data": {"schema_version": 2, "records": {}}}), "unsupported_version"),
    (json.dumps({"version": 1, "data": {"schema_version": 1, "records": {"a": {}}}}), "malformed"),
    (json.dumps({"version": 1, "data": None}), "malformed"),
])
def test_bad_data_is_never_silently_migrated_or_overwritten(setup_store, content, state):
    hass = setup_store
    path = hass.root / ownership.STORAGE_KEY
    path.write_text(content, encoding="utf-8")
    store = ownership.ExecutionOwnershipStore(hass)
    initialize(store, "charger", IDENTITY)
    status = run(store.async_status("charger", IDENTITY))
    assert status["record_state"] == state and status["recorded_owner"] is None
    assert not status["ready"] and not status["armed"]
    assert path.read_text(encoding="utf-8") == content
    assert store._store.saves == 0
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


def test_identity_changes_conflicts_and_aliases(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    unknown = {"supported": False, "resolved_id": None, "connector_id": 1}
    initialize(store, "charger", unknown)
    assert store._store.saves == 0
    gate = CommandAdmission(store)
    run(gate.async_ensure_initialized("charger", lambda: {**IDENTITY, "configured_id": "old-alias"}))
    status = run(store.async_status("charger", {**IDENTITY, "configured_id": "new-alias"}))
    assert status["record_state"] == "valid"
    for identity in ({**IDENTITY, "resolved_id": "other"}, {**IDENTITY, "connector_id": 2}):
        status = run(store.async_status("charger", identity))
        assert status["record_state"] == "identity_mismatch" and status["recorded_owner"] is None
    assert run(store.async_status("charger", unknown))["record_state"] == "identity_unresolved"
    assert run(store.async_status("other", IDENTITY))["record_state"] == "conflict"
    assert run(gate.async_ensure_initialized("other", lambda: IDENTITY)) == "ownership_conflict"
    for entry_id in ("charger", "other"):
        assert run(store.async_status(entry_id, IDENTITY))["record_state"] == "conflict"
    assert run(ownership.ExecutionOwnershipStore(setup_store).async_status("charger", IDENTITY))["record_state"] == "valid"


def test_future_mode_in_stored_metadata_is_never_armed(setup_store):
    record = {"station_id": MOREK_STATION_ID, "connector_id": 1, "owner": "morek_schedule"}
    path = setup_store.root / ownership.STORAGE_KEY
    path.write_text(json.dumps({"version": 1, "data": {"schema_version": 1, "records": {"c": record}}}),
                    encoding="utf-8")
    status = run(ownership.ExecutionOwnershipStore(setup_store).async_status("c", IDENTITY))
    assert status["recorded_owner"] == "morek_schedule"
    assert not status["armed"] and not status["ready"] and not status["schedule_mode_available"]
    assert set(status["blockers"]) == {"command_isolation_not_implemented", "safety_unverified", "site_regulation_conflict_unresolved",
                                       "transaction_authorization_unverified"}


def test_failed_save_and_concurrent_first_use(setup_store):
    async def exercise():
        store = ownership.ExecutionOwnershipStore(setup_store)
        gate = CommandAdmission(store)
        assert set(await asyncio.gather(gate.async_ensure_initialized("a", lambda: IDENTITY),
                                        gate.async_ensure_initialized("b", lambda: IDENTITY))) == {
                                            "initialized", "ownership_conflict"}
        assert (await store.async_status("a", IDENTITY))["record_state"] == "conflict"
        assert (await ownership.ExecutionOwnershipStore(setup_store).async_status("b", IDENTITY))["record_state"] == "conflict"

        retry_root = setup_store.root / "retry"
        retry_root.mkdir()
        failing = ownership.ExecutionOwnershipStore(FakeHass(retry_root))
        failing._store.async_save = AsyncMock(side_effect=OSError("failed"))
        assert await CommandAdmission(failing).async_ensure_initialized(
            "c", lambda: IDENTITY) == "save_uncertain"
        status = await failing.async_status("c", IDENTITY)
        assert status["record_state"] == "save_failed" and status["recorded_owner"] is None
        assert not status["ready"] and not status["armed"]
        setup_store.services.async_call.assert_not_awaited()
        setup_store.station.call.assert_not_awaited()

    run(exercise())


def test_identity_classification():
    assert classify_morek_identity(IDENTITY) == "supported_morek"
    assert classify_morek_identity({**IDENTITY, "supported": False, "resolved_id": "other"}) == "non_target"
    assert classify_morek_identity({**IDENTITY, "supported": False, "match_count": 2}) == "unresolved"
    assert classify_morek_identity({**IDENTITY, "resolved_id": "other", "supported": False,
                                    "reason": "ambiguous_station"}) == "unresolved"
    assert classify_morek_identity({**IDENTITY, "supported": False, "resolved_id": None}) == "unresolved"
    assert classify_morek_identity({**IDENTITY, "connector_id": None}) == "unresolved"


@pytest.mark.asyncio
async def test_offline_reconnect_and_reload_without_status_writes(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    current = [{"supported": False, "resolved_id": None, "connector_id": 1}]
    assert await gate.async_ensure_initialized("c", lambda: current[0]) == "identity_unresolved"
    assert (await store.async_status("c", current[0]))["record_state"] == "missing"
    assert store._store.saves == 0
    current[0] = IDENTITY
    assert await gate.async_ensure_initialized("c", lambda: current[0]) == "initialized"
    assert await gate.async_ensure_initialized("c", lambda: current[0]) == "already_initialized"
    assert store._store.saves == 1
    assert (await ownership.ExecutionOwnershipStore(setup_store).async_status("c", IDENTITY))["record_state"] == "valid"
    setup_store.services.async_call.assert_not_awaited()
    setup_store.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_changes_while_waiting_and_entry_never_rebound(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    current = [IDENTITY]
    lock = gate._lock_for(physical_connector(IDENTITY))
    await lock.acquire()
    task = asyncio.create_task(gate.async_ensure_initialized("c", lambda: current[0]))
    await asyncio.sleep(0)
    current[0] = {**IDENTITY, "connector_id": 2}
    lock.release()
    assert await task == "identity_changed"
    assert store._store.saves == 0
    current[0] = IDENTITY
    assert await gate.async_ensure_initialized("c", lambda: current[0]) == "initialized"
    current[0] = {**IDENTITY, "connector_id": 2}
    assert await gate.async_ensure_initialized("c", lambda: current[0]) == "identity_non_target"
    assert store._store.saves == 1


@pytest.mark.asyncio
async def test_save_failure_retry_and_silent_failure_are_conservative(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    save = store._store.async_save
    store._store.async_save = AsyncMock(side_effect=OSError("failed"))
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "save_uncertain"
    assert (await store.async_status("c", IDENTITY))["record_state"] == "save_failed"
    store._store.async_save = AsyncMock()  # HA Store can swallow a write error
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "save_uncertain"
    assert (await store.async_status("c", IDENTITY))["record_state"] == "save_failed"
    store._store.async_save = save
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "initialized"
    assert (await store.async_status("c", IDENTITY))["record_state"] == "valid"


@pytest.mark.asyncio
async def test_save_error_after_write_is_unknown_until_reread(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    save = store._store.async_save

    async def write_then_fail(data):
        await save(data)
        raise OSError("response lost")

    store._store.async_save = write_then_fail
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "save_uncertain"
    assert (await store.async_status("c", IDENTITY))["record_state"] == "save_failed"
    store._store.async_save = AsyncMock()
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "already_initialized"
    store._store.async_save.assert_not_awaited()
    assert (await store.async_status("c", IDENTITY))["record_state"] == "valid"


@pytest.mark.asyncio
async def test_cancelled_save_blocks_unsafe_retry(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    entered = asyncio.Event()
    blocker = asyncio.Event()

    async def save(_data):
        entered.set()
        await blocker.wait()

    store._store.async_save = save
    task = asyncio.create_task(gate.async_ensure_initialized("c", lambda: IDENTITY))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await store.async_status("c", IDENTITY))["record_state"] == "save_failed"
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "save_uncertain"


@pytest.mark.asyncio
async def test_morek_owned_record_and_existing_conflict_are_never_overwritten(setup_store):
    path = setup_store.root / ownership.STORAGE_KEY
    record = {"station_id": MOREK_STATION_ID, "connector_id": 1, "owner": "morek_schedule"}
    original = json.dumps({"version": 1, "data": {"schema_version": 1, "records": {"a": record}}})
    path.write_text(original, encoding="utf-8")
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    assert await gate.async_ensure_initialized("a", lambda: IDENTITY) == "already_initialized"
    assert await gate.async_ensure_initialized("b", lambda: IDENTITY) == "ownership_conflict"
    assert (await store.async_status("a", IDENTITY))["record_state"] == "conflict"
    assert path.read_text(encoding="utf-8") == original
    assert store._store.saves == 0


@pytest.mark.asyncio
async def test_different_connectors_do_not_share_connector_lock(setup_store):
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    first = physical_connector({**IDENTITY, "connector_id": 2})
    lock = gate._lock_for(first)
    await lock.acquire()
    entered = asyncio.Event()

    async def wait_for_other():
        async with lock:
            entered.set()

    task = asyncio.create_task(wait_for_other())
    await asyncio.sleep(0)
    assert await gate.async_ensure_initialized("b", lambda: IDENTITY) == "initialized"
    assert not task.done()
    lock.release()
    await task
    assert entered.is_set()


@pytest.mark.asyncio
async def test_preexisting_conflicting_document_is_not_modified(setup_store):
    path = setup_store.root / ownership.STORAGE_KEY
    item = {"station_id": MOREK_STATION_ID, "connector_id": 1, "owner": "legacy"}
    original = json.dumps({"version": 1, "data": {"schema_version": 1, "records": {"a": item, "b": item}}})
    path.write_text(original, encoding="utf-8")
    store = ownership.ExecutionOwnershipStore(setup_store)
    gate = CommandAdmission(store)
    assert await gate.async_ensure_initialized("c", lambda: IDENTITY) == "ownership_conflict"
    assert path.read_text(encoding="utf-8") == original
    assert store._store.saves == 0
