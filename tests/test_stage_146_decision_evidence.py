"""Stage 14.6: bounded decision evidence for the Morek schedule worker.

Real worker, planner-publication listener, session observer, comparison and send path, and SpotNav's real
log buffer; HA, OCPP and ownership are the usual mocked boundaries (see `test_morek_worker.setup`). Assertions
are on actual send counts, the recorded decision, the native log lines and their bound. Mocked only: an
intent, an ACK and a readback are not measured charging, and nothing here touches Home Assistant or a charger.
"""

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.log_buffer import MAX_MESSAGE_CHARS, SPOTNAV_LOGGER, attach_log_buffer, detach_log_buffer
from .test_morek_worker import NOW, drain
from .test_stage_144_interruption_policy import LATER, replan, started as started_active, state_box

SENSITIVE = ("chargingSchedule", "startSchedule", "charging_profile", "station", "ocpp", "token", "sensor.", "price")


@pytest.fixture(autouse=True)
def _fast_coalescing(monkeypatch):
    from custom_components.spotnav.execution import morek_worker
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0)  # production value is 2 s; not under test


@pytest.fixture
def logs():
    logger = logging.getLogger(SPOTNAV_LOGGER)
    previous = logger.level
    logger.setLevel(logging.INFO)
    buffer = attach_log_buffer()
    yield lambda: [r for r in buffer.records() if "Morek schedule decision" in r["message"]]
    detach_log_buffer(buffer)
    logger.setLevel(previous)


def recalculating(w):
    async def recalculate(cause=None):
        w.planner.publish(cause)
        return w.planner.current
    w.planner.async_recalculate = AsyncMock(side_effect=recalculate)


async def settle(w):
    await asyncio.sleep(0.02)
    await drain(w.worker)


def status(w, *, verified=False, verification=None):
    return morek_schedule.decision_status(w.worker, verification or {}, verified)


# ---- pure helpers ---------------------------------------------------------------------------------

def test_blockers_are_actionable_codes_and_superseded_runs_are_not_blockers():
    for ok in (None, "unchanged", "upload_accepted_unverified", "stale_work", "pending", "not_started"):
        assert morek_schedule.decision_blocker(ok) is None
    assert morek_schedule.decision_blocker("charger_unavailable") == {
        "code": "charger_unavailable", "action": "wait_for_charger_connection"}
    assert morek_schedule.decision_blocker("target_soc_stale")["action"] == "wait_for_fresh_inputs"
    assert morek_schedule.decision_blocker("something_new")["action"] == "see_reason"
    assert len(morek_schedule.decision_blocker("x" * 500)["code"]) == 60


def test_event_separates_intent_ack_readback_and_physical_and_keeps_only_whitelisted_fields():
    inputs = {"plan_state": "ready", "soc_source": "vehicle", "soc_age_s": 12, "uncertain": False,
              "entity_id": "sensor.secret", "plan_reason": None, "soc_estimated": False}
    cont = {"evidence": "charging", "preserved": True, "reason": None, "until": "x", "profile": {"a": 1}}
    event = morek_schedule.decision_event(now=NOW, kinds={"sensor", "routine"}, last_trigger="sensor",
                                          reason="upload_accepted_unverified", inputs=inputs,
                                          evidence="charging", continuity=cont)
    assert event["stages"] == {"intent": "sent", "ack": "accepted", "readback": None, "physical": "not_measured"}
    assert event["action"] == "sent" and event["changed"] is True and event["blocker"] is None
    assert set(event["continuity"]) == {"evidence", "preserved", "reason"}
    assert "entity_id" not in event["inputs"] and "secret" not in repr(event)
    skipped = morek_schedule.decision_event(now=NOW, kinds=(), last_trigger=None, reason="unchanged",
                                            inputs={}, evidence="unknown", continuity=None)
    assert skipped["action"] == "skipped" and skipped["changed"] is False
    assert skipped["stages"]["intent"] == "none" and skipped["stages"]["ack"] == "accepted_earlier"
    blocked = morek_schedule.decision_event(now=NOW, kinds=(), last_trigger=None, reason="target_soc_stale",
                                            inputs={}, evidence="unknown", continuity=None)
    assert blocked["action"] == "blocked" and blocked["stages"]["ack"] is None and blocked["changed"] is None


# ---- plug-in through calculation and guarded send ---------------------------------------------------

@pytest.mark.asyncio
async def test_plug_in_recalculates_compares_and_records_an_equal_skip(monkeypatch, logs):
    w = await started_active(monkeypatch)
    recalculating(w)
    w.worker.note_plug_in()
    await settle(w)
    w.planner.async_recalculate.assert_awaited_once()
    assert w.point.call.await_count == 1
    latest = status(w)["latest"]
    assert (latest["trigger"], latest["action"], latest["result"], latest["changed"]) == (
        "plug_in", "skipped", "unchanged", False)
    assert latest["evidence"] == "charging" and latest["stages"]["intent"] == "none"
    assert latest["continuity"]["preserved"] is True and latest["blocker"] is None
    lines = logs()
    assert len(lines) == 2 and "trigger=plug_in action=skipped result=unchanged changed=False" in lines[-1]["message"]
    assert "not measured charging" in lines[-1]["message"]
    w.worker.close()


@pytest.mark.asyncio
async def test_changed_plan_is_sent_and_readback_is_reported_separately(monkeypatch, logs):
    w = await started_active(monkeypatch)
    start, end = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end + timedelta(minutes=30)),)
    w.planner.publish("soc")
    await drain(w.worker)
    assert w.point.call.await_count == 2
    first = status(w)["latest"]
    assert first["action"] == "sent" and first["changed"] is True and first["stages"]["ack"] == "accepted"
    assert first["stages"]["readback"] == "unconfirmed" and first["stages"]["physical"] == "not_measured"
    assert status(w, verification={"pending": True})["latest"]["stages"]["readback"] == "pending"
    assert status(w, verification={"reason": "limits_or_transitions_differ"})["latest"]["stages"]["readback"] == "mismatch"
    assert status(w, verified=True)["latest"]["stages"]["readback"] == "verified"
    assert w.worker.decision["stages"]["readback"] is None  # the stored event never claims a readback
    w.worker.close()


# ---- repeated sensor updates while charging ---------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_routine_updates_while_charging_are_one_counted_decision_and_one_log_line(monkeypatch, logs):
    w = await started_active(monkeypatch)
    for _ in range(12):
        w.planner.publish("soc")
        await drain(w.worker)
    assert w.point.call.await_count == 1
    assert w.worker.decision["result"] == "unchanged" and w.worker.decision["repeat"] == 12
    assert len(w.worker.decisions) == 2  # the first send and the skip, however many repeats
    assert len(logs()) == 2
    assert "last_at" in w.worker.decision
    w.worker.close()


# ---- price-driven interruption ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_price_driven_interruption_records_trigger_reason_and_send(monkeypatch, logs):
    w = await started_active(monkeypatch)
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    assert w.point.call.await_count == 2
    latest = status(w)["latest"]
    assert (latest["trigger"], latest["action"], latest["changed"]) == ("price", "sent", True)
    assert latest["continuity"] == {"evidence": "charging", "preserved": False, "reason": "price_improvement"}
    assert "preserved=False reason=price_improvement" in logs()[-1]["message"]
    w.worker.close()


@pytest.mark.asyncio
async def test_unknown_state_keeps_the_window_and_the_decision_says_why(monkeypatch, logs):
    w = await started_active(monkeypatch, state="unknown")
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    latest = status(w)["latest"]
    assert latest["evidence"] == "unknown"
    assert latest["continuity"]["preserved"] is True
    assert latest["continuity"]["reason"] == "active_window_state_unknown"
    w.worker.close()
    state_box["state"] = "charging"


# ---- blockers and recovery ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unavailable_charger_is_an_actionable_blocker_then_recovers(monkeypatch, logs):
    w = await started_active(monkeypatch)
    available = {"v": False}
    w.worker._available = lambda: available["v"]
    w.worker.trigger()
    await drain(w.worker)
    latest = status(w)["latest"]
    assert latest["action"] == "blocked" and latest["stages"]["intent"] == "none"
    assert latest["blocker"] == {"code": "charger_unavailable", "action": "wait_for_charger_connection"}
    assert w.point.call.await_count == 1
    available["v"] = True
    w.worker.trigger()
    await drain(w.worker)
    assert status(w)["latest"]["action"] == "skipped" and status(w)["latest"]["blocker"] is None
    w.worker.close()


@pytest.mark.asyncio
async def test_rejection_and_uncertain_write_are_warnings_with_distinct_acks(monkeypatch, logs):
    w = await started_active(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    latest = status(w)["latest"]
    assert (latest["action"], latest["result"], latest["stages"]["ack"]) == ("sent", "upload_rejected", "rejected")
    assert latest["stages"]["readback"] is None and latest["blocker"]["action"] == "check_charger_response"
    assert [r["level"] for r in logs()][-1] == "WARNING"
    w.worker.close()

    w = await started_active(monkeypatch)
    w.point.call.side_effect = TimeoutError
    replan(w, LATER)
    w.planner.current.price_revision = "p2"
    w.planner.publish()
    await drain(w.worker)
    latest = status(w)["latest"]
    assert (latest["result"], latest["stages"]["ack"]) == ("upload_uncertain", "unknown")
    assert latest["stages"]["intent"] == "sent" and latest["blocker"]["action"] == "check_charger_outcome"
    w.worker.close()


@pytest.mark.asyncio
async def test_stop_race_is_blocked_without_a_send_and_names_the_guard(monkeypatch, logs):
    from custom_components.spotnav.execution.command_admission import physical_connector
    w = await started_active(monkeypatch)
    w.admission._person_stops[physical_connector(w.identity)] = True  # noqa: SLF001
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert w.point.call.await_count == 1
    latest = status(w)["latest"]
    assert latest["action"] == "blocked" and latest["stages"]["intent"] == "none"
    assert latest["blocker"]["code"] in ("stale_generation", "stale_work")
    w.worker.close()


# ---- bounded volume and privacy -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_volume_is_bounded_and_nothing_sensitive_is_recorded(monkeypatch, logs):
    w = await started_active(monkeypatch)
    available = {"v": True}
    w.worker._available = lambda: available["v"]
    for _ in range(40):  # every run changes the decision: worst case for volume
        available["v"] = not available["v"]
        w.worker.trigger()
        await drain(w.worker)
    assert len(w.worker.decisions) == 10
    assert len(status(w)["recent"]) == 5
    assert len(logs()) <= 42
    text = repr(list(w.worker.decisions)) + " ".join(r["message"] for r in logs())
    assert all(len(r["message"]) <= MAX_MESSAGE_CHARS for r in logs())
    for word in SENSITIVE[:-1]:
        assert word not in text, word
    w.worker.close()


@pytest.mark.asyncio
async def test_status_without_a_finished_run_has_no_decision(monkeypatch):
    from .test_morek_worker import setup
    w = setup(monkeypatch)
    assert morek_schedule.decision_status(w.worker, {}, False) is None


# ---- diagnostic accuracy: dispatch, stale continuity, attempt binding --------------------------------------

@pytest.mark.asyncio
async def test_real_rejection_then_cooldown_is_a_sent_then_a_held_decision_without_a_new_command(monkeypatch, logs):
    from .test_morek_worker import setup
    w = setup(monkeypatch)
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    w.worker.start()
    await drain(w.worker)
    first = w.worker.decision
    assert (first["action"], first["result"], first["stages"]["intent"], first["stages"]["ack"]) == (
        "sent", "upload_rejected", "sent", "rejected")
    assert w.point.call.await_count == 1
    w.worker.trigger()  # inside the cooldown: the durable rejection blocks it, no wire call
    await drain(w.worker)
    held = w.worker.decision
    assert w.point.call.await_count == 1
    assert (held["action"], held["result"], held["stages"]["intent"], held["stages"]["ack"]) == (
        "held", "upload_rejected", "none", "rejected_earlier")
    assert held["changed"] is None and held["blocker"]["action"] == "check_charger_response"
    assert held["attempt_id"] == first["attempt_id"] and held["stages"]["readback"] is None
    assert status(w)["latest"]["stages"]["readback"] is None
    assert [r["level"] for r in logs()][-1] == "INFO"  # the earlier rejection already warned
    w.worker.close()


@pytest.mark.asyncio
async def test_early_charger_unavailable_does_not_repeat_continuity_from_the_prior_run(monkeypatch, logs):
    w = await started_active(monkeypatch)
    recalculating(w)
    w.worker.note_plug_in()
    await settle(w)
    assert w.worker.continuity["preserved"] is True  # the earlier run evaluated and kept the window
    assert status(w)["latest"]["continuity"]["preserved"] is True
    w.worker._available = lambda: False  # noqa: SLF001
    w.worker.trigger()
    await drain(w.worker)
    latest = status(w)["latest"]
    assert latest["action"] == "blocked" and latest["result"] == "charger_unavailable"
    assert latest["continuity"] is None and "preserved=None" in logs()[-1]["message"]
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_readback_binds_to_the_decisions_own_attempt(monkeypatch):
    w = await started_active(monkeypatch)
    start, end = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end + timedelta(minutes=30)),)
    w.planner.publish("soc")
    await drain(w.worker)
    sent = w.worker.decision
    assert sent["action"] == "sent" and sent["attempt_id"]
    same = morek_schedule.decision_status(w.worker, {}, True, sent["attempt_id"])["latest"]
    assert same["stages"]["readback"] == "verified"
    other = morek_schedule.decision_status(w.worker, {}, True, "f" * 32)["latest"]
    assert other["stages"]["readback"] == "superseded"
    w.worker.close()
