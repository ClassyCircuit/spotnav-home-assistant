"""Stage 14.3: recalculation triggers and guarded send deduplication.

Real worker, session observer and profile comparison; HA, OCPP and ownership are the usual
mocked boundaries. Assertions are on how many SetChargingProfile calls actually reached the point.
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session, morek_worker
from .test_morek_worker import NOW, drain, setup

M = timedelta(minutes=1)
H = timedelta(hours=1)


def sends(w):
    return w.point.call.await_count


def set_window(w, end):
    start, _ = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end),)


async def started(monkeypatch):
    w = setup(monkeypatch, active=True)  # window NOW-1min .. NOW+2h
    w.worker.start()
    await drain(w.worker)
    assert sends(w) == 1
    return w


async def settle(w):
    await asyncio.sleep(0.02)  # let the plug-in task recalculate and trigger
    await drain(w.worker)


def recalculating(w):
    """A planner whose recalculation publishes the way the real one does: with the caller's cause."""
    async def recalculate(cause=None):
        w.planner.publish(cause)
        return w.planner.current
    w.planner.async_recalculate = AsyncMock(side_effect=recalculate)


def session_for(w):
    session = morek_session.MorekSessionCoordinator(w.worker)
    session.trigger = lambda: None  # the start-request flow is not under test here
    return session


def profile(now, *windows, amps=16):
    return morek_schedule.profile_for(tuple(windows), amps, now, allow_active=True)


# ---- semantic comparison -------------------------------------------------------------

def test_comparison_ignores_creation_time_elapsed_transitions_and_equal_representations():
    accepted = profile(NOW, (NOW - M, NOW + H), (NOW + 2 * H, NOW + 3 * H))
    later = NOW + 90 * M  # the first window is over; the second is still ahead
    assert morek_schedule.same_effective_schedule(accepted, profile(later, (NOW + 2 * H, NOW + 3 * H)))
    redundant = profile(NOW, (NOW - M, NOW + H), (NOW + 2 * H, NOW + 3 * H))
    redundant["chargingSchedule"]["chargingSchedulePeriod"].insert(
        1, {"startPeriod": 10, "limit": 16, "numberPhases": 3})
    assert morek_schedule.same_effective_schedule(accepted, redundant)
    assert morek_schedule.same_effective_schedule(redundant, accepted)
    other_amps = profile(NOW, (NOW - M, NOW + H), (NOW + 2 * H, NOW + 3 * H), amps=10)
    assert not morek_schedule.same_effective_schedule(accepted, other_amps)
    assert not morek_schedule.same_effective_schedule(accepted, profile(later, (NOW + 2 * H, NOW + 4 * H)))
    assert not morek_schedule.same_effective_schedule(None, accepted)
    assert not morek_schedule.same_effective_schedule({"chargingSchedule": {}}, accepted)


def test_end_tolerance_is_strictly_under_five_minutes_and_only_for_switch_offs():
    tolerance = timedelta(minutes=5)
    accepted = profile(NOW, (NOW + H, NOW + 2 * H))

    def shifted(end, start=H):
        return profile(NOW, (NOW + start, NOW + end))

    same = morek_schedule.same_effective_schedule
    assert same(accepted, shifted(2 * H + 4 * M + timedelta(seconds=59)), tolerance)
    assert same(accepted, shifted(2 * H - 4 * M), tolerance)
    assert not same(accepted, shifted(2 * H + 5 * M), tolerance)
    assert not same(accepted, shifted(2 * H + 4 * M))  # no tolerance unless asked for
    assert not same(accepted, shifted(2 * H, start=H + M), tolerance)  # a start is never tolerated
    ending_now = profile(NOW, (NOW - M, NOW + 2 * H))
    assert not same(ending_now, profile(NOW, (NOW + 5 * M, NOW + 2 * H)), tolerance)  # permission now differs


# ---- send counts through the worker -------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_equal_routine_publications_send_once(monkeypatch):
    w = await started(monkeypatch)
    for _ in range(5):
        w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 1 and w.worker.reason == "unchanged" and w.worker.last_trigger == "routine"
    w.worker.close()


@pytest.mark.asyncio
async def test_routine_soc_tolerance_but_larger_change_sends(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 1 and w.worker.reason == "unchanged"
    set_window(w, end + 6 * M)
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_plug_in_recalculates_and_compares_equal_schedule_without_sending(monkeypatch):
    w = await started(monkeypatch)
    w.worker.note_plug_in()
    await settle(w)
    w.planner.async_recalculate.assert_awaited_once()
    assert sends(w) == 1 and w.worker.reason == "unchanged" and w.worker.last_trigger == "plug_in"
    w.worker.close()


@pytest.mark.asyncio
async def test_plug_in_sends_a_changed_schedule_and_ignores_the_soc_tolerance(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)  # would be tolerated as a routine SOC change
    w.worker.note_plug_in()
    await settle(w)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_price_change_is_not_tolerated_but_unchanged_prices_are(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    w.planner.current.price_revision = 1  # first sighting of a price revision
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 1  # equal schedule
    w.planner.current.price_revision = 2
    set_window(w, end + 4 * M)
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.last_trigger == "price"
    w.worker.close()


@pytest.mark.asyncio
async def test_settings_edit_is_sent_even_with_an_equal_schedule_and_resets_the_baseline(monkeypatch):
    w = await started(monkeypatch)
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.last_trigger == "settings"
    w.planner.publish("soc")  # the accepted record now belongs to revision 5
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.reason == "unchanged"
    w.worker.close()


@pytest.mark.asyncio
async def test_required_sync_is_never_suppressed_by_a_matching_accepted_schedule(monkeypatch):
    w = await started(monkeypatch)
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_unknown_outcome_blocks_further_sends_until_resolved(monkeypatch):
    w = setup(monkeypatch, active=True)
    w.point.call.side_effect = TimeoutError()
    w.worker.start()
    await drain(w.worker)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 1 and w.worker.reason == "upload_uncertain"
    w.worker.close()


@pytest.mark.asyncio
async def test_routine_burst_waits_but_an_explicit_control_does_not(monkeypatch):
    w = await started(monkeypatch)
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0.3)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    for _ in range(4):
        w.planner.publish("soc")
    await asyncio.sleep(0.1)
    assert sends(w) == 1  # still coalescing
    w.worker.trigger()  # an explicit control shortens the wait
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_routine_burst_is_one_run(monkeypatch):
    w = await started(monkeypatch)
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0.1)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    for _ in range(6):
        w.planner.publish("soc")
        await asyncio.sleep(0.01)
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_pause_wins_over_a_queued_routine_update(monkeypatch):
    w = await started(monkeypatch)
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0.3)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    w.planner.publish("soc")
    record = await w.ledger.read()
    record["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                "station_id": morek_schedule.MOREK_STATION_ID, "connector_id": 1}
    await w.ledger.write(record)
    w.worker.trigger()
    await drain(w.worker)
    assert sends(w) == 2
    held = w.point.call.await_args_list[1].args[0].payload["cs_charging_profiles"]
    assert [p["limit"] for p in held["chargingSchedule"]["chargingSchedulePeriod"]] == [0]
    w.worker.close()


# ---- cause: only an SOC publication is routine ------------------------------------

@pytest.mark.asyncio
async def test_same_revision_deadline_or_unknown_publication_gets_no_soc_tolerance(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)  # tolerated only for an SOC reading
    w.planner.publish()  # same revisions, cause unknown (deadline rollover, plan watch, ...)
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.last_trigger == "recalc"
    set_window(w, end + 8 * M)
    w.planner.publish("deadline")
    await drain(w.worker)
    assert sends(w) == 3
    w.worker.close()


@pytest.mark.asyncio
async def test_mixed_soc_and_other_cause_in_one_burst_is_strict_and_still_one_run(monkeypatch):
    w = await started(monkeypatch)
    monkeypatch.setattr(morek_worker, "_ROUTINE_COALESCE_SECONDS", 0.1)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    w.planner.publish("soc")
    w.planner.publish()
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2  # one coalesced run, no tolerance
    assert w.worker._strict is False  # the sticky flag clears once the run completes
    # a following pure SOC burst is tolerant again
    set_window(w, end + 8 * M)
    w.planner.publish("soc")
    await drain(w.worker)
    assert sends(w) == 2 and w.worker.reason == "unchanged"
    w.worker.close()


# ---- session evidence through the production wiring --------------------------------

@pytest.mark.asyncio
async def test_connector_sensor_loss_and_return_recalculate_and_compare(monkeypatch):
    w = await started(monkeypatch)
    recalculating(w)
    session = session_for(w)
    session.observe("Charging", "Unavailable")
    await settle(w)
    assert w.planner.async_recalculate.await_count == 1
    assert sends(w) == 1 and w.worker.reason == "unchanged" and w.worker.last_trigger == "sensor"
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)  # SOC would tolerate this; a sensor recovery must not
    session.observe("Unavailable", "Charging")
    await settle(w)
    assert w.planner.async_recalculate.await_count == 2
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_sensor_loss_never_sends_while_the_charger_is_unavailable(monkeypatch):
    w = await started(monkeypatch)
    recalculating(w)
    session = session_for(w)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    w.worker._available = lambda: False
    session.observe("Charging", "Unavailable")
    await settle(w)
    assert w.planner.async_recalculate.await_count == 1
    assert sends(w) == 1 and w.worker.reason == "charger_unavailable"
    w.worker._available = lambda: True
    session.observe("Unavailable", "Charging")
    await settle(w)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_failed_recalculation_on_sensor_return_compares_but_never_forces_a_send(monkeypatch):
    w = await started(monkeypatch)
    w.planner.async_recalculate = AsyncMock(side_effect=RuntimeError("inputs unavailable"))
    session = session_for(w)
    session.observe("Unavailable", "Charging")
    await settle(w)
    assert w.planner.async_recalculate.await_count == 1
    assert sends(w) == 1 and w.worker.reason == "unchanged"
    w.worker.close()


@pytest.mark.asyncio
async def test_available_to_connected_is_a_plug_in_that_recalculates_and_ignores_tolerance(monkeypatch):
    w = await started(monkeypatch)
    recalculating(w)
    session = session_for(w)
    session.observe("Available", "Preparing")
    await settle(w)
    w.planner.async_recalculate.assert_awaited_once_with("plug_in")
    assert sends(w) == 1 and w.worker.last_trigger == "plug_in"  # equal schedule: compared, not sent
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    session.observe("Available", "Charging")  # plugged in with the charger already active
    await settle(w)
    assert w.planner.async_recalculate.await_count == 2 and sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_return_from_unknown_or_unavailable_is_not_inferred_to_be_a_plug_in(monkeypatch):
    w = await started(monkeypatch)
    recalculating(w)
    session = session_for(w)
    for old in ("Unknown", "Unavailable"):
        session.observe(old, "Preparing")
        await settle(w)
        assert w.worker.last_trigger == "sensor", old
    assert [c.args for c in w.planner.async_recalculate.await_args_list] == [("sensor",), ("sensor",)]
    session.observe(None, "Preparing")  # initial seeding is neither
    session.observe("Preparing", "Charging")
    await settle(w)
    assert w.planner.async_recalculate.await_count == 2
    assert sends(w) == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_evidence_noted_during_a_recalculation_is_coalesced_not_lost(monkeypatch):
    w = await started(monkeypatch)
    gate = asyncio.Event()
    calls = []

    async def slow(cause=None):
        calls.append(cause)
        if len(calls) == 1:
            await gate.wait()
        w.planner.publish(cause)

    w.planner.async_recalculate = AsyncMock(side_effect=slow)
    session = session_for(w)
    session.observe("Available", "Preparing")
    await asyncio.sleep(0.01)
    session.observe("Preparing", "Unavailable")
    session.observe("Unavailable", "Preparing")  # several during one in-flight recalculation
    gate.set()
    await settle(w)
    assert calls == ["plug_in", "sensor"]
    assert sends(w) == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_close_cancels_pending_evidence_without_a_send(monkeypatch):
    w = await started(monkeypatch)
    recalculating(w)
    session = session_for(w)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 30 * M)
    session.observe("Available", "Preparing")
    w.worker.close()
    await asyncio.sleep(0.05)
    assert sends(w) == 1
