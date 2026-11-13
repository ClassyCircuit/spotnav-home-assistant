"""Planner-to-dashboard plan details, using actual planner output and no HA I/O."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import dashboard
from custom_components.spotnav.planning.planner import FiscalChoice, calculate_plan, ending_at_need, plan_unpriced
from .planning import build_request, fixture_payload, parse_documents
from .test_planner_price_policy_guard import cap_request


def request():
    scenario = fixture_payload()["scenarios"][0]
    return build_request(scenario["request"], parse_documents(scenario["documents"]))


def section(plan, *, soc=25, ratio=0.75):
    snapshot = SimpleNamespace(proposal=plan, settings_revision=7, proposal_identity="plan", projection_soc=soc,
                               projection_kwh_per_percent=ratio, projection_age_s=86400,
                               projection_source="vehicle", projection_estimated=False)
    return dashboard._proposal_section(SimpleNamespace(snapshot=snapshot, settings=None, area_entry=None))


def test_actual_capped_multiple_partial_windows_and_projection():
    plan = calculate_plan(cap_request(request(), [0.05, 0.2, 0.04, 0.3], need=2))
    data = section(plan)
    rows = data["window_details"]
    assert len(rows) == 2
    assert sum(row["energy_kwh"] for row in rows) == pytest.approx(plan.delivered_kwh)
    assert sum(row["cost"] for row in rows) == pytest.approx(plan.estimated_cost)
    assert rows[-1]["projected_soc"] == pytest.approx(25 + plan.delivered_kwh / .75)
    assert data["cost_basis"] == "configured_variable_cost" and data["cost"]["currency"] == "EUR"
    assert data["projection"]["age_s"] == 86400


def test_uncapped_shortened_final_slot_and_unpriced_plan():
    base = cap_request(request(), [0.05, 0.2, 0.04, 0.3], need=2)
    uncapped = replace(base, soft_price_cap=None, cap_price_basis=None, window_end=None)
    plan = ending_at_need(calculate_plan(replace(request(), requested_kwh=2)))
    assert plan.has_plan and plan.ends_at_need and plan.need_met_at is not None
    data = section(plan)
    assert sum(row["energy_kwh"] for row in data["window_details"]) == pytest.approx(plan.delivered_kwh)
    assert sum(row["cost"] for row in data["window_details"]) == pytest.approx(plan.estimated_cost)
    unpriced = plan_unpriced(uncapped)
    assert unpriced.has_plan and unpriced.unpriced
    data = section(unpriced, soc=None, ratio=None)
    assert data["cost_basis"] is None and data["cost"] is None
    assert all(row["cost"] is None and "projected_soc" not in row for row in data["window_details"])


def test_uncapped_negative_price_partial_window_reconciles():
    base = cap_request(request(), [-.1, -.2, -.04, -.3], need=2)
    plan = ending_at_need(calculate_plan(replace(base, soft_price_cap=None, cap_price_basis=None)))
    assert plan.has_plan and plan.need_met_at is not None
    rows = section(plan)["window_details"]
    assert sum(row["energy_kwh"] for row in rows) == pytest.approx(plan.delivered_kwh)
    assert sum(row["cost"] for row in rows) == pytest.approx(plan.estimated_cost)
    assert plan.estimated_cost < 0


def test_shortened_target_across_dst_and_short_deadline():
    from .test_planner_deadline_dst import SPRING, SPRING_NOW, request as dst_request
    plan = ending_at_need(calculate_plan(dst_request(SPRING_NOW, "06:00", 10, SPRING)))
    assert plan.need_met_at is not None
    rows = section(plan)["window_details"]
    assert sum(row["energy_kwh"] for row in rows) == pytest.approx(plan.delivered_kwh)
    assert sum(row["cost"] for row in rows) == pytest.approx(plan.estimated_cost)
    short = calculate_plan(dst_request(SPRING_NOW, "06:00", 16, SPRING))
    assert short.short_of_deadline
    assert ending_at_need(short) == short


def test_inconsistent_or_missing_slots_do_not_invent_details():
    plan = calculate_plan(cap_request(request(), [0.05, 0.2, 0.04, 0.3]))
    assert section(replace(plan, slots=()))["window_details"] is None
    assert section(replace(plan, estimated_cost=plan.estimated_cost + 1))["window_details"] is None
    slot = plan.slots[0]
    broken = replace(slot, end=slot.end - timedelta(seconds=1))
    assert section(replace(plan, slots=(broken, *plan.slots[1:])))["window_details"] is None


def test_effective_tariff_basis_and_negative_price_are_preserved():
    fiscal = FiscalChoice(tax_enabled=True, tax_minor_per_kwh=2, vat_enabled=True, vat_percent=25)
    plan = calculate_plan(cap_request(request(), [-.1, .2, -.04, .3], need=2, fiscal=fiscal))
    data = section(plan)
    assert data["cost_basis"] == "configured_variable_cost"
    assert data["cost"]["value"] == pytest.approx(sum(row["cost"] for row in data["window_details"]))
    assert data["cost"]["value"] < 0
    non_eur = section(replace(plan, currency="SEK"))
    assert non_eur["cost"]["currency"] == "SEK"
