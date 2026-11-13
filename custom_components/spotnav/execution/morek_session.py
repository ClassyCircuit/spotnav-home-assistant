"""Connector-bound session requests, separate from schedule-window execution."""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timezone
import logging
from uuid import uuid4

from ..api import morek_schedule
from ..runtime import controller_for, domain_data
from .command_admission import classify_morek_identity, command_admission, physical_connector

_REDACT_REQUEST = contextvars.ContextVar("spotnav_morek_remote_start", default=False)


class _RequestLogFilter(logging.Filter):
    """Suppress only this task's OCPP request logging, not other charger tasks."""

    def filter(self, record):
        return not _REDACT_REQUEST.get()


def _request_loggers(point):
    """The known v1.6 call path must expose both protocol and websocket loggers."""
    if type(point).__module__ != "custom_components.ocpp.ocppv16":
        return None
    method = getattr(point, "start_transaction", None)
    def underlying(value):
        return value.logger if isinstance(value, logging.LoggerAdapter) else value
    protocol = underlying(getattr(point, "logger", None))
    websocket = underlying(getattr(getattr(point, "_connection", None), "logger", None))
    if not callable(method) or not all(isinstance(x, logging.Logger) for x in (protocol, websocket)):
        return None
    return tuple({logging.getLogger("custom_components.ocpp"), protocol, websocket})


def _safe_logging(point):
    """Refuse when independent OCPP receive/frame tasks could log identifiers.

    The task-local filter below covers the request itself, not unrelated protocol
    receive tasks. Their potentially sensitive logs must already be disabled.
    """
    loggers = _request_loggers(point)
    if loggers is None:
        return False
    protocol = getattr(point, "logger", None)
    websocket = getattr(getattr(point, "_connection", None), "logger", None)
    return (not logging.getLogger("custom_components.ocpp").isEnabledFor(logging.INFO)
            and not protocol.isEnabledFor(logging.INFO)
            and not websocket.isEnabledFor(logging.DEBUG))


async def _start(point, connector):
    """Call the integration's own start with request-task logging contained."""
    loggers = _request_loggers(point)
    if loggers is None:
        return "unsupported_ocpp_logging_or_interface"
    guard = _RequestLogFilter()
    for logger in loggers:
        logger.addFilter(guard)
    token = _REDACT_REQUEST.set(True)
    try:
        async with asyncio.timeout(30):
            result = await point.start_transaction(connector_id=connector)
        return "accepted" if result is True else "rejected" if result is False else "unknown"
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the command may already have reached the charger
        return "unknown"
    finally:
        _REDACT_REQUEST.reset(token)
        for logger in loggers:
            logger.removeFilter(guard)


class MorekSessionCoordinator:
    """One request for an observed unplug-to-plug transition, serialized with Stop."""

    def __init__(self, worker):
        self.worker = worker
        self.hass = worker._hass
        self.entry_id = worker._entry_id
        self.connection = None
        self.observation = "unknown"
        self.task = None
        self.dirty = False
        self.closed = False
        self.retry = None
        self.completed = False
        self.completion_pending = False
        self.boot_generation = None
        self.offline_observed = False
        self.state = {"state": "waiting", "reason": "waiting_for_vehicle"}

    def observe(self, old, new):
        old = str(old or "").lower()
        new = str(new or "").lower()
        if self.boot_generation is None:
            self.boot_generation = self._charger_boot_generation()
        self.observation = new
        if new == "available":
            self.connection = None
            self.completed = False
            self.offline_observed = False
            self.state = {"state": "waiting", "reason": "waiting_for_vehicle"}
        elif new in ("charging", "suspendedev", "suspendedevse"):
            self.offline_observed = False
            self.state = {"state": "session_observed", "reason": "charger_reports_active"}
        elif new in ("finishing", "faulted", "unavailable", "unknown"):
            if new == "finishing":
                self.completed = True
                self.completion_pending = True
                self.trigger()
            self.state = {"state": "blocked", "reason": "connector_" + new}
        elif new == "preparing" and old == "available":
            self.connection = uuid4().hex
            self.offline_observed = False
            self.trigger()
        elif new == "preparing" and self.offline_observed:
            if not self.worker._suspended and self.worker._available():
                self.reconnect()
        elif new == "preparing" and self.connection is None:
            if self.completed or old in ("finishing", "charging", "suspendedev", "suspendedevse"):
                self.state = {"state": "blocked", "reason": "session_ended_or_completion_ambiguous"}
            else:
                # Stable across process restarts: a previously recorded recovery
                # remains deduplicated even when its callback is delivered again.
                self.connection = "recovery"
                self.state = {"state": "waiting", "reason": "ambiguous_recovery"}
                self.trigger()

    def resume(self, intent_id):
        """An explicit person Resume may authorize one new ambiguous request."""
        if self.observation == "preparing":
            self.completed = False
            self.connection = "resume:" + intent_id
            self.trigger()

    def reconnect(self):
        """A reconnect in Preparing is ambiguous, never proof an old session ended."""
        if self.observation == "preparing" and not self.completed:
            boot = self._charger_boot_generation()
            if self.offline_observed:
                self.connection = "offline:" + uuid4().hex
                self.offline_observed = False
            elif (boot is not None and self.boot_generation is not None and boot > self.boot_generation):
                # Only an increase seen within this process establishes a new boot.
                # A reset across HA restart is not itself a new charger boot.
                self.connection = "boot:" + uuid4().hex
            elif self.connection is None:
                self.connection = "recovery"
            if boot is not None:
                self.boot_generation = boot
        self.trigger()

    def offline(self):
        """Remember a real availability loss until its subsequent online observation."""
        self.offline_observed = True
        self.state = {"state": "offline", "reason": "charger_offline"}

    def availability_lost(self):
        """A transaction-bound switch can be unavailable while OCPP is still online."""
        try:
            target = controller_for(self.hass, self.entry_id).ocpp_target
            identity = morek_schedule._intent_identity_status(self.hass, target)
            if not morek_schedule._owned_intent_identity_ok(identity):
                return
            try:
                morek_schedule._charge_point(self.hass, target)
            except morek_schedule.ScheduleRefused as error:
                if error.code == "morek_offline":
                    self.offline()
        except Exception:  # noqa: BLE001 - ambiguous availability is not a reconnect edge
            return

    def _charger_boot_generation(self):
        try:
            target = controller_for(self.hass, self.entry_id).ocpp_target
            value = getattr(morek_schedule._charge_point(self.hass, target), "charger_generation", None)
            return value if type(value) is int and value > 0 else None
        except Exception:  # noqa: BLE001 - unsupported or offline is not boot evidence
            return None

    def trigger(self):
        self.dirty = True
        if not self.closed and (self.task is None or self.task.done()):
            self.task = self.hass.async_create_task(self._run())

    def close(self):
        self.closed = True
        if self.retry is not None:
            self.retry.cancel()
        if self.task is not None:
            self.task.cancel()

    async def _run(self):
        while self.dirty and not self.closed:
            self.dirty = False
            await self._reconcile()

    async def _reconcile(self):
        if self.observation not in ("preparing", "finishing") and not self.completion_pending:
            return
        worker = self.worker
        identity = worker._identity()
        connector = physical_connector(identity)
        if classify_morek_identity(identity) != "supported_morek" or connector is None:
            self.state = {"state": "blocked", "reason": "identity_unresolved"}
            return
        admission = command_admission(self.hass)
        generation = admission.generation(connector)
        connection = self.connection

        async def run():
            data, _ = await morek_schedule._state(self.hass, self.entry_id)
            async with self.hass.data[morek_schedule._DATA_KEY][self.entry_id][2]:
                ledger = morek_schedule.outcomes_for(self.hass)
                record = await morek_schedule._outcome_record(self.hass, self.entry_id, data)
                if self.completion_pending:
                    if record.get("session_completed") is not True:
                        record["session_completed"] = True
                        await ledger.write(record)
                    self.completion_pending = False
                    if self.observation == "preparing":
                        self.dirty = True
                    return "blocked", "car_completion_reported"

                def validate():
                    if (self.closed or worker._closed or worker._suspended or not worker._available()
                            or generation != admission.generation(connector)
                            or admission._person_stops.get(connector)
                            or not admission.owned_ticket_current(self.entry_id, connector)
                            or physical_connector(worker._identity()) != connector
                            or classify_morek_identity(worker._identity()) != "supported_morek"
                            or self.connection != connection or connection is None
                            or self.observation != "preparing" or self.completed):
                        return "stale_or_ambiguous_session"
                    pause = record.get("schedule_pause")
                    if pause and (pause.get("type") != "resume_requested" or
                                  worker.resume_ticket != (pause.get("id"), generation)):
                        return "paused_until_resume"
                    settings = domain_data(self.hass).auto_store.settings(self.entry_id)
                    if getattr(getattr(settings, "pause", None), "admitted", False):
                        return "legacy_pause_active"
                    controller = controller_for(self.hass, self.entry_id)
                    if callable(getattr(controller, "_start_cap", None)):
                        return "protection_conflict_unresolved"
                    worker._intent(pause)
                    return None

                blocker = validate()
                if blocker:
                    return "blocked", blocker
                if (record.get("session_completed") is True and
                        (connection == "recovery" or connection.startswith(("offline:", "boot:")))):
                    return "blocked", "car_completion_reported"
                if record.get("session_completed") not in (None, True):
                    return "uncertain", "session_record_invalid"
                prior = record.get("session_start")
                attempts = 0
                if prior is not None:
                    if (not isinstance(prior, dict) or prior.get("version") != 1
                            or not isinstance(prior.get("connection"), str)
                            or prior.get("state") not in ("pending", "unknown", "accepted", "rejected",
                                                          "aborted_before_dispatch")):
                        return "uncertain", "session_record_invalid"
                    if prior.get("state") in ("unknown", "pending"):
                        return "uncertain", "previous_start_may_have_applied"
                    if (connection == "recovery" and prior.get("connection", "").startswith(
                            ("resume:", "offline:", "boot:"))):
                        return prior.get("state", "blocked"), "already_requested"
                    if prior.get("connection") == connection:
                        attempts = prior.get("attempts", 1)
                        if type(attempts) is not int or not 1 <= attempts <= 2:
                            return "uncertain", "session_record_invalid"
                        if prior.get("state") not in ("rejected", "aborted_before_dispatch") or attempts >= 2:
                            return prior.get("state", "blocked"), "already_requested"
                        try:
                            age = (datetime.now(timezone.utc) - datetime.fromisoformat(prior["at"])).total_seconds()
                        except (KeyError, ValueError, TypeError):
                            return "uncertain", "session_record_invalid"
                        if age < 60:
                            return "waiting", "retry_cooldown"
                point = morek_schedule._charge_point(self.hass, controller_for(self.hass, self.entry_id).ocpp_target)
                if _request_loggers(point) is None:
                    return "blocked", "unsupported_ocpp_logging_or_interface"
                if not _safe_logging(point):
                    return "blocked", "ocpp_sensitive_logging_enabled"
                attempt = {"version": 1, "connection": connection, "state": "pending",
                           "at": datetime.now(timezone.utc).isoformat(), "attempts": attempts + 1}
                record.pop("session_completed", None)
                record["session_start"] = attempt
                await ledger.write(record)
                if not await admission.async_owned_boundary_current(self.entry_id, connector):
                    if await ledger.read() == record:
                        attempt["state"] = "aborted_before_dispatch"
                        await ledger.write(record)
                        return "blocked", "ownership_recheck_failed"
                    return "uncertain", "outcome_storage_changed"
                if await ledger.read() != record:
                    return "uncertain", "outcome_storage_changed"
                blocker = validate()
                if morek_schedule._charge_point(self.hass, controller_for(self.hass, self.entry_id).ocpp_target) is not point:
                    blocker = "charger_connection_changed"
                if not _safe_logging(point):
                    blocker = "ocpp_sensitive_logging_enabled"
                if blocker:
                    attempt["state"] = "aborted_before_dispatch"
                    await ledger.write(record)
                    return "blocked", blocker
                self.state = {"state": "starting", "reason": "request_in_progress"}
                result = await _start(point, connector.connector_id)
                attempt["state"] = result
                await ledger.write(record)
                if validate() is not None:
                    return "blocked", "newer_stop_or_connection_change"
                return result, "request_" + result

        try:
            result = await admission.async_execute(self.entry_id, "owned_profile", worker._identity, run,
                                                   expected_generation=generation)
            if result.allowed:
                state, reason = result.value
                self.state = {"state": state, "reason": reason}
                if state == "rejected" and reason == "request_rejected" and self.retry is None:
                    def retry():
                        self.retry = None
                        if self.connection == connection and self.observation == "preparing":
                            self.trigger()
                    self.retry = asyncio.get_running_loop().call_later(60, retry)
            else:
                self.state = {"state": "blocked", "reason": result.reason}
        except asyncio.CancelledError:
            self.state = {"state": "uncertain", "reason": "request_interrupted"}
            raise
        except Exception:  # noqa: BLE001 - never print an OCPP exception or payload
            self.state = {"state": "uncertain", "reason": "session_evidence_unavailable"}
