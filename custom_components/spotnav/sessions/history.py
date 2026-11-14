"""Stage 6.3: bounded history queries over the charging evidence store, session store and plan-time tariffs.

Everything here is read-only and answers from what was actually retained; nothing is filled in:

* **Plan versions** keep their own tariff/price context (`blobs`, written when the version was made), so an older
  night is never re-priced or re-planned with today's settings. A version `applies` only from the moment the charger
  *answered* its upload with `accepted` (dispatch state `ack_received`): the **last acknowledged intent**, never proof
  of the profile in force. It is known only until the next accepted ACK, a recorded removal, or the first retained
  uncertain write (dispatch marker with no answer, conflict, ACK of `unknown`, events of a pruned version, a version
  whose events are gone); after that the plan is `unknown`, not carried forward. A writer outside SpotNav or a restart
  leaves no event, so it is only reported (`restarts_after_ack`), not detected. A version that was only recorded,
  aborted, rejected or never answered is listed but never treated as acknowledged; an ACK or an effective-limit
  readback is not evidence of charging or an inventory of installed profiles.
* **Observed charging intervals** come only from genuine measured power samples (`power_w`) that the 6.2 capture marked
  trustworthy (no recorded gap or capture restart between, not stale/future/out-of-order/conflicting, one source and
  unit, <= 660 s apart). A sample is *flow* at or above `MIN_FLOW_W` (an assumed noise threshold, not verified against
  the Morek); an interval needs `DEBOUNCE_SAMPLES` consecutive flow samples, so a lone spike is counted as isolated
  and never as charging. Start and end are reported as the earliest/latest the data allows (the sample resolution),
  and an edge next to a gap, restart or the start/end of the data is *unbounded*, not guessed. Current and connector
  status never create an interval; schedules, offered limits and ACKs never do either.
* **Energy** is reported by basis and never merged (a basis with no segment in the window is null, not 0): meter-counter deltas (observed vs. unobserved placement), power
  integration estimates, and unknown segments with reasons. Segments overlapping the window edge are listed, not
  pro-rated.
* **Comparison**: each planned block (limit above 0, from a version with a known acknowledged intent) is `flow_observed`,
  `no_flow_observed` (only if measured samples cover the whole block and show none) or `unknown`. Observed flow
  outside every known acknowledged-intent window (plus `EDGE_TOLERANCE_S`) is `outside_plan`; flow in an unknown span
  is `plan_unknown`; flow where no acknowledged version is known is `no_plan_evidence`, never "outside the plan".
* **Digests**: once a local day is over, a compact summary is kept (`compact_days`) after the raw rows' retention ends.
  A digest is written once and never replaced; it keeps the fiscal choice of the plan in force but not the price rows.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Final

from .evidence import (
    BASIS_METER,
    BASIS_POWER,
    BASIS_UNKNOWN,
    DISPATCH_ABORTED,
    DISPATCH_ACK_RECEIVED,
    KIND_POWER,
    KIND_REGISTER,
    MAX_POWER_GAP_S,
    SAMPLE_KINDS,
    ChargingEvidenceStore,
    _iso,
    _parse,
)
from .reconcile import public as reconcile_public

HISTORY_API_VERSION: Final = 1
#: A power sample at or above this is flow (assumed noise floor; unverified for the installed charger).
MIN_FLOW_W: Final = 100.0
#: Consecutive flow samples needed before an interval exists.
DEBOUNCE_SAMPLES: Final = 2
#: Flow this close outside a plan window is not reported as outside (command and sampling lag).
EDGE_TOLERANCE_S: Final = 120
#: A meter delta below this is not flow evidence.
MIN_METER_KWH: Final = 0.01
MAX_SPAN: Final = timedelta(days=7)
MAX_ROWS: Final = 200
#: A finished local day is digested only this long after it ended, so the last samples have been captured.
DIGEST_SETTLE: Final = timedelta(minutes=15)
MAX_DIGEST_LOOKBACK_DAYS: Final = 14

Span = tuple[datetime, datetime]
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---- interval helpers --------------------------------------------------------------------------------------------

def _union(spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _clip(spans: list[Span], start: datetime, end: datetime) -> list[Span]:
    return [(max(a, start), min(b, end)) for a, b in spans if min(b, end) > max(a, start)]


def _seconds(spans: list[Span]) -> float:
    return sum((b - a).total_seconds() for a, b in _union(spans))


def _subtract(spans: list[Span], cuts: list[Span]) -> list[Span]:
    out = list(spans)
    for cut_start, cut_end in _union(cuts):
        nxt: list[Span] = []
        for a, b in out:
            if cut_end <= a or cut_start >= b:
                nxt.append((a, b))
                continue
            if a < cut_start:
                nxt.append((a, cut_start))
            if cut_end < b:
                nxt.append((cut_end, b))
        out = nxt
    return out


# ---- plan versions -----------------------------------------------------------------------------------------------

def planned_windows(profile: Any) -> tuple[list[dict[str, Any]], bool]:
    """The charging blocks (limit above 0) an Absolute profile describes, and whether it could be read.

    The last period is open-ended (`end` is `None`): the profile gives no end, so none is invented."""
    try:
        schedule = profile["chargingSchedule"]
        start = _parse(schedule["startSchedule"])
        periods = sorted(({"o": int(item["startPeriod"]), "l": float(item["limit"])}
                          for item in schedule["chargingSchedulePeriod"]), key=lambda item: item["o"])
        unit = schedule.get("chargingRateUnit", "A")
    except (KeyError, TypeError, ValueError, IndexError):
        return [], False
    if start is None or not periods:
        return [], False
    out = []
    for index, period in enumerate(periods):
        if period["l"] <= 0:
            continue
        nxt = periods[index + 1]["o"] if index + 1 < len(periods) else None
        out.append({"start": start + timedelta(seconds=period["o"]),
                    "end": None if nxt is None else start + timedelta(seconds=nxt),
                    "limit": period["l"], "unit": unit})
    return out, True


def _event_time(item: dict[str, Any] | None, fallback: Any = None) -> datetime | None:
    return _parse((item or {}).get("at")) or _parse(fallback)


def _plan_rows(store: ChargingEvidenceStore, charger_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every kept version, and the timeline of what the events support (never from a version alone).

    A version is `acked_intent` only if the charger answered its upload `accepted`. That is the *last acknowledged
    intent*, not proof of the profile in force: an uncertain newer write (a dispatch marker without an answer, an
    abort/answer conflict, an ACK of `unknown`, dispatch events whose version was pruned, a version whose events are
    gone), a writer outside this integration or a restart can each have changed it without leaving an answer. The
    first retained such event after an ACK ends the *known* span there; until the next accepted ACK or removal the
    plan is `unknown`. Events are ordered by recording sequence, not by their (possibly unreadable) times.
    """
    all_events = store.events(charger_id)
    versions = store.plan_versions(charger_id)
    kept_ids = {plan["id"] for plan in versions}
    seqs = [item["seq"] for item in all_events if isinstance(item.get("seq"), int)]
    oldest_event_seq = min(seqs, default=None)
    markers: list[tuple[int, str, dict[str, Any]]] = []
    for item in all_events:
        if not isinstance(item.get("seq"), int):
            continue
        if item.get("kind") == "removal":
            markers.append((item["seq"], "removal", {"at": _parse(item.get("at"))}))
        elif item.get("kind") in ("dispatch_started", "ack") and item.get("plan_id") not in kept_ids:
            markers.append((item["seq"], "uncertain", {"at": _parse(item.get("at")),
                                                       "reason": "dispatch_evidence_for_unretained_version"}))
    rows = []
    for plan in versions:
        state = store.dispatch_state(charger_id, plan["id"])
        own = store.events(charger_id, plan_id=plan["id"])
        acks = [item for item in own if item.get("kind") == "ack" and item.get("status") not in (None, "", "unknown")]
        ack = acks[-1] if acks else None
        answered = str(ack.get("status")).lower() if ack else None
        accepted_at = _parse(ack.get("at")) if answered == "accepted" else None
        windows, readable = planned_windows(plan.get("profile"))
        reason = None
        if state != DISPATCH_ACK_RECEIVED:
            reason = f"dispatch_{state}"
        elif accepted_at is None:
            reason = "ack_not_accepted" if answered != "accepted" else "ack_time_unreadable"
        elif not readable:
            reason = "profile_unreadable"
        ack_seq = ack.get("seq") if ack else None
        marks = [item for item in own if item.get("kind") in ("dispatch_started", "ack") and isinstance(item.get("seq"), int)]
        if reason is None and isinstance(ack_seq, int):
            markers.append((ack_seq, "accepted", {"id": plan["id"], "at": accepted_at}))
        elif state == DISPATCH_ABORTED or (state == DISPATCH_ACK_RECEIVED and answered != "accepted"):
            pass  # stopped before the call, or the charger refused it: it installed nothing
        elif marks:  # accepted but unusable, a marker with no answer, a conflict, or an ACK of unknown: may have written
            first = min(marks, key=lambda item: item["seq"])
            markers.append((first["seq"], "uncertain", {"at": _event_time(first, plan.get("recorded_at")),
                                                        "reason": state if state != DISPATCH_ACK_RECEIVED else (reason or state)}))
        elif not own and oldest_event_seq is not None and isinstance(plan.get("seq"), int) and plan["seq"] < oldest_event_seq:
            markers.append((plan["seq"], "uncertain", {"at": _parse(plan.get("recorded_at")),
                                                       "reason": "events_not_retained_for_version"}))
        readbacks = [item for item in own if item.get("kind") == "readback"]
        context = plan.get("context") or {}
        rows.append({
            "id": plan["id"], "seq": plan.get("seq"), "recorded_at": plan.get("recorded_at"),
            "intent_at": plan.get("intent_at"), "source": plan.get("source"), "intent": plan.get("intent"),
            "revision": plan.get("revision"), "fingerprint": plan.get("fingerprint"),
            "dispatch_state": state, "ack_status": None if ack is None else ack.get("status"),
            "ack_at": None if ack is None else ack.get("at"),
            "readbacks": {"count": len(readbacks), "last_at": readbacks[-1].get("at") if readbacks else None,
                          "note": "effective-limit readback; not installed-profile inventory or charging"},
            "profile_readable": readable, "acked_intent": reason is None, "not_acked_reason": reason,
            "acked_at": None if reason else _iso(accepted_at),
            "intent_ended_at": None, "known_until": None, "unknown_from": None, "unknown_reason": None,
            "earlier_context_retained": False, "restarts_after_ack": None,
            "windows": [{"start": _iso(w["start"]), "end": None if w["end"] is None else _iso(w["end"]),
                         "limit": w["limit"], "unit": w["unit"]} for w in windows],
            "tariff": {
                "time_zone": context.get("time_zone"), "market": context.get("market"),
                "fiscal_state": context.get("fiscal_state", "unknown"),
                "prices_state": context.get("prices_state", "none"),
                "fiscal": plan["blobs"].get("fiscal"), "prices_ref": (plan.get("refs") or {}).get("prices"),
                "captured": "when_this_version_was_made",
            },
            "_windows": windows, "_accepted_at": accepted_at, "_prices": plan["blobs"].get("prices"),
        })
    by_id = {row["id"]: row for row in rows}
    timeline: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def close(at: datetime | None, final: bool = False) -> None:
        nonlocal current
        if current is not None:
            current["end"] = None if at is None and final else (at if at is not None and at >= current["start"] else current["start"])
            timeline.append(current)
            current = None

    for seq, kind, data in sorted(markers, key=lambda item: item[0]):
        when = data.get("at")
        if kind == "accepted":
            close(when)
            current = {"state": "known", "version": data["id"], "start": when, "end": None, "reason": None, "seq": seq}
        elif kind == "uncertain":
            if current is None or current["state"] == "known":
                was_known = current is not None
                close(when)
                current = {"state": "unknown", "version": None, "reason": data["reason"], "end": None, "seq": seq,
                           "start": timeline[-1]["end"] if was_known else (when or _EPOCH)}
        else:  # a recorded removal clears what was acknowledged; nothing is claimed about what follows it
            close(when)
    close(None, final=True)
    restarts = [when for when in (_parse(at) for at in store.capture_starts(charger_id)) if when is not None]
    for index, seg in enumerate(timeline):
        if seg["state"] != "known":
            continue
        row = by_id[seg["version"]]
        nxt = timeline[index + 1] if index + 1 < len(timeline) else None
        row["earlier_context_retained"] = index > 0 and any(prev["seq"] < seg["seq"] for prev in timeline[:index])
        row["restarts_after_ack"] = sum(1 for at in restarts if at > seg["start"] and (seg["end"] is None or at < seg["end"]))
        if seg["end"] is not None:
            row["known_until"] = _iso(seg["end"])
            if nxt is not None and nxt["state"] == "unknown" and nxt["start"] == seg["end"]:
                row["unknown_from"], row["unknown_reason"] = _iso(nxt["start"]), nxt["reason"]
                row["intent_ended_at"] = None if nxt["end"] is None else _iso(nxt["end"])
            else:
                row["intent_ended_at"] = _iso(seg["end"])
        row["_span"] = (seg["start"], seg["end"])
    spans = [{"state": seg["state"], "version": seg["version"], "reason": seg["reason"], "start": seg["start"],
              "end": seg["end"]} for seg in timeline]
    return rows, spans


# ---- measured flow -----------------------------------------------------------------------------------------------

def _watts(value: float, unit: Any) -> float:
    return value * 1000.0 if unit == "kW" else value


def _chains(segments: list[dict[str, Any]]) -> list[list[tuple[datetime, float]]]:
    """Runs of samples joined by trustworthy power segments; any other segment ends a run."""
    chains: list[list[tuple[datetime, float]]] = []
    for seg in sorted(segments, key=lambda item: item["start"]):
        if seg["basis"] != BASIS_POWER:
            continue
        start, end = _parse(seg["start"]), _parse(seg["end"])
        first = (start, _watts(seg["from_value"], seg.get("unit")))
        if chains and chains[-1][-1][0] == start:
            chains[-1].append((end, _watts(seg["to_value"], seg.get("unit"))))
        else:
            chains.append([first, (end, _watts(seg["to_value"], seg.get("unit")))])
    return chains


def observed_intervals(chains: list[list[tuple[datetime, float]]], *, threshold_w: float = MIN_FLOW_W,
                       debounce: int = DEBOUNCE_SAMPLES) -> tuple[list[dict[str, Any]], int]:
    """Charging intervals from trustworthy power chains, and how many lone flow samples were not enough."""
    out: list[dict[str, Any]] = []
    isolated = 0
    for chain in chains:
        index = 0
        while index < len(chain):
            if chain[index][1] < threshold_w:
                index += 1
                continue
            stop = index
            while stop + 1 < len(chain) and chain[stop + 1][1] >= threshold_w:
                stop += 1
            count = stop - index + 1
            if count < debounce:
                isolated += 1
            else:
                first, last = chain[index][0], chain[stop][0]
                before = chain[index - 1][0] if index > 0 else None
                after = chain[stop + 1][0] if stop + 1 < len(chain) else None
                out.append({
                    "first_sample": _iso(first), "last_sample": _iso(last),
                    "start_earliest": None if before is None else _iso(before), "start_latest": _iso(first),
                    "end_earliest": _iso(last), "end_latest": None if after is None else _iso(after),
                    "start_bounded": before is not None, "end_bounded": after is not None,
                    "samples": count, "peak_w": round(max(w for _t, w in chain[index:stop + 1]), 1),
                    "basis": "measured_power", "_core": (first, last),
                })
            index = stop + 1
    return out, isolated


# ---- the query ---------------------------------------------------------------------------------------------------

def _energy(segments: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    """Energy by basis. A basis with no measurement segment inside the window is `None` (unavailable), never 0.0;
    a real measured zero is 0.0 and shows in that basis's `coverage`."""
    sums = {"meter": 0.0, "unobserved": 0.0, "power": 0.0}
    counts = dict.fromkeys(sums, 0)
    seconds = dict.fromkeys(sums, 0.0)
    unknown: Counter[str] = Counter()
    unknown_s = 0.0
    edges: list[dict[str, Any]] = []
    for seg in segments:
        a, b = _parse(seg["start"]), _parse(seg["end"])
        if b <= start or a >= end:
            continue
        if a < start or b > end:
            if len(edges) < 10:
                edges.append({k: seg.get(k) for k in ("start", "end", "basis", "kwh", "coverage", "reason")})
            continue
        if seg["basis"] == BASIS_UNKNOWN:
            unknown[f"{seg.get('kind')}:{seg.get('reason') or 'unknown'}"] += 1
            unknown_s += (b - a).total_seconds()
            continue
        if seg["basis"] == BASIS_METER:
            name = "unobserved" if seg.get("coverage") == "unobserved" else "meter"
        elif seg["basis"] == BASIS_POWER:
            name = "power"
        else:
            continue
        sums[name] += seg["kwh"]
        counts[name] += 1
        seconds[name] += (b - a).total_seconds()

    def value(name: str) -> float | None:
        return round(sums[name], 4) if counts[name] else None

    return {
        "meter_counter_kwh": value("meter"),
        "meter_counter_unobserved_kwh": value("unobserved"),
        "power_integrated_estimate_kwh": value("power"),
        "coverage": {name: {"segments": counts[name], "seconds": round(seconds[name])} for name in counts},
        "unknown_segments": dict(unknown), "unknown_seconds": round(unknown_s),
        "edge_segments_not_prorated": edges,
        "note": "null means no measurement segment lay inside the window (unavailable, not zero); 0.0 is a measured "
                "zero; bases are never summed together; unobserved meter energy has no known placement in time",
    }


def charging_history(store: ChargingEvidenceStore, charger_id: str, *, since: datetime, until: datetime, zone: tzinfo,
                     now: datetime, sessions: tuple[Any, ...] = (), include_prices: bool = False,
                     digests: bool = True) -> dict[str, Any]:
    """One bounded plan-versus-measured answer for `since` <= t < `until` (aware datetimes, at most `MAX_SPAN`)."""
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("invalid window")
    since, until = since.astimezone(timezone.utc), until.astimezone(timezone.utc)  # instants, never wall-clock spans
    if until <= since or until - since > MAX_SPAN:
        raise ValueError("invalid window")
    pad = timedelta(seconds=MAX_POWER_GAP_S)
    oldest = store.oldest_evidence(charger_id)
    plans, spans = _plan_rows(store, charger_id)

    power_segments = store.energy_segments(charger_id, KIND_POWER, since=since - pad, until=until + pad)
    register_segments = store.energy_segments(charger_id, KIND_REGISTER, since=since - pad, until=until + pad)
    chains = _chains(power_segments)
    intervals, isolated = observed_intervals(chains)
    intervals = [item for item in intervals if item["_core"][1] >= since and item["_core"][0] < until]

    trusted = [(_parse(s["start"]), _parse(s["end"])) for s in power_segments if s["basis"] == BASIS_POWER]
    untrusted = [(_parse(s["start"]), _parse(s["end"])) for s in power_segments if s["basis"] != BASIS_POWER]
    seen = _union(_clip(trusted + untrusted, since, until))
    window_s = (until - since).total_seconds()
    coverage = {
        "power_samples_in_retention": bool(store.samples(charger_id, KIND_POWER)),
        "trusted_seconds": round(_seconds(_clip(trusted, since, until))),
        "untrusted_seconds": round(_seconds(_clip(untrusted, since, until))),
        "no_data_seconds": round(window_s - _seconds(seen)),
        "window_seconds": round(window_s), "resolution_note":
            f"samples are at most one per capture tick; pairs are bridged only up to {MAX_POWER_GAP_S}s",
    }

    gaps = []
    for kind in SAMPLE_KINDS:
        for row in store.gaps(charger_id, kind):
            first, last = _parse(row.get("r")), _parse(row.get("r2")) or _parse(row.get("r"))
            if first is not None and last >= since and first < until and len(gaps) < MAX_ROWS:
                gaps.append({"kind": kind, "from": row["r"], "to": row.get("r2"), "reason": row.get("g"),
                             "source": row.get("s")})
    restarts = [at for at in store.capture_starts(charger_id)
                if (when := _parse(at)) is not None and since <= when < until][:MAX_ROWS]

    # Last acknowledged intent and the comparison with measured flow. Only spans the events support are compared;
    # after an uncertain write the plan is unknown, and flow there is never called inside or outside a plan.
    far = until + timedelta(days=3650)
    blocks, known, unknown, cuts = [], [], [], []
    unknown_out = []
    for span in spans:
        pair = (span["start"], span["end"] or far)
        if span["state"] == "known":
            known.append(pair)
        else:
            unknown.append(pair)
            if pair[1] > since and pair[0] < until:
                unknown_out.append({"from": _iso(pair[0]), "until": None if span["end"] is None else _iso(span["end"]),
                                    "reason": span["reason"]})
    for plan in (row for row in plans if row["acked_intent"]):
        a0, b0 = plan["_span"]
        clipped_by = b0 if plan["unknown_from"] is not None else None
        for w in plan["_windows"]:
            a = max(w["start"], a0)
            b = min(w["end"] or until, b0 or until)
            open_ended = w["end"] is None
            a, b = max(a, since), min(b, until)
            if b <= a:
                continue
            cuts.append((a - timedelta(seconds=EDGE_TOLERANCE_S), b + timedelta(seconds=EDGE_TOLERANCE_S)))
            cut_short = clipped_by is not None and (w["end"] is None or w["end"] > clipped_by)
            blocks.append({"version": plan["id"], "start": _iso(a), "end": _iso(b), "limit": w["limit"],
                           "unit": w["unit"], "open_ended_in_profile": open_ended, "_span": (a, b),
                           "intent_uncertain_after": _iso(clipped_by) if cut_short else None})
    for block in blocks:
        a, b = block.pop("_span")
        covered = _seconds(_clip(trusted, a, b))
        reasons = []
        flow = any(item["_core"][0] < b and item["_core"][1] > a for item in intervals)
        contained = sum(s["kwh"] for s in register_segments if s["basis"] == BASIS_METER
                        and s.get("coverage") == "endpoints_only" and a <= _parse(s["start"]) and _parse(s["end"]) <= b)
        unplaced = sum(s["kwh"] for s in register_segments if s["basis"] == BASIS_METER
                       and s.get("coverage") == "unobserved" and _parse(s["start"]) < b and _parse(s["end"]) > a)
        meter_flow = contained >= MIN_METER_KWH
        fraction = covered / (b - a).total_seconds()
        pruned_start = oldest is None or a < oldest
        if pruned_start:
            reasons.append("block_starts_before_retained_evidence")
        if flow or meter_flow:
            verdict = "flow_observed"
        elif fraction >= 0.999 and unplaced < MIN_METER_KWH and not pruned_start:
            verdict = "no_flow_observed"
        else:
            verdict = "unknown"
            reasons.append("no_power_samples" if not coverage["power_samples_in_retention"] else "partial_coverage")
            if unplaced >= MIN_METER_KWH:
                reasons.append("unplaced_meter_energy")
        block.update({"verdict": verdict, "reasons": reasons, "covered_fraction": round(fraction, 3),
                      "power_flow_overlap": flow, "meter_counter_kwh_inside": round(contained, 4),
                      "meter_counter_kwh_unplaced_overlap": round(unplaced, 4)})
    blocks.sort(key=lambda item: item["start"])

    outside = []
    for index, item in enumerate(intervals):
        core = [item["_core"]]
        in_known = _union([(max(a, c0), min(b, c1)) for c0, c1 in core for a, b in known if min(b, c1) > max(a, c0)])
        in_unknown = _union([(max(a, c0), min(b, c1)) for c0, c1 in core for a, b in unknown if min(b, c1) > max(a, c0)])
        for a, b in _subtract(in_known, cuts):
            outside.append({"interval": index, "start": _iso(a), "end": _iso(b), "seconds": round((b - a).total_seconds()),
                            "kind": "outside_plan", "tolerance_seconds": EDGE_TOLERANCE_S})
        for a, b in in_unknown:
            outside.append({"interval": index, "start": _iso(a), "end": _iso(b), "seconds": round((b - a).total_seconds()),
                            "kind": "plan_unknown"})
        for a, b in _subtract(core, in_known + in_unknown):
            outside.append({"interval": index, "start": _iso(a), "end": _iso(b), "seconds": round((b - a).total_seconds()),
                            "kind": "no_plan_evidence"})

    closed = []
    for session in sessions:
        end = session.end
        if end is None or end <= since or session.start >= until:
            continue
        closed.append({
            "id": session.id, "start": _iso(session.start), "end": _iso(end), "energy_kwh": round(session.energy_kwh, 3),
            "energy_source": session.energy_source, "source": session.source, "started_by": session.started_by,
            "area_id": session.area_id, "cost": None, "cost_basis": "not_recomputed_here",
            "price_slices": [{"start": _iso(s.start), "end": _iso(s.end), "kwh": round(s.kwh, 4),
                              "eur_per_kwh": s.eur_per_kwh, "fx": s.fx} for s in session.intervals[:MAX_ROWS]],
            "association": "time_overlap_only",
            # Stage 15.8: the register's total against the energy placed above (`energy_kwh`, never changed), with its
            # provenance; the remainder is unplaced late energy with no known time, never flow, power or progress.
            "reconciliation": reconcile_public(session),
            "overlapping_observed_intervals": sum(1 for it in intervals if _parse(it["first_sample"]) < end
                                                  and _parse(it["last_sample"]) > session.start),
        })
        if len(closed) >= MAX_ROWS:
            break

    in_window = [row for row in plans if
                 (row["acked_intent"] and _parse(row["acked_at"]) < until
                  and (row["intent_ended_at"] is None or _parse(row["intent_ended_at"]) > since))
                 or (not row["acked_intent"] and (when := _parse(row["recorded_at"])) is not None
                     and since <= when < until)]
    snapshots = {}
    if include_prices:
        for row in in_window:
            if row["tariff"]["prices_ref"] and row["_prices"] is not None:
                snapshots[row["tariff"]["prices_ref"]] = row["_prices"]
    for row in plans:
        for key in [k for k in row if k.startswith("_")]:
            del row[key]
    plan_out = in_window[:MAX_ROWS]

    for item in intervals:
        del item["_core"]
    digest_rows = []
    if digests:
        for key, value in sorted(store.digests(charger_id).items()):
            day = date.fromisoformat(key)
            a = datetime.combine(day, time.min, tzinfo=zone)
            if a < until and datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone) > since:
                digest_rows.append(value)

    return {
        "api_version": HISTORY_API_VERSION, "charger_id": charger_id,
        "window": {"since": _iso(since), "until": _iso(until), "zone": getattr(zone, "key", str(zone)),
                   "local_since": since.astimezone(zone).isoformat(), "local_until": until.astimezone(zone).isoformat()},
        "retention": {"oldest_evidence": None if oldest is None else _iso(oldest),
                      "window_starts_before_oldest_evidence": oldest is None or since < oldest,
                      "note": "raw rows are bounded by age and count; earlier days exist only as digests, if any"},
        "provenance": {
            "flow_source": "measured power_w samples only", "min_flow_w": MIN_FLOW_W, "debounce_samples": DEBOUNCE_SAMPLES,
            "edge_tolerance_seconds": EDGE_TOLERANCE_S, "threshold_verified_on_installation": False,
            "plan_intent": "last acknowledged intent: the charger answered a version accepted; not proof that profile is "
                           "effective or installed, nor that charging happened; an uncertain newer write, a writer outside "
                           "SpotNav, missing or pruned events or a restart end what is known (`plan_unknown`)",
            "readback": "effective-limit readback only; never an inventory of installed profiles",
            "not_used_as_flow": ["schedules", "offered limits", "ACK", "readback", "connector status", "current"],
        },
        "plans": plan_out, "plans_truncated": len(in_window) > MAX_ROWS, "price_snapshots": snapshots,
        "observed": {"intervals": intervals[:MAX_ROWS], "isolated_flow_samples": isolated,
                     "coverage": coverage, "energy": _energy([{**s, "kind": "register"} for s in register_segments]
                                                  + [{**s, "kind": "power"} for s in power_segments], since, until),
                     "gaps": gaps, "capture_restarts": restarts},
        "comparison": {"planned_blocks": blocks[:MAX_ROWS], "outside_plan": outside[:MAX_ROWS],
                       "unknown_plan_spans": unknown_out[:MAX_ROWS], "basis": "acknowledged_intent_known_spans_only"},
        "sessions": closed, "digests": digest_rows,
    }


# ---- digests -----------------------------------------------------------------------------------------------------

def day_digest(answer: dict[str, Any], *, day: date, partial: bool, now: datetime) -> dict[str, Any]:
    """A compact finished-day summary from a full answer; keeps verdicts, intervals, energy bases and fiscal choice."""
    applied = [{"id": p["id"], "fingerprint": p["fingerprint"], "intent": p["intent"], "acked_at": p["acked_at"],
                "intent_ended_at": p["intent_ended_at"], "known_until": p["known_until"],
                "unknown_from": p["unknown_from"], "unknown_reason": p["unknown_reason"], "tariff": {k: p["tariff"][k] for k in
                                                                 ("time_zone", "market", "fiscal_state", "fiscal")}}
               for p in answer["plans"] if p["acked_intent"]][:20]
    observed = answer["observed"]
    return {
        "date": day.isoformat(), "zone": answer["window"]["zone"], "computed_at": _iso(now),
        "partial_retention": partial, "raw_prices_retained": False,
        "plans_applied": applied,
        "observed_intervals": [{k: v for k, v in item.items() if k != "basis"} for item in observed["intervals"][:50]],
        "isolated_flow_samples": observed["isolated_flow_samples"], "coverage": observed["coverage"],
        "energy": {k: v for k, v in observed["energy"].items() if k != "edge_segments_not_prorated"},
        "planned_blocks": [{k: b[k] for k in ("version", "start", "end", "limit", "verdict", "covered_fraction")}
                           for b in answer["comparison"]["planned_blocks"][:50]],
        "outside_plan": answer["comparison"]["outside_plan"][:50],
        "unknown_plan_spans": answer["comparison"]["unknown_plan_spans"][:20],
        "gap_count": len(observed["gaps"]), "restart_count": len(observed["capture_restarts"]),
    }


def compact_days(store: ChargingEvidenceStore, charger_id: str, zone: tzinfo, now: datetime) -> list[str]:
    """Keep a digest of every finished local day that has retained evidence and none yet. Returns the days kept."""
    oldest = store.oldest_evidence(charger_id)
    if oldest is None:
        return []
    kept = []
    today = now.astimezone(zone).date()
    day = max(oldest.astimezone(zone).date(), today - timedelta(days=MAX_DIGEST_LOOKBACK_DAYS))
    have = store.digests(charger_id)
    while day < today:
        start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
        if day.isoformat() not in have and now >= end + DIGEST_SETTLE:
            answer = charging_history(store, charger_id, since=start, until=end, zone=zone, now=now, digests=False)
            observed = answer["observed"]
            active = answer["plans"] or answer["comparison"]["unknown_plan_spans"] or observed["intervals"] or observed["coverage"]["trusted_seconds"] \
                or observed["coverage"]["untrusted_seconds"] or observed["gaps"]
            if active and store.keep_digest(charger_id, day.isoformat(),
                                            day_digest(answer, day=day, partial=oldest > start, now=now)):
                kept.append(day.isoformat())
        day += timedelta(days=1)
    return kept
