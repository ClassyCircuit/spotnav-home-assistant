"""Unarmed, event-driven Morek intent reconciliation.

Admission is the final physical-connector lock. No profile, controller or
assignment lock is taken inside it. This is not an ownership transition or a
durable attempt ledger; production owned-profile admission always refuses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..api import morek_schedule
from ..runtime import controller_for, domain_data, preview_for
from .command_admission import classify_morek_identity, command_admission, physical_connector

_LOGGER = logging.getLogger(__name__)
_DATA_KEY = "spotnav_morek_worker_attempts"
_COALESCE_SECONDS = 0.1
_UPLOAD_TIMEOUT = 30


@dataclass
class _ConnectorAttempts:
    """Process-local only; unknown is latched across worker/entry reloads."""

    accepted: str | None = None
    rejected: str | None = None
    uncertain: bool = False


class MorekScheduleWorker:
    """Subscribe to planner publications and reconcile the newest valid intent."""

    def __init__(self, hass: HomeAssistant, entry_id: str, planner: Any) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._planner = planner
        self._serial = 0
        self._task: asyncio.Task | None = None
        self._remove = None
        self._closed = False
        self.reason = "not_started"

    def start(self) -> None:
        """The listener delivers the current snapshot immediately, including on startup."""
        self._remove = self._planner.add_publication_listener(self.trigger)

    def trigger(self, _snapshot: Any = None) -> None:
        if self._closed:
            return
        self._serial += 1
        if self._task is None or self._task.done():
            self._task = self._hass.async_create_task(self._run())

    def close(self) -> None:
        """Unsubscribe and cancel pending work; an in-flight send remains uncertain."""
        self._closed = True
        self._serial += 1
        if self._remove is not None:
            self._remove()
            self._remove = None
        if self._task is not None:
            self._task.cancel()

    def _identity(self) -> dict[str, Any]:
        controller = controller_for(self._hass, self._entry_id)
        return morek_schedule._identity_status(self._hass, getattr(controller, "ocpp_target", None))

    def _intent(self) -> tuple[dict[str, Any], str]:
        if preview_for(self._hass, self._entry_id) is not self._planner:
            raise morek_schedule.ScheduleRefused("planner_changed")
        settings = domain_data(self._hass).auto_store.settings(self._entry_id)
        profile = morek_schedule._proposed_profile(self._hass, self._entry_id, datetime.now(timezone.utc))
        return profile, morek_schedule._preview_id(profile, settings.revision)

    async def _run(self) -> None:
        try:
            while not self._closed:
                serial = self._serial
                await asyncio.sleep(_COALESCE_SECONDS)
                if serial != self._serial:
                    continue
                try:
                    await self._reconcile(serial)
                except morek_schedule.ScheduleRefused as error:
                    self.reason = error.code
                except Exception:  # noqa: BLE001 - a failed calculation is not permission to send
                    self.reason = "worker_unavailable"
                    _LOGGER.exception("Morek schedule worker failed")
                if serial == self._serial:
                    return
        finally:
            self._task = None

    async def _reconcile(self, serial: int) -> None:
        identity = self._identity()
        connector = physical_connector(identity)
        if classify_morek_identity(identity) != "supported_morek" or connector is None:
            self.reason = "identity_unresolved"
            return
        _, fingerprint = self._intent()
        admission = command_admission(self._hass)
        generation = admission.generation(connector)

        async def dispatch() -> str:
            # Admission has checked identity, ownership and generation under the
            # physical connector lock. Do not await between this recheck and call.
            if self._closed or serial != self._serial:
                return "stale_work"
            profile, current = self._intent()
            if current != fingerprint:
                # A time boundary or unpublished edit changed the wire intent.
                self.trigger()
                return "stale_work"
            attempts = self._hass.data.setdefault(_DATA_KEY, {}).setdefault(connector, _ConnectorAttempts())
            if attempts.uncertain:
                return "upload_uncertain"
            if current == attempts.accepted:
                return "unchanged"
            if current == attempts.rejected:
                return "upload_rejected"
            controller = controller_for(self._hass, self._entry_id)
            target = getattr(controller, "ocpp_target", None)
            point = morek_schedule._charge_point(self._hass, target)
            from ocpp.v16 import call as ocpp_call

            request = ocpp_call.SetChargingProfile(connector_id=target.connector_id, cs_charging_profiles=profile)
            # Cancellation/timeout can outlive this task and may have applied.
            attempts.uncertain = True
            try:
                async with asyncio.timeout(_UPLOAD_TIMEOUT):
                    response = await point.call(request)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - unknown outcome is never a failed upload
                return "upload_uncertain"
            status = morek_schedule._status(response).lower()
            if status == "accepted":
                attempts.accepted, attempts.rejected, attempts.uncertain = current, None, False
                return "upload_accepted_unverified"
            if status in ("rejected", "notsupported"):
                attempts.rejected, attempts.uncertain = current, False
                return "upload_rejected"
            return "upload_uncertain"

        result = await admission.async_execute(
            self._entry_id, "owned_profile", self._identity, dispatch, expected_generation=generation
        )
        if self._closed:
            return
        self.reason = result.value if result.allowed else result.reason
