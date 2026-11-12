"""Persisted execution ownership metadata; this release never arms schedule mode.

The document is independent of Auto settings, charge sessions and Morek profile
records. Only a first-use legacy record can be created here. Status never writes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN

STORAGE_KEY = f"{DOMAIN}_execution_ownership"
SCHEMA_VERSION = 1
_DATA_KEY = "spotnav_execution_ownership_store"
_MISSING = object()


def _read_envelope(path: str) -> Any:
    """Read without HA Store's corrupt-file rename or a silent corrupt-to-missing fallback."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _MISSING


def _decode(raw: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    """Validate the entire document: never overwrite an unknown or partial record."""
    if raw is _MISSING:
        return "missing", {}
    if not isinstance(raw, dict) or type(raw.get("version")) is not int:
        return "malformed", {}
    minor = raw.get("minor_version", 1)
    if type(minor) is not int:
        return "malformed", {}
    if raw["version"] != 1 or minor != 1:
        return "unsupported_version", {}
    data = raw.get("data")
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        return "malformed", {}
    if data["schema_version"] != SCHEMA_VERSION:
        return "unsupported_version", {}
    if set(data) != {"schema_version", "records"} or not isinstance(data["records"], dict):
        return "malformed", {}
    records = data["records"]
    for entry_id, record in records.items():
        if (not isinstance(entry_id, str) or not entry_id or not isinstance(record, dict)
                or set(record) not in ({"station_id", "connector_id", "owner"},
                                       {"station_id", "connector_id", "owner", "transition"})
                or not isinstance(record["station_id"], str) or not record["station_id"]
                or type(record["connector_id"]) is not int or record["connector_id"] < 1
                or record["owner"] not in ("legacy", "morek_schedule")):
            return "malformed", {}
        if "transition" in record:
            transition = record["transition"]
            if (record["owner"] != "legacy" or not isinstance(transition, dict)
                    or set(transition) != {"version", "state"} or type(transition["version"]) is not int
                    or transition["version"] != 1 or transition["state"] not in
                    ("requested", "interrupted", "drained_unarmed")):
                return "malformed", {}
    return "valid", records


class ExecutionOwnershipStore:
    """One installation-wide document, serialized to avoid lost first-use records."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = Store(hass, 1, STORAGE_KEY, atomic_writes=True)
        self._lock = asyncio.Lock()
        self._loaded = False
        self._state = "missing"
        self._records: dict[str, dict[str, Any]] = {}
        self._contenders: dict[tuple[str, int], set[str]] = {}
        self._cancelled_write = False
        self._transition_save_uncertain = False
        self._owner_save_uncertain = False

    async def async_handover_unarmed(
        self, entry_id: str, identity: Mapping[str, Any], can_commit: Callable[[], bool],
        stop_requested: Callable[[], bool], identity_valid: Callable[[], bool],
    ) -> str:
        """Commit or compensate a drained entry; caller holds connector admission."""
        async with self._lock:
            await self._load()
            physical = (identity.get("resolved_id"), identity.get("connector_id"))
            record = self._records.get(entry_id)
            if (self._state != "valid" or self._transition_save_uncertain or self._cancelled_write
                    or not record or record.get("owner") != "legacy"
                    or record.get("transition") != {"version": 1, "state": "drained_unarmed"}
                    or (record["station_id"], record["connector_id"]) != physical
                    or len(self._contenders.get(physical, set())) > 1
                    or any(other != entry_id and (item["station_id"], item["connector_id"]) == physical
                           for other, item in self._records.items())):
                return "ownership_unavailable"
            try:
                state, disk = _decode(await self._hass.async_add_executor_job(_read_envelope, self._store.path))
                if state != "valid" or disk != self._records or not can_commit():
                    return "handover_interrupted"
                owned = {**record, "owner": "morek_schedule"}
                del owned["transition"]
                records = {**self._records, entry_id: owned}
                await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
                state, disk = _decode(await self._hass.async_add_executor_job(_read_envelope, self._store.path))
                if state != "valid" or disk != records:
                    raise OSError("ownership verification failed")
                self._records = records
                if stop_requested():
                    if not identity_valid():
                        return "identity_changed"
                    restored = {**record, "transition": {"version": 1, "state": "interrupted"}}
                    records = {**records, entry_id: restored}
                    await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
                    state, disk = _decode(await self._hass.async_add_executor_job(_read_envelope, self._store.path))
                    if state != "valid" or disk != records:
                        raise OSError("restoration verification failed")
                    self._records = records
                    return "interrupted"
                if not can_commit():
                    return "handover_changed"
                return "handed_over_unarmed"
            except asyncio.CancelledError:
                self._state = "save_failed"
                self._transition_save_uncertain = self._owner_save_uncertain = self._cancelled_write = True
                raise
            except Exception:  # noqa: BLE001 - no retry after an uncertain write
                self._state = "save_failed"
                self._transition_save_uncertain = self._owner_save_uncertain = True
                return "save_uncertain"

    async def async_set_entry_transition(
        self, entry_id: str, identity: dict[str, Any], resolve_identity: Callable[[], Mapping[str, Any]],
        state: str,
    ) -> str:
        """Persist one monotonic unarmed entry marker; never acquire a connector lock here."""
        async with self._lock:
            await self._load()
            if self._state != "valid" or self._cancelled_write:
                return "ownership_unavailable"
            record = self._records.get(entry_id)
            physical = (identity.get("resolved_id"), identity.get("connector_id"))
            fresh = resolve_identity()
            if (not record or record["owner"] != "legacy" or not identity.get("supported")
                    or (record["station_id"], record["connector_id"]) != physical
                    or not fresh.get("supported") or (fresh.get("resolved_id"), fresh.get("connector_id")) != physical
                    or len(self._contenders.get(physical, set())) > 1
                    or any(other != entry_id and (item["station_id"], item["connector_id"]) == physical
                           for other, item in self._records.items())):
                return "ownership_unavailable"
            previous = record.get("transition", {}).get("state")
            if (state == "requested" and previous is not None) or (
                    state == "drained_unarmed" and previous != "requested") or (
                    state == "interrupted" and previous not in ("requested", "drained_unarmed")):
                return "ownership_unavailable"
            if state not in ("requested", "interrupted", "drained_unarmed"):
                return "ownership_unavailable"
            records = {**self._records, entry_id: {**record, "transition": {"version": 1, "state": state}}}
            try:
                await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
                raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
                saved_state, saved_records = _decode(raw)
                if saved_state != "valid" or saved_records != records:
                    self._state = "save_failed"
                    self._transition_save_uncertain = True
                    return "save_uncertain"
            except asyncio.CancelledError:
                self._state = "save_failed"
                self._transition_save_uncertain = True
                self._cancelled_write = True
                raise
            except BaseException:
                self._state = "save_failed"
                self._transition_save_uncertain = True
                raise
            self._records = records
            return "saved"

    async def async_abort_entry_transition(
        self, entry_id: str, identity: Mapping[str, Any], expected_state: str,
        can_commit: Callable[[], bool],
    ) -> str:
        """Remove only a verified unarmed marker; caller holds connector admission."""
        async with self._lock:
            await self._load()
            if self._state != "valid" or self._transition_save_uncertain or self._cancelled_write:
                return "ownership_unavailable"
            record = self._records.get(entry_id)
            physical = (identity.get("resolved_id"), identity.get("connector_id"))
            if (not record or record["owner"] != "legacy"
                    or (record["station_id"], record["connector_id"]) != physical
                    or record.get("transition", {}).get("state") != expected_state
                    or len(self._contenders.get(physical, set())) > 1
                    or any(other != entry_id and (item["station_id"], item["connector_id"]) == physical
                           for other, item in self._records.items())):
                return "ownership_unavailable"
            try:
                disk_state, disk_records = _decode(await self._hass.async_add_executor_job(_read_envelope, self._store.path))
                if disk_state != "valid" or disk_records != self._records or not can_commit():
                    return "recovery_changed"
                updated = dict(record)
                del updated["transition"]
                records = {**self._records, entry_id: updated}
                await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
                disk_state, disk_records = _decode(await self._hass.async_add_executor_job(_read_envelope, self._store.path))
                if disk_state != "valid" or disk_records != records:
                    self._state = "save_failed"
                    self._transition_save_uncertain = True
                    return "save_uncertain"
            except asyncio.CancelledError:
                self._state = "save_failed"
                self._transition_save_uncertain = True
                self._cancelled_write = True
                raise
            except Exception:  # noqa: BLE001 - a failed write may have landed
                self._state = "save_failed"
                self._transition_save_uncertain = True
                return "save_uncertain"
            self._records = records
            return "aborted"

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
            self._state, self._records = _decode(raw)
        except (OSError, ValueError, TypeError):
            self._state, self._records = "malformed", {}
        self._loaded = True

    async def _async_ensure_locked_connector(
        self, entry_id: str, identity: dict[str, Any], resolve_identity: Callable[[], Mapping[str, Any]]
    ) -> str:
        """Ensure a legacy record; caller must hold the shared physical connector lock."""
        async with self._lock:
            if self._cancelled_write or self._transition_save_uncertain:
                # An executor-backed write can outlive cancellation; rereading now
                # cannot prove it will not land later. An uncertain transition
                # must not be turned into a fresh legacy initialization either.
                return "save_uncertain"
            # A failed or silently unsuccessful save has an unknown outcome. Reread
            # the durable document before any retry; never publish cached intent.
            if self._state == "save_failed":
                self._loaded = False
            await self._load()
            station, connector = identity.get("resolved_id"), identity.get("connector_id")
            if (not identity.get("supported") or not isinstance(station, str) or not station
                    or type(connector) is not int or connector < 1):
                return "identity_unresolved"
            fresh = resolve_identity()
            if (fresh.get("supported") is not True or type(fresh.get("connector_id")) is not int or
                    (fresh.get("resolved_id"), fresh.get("connector_id")) != (station, connector)):
                return "identity_changed"
            if self._state not in ("missing", "valid"):
                return f"ownership_{self._state}"
            stored_physical = [(item["station_id"], item["connector_id"]) for item in self._records.values()]
            if len(stored_physical) != len(set(stored_physical)):
                return "ownership_conflict"
            physical = (station, connector)
            contenders = self._contenders.setdefault(physical, set())
            contenders.add(entry_id)
            contenders.update(other for other, item in self._records.items()
                              if (item["station_id"], item["connector_id"]) == physical)
            if (len(contenders) > 1 or any(other != entry_id and
                    (item["station_id"], item["connector_id"]) == physical
                    for other, item in self._records.items())):
                return "ownership_conflict"
            existing = self._records.get(entry_id)
            if existing is not None:
                if (existing["station_id"], existing["connector_id"]) != physical:
                    return "ownership_identity_mismatch"
                return "already_initialized"
            # A document that already exists but lacks this binding is not the
            # first installation of the ownership schema. Do not turn lost or
            # partial per-entry evidence into permission for legacy writes.
            if self._state == "valid":
                return "ownership_missing"
            records = {**self._records, entry_id: {
                "station_id": station, "connector_id": connector, "owner": "legacy",
            }}
            try:
                await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
                raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
                saved_state, saved_records = _decode(raw)
                if saved_state != "valid" or saved_records != records:
                    self._state = "save_failed"
                    self._cancelled_write = True
                    return "save_uncertain"
            except asyncio.CancelledError:
                self._state = "save_failed"
                self._cancelled_write = True
                raise
            except BaseException:
                # HA Store may report success after a write error; cancellation can
                # also leave a write in flight. Do not publish success from memory.
                self._state = "save_failed"
                self._cancelled_write = True
                raise
            self._records, self._state = records, "valid"
            fresh = resolve_identity()
            if (fresh.get("supported") is not True or type(fresh.get("connector_id")) is not int or
                    (fresh.get("resolved_id"), fresh.get("connector_id")) != physical):
                return "identity_changed"
            return "initialized"

    async def async_status(self, entry_id: str, identity: dict[str, Any]) -> dict[str, Any]:
        """Read metadata only; this is not a command gate or a safety assessment."""
        async with self._lock:
            await self._load()
            state = "valid" if self._transition_save_uncertain else self._state
            record = self._records.get(entry_id)
            if state == "valid":
                if record is None:
                    physical = (identity.get("resolved_id"), identity.get("connector_id"))
                    state = ("conflict" if physical[0] is not None and any(
                        (item["station_id"], item["connector_id"]) == physical
                        for item in self._records.values()) else "missing")
                elif len(self._contenders.get((record["station_id"], record["connector_id"]), set())) > 1:
                    state = "conflict"
                elif any(other != entry_id and (item["station_id"], item["connector_id"]) ==
                         (record["station_id"], record["connector_id"])
                         for other, item in self._records.items()):
                    state = "conflict"
                elif (identity.get("connector_id") is not None and
                      identity.get("connector_id") != record["connector_id"]):
                    state = "identity_mismatch"
                elif identity.get("resolved_id") is None:
                    state = "identity_unresolved"
                elif (not identity.get("supported") or
                      (identity.get("resolved_id"), identity.get("connector_id")) !=
                      (record["station_id"], record["connector_id"])):
                    state = "identity_mismatch"
            person_stop_safe = (self._transition_save_uncertain and not self._owner_save_uncertain
                                and state == "valid" and record is not None and record["owner"] == "legacy")
            if self._transition_save_uncertain:
                state = "save_failed"
            return {
                "schema_version": SCHEMA_VERSION,
                "record_state": state,
                "recorded_owner": record["owner"] if record is not None and state == "valid" else None,
                "station_id": record["station_id"] if record else None,
                "connector_id": record["connector_id"] if record else None,
                "transition_state": record.get("transition", {}).get("state") if record and state == "valid" else None,
                "person_stop_safe_during_transition_failure": person_stop_safe,
                "schedule_mode_available": False,
                "armed": False,
                "ready": False,
                "blockers": ["command_isolation_not_implemented", "safety_unverified", "site_regulation_conflict_unresolved",
                             "transaction_authorization_unverified"],
            }


def ownership_store(hass: HomeAssistant) -> ExecutionOwnershipStore:
    """The same store is used across entries and their status requests."""
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = ExecutionOwnershipStore(hass)
    return hass.data[_DATA_KEY]
