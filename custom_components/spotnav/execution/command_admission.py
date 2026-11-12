"""Connector-scoped command admission and process-local migration authorization.

Only internal callers may classify an operation. Ordinary physical writes use
this admission; regulator protection and external writers remain separate.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from homeassistant.core import HomeAssistant

from ..const import MOREK_CONNECTOR_ID, MOREK_STATION_ID
from .execution_ownership import ExecutionOwnershipStore, ownership_store

OperationKind = Literal["legacy_actuator", "person_stop", "owned_profile", "read_only"]
T = TypeVar("T")
_DATA_KEY = "spotnav_command_admission"
_STOP_RESERVATION: ContextVar[Any] = ContextVar("spotnav_person_stop", default=None)


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
        self._quiescing: set[PhysicalConnector] = set()
        self._entry_draining: dict[PhysicalConnector, str] = {}
        self._migration_controllers: dict[PhysicalConnector, Any] = {}
        # Reconnect barriers are process-local; only verified durable ownership
        # and current evidence permit release. The entry key covers identities
        # unavailable at the callback.
        self._lifecycle_barriers: dict[str, PhysicalConnector | None] = {}
        self._lifecycle_revisions: dict[str, int] = {}
        self._person_stops: dict[PhysicalConnector, int] = {}
        self._uncertain_operations: set[PhysicalConnector] = set()
        self._recovery_status: dict[str, dict[str, Any]] = {}
        self._completion_tickets: dict[str, tuple[PhysicalConnector, str, int, Generation]] = {}
        self._stop_prior_tickets: dict[asyncio.Task, tuple[PhysicalConnector, str, int, Generation]] = {}

    def reserve_lifecycle_barrier(self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]]) -> int:
        """Synchronously invalidate ordinary target writes before scheduling recovery."""
        revision = self._lifecycle_revisions.get(entry_id, 0) + 1
        self._lifecycle_revisions[entry_id] = revision
        self._completion_tickets.pop(entry_id, None)
        try:
            identity = dict(resolve_identity())
            classification = classify_morek_identity(identity)
            connector = physical_connector(identity) if classification == "supported_morek" else None
        except Exception:  # noqa: BLE001 - unknown identity is not permission
            connector = None
        previous = self._lifecycle_barriers.get(entry_id)
        self._lifecycle_barriers[entry_id] = connector or previous
        connector = connector or previous
        if connector is not None:
            self._generations[connector] = self._generations.get(connector, 0) + 1
            if connector in self._entry_draining:
                self._entry_draining[connector] = "interrupted"
        return revision

    async def async_release_lifecycle_barrier(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], revision: int,
        lifecycle_current: Callable[[], bool],
    ) -> bool:
        """Release only after a current, durable owner and settled ledger are verified.

        This is not dispatch authority. Connector lock precedes the ownership
        store lock; synchronous reservations can invalidate the final check.
        """
        from .execution_ownership import _decode, _read_envelope
        from .morek_outcomes import outcomes_for

        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return False
            generation = self.generation(connector)

            def current() -> bool:
                fresh = dict(resolve_identity())
                return (entry_id in self._lifecycle_barriers and self._lifecycle_revisions.get(entry_id) == revision
                        and lifecycle_current() and generation == self.generation(connector)
                        and not self._person_stops.get(connector) and connector not in self._entry_draining
                        and connector not in self._quiescing and connector not in self._uncertain_operations
                        and classify_morek_identity(fresh) == "supported_morek"
                        and physical_connector(fresh) == connector)

            async with self._lock_for(connector):
                if not current():
                    return False
                status = await self._store.async_status(entry_id, identity)
                if (status.get("record_state") != "valid" or status.get("recorded_owner") != "morek_schedule"
                        or status.get("transition_state") is not None or status.get("armed") is not False
                        or status.get("handover_evidence") != "completed"
                        or not self.ticket_current(entry_id, connector, status.get("handover_id"))
                        or (status.get("station_id"), status.get("connector_id")) !=
                           (connector.station_id, connector.connector_id)):
                    return False
                async with self._store._lock:
                    raw = await self._store._hass.async_add_executor_job(_read_envelope, self._store._store.path)
                    state, disk = _decode(raw)
                    if (state != "valid" or disk != self._store._records or self._store._state != "valid"
                            or self._store._cancelled_write or self._store._transition_save_uncertain):
                        return False
                outcome = await outcomes_for(self._store._hass).read()
                if (outcome is None or outcome.get("entry_id") != entry_id or outcome.get("uncertain") is not False
                        or not isinstance(outcome.get("attempt"), dict)
                        or outcome["attempt"].get("state") not in ("accepted", "rejected", "aborted_before_dispatch")
                        or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                            ("accepted", "rejected", "notsupported")) or not current()):
                    return False
                del self._lifecycle_barriers[entry_id]
                return True
        except Exception:  # noqa: BLE001 - no evidence, no release
            return False

    def lifecycle_blocked(self, entry_id: str, connector: PhysicalConnector) -> bool:
        """Do not apply a target barrier to a positively unrelated connector."""
        if (connector.station_id, connector.connector_id) != (MOREK_STATION_ID, MOREK_CONNECTOR_ID):
            return False
        return entry_id in self._lifecycle_barriers or connector in self._lifecycle_barriers.values()

    def ticket_current(self, entry_id: str, connector: PhysicalConnector, migration_id: str | None) -> bool:
        """Check process evidence synchronously at every wire boundary."""
        ticket = self._completion_tickets.get(entry_id)
        record = self._store._records.get(entry_id, {})
        return bool(ticket and self._store._state == "valid" and not self._store._transition_save_uncertain
                    and not self._store._cancelled_write and record.get("owner") == "morek_schedule"
                    and record.get("handover") == {"version": 1, "state": "completed", "id": migration_id}
                    and (record.get("station_id"), record.get("connector_id")) == (connector.station_id, connector.connector_id)
                    and ticket == (connector, migration_id, self._lifecycle_revisions.get(entry_id, 0),
                                          self.generation(connector))
                    and not self._person_stops.get(connector)
                    and connector not in self._entry_draining and connector not in self._quiescing
                    and connector not in self._uncertain_operations)

    def owned_ticket_current(self, entry_id: str, connector: PhysicalConnector) -> bool:
        ticket = self._completion_tickets.get(entry_id)
        return bool(ticket and self.ticket_current(entry_id, connector, ticket[1])
                    and not self.lifecycle_blocked(entry_id, connector))

    async def async_owned_boundary_current(self, entry_id: str, connector: PhysicalConnector) -> bool:
        """Re-read ownership at the last awaited worker boundary under connector admission."""
        from .execution_ownership import _decode, _read_envelope
        if not self.owned_ticket_current(entry_id, connector):
            return False
        try:
            async with self._store._lock:
                raw = await self._store._hass.async_add_executor_job(_read_envelope, self._store._store.path)
                state, records = _decode(raw)
                return (state == "valid" and records == self._store._records
                        and self.owned_ticket_current(entry_id, connector))
        except Exception:  # noqa: BLE001 - failed read is not permission
            return False

    async def async_reconfirm_completed(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]],
    ) -> str:
        """Explicitly reconfirm a completed owner; never operate the charger."""
        from .execution_ownership import _decode, _read_envelope
        from .morek_outcomes import outcomes_for

        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
            revision = self._lifecycle_revisions.get(entry_id, 0)
            generation = self.generation(connector)

            def current() -> bool:
                fresh = dict(resolve_identity())
                return (self._lifecycle_revisions.get(entry_id, 0) == revision
                        and self.generation(connector) == generation and not self._person_stops.get(connector)
                        and connector not in self._entry_draining and connector not in self._quiescing
                        and connector not in self._uncertain_operations
                        and classify_morek_identity(fresh) == "supported_morek"
                        and physical_connector(fresh) == connector)

            async with self._lock_for(connector):
                if not current():
                    return "reconfirmation_interrupted"
                status = await self._store.async_status(entry_id, identity)
                if (status.get("record_state") != "valid" or status.get("recorded_owner") != "morek_schedule"
                        or status.get("handover_evidence") != "completed" or not status.get("handover_id")
                        or status.get("transition_state") is not None):
                    return "completion_unavailable"
                async with self._store._lock:
                    raw = await self._store._hass.async_add_executor_job(_read_envelope, self._store._store.path)
                    state, disk = _decode(raw)
                    if (state != "valid" or disk != self._store._records or self._store._state != "valid"
                            or self._store._cancelled_write or self._store._transition_save_uncertain):
                        return "ownership_unavailable"
                outcome = await outcomes_for(self._store._hass).read()
                if (outcome is None or outcome.get("entry_id") != entry_id or outcome.get("uncertain") is not False
                        or not isinstance(outcome.get("attempt"), dict)
                        or outcome["attempt"].get("state") not in ("accepted", "rejected", "aborted_before_dispatch")
                        or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                            ("accepted", "rejected", "notsupported"))):
                    return "profile_outcome_unavailable"
                if not current():
                    return "reconfirmation_interrupted"
                ticket = (connector, status["handover_id"], revision, generation)
                self._completion_tickets[entry_id] = ticket
            if entry_id in self._lifecycle_barriers:
                released = await self.async_release_lifecycle_barrier(
                    entry_id, resolve_identity, revision, lambda: self._lifecycle_revisions.get(entry_id, 0) == revision)
                if not released:
                    if self._completion_tickets.get(entry_id) == ticket:
                        self._completion_tickets.pop(entry_id, None)
                    return "reconfirmation_interrupted"
            return "reconfirmed"
        except Exception:  # noqa: BLE001 - missing or malformed evidence is not authority
            return "reconfirmation_unavailable"

    @contextmanager
    def person_stop_reservation(self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]]):
        """Reserve before outer locks; interrupt an unarmed entry without reopening writes."""
        current = _STOP_RESERVATION.get()
        if current is not None and current[0] is self and current[1] == entry_id and current[2] is not None and current[3] is asyncio.current_task():
            yield
            return
        try:
            identity = resolve_identity()
            offline_intent = (identity.get("reason") == "offline_owned_intent"
                              and identity.get("offline_binding") in ("direct", "alias")
                              and identity.get("resolved_id") == MOREK_STATION_ID
                              and identity.get("connector_id") == MOREK_CONNECTOR_ID
                              and identity.get("match_count") == 0)
            connector = physical_connector(identity) if classify_morek_identity(identity) == "supported_morek" or offline_intent else None
        except Exception:  # noqa: BLE001 - the ordinary identity checks still apply
            connector = None
        if connector is not None:
            prior = self._completion_tickets.pop(entry_id, None)
            if prior is not None and asyncio.current_task() is not None:
                self._stop_prior_tickets[asyncio.current_task()] = prior
            self._person_stops[connector] = self._person_stops.get(connector, 0) + 1
            self._generations[connector] = self._generations.get(connector, 0) + 1
            if connector in self._entry_draining:
                self._entry_draining[connector] = "interrupted"
        token = _STOP_RESERVATION.set((self, entry_id, connector, asyncio.current_task()))
        try:
            yield
        finally:
            self._stop_prior_tickets.pop(asyncio.current_task(), None)
            _STOP_RESERVATION.reset(token)
            if connector is not None:
                self._person_stops[connector] -= 1
                if not self._person_stops[connector]:
                    del self._person_stops[connector]

    def renew_ticket_for_durable_pause(self, entry_id: str, connector: PhysicalConnector, generation: Generation) -> None:
        """A successfully recorded Stop may carry forward only its own prior authority."""
        prior = self._stop_prior_tickets.get(asyncio.current_task())
        if (prior is not None and prior[0] == connector and prior[3].revision + 1 == generation.revision
                and prior[2] == self._lifecycle_revisions.get(entry_id, 0)
                and self.generation(connector) == generation and self._person_stops.get(connector) == 1
                and not self.lifecycle_blocked(entry_id, connector) and connector not in self._entry_draining):
            self._completion_tickets[entry_id] = (connector, prior[1], prior[2], generation)

    async def async_begin_unarmed_entry(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], person_stop_active: Callable[[], bool]
    ) -> str:
        """Persist entry evidence and drain; never persist an owner or send a command.

        Call without outer locks. The latch stays closed on cancellation or interruption.
        A successful drain is not ownership and has no production activation path.
        """
        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
            if connector in self._entry_draining or connector in self._quiescing:
                return "entry_unavailable"
            if self._person_stops.get(connector) or person_stop_active():
                return "person_stop_active"
        except Exception:  # noqa: BLE001 - unavailable facts cannot establish a transition
            return "entry_unavailable"
        self._entry_draining[connector] = "draining"
        self._completion_tickets.pop(entry_id, None)
        self._generations[connector] = self._generations.get(connector, 0) + 1
        try:
            saved = await self._store.async_set_entry_transition(entry_id, identity, resolve_identity, "requested")
        except Exception:  # noqa: BLE001 - a failed write may have landed
            return "ownership_unavailable"
        if saved != "saved":
            return "ownership_unavailable"
        async with self._lock_for(connector):
            if self._entry_draining[connector] != "draining" or self._person_stops.get(connector):
                await self._store.async_set_entry_transition(entry_id, identity, resolve_identity, "interrupted")
                return "interrupted"
            try:
                fresh = dict(resolve_identity())
                status = await self._store.async_status(entry_id, fresh)
                if (classify_morek_identity(fresh) != "supported_morek" or physical_connector(fresh) != connector
                        or physical_connector(resolve_identity()) != connector or person_stop_active()
                        or self._person_stops.get(connector) or self._entry_draining[connector] != "draining"):
                    await self._store.async_set_entry_transition(entry_id, identity, resolve_identity, "interrupted")
                    return "interrupted"
                if (status.get("record_state") != "valid" or status.get("recorded_owner") != "legacy"
                        or status.get("armed") is not False or
                        (status.get("station_id"), status.get("connector_id")) != (connector.station_id, connector.connector_id)):
                    return "ownership_unavailable"
            except Exception:  # noqa: BLE001 - unknown state leaves admission closed
                return "ownership_unavailable"
            try:
                saved = await self._store.async_set_entry_transition(entry_id, identity, resolve_identity, "drained_unarmed")
                if saved != "saved":
                    return "ownership_unavailable"
                if self._entry_draining[connector] != "draining" or self._person_stops.get(connector) or person_stop_active():
                    await self._store.async_set_entry_transition(entry_id, identity, resolve_identity, "interrupted")
                    return "interrupted"
            except Exception:  # noqa: BLE001 - leave the durable request or uncertain result blocked
                return "ownership_unavailable"
            self._entry_draining[connector] = "drained_unarmed"
            return "drained_unarmed"

    async def async_abort_unarmed_entry(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], *, settings_store: Any = None
    ) -> str:
        """Abort only this unarmed entry while a verified indefinite Auto pause remains.

        This does not establish profile inventory or resolve older unknown commands.
        Settings lock precedes connector, then ownership store; no producer lock is held.
        """
        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
            if settings_store is None:
                from ..runtime import domain_data
                settings_store = domain_data(self._store._hass).auto_store
            from ..planning.auto_settings import AutoSettingsStore
            if not isinstance(settings_store, AutoSettingsStore):
                return "pause_unavailable"
        except Exception:  # noqa: BLE001 - unknown identity cannot authorize recovery
            return "pause_unavailable"
        generation = self.generation(connector)
        async with settings_store._lock, self._lock_for(connector):
            if connector in self._quiescing or connector in self._entry_draining:
                return "entry_active_or_uncertain"
            if self._person_stops.get(connector):
                return "person_stop_active"
            if generation != self.generation(connector):
                return "stale_generation"
            if connector in self._uncertain_operations:
                return "legacy_operation_uncertain"
            self._entry_draining[connector] = "recovering"
            self._generations[connector] = generation.revision + 1
            generation = self.generation(connector)
            try:
                fresh = dict(resolve_identity())
                if classify_morek_identity(fresh) != "supported_morek" or physical_connector(fresh) != connector:
                    return "identity_changed"
                status = await self._store.async_status(entry_id, fresh)
                if (status.get("record_state") != "valid" or status.get("recorded_owner") != "legacy"
                        or (status.get("station_id"), status.get("connector_id")) !=
                        (connector.station_id, connector.connector_id)):
                    return "ownership_unavailable"
                if status.get("transition_state") is None:
                    return "no_transition"
                if status.get("transition_state") not in ("requested", "interrupted", "drained_unarmed"):
                    return "ownership_unavailable"
                from ..planning.auto_settings import AutoSettings, PAUSE_UNTIL_RESUMED, SUPPORTED_SCHEMAS
                from .execution_ownership import _MISSING, _read_envelope
                from .morek_outcomes import outcomes_for

                hass = self._store._hass
                # HA Store can swallow write errors. Require the exact persisted
                # settings, not merely its in-memory pause or an unsaved Stop.
                if not settings_store.loaded or settings_store.unsaved:
                    return "pause_unavailable"
                raw = await hass.async_add_executor_job(_read_envelope, settings_store._store.path)
                if (not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1
                        or type(raw.get("minor_version", 1)) is not int or raw.get("minor_version", 1) != 1
                        or not isinstance(raw.get("data"), dict) or type(raw["data"].get("schema")) is not int
                        or raw["data"].get("schema") not in SUPPORTED_SCHEMAS
                        or not isinstance(raw["data"].get("chargers"), dict)):
                    return "pause_unavailable"
                entry = raw["data"]["chargers"].get(entry_id)
                if not isinstance(entry, dict):
                    return "pause_unavailable"
                persisted = AutoSettings.from_stored(entry.get("settings"))
                if (persisted != settings_store.settings(entry_id) or persisted.pause.choice != PAUSE_UNTIL_RESUMED
                        or persisted.pause.expires_at is not None):
                    return "pause_not_indefinite"
                outcome = await outcomes_for(hass).read()
                if outcome is not None and outcome.get("entry_id") != entry_id:
                    return "profile_outcome_identity_mismatch"
                if outcome is not None and outcome.get("uncertain") is not False:
                    return "profile_outcome_uncertain"
                if outcome is not None:
                    attempt, removal = outcome.get("attempt"), outcome.get("removal")
                    if ((attempt is not None and (not isinstance(attempt, dict) or attempt.get("state") not in
                                                  ("accepted", "rejected", "aborted_before_dispatch"))) or
                            (removal is not None and (not isinstance(removal, dict) or removal.get("state") not in
                                                      ("accepted", "rejected", "notsupported")))):
                        return "profile_outcome_uncertain"
                # Old manual records predate the connector ledger. Never mutate or
                # infer profile absence from a missing record or composite readback.
                from homeassistant.helpers.storage import Store
                legacy_store = Store(hass, 1, f"spotnav.morek_schedule.{entry_id}")
                old = await hass.async_add_executor_job(_read_envelope, legacy_store.path)
                if old is not _MISSING:
                    if (not isinstance(old, dict) or type(old.get("version")) is not int or old["version"] != 1
                            or type(old.get("minor_version", 1)) is not int or old.get("minor_version", 1) != 1
                            or not isinstance(old.get("data"), dict)):
                        return "legacy_profile_history_invalid"
                    old_data = old["data"]
                    cleanup = old_data.get("cleanup")
                    profile = old_data.get("profile")
                    if ((cleanup is not None and not isinstance(cleanup, dict)) or
                            (profile is not None and not isinstance(profile, dict))):
                        return "legacy_profile_history_invalid"
                    cleanup = cleanup or {}
                    if ((old_data.get("profile") and str(old_data.get("ack", "unknown")).lower() not in
                         ("accepted", "rejected", "notsupported")) or
                        (cleanup and str(cleanup.get("status", "unknown")).lower() not in
                         ("accepted", "rejected", "notsupported"))):
                        return "profile_outcome_uncertain"

                def can_commit() -> bool:
                    current = dict(resolve_identity())
                    return (self._entry_draining.get(connector) == "recovering" and not self._person_stops.get(connector)
                            and generation == self.generation(connector)
                            and classify_morek_identity(current) == "supported_morek"
                            and physical_connector(current) == connector)

                if not can_commit():
                    return "person_stop_or_generation_changed"
                result = await self._store.async_abort_entry_transition(
                    entry_id, identity, status["transition_state"], can_commit)
                if result == "aborted" and not can_commit():
                    return "aborted_stop_pending"
                return result
            except Exception:  # noqa: BLE001 - malformed/unavailable evidence is not permission
                return "recovery_evidence_unavailable"
            finally:
                if self._entry_draining.get(connector) == "recovering":
                    del self._entry_draining[connector]

    async def async_recovery_status(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Read current evidence under connector admission; never change charger or storage.

        A valid record is not proof that a missing document was never recreated.
        This unarmed release has no durable first-use provenance.
        """
        from .morek_outcomes import OutcomeUnavailable, outcomes_for

        result: dict[str, Any] = {"state": "identity_unresolved", "activation_provenance": "unverified",
                                  "activation_allowed": False}
        try:
            identity = dict(resolve_identity())
            classification = classify_morek_identity(identity)
            connector = physical_connector(identity)
            if classification == "non_target":
                result["state"] = "non_target"
            elif classification == "target_unsupported":
                result["state"] = "identity_target_unsupported"
            elif classification == "supported_morek" and connector is not None:
                generation = self.generation(connector)
                async with self._lock_for(connector):
                    fresh = dict(resolve_identity())
                    if classify_morek_identity(fresh) != "supported_morek" or physical_connector(fresh) != connector:
                        result["state"] = "identity_changed"
                    elif generation != self.generation(connector):
                        result["state"] = "stale_generation"
                    elif self._person_stops.get(connector):
                        result["state"] = "person_stop_active"
                    elif connector in self._uncertain_operations:
                        result["state"] = "legacy_operation_uncertain"
                    elif connector in self._entry_draining or connector in self._quiescing:
                        result["state"] = "entry_active_or_uncertain"
                    else:
                        status = await self._store.async_status(entry_id, fresh)
                        state = status.get("record_state")
                        if state != "valid":
                            result["state"] = f"ownership_{state}" if state in (
                                "missing", "malformed", "unsupported_version", "save_failed", "conflict",
                                "identity_unresolved", "identity_mismatch") else "ownership_unavailable"
                        else:
                            outcome = await outcomes_for(self._store._hass).read()
                            if outcome is not None and outcome.get("entry_id") != entry_id:
                                result["state"] = "profile_outcome_identity_mismatch"
                            elif outcome is not None and (outcome.get("uncertain") is not False
                                    or (outcome.get("attempt") is not None and outcome["attempt"].get("state") not in
                                        ("accepted", "rejected", "aborted_before_dispatch"))
                                    or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                                        ("accepted", "rejected", "notsupported"))):
                                result["state"] = "profile_outcome_uncertain"
                            elif status.get("transition_state") == "exit_held_unarmed":
                                result["state"] = "legacy_exit_held_unarmed"
                                result["retained_profile"] = "unresolved"
                            elif status.get("transition_state") is not None:
                                result["state"] = "entry_" + status["transition_state"]
                            elif status.get("recorded_owner") == "legacy":
                                result["state"] = "legacy_unarmed"
                            elif status.get("recorded_owner") == "morek_schedule":
                                result["state"] = "morek_owned_unarmed"
                                result["handover_completion"] = ("owner_written_unconfirmed"
                                    if status.get("handover_evidence") == "owner_written_unconfirmed"
                                    else "not_proven_by_owner_record")
                            else:
                                result["state"] = "ownership_unavailable"
                            result["profile_history"] = "missing_not_inventory" if outcome is None else "recorded"
                        current = dict(resolve_identity())
                        if classify_morek_identity(current) != "supported_morek" or physical_connector(current) != connector:
                            result["state"] = "identity_changed"
                        elif generation != self.generation(connector) or self._person_stops.get(connector):
                            result["state"] = "person_stop_or_generation_changed"
        except OutcomeUnavailable as error:
            result["state"] = str(error) if str(error) in ("outcome_storage_uncertain", "outcome_storage_invalid") else "outcome_storage_invalid"
        except Exception:  # noqa: BLE001 - unavailable evidence never becomes permission
            result["state"] = "recovery_evidence_unavailable"
        self._recovery_status[entry_id] = result
        return dict(result)

    async def async_recover_unarmed(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], *, settings_store: Any = None,
    ) -> str:
        """Explicitly recover only eligible legacy entry markers via the guarded abort."""
        evidence = await self.async_recovery_status(entry_id, resolve_identity)
        if evidence["state"] not in ("entry_requested", "entry_interrupted", "entry_drained_unarmed"):
            return evidence["state"]
        return await self.async_abort_unarmed_entry(entry_id, resolve_identity, settings_store=settings_store)

    async def async_exit_unarmed_held(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]],
    ) -> str:
        """Hand bookkeeping to legacy but retain a durable, non-resumable interlock.

        This internal operation does not resolve or modify any retained profile.
        It waits for connector-admitted operations, never outer producer locks.
        """
        from homeassistant.helpers.storage import Store
        from .execution_ownership import _MISSING, _read_envelope
        from .morek_outcomes import OutcomeUnavailable, outcomes_for

        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
        except Exception:  # noqa: BLE001
            return "identity_unresolved"
        generation = self.generation(connector)
        async with self._lock_for(connector):
            if generation != self.generation(connector):
                return "stale_generation"
            if self._person_stops.get(connector):
                return "person_stop_active"
            if connector in self._entry_draining or connector in self._quiescing:
                return "entry_active_or_uncertain"
            if connector in self._uncertain_operations:
                return "legacy_operation_uncertain"
            self._entry_draining[connector] = "exiting"
            self._generations[connector] = generation.revision + 1
            generation = self.generation(connector)
            try:
                def can_commit() -> bool:
                    current = dict(resolve_identity())
                    return (self._entry_draining.get(connector) == "exiting" and not self._person_stops.get(connector)
                            and self.generation(connector) == generation
                            and classify_morek_identity(current) == "supported_morek"
                            and physical_connector(current) == connector)

                if not can_commit():
                    return "exit_interrupted"
                status = await self._store.async_status(entry_id, dict(resolve_identity()))
                if (status.get("record_state") != "valid" or status.get("recorded_owner") != "morek_schedule"
                        or status.get("armed") is not False or status.get("transition_state") is not None):
                    return "ownership_unavailable"
                outcome = await outcomes_for(self._store._hass).read()
                if outcome is not None and (outcome.get("entry_id") != entry_id or outcome.get("uncertain") is not False
                        or (outcome.get("attempt") is not None and outcome["attempt"].get("state") not in
                            ("accepted", "rejected", "aborted_before_dispatch"))
                        or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                            ("accepted", "rejected", "notsupported"))):
                    return "profile_outcome_uncertain"
                old_store = Store(self._store._hass, 1, f"spotnav.morek_schedule.{entry_id}")
                old = await self._store._hass.async_add_executor_job(_read_envelope, old_store.path)
                if old is not _MISSING:
                    if (not isinstance(old, dict) or type(old.get("version")) is not int or old["version"] != 1
                            or type(old.get("minor_version", 1)) is not int or old.get("minor_version", 1) != 1
                            or not isinstance(old.get("data"), dict)):
                        return "legacy_profile_history_invalid"
                    data = old["data"]
                    profile, cleanup = data.get("profile"), data.get("cleanup")
                    if ((profile is not None and not isinstance(profile, dict))
                            or (cleanup is not None and not isinstance(cleanup, dict))):
                        return "legacy_profile_history_invalid"
                    if ((profile and str(data.get("ack", "unknown")).lower() not in ("accepted", "rejected", "notsupported"))
                            or (cleanup and str(cleanup.get("status", "unknown")).lower() not in
                                ("accepted", "rejected", "notsupported"))):
                        return "profile_outcome_uncertain"
                if not can_commit():
                    return "exit_interrupted"
                return await self._store.async_exit_unarmed_held(entry_id, identity, can_commit)
            except OutcomeUnavailable as error:
                return str(error) if str(error) in ("outcome_storage_uncertain", "outcome_storage_invalid") else "outcome_storage_invalid"
            except Exception:  # noqa: BLE001 - unavailable evidence is not permission
                return "exit_evidence_unavailable"
            finally:
                if self._entry_draining.get(connector) == "exiting":
                    del self._entry_draining[connector]

    async def async_handover_unarmed(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], executor: Any, *,
        require_outcome: bool = False,
    ) -> str:
        """Complete an in-process drain without arming or invoking a charger.

        Producer locks precede connector admission. The synchronous return from
        the verified save and removal of the entry latch is the completion boundary.
        """
        from .auto_execution import AutoExecutor
        from .controller import ChargingController
        from .morek_outcomes import outcomes_for
        from .execution_ownership import _MISSING, _read_envelope
        from ..planning.auto_settings import AutoSettings, SUPPORTED_SCHEMAS
        from homeassistant.helpers.storage import Store

        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
            if not isinstance(executor, AutoExecutor) or not isinstance(executor.controller, ChargingController):
                return "producer_unavailable"
            controller = executor.controller
            if controller.entry_id != entry_id:
                return "producer_unavailable"
        except Exception:  # noqa: BLE001
            return "producer_unavailable"

        def identity_valid() -> bool:
            current = dict(resolve_identity())
            return classify_morek_identity(current) == "supported_morek" and physical_connector(current) == connector

        lifecycle_revision = self._lifecycle_revisions.get(entry_id, 0)
        generation = self.generation(connector)

        def stop_requested() -> bool:
            return (bool(self._person_stops.get(connector)) or self._entry_draining.get(connector) == "interrupted"
                    or self._lifecycle_revisions.get(entry_id, 0) != lifecycle_revision)

        def can_commit() -> bool:
            return (self._entry_draining.get(connector) == "drained_unarmed" and not stop_requested()
                    and self.generation(connector) == generation and identity_valid())

        async with executor._lock, executor._store._lock, controller._lock, controller._assign_lock, self._lock_for(connector):
            try:
                if not can_commit():
                    return "handover_interrupted"
                if executor._shutdown or controller._shut_down:
                    return "producer_unavailable"
                if connector in self._uncertain_operations:
                    return "legacy_operation_uncertain"
                if (not executor._store.loaded or executor._store.unsaved
                        or (executor._store.settings(entry_id).pause.manual
                            and executor._store.settings(entry_id).pause.action == "stop")):
                    return "person_stop_or_settings_unavailable"
                settings_raw = await self._store._hass.async_add_executor_job(_read_envelope, executor._store._store.path)
                if (not isinstance(settings_raw, dict) or type(settings_raw.get("version")) is not int
                        or settings_raw["version"] != 1 or settings_raw.get("minor_version", 1) != 1
                        or not isinstance(settings_raw.get("data"), dict)
                        or settings_raw["data"].get("schema") not in SUPPORTED_SCHEMAS
                        or not isinstance(settings_raw["data"].get("chargers"), dict)):
                    return "settings_unavailable"
                settings_entry = settings_raw["data"]["chargers"].get(entry_id)
                if (not isinstance(settings_entry, dict) or AutoSettings.from_stored(settings_entry.get("settings"))
                        != executor._store.settings(entry_id)):
                    return "settings_unavailable"
                attempt = controller._last_start_attempt
                if (executor._start_pending or controller._start_in_flight
                        or (attempt is not None and attempt.start_dispatch == "unknown")):
                    return "legacy_operation_uncertain"
                outcome = await outcomes_for(self._store._hass).read()
                if require_outcome and (outcome is None or not isinstance(outcome.get("attempt"), dict)):
                    return "profile_history_unavailable"
                if outcome is not None and (outcome.get("entry_id") != entry_id or outcome.get("uncertain") is not False
                        or (outcome.get("attempt") is not None and outcome["attempt"].get("state") not in
                            ("accepted", "rejected", "aborted_before_dispatch"))
                        or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                            ("accepted", "rejected", "notsupported"))):
                    return "profile_outcome_uncertain"
                old = Store(self._store._hass, 1, f"spotnav.morek_schedule.{entry_id}")
                raw = await self._store._hass.async_add_executor_job(_read_envelope, old.path)
                if raw is not _MISSING:
                    if (not isinstance(raw, dict) or raw.get("version") != 1 or raw.get("minor_version", 1) != 1
                            or not isinstance(raw.get("data"), dict)):
                        return "legacy_profile_history_invalid"
                    data = raw["data"]
                    cleanup, profile = data.get("cleanup"), data.get("profile")
                    if ((cleanup is not None and not isinstance(cleanup, dict))
                            or (profile is not None and not isinstance(profile, dict))):
                        return "legacy_profile_history_invalid"
                    if ((profile and str(data.get("ack", "unknown")).lower() not in ("accepted", "rejected", "notsupported"))
                            or (cleanup and str(cleanup.get("status", "unknown")).lower() not in
                                ("accepted", "rejected", "notsupported"))):
                        return "profile_outcome_uncertain"
                if not can_commit():
                    return "handover_interrupted"
                result = await self._store.async_handover_unarmed(
                    entry_id, identity, can_commit, stop_requested, identity_valid)
                if result == "handed_over_unarmed" and require_outcome:
                    # The ledger can change while the owner save is awaiting.
                    outcome = await outcomes_for(self._store._hass).read()
                    if (not can_commit() or outcome is None or outcome.get("entry_id") != entry_id
                            or outcome.get("uncertain") is not False or not isinstance(outcome.get("attempt"), dict)
                            or outcome["attempt"].get("state") not in ("accepted", "rejected", "aborted_before_dispatch")
                            or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                                ("accepted", "rejected", "notsupported"))):
                        return "handover_interrupted"
                    result = await self._store.async_complete_handover(entry_id, identity, can_commit)
                    if result != "completed" or not can_commit():
                        return result if result != "completed" else "completion_interrupted"
                    migration_id = self._store._records[entry_id]["handover"]["id"]
                    # No await between final checks and the ticket/latch update.
                    del self._entry_draining[connector]
                    self._completion_tickets[entry_id] = (connector, migration_id, lifecycle_revision, generation)
                    return "handed_over_unarmed"
                if result == "handed_over_unarmed":
                    # No await between the last Stop check and this boundary.
                    del self._entry_draining[connector]
                return result
            except Exception:  # noqa: BLE001 - unavailable evidence cannot authorize handover
                return "handover_evidence_unavailable"

    def _lock_for(self, connector: PhysicalConnector) -> asyncio.Lock:
        # Do not discard idle locks: a waiting task may still hold a reference.
        return self._locks.setdefault(connector, asyncio.Lock())

    def generation(self, connector: PhysicalConnector) -> Generation:
        """Capture a process-local token before queuing work; not a durable transition."""
        return Generation(connector, self._generations.get(connector, 0))

    async def async_schedule_request(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], *, requested: bool,
    ) -> str:
        """Persist an unarmed request or disable future work; never touch the charger.

        Invalidate before waiting for admission, so a queued or persistence-bound
        worker cannot overtake disable. A dispatched write cannot be recalled.
        """
        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if classify_morek_identity(identity) != "supported_morek" or connector is None:
                return "identity_unresolved"
        except Exception:  # noqa: BLE001
            return "identity_unresolved"
        if self._person_stops.get(connector):
            return "person_stop_active"
        self._generations[connector] = self._generations.get(connector, 0) + 1
        generation = self.generation(connector)

        def current() -> bool:
            fresh = dict(resolve_identity())
            return (not self._person_stops.get(connector) and generation == self.generation(connector)
                    and connector not in self._entry_draining and connector not in self._quiescing
                    and classify_morek_identity(fresh) == "supported_morek" and physical_connector(fresh) == connector)

        async with self._lock_for(connector):
            try:
                if not current():
                    return "request_interrupted"
                return await self._store.async_set_schedule_request(entry_id, identity, requested, current)
            except Exception:  # noqa: BLE001 - unavailable evidence is not permission
                return "request_unavailable"

    async def async_invalidate(self, connector: PhysicalConnector) -> Generation:
        """Invalidate previously captured work after preceding connector operations finish."""
        async with self._lock_for(connector):
            self._generations[connector] = self._generations.get(connector, 0) + 1
            return self.generation(connector)

    async def async_quiesce_for_reload(self, connector: PhysicalConnector) -> Generation:
        """Close ordinary admission and drain its lock for a future handover design.

        The latch is set before waiting for the lock, so queued work cannot overtake
        the drain. Cancellation leaves it closed. This does not cancel a dispatched
        command, stop producers, persist a transition, or authorize a new owner.
        The latch belongs to the HA-process-wide service: an entry reload alone
        does not clear it. No current production path calls this seam.
        Call without holding controller, assignment, profile or connector locks.
        """
        self._quiescing.add(connector)
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
            if connector in self._quiescing:
                return "connector_quiescing"
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
        if kind not in ("legacy_actuator", "person_stop", "owned_profile"):
            return AdmissionResult(False, "invalid_operation")
        try:
            connector = physical_connector(resolve_identity())
        except Exception:  # noqa: BLE001 - an unavailable resolver cannot admit a write
            connector = None
        if connector is None:
            return AdmissionResult(False, "identity_unresolved")

        if expected_generation is None:
            expected_generation = self.generation(connector)

        async with self._lock_for(connector):
            if connector in self._quiescing:
                return AdmissionResult(False, "connector_quiescing")
            reservation = _STOP_RESERVATION.get()
            person = (kind == "person_stop" and reservation == (self, entry_id, connector, asyncio.current_task()))
            if kind == "person_stop" and not person:
                return AdmissionResult(False, "person_stop_not_reserved")
            if not person and self.lifecycle_blocked(entry_id, connector):
                return AdmissionResult(False, "lifecycle_initializing")
            if connector in self._entry_draining and not person:
                return AdmissionResult(False, "connector_quiescing")
            if not person and (expected_generation != self.generation(connector) or self._person_stops.get(connector)):
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
            if not person and self.lifecycle_blocked(entry_id, connector):
                return AdmissionResult(False, "lifecycle_initializing")
            if not person and (expected_generation != self.generation(connector) or self._person_stops.get(connector)):
                return AdmissionResult(False, "stale_generation")
            state = status.get("record_state")
            uncertain_stop = person and state == "save_failed" and status.get("person_stop_safe_during_transition_failure") is True
            if state != "valid" and not uncertain_stop:
                return AdmissionResult(False, f"ownership_{state}" if state in (
                    "missing", "malformed", "unsupported_version", "save_failed", "conflict",
                    "identity_unresolved", "identity_mismatch",
                ) else "ownership_unavailable")
            if (type(status.get("connector_id")) is not int or
                    (status.get("station_id"), status.get("connector_id")) != (connector.station_id, connector.connector_id)):
                return AdmissionResult(False, "ownership_identity_mismatch")
            owner = "legacy" if uncertain_stop else status.get("recorded_owner")
            if owner not in ("legacy", "morek_schedule"):
                return AdmissionResult(False, "ownership_unavailable")
            if kind == "owned_profile":
                # This path is reachable only with a verified completed migration
                # and a process-local ticket; neither an owner nor a disk marker alone
                # is enough after restart or a lifecycle interruption.
                if (owner != "morek_schedule" or status.get("handover_evidence") != "completed"
                        or not self.ticket_current(entry_id, connector, status.get("handover_id"))):
                    return AdmissionResult(False, "schedule_mode_unarmed")
                from .execution_ownership import _decode, _read_envelope
                from .morek_outcomes import outcomes_for
                try:
                    async with self._store._lock:
                        raw = await self._store._hass.async_add_executor_job(_read_envelope, self._store._store.path)
                        disk_state, disk = _decode(raw)
                        if (disk_state != "valid" or disk != self._store._records or self._store._state != "valid"
                                or self._store._transition_save_uncertain or self._store._cancelled_write):
                            return AdmissionResult(False, "ownership_unavailable")
                    outcome = await outcomes_for(self._store._hass).read()
                    if (outcome is None or outcome.get("entry_id") != entry_id or outcome.get("uncertain") is not False
                            or not isinstance(outcome.get("attempt"), dict)
                            or outcome["attempt"].get("state") not in ("accepted", "rejected", "aborted_before_dispatch")
                            or (outcome.get("removal") is not None and outcome["removal"].get("state") not in
                                ("accepted", "rejected", "notsupported"))):
                        return AdmissionResult(False, "profile_outcome_unavailable")
                    fresh = dict(resolve_identity())
                    if (classify_morek_identity(fresh) != "supported_morek" or physical_connector(fresh) != connector
                            or self.lifecycle_blocked(entry_id, connector)
                            or expected_generation != self.generation(connector)
                            or not self.ticket_current(entry_id, connector, status.get("handover_id"))):
                        return AdmissionResult(False, "stale_generation")
                except Exception:  # noqa: BLE001 - unavailable evidence never authorizes a write
                    return AdmissionResult(False, "ownership_unavailable")
                return AdmissionResult(True, "allowed_owned_profile", await operation())
            if owner != "legacy":
                return AdmissionResult(False, "legacy_not_owner")
            if status.get("armed") is not False:
                return AdmissionResult(False, "ownership_inconsistent")
            if status.get("transition_state") == "exit_held_unarmed":
                return AdmissionResult(False, "retained_profile_exit_held")
            if status.get("transition_state") is not None and not person:
                return AdmissionResult(False, "ownership_transition")
            # Quiescing may have begun while the store read was in progress.
            if connector in self._quiescing or (connector in self._entry_draining and not person):
                return AdmissionResult(False, "connector_quiescing")
            try:
                return AdmissionResult(True, "allowed_legacy", await operation())
            except BaseException:
                if not person:
                    self._uncertain_operations.add(connector)
                raise

    async def async_manual_profile(
        self, entry_id: str, resolve_identity: Callable[[], Mapping[str, Any]], operation: Callable[[], Awaitable[T]]
    ) -> AdmissionResult[T]:
        """Serialize the existing explicitly requested experiment, not autonomous ownership.

        The caller retains its admin, pause, preview and selective-clear checks.
        This is not an activation path and does not admit owned_profile work.
        """
        try:
            identity = dict(resolve_identity())
            connector = physical_connector(identity)
            if connector is None or classify_morek_identity(identity) != "supported_morek":
                return AdmissionResult(False, "identity_unresolved")
        except Exception:  # noqa: BLE001
            return AdmissionResult(False, "identity_unresolved")
        generation = self.generation(connector)
        async with self._lock_for(connector):
            if self.lifecycle_blocked(entry_id, connector):
                return AdmissionResult(False, "lifecycle_initializing")
            if connector in self._quiescing or connector in self._entry_draining:
                return AdmissionResult(False, "connector_quiescing")
            if generation != self.generation(connector):
                return AdmissionResult(False, "stale_generation")
            try:
                identity = dict(resolve_identity())
                if classify_morek_identity(identity) != "supported_morek" or physical_connector(identity) != connector:
                    return AdmissionResult(False, "identity_changed")
            except Exception:  # noqa: BLE001
                return AdmissionResult(False, "identity_changed")
            try:
                status = await self._store.async_status(entry_id, identity)
                if (classify_morek_identity(resolve_identity()) != "supported_morek"
                        or physical_connector(resolve_identity()) != connector):
                    return AdmissionResult(False, "identity_changed")
                if status.get("record_state") != "valid" or status.get("transition_state") is not None:
                    return AdmissionResult(False, "ownership_unavailable")
                if status.get("recorded_owner") != "legacy" or status.get("armed") is not False:
                    return AdmissionResult(False, "legacy_not_owner")
                if (status.get("station_id"), status.get("connector_id")) != (connector.station_id, connector.connector_id):
                    return AdmissionResult(False, "ownership_identity_mismatch")
                # A person Stop can reserve the connector while the durable owner
                # lookup is awaiting. Do not admit the older manual profile action.
                if generation != self.generation(connector) or self._person_stops.get(connector):
                    return AdmissionResult(False, "stale_generation")
                if self.lifecycle_blocked(entry_id, connector):
                    return AdmissionResult(False, "lifecycle_initializing")
                if connector in self._quiescing or connector in self._entry_draining:
                    return AdmissionResult(False, "connector_quiescing")
            except Exception:  # noqa: BLE001 - unverified durable state cannot admit profile writes
                return AdmissionResult(False, "ownership_unavailable")
            return AdmissionResult(True, "manual_profile", await operation())


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
    async def guard(operation: Callable[[], Awaitable[T]], *, person_stop: bool = False) -> AdmissionResult[T]:
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
        return await command_admission(hass).async_execute(
            entry_id, "person_stop" if person_stop else "legacy_actuator", identity, operation)
    def stop_scope():
        from ..api.morek_schedule import _identity_status

        return command_admission(hass).person_stop_reservation(entry_id, lambda: _identity_status(hass, resolve_target()))

    guard.stop_scope = stop_scope
    return guard
