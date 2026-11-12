"""Connector-wide durable evidence; caller serializes through connector admission."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.helpers.storage import Store

from .execution_ownership import _MISSING, _read_envelope

_DATA_KEY = "spotnav_morek_outcomes"
_STORAGE_KEY = "spotnav.morek_schedule.connector_outcomes"


class OutcomeUnavailable(Exception):
    """Storage cannot be trusted; no profile dispatch is permitted."""


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
