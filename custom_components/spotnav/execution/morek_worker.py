"""Event-driven Morek intent reconciliation.

Admission is the final physical-connector lock. No controller or assignment
lock is taken inside it. The shared outcome ledger is not an ownership
transition; production admission requires completed ownership and a current ticket.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from ..api import morek_schedule
from ..runtime import controller_for, domain_data, preview_for
from .command_admission import classify_morek_identity, command_admission, physical_connector

_LOGGER = logging.getLogger(__name__)
_COALESCE_SECONDS = 0.1  # explicit controls, plug-in, settings: do not wait
_ROUTINE_COALESCE_SECONDS = 2.0  # routine SOC/price bursts
_SOC_END_TOLERANCE = timedelta(minutes=5)  # SOC-only: an end instant that moves less is not news
_TRIGGER_RANK = ("plug_in", "sync", "settings", "control", "repair", "sensor", "recovery", "recalc", "price", "routine")
_SETTLED = ("upload_accepted_unverified", "unchanged")  # outcomes that end a pending price decision
_DECISION_HISTORY = 10
_DECISION_REPAIR_SENT = ("upload_accepted_unverified", "upload_rejected", "upload_uncertain")
_DECISION_REPAIR_WAITING = ("repair_deferred",)
_SOC_CAUSE = "soc"  # the only planner cause that is routine and may use the SOC tolerance


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
        self.reason_serial = -1
        self.resume_ticket = None
        self.hold_ticket = None
        self._expiry = None
        self.override_degraded = None
        self._baseline: dict[str, Any] | None = None  # reserve-free twin of the profile `_intent` last built
        self._sync_serial = None
        self.continuity: dict[str, Any] | None = None
        self._continuity_timer = None
        self._retry_timer = None
        # Stage 9.5: bounded timer re-evaluation of a transient blocker (memory only; events still re-evaluate).
        self._blocker_timer = None
        self._blocker_runs = 0
        self.blocker_retry: dict[str, Any] | None = None
        self.resume_interrupted: str | None = None  # a Resume id a person Stop pre-empted in this process
        self._continuity_end: datetime | None = None
        self._deadline: float | None = None
        self._wake = asyncio.Event()
        self._strict = False  # sticky until a run completes: no SOC tolerance for this run
        self._kinds: set[str] = set()
        # A price publication that may still deserve an interruption decision. It survives stale work,
        # a refused or rejected send, an unavailable charger and a reconnect (a direct trigger re-evaluates it
        # against fresh data); it ends once a run decided it or the schedule was accepted/unchanged.
        self._price_pending = False
        self._price_evaluated = False
        self._seen: tuple[Any, Any] | None = None
        self.last_trigger: str | None = None
        self._evidence: set[str] = set()
        self._evidence_task: asyncio.Task | None = None
        # Stage 14.6: the last finished run's decision and a few before it (memory only, bounded; the durable
        # record is the outcome ledger and the history is SpotNav's own log buffer).
        self.decision: dict[str, Any] | None = None
        self.decisions: deque[dict[str, Any]] = deque(maxlen=_DECISION_HISTORY)
        self._decision_key: tuple[Any, ...] | None = None
        # Per-run evidence so a decision never reports an earlier run's continuity, dispatch or attempt.
        self._continuity_fresh = False
        self._dispatch_before: str | None = None
        self._run_attempt_id: str | None = None
        # Stage 15.4a: the checker's confirmed-mismatch request and the status of the last one. The request is
        # consumed by the run it triggers; `repairing` is true only inside that run (the intent it builds is the
        # *current* guarded one, but never carries a price or cap trigger, so a repair cannot release a window).
        self._repair_request: dict[str, Any] | None = None
        self._repair_run: dict[str, Any] | None = None
        self.repair_confirmed: dict[str, Any] | None = None

    def _dispatched_id(self) -> str | None:
        return self._hass.data.get("spotnav_morek_dispatched", {}).get(self._entry_id)

    def start(self) -> None:
        """The listener delivers the current snapshot immediately, including on startup."""
        self._remove = self._planner.add_publication_listener(self.trigger)

    def trigger(self, snapshot: Any = None, *, sync: bool = False, kind: str | None = None) -> None:
        """Request reconciliation.

        A planner publication is routine only when its settings and prices are unchanged AND the planner
        names the cause as an SOC reading (`publication_cause == "soc"`); only a routine run may use the SOC
        end-time tolerance. Any other same-revision publication (deadline rollover, plan watch, unread
        notice, execution change, a caller that did not say) is a "recalc": strict, coalesced like a routine
        one. A run that mixes causes is strict. A direct call (control, plug-in, sensor, recovery sync)
        never waits; a settings edit does not wait either; a price change coalesces like a routine one but
        gets no tolerance.
        """
        if self._closed:
            return
        routine, urgent = False, True
        if snapshot is not None:
            key = (getattr(snapshot, "settings_revision", None), getattr(snapshot, "price_revision", None))
            previous, self._seen = self._seen, key
            same = previous == key
            cause = getattr(self._planner, "publication_cause", None)
            routine = same and cause == _SOC_CAUSE
            settings_changed = previous is None or previous[0] != key[0]
            urgent = settings_changed
            kind = kind or ("routine" if routine else "settings" if settings_changed
                            else "recalc" if same else "price")
        kind = kind or "control"
        self._kinds.add(kind)
        if kind == "price":
            self._price_pending = True
        if not routine or sync:
            self._strict = True
        wait = _COALESCE_SECONDS if urgent or sync else _ROUTINE_COALESCE_SECONDS
        due = asyncio.get_running_loop().time() + wait
        if self._deadline is None or due < self._deadline:
            self._deadline = due
            self._wake.set()
        session = getattr(self, "session", None)
        if session is not None:
            session.trigger()
        self._serial += 1
        if sync:
            self._sync_serial = self._serial
        if self._task is None or self._task.done():
            self._task = self._hass.async_create_task(self._run())

    def request_repair(self, confirmation: dict[str, Any]) -> None:
        """Stage 15.4a: the checker confirmed a material mismatch of the acknowledged intent.

        `confirmation` is `{attempt_id, connection_id, readback_at, current}` (`current()` re-asserts the
        confirmation: same token, link up, same connection). With the gate off (`REPAIR_DISPATCH_ENABLED`, until
        15.4b) this only records the finding: no run is raised, so nothing at all is sent. With it on, a strict
        `repair` run goes through the one guarded path (`_reconcile` -> `_send_profile_shared`); every existing
        guard, the repair budget and the pre-dispatch revalidation still apply."""
        if self._closed:
            return
        now = datetime.now(timezone.utc).isoformat()
        info = {"attempt_id": confirmation.get("attempt_id"), "at": now, "readback_at": confirmation.get("readback_at"),
                "state": "confirmed", "result": None}
        if not morek_schedule.REPAIR_DISPATCH_ENABLED:
            info["state"], info["result"] = "gated", "repair_gated"
            self.repair_confirmed = info
            self._record_decision({"repair"}, reason="repair_gated", trigger="repair")
            return
        self.repair_confirmed = info
        self._repair_request = confirmation
        self.trigger(kind="repair")

    def note_plug_in(self) -> None:
        """A vehicle was reliably seen going from Available to connected: always recalculate, then compare.

        The comparison may decide not to send (equal schedule); it is never skipped.
        """
        self._note_evidence("plug_in")

    def note_sensor(self) -> None:
        """The connector sensor went to or came back from unknown/unavailable: recalculate and compare.

        This does not identify a plug-in. Unavailable inputs are the planner's and the reconcile guards'
        to judge: nothing is sent while the charger is unavailable or the plan is blocked.
        """
        self._note_evidence("sensor")

    def _note_evidence(self, kind: str) -> None:
        if self._closed:
            return
        self._evidence.add(kind)
        if self._evidence_task is None or self._evidence_task.done():
            self._evidence_task = self._hass.async_create_task(self._evidence_run())

    async def _evidence_run(self) -> None:
        """One recalculation at a time; evidence noted meanwhile gets another round, never a lost one."""
        try:
            while self._evidence and not self._closed:
                kinds, self._evidence = self._evidence, set()
                kind = "plug_in" if "plug_in" in kinds else "sensor"
                try:
                    await self._planner.async_recalculate(kind)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - compare with what the planner has rather than skip
                    _LOGGER.debug("Recalculation after %s evidence failed", kind, exc_info=True)
                self.trigger(kind=kind)
        finally:
            self._evidence_task = None

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
            session = getattr(self, "session", None)
            if session is not None:
                session.reconnect()
            checker = getattr(self, "checker", None)
            if checker is not None:
                checker.request("availability_return")  # additional, read-only; never replaces the trigger above

    def close(self) -> None:
        """Unsubscribe and cancel pending work; an in-flight send remains uncertain."""
        self._closed = True
        checker = getattr(self, "checker", None)
        if checker is not None:
            checker.close()
        self._evidence.clear()
        if self._evidence_task is not None:
            self._evidence_task.cancel()
        morek_schedule._cancel_verification(self._hass, self._entry_id)
        self._serial += 1
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if self._continuity_timer is not None:
            self._continuity_timer.cancel()
            self._continuity_timer = None
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        if self._blocker_timer is not None:
            self._blocker_timer.cancel()
            self._blocker_timer = None
        if self._remove is not None:
            self._remove()
            self._remove = None
        if self._task is not None:
            self._task.cancel()

    def _identity(self) -> dict[str, Any]:
        controller = controller_for(self._hass, self._entry_id)
        return morek_schedule._identity_status(self._hass, getattr(controller, "ocpp_target", None))

    def _continued_profile(self, record: dict[str, Any] | None, settings: Any, now: datetime) -> dict[str, Any] | None:
        """The acknowledged routine profile whose currently allowed window must be preserved.

        Pause, Stop, Charge Now and protection never reach here. Evidence is only the
        connector status (not measured power): a fresh unplugged vehicle releases the
        window, while charging, waiting and unknown all keep it, so unknown state never
        causes an automatic interruption. Only a planning edit (cap rule) or a price event (savings rule) may
        release it, through `morek_schedule.window_release` (Stage 14.4); anything uncertain keeps it.
        """
        self.continuity = None
        self._continuity_end = None
        self._continuity_fresh = True  # this run evaluated continuity (a later early exit is not this)
        profile = morek_schedule.acknowledged_profile(record)
        active = morek_schedule.active_window(profile, now)
        if active is None or active[1] != settings.amps:
            return None
        evidence = morek_schedule.connector_evidence(
            self._hass, controller_for(self._hass, self._entry_id), now)
        until = active[0].isoformat()
        if evidence == "unplugged":
            self.continuity = {"evidence": evidence, "preserved": False, "until": until,
                               "reason": "vehicle_unplugged"}
            return None
        lowered = morek_schedule.cap_lowered(record, settings) and self._repair_run is None
        price_event = self._price_pending and not lowered and self._repair_run is None
        release, reason = morek_schedule.window_release(
            self._planner.snapshot(), settings, now, profile, cap_lowered=lowered,
            price_event=price_event, evidence=evidence,
            active_baseline=morek_schedule.acknowledged_baseline(record))
        self._price_evaluated = price_event and not release
        if release:
            self.continuity = {"evidence": evidence, "preserved": False, "until": until, "reason": reason}
            return None
        self._continuity_end = active[0]
        self.continuity = {"evidence": evidence, "preserved": True, "until": until,
                           "reason": "active_window_state_unknown" if evidence == "unknown" else reason}
        return profile

    async def _arm_retry_timer(self, data: dict[str, Any]) -> None:
        """After a definite rejection, one bounded later attempt (`morek_schedule.rejection_retry_at`).

        Re-evaluates the newest plan through the normal guarded path; it never retries an uncertain write and
        never clears a profile. Cancelled by any later run that no longer ends in a rejection."""
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None
        if self._closed:
            return
        try:
            record = await morek_schedule._outcome_record(self._hass, self._entry_id, data)
        except Exception:  # noqa: BLE001 - no evidence, no retry
            return
        at = morek_schedule.rejection_retry_at(record)
        if at is None:
            return
        delay = (at - datetime.now(timezone.utc)).total_seconds() + 1
        if delay <= 1:
            return  # already due: this very run is the retry; never a tight re-arm loop
        self._retry_timer = asyncio.get_running_loop().call_later(delay, lambda: self.trigger(kind="recovery"))

    def _arm_blocker_timer(self, kinds: set[str]) -> None:
        """A transient blocker (reconnect, prices, fresh reading, a finished Stop) usually ends with an event.
        Where none arrives, re-evaluate after a bounded backoff (`morek_schedule.blocker_retry_delay`).

        This only re-runs the guarded read-and-compare path: an uncertain write, a person pause, an ownership or
        protection conflict and a rejection (its own cooldown) are never in the transient set, and a
        send still passes every admission check. Counting continues across other triggers; only a run that
        is no longer blocked that way resets it."""
        if self._blocker_timer is not None:
            self._blocker_timer.cancel()
            self._blocker_timer = None
        if self._closed or self.reason not in morek_schedule.TRANSIENT_BLOCKERS:
            self._blocker_runs = 0
            self.blocker_retry = None
            return
        if "recovery" in kinds:
            self._blocker_runs += 1
        delay = morek_schedule.blocker_retry_delay(self._blocker_runs)
        state: dict[str, Any] = {"code": self.reason, "attempts": self._blocker_runs,
                                 "limit": morek_schedule.BLOCKER_RETRY_LIMIT, "next_retry_at": None,
                                 "exhausted": delay is None}
        self.blocker_retry = state
        if delay is None:
            return
        state["next_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        self._blocker_timer = asyncio.get_running_loop().call_later(delay, lambda: self.trigger(kind="recovery"))

    def _arm_continuity_timer(self) -> None:
        """Replan again just after a preserved window ends; planner events may not."""
        if self._continuity_timer is not None:
            self._continuity_timer.cancel()
            self._continuity_timer = None
        if self._closed or not self.continuity or not self.continuity.get("preserved") or self._continuity_end is None:
            return
        delay = (self._continuity_end - datetime.now(timezone.utc)).total_seconds() + 1
        if delay > 0:
            self._continuity_timer = asyncio.get_running_loop().call_later(delay, self.trigger)

    def _intent(self, pause: dict[str, Any] | None = None, override: dict[str, Any] | None = None,
                record: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        settings = domain_data(self._hass).auto_store.settings(self._entry_id)
        self._baseline = None
        if pause is not None and pause["type"] == "pause_until_resumed":
            self.continuity = self._continuity_end = None
            profile = morek_schedule.held_off_profile(datetime.now(timezone.utc))
            return profile, morek_schedule._preview_id(profile, [settings.revision, pause["id"]])
        if preview_for(self._hass, self._entry_id) is not self._planner:
            raise morek_schedule.ScheduleRefused("planner_changed")
        now = datetime.now(timezone.utc)
        if override is not None and datetime.fromisoformat(override["end"]) > now:
            self.continuity = self._continuity_end = None
            if settings.amps != 16:
                raise morek_schedule.ScheduleRefused("current_must_be_16")
            auto = ()
            self.override_degraded = None
            try:
                morek_schedule._proposed_profile(self._hass, self._entry_id, now)
                blocker = self._planner.morek_plan_blocker(self._planner.snapshot(), now)
                if blocker:
                    raise morek_schedule.ScheduleRefused(blocker)
                auto = tuple(self._planner.snapshot().proposal.shown_periods)
            except morek_schedule.ScheduleRefused as error:
                if error.code in ("too_many_blocks", "invalid_plan"):
                    raise
                self.override_degraded = error.code
            profile = morek_schedule.charge_now_profile(datetime.fromisoformat(override["start"]),
                datetime.fromisoformat(override["end"]), auto, settings.amps, now)
            return profile, morek_schedule._preview_id(profile, [settings.revision, override["id"]])
        self.override_degraded = None
        now = datetime.now(timezone.utc)
        continued = None if pause is not None else self._continued_profile(record, settings, now)
        profile = morek_schedule._proposed_profile(self._hass, self._entry_id, now, active_profile=continued)
        # The reserve-free twin (Stage 15.1a) judges SOC-only drift on the need alone; None when there is no reserve.
        self._baseline = morek_schedule._proposed_baseline(
            self._hass, self._entry_id, now, active_profile=continued,
            active_baseline=morek_schedule.acknowledged_baseline(record))
        blocker = self._planner.morek_plan_blocker(self._planner.snapshot(), datetime.now(timezone.utc))
        if blocker is not None:
            raise morek_schedule.ScheduleRefused(blocker)
        return profile, morek_schedule._preview_id(profile, [settings.revision, pause["id"]] if pause is not None else settings.revision)

    async def _wait_for_burst(self) -> None:
        """Sleep to the earliest requested deadline; an urgent trigger shortens it, a routine one never extends."""
        loop = asyncio.get_running_loop()
        await asyncio.sleep(0)
        while not self._closed:
            remaining = (self._deadline or 0) - loop.time()
            if remaining <= 0:
                break
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), remaining)
            except TimeoutError:
                pass
        self._deadline = None

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self._wait_for_burst()
                serial = self._serial
                kinds = set(self._kinds)
                self._price_evaluated = False
                self._continuity_fresh = False
                self._run_attempt_id = None
                self._dispatch_before = self._dispatched_id()
                repair_asked = self._repair_request if "repair" in kinds else None
                self._repair_run = repair_asked if morek_schedule.REPAIR_DISPATCH_ENABLED else None
                try:
                    await self._reconcile(serial, None if self._strict else _SOC_END_TOLERANCE)
                except morek_schedule.ScheduleRefused as error:
                    self.reason = error.code
                except Exception:  # noqa: BLE001 - a failed calculation is not permission to send
                    self.reason = "worker_unavailable"
                    _LOGGER.exception("Morek schedule worker failed")
                repaired, self._repair_run = self._repair_run, None
                if serial == self._serial:
                    if repaired is not None and self.repair_confirmed is not None:
                        self.repair_confirmed.update(
                            state="sent" if self.reason in _DECISION_REPAIR_SENT
                            else "deferred" if self.reason in _DECISION_REPAIR_WAITING else "refused", result=self.reason)
                        checker = getattr(self, "checker", None)
                        if self.reason == "upload_accepted_unverified" and checker is not None:
                            checker.request_post_repair()  # one later read-only look at the repaired attempt
                    if repair_asked is not None:
                        self._repair_request = None
                    # a repair carries no price decision: its acceptance must not end a pending one
                    if self._price_pending and (self._price_evaluated or (self.reason in _SETTLED and repaired is None)):
                        self._price_pending = False
                    self.reason_serial = serial
                    self._strict = False
                    self._kinds -= kinds
                    self.last_trigger = next((k for k in _TRIGGER_RANK if k in kinds), None)
                    self._record_decision(kinds)
                    self._arm_blocker_timer(kinds)
                    return
        finally:
            self._task = None

    def _record_decision(self, kinds: set[str], *, reason: str | None = None, trigger: str | None = None) -> None:
        """Describe the finished run: trigger, input/state freshness, changed or not, preserved or interrupted,
        sent or skipped and the result. A repeat of the same decision only counts (no new log line), so a burst of
        sensor updates while charging stays one line. Never raises: diagnostics must not affect charging."""
        try:
            now = datetime.now(timezone.utc)
            controller = controller_for(self._hass, self._entry_id)
            event = morek_schedule.decision_event(
                now=now, kinds=kinds, last_trigger=trigger or self.last_trigger, reason=reason or self.reason,
                inputs=morek_schedule._planning_inputs(self._hass, self._entry_id),
                evidence=morek_schedule.connector_evidence(self._hass, controller, now),
                continuity=self.continuity if self._continuity_fresh and reason is None else None,
                dispatched=False if reason else self._dispatched_id() not in (None, self._dispatch_before),
                attempt_id=None if reason else self._run_attempt_id)
            key = (event["action"], event["result"], event["evidence"], event["changed"], event["attempt_id"],
                   None if event["continuity"] is None else tuple(event["continuity"].values()),
                   event["inputs"].get("plan_state"), event["inputs"].get("uncertain"))
            if key == self._decision_key and self.decision is not None:
                self.decision["repeat"] += 1
                self.decision["last_at"] = event["at"]
                self.decision["triggers"] = sorted(set(self.decision["triggers"]) | set(event["triggers"]))[:9]
                return
            self._decision_key = key
            self.decision = event
            self.decisions.append(event)
            inputs, cont = event["inputs"], event["continuity"] or {}
            level = (logging.WARNING if event["result"] in ("upload_rejected", "upload_uncertain", "worker_unavailable")
                     and event["action"] != "held" else logging.INFO)
            _LOGGER.log(
                level,
                "Morek schedule decision: trigger=%s action=%s result=%s changed=%s evidence=%s preserved=%s "
                "reason=%s soc_source=%s soc_age_s=%s plan=%s/%s ack=%s (not measured charging)",
                event["trigger"], event["action"], event["result"], event["changed"], event["evidence"],
                cont.get("preserved"), cont.get("reason"), inputs.get("soc_source"), inputs.get("soc_age_s"),
                inputs.get("plan_state"), inputs.get("plan_reason"), event["stages"]["ack"])
        except Exception:  # noqa: BLE001 - never let a diagnostic change the outcome
            _LOGGER.debug("Morek decision evidence unavailable", exc_info=True)

    async def _reconcile(self, serial: int, end_tolerance: timedelta | None = None) -> None:
        # Restore the fixed expiry even when the charger is offline.
        data, store = await morek_schedule._state(self._hass, self._entry_id)
        record = await morek_schedule._outcome_record(self._hass, self._entry_id, data)
        override = record.get("charge_now")
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if override is not None:
            delay = (datetime.fromisoformat(override["end"]) - datetime.now(timezone.utc)).total_seconds()
            if delay > 0:
                self._expiry = asyncio.get_running_loop().call_later(delay, self.trigger)
        # After a restart the durable rejection record alone re-arms the bounded retry, whatever this run does.
        await self._arm_retry_timer(data)
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

        repair = self._repair_run
        post_repair = False  # the confirmed attempt is itself a repair: the send path escalates instead of deferring

        def repair_deferral() -> None:
            """15.4b, at every validation up to the wire: a correct charge with only a distant future difference
            waits. Flow is read fresh each time; the readback's age comes from the confirmation token."""
            if repair is None or post_repair:
                return
            try:
                flow = morek_schedule.measured_flow(morek_schedule._live_measurements(
                    self._hass, controller_for(self._hass, self._entry_id), datetime.now(timezone.utc)))
                elapsed = morek_schedule.readback_age_s(repair["readback_at"])
            except Exception:  # noqa: BLE001 - unreadable evidence is unknown flow / unknown age: never permission
                flow, elapsed = "unknown", 0.0
            why = morek_schedule.repair_deferral(repair.get("facts"), flow, elapsed)
            if why is not None:
                if self.repair_confirmed is not None:
                    self.repair_confirmed["defer_reason"] = why
                raise morek_schedule.ScheduleRefused("repair_deferred")

        async def dispatch() -> tuple[str, str | None, str | None]:
            nonlocal post_repair
            # Admission has checked identity, ownership and generation under the
            # physical connector lock. Do not await between this recheck and call.
            if self._closed or serial != self._serial:
                return "stale_work", None, None
            pause: dict[str, Any] | None = None
            fingerprint = ""
            def active_override():
                override = record.get("charge_now")
                return bool(override and datetime.fromisoformat(override["end"]) > datetime.now(timezone.utc))
            def validate():
                if self._closed or serial != self._serial:
                    raise morek_schedule.ScheduleRefused("stale_work")
                if generation != admission.generation(connector) or admission._person_stops.get(connector):
                    raise morek_schedule.ScheduleRefused("stale_generation")
                if not admission.owned_ticket_current(self._entry_id, connector):
                    raise morek_schedule.ScheduleRefused("migration_confirmation_required")
                if self._suspended or not self._available():
                    raise morek_schedule.ScheduleRefused("charger_unavailable")
                if repair is not None and not repair["current"]():
                    raise morek_schedule.ScheduleRefused("repair_unconfirmed")  # reconnect / new attempt / unload / stale read
                repair_deferral()
                identity_now = self._identity()
                if classify_morek_identity(identity_now) != "supported_morek" or physical_connector(identity_now) != connector:
                    raise morek_schedule.ScheduleRefused("identity_changed")
                profile, current = self._intent(pause, record.get("charge_now"), record)
                if current != fingerprint:
                    self.trigger()
                    raise morek_schedule.ScheduleRefused("stale_work")
                controller = controller_for(self._hass, self._entry_id)
                if (record.get("clean_start") or active_override()) and callable(getattr(controller, "_start_cap", None)):
                    raise morek_schedule.ScheduleRefused("protection_conflict_unresolved")
                settings = domain_data(self._hass).auto_store.settings(self._entry_id)
                if (record.get("clean_start") and pause is not None and pause.get("type") == "resume_requested"
                        and getattr(getattr(settings, "pause", None), "admitted", False)):
                    raise morek_schedule.ScheduleRefused("legacy_pause_active")
                target = getattr(controller, "ocpp_target", None)
                return profile, morek_schedule._charge_point(self._hass, target), target

            async with self._hass.data[morek_schedule._DATA_KEY][self._entry_id][2]:
                record = await morek_schedule._outcome_record(self._hass, self._entry_id, data)
                post_repair = repair is not None and (repair["attempt_id"] in morek_schedule.repaired_ids(record)
                                                       or morek_schedule.repair_escalated(record, repair["attempt_id"]))
                pause = record.get("schedule_pause")
                sync = self._sync_serial == serial
                if sync and pause is not None and pause.get("type") == "pause_until_resumed":
                    return "paused_until_resume", None, None
                if sync and active_override():
                    return "charge_now_active", None, None
                if (record.get("clean_start") or active_override()) and callable(getattr(controller_for(self._hass, self._entry_id), "_start_cap", None)):
                    return "protection_conflict_unresolved", None, None
                if (record.get("clean_start") and record.get("attempt") is None and pause
                        and pause.get("type") == "pause_until_resumed"
                        and self.hold_ticket != (pause.get("id"), generation)):
                    return "paused_until_resume", None, None
                if pause is not None and pause["type"] == "resume_requested" and not morek_schedule._resume_authorized(record, self, generation):
                    return "resume_requires_confirmation", None, None
                if pause is not None and pause["type"] == "resume_requested":
                    # Carry recovered authority across the next write's pending record;
                    # connector generation and person-Stop checks still invalidate it.
                    self.resume_ticket = (pause["id"], generation)
                _, fingerprint = self._intent(pause, record.get("charge_now"), record)
                ticket = admission._completion_tickets.get(self._entry_id)
                outcome = await morek_schedule._send_profile_shared(
                    self._hass, self._entry_id, data, store, fingerprint, validate, automatic=True,
                    pause_id=None if pause is None else pause["id"],
                    override_id=(record.get("charge_now") or {}).get("id") if record.get("charge_now")
                        and datetime.fromisoformat(record["charge_now"]["end"]) > datetime.now(timezone.utc) else None,
                    force_sync=sync, end_tolerance=end_tolerance, baseline=lambda: self._baseline,
                    repair=None if repair is None else repair["attempt_id"],
                    validate_durable=lambda: admission.async_owned_boundary_current(self._entry_id, connector),
                    migration_id=None if ticket is None else ticket[1])
                return outcome, data.get("sent_at"), data.get("attempt_id")

        result = await admission.async_execute(
            self._entry_id, "owned_profile", self._identity, dispatch, expected_generation=generation
        )
        if self._closed:
            return
        self._arm_continuity_timer()
        if not result.allowed:
            self.reason = result.reason
            return
        outcome, sent_at, attempt_id = result.value
        self.reason = outcome
        self._run_attempt_id = attempt_id
        if outcome == "upload_rejected":
            await self._arm_retry_timer(data)
        elif self._retry_timer is not None and outcome != "upload_uncertain":
            self._retry_timer.cancel()
            self._retry_timer = None
        if (outcome == "upload_accepted_unverified" and sent_at and attempt_id
                and not self._closed):
            # Admission has been released. The read-only path reacquires it itself.
            morek_schedule._schedule_verification(self._hass, self._entry_id, sent_at, -1, attempt_id)
