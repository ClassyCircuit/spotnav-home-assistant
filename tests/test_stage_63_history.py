"""Stage 6.3: bounded history queries over retained plan versions, their own tariffs and measured flow.

Deterministic fixtures through the real evidence store and query; HA, OCPP and storage are the usual mocked
boundaries. Nothing here shows what the installed Morek exposes, or that a car charged.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_63_history.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav import time_zones
from custom_components.spotnav.api import sessions as api
from custom_components.spotnav.sessions import evidence as ev
from custom_components.spotnav.sessions import history as hist
from .test_stage_62_evidence import MemBackend

UTC = timezone.utc
HELSINKI = time_zones.zone("Europe/Helsinki")  # UTC+2 in November: local midnight is 22:00Z
NOON = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)  # local 12:00 on the 13th
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
CLOCK = {"now": NOON}


def at(hours: int, minutes: int = 0) -> datetime:
    """Absolute instants on the night of 13/14 November (UTC)."""
    return datetime(2026, 11, 13, tzinfo=UTC) + timedelta(hours=hours, minutes=minutes)


def make_store(backend=None):
    backend = backend or MemBackend()
    return ev.ChargingEvidenceStore(SimpleNamespace(data={}), store=backend, now=lambda: CLOCK["now"]), backend


def profile(start: datetime, *periods: tuple[int, float], plan_id: int = 1) -> dict:
    return {"chargingProfileId": plan_id, "chargingSchedule": {
        "startSchedule": start.isoformat(), "chargingRateUnit": "A",
        "chargingSchedulePeriod": [{"startPeriod": o, "limit": limit} for o, limit in periods]}}


def send(store, plan_id, prof, *, accepted_at, status="accepted", fiscal=None, prices=None, ack=True):
    blobs = {}
    if fiscal is not None:
        blobs["fiscal"] = fiscal
    if prices is not None:
        blobs["prices"] = {"rows": prices}
    store.record_plan("c", plan_id=plan_id, fingerprint="f-" + plan_id, profile=prof, intent_at=accepted_at.isoformat(),
                      source="worker", intent="schedule", revision=1,
                      context={"time_zone": "Europe/Helsinki", "fiscal_state": "resolved" if fiscal else "unknown",
                               "prices_state": "published" if prices else "none", "market": {"area_id": "FI"}},
                      blobs=blobs)
    if ack:
        store.record_event("c", "dispatch_started", plan_id=plan_id, at=accepted_at.isoformat())
        store.record_event("c", "ack", plan_id=plan_id, at=accepted_at.isoformat(), status=status)


def power(store, when: datetime, watts: float, kwh: float | None = None, *, entity="sensor.p") -> None:
    store.record_sample("c", ev.KIND_POWER, value=watts, observed_at=when, received_at=when, entity_id=entity, unit="W")
    if kwh is not None:
        store.record_sample("c", ev.KIND_REGISTER, value=kwh, observed_at=when, received_at=when,
                            entity_id="sensor.kwh", unit="kWh")


def run(store, since=None, until=None, **kwargs):
    since, until = since or at(12), until or at(36)
    return hist.charging_history(store, "c", since=since, until=until, zone=HELSINKI, now=NOW, **kwargs)


FISCAL_A = {"vat": 0.255, "margin_c": 1.0}
FISCAL_B = {"vat": 0.0, "margin_c": 9.0}
PRICES_A = [[1, 2, 0.10, 1.0]]
PRICES_B = [[1, 2, 0.99, 1.0]]


def night_store():
    """Plan 22:30-23:30Z accepted at 21:00Z. Flow 21:50-22:05 (before the block), HA down 22:05-22:20, then idle."""
    store, backend = make_store()
    store.record_capture_start("c", at(21, 40))
    send(store, "p1", profile(at(22, 30), (0, 16), (3600, 0)), accepted_at=at(21), fiscal=FISCAL_A, prices=PRICES_A)
    for minute in range(10, 26):  # 21:50 .. 22:05 across local midnight (22:00Z), measured every minute
        power(store, at(21, 40) + timedelta(minutes=minute), 7000.0, 20.0 + 0.1 * (minute - 10))
    store.record_capture_start("c", at(22, 20))  # HA restart: nothing was captured 22:06-22:19
    for minute in range(0, 100):  # 22:20 .. 23:59 idle, a measured zero
        power(store, at(22, 20) + timedelta(minutes=minute), 0.0, 21.5)
    return store, backend


# ---- restart and midnight, outside-plan flow, planned block with no flow ------------------------------------

def test_night_across_midnight_and_restart_keeps_plan_gap_outside_flow_and_idle_block():
    store, _ = night_store()
    answer = run(store)
    interval, = answer["observed"]["intervals"]
    assert interval["basis"] == "measured_power" and interval["samples"] == 16 and interval["peak_w"] == 7000.0
    assert interval["first_sample"] == at(21, 50).isoformat() and interval["end_bounded"] is False
    assert interval["end_latest"] is None  # the next sample is after the restart gap: the end is unbounded, not guessed
    outside = answer["comparison"]["outside_plan"]
    assert [item["kind"] for item in outside] == ["outside_plan"]  # a plan applied, charging was outside its window
    assert outside[0]["start"] == at(21, 50).isoformat()
    assert outside[0]["seconds"] == 15 * 60
    block, = answer["comparison"]["planned_blocks"]
    assert block["start"] == at(22, 30).isoformat() and block["verdict"] == "no_flow_observed"  # measured zeros
    assert block["covered_fraction"] >= 0.999 and block["power_flow_overlap"] is False
    assert answer["observed"]["capture_restarts"] == [at(21, 40).isoformat(), at(22, 20).isoformat()]
    energy = answer["observed"]["energy"]
    assert energy["power_integrated_estimate_kwh"] == pytest.approx(7000 * 60 * 15 / 3.6e6)  # the gap is not 7 kW
    assert energy["unknown_seconds"] >= 14 * 60 and any("capture_restart" in key for key in energy["unknown_segments"])
    assert energy["meter_counter_unobserved_kwh"] == pytest.approx(0.0)  # restart span: how much, never when
    assert answer["observed"]["coverage"]["no_data_seconds"] > 0
    assert answer["window"]["local_since"].endswith("+02:00")


def test_a_gap_inside_the_block_makes_it_unknown_not_no_flow():
    store, _ = make_store()
    send(store, "p1", profile(at(22, 30), (0, 16), (3600, 0)), accepted_at=at(21))
    store.record_capture_start("c", at(22, 30))
    for minute in range(0, 20):
        power(store, at(22, 30) + timedelta(minutes=minute), 0.0)
    store.record_capture_start("c", at(23))  # a restart in the middle: 23:00-23:30 was not seen
    for minute in range(0, 8):
        power(store, at(23) + timedelta(minutes=minute), 0.0)
    block, = run(store)["comparison"]["planned_blocks"]
    assert block["verdict"] == "unknown" and block["covered_fraction"] < 0.999 and "partial_coverage" in block["reasons"]


def test_flow_in_the_block_is_observed_and_an_isolated_spike_is_not_charging():
    store, _ = make_store()
    send(store, "p1", profile(at(22, 30), (0, 16), (3600, 0)), accepted_at=at(21))
    store.record_capture_start("c", at(22, 25))
    for minute in range(0, 60):
        power(store, at(22, 25) + timedelta(minutes=minute), 7000.0 if 10 <= minute < 30 else 0.0)
    for minute in range(60, 120):
        power(store, at(22, 25) + timedelta(minutes=minute), 6000.0 if minute == 90 else 0.0)  # one lone sample
    answer = run(store)
    interval, = answer["observed"]["intervals"]
    assert interval["samples"] == 20 and answer["observed"]["isolated_flow_samples"] == 1
    assert answer["comparison"]["planned_blocks"][0]["verdict"] == "flow_observed"
    assert answer["comparison"]["outside_plan"] == []


def test_unacknowledged_rejected_or_unanswered_versions_are_listed_but_never_the_plan_in_force():
    store, _ = make_store()
    send(store, "rej", profile(at(22), (0, 16), plan_id=2), accepted_at=at(20), status="rejected")
    send(store, "none", profile(at(22), (0, 16), plan_id=3), accepted_at=at(20), ack=False)
    store.record_capture_start("c", at(21))
    for minute in range(0, 30):
        power(store, at(22) + timedelta(minutes=minute), 7000.0)
    answer = run(store, since=at(0))
    plans = {p["id"]: p for p in answer["plans"]}
    assert plans["rej"]["acked_intent"] is False and plans["rej"]["not_acked_reason"] == "ack_not_accepted"
    assert plans["none"]["acked_intent"] is False and plans["none"]["dispatch_state"] == "unknown"
    assert answer["comparison"]["planned_blocks"] == []  # nothing applied, so no planned block...
    kinds = {item["kind"] for item in answer["comparison"]["outside_plan"]}
    assert kinds == {"no_plan_evidence"}  # ...and flow is not called "outside the plan" either


def test_later_version_and_removal_end_the_earlier_plan_without_rewriting_it():
    store, _ = make_store()
    send(store, "a", profile(at(22), (0, 16), plan_id=1), accepted_at=at(20), fiscal=FISCAL_A, prices=PRICES_A)
    send(store, "b", profile(at(23), (0, 10), plan_id=2), accepted_at=at(22, 30), fiscal=FISCAL_B, prices=PRICES_B)
    store.record_event("c", "removal", plan_id=None, at=at(25).isoformat())
    plans = {p["id"]: p for p in run(store, include_prices=True)["plans"]}
    assert plans["a"]["intent_ended_at"] == at(22, 30).isoformat() and plans["b"]["intent_ended_at"] == at(25).isoformat()
    assert plans["a"]["tariff"]["fiscal"] == FISCAL_A and plans["b"]["tariff"]["fiscal"] == FISCAL_B
    assert plans["a"]["tariff"]["captured"] == "when_this_version_was_made"
    answer = run(store, include_prices=True)
    snapshots = answer["price_snapshots"]
    assert sorted(len(v["rows"]) for v in snapshots.values()) == [1, 1] and len(snapshots) == 2
    assert {tuple(map(tuple, v["rows"]))[0][2] for v in snapshots.values()} == {0.10, 0.99}
    assert run(store)["price_snapshots"] == {}  # prices only when asked, bounded by what versions kept


# ---- tariff capture: nothing is filled in ---------------------------------------------------------------

def test_plan_tariff_snapshot_is_unknown_when_unreadable_and_never_defaulted(monkeypatch):
    from custom_components.spotnav.sessions import inputs

    def boom(*_a, **_k):
        raise RuntimeError("no market")

    monkeypatch.setattr(inputs, "price_market", boom)
    context, blobs = inputs.plan_tariff_snapshot(SimpleNamespace(), "c", NOW)
    assert context["fiscal_state"] == "unknown" and context["prices_state"] == "none" and blobs == {}
    monkeypatch.setattr(inputs, "price_market", lambda *_a: None)
    context, blobs = inputs.plan_tariff_snapshot(SimpleNamespace(), "c", NOW)
    assert context == {"fiscal_state": "unknown", "prices_state": "none", "market": None} and blobs == {}


def test_blobs_are_kept_once_per_content_bounded_and_survive_restart():
    store, backend = make_store()
    send(store, "a", profile(at(22), (0, 16), plan_id=1), accepted_at=at(20), fiscal=FISCAL_A, prices=PRICES_A)
    send(store, "b", profile(at(23), (0, 16), plan_id=2), accepted_at=at(21), fiscal=FISCAL_A, prices=PRICES_A)
    doc = store._charger("c")
    assert len(doc["blobs"]) == 2  # identical fiscal and prices content are shared, not duplicated
    backend.flush()
    again, _ = make_store(backend)
    asyncio.run(again.async_load())
    assert again.plan_version("c", "a")["blobs"]["fiscal"] == FISCAL_A  # the older version keeps its own tariff
    CLOCK["now"] = NOON + timedelta(days=ev.RETENTION_DAYS + 1)
    try:
        again.record_capture_start("c")  # prune: the versions age out and their blobs go with them
        assert again.plan_versions("c") == [] and again._charger("c")["blobs"] == {}
    finally:
        CLOCK["now"] = NOON


# ---- counters: resets, unobserved and observed meter energy are not merged ----------------------------------

def test_meter_reset_is_unknown_and_unobserved_energy_is_reported_apart_from_observed():
    store, _ = make_store()
    store.record_capture_start("c", at(22))
    for minute, kwh in ((0, 5.0), (1, 5.1), (2, 5.2), (3, 0.1), (4, 0.2)):  # a counter reset at minute 3
        power(store, at(22) + timedelta(minutes=minute), 6000.0, kwh)
    store.record_capture_start("c", at(22, 20))
    power(store, at(22, 30), 0.0, 0.9)  # 0.7 kWh arrived while capture was down: how much, not when
    energy = run(store)["observed"]["energy"]
    assert energy["meter_counter_kwh"] == pytest.approx(0.3)  # 5.0->5.2 and 0.1->0.2; the reset pair itself is unknown
    assert energy["meter_counter_unobserved_kwh"] == pytest.approx(0.7)
    assert any("counter_decrease" in key for key in energy["unknown_segments"])
    assert "never summed" in energy["note"]


# ---- retention, windows and timestamps ----------------------------------------------------------------------

def test_window_before_retained_evidence_says_so_and_empty_history_invents_nothing():
    store, _ = make_store()
    empty = run(store)
    assert empty["retention"]["oldest_evidence"] is None and empty["retention"]["window_starts_before_oldest_evidence"]
    assert empty["observed"]["intervals"] == [] and empty["comparison"] == {
        "planned_blocks": [], "outside_plan": [], "unknown_plan_spans": [],
        "basis": "acknowledged_intent_known_spans_only"}
    assert empty["observed"]["coverage"]["no_data_seconds"] == empty["observed"]["coverage"]["window_seconds"]
    store.record_capture_start("c", at(30))
    power(store, at(30), 0.0)
    partial = run(store)
    assert partial["retention"]["window_starts_before_oldest_evidence"] is True
    assert partial["retention"]["oldest_evidence"] == at(30).isoformat()


def test_digests_are_kept_once_survive_raw_retention_and_do_not_keep_price_rows():
    store, _ = night_store()
    kept = hist.compact_days(store, "c", HELSINKI, NOW)
    assert kept == ["2026-11-13"]  # the only finished local day with evidence (clock is 14 Nov 14:00 local)
    today = NOW.astimezone(HELSINKI).date().isoformat()
    assert today not in kept  # the day in progress is not digested
    digests = store.digests("c")
    first = digests[kept[0]]
    assert first["raw_prices_retained"] is False and "prices" not in str(first.get("plans_applied"))
    assert first["plans_applied"][0]["tariff"]["fiscal"] == FISCAL_A  # the tariff in force at that time survives
    assert hist.compact_days(store, "c", HELSINKI, NOW) == []  # written once, never recomputed
    assert store.keep_digest("c", kept[0], {"changed": True}) is False
    assert store.digests("c")[kept[0]] == first
    store._charger("c")["samples"][ev.KIND_POWER].clear()  # raw rows aged out: the digest still answers
    answer = run(store, since=at(12), until=at(36))
    assert [d["date"] for d in answer["digests"]] == sorted(d["date"] for d in answer["digests"]) and answer["digests"]


def test_midnight_window_and_dst_days_are_local_days_not_24_hour_guesses():
    zone = time_zones.zone("Europe/Helsinki")
    day = api._history_window({"date": "2026-10-25"}, zone)  # clocks go back: 25 local hours
    assert day[1] - day[0] == timedelta(hours=25)
    night = api._history_window({"night": "2026-11-13"}, zone)
    assert night[0] == datetime(2026, 11, 13, 10, tzinfo=UTC) and night[1] - night[0] == timedelta(hours=24)
    explicit = api._history_window({"from": "2026-11-13T22:00:00+02:00", "to": "2026-11-14T00:00:00Z"}, zone)
    assert explicit == (at(20), at(24)) and explicit[0].utcoffset() == timedelta(0)  # instants, not wall time
    for bad in ({}, {"date": "2026-11-13", "night": "2026-11-13"}, {"date": "x"}, {"date": "2026-11-13", "from": "2026-11-13T00:00:00Z"},
                {"from": "2026-11-13T00:00:00", "to": "2026-11-14T00:00:00Z"}, {"from": "bad", "to": "bad"}, {"from": "2026-11-13T00:00:00Z"}):
        with pytest.raises(api.SessionsRefusal) as refusal:
            api._history_window(bad, zone)
        assert refusal.value.code == api.ERROR_INVALID_RANGE


# ---- API: permissions, refusals, read-only ------------------------------------------------------------------

def hass_with(store, sessions=()):
    hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Helsinki"), data={})
    return hass, store, sessions


def test_history_answer_refuses_bad_windows_unavailable_evidence_and_never_writes(monkeypatch):
    store, backend = night_store()
    hass, *_ = hass_with(store)
    monkeypatch.setattr(api, "evidence_for", lambda _h: store)
    monkeypatch.setattr(api, "domain_data", lambda _h: SimpleNamespace(session_store=None))
    before = repr(store._charger("c"))
    answer = api.charging_history_answer(hass, "c", {"night": "2026-11-13"})
    assert answer["api_version"] == hist.HISTORY_API_VERSION and answer["sessions"] == []
    assert repr(store._charger("c")) == before and backend.func is not None  # a query changes nothing
    for bad in ({"date": "2026-11-13", "include_prices": "yes"}, {"from": "2026-11-01T00:00:00Z", "to": "2026-11-20T00:00:00Z"},
                {"from": "2026-11-14T00:00:00Z", "to": "2026-11-13T00:00:00Z"}):
        with pytest.raises(api.SessionsRefusal) as refusal:
            api.charging_history_answer(hass, "c", bad)
        assert refusal.value.code == api.ERROR_INVALID_RANGE
    monkeypatch.setattr(api, "evidence_for", lambda _h: None)
    with pytest.raises(api.SessionsRefusal) as refusal:
        api.charging_history_answer(hass, "c", {"date": "2026-11-13"})
    assert refusal.value.code == api.ERROR_HISTORY_UNAVAILABLE


def test_websocket_handler_checks_version_and_charger_and_is_open_to_any_authenticated_user(monkeypatch):
    sent = []
    connection = SimpleNamespace(send_error=lambda *a: sent.append(("error", *a)),
                                 send_result=lambda *a: sent.append(("result", *a)), user=SimpleNamespace(is_admin=False))
    handler = api.websocket_get_charging_history
    assert hasattr(handler, "__wrapped__")

    def run_ws(msg):
        return asyncio.run(handler.__wrapped__(SimpleNamespace(), connection, msg))

    run_ws({"id": 1, "type": "spotnav/get_charging_history", "api_version": 2, "charger_id": "c", "date": "2026-11-13"})
    run_ws({"id": 2, "type": "spotnav/get_charging_history", "api_version": True, "charger_id": "c", "date": "2026-11-13"})
    assert [item[0] for item in sent] == ["error", "error"]
    store, _ = night_store()
    monkeypatch.setattr(api, "resolve_charger_request", lambda *_a: SimpleNamespace(entry_id="c"))
    monkeypatch.setattr(api, "evidence_for", lambda _h: store)
    monkeypatch.setattr(api, "domain_data", lambda _h: SimpleNamespace(session_store=None))
    monkeypatch.setattr(api, "dt_util", SimpleNamespace(utcnow=lambda: NOW))
    monkeypatch.setattr(api, "local_zone", lambda _h: HELSINKI)
    sent.clear()
    run_ws({"id": 3, "type": "spotnav/get_charging_history", "api_version": 1, "charger_id": "c", "night": "2026-11-13"})
    assert sent[0][0] == "result" and sent[0][2]["comparison"]["planned_blocks"]  # a non-admin may read (as sessions)
    sent.clear()
    run_ws({"id": 4, "type": "spotnav/get_charging_history", "api_version": 1, "charger_id": "c", "night": "bad"})
    assert sent[0][0] == "error" and sent[0][2] == api.ERROR_INVALID_RANGE
    assert "profile" not in sent and "chargingSchedule" not in str(answer_keys(store))  # raw profiles are not exposed


def answer_keys(store):
    answer = run(store)
    return [key for plan in answer["plans"] for key in plan]


# ---- production wiring --------------------------------------------------------------------------------------

def test_send_path_keeps_the_tariff_in_force_with_the_version(monkeypatch):
    from custom_components.spotnav.api import morek_schedule as ms
    from custom_components.spotnav.sessions import inputs

    monkeypatch.setattr(inputs, "plan_tariff_snapshot", lambda *_a: (
        {"fiscal_state": "resolved", "prices_state": "published", "market": {"area_id": "FI"}},
        {"fiscal": FISCAL_A, "prices": {"rows": PRICES_A}}))
    captured = {}
    monkeypatch.setattr(ms, "_evidence_call", lambda hass, entry, name, **kw: captured.update(kw, name=name))
    hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Helsinki"))
    ms._evidence_plan(hass, "c", {"id": "x", "fingerprint": "f", "at": "t", "source": "worker", "revision": 1}, {"p": 1})
    assert captured["name"] == "record_plan" and captured["blobs"]["fiscal"] == FISCAL_A
    assert captured["context"]["time_zone"] == "Europe/Helsinki" and captured["context"]["fiscal_state"] == "resolved"
    monkeypatch.setattr(inputs, "plan_tariff_snapshot", lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
    ms._evidence_plan(hass, "c", {"id": "y", "fingerprint": "f", "at": "t", "source": "worker"}, {"p": 1})
    assert captured["context"]["fiscal_state"] == "unknown" and captured["blobs"] == {}  # never alters the send


# ---- acknowledged intent is not proof of the effective profile ------------------------------------------------

def flow_night(store, start_min=40, minutes=20):
    store.record_capture_start("c", at(22, 25))
    for minute in range(0, 100):
        power(store, at(22, 25) + timedelta(minutes=minute), 7000.0 if start_min - 25 <= minute < start_min - 25 + minutes else 0.0)


def test_ack_then_unknown_upload_ends_what_is_known_and_flow_after_it_is_plan_unknown():
    store, _ = make_store()
    send(store, "p1", profile(at(22, 30), (0, 16), (3600, 0)), accepted_at=at(21))
    store.record_plan("c", plan_id="p2", fingerprint="f-p2", profile=profile(at(22, 30), (0, 6), plan_id=2),
                      intent_at=at(22).isoformat(), source="worker", intent="schedule", revision=2)
    store.record_event("c", "dispatch_started", plan_id="p2", at=at(22).isoformat())  # no answer: maybe written
    store.record_readback("c", {"status": "Accepted", "fetched_at": at(22, 10).isoformat(),
                                "periods": [{"startPeriod": 0, "limit": 16}]}, plan_id="p1")
    flow_night(store)
    answer = run(store, since=at(0))
    plans = {p["id"]: p for p in answer["plans"]}
    p1 = plans["p1"]
    assert p1["acked_intent"] is True and p1["acked_at"] == at(21).isoformat()
    assert p1["known_until"] == at(22).isoformat() and p1["unknown_from"] == at(22).isoformat()
    assert p1["unknown_reason"] == "dispatch_started" and p1["intent_ended_at"] is None
    assert plans["p2"]["acked_intent"] is False and plans["p2"]["dispatch_state"] == "dispatch_started"
    assert p1["readbacks"]["count"] == 1 and "not installed-profile inventory" in p1["readbacks"]["note"]  # no restore
    assert answer["comparison"]["planned_blocks"] == []  # the block begins inside the unknown span: never compared
    assert [s["reason"] for s in answer["comparison"]["unknown_plan_spans"]] == ["dispatch_started"]
    kinds = {item["kind"] for item in answer["comparison"]["outside_plan"]}
    assert kinds == {"plan_unknown"}  # neither "outside the plan" nor "no plan evidence"
    assert "last acknowledged intent" in answer["provenance"]["plan_intent"]
    assert "inventory" in answer["provenance"]["readback"]


def test_a_later_accepted_ack_restores_known_intent_and_a_block_cut_short_is_flagged():
    store, _ = make_store()
    send(store, "p1", profile(at(22), (0, 16), (7200, 0)), accepted_at=at(20))  # block 22:00-24:00
    store.record_event("c", "dispatch_started", plan_id=None, at=at(23).isoformat())  # orphan marker: version not kept
    store.record_capture_start("c", at(21, 50))
    for minute in range(0, 130):
        power(store, at(21, 50) + timedelta(minutes=minute), 0.0)
    answer = run(store)
    block, = answer["comparison"]["planned_blocks"]
    assert block["end"] == at(23).isoformat() and block["intent_uncertain_after"] == at(23).isoformat()
    assert answer["plans"][0]["unknown_reason"] == "dispatch_evidence_for_unretained_version"
    send(store, "p3", profile(at(23, 30), (0, 10), plan_id=3), accepted_at=at(23, 20))  # answered after the unknown
    plans = {p["id"]: p for p in run(store)["plans"]}
    assert plans["p1"]["intent_ended_at"] == at(23, 20).isoformat()  # the unknown span ended by the newer ACK
    assert plans["p3"]["acked_intent"] is True and plans["p3"]["unknown_from"] is None
    assert plans["p3"]["earlier_context_retained"] is True and plans["p1"]["earlier_context_retained"] is False


def test_pruned_version_events_and_restarts_never_extend_certainty():
    store, _ = make_store()
    store.record_plan("c", plan_id="lost", fingerprint="f-lost", profile=profile(at(22), (0, 16), plan_id=9),
                      intent_at=at(19).isoformat(), source="worker", intent="schedule")  # its events were never kept
    send(store, "p1", profile(at(22, 30), (0, 16), (3600, 0)), accepted_at=at(21))
    store.record_capture_start("c", at(21, 30))  # HA restarted after the ACK: nothing says the charger still holds it
    flow_night(store)
    answer = run(store)
    p1 = {p["id"]: p for p in answer["plans"]}["p1"]
    assert p1["acked_intent"] is True and p1["restarts_after_ack"] == 2 and p1["earlier_context_retained"] is True
    assert [s["reason"] for s in answer["comparison"]["unknown_plan_spans"]] == ["events_not_retained_for_version"]
    block, = answer["comparison"]["planned_blocks"]
    assert block["verdict"] == "flow_observed" and block["intent_uncertain_after"] is None


def test_block_before_retained_evidence_is_unknown_not_no_flow():
    store, _ = make_store()
    send(store, "p1", profile(at(2), (0, 16), (3600, 0)), accepted_at=at(1))  # block 02:00-03:00
    store.record_capture_start("c", at(2, 20))  # the oldest raw row: the first 20 minutes were pruned or never seen
    for minute in range(0, 50):
        power(store, at(2, 20) + timedelta(minutes=minute), 0.0)
    block, = run(store, since=at(0), until=at(6))["comparison"]["planned_blocks"]
    assert block["verdict"] == "unknown" and "partial_coverage" in block["reasons"]
    store2, _ = make_store()
    send(store2, "p1", profile(at(2), (0, 16), (3600, 0)), accepted_at=at(1))
    block2, = run(store2, since=at(0), until=at(6))["comparison"]["planned_blocks"]
    assert block2["verdict"] == "unknown" and "no_power_samples" in block2["reasons"]


def test_energy_absent_data_is_null_with_coverage_and_a_measured_zero_is_zero():
    store, _ = make_store()
    empty = run(store)["observed"]["energy"]
    assert empty["meter_counter_kwh"] is None and empty["meter_counter_unobserved_kwh"] is None
    assert empty["power_integrated_estimate_kwh"] is None
    assert empty["coverage"] == {name: {"segments": 0, "seconds": 0} for name in ("meter", "unobserved", "power")}
    store.record_capture_start("c", at(22))  # a restart alone is not a measurement either
    only_gap = run(store)["observed"]["energy"]
    assert only_gap["power_integrated_estimate_kwh"] is None and only_gap["meter_counter_kwh"] is None
    for minute in range(0, 10):  # a real measured zero: idle at a constant register
        power(store, at(22) + timedelta(minutes=minute), 0.0, 5.0)
    zero = run(store)["observed"]["energy"]
    assert zero["power_integrated_estimate_kwh"] == 0.0 and zero["meter_counter_kwh"] == 0.0
    assert zero["coverage"]["power"]["segments"] == 9 and zero["coverage"]["meter"]["segments"] == 9
    assert zero["meter_counter_unobserved_kwh"] is None  # no restart span between samples: nothing to report as zero
    assert "not zero" in zero["note"]
