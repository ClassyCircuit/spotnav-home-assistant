"""Startup and control-availability retry use the same metadata-only protocol."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import custom_components.spotnav as integration
from custom_components.spotnav.execution.command_admission import CommandAdmission
from custom_components.spotnav.execution import execution_ownership
from custom_components.spotnav.const import MOREK_STATION_ID


@pytest.mark.asyncio
async def test_offline_startup_then_control_availability(tmp_path, monkeypatch):
    import json

    class Store:
        def __init__(self, hass, version, key, **kwargs):
            self.path = str(tmp_path / key)

        async def async_save(self, data):
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump({"version": 1, "data": data}, file)

    async def run_job(fn, *args):
        return fn(*args)

    calls = []
    tasks = []
    def unsub():
        return None
    def track(hass, entities, cb):
        calls.append((entities, cb))
        return unsub

    def create_task(hass, coro, name):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(execution_ownership, "Store", Store)
    hass = SimpleNamespace(async_add_executor_job=run_job, services=SimpleNamespace(async_call=AsyncMock()))
    store = execution_ownership.ExecutionOwnershipStore(hass)
    gate = CommandAdmission(store)
    current = [{"supported": False, "resolved_id": None, "connector_id": 1}]
    monkeypatch.setattr(integration, "command_admission", lambda _: gate)
    monkeypatch.setattr(integration, "_identity_status", lambda h, target: current[0])
    monkeypatch.setattr(integration, "async_track_state_change_event", track)
    entry = SimpleNamespace(entry_id="c", async_on_unload=lambda cb: calls.append(cb),
                            async_create_background_task=create_task)
    controller = SimpleNamespace(ocpp_target=object(), charge_control="switch.charger")
    await integration._async_setup_ownership_metadata(hass, entry, controller)
    assert calls[0][0] == ["switch.charger"] and calls[1] is unsub
    assert (await store.async_status("c", current[0]))["record_state"] == "missing"
    current[0] = {"supported": True, "resolved_id": MOREK_STATION_ID, "connector_id": 1,
                  "match_count": 1, "ocpp_version": "1.6"}
    events = []
    class Worker:
        def suspend_for_availability_change(self):
            events.append("suspend")
            return 1

        def resume_after_availability_change(self, generation):
            assert (tmp_path / execution_ownership.STORAGE_KEY).exists()
            events.append(("resume", generation))

    entry.runtime_data = SimpleNamespace(morek_worker=Worker())
    calls[0][1](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                      "new_state": SimpleNamespace(state="off")}))
    assert events == ["suspend"]
    await asyncio.gather(*tasks)
    assert events == ["suspend", ("resume", 1)]
    assert (await store.async_status("c", current[0]))["record_state"] == "valid"
    hass.services.async_call.assert_not_awaited()
    entry.runtime_data.morek_worker.session = SimpleNamespace(availability_lost=lambda: events.append("offline"))
    calls[0][1](SimpleNamespace(data={"old_state": SimpleNamespace(state="off"),
                                      "new_state": SimpleNamespace(state="unavailable")}))
    calls[0][1](SimpleNamespace(data={"old_state": SimpleNamespace(state="unavailable"),
                                      "new_state": SimpleNamespace(state="off")}))
    await asyncio.gather(*tasks)
    assert events.count("offline") == 1
