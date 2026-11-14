"""Stage 16.1 through the real controller: a Morek daily ready-by that rolled into an unpublished tomorrow still
plans on the published prices (the whole need, or the part today can carry), without moving the real deadline.

Doubles are the HA transport, the stored settings and the vehicle facts only; the planner, the wait policies and the
history comparison are the real modules. No live Home Assistant, charger or deployment.
"""

from dataclasses import replace
from datetime import time, timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.pricing.relay_contract import PriceProfile, ProfileHour
from custom_components.spotnav import time_zones

from .test_stage_13_reactive import _world
from .test_stage_141_current_interval import _plan

MIN = timedelta(minutes=1)
UNCAPPED = dict(soft_price_cap=None, cap_price_basis=None, minimum_ready_by_soc=None, max_periods=2,
                departure_enabled=True, departure=time(8), time_reserve_percent=0)


@pytest.fixture(autouse=True)
def resolved_fixture_zones():
    # Production resolves document zones before parsing. Do the same before the async test's first read.
    time_zones.require_zone("Europe/Stockholm")
    time_zones.require_zone("Europe/Brussels")


def _profile(world, *, night, day=0.08, std=0.0):
    """A usable history profile: `night` EUR/kWh for local hours 0-7 of every weekday, `day` otherwise."""
    doc = world.area.today_snapshot.document
    hours = {(weekday, hour): ProfileHour(median=night if hour < 8 else day, std=std, n=20)
             for weekday in range(1, 8) for hour in range(24)}
    return PriceProfile(version=1, area_id=doc.area_id, tz=doc.tz, unit="EUR/kWh", generated=doc.start_instant,
                        from_date=doc.day - timedelta(days=28), to_date=doc.day - timedelta(days=1), weeks=4,
                        hours=hours)


async def _daily(world, prices, *, soc, hours=10, minutes=7, profile=None, owned=True, **settings):
    world.controller._manager.async_profile = AsyncMock(return_value=profile)
    world.facts[0] = replace(world.facts[0], soc_percent=soc)
    return await _plan(world, prices, owned=owned, hours=hours, minutes=minutes, **{**UNCAPPED, **settings})


def _all_published(proposal, doc):
    midnight = doc.start_instant + timedelta(hours=24)
    return proposal.slots and all(slot.end <= midnight for slot in proposal.slots)


@pytest.mark.asyncio
async def test_whole_need_is_placed_in_the_cheapest_published_hours_not_forced_to_start_now(monkeypatch):
    world = await _world(monkeypatch)
    prices = [.08] * 96
    prices[40] = .04  # the current interval
    for index in range(72, 80):
        prices[index] = .01  # a cheaper known evening block
    now, snapshot = await _daily(world, prices, soc=70)
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "ready")
    assert snapshot.price_wait is None
    proposal = snapshot.proposal
    doc = world.area.today_snapshot.document
    assert proposal.has_plan and not proposal.unpriced and _all_published(proposal, doc)
    assert proposal.shown_periods[0][0] > now  # the cheaper later known block, not "now"
    assert proposal.policy_shortfall_kwh == pytest.approx(0, abs=1e-6)
    assert proposal.requested_kwh == pytest.approx(proposal.delivered_kwh)
    assert not proposal.short_of_deadline
    assert proposal.price_coverage_end == doc.start_instant + timedelta(hours=24)  # tomorrow is pending
    assert not world.controller.snapshot().applied


@pytest.mark.asyncio
async def test_the_part_elapsed_current_interval_is_selected_when_it_is_the_cheapest_known(monkeypatch):
    world = await _world(monkeypatch)
    prices = [.08] * 96
    prices[40] = .01
    now, snapshot = await _daily(world, prices, soc=79)
    proposal = snapshot.proposal
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "ready")
    assert proposal.has_plan and proposal.lead_kwh > 0
    assert proposal.shown_periods[0][0] == now
    assert proposal.slots[0].end <= now + 8 * MIN  # the rest of the interval, or less once the need is met


@pytest.mark.asyncio
async def test_a_plug_in_late_in_the_day_plans_the_published_part_and_keeps_the_real_need(monkeypatch):
    world = await _world(monkeypatch)
    doc = world.area.today_snapshot.document
    now, snapshot = await _daily(world, [.08] * 96, soc=25, hours=22)
    proposal = snapshot.proposal
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "ready")
    assert proposal.has_plan and not proposal.unpriced and _all_published(proposal, doc)
    assert proposal.delivered_kwh < proposal.requested_kwh  # only what today's prices can carry
    assert proposal.policy_shortfall_kwh == pytest.approx(proposal.requested_kwh - proposal.delivered_kwh)
    assert proposal.policy_shortfall_kwh > 1
    assert not proposal.short_of_deadline  # the 08:00 deadline is not claimed unreachable
    assert proposal.price_coverage_end == doc.start_instant + timedelta(hours=24)
    assert proposal.priced_slots == len(proposal.slots) and proposal.unpriced_slots == 0
    assert proposal.shown_periods[0][0] <= now + 8 * MIN
    assert proposal.requested_kwh > 20  # the whole remaining need, not the truncated one


@pytest.mark.asyncio
async def test_partial_progress_is_not_bought_twice_on_a_recalculation(monkeypatch):
    world = await _world(monkeypatch)
    _, first = await _daily(world, [.08] * 96, soc=25, hours=22)
    _, again = await _daily(world, [.08] * 96, soc=25, hours=22)
    assert again.proposal.requested_kwh == pytest.approx(first.proposal.requested_kwh)
    assert [s.start for s in again.proposal.slots] == [s.start for s in first.proposal.slots]
    # The car gained part of the plan (a later SOC reading): the need shrinks by exactly that, nothing is re-bought.
    world.facts[0] = replace(world.facts[0], soc_percent=30)
    _, later = await _daily(world, [.08] * 96, soc=30, hours=22)
    assert later.proposal.requested_kwh < first.proposal.requested_kwh - 1
    assert later.proposal.requested_kwh == pytest.approx(first.proposal.requested_kwh * 50 / 55, rel=0.05)


@pytest.mark.asyncio
async def test_without_published_prices_nothing_priced_is_planned(monkeypatch):
    world = await _world(monkeypatch)
    # Only 00:00-10:00 is published and now is 10:07: no usable interval, so there is nothing to plan on.
    _, snapshot = await _daily(world, [.08] * 40, soc=70)
    assert not snapshot.proposal.unpriced
    assert not snapshot.proposal.has_plan
    assert (snapshot.state, snapshot.reason) == ("waiting_for_publication", "publication_pending")


@pytest.mark.asyncio
async def test_history_that_clearly_favours_tomorrow_night_keeps_the_guarded_wait(monkeypatch):
    world = await _world(monkeypatch)
    prices = [.08] * 96
    profile = _profile(world, night=.001)
    _, snapshot = await _daily(world, prices, soc=70, profile=profile)
    assert (snapshot.state, snapshot.reason) == ("waiting_for_publication", "waiting_for_history")
    assert snapshot.history.outcome == "wait" and snapshot.wait_rule == "history"
    assert not snapshot.proposal.has_plan


@pytest.mark.asyncio
@pytest.mark.parametrize("night", [.08, .30])
async def test_flat_or_dearer_history_does_not_block_the_published_plan(monkeypatch, night):
    world = await _world(monkeypatch)
    _, snapshot = await _daily(world, [.08] * 96, soc=70, profile=_profile(world, night=night))
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "ready")
    assert snapshot.proposal.has_plan and not snapshot.proposal.unpriced


@pytest.mark.asyncio
async def test_non_morek_chargers_keep_the_wait_for_the_publication(monkeypatch):
    world = await _world(monkeypatch)
    _, snapshot = await _daily(world, [.08] * 96, soc=70, owned=False)
    assert (snapshot.state, snapshot.reason) == ("waiting_for_publication", "publication_pending")
    assert not snapshot.proposal.has_plan


@pytest.mark.asyncio
async def test_a_need_that_cannot_wait_is_still_bought_by_the_existing_urgency_rule(monkeypatch):
    world = await _world(monkeypatch)
    # 22:07, a need that fills the night: waiting for tomorrow's prices is not safe, so the old rule applies.
    _, snapshot = await _daily(world, [.08] * 96, soc=0, hours=22)
    assert snapshot.price_wait in {"buy_now", "guarantee"}
    assert snapshot.reason in {"buying_before_publication", "charging_without_prices"}


@pytest.mark.asyncio
async def test_the_reserve_is_added_after_the_need_and_never_inflates_the_baseline(monkeypatch):
    world = await _world(monkeypatch)
    prices = [.08] * 96
    profile = _profile(world, night=.08)  # history diagnostics are present; they must not skip the reserve
    _, plain = await _daily(world, prices, soc=70, profile=profile, time_reserve_percent=0)
    _, reserved = await _daily(world, prices, soc=70, profile=profile, time_reserve_percent=10)
    assert plain.history is not None and reserved.history is not None
    assert not plain.proposal.reserve_pieces
    assert reserved.proposal.reserve_pieces and reserved.proposal.reserve_percent == 10
    assert reserved.proposal.requested_kwh == pytest.approx(plain.proposal.requested_kwh)
    assert reserved.proposal.delivered_kwh == pytest.approx(plain.proposal.delivered_kwh)
    assert reserved.proposal.estimated_cost == pytest.approx(plain.proposal.estimated_cost)
    assert reserved.proposal.baseline_shown_periods == plain.proposal.baseline_shown_periods
    for piece in reserved.proposal.reserve_pieces:
        assert piece.end <= world.area.today_snapshot.document.start_instant + timedelta(hours=24)


@pytest.mark.asyncio
async def test_a_deadline_just_past_the_published_end_is_not_moved(monkeypatch):
    world = await _world(monkeypatch)
    doc = world.area.today_snapshot.document
    # 00:30 is past the last published price (24:00) but the whole need fits before it: planned in published time.
    _, snapshot = await _daily(world, [.08] * 96, soc=65, hours=22, departure=time(0, 30))
    proposal = snapshot.proposal
    assert (snapshot.state, snapshot.reason) == ("proposal_ready", "ready")
    assert not proposal.short_of_deadline and proposal.delivered_kwh == pytest.approx(proposal.requested_kwh)
    assert proposal.has_plan and _all_published(proposal, doc)
    assert proposal.price_coverage_end == doc.start_instant + timedelta(hours=24)
    assert proposal.shown_periods[-1][1] <= doc.start_instant + timedelta(hours=24)
