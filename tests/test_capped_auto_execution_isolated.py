"""Actual Auto reconciliation methods with mocked charger boundaries; no HA server."""

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav.execution import auto_execution
from custom_components.spotnav.execution.auto_execution import AutoExecutor, application_for
from custom_components.spotnav.execution.controller import ChargingController, ChargingPlan, stored_plan
from custom_components.spotnav.planning.auto_settings import AutoSettings
from custom_components.spotnav.planning.auto_settings import TargetSocIntent, DRIVER_TARGET_SOC
from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.planning.auto_controller import AutoPlannerController, LiveVehicleFacts
from custom_components.spotnav.planning.learned_energy import NOTHING_LEARNED
from custom_components.spotnav.planning.planner import FiscalChoice
from custom_components.spotnav.api.plan_preview import encode_preview

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_price_policy_guard import cap_request
from custom_components.spotnav.planning.planner import calculate_plan


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def make_executor(monkeypatch, *, fail=False):
    settings = AutoSettings(revision=4, area_id="SE4", amps=16, soft_price_cap=.1, cap_price_basis="nord_pool")
    store = MagicMock()
    store.settings.return_value = settings
    controller = MagicMock()
    controller.entry_id = "test"
    controller.plan = ChargingPlan(
        start=NOW.isoformat(), end=(NOW + timedelta(hours=1)).isoformat(), amps=16,
        auto_identity="a" * 32, auto_settings_revision=4, auto_price_identity="price",
    )

    async def clear():
        if fail:
            raise RuntimeError("synthetic failure")
        controller.plan = None
        return True

    controller.async_end_superseded_plan = AsyncMock(side_effect=clear)
    controller.add_charge_state_listener.return_value = lambda: None
    executor = AutoExecutor(MagicMock(), controller, store, now=lambda: NOW)
    executor.begin_attempt()
    executor._pending = MagicMock()  # noqa: SLF001 - exercise actual pending invalidation
    monkeypatch.setattr(auto_execution, "effective_phases", lambda *_args: 3)
    return executor, controller, settings


@pytest.mark.parametrize("state", ["nothing_to_charge", "planning_unavailable", "waiting_for_prices"])
def test_empty_or_unavailable_stands_down_actual_auto_plan(monkeypatch, state):
    executor, controller, settings = make_executor(monkeypatch)
    snapshot = SimpleNamespace(proposal=None, state=state)
    result = asyncio.run(executor.async_reconcile(settings, snapshot, attempt=executor.attempt))
    assert result is None and controller.plan is None
    controller.async_end_superseded_plan.assert_awaited_once()
    assert executor.pending is None and executor.last_error is None


def test_failed_stand_down_is_visible_and_retryable(monkeypatch):
    executor, controller, settings = make_executor(monkeypatch, fail=True)
    result = asyncio.run(executor.async_reconcile(settings, SimpleNamespace(proposal=None), attempt=executor.attempt))
    assert result is not None and controller.plan is not None
    assert executor.last_error == "policy_stand_down_failed"
    assert executor.execution_state() == "execution_error"
    assert executor.superseded_by_wait()
    assert executor._clear_waiting == executor.attempt  # noqa: SLF001
    async def succeeding_clear():
        controller.plan = None
        return True
    controller.async_end_superseded_plan.side_effect = succeeding_clear
    asyncio.run(executor.async_clear_superseded_plan())
    assert controller.plan is None and executor.last_error is None


def test_stale_attempt_cannot_clear_newer_plan(monkeypatch):
    executor, controller, settings = make_executor(monkeypatch)
    old = executor.attempt
    executor.begin_attempt()
    asyncio.run(executor.async_reconcile(settings, SimpleNamespace(proposal=None), attempt=old))
    assert controller.plan is not None
    controller.async_end_superseded_plan.assert_not_awaited()


def test_nonempty_cap_replaces_active_plan_without_deferring(monkeypatch):
    executor, controller, settings = make_executor(monkeypatch)
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    proposal = calculate_plan(cap_request(base, [.1, .2], need=1))
    snapshot = SimpleNamespace(
        proposal=proposal, state="proposal_ready", last_error_code=None, area_id="SE4", price_identity="prices",
        price_revision=None, departure_at=None, room_limited=False,
    )
    async def install(plan):
        controller.plan = plan
    controller.async_install = AsyncMock(side_effect=install)
    monkeypatch.setattr(executor, "_may_apply", lambda *_: True)
    monkeypatch.setattr(executor, "_prices_still_live", lambda *_: True)
    result = asyncio.run(executor.async_reconcile(settings, snapshot, attempt=executor.attempt))
    controller.async_end_superseded_plan.assert_awaited_once()
    controller.async_install.assert_awaited_once()
    assert result is not None and result.plan.strict_windows
    assert tuple(result.plan.windows) == proposal.periods
    assert executor.pending is None


def test_failed_strict_install_does_not_leave_old_future_windows(monkeypatch):
    executor, controller, settings = make_executor(monkeypatch)
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    proposal = calculate_plan(cap_request(base, [.1, .2], need=1))
    snapshot = SimpleNamespace(
        proposal=proposal, state="proposal_ready", last_error_code=None, area_id="SE4", price_identity="prices",
        price_revision=None, departure_at=None, room_limited=False,
    )
    controller.async_install = AsyncMock(side_effect=RuntimeError("synthetic install failure"))
    monkeypatch.setattr(executor, "_may_apply", lambda *_: True)
    monkeypatch.setattr(executor, "_prices_still_live", lambda *_: True)
    monkeypatch.setattr(executor, "window_charging_now", lambda: False)
    result = asyncio.run(executor.async_reconcile(settings, snapshot, attempt=executor.attempt))
    assert result is None and controller.plan is None and executor.pending is None
    assert executor.last_error == "install_failed"


def test_exact_periods_are_applied_and_strict_marker_persists():
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.1, .2], need=1)
    proposal = calculate_plan(request)
    settings = AutoSettings(revision=4, area_id="SE4", amps=16, soft_price_cap=.1, cap_price_basis="nord_pool")
    snapshot = SimpleNamespace(
        proposal=proposal, state="proposal_ready", last_error_code=None, area_id="SE4", price_identity="prices",
        price_revision=None, departure_at=None, room_limited=False,
    )
    application = application_for(settings, snapshot, 3)
    assert application is not None and application.plan.strict_windows
    assert tuple(application.plan.windows) == proposal.periods == proposal.shown_periods
    assert stored_plan(asdict(application.plan)).strict_windows
    legacy = asdict(application.plan)
    del legacy["strict_windows"]
    assert not stored_plan(legacy).strict_windows


def test_strict_vehicle_limit_never_requests_top_off():
    plan = ChargingPlan(start=NOW.isoformat(), end=(NOW + timedelta(hours=1)).isoformat(), amps=16,
                        strict_windows=True, to_vehicle_limit=True)
    controller = SimpleNamespace(plan=plan)
    assert ChargingController._top_off_wanted(controller) is None  # noqa: SLF001


def test_strict_need_met_uses_owned_stop_not_leave_to_car():
    plan = ChargingPlan(start=NOW.isoformat(), end=(NOW + timedelta(hours=1)).isoformat(), amps=16,
                        strict_windows=True, to_vehicle_limit=True)
    controller = SimpleNamespace(plan=plan, _lock=asyncio.Lock(), _need_met_locked=AsyncMock(return_value=True))
    assert asyncio.run(ChargingController.async_end_plan_need_met(controller))
    controller._need_met_locked.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("owner", ["manual", "min_soc"])
def test_actual_superseded_plan_does_not_stop_non_plan_owner(owner):
    plan = ChargingPlan(start=NOW.isoformat(), end=(NOW + timedelta(hours=1)).isoformat(), amps=16)
    runner = MagicMock()
    controller = SimpleNamespace(
        plan=plan, _lock=asyncio.Lock(), _owner_origin=owner, _control_on=True,
        balancing_holds=lambda _: False, _runner=runner, _end_plan_locked=AsyncMock(),
        _stop_locked=AsyncMock(),
    )
    assert asyncio.run(ChargingController.async_end_superseded_plan(controller))
    controller._end_plan_locked.assert_awaited_once()  # noqa: SLF001
    controller._stop_locked.assert_not_awaited()  # noqa: SLF001


def test_actual_superseded_plan_stops_owned_charge():
    plan = ChargingPlan(start=NOW.isoformat(), end=(NOW + timedelta(hours=1)).isoformat(), amps=16)
    runner = MagicMock()
    runner.verdict.return_value = frozenset({("stop", "superseded")})
    controller = SimpleNamespace(
        plan=plan, entry_id="test", _lock=asyncio.Lock(), _owner_origin="plan_window", _control_on=True,
        _runner=runner, _core_facts=MagicMock(return_value={}), _core_end_event=MagicMock(),
        _core_stop_outcome=MagicMock(), _stop_locked=AsyncMock(),
    )
    async def stop(**_kwargs):
        controller.plan = None
    controller._stop_locked.side_effect = stop  # noqa: SLF001
    assert asyncio.run(ChargingController.async_end_superseded_plan(controller))
    controller._stop_locked.assert_awaited_once_with(clear_schedule=True)  # noqa: SLF001


def test_saved_capped_settings_reach_real_calculation_and_preview(monkeypatch):
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.2] * 8, need=30)
    doc = request.documents[0]
    settings = AutoSettings(
        revision=4, area_id=doc.area_id, amps=16, driver=DRIVER_TARGET_SOC,
        target=TargetSocIntent(vehicle_id="veh-1", target_percent=80),
        soft_price_cap=.1, cap_price_basis="nord_pool", minimum_ready_by_soc=40,
        departure_enabled=False, max_periods=8,
    ).validated()
    settings = AutoSettings.from_stored(settings.as_dict())
    entry = SimpleNamespace(id=doc.area_id, tz=doc.tz, currency="EUR", major_unit="EUR", minor_unit="cent")
    area = SimpleNamespace(
        catalogue=entry, today_state="ready", tomorrow_state="unavailable", fetched_at=request.now,
        today=doc.day, tomorrow=doc.day + timedelta(days=1), state="ready",
        today_snapshot=SimpleNamespace(document=doc), tomorrow_snapshot=SimpleNamespace(document=None),
    )
    manager = MagicMock()
    manager.area_snapshot.return_value = area
    store = MagicMock()
    store.settings.return_value = settings
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=1, reported_capacity_kwh=60)
    controller = AutoPlannerController(MagicMock(), "test", store, manager,
                                       vehicle_reader=lambda _: facts, now=lambda: request.now)
    monkeypatch.setattr(auto_controller, "effective_phases", lambda *_: 3)
    monkeypatch.setattr(auto_controller, "voltage_between_phases_v", lambda *_: 400)
    monkeypatch.setattr(controller, "_fiscal_for", lambda *_: FiscalChoice())
    monkeypatch.setattr(controller, "_learned_energy_for", lambda *_args, **_kw: NOTHING_LEARNED)
    monkeypatch.setattr(controller, "_plan_power_cap_kw", lambda *_: 6)
    snapshot = asyncio.run(controller._compute_plan(store.settings("test"), 1, {}, preview=True))  # noqa: SLF001
    assert snapshot.state == "proposal_ready", snapshot.reason
    assert snapshot.proposal.requested_kwh == pytest.approx(33 / .9)
    assert snapshot.proposal.exception_kwh == pytest.approx(10)
    encoded = encode_preview(snapshot, settings)
    assert encoded["price_policy"]["basis"] == "nord_pool"
    assert encoded["price_policy"]["exception_kwh"] == pytest.approx(10)
    assert encoded["plan"]["periods"]

    # No vehicle evidence is used to create an exception for manual kWh.
    manual = replace(settings, driver="manual_kwh", requested_kwh=3)
    controller._vehicle_reader = None  # noqa: SLF001
    monkeypatch.setattr(controller, "_manual_kwh_remaining", AsyncMock(
        return_value=auto_controller._EnergyResolution(kwh=3, delivered_energy_trustworthy=False),  # noqa: SLF001
    ))
    monkeypatch.setattr(controller, "_capped_by_room", lambda _settings, resolved: resolved)
    empty = asyncio.run(controller._compute_plan(manual, 2, {}, preview=True))  # noqa: SLF001
    assert empty.state == "nothing_to_charge" and empty.reason == "no_eligible_energy"
    assert not empty.proposal.periods and empty.proposal.exception_kwh == 0
    empty_encoded = encode_preview(empty, manual)
    assert empty_encoded["plan"] is None
    assert empty_encoded["price_policy"]["target_shortfall_kwh"] == pytest.approx(3)

    # An expired published horizon cannot invoke unpriced or history fallback.
    controller._vehicle_reader = lambda _: facts  # noqa: SLF001
    controller._now = lambda: request.now + timedelta(hours=3)  # noqa: SLF001
    unpriced = MagicMock(side_effect=AssertionError("unpriced fallback"))
    monkeypatch.setattr(auto_controller, "plan_unpriced", unpriced)
    unavailable = asyncio.run(controller._compute_plan(settings, 3, {}, preview=True))  # noqa: SLF001
    assert unavailable.reason == "insufficient_price_horizon"
    assert not unavailable.proposal.periods and not unavailable.proposal.unpriced
    unpriced.assert_not_called()
