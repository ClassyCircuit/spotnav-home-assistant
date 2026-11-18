"""Stage 19.5 + 19.9b: durable material-input provenance and restart/reconnect send counts.

Real worker, send path and comparison; HA, OCPP and ownership are the usual mocked boundaries. A "restart" is a new
worker over the same durable ledger. Assertions are on SetChargingProfile calls actually made.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_worker
from .test_morek_worker import NOW, drain, setup

M = timedelta(minutes=1)
H = timedelta(hours=1)


def rows(price=10.0, count=12, first=-1):
    return tuple(SimpleNamespace(utc_start=NOW + (first + i) * H, utc_end=NOW + (first + i + 1) * H,
                                 effective_minor_per_kwh=price + i) for i in range(count))


def provenance(w, horizon=None):
    proposal = w.planner.current.proposal
    proposal.horizon = horizon if horizon is not None else rows()
    proposal.current_interval = None
    proposal.power_kw = 11.0
    proposal.currency = "EUR"
    w.planner.current.price_revision = "fees-a"
    w.planner.current.departure_at = NOW + 10 * H
    w.settings.soft_price_cap = None
    w.settings.cap_price_basis = None


def sends(w):
    return w.point.call.await_count


def set_window(w, end):
    start, _ = w.planner.current.proposal.shown_periods[0]
    w.planner.current.proposal.shown_periods = ((start, end),)


async def started(monkeypatch, *, with_provenance=True):
    w = setup(monkeypatch, active=True)
    if with_provenance:
        provenance(w)
    w.worker.start()
    await drain(w.worker)
    assert sends(w) == 1
    return w


async def restart(w):
    w.worker.close()
    w.worker = morek_worker.MorekScheduleWorker(w.hass, "charger", w.planner)
    w.worker.start()  # the planner delivers its current snapshot at once: the first publication of this process
    await drain(w.worker)


async def accepted(w):
    return morek_schedule.acknowledged_inputs(await w.ledger.read())


@pytest.mark.asyncio
async def test_acceptance_stores_compact_provenance_without_soc(monkeypatch):
    w = await started(monkeypatch)
    inputs = await accepted(w)
    assert inputs["settings_revision"] == 4 and inputs["price_revision"] == "fees-a" and len(inputs["rows"]) == 12
    assert "soc" not in str(inputs).lower()
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_soc_drift_under_five_minutes_with_matching_provenance_sends_nothing(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    await restart(w)
    assert sends(w) == 1 and w.worker.reason == "unchanged" and w.worker.dedup_basis == "soc_provenance"
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_drift_of_five_minutes_or_more_still_sends(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 5 * M)
    await restart(w)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_without_stored_provenance_stays_strict(monkeypatch):
    w = await started(monkeypatch, with_provenance=False)  # an older record / unknowable inputs
    assert await accepted(w) is None
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    await restart(w)
    assert sends(w) == 2 and w.worker.dedup_basis is None
    w.worker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["price_row", "price_revision", "departure", "cap", "basis", "power"])
async def test_restart_with_a_changed_material_input_stays_strict(monkeypatch, change):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    if change == "price_row":
        changed = list(rows())
        changed[3] = SimpleNamespace(**{**vars(changed[3]), "effective_minor_per_kwh": 99.0})
        w.planner.current.proposal.horizon = tuple(changed)
    elif change == "price_revision":
        w.planner.current.price_revision = "fees-b"
    elif change == "departure":
        w.planner.current.departure_at = NOW + 12 * H
    elif change == "cap":
        w.settings.soft_price_cap = 20.0
    elif change == "basis":
        w.planner.current.projection_estimated = True
    else:
        w.planner.current.proposal.power_kw = 7.4
    await restart(w)
    assert sends(w) == 2 and w.worker.dedup_basis is None
    w.worker.close()


@pytest.mark.asyncio
async def test_restart_with_a_settings_revision_change_sends(monkeypatch):
    w = await started(monkeypatch)
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    await restart(w)
    assert sends(w) == 2
    w.worker.close()


@pytest.mark.asyncio
async def test_reconnect_control_uses_provenance_but_sync_plug_in_and_sensor_stay_strict(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    w.worker.trigger()  # link/availability return
    await drain(w.worker)
    assert sends(w) == 1 and w.worker.dedup_basis == "soc_provenance"
    w.worker.trigger(kind="recovery")
    await drain(w.worker)
    assert sends(w) == 1
    w.worker.trigger(kind="plug_in")
    await drain(w.worker)
    assert sends(w) == 2  # plug-in ignores the tolerance (Stage 14)
    set_window(w, end + 8 * M)  # 4 minutes from the newest acceptance
    w.worker.trigger(kind="sensor")
    await drain(w.worker)
    assert sends(w) == 3  # a sensor recovery never uses the tolerance
    set_window(w, end + 11 * M)
    w.worker.trigger(sync=True)
    await drain(w.worker)
    assert sends(w) == 4  # a required sync is never suppressed
    w.worker.close()


@pytest.mark.asyncio
async def test_a_mixed_run_with_a_hard_trigger_is_strict(monkeypatch):
    w = await started(monkeypatch)
    _, end = w.planner.current.proposal.shown_periods[0]
    set_window(w, end + 4 * M)
    w.worker.trigger()
    w.worker.trigger(kind="plug_in")
    await drain(w.worker)
    assert sends(w) == 2
    w.worker.close()


def test_provenance_comparison_units():
    class S:
        revision, amps, soft_price_cap, cap_price_basis = 4, 16, None, None

    def snap(horizon):
        proposal = SimpleNamespace(has_plan=True, power_kw=11.0, currency="EUR", horizon=horizon,
                                   current_interval=None)
        return SimpleNamespace(proposal=proposal, settings_revision=4, price_state="ready", price_revision=None,
                               departure_at=None)

    stored = morek_schedule.material_inputs(S, snap(rows()))
    same = morek_schedule.material_inputs_unchanged
    assert stored is not None
    later = NOW + 3 * H  # elapsed rows drop out; the horizon rolled forward over newly visible later prices
    rolled = morek_schedule.material_inputs(S, snap(rows(count=16)))
    assert same(stored, rolled, later)
    inserted = list(rows(count=16))
    inserted[5] = SimpleNamespace(**{**vars(inserted[5]), "effective_minor_per_kwh": 1.0})
    assert not same(stored, morek_schedule.material_inputs(S, snap(tuple(inserted))), later)
    assert not same(stored, rolled, NOW + 20 * H)  # evidence aged out: not provable
    assert not same(None, stored, NOW) and not same(stored, None, NOW) and not same({}, {}, NOW)
    assert morek_schedule.material_inputs(S, snap(())) is None  # no priced rows: unknown, never empty-equal
    S.amps = "16"
    assert morek_schedule.material_inputs(S, snap(rows())) is None
