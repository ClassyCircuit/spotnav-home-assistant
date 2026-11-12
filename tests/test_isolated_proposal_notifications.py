"""Actual notifier and planner values, with HA delivery and scheduling mocked."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.spotnav.execution.charger_events import ChargerEventTracker, ChargerFacts
from custom_components.spotnav.notifications import notifier as module
from custom_components.spotnav.notifications.settings import NotificationSettings
from custom_components.spotnav.planning.auto_controller import AutoPlannerController, AutoSnapshot
from custom_components.spotnav.planning.planner import PlanResult

NOW = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)


def snapshot(started=NOW + timedelta(seconds=6), *, attempt=1, proposal=True, revision=1):
    plan = PlanResult(
        version=1, area_id="SE4", timezone="Europe/Stockholm", currency="EUR", major_unit="EUR",
        minor_unit="cent", now=NOW, reason=None, power_kw=4, requested_kwh=4, delivered_kwh=4,
        distance_mil=0, estimated_cost=1.59,
        periods=((NOW + timedelta(hours=1), NOW + timedelta(hours=2, minutes=30)),), slots=(),
        unpriced_slots=0, priced_slots=6, unpriced=False, slots_needed=6,
    ) if proposal else None
    return AutoSnapshot(
        state="planned", reason="ok", settings_revision=revision, generation=1, calculated_at=NOW,
        area_id="SE4", currency="EUR", major_unit="EUR", minor_unit="cent", timezone="Europe/Stockholm",
        missing=(), price_state=None, price_identity=None, today=None, tomorrow=None, proposal=plan,
        priced_slots=6, unpriced_slots=0, unpriced=False, applied=False, in_process=True, attempt=attempt,
        execution="not_applied", applied_identity=None, pending_identity=None, last_error_code=None,
        departure_at=NOW + timedelta(hours=10), expected_soc_percent=57, calculation_started_at=started,
        connection_generation=1,
        notification_vehicle_id="car", notification_vehicle_checked=True,
    )


@pytest.fixture
def env(monkeypatch):
    class Storage:
        def __init__(self, *args, **kwargs):
            self.record = None
        async def async_save(self, record):
            self.record = record
        async def async_load(self):
            return self.record

    monkeypatch.setattr(module, "_NotifierStore", Storage)
    monkeypatch.setattr(module, "async_track_point_in_utc_time", lambda *args: lambda: None)
    dt_util.set_default_time_zone(ZoneInfo("Europe/Stockholm"))
    service = SimpleNamespace(has_service=lambda domain, target: True, async_call=AsyncMock())
    hass = SimpleNamespace(services=service, config=SimpleNamespace(language="en"),
                           async_create_task=lambda coro, **kwargs: __import__("asyncio").create_task(coro))
    settings = SimpleNamespace(revision=1, driver="target_soc", target=SimpleNamespace(target_percent=80),
        notifications=NotificationSettings(targets=("mobile_app_test",), events=("plugged_in", "plan_installed")))
    store = SimpleNamespace(settings=lambda entry: settings)
    controller = SimpleNamespace(held_off_by_person=False, plan=None,
        adapter=SimpleNamespace(reports_connection=True, vehicle_connected=lambda: True))
    n = module.ChargerNotifier(hass, "test", name=lambda: "Charger", controller=controller, store=store)
    n._connected = True
    n._proposal_since = NOW
    preview = SimpleNamespace(current=None)
    preview.snapshot_is_current = lambda value: value is preview.current and value.settings_revision == settings.revision
    preview.snapshot_matches_connection = preview.snapshot_is_current
    n._preview = preview
    yield n, preview, settings, service, controller
    dt_util.set_default_time_zone(timezone.utc)


@pytest.mark.asyncio
async def test_only_fresh_current_proposal_is_sent(env):
    n, preview, _, service, _ = env
    old = snapshot(NOW - timedelta(seconds=1))
    preview.current = n._snapshot = old
    n._judge_proposal(NOW + timedelta(seconds=60))
    await __import__("asyncio").sleep(0)
    assert "Waiting" in service.async_call.call_args.args[2]["message"]
    fresh = snapshot()
    preview.current = n._snapshot = fresh
    n._judge_proposal(NOW + timedelta(seconds=90))
    await __import__("asyncio").sleep(0)
    message = service.async_call.call_args.args[2]["message"]
    assert "Proposed charging: 2026-11-06 22:00–2026-11-06 23:30" in message
    assert "Estimated SOC by ready-by: 57%" in message
    assert "Target: 80%" in message and "Estimated plan cost: €1.59" in message
    assert service.async_call.call_count == 2
    assert all(call.args[0] == "notify" for call in service.async_call.call_args_list)


@pytest.mark.asyncio
async def test_stale_revision_and_out_of_order_are_never_used(env):
    n, preview, settings, service, _ = env
    older = snapshot(attempt=1)
    newer = snapshot(attempt=2)
    preview.current = newer
    n._snapshot = older
    assert not n._proposal_current(older)
    n._snapshot = newer
    settings.revision = 2
    n._judge_proposal(NOW + timedelta(seconds=60))
    await __import__("asyncio").sleep(0)
    assert "Waiting" in service.async_call.call_args.args[2]["message"]


@pytest.mark.asyncio
async def test_no_plan_no_phones_and_person_stop(env):
    n, preview, settings, service, controller = env
    preview.current = n._snapshot = snapshot(proposal=False)
    settings.notifications = NotificationSettings(targets=(), events=("plugged_in",))
    n._judge_proposal(NOW + timedelta(seconds=60))
    await __import__("asyncio").sleep(0)
    assert not service.async_call.called
    n._proposal_waiting_told = False
    settings.notifications = NotificationSettings(targets=("mobile_app_test",), events=("plugged_in",))
    preview.current = n._snapshot = snapshot()
    controller.held_off_by_person = True
    n._judge_proposal(NOW + timedelta(seconds=61))
    await __import__("asyncio").sleep(0)
    assert "Waiting" in service.async_call.call_args.args[2]["message"]
    assert n._proposal_since is not None


def test_actual_event_tracker_and_connection_generation():
    tracker = ChargerEventTracker()
    assert tracker.observe(ChargerFacts(charging=False, connected=False)) == []
    assert tracker.observe(ChargerFacts(charging=False, connected=True)) == [("plugged_in", {})]
    assert tracker.observe(ChargerFacts(charging=False, connected=False)) == [("unplugged", {})]

    planner = object.__new__(AutoPlannerController)
    planner._shutdown = False
    planner._executor = None
    planner._attempt = 1
    planner._entry_id = "test"
    planner._store = SimpleNamespace(settings=lambda _: SimpleNamespace(revision=1))
    planner._connection_generation = 1
    planner._connection_ready_generation = None
    planner._notification_vehicle = lambda: (True, "car")
    planner._snapshot = snapshot()
    assert not planner.snapshot_matches_connection(planner._snapshot)
    planner._connection_ready_generation = 1
    assert planner.snapshot_matches_connection(planner._snapshot)
    planner._connection_generation = 2
    assert not planner.snapshot_matches_connection(planner._snapshot)
    planner._connection_generation = 1
    planner._notification_vehicle = lambda: (True, "other")
    assert not planner.snapshot_matches_connection(planner._snapshot)


@pytest.mark.asyncio
async def test_unplug_replug_invalidates_owed_and_old_proposal(env):
    n, preview, _, service, controller = env
    n._baselined = True
    controller.adapter.vehicle_connected = lambda: False
    n._observe_connection(NOW + timedelta(minutes=1))
    assert n._proposal_since is None
    controller.adapter.vehicle_connected = lambda: True
    n._observe_connection(NOW + timedelta(minutes=2))
    old = snapshot()
    preview.current = n._snapshot = old
    assert not n._proposal_current(old)
    n._judge_proposal(NOW + timedelta(minutes=3))
    await __import__("asyncio").sleep(0)
    assert "Waiting" in service.async_call.call_args.args[2]["message"]


@pytest.mark.asyncio
async def test_restart_restores_owed_without_trusting_old_snapshot(env):
    n, preview, _, service, _ = env
    n._save_plan()
    await __import__("asyncio").sleep(0)
    n._proposal_since = None
    await n.async_load()
    assert n._proposal_since == NOW
    old = snapshot(NOW - timedelta(seconds=1))
    preview.current = n._snapshot = old
    n._judge_proposal(NOW + timedelta(minutes=1))
    await __import__("asyncio").sleep(0)
    assert "Waiting" in service.async_call.call_args.args[2]["message"]


@pytest.mark.asyncio
async def test_optional_values_and_rate_limit(env):
    n, preview, _, service, _ = env
    fresh = snapshot()
    fresh = replace(fresh, expected_soc_percent=None, departure_at=None,
                    proposal=replace(fresh.proposal, unpriced=True))
    preview.current = n._snapshot = fresh
    n._judge_proposal(NOW + timedelta(seconds=40))
    await __import__("asyncio").sleep(0)
    message = service.async_call.call_args.args[2]["message"]
    assert "Estimated SOC" not in message and "Estimated plan cost" not in message
    n._proposal_since = NOW + timedelta(seconds=50)
    fresh = replace(fresh, calculation_started_at=NOW + timedelta(seconds=51))
    preview.current = n._snapshot = fresh
    n._judge_proposal(NOW + timedelta(seconds=90))
    await __import__("asyncio").sleep(0)
    assert service.async_call.call_count == 1


@pytest.mark.asyncio
async def test_partial_window_and_day_boundary(env):
    n, preview, _, service, _ = env
    fresh = snapshot()
    plan = replace(fresh.proposal, periods=((NOW + timedelta(hours=2, minutes=45), NOW + timedelta(hours=4, minutes=15)),),
                   ends_at_need=True)
    fresh = replace(fresh, proposal=plan)
    preview.current = n._snapshot = fresh
    n._judge_proposal(NOW + timedelta(seconds=40))
    await asyncio.sleep(0)
    message = service.async_call.call_args.args[2]["message"]
    assert "2026-11-06 23:45–2026-11-07 00:45" in message


@pytest.mark.asyncio
async def test_actual_calculation_captures_connection_before_await():
    planner = object.__new__(AutoPlannerController)
    planner._shutdown = False
    planner._executor = None
    planner._attempt = 0
    planner._entry_id = "test"
    settings = SimpleNamespace(revision=1)
    planner._store = SimpleNamespace(settings=lambda _: settings)
    planner._now = lambda: NOW
    planner._notification_vehicle = lambda: (True, "car")
    planner._connection_generation = 1
    planner._connection_ready_generation = 1
    planner._calculation_lock = asyncio.Lock()
    planner._source = lambda: None
    planner._lapse_target_stop = lambda _: None
    planner._arm_watch = lambda: None
    planner._republish_execution = lambda value: value
    planner._apply = AsyncMock()
    started, finish = asyncio.Event(), asyncio.Event()

    async def compute(_settings, _attempt):
        started.set()
        await finish.wait()
        return snapshot()

    planner._compute = compute
    task = asyncio.create_task(planner._calculate(settings))
    await started.wait()
    planner._connection_generation = 2
    planner._connection_ready_generation = 2
    finish.set()
    result = await task
    planner._snapshot = result
    assert result.connection_generation == 1
    assert not planner.snapshot_matches_connection(result)


def test_publication_listener_delivers_unchanged_calculation_and_currentness():
    planner = object.__new__(AutoPlannerController)
    planner._shutdown = False
    planner._executor = None
    planner._attempt = 1
    planner._entry_id = "test"
    planner._store = SimpleNamespace(settings=lambda _: SimpleNamespace(revision=1))
    planner._connection_generation = 1
    planner._connection_ready_generation = 1
    planner._notification_vehicle = lambda: (True, "car")
    planner._snapshot = None
    planner._last_key = None
    planner._listeners = []
    planner._publication_listeners = []
    publications, changes = [], []
    planner.add_publication_listener(publications.append)
    planner.add_listener(changes.append)
    first = snapshot()
    planner._publish(first)
    planner._attempt = 2
    second = replace(first, attempt=2, calculation_started_at=NOW + timedelta(seconds=8))
    planner._publish(second)
    assert publications == [first, second]
    assert changes == [first]
    assert not planner.snapshot_matches_connection(first)
    assert planner.snapshot_matches_connection(second)


def test_late_callbacks_and_bursts_cannot_replace_current(env, monkeypatch):
    n, preview, settings, _, _ = env
    n._observe = lambda: None
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: NOW + timedelta(seconds=100))
    current = snapshot(attempt=2)
    preview.current = current
    n._on_snapshot(current)
    assert n._proposal_due == NOW + timedelta(seconds=120)
    old = snapshot(attempt=1)
    n._on_snapshot(old)
    assert n._snapshot is current
    settings.revision = 2
    assert not n._proposal_current(current)


@pytest.mark.asyncio
async def test_waiting_is_bounded_and_not_repeated(env):
    n, preview, _, service, _ = env
    no_plan = snapshot(proposal=False)
    preview.current = n._snapshot = no_plan
    n._judge_proposal(NOW + timedelta(seconds=60))
    n._judge_proposal(NOW + timedelta(seconds=90))
    await asyncio.sleep(0)
    assert service.async_call.call_count == 1
    assert "Waiting" in service.async_call.call_args.args[2]["message"]


@pytest.mark.asyncio
async def test_new_waiting_notice_can_be_replaced_despite_recent_plan(env):
    n, preview, _, service, _ = env
    fresh = snapshot()
    preview.current = n._snapshot = fresh
    n._judge_proposal(NOW + timedelta(seconds=40))
    await asyncio.sleep(0)
    n._proposal_since = NOW + timedelta(seconds=50)
    preview.current = n._snapshot = snapshot(started=NOW + timedelta(seconds=51), proposal=False)
    n._judge_proposal(NOW + timedelta(seconds=110))
    await asyncio.sleep(0)
    preview.current = n._snapshot = snapshot(started=NOW + timedelta(seconds=120))
    n._judge_proposal(NOW + timedelta(seconds=150))
    await asyncio.sleep(0)
    assert service.async_call.call_count == 3
    payloads = [call.args[2] for call in service.async_call.call_args_list]
    assert payloads[1]["data"]["tag"] == payloads[2]["data"]["tag"]
    assert "Proposed charging" in payloads[2]["message"]


def test_shutdown_cancels_notification_timer(env):
    n, _, _, _, _ = env
    cancelled = []
    n._proposal_timer = lambda: cancelled.append(True)
    n._proposal_due = NOW
    n.async_shutdown()
    assert cancelled == [True]
    assert n._proposal_due is None
    assert n._preview is None
