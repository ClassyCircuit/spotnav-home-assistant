"""Stage 7.4b: monthly price statistics, at the pure module boundary and through the registered command.

Pure half: `monthly_insights` with plain rows. Command half: `websocket_get_price_insights` (mode `monthly`) against a
real `PriceRepository` holding real day documents; every fetch/persist path is made to fail the test, so a read
that fetched, refreshed or wrote would be caught. Fixtures and helpers are the 7.4a ones.
"""

# ruff: noqa: F811  (fixtures imported from the 7.4a module are redefined as test arguments)

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.spotnav.api import price_insights as module
from custom_components.spotnav.pricing import price_insights as pure
from custom_components.spotnav.pricing.price_insights import DayInput, PriceRow
from custom_components.spotnav.pricing.price_repository import HISTORY_KEEP_DAYS

from .test_stage_74a_price_insights import (  # noqa: F401  (fixtures are used by name)
    AREA,
    LATER,
    Connection,
    document,
    hold,
    repository,
    world,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 1, tzinfo=UTC)
CODE = "spotnav_invalid_insight_request"


# ---------------------------------------------------------------- pure module


def _rows(start: datetime, spans: list[tuple[int, float]]) -> tuple[PriceRow, ...]:
    rows, cursor = [], start
    for minutes, price in spans:
        rows.append(PriceRow(cursor, cursor + timedelta(minutes=minutes), price))
        cursor += timedelta(minutes=minutes)
    return tuple(rows)


def _day(index: int, spans: list[tuple[int, float]] | None, *, hours: int = 24, **extra: Any) -> DayInput:
    start = T0 + timedelta(days=index)
    rows = None if spans is None else _rows(start, spans)
    return DayInput(start.date(), start, start + timedelta(hours=hours), rows, **extra)


def _month(days: list[DayInput], *, complete: bool = True) -> dict[str, Any]:
    return pure.monthly_insights(month="2026-08", days=tuple(days), days_in_month=31, calendar_complete=complete)


HALF = [(720, 10.0), (720, 20.0)]


def test_six_complete_days_is_unknown_with_coverage_and_seven_is_known() -> None:
    six = _month([_day(i, HALF) for i in range(6)])
    assert six["status"] == "unknown" and six["unknown_reason"] == "too_few_complete_days"
    assert six["statistics"] is None and six["comparable"]["meets_minimum"] is False
    assert six["days_complete"] == 6 and six["coverage"]["seconds_valid"] == 6 * 86400
    assert six["coverage"]["valid_ratio"] == 1.0
    seven = _month([_day(i, HALF) for i in range(7)])
    assert seven["status"] == "known" and seven["unknown_reason"] is None
    assert seven["comparable"]["meets_minimum"] is True


def test_weighted_statistics_and_the_lower_quantile_definition() -> None:
    stats = _month([_day(i, HALF) for i in range(7)])["statistics"]
    # Half the time at 10, half at 20: 50 % cumulative is reached at 10 (lower inverse CDF), 90 % only at 20.
    assert (stats["min"], stats["max"], stats["mean"]) == (10.0, 20.0, 15.0)
    assert (stats["p10"], stats["p50"], stats["p90"]) == (10.0, 10.0, 20.0)
    assert stats["population_seconds"] == 7 * 86400 and stats["negative_share"] == 0.0


def test_statistics_follow_time_not_interval_count() -> None:
    quarter = [(15, 30.0)] * 96  # 96 intervals, one day of time
    hourly = [(60, 10.0)] * 24
    stats = _month([_day(i, hourly) for i in range(6)] + [_day(6, quarter)])["statistics"]
    assert stats["mean"] == pytest.approx((6 * 10 + 30) / 7)
    assert (stats["p10"], stats["p50"], stats["p90"]) == (10.0, 10.0, 30.0)  # 6/7 of the time is at 10


def test_negative_share_counts_strictly_negative_time_not_zero() -> None:
    spans = [(360, -5.0), (360, 0.0), (720, 5.0)]
    stats = _month([_day(i, spans) for i in range(7)])["statistics"]
    assert stats["negative_share"] == 25.0 and stats["negative_seconds"] == 7 * 21600
    assert stats["min"] == -5.0 and stats["mean"] == pytest.approx(-5 * 0.25 + 5 * 0.5)
    assert (stats["p10"], stats["p50"], stats["p90"]) == (-5.0, 0.0, 5.0)


def test_partial_days_are_counted_but_never_enter_the_population() -> None:
    good = [_day(i, HALF) for i in range(7)]
    partial = _day(7, [(720, 1000.0)])  # half a day, absurd price
    answer = _month(good + [partial])
    assert answer["status"] == "known" and answer["statistics"]["max"] == 20.0
    assert (answer["days_expected"], answer["days_held"], answer["days_complete"], answer["days_partial"]) == (8, 8, 7, 1)
    assert answer["days_excluded"] == {"count": 1, "reasons": {"partial": 1}}
    coverage = answer["coverage"]
    assert coverage["seconds_valid"] == 7 * 86400 and coverage["seconds_partial"] == 43200
    assert coverage["seconds_expected"] == 8 * 86400
    assert coverage["valid_ratio"] == round(7 / 8, 6)


def test_exclusions_are_counted_by_reason_and_duplicates_are_not_double_counted() -> None:
    rows = _rows(T0, HALF)
    identical = DayInput(date(2026, 8, 1), T0, T0 + timedelta(hours=24), (rows[0], rows[0], rows[1]))
    others = [_day(i, HALF) for i in range(1, 7)]
    day = timedelta(hours=24)
    bad = [
        _day(8, None),
        _day(9, HALF, unusable="no_price_rate"),
        _day(10, [(720, 10.0), (720, float("nan"))]),
        DayInput(date(2026, 8, 12), T0, T0 + day,
                 (PriceRow(T0, T0 + day, 1.0), PriceRow(T0, T0 + timedelta(hours=12), 2.0))),
        DayInput(date(2026, 8, 13), T0, T0 + day,
                 (PriceRow(T0, T0 + timedelta(hours=20), 1.0), PriceRow(T0 + timedelta(hours=12), T0 + day, 2.0))),
    ]
    answer = _month([identical, *others, *bad])
    assert answer["days_complete"] == 7 and answer["coverage"]["seconds_valid"] == 7 * 86400
    assert answer["statistics"]["population_seconds"] == 7 * 86400
    assert answer["days_excluded"]["reasons"] == {
        "conflicting_duplicate": 1, "invalid_prices": 1, "no_price_rate": 1, "not_held": 1, "overlap": 1}
    assert answer["days_held"] == 11 and answer["days_partial"] == 0


def test_duplicate_calendar_days_are_refused_and_no_days_is_unknown_not_a_division() -> None:
    with pytest.raises(ValueError):
        _month([_day(0, HALF), _day(0, HALF)])
    empty = _month([], complete=False)
    assert empty["status"] == "unknown" and empty["unknown_reason"] == "no_completed_days"
    assert empty["days_expected"] == 0 and empty["coverage"]["valid_ratio"] is None
    assert empty["statistics"] is None and empty["as_of_day"] is None
    assert empty["scope"] == "completed_days_to_date"


def test_scope_and_calendar_complete_flag() -> None:
    days = [_day(i, HALF) for i in range(7)]
    past, now = _month(days, complete=True), _month(days, complete=False)
    assert (past["scope"], past["calendar_complete"]) == ("complete_calendar_month", True)
    assert (now["scope"], now["calendar_complete"], now["as_of_day"]) == ("completed_days_to_date", False, "2026-08-07")


def test_weighted_quantile_is_deterministic_and_exact_at_the_edges() -> None:
    prices, cumulative = (1.0, 2.0, 3.0), (10, 20, 100)
    assert pure.weighted_quantile(prices, cumulative, 10) == 1.0  # cumulative 10 reaches 10 % exactly
    assert pure.weighted_quantile(prices, cumulative, 11) == 2.0
    assert pure.weighted_quantile(prices, cumulative, 21) == 3.0
    assert pure.weighted_quantile(prices, cumulative, 100) == 3.0


# ------------------------------------------------------------ the command


def month_days(year: int, month: int) -> list[date]:
    day, out = date(year, month, 1), []
    while day.month == month:
        out.append(day)
        day += timedelta(days=1)
    return out


def hold_month(repository_: Any, year: int, month: int, *, last: int | None = None, **fields: Any) -> None:
    hold(repository_, *(document(day, **fields) for day in month_days(year, month)[:last]))


def ask(world_: SimpleNamespace, **fields: Any) -> Connection:
    connection = Connection()
    msg = {"id": 1, "type": "spotnav/get_price_insights", "api_version": 1, "charger_id": "c1", "mode": "monthly", **fields}
    module.websocket_get_price_insights(world_.hass, connection, msg)
    return connection


def answer_of(world_: SimpleNamespace, **fields: Any) -> dict[str, Any]:
    connection = ask(world_, **fields)
    assert connection.errors == [], connection.errors
    return connection.results[0]


def at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: moment)


def codes(connection: Connection) -> list[str]:
    return [code for code, _ in connection.errors]


def test_completed_past_month_through_the_command_reads_nothing_else(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 8, prices=[0.10] * 96)
    before = set(world.repository._days)  # noqa: SLF001
    calls: list[date] = []
    real = world.repository.day_snapshot

    def counting(area: str, day: date) -> Any:
        calls.append(day)
        return real(area, day)

    world.repository.day_snapshot = counting  # type: ignore[method-assign]
    answer = answer_of(world, month="2026-08")
    assert len(calls) == 31 and len(set(calls)) == 31  # one snapshot per distinct day, none re-read
    assert (answer["api_version"], answer["mode"], answer["area_id"], answer["zone"], answer["currency"]) == (
        1, "monthly", AREA, "Europe/Stockholm", "SEK")
    assert answer["basis"] == {"kind": "published_spot", "unit": "major_per_kwh", "currency": "SEK", "fees": "none"}
    assert (answer["month"], answer["scope"], answer["calendar_complete"]) == ("2026-08", "complete_calendar_month", True)
    assert (answer["days_expected"], answer["days_held"], answer["days_complete"], answer["days_partial"]) == (31, 31, 31, 0)
    assert answer["coverage"]["seconds_expected"] == 31 * 86400 == answer["coverage"]["seconds_valid"]
    stats = answer["statistics"]
    assert answer["status"] == "known" and stats["min"] == stats["max"] == stats["p50"] == pytest.approx(stats["mean"])
    assert stats["negative_share"] == 0.0 and stats["min"] > 0.10  # SEK per kWh: the day's own rate applied once
    assert (answer["window_from"], answer["window_to"]) == ("2026-08-01", "2026-08-31")
    assert answer["provenance"] == {"providers": [{"provider": "stub", "files": 31}]}
    assert answer["resolution_minutes"] == [15] and answer["comparable"]["meets_minimum"] is True
    assert set(world.repository._days) == before and world.repository._store.saves == 0  # noqa: SLF001
    assert "cheap" not in json.dumps(answer).lower()


def test_current_month_counts_completed_days_only_and_excludes_today_and_the_future(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 9, last=21, prices=[0.10] * 96)  # 09-01 .. 09-21
    hold(world.repository, document(date(2026, 9, 22), prices=[9.0] * 96), document(date(2026, 9, 23), prices=[9.0] * 96))
    for fields in ({}, {"month": "2026-09"}):
        answer = answer_of(world, **fields)
        assert (answer["month"], answer["scope"], answer["calendar_complete"]) == ("2026-09", "completed_days_to_date", False)
        assert (answer["days_expected"], answer["days_complete"], answer["as_of_day"]) == (21, 21, "2026-09-21")
        assert answer["days_in_month"] == 30 and answer["today"] == "2026-09-22"
        assert answer["coverage"]["seconds_expected"] == 21 * 86400
        assert answer["statistics"]["max"] < 2.0  # today's and tomorrow's 9.0 EUR (~100 SEK) never enter
        assert (answer["window_from"], answer["window_to"]) == ("2026-09-01", "2026-09-30")


def test_first_day_of_the_current_month_has_no_completed_day_and_is_unknown(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(monkeypatch, datetime(2026, 9, 30, 23, 0, tzinfo=UTC))  # 2026-10-01 01:00 in Stockholm
    answer = answer_of(world)
    assert answer["month"] == "2026-10" and answer["days_expected"] == 0 and answer["as_of_day"] is None
    assert answer["status"] == "unknown" and answer["unknown_reason"] == "no_completed_days"
    assert answer["coverage"] == {"seconds_expected": 0.0, "seconds_valid": 0.0, "seconds_partial": 0.0, "valid_ratio": None}
    assert answer["statistics"] is None


def test_minimum_is_seven_fully_held_days_six_is_unknown_with_coverage(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 8, last=6)
    six = answer_of(world, month="2026-08")
    assert six["status"] == "unknown" and six["unknown_reason"] == "too_few_complete_days" and six["statistics"] is None
    assert six["days_complete"] == 6 and six["days_expected"] == 31 and six["days_excluded"]["reasons"] == {"not_held": 25}
    assert six["coverage"]["seconds_valid"] == 6 * 86400 and six["comparable"]["meets_minimum"] is False
    hold_month(world.repository, 2026, 8, last=7)
    assert answer_of(world, month="2026-08")["status"] == "known"


def test_partially_held_month_with_partial_days_reports_them_apart(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 8, last=10, prices=[0.10] * 96)
    hold(world.repository, document(date(2026, 8, 3), count=40), document(date(2026, 8, 4), count=95), fetched=LATER)
    answer = answer_of(world, month="2026-08")
    assert answer["days_held"] == 10 and answer["days_complete"] == 8 and answer["days_partial"] == 2
    assert answer["days_excluded"]["reasons"] == {"not_held": 21, "partial": 2}
    # 40 + 95 quarter-hours were published on the two partial days: coverage, not population.
    assert answer["coverage"]["seconds_partial"] == (40 + 95) * 900
    assert answer["coverage"]["seconds_valid"] == 8 * 86400 == answer["statistics"]["population_seconds"]


def test_a_day_without_a_usable_rate_is_excluded_and_counted_never_converted(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 8, last=9)
    hold(world.repository, document(date(2026, 8, 5), fx=False), fetched=LATER)
    answer = answer_of(world, month="2026-08")
    assert answer["days_held"] == 9 and answer["days_complete"] == 8
    assert answer["days_excluded"]["reasons"]["no_price_rate"] == 1


def test_negative_prices_and_mixed_resolutions_are_weighted_by_time(world: SimpleNamespace) -> None:
    quarter = [-0.02] * 24 + [0.10] * 72  # 6 h negative of 24 h
    hourly = [-0.02] * 6 + [0.10] * 18
    hold(world.repository, *(
        document(day, prices=quarter if day.day % 2 else hourly, res=15 if day.day % 2 else 60)
        for day in month_days(2026, 8)
    ))
    answer = answer_of(world, month="2026-08")
    assert answer["resolution_minutes"] == [15, 60]
    stats = answer["statistics"]
    assert stats["negative_share"] == 25.0 and stats["min"] < 0 < stats["p90"] and stats["p10"] == stats["min"]
    assert stats["negative_seconds"] == 31 * 6 * 3600


def test_dst_months_use_real_23_and_25_hour_days(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    at(monkeypatch, datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    hold_month(world.repository, 2026, 10)  # 2026-10-25 has 100 quarter-hours
    october = answer_of(world, month="2026-10")
    assert october["coverage"]["seconds_expected"] == 31 * 86400 + 3600 == october["coverage"]["seconds_valid"]
    assert october["days_complete"] == 31
    hold(world.repository, document(date(2026, 10, 25), prices=[0.05] * 96), fetched=LATER)  # 96 is short of 25 h
    short = answer_of(world, month="2026-10")
    assert short["days_complete"] == 30 and short["days_partial"] == 1

    at(monkeypatch, datetime(2027, 4, 10, 12, 0, tzinfo=UTC))
    hold_month(world.repository, 2027, 3)  # 2027-03-28 is 23 hours: 92 quarter-hours
    march = answer_of(world, month="2027-03")
    assert march["coverage"]["seconds_expected"] == 31 * 86400 - 3600 == march["coverage"]["seconds_valid"]
    assert march["days_complete"] == 31


def test_riga_dst_days_in_its_own_zone(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    riga = ZoneInfo("Europe/Riga")
    world.settings.area_id = "LV"
    at(monkeypatch, datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    days: dict[str, Any] = {}
    for day in month_days(2026, 10):
        body = document(day, area="LV")
        start = datetime(day.year, day.month, day.day, tzinfo=riga)
        nxt = day + timedelta(days=1)
        hours = (datetime(nxt.year, nxt.month, nxt.day, tzinfo=riga).astimezone(UTC) - start.astimezone(UTC)).total_seconds() // 3600
        body["start"], body["tz"] = start.isoformat(), "Europe/Riga"
        body["prices"] = [0.10] * int(hours * 4)
        days[f"LV|Europe/Riga|{day.isoformat()}"] = {
            "document": body, "fetched_at": "2026-11-01T00:00:00+00:00", "provider": "stub"}
    world.repository._adopt({"schema": 2, "days": days})  # noqa: SLF001
    answer = answer_of(world, month="2026-10")
    assert (answer["zone"], answer["currency"], answer["area_id"]) == ("Europe/Riga", "EUR", "LV")
    assert answer["days_complete"] == 31 and answer["coverage"]["seconds_expected"] == 31 * 86400 + 3600
    assert answer["statistics"]["mean"] == pytest.approx(0.10)


def test_an_old_complete_month_is_not_stale_for_its_age(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    at(monkeypatch, datetime(2027, 4, 10, 12, 0, tzinfo=UTC))
    hold_month(world.repository, 2026, 5, prices=[0.10] * 96)  # about 11 months old
    answer = answer_of(world, month="2026-05")
    assert answer["status"] == "known" and answer["days_complete"] == 31


def test_an_area_change_reads_only_that_areas_days(world: SimpleNamespace) -> None:
    hold_month(world.repository, 2026, 8)
    assert answer_of(world, month="2026-08")["days_complete"] == 31
    world.settings.area_id = "SE3"
    other = answer_of(world, month="2026-08")
    assert other["area_id"] == "SE3" and other["days_held"] == 0 and other["status"] == "unknown"
    assert other["days_excluded"]["reasons"] == {"not_held": 31} and other["provenance"] == {"providers": []}


@pytest.mark.parametrize(
    "bad",
    ["2026-9", "2026-13", "2026-00", "2026-8-1", "2026-08-01", "202608", " 2026-08", "2026-08\n", "2026/08", "../2026-08",
     "２０２６-０８", "0000-01", "", None, 202608, 8, True, 2026.08, ["2026-08"], {"month": "2026-08"}],
)
def test_invalid_month_values_are_refused(world: SimpleNamespace, bad: Any) -> None:
    assert codes(ask(world, month=bad)) == [CODE]


def test_future_and_out_of_retention_months_are_refused_and_the_bound_is_inclusive(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert codes(ask(world, month="2026-10")) == [CODE]
    assert codes(ask(world, month="2099-01")) == [CODE]
    today = date(2025, 12, 1) + timedelta(days=HISTORY_KEEP_DAYS)  # the 1st of 2025-12 is exactly at the bound
    at(monkeypatch, datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC))
    assert ask(world, month="2025-12").errors == []
    assert codes(ask(world, month="2025-11")) == [CODE]


def test_mode_specific_parameters_are_refused_in_the_other_mode(world: SimpleNamespace) -> None:
    assert codes(ask(world, duration_minutes=60)) == [CODE]
    live = Connection()
    module.websocket_get_price_insights(
        world.hass, live, {"id": 1, "type": "x", "api_version": 1, "charger_id": "c1", "mode": "live", "month": "2026-08"})
    assert codes(live) == [CODE]
    for mode in (None, "", "Monthly", "month", 7):
        assert codes(ask(world, mode=mode)) == [CODE]


def test_same_command_registered_once_live_is_unaffected_and_refusals_are_shared(world: SimpleNamespace) -> None:
    text = (Path(module.__file__).parent.parent / "__init__.py").read_text(encoding="utf-8")
    assert text.count("async_setup_price_insights_api(hass)") == 1 and "get_price_insights_monthly" not in text
    hold(world.repository, document(date(2026, 9, 22)), document(date(2026, 9, 23)))
    live = Connection()
    module.websocket_get_price_insights(
        world.hass, live, {"id": 1, "type": "x", "api_version": 1, "charger_id": "c1", "mode": "live"})
    assert live.errors == [] and live.results[0]["mode"] == "live" and "month" not in live.results[0]
    assert ask(world, api_version=2).errors[0][0] == "spotnav_unsupported_api_version"
    assert ask(world, charger_id="nope").errors[0][0] == "spotnav_unknown_charger"
    world.settings.area_id = None
    assert ask(world, month="2026-08").errors[0][0] == "spotnav_no_price_area"
    world.settings.area_id = "ZZ-NOWHERE"
    assert ask(world, month="2026-08").errors[0][0] == "spotnav_unknown_price_area"
