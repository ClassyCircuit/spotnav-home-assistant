"""Durable unresolved evidence is exact-attempt data, never an actuator decision."""

import asyncio
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from homeassistant.core import HomeAssistant

from custom_components.spotnav.execution import unresolved_start as evidence


class FakeStore:
    def __init__(self, hass, version, key, **kwargs):
        self.path = str(hass.root / key)
        self.saves = 0

    async def async_save(self, data):
        self.saves += 1
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "minor_version": 1, "data": data}, file)


class FakeHass:
    def __init__(self, root):
        self.root = root
        self.data = {}
        self.services = SimpleNamespace(async_call=AsyncMock())
        self.station = SimpleNamespace(call=AsyncMock())

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


@pytest.fixture
def hass_store(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "Store", FakeStore)
    return FakeHass(tmp_path)


def record(**changes):
    values = {"attempt_id": str(uuid4()), "station_id": "station", "connector_id": 1,
              "session_id": str(uuid4()), "origin": "plan", "prospective_owner": "plan"}
    return evidence.UnresolvedStart(**(values | changes))


def update_for(item, **changes):
    values = {"attempt_id": item.attempt_id, "station_id": item.station_id, "connector_id": item.connector_id,
              "session_id": item.session_id, "expected_revision": item.revision, "command_evidence": "dispatched"}
    return values | changes


@pytest.mark.asyncio
async def test_persist_reload_restart_and_other_stores_untouched(hass_store):
    paths = [hass_store.root / "spotnav_execution_ownership", hass_store.root / "spotnav.charger",
             hass_store.root / "spotnav_auto_settings"]
    for path in paths:
        path.write_text('{"existing":true}', encoding="utf-8")
    store = evidence.unresolved_start_store(hass_store)
    assert evidence.unresolved_start_store(hass_store) is store
    assert (await store.async_status()).state == "missing" and store._store.saves == 0
    attempt = record()
    assert await store.async_add(attempt) == "saved"
    assert (await store.async_status()).records == (attempt,)
    # A new store models process reload. Restart is not a verified unplug.
    reloaded = evidence.UnresolvedStartStore(hass_store)
    assert await reloaded.async_status() == evidence.EvidenceSnapshot("valid", (attempt,))
    assert all(path.read_text(encoding="utf-8") == '{"existing":true}' for path in paths)
    hass_store.services.async_call.assert_not_awaited()
    hass_store.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_independent_attempts_exact_update_and_stale_rejection(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    first, second = record(), record()
    assert await store.async_add(first) == "saved"
    assert await store.async_add(second) == "saved"
    assert await store.async_add(first) == "duplicate_attempt"
    assert await store.async_add(replace(first, origin="person")) == "duplicate_attempt"
    for change in ({"station_id": "other"}, {"connector_id": 2}, {"session_id": second.session_id}):
        assert await store.async_refine(**update_for(first, **change)) == "identity_mismatch"
    assert await store.async_refine(**update_for(first, attempt_id=str(uuid4()))) == "unknown_attempt"
    assert await store.async_refine(**update_for(first, expected_revision=1)) == "stale_update"
    assert await store.async_refine(**update_for(first)) == "saved"
    assert await store.async_refine(**update_for(first)) == "stale_update"
    snapshot = await store.async_status()
    assert snapshot.records == (replace(first, command_evidence="dispatched", revision=1), second)
    # The record remains unresolved even after command evidence is refined.
    assert (await evidence.UnresolvedStartStore(hass_store).async_status()).records == snapshot.records
    assert await store.async_refine(**update_for(second, command_evidence="not_dispatched")) == "saved"
    hass_store.services.async_call.assert_not_awaited()
    hass_store.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_late_results_cannot_overwrite_one_another(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    attempt = record()
    assert await store.async_add(attempt) == "saved"
    results = await asyncio.gather(
        store.async_refine(**update_for(attempt, command_evidence="dispatched")),
        store.async_refine(**update_for(attempt, command_evidence="not_dispatched")),
    )
    assert sorted(results) == ["saved", "stale_update"]
    assert (await store.async_status()).records[0].revision == 1


@pytest.mark.parametrize(("payload", "state"), [
    ("{bad", "malformed"),
    ("null", "malformed"),
    ('{"version":1,"version":1,"data":{}}', "malformed"),
    (json.dumps({"version": 2, "data": {}}), "unsupported_version"),
    (json.dumps({"version": 1, "data": {"schema_version": 2, "records": []}}), "unsupported_version"),
    (json.dumps({"version": 1, "data": {"schema_version": 1, "records": [{}]}}), "malformed"),
])
@pytest.mark.asyncio
async def test_untrusted_data_is_visible_and_unchanged(hass_store, payload, state):
    path = hass_store.root / evidence.STORAGE_KEY
    path.write_text(payload, encoding="utf-8")
    store = evidence.UnresolvedStartStore(hass_store)
    assert (await store.async_status()).state == state
    assert await store.async_add(record()) == state
    assert path.read_text(encoding="utf-8") == payload
    assert store._store.saves == 0


@pytest.mark.asyncio
async def test_duplicate_attempts_in_stored_document_are_conflict(hass_store):
    item = asdict(record())
    conflict = {**item, "station_id": "another"}
    payload = json.dumps({"version": 1, "data": {"schema_version": 1, "records": [item, conflict]}})
    path = hass_store.root / evidence.STORAGE_KEY
    path.write_text(payload, encoding="utf-8")
    store = evidence.UnresolvedStartStore(hass_store)
    assert (await store.async_status()).state == "conflict"
    assert await store.async_add(record()) == "conflict"
    assert path.read_text(encoding="utf-8") == payload


@pytest.mark.asyncio
async def test_failed_or_silent_save_is_uncertain_and_blocks_further_mutation(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    first, second = record(), record()
    assert await store.async_add(first) == "saved"
    store._store.async_save = AsyncMock(side_effect=OSError("write unknown"))
    assert await store.async_add(second) == "save_uncertain"
    assert await store.async_status() == evidence.EvidenceSnapshot("save_uncertain", (first,), (first, second))
    assert await store.async_refine(**update_for(first)) == "save_uncertain"
    # A silently unsuccessful save is also detected by disk verification.
    fresh = evidence.UnresolvedStartStore(hass_store)
    fresh._store.async_save = AsyncMock()
    assert await fresh.async_add(second) == "save_uncertain"
    assert (await fresh.async_status()).state == "save_uncertain"
    assert (await evidence.UnresolvedStartStore(hass_store).async_status()).records == (first,)


@pytest.mark.asyncio
async def test_cancelled_save_never_claims_success_or_retries(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    entered, never = asyncio.Event(), asyncio.Event()

    async def blocked(_data):
        entered.set()
        await never.wait()

    store._store.async_save = blocked
    attempt = record()
    task = asyncio.create_task(store.async_add(attempt))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = await store.async_status()
    assert snapshot.state == "save_uncertain" and snapshot.pending_records == (attempt,)
    assert await store.async_add(record()) == "save_uncertain"
    hass_store.services.async_call.assert_not_awaited()
    hass_store.station.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_response_lost_after_write_stays_unresolved(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    attempt = record()
    save = store._store.async_save

    async def save_then_raise(data):
        await save(data)
        raise OSError("response lost")

    store._store.async_save = save_then_raise
    assert await store.async_add(attempt) == "save_uncertain"
    assert (await store.async_status()).pending_records == (attempt,)
    # A later process may see a durable record, but it is still unresolved.
    restored = await evidence.UnresolvedStartStore(hass_store).async_status()
    assert restored == evidence.EvidenceSnapshot("valid", (attempt,))
    assert restored.records[0].command_evidence == "unknown"


@pytest.mark.asyncio
async def test_invalid_records_and_updates_are_refused(hass_store):
    store = evidence.UnresolvedStartStore(hass_store)
    first = record()
    for invalid in (replace(first, attempt_id="bad"), replace(first, session_id="bad"),
                    replace(first, connector_id=True), replace(first, command_evidence="dispatched"),
                    replace(first, revision=1)):
        assert await store.async_add(invalid) == "invalid_record"
    assert await store.async_refine(**update_for(first, command_evidence="unknown")) == "invalid_update"
    assert (await store.async_status()).state == "missing"
    assert store._store.saves == 0


@pytest.mark.asyncio
async def test_real_ha_store_round_trip(hass: HomeAssistant):
    """HA's real Store envelope and atomic write can be read after reload."""
    store = evidence.UnresolvedStartStore(hass)
    attempt = record()
    assert await store.async_add(attempt) == "saved"
    assert await evidence.UnresolvedStartStore(hass).async_status() == evidence.EvidenceSnapshot("valid", (attempt,))
