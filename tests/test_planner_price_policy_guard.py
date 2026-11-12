"""Cheap-only capped planning and the separate unpriced safety guard."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.spotnav.planning.planner import (
    FiscalChoice, PlannerInputError, calculate_plan, ending_at_need, plan_unpriced,
)
from .planning import build_request, fixture_payload, parse_documents


@pytest.fixture
def plan_request():
    scenario = fixture_payload()["scenarios"][0]
    return build_request(scenario["request"], parse_documents(scenario["documents"]))


@pytest.mark.parametrize("cap", [-0.10, 0.0, 0.10])
@pytest.mark.parametrize("basis", ["nord_pool", "configured_variable_cost"])
def test_configured_cap_never_reaches_unpriced_fallback(plan_request, cap, basis):
    capped = replace(plan_request, soft_price_cap=cap, cap_price_basis=basis)
    plan = plan_unpriced(capped)
    assert plan.reason == "price_policy_unavailable"
    assert not plan.periods and not plan.unpriced


def test_null_cap_preserves_existing_planner(plan_request):
    assert calculate_plan(plan_request) == calculate_plan(replace(plan_request, soft_price_cap=None))


@pytest.mark.parametrize("value", [True, float("inf"), float("nan")])
def test_invalid_cap_rejected(plan_request, value):
    with pytest.raises(PlannerInputError):
        calculate_plan(replace(plan_request, soft_price_cap=value, cap_price_basis="nord_pool"))


def test_cap_requires_basis(plan_request):
    with pytest.raises(PlannerInputError):
        calculate_plan(replace(plan_request, soft_price_cap=0))


def cap_request(plan_request, prices, *, need=3.0, periods=8, cap=0.10, basis="nord_pool", fiscal=None):
    doc = replace(plan_request.documents[0], prices=tuple(prices))
    start = doc.start_instant
    return replace(
        plan_request, documents=(doc,), currency="EUR", now=start, departure=None,
        departure_date=None, window_end=start + timedelta(minutes=15 * len(prices)),
        phases=3, amps=16, power_cap_kw=6.0, requested_kwh=need,
        max_periods=periods, soft_price_cap=cap, cap_price_basis=basis, fiscal=fiscal or FiscalChoice(),
    )


def test_cheap_only_exact_two_slots(plan_request):
    request = cap_request(plan_request, [0.05, 0.2, 0.04, 0.3])
    result = calculate_plan(request)
    start = request.now
    assert result.periods == ((start, start + timedelta(minutes=15)),
                              (start + timedelta(minutes=30), start + timedelta(minutes=45)))
    assert result.delivered_kwh == pytest.approx(3)
    assert result.policy_shortfall_kwh == pytest.approx(0)
    assert result.estimated_cost == pytest.approx(0.135)
    assert result.periods == result.shown_periods


def test_partial_duration_and_cost_are_actual(plan_request):
    request = cap_request(plan_request, [0.1, 0.2], need=1)
    result = calculate_plan(request)
    assert len(result.slots) == 1
    assert result.periods == ((request.now + timedelta(minutes=5), request.now + timedelta(minutes=15)),)
    assert result.periods[0][1] - result.periods[0][0] == timedelta(minutes=10)
    assert result.periods == result.shown_periods
    assert result.delivered_kwh == pytest.approx(1)
    assert result.estimated_cost == pytest.approx(0.1)
    assert ending_at_need(result) == result


def test_shortfall_and_no_eligible_energy(plan_request):
    result = calculate_plan(cap_request(plan_request, [0.05, 0.2], need=3))
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.policy_shortfall_kwh == pytest.approx(1.5)
    assert not result.unpriced
    empty = calculate_plan(cap_request(plan_request, [0.2, 0.3], need=3))
    assert empty.reason == "no_eligible_energy"
    assert empty.periods == ()
    assert empty.policy_shortfall_kwh == pytest.approx(3)


def test_period_limit_never_bridges_excluded_gap(plan_request):
    result = calculate_plan(cap_request(plan_request, [0.05, 0.2, 0.04], periods=1))
    assert len(result.periods) == 1
    assert result.periods[0][0] == plan_request.documents[0].start_instant + timedelta(minutes=30)
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.policy_shortfall_kwh == pytest.approx(1.5)


@pytest.mark.parametrize("price,cap", [(0.0, 0.0), (-0.1, -0.1), (-0.2, -0.1)])
@pytest.mark.parametrize("basis", ["nord_pool", "configured_variable_cost"])
def test_equality_and_negative_prices(plan_request, price, cap, basis):
    result = calculate_plan(cap_request(plan_request, [price], need=1.5, cap=cap, basis=basis))
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.estimated_cost == pytest.approx(price * 1.5)


def test_configured_fees_change_eligibility(plan_request):
    fiscal = FiscalChoice(tax_enabled=True, tax_minor_per_kwh=3)
    raw = cap_request(plan_request, [0.08], need=1.5, fiscal=fiscal)
    assert calculate_plan(raw).delivered_kwh == pytest.approx(1.5)
    result = calculate_plan(replace(raw, cap_price_basis="configured_variable_cost"))
    assert result.reason == "no_eligible_energy"


def test_unpublished_horizon_does_not_supply_energy(plan_request):
    request = cap_request(plan_request, [0.05], need=3)
    request = replace(request, window_end=request.now + timedelta(hours=2))
    result = calculate_plan(request)
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.policy_shortfall_kwh == pytest.approx(1.5)
    assert len(result.slots) == 1 and not result.unpriced


def test_unpublished_gap_is_not_a_contiguous_run(plan_request):
    request = cap_request(plan_request, [0.05], need=3, periods=1)
    first = request.documents[0]
    second = replace(first, start_instant=first.start_instant + timedelta(minutes=30), prices=(0.04,))
    result = calculate_plan(replace(request, documents=(first, second), window_end=request.now + timedelta(hours=1)))
    assert result.delivered_kwh == pytest.approx(1.5)
    assert len(result.periods) == 1
    assert result.periods[0][0] == request.now + timedelta(minutes=30)


def test_short_deadline_uses_known_partial_interval(plan_request):
    request = cap_request(plan_request, [0.05], need=3)
    result = calculate_plan(replace(request, window_end=request.now + timedelta(minutes=10)))
    assert result.periods == ((request.now, request.now + timedelta(minutes=10)),)
    assert result.delivered_kwh == pytest.approx(1)
    assert result.policy_shortfall_kwh == pytest.approx(2)
    assert result.estimated_cost == pytest.approx(0.05)


def test_deadline_fragment_only_buys_needed_remainder(plan_request):
    request = cap_request(plan_request, [0.01, 0.09], need=2, periods=1)
    result = calculate_plan(replace(request, window_end=request.now + timedelta(minutes=27)))
    assert result.periods == ((request.now, request.now + timedelta(minutes=20)),)
    assert result.delivered_kwh == pytest.approx(2)
    assert result.estimated_cost == pytest.approx(0.06)


def test_fraction_can_precede_cheaper_full_slot_without_bridging(plan_request):
    request = cap_request(plan_request, [0.09, 0.01], need=2, periods=1)
    result = calculate_plan(request)
    assert result.periods == ((request.now + timedelta(minutes=10), request.now + timedelta(minutes=30)),)
    assert result.estimated_cost == pytest.approx(0.06)


def test_converts_currency_before_comparing_cap(plan_request):
    request = cap_request(plan_request, [0.04, 0.06], need=3, cap=0.10)
    document = replace(request.documents[0], fx={"SEK": 2.0})
    result = calculate_plan(replace(request, documents=(document,), currency="SEK"))
    assert result.delivered_kwh == pytest.approx(1.5)
    assert result.estimated_cost == pytest.approx(0.12)
    assert result.policy_shortfall_kwh == pytest.approx(1.5)
    missing_fx = calculate_plan(replace(request, documents=(replace(document, fx={}),), currency="SEK"))
    assert missing_fx.reason == "missing_fx_rate" and not missing_fx.periods


def test_automatic_periods_never_bridge_gap(plan_request):
    result = calculate_plan(cap_request(plan_request, [0.04, 0.20, 0.05], periods=None))
    assert len(result.periods) == 2
    assert result.delivered_kwh == pytest.approx(3)
