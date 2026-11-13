"""Stage 14.5 corrections: measured partial progress, uncapped Morek guards, retry timer after restart.

The controller tests drive the real `_energy_for` path (real `_vehicle_update_wait`, `_progress_adjusted`
and `vehicle_update_wait.measured_progress`); only the charger controller and the session store are
stubbed. Mocked: nothing here proves deployed behaviour or physical charging.
"""

import asyncio
from dataclasses import replace
from datetime import time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.spotnav.planning import auto_controller
from custom_components.spotnav.planning.vehicle_update_wait import measured_progress
from custom_components.spotnav.sessions.model import SOURCE_ESTIMATED, SOURCE_REGISTER
from custom_components.spotnav.execution.command_admission import physical_connector
from .sessions_helpers import session
from .test_morek_worker import NOW, drain, setup
from .test_stage_13_reactive import _world
from .test_stage_145_fresh_inputs_recovery import _zones  # noqa: F401  (autouse fixture)


@pytest.fixture(autouse=True)
def _restore_domain_data():
    original = auto_controller.domain_data
    yield
    auto_controller.domain_data = original


def _wire(w, sessions, *, owned=True):
    car = SimpleNamespace(plugged_in_for_count=w.request.now - timedelta(hours=6), plan=None, charging=False,
                          car_ended_at=None, car_ended_waits_for=lambda **_k: False,
                          adapter=SimpleNamespace(vehicle_connected=lambda: True))
    w.controller._charger_controller = lambda: car  # noqa: SLF001
    store = SimpleNamespace(closed_raw=lambda _id: tuple(sessions), open_raw=lambda _id: None)
    auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
    w.controller._schedule_owned = AsyncMock(return_value=owned)  # noqa: SLF001
    return car


def _charge(start, kwh, *, source=SOURCE_REGISTER, vehicle="veh-1", hours=0.25):
    charge = session(start, hours=hours, energy=kwh, source=source, charger_id="test")
    charge.vehicle_id = vehicle
    return charge


async def _uncap(w):
    entry = w.area.catalogue
    entry.market_tz = entry.tz
    entry.publication = SimpleNamespace(tz=entry.tz, local_time=time(13, 0))
    await w.store.async_update("test", mutate=lambda s: replace(
        s, soft_price_cap=None, cap_price_basis=None, minimum_ready_by_soc=None))


def _read(w, read_at):
    """The car's level as read at `read_at`; the order memory of the world's setup calculation is forgotten."""
    w.facts[0] = replace(w.facts[0], soc_report_at=read_at)
    w.controller._soc_newest.clear()  # noqa: SLF001


def _shown(proposal):
    return proposal.requested_kwh


# ---- pure accounting -----------------------------------------------------------------------------

def test_measured_progress_counts_once_and_flags_unattributable_energy():
    read_at = NOW - timedelta(hours=1)
    plug = read_at - timedelta(hours=2)
    args = dict(read_at=read_at, plugged_in_at=plug, vehicle_id="veh-1", now=NOW)
    assert measured_progress([_charge(read_at + timedelta(minutes=5), 4.0)], **args).kwh == pytest.approx(4.0)
    # began before the reading: already in the level (counted nowhere), only uncertain while the reading is stale
    straddle = _charge(read_at - timedelta(minutes=10), 3.0, hours=2)
    got = measured_progress([straddle], **args)
    assert got.kwh == 0 and got.uncertain
    assert not measured_progress([straddle], **{**args, "now": read_at + timedelta(minutes=2)}).uncertain
    assert measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, vehicle=None)], **args).uncertain
    assert measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, vehicle="veh-2")], **args).kwh == 0
    est = measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, source=SOURCE_ESTIMATED)], **args)
    assert est.kwh == 0 and not est.uncertain
    done = _charge(read_at - timedelta(hours=1), 3.0, hours=0.25)  # ended before the reading
    assert measured_progress([done], **args) == measured_progress([], **args)


# ---- real controller path ------------------------------------------------------------------------

@pytest.mark.parametrize("uncapped", [False, True])
def test_partial_measured_energy_is_counted_once_and_a_fresh_reading_rebases(monkeypatch, uncapped):
    async def run():
        w = await _world(monkeypatch)
        if uncapped:
            await _uncap(w)
        now = w.request.now
        read_at = now - timedelta(hours=1)
        _read(w, read_at)
        _wire(w, [])
        base = (await w.controller.async_recalculate()).proposal
        assert base is not None
        _wire(w, [_charge(read_at + timedelta(minutes=5), 4.0)])
        partial = (await w.controller.async_recalculate()).proposal
        assert partial is not None and _shown(partial) == pytest.approx(_shown(base) - 4.0, abs=0.01)
        w.facts[0] = replace(w.facts[0], soc_report_at=now - timedelta(minutes=1))
        rebased = (await w.controller.async_recalculate()).proposal
        assert rebased is not None and _shown(rebased) == _shown(base)
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_energy_that_covers_the_need_holds_the_accepted_plan(monkeypatch, uncapped):
    async def run():
        w = await _world(monkeypatch)
        if uncapped:
            await _uncap(w)
        read_at = w.request.now - timedelta(hours=1)
        _read(w, read_at)
        _wire(w, [_charge(read_at + timedelta(minutes=5), 500.0)])
        snap = await w.controller.async_recalculate()
        assert snap.proposal is None and snap.reason == "waiting_for_vehicle_update"
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_unattributable_measured_energy_keeps_the_accepted_plan_with_a_reason(monkeypatch, uncapped):
    async def run():
        w = await _world(monkeypatch)
        if uncapped:
            await _uncap(w)
        read_at = w.request.now - timedelta(hours=1)
        _read(w, read_at)
        _wire(w, [_charge(read_at + timedelta(minutes=5), 2.0, vehicle=None)])
        snap = await w.controller.async_recalculate()
        assert (snap.state, snap.reason) == ("planning_unavailable", "target_progress_uncertain")
        assert snap.proposal is None
        _wire(w, [_charge(read_at - timedelta(minutes=30), 3.0, hours=2)])
        assert (await w.controller.async_recalculate()).reason == "target_progress_uncertain"
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now - timedelta(minutes=1))
        assert (await w.controller.async_recalculate()).proposal is not None
        _read(w, read_at)
        _wire(w, [_charge(read_at + timedelta(minutes=5), 9.0, vehicle="veh-2")])
        assert (await w.controller.async_recalculate()).proposal is not None
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_no_meter_or_unknown_plug_in_plans_from_the_reading_unchanged(monkeypatch, uncapped):
    async def run():
        w = await _world(monkeypatch)
        if uncapped:
            await _uncap(w)
        read_at = w.request.now - timedelta(hours=1)
        _read(w, read_at)
        _wire(w, [])
        base = (await w.controller.async_recalculate()).proposal
        _wire(w, [_charge(read_at + timedelta(minutes=5), 4.0, source=SOURCE_ESTIMATED)])
        again = (await w.controller.async_recalculate()).proposal
        assert again is not None and _shown(again) == _shown(base)
        car = _wire(w, [_charge(read_at + timedelta(minutes=5), 4.0)])
        car.plugged_in_for_count = None  # after a restart: no known plug-in, nothing attributable
        assert _shown((await w.controller.async_recalculate()).proposal) == _shown(base)
        w.controller._charger_controller = lambda: None  # noqa: SLF001
        assert _shown((await w.controller.async_recalculate()).proposal) == _shown(base)
    asyncio.run(run())


def test_uncapped_guards_apply_to_morek_only(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        await _uncap(w)
        _wire(w, [], owned=True)
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now + timedelta(hours=2))
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (True, "veh-2"))
        w.facts[0] = replace(w.facts[0], soc_report_at=None)
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
        _wire(w, [], owned=False)  # another charger: unchanged
        assert (await w.controller.async_recalculate()).proposal is not None
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now + timedelta(hours=2), vehicle_id="")
        assert (await w.controller.async_recalculate()).proposal is not None
    asyncio.run(run())


def test_uncapped_out_of_order_does_not_replace_good_plan(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        await _uncap(w)
        _wire(w, [])
        newer = w.request.now
        w.facts[0] = replace(w.facts[0], soc_report_at=newer)
        assert (await w.controller.async_recalculate()).proposal is not None
        w.facts[0] = replace(w.facts[0], soc_percent=60, soc_report_at=newer - timedelta(hours=1))
        stale = await w.controller.async_recalculate()
        assert stale.reason == "target_soc_stale" and stale.proposal is None
        # restart: the in-memory order memory is gone, so the older report is the baseline again
        w.controller._soc_newest.clear()  # noqa: SLF001
        assert (await w.controller.async_recalculate()).proposal is not None
    asyncio.run(run())


# ---- retry timer: restart, uncertainty, Stop -----------------------------------------------------

def _rejected(count, *, at, uncertain=False):
    return {"schema": 1, "entry_id": "charger", "uncertain": uncertain, "clean_start": None,
            "schedule_pause": None,
            "attempt": {"fingerprint": "old", "profile": {}, "at": at.isoformat(), "id": "a", "revision": 4,
                        "source": "worker", "state": "rejected", "rejections": count}}


async def _restarted(monkeypatch, record):
    w = setup(monkeypatch)
    w.ledger.value = record
    w.planner.morek_plan_blocker = lambda *_: "target_soc_stale"  # the run refuses: nothing is sent
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    return w


@pytest.mark.asyncio
async def test_retry_timer_is_rearmed_after_restart_respecting_uncertainty_and_limit(monkeypatch):
    w = await _restarted(monkeypatch, _rejected(1, at=NOW - timedelta(seconds=60)))
    assert w.worker._retry_timer is not None  # noqa: SLF001
    w.worker.close()
    assert w.worker._retry_timer is None  # noqa: SLF001
    for record in (_rejected(1, at=NOW - timedelta(seconds=60), uncertain=True),
                   _rejected(3, at=NOW - timedelta(seconds=60))):
        other = await _restarted(monkeypatch, record)
        assert other.worker._retry_timer is None  # noqa: SLF001
        other.worker.close()


@pytest.mark.asyncio
async def test_due_retry_does_not_rearm_in_a_loop_and_stop_blocks_the_send(monkeypatch):
    w = setup(monkeypatch)
    w.ledger.value = _rejected(1, at=NOW - timedelta(hours=1))
    w.admission._person_stops[physical_connector(w.identity)] = True  # noqa: SLF001
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    assert w.worker._retry_timer is None  # noqa: SLF001
    w.worker.close()
