"""Partial published prices through actual planner and schedule admission."""

import asyncio
from dataclasses import replace
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api.price_policy import encode_price_policy
from custom_components.spotnav.execution import morek_worker
from custom_components.spotnav.planning.planner import calculate_plan, price_gap
from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.pricing.relay_contract import PriceInterval
from custom_components.spotnav import time_zones

from .planning import build_request, fixture_payload, parse_documents
from .test_morek_worker import drain, real_admission_planner_worker
from .test_planner_price_policy_guard import cap_request
from .test_stage_13_reactive import _world


def test_partial_minimum_waits_or_uses_only_urgent_exception():
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.05, .20, .30, .30], need=6)
    request = replace(request, minimum_energy_kwh=3, partial_recheck_at=request.now + timedelta(minutes=30))
    # Plenty of time after the next re-evaluation, including the known cheap interval.
    relaxed = calculate_plan(replace(request, window_end=request.now + timedelta(hours=8)))
    assert relaxed.exception_kwh == 0
    assert relaxed.delivered_kwh == pytest.approx(1.5)
    # At a tight deadline only a bounded portion of minimum needs an exception.
    urgent = calculate_plan(replace(request, window_end=request.now + timedelta(minutes=45)))
    assert 0 < urgent.exception_kwh < 1.5
    assert urgent.delivered_kwh <= 3
    assert urgent.policy_shortfall_kwh > 0


def test_partial_without_cheap_window_is_not_automatically_a_minimum_exception():
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.20] * 4, need=6)
    request = replace(request, minimum_energy_kwh=3, partial_recheck_at=request.now + timedelta(minutes=30),
                      window_end=request.now + timedelta(hours=8))
    result = calculate_plan(request)
    assert result.reason == "no_eligible_energy"
    assert not result.periods and result.minimum_shortfall_kwh == 3


def test_internal_gap_is_reported_and_never_bridged():
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.05], need=3)
    doc = request.documents[0]
    later = replace(doc, start_instant=doc.start_instant + timedelta(minutes=30), prices=(.05,))
    request = replace(request, documents=(doc, later), window_end=request.now + timedelta(minutes=45),
                      partial_recheck_at=request.now + timedelta(hours=1), minimum_energy_kwh=0)
    gap = price_gap(request)
    assert gap is not None and gap.missing_from == request.now + timedelta(minutes=15)
    result = calculate_plan(request)
    assert result.periods == ((request.now, request.now + timedelta(minutes=15)),
                              (request.now + timedelta(minutes=30), request.now + timedelta(minutes=45)))


def test_capped_fractional_deadline_requires_its_own_price():
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.05], need=1)
    request = replace(request, window_end=request.now + timedelta(minutes=20))
    gap = price_gap(request)
    assert gap is not None and gap.missing_from == request.now + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_uncapped_partial_wait_and_required_purchase(monkeypatch):
    world = await _world(monkeypatch)
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [.05] * 16, need=3)
    request = replace(request, soft_price_cap=None, cap_price_basis=None, departure=time(8), window_end=None)
    publication = request.now + timedelta(hours=2)
    monkeypatch.setattr(auto_controller, "expected_publication", lambda *_: publication)
    monkeypatch.setattr(world.controller, "_arm_wake", lambda *_: None)
    refusal = calculate_plan(request)
    assert refusal.reason == "insufficient_price_horizon"
    waited = world.controller._plan_while_prices_are_missing(request, refusal, world.area.catalogue, request.now)
    assert waited[2][0] == "waiting_for_publication"
    urgent = replace(request, requested_kwh=33)
    bought = world.controller._plan_while_prices_are_missing(urgent, calculate_plan(urgent),
                                                              world.area.catalogue, urgent.now)
    assert bought[1]["price_wait_action"] == "buy_now"
    assert bought[0].has_plan and not bought[0].unpriced
    assert bought[0].requested_kwh < urgent.requested_kwh


@pytest.mark.asyncio
async def test_partial_timer_recalculates_when_publication_is_delayed(monkeypatch):
    world = await _world(monkeypatch)
    doc = world.area.today_snapshot.document
    now = [doc.start_instant + timedelta(hours=14)]
    world.controller._now = lambda: now[0]
    world.area.today_snapshot.document = replace(doc, prices=(.05,) * 96)
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    callbacks = []
    world.controller._manager.schedule_at = lambda when, callback: (callbacks.append((when, callback)) or (lambda: None))
    await world.store.async_update("test", mutate=lambda s: replace(s, departure_enabled=True, departure=time(8)))
    initial = await world.controller.async_recalculate()
    assert initial.proposal.price_coverage_end is not None
    when, callback = callbacks[-1]
    assert timedelta(0) < when - now[0] <= timedelta(minutes=15, seconds=2)
    published = asyncio.Event()
    remove = world.controller.add_publication_listener(lambda _: published.set())
    published.clear()
    now[0] = when
    callback(when)
    await asyncio.wait_for(published.wait(), 2)
    remove()
    assert world.controller.snapshot().attempt > initial.attempt
    assert callbacks[-1][0] > when


@pytest.mark.asyncio
async def test_empty_partial_plan_waits_and_full_cheap_target_stays_provisional(monkeypatch):
    world = await _world(monkeypatch)
    doc = world.area.today_snapshot.document
    world.controller._now = lambda: doc.start_instant + timedelta(hours=10, minutes=48)
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    world.area.today_snapshot.document = replace(doc, prices=(.3,) * 96)
    await world.store.async_update("test", mutate=lambda s: replace(s, departure_enabled=True, departure=time(8)))
    waiting = await world.controller.async_recalculate()
    assert waiting.state == "waiting_for_publication"
    assert waiting.proposal.reason == "no_eligible_energy"
    assert waiting.proposal.minimum_shortfall_kwh > 0
    assert waiting.proposal.price_coverage_end is not None
    world.area.today_snapshot.document = replace(doc, prices=(.05,) * 96)
    await world.store.async_update("test", mutate=lambda s: replace(s, target=replace(s.target, target_percent=40)))
    covered = await world.controller.async_recalculate()
    assert covered.proposal.policy_shortfall_kwh == pytest.approx(0)
    assert covered.proposal.price_coverage_end is not None


@pytest.mark.asyncio
async def test_uncapped_necessary_purchase_passes_real_morek_path(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    doc = world.area.today_snapshot.document
    now = doc.start_instant + timedelta(hours=10, minutes=48)
    values = [.05] * 96
    step = timedelta(minutes=doc.resolution_minutes)
    intervals = tuple(PriceInterval.from_instants(doc.start_instant + step * i, doc.start_instant + step * (i + 1),
                      zone=time_zones.require_zone(doc.tz), eur_per_kwh=value)
                      for i, value in enumerate(values))
    world.area.today_snapshot.document = replace(doc, prices=tuple(values), intervals=intervals)
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    world.controller._now = lambda: now
    world.controller._schedule_owned = AsyncMock(return_value=True)
    world.controller._manager.async_profile = AsyncMock(return_value=None)  # no history
    world.facts[0] = replace(world.facts[0], soc_percent=0, reported_capacity_kwh=100)
    class Clock:
        now = staticmethod(lambda _: now)
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    await world.store.async_update("test", mutate=lambda s: replace(s, departure_enabled=True, departure=time(8),
                                   soft_price_cap=None, cap_price_basis=None, minimum_ready_by_soc=None))
    snapshot = await world.controller.async_recalculate()
    assert snapshot.price_wait == "buy_now"
    assert snapshot.proposal.price_coverage_end is not None
    assert snapshot.proposal.ends_at_need
    assert snapshot.proposal.policy_shortfall_kwh > 0
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    w.worker.close()


@pytest.mark.asyncio
async def test_provisional_published_plan_reaches_real_admission(monkeypatch, tmp_path):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    doc = world.area.today_snapshot.document
    now = doc.start_instant + timedelta(hours=10, minutes=48)
    prices = [.25] * 96
    prices[46:60] = [.05] * 14
    def priced_document(start, values, day):
        step = timedelta(minutes=doc.resolution_minutes)
        intervals = tuple(PriceInterval.from_instants(start + step * i, start + step * (i + 1),
                          zone=time_zones.require_zone(doc.tz), eur_per_kwh=value)
                          for i, value in enumerate(values))
        return replace(doc, day=day, start=start.astimezone(time_zones.require_zone(doc.tz)),
                       start_instant=start, prices=tuple(values), intervals=intervals)
    world.area.today_snapshot.document = priced_document(doc.start_instant, prices, doc.day)
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    world.controller._now = lambda: now
    class Clock:
        now = staticmethod(lambda _: now)
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    await world.store.async_update("test", mutate=lambda s: replace(s, departure_enabled=True, departure=time(8)))
    snapshot = await world.controller.async_recalculate()
    proposal = snapshot.proposal
    assert proposal and proposal.has_plan
    assert proposal.price_coverage_end is not None
    assert proposal.exception_kwh == 0
    assert proposal.shown_periods[0][0] >= doc.start_instant + timedelta(hours=11, minutes=30)
    assert proposal.shown_periods[-1][1] <= doc.start_instant + timedelta(hours=15)
    assert encode_price_policy(world.store.settings("test"), snapshot)["provisional"]
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    payload = w.point.call.await_args.args[0].payload
    periods = payload["cs_charging_profiles"]["chargingSchedule"]["chargingSchedulePeriod"]
    assert periods[-1]["limit"] == 0
    count = w.point.call.await_count
    await world.controller.async_recalculate()
    await drain(w.worker)
    assert w.point.call.await_count == count
    # A real price subscription event makes tomorrow's published data authoritative.
    tomorrow = priced_document(doc.start_instant + timedelta(days=1), [.01] * 96, doc.day + timedelta(days=1))
    world.area.tomorrow_snapshot.document = tomorrow
    world.area.tomorrow_state = "ready"
    world.area.tomorrow_authority = "listed"
    world.area.state = "ready"
    world.facts[0] = replace(world.facts[0], soc_percent=35)
    changed = asyncio.Event()
    remove = world.controller.add_publication_listener(lambda _: changed.set())
    changed.clear()
    world.listeners[-1](world.area)
    await asyncio.wait_for(changed.wait(), 2)
    remove()
    await drain(w.worker)
    assert world.controller.snapshot().proposal.price_coverage_end is None
    assert w.point.call.await_count == count + 1, w.worker.reason
    await world.controller.async_recalculate()
    await drain(w.worker)
    assert w.point.call.await_count == count + 1
    w.worker.close()
