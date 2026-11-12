"""Capped target-energy resolution against the actual Auto controller module."""

import pytest
from dataclasses import replace
from datetime import timedelta

from custom_components.spotnav.planning.auto_controller import LiveVehicleFacts, capped_vehicle_energy
from custom_components.spotnav.planning.learned_energy import LearnedEnergy, NOTHING_LEARNED
from custom_components.spotnav.planning.planner import calculate_plan

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_price_policy_guard import cap_request


def test_actual_soc_not_immediate_floor() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=5, reported_capacity_kwh=60, min_percent=35)
    reason, target, minimum = capped_vehicle_energy(
        facts, target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED,
    )
    assert reason == "ok"
    assert target == pytest.approx(33 / 0.9)
    assert minimum == pytest.approx(9 / 0.9)


def test_fractional_minimum() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=36.5, soc_age_s=0, reported_capacity_kwh=60)
    _, _, minimum = capped_vehicle_energy(facts, target_percent=80, minimum_percent=40.5, learned=NOTHING_LEARNED)
    assert minimum == pytest.approx(2.4 / 0.9)


@pytest.mark.parametrize("age,estimated", [(None, False), (181, False), (0, True), (-1, False)])
def test_untrusted_soc(age, estimated) -> None:
    facts = LiveVehicleFacts(
        vehicle_id="veh-1", soc_percent=25, soc_age_s=age, soc_estimated=estimated, reported_capacity_kwh=60,
    )
    assert capped_vehicle_energy(facts, target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED) == (
        "target_soc_stale", None, None,
    )


def test_minimum_above_resolved_target() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=5, reported_capacity_kwh=60, max_percent=35)
    assert capped_vehicle_energy(facts, target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED) == (
        "minimum_above_target", None, None,
    )


@pytest.mark.parametrize("minimum, expected", [(None, None), (40, 0)])
def test_minimum_already_met_or_unset(minimum, expected) -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=45, soc_age_s=1, reported_capacity_kwh=60)
    reason, _, actual = capped_vehicle_energy(facts, target_percent=80, minimum_percent=minimum, learned=NOTHING_LEARNED)
    assert reason == "ok" and actual == expected


def test_missing_capacity() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=5)
    assert capped_vehicle_energy(facts, target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED) == (
        "target_capacity_unknown", None, None,
    )


def test_trusted_learned_wall_energy_is_shared() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=5, reported_capacity_kwh=60)
    learned = LearnedEnergy(vehicle_id="veh-1", kwh_per_percent=0.8, samples=(), trusted=True)
    reason, target, minimum = capped_vehicle_energy(facts, target_percent=80, minimum_percent=40, learned=learned)
    assert reason == "ok"
    assert target == pytest.approx(44)
    assert minimum == pytest.approx(12)


def test_vehicle_energy_can_feed_actual_pure_planner() -> None:
    facts = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=25, soc_age_s=5, reported_capacity_kwh=60)
    _, target, minimum = capped_vehicle_energy(facts, target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED)
    scenario = fixture_payload()["scenarios"][0]
    base = build_request(scenario["request"], parse_documents(scenario["documents"]))
    request = cap_request(base, [0.2] * 8, need=target)
    result = calculate_plan(replace(request, minimum_energy_kwh=minimum))
    assert result.requested_kwh == pytest.approx(33 / .9)
    assert result.delivered_kwh == pytest.approx(9 / .9)
    assert result.exception_kwh == pytest.approx(9 / .9)
    assert result.periods == (
        (request.now + timedelta(minutes=15), request.now + timedelta(minutes=105)),
        (request.now + timedelta(minutes=110), request.now + timedelta(minutes=120)),
    )
