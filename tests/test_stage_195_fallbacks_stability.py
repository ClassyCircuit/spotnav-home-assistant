"""Stage 19.5: planner fallbacks table and active-window stability under the paths that exist today.

Part 1 classifies EVERY planner reason (`AutoReason`) as a fallback that plans, a healthy "nothing to charge", or a
hold with a stated who-acts. Part 2 drives the real worker through a healthy active window: observation reads,
routine publications, equal schedules and a horizon extension send nothing beyond the existing triggers.

Not covered, because it does not exist in production: Stage 19.2 (`resolve`, late responses; blocked) and 19.3's slow
retry. Mocked boundaries only; nothing here shows installed behaviour or physical charging.
"""

import typing
from datetime import timedelta
from pathlib import Path

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.api.morek_schedule import EXTRA_PLANNING_HOLDS, PLANNING_HOLDS, decision_blocker
from custom_components.spotnav.planning.auto_controller import AutoReason
from .test_morek_worker import NOW, drain, setup

H = timedelta(hours=1)
M = timedelta(minutes=1)

# ---- part 1: the fallback table (reason -> how it is handled) --------------------------------------------------
#: kind: `plans` (a plan is still produced from an honest input; the label says which), `healthy` (nothing to charge or
#: another owner runs it; not a hold), `hold` (no current intent; `who` acts), `retired`/`internal` (never reaches
#: the worker as a plan hold). `proof` names the existing test that exercises the fallback, or "" for a hold.
FALLBACKS: dict[str, tuple[str, str]] = {
    "settings_missing": ("hold", ""),
    "area_unknown": ("internal", ""),  # declared, not produced by the controller
    "fiscal_value_missing": ("hold", ""),
    "target_capacity_unknown": ("hold", ""),  # 17.3 plans from a learned kWh per percent; a hold only with none
    "target_soc_unknown": ("hold", ""),
    "target_soc_stale": ("hold", ""),  # 17.2 plans from a trusted estimate; a hold only with none
    "target_progress_uncertain": ("retired", ""),  # 17.1: plans from the reading, labelled `progress_unknown`
    "minimum_above_target": ("hold", ""),
    "no_prices_yet": ("hold", ""),
    "price_data_stale": ("hold", ""),  # an in-process uncapped proposal is retained (`_preserved_snapshot`)
    "ready": ("plans", "test_stage_162_safe_dispatch"),
    "unpriced": ("plans", "test_stage_162_safe_dispatch"),  # labelled unpriced; never sent as a priced plan
    "publication_pending": ("hold", ""),
    "waiting_for_history": ("hold", ""),
    "buying_before_publication": ("plans", "test_stage_162_safe_dispatch"),
    "charging_without_prices": ("plans", "test_stage_162_safe_dispatch"),
    "already_at_target": ("healthy", ""),
    "waiting_for_vehicle_update": ("healthy", ""),
    "solar_covers_need": ("healthy", ""),
    "no_published_prices": ("hold", ""),
    "price_data_invalid": ("hold", ""),
    "insufficient_price_horizon": ("hold", ""),  # the wait policy buys what cannot wait; else this hold
    "deadline_too_short": ("hold", ""),  # a best-effort conservative run is planned whenever one whole slot fits
    "missing_fx_rate": ("hold", ""),
    "unexpected_failure": ("hold", ""),
    "shutdown": ("internal", ""),
    "solar_execution_unavailable": ("hold", ""),
    "solar_running": ("healthy", ""),  # another owner (solar execution) runs the charger
    "price_policy_unavailable": ("hold", ""),
    "no_eligible_energy": ("healthy", ""),
}
_KINDS = {"plans", "healthy", "hold", "retired", "internal"}


def test_every_planner_reason_is_classified_exactly_once():
    assert set(FALLBACKS) == set(typing.get_args(AutoReason))
    assert {kind for kind, _ in FALLBACKS.values()} <= _KINDS


def test_every_hold_states_who_acts_and_what_ends_it_and_claims_nothing_else():
    for reason, (kind, _proof) in FALLBACKS.items():
        if kind != "hold":
            continue
        row = PLANNING_HOLDS.get(reason) or EXTRA_PLANNING_HOLDS.get(reason)
        assert row is not None, f"{reason} is a hold with no who-acts"
        action, who, recovery = row
        assert who in {"system", "vehicle", "person"} and recovery
        assert action in morek_schedule.DECISION_BLOCKERS.values() or action in {
            "set_battery_capacity", "wait_for_exchange_rate", "check_logs", "adjust_planning_settings"}
        block = decision_blocker("no_current_plan", reason)
        assert (block["action"], block["who"], block["recovery"], block["detail"]) == (action, who, recovery, reason)
    assert not set(PLANNING_HOLDS) & set(EXTRA_PLANNING_HOLDS)  # one owner per row


def test_person_owned_holds_never_invent_an_input():
    # A person's setting, departure or strategy is asked for; nothing is defaulted. They are not timer-retried as a
    # person-less automatic wait: the banner shows them as needing attention.
    for reason in ("settings_missing", "fiscal_value_missing", "minimum_above_target", "price_policy_unavailable",
                   "solar_execution_unavailable", "deadline_too_short"):
        assert decision_blocker("no_current_plan", reason)["who"] == "person"
    for reason in ("price_data_invalid", "insufficient_price_horizon", "publication_pending", "waiting_for_history"):
        assert decision_blocker("prices_stale_or_unavailable", reason)["action"] == "wait_for_prices"


def test_healthy_reasons_are_not_relabelled_as_holds_and_a_person_stop_is_never_relabelled():
    for reason, (kind, _) in FALLBACKS.items():
        if kind in ("healthy", "plans", "retired", "internal"):
            assert reason not in EXTRA_PLANNING_HOLDS
    for worker_reason in ("paused_until_resume", "upload_uncertain", "charge_now_active", "upload_not_sent"):
        assert decision_blocker(worker_reason, "deadline_too_short") == decision_blocker(worker_reason)
    assert decision_blocker("no_current_plan", "not_a_reason") == decision_blocker("no_current_plan")


@pytest.mark.parametrize("name", sorted({proof for _, proof in FALLBACKS.values() if proof}))
def test_named_fallback_proofs_exist(name):
    assert (Path(__file__).parent / f"{name}.py").is_file()


# ---- part 2: stability of a healthy active window --------------------------------------------------------------

def sent(w):
    return [call.args[0].payload["cs_charging_profiles"] for call in w.point.call.await_args_list]


def limits(profile):
    return [(p["startPeriod"], p["limit"]) for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]


async def started(monkeypatch):
    w = setup(monkeypatch, active=True)  # window NOW-1min .. NOW+2h
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: "charging")
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    return w


@pytest.mark.asyncio
async def test_status_and_observation_reads_never_send_during_a_healthy_window(monkeypatch):
    w = await started(monkeypatch)
    profile = sent(w)[0]
    ack = morek_schedule.acknowledged_profile(w.ledger.value)
    for _ in range(25):  # a status poll, a horizon read, recovery and blocker summaries are observation only
        morek_schedule.schedule_horizon(profile, "Accepted", {}, NOW)
        morek_schedule.recovery_status(w.ledger.value, NOW)
        morek_schedule.blocker_retry_status(w.worker)
        morek_schedule.decision_blocker(w.worker.reason, "deadline_too_short")
    assert ack is not None and w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_publication_soc_drift_and_equal_schedule_send_nothing_in_a_window(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    for cause in ("soc", "publication", "soc", None):
        w.planner.publish(cause)  # equal schedule, with each routine cause
        await drain(w.worker)
    # (a mixed SOC + publication burst is strict by the 14.3 rule, so the drift below is its own burst)
    w.planner.current.proposal.shown_periods = ((NOW - M, end + 4 * M),)  # SOC drift inside the 5 min tolerance
    w.planner.publish("soc")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "unchanged"
    w.worker.close()


@pytest.mark.asyncio
async def test_horizon_extension_sends_once_carries_the_window_and_an_equal_repeat_sends_nothing(monkeypatch):
    w = await started(monkeypatch)
    first = limits(sent(w)[0])
    w.planner.current.proposal.shown_periods = ((NOW - M, NOW + 2 * H), (NOW + 5 * H, NOW + 6 * H))  # later publication
    w.planner.publish("publication")
    await drain(w.worker)
    assert w.point.call.await_count == 2
    extended = limits(sent(w)[1])
    assert extended[0] == (0, 16) and first[0] == (0, 16)  # the acknowledged window continues: no 0 A gap
    assert extended == [(0, 16), (7200, 0), (18000, 16), (21600, 0)]
    for _ in range(3):
        w.planner.publish("publication")  # the same publication again
    await drain(w.worker)
    assert w.point.call.await_count == 2 and w.worker.reason == "unchanged"
    w.worker.close()


@pytest.mark.asyncio
async def test_a_hold_with_an_active_window_sends_nothing_and_keeps_the_acknowledged_window(monkeypatch):
    w = await started(monkeypatch)
    w.planner.current.proposal = None  # the planner now holds (no current intent)
    w.planner.publish("soc")
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason in {"no_current_plan", "unchanged"}
    assert morek_schedule.acknowledged_profile(w.ledger.value) is not None  # nothing was cleared
    w.worker.close()
