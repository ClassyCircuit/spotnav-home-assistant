"""Unwired connector-scoped command admission; it does not activate an owner.

Only internal callers may classify an operation. Production writers do not use
this service yet. In particular, it does not provide a safety-stop exception.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from homeassistant.core import HomeAssistant

from .execution_ownership import ExecutionOwnershipStore, ownership_store

OperationKind = Literal["legacy_actuator", "owned_profile", "read_only"]
T = TypeVar("T")
_DATA_KEY = "spotnav_command_admission"


@dataclass(frozen=True)
class PhysicalConnector:
    """The resolved station ID, never an alias, and its actual connector number."""

    station_id: str
    connector_id: int


@dataclass(frozen=True)
class Generation:
    connector: PhysicalConnector
    revision: int


@dataclass(frozen=True)
class AdmissionResult(Generic[T]):
    allowed: bool
    reason: str
    value: T | None = None


def physical_connector(identity: Mapping[str, Any]) -> PhysicalConnector | None:
    """Accept only a uniquely resolved, supported physical identity, not its alias."""
    station, connector = identity.get("resolved_id"), identity.get("connector_id")
    if (identity.get("supported") is not True or not isinstance(station, str) or not station
            or type(connector) is not int or connector < 1):
        return None
    return PhysicalConnector(station, connector)


class CommandAdmission:
    """Serialize writes by physical connector and re-evaluate intent inside the lock."""

    def __init__(self, store: ExecutionOwnershipStore) -> None:
        self._store = store
        self._locks: dict[PhysicalConnector, asyncio.Lock] = {}
        self._generations: dict[PhysicalConnector, int] = {}

    def _lock_for(self, connector: PhysicalConnector) -> asyncio.Lock:
        # Do not discard idle locks: a waiting task may still hold a reference.
        return self._locks.setdefault(connector, asyncio.Lock())

    def generation(self, connector: PhysicalConnector) -> Generation:
        """Capture a process-local token before queuing work; not a durable transition."""
        return Generation(connector, self._generations.get(connector, 0))

    async def async_invalidate(self, connector: PhysicalConnector) -> Generation:
        """Invalidate previously captured work after preceding connector operations finish."""
        async with self._lock_for(connector):
            self._generations[connector] = self._generations.get(connector, 0) + 1
            return self.generation(connector)

    async def async_execute(
        self,
        entry_id: str,
        kind: OperationKind,
        resolve_identity: Callable[[], Mapping[str, Any]],
        operation: Callable[[], Awaitable[T]],
        *,
        expected_generation: Generation | None = None,
    ) -> AdmissionResult[T]:
        """Run an admitted operation; exceptions and cancellation propagate after unlocking.

        Read-only work bypasses write admission, not its own authorization or target
        validation. A resolved read shares the connector lock; an unresolved read may
        still run without one. Identity is checked again inside a resolved lock.
        """
        if kind == "read_only":
            try:
                read_connector = physical_connector(resolve_identity())
            except Exception:  # noqa: BLE001 - read access is not contingent on write identity
                read_connector = None
            if read_connector is None:
                return AdmissionResult(True, "allowed_read_only", await operation())
            async with self._lock_for(read_connector):
                try:
                    if physical_connector(resolve_identity()) != read_connector:
                        return AdmissionResult(False, "identity_changed")
                except Exception:  # noqa: BLE001 - a queued read must not use the wrong connector lock
                    return AdmissionResult(False, "identity_changed")
                return AdmissionResult(True, "allowed_read_only", await operation())
        if kind not in ("legacy_actuator", "owned_profile"):
            return AdmissionResult(False, "invalid_operation")
        try:
            connector = physical_connector(resolve_identity())
        except Exception:  # noqa: BLE001 - an unavailable resolver cannot admit a write
            connector = None
        if connector is None:
            return AdmissionResult(False, "identity_unresolved")

        async with self._lock_for(connector):
            if expected_generation is not None and expected_generation != self.generation(connector):
                return AdmissionResult(False, "stale_generation")
            try:
                identity = dict(resolve_identity())
                if physical_connector(identity) != connector:
                    return AdmissionResult(False, "identity_changed")
                status = await self._store.async_status(entry_id, identity)
                if physical_connector(resolve_identity()) != connector:
                    return AdmissionResult(False, "identity_changed")
            except Exception:  # noqa: BLE001 - unknown state is never write permission
                return AdmissionResult(False, "ownership_unavailable")

            if not isinstance(status, Mapping):
                return AdmissionResult(False, "ownership_unavailable")
            state = status.get("record_state")
            if state != "valid":
                return AdmissionResult(False, f"ownership_{state}" if state in (
                    "missing", "malformed", "unsupported_version", "save_failed", "conflict",
                    "identity_unresolved", "identity_mismatch",
                ) else "ownership_unavailable")
            if (type(status.get("connector_id")) is not int or
                    (status.get("station_id"), status.get("connector_id")) != (connector.station_id, connector.connector_id)):
                return AdmissionResult(False, "ownership_identity_mismatch")
            owner = status.get("recorded_owner")
            if owner not in ("legacy", "morek_schedule"):
                return AdmissionResult(False, "ownership_unavailable")
            if kind == "owned_profile":
                return AdmissionResult(False, "schedule_mode_unarmed")
            if owner != "legacy":
                return AdmissionResult(False, "legacy_not_owner")
            if status.get("armed") is not False:
                return AdmissionResult(False, "ownership_inconsistent")
            return AdmissionResult(True, "allowed_legacy", await operation())


def command_admission(hass: HomeAssistant) -> CommandAdmission:
    """Share the same connector locks across all future callers in this HA instance."""
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = CommandAdmission(ownership_store(hass))
    return hass.data[_DATA_KEY]
