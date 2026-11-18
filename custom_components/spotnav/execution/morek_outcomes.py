"""Connector-wide durable evidence; caller serializes through connector admission."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from homeassistant.helpers.storage import Store

from ..const import MOREK_CONNECTOR_ID, MOREK_STATION_ID
from .execution_ownership import _MISSING, _read_envelope

_DATA_KEY = "spotnav_morek_outcomes"
_STORAGE_KEY = "spotnav.morek_schedule.connector_outcomes"


class OutcomeUnavailable(Exception):
    """Storage cannot be trusted; no profile dispatch is permitted."""


def clean_start_origin(record: Any, entry_id: str, migration_id: str | None) -> bool:
    """Validate the persistent clean-start origin, not the state of later operations."""
    if not isinstance(record, dict) or record.get("entry_id") != entry_id or record.get("uncertain") is not False:
        return False
    proof = record.get("clean_start")
    if not isinstance(migration_id, str) or len(migration_id) != 32 or any(c not in "0123456789abcdef" for c in migration_id):
        return False
    if (not isinstance(proof, dict) or type(proof.get("version")) is not int
            or type(proof.get("connector_id")) is not int or proof != {"version": 1, "id": migration_id, "station_id": MOREK_STATION_ID,
                 "connector_id": MOREK_CONNECTOR_ID, "history": "missing"}):
        return False
    recovery = record.get("migration_recovery_proof")
    if (not isinstance(recovery, dict) or type(recovery.get("version")) is not int
            or type(recovery.get("connector_id")) is not int
            or recovery != {"version": 1, "migration_id": migration_id,
                            "station_id": MOREK_STATION_ID, "connector_id": MOREK_CONNECTOR_ID}):
        return False
    return True


def clean_start_proven(record: Any, entry_id: str, migration_id: str | None) -> bool:
    """Approved missing-history provenance, never evidence of a previous profile action."""
    if not clean_start_origin(record, entry_id, migration_id):
        return False
    if (record.get("attempt") is not None or record.get("removal") is not None
            or any(record.get(key) is not None for key in ("desired", "acknowledged", "verified"))):
        return False
    pause = record.get("schedule_pause")
    return (isinstance(pause, dict) and set(pause) == {"version", "type", "id", "station_id", "connector_id"}
            and type(pause.get("version")) is int and pause["version"] == 1
            and pause.get("type") in ("pause_until_resumed", "resume_requested")
            and isinstance(pause.get("id"), str) and bool(pause["id"])
            and pause.get("station_id") == MOREK_STATION_ID
            and type(pause.get("connector_id")) is int and pause["connector_id"] == MOREK_CONNECTOR_ID)


class MorekOutcomes:
    """One supported physical connector. Failed or cancelled writes poison it until a verified reread recovers."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, _STORAGE_KEY, atomic_writes=True)
        self.poisoned = False
        # What a poisoned write may still change. `_late_write` is the exact record an executor job may yet write
        # (only after a cancellation: the job outlives its awaiter); `_before_write` is the record known to be on
        # disk before that write. Both are only meaningful while `poisoned`.
        self._late_write: dict[str, Any] | None = None
        self._before_write: Any = _MISSING
        self.recovery: str | None = None
        # Ledger-internal, non-reentrant, leaf lock: it covers exactly one public read/write, which only awaits the
        # executor and HA's own Store write lock (neither ever calls back here). Public methods take it once and
        # call the `_locked` internals, so there is no recursion. It makes recovery, poison and late-write state a
        # single critical section: two readers cannot both recover, and a recovery cannot clear a poison that a
        # newer failed write set while it was awaiting. A caller cancelled while waiting holds nothing.
        self._lock = asyncio.Lock()

    async def _recover(self) -> None:
        """Clear the poison only when a verified reread proves no write of ours can still land.

        Never reinitializes or overwrites an invalid, unsupported or unreadable file (that could hide a dispatched
        write). After a *completed* failed save (the job returned an error) no job is in flight, so two equal valid
        rereads suffice. After a cancelled save the job may still run, so recovery needs proof that it already
        landed: the disk must equal the exact record that write carried and differ from what was there before
        (an equal record could be a not-yet-run job overwriting a later write)."""
        try:
            first = await self._read_disk()
            second = await self._read_disk()
        except OutcomeUnavailable:
            self.recovery = "storage_still_invalid"
            raise
        if first != second:
            self.recovery = "storage_changing"
            raise OutcomeUnavailable("outcome_storage_uncertain")
        if self._late_write is not None and (first != self._late_write or self._before_write is _MISSING
                                             or first == self._before_write):
            self.recovery = "late_write_unproven"
            raise OutcomeUnavailable("outcome_storage_uncertain")
        self.poisoned = False
        self._late_write = None
        self._before_write = _MISSING
        self.recovery = "recovered"

    async def read(self) -> dict[str, Any] | None:
        async with self._lock:
            if self.poisoned:
                await self._recover()
            return await self._read_disk()

    async def _read_disk(self) -> dict[str, Any] | None:
        try:
            envelope = await self.hass.async_add_executor_job(_read_envelope, self.store.path)
            if envelope is _MISSING:
                return None
            if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int or envelope["version"] != 1
                    or type(envelope.get("minor_version", 1)) is not int or envelope.get("minor_version", 1) != 1
                    or not isinstance(envelope.get("data"), dict)
                    or type(envelope["data"].get("schema")) is not int or envelope["data"]["schema"] != 1):
                raise OutcomeUnavailable("outcome_storage_invalid")
            data = envelope["data"]
            if (not isinstance(data.get("entry_id"), str) or not data["entry_id"]
                    or type(data.get("uncertain")) is not bool
                    or any(data.get(key) is not None and not isinstance(data[key], dict)
                           for key in ("desired", "attempt", "acknowledged", "verified", "removal"))
                    or ((data.get("attempt") or {}).get("state") == "uncertain" and not data["uncertain"])
                    or ((data.get("removal") or {}).get("state") == "uncertain" and not data["uncertain"])):
                raise OutcomeUnavailable("outcome_storage_invalid")
            return deepcopy(data)
        except (OSError, ValueError, TypeError) as error:
            raise OutcomeUnavailable("outcome_storage_invalid") from error

    async def write(self, data: dict[str, Any]) -> None:
        async with self._lock:
            await self._write_locked(data)

    async def _write_locked(self, data: dict[str, Any]) -> None:
        if self.poisoned:
            await self._recover()
        saving = started = False
        # A genuinely missing file reads as None (initialization is allowed). An invalid, unsupported or unreadable
        # file raises here, before anything is written: it is never overwritten (it could hide a dispatched write),
        # and this refusal is not a failed save, so it does not poison.
        before: Any = await self._read_disk()
        try:
            saving = started = True
            await self.store.async_save(deepcopy(data))
            saving = False
            saved = await self._read_disk()
            if saved != data:
                raise OutcomeUnavailable("outcome_storage_uncertain")
        except BaseException as error:
            # An executor write can still complete after cancellation. Do not race it: only an error returned by
            # the save itself means its job has finished; a cancellation or a failed/mismatching verification read
            # leaves a landing possible.
            self.poisoned = True
            self.recovery = None
            late = started and not (saving and isinstance(error, Exception))
            self._late_write = deepcopy(data) if late else None
            self._before_write = before if late else _MISSING
            raise


def outcomes_for(hass) -> MorekOutcomes:
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = MorekOutcomes(hass)
    return hass.data[_DATA_KEY]
