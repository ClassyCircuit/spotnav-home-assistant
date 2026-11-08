"""Persisted execution ownership metadata; this release never enforces or arms it.

The document is independent of Auto settings, charge sessions and Morek profile
records. Only a first-use legacy record can be created here. Status never writes.
"""

from __future__ import annotations

import asyncio
import json
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
                or set(record) != {"station_id", "connector_id", "owner"}
                or not isinstance(record["station_id"], str) or not record["station_id"]
                or type(record["connector_id"]) is not int or record["connector_id"] < 1
                or record["owner"] not in ("legacy", "morek_schedule")):
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

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            raw = await self._hass.async_add_executor_job(_read_envelope, self._store.path)
            self._state, self._records = _decode(raw)
        except (OSError, ValueError, TypeError):
            self._state, self._records = "malformed", {}
        self._loaded = True

    async def async_initialize(self, entry_id: str, identity: dict[str, Any]) -> None:
        """Create only a legacy record, only for a uniquely resolved physical connector."""
        async with self._lock:
            await self._load()
            station, connector = identity.get("resolved_id"), identity.get("connector_id")
            if (self._state not in ("missing", "valid") or entry_id in self._records
                    or not identity.get("supported") or not isinstance(station, str) or not station
                    or type(connector) is not int or connector < 1):
                return
            records = {**self._records, entry_id: {
                "station_id": station, "connector_id": connector, "owner": "legacy",
            }}
            try:
                await self._store.async_save({"schema_version": SCHEMA_VERSION, "records": records})
            except Exception:  # noqa: BLE001 - status must expose an uncertain save, not assume success
                self._state = "save_failed"
                return
            self._records, self._state = records, "valid"

    async def async_status(self, entry_id: str, identity: dict[str, Any]) -> dict[str, Any]:
        """Read metadata only; this is not a command gate or a safety assessment."""
        async with self._lock:
            await self._load()
            state = self._state
            record = self._records.get(entry_id)
            if state == "valid":
                if record is None:
                    physical = (identity.get("resolved_id"), identity.get("connector_id"))
                    state = ("conflict" if physical[0] is not None and any(
                        (item["station_id"], item["connector_id"]) == physical
                        for item in self._records.values()) else "missing")
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
            return {
                "schema_version": SCHEMA_VERSION,
                "record_state": state,
                "recorded_owner": (record["owner"] if record is not None and state == "valid"
                                   else "legacy" if state == "missing" else None),
                "station_id": record["station_id"] if record else None,
                "connector_id": record["connector_id"] if record else None,
                "schedule_mode_available": False,
                "armed": False,
                "ready": False,
                "blockers": ["command_isolation_not_implemented", "safety_unverified",
                             "transaction_authorization_unverified"],
            }


def ownership_store(hass: HomeAssistant) -> ExecutionOwnershipStore:
    """The same store is used across entries and their status requests."""
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = ExecutionOwnershipStore(hass)
    return hass.data[_DATA_KEY]
