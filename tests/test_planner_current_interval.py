"""Stage 14.1: the rest of the current price interval, and the three-window limit of a Morek schedule.

Pure planner behaviour with actual planner output; no HA, controller or charger. Both engines are
covered: the cap-aware exact one and the whole-slot one. A request that does not ask for the current
interval or a window limit keeps the previous behaviour.
"""

from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.planning.planner import (
    MOREK_MAX_BLOCKS, PlannerInputError, calculate_plan, ending_at_need, price_gap,
)

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_deadline_dst import day, request as dst_request, utc
from .test_planner_price_policy_guard import cap_request

MIN = timedelta(minutes=1)


@pytest.fixture
def base():
    scenario = fixture_payload()["scenarios"][0]
    return build_request(scenario["request"], parse_documents(scenario["documents"]))


def mid(request, minutes=7):
    """The same request, asked mid-interval and for the current interval."""
    return replace(request, now=request.now + minutes * MIN, include_current_interval=True)


def kwh(period, power=6.0):
    return (period[1] - period[0]).total_seconds() / 3600 * power


# ---- cap-aware engine ------------------------------------------------------------------------------

def test_capped_starts_now_with_proportional_energy_and_cost(base):
    request = cap_request(base, [.05, .20, .04, .20], need=2.3)
    start = request.now
    result = calculate_plan(mid(request))
    assert result.periods == ((start + 7 * MIN, start + 15 * MIN), (start + 30 * MIN, start + 45 * MIN))
    assert result.delivered_kwh == pytest.approx(2.3)
    assert result.estimated_cost == pytest.approx(.8 * .05 + 1.5 * .04)
    assert result.policy_shortfall_kwh == pytest.approx(0)
    # Per-window energy and cost add up to the plan totals.
    assert sum(kwh(p) for p in result.shown_periods) == pytest.approx(result.delivered_kwh)
    # The same request without it starts at the next boundary, as before.
    old = calculate_plan(replace(mid(request), include_current_interval=False))
    assert old.periods == ((start + 30 * MIN, start + 45 * MIN),)
    assert old.delivered_kwh == pytest.approx(1.5)


def test_capped_current_interval_continues_into_the_next_interval_as_one_window(base):
    request = cap_request(base, [.05, .05, .20, .20], need=2.3)
    start = request.now
    result = calculate_plan(mid(request))
    assert result.periods == ((start + 7 * MIN, start + 30 * MIN),)
    assert result.delivered_kwh == pytest.approx(2.3)


def test_capped_exact_boundary_has_no_current_interval_fragment(base):
    request = cap_request(base, [.05, .20, .04, .20], need=2.3)
    on_boundary = replace(request, now=request.now + 15 * MIN, include_current_interval=True)
    assert calculate_plan(on_boundary) == calculate_plan(replace(on_boundary, include_current_interval=False))


def test_capped_seconds_left_in_the_interval_are_not_silently_dropped(base):
    request = cap_request(base, [.05, .20, .04, .20], need=2.3)
    nearly = replace(request, now=request.now + 15 * MIN - timedelta(seconds=20), include_current_interval=True)
    result = calculate_plan(nearly)
    # The 20 seconds at the current (cheap) price are a window of their own, in front of the cheap slot.
    assert result.periods[0] == (nearly.now, nearly.now + timedelta(seconds=20))
    old = calculate_plan(replace(nearly, include_current_interval=False))
    assert result.delivered_kwh == pytest.approx(old.delivered_kwh + 6.0 * 20 / 3600)


def test_capped_expensive_current_interval_is_not_used_when_not_needed(base):
    request = cap_request(base, [.20, .05, .05, .20], need=3)
    result = calculate_plan(mid(request))
    assert result.periods == ((request.now + 15 * MIN, request.now + 45 * MIN),)
    assert result.exception_kwh == 0


def test_capped_minimum_exception_may_use_the_cheapest_necessary_current_interval(base):
    request = replace(cap_request(base, [.12, .30, .30, .30], need=3), minimum_energy_kwh=.8)
    result = calculate_plan(mid(request))
    assert result.periods == ((request.now + 7 * MIN, request.now + 15 * MIN),)
    assert result.exception_periods == result.periods
    assert result.exception_kwh == pytest.approx(.8)
    assert result.minimum_shortfall_kwh == pytest.approx(0, abs=1e-7)
    assert result.estimated_cost == pytest.approx(.8 * .12)


def test_capped_deadline_inside_the_current_interval_is_a_partial_window(base):
    request = cap_request(base, [.05, .05, .05, .05], need=3)
    request = mid(replace(request, window_end=request.now + 12 * MIN))
    result = calculate_plan(request)
    assert result.periods == ((request.now + 0 * MIN, request.now + 5 * MIN),)
    assert result.delivered_kwh == pytest.approx(.5)
    assert result.policy_shortfall_kwh == pytest.approx(2.5)


def test_capped_negative_current_interval_price_is_proportional(base):
    request = cap_request(base, [-.05, .20, -.04, .20], need=2.3)
    result = calculate_plan(mid(request))
    assert result.estimated_cost == pytest.approx(.8 * -.05 + 1.5 * -.04)
    assert result.periods[0][0] == request.now + 7 * MIN


def test_an_unpublished_current_interval_is_never_priced_from_a_neighbour(base):
    request = cap_request(base, [.05, .04], need=2.3)
    doc = request.documents[0]
    late = replace(doc, start_instant=doc.start_instant + 15 * MIN, prices=(.05, .04))
    request = replace(request, documents=(late,), now=doc.start_instant, window_end=doc.start_instant + 45 * MIN)
    asked = mid(request)
    assert calculate_plan(asked) == calculate_plan(replace(asked, include_current_interval=False))


def test_capped_three_window_limit_in_automatic_mode_reports_the_compromise(base):
    prices = [.05, .20] * 4
    request = cap_request(base, prices, need=6.0, periods=8)
    request = replace(request, max_periods=None)
    free = calculate_plan(request)
    assert len(free.periods) == 4 and free.block_limit is None
    limited = calculate_plan(replace(request, max_blocks=MOREK_MAX_BLOCKS))
    assert len(limited.periods) == 3
    assert limited.delivered_kwh == pytest.approx(4.5)
    assert limited.policy_shortfall_kwh == pytest.approx(1.5)
    assert limited.block_limit == 3 and limited.block_limit_compromise
    assert limited.unrestricted_blocks == 4
    assert limited.block_limit_shortfall_kwh == pytest.approx(1.5)
    # A limit that costs nothing is not a compromise.
    easy = calculate_plan(replace(request, requested_kwh=3.0, max_blocks=MOREK_MAX_BLOCKS))
    assert easy.block_limit == 3 and not easy.block_limit_compromise


def test_the_current_interval_counts_toward_the_window_limit(base):
    prices = [.05, .20, .05, .20, .05, .20, .05, .20]
    request = replace(cap_request(base, prices, need=8.0, periods=8), max_periods=None)
    # Three cheap whole intervals already fill three windows: the fragment would be a fourth.
    three = calculate_plan(replace(mid(request), max_blocks=3))
    assert len(three.periods) == 3 and three.delivered_kwh == pytest.approx(4.5)
    assert all(start >= request.now + 15 * MIN for start, _ in three.periods)
    four = calculate_plan(replace(mid(request), max_blocks=4))
    assert len(four.periods) == 4 and four.delivered_kwh == pytest.approx(5.3)
    assert four.periods[0][0] == request.now + 7 * MIN


# ---- whole-slot engine -----------------------------------------------------------------------------

def uncapped(request, **changes):
    return replace(request, soft_price_cap=None, cap_price_basis=None, max_periods=2, **changes)


def test_uncapped_starts_now_when_that_is_cheaper_and_stops_at_the_need(base):
    request = uncapped(cap_request(base, [.04, .05, .30, .30, .06, .30, .30, .30], need=3.0))
    start = request.now
    plain = calculate_plan(replace(mid(request), include_current_interval=False))
    assert plain.periods[0][0] == start + 15 * MIN
    started = ending_at_need(calculate_plan(mid(request)))
    assert started.periods[0][0] == start + 7 * MIN
    assert started.periods[0][1] == start + 30 * MIN
    assert started.delivered_kwh == pytest.approx(3.0)
    assert started.estimated_cost < ending_at_need(plain).estimated_cost
    assert started.estimated_cost == pytest.approx(.8 * .04 + 1.5 * .05 + 1.5 * .06 - .8 * .06)
    # The shown windows deliver exactly the need and the last one ends where the need is met.
    assert sum(kwh(p) for p in started.shown_periods) == pytest.approx(3.0)
    assert started.shown_periods[-1][1] < started.periods[-1][1]


def test_uncapped_current_interval_alone_can_cover_a_small_need(base):
    request = uncapped(cap_request(base, [.04, .05, .30, .30, .06, .30, .30, .30], need=0.5))
    result = ending_at_need(calculate_plan(mid(request)))
    assert result.periods == ((request.now + 7 * MIN, request.now + 12 * MIN),)
    assert result.delivered_kwh == pytest.approx(.5)
    assert result.estimated_cost == pytest.approx(.5 * .04)


def test_uncapped_current_interval_is_ignored_when_it_is_not_cheaper(base):
    request = uncapped(cap_request(base, [.30, .05, .30, .30, .06, .30, .30, .30], need=3.0))
    assert calculate_plan(mid(request)) == calculate_plan(replace(mid(request), include_current_interval=False))


def test_uncapped_three_window_limit_in_automatic_mode(base):
    prices = [.02, .02, .40, .40] * 4
    request = replace(cap_request(base, prices, need=12.0), soft_price_cap=None, cap_price_basis=None,
                      max_periods=None)
    free = calculate_plan(request)
    assert len(free.periods) == 4
    limited = calculate_plan(replace(request, max_blocks=3))
    assert len(limited.periods) <= 3
    assert limited.delivered_kwh == pytest.approx(free.delivered_kwh)
    assert limited.unrestricted_blocks == 4 and limited.block_limit == 3
    assert limited.block_limit_extra_cost > 0
    # A configured 2-window limit stays tighter than the executor's.
    two = calculate_plan(replace(request, max_periods=2, max_blocks=3))
    assert len(two.periods) <= 2


def test_uncapped_spring_forward_lead_uses_elapsed_time():
    document = day("2026-03-29", 92, "2026-03-29T00:00:00+01:00", expensive=range(12, 16))
    document["prices"][7] = 0.1  # 00:45Z-01:00Z, the interval the clock change falls at the end of
    document["prices"][8] = 0.1  # the next one, so the plan continues straight on
    now = "2026-03-29T01:52:00+01:00"  # 00:52Z, eight minutes before 03:00+02:00
    request = replace(dst_request(now, "06:00", 4, [document]), include_current_interval=True)
    result = calculate_plan(request)
    lead = result.slots[0]
    assert lead.start == utc(now) and lead.end == utc("2026-03-29T01:00:00Z")
    assert (lead.end - lead.start) == timedelta(minutes=8)
    # Next slots continue straight on in absolute time.
    assert result.periods[0][0] == utc(now)
    assert result.slots[1].start == lead.end


def test_validation_of_the_new_inputs(base):
    with pytest.raises(PlannerInputError):
        calculate_plan(replace(base, max_blocks=0))
    with pytest.raises(PlannerInputError):
        calculate_plan(replace(base, max_blocks=True))
    with pytest.raises(PlannerInputError):
        calculate_plan(replace(base, include_current_interval="yes"))


# ---- the stored Morek profile agrees with the displayed plan -------------------------------------------

def test_profile_from_a_plan_starting_now_is_active_and_matches_the_windows(base):
    request = cap_request(base, [.05, .20, .04, .20], need=2.3)
    result = calculate_plan(mid(request))
    sent_at = request.now + 7 * MIN + timedelta(seconds=2)
    profile = morek_schedule.profile_for(result.shown_periods, 16, sent_at, allow_active=True)
    periods = profile["chargingSchedule"]["chargingSchedulePeriod"]
    assert periods[0]["limit"] == 16  # the window that started now is already allowed
    start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
    assert start + timedelta(seconds=periods[1]["startPeriod"]) <= request.now + 15 * MIN
    assert periods[1]["limit"] == 0 and periods[-1]["limit"] == 0
    assert len(result.shown_periods) <= MOREK_MAX_BLOCKS


def test_a_fourth_window_is_refused_by_the_profile_builder(base):
    request = replace(cap_request(base, [.05, .20] * 4, need=6.0), max_periods=None)
    four = calculate_plan(request)
    assert len(four.periods) == 4
    with pytest.raises(morek_schedule.ScheduleRefused) as error:
        morek_schedule.profile_for(four.shown_periods, 16, request.now - MIN)
    assert error.value.code == "too_many_blocks"
    three = calculate_plan(replace(request, max_blocks=MOREK_MAX_BLOCKS))
    assert morek_schedule.profile_for(three.shown_periods, 16, request.now - MIN)


# ---- the current interval is a real candidate: stand-alone, short of the deadline, near the deadline ---------

def test_uncapped_current_interval_may_be_a_window_of_its_own(base):
    # The next interval is expensive, so the cheap rest of this one cannot continue into it.
    request = uncapped(cap_request(base, [.04, .30, .30, .30, .06, .06, .30, .30], need=3.0))
    plain = ending_at_need(calculate_plan(replace(mid(request), include_current_interval=False)))
    result = ending_at_need(calculate_plan(mid(request)))
    start = request.now
    assert result.periods[0] == (start + 7 * MIN, start + 15 * MIN)
    assert result.periods[1][0] == start + 60 * MIN
    assert len(result.periods) <= 2
    assert result.delivered_kwh == pytest.approx(3.0)
    assert result.estimated_cost == pytest.approx(.8 * .04 + 2.2 * .06)
    assert result.estimated_cost < plain.estimated_cost
    assert sum(kwh(p) for p in result.shown_periods) == pytest.approx(3.0)


def test_uncapped_stand_alone_current_interval_counts_toward_the_period_limit(base):
    request = uncapped(cap_request(base, [.04, .30, .30, .30, .06, .06, .30, .30], need=3.0))
    one = ending_at_need(calculate_plan(replace(mid(request), max_periods=1)))
    # Both the rest of this interval and the later cheap pair would be two windows: one is the limit.
    assert len(one.periods) == 1
    assert one.delivered_kwh == pytest.approx(3.0)
    # And the executor's limit of one holds in automatic mode too.
    auto = ending_at_need(calculate_plan(replace(mid(request), max_periods=None, max_blocks=1)))
    assert len(auto.periods) == 1 and auto.delivered_kwh == pytest.approx(3.0)


def test_uncapped_window_limit_counts_the_current_interval_in_automatic_mode(base):
    # Cheap pairs of intervals (an automatic window is at least two slots), the first one the current one.
    prices = [.02, .02, .40, .40] * 4
    request = replace(uncapped(cap_request(base, prices, need=11.0)), max_periods=None)
    four = calculate_plan(replace(mid(request), max_blocks=4))
    assert len(four.periods) == 4 and four.periods[0][0] == request.now + 7 * MIN
    assert four.block_limit == 4 and not four.block_limit_compromise
    three = calculate_plan(replace(mid(request), max_blocks=3))
    # The rest of this interval is one of the three windows, not a free extra one.
    assert len(three.periods) <= 3
    assert three.block_limit == 3 and three.block_limit_compromise
    assert three.unrestricted_blocks == 4 and three.block_limit_extra_cost > 0
    assert ending_at_need(three).delivered_kwh == pytest.approx(11.0)


def test_uncapped_seconds_left_in_the_interval_are_a_candidate(base):
    request = uncapped(cap_request(base, [.01, .30, .30, .30, .06, .30, .30, .30], need=3.0))
    nearly = replace(request, now=request.now + 15 * MIN - timedelta(seconds=30), include_current_interval=True)
    result = ending_at_need(calculate_plan(nearly))
    plain = ending_at_need(calculate_plan(replace(nearly, include_current_interval=False)))
    assert result.periods[0] == (nearly.now, nearly.now + timedelta(seconds=30))
    assert result.estimated_cost < plain.estimated_cost
    assert result.delivered_kwh == pytest.approx(3.0)


# One June day in Europe/Stockholm (+02:00), flat price; the current interval is the 05:00-05:15 one.
def june(**changes):
    document = day("2026-06-10", 96, "2026-06-10T00:00:00+02:00")
    return replace(dst_request("2026-06-10T05:07:00+02:00", "06:00", 4, [document]), include_current_interval=True,
                   **changes)


def test_uncapped_best_effort_plan_still_uses_the_current_interval():
    # Four slots are wanted but only the rest of this interval and three whole slots fit before 06:00.
    request = june()
    plain = calculate_plan(replace(request, include_current_interval=False))
    result = calculate_plan(request)
    assert plain.short_of_deadline and len(plain.slots) == 3
    assert result.short_of_deadline
    assert result.periods == ((utc("2026-06-10T05:07:00+02:00"), utc("2026-06-10T06:00:00+02:00")),)
    assert result.delivered_kwh == pytest.approx(plain.delivered_kwh + result.lead_kwh)
    assert result.lead_kwh == pytest.approx(result.power_kw * 8 / 60)


def test_uncapped_need_that_only_fits_with_the_current_interval_is_not_short():
    request = june()
    plain = calculate_plan(replace(request, include_current_interval=False))
    wanted = plain.delivered_kwh + request.planned_kw * 5 / 60  # three whole slots and part of the lead
    result = calculate_plan(replace(request, requested_kwh=wanted))
    assert replace(request, requested_kwh=wanted) and not result.short_of_deadline
    assert calculate_plan(replace(request, requested_kwh=wanted, include_current_interval=False)).short_of_deadline
    ended = ending_at_need(result)
    assert ended.delivered_kwh == pytest.approx(wanted)
    assert result.periods[0][0] == utc("2026-06-10T05:07:00+02:00")
    assert ended.shown_periods[-1][1] <= utc("2026-06-10T06:00:00+02:00")


def test_uncapped_deadline_inside_the_current_interval_uses_it_up_to_the_deadline():
    # Departure 05:12 is five minutes ahead: no whole slot fits, the rest of this interval up to 05:12 does.
    request = replace(june(), departure=time(5, 12), requested_kwh=5.0)
    result = calculate_plan(request)
    assert result.reason is None and result.short_of_deadline
    assert result.periods == ((utc("2026-06-10T05:07:00+02:00"), utc("2026-06-10T05:12:00+02:00")),)
    assert result.delivered_kwh == pytest.approx(request.planned_kw * 5 / 60)
    assert result.estimated_cost > 0


def test_uncapped_small_need_inside_a_deadline_interval_is_met_exactly():
    request = replace(june(), departure=time(5, 12), requested_kwh=0.5)
    result = calculate_plan(request)
    assert result.reason is None and not result.short_of_deadline
    assert result.delivered_kwh == pytest.approx(0.5)
    start = utc("2026-06-10T05:07:00+02:00")
    assert result.periods == ((start, start + timedelta(hours=0.5 / request.planned_kw)),)
    assert result.shown_periods == result.periods


def test_uncapped_deadline_already_passed_in_the_interval_is_not_a_window():
    request = replace(june(), departure=None, window_end=utc("2026-06-10T05:07:00+02:00"), requested_kwh=1.0)
    assert calculate_plan(request).reason == "deadline_too_short"


def test_capped_departure_inside_the_current_interval_is_today_not_tomorrow(base):
    # The document starts at local midnight (UTC+2 in September): a 00:12 departure, asked at 00:07.
    request = cap_request(base, [.05] * 8, need=3.0)
    request = mid(replace(request, window_end=None, departure=time(0, 12)))
    result = calculate_plan(request)
    start = request.documents[0].start_instant
    assert result.periods == ((start + 7 * MIN, start + 12 * MIN),)
    assert result.delivered_kwh == pytest.approx(.5)
    # Without the current interval the same departure is the next one, tomorrow's.
    assert calculate_plan(replace(request, include_current_interval=False)).periods[0][0] >= start + 15 * MIN


def test_uncapped_current_interval_is_considered_when_later_prices_are_missing():
    # Prices exist only until 06:00 but the car leaves at 08:00: the whole-slot plan has no complete horizon.
    document = day("2026-06-10", 24, "2026-06-10T00:00:00+02:00")
    request = replace(dst_request("2026-06-10T05:07:00+02:00", "08:00", 1, [document]),
                      include_current_interval=True, requested_kwh=0.5)
    assert calculate_plan(replace(request, include_current_interval=False)).reason == "insufficient_price_horizon"
    result = calculate_plan(request)
    assert result.reason is None and result.lead_kwh == pytest.approx(0.5)
    assert result.periods == ((utc("2026-06-10T05:07:00+02:00"),
                               utc("2026-06-10T05:07:00+02:00") + timedelta(hours=0.5 / request.planned_kw)),)
    # A need the current interval cannot meet alone still waits for the missing prices, as before.
    assert calculate_plan(replace(request, requested_kwh=5.0)).reason == "insufficient_price_horizon"


def test_price_gap_reports_the_published_current_interval_only_when_it_is_used():
    document = day("2026-06-10", 24, "2026-06-10T00:00:00+02:00")
    request = replace(dst_request("2026-06-10T05:07:00+02:00", "08:00", 1, [document]), include_current_interval=True)
    gap = price_gap(request)
    assert gap is not None and gap.known and gap.current is not None
    assert (gap.current.start, gap.current.end) == (utc("2026-06-10T05:07:00+02:00"), utc("2026-06-10T05:15:00+02:00"))
    assert price_gap(replace(request, include_current_interval=False)).current is None
    # An unpublished current interval is never priced from a neighbour.
    late = replace(request, now=utc("2026-06-10T08:07:00+02:00"), departure=time(10))
    gap = price_gap(late)
    assert gap is not None and gap.current is None
