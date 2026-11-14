"""Stage 15.6: one connection-aware freshness judgement for Morek *display and readiness* (read-only, no I/O).

Silence alone proves neither health nor failure. Each quantity gets one judgement::

    {state: current|last_known|idle|unknown, basis, reported_at, age_s, link, reason}

* **Event quantities** (connector status, transaction, the derived charge-control switch) are `current` while the
  link has been continuously up *since the report* ("unchanged since {time}", no age cap). A report that predates
  this process's continuous observation of the link (a reconnect, a new connection, a cold start or an HA restart:
  the monitor is memory only) is `last_known`; link down is `last_known` with its age, an unobserved link `unknown`.
* **Sampled quantities** (power, current, register) are `current` only with the link up, a report observed after the
  link's continuity began, and an age within `max(180 s, 3 x median of the last 10 observed report intervals,
  capped at 900 s)`. Past the bound they are `idle` only when *no reading is expected* (never a false zero) and
  `unknown` otherwise, in particular while a transaction or flow is expected. Link not up is `unknown`.
* No link monitor at all falls back to the strict 180 s bound (`basis` says so), so absent evidence never becomes
  more generous than before.

This is a **display/readiness** judgement. Control flow keeps `STRICT_EVIDENCE_MAX_AGE_S` through the readings'
`fresh` flag and `connector_evidence` (Stage 14.2/14.4 release rules, the 15.5 post-boot evidence, 15.4b flow); a
judgement never feeds those, so it can only ever show more than they act on, never act on more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any, Final

#: The strict bound control flow keeps (Stage 14.2/14.4 evidence, 15.4b flow, `fresh`). 15.6 never loosens it.
STRICT_EVIDENCE_MAX_AGE_S: Final = 180
SAMPLED_CAP_S: Final = 900
CADENCE_WINDOW: Final = 10  # observed report intervals considered
CADENCE_MIN_INTERVALS: Final = 3  # fewer than this and the floor applies: no cadence is guessed
#: An interval counts only between two genuinely separate reports: duplicates and replay bursts are shorter, and
#: a gap (an outage, not a cadence) is longer.
MIN_INTERVAL_S: Final = 5
MAX_INTERVAL_S: Final = 3600
_UNTRUSTED_FLAGS: Final = frozenset({"out_of_order", "future_timestamp", "conflicting_duplicate"})

CURRENT: Final = "current"
LAST_KNOWN: Final = "last_known"
IDLE: Final = "idle"
UNKNOWN: Final = "unknown"


@dataclass(frozen=True)
class LinkFacts:
    """What the monitor knows: `continuous_since` is when this process began observing an unbroken up link."""

    state: str  # up / down / unknown
    continuous_since: datetime | None
    connection_id: int | None = None


def link_facts(monitor: Any) -> LinkFacts | None:
    """The monitor's link facts, or None when there is no usable monitor (callers then use the strict bound)."""
    if monitor is None:
        return None
    state = getattr(monitor, "state", None)
    if state not in ("up", "down", "unknown"):
        return None
    if state != "up":
        return LinkFacts(state, None, getattr(monitor, "connection_id", None))
    marks = [value for value in (getattr(monitor, "since", None), getattr(monitor, "connection_changed_at", None))
             if isinstance(value, datetime) and value.tzinfo is not None]
    if not marks or not isinstance(getattr(monitor, "since", None), datetime):
        return None  # an up link with no known start proves no continuity
    return LinkFacts("up", max(marks), getattr(monitor, "connection_id", None))


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _judgement(state: str, basis: str, reason: str, reported_at: datetime | None, age: float | None,
               link: LinkFacts | None, **extra: Any) -> dict[str, Any]:
    return {"state": state, "basis": basis, "reported_at": _iso(reported_at),
            "age_s": None if age is None else max(0, int(age)), "link": None if link is None else
            {"state": link.state, "since": _iso(link.continuous_since), "connection_id": link.connection_id},
            "reason": reason, **extra}


def _common(reported_at: Any, now: datetime, link: LinkFacts | None) -> tuple[dict[str, Any] | None, float | None]:
    """Shared preconditions: a usable timestamp and sane clocks. Returns (verdict-or-None, age)."""
    if not isinstance(reported_at, datetime) or reported_at.tzinfo is None:
        return _judgement(UNKNOWN, "no_report", "no_report", None, None, link), None
    age = (now - reported_at).total_seconds()
    if age < 0 or (link is not None and link.continuous_since is not None and link.continuous_since > now):
        return _judgement(UNKNOWN, "clock_skew", "clock_skew", reported_at, None, link), None
    return None, age


def judge_event(reported_at: Any, now: datetime, link: LinkFacts | None) -> dict[str, Any]:
    """Status, transaction and control-switch judgement; see the module docstring."""
    verdict, age = _common(reported_at, now, link)
    if verdict is not None:
        return verdict
    if link is None:
        within = age <= STRICT_EVIDENCE_MAX_AGE_S
        return _judgement(CURRENT if within else UNKNOWN, "recent_report_no_link_monitor",
                          "no_link_monitor" if within else "stale_without_link_monitor", reported_at, age, link)
    if link.state == "down":
        return _judgement(LAST_KNOWN, "link_down", "link_down", reported_at, age, link)
    if link.state != "up" or link.continuous_since is None:
        return _judgement(UNKNOWN, "link_unobserved", "link_unknown", reported_at, age, link)
    if reported_at >= link.continuous_since:
        return _judgement(CURRENT, "link_continuous_since_report", "unchanged_since_report", reported_at, age, link)
    return _judgement(LAST_KNOWN, "report_before_link_continuity", "awaiting_report_after_link", reported_at, age, link)


def judge_sampled(reported_at: Any, now: datetime, link: LinkFacts | None, *, bound_s: float,
                  expected: bool | None) -> dict[str, Any]:
    """Power/current/register judgement. `expected` says whether a reading should be arriving: True while a
    transaction or flow is expected, False when positively none is, None when that is not known."""
    verdict, age = _common(reported_at, now, link)
    if verdict is not None:
        return {**verdict, "bound_s": int(bound_s)}
    extra = {"bound_s": int(bound_s)}
    if link is None:
        within = age <= STRICT_EVIDENCE_MAX_AGE_S
        return _judgement(CURRENT if within else UNKNOWN, "recent_report_no_link_monitor",
                          "no_link_monitor" if within else "stale_without_link_monitor", reported_at, age, link,
                          **{"bound_s": STRICT_EVIDENCE_MAX_AGE_S})
    if link.state != "up" or link.continuous_since is None:
        return _judgement(UNKNOWN, "link_not_up", "link_down" if link.state == "down" else "link_unknown",
                          reported_at, age, link, **extra)
    if age <= bound_s:
        if reported_at >= link.continuous_since:
            return _judgement(CURRENT, "report_within_cadence_bound", "recent_report", reported_at, age, link, **extra)
        return _judgement(LAST_KNOWN, "report_before_link_continuity", "awaiting_report_after_link", reported_at,
                          age, link, **extra)
    if expected is False:
        return _judgement(IDLE, "no_reading_expected", "no_reading_expected", reported_at, age, link, **extra)
    return _judgement(UNKNOWN, "silent_beyond_bound",
                      "silent_in_transaction" if expected else "expectation_unknown", reported_at, age, link, **extra)


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def report_intervals(rows: list[dict[str, Any]]) -> list[float]:
    """Intervals (s) between genuinely separate observed reports, newest `CADENCE_WINDOW` kept.

    `rows` are evidence-store samples (`t` observed, `r` received, `q` quality flags). Untrusted rows (future,
    out of order, conflicting), duplicates, replay bursts (reports that *arrived* together) and outage-length gaps
    are ignored rather than averaged in, so the 60 s capture tick or a backlog never distorts the cadence."""
    points = []
    for row in rows:
        if _UNTRUSTED_FLAGS & set(row.get("q") or ()):
            continue
        observed, received = _parse(row.get("t")), _parse(row.get("r"))
        if observed is not None and received is not None:
            points.append((observed, received))
    points.sort()
    out: list[float] = []
    previous: tuple[datetime, datetime] | None = None
    for observed, received in points:
        if previous is not None:
            apart = (observed - previous[0]).total_seconds()
            arrived = (received - previous[1]).total_seconds()
            if apart < MIN_INTERVAL_S or arrived < MIN_INTERVAL_S:
                continue  # duplicate or burst: not a new report, keep comparing against the last genuine one
            if apart <= MAX_INTERVAL_S:
                out.append(apart)
        previous = (observed, received)
    return out[-CADENCE_WINDOW:]


def sampled_bound_s(rows: list[dict[str, Any]]) -> float:
    """`max(180, 3 x median interval of the last 10 observed reports)`, capped at 900; the floor without evidence."""
    intervals = report_intervals(rows)
    if len(intervals) < CADENCE_MIN_INTERVALS:
        return float(STRICT_EVIDENCE_MAX_AGE_S)
    return float(min(SAMPLED_CAP_S, max(STRICT_EVIDENCE_MAX_AGE_S, 3 * median(intervals))))


def expectation(status: dict[str, Any] | None, transaction: dict[str, Any] | None) -> bool | None:
    """Whether sampled readings should be arriving: True with a current open transaction or charging status,
    False when current evidence says there is none, None (never idle) when that is not established.

    `status`/`transaction` are `{"judgement": ..., "value": ...}` pairs; only a `current` judgement counts."""
    def current(item: dict[str, Any] | None) -> bool:
        return isinstance(item, dict) and (item.get("judgement") or {}).get("state") == CURRENT

    if current(transaction) and transaction.get("value") is True:
        return True
    if current(status) and status.get("value") == "charging":
        return True
    if current(transaction) and transaction.get("value") is False:
        return False
    if current(status) and status.get("value") == "disconnected":
        return False
    return None
