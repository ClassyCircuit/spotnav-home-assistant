"""Actual Morek comparator used as preliminary session-start safety evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.spotnav.api.morek_schedule import session_start_schedule_evidence

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def sample():
    at = lambda value: value.isoformat()  # noqa: E731
    profile = {"chargingSchedule": {"startSchedule": at(NOW - timedelta(minutes=1)),
        "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0},
                                   {"startPeriod": 660, "limit": 16},
                                   {"startPeriod": 1260, "limit": 0}]}}
    actual = {"status": "Accepted", "rate_unit": "A", "requested_at": at(NOW), "fetched_at": at(NOW),
              "schedule_start": at(NOW), "duration_s": 7200,
              "periods": [{"at": at(NOW), "amps": 0},
                          {"at": at(NOW + timedelta(minutes=10)), "amps": 16},
                          {"at": at(NOW + timedelta(minutes=20)), "amps": 0}]}
    return profile, actual


def test_matching_is_only_bounded_schedule_evidence():
    profile, actual = sample()
    assert session_start_schedule_evidence(profile, actual, NOW + timedelta(seconds=30)) == "matched"
    assert session_start_schedule_evidence(profile, actual, NOW + timedelta(seconds=31)) == "readback_stale"
    assert session_start_schedule_evidence(profile, actual, NOW - timedelta(seconds=1)) == "readback_stale"


@pytest.mark.parametrize(("mutation", "expected"), [
    ("missing", "readback_unavailable"),
    ("unit", "readback_unit_unavailable"),
    ("short", "coverage_too_short"),
    ("wrong_limit", "limits_or_transitions_differ"),
    ("drift", "limits_or_transitions_differ"),
])
def test_refuses_incomplete_or_different_evidence(mutation, expected):
    profile, actual = sample()
    actual = deepcopy(actual)
    if mutation == "missing":
        actual = None
    elif mutation == "unit":
        actual["rate_unit"] = "W"
    elif mutation == "short":
        actual["duration_s"] = 60
    elif mutation == "wrong_limit":
        actual["periods"][0]["amps"] = 16
    else:
        actual["periods"][1]["at"] = (NOW + timedelta(minutes=10, seconds=1)).isoformat()
    assert session_start_schedule_evidence(profile, actual, NOW) == expected


def test_no_plan_never_uses_readback_as_authority():
    _, actual = sample()
    assert session_start_schedule_evidence(None, actual, NOW) == "no_current_plan"


@pytest.mark.parametrize(("drift", "expected"), [
    (0, "matched"), (56, "matched"), (90, "matched"),
    (91, "limits_or_transitions_differ"),
])
def test_bounded_drift_away_from_transition(drift, expected):
    profile, actual = sample()
    for index, minutes in ((1, 10), (2, 20)):
        actual["periods"][index]["at"] = (NOW + timedelta(minutes=minutes, seconds=drift)).isoformat()
    assert session_start_schedule_evidence(profile, actual, NOW, tolerance_s=90) == expected


def test_boundary_ambiguity_and_current_disagreement_block():
    profile, actual = sample()
    actual["periods"][1]["at"] = (NOW + timedelta(minutes=10, seconds=56)).isoformat()
    actual["periods"][2]["at"] = (NOW + timedelta(minutes=20, seconds=56)).isoformat()
    # Simulate a newly obtained read shortly before the first transition.
    read = NOW + timedelta(minutes=8, seconds=20)
    actual.update({"requested_at": read.isoformat(), "fetched_at": read.isoformat(),
                   "schedule_start": read.isoformat()})
    actual["periods"][0]["at"] = read.isoformat()
    assert session_start_schedule_evidence(profile, actual, read + timedelta(seconds=20), tolerance_s=90) == "transition_boundary_ambiguous"
