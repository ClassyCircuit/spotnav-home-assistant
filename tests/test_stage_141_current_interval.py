"""Stage 14.1 through the real controller: Morek-owned plans start now and use at most three windows."""

from dataclasses import replace
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.api.price_policy import encode_price_policy
from custom_components.spotnav.planning.planner import MOREK_MAX_BLOCKS

from .test_stage_13_reactive import _world

MIN = timedelta(minutes=1)


async def _plan(world, prices, *, owned, minutes=7, hours=10, **settings):
    doc = world.area.today_snapshot.document
    now = doc.start_instant + timedelta(hours=hours, minutes=minutes)
    world.area.today_snapshot.document = replace(doc, prices=tuple(prices))
    world.controller._now = lambda: now
    world.controller._schedule_owned = AsyncMock(return_value=owned)
    world.area.catalogue.market_tz = doc.tz
    world.area.catalogue.publication = SimpleNamespace(tz=doc.tz, local_time=time(13))
    if settings:
        await world.store.async_update("test", mutate=lambda s: replace(s, **settings))
    return now, await world.controller.async_recalculate()


def _prices(current=.01, rest=.08):
    prices = [rest] * 96
    prices[40] = current  # 10:00-10:15 local-day offset: the interval `now` falls in
    return prices


@pytest.mark.asyncio
async def test_schedule_owned_capped_plan_starts_now_and_other_chargers_keep_the_boundary_start(monkeypatch):
    world = await _world(monkeypatch)
    now, owned = await _plan(world, _prices(), owned=True)
    proposal = owned.proposal
    assert proposal.has_plan and proposal.exact_periods
    assert proposal.periods[0][0] == now  # starts now, inside the 10:00 price interval
    assert proposal.slots[0].start == now and proposal.slots[0].end == now + 8 * MIN
    assert proposal.slots[0].local_major_per_kwh == .01
    assert proposal.block_limit == MOREK_MAX_BLOCKS and len(proposal.shown_periods) <= MOREK_MAX_BLOCKS
    # The stored profile accepts exactly these windows and treats the first as already running.
    profile = morek_schedule.profile_for(proposal.shown_periods, 16, now + timedelta(seconds=1), allow_active=True)
    assert profile["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 16

    _, legacy = await _plan(world, _prices(), owned=False)
    assert legacy.proposal.block_limit is None
    assert all(slot.start >= now + 8 * MIN for slot in legacy.proposal.slots)


@pytest.mark.asyncio
async def test_unavailable_ownership_is_a_legacy_plan(monkeypatch):
    world = await _world(monkeypatch)
    doc = world.area.today_snapshot.document
    now = doc.start_instant + timedelta(hours=10, minutes=7)
    world.area.today_snapshot.document = replace(doc, prices=tuple(_prices()))
    world.controller._now = lambda: now
    world.controller._schedule_owned = AsyncMock(side_effect=RuntimeError("store unavailable"))
    snapshot = await world.controller.async_recalculate()
    assert snapshot.proposal.block_limit is None
    assert all(slot.start >= now + 8 * MIN for slot in snapshot.proposal.slots)


@pytest.mark.asyncio
async def test_fragmented_cheap_prices_are_limited_to_three_windows_and_reported(monkeypatch):
    world = await _world(monkeypatch)
    prices = [.05, .20] * 48
    now, snapshot = await _plan(world, prices, owned=True, minutes=0)
    proposal = snapshot.proposal
    assert proposal.has_plan
    assert len(proposal.shown_periods) <= MOREK_MAX_BLOCKS
    assert proposal.block_limit_compromise and proposal.unrestricted_blocks > MOREK_MAX_BLOCKS
    assert proposal.block_limit_shortfall_kwh > 0
    # What is shown and what would be sent agree, and the compromise reaches the policy payload.
    assert morek_schedule.profile_for(proposal.shown_periods, 16, now - MIN)
    policy = encode_price_policy(world.store.settings("test"), snapshot)
    assert {"code": "block_limit"} in policy["explanations"]
    assert policy["block_limit"] == 3 and policy["unrestricted_blocks"] == proposal.unrestricted_blocks
    assert policy["block_limit_shortfall_kwh"] == pytest.approx(proposal.block_limit_shortfall_kwh)
    _, legacy = await _plan(world, prices, owned=False, minutes=0)
    assert legacy.proposal.block_limit is None and len(legacy.proposal.periods) > MOREK_MAX_BLOCKS


@pytest.mark.asyncio
async def test_schedule_owned_uncapped_plan_starts_now_and_stops_at_the_need(monkeypatch):
    world = await _world(monkeypatch)
    prices = _prices()
    now, snapshot = await _plan(world, prices, owned=True, soft_price_cap=None, cap_price_basis=None,
                                minimum_ready_by_soc=None, max_periods=2,
                                departure_enabled=True, departure=time(22))
    proposal = snapshot.proposal
    assert proposal.has_plan and proposal.ends_at_need
    assert proposal.shown_periods[0][0] == now
    assert len(proposal.shown_periods) <= 2
    power = proposal.power_kw
    energy = sum((end - start).total_seconds() / 3600 * power for start, end in proposal.shown_periods)
    assert energy == pytest.approx(proposal.delivered_kwh) == pytest.approx(proposal.requested_kwh)


@pytest.mark.asyncio
@pytest.mark.parametrize("capped", [False, True])
async def test_a_plan_starting_now_has_a_storable_summary(monkeypatch, capped):
    world = await _world(monkeypatch)
    changes = {} if capped else dict(soft_price_cap=None, cap_price_basis=None, minimum_ready_by_soc=None,
                                     max_periods=2, departure_enabled=True, departure=time(22))
    _, snapshot = await _plan(world, _prices(), owned=True, **changes)
    assert snapshot.proposal.lead_kwh > 0 or capped
    settings = world.store.settings("test")
    assert await world.controller._persist_proposal(settings, snapshot)
    stored = world.store.proposal("test")
    assert stored is not None and stored.period_starts
    assert stored.priced_slots == len(snapshot.proposal.slots) == stored.slots_needed


async def _missing_prices(world, *, soc, hours, published, departure, minutes=7):
    """A Morek uncapped plan whose departure needs prices that are not published (`published` quarter-hours today).

    The current interval is the last published one, so a plan starting now needs no later price at all.
    """
    world.controller._manager.async_profile = AsyncMock(return_value=None)  # no history: the daily rule decides
    world.facts[0] = replace(world.facts[0], soc_percent=soc)
    prices = [.08] * published
    prices[-1] = .01
    return await _plan(
        world, prices, owned=True, hours=hours, minutes=minutes, soft_price_cap=None, cap_price_basis=None,
        minimum_ready_by_soc=None, max_periods=2, departure_enabled=True, departure=departure,
    )


@pytest.mark.asyncio
async def test_a_current_interval_that_covers_the_need_still_waits_for_unpublished_prices(monkeypatch):
    # 10:07, tomorrow's prices unpublished, the car leaves at 08:00: waiting is safe, so nothing is charged
    # now just because the rest of the 10:00 interval could hold a 0.33 kWh need.
    world = await _world(monkeypatch)
    prices = _prices()
    world.controller._manager.async_profile = AsyncMock(return_value=None)
    world.facts[0] = replace(world.facts[0], soc_percent=79.5)
    _, snapshot = await _plan(world, prices, owned=True, soft_price_cap=None, cap_price_basis=None,
                              minimum_ready_by_soc=None, max_periods=2, departure_enabled=True, departure=time(8))
    assert (snapshot.state, snapshot.reason) == ("waiting_for_publication", "publication_pending")
    assert snapshot.price_wait == "waiting" and snapshot.must_buy_kwh == 0.0
    assert snapshot.proposal is not None and not snapshot.proposal.has_plan
    assert snapshot.proposal.reason == "insufficient_price_horizon"
    assert snapshot.proposal.requested_kwh < .8  # less than the rest of the current interval holds


@pytest.mark.asyncio
async def test_urgent_need_buys_only_what_cannot_wait_and_may_use_the_published_current_interval(monkeypatch):
    # 22:07, prices published only to 22:15, departure 22:30, publication overdue: 0.64 kWh can wait, so
    # 0.09 kWh of the 0.73 kWh need is bought now, from the rest of the published current interval.
    world = await _world(monkeypatch)
    now, snapshot = await _missing_prices(world, soc=78.9, hours=22, published=89, departure=time(22, 30))
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "buying_before_publication")
    assert snapshot.price_wait == "buy_now" and 0 < snapshot.must_buy_kwh < .8
    proposal = snapshot.proposal
    assert proposal.has_plan and not proposal.unpriced and proposal.lead_kwh > 0
    assert proposal.periods[0][0] == now and proposal.periods[-1][1] <= now + 8 * MIN  # nothing later is invented
    assert proposal.delivered_kwh == pytest.approx(snapshot.must_buy_kwh)
    assert proposal.policy_shortfall_kwh == pytest.approx(.64, abs=.02)  # the rest waits for the publication


@pytest.mark.asyncio
async def test_urgent_need_the_current_interval_cannot_hold_is_charged_unpriced_from_the_next_slot(monkeypatch):
    # 1.5 kWh: the part that cannot wait (0.86 kWh) exceeds the published 0.8 kWh, so the guarantee applies as before.
    world = await _world(monkeypatch)
    now, snapshot = await _missing_prices(world, soc=77.75, hours=22, published=89, departure=time(22, 30))
    assert (snapshot.state, snapshot.reason) == ("proposal_unpriced", "charging_without_prices")
    assert snapshot.price_wait == "guarantee" and snapshot.must_buy_kwh == pytest.approx(snapshot.proposal.requested_kwh)
    proposal = snapshot.proposal
    assert proposal.unpriced and proposal.priced_slots == 0 and proposal.lead_kwh == 0
    assert proposal.periods[0][0] >= now + 8 * MIN
