"""Unarmed, event-driven Morek intent reconciliation.

Admission is the final physical-connector lock. No controller or assignment
lock is taken inside it. The shared outcome ledger is not an ownership
transition; production owned-profile admission always refuses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from ..api import morek_schedule
from ..runtime import controller_for, domain_data, preview_for
from .command_admission import classify_morek_identity, command_admission, physical_connector

_LOGGER = logging.getLogger(__name__)
_COALESCE_SECONDS = 0.1


class MorekScheduleWorker:
    """Subscribe to planner publications and reconcile the newest valid intent."""

    def __init__(self, hass: HomeAssistant, entry_id: str, planner: Any,
                 available: Callable[[], bool] | None = None) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._planner = planner
        self._available = available or (lambda: True)
        self._serial = 0
        self._task: asyncio.Task | None = None
        self._remove = None
        self._closed = False
        self._availability_generation = 0
        self._suspended = False
        self.reason = "not_started"
        self.resume_ticket = None

    def start(self) -> None:
        """The listener delivers the current snapshot immediately, including on startup."""
        self._remove = self._planner.add_publication_listener(self.trigger)

    def trigger(self, _snapshot: Any = None) -> None:
        if self._closed:
            return
        self._serial += 1
        if self._task is None or self._task.done():
            self._task = self._hass.async_create_task(self._run())

    def suspend_for_availability_change(self) -> int:
        """Invalidate queued work until this transition's initialization completes."""
        self._availability_generation += 1
        self._suspended = True
        self.trigger()
        return self._availability_generation

    def resume_after_availability_change(self, generation: int) -> None:
        if not self._closed and generation == self._availability_generation:
            self._suspended = False
            self.trigger()

    def close(self) -> None:
        """Unsubscribe and cancel pending work; an in-flight send remains uncertain."""
        self._closed = True
        morek_schedule._cancel_verification(self._hass, self._entry_id)
        self._serial += 1
        if self._remove is not None:
            self._remove()
            self._remove = None
        if self._task is not None:
            self._task.cancel()

    def _identity(self) -> dict[str, Any]:
        controller = controller_for(self._hass, self._entry_id)
        return morek_schedule._identity_status(self._hass, getattr(controller, "ocpp_target", None))

    def _intent(self, pause: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        settings = domain_data(self._hass).auto_store.settings(self._entry_id)
        if pause is not None and pause["type"] == "pause_until_resumed":
            profile = morek_schedule.held_off_profile(datetime.now(timezone.utc))
            return profile, morek_schedule._preview_id(profile, [settings.revision, pause["id"]])
        if preview_for(self._hass, self._entry_id) is not self._planner:
            raise morek_schedule.ScheduleRefused("planner_changed")
        profile = morek_schedule._proposed_profile(self._hass, self._entry_id, datetime.now(timezone.utc))
        return profile, morek_schedule._preview_id(profile, [settings.revision, pause["id"]] if pause is not None else settings.revision)

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
        if self._suspended or not self._available():
            self.reason = "charger_unavailable"
            return
        identity = self._identity()
        connector = physical_connector(identity)
        if classify_morek_identity(identity) != "supported_morek" or connector is None:
            self.reason = "identity_unresolved"
            return
        admission = command_admission(self._hass)
        generation = admission.generation(connector)
        data, store = await morek_schedule._state(self._hass, self._entry_id)

        async def dispatch() -> tuple[str, str | None, str | None]:
            # Admission has checked identity, ownership and generation under the
            # physical connector lock. Do not await between this recheck and call.
            if self._closed or serial != self._serial:
                return "stale_work", None, None
            pause: dict[str, Any] | None = None
            fingerprint = ""
            def validate():
                if self._closed or serial != self._serial:
                    raise morek_schedule.ScheduleRefused("stale_work")
                if generation != admission.generation(connector) or admission._person_stops.get(connector):
                    raise morek_schedule.ScheduleRefused("stale_generation")
                if self._suspended or not self._available():
                    raise morek_schedule.ScheduleRefused("charger_unavailable")
                identity_now = self._identity()
                if classify_morek_identity(identity_now) != "supported_morek" or physical_connector(identity_now) != connector:
                    raise morek_schedule.ScheduleRefused("identity_changed")
                profile, current = self._intent(pause)
                if current != fingerprint:
                    self.trigger()
                    raise morek_schedule.ScheduleRefused("stale_work")
                controller = controller_for(self._hass, self._entry_id)
                target = getattr(controller, "ocpp_target", None)
                return profile, morek_schedule._charge_point(self._hass, target), target

            async with self._hass.data[morek_schedule._DATA_KEY][self._entry_id][2]:
                record = await morek_schedule._outcome_record(self._hass, self._entry_id, data)
                pause = record.get("schedule_pause")
                if pause is not None and pause["type"] == "resume_requested" and self.resume_ticket != (pause["id"], generation):
                    return "resume_requires_confirmation", None, None
                _, fingerprint = self._intent(pause)
                outcome = await morek_schedule._send_profile_shared(
                    self._hass, self._entry_id, data, store, fingerprint, validate, automatic=True,
                    pause_id=None if pause is None else pause["id"])
                return outcome, data.get("sent_at"), data.get("attempt_id")

        result = await admission.async_execute(
            self._entry_id, "owned_profile", self._identity, dispatch, expected_generation=generation
        )
        if self._closed:
            return
        if not result.allowed:
            self.reason = result.reason
            return
        outcome, sent_at, attempt_id = result.value
        self.reason = outcome
        if (outcome == "upload_accepted_unverified" and sent_at and attempt_id
                and not self._closed):
            # Admission has been released. The read-only path reacquires it itself.
            morek_schedule._schedule_verification(self._hass, self._entry_id, sent_at, -1, attempt_id)
