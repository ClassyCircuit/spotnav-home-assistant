"""A2.1 metadata is durable, strictly read, and never commands a charger."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.execution import execution_ownership as ownership


IDENTITY = {"supported": True, "resolved_id": "physical-station", "connector_id": 1}


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


def test_first_use_is_legacy_persists_and_does_not_touch_other_stores(setup_store):
    hass = setup_store
    auto = hass.root / "spotnav_auto_settings"
    morek = hass.root / "spotnav.morek_schedule.charger"
    auto.write_text('{"pause":"until_resumed"}', encoding="utf-8")
    morek.write_text('{"profile":"retained"}', encoding="utf-8")
    store = ownership.ownership_store(hass)
    missing = run(store.async_status("charger", IDENTITY))
    assert missing["record_state"] == "missing" and missing["recorded_owner"] == "legacy"
    assert store._store.saves == 0  # status is read-only
    run(store.async_initialize("charger", IDENTITY))
    status = run(store.async_status("charger", IDENTITY))
    assert status["record_state"] == "valid" and status["recorded_owner"] == "legacy"
    assert (status["station_id"], status["connector_id"]) == ("physical-station", 1)
    assert status["armed"] is status["ready"] is status["schedule_mode_available"] is False
    assert store._store.saves == 1
    reloaded = ownership.ExecutionOwnershipStore(hass)
    assert run(reloaded.async_status("charger", IDENTITY)) == status
    run(reloaded.async_initialize("charger", IDENTITY))
    assert reloaded._store.saves == 0
    assert auto.read_text(encoding="utf-8") == '{"pause":"until_resumed"}'
    assert morek.read_text(encoding="utf-8") == '{"profile":"retained"}'
    hass.services.async_call.assert_not_awaited()
    hass.station.call.assert_not_awaited()


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
    run(store.async_initialize("charger", IDENTITY))
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
    run(store.async_initialize("charger", unknown))
    assert store._store.saves == 0
    run(store.async_initialize("charger", {**IDENTITY, "configured_id": "old-alias"}))
    status = run(store.async_status("charger", {**IDENTITY, "configured_id": "new-alias"}))
    assert status["record_state"] == "valid"
    for identity in ({**IDENTITY, "resolved_id": "other"}, {**IDENTITY, "connector_id": 2}):
        status = run(store.async_status("charger", identity))
        assert status["record_state"] == "identity_mismatch" and status["recorded_owner"] is None
    assert run(store.async_status("charger", unknown))["record_state"] == "identity_unresolved"
    assert run(store.async_status("other", IDENTITY))["record_state"] == "conflict"
    run(store.async_initialize("other", IDENTITY))
    for entry_id in ("charger", "other"):
        assert run(store.async_status(entry_id, IDENTITY))["record_state"] == "conflict"
    assert run(ownership.ExecutionOwnershipStore(setup_store).async_status("charger", IDENTITY))["record_state"] == "conflict"


def test_future_mode_in_stored_metadata_is_never_armed(setup_store):
    record = {"station_id": "physical-station", "connector_id": 1, "owner": "morek_schedule"}
    path = setup_store.root / ownership.STORAGE_KEY
    path.write_text(json.dumps({"version": 1, "data": {"schema_version": 1, "records": {"c": record}}}),
                    encoding="utf-8")
    status = run(ownership.ExecutionOwnershipStore(setup_store).async_status("c", IDENTITY))
    assert status["recorded_owner"] == "morek_schedule"
    assert not status["armed"] and not status["ready"] and not status["schedule_mode_available"]
    assert set(status["blockers"]) == {"command_isolation_not_implemented", "safety_unverified",
                                       "transaction_authorization_unverified"}


def test_failed_save_and_concurrent_first_use(setup_store):
    async def exercise():
        store = ownership.ExecutionOwnershipStore(setup_store)
        await asyncio.gather(store.async_initialize("a", IDENTITY), store.async_initialize("b", IDENTITY))
        assert (await store.async_status("a", IDENTITY))["record_state"] == "conflict"
        assert (await ownership.ExecutionOwnershipStore(setup_store).async_status("b", IDENTITY))["record_state"] == "conflict"

        failing = ownership.ExecutionOwnershipStore(setup_store)
        failing._store.async_save = AsyncMock(side_effect=OSError("failed"))
        await failing.async_initialize("c", {**IDENTITY, "connector_id": 2})
        status = await failing.async_status("c", {**IDENTITY, "connector_id": 2})
        assert status["record_state"] == "save_failed" and status["recorded_owner"] is None
        assert not status["ready"] and not status["armed"]
        setup_store.services.async_call.assert_not_awaited()
        setup_store.station.call.assert_not_awaited()

    run(exercise())
