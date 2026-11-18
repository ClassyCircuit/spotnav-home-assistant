"""Stage 19.2/19.9a review: the sidebar Resume/Stop click through the real `spotnav/manual_action` handler, a real
AutoExecutor owned route, real CommandAdmission/ownership/ledger stores and the real worker send path. HA, OCPP and the
wire are mocked boundaries. Nothing here proves charger behavior or physical charging.
Run (short): PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
tests/test_stage_192_ui_click.py"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.spotnav.api import manual_action, morek_schedule
from custom_components.spotnav.execution import command_admission, execution_ownership, morek_outcomes, morek_worker
from .test_morek_worker import drain
from .test_stage_192_recovery import _real_unknown
from .test_stage_192_ui_path import Connection, _status

_STATE_KEYS = (command_admission._DATA_KEY, execution_ownership._DATA_KEY, morek_outcomes._DATA_KEY,  # noqa: SLF001
               "spotnav_morek_sending")


def _wire_ui(monkeypatch, w):
    from custom_components.spotnav.execution.auto_execution import AutoExecutor
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(morek_worker=w.worker),
                            async_on_unload=lambda _: None)
    controller = MagicMock(ocpp_target=w.target, entry_id="test")
    monkeypatch.setattr(manual_action, "resolve_charger_request", lambda *_: entry)

    async def owned(action):  # the same translation as the production wiring in __init__.py
        from custom_components.spotnav.execution.auto_execution import AutoControlRefused
        try:
            return await morek_schedule.async_maybe_owned_action(w.hass, "test", action)
        except morek_schedule.ScheduleRefused as error:
            raise AutoControlRefused(error.code) from None
    settings = SimpleNamespace(settings=lambda _: SimpleNamespace(pause=SimpleNamespace(admitted=False)))
    executor = AutoExecutor(w.hass, controller, settings, owned_manual_action=owned,
                            owned_resume_complete=w.worker.trigger)
    monkeypatch.setattr(manual_action, "preview_for",
                        lambda *_: SimpleNamespace(async_manual_action=executor.async_manual_action))
    checker = MagicMock()
    w.hass.data.setdefault("spotnav_morek_checker", {})["test"] = checker
    return checker


async def _click(w, action="resume"):
    connection = Connection()
    await manual_action.websocket_manual_action.__wrapped__(
        w.hass, connection, {"id": 2, "type": "spotnav/manual_action", "api_version": manual_action.ACTION_API_VERSION,
                             "charger_id": "test", "action": action})
    return connection.results[-1]


def _no_ticket(w):
    w.admission._completion_tickets.clear()  # noqa: SLF001 - HA restarted: no ownership ticket
    w.admission.reserve_lifecycle_barrier("test", lambda: w.identity)


def _restart(monkeypatch, w):
    for key in _STATE_KEYS:
        w.hass.data.pop(key, None)
    restarted = command_admission.command_admission(w.hass)
    monkeypatch.setattr(morek_schedule, "command_admission", lambda _: restarted)
    monkeypatch.setattr(morek_schedule, "ownership_store", lambda _: restarted._store)  # noqa: SLF001
    monkeypatch.setattr(morek_worker, "command_admission", lambda _: restarted)
    return restarted


@pytest.mark.allow_loop_io
@pytest.mark.asyncio
async def test_ui_resume_on_the_ticketless_legacy_record_is_accepted_durable_then_sent_once(monkeypatch, tmp_path):
    w, _ = await _real_unknown(monkeypatch, tmp_path)
    checker = _wire_ui(monkeypatch, w)
    _no_ticket(w)
    link = w.worker._available  # noqa: SLF001
    w.worker._available = lambda: False  # noqa: SLF001 - link down: the click can only be made durable
    before = await _status(w)
    assert before["ownership"]["completion_authorized"] is False and before["schedule_pause"]["resume_recoverable"] is True
    result = await _click(w)
    # no earlier backend rejection (owner/ticket/identity/legacy admission): accepted
    assert result["ok"] is True and result["error"] is None and result["action"] == "resume", result
    await drain(w.worker)
    record = await w.ledger.read()
    assert record["pending_resume"]["pause_id"] == "p1" and record["schedule_pause"]["type"] == "pause_until_resumed"
    assert record["uncertain"] is True and w.point.call.await_count == 0
    during = await _status(w)
    assert during["schedule_pause"]["request"] == "resume_pending" and during["schedule_pause"]["resume_pending"] is True
    assert during["schedule_pause"]["resume_recoverable"] is False  # the panel offers nothing twice
    first_id = record["pending_resume"]["id"]
    await _click(w)
    assert (await w.ledger.read())["pending_resume"]["id"] == first_id  # a second click is not a second request
    w.worker._available = link  # noqa: SLF001
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    final = await w.ledger.read()
    assert final["uncertain"] is False and final["attempt"]["dispatch_class"] == "resolved"
    assert final["attempt"]["replaces"] == "o" * 32 and final["unknown_history"][0]["outcome"] == "unknown"
    assert final["schedule_pause"]["type"] == "resume_requested" and "pending_resume" not in final
    checker.request_transition_watch.assert_called()  # the watch for the standing ordering risk is armed
    w.worker.close()


@pytest.mark.allow_loop_io
@pytest.mark.asyncio
async def test_ui_stop_arriving_while_the_resume_is_persisted_wins_and_survives_restart(monkeypatch, tmp_path):
    w, world = await _real_unknown(monkeypatch, tmp_path)
    _wire_ui(monkeypatch, w)
    _no_ticket(w)
    entered, release = asyncio.Event(), asyncio.Event()
    real_write = w.ledger.write

    async def blocked(value):
        if value.get("pending_resume") and not entered.is_set():
            entered.set()
            await release.wait()
        await real_write(value)
    monkeypatch.setattr(w.ledger, "write", blocked)
    click = asyncio.ensure_future(_click(w))
    await entered.wait()
    with w.admission.person_stop_reservation("test", lambda: w.identity):  # the Stop handler's real reservation
        release.set()
        result = await click
    assert result["ok"] is False and result["error"] == "resume_interrupted", result
    await drain(w.worker)
    record = await w.ledger.read()
    assert "pending_resume" not in record and record["schedule_pause"]["type"] == "pause_until_resumed"
    assert w.point.call.await_count == 0
    w.worker.close()
    restarted = _restart(monkeypatch, w)
    revision = restarted.reserve_lifecycle_barrier("test", lambda: w.identity)
    await restarted.async_recover_after_restart("test", lambda: w.identity, revision, 0)
    worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    worker.start()
    await drain(worker)
    assert w.point.call.await_count == 0, worker.reason  # a Resume that lost to the Stop is never recovered
    final = await morek_outcomes.outcomes_for(w.hass).read()
    assert "pending_resume" not in final and final["uncertain"] is True
    worker.close()


@pytest.mark.allow_loop_io
@pytest.mark.asyncio
async def test_ui_stop_after_a_pending_resume_deletes_it_and_restart_never_recovers_it(monkeypatch, tmp_path):
    w, world = await _real_unknown(monkeypatch, tmp_path)
    _wire_ui(monkeypatch, w)
    _no_ticket(w)
    w.worker._available = lambda: False  # noqa: SLF001
    assert (await _click(w))["ok"] is True
    assert "pending_resume" in await w.ledger.read()
    stopped = await _click(w, "stop")
    assert stopped["ok"] is True, stopped
    record = await w.ledger.read()
    assert "pending_resume" not in record and record["schedule_pause"]["type"] == "pause_until_resumed"
    w.worker.close()
    _restart(monkeypatch, w)
    worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    worker.start()
    await drain(worker)
    final = await morek_outcomes.outcomes_for(w.hass).read()
    assert "pending_resume" not in final and final["schedule_pause"]["type"] == "pause_until_resumed"
    for call in w.point.call.await_args_list:  # anything sent is only ever a hold, never a plan
        periods = call.args[0].payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
        assert {p["limit"] for p in periods} == {0}
    worker.close()
