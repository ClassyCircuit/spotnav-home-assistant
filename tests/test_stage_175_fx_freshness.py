"""Stage 17.5: exchange-rate freshness and a truthful soft-cap statement.

The rate rule is read from the document only (`pricing/rate_label.py`): no fetch, estimate or substitute. Mocked
planner/controller; no Home Assistant, charger or deployment. An accepted plan is never physical charging.
"""

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from custom_components.spotnav.api.price_policy import encode_price_policy
from custom_components.spotnav.planning import planner
from custom_components.spotnav.pricing import rate_label
from custom_components.spotnav.pricing.relay_contract import parse_day

from .test_stage_162_safe_dispatch import _world


def _with_rate(doc, rate, fx_date, src="ECB", currency="SEK"):
    fx = {} if rate is None else {currency: rate}
    return replace(doc, fx=fx, fx_date=fx_date, fx_src=src if rate is not None else None)


def _fixture_doc():
    path = Path(__file__).parent / "fixtures" / "relay" / "day_SE4_2026-09-22_96.json"
    return parse_day(json.loads(path.read_text(encoding="utf-8")), area_id="SE4", day=date(2026, 9, 22))


def test_label_states_own_dated_undated_missing_and_too_old():
    base = _fixture_doc()
    day = base.day
    assert rate_label.piece_rate(_with_rate(base, 11.0, day), "SEK")["state"] == "own"
    dated = rate_label.piece_rate(_with_rate(base, 11.0, day - timedelta(days=3)), "SEK")
    assert (dated["state"], dated["age_days"], dated["date"], dated["source"]) == (
        "dated", 3, (day - timedelta(days=3)).isoformat(), "ECB")
    assert rate_label.piece_rate(_with_rate(base, 11.0, None), "SEK")["state"] == "undated"
    assert rate_label.piece_rate(_with_rate(base, None, None), "SEK")["state"] == "missing"
    assert rate_label.piece_rate(_with_rate(base, 11.0, day - timedelta(days=7)), "SEK")["state"] == "dated"
    assert rate_label.piece_rate(_with_rate(base, 11.0, day - timedelta(days=8)), "SEK")["state"] == "missing"
    assert rate_label.piece_rate(_with_rate(base, 11.0, day + timedelta(days=1)), "SEK")["state"] == "missing"
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        assert rate_label.piece_rate(_with_rate(base, bad, day), "SEK")["state"] == "missing"
    assert rate_label.piece_rate(_with_rate(base, 11.0, day), "NOK")["state"] == "missing"  # another currency
    assert rate_label.labels_for((base,), "EUR") is None and rate_label.rate_usable(base, "EUR")


def test_planner_converts_with_the_labelled_rate_and_refuses_otherwise():
    base = _fixture_doc()
    old = _with_rate(base, 10.0, base.day - timedelta(days=5))
    slots = planner.planning_slots((old,), currency="SEK", timezone=old.tz)
    assert slots[0].local_major_per_kwh == pytest.approx(base.prices[0] * 10.0)
    for bad in (_with_rate(base, None, None), _with_rate(base, 10.0, base.day - timedelta(days=8)),
                _with_rate(base, 10.0, base.day + timedelta(days=1))):
        with pytest.raises(planner.PlannerInputError) as err:
            planner.planning_slots((bad,), currency="SEK", timezone=bad.tz)
        assert err.value.code == "missing_fx_rate"
    # EUR is unchanged: no label, no rate lookup, the document's own fx is irrelevant.
    eur = planner.planning_slots((_with_rate(base, None, None),), currency="EUR", timezone=base.tz)
    assert eur[0].local_major_per_kwh == base.prices[0]


def test_cap_boundary_price_is_converted_with_the_labelled_rate():
    base = _fixture_doc()
    a = planner.planning_slots((_with_rate(base, 10.0, base.day - timedelta(days=2)),), currency="SEK", timezone=base.tz)
    b = planner.planning_slots((_with_rate(base, 12.0, base.day),), currency="SEK", timezone=base.tz)
    assert b[0].local_major_per_kwh / a[0].local_major_per_kwh == pytest.approx(1.2)


async def _sek_world(monkeypatch, tmp_path, *, with_tomorrow=False):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="ready",
                                 tomorrow_authority="listed", tomorrow_doc=[.2] * 96 if with_tomorrow else None)
    world.area.catalogue.currency = "SEK"
    if not with_tomorrow:
        world.area.tomorrow_state = "unavailable"
    return w, world, now


@pytest.mark.asyncio
async def test_missing_rate_waits_then_arrival_replans_once_and_labels_the_dated_rate(monkeypatch, tmp_path):
    w, world, now = await _sek_world(monkeypatch, tmp_path)
    doc = world.area.today_snapshot.document
    world.area.today_snapshot.document = _with_rate(doc, None, None)
    snapshot = await world.controller.async_recalculate()
    assert snapshot.reason == "missing_fx_rate" and not snapshot.proposal.has_plan
    policy = encode_price_policy(world.store.settings("test"), snapshot)
    assert policy["fx_state"] == "missing" and policy["fx_waiting"] is True
    assert "asked for again automatically" in policy["fx_note"]
    # The rate arrives: the rebuilt document is different price evidence, so the old calculation is never sent
    # and one recalculation plans from it. No other number was used meanwhile.
    day = doc.day
    world.area.today_snapshot.document = _with_rate(doc, 11.0, day - timedelta(days=2))
    assert world.controller.morek_price_blocker(snapshot, now) is not None
    fresh = await world.controller.async_recalculate()
    assert fresh.proposal.has_plan, fresh.reason
    policy = encode_price_policy(world.store.settings("test"), fresh)
    assert policy["fx_state"] == "dated" and policy["fx_waiting"] is False
    label = policy["fx"][0]
    assert (label["state"], label["age_days"], label["source"]) == ("dated", 2, "ECB")
    assert "ECB rate of" in policy["fx_note"] and "2 day(s)" in policy["fx_note"]
    again = await world.controller.async_recalculate()  # unchanged inputs: the same plan, no churn
    assert again.proposal.has_plan and again.proposal.slots == fresh.proposal.slots


@pytest.mark.asyncio
async def test_a_day_without_its_rate_does_not_cover_but_never_invalidates_the_other_day(monkeypatch, tmp_path):
    w, world, now = await _sek_world(monkeypatch, tmp_path, with_tomorrow=True)
    today = world.area.today_snapshot.document
    world.area.today_snapshot.document = _with_rate(today, 11.0, today.day)
    world.area.tomorrow_snapshot.document = _with_rate(world.area.tomorrow_snapshot.document, None, None)
    snapshot = await world.controller.async_recalculate()
    assert snapshot.proposal.has_plan, snapshot.reason
    assert all(slot.source == today.day.isoformat() for slot in snapshot.proposal.slots)
    assert rate_label.rate_usable(world.area.today_snapshot.document, "SEK")
    assert not rate_label.rate_usable(world.area.tomorrow_snapshot.document, "SEK")
    policy = encode_price_policy(world.store.settings("test"), snapshot)
    assert policy["fx_state"] == "missing"  # honest: one day still waits for its rate


@pytest.mark.asyncio
async def test_eur_area_has_no_label_and_is_unchanged(monkeypatch, tmp_path):
    w, world, now = await _world(monkeypatch, tmp_path, area_state="ready", tomorrow_state="unavailable",
                                 tomorrow_authority="unknown")
    snapshot = await world.controller.async_recalculate()
    assert snapshot.fx_provenance is None
    policy = encode_price_policy(world.store.settings("test"), snapshot)
    assert policy["fx"] is None and policy["fx_state"] is None and policy["fx_note"] is None
