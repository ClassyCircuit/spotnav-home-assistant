"""Reactive policy against the real settings API, controller, store and planner.

Only HA transport, persistence and charger boundaries are doubles; no live HA or
charger is used. These tests can also run in the isolated actual-module harness.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav.api import dashboard, morek_schedule, settings as settings_api
from custom_components.spotnav.api.plan_preview import encode_preview
from custom_components.spotnav.execution import auto_execution
from custom_components.spotnav.execution.auto_execution import AutoExecutor
from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.planning.auto_controller import AutoPlannerController, LiveVehicleFacts
from custom_components.spotnav.planning.auto_settings import AutoSettings, AutoSettingsStore, DRIVER_TARGET_SOC, TargetSocIntent
from custom_components.spotnav.planning.learned_energy import NOTHING_LEARNED
from custom_components.spotnav.planning.planner import FiscalChoice, calculate_plan
from custom_components.spotnav.vehicles.soc_estimate import SocReader

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_price_policy_guard import cap_request


async def _world(monkeypatch):
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.2] * 8, need=30)
    doc = request.documents[0]
    entry = SimpleNamespace(id=doc.area_id, tz=doc.tz, currency="EUR", major_unit="EUR", minor_unit="cent")
    area = SimpleNamespace(
        area_id=doc.area_id, generation=1, today_authority="listed", tomorrow_authority="not_listed",
        catalogue=entry, today_state="ready", tomorrow_state="unavailable", fetched_at=request.now,
        today=doc.day, tomorrow=doc.day + timedelta(days=1), state="waiting_for_tomorrow",
        today_snapshot=SimpleNamespace(document=doc, attempt_error=None),
        tomorrow_snapshot=SimpleNamespace(document=None, attempt_error=None),
    )
    hass = MagicMock()
    hass.async_create_task.side_effect = asyncio.create_task
    disk = SimpleNamespace(async_load=AsyncMock(return_value=None), async_save=AsyncMock())
    store = AutoSettingsStore(hass, store=disk)
    await store.async_load()
    initial = AutoSettings(
        area_id=doc.area_id, amps=16, driver=DRIVER_TARGET_SOC,
        target=TargetSocIntent(vehicle_id="veh-1", target_percent=80),
        soft_price_cap=.1, cap_price_basis="nord_pool", minimum_ready_by_soc=40,
        departure_enabled=False, max_periods=8,
    )
    await store.async_update("test", mutate=lambda _: initial)
    listeners = []

    async def subscribe(**kwargs):
        listeners.append(kwargs["listener"])
        return lambda: None

    manager = MagicMock()
    manager.area_snapshot.return_value = area
    manager.async_subscribe = subscribe
    facts = [LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=1, reported_capacity_kwh=60)]
    controller = AutoPlannerController(hass, "test", store, manager, vehicle_reader=lambda _: facts[0], now=lambda: request.now)
    monkeypatch.setattr(controller, "_notification_vehicle", lambda: (True, "veh-1"))
    monkeypatch.setattr(auto_controller, "effective_phases", lambda *_: 3)
    monkeypatch.setattr(auto_controller, "voltage_between_phases_v", lambda *_: 400)
    monkeypatch.setattr(auto_controller.hybrid_execution, "clear_hybrid_state", lambda *_: None)
    monkeypatch.setattr(controller, "_source", lambda: None)
    monkeypatch.setattr(controller, "_fiscal_for", lambda *_: FiscalChoice())
    monkeypatch.setattr(controller, "_learned_energy_for", lambda *_args, **_kw: NOTHING_LEARNED)
    monkeypatch.setattr(controller, "_plan_power_cap_kw", lambda *_: 6)
    for name in ("_arm_energy_watch", "_arm_departure", "_arm_charge_watch", "_arm_watch", "_cancel_wake"):
        monkeypatch.setattr(controller, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(settings_api, "lookup_charger", lambda *_: (entry, None))
    monkeypatch.setattr(settings_api, "domain_data", lambda _: SimpleNamespace(auto_store=store))
    monkeypatch.setattr(settings_api, "entry_source_for", lambda *_: None)
    monkeypatch.setattr(settings_api, "wire_offset", lambda *_: 0)
    monkeypatch.setattr(settings_api, "preview_for", lambda *_: controller)
    monkeypatch.setattr(settings_api, "refuse_amps_above_charger_range", lambda *_: None)
    monkeypatch.setattr(settings_api, "async_price_entry_from_settings", AsyncMock())
    monkeypatch.setattr(settings_api.vehicle_properties, "stored_properties", lambda *_: SimpleNamespace(target_percent=None))
    await controller._reconcile(store.settings("test"))  # noqa: SLF001
    return SimpleNamespace(hass=hass, store=store, controller=controller, listeners=listeners,
                           facts=facts, area=area, request=request)


async def _save(world, **changes):
    settings = world.store.settings("test")
    body = settings_api.encode_settings(settings)
    body.pop("revision")
    body.update(changes)
    await settings_api.async_update_settings(world.hass, "test", expected_revision=settings.revision, replacement=body)
    return world.controller.snapshot()


def test_settings_api_replans_and_preview_policy_matches_dashboard(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        initial = w.controller.snapshot()
        assert initial.proposal.exception_kwh == pytest.approx(10)
        assert initial.projection_soc == 25
        assert initial.projection_kwh_per_percent == pytest.approx(60 / 90)
        assert initial.projection_age_s == 1
        details = dashboard._proposal_section(SimpleNamespace(snapshot=initial, settings=None, area_entry=None))
        assert sum(row["energy_kwh"] for row in details["window_details"]) == pytest.approx(initial.proposal.delivered_kwh)
        assert sum(row["cost"] for row in details["window_details"]) == pytest.approx(initial.proposal.estimated_cost)
        initial_policy = encode_preview(initial, w.store.settings("test"))["price_policy"]
        assert {item["code"] for item in initial_policy["explanations"]} >= {"minimum_exception", "target_shortfall"}
        assert initial_policy["estimated_exception_cost"]["value"] == pytest.approx(2)

        minimum = await _save(w, minimum_ready_by_soc=35)
        assert minimum.proposal.exception_kwh == pytest.approx(10 / 1.5)
        cap = await _save(w, soft_price_cap=.3)
        assert cap.proposal.exception_kwh == 0
        assert cap.proposal.delivered_kwh > minimum.proposal.delivered_kwh
        target = settings_api.encoded_target(w.store.settings("test").target)
        target["target_percent"] = 40
        lowered = await _save(w, target=target)
        assert lowered.proposal.delivered_kwh == pytest.approx(10)
        local = w.request.now.astimezone(auto_controller.time_zones.require_zone(w.request.timezone))
        deadline = (local + timedelta(hours=1)).strftime("%H:%M")
        moved = await _save(w, departure_enabled=True, departure_time=deadline)
        assert moved.proposal.delivered_kwh == pytest.approx(6)
        assert moved.departure_at is not None

        # The existing two serializers consume exactly the same proposal facts.
        settings = w.store.settings("test")
        preview = encode_preview(moved, settings)["price_policy"]
        fresh_preview = encode_preview(await w.controller.async_preview(settings), settings)["price_policy"]
        assert fresh_preview == preview
        capture = SimpleNamespace(settings=settings, snapshot=moved,
                                  execution=SimpleNamespace(applied_identity=None, pending_identity=None))
        monkeypatch.setattr(dashboard, "_proposal_section", lambda _: None)
        monkeypatch.setattr(dashboard, "_installed_section", lambda _: None)
        assert dashboard.serialize_plan(capture)["price_policy"] == preview
        assert preview["estimated_plan_kwh"] == pytest.approx(moved.proposal.delivered_kwh)
        assert preview["estimated_plan_cost"]["value"] == pytest.approx(moved.proposal.estimated_cost)

    asyncio.run(run())


def test_independent_soc_and_price_events_change_policy(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        before = w.controller.snapshot()
        await w.controller._on_prices_changed(w.controller._subscription - 1)  # noqa: SLF001
        assert w.controller.snapshot().attempt == before.attempt
        # Exercise the real reader's notification threshold and callback independently
        # of the price subscription. Its storage and HA entity listeners are not needed here.
        reader = object.__new__(SocReader)
        reader._last_notified = 25  # noqa: SLF001
        reader._notify_next = False  # noqa: SLF001
        reader._arrival_cancel = None  # noqa: SLF001
        reader._arrival_watched = ()  # noqa: SLF001
        tasks = []
        reader.set_on_reading(lambda: tasks.append(asyncio.create_task(w.controller.async_recalculate())))
        reader.set_notify_every_reading(lambda: False)
        reader._tell(SimpleNamespace(soc_percent=25.5))  # noqa: SLF001
        assert not tasks  # legacy uncapped threshold is unchanged
        reader.set_notify_every_reading(lambda: True)
        w.facts[0] = replace(w.facts[0], soc_percent=25.5)
        reader._tell(SimpleNamespace(soc_percent=25.5))  # noqa: SLF001
        soc = await tasks.pop()
        assert soc.proposal.exception_kwh < before.proposal.exception_kwh
        assert encode_preview(soc, w.store.settings("test"))["price_policy"]["exception_kwh"] == pytest.approx(29 / 3)
        new_doc = replace(w.area.today_snapshot.document, prices=(.05,) * 8)
        w.area.today_snapshot.document = new_doc
        w.listeners[-1](w.area)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        price = w.controller.snapshot()
        assert price.proposal.exception_kwh == 0
        assert price.proposal.delivered_kwh > soc.proposal.delivered_kwh
        policy = encode_preview(price, w.store.settings("test"))["price_policy"]
        assert "minimum_exception" not in {item["code"] for item in policy["explanations"]}
        w.facts[0] = replace(w.facts[0], soc_age_s=10000)
        older = await w.controller.async_recalculate()
        policy = encode_preview(older, w.store.settings("test"))["price_policy"]
        assert policy["estimated_plan_kwh"] == pytest.approx(price.proposal.delivered_kwh)

    asyncio.run(run())


def test_newer_attempt_wins_during_slow_calculation(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        compute = w.controller._compute  # noqa: SLF001
        first = True

        async def delayed(settings, attempt):
            nonlocal first
            if first:
                first = False
                result = await compute(settings, attempt)
                entered.set()
                await release.wait()
                return result
            return await compute(settings, attempt)

        monkeypatch.setattr(w.controller, "_compute", delayed)
        old = asyncio.create_task(w.controller.async_recalculate())
        await entered.wait()
        w.facts[0] = replace(w.facts[0], soc_percent=39)
        new = asyncio.create_task(w.controller.async_recalculate())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(old, new)
        latest = w.controller.snapshot()
        assert latest.proposal.exception_kwh == pytest.approx(2 / 3)
        assert latest.attempt == w.controller._attempt  # noqa: SLF001
        assert w.store.proposal("test").settings_revision == latest.settings_revision

    asyncio.run(run())


def test_morek_preview_refuses_snapshot_while_new_calculation_runs(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        compute = w.controller._compute  # noqa: SLF001

        async def delayed(settings, attempt):
            entered.set()
            await release.wait()
            return await compute(settings, attempt)

        monkeypatch.setattr(w.controller, "_compute", delayed)
        monkeypatch.setattr(morek_schedule, "domain_data", lambda _: SimpleNamespace(auto_store=w.store))
        monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: w.controller)
        task = asyncio.create_task(w.controller.async_recalculate())
        await entered.wait()
        assert not w.controller.snapshot_is_current(w.controller.snapshot())
        with pytest.raises(morek_schedule.ScheduleRefused, match="no_current_plan"):
            morek_schedule._proposed_profile(w.hass, "test", w.request.now)  # noqa: SLF001
        release.set()
        await task
        assert w.controller.snapshot_is_current(w.controller.snapshot())

    asyncio.run(run())


def test_concurrent_settings_edit_cannot_publish_old_revision(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        old_revision = w.store.settings("test").revision
        entered, release = asyncio.Event(), asyncio.Event()
        compute = w.controller._compute  # noqa: SLF001
        first = True
        seen = []
        w.controller.add_listener(seen.append)

        async def delayed(settings, attempt):
            nonlocal first
            if first:
                first = False
                result = await compute(settings, attempt)
                entered.set()
                await release.wait()
                return result
            return await compute(settings, attempt)

        monkeypatch.setattr(w.controller, "_compute", delayed)
        old = asyncio.create_task(w.controller.async_recalculate())
        await entered.wait()
        edit = asyncio.create_task(_save(w, minimum_ready_by_soc=35))
        # Let the API write and its new calculation claim their attempt.
        while w.store.settings("test").revision == old_revision:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        seen.clear()
        release.set()
        await asyncio.gather(old, edit)
        latest = w.controller.snapshot()
        assert latest.settings_revision == old_revision + 1
        assert latest.proposal.exception_kwh == pytest.approx(10 / 1.5)
        assert all(snapshot.settings_revision == latest.settings_revision for snapshot in seen)
        assert w.store.proposal("test").settings_revision == latest.settings_revision

    asyncio.run(run())


def test_real_executor_rejects_older_inflight_attempt(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        charger = MagicMock()
        charger.entry_id = "test"
        charger.plan = None
        charger.target_stop_record = None
        executor = AutoExecutor(w.hass, charger, w.store, now=lambda: w.request.now)
        monkeypatch.setattr(auto_execution, "effective_phases", lambda *_: 3)
        monkeypatch.setattr(executor, "_may_apply", lambda *_: False)
        reconcile = AsyncMock(wraps=executor.async_reconcile)
        monkeypatch.setattr(executor, "async_reconcile", reconcile)
        w.controller._executor = executor  # noqa: SLF001
        entered, release = asyncio.Event(), asyncio.Event()
        compute = w.controller._compute  # noqa: SLF001
        first = True

        async def delayed(settings, attempt):
            nonlocal first
            result = await compute(settings, attempt)
            if first:
                first = False
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(w.controller, "_compute", delayed)
        old = asyncio.create_task(w.controller.async_recalculate())
        await entered.wait()
        w.facts[0] = replace(w.facts[0], soc_percent=39)
        new = asyncio.create_task(w.controller.async_recalculate())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(old, new)
        latest = w.controller.snapshot()
        assert latest.attempt == executor.attempt
        assert latest.proposal.exception_kwh == pytest.approx(2 / 3)
        assert reconcile.await_count == 1
        assert reconcile.await_args.kwargs["attempt"] == executor.attempt
        charger.async_install.assert_not_called()

    asyncio.run(run())


def test_price_event_invalidates_before_pause_lock(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        charger = MagicMock()
        charger.entry_id = "test"
        charger.plan = None
        charger.target_stop_record = None
        executor = AutoExecutor(w.hass, charger, w.store, now=lambda: w.request.now)
        monkeypatch.setattr(auto_execution, "effective_phases", lambda *_: 3)
        monkeypatch.setattr(executor, "_may_apply", lambda *_: False)
        reconcile = AsyncMock(wraps=executor.async_reconcile)
        monkeypatch.setattr(executor, "async_reconcile", reconcile)
        w.controller._executor = executor  # noqa: SLF001
        computing, finish_old = asyncio.Event(), asyncio.Event()
        settling, finish_settle = asyncio.Event(), asyncio.Event()
        compute = w.controller._compute  # noqa: SLF001
        first = True

        async def delayed(settings, attempt):
            nonlocal first
            result = await compute(settings, attempt)
            if first:
                first = False
                computing.set()
                await finish_old.wait()
            return result

        async def settle():
            settling.set()
            await finish_settle.wait()
            return False

        monkeypatch.setattr(w.controller, "_compute", delayed)
        monkeypatch.setattr(executor, "async_settle_pause", settle)
        old = asyncio.create_task(w.controller.async_recalculate())
        await computing.wait()
        event = asyncio.create_task(w.controller._on_prices_changed(w.controller._subscription))  # noqa: SLF001
        await settling.wait()
        finish_old.set()
        await old
        reconcile.assert_not_awaited()
        w.area.today_snapshot.document = replace(w.area.today_snapshot.document, prices=(.05,) * 8)
        finish_settle.set()
        await event
        assert reconcile.await_count == 1
        assert w.controller.snapshot().proposal.exception_kwh == 0

    asyncio.run(run())


def test_empty_missing_and_unavailable_are_not_measured_energy(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.facts[0] = replace(w.facts[0], soc_percent=45)
        empty = await w.controller.async_recalculate()
        policy = encode_preview(empty, w.store.settings("test"))["price_policy"]
        codes = {line["code"] for line in policy["explanations"]}
        assert empty.reason == "no_eligible_energy"
        assert {"minimum_covered", "target_shortfall"} <= codes
        assert policy["estimated_plan_kwh"] == 0
        assert policy["estimated_exception_cost"]["value"] == 0

        w.facts[0] = replace(w.facts[0], soc_percent=85)
        met = await w.controller.async_recalculate()
        met_policy = encode_preview(met, w.store.settings("test"))["price_policy"]
        assert met_policy["explanations"] == [{"code": "target_met"}]

        w.facts[0] = replace(w.facts[0], soc_percent=None)
        missing = await w.controller.async_recalculate()
        policy = encode_preview(missing, w.store.settings("test"))["price_policy"]
        assert policy["reason"] == "target_soc_unknown"
        assert policy["explanations"] == [{"code": "unavailable", "reason": "target_soc_unknown", "missing": ["live_soc"]}]
        assert policy["estimated_plan_kwh"] is None and policy["estimated_plan_cost"] is None

        w.facts[0] = replace(w.facts[0], soc_percent=25)
        w.area.today_state = "stale"
        w.listeners[-1](w.area)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        stale = w.controller.snapshot()
        policy = encode_preview(stale, w.store.settings("test"))["price_policy"]
        assert policy["reason"] == "price_data_stale"
        assert policy["estimated_plan_kwh"] is None
        mismatch = encode_preview(stale, replace(w.store.settings("test"), revision=999))["price_policy"]
        assert mismatch["reason"] is None and mismatch["explanations"] == [{"code": "recalculating"}]

    asyncio.run(run())


def test_reader_source_loss_notifies_once_on_transition():
    reader = object.__new__(SocReader)
    reader._note_source_state = MagicMock()  # noqa: SLF001
    reader.read = MagicMock(return_value=None)
    reader._watch_vehicle = "veh-1"  # noqa: SLF001
    reader._watched_report_time = None  # noqa: SLF001
    reader._last_reading = None  # noqa: SLF001
    reader._last_signal_reading = None  # noqa: SLF001
    reader._anchor = None  # noqa: SLF001
    lost = []
    reader.set_on_source_unavailable(lambda: lost.append(True))
    reader._on_source_changed(SimpleNamespace(data={  # noqa: SLF001
        "entity_id": "sensor.soc", "old_state": SimpleNamespace(state="25"), "new_state": SimpleNamespace(state="unavailable"),
    }))
    reader._on_source_changed(SimpleNamespace(data={  # noqa: SLF001
        "entity_id": "sensor.soc", "old_state": SimpleNamespace(state="unavailable"), "new_state": SimpleNamespace(state="unknown"),
    }))
    assert lost == [True]


def test_partial_exception_cost_uses_actual_selected_duration(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        request = cap_request(w.request, [.20, .05], need=10)
        request = replace(request, minimum_energy_kwh=2.1)
        proposal = calculate_plan(request)
        snapshot = replace(w.controller.snapshot(), proposal=proposal)
        policy = encode_preview(snapshot, w.store.settings("test"))["price_policy"]
        assert policy["exception_kwh"] == pytest.approx(.6)
        assert policy["estimated_exception_cost"]["value"] == pytest.approx(.12)
        assert policy["estimated_plan_cost"]["value"] == pytest.approx(.195)
        assert policy["estimated_plan_kwh"] == pytest.approx(2.1)
        failed = encode_preview(replace(snapshot, last_error_code="proposal_not_saved"), w.store.settings("test"))
        assert failed["price_policy"]["error"] == "proposal_not_saved"
        assert {"code": "error", "reason": "proposal_not_saved"} in failed["price_policy"]["explanations"]

    asyncio.run(run())
