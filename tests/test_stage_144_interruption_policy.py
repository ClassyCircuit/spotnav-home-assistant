"""Stage 14.4: when a replanned schedule may interrupt an acknowledged active Morek window.

Pure decision tests cover the exact thresholds; worker tests use the real worker, profile builder and
send path (HA, OCPP and ownership are the usual mocked boundaries) and assert actual send counts.
A real planner calculation proves the evidence the decision needs is produced. Mocked only: not proof
of savings, installed behavior or physical charging.
"""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.planning.planner import CurrentInterval, calculate_plan
from .test_morek_worker import IDENTITY, NOW, drain, setup
from .test_planner_current_interval import mid
from .test_planner_price_policy_guard import cap_request
from .test_planner_current_interval import base  # noqa: F401  (fixture)

H = timedelta(hours=1)
M = timedelta(minutes=1)
POWER = 10.0  # kW: one hour is 10 kWh


def active_profile():
    """Accepted routine schedule: charging NOW-1min .. NOW+2h."""
    return morek_schedule.profile_for(((NOW - M, NOW + 2 * H),), 16, NOW - M, allow_active=True)


def rows(price_by_hour):
    """Horizon rows of 15 minutes from NOW+15min for 12 h; `price_by_hour(i)` is minor units per kWh."""
    out = []
    for i in range(1, 48):
        start = NOW + i * 15 * M
        out.append(SimpleNamespace(utc_start=start, utc_end=start + 15 * M,
                                   effective_minor_per_kwh=price_by_hour(int(i // 4))))
    return tuple(out)


def snapshot(periods, *, price=lambda h: 30.0 if h < 2 else 5.0, now_price=30.0, within_cap=False,
             minimum_kwh=10.0, shortfall=0.0, currency="EUR", deadline=NOW + 10 * H):
    proposal = SimpleNamespace(
        has_plan=True, unpriced=False, shown_periods=tuple(periods), power_kw=POWER, currency=currency,
        horizon=rows(price), current_interval=CurrentInterval(NOW, NOW + 15 * M, now_price, within_cap),
        minimum_energy_kwh=minimum_kwh, minimum_shortfall_kwh=shortfall)
    return SimpleNamespace(in_process=True, proposal=proposal, settings_revision=4, price_state="ready",
                           departure_at=deadline, price_revision=None)


def settings(cap=0.10, minimum=40.0):
    return SimpleNamespace(revision=4, amps=16, soft_price_cap=cap, minimum_ready_by_soc=minimum)


def decide(snap, *, cap_lowered=False, price=True, evidence="charging", cfg=None):
    return morek_schedule.window_release(snap, cfg or settings(), NOW, active_profile(),
                                         cap_lowered=cap_lowered, price_event=price, evidence=evidence)


LATER = ((NOW + 6 * H, NOW + 8 * H),)  # 02:00-04:00 at 5 c


# ---- price improvement: thresholds ----------------------------------------------------------------

def test_clear_price_improvement_releases_the_window():
    assert decide(snapshot(LATER)) == (True, "price_improvement")


def test_routine_event_never_releases_even_with_a_large_saving():
    assert decide(snapshot(LATER), price=False) == (False, "active_window_preserved")


def test_new_plan_that_already_carries_the_window_is_not_an_interruption():
    assert decide(snapshot(((NOW, NOW + 2 * H),))) == (False, "active_window_preserved")


def test_saving_below_fifty_cents_is_kept():
    # 20 kWh * 2.4 c = EUR 0.48 saving (< 0.50) even though it is 100 % of the baseline.
    snap = snapshot(LATER, price=lambda h: 2.4 if h < 2 else 0.0, now_price=2.4)
    assert decide(snap) == (False, "release_saving_too_small")


def test_saving_exactly_fifty_cents_and_ten_percent_is_allowed():
    snap = snapshot(LATER, price=lambda h: 2.5 if h < 2 else 0.0, now_price=2.5)
    assert decide(snap) == (True, "price_improvement")


def test_saving_above_fifty_cents_but_below_ten_percent_is_kept():
    # baseline EUR 20 (20 kWh at 100 c), alternative EUR 18.5: saving 1.50 < 10 %.
    snap = snapshot(LATER, price=lambda h: 100.0 if h < 2 else 92.5 if h >= 6 else 100.0, now_price=100.0)
    assert decide(snap) == (False, "release_saving_too_small")


def test_saving_exactly_ten_percent_is_allowed():
    snap = snapshot(LATER, price=lambda h: 100.0 if h < 2 else 90.0, now_price=100.0)
    assert decide(snap) == (True, "price_improvement")


@pytest.mark.parametrize("baseline", [0.0, -5.0])
def test_zero_or_negative_baseline_cannot_pass_the_percentage_test(baseline):
    snap = snapshot(LATER, price=lambda h: baseline if h < 2 else -50.0, now_price=baseline)
    assert decide(snap) == (False, "release_baseline_not_positive")


def test_gap_below_thirty_minutes_is_kept_and_exactly_thirty_is_allowed():
    # The new plan cuts the active window after 45 min (cheap), skips the expensive half hour, and resumes.
    def cut(gap):
        windows = ((NOW, NOW + 45 * M), (NOW + 45 * M + gap, NOW + 45 * M + gap + 75 * M))
        snap = snapshot(windows, now_price=5.0)
        snap.proposal.horizon = tuple(
            replace_price(row, 30.0 if NOW + 45 * M <= row.utc_start < NOW + 75 * M else 5.0)
            for row in snap.proposal.horizon)
        return snap
    assert decide(cut(30 * M)) == (True, "price_improvement")
    assert decide(cut(29 * M)) == (False, "release_gap_too_short")


def replace_price(row, price):
    return SimpleNamespace(utc_start=row.utc_start, utc_end=row.utc_end, effective_minor_per_kwh=price)


def test_slack_before_ready_by_must_be_fifteen_minutes_beyond_the_minimum():
    # Minimum 10 kWh = 1 h. Resume at +6 h: slack = deadline - 6 h - 1 h.
    ok = snapshot(LATER, deadline=NOW + 7 * H + 15 * M)
    assert decide(ok) == (True, "price_improvement")
    tight = snapshot(LATER, deadline=NOW + 7 * H + 14 * M)
    assert decide(tight) == (False, "release_slack_too_small")


FRAGMENTED = ((NOW + 6 * H, NOW + 6 * H + 20 * M), (NOW + 9 * H, NOW + 10 * H))  # 3.33 + 10 kWh at 10 kW


def test_fragmented_plan_that_cannot_deliver_the_minimum_by_ready_by_minus_slack_is_kept():
    # Minimum 10 kWh. By 09:45 (ready-by 10:00 - 15 min) the plan delivers 3.33 + 7.5 = 10.83: enough.
    assert decide(snapshot(FRAGMENTED, deadline=NOW + 10 * H)) == (True, "price_improvement")
    # Ready-by 09:30: the cutoff 09:15 delivers only 3.33 + 2.5 = 5.83 < 10, however early the first resume is.
    assert decide(snapshot(FRAGMENTED, deadline=NOW + 9 * H + 30 * M)) == (False, "release_slack_too_small")


def test_minimum_delivered_exactly_fifteen_minutes_before_ready_by_is_allowed():
    windows = ((NOW + 6 * H, NOW + 7 * H),)  # exactly the 10 kWh minimum, ending 07:00
    assert decide(snapshot(windows, deadline=NOW + 7 * H + 15 * M)) == (True, "price_improvement")
    assert decide(snapshot(windows, deadline=NOW + 7 * H + 14 * M)) == (False, "release_slack_too_small")


def test_no_resume_needs_a_real_gap_to_ready_by_and_the_minimum_met():
    cut = ((NOW, NOW + 45 * M),)  # stop after 45 min and never resume

    def snap(deadline, minimum):
        s = snapshot(cut, now_price=5.0, minimum_kwh=minimum)
        s.proposal.horizon = tuple(replace_price(r, 30.0) for r in s.proposal.horizon)
        s.departure_at = deadline
        return s
    # 7.5 kWh delivered in the kept 45 minutes; minimum 5 kWh already met.
    # Exactly 30 min from the stop to ready-by passes the gap; with no later window nothing is cheaper (same energy).
    assert decide(snap(NOW + 75 * M, 5.0)) == (False, "release_saving_too_small")
    assert decide(snap(NOW + 74 * M, 5.0)) == (False, "release_gap_too_short")
    # The minimum cannot be delivered before ready-by - 15 min with no further window: kept.
    assert decide(snap(NOW + 75 * M, 10.0)) == (False, "release_slack_too_small")


def test_unknown_shortfall_or_stale_prices_keep_the_window_for_price_events():
    assert decide(snapshot(LATER, shortfall=None)) == (False, "release_minimum_uncertain")
    assert decide(snapshot(LATER, shortfall=0.5)) == (False, "release_minimum_uncertain")
    stale = snapshot(LATER)
    stale.price_state = "stale"
    assert decide(stale) == (False, "release_price_unknown")


def test_no_configured_minimum_requires_the_whole_plan_before_the_slack():
    cfg = settings(minimum=None)
    ok = snapshot(LATER, minimum_kwh=None, shortfall=None, deadline=NOW + 8 * H + 15 * M)
    assert decide(ok, cfg=cfg) == (True, "price_improvement")
    tight = snapshot(LATER, minimum_kwh=None, shortfall=None, deadline=NOW + 8 * H + 14 * M)
    assert decide(tight, cfg=cfg) == (False, "release_slack_too_small")


@pytest.mark.parametrize("change,reason", [
    ({"currency": "SEK"}, "release_currency_unknown"),
    ({"deadline": None}, "release_ready_by_unknown"),
    ({"minimum_kwh": None}, "release_minimum_uncertain"),
])
def test_uncertain_cost_state_or_feasibility_preserves_the_window(change, reason):
    assert decide(snapshot(LATER, **change)) == (False, reason)


def test_missing_price_for_the_window_preserves_it():
    snap = snapshot(LATER)
    snap.proposal.horizon = snap.proposal.horizon[:8]  # prices stop at NOW+3h
    assert decide(snap) == (False, "release_price_unknown")
    snap = snapshot(LATER)
    snap.proposal.current_interval = None  # the interval holding now is unpublished
    assert decide(snap) == (False, "release_price_unknown")


@pytest.mark.parametrize("evidence", ["unknown", "other"])
def test_unknown_state_never_releases(evidence):
    assert decide(snapshot(LATER), evidence=evidence) == (False, "active_window_state_unknown")


def test_waiting_state_may_release():
    assert decide(snapshot(LATER), evidence="waiting") == (True, "price_improvement")


def test_malformed_snapshot_preserves():
    assert decide(SimpleNamespace(proposal=None, in_process=True)) == (False, "active_window_preserved")
    assert decide(SimpleNamespace()) == (False, "release_decision_unavailable")


# ---- cap edit -------------------------------------------------------------------------------------

def test_lowered_cap_below_current_price_ends_the_window_when_the_minimum_is_met_later():
    assert decide(snapshot(LATER), cap_lowered=True, price=False) == (True, "cap_lowered")


def test_cap_still_covering_now_or_raised_does_not_stop():
    assert decide(snapshot(LATER, within_cap=True), cap_lowered=True, price=False) == (False, "cap_still_covers_now")


def test_cap_edit_needs_a_cap_and_a_known_price_of_now():
    assert decide(snapshot(LATER), cap_lowered=True, price=False, cfg=settings(cap=None)) == \
        (False, "active_window_preserved")
    snap = snapshot(LATER)
    snap.proposal.current_interval = None
    assert decide(snap, cap_lowered=True, price=False) == (False, "release_price_unknown")
    snap = snapshot(LATER)
    snap.proposal.current_interval = CurrentInterval(NOW, NOW + 15 * M, 30.0, None)
    assert decide(snap, cap_lowered=True, price=False) == (False, "release_price_unknown")


@pytest.mark.parametrize("shortfall", [0.5, None])
def test_cap_edit_never_stops_when_the_minimum_cannot_be_assured(shortfall):
    assert decide(snapshot(LATER, shortfall=shortfall), cap_lowered=True, price=False) == \
        (False, "release_minimum_uncertain")
    assert decide(snapshot(LATER, minimum_kwh=None), cap_lowered=True, price=False) == \
        (False, "release_minimum_uncertain")


def test_cap_edit_without_a_minimum_setting_needs_no_minimum_evidence():
    snap = snapshot(LATER, minimum_kwh=None, shortfall=None)
    assert decide(snap, cap_lowered=True, price=False, cfg=settings(minimum=None)) == (True, "cap_lowered")


def test_minimum_exception_keeps_charging_only_for_the_needed_energy():
    # The new plan still needs 1 h now for the minimum: it replaces the window (shorter), nothing more.
    needed = ((NOW, NOW + H),)
    assert decide(snapshot(needed), cap_lowered=True, price=False) == (True, "cap_lowered")


# ---- worker: real send path -----------------------------------------------------------------------

def sent(w):
    return [call.args[0].payload["cs_charging_profiles"] for call in w.point.call.await_args_list]


def limits(profile):
    return [(p["startPeriod"], p["limit"]) for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]


async def started(monkeypatch, state="charging", cap=0.10, minimum=40.0):
    w = setup(monkeypatch, active=True)
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: state_box["state"])
    state_box["state"] = state
    w.settings.soft_price_cap, w.settings.minimum_ready_by_soc = cap, minimum
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    return w


state_box = {"state": "charging"}


def replan(w, periods, **kw):
    snap = snapshot(periods, **kw)
    w.planner.current.proposal = snap.proposal
    w.planner.current.departure_at = snap.departure_at


@pytest.mark.asyncio
async def test_price_event_with_a_clear_saving_interrupts_and_sends_once(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    assert limits(sent(w)[1]) == [(0, 0), (21600, 16), (28800, 0)]
    assert w.worker.continuity["preserved"] is False and w.worker.continuity["reason"] == "price_improvement"
    # Repeating the event cannot restart or re-interrupt: the accepted schedule already says this.
    w.planner.current.price_revision = "p3"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_price_reason_survives_an_unavailable_charger_and_reconnect(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    available = {"v": False}
    w.worker._available = lambda: available["v"]
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "charger_unavailable"
    assert w.worker._price_pending is True
    available["v"] = True
    w.worker.trigger()  # reconnect: a direct trigger, not a price publication
    await drain(w.worker)
    assert w.point.call.await_count == 2 and limits(sent(w)[1]) == [(0, 0), (21600, 16), (28800, 0)]
    assert w.worker._price_pending is False
    w.worker.close()


@pytest.mark.asyncio
async def test_price_reason_survives_a_rejected_release_without_a_blind_resend(monkeypatch):
    w = await started(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker._price_pending is True
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker.reason == "upload_rejected"
    w.worker.close()


@pytest.mark.asyncio
async def test_price_reason_survives_stale_work_and_uncertain_operations_send_nothing(monkeypatch):
    w = await started(monkeypatch)
    w.ledger.value["uncertain"] = True
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker._price_pending is True
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1  # still uncertain: nothing is retried
    w.ledger.value["uncertain"] = False
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and limits(sent(w)[1])[0] == (0, 0)
    w.worker.close()


@pytest.mark.asyncio
async def test_a_decided_price_event_is_not_carried_forward(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER, price=lambda h: 3.0 if h < 2 else 1.0, now_price=3.0)  # saving too small: decided
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.worker.continuity["reason"] == "release_saving_too_small" and w.worker._price_pending is False
    replan(w, LATER)  # a later, non-price run must not reuse the old event
    w.planner.publish("soc")
    await drain(w.worker)
    assert w.worker.continuity["preserved"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_routine_soc_update_with_the_same_plan_keeps_the_window(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER)
    w.planner.publish("soc")
    await drain(w.worker)
    assert limits(sent(w)[1]) == [(0, 16), (7200, 0), (21600, 16), (28800, 0)]  # window kept, later one added
    assert w.worker.continuity["preserved"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_small_price_improvement_keeps_the_window_and_adds_the_future_one(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER, price=lambda h: 3.0 if h < 2 else 1.0, now_price=3.0)  # saving EUR 0.40
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1])[0] == (0, 16)
    assert w.worker.continuity["reason"] == "release_saving_too_small"
    w.worker.close()


@pytest.mark.asyncio
async def test_unknown_state_price_event_keeps_the_window(monkeypatch):
    w = await started(monkeypatch, state="unknown")
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1])[0] == (0, 16)
    assert w.worker.continuity["reason"] == "active_window_state_unknown"
    w.worker.close()


@pytest.mark.asyncio
async def test_lowered_cap_edit_ends_the_window_immediately(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER)
    w.settings.revision, w.settings.soft_price_cap = 5, 0.05  # actually lowered from the accepted 0.10
    w.planner.current.settings_revision = 5
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1]) == [(0, 0), (21600, 16), (28800, 0)]
    assert w.worker.continuity["reason"] == "cap_lowered"
    w.worker.close()


@pytest.mark.asyncio
async def test_raised_cap_edit_never_stops_a_window(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER, within_cap=True)  # price now within the raised cap
    w.settings.revision, w.settings.soft_price_cap = 5, 0.20
    w.planner.current.settings_revision = 5
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1])[0] == (0, 16)
    assert w.worker.continuity["preserved"] is True  # a raised cap is not a lowered cap
    w.worker.close()


@pytest.mark.asyncio
async def test_unrelated_settings_edit_while_above_the_cap_never_stops_a_window(monkeypatch):
    w = await started(monkeypatch)
    replan(w, LATER)  # price of now is above the (unchanged) cap, but nothing lowered it
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1])[0] == (0, 16)
    assert w.worker.continuity["preserved"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_older_record_without_cap_evidence_is_conservative(monkeypatch):
    w = await started(monkeypatch)
    del w.ledger.value["acknowledged"]["cap"]  # an acknowledgement written before 2.5.106
    replan(w, LATER)
    w.settings.revision, w.settings.soft_price_cap = 5, 0.05
    w.planner.current.settings_revision = 5
    w.planner.publish()
    await drain(w.worker)
    assert limits(sent(w)[1])[0] == (0, 16)
    assert w.worker.continuity["preserved"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_accepted_profile_stores_only_the_cap_and_basis(monkeypatch):
    w = await started(monkeypatch)
    assert w.ledger.value["acknowledged"]["cap"] == {"value": 0.10, "basis": None}
    w.worker.close()


def test_cap_lowered_evidence_rules():
    def record(**cap):
        return {"acknowledged": {"cap": cap}} if cap else {"acknowledged": {}}
    def cfg(cap, basis=None):
        return SimpleNamespace(soft_price_cap=cap, cap_price_basis=basis)
    stored = {"value": 0.10, "basis": "nord_pool"}
    assert morek_schedule.cap_lowered(record(**stored), cfg(0.05, "nord_pool")) is True
    assert morek_schedule.cap_lowered(record(**stored), cfg(0.10, "nord_pool")) is False
    assert morek_schedule.cap_lowered(record(**stored), cfg(0.20, "nord_pool")) is False
    assert morek_schedule.cap_lowered(record(**stored), cfg(None, "nord_pool")) is False
    assert morek_schedule.cap_lowered(record(**stored), cfg(0.05, "other")) is False  # basis changed: unknown
    assert morek_schedule.cap_lowered(record(value=None, basis=None), cfg(0.05)) is True
    assert morek_schedule.cap_lowered(record(), cfg(0.05)) is False
    assert morek_schedule.cap_lowered(None, cfg(0.05)) is False
    assert morek_schedule.cap_lowered(record(value="x", basis=None), cfg(0.05)) is False


@pytest.mark.asyncio
async def test_lowered_cap_survives_a_rejected_send_and_is_not_blindly_resent(monkeypatch):
    w = await started(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    replan(w, LATER)
    w.settings.revision, w.settings.soft_price_cap = 5, 0.05
    w.planner.current.settings_revision = 5
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker.reason == "upload_rejected"
    assert w.ledger.value["acknowledged"]["cap"]["value"] == 0.10  # the accepted profile is unchanged
    w.worker.trigger()  # reconnect-like direct trigger: still lowered vs the accepted profile, no resend
    await drain(w.worker)
    assert w.point.call.await_count == 2
    w.point.call.return_value = SimpleNamespace(status="Accepted")
    w.ledger.value["attempt"]["state"] = "aborted_before_dispatch"  # an operator-cleared rejection
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 3 and limits(sent(w)[2])[0] == (0, 0)
    assert w.ledger.value["acknowledged"]["cap"]["value"] == 0.05
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_write_blocks_any_interruption(monkeypatch):
    w = await started(monkeypatch)
    w.ledger.value["uncertain"] = True
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_uncertain"
    w.worker.close()


@pytest.mark.asyncio
async def test_pause_still_wins_immediately(monkeypatch):
    w = await started(monkeypatch)
    w.ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                        "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    from custom_components.spotnav.execution.command_admission import physical_connector
    w.worker.hold_ticket = ("p", w.admission.generation(physical_connector(w.identity)))
    replan(w, LATER)
    w.worker.trigger()
    await drain(w.worker)
    assert limits(sent(w)[1]) == [(0, 0)] and w.worker.continuity is None
    w.worker.close()


# ---- real planner evidence --------------------------------------------------------------------------

def test_real_planner_result_carries_current_price_cap_status_and_minimum(base):  # noqa: F811
    request = cap_request(base, [.20, .05, .04, .20], need=2.3, cap=0.10)
    result = calculate_plan(replace(mid(request), minimum_energy_kwh=1.0))
    assert result.current_interval.within_cap is False
    assert result.current_interval.effective_minor_per_kwh == pytest.approx(20.0)
    assert result.current_interval.start == request.now
    assert result.minimum_energy_kwh == 1.0
    cheap = calculate_plan(mid(cap_request(base, [.05, .05, .04, .20], need=2.3, cap=0.10)))
    assert cheap.current_interval.within_cap is True and cheap.minimum_energy_kwh is None
    uncapped = calculate_plan(replace(mid(request), soft_price_cap=None, cap_price_basis=None))
    assert uncapped.current_interval.within_cap is None


def test_decision_accepts_a_real_planner_proposal(base):  # noqa: F811
    request = cap_request(base, [.20, .05, .04, .20], need=2.3, cap=0.10)
    result = calculate_plan(replace(mid(request, 0), minimum_energy_kwh=1.0))
    now = request.now
    profile = morek_schedule.profile_for(((now - M, now + 30 * M),), 16, now - M, allow_active=True)
    snap = SimpleNamespace(in_process=True, proposal=result, departure_at=None, price_state="ready")
    cfg = settings()
    release = morek_schedule.window_release(snap, cfg, now, profile, cap_lowered=True, price_event=False,
                                            evidence="charging")
    assert release == (True, "cap_lowered")
    assert morek_schedule.window_release(snap, cfg, now, profile, cap_lowered=False, price_event=True,
                                         evidence="charging") == (False, "release_ready_by_unknown")
