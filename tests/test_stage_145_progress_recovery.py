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
from custom_components.spotnav.api import dashboard
from custom_components.spotnav.planning.vehicle_update_wait import measured_delivery_since, measured_progress, valid_energy_kwh
from custom_components.spotnav.sessions.model import SOURCE_ESTIMATED, SOURCE_REGISTER
from custom_components.spotnav.execution.command_admission import physical_connector
from .sessions_helpers import session
from .test_morek_worker import NOW, drain, real_planner_worker, setup
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
    assert got.kwh == 0 and got.unknown
    assert not measured_progress([straddle], **{**args, "now": read_at + timedelta(minutes=2)}).unknown
    assert measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, vehicle=None)], **args).unknown
    assert measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, vehicle="veh-2")], **args).kwh == 0
    est = measured_progress([_charge(read_at + timedelta(minutes=5), 2.0, source=SOURCE_ESTIMATED)], **args)
    assert est.kwh == 0 and not est.unknown
    done = _charge(read_at - timedelta(hours=1), 3.0, hours=0.25)  # ended before the reading
    assert measured_progress([done], **args) == measured_progress([], **args)


INVALID_ENERGY = (float("inf"), float("-inf"), float("nan"), -1.0, True, "5", None)


def test_invalid_measured_energy_never_counts_but_marks_unknown_and_valid_energy_is_kept():
    read_at = NOW - timedelta(hours=1)
    args = dict(read_at=read_at, plugged_in_at=read_at - timedelta(hours=2), vehicle_id="veh-1")
    after = read_at + timedelta(minutes=5)
    for bad in INVALID_ENERGY:
        assert measured_delivery_since([_charge(after, bad)], **args) is None
        got = measured_progress([_charge(after, bad)], now=NOW, **args)
        assert got.kwh == 0 and got.unknown, bad
        # valid plus invalid sessions: the valid energy is counted once, the invalid one only flags unknown
        both = measured_progress([_charge(after, bad), _charge(after + timedelta(minutes=30), 4.0)], now=NOW, **args)
        assert both.kwh == pytest.approx(4.0) and both.unknown, bad
        delivery = measured_delivery_since([_charge(after, bad), _charge(after + timedelta(minutes=30), 4.0)], **args)
        assert delivery is not None and delivery.kwh == pytest.approx(4.0)
        # another car's invalid energy is ignored entirely
        other = measured_progress([_charge(after, bad, vehicle="veh-2")], now=NOW, **args)
        assert other.kwh == 0 and not other.unknown, bad
    assert valid_energy_kwh(0) and valid_energy_kwh(2.5) and not valid_energy_kwh(True)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -5.0, True])
def test_invalid_post_reading_energy_cannot_wait_nor_hide_valid_progress(monkeypatch, bad):
    async def run():
        w = await _stale_world(monkeypatch, False)
        seen = _spy(w)
        await w.controller.async_recalculate()
        base_need = seen[-1][0]
        _wire(w, [_charge(w.read_at + timedelta(minutes=20), bad)])
        got = await w.controller.async_recalculate()
        assert got.reason != "waiting_for_vehicle_update" and got.proposal is not None
        assert got.progress_unknown and _shown(got.proposal) == pytest.approx(_shown(w.base.proposal))
        # valid known energy beside it is still subtracted, once, and the unknown flag is kept
        _wire(w, [_charge(w.read_at + timedelta(minutes=20), bad), _charge(w.read_at + timedelta(minutes=40), 4.0)])
        both = await w.controller.async_recalculate()
        assert both.progress_unknown and both.proposal is not None
        assert seen[-1][0] == pytest.approx(base_need - 4.0)
        # the sessions-based accounting never reads invalid energy as delivered
        assert w.controller._session_energy_since(w.read_at) == pytest.approx(4.0)  # noqa: SLF001
    asyncio.run(run())


def test_unattributable_energy_is_flagged_never_counted_and_known_energy_is_kept():
    read_at = NOW - timedelta(hours=1)  # stale: older than PROGRESS_FRESH_S
    args = dict(read_at=read_at, plugged_in_at=read_at - timedelta(hours=2), vehicle_id="veh-1", now=NOW)
    # a just-closed identified session that straddles the reading: not counted, progress unknown (whatever its size)
    for kwh in (0.05, 3.0):
        got = measured_progress([_charge(read_at - timedelta(minutes=10), kwh, hours=0.5)], **args)
        assert got.kwh == 0 and got.unknown
    # an unidentified one, before or after the reading
    for start in (read_at - timedelta(minutes=10), read_at + timedelta(minutes=5)):
        assert measured_progress([_charge(start, 0.05, vehicle=None, hours=0.5)], **args).unknown
    # genuinely known energy after the reading is counted once beside it (sessions are disjoint)
    mixed = measured_progress([_charge(read_at - timedelta(minutes=10), 1.0, hours=0.5),
                               _charge(read_at + timedelta(minutes=5), 4.0)], **args)
    assert mixed.kwh == pytest.approx(4.0) and mixed.unknown
    # an open straddling charge on a stale reading; invalid energy that overlaps the reading
    open_charge = _charge(read_at - timedelta(minutes=10), 1.0)
    open_charge.end = None
    assert measured_progress([open_charge], **args).unknown
    for bad in (float("nan"), float("inf"), -1.0):
        assert measured_progress([_charge(read_at - timedelta(minutes=10), bad, hours=0.5)], **args).unknown
        assert measured_progress([_charge(read_at + timedelta(minutes=5), bad)], **args).unknown
    # not unknown: nothing, an estimate, another car, an older session, a fresh reading
    assert not measured_progress([], **args).unknown
    assert measured_progress([_charge(read_at - timedelta(minutes=10), 9.0, hours=2, source=SOURCE_ESTIMATED),
                              _charge(read_at - timedelta(minutes=10), float("nan"), hours=2, vehicle="veh-2"),
                              _charge(read_at - timedelta(minutes=10), 9.0, hours=2, vehicle="veh-2"),
                              _charge(read_at - timedelta(hours=1), 3.0)], **args) == measured_progress([], **args)
    fresh = {**args, "now": read_at + timedelta(minutes=2)}
    assert not measured_progress([_charge(read_at - timedelta(minutes=10), 3.0, hours=2)], **fresh).unknown


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




# ---- ambiguous measured progress plans from the reading, marked unknown (2.5.145) -----------------------

def _spy(w):
    """What `_progress_adjusted` answered, in order: `(need, minimum, progress_unknown)` or a snapshot."""
    seen, real = [], w.controller._progress_adjusted  # noqa: SLF001

    def spy(*args, **kwargs):
        out = real(*args, **kwargs)
        seen.append(out)
        return out
    w.controller._progress_adjusted = spy  # noqa: SLF001
    return seen


def _projection(snapshot):
    return dashboard._proposal_section(SimpleNamespace(snapshot=snapshot, settings=None, area_entry=None, soc=None))["projection"]  # noqa: SLF001


async def _stale_world(monkeypatch, uncapped, sessions=()):
    """The live-like state: reserve saved at 20 %, a reading two hours old, a plug-in older than it."""
    w = await _world(monkeypatch)
    if uncapped:
        await _uncap(w)
    await w.store.async_update("test", mutate=lambda s: replace(s, time_reserve_percent=20))
    w.read_at = w.request.now - timedelta(hours=2)
    _read(w, w.read_at)
    _wire(w, [])
    w.base = await w.controller.async_recalculate()
    assert w.base.proposal is not None and not w.base.progress_unknown
    _wire(w, list(sessions))
    return w


@pytest.mark.parametrize("uncapped", [False, True])
def test_just_closed_unreconciled_identified_session_plans_unreduced_and_is_marked_unknown(monkeypatch, uncapped):
    """The reported symptom: a session for the identified car closed across the reading, its total not yet final.
    No `target_progress_uncertain` hold: the plan is the unreduced need, marked unknown, never shown as measured."""
    async def run():
        w = await _stale_world(monkeypatch, uncapped)
        closed = _charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)  # no register pair, no late record
        _wire(w, [closed])
        got = await w.controller.async_recalculate()
        assert got.reason != "target_progress_uncertain" and got.proposal is not None
        assert got.progress_unknown and _shown(got.proposal) == pytest.approx(_shown(w.base.proposal))
        if not uncapped:  # the dashboard's own projection says so (the uncapped fixture's plan is a price-wait one)
            assert _projection(got)["progress_unknown"] is True and _projection(w.base)["progress_unknown"] is False
        # a later reading (after the session) rebases: no longer unknown, same need from that level
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now - timedelta(minutes=1))
        later = await w.controller.async_recalculate()
        assert later.proposal is not None and not later.progress_unknown
        # the same session, once it ended before a reading, is not ambiguous at all
        _read(w, w.read_at + timedelta(hours=1))
        _wire(w, [closed])
        assert not (await w.controller.async_recalculate()).progress_unknown
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_known_energy_is_kept_once_beside_unknown_energy_and_nothing_is_double_counted(monkeypatch, uncapped):
    async def run():
        w = await _stale_world(monkeypatch, uncapped)
        seen = _spy(w)
        await w.controller.async_recalculate()
        base_need = seen[-1][0]
        crossing = _charge(w.read_at - timedelta(minutes=10), 2.0, hours=0.5)
        unidentified = _charge(w.read_at + timedelta(minutes=20), 1.0, vehicle=None)
        known = _charge(w.read_at + timedelta(minutes=40), 4.0)
        _wire(w, [crossing, unidentified, known])
        got = await w.controller.async_recalculate()
        assert got.progress_unknown
        # only the identified 4 kWh after the reading is subtracted; the 2 + 1 kWh are neither counted nor guessed
        assert _shown(got.proposal) == pytest.approx(_shown(w.base.proposal) - 4.0, abs=0.01)
        need, minimum, unknown = seen[-1]
        assert unknown and need == pytest.approx(base_need - 4.0)
        # known energy that covers the need still waits for the car's level, unknown energy or not
        _wire(w, [crossing, _charge(w.read_at + timedelta(minutes=40), 500.0)])
        assert (await w.controller.async_recalculate()).reason == "waiting_for_vehicle_update"
    asyncio.run(run())


def test_minimum_exception_need_is_not_reduced_by_unknown_energy_and_is_flagged(monkeypatch):
    """With a minimum level the cap exception is sized from the reading; unattributed energy does not shrink it, so
    it can plan above-cap energy the car may already have. Known energy still reduces it, once."""
    async def run():
        w = await _stale_world(monkeypatch, uncapped=False)
        seen = _spy(w)
        _wire(w, [])
        await w.controller.async_recalculate()
        base_need, base_min, _ = seen[-1]
        assert base_min is not None and base_min > 0
        crossing = _charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)
        _wire(w, [crossing])
        await w.controller.async_recalculate()
        assert seen[-1] == (base_need, base_min, True)
        _wire(w, [crossing, _charge(w.read_at + timedelta(minutes=5), 1.0)])
        await w.controller.async_recalculate()
        need, minimum, unknown = seen[-1]
        assert unknown and need == pytest.approx(base_need - 1.0) and minimum == pytest.approx(max(0.0, base_min - 1.0))
        await _uncap(w)  # uncapped: no minimum, so no exception to over-plan
        _wire(w, [crossing])
        assert (await w.controller.async_recalculate()).progress_unknown
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_active_session_and_active_window_plan_from_the_reading_unknown(monkeypatch, uncapped):
    async def run():
        w = await _stale_world(monkeypatch, uncapped)
        car = _wire(w, [])
        car.charging = True
        car.plan = SimpleNamespace(windows=[(w.request.now - timedelta(minutes=30), w.request.now + timedelta(hours=1))])
        active = _charge(w.read_at - timedelta(minutes=10), 5.0)
        active.end = None
        store = SimpleNamespace(closed_raw=lambda _id: (), open_raw=lambda _id: active)
        auto_controller.domain_data = lambda _h: SimpleNamespace(session_store=store)
        got = await w.controller.async_recalculate()
        assert got.proposal is not None and got.progress_unknown
        assert _shown(got.proposal) == pytest.approx(_shown(w.base.proposal))
    asyncio.run(run())


@pytest.mark.parametrize("uncapped", [False, True])
def test_identity_and_stale_level_guards_stay_separate_from_unknown_progress(monkeypatch, uncapped):
    async def run():
        w = await _stale_world(monkeypatch, uncapped, [_charge(NOW, 1.0, vehicle=None)])
        assert (await w.controller.async_recalculate()).progress_unknown  # unidentified energy, identified car
        w.facts[0] = replace(w.facts[0], vehicle_id="")  # the reading is for no car: identity is never guessed
        snap = await w.controller.async_recalculate()
        assert snap.reason == "target_soc_stale" and snap.proposal is None and not snap.progress_unknown
        w.facts[0] = replace(w.facts[0], vehicle_id="veh-1")
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (True, "veh-2"))  # mismatched car
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (True, "veh-1"))
        w.facts[0] = replace(w.facts[0], soc_report_at=w.request.now + timedelta(hours=2))  # a level from the future
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
    asyncio.run(run())


# ---- real controller + real worker: what automatic upload does with an unknown-progress plan -------

async def _ambiguous_worker(monkeypatch, *, stop=False):
    w, world = await real_planner_worker(monkeypatch)
    world.read_at = world.request.now - timedelta(hours=2)
    _read(world, world.read_at)
    _wire(world, [])
    base = await world.controller.async_recalculate()
    assert base.proposal is not None
    _wire(world, [_charge(world.read_at - timedelta(minutes=10), 0.2, hours=0.5)])
    world.base = base
    if stop:
        w.admission._person_stops[physical_connector(w.identity)] = True  # noqa: SLF001
    return w, world


@pytest.mark.asyncio
async def test_unknown_progress_plan_is_admitted_and_uploaded_once_and_later_inputs_do_not_churn(monkeypatch):
    w, world = await _ambiguous_worker(monkeypatch)
    snap = await world.controller.async_recalculate()
    assert snap.progress_unknown and snap.proposal is not None
    assert world.controller.morek_plan_blocker(snap, world.request.now) is None  # no new admission refusal
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1  # the same guarded send path as any plan
    # the same need again (session finalised, nothing else changed): the accepted plan is not re-sent
    world.controller._publish(await world.controller.async_recalculate())  # noqa: SLF001
    await drain(w.worker)
    assert w.point.call.await_count == 1
    # a fresh reading rebases: not unknown any more, same level, same need, still one upload
    world.facts[0] = replace(world.facts[0], soc_report_at=world.request.now - timedelta(minutes=1))
    later = await world.controller.async_recalculate()
    assert later.proposal is not None and not later.progress_unknown
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_person_stop_blocks_the_unknown_progress_upload(monkeypatch):
    w, world = await _ambiguous_worker(monkeypatch, stop=True)
    assert (await world.controller.async_recalculate()).progress_unknown
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 0
    w.worker.close()


@pytest.mark.asyncio
async def test_unknown_dispatch_outcome_blocks_a_changed_unknown_progress_plan(monkeypatch):
    w, world = await _ambiguous_worker(monkeypatch)
    await world.controller.async_recalculate()
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.ledger.value["uncertain"] = True  # the send's outcome is genuinely unknown: never retried or replaced
    world.facts[0] = replace(world.facts[0], soc_percent=30, soc_report_at=world.read_at)
    world.controller._soc_newest.clear()  # noqa: SLF001
    assert (await world.controller.async_recalculate()).progress_unknown
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_uncertain"
    w.worker.close()


# ---- 17.1 review: evidence, churn, minimum-exception bounds --------------------------------------

def test_decision_evidence_records_progress_unknown_additively_and_never_as_measured(monkeypatch):
    """A plan sent from an unknown-progress calculation is visible in the decision's `inputs`; no new sensitive field."""
    from custom_components.spotnav.api import morek_schedule

    async def run():
        w = await _stale_world(monkeypatch, uncapped=False)
        _wire(w, [_charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)])
        unknown = await w.controller.async_recalculate()
        assert unknown.progress_unknown
        for snap, expected in ((unknown, True), (w.base, False)):
            monkeypatch.setattr(morek_schedule, "preview_for", lambda *_a, _s=snap: SimpleNamespace(snapshot=lambda: _s))
            inputs = morek_schedule._planning_inputs(None, "test")  # noqa: SLF001
            assert inputs["progress_unknown"] is expected
            event = morek_schedule.decision_event(
                now=NOW, kinds=("settings",), last_trigger="settings", reason="upload_accepted_unverified",
                inputs=inputs, evidence="x", continuity=None, dispatched=True)
            assert event["inputs"]["progress_unknown"] is expected
            assert event["stages"]["physical"] == "not_measured"
        # a calculation failure still yields a plain unknown record
        monkeypatch.setattr(morek_schedule, "preview_for", lambda *_a: (_ for _ in ()).throw(RuntimeError()))
        assert morek_schedule._planning_inputs(None, "test") == {"plan_state": "unknown", "uncertain": True}  # noqa: SLF001
    asyncio.run(run())


def test_progress_unknown_flip_alone_publishes_once_and_never_recalculates(monkeypatch):
    """The flag is in `meaningful_key` so the display updates; a repeat of the same flag is silent, and no
    publication starts another calculation (no loop)."""
    async def run():
        w = await _stale_world(monkeypatch, uncapped=False)
        base = w.base
        flagged = replace(base, progress_unknown=True)
        assert base.meaningful_key() != flagged.meaningful_key()
        assert replace(flagged, progress_unknown=False).meaningful_key() == base.meaningful_key()
        calls, heard = [], []
        real = w.controller.async_recalculate

        async def counted(*a, **k):
            calls.append(1)
            return await real(*a, **k)
        monkeypatch.setattr(w.controller, "async_recalculate", counted)
        w.controller.add_listener(heard.append)
        heard.clear()  # a new listener is first told the current snapshot
        w.controller._last_key = base.meaningful_key()  # noqa: SLF001
        w.controller._publish(flagged, force=False)  # noqa: SLF001
        w.controller._publish(flagged, force=False)  # noqa: SLF001
        assert len(heard) == 1 and heard[0].progress_unknown and not calls
    asyncio.run(run())


def test_minimum_exception_never_exceeds_the_minimum_need_from_the_reading_nor_the_target(monkeypatch):
    """Unknown progress with a soft cap and a minimum level: the above-cap energy stays within the minimum need
    worked out from the reading (the documented limit) and never past the target; the plan is flagged."""
    async def run():
        w = await _stale_world(monkeypatch, uncapped=False)
        seen = _spy(w)
        _wire(w, [])
        await w.controller.async_recalculate()
        base_need, base_min, _ = seen[-1]
        _wire(w, [_charge(w.read_at - timedelta(minutes=10), 0.2, hours=0.5)])
        snap = await w.controller.async_recalculate()
        need, minimum, unknown = seen[-1]
        assert unknown and snap.progress_unknown and snap.proposal is not None
        assert base_min is not None and minimum is not None and minimum <= base_min + 1e-9
        assert minimum <= need + 1e-9 and need <= base_need + 1e-9  # never past the target need
        assert _shown(snap.proposal) <= base_need + 1e-6
    asyncio.run(run())
