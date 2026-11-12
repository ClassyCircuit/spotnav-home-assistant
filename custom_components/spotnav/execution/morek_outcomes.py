"""Connector-wide durable evidence; caller serializes through connector admission."""

from __future__ import annotations

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
    """One supported physical connector. Failed or cancelled writes poison this process."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, _STORAGE_KEY, atomic_writes=True)
        self.poisoned = False

    async def read(self) -> dict[str, Any] | None:
        if self.poisoned:
            raise OutcomeUnavailable("outcome_storage_uncertain")
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
        if self.poisoned:
            raise OutcomeUnavailable("outcome_storage_uncertain")
        try:
            await self.store.async_save(deepcopy(data))
            saved = await self.read()
            if saved != data:
                raise OutcomeUnavailable("outcome_storage_uncertain")
        except BaseException:
            # An executor write can still complete after cancellation. Do not race it.
            self.poisoned = True
            raise


def outcomes_for(hass) -> MorekOutcomes:
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = MorekOutcomes(hass)
    return hass.data[_DATA_KEY]
