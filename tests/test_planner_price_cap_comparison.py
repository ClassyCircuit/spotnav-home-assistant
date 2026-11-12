"""Price-cap comparison uses the same units and fiscal arithmetic as planning."""

from datetime import datetime, timezone

import pytest

from custom_components.spotnav.planning.planner import FiscalChoice, PlannerInputError, price_within_cap


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("price", "cap", "allowed"),
    [(-0.10, -0.10, True), (-0.09, -0.10, False), (0.0, 0.0, True), (0.1, 0.1, True), (0.11, 0.1, False)],
)
def test_published_basis(price, cap, allowed):
    assert price_within_cap(
        price, cap_major_per_kwh=cap, basis="nord_pool", fiscal=FiscalChoice(), start=NOW
    ) is allowed


def test_configured_basis_uses_minor_fee_then_vat():
    fiscal = FiscalChoice(tax_enabled=True, tax_minor_per_kwh=2, vat_enabled=True, vat_percent=25)
    assert price_within_cap(0.08, cap_major_per_kwh=0.10, basis="nord_pool", fiscal=fiscal, start=NOW)
    assert not price_within_cap(
        0.08, cap_major_per_kwh=0.10, basis="configured_variable_cost", fiscal=fiscal, start=NOW
    )
    assert price_within_cap(
        0.08, cap_major_per_kwh=0.125, basis="configured_variable_cost", fiscal=fiscal, start=NOW
    )


@pytest.mark.parametrize("basis,price", [("unknown", 0.1), ("nord_pool", float("nan"))])
def test_bad_basis_or_price_is_refused(basis, price):
    with pytest.raises(PlannerInputError):
        price_within_cap(price, cap_major_per_kwh=0.1, basis=basis, fiscal=FiscalChoice(), start=NOW)


def test_missing_enabled_fee_is_refused():
    with pytest.raises(PlannerInputError):
        price_within_cap(
            0.08, cap_major_per_kwh=0.1, basis="configured_variable_cost",
            fiscal=FiscalChoice(tax_enabled=True), start=NOW,
        )
