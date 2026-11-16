"""Stage 8.2a: the spot-only cost of the energy a session placed, by local delivery day, month and history window.

Pure, hass-free: real `ChargeSession` records and the real allocation; nothing fetches, writes or reads a fee.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_82a_spot_cost.py
"""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.spotnav.api.sessions import sessions_payload
from custom_components.spotnav.planning.planner import FiscalChoice
from custom_components.spotnav.sessions import history as hist
from custom_components.spotnav.sessions.costing import (
    day_bounds,
    PlacedSpan,
    RetainedPrice,
    session_spot,
    session_spot_row,
    Slice,
    SpotAllocation,
    spot_block,
    spot_total,
)
from custom_components.spotnav.sessions.summary import (
    delivery_allocation,
    delivery_day_row,
    delivery_month_rows,
)

from .sessions_helpers import session as base_session, STOCKHOLM, UTC
from .test_stage_63_history import make_store, NOW as HISTORY_NOW

HELSINKI = ZoneInfo("Europe/Helsinki")
KOLKATA = ZoneInfo("Asia/Kolkata")


def local(day: int, hour: int, minute: int = 0, *, month: int = 9, zone=STOCKHOLM) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=zone).astimezone(UTC)


def hourly(start: datetime, kwh: float, price: float, *, fx: float = 1.0, fx_date: date | None = None) -> Slice:
    """`kwh` placed in the hour starting at `start`, priced `price` in the major unit per kWh (rate `fx`)."""
    return Slice(start, start + timedelta(hours=1), kwh, price / fx, fx, fx_date, price / fx)


def charge(start: datetime, slices, *, energy: float | None = None, currency: str | None = "EUR",
           source: str = "register", hours: float | None = None, charger: str = "c", **over):
    """A finished session whose placement is `slices`; its energy defaults to exactly what they hold."""
    total = sum(item.kwh for item in slices)
    span = hours if hours is not None else max((slices[-1].end - start).total_seconds() / 3600 if slices else 1.0, 0.1)
    row = base_session(start, hours=span, energy=total if energy is None else energy, cost_minor=None,
                       currency=currency, charger_id=charger, source=source)
    return replace(row, intervals=tuple(slices), currency=currency, major_unit="€", area_id="FI")


def day_block(sessions, day: date, zone=STOCKHOLM):
    allocation = SpotAllocation([session_spot(s) for s in sessions], zone)
    return delivery_day_row(allocation, day)["spot_cost"]


# ---- what is priced ----------------------------------------------------------------------------------------------

def test_spot_cost_is_placed_kwh_times_the_raw_price_and_fee_changes_do_not_move_it() -> None:
    row = charge(local(22, 10), [hourly(local(22, 10), 2.0, 0.10), hourly(local(22, 11), 3.0, 0.30)])
    before = session_spot_row(row)
    fees = FiscalChoice(vat_enabled=True, vat_percent=25.5, transfer_enabled=True, transfer_minor_per_kwh=7.0,
                        tax_enabled=True, tax_minor_per_kwh=2.8)
    plain = row.priced(FiscalChoice())
    fiscal = row.priced(fees)

    assert plain.cost_minor != fiscal.cost_minor  # the fiscal field moves with the settings, as before
    assert session_spot_row(plain) == session_spot_row(fiscal) == before
    assert before["amount"] == pytest.approx(2.0 * 0.10 + 3.0 * 0.30)
    assert before["priced_kwh"] == 5.0 and before["unpriced_kwh"] == 0.0
    assert before["basis"] == "recorded_price_slices" and before["unit"] == "major" and before["currency"] == "EUR"
    assert before["coverage"]["state"] == "complete" and before["price_source"] is None
    assert before["price_source_state"] == "not_recorded"  # the provider was never stored: no Nord Pool claim
    assert fiscal.public(STOCKHOLM)["cost"] is not None and fiscal.public(STOCKHOLM)["spot_cost"]["amount"] == before["amount"]


def test_negative_and_zero_prices_are_valid_and_an_unpriced_session_is_unknown_not_zero() -> None:
    negative = charge(local(22, 2), [hourly(local(22, 2), 4.0, -0.05)])
    zero = charge(local(22, 4), [hourly(local(22, 4), 4.0, 0.0)])
    nothing = charge(local(22, 6), [], energy=3.0)

    assert session_spot_row(negative)["amount"] == pytest.approx(-0.2)
    assert session_spot_row(zero)["amount"] == 0.0 and session_spot_row(zero)["coverage"]["state"] == "complete"
    row = session_spot_row(nothing)
    assert row["amount"] is None and row["basis"] == "unknown" and row["unpriced_kwh"] == 3.0
    assert row["coverage"]["state"] == "none"
    day = day_block([negative, zero, nothing], date(2026, 9, 22))
    assert day["amount"] == pytest.approx(-0.2) and day["coverage"]["state"] == "partial"
    assert day["coverage"]["unpriced_reasons"] == {"no_price_slice": 3.0}


def test_partial_slices_make_a_labelled_partial_amount_and_a_missing_day_is_not_zero() -> None:
    partial = charge(local(22, 10), [hourly(local(22, 10), 6.0, 0.20)], energy=10.0)

    row = session_spot_row(partial)
    assert row["amount"] == pytest.approx(1.2) and row["priced_kwh"] == 6.0 and row["unpriced_kwh"] == 4.0
    assert row["coverage"]["state"] == "partial" and row["coverage"]["priced_fraction"] == pytest.approx(0.6)
    empty = day_block([partial], date(2026, 9, 23))
    assert empty["amount"] is None and empty["coverage"]["state"] == "no_sessions_recorded"


def test_currency_and_rate_errors_never_price_and_are_counted() -> None:
    sek = charge(local(22, 10), [hourly(local(22, 10), 5.0, 1.0, fx=11.0, fx_date=date(2026, 9, 22))], currency="SEK")
    no_rate_date = charge(local(22, 12), [hourly(local(22, 12), 2.0, 1.0, fx=11.0)], currency="SEK")
    bad_euro = charge(local(22, 13), [hourly(local(22, 13), 1.0, 0.1, fx=1.2)], currency="EUR")
    missing = charge(local(22, 14), [hourly(local(22, 14), 1.5, 0.1)], currency=None)

    assert session_spot_row(sek)["amount"] == pytest.approx(5.0)  # price x rate, the stored trustworthy basis
    assert session_spot_row(no_rate_date)["amount"] is None
    assert session_spot_row(no_rate_date)["coverage"]["unpriced_reasons"] == {"untrusted_rate": 2.0}
    assert session_spot_row(bad_euro)["amount"] is None
    row = session_spot_row(missing)  # no currency: nothing is priced and the energy is counted as excluded
    assert row["amount"] is None and row["currency"] is None and row["coverage"]["state"] == "none"
    assert row["currency_exclusions"]["missing_currency_kwh"] == 1.5 and row["sessions"] == 1

    eur = charge(local(22, 20), [hourly(local(22, 20), 2.0, 0.5)], currency="EUR")
    day = day_block([sek, eur, missing], date(2026, 9, 22))
    # The most recent session (EUR) sets the currency; the others are counted, not added and not dropped.
    assert day["currency"] == "EUR" and day["amount"] == pytest.approx(1.0)
    assert day["currency_exclusions"] == {"kwh": 6.5, "sessions": 2, "currencies": {"SEK": 5.0}, "missing_currency_kwh": 1.5}
    assert "currency_exclusions" in day["coverage"]["reasons"] and day["coverage"]["state"] == "partial"


def test_malformed_duplicate_and_overlapping_slices_are_handled_conservatively() -> None:
    first = hourly(local(22, 10), 2.0, 0.10)
    row = charge(local(22, 10), [first, first, hourly(local(22, 11), 1.0, 0.20)])  # an identical duplicate row
    out = session_spot_row(row)
    assert out["priced_kwh"] == 3.0 and out["amount"] == pytest.approx(0.4)  # counted once

    overlap = replace(first, start=local(22, 10, 30), end=local(22, 11, 30), eur_per_kwh=0.9)  # conflicts with `first`
    bad = charge(local(22, 10), [first, overlap], energy=4.0)
    out = session_spot_row(bad)
    assert out["priced_kwh"] == 0.0 and out["amount"] is None
    assert out["coverage"]["unpriced_reasons"]["conflicting_slice"] == 4.0 and "conflicting_slices" in out["coverage"]["reasons"]

    broken = charge(local(22, 10), [first, replace(first, kwh=float("nan"), start=local(22, 12), end=local(22, 13))],
                    energy=2.0)
    out = session_spot_row(broken)
    assert out["priced_kwh"] == 2.0 and "invalid_slices" in out["coverage"]["reasons"]

    too_much = charge(local(22, 10), [hourly(local(22, 10), 9.0, 0.1)], energy=2.0)
    out = session_spot_row(too_much)
    assert out["amount"] is None and "slice_energy_exceeds_session_energy" in out["coverage"]["reasons"]


def test_receipt_only_late_energy_is_never_priced_or_summed_and_unknown_is_reported() -> None:
    reconciled = {"state": "reconciled", "unplaced_late_kwh": 1.5, "unassigned_register_kwh": None}
    inside = replace(charge(local(22, 10), [hourly(local(22, 10), 5.0, 0.2)]), late=reconciled)
    unknown = charge(local(22, 12), [hourly(local(22, 12), 1.0, 0.2)])

    one = session_spot_row(inside)
    assert one["unplaced_kwh"] == 1.5 and one["priced_kwh"] == 5.0 and one["amount"] == pytest.approx(1.0)
    assert one["coverage"]["state"] == "partial" and "unplaced_late_energy_not_priced" in one["coverage"]["reasons"]
    day = day_block([inside, unknown], date(2026, 9, 22))
    assert day["unplaced_kwh"] == 1.5 and day["unplaced_unknown_sessions"] == 1
    assert day["priced_kwh"] == 6.0 and day["amount"] == pytest.approx(1.2)  # the late kWh adds no cost


def test_register_and_integrated_energy_are_reported_separately_and_estimates_are_flagged() -> None:
    register = charge(local(22, 10), [hourly(local(22, 10), 2.0, 0.1)], source="register")
    integrated = charge(local(22, 11), [hourly(local(22, 11), 3.0, 0.1)], source="integrated_power")
    estimated = charge(local(22, 12), [hourly(local(22, 12), 1.0, 0.1)], source="estimated")

    day = day_block([register, integrated, estimated], date(2026, 9, 22))
    assert day["energy_sources"] == {"estimated": 1.0, "integrated_power": 3.0, "register": 2.0}
    assert day["priced_kwh"] == 6.0 and day["estimated_kwh"] == 1.0


def test_an_open_session_and_overlapping_sessions_are_never_called_complete() -> None:
    open_row = replace(charge(local(22, 10), [hourly(local(22, 10), 2.0, 0.1)]), end=None)
    assert session_spot_row(open_row)["coverage"]["state"] == "partial"
    assert "open_session" in session_spot_row(open_row)["coverage"]["reasons"]

    a = charge(local(22, 10), [hourly(local(22, 10), 2.0, 0.1)], hours=2.0)
    b = replace(charge(local(22, 11), [hourly(local(22, 11), 1.0, 0.1)], hours=1.0), id="other")
    day = day_block([a, b], date(2026, 9, 22))
    assert "overlapping_sessions" in day["coverage"]["reasons"] and day["coverage"]["state"] == "partial"


# ---- calendar-day accounting --------------------------------------------------------------------------------------

def test_a_midnight_session_is_split_by_the_hour_each_slice_belongs_to_and_counted_once() -> None:
    row = charge(local(22, 22), [hourly(local(22, 22), 2.0, 0.10), hourly(local(22, 23), 4.0, 0.20),
                                 hourly(local(23, 0), 6.0, 0.30), hourly(local(23, 1), 1.0, 0.40)])
    allocation = SpotAllocation([session_spot(row)], STOCKHOLM)

    first = delivery_day_row(allocation, date(2026, 9, 22))["spot_cost"]
    second = delivery_day_row(allocation, date(2026, 9, 23))["spot_cost"]
    assert first["priced_kwh"] == 6.0 and first["amount"] == pytest.approx(0.2 + 0.8)
    assert second["priced_kwh"] == 7.0 and second["amount"] == pytest.approx(1.8 + 0.4)
    assert first["allocation"] == "price_interval_overlap_estimate"
    whole = session_spot_row(row, STOCKHOLM)
    assert first["amount"] + second["amount"] == pytest.approx(whole["amount"])
    assert [d["day"] for d in whole["by_delivery_day"]] == ["2026-09-22", "2026-09-23"]
    assert sum(d["priced_kwh"] for d in whole["by_delivery_day"]) == pytest.approx(13.0)


def test_an_interval_straddling_local_midnight_is_split_by_elapsed_time() -> None:
    """A zone 5h30 ahead of UTC: the UTC hour 18:00-19:00 is 23:30-00:30 local, half on each day."""
    start = datetime(2026, 9, 22, 18, tzinfo=UTC)
    row = charge(start, [hourly(start, 4.0, 0.5)])
    allocation = SpotAllocation([session_spot(row)], KOLKATA)

    a = delivery_day_row(allocation, date(2026, 9, 22))["spot_cost"]
    b = delivery_day_row(allocation, date(2026, 9, 23))["spot_cost"]
    assert a["priced_kwh"] == pytest.approx(2.0) and b["priced_kwh"] == pytest.approx(2.0)
    assert a["amount"] + b["amount"] == pytest.approx(2.0)


@pytest.mark.parametrize(("day", "hours"), [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 9, 22), 24)])
def test_dst_days_are_their_real_length_and_every_hour_of_them_is_counted_once(day: date, hours: int) -> None:
    since, until = day_bounds(day, STOCKHOLM)
    assert (until - since) == timedelta(hours=hours)
    slices = [hourly(since + timedelta(hours=h), 1.0, 0.1 * (h + 1)) for h in range(hours)]
    row = charge(since, slices)
    total = sum(0.1 * (h + 1) for h in range(hours))

    block = day_block([row], day)
    assert block["priced_kwh"] == hours and block["amount"] == pytest.approx(total)
    assert day_block([row], day + timedelta(days=1))["amount"] is None  # the neighbours received none of it
    assert day_block([row], day - timedelta(days=1))["amount"] is None


def test_a_month_is_the_sum_of_its_delivery_days_and_nothing_is_counted_twice() -> None:
    rows = [
        charge(local(30, 22), [hourly(local(30, 22), 2.0, 0.1), hourly(local(30, 23), 3.0, 0.2),
                               hourly(local(1, 0, month=10), 4.0, 0.3)]),
        charge(local(2, 12, month=10), [hourly(local(2, 12, month=10), 5.0, -0.1)]),
        charge(local(28, 12), [hourly(local(28, 12), 1.0, 0.5)]),
    ]
    zone = STOCKHOLM
    today = date(2026, 10, 3)
    allocation = delivery_allocation(rows, zone, [(day_bounds(date(2026, 9, 1), zone)[0], day_bounds(today, zone)[1])])

    october, october_days = delivery_month_rows(allocation, "2026-10")
    september, september_days = delivery_month_rows(allocation, "2026-09")
    assert len(october_days) == 31 and len(september_days) == 30
    for summary, days in ((october, october_days), (september, september_days)):
        blocks = [d["spot_cost"] for d in days]
        assert sum(b["priced_kwh"] for b in blocks) == pytest.approx(summary["spot_cost"]["priced_kwh"])
        assert sum(b["amount"] or 0.0 for b in blocks) == pytest.approx(summary["spot_cost"]["amount"])
    assert october["spot_cost"]["priced_kwh"] == 9.0 and october["spot_cost"]["amount"] == pytest.approx(1.2 - 0.5)
    assert september["spot_cost"]["priced_kwh"] == 6.0 and september["spot_cost"]["amount"] == pytest.approx(0.2 + 0.6 + 0.5)
    # Every placed kWh appears in exactly one month: 15 in all.
    assert october["spot_cost"]["priced_kwh"] + september["spot_cost"]["priced_kwh"] == 15.0
    assert october_days[0]["spot_cost"]["coverage"]["state"] != "no_sessions_recorded"
    assert october_days[10]["spot_cost"]["amount"] is None  # nothing recorded that day: unknown, not zero


def test_energy_without_placement_is_never_moved_to_the_start_day() -> None:
    spanning = charge(local(22, 20), [], energy=6.0, hours=30.0)  # two local days, no slices at all
    within = charge(local(22, 8), [], energy=2.0, hours=1.0)
    allocation = SpotAllocation([session_spot(spanning), session_spot(within)], STOCKHOLM)

    day_one = delivery_day_row(allocation, date(2026, 9, 22))["spot_cost"]
    day_two = delivery_day_row(allocation, date(2026, 9, 23))["spot_cost"]
    assert day_one["unpriced_kwh"] == 2.0 and day_one["unallocated_kwh"] == 6.0  # only the contained session
    assert day_two["unpriced_kwh"] == 0.0 and day_two["unallocated_kwh"] == 6.0
    assert "energy_without_placement_overlaps_period" in day_one["coverage"]["reasons"]
    month, _ = delivery_month_rows(allocation, "2026-09")
    assert month["spot_cost"]["unpriced_kwh"] == 8.0 and month["spot_cost"]["unallocated_kwh"] == 0.0
    assert month["spot_cost"]["amount"] is None  # nothing priced: unknown


# ---- history and get_sessions agree -------------------------------------------------------------------------------

def test_history_window_for_a_local_day_equals_the_sessions_delivery_day_and_the_month_row() -> None:
    zone = HELSINKI
    rows = [
        charge(local(22, 21, zone=zone), [hourly(local(22, 21, zone=zone), 2.0, 0.10), hourly(local(22, 23, zone=zone), 3.0, 0.20),
                                          hourly(local(23, 0, zone=zone), 4.0, 0.30)]),
        charge(local(23, 9, zone=zone), [hourly(local(23, 9, zone=zone), 1.0, 0.05)]),
    ]
    rows = [replace(r, id=f"s{i}") for i, r in enumerate(rows)]
    store, _ = make_store()
    day = date(2026, 9, 23)
    since, until = day_bounds(day, zone)

    answer = hist.charging_history(store, "c", since=since, until=until, zone=zone, now=HISTORY_NOW, sessions=tuple(rows))
    window = answer["window_spot_cost"]
    delivered = delivery_day_row(SpotAllocation([session_spot(r) for r in rows], zone), day)["spot_cost"]

    assert window["local_day"] == "2026-09-23"
    for key in ("amount", "priced_kwh", "unpriced_kwh", "unplaced_kwh", "currency", "basis", "coverage", "sessions"):
        assert window[key] == delivered[key]
    assert window["amount"] == pytest.approx(1.2 + 0.05)
    assert [row["spot_cost_in_window"]["priced_kwh"] for row in answer["sessions"]] == [4.0, 1.0]
    assert [row["spot_cost"]["priced_kwh"] for row in answer["sessions"]] == [9.0, 1.0]  # whole session, not the window
    other_day = hist.charging_history(store, "c", since=day_bounds(date(2026, 9, 22), zone)[0], until=since, zone=zone,
                                      now=HISTORY_NOW, sessions=tuple(rows))
    assert other_day["window_spot_cost"]["priced_kwh"] + window["priced_kwh"] == pytest.approx(10.0)

    payload = sessions_payload(tuple(rows), None, charger_id="c", zone=zone, now=datetime(2026, 9, 24, 8, tzinfo=UTC),
                               limit=20, month="2026-09")
    by_day = {row["period"]: row["spot_cost"] for row in payload["delivery_days"]}
    assert by_day["2026-09-23"] == delivered
    month = payload["delivery_month_summary"]["spot_cost"]
    assert month["priced_kwh"] == 10.0 and month["amount"] == pytest.approx(0.2 + 0.6 + 1.2 + 0.05)
    assert sum(r["spot_cost"]["priced_kwh"] for r in payload["delivery_month_days"]) == pytest.approx(10.0)
    assert payload["delivery_accounting"]["day"] == "home_assistant_local_calendar_day"
    # The legacy start-day fields are still there, and still the whole session on the day it started.
    assert payload["month_days"][21]["sessions"] == 1 and payload["month_days"][22]["sessions"] == 1


def test_history_prices_every_matching_session_but_says_when_rows_are_cut(monkeypatch) -> None:
    monkeypatch.setattr(hist, "MAX_ROWS", 2)
    zone = HELSINKI
    rows = [replace(charge(local(22, 8 + i, zone=zone), [hourly(local(22, 8 + i, zone=zone), 1.0, 0.1)]), id=f"s{i}")
            for i in range(4)]
    store, _ = make_store()
    since, until = day_bounds(date(2026, 9, 22), zone)

    answer = hist.charging_history(store, "c", since=since, until=until, zone=zone, now=HISTORY_NOW, sessions=tuple(rows))

    assert len(answer["sessions"]) == 2 and answer["truncated"]["sessions"]["truncated"]
    assert answer["window_spot_cost"]["priced_kwh"] == 4.0 and answer["window_spot_cost"]["sessions"] == 4
    assert "rows_truncated" in answer["window_spot_cost"]["coverage"]["reasons"]
    assert answer["window_spot_cost"]["coverage"]["state"] == "partial"


# ---- retained prices, provenance, read-only -----------------------------------------------------------------------

def retained(start: datetime, price: float, **over) -> RetainedPrice:
    values = dict(utc_start=start, utc_end=start + timedelta(hours=1), eur_per_kwh=price, fx=1.0, fx_date=None,
                  area_id="FI", currency="EUR", source="relay-a")
    values.update(over)
    return RetainedPrice(**values)


def test_placed_energy_joins_retained_prices_only_with_matching_provenance() -> None:
    start = local(22, 10)
    span = PlacedSpan(start, start + timedelta(hours=2), 6.0, price_source="relay-a")
    row = replace(charge(start, [], energy=6.0, hours=2.0), id="r")
    prices = [retained(start, 0.10), retained(start + timedelta(hours=1), 0.30)]

    ok = session_spot(row, spans=[span], retained=prices)
    block = spot_block(spot_total(ok))
    assert block["basis"] == "retained_price_intervals" and block["amount"] == pytest.approx(3 * 0.10 + 3 * 0.30)
    assert block["price_sources"] == ["relay-a"] and block["coverage"]["state"] == "complete"

    def priced(**change):
        return spot_block(spot_total(session_spot(row, spans=[replace(span, **change.pop("span", {}))],
                                                  retained=[retained(start, 0.10, **change),
                                                            retained(start + timedelta(hours=1), 0.30, **change)])))

    assert priced(source="relay-b")["amount"] is None  # another source: no proof
    assert priced(source="relay-b")["coverage"]["unpriced_reasons"] == {"price_provenance_mismatch": 6.0}
    assert priced(area_id="SE3")["amount"] is None
    assert priced(currency="SEK")["coverage"]["unpriced_reasons"] == {"currency_mismatch": 6.0}
    assert priced(span={"price_source": None})["amount"] is None
    assert priced(fx=1.3)["amount"] is None  # a euro price with a non-unit rate is untrusted
    # A price missing from the retained set is unknown, never filled from another day or today.
    gap = spot_block(spot_total(session_spot(row, spans=[span], retained=prices[:1])))
    assert gap["priced_kwh"] == 3.0 and gap["coverage"]["unpriced_reasons"] == {"no_retained_price": 3.0}
    assert gap["coverage"]["state"] == "partial"
    # Two conflicting rows for one start price nothing.
    clash = spot_block(spot_total(session_spot(row, spans=[span], retained=[*prices, retained(start, 0.99)])))
    assert clash["priced_kwh"] == 3.0 and "conflicting_retained_prices" in clash["coverage"]["reasons"]


def test_retained_prices_never_price_energy_a_recorded_slice_already_holds() -> None:
    start = local(22, 10)
    row = charge(start, [hourly(start, 2.0, 0.10)], energy=4.0, hours=2.0)
    span = PlacedSpan(start + timedelta(minutes=30), start + timedelta(hours=1, minutes=30), 2.0, price_source="relay-a")

    out = spot_block(spot_total(session_spot(row, spans=[span], retained=[retained(start, 0.5)])))
    assert out["priced_kwh"] == 2.0 and out["amount"] == pytest.approx(0.2)
    assert out["coverage"]["unpriced_reasons"] == {"already_priced_window": 2.0}


def test_no_network_no_writes_no_mutation(monkeypatch) -> None:
    def refuse(*_a, **_k):
        raise AssertionError("a spot-cost read must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    rows = [charge(local(22, 10), [hourly(local(22, 10), 2.0, 0.1)])]
    stored = [r.as_dict() for r in rows]

    payload = sessions_payload(tuple(rows), None, charger_id="c", zone=STOCKHOLM,
                               now=datetime(2026, 9, 22, 20, tzinfo=UTC), limit=20)

    assert [r.as_dict() for r in rows] == stored
    assert payload["delivery_days"][0]["spot_cost"]["amount"] == pytest.approx(0.2)
    # The fiscal fields keep their meaning: this record stored no cost, so it still has none.
    assert payload["sessions"][0]["cost"] is None and payload["sessions"][0]["savings_estimate"] is True
