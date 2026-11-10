"""Connector-scoped command admission; it does not activate an owner.

Only internal callers may classify an operation. The Auto boundary uses a
preparation check; final physical writers and safety stops are not guarded here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from homeassistant.core import HomeAssistant

from ..const import MOREK_CONNECTOR_ID, MOREK_STATION_ID
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


def classify_morek_identity(identity: Mapping[str, Any]) -> str:
    """Classify the existing Morek resolver's result, never an unresolved alias."""
    # A known, different connector number cannot be the owned connector on any station.
    if identity.get("reason") == "ambiguous_station":
        return "unresolved"
    connector = identity.get("connector_id")
    if type(connector) is int and connector > 0 and connector != MOREK_CONNECTOR_ID:
        return "non_target"
    if (identity.get("reason") == "ambiguous_station" or type(identity.get("match_count")) is not int
            or identity["match_count"] != 1):
        return "unresolved"
    if not isinstance(identity.get("resolved_id"), str) or not identity["resolved_id"]:
        return "unresolved"
    if type(identity.get("connector_id")) is not int or identity["connector_id"] < 1:
        return "unresolved"
    if (identity["resolved_id"], identity["connector_id"]) != (MOREK_STATION_ID, MOREK_CONNECTOR_ID):
        return "non_target"
    if identity.get("ocpp_version") == "1.6" and identity.get("supported") is True:
        return "supported_morek"
    return "target_unsupported"


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

    async def async_ensure_initialized(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]]
    ) -> str:
        """Initialize metadata under the same physical connector lock as admission."""
        try:
            identity = dict(resolve_identity())
            classification = classify_morek_identity(identity)
            connector = physical_connector(identity)
        except Exception:  # noqa: BLE001 - an unknown identity cannot create ownership
            return "identity_unresolved"
        if classification == "non_target":
            return "identity_non_target"
        if classification == "target_unsupported":
            return "identity_target_unsupported"
        if classification != "supported_morek" or connector is None:
            return "identity_unresolved"
        async with self._lock_for(connector):
            try:
                identity = dict(resolve_identity())
                if classify_morek_identity(identity) != "supported_morek" or physical_connector(identity) != connector:
                    return "identity_changed"
                return await self._store._async_ensure_locked_connector(entry_id, identity, resolve_identity)
            except Exception:  # noqa: BLE001 - failed persistence is an unknown outcome
                return "save_uncertain"

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


async def async_auto_legacy_allowed(
    admission: CommandAdmission, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]]
) -> bool:
    """Check the target's ownership without changing it; unrelated connectors retain legacy behavior.

    This is a boundary check, not transition serialization or final dispatch admission.
    Unknown OCPP identity fails closed rather than treating an alias as unrelated.
    """
    try:
        classification = classify_morek_identity(resolve_identity())
        if classification == "non_target":
            return True
        if classification != "supported_morek":
            return False

        async def checked() -> bool:
            return True

        result = await admission.async_execute(entry_id, "legacy_actuator", resolve_identity, checked)
        return result.allowed
    except Exception:  # noqa: BLE001 - unknown ownership cannot permit execution
        return False


def legacy_write_guard(
    hass: HomeAssistant, entry_id: str, resolve_target: Callable[[], Any], *, ocpp: bool
) -> Callable[[Callable[[], Awaitable[T]]], Awaitable[AdmissionResult[T]]]:
    """Create a final-write guard; the connector lock is taken last around the operation.

    Only positively unrelated connectors bypass target admission. A configured OCPP
    charger with no resolved target is not treated as a non-OCPP charger.
    """
    async def guard(operation: Callable[[], Awaitable[T]]) -> AdmissionResult[T]:
        if not ocpp:
            return AdmissionResult(True, "non_ocpp", await operation())
        from ..api.morek_schedule import _identity_status

        def identity() -> Mapping[str, Any]:
            return _identity_status(hass, resolve_target())

        try:
            classification = classify_morek_identity(identity())
        except Exception:  # noqa: BLE001 - failure to establish identity is not permission
            return AdmissionResult(False, "ownership_unavailable")
        if classification == "non_target":
            return AdmissionResult(True, "non_target", await operation())
        if classification != "supported_morek":
            return AdmissionResult(False, "identity_unresolved")
        return await command_admission(hass).async_execute(entry_id, "legacy_actuator", identity, operation)
    return guard
