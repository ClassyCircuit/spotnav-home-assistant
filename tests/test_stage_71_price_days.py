"""Stage 7.1: `spotnav/get_price_days` against a real `PriceRepository` holding real day documents.

No `hass` fixture: the repository is built without one (its store is a double and nothing is fetched), and the
command's handler is called with a fake connection. Every case asserts the handler's own answer.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.spotnav.api import price_calendar as module
from custom_components.spotnav.api.dashboard import published_rows
from custom_components.spotnav.planning.planner import FiscalChoice, chart_intervals
from custom_components.spotnav.pricing.price_repository import PriceRepository
from custom_components.spotnav.runtime import DATA_KEY

from .relay import BUNDLED, STOCKHOLM, Clock, StoreDouble, day_body

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 22)
AREA = "SE4"


def document(day: date, *, count: int | None = None, res: int = 15, price: float | None = None) -> dict[str, Any]:
    """A held day document, optionally hourly (`res` 60) or cut to `count` prices (a partial day)."""
    body = json.loads(day_body(AREA, day))
    start = datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM)
    end = datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM) + timedelta(days=1)
    end = datetime(end.year, end.month, end.day, tzinfo=STOCKHOLM)
    hours = int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 3600)
    body["start"] = start.isoformat()
    body["fx_date"] = (day - timedelta(days=1)).isoformat()
    body["res"] = res
    full = hours * (60 // res)
    prices = [round(0.05 + 0.001 * (index % 7), 5) for index in range(full if count is None else count)]
    if price is not None:
        prices[0] = price
    body["prices"] = prices
    return body


def hold(repository: PriceRepository, *documents: dict[str, Any]) -> None:
    days = {
        f"{AREA}|Europe/Stockholm|{item['date']}": {
            "document": item, "fetched_at": "2026-09-22T05:00:00+00:00", "provider": "stub"
        }
        for item in documents
    }
    repository._adopt({"schema": 2, "days": days})  # noqa: SLF001 - the store's own path


@pytest.fixture
def repository() -> PriceRepository:
    return PriceRepository(None, store=StoreDouble(), bundled=BUNDLED, now=Clock(NOW))  # type: ignore[arg-type]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, repository: PriceRepository) -> SimpleNamespace:
    settings = SimpleNamespace(area_id=AREA)
    hass = SimpleNamespace(data={DATA_KEY: SimpleNamespace(auto_store=SimpleNamespace(settings=lambda _id: settings),
                                                           price_repository=repository)})
    monkeypatch.setattr(module, "effective_settings", lambda _h, _c, current: current)
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: NOW)
    monkeypatch.setattr(module, "lookup_charger", lambda _h, cid: (SimpleNamespace(entry_id=cid), None)
                        if cid == "c1" else (None, "spotnav_unknown_charger"))
    return SimpleNamespace(hass=hass, settings=settings, repository=repository, clock=None)


class Connection:
    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[tuple[str, str]] = []

    def send_result(self, _id: int, answer: Any) -> None:
        self.results.append(answer)

    def send_error(self, _id: int, code: str, _message: str) -> None:
        self.errors.append((code, _message))


def ask(world: SimpleNamespace, **fields: Any) -> Connection:
    connection = Connection()
    msg = {"id": 1, "type": "spotnav/get_price_days", "api_version": 1, "charger_id": "c1", **fields}
    module.websocket_get_price_days(world.hass, connection, msg)
    return connection


def test_available_lists_held_days_newest_first_with_provenance_and_partial_tomorrow(world: SimpleNamespace) -> None:
    hold(world.repository, document(date(2026, 9, 20)), document(date(2026, 9, 21), res=60),
         document(TODAY), document(date(2026, 9, 23), count=40))
    held_before = set(world.repository._days)  # noqa: SLF001
    answer = ask(world, mode="available").results[0]
    assert [row["day"] for row in answer["days"]] == ["2026-09-23", "2026-09-22", "2026-09-21", "2026-09-20"]
    assert (answer["oldest"], answer["newest"], answer["today"]) == ("2026-09-20", "2026-09-23", "2026-09-22")
    assert (answer["area_id"], answer["zone"], answer["currency"]) == (AREA, "Europe/Stockholm", "SEK")
    tomorrow, today, hourly, _older = answer["days"]
    assert tomorrow["complete"] is False and tomorrow["state"] == "incomplete" and tomorrow["interval_count"] == 40
    assert today["complete"] is True and today["interval_count"] == 96 and today["resolution_minutes"] == 15
    assert hourly["resolution_minutes"] == 60 and hourly["interval_count"] == 24
    assert today["source"] in ("store", "memory", "bundled", "network")
    assert today["fetched_at"] is not None
    assert "intervals" not in today
    assert set(world.repository._days) == held_before  # noqa: SLF001 - nothing was fetched or stored


def test_available_with_nothing_held_is_honest_not_a_failure(world: SimpleNamespace) -> None:
    answer = ask(world, mode="available").results[0]
    assert answer["days"] == [] and answer["oldest"] is None and answer["newest"] is None


def test_available_is_capped_and_yesterday_reachability_is_reported(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    hold(world.repository, document(TODAY))
    monkeypatch.setattr(module, "MAX_AVAILABLE_DAYS", 1)
    monkeypatch.setattr(world.repository, "archive_reachable", lambda _a, _d: False)
    answer = ask(world, mode="available").results[0]
    assert len(answer["days"]) == 1 and answer["yesterday_reachable"] is False


def test_range_rows_are_the_published_row_shape_in_major_units_once(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY, price=-0.02))
    answer = ask(world, mode="range", **{"from": "2026-09-22", "to": "2026-09-22"}).results[0]
    day = answer["days"][0]
    assert day["held"] is True and day["reason"] is None and len(day["intervals"]) == 96
    first = day["intervals"][0]
    assert set(first) == {"start", "end", "raw_price"}
    # -0.02 EUR/kWh at the document's own SEK rate, in SEK (major) per kWh: not multiplied by 100.
    assert first["raw_price"] == pytest.approx(-0.02 * 11.275)
    assert day["provenance"] == [{"market_day": "2026-09-22", "provider": "stub",
                                  "fetched_at": "2026-09-22T05:00:00+00:00", "state": "ready"}]
    parsed = world.repository.day_snapshot(AREA, TODAY).document
    assert day["intervals"] == published_rows(chart_intervals((parsed,), currency="SEK", fiscal=FiscalChoice()))


def test_range_missing_days_carry_a_reason_and_no_fake_zero(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    hold(world.repository, document(TODAY), document(date(2026, 9, 20), count=48))
    monkeypatch.setattr(world.repository, "archive_reachable", lambda _a, day: day >= date(2026, 9, 21))
    answer = ask(world, mode="range", **{"from": "2026-09-19", "to": "2026-09-23"}).results[0]
    by_day = {row["day"]: row for row in answer["days"]}
    assert [row["day"] for row in answer["days"]] == sorted(by_day)
    assert by_day["2026-09-19"]["reason"] == "outside_provider_reach" and by_day["2026-09-19"]["intervals"] is None
    assert by_day["2026-09-21"]["reason"] == "not_held" and by_day["2026-09-21"]["held"] is False
    assert by_day["2026-09-23"]["reason"] == "not_published" and by_day["2026-09-23"]["intervals"] is None
    partial = by_day["2026-09-20"]
    assert partial["held"] is True and partial["complete"] is False and len(partial["intervals"]) == 48
    assert partial["intervals"][-1]["end"] == "2026-09-20T12:00:00+02:00"  # the gap stays a gap, never zero rows


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": "bogus"},
        {"mode": "range"},
        {"mode": "range", "from": "2026-09-22", "to": "2026-09-21"},
        {"mode": "range", "from": "2026-09-10", "to": "2026-09-18"},  # nine days
        {"mode": "range", "from": "2026-9-22", "to": "2026-09-22"},
        {"mode": "range", "from": "20260922", "to": "2026-09-22"},
        {"mode": "range", "from": "2026-02-30", "to": "2026-09-22"},
        {"mode": "range", "from": 20260922, "to": "2026-09-22"},
        {"mode": "range", "from": "2026-09-22", "to": "2026-09-24"},  # beyond tomorrow
        {"mode": "range", "from": "2025-01-01", "to": "2025-01-02"},  # older than the repository keeps
    ],
)
def test_invalid_requests_are_refused_with_a_stable_code(world: SimpleNamespace, fields: dict[str, Any]) -> None:
    hold(world.repository, document(TODAY))
    connection = ask(world, **fields)
    assert connection.results == [] and [code for code, _ in connection.errors] == ["spotnav_invalid_range"]


def test_eight_days_is_the_bound_and_nine_is_not(world: SimpleNamespace) -> None:
    ok = ask(world, mode="range", **{"from": "2026-09-15", "to": "2026-09-22"})
    assert len(ok.results[0]["days"]) == 8
    assert ask(world, mode="range", **{"from": "2026-09-14", "to": "2026-09-22"}).errors


def test_dst_days_report_actual_elapsed_time_and_mixed_resolution_keeps_real_intervals(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    spring, before, fall = date(2026, 3, 29), date(2026, 10, 24), date(2026, 10, 25)
    hold(world.repository, document(spring, res=60), document(before), document(fall, res=60))
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: datetime(2026, 10, 25, 10, tzinfo=timezone.utc))
    answer = ask(world, mode="range", **{"from": "2026-10-24", "to": "2026-10-25"}).results[0]
    quarter, long_day = answer["days"]
    assert (quarter["resolution_minutes"], long_day["resolution_minutes"]) == (15, 60)

    def hours(day: dict[str, Any]) -> float:
        rows = day["intervals"]
        return sum((datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).total_seconds() for r in rows) / 3600

    assert hours(quarter) == 24 and hours(long_day) == 25 and long_day["interval_count"] == 25
    assert len({r["start"] for r in long_day["intervals"]}) == 25  # the repeated 02:00 hour is two rows
    short = ask(world, mode="range", **{"from": "2026-03-29", "to": "2026-03-29"}).results[0]["days"][0]
    assert hours(short) == 23 and short["interval_count"] == 23


def test_today_follows_the_price_areas_zone_not_utc(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.dt_util, "utcnow", lambda: datetime(2026, 9, 22, 23, 30, tzinfo=timezone.utc))
    assert ask(world, mode="available").results[0]["today"] == "2026-09-23"


def test_area_change_and_charger_errors(world: SimpleNamespace) -> None:
    hold(world.repository, document(TODAY))
    assert ask(world, mode="available").results[0]["days"]
    world.settings.area_id = "DE-LU"
    other = ask(world, mode="available").results[0]
    assert other["area_id"] == "DE-LU" and other["days"] == [] and other["currency"] == "EUR"
    world.settings.area_id = None
    assert ask(world, mode="available").errors[0][0] == "spotnav_no_price_area"
    world.settings.area_id = "NOPE"
    assert ask(world, mode="available").errors[0][0] == "spotnav_unknown_price_area"
    assert ask(world, mode="available", charger_id="other").errors[0][0] == "spotnav_unknown_charger"
    assert ask(world, mode="available", charger_id=None).errors[0][0] == "spotnav_unknown_charger"


def test_unsupported_versions_are_refused_before_anything_is_read(world: SimpleNamespace) -> None:
    for version in (2, True, "1", None):
        connection = Connection()
        msg = {"id": 1, "type": "spotnav/get_price_days", "api_version": version, "charger_id": "c1", "mode": "available"}
        module.websocket_get_price_days(world.hass, connection, msg)
        assert [code for code, _ in connection.errors] == ["spotnav_unsupported_api_version"]


def test_overlapping_rows_are_refused_not_repaired(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    hold(world.repository, document(TODAY))
    monkeypatch.setattr(module, "published_rows", lambda _rows: None)
    day = ask(world, mode="range", **{"from": "2026-09-22", "to": "2026-09-22"}).results[0]["days"][0]
    assert day["held"] is True and day["intervals"] is None and day["reason"] == "invalid_intervals"


def test_command_is_registered_once_at_setup() -> None:
    from pathlib import Path

    text = (Path(module.__file__).parent.parent / "__init__.py").read_text(encoding="utf-8")
    assert text.count("async_setup_price_calendar_api(hass)") == 1


def test_a_held_day_without_a_usable_rate_is_unknown_not_a_failure_or_a_guess(world: SimpleNamespace) -> None:
    broken = document(TODAY)
    broken["fx"] = {}
    hold(world.repository, broken, document(date(2026, 9, 21)))
    days = ask(world, mode="range", **{"from": "2026-09-21", "to": "2026-09-22"}).results[0]["days"]
    assert days[0]["intervals"] is not None and days[0]["reason"] is None
    assert days[1]["held"] is True and days[1]["intervals"] is None and days[1]["reason"] == "no_price_rate"
