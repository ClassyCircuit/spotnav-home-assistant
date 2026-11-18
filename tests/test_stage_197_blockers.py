"""Stage 19.7 (independent part): verified recovery of a poisoned outcome ledger and the upload-only link gate."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from custom_components import spotnav
from custom_components.spotnav.const import MOREK_CONNECTOR_ID, MOREK_STATION_ID
from custom_components.spotnav.execution import morek_outcomes
from custom_components.spotnav.execution.morek_worker import MorekScheduleWorker


def record(tag: str) -> dict:
    return {"schema": 1, "entry_id": "charger", "uncertain": False, "tag": tag,
            "desired": None, "attempt": None, "acknowledged": None, "verified": None, "removal": None}


def disk_write(path, data) -> None:
    path.write_text(json.dumps({"version": 1, "minor_version": 1, "data": data}), encoding="utf-8")


def make(monkeypatch, path, save, executor=None):
    class Disk:
        def __init__(self, *args, **kwargs):
            self.path = str(path)

        async_save = staticmethod(save)

    async def default_executor(func, *args):
        return func(*args)

    executor = executor or default_executor

    async def bound_save(self, data):
        await save(data)

    Disk.async_save = bound_save
    monkeypatch.setattr(morek_outcomes, "Store", Disk)
    return morek_outcomes.MorekOutcomes(SimpleNamespace(async_add_executor_job=executor))


@pytest.mark.asyncio
async def test_completed_failed_save_recovers_by_verified_reread(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))

    async def save(data):
        raise OSError("disk full")  # the job finished with an error: nothing can land later

    ledger = make(monkeypatch, path, save)
    with pytest.raises(OSError):
        await ledger.write(record("new"))
    assert ledger.poisoned
    assert (await ledger.read())["tag"] == "old"  # verified reread of what is really on disk
    assert not ledger.poisoned and ledger.recovery == "recovered"


@pytest.mark.asyncio
async def test_cancelled_save_stays_poisoned_until_the_late_write_is_seen_to_land(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    entered = asyncio.Event()

    async def save(data):
        entered.set()
        await asyncio.Event().wait()

    ledger = make(monkeypatch, path, save)
    task = asyncio.create_task(ledger.write(record("new")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The executor job may still run: a valid "old" record is NOT proof, a later landing could overwrite a new write.
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.read()
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.write(record("other"))
    assert ledger.poisoned and ledger.recovery == "late_write_unproven"
    disk_write(path, record("new"))  # the late job lands
    assert (await ledger.read())["tag"] == "new"
    assert not ledger.poisoned


@pytest.mark.asyncio
async def test_cancelled_save_of_an_identical_record_cannot_be_proven(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("same"))
    entered = asyncio.Event()

    async def save(data):
        entered.set()
        await asyncio.Event().wait()

    ledger = make(monkeypatch, path, save)
    task = asyncio.create_task(ledger.write(record("same")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.read()  # equal to before: a not-yet-run job could still overwrite a later write


@pytest.mark.asyncio
async def test_invalid_file_is_never_reinitialized(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))

    async def save(data):
        raise OSError("boom")

    ledger = make(monkeypatch, path, save)
    with pytest.raises(OSError):
        await ledger.write(record("new"))
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.read()
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.write(record("fresh"))
    assert path.read_text(encoding="utf-8") == "{not json"
    assert ledger.poisoned


@pytest.mark.asyncio
async def test_recovered_ledger_writes_again(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    fail = [True]

    async def save(data):
        if fail[0]:
            raise OSError("once")
        disk_write(path, data)

    ledger = make(monkeypatch, path, save)
    with pytest.raises(OSError):
        await ledger.write(record("a"))
    fail[0] = False
    await ledger.write(record("b"))  # missing file is a valid reread; the poison clears first
    assert (await ledger.read())["tag"] == "b"


def worker(available, link):
    return MorekScheduleWorker(None, "e", None, lambda: available[0], link)


def test_upload_gate_uses_link_only_when_switch_is_unavailable():
    switch = [False]
    assert worker(switch, None)._upload_available() is False
    assert worker(switch, lambda: True)._upload_available() is True
    assert worker(switch, lambda: False)._upload_available() is False

    def broken():
        raise RuntimeError("registry")

    assert worker(switch, broken)._upload_available() is False
    switch[0] = True
    w = worker(switch, lambda: False)
    assert w._upload_available() is True and w._available() is True
    w._available = lambda: False  # the switch-only gate used by start/session paths is unchanged
    assert w._upload_available() is False


async def poison_by_failed_save(ledger):
    with pytest.raises(OSError):
        await ledger.write(record("new"))
    assert ledger.poisoned


@pytest.mark.asyncio
async def test_concurrent_readers_recover_once(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    gate = asyncio.Event()
    state = {"parked": False}

    async def executor(func, *args):
        if state["parked"]:
            state["parked"] = False
            await gate.wait()  # the first recovery read of the first reader pauses
        return func(*args)

    async def save(data):
        raise OSError("full")

    ledger = make(monkeypatch, path, save, executor)
    await poison_by_failed_save(ledger)
    recovers = []
    original = ledger._recover

    async def counting():
        recovers.append(1)
        await original()

    ledger._recover = counting
    state["parked"] = True
    first = asyncio.create_task(ledger.read())
    second = asyncio.create_task(ledger.read())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    gate.set()
    assert (await first)["tag"] == "old" and (await second)["tag"] == "old"
    assert len(recovers) == 1 and not ledger.poisoned


@pytest.mark.asyncio
async def test_recovery_cannot_clear_a_newer_failed_write_poison(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    gate = asyncio.Event()
    state = {"parked": False}

    async def executor(func, *args):
        if state["parked"]:
            state["parked"] = False
            await gate.wait()  # reader 1 is parked inside its recovery
        return func(*args)

    async def save(data):
        raise OSError("full")

    ledger = make(monkeypatch, path, save, executor)
    ledger.poisoned = True  # an earlier completed failed write
    state["parked"] = True
    reader = asyncio.create_task(ledger.read())
    await asyncio.sleep(0)
    writer = asyncio.create_task(ledger.write(record("newer")))  # queued behind the recovery, then fails again
    await asyncio.sleep(0)
    gate.set()
    assert (await reader)["tag"] == "old"
    with pytest.raises(OSError):
        await writer
    # Unserialized, the reader's recovery could finish after the writer failed and wrongly clear this poison.
    assert ledger.poisoned and ledger.recovery is None
    assert (await ledger.read())["tag"] == "old" and not ledger.poisoned


@pytest.mark.asyncio
async def test_cancelled_save_with_two_waiting_readers_recovers_only_after_landing(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    entered = asyncio.Event()

    async def save(data):
        entered.set()
        await asyncio.Event().wait()

    ledger = make(monkeypatch, path, save)
    writer = asyncio.create_task(ledger.write(record("new")))
    await entered.wait()
    writer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer
    results = await asyncio.gather(ledger.read(), ledger.read(), return_exceptions=True)
    assert all(isinstance(r, morek_outcomes.OutcomeUnavailable) for r in results) and ledger.poisoned
    disk_write(path, record("new"))
    results = await asyncio.gather(ledger.read(), ledger.read())
    assert [r["tag"] for r in results] == ["new", "new"] and not ledger.poisoned


@pytest.mark.asyncio
async def test_cancelled_waiter_holds_nothing_and_does_not_poison(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    entered, release = asyncio.Event(), asyncio.Event()

    async def save(data):
        entered.set()
        await release.wait()
        disk_write(path, data)

    ledger = make(monkeypatch, path, save)
    holder = asyncio.create_task(ledger.write(record("a")))
    await entered.wait()
    waiter = asyncio.create_task(ledger.write(record("b")))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not ledger.poisoned
    release.set()
    await holder
    assert (await ledger.read())["tag"] == "a" and not ledger.poisoned


@pytest.mark.asyncio
async def test_cancelled_executor_read_during_recovery_keeps_poison_and_releases_lock(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    entered = asyncio.Event()

    async def save(data):
        raise OSError("full")

    ledger = make(monkeypatch, path, save)
    await poison_by_failed_save(ledger)

    async def hang(func, *args):
        entered.set()
        await asyncio.Event().wait()

    ledger.hass.async_add_executor_job = hang
    task = asyncio.create_task(ledger.read())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ledger.poisoned and not ledger._lock.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "{not json", json.dumps({"version": 2, "data": {}}), json.dumps({"version": 1, "data": {"schema": 9}}),
    json.dumps([1]), json.dumps({"version": 1, "minor_version": 1, "data": {**record("x"), "entry_id": ""}}),
])
async def test_write_never_overwrites_an_invalid_existing_file(monkeypatch, tmp_path, content):
    path = tmp_path / "o.json"
    path.write_text(content, encoding="utf-8")
    saves = []

    async def save(data):
        saves.append(data)

    ledger = make(monkeypatch, path, save)
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.write(record("fresh"))
    assert saves == [] and path.read_text(encoding="utf-8") == content
    assert not ledger.poisoned  # a refusal before any save is not a failed save


@pytest.mark.asyncio
async def test_write_never_overwrites_an_unreadable_file(monkeypatch, tmp_path):
    path = tmp_path / "o.json"
    disk_write(path, record("old"))
    saves = []

    async def save(data):
        saves.append(data)

    async def executor(func, *args):
        raise PermissionError("locked")

    ledger = make(monkeypatch, path, save, executor)
    with pytest.raises(morek_outcomes.OutcomeUnavailable):
        await ledger.write(record("fresh"))
    assert saves == []


@pytest.mark.asyncio
async def test_missing_file_initializes(monkeypatch, tmp_path):
    path = tmp_path / "o.json"

    async def save(data):
        disk_write(path, data)

    ledger = make(monkeypatch, path, save)
    assert await ledger.read() is None
    await ledger.write(record("first"))
    assert (await ledger.read())["tag"] == "first"


def point(version="1.6", status="ok"):
    return SimpleNamespace(_ocpp_version=version, status=status)


def ocpp_hass(*systems):
    return SimpleNamespace(data={"ocpp": {str(i): system for i, system in enumerate(systems)}})


def system(points, cpids=None):
    return SimpleNamespace(charge_points=points, cpids=cpids or {})


TARGET = SimpleNamespace(devid="alias", connector_id=MOREK_CONNECTOR_ID)


def test_production_link_check_and_worker_gate():
    """`spotnav._morek_upload_link` is the function the integration setup's closure calls for the worker."""
    link = spotnav._morek_upload_link
    alias = {"alias": MOREK_STATION_ID}
    good = ocpp_hass(system({MOREK_STATION_ID: point()}, alias))
    assert link(good, TARGET) is True
    assert link(good, None) is False
    assert link(ocpp_hass(system({MOREK_STATION_ID: point(status="connecting")}, alias)), TARGET) is False
    assert link(ocpp_hass(system({MOREK_STATION_ID: point(version="2.0.1")}, alias)), TARGET) is False
    assert link(ocpp_hass(system({})), TARGET) is False
    assert link(SimpleNamespace(data={}), TARGET) is False
    assert link(ocpp_hass(system({"other": point()}, {"alias": "other"})), TARGET) is False
    two = ocpp_hass(system({MOREK_STATION_ID: point()}, alias), system({MOREK_STATION_ID: point()}, alias))
    assert link(two, TARGET) is False
    assert link(good, SimpleNamespace(devid="alias", connector_id=MOREK_CONNECTOR_ID + 1)) is False
    switch = [False]
    live = MorekScheduleWorker(None, "e", None, lambda: switch[0], lambda: link(good, TARGET))
    dead = MorekScheduleWorker(None, "e", None, lambda: switch[0], lambda: link(ocpp_hass(system({})), TARGET))
    assert live._upload_available() is True and dead._upload_available() is False
