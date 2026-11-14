"""Stage 16.2: a degraded aggregate price state (tomorrow impaired) dispatches only on valid listed today coverage.

Real planner, worker and admission path (`real_admission_planner_worker`); doubles are the HA transport, stored
settings and vehicle facts. No live Home Assistant, charger or deployment; an accepted upload is never physical flow.
"""

import asyncio
from dataclasses import replace
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav import time_zones
from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.api.price_policy import encode_price_policy
from custom_components.spotnav.execution import morek_worker
from custom_components.spotnav.pricing.relay_contract import PriceInterval

from .test_morek_worker import drain, real_admission_planner_worker


def _document(doc, start, values, day):
    step = timedelta(minutes=doc.resolution_minutes)
    intervals = tuple(PriceInterval.from_instants(start + step * i, start + step * (i + 1),
                      zone=time_zones.require_zone(doc.tz), eur_per_kwh=value) for i, value in enumerate(values))
    return replace(doc, day=day, start=start.astimezone(time_zones.require_zone(doc.tz)), start_instant=start,
                   prices=tuple(values), intervals=intervals)


async def _world(monkeypatch, tmp_path, *, area_state, tomorrow_state, tomorrow_authority, tomorrow_doc=None):
    w, world, _ = await real_admission_planner_worker(monkeypatch, tmp_path)
    doc = world.area.today_snapshot.document
    now = doc.start_instant + timedelta(hours=10, minutes=48)
    prices = [.25] * 96
    prices[46:60] = [.05] * 14
    world.area.today_snapshot.document = _document(doc, doc.start_instant, prices, doc.day)
    if tomorrow_doc is not None:
        world.area.tomorrow_snapshot.document = _document(
            doc, doc.start_instant + timedelta(days=1), tomorrow_doc, doc.day + timedelta(days=1))
    world.area.state = area_state
    world.area.tomorrow_state = tomorrow_state
    world.area.tomorrow_authority = tomorrow_authority
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    world.controller._now = lambda: now

    class Clock:
        now = staticmethod(lambda _: now)
    monkeypatch.setattr(morek_worker, "datetime", Clock)
    world.controller._schedule_owned = AsyncMock(return_value=True)
    world.controller._manager.async_profile = AsyncMock(return_value=None)
    await world.store.async_update("test", mutate=lambda s: replace(
        s, departure_enabled=True, departure=time(8), soft_price_cap=None, cap_price_basis=None,
        minimum_ready_by_soc=None))
    await world.controller.async_recalculate()  # warms the lazily loaded learning flag so the evidence is stable
    return w, world, now


@pytest.mark.asyncio
@pytest.mark.parametrize("tomorrow_authority", ["unknown", "listed"])
async def test_degraded_only_by_tomorrow_reaches_the_wire_once_on_valid_today_coverage(
        monkeypatch, tmp_path, tomorrow_authority):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="unavailable",
                                 tomorrow_authority=tomorrow_authority)
    snapshot = await world.controller.async_recalculate()
    assert snapshot.price_state == "degraded"
    assert snapshot.proposal.has_plan and snapshot.proposal.price_coverage_end is not None
    assert world.controller.morek_price_blocker(snapshot, now) is None
    assert world.controller.morek_plan_blocker(snapshot, now) is None
    # The manual path is the same judgement: it builds the proposal instead of refusing a degraded state.
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    _, proposal = morek_schedule._validated_proposal(world.hass, "test", now)
    assert proposal is snapshot.proposal
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    count = w.point.call.await_count
    await world.controller.async_recalculate()  # identical publication state and SOC: nothing is sent again
    await drain(w.worker)
    assert w.point.call.await_count == count
    policy = encode_price_policy(world.store.settings("test"), world.controller.snapshot())
    assert policy["provisional"] and policy["tomorrow_pending"] and policy["price_state"] == "degraded"
    w.worker.close()


@pytest.mark.asyncio
async def test_a_stale_tomorrow_is_never_a_price_the_plan_is_bought_from(monkeypatch, tmp_path):
    # Tomorrow's last-good document is cheap but stale: planning ignores it, so the plan is dispatchable from today.
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="stale",
                                 tomorrow_authority="listed", tomorrow_doc=[.001] * 96)
    snapshot = await world.controller.async_recalculate()
    day_end = world.area.today_snapshot.document.start_instant + timedelta(hours=24)
    assert snapshot.proposal.has_plan
    assert all(end <= day_end for _, end in snapshot.proposal.shown_periods)
    assert snapshot.proposal.price_coverage_end == day_end
    assert world.controller.morek_price_blocker(snapshot, now) is None
    # A plan that did use the stale day would not pass: the same coverage judgement refuses it.
    leaking = replace(snapshot, proposal=replace(
        snapshot.proposal, periods=((day_end - timedelta(minutes=30), day_end + timedelta(minutes=30)),),
        exact_periods=True))
    assert world.controller.morek_price_blocker(leaking, now) == "price_coverage_unavailable"
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1, w.worker.reason
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stale_today", "gapped_today", "today_unlisted", "unusable_state"])
async def test_stale_gapped_or_untrusted_used_prices_still_block(monkeypatch, tmp_path, change):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    snapshot = await world.controller.async_recalculate()
    assert world.controller.morek_price_blocker(snapshot, now) is None
    area = world.area
    if change == "stale_today":
        area.today_state, area.state = "stale", "stale"
    elif change == "today_unlisted":
        area.today_authority = "unknown"
    elif change == "unusable_state":
        area.state = "incomplete"
    else:
        doc = area.today_snapshot.document
        area.today_snapshot.document = replace(doc, intervals=doc.intervals[:50])  # the plan's minutes lose cover
    judged = replace(snapshot, morek_price_evidence=world.controller._morek_price_evidence(area))
    assert world.controller.morek_price_blocker(judged, now) in (
        "prices_stale_or_unavailable", "price_coverage_unavailable")
    # A price change after the calculation is the existing `price_inputs_changed` hold (recalculation follows).
    assert world.controller.morek_price_blocker(snapshot, now) == "price_inputs_changed"
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_manual_path_refuses_what_the_shared_judgement_refuses(monkeypatch, tmp_path):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    await world.controller.async_recalculate()
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    world.controller.morek_price_blocker = lambda *_: "price_coverage_unavailable"
    with pytest.raises(morek_schedule.ScheduleRefused) as refused:
        morek_schedule._validated_proposal(world.hass, "test", now)
    assert refused.value.code == "price_coverage_unavailable"
    w.worker.close()


@pytest.mark.asyncio
async def test_tomorrow_arriving_replans_from_the_better_data_and_sends_at_most_once(monkeypatch, tmp_path):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    first = await world.controller.async_recalculate()
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    doc = world.area.today_snapshot.document
    world.area.tomorrow_snapshot.document = _document(
        doc, doc.start_instant + timedelta(days=1), [.25] * 96, doc.day + timedelta(days=1))
    world.area.tomorrow_state, world.area.tomorrow_authority, world.area.state = "ready", "listed", "ready"
    changed = asyncio.Event()
    remove = world.controller.add_publication_listener(lambda _: changed.set())
    world.listeners[-1](world.area)
    await asyncio.wait_for(changed.wait(), 2)
    remove()
    later = await world.controller.async_recalculate()
    await drain(w.worker)
    assert later.price_state == "ready" and later.proposal.price_coverage_end is None
    count = w.point.call.await_count
    assert count == (1 if later.proposal.shown_periods == first.proposal.shown_periods else 2), w.worker.reason
    await world.controller.async_recalculate()  # identical publication and SOC: nothing more is sent
    await drain(w.worker)
    assert w.point.call.await_count == count
    w.worker.close()


def _manual_code(monkeypatch, world, snapshot, now):
    """What manual Send/preview answers for exactly this snapshot (`None` when it admits the proposal)."""
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    monkeypatch.setattr(world.controller, "snapshot", lambda: snapshot)
    # Freshness is a separate guard; isolate the price judgement the two paths must share.
    monkeypatch.setattr(world.controller, "snapshot_is_current", lambda _: True)
    try:
        morek_schedule._validated_proposal(world.hass, "test", now)
    except morek_schedule.ScheduleRefused as refused:
        return refused.code
    return None


def _alter(area, change):
    today = area.today_snapshot.document
    if change == "stale":
        area.today_state = "stale"
    elif change == "unlisted":
        area.today_authority = "unknown"
    elif change == "gapped":
        area.today_snapshot.document = replace(today, intervals=today.intervals[:50])
    elif change == "nonfinite":
        bad = replace(today.intervals[60], eur_per_kwh=float("nan"))
        area.today_snapshot.document = replace(
            today, intervals=today.intervals[:60] + (bad,) + today.intervals[61:])
    elif change == "area_stale":
        area.state = "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("area_state", ["ready", "waiting_for_tomorrow"])
async def test_manual_and_auto_share_one_price_judgement_for_ready_and_waiting(monkeypatch, tmp_path, area_state):
    w, world, now = await _world(monkeypatch, tmp_path, area_state=area_state, tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    snapshot = await world.controller.async_recalculate()
    assert snapshot.price_state == area_state and snapshot.proposal.shown_periods
    # Valid data: both admit.
    assert world.controller.morek_price_blocker(snapshot, now) is None
    assert _manual_code(monkeypatch, world, snapshot, now) is None
    # Evidence changed after the calculation (the plan is no longer the one these prices produced): both refuse.
    world.area.today_snapshot.document = _document(
        world.area.today_snapshot.document, world.area.today_snapshot.document.start_instant, [.31] * 96,
        world.area.today_snapshot.document.day)
    assert world.controller.morek_price_blocker(snapshot, now) == "price_inputs_changed"
    assert _manual_code(monkeypatch, world, snapshot, now) == "price_inputs_changed"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("area_state", ["ready", "waiting_for_tomorrow"])
@pytest.mark.parametrize("change", ["stale", "unlisted", "gapped", "nonfinite", "area_stale"])
async def test_manual_refuses_stale_unlisted_or_gapped_used_prices_like_the_worker(
        monkeypatch, tmp_path, area_state, change):
    w, world, now = await _world(monkeypatch, tmp_path, area_state=area_state, tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    snapshot = await world.controller.async_recalculate()
    _alter(world.area, change)
    # The evidence is re-stamped so only the coverage/trust judgement can speak (not the changed-evidence hold).
    judged = replace(snapshot, morek_price_evidence=world.controller._morek_price_evidence(world.area))
    auto = world.controller.morek_price_blocker(judged, now)
    assert auto in ("prices_stale_or_unavailable", "price_coverage_unavailable")
    assert _manual_code(monkeypatch, world, judged, now) == auto
    w.point.call.assert_not_awaited()
    w.worker.close()


@pytest.mark.asyncio
async def test_manual_refuses_when_the_planner_cannot_judge_prices(monkeypatch, tmp_path):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    snapshot = await world.controller.async_recalculate()
    blind = SimpleNamespace(snapshot=lambda: snapshot, snapshot_is_current=lambda _: True)
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: blind)
    with pytest.raises(morek_schedule.ScheduleRefused) as refused:
        morek_schedule._validated_proposal(world.hass, "test", now)
    assert refused.value.code == "prices_stale_or_unavailable"
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("today", ["stale", "unlisted", "no_document"])
async def test_no_usable_today_never_falls_back_to_unusable_documents(monkeypatch, tmp_path, today):
    # Tomorrow is cheap but unusable (stale); today is unusable too. Nothing may be planned from either document.
    w, world, now = await _world(monkeypatch, tmp_path, area_state="degraded", tomorrow_state="stale",
                                 tomorrow_authority="listed", tomorrow_doc=[.001] * 96)
    area = world.area
    if today == "stale":
        area.today_state = "stale"
    elif today == "unlisted":
        area.today_authority = "unknown"
    else:
        area.today_snapshot.document = None
    snapshot = await world.controller.async_recalculate()
    # Without a usable (ready, listed) day the planner waits rather than planning from what it may not buy from;
    # a stale today is the existing data gate's business.
    assert snapshot.state == ("price_data_stale" if today == "stale" else "waiting_for_prices")
    # A previously calculated plan may be retained for display, but none is planned from tomorrow's unusable day
    # and nothing is dispatchable.
    day_end = area.today_snapshot.document.start_instant + timedelta(hours=24) if area.today_snapshot.document else None
    assert snapshot.proposal is None or day_end is None or all(
        end <= day_end for _, end in snapshot.proposal.shown_periods)
    assert snapshot.price_state != "ready"
    monkeypatch.setattr(morek_schedule, "preview_for", lambda *_: world.controller)
    with pytest.raises(morek_schedule.ScheduleRefused):
        morek_schedule._validated_proposal(world.hass, "test", now)
    w.worker.start()
    await drain(w.worker)
    w.point.call.assert_not_awaited()
    w.worker.close()
