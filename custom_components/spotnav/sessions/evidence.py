"""Stage 6.2: bounded charging evidence. Sent-plan versions and command evidence are kept apart from measurements.

Two kinds of records live here, in one small HA `Store`, and they never stand in for one another:

* **Intent evidence** (`plans`, `events`): every profile SpotNav recorded as an attempt just before dispatch, as an
  immutable *plan version*. A version alone is NOT proof it reached the wire. Separate append-only events come from
  the send path: `dispatch_started` (written synchronously right BEFORE the OCPP call: a process crash,
  cancellation or lost write between the marker and the call means nothing was sent, so it only says a send was
  about to start, never that it happened), `dispatch_aborted` (with a reason; nothing was sent), `ack` (the
  charger's answer, the only event that shows a command reached it; an `ack` with status `unknown` means no answer
  was received), `readback` and `removal`. `dispatch_state` combines them; absent or conflicting events are
  `unknown`/`conflicting`, never a claim of sending. A readback is the effective current limit the charger
  reports; neither it nor an ACK is installed-profile inventory or evidence of physical charging.
* **Measurements** (`samples`): values genuinely read from the connector's HA entities (power, current,
  cumulative energy register, and connector status as status-only evidence), each with the entity it came from,
  the HA state time it was observed (`t`), the time SpotNav received it (`r`) and quality flags. A plan,
  offered limit, ACK or schedule window is never written as a sample. A source that cannot be read is stored
  as an explicit *gap* row (value `None`, reason), never as 0, and a restart of the capture is marked too.

Duplicates (same source entity and observed time) are dropped, a differing value at the same observed time is kept
and flagged, out-of-order arrivals and counter decreases are kept and flagged, nothing is repaired or bridged.
`derive_energy` turns stored samples, gap rows and restart marks into separately labelled segments
(`meter_counter` delta versus `power_integrated_estimate`) and unknown segments; it is the seam the Stage 6.3 queries
(`sessions/history.py`) build on. Plan versions also keep, once per distinct content, the tariff and published prices in
force when they were made (`blobs`), and finished local days are compacted into small digests (`days`). Explicit gaps, restarts, stale/future/conflicting/out-of-order rows and source changes are never bridged.

Retention is bounded by age (`RETENTION_DAYS`) AND by count per list (whichever is hit first); oldest rows go first.
Measurements are one row per kind per capture tick at most, so `MAX_SAMPLES_PER_KIND` rows are only
`MAX_SAMPLES_PER_KIND` minutes of data at the 60 s tick: the count, not the age, is the binding limit at full rate. The store is written
`SAVE_DELAY_S` after a change and flushed by Home Assistant's final write. Nothing here writes to a charger.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}_charging_evidence"
DATA_KEY: Final = "spotnav_charging_evidence"
RETENTION_DAYS: Final = 7
MAX_PLANS: Final = 120
MAX_EVENTS: Final = 600
#: 3 days of rows at one per 60 s tick per kind (1440/day); sparser reporting lasts up to `RETENTION_DAYS`.
MAX_SAMPLES_PER_KIND: Final = 4320
MAX_CAPTURE_MARKS: Final = 100
MAX_READBACK_PERIODS: Final = 96
#: Compact per-local-day digests kept after the raw rows are gone (Stage 6.3).
MAX_DIGEST_DAYS: Final = 62
SAVE_DELAY_S: Final = 120
#: How many recent rows are searched for a duplicate or the previous reading of a source.
LOOKBACK: Final = 200
#: An observed time this far after the receipt time is clock drift, flagged and kept.
FUTURE_SKEW_S: Final = 120
#: A register that falls to this or below after a decrease is *probably* a reset; the amount since is still unknown.
RESET_TOLERANCE_KWH: Final = 0.5
#: Power samples further apart than this are not bridged (the existing `power_energy` bound for a charger's sensor).
MAX_POWER_GAP_S: Final = 660

KIND_POWER: Final = "power_w"
KIND_CURRENT: Final = "current_a"
KIND_REGISTER: Final = "energy_register_kwh"
KIND_STATUS: Final = "status"  # status-only evidence: a label, never flow
MEASURED_KINDS: Final = (KIND_POWER, KIND_CURRENT, KIND_REGISTER)
SAMPLE_KINDS: Final = (*MEASURED_KINDS, KIND_STATUS)
EVENT_KINDS: Final = ("dispatch_started", "ack", "dispatch_aborted", "readback", "removal")
#: Only the marker before the call exists: possibly sent, not proven (the call may never have happened).
DISPATCH_STARTED: Final = "dispatch_started"
#: The charger answered (any status other than `unknown`): the one state that shows the command reached it.
DISPATCH_ACK_RECEIVED: Final = "ack_received"
DISPATCH_ABORTED: Final = "aborted_before_dispatch"
#: No event, or an ACK of `unknown` with no marker: nothing is known about sending.
DISPATCH_UNKNOWN: Final = "unknown"
DISPATCH_CONFLICT: Final = "conflicting"
BASIS_METER: Final = "meter_counter"
BASIS_POWER: Final = "power_integrated_estimate"
BASIS_UNKNOWN: Final = "unknown"

ADDED: Final = "added"
DUPLICATE: Final = "duplicate"
REJECTED: Final = "rejected"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class ChargingEvidenceStore:
    """Per charger: immutable plan versions, command/readback events, measurement samples and gaps."""

    def __init__(self, hass: Any, *, store: Any = None, now: Callable[[], datetime] | None = None) -> None:
        self._hass = hass
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._chargers: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._seq = 0

    # ---- persistence

    def _backend(self) -> Any:
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(self._hass, STORAGE_VERSION, STORAGE_KEY)
        return self._store

    async def async_load(self) -> None:
        """Merge the stored record under anything captured before the load finished (nothing is lost or repeated)."""
        raw = await self._backend().async_load()
        if self._loaded:
            return
        self._loaded = True
        if not isinstance(raw, dict) or raw.get("version") != STORAGE_VERSION:
            return
        chargers = raw.get("chargers")
        if not isinstance(chargers, dict):
            return
        dropped = 0
        early, self._chargers = self._chargers, {}
        for charger_id, doc in chargers.items():
            if isinstance(charger_id, str) and isinstance(doc, dict):
                dropped += self._adopt(charger_id, doc)
        for charger_id, doc in early.items():
            mine = self._charger(charger_id)
            known = {item.get("id") for item in mine["plans"]}
            mine["plans"].extend(item for item in doc["plans"] if item.get("id") not in known)
            mine["events"].extend(doc["events"])
            mine["captures"].extend(doc["captures"])
            mine["blobs"].update({key: value for key, value in doc["blobs"].items() if key not in mine["blobs"]})
            mine["days"].update({key: value for key, value in doc["days"].items() if key not in mine["days"]})
            for kind, rows in doc["samples"].items():
                mine["samples"][kind].extend(rows)
        if dropped:
            _LOGGER.warning("Ignored %d unreadable charging evidence record(s)", dropped)
        for doc in self._chargers.values():
            self._prune(doc, self._now())
        self._seq = max((item.get("seq", 0) for doc in self._chargers.values()
                         for item in (*doc["plans"], *doc["events"]) if isinstance(item.get("seq"), int)), default=0)

    def _adopt(self, charger_id: str, doc: dict[str, Any]) -> int:
        mine = self._charger(charger_id)
        dropped = 0
        for name in ("plans", "events", "captures"):
            for item in doc.get(name) or ():
                if isinstance(item, dict):
                    mine[name].append(item)
                else:
                    dropped += 1
        for name in ("blobs", "days"):
            found = doc.get(name)
            if isinstance(found, dict):
                mine[name].update({key: value for key, value in found.items() if isinstance(key, str)
                                   and isinstance(value, dict)})
        samples = doc.get("samples")
        if isinstance(samples, dict):
            for kind in SAMPLE_KINDS:
                for row in samples.get(kind) or ():
                    if isinstance(row, dict) and isinstance(row.get("r"), str):
                        mine["samples"][kind].append(row)
                    else:
                        dropped += 1
        return dropped

    def _document(self) -> dict[str, Any]:
        return {"version": STORAGE_VERSION, "chargers": self._chargers}

    def _changed(self) -> None:
        try:
            self._backend().async_delay_save(self._document, SAVE_DELAY_S)
        except Exception:  # noqa: BLE001 - evidence must never break a send or a capture tick
            _LOGGER.warning("Charging evidence could not be scheduled for saving")

    async def async_flush(self) -> None:
        await self._backend().async_save(self._document())

    async def async_remove_charger(self, charger_id: str) -> None:
        if self._chargers.pop(charger_id, None) is not None:
            self._changed()

    # ---- writes: intent evidence

    def record_plan(self, charger_id: str, *, plan_id: str, fingerprint: str, profile: dict[str, Any],
                    intent_at: str, source: str, intent: str, revision: Any = None,
                    context: dict[str, Any] | None = None, blobs: dict[str, Any] | None = None) -> str:
        """Keep the profile that was put on the wire as an immutable version. `plan_id` is the attempt id.

        `blobs` are the tariff/price facts in force when it was made (Stage 6.3), kept once per distinct content and
        referenced by digest, so a later settings or price change can never rewrite what an older version was made
        under. A second call with an id already kept changes nothing (`duplicate`): a version is never edited."""
        if not plan_id or not isinstance(profile, dict):
            return REJECTED
        doc = self._charger(charger_id)
        if any(item.get("id") == plan_id for item in doc["plans"]):
            return DUPLICATE
        refs: dict[str, str] = {}
        for name, blob in (blobs or {}).items():
            if blob is None:
                continue
            digest = hashlib.sha256(json.dumps(blob, sort_keys=True, separators=(",", ":"),
                                               default=str).encode()).hexdigest()[:16]
            doc["blobs"].setdefault(digest, {"name": name, "value": deepcopy(blob)})
            refs[name] = digest
        self._seq += 1
        doc["plans"].append({
            "id": plan_id, "seq": self._seq, "recorded_at": _iso(self._now()), "intent_at": intent_at,
            "fingerprint": fingerprint, "source": source, "intent": intent, "revision": revision,
            "context": deepcopy(context or {}), "refs": refs, "profile": deepcopy(profile),
        })
        self._prune(doc, self._now())
        self._changed()
        return ADDED

    def record_event(self, charger_id: str, kind: str, *, plan_id: str | None, at: str | None = None,
                     **fields: Any) -> str:
        """Append command evidence about a plan version (or, with `plan_id=None`, about no kept version)."""
        if kind not in EVENT_KINDS:
            return REJECTED
        doc = self._charger(charger_id)
        self._seq += 1
        doc["events"].append({"seq": self._seq, "kind": kind, "plan_id": plan_id,
                              "at": at or _iso(self._now()), "recorded_at": _iso(self._now()),
                              **{key: deepcopy(value) for key, value in fields.items()}})
        self._prune(doc, self._now())
        self._changed()
        return ADDED

    def record_readback(self, charger_id: str, effective: Any, *, plan_id: str | None) -> str:
        """Keep one effective-limit readback. `plan_id` only when the caller established it belongs to that version."""
        if not isinstance(effective, dict):
            return REJECTED
        periods = effective.get("periods")
        periods = [dict(item) for item in periods[:MAX_READBACK_PERIODS] if isinstance(item, dict)] \
            if isinstance(periods, list) else []
        return self.record_event(
            charger_id, "readback", plan_id=plan_id, at=effective.get("fetched_at"),
            status=str(effective.get("status"))[:40], requested_at=effective.get("requested_at"),
            periods=periods, truncated=isinstance(effective.get("periods"), list)
            and len(effective["periods"]) > MAX_READBACK_PERIODS, associated=plan_id is not None)

    # ---- writes: measurements

    def record_capture_start(self, charger_id: str, at: datetime | None = None) -> None:
        """Mark that capture (re)started: no sample can exist for the time before it that this run did not see."""
        doc = self._charger(charger_id)
        doc["captures"].append({"at": _iso(at or self._now())})
        self._prune(doc, self._now())
        self._changed()

    def record_sample(self, charger_id: str, kind: str, *, value: Any, observed_at: datetime | None,
                      received_at: datetime | None = None, entity_id: str | None = None, unit: str | None = None,
                      source: str | None = None, normalized: str | None = None, stale: bool = False) -> str:
        """Keep one genuinely read value with its provenance. Returns `added`, `duplicate` or `rejected`.

        Unknown, non-finite, negative-energy or timezone-less observations are rejected (record a gap instead)."""
        if kind not in SAMPLE_KINDS:
            return REJECTED
        if kind == KIND_STATUS:
            if not isinstance(value, str) or not value:
                return REJECTED
            number: Any = value[:40]
        else:
            number = _finite(value)
            if number is None or (kind == KIND_REGISTER and number < 0):
                return REJECTED
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            return REJECTED
        received = received_at or self._now()
        rows = self._charger(charger_id)["samples"][kind]
        tail = rows[-LOOKBACK:]
        stamp = _iso(observed_at)
        for row in tail:
            if row.get("t") == stamp and row.get("e") == entity_id:
                if row.get("v") == number:
                    return DUPLICATE
                flags = ["conflicting_duplicate"]
                break
        else:
            flags = []
        seen = [(_parse(row.get("t")), row) for row in tail if row.get("v") is not None and row.get("e") == entity_id]
        seen = [(when, row) for when, row in seen if when is not None]
        if seen:
            if observed_at < max(when for when, _ in seen):
                flags.append("out_of_order")
            earlier = [(when, row) for when, row in seen if when <= observed_at]
            if kind == KIND_REGISTER and earlier and max(earlier, key=lambda pair: pair[0])[1]["v"] > number:
                flags.append("counter_decrease")
        if (observed_at - received).total_seconds() > FUTURE_SKEW_S:
            flags.append("future_timestamp")
        if stale:  # the source reported this long ago and had not updated since: kept, never trusted as current
            flags.append("stale_source")
        row = {"t": stamp, "r": _iso(received), "v": number, "u": unit, "e": entity_id, "s": source}
        if normalized is not None:
            row["n"] = normalized
        if flags:
            row["q"] = flags
        rows.append(row)
        self._prune(self._charger(charger_id), self._now())
        self._changed()
        return ADDED

    def record_gap(self, charger_id: str, kind: str, reason: str, *, received_at: datetime | None = None,
                   source: str | None = None) -> None:
        """Keep that `kind` could not be read at this time. A repeat of the same reason extends the one gap row."""
        if kind not in SAMPLE_KINDS:
            return
        received = _iso(received_at or self._now())
        rows = self._charger(charger_id)["samples"][kind]
        last = rows[-1] if rows else None
        if last is not None and last.get("v") is None and last.get("g") == reason and last.get("s") == source:
            last["r2"] = received
        else:
            rows.append({"t": None, "r": received, "r2": received, "v": None, "g": reason, "s": source})
        self._prune(self._charger(charger_id), self._now())
        self._changed()

    # ---- reads (copies; the seam for Stage 6.3 queries)

    def plan_versions(self, charger_id: str) -> list[dict[str, Any]]:
        """The kept plan versions, oldest first, each with its own tariff/price blobs resolved (`None`: not kept)."""
        doc = self._charger(charger_id, create=False)
        return [self._resolved(doc, item) for item in doc.get("plans", [])]

    def plan_version(self, charger_id: str, plan_id: str) -> dict[str, Any] | None:
        doc = self._charger(charger_id, create=False)
        for item in doc.get("plans", []):
            if item.get("id") == plan_id:
                return self._resolved(doc, item)
        return None

    @staticmethod
    def _resolved(doc: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        out = deepcopy(item)
        found = doc.get("blobs", {})
        out["blobs"] = {name: deepcopy((found.get(ref) or {}).get("value")) for name, ref in (item.get("refs") or {}).items()}
        return out

    def oldest_evidence(self, charger_id: str) -> datetime | None:
        """The earliest retained observation, receipt, plan or capture start: nothing before it can be answered."""
        doc = self._charger(charger_id, create=False)
        stamps = [_parse(row.get(name)) for rows in doc.get("samples", {}).values() for row in rows[:1]
                  for name in ("t", "r")]
        stamps += [_parse(item.get(name)) for name, items in (("recorded_at", doc.get("plans", [])[:1]),
                                                              ("at", doc.get("captures", [])[:1])) for item in items]
        found = [stamp for stamp in stamps if stamp is not None]
        return min(found) if found else None

    def digests(self, charger_id: str) -> dict[str, dict[str, Any]]:
        return deepcopy(self._charger(charger_id, create=False).get("days", {}))

    def keep_digest(self, charger_id: str, day: str, digest: dict[str, Any]) -> bool:
        """Keep one finished local day's compact summary once; it is never replaced (`False`: already kept)."""
        doc = self._charger(charger_id)
        if day in doc["days"]:
            return False
        doc["days"][day] = deepcopy(digest)
        self._prune(doc, self._now())
        self._changed()
        return True

    def events(self, charger_id: str, *, plan_id: str | None = None, kinds: Iterable[str] | None = None,
               since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
        """Command evidence in the order it was recorded, optionally for one version, kind and time range (`at`)."""
        wanted = None if kinds is None else set(kinds)
        out = []
        for item in self._charger(charger_id, create=False).get("events", []):
            if (plan_id is not None and item.get("plan_id") != plan_id) or (wanted and item.get("kind") not in wanted):
                continue
            when = _parse(item.get("at"))
            if (since or until) and when is None:
                continue
            if (since is not None and when < since) or (until is not None and when >= until):
                continue
            out.append(deepcopy(item))
        return out

    def dispatch_state(self, charger_id: str, plan_id: str) -> str:
        """What the events support about a kept plan version, never more than they prove.

        `ack_received` (the charger answered), `dispatch_started` (marker only: possibly sent, possibly not),
        `aborted_before_dispatch`, `conflicting` (an abort alongside a start/answer, or an answer with no marker) and
        `unknown` (no event, or only an unanswered ACK of `unknown`). Nothing here says a profile was sent unless the
        charger answered."""
        events = [item for item in self._charger(charger_id, create=False).get("events", [])
                  if item.get("plan_id") == plan_id]
        kinds = {item.get("kind") for item in events}
        started, aborted = "dispatch_started" in kinds, "dispatch_aborted" in kinds
        answered = any(item.get("kind") == "ack" and item.get("status") not in (None, "", "unknown") for item in events)
        if aborted and (started or answered):
            return DISPATCH_CONFLICT
        if answered:
            return DISPATCH_ACK_RECEIVED if started else DISPATCH_CONFLICT
        if aborted:
            return DISPATCH_ABORTED
        return DISPATCH_STARTED if started else DISPATCH_UNKNOWN

    def energy_segments(self, charger_id: str, kind: str, *, since: datetime | None = None,
                        until: datetime | None = None) -> list[dict[str, Any]]:
        """`derive_energy` over the stored rows of `kind` with this charger's explicit gaps and restart marks."""
        rows = [*self.samples(charger_id, kind, since=since, until=until), *self.gaps(charger_id, kind)]
        return derive_energy(rows, kind, restarts=self.capture_starts(charger_id))

    def samples(self, charger_id: str, kind: str, *, since: datetime | None = None,
                until: datetime | None = None) -> list[dict[str, Any]]:
        """Observations of `kind` sorted by observed time (gap rows excluded), `since` <= observed < `until`."""
        out = []
        for row in self._charger(charger_id, create=False).get("samples", {}).get(kind, []):
            when = _parse(row.get("t")) if row.get("v") is not None else None
            if when is None or (since is not None and when < since) or (until is not None and when >= until):
                continue
            out.append((when, deepcopy(row)))
        return [row for _when, row in sorted(out, key=lambda pair: pair[0])]

    def gaps(self, charger_id: str, kind: str) -> list[dict[str, Any]]:
        """The explicit could-not-read rows of `kind`, in the order recorded."""
        return [deepcopy(row) for row in self._charger(charger_id, create=False).get("samples", {}).get(kind, [])
                if row.get("v") is None]

    def capture_starts(self, charger_id: str) -> list[str]:
        return [item["at"] for item in self._charger(charger_id, create=False).get("captures", [])
                if isinstance(item.get("at"), str)]

    # ---- internals

    def _charger(self, charger_id: str, create: bool = True) -> dict[str, Any]:
        doc = self._chargers.get(charger_id)
        if doc is None:
            doc = {"plans": [], "events": [], "captures": [], "blobs": {}, "days": {},
                   "samples": {kind: [] for kind in SAMPLE_KINDS}}
            if create:
                self._chargers[charger_id] = doc
        return doc

    def _prune(self, doc: dict[str, Any], now: datetime) -> None:
        cutoff = now - timedelta(days=RETENTION_DAYS)

        def fresh(item: dict[str, Any], *names: str) -> bool:
            for name in names:
                when = _parse(item.get(name))
                if when is not None:
                    return when >= cutoff
            return True  # an unreadable stamp is not a reason to drop evidence here; the count bound applies

        doc["plans"][:] = [item for item in doc["plans"] if fresh(item, "recorded_at")][-MAX_PLANS:]
        doc["events"][:] = [item for item in doc["events"] if fresh(item, "recorded_at")][-MAX_EVENTS:]
        doc["captures"][:] = [item for item in doc["captures"] if fresh(item, "at")][-MAX_CAPTURE_MARKS:]
        for rows in doc["samples"].values():
            rows[:] = [row for row in rows if fresh(row, "t", "r")][-MAX_SAMPLES_PER_KIND:]
        used = {ref for item in doc["plans"] for ref in (item.get("refs") or {}).values()}
        doc["blobs"] = {key: value for key, value in doc["blobs"].items() if key in used}
        doc["days"] = dict(sorted(doc["days"].items())[-MAX_DIGEST_DAYS:])


def evidence_for(hass: Any) -> ChargingEvidenceStore | None:
    """The installation's store, or `None` before setup created it (callers then simply keep nothing)."""
    data = getattr(hass, "data", None)
    store = data.get(DATA_KEY) if isinstance(data, dict) else None
    return store if isinstance(store, ChargingEvidenceStore) else None


async def async_get_evidence(hass: Any) -> ChargingEvidenceStore:
    """Create (once) and load the installation's store."""
    store = evidence_for(hass)
    if store is None:
        store = ChargingEvidenceStore(hass)
        hass.data[DATA_KEY] = store
        await store.async_load()
    return store


def _as_of(value: Any, fallback: datetime) -> datetime:
    return _parse(value) or fallback


def derive_energy(samples: list[dict[str, Any]], kind: str, *, restarts: Iterable[str] = (),
                  max_power_gap_s: float = MAX_POWER_GAP_S) -> list[dict[str, Any]]:
    """Energy segments from ONE `kind` (register or power), each labelled by how it was obtained.

    `samples` should include the kind's explicit gap rows (`v` is `None`; they cover received times `r`..`r2`) and
    `restarts` the capture-start marks; both are coverage evidence. A pair of consecutive readings is *unobserved*
    when a recorded gap or a capture restart falls between them (receipt time axis) or an endpoint is `stale_source`.
    Nothing is ever bridged:

    * `power_w`: `power_integrated_estimate` (trapezoid) only for an observed, trustworthy pair no further apart
      than `max_power_gap_s`. Anything else is `unknown` with `kwh: None` and `reasons`.
    * `energy_register_kwh`: the counter difference is a `meter_counter` segment. When the span is unobserved the
      segment says so (`coverage: "unobserved"`, `placement: "unknown"`, `reasons`): the energy between the two
      readings, with no claim about when or at what rate it was delivered. An observed pair is
      `coverage: "endpoints_only"`, `placement: "within_interval"`. A decrease is `unknown` (`counter_decrease`;
      `probable_reset` if it fell to near 0): the amount since the reset is not assumed.
    * Always `unknown`, even for a register: a source/unit change, a conflicting duplicate (same entity and
      observed time, different value), a `future_timestamp` or `out_of_order` endpoint.

    Segments never come from plans, limits or status."""
    if kind not in (KIND_REGISTER, KIND_POWER):
        return []  # current and status are not energy
    gaps: list[tuple[datetime, datetime]] = []
    values = []
    for row in samples:
        if row.get("v") is None:
            first = _parse(row.get("r"))
            if first is not None:
                gaps.append((first, _as_of(row.get("r2"), first)))
        elif _parse(row.get("t")) is not None and isinstance(row["v"], (int, float)):
            values.append(row)
    marks = [mark for mark in (_parse(item) for item in restarts) if mark is not None]
    seen_values: dict[tuple[Any, str], set[float]] = {}
    for row in values:
        seen_values.setdefault((row.get("e"), row["t"]), set()).add(row["v"])
    conflicted = {key for key, found in seen_values.items() if len(found) > 1}
    ordered = sorted(values, key=lambda row: _parse(row["t"]))
    is_register = kind == KIND_REGISTER
    segments: list[dict[str, Any]] = []
    for before, after in zip(ordered, ordered[1:]):
        start, end = _parse(before["t"]), _parse(after["t"])
        if end <= start:
            continue  # same instant: a conflict is reported by the neighbours below, never as a zero-length segment
        base = {"start": _iso(start), "end": _iso(end), "entity": after.get("e"),
                "from_value": before["v"], "to_value": after["v"], "unit": after.get("u")}
        lower = max(start, _as_of(before.get("r"), start))
        upper = max(end, _as_of(after.get("r"), end))
        flags = {*(before.get("q") or ()), *(after.get("q") or ())}
        hard: list[str] = []
        if before.get("e") != after.get("e"):
            hard.append("source_changed")
        if before.get("u") != after.get("u"):
            hard.append("unit_changed")
        if (before.get("e"), before["t"]) in conflicted or (after.get("e"), after["t"]) in conflicted \
                or "conflicting_duplicate" in flags:
            hard.append("conflicting_duplicate")
        hard += [name for name in ("future_timestamp", "out_of_order") if name in flags]
        soft: list[str] = []
        if any(g_end > lower and g_start < upper for g_start, g_end in gaps):
            soft.append("recorded_gap")
        if any(lower < mark <= upper for mark in marks):
            soft.append("capture_restart")
        if "stale_source" in flags:
            soft.append("stale_source")
        unknown = {**base, "basis": BASIS_UNKNOWN, "kwh": None}
        if hard:
            segments.append({**unknown, "reason": hard[0], "reasons": hard + soft})
        elif is_register:
            if after["v"] < before["v"]:
                segments.append({**unknown, "reason": "counter_decrease", "reasons": ["counter_decrease", *soft],
                                 "probable_reset": after["v"] <= RESET_TOLERANCE_KWH})
            elif soft:
                segments.append({**base, "basis": BASIS_METER, "kwh": after["v"] - before["v"],
                                 "coverage": "unobserved", "placement": "unknown", "reasons": soft})
            else:
                segments.append({**base, "basis": BASIS_METER, "kwh": after["v"] - before["v"],
                                 "coverage": "endpoints_only", "placement": "within_interval"})
        else:
            seconds = (end - start).total_seconds()
            if seconds > max_power_gap_s:
                soft.append("span_too_long")
            if before["v"] < 0 or after["v"] < 0:
                soft.append("negative_power")
            if soft:
                segments.append({**unknown, "reason": soft[0], "reasons": soft})
            else:
                watts = (before["v"] + after["v"]) / 2.0
                if before.get("u") == "kW":
                    watts *= 1000.0
                segments.append({**base, "basis": BASIS_POWER, "kwh": watts * seconds / 3_600_000.0})
    return segments


class MeasurementCapture:
    """Reads the connector's genuine HA measurements on a tick and keeps them, with gaps, in the evidence store.

    Resolution is the tick (`TICK_S`): the latest state is read, so intermediate changes between ticks are not
    retained, and an unchanged state (same observed time) is stored once. It reads through the existing connector-bound
    `_live_measurements`, so entity matching, units and the power rule are the dashboard's, not a second copy."""

    TICK_S: Final = 60

    def __init__(self, hass: Any, charger_id: str, controller: Any, store: ChargingEvidenceStore, *,
                 now: Callable[[], datetime] | None = None) -> None:
        self._hass = hass
        self._charger_id = charger_id
        self._controller = controller
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cancel: Callable[[], None] | None = None
        self._compacted_on: Any = None

    def start(self) -> None:
        from homeassistant.helpers.event import async_track_time_interval

        self._store.record_capture_start(self._charger_id, self._now())
        self.capture()
        self._cancel = async_track_time_interval(self._hass, lambda _now: self.capture(),
                                                 timedelta(seconds=self.TICK_S))

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    def _compact(self, now: datetime) -> None:
        """Once per local day (and at the first tick): keep digests of finished days. Never raises."""
        try:
            from .. import time_zones
            from .history import compact_days

            zone = time_zones.zone(getattr(getattr(self._hass, "config", None), "time_zone", None))
            if zone is None:
                return
            today = now.astimezone(zone).date()
            if self._compacted_on != today:
                self._compacted_on = today
                compact_days(self._store, self._charger_id, zone, now)
        except Exception:  # noqa: BLE001 - a digest is a convenience; capture must continue
            _LOGGER.debug("Charging evidence digests were not compacted", exc_info=True)

    def capture(self, now: datetime | None = None) -> None:
        """One read of every source; never raises, never writes to the charger."""
        now = now or self._now()
        self._compact(now)
        try:
            from ..api.morek_schedule import _live_measurements

            entities: dict[str, str | None] = {}
            live = _live_measurements(self._hass, self._controller, now, entities=entities)
        except Exception:  # noqa: BLE001 - an unreadable source is a gap, not a failure
            for kind in SAMPLE_KINDS:
                self._store.record_gap(self._charger_id, kind, "read_failed", received_at=now)
            return
        sources = live.get("sources") or {}
        for kind, key, why in ((KIND_POWER, "power_w", sources.get("power")),
                               (KIND_CURRENT, "current_a", "ocpp_registry"),
                               (KIND_REGISTER, "energy_register_kwh", sources.get("energy"))):
            reading = live.get(key)
            when = _parse(reading.get("observed_at")) if isinstance(reading, dict) else None
            if when is None:
                reason = "unreadable" if why in ("ocpp_registry", "configured_entity") else str(why or "none")
                self._store.record_gap(self._charger_id, kind, reason, received_at=now, source=why)
                continue
            self._store.record_sample(self._charger_id, kind, value=reading.get("value"), observed_at=when,
                                      received_at=now, entity_id=entities.get(kind), unit=reading.get("unit"),
                                      source=why, stale=reading.get("fresh") is False)
        status = live.get("status")
        when = _parse(status.get("observed_at")) if isinstance(status, dict) else None
        if when is None:
            self._store.record_gap(self._charger_id, KIND_STATUS, "unreadable", received_at=now)
        else:
            self._store.record_sample(self._charger_id, KIND_STATUS, value=status.get("value"), observed_at=when,
                                      received_at=now, entity_id=entities.get(KIND_STATUS), source="ocpp_registry",
                                      normalized=status.get("normalized"), stale=status.get("fresh") is False)
