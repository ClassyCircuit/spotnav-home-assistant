"""Actual intent/worker modules; HA, OCPP and simulated ownership are boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_worker
from custom_components.spotnav.execution.command_admission import AdmissionResult, CommandAdmission, physical_connector

NOW = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)
IDENTITY = {"supported": True, "resolved_id": morek_schedule.MOREK_STATION_ID,
            "connector_id": 1, "match_count": 1, "ocpp_version": "1.6"}


class SimulatedAdmission(CommandAdmission):
    """Test-only authorization, with the real connector lock and generation."""

    def __init__(self):
        super().__init__(None)
        self.entered = None
        self.release = None

    async def async_execute(self, entry_id, kind, resolve_identity, operation, *, expected_generation=None):
        assert kind == "owned_profile"
        connector = physical_connector(resolve_identity())
        async with self._lock_for(connector):
            if self.entered:
                self.entered.set()
                await self.release.wait()
            if expected_generation != self.generation(connector):
                return AdmissionResult(False, "stale_generation")
            if physical_connector(resolve_identity()) != connector:
                return AdmissionResult(False, "identity_changed")
            return AdmissionResult(True, "simulated", await operation())


class Planner:
    def __init__(self, snapshot):
        self.current = snapshot
        self.listeners = []

    def snapshot(self):
        return self.current

    def snapshot_is_current(self, snapshot):
        return snapshot is self.current and getattr(snapshot, "current", True)

    def add_publication_listener(self, listener):
        self.listeners.append(listener)
        listener(self.current)
        return lambda: self.listeners.remove(listener)

    def publish(self):
        for listener in list(self.listeners):
            listener(self.current)


def setup(monkeypatch, *, active=False, admission=None):
    class Clock:
        now = staticmethod(lambda _: NOW)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_worker, "_COALESCE_SECONDS", 0)
    window = (NOW - timedelta(minutes=1) if active else NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    proposal = SimpleNamespace(has_plan=True, unpriced=False, shown_periods=(window,))
    snapshot = SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready")
    planner = Planner(snapshot)
    settings = SimpleNamespace(revision=4, amps=16)
    hass = SimpleNamespace(data={}, async_create_task=asyncio.create_task)
    point = SimpleNamespace(call=AsyncMock(return_value=SimpleNamespace(status="Accepted")))
    target = SimpleNamespace(connector_id=1)
    state = SimpleNamespace(identity=dict(IDENTITY), settings=settings, planner=planner, point=point,
                            target=target, admission=admission or SimulatedAdmission(), hass=hass)
    monkeypatch.setattr(morek_worker, "controller_for", lambda *_: SimpleNamespace(ocpp_target=target))
    monkeypatch.setattr(morek_schedule, "_identity_status", lambda *_: state.identity)
    monkeypatch.setattr(morek_schedule, "_charge_point", lambda *_: point)
    monkeypatch.setattr(morek_worker, "domain_data", lambda *_: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda _: settings)))
    monkeypatch.setattr(morek_schedule, "domain_data", lambda *_: SimpleNamespace(
        auto_store=SimpleNamespace(settings=lambda _: settings)))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: planner)
    monkeypatch.setattr(morek_worker, "preview_for", lambda *_: planner)
    monkeypatch.setattr(morek_worker, "command_admission", lambda _: state.admission)
    import sys
    monkeypatch.setitem(sys.modules, "ocpp.v16", SimpleNamespace(call=SimpleNamespace(
        SetChargingProfile=lambda **kw: SimpleNamespace(payload=kw))))
    state.worker = morek_worker.MorekScheduleWorker(hass, "charger", planner)
    return state


async def drain(worker):
    while worker._task is not None:
        await worker._task


@pytest.mark.asyncio
async def test_coalesce_deduplicate_and_changed_active_intent(monkeypatch):
    w = setup(monkeypatch, active=True)
    w.worker.start()
    for _ in range(5):
        w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    sent = w.point.call.call_args.args[0].payload["cs_charging_profiles"]
    assert sent["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16
    assert w.worker.reason == "upload_accepted_unverified"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "unchanged"
    start, end = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end - timedelta(minutes=1)),)
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_queued_work_rechecks_edit_and_identity(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish()
    w.admission.release.set()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.reason == "upload_accepted_unverified"
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.settings.revision = 6
    w.planner.current.settings_revision = 6
    w.planner.publish()
    await w.admission.entered.wait()
    w.identity = {**IDENTITY, "resolved_id": "different"}
    w.admission.release.set()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "identity_changed"
    w.worker.close()


@pytest.mark.asyncio
async def test_queued_revision_edit_without_new_publication_is_refused(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    w.settings.revision = 5
    w.admission.release.set()
    await drain(w.worker)
    assert w.worker.reason == "no_current_plan"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_definite_rejection_is_not_retried_for_same_intent(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    w.planner.publish()
    await drain(w.worker)
    assert w.worker.reason == "upload_rejected" and w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_plan", "expired", "stale_prices", "unpriced", "invalid", "pending"])
async def test_unavailable_intents_never_send_or_clear(monkeypatch, case):
    w = setup(monkeypatch)
    proposal = w.planner.current.proposal
    if case == "no_plan":
        w.planner.current.proposal = None
    elif case == "expired":
        proposal.shown_periods = ((NOW - timedelta(hours=2), NOW),)
    elif case == "stale_prices":
        w.planner.current.price_state = "stale"
    elif case == "unpriced":
        proposal.unpriced = True
    elif case == "invalid":
        proposal.shown_periods = ((NOW + timedelta(hours=2), NOW + timedelta(hours=1)),)
    else:
        w.planner.current.current = False
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    assert w.worker.reason in {"no_current_plan", "plan_expired", "prices_stale_or_unavailable",
                               "prices_unavailable", "invalid_plan"}
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_upload_blocks_changed_intents_and_reload(monkeypatch):
    w = setup(monkeypatch)
    w.point.call.side_effect = TimeoutError
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "upload_uncertain" and w.point.call.await_count == 1
    w.worker.close()
    w.settings.revision = w.planner.current.settings_revision = 5
    again = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    again.start()
    await drain(again)
    assert again.reason == "upload_uncertain" and w.point.call.await_count == 1
    again.close()


@pytest.mark.asyncio
async def test_real_production_admission_unconditionally_unarmed(monkeypatch):
    status = {"record_state": "valid", "recorded_owner": "morek_schedule", "armed": True,
              "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    admission = CommandAdmission(SimpleNamespace(async_status=AsyncMock(return_value=status)))
    w = setup(monkeypatch, admission=admission)
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "schedule_mode_unarmed"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_two_workers_serialize_and_share_deduplication(monkeypatch):
    w = setup(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_send(_request):
        entered.set()
        await release.wait()
        return SimpleNamespace(status="Accepted")

    w.point.call.side_effect = slow_send
    other = morek_worker.MorekScheduleWorker(w.hass, "second-entry", w.planner)
    w.worker.start()
    await entered.wait()
    other.start()
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(drain(w.worker), drain(other))
    assert w.point.call.await_count == 1
    assert other.reason == "unchanged"
    w.worker.close()
    other.close()


@pytest.mark.asyncio
async def test_stale_generation_and_cancelled_inflight_fail_closed(monkeypatch):
    w = setup(monkeypatch)
    w.admission.entered, w.admission.release = asyncio.Event(), asyncio.Event()
    w.worker.start()
    await w.admission.entered.wait()
    connector = physical_connector(IDENTITY)
    w.admission._generations[connector] = 1
    w.admission.release.set()
    await drain(w.worker)
    assert w.worker.reason == "stale_generation"
    w.point.call.assert_not_awaited()
    w.admission.entered = None
    entered = asyncio.Event()

    async def waiting(_request):
        entered.set()
        await asyncio.Event().wait()

    w.point.call.side_effect = waiting
    w.planner.publish()
    await entered.wait()
    task = w.worker._task
    w.worker.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    replacement = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    replacement.start()
    await drain(replacement)
    assert replacement.reason == "upload_uncertain" and w.point.call.await_count == 1
    replacement.close()


@pytest.mark.asyncio
async def test_real_planner_publications_drive_worker_without_browser(monkeypatch):
    from .test_stage_13_reactive import _save, _world
    from custom_components.spotnav.vehicles.soc_estimate import SocReader

    world = await _world(monkeypatch)
    w = setup(monkeypatch)
    class Clock:
        now = staticmethod(lambda _: world.request.now)

    monkeypatch.setattr(morek_worker, "datetime", Clock)
    monkeypatch.setattr(morek_schedule, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_worker, "domain_data", lambda _: SimpleNamespace(auto_store=world.store))
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    monkeypatch.setattr(morek_worker, "preview_for", lambda *_: world.controller)
    worker = morek_worker.MorekScheduleWorker(w.hass, "test", world.controller)
    worker.start()
    await drain(worker)
    assert w.point.call.await_count == 1, worker.reason
    # Settings API and deadline use the real reconciliation and publish path.
    await _save(world, minimum_ready_by_soc=35)
    await drain(worker)
    assert w.point.call.await_count == 2
    local = world.request.now.astimezone(auto_controller_zone(world.request.timezone))
    await _save(world, departure_enabled=True, departure_time=(local + timedelta(hours=1)).strftime("%H:%M"))
    await drain(worker)
    assert w.point.call.await_count == 3
    # An SOC-originated calculation and an actual price subscription event.
    serial = worker._serial
    world.facts[0] = replace(world.facts[0], soc_percent=39)
    reader = object.__new__(SocReader)
    reader._last_notified, reader._notify_next = 25, False
    reader._arrival_cancel, reader._arrival_watched = None, ()
    tasks = []
    reader.set_on_reading(lambda: tasks.append(asyncio.create_task(world.controller.async_recalculate())))
    reader.set_notify_every_reading(lambda: True)
    reader._tell(SimpleNamespace(soc_percent=39))
    await tasks.pop()
    await drain(worker)
    assert worker._serial > serial
    serial = worker._serial
    world.area.today_snapshot.document = replace(world.area.today_snapshot.document, prices=(.05,) * 8)
    published = asyncio.Event()
    remove = world.controller.add_publication_listener(lambda _: published.set())
    published.clear()
    world.listeners[-1](world.area)
    await asyncio.wait_for(published.wait(), timeout=2)
    remove()
    await drain(worker)
    assert worker._serial > serial
    # Even an equal calculation is published to this consumer, but deduplicated on wire.
    count = w.point.call.await_count
    await world.controller.async_recalculate()
    await drain(worker)
    assert w.point.call.await_count == count
    worker.close()


def auto_controller_zone(name):
    from custom_components.spotnav import time_zones
    return time_zones.require_zone(name)
