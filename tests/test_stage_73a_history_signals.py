"""Stage 7.3a: the additive truncation/retention signals of `charging_history` (API version stays 1).

Real evidence store and history builder; nothing here shows the installed Morek or that a car charged.
Run: python tools/run_isolated_logs_tests.py tests/test_stage_73a_history_signals.py
"""

from __future__ import annotations

from datetime import timedelta, timezone
from types import SimpleNamespace

from custom_components.spotnav.sessions import evidence as ev
from custom_components.spotnav.sessions import history as hist

from .test_stage_63_history import NOW, at, make_store, power, profile, run, send

LISTS = ("plans", "intervals", "gaps", "restarts", "planned_blocks", "outside_plan", "unknown_plan_spans", "sessions")


def session(index: int, *, slices: int = 1):
    start = at(12) + timedelta(minutes=index * 3)
    return SimpleNamespace(
        id=f"s{index}", start=start, end=start + timedelta(minutes=2), energy_kwh=1.0, energy_source="register",
        source="morek", started_by="auto", area_id="FI", late=None, register_pair=None,
        intervals=[SimpleNamespace(start=start, end=start + timedelta(seconds=1), kwh=0.001, eur_per_kwh=0.1, fx=1.0)
                   for _ in range(slices)])


def flow_bursts(store, count: int, *, origin=None, step: int = 3) -> None:
    """`count` separate measured flow intervals: two flow samples, then an idle one."""
    origin = origin or at(0)
    for index in range(count):
        base = origin + timedelta(minutes=index * step)
        power(store, base, 5000.0)
        power(store, base + timedelta(minutes=1), 5000.0)
        power(store, base + timedelta(minutes=2), 0.0)


def test_every_capped_list_reports_truncation_and_the_cut_count_without_dropping_silently(monkeypatch):
    store, _ = make_store()
    flow_bursts(store, 234)  # 234 intervals > 200; the real store keeps all of them below its 4320-row cap
    for index in range(210):  # separate explicit gaps (consecutive gap rows would be coalesced, so samples sit between)
        when = at(12) + timedelta(minutes=index * 2)
        power(store, when, 0.0)
        store.record_gap("c", ev.KIND_POWER, "unreadable", received_at=when + timedelta(minutes=1))
    sessions = tuple(session(i, slices=205 if i == 0 else 1) for i in range(205))
    answer = run(store, since=at(0), until=at(24), sessions=sessions)
    monkeypatch.setattr(hist, "MAX_ROWS", 100000)
    full = run(store, since=at(0), until=at(24), sessions=sessions)  # the same data uncut: the true totals
    monkeypatch.undo()
    assert full["truncated"]["intervals"]["truncated"] is False
    total = len(full["observed"]["intervals"])
    assert total > 200
    truncated = answer["truncated"]
    assert set(truncated) == set(LISTS) | {"price_slices"}
    assert answer["plans_truncated"] is False and truncated["plans"] == {"truncated": False, "cut": 0, "limit": 200}
    assert len(answer["observed"]["intervals"]) == 200
    assert truncated["intervals"] == {"truncated": True, "cut": total - 200, "limit": 200}
    for name, rows in (("gaps", answer["observed"]["gaps"]), ("sessions", answer["sessions"])):
        assert len(rows) == 200 and truncated[name]["truncated"] and truncated[name]["limit"] == 200, name
    assert truncated["gaps"]["cut"] == len(full["observed"]["gaps"]) - 200 >= 10 and truncated["sessions"]["cut"] == 5
    assert truncated["restarts"] == {"truncated": False, "cut": 0, "limit": 200}  # the store keeps <= 100 capture marks
    first = answer["sessions"][0]
    assert len(first["price_slices"]) == 200 and first["price_slices_truncated"] and first["price_slices_cut"] == 5
    assert answer["sessions"][1]["price_slices_truncated"] is False and answer["sessions"][1]["price_slices_cut"] == 0
    assert truncated["price_slices"] == {"truncated": True, "cut": 5, "limit": 200, "per": "session", "sessions": ["s0"]}
    assert truncated["planned_blocks"] == {"truncated": False, "cut": 0, "limit": 200}  # untouched lists say false/0


def test_plans_flag_mirrors_plans_truncated_when_the_version_list_is_cut(monkeypatch):
    store, _ = make_store()
    monkeypatch.setattr(hist, "MAX_ROWS", 3)
    for index in range(5):
        accepted = at(0) + timedelta(minutes=index * 5)
        send(store, f"p{index}", profile(accepted + timedelta(minutes=1), (0, 16), (60, 0), plan_id=index + 1),
             accepted_at=accepted)
    answer = run(store, since=at(0), until=at(24))
    assert answer["plans_truncated"] is True and len(answer["plans"]) == 3
    assert answer["truncated"]["plans"] == {"truncated": True, "cut": 2, "limit": 3}
    assert answer["truncated"]["planned_blocks"]["cut"] == 5 - len(answer["comparison"]["planned_blocks"])
    assert answer["truncated"]["planned_blocks"]["truncated"] is (len(answer["comparison"]["planned_blocks"]) == 3)


def test_restart_list_is_counted_before_the_cut(monkeypatch):
    store, _ = make_store()
    monkeypatch.setattr(hist, "MAX_ROWS", 2)
    for index in range(5):
        store.record_capture_start("c", at(1) + timedelta(minutes=index))
    answer = run(store, since=at(0), until=at(6))
    assert len(answer["observed"]["capture_restarts"]) == 2
    assert answer["truncated"]["restarts"] == {"truncated": True, "cut": 3, "limit": 2}


def test_outside_plan_and_interval_cut_counts_come_from_the_full_lists(monkeypatch):
    store, _ = make_store()
    monkeypatch.setattr(hist, "MAX_ROWS", 2)
    flow_bursts(store, 5, step=10)  # no plan known at all: every interval is `no_plan_evidence` flow
    answer = run(store, since=at(0), until=at(6))
    truncated = answer["truncated"]
    assert len(answer["observed"]["intervals"]) == 2 and truncated["intervals"] == {"truncated": True, "cut": 3, "limit": 2}
    assert len(answer["comparison"]["outside_plan"]) == 2
    assert truncated["outside_plan"] == {"truncated": True, "cut": 3, "limit": 2}
    assert {row["kind"] for row in answer["comparison"]["outside_plan"]} == {"no_plan_evidence"}


def test_unknown_plan_spans_are_counted_before_the_cut(monkeypatch):
    store, _ = make_store()
    monkeypatch.setattr(hist, "MAX_ROWS", 1)
    for index in range(3):  # accepted, then an unanswered dispatch marker: known, then unknown spans, repeatedly
        at_time = at(0) + timedelta(hours=index * 2)
        send(store, f"a{index}", profile(at_time, (0, 16), (60, 0), plan_id=index + 1), accepted_at=at_time)
        send(store, f"u{index}", profile(at_time, (0, 16), (60, 0), plan_id=index + 11), accepted_at=at_time + timedelta(hours=1),
             ack=False)
        store.record_event("c", "dispatch_started", plan_id=f"u{index}", at=(at_time + timedelta(hours=1)).isoformat())
    answer = run(store, since=at(0), until=at(24))
    spans = answer["comparison"]["unknown_plan_spans"]
    assert len(spans) == 1
    assert answer["truncated"]["unknown_plan_spans"]["truncated"] is True and answer["truncated"]["unknown_plan_spans"]["cut"] >= 1


def test_oldest_by_kind_is_the_earliest_retained_row_of_each_kind_not_the_overall_oldest_evidence():
    store, _ = make_store()
    send(store, "p1", profile(at(2), (0, 16), (3600, 0)), accepted_at=at(1))  # a plan older than every power row
    store.record_capture_start("c", at(1))
    for minute in range(0, 20):
        power(store, at(5) + timedelta(minutes=minute), 0.0, 1.0)
    answer = run(store, since=at(1, 30), until=at(8))
    retention = answer["retention"]
    by_kind = retention["oldest_by_kind"]
    assert set(by_kind) == set(ev.SAMPLE_KINDS)
    assert by_kind[ev.KIND_POWER] == at(5).isoformat() and by_kind[ev.KIND_REGISTER] == at(5).isoformat()
    assert by_kind[ev.KIND_CURRENT] is None and by_kind[ev.KIND_STATUS] is None  # nothing retained: null, not a time
    # the plan and capture start make the overall oldest evidence earlier than any power row
    assert retention["oldest_evidence"] < by_kind[ev.KIND_POWER]
    assert retention["window_starts_before_oldest_evidence"] is False  # the guess the new signal replaces
    block, = answer["comparison"]["planned_blocks"]
    assert block["verdict"] == "unknown" and "block_starts_before_retained_power" in block["reasons"]
    assert retention["limits"] == {"max_samples_per_kind": ev.MAX_SAMPLES_PER_KIND, "max_age_days": ev.RETENTION_DAYS,
                                   "max_digest_days": ev.MAX_DIGEST_DAYS}


def test_a_gap_row_is_not_a_retained_sample_and_an_empty_store_has_no_oldest():
    store, _ = make_store()
    assert run(store)["retention"]["oldest_by_kind"] == dict.fromkeys(ev.SAMPLE_KINDS)
    store.record_gap("c", ev.KIND_POWER, "unreadable", received_at=at(3))
    assert run(store)["retention"]["oldest_by_kind"][ev.KIND_POWER] is None
    power(store, at(4), 0.0)
    assert run(store)["retention"]["oldest_by_kind"][ev.KIND_POWER] == at(4).isoformat()


def test_digest_days_list_every_kept_digest_even_when_the_window_is_elsewhere():
    store, _ = make_store()
    for minute in range(0, 30):
        power(store, at(1) + timedelta(minutes=minute), 7000.0)
    assert hist.compact_days(store, "c", timezone.utc, NOW) == ["2026-11-13"]
    far = run(store, since=at(24 * 5), until=at(24 * 6))
    assert far["retention"]["digest_days"] == ["2026-11-13"] and far["digests"] == []  # not repeated for another window
    store._charger("c")["samples"][ev.KIND_POWER].clear()
    gone = run(store)
    assert gone["retention"]["oldest_by_kind"][ev.KIND_POWER] is None
    assert gone["retention"]["digest_days"] == ["2026-11-13"] and len(gone["digests"]) == 1


def test_existing_sections_and_flags_are_unchanged_by_the_signals():
    store, _ = make_store()
    answer = run(store)
    assert answer["api_version"] == 1 and answer["plans"] == [] and answer["plans_truncated"] is False
    assert "oldest_evidence" in answer["retention"] and "window_starts_before_oldest_evidence" in answer["retention"]
    assert answer["sessions"] == [] and answer["truncated"]["sessions"]["truncated"] is False


# ---- the wire shape the shared client and the preview fixtures are written against ---------------------------------

def _shape(answer: dict) -> dict:
    def keys(rows):
        return sorted({key for row in rows for key in row})

    return {
        "top": sorted(answer), "window": sorted(answer["window"]), "retention": sorted(answer["retention"]),
        "oldest_by_kind": sorted(answer["retention"]["oldest_by_kind"]), "limits": sorted(answer["retention"]["limits"]),
        "truncated": sorted(answer["truncated"]), "truncated_row": sorted(answer["truncated"]["intervals"]),
        "price_slices_signal": sorted(answer["truncated"]["price_slices"]),
        "observed": sorted(answer["observed"]), "coverage": sorted(answer["observed"]["coverage"]),
        "energy": sorted(answer["observed"]["energy"]), "interval": keys(answer["observed"]["intervals"]),
        "gap": keys(answer["observed"]["gaps"]), "comparison": sorted(answer["comparison"]),
        "block": keys(answer["comparison"]["planned_blocks"]), "outside": keys(answer["comparison"]["outside_plan"]),
        "unknown_span": keys(answer["comparison"]["unknown_plan_spans"]), "session": keys(answer["sessions"]),
        "reconciliation": keys([row["reconciliation"] for row in answer["sessions"]]),
    }


def test_the_wire_shape_matches_the_committed_fixture_contract():
    """`frontend/prototype/history-day-fixture.js` is checked against the same file (`history-day-fixture.test.ts`)."""
    import json
    from pathlib import Path

    from .test_stage_63_history import night_store

    store, _ = night_store()
    store.record_gap("c", ev.KIND_POWER, "unreadable", received_at=at(23, 50))
    send(store, "p2", profile(at(23, 0), (0, 16), (600, 0), plan_id=2), accepted_at=at(22, 40), ack=False)
    store.record_event("c", "dispatch_started", plan_id="p2", at=at(22, 40).isoformat())
    evaluated = session(2)
    evaluated.late = {"state": "uncertain", "reason": "late_register_unassigned", "total_kwh": None, "unplaced_late_kwh": 1.0,
                      "placement": None, "placement_reasons": [], "register_open_kwh": 1.0, "register_close_kwh": 2.0,
                      "unassigned_register_kwh": 0.5, "source": None, "quality": [], "final": False, "evaluated_at": at(23).isoformat()}
    answer = run(store, sessions=(session(1), evaluated))
    assert answer["comparison"]["unknown_plan_spans"] and answer["comparison"]["outside_plan"] and answer["observed"]["gaps"]
    path = Path(__file__).parent / "fixtures" / "history" / "answer_shape.json"
    assert json.loads(path.read_text(encoding="utf-8")) == _shape(answer)
