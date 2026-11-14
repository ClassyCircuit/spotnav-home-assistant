"""Stage 15.1a: the planner time reserve, backend only.

Real settings codec/store, real planner output, the real controller and the real window-release decision (HA,
charger and ownership are the usual mocked boundaries). Mocked only: not proof of installed behavior, charger
clock behavior or physical charging.
"""

from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import dashboard, morek_schedule, settings as settings_api
from custom_components.spotnav.api.settings import decode_settings, encode_settings, replacement_mutator
from custom_components.spotnav.planning.auto_settings import (
    AutoSettings, AutoSettingsError, DEFAULT_TIME_RESERVE_PERCENT, TargetSocIntent,
)
from custom_components.spotnav.planning.planner import (
    PlannerInputError, RESERVE_MAX, RESERVE_RESOLUTION, calculate_plan, ending_at_need, plan_unpriced, with_time_reserve,
)

from .planning import build_request, fixture_payload, parse_documents
from .test_planner_current_interval import mid
from .test_planner_deadline_dst import day, request as dst_request
from .test_planner_price_policy_guard import cap_request
from .test_stage_13_reactive import _world
from .test_stage_141_current_interval import _plan, _prices

MIN = timedelta(minutes=1)
H = timedelta(hours=1)
KW = 6.0  # `cap_request` plans at 6 kW: a quarter-hour is 1.5 kWh


@pytest.fixture
def base():
    scenario = fixture_payload()["scenarios"][0]
    return build_request(scenario["request"], parse_documents(scenario["documents"]))


def planned(request, percent=10, **changes):
    """(request, plain result, result with reserve) the way the controller builds them (Morek flags on)."""
    request = replace(request, time_reserve_percent=percent, **changes)
    plain = calculate_plan(request)
    return request, plain, with_time_reserve(request, plain)


def length(spans):
    return sum((end - start for start, end in spans), timedelta(0))


def windows_of(profile):
    """The fixed-time windows a profile allows, as absolute instants."""
    schedule = profile["chargingSchedule"]
    start = datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00"))
    out, opened = [], None
    for item in schedule["chargingSchedulePeriod"]:
        at = start + timedelta(seconds=item["startPeriod"])
        if item["limit"] and opened is None:
            opened = at
        elif not item["limit"] and opened is not None:
            out.append((opened, at))
            opened = None
    return out


# ---- settings: validation, storage, migration, API ------------------------------------------------------

def test_default_is_ten_and_an_old_record_loads_as_ten():
    assert AutoSettings().time_reserve_percent == DEFAULT_TIME_RESERVE_PERCENT == 10
    stored = AutoSettings().as_dict()
    assert "time_reserve_percent" not in stored  # absent in a stored record is the default
    assert AutoSettings.from_stored(stored).time_reserve_percent == 10


@pytest.mark.parametrize("percent", [0, 1, 10, 25, 50])
def test_storage_and_wire_roundtrip(percent):
    settings = replace(AutoSettings(), time_reserve_percent=percent).validated()
    stored = settings.as_dict()
    assert ("time_reserve_percent" in stored) == (percent != 10)
    assert AutoSettings.from_stored(stored) == settings
    wire = {k: v for k, v in encode_settings(settings).items() if k != "revision"}
    assert wire["time_reserve_percent"] == percent
    assert decode_settings(wire) == replace(settings, revision=0)


@pytest.mark.parametrize("value", [-1, 51, 100, 10.5, "10", None, True, False, float("nan")])
def test_invalid_reserve_is_refused_everywhere(value):
    with pytest.raises(AutoSettingsError):
        replace(AutoSettings(), time_reserve_percent=value).validated()
    wire = {k: v for k, v in encode_settings(AutoSettings()).items() if k != "revision"}
    wire["time_reserve_percent"] = value
    with pytest.raises(AutoSettingsError):
        decode_settings(wire)
    with pytest.raises(AutoSettingsError):
        AutoSettings.from_stored({**AutoSettings().as_dict(), "time_reserve_percent": value})


def test_omitted_key_keeps_the_stored_value(monkeypatch):
    current = replace(AutoSettings(), time_reserve_percent=30, target=TargetSocIntent("car", 80)).validated()
    wire = {k: v for k, v in encode_settings(current).items() if k != "revision"}
    wire.pop("time_reserve_percent")
    wire["amps"] = 10
    monkeypatch.setattr(settings_api, "domain_data", lambda _: SimpleNamespace(auto_store=None))
    monkeypatch.setattr(settings_api.vehicle_properties, "stored_properties", lambda *_: SimpleNamespace(target_percent=None))
    updated = settings_api.body_mutator(None, "charger", wire, decode_settings(wire))(current).validated()
    assert (updated.time_reserve_percent, updated.amps) == (30, 10)
    # Named explicitly (even back to the default), it is the person's value.
    wire["time_reserve_percent"] = 10
    explicit = settings_api.body_mutator(None, "charger", wire, decode_settings(wire))(current).validated()
    assert explicit.time_reserve_percent == 10


@pytest.mark.asyncio
async def test_reserve_edit_is_a_compare_and_set_revision(monkeypatch):
    world = await _world(monkeypatch)
    saved = world.store.settings("test")
    wire = {k: v for k, v in encode_settings(saved).items() if k != "revision"}
    wire["time_reserve_percent"] = 20
    mutate = replacement_mutator(decode_settings(wire), keep_cap_price_basis=False)
    changed = await world.store.async_update("test", mutate=mutate, expected_revision=saved.revision)
    assert changed.time_reserve_percent == 20 and changed.revision == saved.revision + 1
    with pytest.raises(AutoSettingsError) as conflict:
        await world.store.async_update("test", mutate=mutate, expected_revision=saved.revision)
    assert conflict.value.code == "revision_conflict"
    assert world.store.settings("test").time_reserve_percent == 20


def test_planner_request_validates_the_percent(base):
    for bad in (-1, 51, 5.5, True, "10"):
        with pytest.raises(PlannerInputError):
            calculate_plan(replace(base, time_reserve_percent=bad))


# ---- planner: reserve length, placement, baseline untouched ---------------------------------------------

def test_zero_percent_changes_nothing(base):
    request = cap_request(base, [.1, .2], need=1)
    result = calculate_plan(request)
    assert with_time_reserve(request, result) is result
    assert with_time_reserve(replace(request, time_reserve_percent=0), result) is result
    assert result.shown_periods == result.baseline_shown_periods == result.periods_with_reserve == result.periods
    assert result.reserve_minutes == 0 and result.reserve_pieces == () and result.reserve_percent == 0


def test_short_need_gets_a_proportionally_short_reserve_not_a_whole_slot(base):
    # 1 kWh at 6 kW = 10 minutes of charging; 10 % is one minute, never a 15-minute slot.
    request, plain, result = planned(cap_request(base, [.1, .1, .2, .2], need=1))
    assert length(plain.shown_periods) == 10 * MIN
    assert result.reserve_minutes == pytest.approx(1) and result.reserve_requested_minutes == pytest.approx(1)
    assert result.reserve_limit is None
    assert length(result.shown_periods) == 11 * MIN
    # The baseline is untouched: same periods, slots, energy and cost as without the reserve.
    for name in ("periods", "slots", "delivered_kwh", "estimated_cost", "policy_shortfall_kwh",
                 "baseline_shown_periods", "need_met_at", "exact_periods"):
        assert getattr(result, name) == getattr(plain, name)
    assert result.baseline_shown_periods == plain.shown_periods
    # Allowance: separately labelled, at plan power and the reserve's own price.
    assert result.reserve_energy_kwh == pytest.approx(KW / 60)
    assert result.reserve_cost == pytest.approx(KW / 60 * 10 / 100 * 1)  # .1 EUR/kWh = 10 cent
    assert result.delivered_kwh == pytest.approx(1)  # not increased


def test_reserve_only_rounds_up_to_the_dispatch_resolution(base):
    # The Morek profile is dispatched in whole SECONDS (`profile_for` ceils a start and floors an end), so that is
    # the resolution: 2.5 kWh = 25 min -> 2.5 min exactly; no extra minute is invented.
    assert RESERVE_RESOLUTION == timedelta(seconds=1)
    for need, percent, seconds in ((2.5, 10, 150), (2.4, 10, 144), (3.0, 10, 180), (0.1, 10, 6),
                                   (0.1, 33, 20)):  # 60 s * 33 % = 19.8 s -> 20 s, the only rounding
        _, _, result = planned(cap_request(base, [.05] * 8, need=need), percent)
        assert result.reserve_requested_minutes * 60 == pytest.approx(seconds), (need, percent)
        assert result.reserve_minutes * 60 == pytest.approx(seconds), (need, percent)


def test_reserve_seconds_survive_the_profile_unchanged(base):
    # A 20 s reserve behind a 1-minute need is 20 s of permission on the wire, not a rounded-up minute.
    request, plain, result = planned(cap_request(base, [.05] * 8, need=0.1), 33)
    at = request.now - MIN
    wire = windows_of(morek_schedule.profile_for(tuple(result.shown_periods), 16, at, allow_active=True))
    plain_wire = windows_of(morek_schedule.profile_for(tuple(plain.shown_periods), 16, at, allow_active=True))
    assert length(wire) - length(plain_wire) == timedelta(seconds=20)


def test_reserve_is_at_most_two_hours(base):
    # A 20-hour need at 50 % would be 10 h: clamped to 2 h, and said so.
    request = cap_request(base, [.05] * 96, need=KW * 20)
    _, plain, result = planned(request, 50)
    assert result.reserve_requested_minutes == pytest.approx(120)
    assert result.reserve_minutes == pytest.approx(120) and result.reserve_limit == "two_hour_limit"
    assert RESERVE_MAX == 2 * H
    assert length(result.shown_periods) == length(plain.shown_periods) + 2 * H
    # Exactly two hours (10 % of 20 h) is not a clamp.
    _, _, ten = planned(request, 10)
    assert ten.reserve_minutes == pytest.approx(120) and ten.reserve_limit is None


def test_reserve_fits_what_it_can_and_never_changes_feasibility(base):
    # The need fills every eligible quarter: nothing is left for a reserve, and the plan stays feasible.
    request = cap_request(base, [.05, .05, .05, .05], need=KW)
    _, plain, result = planned(request)
    assert plain.reason is None and plain.policy_shortfall_kwh == pytest.approx(0)
    assert result.reserve_pieces == () and result.reserve_limit == "no_eligible_time"
    assert result.reserve_requested_minutes == pytest.approx(6) and result.reserve_minutes == 0
    assert result.shown_periods == plain.shown_periods and result.reason is None
    # A partial fit: 45 of 60 minutes used, 15 free, 10 % of 45 min is 4.5 -> 5 min: it fits.
    _, _, partial = planned(cap_request(base, [.05] * 4, need=KW * .75), 50)
    assert partial.reserve_minutes == pytest.approx(15) and partial.reserve_limit == "no_eligible_time"
    assert partial.reserve_requested_minutes == pytest.approx(22.5)  # 50 % of 45 min, to the second
    assert length(partial.shown_periods) == 60 * MIN  # every eligible minute before the deadline, no more


def test_reserve_never_goes_above_the_soft_cap_or_past_the_deadline(base):
    # Only the first and third quarter are cheap: the base takes one, the reserve may only use the other.
    request = cap_request(base, [.05, .20, .05, .20, .20, .20], need=1.5)
    _, plain, result = planned(request, 50)
    cheap = (request.now, request.now + 15 * MIN), (request.now + 30 * MIN, request.now + 45 * MIN)
    for start, end in result.reserve_periods:
        assert any(lo <= start and end <= hi for lo, hi in cheap)
    assert result.reserve_minutes == pytest.approx(7.5)  # 50 % of 15 min
    end = request.window_end
    assert all(end_ <= end for _, end_ in result.shown_periods)
    # Nothing cheap is free at all: no above-cap time is invented.
    _, _, none_free = planned(cap_request(base, [.05, .2, .2, .2], need=1.5), 50)
    assert none_free.reserve_pieces == () and none_free.reserve_limit == "no_eligible_time"
    # A minimum-SOC exception stays part of the baseline and is not extended above the cap by the reserve.
    exception = replace(cap_request(base, [.05, .2, .2, .2], need=3.0), minimum_energy_kwh=3.0)
    _, plain_exc, with_exc = planned(exception, 50)
    assert with_exc.exception_kwh == plain_exc.exception_kwh > 0
    assert with_exc.reserve_pieces == ()


def test_reserve_prefers_the_cheapest_time_then_continuing_a_window_then_the_earliest(base):
    request = cap_request(base, [.05, .04, .05, .03, .05, .05], need=1.5)
    _, plain, result = planned(request, 50)
    cheapest = (request.now + 45 * MIN, request.now + 60 * MIN)  # .03, the cheapest, is the base itself
    assert plain.periods == (cheapest,)
    # Next cheapest is .04 (slot 1), then .05; the 7.5 minutes come from slot 1, taken from its start.
    assert result.reserve_periods == ((request.now + 15 * MIN, request.now + 22 * MIN + 30 * timedelta(seconds=1)),)
    # Equal prices: time that continues the base window beats an earlier separate one (slot 3 over slots 0-1).
    tied = cap_request(base, [.05, .05, .04, .05, .05, .05], need=1.5, periods=8)
    _, plain_t, result_t = planned(tied, 10)
    assert plain_t.periods == ((tied.now + 30 * MIN, tied.now + 45 * MIN),)
    assert result_t.reserve_periods == ((tied.now + 45 * MIN, tied.now + 46 * MIN + 30 * timedelta(seconds=1)),)  # 10 % of 15 min
    assert len(result_t.shown_periods) == 1


def test_placement_is_deterministic(base):
    request = cap_request(base, [.05, .04, .05, .03, .05, .05, .04, .05], need=3)
    first = planned(request, 17)[2]
    second = planned(request, 17)[2]
    assert first == second and first.reserve_pieces


def test_reserve_never_makes_a_fourth_window_and_keeps_the_part_that_fits(base):
    # Three separate cheap quarters are the base: a distant cheap quarter would be a fourth window.
    prices = [.05, .20, .05, .20, .05, .20, .04, .20]
    request = replace(cap_request(base, prices, need=4.5, periods=8), max_blocks=3)
    _, plain, result = planned(request, 20)
    assert len(plain.shown_periods) == 3
    assert result.reserve_pieces == () and result.reserve_limit == "window_limit"
    assert len(result.shown_periods) == 3
    # Without the executor's limit the same time is a fourth window.
    free = replace(request, max_blocks=None, time_reserve_percent=20)
    unrestricted = with_time_reserve(free, calculate_plan(free))
    assert len(unrestricted.shown_periods) == 4 and unrestricted.reserve_limit is None
    # Time that continues a window is not a new window: kept even at the limit, and the rest is reported.
    prices = [.05, .05, .20, .05, .20, .05, .20, .20]
    request = replace(cap_request(base, prices, need=1.5 * 3, periods=8), max_blocks=3)
    _, plain2, result2 = planned(request, 20)
    assert len(plain2.shown_periods) <= 3 and len(result2.shown_periods) <= 3
    assert morek_schedule.profile_for(tuple(result2.shown_periods), 16, request.now - MIN, allow_active=True)


def test_current_partial_interval_and_generated_profile_equal_displayed_windows(base):
    request = mid(cap_request(base, [.05, .20, .04, .20, .05, .20], need=2.3), 7)
    request, plain, result = planned(request, 20)
    assert result.reserve_minutes > 0 and result.shown_periods != plain.shown_periods
    now = request.now + timedelta(seconds=1)
    profile = morek_schedule.profile_for(tuple(result.shown_periods), 16, now, allow_active=True)
    sent = windows_of(profile)
    assert len(sent) == len(result.shown_periods)
    for (s_start, s_end), (p_start, p_end) in zip(sent, result.shown_periods):
        # Whole OCPP seconds, never before a shown start nor after a shown end.
        assert abs((max(s_start, request.now) - max(p_start, request.now)).total_seconds()) <= 2
        assert 0 <= (p_end - s_end).total_seconds() < 1
    # Every reserve minute lies inside a shown (sent) window, and nothing starts before now.
    for r_start, r_end in result.reserve_periods:
        assert any(w_start <= r_start and r_end <= w_end for w_start, w_end in result.shown_periods)
        assert r_start >= request.now


def test_uncapped_whole_slot_plan_with_current_interval_gets_reserve_after_ending_at_need(base):
    request = replace(cap_request(base, [.05] * 8, need=2.3), soft_price_cap=None, cap_price_basis=None,
                      minimum_energy_kwh=None, max_periods=2, max_blocks=3, include_current_interval=True,
                      now=cap_request(base, [.05] * 8, need=2.3).now + 7 * MIN, time_reserve_percent=10)
    plain = ending_at_need(calculate_plan(request))
    result = with_time_reserve(request, plain)
    assert plain.ends_at_need and plain.need_met_at is not None
    # 2.3 kWh at 6 kW = 23 min of charging; 10 % = 2.3 min (138 s), continuing the trimmed last window.
    assert length(plain.shown_periods) == pytest.approx(length(plain.shown_periods))
    assert result.reserve_minutes == pytest.approx(2.3)
    assert result.baseline_shown_periods == plain.shown_periods
    assert result.shown_periods[-1][1] == plain.shown_periods[-1][1] + timedelta(seconds=138)
    assert result.delivered_kwh == pytest.approx(2.3) == pytest.approx(plain.delivered_kwh)


def test_dst_night_reserve_is_elapsed_time_before_the_absolute_deadline():
    # 2026-03-29: 02:00+01:00 jumps to 03:00+02:00; leaving at 07:00 the car has 8 elapsed hours from 22:00.
    docs = [day("2026-03-28", 96, "2026-03-28T00:00:00+01:00"), day("2026-03-29", 92, "2026-03-29T00:00:00+01:00")]
    plan_request = replace(dst_request("2026-03-28T22:00:00+01:00", "04:00", 16, docs), time_reserve_percent=10,
                           max_periods=3)
    plain = ending_at_need(calculate_plan(plan_request))
    result = with_time_reserve(plan_request, plain)
    assert result.reserve_percent == 10 and result.reserve_pieces
    base_time = length(plain.shown_periods)
    expected = timedelta(seconds=-(-base_time.total_seconds() * 0.1 // 60) * 60)
    assert length(result.reserve_periods) == expected
    deadline = datetime(2026, 3, 29, 4, 0, tzinfo=timezone(timedelta(hours=2)))
    assert all(end <= deadline for _, end in result.shown_periods)
    assert all(start >= plan_request.now for start, _ in result.shown_periods)


def test_unknown_or_short_plans_are_left_alone(base):
    request = cap_request(base, [.05] * 4, need=1.5)
    asking = replace(request, time_reserve_percent=10)
    # No prices (unpriced guarantee), no plan, and a best-effort plan short of its deadline.
    assert with_time_reserve(asking, plan_unpriced(replace(request, soft_price_cap=None, cap_price_basis=None))) \
        .reserve_pieces == ()
    refused = calculate_plan(replace(asking, requested_kwh=1.5, documents=asking.documents, window_end=asking.now))
    assert with_time_reserve(asking, refused) is refused
    short = calculate_plan(replace(cap_request(base, [.05] * 2, need=9.0), time_reserve_percent=10))
    assert with_time_reserve(replace(asking, requested_kwh=9.0), short) is short or short.reserve_pieces == ()


# ---- Stage 14 invariants -----------------------------------------------------------------------------------

def _release_snapshot(result, deadline):
    return SimpleNamespace(in_process=True, proposal=result, settings_revision=4, price_state="ready",
                           departure_at=deadline, price_revision=None)


def _decide(result, request, *, price_event=True, cfg=None):
    active = morek_schedule.profile_for(((request.now - MIN, request.now + 2 * H),), 16, request.now - MIN,
                                        allow_active=True)
    cfg = cfg or SimpleNamespace(revision=4, amps=16, soft_price_cap=None, minimum_ready_by_soc=None)
    return morek_schedule.window_release(
        _release_snapshot(result, request.window_end), cfg, request.now, active, cap_lowered=False,
        price_event=price_event, evidence="charging")


@pytest.mark.parametrize("prices,hours", [
    ([30.0] * 8 + [5.0] * 24, 6),     # a clear saving later
    ([30.0] * 8 + [29.0] * 24, 6),    # a tiny saving
    ([30.0] * 8 + [5.0] * 4, 2.5),    # little room after the expensive part
    ([30.0] * 4 + [5.0] * 28, 7),     # long need, short gap
])
def test_window_release_is_identical_with_and_without_reserve(base, prices, hours):
    need = hours * KW
    prices = [p / 100 for p in prices]  # EUR major units (the effective price is minor units)
    request = replace(cap_request(base, prices, need=need), soft_price_cap=None, cap_price_basis=None,
                      minimum_energy_kwh=None, max_periods=3, max_blocks=3, include_current_interval=True)
    none_request, none_plain, none_result = planned(request, 0)
    ten_request, ten_plain, ten_result = planned(request, 10)
    plain, reserved = ending_at_need(none_plain), with_time_reserve(ten_request, ending_at_need(ten_plain))
    assert reserved.reserve_minutes > 0 and reserved.shown_periods != plain.shown_periods
    for event in (True, False):
        assert _decide(reserved, ten_request, price_event=event) == _decide(plain, none_request, price_event=event)


def test_release_quantities_use_the_reserve_free_periods(base):
    request = replace(cap_request(base, [.30] * 8 + [.05] * 24, need=6 * KW), soft_price_cap=None,
                      cap_price_basis=None, minimum_energy_kwh=None, max_periods=3, max_blocks=3,
                      include_current_interval=True, time_reserve_percent=50)
    result = with_time_reserve(request, ending_at_need(calculate_plan(request)))
    assert result.reserve_minutes > 0
    # A proposal whose baseline is later than the active window but whose reserve overlaps it must still release on
    # price: the reserve minutes neither create the gap nor shrink the slack.
    plain = replace(result, reserve_pieces=(), reserve_percent=0)
    assert _decide(result, request) == _decide(plain, request)


def test_reserve_placement_is_stable_across_current_time_and_slot_boundaries(base):
    # Same need, only the clock moves (a minute, and across a quarter-hour boundary): the reserve never starts at
    # `now` and so never creeps; the strict wire comparison (no tolerance at all) sees the same future schedule.
    prices = [.05, .20, .20, .20, .04, .04, .20, .20]
    first = None
    for minutes in (2, 3, 16):
        request = replace(mid(cap_request(base, prices, need=3.0, periods=8), minutes), max_blocks=3,
                          time_reserve_percent=10, soft_price_cap=None, cap_price_basis=None,
                          minimum_energy_kwh=None, include_current_interval=True)
        result = with_time_reserve(request, ending_at_need(calculate_plan(request)))
        assert result.reserve_minutes > 0
        assert all(piece.start > request.now for piece in result.reserve_pieces)
        profile = morek_schedule.profile_for(tuple(result.shown_periods), 16, request.now, allow_active=True)
        if first is None:
            first, first_periods = profile, result.shown_periods
        else:
            assert morek_schedule.same_effective_schedule(first, profile, None), minutes
            assert result.shown_periods == first_periods


def test_reserve_percent_alone_changes_the_sent_schedule_and_is_stable_otherwise(base):
    request = cap_request(base, [.05] * 8, need=2.0)
    a = planned(request, 10)[2]
    b = planned(request, 20)[2]
    assert a.reserve_minutes < b.reserve_minutes and a.periods == b.periods


# ---- actual worker/dispatch: SOC-only drift is judged on the reserve-free need ------------------------------

from custom_components.spotnav.execution import morek_worker  # noqa: E402

from .test_morek_worker import drain, setup  # noqa: E402

LATE = [.20] * 4 + [.05] * 8  # cheap from +60 min: the baseline is one later window, the reserve continues it
NEED = 3.5  # 35 minutes: three quarter-hour slots, so a drift of a few minutes moves only the switch-off instant


def real_plan(base, percent, need):
    request = replace(cap_request(base, LATE, need=need), soft_price_cap=None, cap_price_basis=None,
                      minimum_energy_kwh=None, max_periods=2, max_blocks=3, include_current_interval=True,
                      time_reserve_percent=percent)
    return request, with_time_reserve(request, ending_at_need(calculate_plan(request)))


def sends(w):
    return w.point.call.await_count


async def started(monkeypatch, base, percent, need=NEED):
    request, result = real_plan(base, percent, need)
    w = setup(monkeypatch)
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0)
    monkeypatch.setattr(morek_worker, "datetime", SimpleNamespace(now=lambda _tz=None: request.now))
    w.planner.current.proposal = result
    w.request = request
    w.worker.start()
    await drain(w.worker)
    assert sends(w) == 1 and (result.reserve_minutes > 0) == (percent > 0)
    return w


def drift(w, base, percent, seconds, cause="soc"):
    """Publish the plan the need drifted to by `seconds` of charging at plan power (6 kW)."""
    _, plain = real_plan(base, 0, NEED)
    request, result = real_plan(base, percent, NEED + seconds / 3600 * KW)
    if abs(seconds) < 300:  # the slots stay the same: only the need's own switch-off instant moves, by this
        assert result.baseline_shown_periods[-1][0] == plain.shown_periods[-1][0]
        moved = result.baseline_shown_periods[-1][1] - plain.shown_periods[-1][1]
        assert moved.total_seconds() == pytest.approx(seconds, abs=1e-3)
    w.planner.current.proposal = result
    w.planner.publish(cause)


@pytest.mark.parametrize("percent", [0, 10, 50])
@pytest.mark.parametrize("seconds", [270, 299, -299])
async def test_sub_five_minute_soc_drift_is_never_a_resend_whatever_the_reserve(monkeypatch, base, percent, seconds):
    w = await started(monkeypatch, base, percent)
    drift(w, base, percent, seconds)
    await drain(w.worker)
    assert sends(w) == 1 and w.worker.reason == "unchanged"
    # With a reserve, the reserve-free twin is what judged it, stored with the accepted profile.
    assert ("baseline" in w.ledger.value["acknowledged"]) == (percent > 0)
    w.worker.close()


@pytest.mark.parametrize("percent", [0, 10, 50])
@pytest.mark.parametrize("seconds", [301, 330, 600, -301])
async def test_five_minute_or_larger_soc_drift_still_sends_whatever_the_reserve(monkeypatch, base, percent, seconds):
    w = await started(monkeypatch, base, percent)
    drift(w, base, percent, seconds)
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.parametrize("percent", [10, 50])
async def test_exactly_five_minutes_is_strict_as_without_a_reserve(monkeypatch, base, percent):
    # The boundary itself (a drift of 5 min or more is strict) is what the reserve-free plan does.
    outcomes = []
    for pct in (0, percent):
        w = await started(monkeypatch, base, pct)
        _, result = real_plan(base, pct, NEED + 0.5)  # 0.5 kWh at 6 kW = 5 minutes
        w.planner.current.proposal = result
        w.planner.publish("soc")
        await drain(w.worker)
        outcomes.append(sends(w))
        w.worker.close()
    assert outcomes == [2, 2]


@pytest.mark.parametrize("percent", [10, 50])
async def test_settings_price_and_plug_in_stay_strict_with_a_reserve(monkeypatch, base, percent):
    w = await started(monkeypatch, base, percent)
    w.planner.current.price_revision = 1  # first sighting of a price revision: equal schedule
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 1
    drift(w, base, percent, 270)  # tolerated as a pure SOC reading ...
    await drain(w.worker)
    assert sends(w) == 1
    w.planner.current.price_revision = 2  # ... but not together with a price change
    drift(w, base, percent, 270)
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.last_trigger == "price"
    drift(w, base, percent, 280)  # a settings edit is never tolerated either
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 3
    w.worker.close()


async def test_a_reserve_edit_is_a_settings_send_and_the_twin_follows_the_accepted_profile(monkeypatch, base):
    w = await started(monkeypatch, base, 10)
    old = w.ledger.value["acknowledged"]["baseline"]
    _, result = real_plan(base, 50, NEED)
    w.planner.current.proposal = result
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2 and w.ledger.value["acknowledged"]["baseline"] == old  # same need, same reserve-free windows


async def test_a_reserve_that_disappears_from_the_plan_resends(monkeypatch, base):
    w = await started(monkeypatch, base, 50)
    _, result = real_plan(base, 0, NEED)  # the same baseline, but no reserve in the plan any more
    w.planner.current.proposal = result
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2 and "baseline" not in w.ledger.value["acknowledged"]


# ---- Stage 14 window release: the accepted window's reserve is not part of the need ----------------------

def _release(request, result, *, wire_extra, baseline_end, twin, price_event=True):
    now = request.now
    wire = morek_schedule.profile_for(((now - MIN, now + baseline_end + wire_extra),), 16, now - MIN, allow_active=True)
    base = morek_schedule.profile_for(((now - MIN, now + baseline_end),), 16, now - MIN, allow_active=True)
    snapshot = SimpleNamespace(in_process=True, proposal=result, settings_revision=4, price_state="ready",
                               departure_at=now + 14 * H, price_revision=None)
    cfg = SimpleNamespace(revision=4, amps=16, soft_price_cap=None, minimum_ready_by_soc=None)
    return morek_schedule.window_release(snapshot, cfg, now, wire, cap_lowered=False, price_event=price_event,
                                         evidence="charging", active_baseline=base if twin else None)


@pytest.mark.parametrize("percent,reserve", [(10, 4), (50, 20)])
@pytest.mark.parametrize("baseline_minutes", [16, 18, 19, 20, 22])  # the 0.50 EUR price threshold sits at 20 min
def test_window_release_on_an_accepted_window_with_reserve_equals_the_reserve_free_decision(
        base, percent, reserve, baseline_minutes):
    prices = [.30] * 8 + [.05] * 24
    request = replace(cap_request(base, prices, need=4.0), soft_price_cap=None, cap_price_basis=None,
                      minimum_energy_kwh=None, max_periods=3, max_blocks=3, include_current_interval=True,
                      time_reserve_percent=percent)
    result = with_time_reserve(request, ending_at_need(calculate_plan(request)))
    assert result.reserve_minutes > 0
    free_request = replace(request, time_reserve_percent=0)
    free = ending_at_need(calculate_plan(free_request))
    for price_event in (True, False):
        expected = _release(free_request, free, wire_extra=timedelta(0), baseline_end=baseline_minutes * MIN,
                            twin=False, price_event=price_event)
        got = _release(request, result, wire_extra=reserve * MIN, baseline_end=baseline_minutes * MIN, twin=True,
                       price_event=price_event)
        assert got == expected, (price_event, expected)
    # A 16-19 minute window saves less than 0.50 EUR: no release. Without the twin, the reserve inside the accepted
    # window would inflate the kept cost and release it, which is what the twin prevents.
    if baseline_minutes < 20 and percent == 10:
        assert _release(request, result, wire_extra=reserve * MIN, baseline_end=baseline_minutes * MIN,
                        twin=True) == (False, "release_saving_too_small")
        assert _release(request, result, wire_extra=reserve * MIN, baseline_end=baseline_minutes * MIN,
                        twin=False)[0] is True


def test_window_release_cap_rule_uses_the_reserve_free_window_too(base):
    request = replace(cap_request(base, [.30] * 8 + [.05] * 24, need=4.0), time_reserve_percent=10, max_blocks=3,
                      include_current_interval=True)
    result = with_time_reserve(request, ending_at_need(calculate_plan(request)))
    free = ending_at_need(calculate_plan(replace(request, time_reserve_percent=0)))
    now = request.now

    def snapshot(proposal):
        return SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready",
                               departure_at=now + 14 * H, price_revision=None)

    cfg = SimpleNamespace(revision=4, amps=16, soft_price_cap=0.01, minimum_ready_by_soc=None)
    for end, extra in ((18, 4), (20, 6)):
        wire = morek_schedule.profile_for(((now - MIN, now + (end + extra) * MIN),), 16, now - MIN, allow_active=True)
        twin = morek_schedule.profile_for(((now - MIN, now + end * MIN),), 16, now - MIN, allow_active=True)
        assert (morek_schedule.window_release(snapshot(result), cfg, now, wire, cap_lowered=True, price_event=False,
                                              evidence="charging", active_baseline=twin)
                == morek_schedule.window_release(snapshot(free), cfg, now, twin, cap_lowered=True,
                                                 price_event=False, evidence="charging"))


# ---- production wiring: controller, preview key, dashboard ----------------------------------------------------

@pytest.mark.asyncio
async def test_controller_applies_the_setting_to_morek_plans_only_and_zero_is_off(monkeypatch):
    world = await _world(monkeypatch)
    now, owned = await _plan(world, _prices(), owned=True, time_reserve_percent=10)
    proposal = owned.proposal
    assert proposal.has_plan and proposal.reserve_percent == 10 and proposal.reserve_pieces
    assert length(proposal.shown_periods) == length(proposal.baseline_shown_periods) + length(proposal.reserve_periods)
    # What would be sent is exactly what is shown.
    profile = morek_schedule.profile_for(proposal.shown_periods, 16, now + timedelta(seconds=1), allow_active=True)
    assert len(windows_of(profile)) == len(proposal.shown_periods) <= 3
    # The baseline equals the 0 % plan; the proposal key differs so a change is published.
    _, off = await _plan(world, _prices(), owned=True, time_reserve_percent=0)
    assert off.proposal.reserve_pieces == () and off.proposal.reserve_percent == 0
    for name in ("periods", "slots", "delivered_kwh", "estimated_cost", "baseline_shown_periods"):
        assert getattr(proposal, name) == getattr(off.proposal, name)
    assert owned.meaningful_key() != off.meaningful_key()
    # Another charger's plan never carries a reserve.
    _, legacy = await _plan(world, _prices(), owned=False, time_reserve_percent=10)
    assert legacy.proposal.reserve_pieces == () and legacy.proposal.reserve_percent == 0


@pytest.mark.asyncio
async def test_controller_uncapped_plan_and_reserve_edit_replans(monkeypatch):
    world = await _world(monkeypatch)
    changes = dict(soft_price_cap=None, cap_price_basis=None, minimum_ready_by_soc=None, max_periods=2,
                   departure_enabled=True, departure=time(22))
    now, with_reserve = await _plan(world, _prices(), owned=True, time_reserve_percent=10, **changes)
    proposal = with_reserve.proposal
    assert proposal.ends_at_need and proposal.reserve_minutes > 0 and len(proposal.shown_periods) <= 2
    assert proposal.delivered_kwh == pytest.approx(proposal.requested_kwh)
    # Editing only the reserve through the settings store moves the next plan, nothing else.
    _, edited = await _plan(world, _prices(), owned=True, time_reserve_percent=30)
    assert edited.proposal.reserve_minutes > proposal.reserve_minutes
    assert edited.proposal.baseline_shown_periods == proposal.baseline_shown_periods
    assert world.store.settings("test").time_reserve_percent == 30


@pytest.mark.asyncio
async def test_dashboard_exposes_baseline_and_allowance_separately(monkeypatch):
    world = await _world(monkeypatch)
    _, snapshot = await _plan(world, _prices(), owned=True, time_reserve_percent=10)
    proposal = snapshot.proposal
    capture = SimpleNamespace(snapshot=snapshot, settings=world.store.settings("test"), generated_at=proposal.now,
                              plan=None, charging_phases=None)
    section = dashboard._proposal_section(capture)
    reserve = section["reserve"]
    assert reserve["percent"] == 10 and reserve["minutes"] == pytest.approx(proposal.reserve_minutes)
    assert reserve["allowance"]["kind"] == "upper_allowance"
    assert reserve["allowance"]["energy_kwh"] == pytest.approx(proposal.reserve_energy_kwh)
    assert reserve["allowance"]["cost"]["value"] == pytest.approx(proposal.reserve_cost)
    assert reserve["periods"] == [{"start": dashboard.aware_iso(s), "end": dashboard.aware_iso(e)}
                                  for s, e in proposal.reserve_periods]
    # The baseline fields never include the reserve, and the window details add up to them without it.
    assert section["planned_kwh"] == pytest.approx(proposal.delivered_kwh)
    assert section["cost"]["value"] == pytest.approx(proposal.estimated_cost)
    details = section["window_details"]
    assert details is not None and len(details) == len(section["periods"])
    assert sum(row["energy_kwh"] for row in details) == pytest.approx(proposal.delivered_kwh)
    assert sum(row["reserve_kwh"] for row in details) == pytest.approx(proposal.reserve_energy_kwh)
    assert sum(row["reserve_cost"] for row in details) == pytest.approx(proposal.reserve_cost)
    # 0 % adds nothing to the payload.
    _, off = await _plan(world, _prices(), owned=True, time_reserve_percent=0)
    capture = SimpleNamespace(snapshot=off, settings=world.store.settings("test"), generated_at=off.proposal.now, plan=None,
                              charging_phases=None)
    plain = dashboard._proposal_section(capture)
    assert "reserve" not in plain and all("reserve_kwh" not in row for row in plain["window_details"])
