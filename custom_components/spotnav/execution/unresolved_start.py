"""Durable, attempt-specific start evidence. This module controls no charger.

The record is evidence, not session ownership, authorization, or measured flow.
No controller produces or consumes these records in this release.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN

STORAGE_KEY = f"{DOMAIN}_unresolved_starts"
SCHEMA_VERSION = 1
_DATA_KEY = "spotnav_unresolved_start_store"
_MISSING = object()
CommandEvidence = Literal["unknown", "dispatched", "not_dispatched"]


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


@dataclass(frozen=True, slots=True)
class UnresolvedStart:
    """Immutable identity/context and revisioned command evidence for one attempt."""

    attempt_id: str
    station_id: str
    connector_id: int
    session_id: str
    origin: str
    prospective_owner: str | None
    command_evidence: CommandEvidence = "unknown"
    revision: int = 0

    def valid(self) -> bool:
        return (
            _uuid(self.attempt_id) and _text(self.station_id)
            and type(self.connector_id) is int and self.connector_id > 0
            and _uuid(self.session_id) and _text(self.origin)
            and (self.prospective_owner is None or _text(self.prospective_owner))
            and self.command_evidence in ("unknown", "dispatched", "not_dispatched")
            and type(self.revision) is int
            and ((self.revision == 0 and self.command_evidence == "unknown")
                 or (self.revision == 1 and self.command_evidence in ("dispatched", "not_dispatched")))
        )


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """`state` must be checked: non-valid states never mean no unresolved attempts."""

    state: str
    records: tuple[UnresolvedStart, ...]
    #: Candidate document after an uncertain write; never presented as durable.
    pending_records: tuple[UnresolvedStart, ...] = ()


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_envelope(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    except FileNotFoundError:
        return _MISSING


def _decode(raw: Any) -> EvidenceSnapshot:
    if raw is _MISSING:
        return EvidenceSnapshot("missing", ())
    if not isinstance(raw, dict) or type(raw.get("version")) is not int:
        return EvidenceSnapshot("malformed", ())
    minor = raw.get("minor_version", 1)
    if type(minor) is not int:
        return EvidenceSnapshot("malformed", ())
    if raw["version"] != 1 or minor != 1:
        return EvidenceSnapshot("unsupported_version", ())
    data = raw.get("data")
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        return EvidenceSnapshot("malformed", ())
    if data["schema_version"] != SCHEMA_VERSION:
        return EvidenceSnapshot("unsupported_version", ())
    if set(data) != {"schema_version", "records"} or not isinstance(data["records"], list):
        return EvidenceSnapshot("malformed", ())
    records: list[UnresolvedStart] = []
    for item in data["records"]:
        if not isinstance(item, dict) or set(item) != set(UnresolvedStart.__dataclass_fields__):
            return EvidenceSnapshot("malformed", ())
        try:
            record = UnresolvedStart(**item)
            if not record.valid():
                return EvidenceSnapshot("malformed", ())
        except (TypeError, ValueError):
            return EvidenceSnapshot("malformed", ())
        records.append(record)
    if len({item.attempt_id for item in records}) != len(records):
        return EvidenceSnapshot("conflict", ())
    return EvidenceSnapshot("valid", tuple(records))


class UnresolvedStartStore:
    """One installation-wide store; status is read-only and mutations serialize."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = Store(hass, 1, STORAGE_KEY, atomic_writes=True)
        self._lock = asyncio.Lock()
        self._loaded = False
        self._snapshot = EvidenceSnapshot("missing", ())

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
            self._snapshot = _decode(raw)
        except (OSError, ValueError, TypeError):
            self._snapshot = EvidenceSnapshot("malformed", ())
        self._loaded = True

    async def async_status(self) -> EvidenceSnapshot:
        """Read evidence without creating, resolving, or rewriting anything."""
        async with self._lock:
            await self._load()
            return self._snapshot

    async def _save(self, records: tuple[UnresolvedStart, ...]) -> str:
        """Confirm disk contents; a failure/cancellation blocks writes in this instance."""
        before = self._snapshot.records
        self._snapshot = EvidenceSnapshot("save_uncertain", before, records)
        try:
            await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": [asdict(r) for r in records]})
            raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
            written = _decode(raw)
            if written != EvidenceSnapshot("valid", records):
                return "save_uncertain"
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed write can still have reached disk
            return "save_uncertain"
        self._snapshot = written
        return "saved"

    async def async_add(self, record: UnresolvedStart) -> str:
        """Save a new unknown attempt; a repeated/conflicting ID is never overwritten."""
        if not isinstance(record, UnresolvedStart) or not record.valid() or record.revision != 0:
            return "invalid_record"
        async with self._lock:
            await self._load()
            if self._snapshot.state not in ("missing", "valid"):
                return self._snapshot.state
            if any(item.attempt_id == record.attempt_id for item in self._snapshot.records):
                return "duplicate_attempt"
            return await self._save((*self._snapshot.records, record))

    async def async_refine(
        self, *, attempt_id: str, station_id: str, connector_id: int, session_id: str,
        expected_revision: int, command_evidence: Literal["dispatched", "not_dispatched"],
    ) -> str:
        """Refine exactly one attempt's command evidence, without resolving the record."""
        if (not _uuid(attempt_id) or not _text(station_id) or type(connector_id) is not int
                or connector_id < 1 or not _uuid(session_id) or type(expected_revision) is not int
                or expected_revision < 0 or command_evidence not in ("dispatched", "not_dispatched")):
            return "invalid_update"
        async with self._lock:
            await self._load()
            if self._snapshot.state not in ("missing", "valid"):
                return self._snapshot.state
            record = next((item for item in self._snapshot.records if item.attempt_id == attempt_id), None)
            if record is None:
                return "unknown_attempt"
            if (record.station_id, record.connector_id, record.session_id) != (station_id, connector_id, session_id):
                return "identity_mismatch"
            if record.revision != expected_revision or record.command_evidence != "unknown":
                return "stale_update"
            refined = replace(record, command_evidence=command_evidence, revision=record.revision + 1)
            records = tuple(refined if item.attempt_id == attempt_id else item for item in self._snapshot.records)
            return await self._save(records)


def unresolved_start_store(hass: HomeAssistant) -> UnresolvedStartStore:
    """One store/lock per HA instance; future integrations must share this accessor."""
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = UnresolvedStartStore(hass)
    return hass.data[_DATA_KEY]
