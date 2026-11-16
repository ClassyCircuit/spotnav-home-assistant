"""Stage 8.3a: day-average spot savings, through the live callers (`sessions_answer`, `charging_history_answer`).

A real `PriceRepository` holds real day documents (hass-free: store double, every fetch path fails the test); the
sessions and evidence stores are doubles. Nothing fetches, refreshes or writes.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_83a_savings.py
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.spotnav.api import sessions as api
from custom_components.spotnav.planning.planner import document_rate, FiscalChoice
from custom_components.spotnav.runtime import DATA_KEY
from custom_components.spotnav.sessions.costing import (
    PlacedSpan, RetainedPrice, session_spot, Slice, SpotAllocation, day_bounds,
)
from custom_components.spotnav.sessions.savings import DayAverageReference

from .sessions_helpers import STOCKHOLM, UTC
from .test_stage_63_history import make_store
from .test_stage_74a_price_insights import AREA, CLOCK_NOW, document, hold, repository  # noqa: F401
from .test_stage_82a_spot_cost import charge

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
D21, D22, D23, D24 = (date(2026, 9, day) for day in (21, 22, 23, 24))
DST = date(2026, 10, 25)
QUARTERS_20 = [0.10] * 48 + [0.30] * 48  # quarter-hour day: 12 h at 0.10, 12 h at 0.30 -> mean 0.20
HOURS_15 = [0.05] * 12 + [0.25] * 12  # hourly day, mean 0.15


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=STOCKHOLM).astimezone(UTC)


class World(SimpleNamespace):
    def fx(self, day: date) -> float:
        return document_rate(self.repository.day_snapshot(AREA, day).document, "SEK")

    def slice(self, start: datetime, hours: float, kwh: float, eur: float, *, currency: str = "SEK") -> Slice:
        if currency == "EUR":
            return Slice(start, start + timedelta(hours=hours), kwh, eur, 1.0, None, 999.0)
        day = start.astimezone(STOCKHOLM).date()
        doc = self.repository.day_snapshot(AREA, day).document or self.repository.day_snapshot(AREA, D22).document
        # `day_avg_eur` is nonsense on purpose: the reference must come from the held full day, never from it.
        return Slice(start, start + timedelta(hours=hours), kwh, eur, document_rate(doc, "SEK"), doc.fx_date, 999.0)

    def session(self, sid: str, start: datetime, slices: list[Slice], *, currency: str = "SEK"):
        row = charge(start, slices, currency=currency)
        return replace(row, id=sid, area_id=AREA)

    def hass(self, sessions: list[Any]) -> Any:
        self.sessions = sessions
        data = SimpleNamespace(
            session_store=SimpleNamespace(closed=lambda _id: tuple(self.sessions), closed_raw=lambda _id: tuple(self.sessions),
                                          open_session=lambda _id: None),
            price_repository=self.repository,
        )
        return SimpleNamespace(data={DATA_KEY: data}, config=SimpleNamespace(time_zone="Europe/Stockholm"))

    def history(self, sessions: list[Any], day: date) -> dict[str, Any]:
        return api.charging_history_answer(self.hass(sessions), "c", {"date": day.isoformat()})

    def month(self, sessions: list[Any]) -> dict[str, Any]:
        return api.sessions_answer(self.hass(sessions), "c", {"month": "2026-09"})


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, repository) -> World:  # noqa: F811
    hold(repository, document(D22, res=15, prices=QUARTERS_20), document(D23, res=60, prices=HOURS_15))
    store, _ = make_store()
    monkeypatch.setattr(api, "evidence_for", lambda _hass: store)
    monkeypatch.setattr(api.dt_util, "utcnow", lambda: NOW)

    def forbidden(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a savings read must never fetch, refresh or write")

    for name in ("async_get_day", "async_get_file", "async_get_archive_day", "async_fetch_history",
                 "async_persist_history", "async_get_profile", "_persist"):
        monkeypatch.setattr(repository, name, forbidden)
    return World(repository=repository)


def close(value: float | None, expected: float) -> bool:
    return value is not None and abs(value - round(expected, 4)) < 1.5e-4


# ---- the baseline itself ----------------------------------------------------------------------------------------

def test_quarter_hour_day_reference_is_the_duration_weighted_mean_and_stored_day_average_is_ignored(world) -> None:
    session = world.session("a", at(D22, 2), [world.slice(at(D22, 2), 1, 1.0, 0.10), world.slice(at(D22, 3), 1, 1.0, 0.10)])
    answer = world.history([session], D22)
    block = answer["window_spot_cost"]["savings"]
    fx = world.fx(D22)
    assert block["basis"] == "day_average_price" and block["state"] == "complete" and block["estimate"] is True
    assert close(block["reference_cost"], 2 * 0.20 * fx) and close(block["actual_cost"], 2 * 0.10 * fx)
    assert close(block["amount"], 2 * 0.10 * fx) and block["percentage"] == 50.0
    assert block["comparable_kwh"] == 2.0 and block["excluded_kwh"] == 0.0 and block["currency"] == "SEK"
    assert block["reference_sources"] == ["stub"] and block["reference_days"] == 1
    # The row blocks come from the same path; the total spot cost is the unchanged 8.2a one.
    row = answer["sessions"][0]
    assert row["spot_cost"]["savings"]["amount"] == block["amount"]
    assert row["spot_cost_in_window"]["savings"]["amount"] == block["amount"]
    assert close(answer["window_spot_cost"]["amount"], 2 * 0.10 * fx)


def test_hourly_day_and_negative_savings_when_charging_above_the_average(world) -> None:
    session = world.session("a", at(D23, 13), [world.slice(at(D23, 13), 1, 1.0, 0.25)])
    block = world.history([session], D23)["window_spot_cost"]["savings"]
    fx = world.fx(D23)
    assert close(block["amount"], (0.15 - 0.25) * fx) and block["amount"] < 0
    assert block["percentage"] == round((0.15 - 0.25) / 0.15 * 100, 2)


def test_midnight_slice_is_split_by_delivery_day_before_the_reference(world) -> None:
    straddle = at(D22, 23, 30)
    session = world.session("a", straddle, [world.slice(straddle, 1, 2.0, 0.10)])
    day22 = world.history([session], D22)["window_spot_cost"]["savings"]
    day23 = world.history([session], D23)["window_spot_cost"]["savings"]
    assert day22["comparable_kwh"] == 1.0 and day23["comparable_kwh"] == 1.0
    assert close(day22["reference_cost"], 1 * 0.20 * world.fx(D22)) and close(day23["reference_cost"], 1 * 0.15 * world.fx(D23))
    whole = world.history([session], D22)["sessions"][0]["spot_cost"]["savings"]
    assert whole["comparable_kwh"] == 2.0
    assert close(whole["reference_cost"], 0.20 * world.fx(D22) + 0.15 * world.fx(D23))


def test_dst_25_hour_day_is_averaged_over_25_hours(world, repository) -> None:  # noqa: F811
    hold(repository, document(DST, res=60, prices=[0.10] * 24 + [1.35]))
    session = world.session("a", at(DST, 12), [world.slice(at(DST, 12), 1, 1.0, 0.10)])
    block = world.history([session], DST)["window_spot_cost"]["savings"]
    start, end = day_bounds(DST, STOCKHOLM)
    assert (end - start) == timedelta(hours=25)
    assert close(block["reference_cost"], (24 * 0.10 + 1.35) / 25 * world.fx(DST))


def test_zero_and_negative_reference_have_amounts_but_no_percentage(world, repository) -> None:  # noqa: F811
    hold(repository, document(D24, res=60, prices=[0.0] * 24), document(date(2026, 9, 20), res=60, prices=[-0.10] * 24))
    zero = world.session("z", at(D24, 5), [world.slice(at(D24, 5), 1, 1.0, 0.05)])
    negative = world.session("n", at(date(2026, 9, 20), 5), [world.slice(at(date(2026, 9, 20), 5), 1, 1.0, -0.20)])
    zero_block = world.history([zero], D24)["window_spot_cost"]["savings"]
    negative_block = world.history([negative], date(2026, 9, 20))["window_spot_cost"]["savings"]
    assert zero_block["percentage"] is None and close(zero_block["amount"], -0.05 * world.fx(D24))
    assert negative_block["percentage"] is None and negative_block["state"] == "complete"
    assert close(negative_block["amount"], (-0.10 + 0.20) * world.fx(date(2026, 9, 20)))
    assert zero_block["reference_cost"] == 0.0 and negative_block["reference_cost"] < 0


# ---- missing / partial references --------------------------------------------------------------------------------

def test_missing_held_day_is_counted_unknown_never_a_subset_average(world) -> None:
    straddle = at(D21, 23, 30)  # half in the held 22nd, half in the 21st that is not held
    session = world.session("a", straddle, [world.slice(straddle, 1, 2.0, 0.10)])
    answer = world.history([session], D22)
    window = answer["window_spot_cost"]
    assert close(window["amount"], 0.0 + 1 * 0.10 * world.fx(D22)) and window["priced_kwh"] == 1.0
    whole = answer["sessions"][0]["spot_cost"]
    assert whole["priced_kwh"] == 2.0  # the total actual cost stays whole
    savings = whole["savings"]
    assert savings["state"] == "partial" and savings["comparable_kwh"] == 1.0 and savings["excluded_kwh"] == 1.0
    assert savings["excluded_reasons"] == {"reference_day_not_held": 1.0} and savings["excluded_days"] == ["2026-09-21"]
    assert close(savings["actual_cost"], 0.10 * world.fx(D22)) and savings["actual_cost"] < whole["amount"]
    only_missing = world.history([world.session("b", at(D21, 3), [world.slice(at(D21, 3), 1, 1.0, 0.10)])], D21)
    block = only_missing["window_spot_cost"]["savings"]
    assert block["state"] == "none" and block["amount"] is None and block["percentage"] is None
    assert block["excluded_kwh"] == 1.0 and only_missing["window_spot_cost"]["amount"] is not None


def test_a_partial_held_day_is_not_a_reference(world, repository) -> None:  # noqa: F811
    hold(repository, document(D24, res=15, count=40))
    session = world.session("a", at(D24, 3), [world.slice(at(D24, 3), 1, 1.0, 0.10)])
    block = world.history([session], D24)["window_spot_cost"]["savings"]
    assert block["amount"] is None and block["excluded_kwh"] == 1.0
    assert list(block["excluded_reasons"]) in (["reference_day_partial"], ["reference_day_not_held"])


def test_unplaced_and_receipt_only_energy_is_never_compared(world) -> None:
    session = world.session("a", at(D22, 2), [world.slice(at(D22, 2), 1, 1.0, 0.10)])
    session = replace(session, energy_kwh=3.0)  # 2 kWh with no price slice
    block = world.history([session], D22)["window_spot_cost"]
    assert block["savings"]["comparable_kwh"] == 1.0 and block["unpriced_kwh"] == 2.0
    assert block["savings"]["unpriced_kwh"] == 2.0 and block["savings"]["state"] == "partial"


# ---- currency, source, fees -------------------------------------------------------------------------------------

def test_currencies_are_never_added_and_the_excluded_one_is_reported(world) -> None:
    sek = world.session("s", at(D22, 2), [world.slice(at(D22, 2), 1, 1.0, 0.10)])
    eur = world.session("e", at(D22, 8), [world.slice(at(D22, 8), 1, 2.0, 0.10, currency="EUR")], currency="EUR")
    newest_eur = world.history([sek, eur], D22)["window_spot_cost"]
    assert newest_eur["currency"] == "EUR" and newest_eur["savings"]["currency"] == "EUR"
    assert newest_eur["savings"]["state"] == "none"  # a SEK price area cannot reference euro-priced energy
    assert newest_eur["savings"]["excluded_reasons"] == {"reference_currency_mismatch": 2.0}
    assert newest_eur["savings"]["currency_exclusions"]["currencies"] == {"SEK": 1.0}
    sek_late = world.session("s2", at(D22, 12), [world.slice(at(D22, 12), 1, 1.0, 0.10)])
    newest_sek = world.history([eur, sek_late], D22)["window_spot_cost"]["savings"]
    assert newest_sek["currency"] == "SEK" and newest_sek["comparable_kwh"] == 1.0
    assert newest_sek["currency_exclusions"]["currencies"] == {"EUR": 2.0}


def test_retained_price_source_must_match_the_held_reference_source(world) -> None:
    start = at(D22, 10)
    row = replace(world.session("r", start, []), energy_kwh=1.0)
    fx = world.fx(D22)
    fx_date = world.repository.day_snapshot(AREA, D22).document.fx_date

    def blocks(source: str) -> dict[str, Any]:
        retained = [RetainedPrice(start, start + timedelta(hours=1), 0.10, fx, fx_date, AREA, "SEK", source)]
        spot = session_spot(row, spans=[PlacedSpan(start, start + timedelta(hours=1), 1.0, source)], retained=retained)
        allocation = SpotAllocation([spot], STOCKHOLM, DayAverageReference(world.repository, STOCKHOLM))
        return allocation.delivery_day(D22)["SEK"]

    other = blocks("elsewhere")
    assert other.comparable_kwh == 0.0 and other.excluded_reasons == {"price_source_mismatch": 1.0}
    same = blocks("stub")
    assert same.comparable_kwh == 1.0 and same.reference_sources == {"stub"}


def test_fees_do_not_change_the_savings_and_legacy_fields_are_untouched(world) -> None:
    session = world.session("a", at(D22, 2), [world.slice(at(D22, 2), 1, 1.0, 0.10)])
    fees = FiscalChoice(vat_enabled=True, vat_percent=25.5, transfer_enabled=True, transfer_minor_per_kwh=7.0)
    plain = world.history([session.priced(FiscalChoice())], D22)["window_spot_cost"]["savings"]
    fiscal = world.history([session.priced(fees)], D22)["window_spot_cost"]["savings"]
    assert plain == fiscal
    payload = world.month([session])
    without = api.sessions_payload(
        (session,), None, charger_id="c", zone=STOCKHOLM, now=NOW, limit=20, month="2026-09")
    for key in ("this_month", "months", "days", "month_summary", "month_days", "sessions"):
        assert payload[key] == without[key]
    for row in payload["delivery_days"]:
        assert "savings" in row["spot_cost"]
    plain_days = [{k: v for k, v in row["spot_cost"].items() if k != "savings"} for row in payload["delivery_days"]]
    assert plain_days == [row["spot_cost"] for row in without["delivery_days"]]


# ---- day / month / history agreement ---------------------------------------------------------------------------

def test_day_month_and_history_agree_and_percentage_is_sum_over_sum(world) -> None:
    a = world.session("a", at(D22, 2), [world.slice(at(D22, 2), 1, 2.0, 0.10)])  # +50 % on day 22
    b = world.session("b", at(D23, 13), [world.slice(at(D23, 13), 1, 1.0, 0.25)])  # -66.67 % on day 23
    payload = world.month([a, b])
    days = {row["period"]: row["spot_cost"]["savings"] for row in payload["delivery_days"]}
    month = payload["delivery_month_summary"]["spot_cost"]["savings"]
    assert month["comparable_kwh"] == 3.0 and month["excluded_kwh"] == 0.0 and month["state"] == "complete"
    assert close(month["amount"], days["2026-09-22"]["amount"] + days["2026-09-23"]["amount"])
    assert close(month["reference_cost"], days["2026-09-22"]["reference_cost"] + days["2026-09-23"]["reference_cost"])
    assert month["percentage"] == round(month["amount"] / month["reference_cost"] * 100, 2)
    assert month["percentage"] != round((days["2026-09-22"]["percentage"] + days["2026-09-23"]["percentage"]) / 2, 2)
    month_days = {row["period"]: row["spot_cost"]["savings"] for row in payload["delivery_month_days"]}
    assert month_days["2026-09-22"]["amount"] == days["2026-09-22"]["amount"]
    for day, key in ((D22, "2026-09-22"), (D23, "2026-09-23")):
        history = world.history([a, b], day)["window_spot_cost"]["savings"]
        assert history == days[key]


def test_a_day_with_no_sessions_says_so_and_a_read_never_fetches(world) -> None:
    payload = world.month([])
    empty = payload["delivery_month_summary"]["spot_cost"]["savings"]
    assert empty["state"] == "no_sessions_recorded" and empty["amount"] is None and empty["comparable_kwh"] == 0.0
    # Without a repository the answer is an explained unknown, not zero.
    session = world.session("a", at(D22, 2), [world.slice(at(D22, 2), 1, 1.0, 0.10)])
    reference = DayAverageReference(None, STOCKHOLM)
    spot = session_spot(session)
    bucket = SpotAllocation([spot], STOCKHOLM, reference).delivery_day(D22)["SEK"]
    assert bucket.comparable_kwh == 0.0 and bucket.excluded_reasons == {"reference_prices_unavailable": 1.0}
