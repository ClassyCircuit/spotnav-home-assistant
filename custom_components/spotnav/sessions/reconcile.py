"""Stage 15.8: reconciliation of a closed session's register total, with late register rises kept UNASSIGNED
(read only, additive).

The session recorder keeps the register pair of a register-measured session (`register_pair`: the reading when the
session opened, the last reading *it took while the session was open*, the entity they came from and when the session
closed). A session's own `energy_kwh` is what the recorder *placed* from the samples it saw, and it is never changed
here (Stage 14.5 and the cost read it).

**What is accepted as proof.** Only the recorder's own pair: both endpoints were read by the recorder, inside this
session, from one entity, with no reset or source change (`broke`). Then

    total = pair close - pair open        versus        placed = session.energy_kwh

and a remainder is stored as **unplaced** energy with `placement: "unknown"` (a reading the recorder took but did not
place, e.g. around a gap or restart; never flow, never priced, never power or progress).

**What is never accepted as proof.** A register sample the evidence store retained *after* the close carries only an
entity, an observed time and a HA receipt time: no session, transaction or connector binding. A higher late value can
be a buffered replay of this session, or the next car's energy (a charge SpotNav never opened, or one under
`MIN_ENERGY_KWH`), and a settled counter, a time window or the absence of a later session record does not tell them
apart. So such a rise is reported as `unassigned_register_kwh` (observed register difference, certified for no session)
and the session's state is `uncertain` with no total and no unplaced figure.

The result is recomputed from the persisted pair and the retained evidence, so a repeat, a duplicate or a restart
changes nothing, and nothing unproven is ever stored as a total (so nothing needs to be withdrawn).

Nothing here awaits, writes to a charger or touches the planner; stored JSON is untrusted (`clean_pair`,
`clean_late`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from .evidence import KIND_REGISTER

#: A register that falls to this or below is a reset to zero.
RESET_TOLERANCE_KWH: Final = 0.5
#: How long after a session closed a late register rise is still looked for (and reported as unassigned).
LATE_WINDOW_S: Final = 6 * 3600
#: A difference this small between the register total and the placed energy is a match, not unplaced energy.
MATCH_TOLERANCE_KWH: Final = 0.01
#: A sample this close to (or after) the next session's start is the next session's, not a late rise of this one.
BOUNDARY_MARGIN_S: Final = 120
#: Placement reasons kept per record.
MAX_REASONS: Final = 3

STATE_RECONCILED: Final = "reconciled"
STATE_CONSISTENT: Final = "consistent"
STATE_INCONSISTENT: Final = "inconsistent"
STATE_UNKNOWN: Final = "unknown"
STATE_UNCERTAIN: Final = "uncertain"
STATE_SKIPPED: Final = "skipped"
STATES: Final = (
    STATE_RECONCILED, STATE_CONSISTENT, STATE_INCONSISTENT, STATE_UNKNOWN, STATE_UNCERTAIN, STATE_SKIPPED,
)
REASONS: Final = (
    "register_reset", "identity", "source_not_register", "register_open_unknown", "register_close_unknown",
    "ambiguous_association", "late_register_unassigned", "total_below_placed", "register_pair_missing",
)
PLACEMENT_REASONS: Final = ("restart", "gap", "link_down", "unattributed")
QUALITY: Final = (
    "quality_ignored", "other_source_ignored", "bounded_by_next_session",
    "decrease_after_close",
)
_IGNORED_FLAGS: Final = frozenset({"future_timestamp", "conflicting_duplicate", "stale_source"})
_PAIR_KEYS: Final = frozenset({"open", "close", "entity", "broke", "closed_at"})
_LATE_KEYS: Final = frozenset({
    "state", "reason", "placed_kwh", "total_kwh", "unplaced_late_kwh", "placement", "placement_reasons",
    "register_open_kwh", "register_close_kwh", "unassigned_register_kwh", "source", "quality", "final",
    "evaluated_at",
})


def _number(value: Any, *, minimum: float | None = 0.0) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if minimum is not None and value < minimum:
        return None
    return float(value)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


# ---- the register pair the recorder keeps ---------------------------------------------------------------------------

def new_pair(open_kwh: float | None, entity: str | None) -> dict[str, Any]:
    """The pair of a session that opens measured on a register (the reading at open, `None` when it was not readable)."""
    return {"open": open_kwh, "close": open_kwh, "entity": entity, "broke": None, "closed_at": None}


def break_pair(pair: dict[str, Any] | None, reason: str) -> None:
    """The register's origin changed or it reset inside the session: its difference is no longer the energy."""
    if pair is not None and pair.get("broke") is None:
        pair["broke"] = reason


def note_reading(pair: dict[str, Any] | None, reading: float) -> None:
    """The recorder took `reading` from the register: the latest close endpoint it knows."""
    if pair is not None and pair.get("broke") is None:
        pair["close"] = reading


def close_pair(pair: dict[str, Any] | None, now: datetime) -> None:
    if pair is not None and pair.get("closed_at") is None:
        pair["closed_at"] = _iso(now)


def clean_pair(raw: Any) -> dict[str, Any] | None:
    """A stored pair read back, or `None` when it is not exactly this shape (the session loads without it)."""
    if not isinstance(raw, dict) or set(raw) != _PAIR_KEYS:
        return None
    opened = None if raw["open"] is None else _number(raw["open"])
    closed = None if raw["close"] is None else _number(raw["close"])
    entity = raw["entity"]
    if (
        (raw["open"] is not None and opened is None)
        or (raw["close"] is not None and closed is None)
        or (entity is not None and (not isinstance(entity, str) or not entity))
        or raw["broke"] not in (None, "register_reset", "identity")
        or (raw["closed_at"] is not None and _parse(raw["closed_at"]) is None)
    ):
        return None
    return {"open": opened, "close": closed, "entity": entity, "broke": raw["broke"], "closed_at": raw["closed_at"]}


def clean_late(raw: Any) -> dict[str, Any] | None:
    """A stored reconciliation record read back, or `None` (the session loads without it and is evaluated again)."""
    if not isinstance(raw, dict) or set(raw) != _LATE_KEYS or raw["state"] not in STATES:
        return None
    if raw["reason"] is not None and raw["reason"] not in REASONS:
        return None
    reasons, quality = raw["placement_reasons"], raw["quality"]
    if (
        not isinstance(reasons, list) or len(reasons) > MAX_REASONS or any(r not in PLACEMENT_REASONS for r in reasons)
        or not isinstance(quality, list) or len(quality) > len(QUALITY) or any(q not in QUALITY for q in quality)
        or raw["placement"] not in (None, "unknown")
        or not isinstance(raw["final"], bool)
        or _parse(raw["evaluated_at"]) is None
    ):
        return None
    numbers = {}
    for key in ("placed_kwh", "total_kwh", "unplaced_late_kwh", "register_open_kwh", "register_close_kwh",
                "unassigned_register_kwh"):
        if raw[key] is None:
            numbers[key] = None
        elif (value := _number(raw[key])) is None:
            return None
        else:
            numbers[key] = value
    source = raw["source"]
    if source is not None:
        if (
            not isinstance(source, dict) or set(source) != {"basis", "r", "entity"}
            or source["basis"] != "recorder_close"
            or any(source[k] is not None and not isinstance(source[k], str) for k in ("r", "entity"))
        ):
            return None
        source = dict(source)
    return {**raw, **numbers, "placement_reasons": list(reasons), "quality": list(quality), "source": source}


def comparable(late: dict[str, Any] | None) -> dict[str, Any] | None:
    """The record without its evaluation stamp: what makes two evaluations the same."""
    return None if late is None else {k: v for k, v in late.items() if k != "evaluated_at"}


# ---- the evidence the reconciliation reads --------------------------------------------------------------------------

class LateEvidence:
    """The register rows, register gap rows and capture restarts of one charger (copies, read once per pass)."""

    __slots__ = ("samples", "gaps", "restarts")

    def __init__(self, samples: Sequence[dict[str, Any]], gaps: Sequence[dict[str, Any]], restarts: Sequence[str]) -> None:
        self.samples, self.gaps, self.restarts = samples, gaps, restarts


def read_evidence(evidence: Any, charger_id: str, *, since: datetime) -> LateEvidence:
    return LateEvidence(
        evidence.samples(charger_id, KIND_REGISTER, since=since),
        evidence.gaps(charger_id, KIND_REGISTER),
        evidence.capture_starts(charger_id),
    )


# ---- the reconciliation ---------------------------------------------------------------------------------------------

def pending(session: Any) -> bool:
    """Whether a finished session still awaits (or may still gain) a reconciliation."""
    late = session.late
    return session.register_pair is not None and (late is None or not late["final"])


def reconcile(session: Any, evidence: LateEvidence, others: Iterable[Any], now: datetime) -> dict[str, Any] | None:
    """The reconciliation record of a finished `session` given the retained evidence and the charger's other sessions
    (`None` for a session without a register pair). Pure; the caller stores a changed result."""
    pair = session.register_pair
    if pair is None:
        return None
    placed = session.energy_kwh
    fields: dict[str, Any] = {
        "placed_kwh": round(placed, 4), "total_kwh": None, "unplaced_late_kwh": None, "placement": None,
        "placement_reasons": [], "register_open_kwh": pair["open"], "register_close_kwh": None,
        "unassigned_register_kwh": None, "source": None, "quality": [],
    }

    def result(state: str, reason: str | None = None, *, final: bool = True) -> dict[str, Any]:
        return {"state": state, "reason": reason, **fields, "final": final, "evaluated_at": _iso(now)}

    closed_at = _parse(pair["closed_at"])
    if session.energy_source != "register":
        return result(STATE_SKIPPED, "source_not_register")
    if pair["broke"] is not None:
        return result(STATE_SKIPPED, pair["broke"])
    if pair["open"] is None:
        return result(STATE_UNKNOWN, "register_open_unknown")
    recorded = pair["close"]
    if closed_at is None or session.end is None or recorded is None:
        return result(STATE_UNKNOWN, "register_close_unknown")
    start, boundary = session.start, None
    for other in others:
        if other.id == session.id:
            continue
        other_end = other.end
        if other.start < closed_at and (other_end is None or other_end > start):
            return result(STATE_UNKNOWN, "ambiguous_association")
        if other.start >= start and (boundary is None or other.start < boundary):
            boundary = other.start
    limit = closed_at + timedelta(seconds=LATE_WINDOW_S)
    edge = None if boundary is None else boundary - timedelta(seconds=BOUNDARY_MARGIN_S)
    entity = pair["entity"]
    final = boundary is not None or now >= limit
    quality: list[str] = []

    def note(flag: str) -> None:
        if flag not in quality:
            quality.append(flag)

    # Register values retained after the close. They have no session binding, so they are never a total; a rise above
    # the recorder's close reading is only reported as unassigned.
    candidates: list[tuple[datetime, datetime, float]] = []
    for row in evidence.samples:
        when, received, value = _parse(row.get("t")), _parse(row.get("r")), _number(row.get("v"))
        if when is None or received is None or value is None or when < start or received < closed_at:
            continue
        if entity is None or row.get("e") != entity:
            if received <= limit:
                note("other_source_ignored")
            continue
        if _IGNORED_FLAGS & set(row.get("q") or ()):
            note("quality_ignored")
            continue
        if when > limit or received > limit:
            continue
        if edge is not None and (when >= edge or received >= edge):
            note("bounded_by_next_session")
            continue
        candidates.append((when, received, value))
    candidates.sort()
    peak = recorded
    for _when, _received, value in candidates:
        if value < peak - 1e-9:
            # The register fell back: after a reset it counts something else, so nothing later is comparable.
            note("decrease_after_close")
            break
        peak = max(peak, value)
    fields["quality"] = quality
    fields["register_close_kwh"] = round(recorded, 4)
    fields["source"] = {"basis": "recorder_close", "r": _iso(closed_at), "entity": entity}
    if peak - recorded > MATCH_TOLERANCE_KWH:
        fields["unassigned_register_kwh"] = round(peak - recorded, 4)
        return result(STATE_UNCERTAIN, "late_register_unassigned", final=final)
    total = recorded - pair["open"]
    if total < 0:
        # Below the reading it opened at: a reset or another register's origin, never energy.
        return result(STATE_SKIPPED, "register_reset", final=True)
    gap = total - placed
    fields["total_kwh"] = round(total, 4)
    if abs(gap) <= MATCH_TOLERANCE_KWH:
        fields["unplaced_late_kwh"] = 0.0
        return result(STATE_CONSISTENT, final=final)
    if gap < 0:
        fields["total_kwh"] = round(placed, 4)
        fields["unplaced_late_kwh"] = 0.0
        return result(STATE_INCONSISTENT, "total_below_placed", final=final)
    reasons: list[str] = []
    if any((moment := _parse(item)) is not None and start <= moment <= closed_at for item in evidence.restarts):
        reasons.append("restart")
    inside = [
        item for item in evidence.gaps if (moment := _parse(item.get("r"))) is not None and start <= moment <= closed_at
    ]
    if any(item.get("g") == "link_down" for item in inside):
        reasons.append("link_down")
    if any(item.get("g") != "link_down" for item in inside):
        reasons.append("gap")
    fields["unplaced_late_kwh"] = round(gap, 4)
    fields["placement"] = "unknown"
    fields["placement_reasons"] = (reasons or ["unattributed"])[:MAX_REASONS]
    return result(STATE_RECONCILED, final=final)


def public(session: Any) -> dict[str, Any]:
    """The history wire block of a finished session: the reconciled total with its provenance. A session with no
    stored record (an older one, or one not yet evaluated) is `unknown`, never zero."""
    late = session.late
    placed = round(session.energy_kwh, 3)
    if late is None:
        reason = "register_pair_missing" if session.register_pair is None else "not_evaluated"
        return {
            "state": STATE_UNKNOWN, "reason": reason, "placed_kwh": placed, "total_kwh": None,
            "unplaced_late_kwh": None, "placement": None, "placement_reasons": [], "final": False,
            "provenance": _provenance(None),
        }
    return {
        "state": late["state"], "reason": late["reason"], "placed_kwh": placed, "total_kwh": late["total_kwh"],
        "unplaced_late_kwh": late["unplaced_late_kwh"], "placement": late["placement"],
        "placement_reasons": list(late["placement_reasons"]), "final": late["final"],
        "quality": list(late["quality"]), "register_open_kwh": late["register_open_kwh"],
        "register_close_kwh": late["register_close_kwh"], "unassigned_register_kwh": late["unassigned_register_kwh"],
        "evaluated_at": late["evaluated_at"], "provenance": _provenance(late["source"]),
    }


def _provenance(source: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "basis": "recorder_register_pair", "endpoint": source,
        "when_delivered": "unknown",
        "note": "the recorder's own register readings at open and close, against the energy placed from observed "
                "samples; any remainder has no known placement in time and is neither flow, current power nor "
                "progress. A later register rise (unassigned_register_kwh) is observed by receipt time only, has no "
                "session or transaction binding and is not certified as this session's energy",
        "window_seconds": LATE_WINDOW_S,
    }
