"""Actual ledger storage protocol with filesystem and HA persistence boundary doubles."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from custom_components.spotnav.execution import morek_outcomes


@pytest.mark.asyncio
async def test_atomic_evidence_survives_new_instance_and_detects_bad_storage(monkeypatch, tmp_path):
    path = tmp_path / "outcomes.json"

    class Disk:
        def __init__(self, *args, **kwargs):
            self.path = str(path)

        async def async_save(self, data):
            path.write_text(json.dumps({"version": 1, "minor_version": 1, "data": data}), encoding="utf-8")

    async def executor(func, *args):
        return func(*args)

    monkeypatch.setattr(morek_outcomes, "Store", Disk)
    hass = SimpleNamespace(async_add_executor_job=executor)
    ledger = morek_outcomes.MorekOutcomes(hass)
    assert await ledger.read() is None
    pending = {"schema": 1, "entry_id": "charger", "desired": {"fingerprint": "x"},
               "attempt": {"fingerprint": "x", "state": "uncertain"}, "uncertain": True,
               "acknowledged": None, "verified": None, "removal": None}
    await ledger.write(pending)
    assert await morek_outcomes.MorekOutcomes(hass).read() == pending
    path.write_text('{"version":1,"data":{"schema":1,"entry_id":"charger","uncertain":false,'
                    '"attempt":{"state":"uncertain"}}}', encoding="utf-8")
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await morek_outcomes.MorekOutcomes(hass).read()


@pytest.mark.asyncio
async def test_cancelled_or_silently_failed_write_poison_process(monkeypatch, tmp_path):
    entered = asyncio.Event()

    class Disk:
        def __init__(self, *args, **kwargs):
            self.path = str(tmp_path / "missing")

        async def async_save(self, data):
            entered.set()
            await asyncio.Event().wait()

    async def executor(func, *args):
        return func(*args)

    monkeypatch.setattr(morek_outcomes, "Store", Disk)
    ledger = morek_outcomes.MorekOutcomes(SimpleNamespace(async_add_executor_job=executor))
    task = asyncio.create_task(ledger.write({"schema": 1}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.read()

    class SilentDisk(Disk):
        async def async_save(self, data):
            pass

    monkeypatch.setattr(morek_outcomes, "Store", SilentDisk)
    ledger = morek_outcomes.MorekOutcomes(SimpleNamespace(async_add_executor_job=executor))
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.write({"schema": 1})
    assert ledger.poisoned


@pytest.mark.asyncio
async def test_uncertain_manual_attempt_blocks_worker_after_storage_reload(monkeypatch, tmp_path):
    from .test_morek_worker import drain, manual_setup
    from custom_components.spotnav.api import morek_schedule
    from custom_components.spotnav.execution.morek_worker import MorekScheduleWorker

    w = manual_setup(monkeypatch)
    path = tmp_path / "outcomes.json"

    class Disk:
        def __init__(self, *args, **kwargs):
            self.path = str(path)

        async def async_save(self, data):
            path.write_text(json.dumps({"version": 1, "data": data}), encoding="utf-8")

    async def executor(func, *args):
        return func(*args)

    monkeypatch.setattr(morek_outcomes, "Store", Disk)
    w.hass.async_add_executor_job = executor
    ledger = morek_outcomes.MorekOutcomes(w.hass)
    monkeypatch.setattr(morek_schedule, "outcomes_for", lambda _: ledger)
    w.point.call.side_effect = TimeoutError
    with pytest.raises(morek_schedule.ScheduleRefused, match="upload_uncertain"):
        await morek_schedule.async_schedule_action(w.hass, "charger", "send", w.worker._intent()[1])
    ledger = morek_outcomes.MorekOutcomes(w.hass)  # simulate a fresh process's durable reader
    assert (await ledger.read())["uncertain"] is True
    again = MorekScheduleWorker(w.hass, "charger", w.planner)
    again.start()
    await drain(again)
    assert again.reason == "upload_uncertain" and w.point.call.await_count == 1
    again.close()
