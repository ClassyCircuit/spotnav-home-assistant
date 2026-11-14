"""Connector-bound session requests, separate from schedule-window execution."""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timezone
import logging
from uuid import uuid4

from ..api import morek_schedule
from ..runtime import controller_for, domain_data, preview_for
from .morek_freshness import STRICT_EVIDENCE_MAX_AGE_S, judge_event, link_facts
from .command_admission import classify_morek_identity, command_admission, physical_connector

_LOGGER = logging.getLogger(__name__)

# Bounded, memory-only re-evaluation of a transient session blocker (seconds; the last repeats).
SESSION_RETRY_DELAYS = (5, 15, 30, 60, 120, 300)
SESSION_RETRY_LIMIT = 12
NO_TRANSACTION_AFTER_S = 120  # an accepted start with the connector still Preparing: show it, never repeat it
BOOT_EVIDENCE_WINDOW_S = 600  # Stage 15.5: how long a boot signal waits for its post-boot status evidence
_ACTIVE_STATUSES = ("charging", "suspendedev", "suspendedevse")
TRANSIENT_SESSION_BLOCKERS = frozenset({
    "worker_suspended", "charger_unavailable", "stale_generation", "ownership_not_current",
    "identity_changed", "connector_quiescing", "lifecycle_initializing", "retry_cooldown",
    "planner_changed", "ownership_recheck_failed",
})

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
        self.vehicle_events = []
        self._boot = None  # Stage 15.5: the one pending/last boot signal (memory only)
        self.offline_observed = False
        self.available_before_loss = False
        self._fresh_connection = False
        self._recheck = None
        self._recheck_runs = 0
        self._no_transaction = None
        self.state_at = None
        self.state = {"state": "waiting", "reason": "waiting_for_vehicle"}

    @property
    def state(self):
        """The session-start request state (a request outcome, never measured charging)."""
        return self._state

    @state.setter
    def state(self, value):
        # When the state last *changed*, so the status can tell a transient moment from a lasting one.
        # Memory only: after a restart it is the restart time, never an older request's time.
        if value != getattr(self, "_state", None):
            self.state_at = datetime.now(timezone.utc)
        self._state = value

    def observe(self, old, new):
        """Record a connector status change. Never raises into the event bus.

        The coordinator's own state (observation, connection token) is settled first; telling the worker
        about the plug-in comes last and is guarded, so a failure there can never leave a half-observed
        connection that blocks the start.
        """
        old = str(old or "").lower()
        new = str(new or "").lower()
        self._fresh_connection = False
        try:
            self._observe(old, new)
        except Exception as error:  # noqa: BLE001 - one bad observation must not strand the coordinator
            _LOGGER.warning("Morek session observation failed (%s)", type(error).__name__)
            self.state = {"state": "blocked", "reason": "session_observation_failed"}
            return
        try:
            self._note_schedule_evidence(old, new, self._fresh_connection)
        except Exception as error:  # noqa: BLE001 - the recalculation is best effort; the start is not
            _LOGGER.warning("Morek schedule evidence could not be noted (%s)", type(error).__name__)
        self.evaluate_boot()

    def _observe(self, old, new):
        self.observation = new
        boot = self._boot
        if boot is not None and new in _ACTIVE_STATUSES and (not boot["done"] or boot.get("token")):
            boot["active_seen"] = True  # also after the token is minted: it must stay revocable until dispatch
        elif boot is not None and not boot["done"] and new == "available":
            self._close_boot("unplugged_after_boot")
        if new != "preparing":
            self._cancel_no_transaction()
        if new == "available":
            self.available_before_loss = True
            self.connection = None
            self.completed = False
            self.offline_observed = False
            self.state = {"state": "waiting", "reason": "waiting_for_vehicle"}
            self._reset_recheck()
            if old in ("preparing", "charging", "suspendedev", "suspendedevse", "finishing"):
                self.vehicle_events.append(("unplugged", uuid4().hex))
                self.trigger()
        elif new in ("charging", "suspendedev", "suspendedevse"):
            self.available_before_loss = False
            self.offline_observed = False
            self.state = {"state": "session_observed", "reason": "charger_reports_active"}
        elif new in ("finishing", "faulted", "unavailable", "unknown"):
            if new == "finishing":
                self.completed = True
                self.vehicle_events.append(("completed", None))
                self.trigger()
            self.state = {"state": "blocked", "reason": "connector_" + new}
        elif new == "preparing" and (old == "available" or (self.connection is None and self.available_before_loss
                                                             and old in ("unknown", "unavailable", ""))):
            # A plug-in, or a Preparing that follows a sensor/charger flap from a connector last seen Available:
            # no vehicle was there before, so this is one new connection, never an inherited stale session.
            self.available_before_loss = False
            self.connection = uuid4().hex
            self._fresh_connection = True
            self.completed = False
            self.offline_observed = False
            self._reset_recheck()
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
        elif new == "preparing" and old != "preparing":
            # Preparing again after a flap (unavailable and back): the same connection, re-evaluated.
            # Reconcile is idempotent: a recorded request is never repeated, a never-dispatched one proceeds.
            self.trigger()

    def _note_schedule_evidence(self, old, new, fresh=False):
        """Plug-in, and the connector sensor going missing or returning, re-evaluate the schedule.

        A plug-in is only Available to connected. A return from unknown/unavailable is ambiguous (the
        vehicle may have been there all along), so it is a sensor event, never a plug-in.
        `fresh` is set by `_observe` when it created a new connection (including Preparing after a flap from a
        connector last seen Available): that is one plug-in recalculation, never also a sensor one. A return
        to Preparing that reuses an existing connection stays a sensor event, not a plug-in.
        This never sends by itself: the worker recalculates and compares with the accepted schedule.
        """
        lost = ("unknown", "unavailable")
        if fresh or (old == "available" and new in ("preparing", "charging", "suspendedev", "suspendedevse")):
            note = getattr(self.worker, "note_plug_in", None)
            if callable(note):
                note()
        elif old and (old in lost) != (new in lost):
            note = getattr(self.worker, "note_sensor", None)
            if callable(note):
                note()

    def resume(self, intent_id):
        """An explicit person Resume may authorize one new ambiguous request."""
        if self.observation == "preparing":
            self.completed = False
            self.connection = "resume:" + intent_id
            self.trigger()

    def reconnect(self):
        """A reconnect in Preparing is ambiguous, never proof an old session ended.

        Only an observed offline period gives the existing guarded `offline:` recovery token. A boot counter
        rise is not decided here: `note_boot`/`evaluate_boot` require positive post-boot evidence (15.5).
        """
        if self.observation == "preparing" and not self.completed:
            if self.offline_observed:
                self.connection = "offline:" + uuid4().hex
                self.offline_observed = False
                if self._boot is not None and not self._boot["done"]:
                    # This boot's one recovery opportunity is the existing offline request, never a second one.
                    self._close_boot("covered_by_offline_recovery")
            elif self.connection is None:
                self.connection = "recovery"
        self.trigger()

    # ---- Stage 15.5: guarded start after a confirmed reboot

    def note_boot(self, generation):
        """The link monitor saw the boot counter rise within this process: the only positive boot evidence.

        This only opens an evidence window. It starts nothing by itself: `evaluate_boot` mints the `boot:` token
        once a fresh post-boot Preparing report and an affirmative no-transaction report exist. It is deliberately
        not evaluated in this call, so a link edge delivered right after it is ordered first.
        """
        self._boot = {"at": datetime.now(timezone.utc), "generation": generation, "done": False,
                      "active_seen": False, "connection": self.connection,
                      "state": "waiting", "reason": "waiting_for_post_boot_status"}

    def _close_boot(self, reason, state="closed"):
        if self._boot is not None:
            self._boot.update(done=True, state=state, reason=reason)

    def boot_status(self, counter_known):
        """Additive readiness evidence for the boot-triggered start (a request intent, never measured charging)."""
        boot = self._boot
        if boot is None:
            return ({"state": "none", "reason": "no_boot_observed"} if counter_known
                    else {"state": "unknown", "reason": "boot_counter_unavailable"})
        return {"state": boot["state"], "reason": boot["reason"], "at": boot["at"].isoformat(),
                "boot_generation": boot["generation"]}

    def evaluate_boot(self):
        """Re-evaluate a pending boot signal. Local reads only; never raises; at most one token per boot.

        A confirmed reboot is a counter rise **and**, after that signal: a fresh `Preparing` connector report, an
        affirmative no-transaction report (a missing, unknown or pre-signal value blocks) and no Charging/Suspended.
        Everything else (link edges, a new point object, an HA restart) is not boot evidence.
        """
        boot = self._boot
        if boot is None or boot["done"] or self.closed:
            return
        try:
            now = datetime.now(timezone.utc)
            if (now - boot["at"]).total_seconds() > BOOT_EVIDENCE_WINDOW_S:
                self._close_boot("boot_evidence_expired")
                return
            if self.connection != boot["connection"]:
                # A plug-in, recovery or offline request since the signal already owns this opportunity.
                self._close_boot("covered_by_new_connection")
                return
            if boot["active_seen"]:
                self._close_boot("charging_seen_after_boot")
                return
            if self.completed:
                self._close_boot("completion_reported")
                return
            if self.observation != "preparing":
                boot.update(state="waiting", reason="connector_not_preparing")
                return
            reason = self._post_boot_blocker(boot, now)
            if reason == "charging_seen_after_boot":
                boot["active_seen"] = True
                self._close_boot(reason)
            elif reason is not None:
                boot.update(state="waiting" if reason == "waiting_for_post_boot_status" else "blocked", reason=reason)
            else:
                self.connection = boot["token"] = "boot:" + uuid4().hex  # the evidence this token stands for
                self._close_boot("boot_start_requested", state="requested")
                self.trigger()
        except Exception as error:  # noqa: BLE001 - boot evidence is best effort and never blocks other paths
            _LOGGER.debug("Morek boot evidence failed (%s)", type(error).__name__)

    def _post_boot_blocker(self, boot, now):
        """None when the post-boot evidence is complete; otherwise the truthful reason it is not."""
        live = morek_schedule._live_measurements(self.hass, controller_for(self.hass, self.entry_id), now)

        def after(reading):  # a fresh HA-stamped reading that postdates the boot signal
            return (isinstance(reading, dict) and reading.get("fresh") is True
                    and datetime.fromisoformat(reading["observed_at"]) > boot["at"])

        status = live.get("status")
        value = str((status or {}).get("value", "")).lower()
        if after(status) and value in _ACTIVE_STATUSES:
            return "charging_seen_after_boot"
        if not after(status) or value != "preparing":
            return "waiting_for_post_boot_status"
        transaction = live.get("transaction")
        if transaction is None or transaction.get("value") is None:
            return "transaction_unknown"
        if not after(transaction):
            return "transaction_not_reported_after_boot"
        if transaction["value"] is not False:
            return "transaction_present"
        return None

    def _boot_start_blocker(self, connection):
        """Pre-dispatch recheck of a `boot:` token against its own boot evidence (None = still valid).

        The token was minted from fresh post-boot evidence, but `_reconcile` awaits storage and admission before
        the wire; a transaction or Charging can appear meanwhile. Local reads only, never raises.
        """
        try:
            boot = self._boot
            if boot is None or boot.get("token") != connection:
                return "boot_evidence_replaced"
            now = datetime.now(timezone.utc)
            if (now - boot["at"]).total_seconds() > BOOT_EVIDENCE_WINDOW_S:
                return "boot_evidence_expired"
            if boot["active_seen"]:
                return "charging_seen_after_boot"
            reason = self._post_boot_blocker(boot, now)
            if reason == "charging_seen_after_boot":
                boot["active_seen"] = True
            return reason
        except Exception as error:  # noqa: BLE001 - unverifiable evidence withholds the start
            _LOGGER.debug("Morek boot recheck failed (%s)", type(error).__name__)
            return "boot_evidence_unavailable"

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

    def observe_initial(self, state, now):
        """Use a fresh HA state, or a corroborating in-process OCPP Preparing value.

        OCPP 0.12's connector metric has no report timestamp; it is last-known,
        not proof of a live vehicle or transaction. The user permits one bounded
        ambiguous Preparing recovery, never an active-session assertion.
        """
        if state is None or getattr(state, "attributes", {}).get("restored", False):
            return
        stamp = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
        if isinstance(stamp, datetime) and stamp.tzinfo is not None and (
                0 <= (now - stamp).total_seconds() <= STRICT_EVIDENCE_MAX_AGE_S
                # 15.6: an unchanged report is also current while this process has seen the link continuously up
                # since it (never a report that predates the monitor's own observation, so never pre-restart).
                or judge_event(stamp, now, link_facts(getattr(self.worker, "link_monitor", None)))["state"]
                == "current"):
            self.observe(None, state.state)
            return
        if str(state.state).lower() != "preparing":
            return
        try:
            identity = self.worker._identity()
            if classify_morek_identity(identity) != "supported_morek":
                return
            target = controller_for(self.hass, self.entry_id).ocpp_target
            point = morek_schedule._charge_point(self.hass, target)
            if type(point).__module__ != "custom_components.ocpp.ocppv16":
                return
            metric = getattr(point, "_metrics", {}).get((target.connector_id, "Status.Connector"))
            if str(getattr(metric, "value", "")).lower() == "preparing":
                self.observe(None, "Preparing")
        except Exception:  # noqa: BLE001 - an unavailable metric is not an observation
            return

    def trigger(self):
        self.dirty = True
        if not self.closed and (self.task is None or self.task.done()):
            self.task = self.hass.async_create_task(self._run())

    def _reset_recheck(self):
        self._recheck_runs = 0
        if self._recheck is not None:
            self._recheck.cancel()
            self._recheck = None

    def _cancel_no_transaction(self):
        if self._no_transaction is not None:
            self._no_transaction.cancel()
            self._no_transaction = None

    def _arm_recheck(self):
        """Bounded timer re-evaluation of a transient blocker; events still re-evaluate immediately.

        Only blockers that end by themselves are in the set. A person Stop/Pause, a completed or ambiguous
        session, an unknown or pending earlier request and an identity or protection conflict never are.
        """
        if self._recheck is not None:
            self._recheck.cancel()
            self._recheck = None
        state = self.state
        if (self.closed or self.observation != "preparing" or state.get("state") not in ("blocked", "waiting")
                or state.get("reason") not in TRANSIENT_SESSION_BLOCKERS):
            self._recheck_runs = 0
            return
        if self._recheck_runs >= SESSION_RETRY_LIMIT:
            return
        delay = 61 if state.get("reason") == "retry_cooldown" else SESSION_RETRY_DELAYS[
            min(self._recheck_runs, len(SESSION_RETRY_DELAYS) - 1)]
        self._recheck_runs += 1

        def fire():
            self._recheck = None
            if not self.closed and self.observation == "preparing":
                self.trigger()

        self._recheck = asyncio.get_running_loop().call_later(delay, fire)

    def _arm_no_transaction(self, connection):
        """An accepted start with the connector still Preparing is shown, never silently repeated."""
        self._cancel_no_transaction()

        def fire():
            self._no_transaction = None
            if (not self.closed and self.observation == "preparing" and self.connection == connection
                    and self.state == {"state": "accepted", "reason": "request_accepted"}):
                self.state = {"state": "accepted", "reason": "no_transaction_observed"}
                _LOGGER.warning("Morek session start accepted but no transaction was observed; "
                                "it is not repeated automatically")

        self._no_transaction = asyncio.get_running_loop().call_later(NO_TRANSACTION_AFTER_S, fire)

    def close(self):
        self.closed = True
        self._reset_recheck()
        self._cancel_no_transaction()
        if self.retry is not None:
            self.retry.cancel()
        if self.task is not None:
            self.task.cancel()

    async def _run(self):
        while self.dirty and not self.closed:
            self.dirty = False
            before = dict(self.state)
            await self._reconcile()
            self._log_state(before)

    def _log_state(self, before):
        """One line per changed session-start state: the request (intent), never a measured charge.

        Codes only: no station, connector or OCPP payload. A repeat of the same state is silent.
        """
        state = self.state
        if state == before or state.get("reason") == "waiting_for_vehicle":
            return
        code, reason = state.get("state"), state.get("reason")
        level = logging.WARNING if code in ("rejected", "uncertain") else logging.INFO
        _LOGGER.log(level, "Morek session start %s (%s); a request outcome is not measured charging", code, reason)

    async def _reconcile(self):
        if self.observation not in ("preparing", "finishing") and not self.vehicle_events:
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
            nonlocal connection
            data, _ = await morek_schedule._state(self.hass, self.entry_id)
            async with self.hass.data[morek_schedule._DATA_KEY][self.entry_id][2]:
                ledger = morek_schedule.outcomes_for(self.hass)
                record = await morek_schedule._outcome_record(self.hass, self.entry_id, data)
                if self.vehicle_events:
                    event, marker = self.vehicle_events[0]
                    if event == "completed":
                        record["session_completed"] = True
                        record.pop("session_unplugged", None)
                    else:
                        record.pop("session_completed", None)
                        record["session_unplugged"] = marker
                    await ledger.write(record)
                    self.vehicle_events.pop(0)
                    if self.vehicle_events or self.observation == "preparing":
                        self.dirty = True
                    return "waiting", "vehicle_event_recorded"

                unplugged = record.get("session_unplugged")
                if unplugged is not None and (not isinstance(unplugged, str) or len(unplugged) != 32
                                              or any(c not in "0123456789abcdef" for c in unplugged)):
                    return "uncertain", "session_record_invalid"
                if connection == "recovery" and unplugged and self.connection == connection:
                    connection = self.connection = "unplug:" + unplugged

                def validate(post=False):
                    if self.closed or worker._closed:
                        return "session_closed"
                    if worker._suspended:
                        return "worker_suspended"
                    if not worker._available():
                        return "charger_unavailable"
                    if generation != admission.generation(connector):
                        return "stale_generation"
                    if admission._person_stops.get(connector):
                        return "person_stop_active"
                    if not admission.owned_ticket_current(self.entry_id, connector):
                        return "ownership_not_current"
                    if (physical_connector(worker._identity()) != connector
                            or classify_morek_identity(worker._identity()) != "supported_morek"):
                        return "identity_changed"
                    if connection is None or self.connection is None:
                        return ("session_ended_or_completion_ambiguous" if self.completed
                                else "waiting_for_new_connection")
                    if self.connection != connection:
                        return "connection_changed"
                    if not post:
                        if self.completed:
                            return "session_completed"
                        if self.observation != "preparing":
                            return "connector_not_preparing"
                        if connection.startswith("boot:"):
                            reason = self._boot_start_blocker(connection)
                            if reason is not None:
                                return reason
                    pause = record.get("schedule_pause")
                    if pause and not morek_schedule._resume_authorized(record, worker, generation):
                        return "paused_until_resume"
                    settings = domain_data(self.hass).auto_store.settings(self.entry_id)
                    if getattr(getattr(settings, "pause", None), "admitted", False):
                        return "legacy_pause_active"
                    controller = controller_for(self.hass, self.entry_id)
                    if callable(getattr(controller, "_start_cap", None)):
                        return "protection_conflict_unresolved"
                    # Deliberately NOT worker._intent: it has side effects (continuity, override state) and
                    # its refusals are mostly plan quality (stale SOC/prices), which never withholds a start.
                    # The independent gates are: explicit Pause (above), legacy pause, protection, identity,
                    # ownership, person Stop, and these two. Nothing here asserts a retained schedule is effective.
                    if record.get("uncertain") is not False:
                        return "profile_outcome_uncertain"
                    planner = getattr(worker, "_planner", None)
                    if planner is not None and preview_for(self.hass, self.entry_id) is not planner:
                        return "planner_changed"
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
                    if connection == "recovery" and prior.get("connection") != "recovery":
                        return prior.get("state", "blocked"), "already_requested"
                    if prior.get("connection") == connection:
                        attempts = prior.get("attempts", 1)
                        if type(attempts) is not int or not 1 <= attempts <= 2:
                            return "uncertain", "session_record_invalid"
                        if prior.get("state") not in ("rejected", "aborted_before_dispatch") or attempts >= 2:
                            return prior.get("state", "blocked"), "already_requested"
                        if prior.get("state") == "rejected":
                            try:
                                age = (datetime.now(timezone.utc) - datetime.fromisoformat(prior["at"])).total_seconds()
                            except (KeyError, ValueError, TypeError):
                                return "uncertain", "session_record_invalid"
                            if age < 60:
                                return "waiting", "retry_cooldown"
                        # An attempt aborted before dispatch sent nothing: no cooldown, and it is not counted.
                        else:
                            attempts -= 1
                point = morek_schedule._charge_point(self.hass, controller_for(self.hass, self.entry_id).ocpp_target)
                if _request_loggers(point) is None:
                    return "blocked", "unsupported_ocpp_logging_or_interface"
                if not _safe_logging(point):
                    return "blocked", "ocpp_sensitive_logging_enabled"
                attempt = {"version": 1, "connection": connection, "state": "pending",
                           "at": datetime.now(timezone.utc).isoformat(), "attempts": attempts + 1}
                record.pop("session_completed", None)
                record.pop("session_unplugged", None)
                record["session_start"] = attempt
                await ledger.write(record)
                if not await admission.async_owned_boundary_current(self.entry_id, connector):
                    if await ledger.read() == record:
                        attempt["state"] = "aborted_before_dispatch"
                        attempt["attempts"] = max(1, attempts)
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
                    attempt["attempts"] = max(1, attempts)
                    await ledger.write(record)
                    return "blocked", blocker
                self.state = {"state": "starting", "reason": "request_in_progress"}
                result = await _start(point, connector.connector_id)
                attempt["state"] = result
                await ledger.write(record)
                if validate(post=True) is not None:
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
                reason = result.reason
                if reason == "stale_generation" and admission._person_stops.get(connector):
                    reason = "person_stop_active"  # a person Stop in progress is not a transient race
                self.state = {"state": "blocked", "reason": reason}
            if self.state.get("state") == "accepted" and self.state.get("reason") == "request_accepted":
                self._arm_no_transaction(connection)
            self._arm_recheck()
        except asyncio.CancelledError:
            self.state = {"state": "uncertain", "reason": "request_interrupted"}
            raise
        except Exception as error:  # noqa: BLE001 - never print an OCPP exception or payload
            _LOGGER.warning("Morek session start evidence unavailable (%s)", type(error).__name__)
            self.state = {"state": "uncertain", "reason": "session_evidence_unavailable"}
