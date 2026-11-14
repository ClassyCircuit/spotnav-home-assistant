"""Stage 17.2: stale SOC with trustworthy estimates.

The shared trust rule (`estimate_trusted`/`capped_planning_facts`), the real controller capped path, the guarded
admission blocker and the real Morek worker (HA/OCPP are the usual mocked boundaries). Not deployed or physically
verified.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.spotnav.execution.target_stop import SocReading
from custom_components.spotnav.planning.auto_controller import (
    ESTIMATE_MAX_ANCHOR_AGE_S, ESTIMATE_MAX_DELIVERED_KWH, LiveVehicleFacts, capped_planning_facts,
    capped_vehicle_energy, estimate_trusted,
)
from custom_components.spotnav.planning.learned_energy import NOTHING_LEARNED
from custom_components.spotnav.vehicles.soc_estimate import SocAnchor, resolve_soc
from .test_morek_worker import NOW, drain, real_planner_worker
from .test_stage_13_reactive import _world


@pytest.fixture(autouse=True)
def _zones():
    from zoneinfo import ZoneInfo
    from custom_components.spotnav import time_zones
    time_zones._remember("Europe/Stockholm", ZoneInfo("Europe/Stockholm"))  # noqa: SLF001


def est(**kw):
    """A trusted estimate: anchor 25 %, 6 kWh delivered since, so the running level is higher."""
    base = dict(vehicle_id="veh-1", soc_percent=34.0, soc_age_s=3600, reported_capacity_kwh=60, soc_estimated=True,
                anchor_percent=25.0, anchor_at=NOW - timedelta(hours=1), delivered_kwh=6.0, soc_entity_id="sensor.soc")
    base.update(kw)
    return LiveVehicleFacts(**base)


# ---- the one trust rule --------------------------------------------------------------------------------

def test_trust_rule_and_fallback_basis():
    assert estimate_trusted(est())
    for bad in (dict(vehicle_id=""), dict(anchor_percent=None), dict(anchor_at=None), dict(reported_capacity_kwh=None),
                dict(reported_capacity_kwh=0), dict(delivered_kwh=None), dict(delivered_kwh=0),
                dict(delivered_kwh=ESTIMATE_MAX_DELIVERED_KWH + 1), dict(register_reset=True),
                dict(soc_age_s=ESTIMATE_MAX_ANCHOR_AGE_S + 1), dict(soc_age_s=None), dict(soc_age_s=float("nan"))):
        f = est(**bad)
        assert not estimate_trusted(f), bad
        basis = capped_planning_facts(f)
        if f.anchor_percent is None:
            assert basis is None
        else:  # never worse than 12.8: the anchor reading itself, an actual one
            assert basis.soc_percent == 25.0 and not basis.soc_estimated
    assert capped_planning_facts(est()).soc_estimated and capped_planning_facts(est()).soc_percent == 34.0
    actual = LiveVehicleFacts(vehicle_id="veh-1", soc_percent=40, soc_age_s=9e6, reported_capacity_kwh=60)
    assert capped_planning_facts(actual) is actual and not estimate_trusted(actual)


def test_capped_energy_uses_only_trusted_estimates():
    kw = dict(target_percent=80, minimum_percent=40, learned=NOTHING_LEARNED)
    ok = capped_vehicle_energy(est(), **kw)
    assert ok[0] == "ok"
    lower = capped_vehicle_energy(replace(est(), soc_percent=25.0, soc_estimated=False), **kw)
    assert ok[1] < lower[1] and ok[2] < lower[2]  # the estimate shrinks target need and the minimum, one figure
    assert capped_vehicle_energy(est(delivered_kwh=None), **kw)[0] == "target_soc_stale"


# ---- SocReader provenance -------------------------------------------------------------------------------

def test_resolved_estimate_carries_anchor_provenance_and_reset_flag():
    anchor = SocAnchor(50.0, 100.0, NOW - timedelta(hours=2), "vehicle", "veh-1", "sensor.reg")
    stale = SocReading(soc_percent=50.0, source="vehicle", entity_id="sensor.soc", vehicle_id="veh-1",
                       age_s=7200, time_basis="last_updated")
    kw = dict(reading=stale, capacity_kwh=60.0, now=NOW, vehicle_id="veh-1", register_entity_id="sensor.reg",
              register_updated_at=NOW)
    got = resolve_soc(anchor=anchor, register_kwh=106.0, **kw).reading
    assert got.estimated and got.anchor_percent == 50.0 and got.anchor_at == anchor.read_at
    assert got.delivered_kwh == pytest.approx(6.0) and not got.register_reset
    # a register that fell back and kept counting: the carry is kept, flagged as a reset (not trusted)
    after_reset = resolve_soc(anchor=anchor, register_kwh=1.0, **kw)
    reset = resolve_soc(anchor=after_reset.anchor, register_kwh=3.0, **kw).reading
    assert reset.estimated and reset.register_reset
    # a register that went backwards leaves no estimate at all
    assert not resolve_soc(anchor=anchor, register_kwh=60.0, **kw).reading.estimated


# ---- real controller ------------------------------------------------------------------------------------

def test_trusted_estimate_plans_capped_and_labels_it(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        base = await w.controller.async_recalculate()
        w.controller._soc_newest.clear()  # the estimate's anchor is older than the base reading's instant
        w.facts[0] = est(soc_age_s=1800, soc_percent=25.0 + 12.0, delivered_kwh=8.0)
        snap = await w.controller.async_recalculate()
        assert snap.proposal is not None, (snap.state, snap.reason)
        assert snap.proposal.requested_kwh < base.proposal.requested_kwh  # planned from the estimate
        assert snap.projection_estimated and snap.projection_source == w.facts[0].soc_source
    asyncio.run(run())


def test_untrusted_estimate_falls_back_to_anchor_reading_not_hold(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        base = await w.controller.async_recalculate()
        w.controller._soc_newest.clear()
        w.facts[0] = est(soc_percent=60.0, anchor_percent=25.0, register_reset=True, soc_age_s=1800)
        snap = await w.controller.async_recalculate()
        assert snap.proposal is not None and not snap.projection_estimated
        assert snap.proposal.requested_kwh == pytest.approx(base.proposal.requested_kwh)  # from the 25 % anchor
        w.facts[0] = est(anchor_percent=None, delivered_kwh=None)
        held = await w.controller.async_recalculate()
        assert held.reason == "target_soc_stale" and held.proposal is None
        w.facts[0] = est(vehicle_id="")  # unknown car identity is never planned from, estimate or not
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
    asyncio.run(run())


def test_estimate_without_capacity_is_not_trusted_and_capacity_hold_stays(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.facts[0] = est(reported_capacity_kwh=None)
        snap = await w.controller.async_recalculate()
        assert snap.proposal is None and snap.reason == "target_capacity_unknown"
    asyncio.run(run())


def test_other_car_and_order_guard_still_apply_to_estimates(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        monkeypatch.setattr(w.controller, "_notification_vehicle", lambda: (True, "veh-2"))
        w.facts[0] = est()
        assert (await w.controller.async_recalculate()).reason == "target_soc_stale"
    asyncio.run(run())


def test_estimate_drift_does_not_change_evidence_but_anchor_and_trust_do(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        settings = w.store.settings("test")
        w.facts[0] = est(soc_percent=34.0, delivered_kwh=6.0)
        first = w.controller._morek_input_evidence(settings)  # noqa: SLF001
        w.facts[0] = est(soc_percent=41.0, delivered_kwh=9.5, soc_age_s=3900)  # register ticks, same anchor
        assert w.controller._morek_input_evidence(settings) == first  # noqa: SLF001
        w.facts[0] = est(anchor_percent=30.0)  # a fresh reading rebased the anchor
        assert w.controller._morek_input_evidence(settings) != first  # noqa: SLF001
        w.facts[0] = est(register_reset=True)  # trust flipped
        assert w.controller._morek_input_evidence(settings) != first  # noqa: SLF001
        w.facts[0] = replace(est(), soc_estimated=False, soc_percent=34.0)  # label cleared by an actual level
        assert w.controller._morek_input_evidence(settings) != first  # noqa: SLF001
    asyncio.run(run())


def test_blocker_admits_trusted_estimate_and_ticks_do_not_block(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.controller._soc_newest.clear()
        w.facts[0] = est(soc_percent=37.0, delivered_kwh=8.0, soc_age_s=1800)
        snap = await w.controller.async_recalculate()
        assert snap.proposal is not None
        assert w.controller.morek_plan_blocker(snap, w.request.now) is None
        w.facts[0] = est(soc_percent=39.0, delivered_kwh=9.0, soc_age_s=1900)  # routine tick
        assert w.controller.morek_plan_blocker(snap, w.request.now) is None
        w.facts[0] = est(soc_percent=39.0, delivered_kwh=9.0, soc_age_s=1900, register_reset=True)
        assert w.controller.morek_plan_blocker(snap, w.request.now) == "plan_inputs_changed"
        w.facts[0] = est(anchor_percent=None, delivered_kwh=None)
        assert w.controller.morek_plan_blocker(snap, w.request.now) == "plan_inputs_changed"
    asyncio.run(run())


def test_blocker_refuses_unanchored_estimate_when_evidence_matches(monkeypatch):
    async def run():
        w = await _world(monkeypatch)
        w.facts[0] = est(anchor_percent=None, delivered_kwh=None)
        snap = await w.controller.async_recalculate()
        assert snap.proposal is None
        monkeypatch.setattr(w.controller, "_morek_input_evidence", lambda *_: snap.morek_input_evidence)
        assert w.controller.morek_plan_blocker(snap, w.request.now) in ("vehicle_input_stale", "plan_input_provenance_unavailable")
    asyncio.run(run())


# ---- real worker: dispatches once, drift neither resends nor blocks -------------------------------------

@pytest.mark.asyncio
async def test_trusted_estimate_dispatches_once_and_register_drift_neither_resends_nor_blocks(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.controller._soc_newest.clear()
    world.facts[0] = est(soc_percent=37.0, delivered_kwh=8.0, soc_age_s=1800)
    await world.controller.async_recalculate()
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    world.facts[0] = est(soc_percent=39.5, delivered_kwh=9.4, soc_age_s=1900)
    assert world.controller.morek_plan_blocker(world.controller.snapshot(), world.request.now) is None
    w.worker.trigger()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()


@pytest.mark.asyncio
async def test_untrusted_estimate_dispatches_from_anchor_reading_once(monkeypatch):
    w, world = await real_planner_worker(monkeypatch)
    world.controller._soc_newest.clear()
    world.facts[0] = est(soc_percent=60.0, register_reset=True, soc_age_s=1800)
    snap = await world.controller.async_recalculate()
    assert snap.proposal is not None
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()
