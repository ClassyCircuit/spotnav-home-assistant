"""Stage 7.4a: live price insights, at the pure module boundary and through the registered command.

The pure half calls `pricing/price_insights.py` with plain rows (no Home Assistant, no clock). The command half
runs `websocket_get_price_insights` against a real `PriceRepository` holding real day documents (hass-free: the
store is a double and every fetch path is made to fail the test), with a fake connection.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.spotnav.api import price_insights as module
from custom_components.spotnav.pricing import price_insights as pure
from custom_components.spotnav.pricing.price_insights import DayInput, PriceRow
from custom_components.spotnav.pricing.price_repository import PriceRepository
from custom_components.spotnav.runtime import DATA_KEY

from .relay import BUNDLED, STOCKHOLM, Clock, StoreDouble, day_body

UTC = timezone.utc
T0 = datetime(2026, 9, 22, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------- pure module


def _rows(start: datetime, spans: list[tuple[int, float]]) -> tuple[PriceRow, ...]:
    rows, cursor = [], start
    for minutes, price in spans:
        rows.append(PriceRow(cursor, cursor + timedelta(minutes=minutes), price))
        cursor += timedelta(minutes=minutes)
    return tuple(rows)


def _day(index: int, spans: list[tuple[int, float]] | None, *, hours: int = 24, **extra: Any) -> DayInput:
    start = T0 + timedelta(days=index)
    return DayInput(
        (start).date(), start, start + timedelta(hours=hours),
        None if spans is None else _rows(start, spans), **extra,
    )


def _baseline(days: list[DayInput]) -> pure.Baseline:
    return pure.build_baseline(tuple(days), window_from=date(2026, 9, 1), window_to=date(2026, 9, 30))


HALF = [(720, 10.0), (720, 20.0)]


def test_below_seven_used_days_is_unknown_and_seven_is_known() -> None:
    six = _baseline([_day(i, HALF) for i in range(6)])
    seven = _baseline([_day(i, HALF) for i in range(7)])
    assert six.summary["status"] == "unknown" and six.summary["unknown_reason"] == "baseline_too_short"
    assert six.percentile(10.0)["status"] == "unknown"
    assert seven.summary["status"] == "known" and seven.summary["days_used"] == 7


def test_percentile_is_exact_by_seconds_with_half_of_the_ties() -> None:
    base = _baseline([_day(i, HALF) for i in range(7)])
    assert base.percentile(10.0)["percentile"] == 25.0  # nothing cheaper, half of the 50 % equal
    assert base.percentile(20.0)["percentile"] == 75.0
    assert base.percentile(15.0)["percentile"] == 50.0
    assert base.percentile(5.0)["percentile"] == 0.0 and base.percentile(25.0)["percentile"] == 100.0
    assert base.percentile(10.0)["baseline_seconds"] == 7 * 86400


def test_resolutions_weigh_by_time_not_by_interval_count() -> None:
    quarter = [(15, 30.0)] * 96  # 96 votes by count, one day by time
    hourly = [(60, 10.0)] * 24
    base = _baseline([_day(i, hourly) for i in range(6)] + [_day(6, quarter)])
    assert base.percentile(20.0)["percentile"] == round(100 * 6 / 7, 2)
    assert base.summary["resolution_minutes"] == [15, 60]


def test_excluded_days_are_counted_by_reason_and_never_used() -> None:
    good = [_day(i, HALF) for i in range(7)]
    bad = [
        _day(7, None),  # not held
        _day(8, [(720, 10.0), (660, 20.0)]),  # an hour short
        _day(9, [(720, 10.0), (720, math.nan)]),
        _day(10, [(720, 10.0), (720, 20.0), (60, 20.0)]),  # runs beyond the day: partial
        _day(11, HALF, unusable="no_price_rate"),
        DayInput(date(2026, 10, 3), T0, T0 + timedelta(hours=24),
                 (PriceRow(T0, T0 + timedelta(hours=24), 10.0), PriceRow(T0, T0 + timedelta(hours=12), 11.0))),
        DayInput(date(2026, 10, 4), T0, T0 + timedelta(hours=24),
                 (PriceRow(T0, T0 + timedelta(hours=20), 10.0), PriceRow(T0 + timedelta(hours=12), T0 + timedelta(hours=24), 11.0))),
    ]
    summary = _baseline(good + bad).summary
    assert (summary["days_expected"], summary["days_held"], summary["days_used"]) == (14, 13, 7)
    assert summary["days_excluded"] == {
        "count": 7,
        "reasons": {"conflicting_duplicate": 1, "invalid_prices": 1, "no_price_rate": 1, "not_held": 1,
                    "overlap": 1, "partial": 2},
    }
    assert summary["seconds_used"] == 7 * 86400 and summary["seconds_expected"] == 14 * 86400


def test_an_identical_duplicate_is_dropped_once_and_the_day_still_counts() -> None:
    start = T0
    rows = _rows(start, HALF)
    duplicated = DayInput(date(2026, 9, 22), start, start + timedelta(hours=24), (rows[0], rows[0], rows[1]))
    base = _baseline([duplicated] + [_day(i, HALF) for i in range(1, 7)])
    assert base.summary["days_used"] == 7 and base.summary["seconds_used"] == 7 * 86400


def test_negative_prices_rank_normally() -> None:
    base = _baseline([_day(i, [(720, -5.0), (720, 5.0)]) for i in range(7)])
    assert base.percentile(-5.0)["percentile"] == 25.0 and base.percentile(0.0)["percentile"] == 50.0


def test_dst_days_are_full_only_at_their_real_length() -> None:
    zone = ZoneInfo("Europe/Stockholm")

    def local_day(day: date, quarters: int) -> DayInput:
        start = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
        end = datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(days=1)
        end = datetime(end.year, end.month, end.day, tzinfo=zone).astimezone(UTC)
        return DayInput(day, start, end, _rows(start, [(15, 1.0 + index % 5) for index in range(quarters)]))

    short = local_day(date(2027, 3, 28), 92)  # 23 h
    long = local_day(date(2026, 10, 25), 100)  # 25 h
    assert (short.span_end - short.span_start, long.span_end - long.span_start) == (timedelta(hours=23), timedelta(hours=25))
    ordinary = [local_day(date(2026, 9, 1) + timedelta(days=i), 96) for i in range(5)]
    base = _baseline([short, long, *ordinary])
    assert base.summary["days_used"] == 7
    assert base.summary["seconds_used"] == 5 * 86400 + 23 * 3600 + 25 * 3600
    # A fixed 96/100-row assumption is wrong on these days and is refused, not accepted.
    wrong = _baseline([local_day(date(2027, 3, 28), 96), local_day(date(2026, 10, 25), 96), *ordinary])
    assert wrong.summary["days_excluded"]["reasons"] == {"partial": 2}


NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def _live(spans: list[tuple[int, float]], *, start: datetime = NOW, state: str = "ready") -> tuple[DayInput, ...]:
    return (DayInput(NOW.date(), start, start + timedelta(hours=24), _rows(start, spans), state=state),)


def _insights(live: tuple[DayInput, ...], *, minutes: int = 60, now: datetime = NOW, baseline: bool = True) -> dict[str, Any]:
    days = tuple(_day(i, HALF) for i in range(10 if baseline else 3))
    return pure.live_insights(now=now, today="2026-09-22", window_minutes=minutes, baseline_days=days,
                              live_days=live, window_from=date(2026, 9, 1), window_to=date(2026, 9, 21))


def test_current_interval_and_its_percentile_against_the_baseline() -> None:
    answer = _insights(_live([(60, 20.0), (60, 5.0)]))
    current = answer["current"]
    assert current["status"] == "known" and current["interval"]["price"] == 20.0
    assert current["interval"]["elapsed_seconds"] == 0.0
    assert current["comparison"]["percentile"] == 75.0
    assert "cheap" not in json.dumps(answer).lower().replace("cheaper_seconds", "").replace("cheapest_window", "")


def test_a_missing_baseline_never_blocks_the_window_or_the_current_price() -> None:
    answer = _insights(_live([(60, 20.0), (60, 5.0), (60, 7.0)]), baseline=False)
    assert answer["baseline"]["status"] == "unknown"
    assert answer["current"]["status"] == "known"
    assert answer["current"]["comparison"] == {"status": "unknown", "unknown_reason": "baseline_unknown", "percentile": None}
    window = answer["cheapest_window"]
    assert window["status"] == "known" and window["start"] == "2026-09-22T11:00:00+00:00"
    assert window["mean_price"] == 5.0 and window["comparison"]["status"] == "unknown"
    assert answer["unknown_reason"] is None


def test_window_start_and_end_boundary_candidates_find_the_exact_optimum() -> None:
    # 0-45 min p5, 45-90 min p1, 90-120 min p9: the best 60 minutes starts at 30 = (the 90-minute boundary) - 60,
    # which is no interval start; starting at an interval start alone would give 3, not 2.
    answer = _insights(_live([(45, 5.0), (45, 1.0), (30, 9.0)]))
    window = answer["cheapest_window"]
    assert window["start"] == "2026-09-22T10:30:00+00:00" and window["end"] == "2026-09-22T11:30:00+00:00"
    assert window["mean_price"] == pytest.approx(2.0)


def test_ties_go_to_the_earliest_window() -> None:
    answer = _insights(_live([(60, 3.0), (60, 9.0), (60, 3.0)]))
    assert answer["cheapest_window"]["start"] == "2026-09-22T10:00:00+00:00"


def test_the_current_interval_counts_only_from_now() -> None:
    now = NOW + timedelta(minutes=30)
    answer = _insights(_live([(60, 1.0), (60, 5.0)]), now=now)
    window = answer["cheapest_window"]
    # [10:30, 11:30] = 30 min at 1 and 30 min at 5.
    assert window["start"] == "2026-09-22T10:30:00+00:00" and window["mean_price"] == pytest.approx(3.0)
    assert answer["current"]["interval"]["elapsed_seconds"] == 1800.0
    # A shorter window than the rest of the current interval uses only what is left of it.
    half = _insights(_live([(60, 1.0), (60, 5.0)]), now=now, minutes=30)["cheapest_window"]
    assert half["start"] == "2026-09-22T10:30:00+00:00" and half["mean_price"] == 1.0


def test_gap_and_published_end_refuse_a_window_and_a_run_after_a_gap_is_still_used() -> None:
    start = NOW
    rows = _rows(start, [(60, 4.0)]) + _rows(start + timedelta(minutes=90), [(60, 2.0)])
    live = (DayInput(NOW.date(), start, start + timedelta(hours=24), rows, state="ready"),)
    assert _insights(live, minutes=90)["cheapest_window"]["unknown_reason"] == "no_contiguous_window"
    two = _insights(live, minutes=60)["cheapest_window"]
    assert two["start"] == "2026-09-22T11:30:00+00:00" and two["horizon"]["runs"] == 2
    assert _insights(_live([(60, 1.0)]), minutes=120)["cheapest_window"]["unknown_reason"] == "no_contiguous_window"


def test_nothing_published_ahead_is_unknown_not_zero() -> None:
    answer = _insights(_live([(60, 1.0)]), now=NOW + timedelta(hours=3))
    assert answer["current"]["status"] == "unknown" and answer["current"]["unknown_reason"] == "no_current_interval"
    assert answer["current"]["interval"] is None and answer["cheapest_window"]["unknown_reason"] == "no_future_prices"
    assert answer["unknown_reason"] == "no_current_interval"


def test_a_stale_current_day_is_unknown_but_valid_future_slots_still_answer() -> None:
    tomorrow_start = NOW + timedelta(hours=14)
    live = (
        DayInput(NOW.date(), NOW - timedelta(hours=10), tomorrow_start, _rows(NOW - timedelta(hours=10), [(1440, 1.0)]),
                 state="stale"),
        DayInput(date(2026, 9, 23), tomorrow_start, tomorrow_start + timedelta(hours=24),
                 _rows(tomorrow_start, [(60, 8.0), (60, 2.0)]), state="ready"),
    )
    answer = _insights(live)
    assert answer["current"]["status"] == "unknown" and answer["current"]["unknown_reason"] == "day_stale"
    window = answer["cheapest_window"]
    assert window["status"] == "known" and window["start"] == "2026-09-23T01:00:00+00:00"
    assert answer["live_days_skipped"] == {"2026-09-22": "day_stale"}
    assert answer["unknown_reason"] is None


def test_conflicting_live_rows_leave_that_day_out_and_unknown() -> None:
    rows = _rows(NOW, [(60, 1.0)]) + (PriceRow(NOW, NOW + timedelta(hours=1), 2.0),)
    live = (DayInput(NOW.date(), NOW, NOW + timedelta(hours=24), rows, state="ready"),)
    answer = _insights(live)
    assert answer["current"]["unknown_reason"] == "conflicting_duplicate"
    assert answer["cheapest_window"]["unknown_reason"] == "conflicting_duplicate"


def test_mixed_resolutions_in_the_live_timeline_are_not_resampled() -> None:
    answer = _insights(_live([(60, 6.0), (15, 2.0), (15, 4.0), (30, 3.0), (60, 9.0)]), minutes=60)
    assert answer["resolution_minutes"]["live"] == [15, 30, 60]
    window = answer["cheapest_window"]
    assert window["start"] == "2026-09-22T11:00:00+00:00"
    assert window["mean_price"] == pytest.approx((15 * 2 + 15 * 4 + 30 * 3) / 60)


def test_a_negative_window_wins_and_has_a_percentile() -> None:
    answer = _insights(_live([(60, 4.0), (60, -3.0), (60, 4.0)]))
    assert answer["cheapest_window"]["mean_price"] == -3.0
    assert answer["cheapest_window"]["comparison"]["percentile"] == 0.0


# ------------------------------------------------------------ the command

AREA = "SE4"
TODAY = date(2026, 9, 22)
LATER = "2026-09-22T06:00:00+00:00"
CLOCK_NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)  # 12:00 in Stockholm


def document(day: date, *, area: str = AREA, prices: list[float] | None = None, res: int = 15,
             count: int | None = None, fx: bool = True) -> dict[str, Any]:
    body = json.loads(day_body(area, day))
    start = datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM)
    end = datetime(*(start + timedelta(days=1)).timetuple()[:3], tzinfo=STOCKHOLM)
    hours = int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() // 3600)
    body["fx_date"] = (day - timedelta(days=1)).isoformat()
    body["res"] = res
    full = hours * (60 // res)
    body["prices"] = prices if prices is not None else [round(0.05 + 0.001 * (i % 7), 5) for i in range(full)]
    if count is not None:
        body["prices"] = body["prices"][:count]
    if not fx:
        body["fx"], body["fx_date"] = {}, None
        body.pop("fx_date")
        body.pop("fx_src", None)
    return body


def hold(repository: PriceRepository, *documents: dict[str, Any], fetched: str = "2026-09-22T05:00:00+00:00") -> None:
    """Hold these documents; the repository keeps the newer fetch of a day, so a replacement says `fetched`."""
    days = {
        f"{item['area']}|Europe/Stockholm|{item['date']}": {
            "document": item, "fetched_at": fetched, "provider": "stub"
        }
        for item in documents
    }
    repository._adopt({"schema": 2, "days": days})  # noqa: SLF001


def hold_baseline(repository: PriceRepository, days: int = 30, **fields: Any) -> None:
    hold(repository, *(document(TODAY - timedelta(days=offset), **fields) for offset in range(1, days + 1)))


class Connection:
    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[tuple[str, str]] = []

    def send_result(self, _id: int, answer: Any) -> None:
        self.results.append(answer)

    def send_error(self, _id: int, code: str, message: str) -> None:
        self.errors.append((code, message))


@pytest.fixture
def repository() -> PriceRepository:
    return PriceRepository(None, store=StoreDouble(), bundled=BUNDLED, now=Clock(CLOCK_NOW))  # type: ignore[arg-type]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, repository: PriceRepository) -> SimpleNamespace:
    settings = SimpleNamespace(area_id=AREA)
    writes: list[str] = []
    store = SimpleNamespace(settings=lambda _id: settings)
    hass = SimpleNamespace(data={DATA_KEY: SimpleNamespace(auto_store=store, price_repository=repository)})
    monkeypatch.setattr(module, "effective_settings", lambda _h, _c, current: current)
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: CLOCK_NOW)
    monkeypatch.setattr(module, "lookup_charger", lambda _h, cid: (SimpleNamespace(entry_id=cid), None)
                        if cid == "c1" else (None, "spotnav_unknown_charger"))

    def forbidden(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a read must never fetch, refresh or write")

    for name in ("async_get_day", "async_get_file", "async_get_archive_day", "async_fetch_history",
                 "async_persist_history", "async_get_profile", "_persist"):
        monkeypatch.setattr(repository, name, forbidden)
    return SimpleNamespace(hass=hass, settings=settings, repository=repository, writes=writes)


def ask(world: SimpleNamespace, **fields: Any) -> Connection:
    connection = Connection()
    msg = {"id": 1, "type": "spotnav/get_price_insights", "api_version": 1, "charger_id": "c1", "mode": "live", **fields}
    module.websocket_get_price_insights(world.hass, connection, msg)
    return connection


def answer_of(world: SimpleNamespace, **fields: Any) -> dict[str, Any]:
    connection = ask(world, **fields)
    assert connection.errors == [], connection.errors
    return connection.results[0]


def test_full_answer_from_held_days_without_any_fetch_or_write(world: SimpleNamespace) -> None:
    hold_baseline(world.repository)
    hold(world.repository, document(TODAY, prices=[0.10] * 96), document(date(2026, 9, 23), prices=[0.05] * 96))
    before = set(world.repository._days)  # noqa: SLF001
    answer = answer_of(world)
    assert (answer["api_version"], answer["mode"], answer["area_id"], answer["zone"], answer["currency"]) == (
        1, "live", AREA, "Europe/Stockholm", "SEK")
    assert answer["basis"] == {"kind": "published_spot", "unit": "major_per_kwh", "currency": "SEK", "fees": "none"}
    baseline = answer["baseline"]
    assert (baseline["days_expected"], baseline["days_held"], baseline["days_used"]) == (30, 30, 30)
    assert (baseline["window_from"], baseline["window_to"]) == ("2026-08-23", "2026-09-21")
    assert baseline["days_excluded"] == {"count": 0, "reasons": {}}
    current = answer["current"]
    assert current["status"] == "known" and current["interval"]["start"] == "2026-09-22T10:00:00+00:00"
    assert current["interval"]["start_local"] == "2026-09-22T12:00:00+02:00"
    assert current["interval"]["price"] > 0.10  # SEK per kWh: the day's own rate applied once
    assert current["comparison"]["status"] == "known"
    window = answer["cheapest_window"]
    assert window["status"] == "known" and window["start"] == "2026-09-22T22:00:00+00:00"  # tomorrow's 00:00 local
    assert window["start_local"].endswith("+02:00")
    assert answer["now"] == "2026-09-22T10:00:00+00:00" and answer["now_local"] == "2026-09-22T12:00:00+02:00"
    assert answer["provenance"]["baseline_providers"] == [{"provider": "stub", "files": 30}]
    assert [row["day"] for row in answer["provenance"]["live"]] == ["2026-09-22", "2026-09-23"]
    assert "unknown_reason" in answer and answer["assumptions"] == list(pure.ASSUMPTIONS)
    assert set(world.repository._days) == before  # noqa: SLF001
    assert world.repository._store.saves == 0  # noqa: SLF001


def test_default_and_explicit_durations_and_invalid_ones(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    assert answer_of(world)["window_minutes"] == 60
    assert answer_of(world, duration_minutes=15)["cheapest_window"]["duration_minutes"] == 15
    assert answer_of(world, duration_minutes=720)["window_minutes"] == 720
    for bad in (0, 14, 20, 735, -15, 15.0, "60", True, None):
        connection = ask(world, duration_minutes=bad)
        assert [code for code, _ in connection.errors] == ["spotnav_invalid_insight_request"], bad
    assert [code for code, _ in ask(world, mode="yearly").errors] == ["spotnav_invalid_insight_request"]
    assert ask(world, mode=None).errors[0][0] == "spotnav_invalid_insight_request"


def test_refusals_for_version_charger_and_area(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Connection()
    module.websocket_get_price_insights(world.hass, connection, {"id": 1, "type": "x", "api_version": 2, "charger_id": "c1",
                                                                  "mode": "live"})
    assert connection.errors[0][0] == "spotnav_unsupported_api_version"
    assert ask(world, charger_id="nope").errors[0][0] == "spotnav_unknown_charger"
    assert ask(world, charger_id=None).errors[0][0] == "spotnav_unknown_charger"
    world.settings.area_id = None
    assert ask(world).errors[0][0] == "spotnav_no_price_area"
    world.settings.area_id = "ZZ-NOWHERE"
    assert ask(world).errors[0][0] == "spotnav_unknown_price_area"


def test_signed_in_user_needs_no_admin_and_the_handler_reads_nothing_else(world: SimpleNamespace) -> None:
    connection = SimpleNamespace(results=[], errors=[], user=SimpleNamespace(is_admin=False))
    connection.send_result = lambda _i, a: connection.results.append(a)
    connection.send_error = lambda _i, c, m: connection.errors.append(c)
    module.websocket_get_price_insights(world.hass, connection,
                                        {"id": 1, "type": "x", "api_version": 1, "charger_id": "c1", "mode": "live"})
    assert connection.errors == [] and len(connection.results) == 1
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "is_admin" not in text and ".set(" not in text and "async_" not in text.replace("async_setup", "").replace(
        "async_register_command", "")


def test_command_is_registered_once_at_setup() -> None:
    text = (Path(module.__file__).parent.parent / "__init__.py").read_text(encoding="utf-8")
    assert text.count("async_setup_price_insights_api(hass)") == 1


def test_six_baseline_days_is_unknown_and_seven_known_but_the_window_always_answers(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    hold_baseline(world.repository, 6)
    six = answer_of(world)
    assert six["baseline"]["days_used"] == 6 and six["baseline"]["status"] == "unknown"
    assert six["baseline"]["days_excluded"]["reasons"] == {"not_held": 24}
    assert six["current"]["status"] == "known" and six["current"]["comparison"]["status"] == "unknown"
    assert six["cheapest_window"]["status"] == "known" and six["cheapest_window"]["comparison"]["status"] == "unknown"
    hold_baseline(world.repository, 7)
    assert answer_of(world)["baseline"]["status"] == "known"


def test_partial_baseline_day_is_excluded_and_counted(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    hold_baseline(world.repository, 8)
    hold(world.repository, document(TODAY - timedelta(days=3), count=40), fetched=LATER)
    baseline = answer_of(world)["baseline"]
    assert baseline["days_held"] == 8 and baseline["days_used"] == 7
    assert baseline["days_excluded"]["reasons"]["partial"] == 1


def test_old_complete_days_are_not_stale_for_being_old(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    hold(world.repository, *(document(TODAY - timedelta(days=offset)) for offset in range(24, 31)))  # 24..30 days old
    baseline = answer_of(world)["baseline"]
    assert baseline["days_used"] == 7 and baseline["status"] == "known"


def test_mixed_hourly_and_quarter_hour_baseline_days(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23), res=60))
    hold(world.repository, *(document(TODAY - timedelta(days=i), res=60 if i % 2 else 15) for i in range(1, 11)))
    answer = answer_of(world)
    assert answer["baseline"]["resolution_minutes"] == [15, 60]
    assert answer["resolution_minutes"]["live"] == [15, 60]
    assert answer["baseline"]["days_used"] == 10


def test_a_day_without_a_usable_rate_is_excluded_not_converted(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    hold_baseline(world.repository, 10)
    hold(world.repository, document(TODAY - timedelta(days=2), fx=False), fetched=LATER)
    baseline = answer_of(world)["baseline"]
    assert baseline["days_held"] == 10 and baseline["days_used"] == 9
    assert baseline["days_excluded"]["reasons"]["no_price_rate"] == 1


def test_an_area_change_reads_only_that_areas_days(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23)))
    hold_baseline(world.repository, 10)
    assert answer_of(world)["baseline"]["days_used"] == 10
    area = world.repository.area_entry("SE3")
    assert area is not None and area.tz == "Europe/Stockholm"
    world.settings.area_id = "SE3"
    other = answer_of(world)
    assert other["area_id"] == "SE3" and other["baseline"]["days_held"] == 0
    assert other["baseline"]["status"] == "unknown" and other["current"]["unknown_reason"] == "not_held"
    assert other["cheapest_window"]["unknown_reason"] == "not_held"
    assert other["unknown_reason"] == "not_held"


def test_dst_baseline_days_through_the_command(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)  # the baseline reaches 2026-10-25, a 25-hour day
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: now)
    today = date(2026, 11, 3)
    hold(world.repository, document(today), document(date(2026, 11, 4)))
    hold(world.repository, *(document(today - timedelta(days=i)) for i in range(1, 12)))  # 25 h day gets 100 rows
    baseline = answer_of(world)["baseline"]
    assert baseline["days_used"] == 11 and baseline["days_excluded"]["count"] == 19
    assert baseline["seconds_used"] == 10 * 86400 + 25 * 3600
    # The same day with 96 rows is short of its 25 real hours: partial.
    hold(world.repository, document(date(2026, 10, 25), prices=[0.05] * 96), fetched=LATER)
    again = answer_of(world)["baseline"]
    assert again["days_used"] == 10 and again["days_excluded"]["reasons"]["partial"] == 1

    spring = datetime(2027, 4, 3, 10, 0, tzinfo=UTC)  # 2027-03-28 is 23 hours
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: spring)
    hold(world.repository, document(date(2027, 4, 3)), document(date(2027, 4, 4)))
    hold(world.repository, *(document(date(2027, 4, 3) - timedelta(days=i)) for i in range(1, 10)))
    result = answer_of(world)["baseline"]
    assert result["days_used"] == 9 and result["seconds_used"] == 8 * 86400 + 23 * 3600


def test_stale_current_day_is_unknown_but_a_valid_tomorrow_window_remains(world: SimpleNamespace,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23), prices=[0.05] * 95 + [0.01]))
    hold_baseline(world.repository, 8)
    real = world.repository.day_snapshot

    def snapshot(area_id: str, day: date) -> Any:
        found = real(area_id, day)
        if day == TODAY:
            from dataclasses import replace

            return replace(found, state="stale")
        return found

    monkeypatch.setattr(world.repository, "day_snapshot", snapshot)
    answer = answer_of(world)
    assert answer["current"]["status"] == "unknown" and answer["current"]["unknown_reason"] == "day_stale"
    assert answer["cheapest_window"]["status"] == "known"
    assert answer["cheapest_window"]["start"].startswith("2026-09-23")
    assert answer["baseline"]["days_used"] == 8  # the baseline is not touched by the current day's state


def test_missing_today_is_unknown_never_zero(world: SimpleNamespace) -> None:
    hold_baseline(world.repository, 8)
    answer = answer_of(world)
    assert answer["current"]["interval"] is None and answer["current"]["unknown_reason"] == "not_held"
    assert answer["cheapest_window"]["mean_price"] is None and answer["cheapest_window"]["unknown_reason"] == "not_held"
    assert "0.0" not in json.dumps({k: answer[k] for k in ("current", "cheapest_window")})


def test_published_end_and_a_partial_tomorrow_limit_the_window(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 23), count=8))  # tomorrow 00:00-02:00 local only
    answer = answer_of(world, duration_minutes=720)
    window = answer["cheapest_window"]
    # 10:00Z today to 00:00Z tomorrow plus 2 h of tomorrow: 16 h published, 12 h fits.
    assert window["status"] == "known" and window["horizon"]["until"] == "2026-09-23T00:00:00+00:00"
    assert window["horizon"]["runs"] == 1
    assert answer_of(world, duration_minutes=720)["cheapest_window"]["duration_minutes"] == 720


def test_a_negative_raw_price_is_kept_and_wins_a_window(world: SimpleNamespace) -> None:
    prices = [0.20] * 96
    prices[56:60] = [-0.02] * 4  # 14:00-15:00 local, 12:00-13:00 UTC
    hold(world.repository, document(TODAY, prices=prices), document(date(2026, 9, 23)))
    window = answer_of(world)["cheapest_window"]
    assert window["start"] == "2026-09-22T12:00:00+00:00" and window["mean_price"] < 0
