"""Stage 19.4: ahead-of-time horizon, covered-span effective verification, offline-safe status facts.

Mocked and pure: nothing here shows installed behavior, the charger's clock/firmware, or physical charging."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.api.morek_schedule import (
    COVERAGE_DIFFERS, COVERAGE_MATCHES, COVERAGE_SPAN, COVERAGE_UNVERIFIABLE,
    ScheduleRefused, compare_schedule, profile_for, readback, same_effective_schedule, schedule_horizon,
)

NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)
TOL = timedelta(seconds=morek_schedule.VERIFY_TOLERANCE_S)
THREE = ((NOW + H, NOW + 2 * H), (NOW + 4 * H, NOW + 5 * H), (NOW + 7 * H, NOW + 8 * H))


def _reply(duration, periods):
    return readback(SimpleNamespace(status="Accepted", schedule_start=NOW.isoformat(), charging_schedule={
        "chargingRateUnit": "A", "duration": duration,
        "chargingSchedulePeriod": [{"startPeriod": s, "limit": a} for s, a in periods]}), NOW)


FULL = [(0, 0), (3600, 16), (7200, 0), (14400, 16), (18000, 0), (25200, 16), (28800, 0)]


def _transitions(profile):
    return [(p["startPeriod"], p["limit"]) for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]


def test_wire_profile_covers_every_known_window_through_its_end_and_never_truncates():
    profile = profile_for(THREE, 16, NOW)
    assert _transitions(profile) == FULL  # every window, final 0 A, seven transitions
    # A fourth window would exceed the three-window hardware limit: refused, never silently cut short.
    with pytest.raises(ScheduleRefused, match="too_many_blocks"):
        profile_for(THREE + ((NOW + 10 * H, NOW + 11 * H),), 16, NOW)


def test_partial_price_day_sends_only_the_known_part_and_a_later_publication_extends_once():
    known = profile_for(THREE[:1], 16, NOW)
    assert _transitions(known) == [(0, 0), (3600, 16), (7200, 0)]  # nothing invented beyond the known window
    extended = profile_for(THREE[:2], 16, NOW)
    assert _transitions(extended)[:3] == _transitions(known)
    assert not same_effective_schedule(known, extended)  # extension is a real difference: one compared send
    again = profile_for(THREE[:2], 16, NOW + timedelta(minutes=10))
    assert same_effective_schedule(extended, again)  # republication of the equal schedule sends nothing


def test_active_window_is_carried_without_a_zero_amp_gap_when_the_horizon_extends():
    active = ((NOW - H, NOW + H), THREE[1])
    profile = profile_for(active, 16, NOW, allow_active=True)
    assert _transitions(profile) == [(0, 16), (3600, 0), (14400, 16), (18000, 0)]


def test_full_readback_matches_with_whole_plan_coverage():
    comparison = compare_schedule(profile_for(THREE, 16, NOW), _reply(36000, FULL))
    assert comparison["matched"] is True and comparison["coverage_state"] == COVERAGE_MATCHES
    assert comparison["plan_end"] == (NOW + 8 * H).isoformat()
    assert comparison["covered_until"] == (NOW + 10 * H).isoformat()


def test_shorter_readback_reports_covered_span_and_is_never_a_full_match():
    profile = profile_for(THREE, 16, NOW)
    comparison = compare_schedule(profile, _reply(6 * 3600, FULL[:5]))
    assert comparison["matched"] is False and comparison["reason"] == "coverage_too_short"
    assert comparison["coverage_state"] == COVERAGE_SPAN
    # The claim stops where comparison stopped: the final tolerance margin was never compared.
    assert comparison["covered_until"] == (NOW + 6 * H - TOL).isoformat()
    assert comparison["coverage_end"] == (NOW + 6 * H).isoformat()
    assert comparison["plan_end"] == (NOW + 8 * H).isoformat()


def test_covered_until_never_extends_over_a_mismatch_inside_the_trailing_margin():
    # Readback ends 5 h 0 min 30 s; the expected 5 h stop is inside the margin, the observed one is wrong (16 A kept).
    # The mismatch is unchecked, so the claim must end before it, never at the reported end.
    wrong = [(0, 0), (3600, 16), (7200, 0), (14400, 16)]  # no 5 h stop observed at all
    comparison = compare_schedule(profile_for(THREE, 16, NOW), _reply(5 * 3600 + 30, wrong))
    assert comparison["coverage_state"] == COVERAGE_SPAN and comparison["matched"] is False
    covered = datetime.fromisoformat(comparison["covered_until"])
    assert covered <= NOW + 5 * H - timedelta(seconds=1)  # before the unchecked 5 h transition
    assert covered == NOW + 5 * H + timedelta(seconds=30) - TOL
    # A readback ending within the margin of the observed transition leaves it equally unchecked.
    moved = [(0, 0), (3600, 16), (7200, 0), (14400, 16), (18000 + 20, 0)]
    shifted = compare_schedule(profile_for(THREE, 16, NOW), _reply(5 * 3600 + 30, moved))
    assert shifted["coverage_state"] == COVERAGE_SPAN
    assert datetime.fromisoformat(shifted["covered_until"]) < NOW + 5 * H


def test_short_or_expired_span_makes_no_claim():
    profile = profile_for(THREE, 16, NOW)
    # Shorter than the margin itself: nothing was compared, so no span claim and no covered_until beyond the read.
    tiny = compare_schedule(profile, _reply(60, [(0, 0)]))
    assert tiny["coverage_state"] == COVERAGE_UNVERIFIABLE
    comparison = compare_schedule(profile, _reply(6 * 3600, FULL[:5]))
    base = dict(comparison, readback_at="r")
    inside = dict(base)
    morek_schedule._guard_coverage_state(inside, True, NOW + 6 * H - 2 * TOL)
    assert inside["coverage_state"] == COVERAGE_SPAN
    # Between the compared end and the reported end the span claim already no longer holds.
    margin = dict(base)
    morek_schedule._guard_coverage_state(margin, True, NOW + 6 * H - TOL / 2)
    assert margin["coverage_state"] == COVERAGE_UNVERIFIABLE and margin["covered_until"] is None


def test_shorter_readback_with_a_differing_span_is_differs_not_a_match():
    changed = [(0, 0), (3600, 16), (7200, 0), (14400, 10), (18000, 0)]
    comparison = compare_schedule(profile_for(THREE, 16, NOW), _reply(6 * 3600, changed))
    assert comparison["matched"] is False and comparison["coverage_state"] == COVERAGE_DIFFERS


def test_transition_at_the_edge_of_a_short_readback_is_not_judged():
    # Covered end 5 h 0 min 30 s: the 5 h stop is inside the tolerance of the edge, so the span ends before it.
    comparison = compare_schedule(profile_for(THREE, 16, NOW), _reply(5 * 3600 + 30, FULL[:5]))
    assert comparison["coverage_state"] == COVERAGE_SPAN and comparison["matched"] is False
    # A readback that covers almost nothing says nothing.
    tiny = compare_schedule(profile_for(THREE, 16, NOW), _reply(60, [(0, 0)]))
    assert tiny["coverage_state"] == COVERAGE_UNVERIFIABLE and tiny["matched"] is False


def test_full_differing_readback_and_unavailable_readback_states():
    differing = [(0, 0), (3600, 16), (7200, 0), (14400, 16), (19000, 0), (25200, 16), (28800, 0)]
    assert compare_schedule(profile_for(THREE, 16, NOW), _reply(36000, differing))["coverage_state"] == COVERAGE_DIFFERS
    unavailable = compare_schedule(profile_for(THREE, 16, NOW), {"status": "unavailable", "periods": []})
    assert unavailable["coverage_state"] == COVERAGE_UNVERIFIABLE and unavailable["covered_until"] is None
    assert compare_schedule(None, None)["coverage_state"] == COVERAGE_UNVERIFIABLE


def test_status_guard_never_keeps_a_coverage_claim_for_the_wrong_readback_or_after_it_expired():
    base = {"coverage_state": COVERAGE_SPAN, "covered_until": (NOW + 6 * H - TOL).isoformat(), "reason": "coverage_too_short",
            "coverage_start": NOW.isoformat(), "coverage_end": (NOW + 6 * H).isoformat(), "matched": False}
    mine = dict(base)
    morek_schedule._guard_coverage_state(mine, True, NOW + H)
    assert mine["coverage_state"] == COVERAGE_SPAN
    expired = dict(base)
    morek_schedule._guard_coverage_state(expired, True, NOW + 7 * H)
    assert expired["coverage_state"] == COVERAGE_UNVERIFIABLE and expired["covered_until"] is None
    foreign = dict(base)
    morek_schedule._guard_coverage_state(foreign, False, NOW + H)
    assert foreign["coverage_state"] == COVERAGE_UNVERIFIABLE
    superseded = dict(base, reason="verification_superseded")
    morek_schedule._guard_coverage_state(superseded, True, NOW + H)
    assert superseded["coverage_state"] == COVERAGE_UNVERIFIABLE
    differs = dict(base, coverage_state=COVERAGE_DIFFERS, reason="limits_or_transitions_differ")
    morek_schedule._guard_coverage_state(differs, True, NOW + H)
    assert differs["coverage_state"] == COVERAGE_DIFFERS


def test_schedule_horizon_states_plain_facts_and_no_physical_claim():
    profile = profile_for(THREE, 16, NOW)
    verification = {"coverage_state": COVERAGE_SPAN, "covered_until": (NOW + 6 * H).isoformat()}
    horizon = schedule_horizon(profile, "Accepted", verification, NOW + H)
    assert horizon["state"] == "sent" and horizon["windows"] == 3 and horizon["ack"] == "accepted"
    assert horizon["plan_end"] == (NOW + 8 * H).isoformat() and horizon["plan_ended"] is False
    assert horizon["coverage_state"] == COVERAGE_SPAN and horizon["covered_until"] == (NOW + 6 * H).isoformat()
    assert horizon["physical_charging"] == "unknown"
    assert schedule_horizon(profile, "Accepted", {}, NOW + 9 * H)["plan_ended"] is True
    assert schedule_horizon(profile, "Accepted", {}, NOW)["coverage_state"] is None  # no readback: no claim
    assert schedule_horizon(None, None, {}, NOW)["state"] == "none"
    assert schedule_horizon({"chargingSchedule": {}}, None, {}, NOW)["state"] == "none"
