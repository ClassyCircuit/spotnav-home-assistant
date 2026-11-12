"""Pure capped planning with a caller-resolved minimum wall-energy deficit."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.spotnav.planning.planner import (
    FiscalChoice, PlannerInputError, calculate_plan, ending_at_need, plan_unpriced,
)

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_price_policy_guard import cap_request


@pytest.fixture
def plan_request():
    scenario = fixture_payload()["scenarios"][0]
    return build_request(scenario["request"], parse_documents(scenario["documents"]))


def with_minimum(request, minimum):
    return replace(request, minimum_energy_kwh=minimum)


def test_all_expensive_buys_cheapest_nine_not_thirty_three(plan_request):
    request = with_minimum(cap_request(plan_request, [.30, .25, .20, .18, .16, .14, .12, .11], need=33), 9)
    result = calculate_plan(request)
    assert result.periods == ((request.now + timedelta(minutes=30), request.now + timedelta(minutes=120)),)
    assert result.exception_periods == result.periods == result.shown_periods
    assert result.delivered_kwh == pytest.approx(9)
    assert result.exception_kwh == pytest.approx(9)
    assert result.minimum_shortfall_kwh == pytest.approx(0)
    assert result.policy_shortfall_kwh == pytest.approx(24)
    assert result.estimated_cost == pytest.approx(1.365)


def test_partial_expensive_before_cheap_exact_windows(plan_request):
    request = with_minimum(cap_request(plan_request, [.20, .05], need=10), 2.1)
    result = calculate_plan(request)
    assert result.exception_periods == ((request.now + timedelta(minutes=9), request.now + timedelta(minutes=15)),)
    assert result.periods == result.shown_periods == ((request.now + timedelta(minutes=9), request.now + timedelta(minutes=30)),)
    assert result.exception_kwh == pytest.approx(.6)
    assert result.delivered_kwh == pytest.approx(2.1)
    assert result.estimated_cost == pytest.approx(.195)
    assert result.minimum_shortfall_kwh == pytest.approx(0, abs=1e-7)
    assert result.policy_shortfall_kwh == pytest.approx(7.9)
    assert ending_at_need(result) == result


def test_cheap_minimum_sufficient_continues_toward_target(plan_request):
    request = with_minimum(cap_request(plan_request, [.04, .20, .05, .06], need=4.5), 2.1)
    result = calculate_plan(request)
    assert result.exception_periods == () and result.exception_kwh == 0
    assert result.delivered_kwh == pytest.approx(4.5)
    assert result.minimum_shortfall_kwh == pytest.approx(0)


@pytest.mark.parametrize("minimum", [None, 0])
def test_unset_or_zero_minimum_cannot_authorize_expensive_energy(plan_request, minimum):
    result = calculate_plan(with_minimum(cap_request(plan_request, [.20, .30]), minimum))
    assert result.reason == "no_eligible_energy"
    assert result.periods == () and result.exception_kwh == 0
    assert result.minimum_shortfall_kwh == minimum


def test_shared_period_limit_finds_minimum_without_expensive_padding(plan_request):
    request = with_minimum(cap_request(plan_request, [.05, .40, .05, .11], need=8, periods=1), 2.1)
    result = calculate_plan(request)
    assert result.periods == result.shown_periods
    assert len(result.periods) == 1
    assert result.exception_kwh == pytest.approx(.6)
    assert result.exception_periods == ((request.now + timedelta(minutes=45), request.now + timedelta(minutes=51)),)
    assert result.delivered_kwh == pytest.approx(2.1)
    assert result.estimated_cost == pytest.approx(.141)


def test_period_limit_causes_real_shortfall_without_bridging_unknown_gap(plan_request):
    request = with_minimum(cap_request(plan_request, [.05], need=6, periods=1), 3)
    doc = request.documents[0]
    later = replace(doc, start_instant=doc.start_instant + timedelta(minutes=30), prices=(.20,))
    result = calculate_plan(replace(request, documents=(doc, later), window_end=request.now + timedelta(hours=1)))
    assert len(result.periods) == 1
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.minimum_shortfall_kwh == pytest.approx(1.5)
    assert result.policy_shortfall_kwh == pytest.approx(4.5)
    assert result.exception_kwh == 0


def test_insufficient_known_prices_report_both_shortfalls(plan_request):
    request = with_minimum(cap_request(plan_request, [.05, .20], need=10), 6)
    result = calculate_plan(replace(request, window_end=request.now + timedelta(hours=4)))
    assert result.delivered_kwh == pytest.approx(3)
    assert result.minimum_shortfall_kwh == pytest.approx(3)
    assert result.policy_shortfall_kwh == pytest.approx(7)
    assert result.exception_kwh == pytest.approx(1.5)
    assert not result.unpriced


def test_minimum_coverage_wins_over_isolated_cheap_slot(plan_request):
    request = with_minimum(cap_request(plan_request, [.05], need=6, periods=1), 3)
    doc = request.documents[0]
    later = replace(doc, start_instant=doc.start_instant + timedelta(minutes=30), prices=(.20, .21))
    result = calculate_plan(replace(request, documents=(doc, later), window_end=request.now + timedelta(hours=1)))
    assert result.periods == ((request.now + timedelta(minutes=30), request.now + timedelta(minutes=60)),)
    assert result.delivered_kwh == pytest.approx(3)
    assert result.exception_kwh == pytest.approx(3)
    assert result.minimum_shortfall_kwh == pytest.approx(0)
    assert result.policy_shortfall_kwh == pytest.approx(3)


def test_exception_search_prioritizes_cheap_energy_over_effective_cost(plan_request):
    # A high time-of-use fee can make the configured cost of a Nord Pool-cheap
    # interval greater than an above-cap interval. It is still eligible cheap energy.
    from custom_components.spotnav.planning.planner import HighLoadWindow

    fiscal = FiscalChoice(
        transfer_high_enabled=True, transfer_high_minor_per_kwh=50,
        high_load_window=HighLoadWindow(days="all", from_month=1, to_month=12, from_hour=0, to_hour=1,
                                        tz="Europe/Stockholm"),
    )
    request = with_minimum(cap_request(plan_request, [.05, .9, .9, .9, .20], need=5, fiscal=fiscal), 2.1)
    result = calculate_plan(request)
    assert result.delivered_kwh == pytest.approx(2.1)
    assert result.exception_kwh == pytest.approx(.6)


@pytest.mark.parametrize("basis,expected_exception", [("nord_pool", 0), ("configured_variable_cost", 1.5)])
def test_both_cap_bases_and_fees(plan_request, basis, expected_exception):
    fiscal = FiscalChoice(tax_enabled=True, tax_minor_per_kwh=3)
    request = with_minimum(cap_request(plan_request, [.08], need=3, basis=basis, fiscal=fiscal), 1.5)
    result = calculate_plan(request)
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.exception_kwh == pytest.approx(expected_exception)
    assert result.estimated_cost == pytest.approx(.165)


def test_partial_deadline_limits_exception(plan_request):
    request = with_minimum(cap_request(plan_request, [.20], need=5), 3)
    result = calculate_plan(replace(request, window_end=request.now + timedelta(minutes=10)))
    assert result.periods == result.exception_periods == ((request.now, request.now + timedelta(minutes=10)),)
    assert result.exception_kwh == pytest.approx(1)
    assert result.minimum_shortfall_kwh == pytest.approx(2)
    assert result.policy_shortfall_kwh == pytest.approx(4)


@pytest.mark.parametrize("minimum", [-.1, 3.01, True, float("nan"), float("inf"), "1"])
def test_invalid_minimum_rejected(plan_request, minimum):
    request = with_minimum(cap_request(plan_request, [.05], need=3), minimum)
    with pytest.raises(PlannerInputError):
        calculate_plan(request)


def test_negative_expensive_price_does_not_extend_exception(plan_request):
    request = with_minimum(cap_request(plan_request, [-.05, -.05], need=3, cap=-.1), .6)
    result = calculate_plan(request)
    assert result.delivered_kwh == pytest.approx(.6)
    assert result.exception_kwh == pytest.approx(.6)
    assert result.policy_shortfall_kwh == pytest.approx(2.4)


def test_minimum_does_not_bypass_unpriced_guard(plan_request):
    request = with_minimum(cap_request(plan_request, [.20], need=3), 1.5)
    result = plan_unpriced(request)
    assert result.reason == "price_policy_unavailable" and not result.periods and not result.unpriced


def test_no_published_candidate_reports_shortfalls(plan_request):
    request = with_minimum(cap_request(plan_request, [.20], need=3), 1.5)
    request = replace(request, now=request.now + timedelta(hours=1), window_end=request.now + timedelta(hours=2))
    result = calculate_plan(request)
    assert result.reason == "insufficient_price_horizon"
    assert result.policy_shortfall_kwh == pytest.approx(3)
    assert result.minimum_shortfall_kwh == pytest.approx(1.5)
    assert not result.periods and result.exception_kwh == 0
