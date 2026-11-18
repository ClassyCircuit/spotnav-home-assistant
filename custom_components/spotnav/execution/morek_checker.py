"""Stage 15.3: the read-only reconnect/startup schedule check for one Morek entry.

After a link-up or connection change, the existing availability return, a within-process boot-counter rise and HA
startup once the link is up, the checker runs the *existing* read path (`morek_schedule.async_schedule_action(...,
"fetch", check=...)`: `read_only` admission, `GetCompositeSchedule`, `compare_schedule`) against the latest
acknowledged intent (a routine plan, a Pause hold or a Charge Now profile) while it is still inside its coverage.
It has no comparator and no sender of its own and **sends nothing**: no profile, no clear, no start, no setting.

Classes, one per check: `healthy` (fresh clean match), `unknown` (readback unavailable, coverage reasons, link
unproven, uncertain or pending record, clock doubt: nothing sent, says what was not checked) and
`differs_unconfirmed` (one fresh clean `limits_or_transitions_differ`). A mismatch is rechecked at 30, 60, 120 s and
then every 300 s, at most `CHECK_RECHECK_LIMIT` per episode; a link edge, a new attempt or unload ends the episode.
Whether a mismatch is *confirmed* material is decided by `morek_schedule.confirm_mismatch` (Stage 15.4a): two clean
covering mismatches of the same acknowledged attempt on one continuously-up connection, at least 30 s apart, the
latest fresh. A confirmation is only a *request* to the worker (`worker.request_repair`), which owns the single
guarded send path and the feature gate; the checker still sends nothing. There is no periodic readback: a
check starts only from one of the triggers above and a flapping link coalesces to at most one check per
`CHECK_MIN_INTERVAL_S`.

Stage 19.2 late-frame guard: once a replacement of an ambiguous upload exists (the standing `supersession` risk, which an
ACK never clears), more triggers exist, all derived from the durable ledger so a restart loses none: ONE read-only look
shortly after the acknowledged profile's next planned transition; ONE look when a *definitely rejected* reassert becomes
retryable (its persisted `reassert.next_at`); and a bounded follow-up when a look was inconclusive only because a change
was too close (`FOLLOWUP_REASONS`). The watch is armed on every check request (startup, link edges), after every check and
after every accepted/rejected/aborted send; nothing while no such look is due, the link is down, or the risk does not
exist. It is the same check, comparator and confirmation as above; a confirmed mismatch is still only a *request* to the
worker, whose guarded reassert has its own persisted pace, so the retry of a refused reassert needs a fresh confirmed
mismatch and is never a blind resend.

The checker never touches the worker's trigger classes, `last_trigger`, `continuity`, the decision record, the
ledger's acknowledged/uncertain fields or any `verified` field. A read is bound to the connection, the
acknowledged attempt, the owner generation and the request epoch, re-checked after every await; a result that is
no longer current is discarded.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from ..api import morek_schedule
from .command_admission import command_admission, physical_connector

_LOGGER = logging.getLogger(__name__)

CHECK_SETTLE_S: Final = 5  # a just-restored link gets a moment; triggers inside it coalesce into one check
CHECK_MIN_INTERVAL_S: Final = 60  # a flapping link: at most one check start per interval
CHECK_RECHECK_DELAYS: Final = (30, 60, 120, 300)  # the last repeats
CHECK_RECHECK_LIMIT: Final = 12
CHECK_EVENT_HISTORY: Final = 10
POST_REPAIR_DELAY_S: Final = 150  # a repair's own verification reads run at about 30/75/120 s; check after them
POST_REPAIR_WAIT_S: Final = 60  # while that verification is still pending, look again (bounded)
POST_REPAIR_WAIT_LIMIT: Final = 4
#: The comparator calls a readback within `VERIFY_TOLERANCE_S` of any planned change ambiguous, so the look is taken just
#: beyond it (an earlier one could only ever come back `coverage_boundary_ambiguous`).
TRANSITION_SETTLE_S: Final = morek_schedule.VERIFY_TOLERANCE_S + 30
#: A look that came back inconclusive only because a planned change was too near (or a send's own verification was still
#: running) is taken once more shortly after, a bounded number of times, rather than waiting for the next transition.
FOLLOWUP_REASONS: Final = ("coverage_boundary_ambiguous", "verification_pending")
FOLLOWUP_LIMIT: Final = 3
REASSERT_RETRY_SETTLE_S: Final = 1
_DISCARDED: Final = ("check_superseded",)


class MorekScheduleChecker:
    """One bounded, read-only check state machine per Morek entry (memory only)."""

    def __init__(self, hass: Any, entry_id: str, worker: Any, *,
                 monotonic: Callable[[], float] | None = None) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._worker = worker
        self._mono = monotonic or time.monotonic
        self._closed = False
        self._epoch = 0  # bumped by every edge/new attempt/unload: an older read is stale
        self._timer: Callable[[], None] | None = None
        self._recheck_due = False
        self._task: Any = None
        self._rerun = False
        self._last_start: float | None = None
        self._trigger: str | None = None
        self._episode_attempt: str | None = None
        self._observations: list[dict[str, Any]] = []  # clean covering mismatches of this episode (15.4a)
        self._confirmation: dict[str, Any] | None = None  # the token the worker's repair revalidates against
        self._rechecks = 0
        self._post_waits = 0
        self._transition_cancel: Callable[[], None] | None = None
        self._transition_at: str | None = None
        self._transition_why = "transition"
        self._pending_retry_key: tuple[Any, Any] | None = None
        self._transition_task: Any = None
        self._followup_at: datetime | None = None
        self._followups = 0
        self._watch_again = False  # a watch was requested while one was being derived: derive once more
        self._retry_looked: tuple[Any, Any] | None = None  # the refused-reassert pace state a retry look was started for
        self._class: str | None = None
        self._status: dict[str, Any] = {"class": None, "at": None, "readback_at": None, "reason": None}
        self.events: deque[dict[str, Any]] = deque(maxlen=CHECK_EVENT_HISTORY)

    # ---- requests (all synchronous, never raise into the event bus)

    def request(self, trigger: str) -> None:
        """A link-up/connection-change edge, availability return, boot or startup: (re)start one check."""
        if self._closed:
            return
        self._epoch += 1
        self._cancel_timer()
        self._rechecks = 0
        self._episode_attempt = None
        self._forget_observations()
        self._trigger = trigger
        self._post_waits = 0
        self._arm_first()
        self.request_transition_watch()  # startup/a link edge also re-derives the late-frame look from the ledger

    def request_post_repair(self) -> None:
        """Stage 15.4b: a repair was accepted. After its own verification reads, one ordinary read-only check episode
        looks at the repaired attempt; a *confirmed* mismatch of an attempt that is itself a repair escalates to a
        person (the worker/send path decides) instead of repairing again. Nothing here sends."""
        if self._closed:
            return
        self.request("post_repair")
        if self._task is None:
            self._arm(POST_REPAIR_DELAY_S, recheck=False)

    def request_transition_watch(self) -> None:
        """Stage 19.2: (re)arm the one-shot look at the acknowledged profile's next planned transition. Synchronous and
        never raises; the ledger read and the arming happen in one short task. Sends nothing."""
        if self._closed:
            return
        if self._transition_task is not None:
            self._watch_again = True
            return
        try:
            self._transition_task = self._hass.async_create_task(self._arm_transition())
        except Exception:  # noqa: BLE001 - no watch is only a missed extra look, never a send
            self._transition_task = None

    def _cancel_transition(self) -> None:
        if self._transition_cancel is not None:
            self._transition_cancel()
            self._transition_cancel = None
        self._transition_at = None

    async def _arm_transition(self) -> None:
        try:
            record = await morek_schedule.outcomes_for(self._hass).read()
            now = datetime.now(timezone.utc)
            at, why, key = None, "transition", None
            if morek_schedule.reassert_open(record):
                planned = morek_schedule.next_planned_transition(record, now)
                if planned is not None:
                    at = planned + timedelta(seconds=TRANSITION_SETTLE_S)
                key = self._retry_key(record)
                if key is not None and key != self._retry_looked:
                    # a refused reassert: look again once its persisted pace allows (never earlier, never blindly),
                    # once per pace state: a look that could not conclude waits for the next trigger, it never polls
                    due = max(morek_schedule.reassert_next_at(record, now) or now, now)
                    retry = due + timedelta(seconds=REASSERT_RETRY_SETTLE_S)
                    if at is None or retry < at:
                        at, why = retry, "reassert_retry"
                if self._followup_at is not None and (at is None or self._followup_at < at):
                    at, why = self._followup_at, "followup"
            else:
                self._followup_at = None
            if self._closed:
                return
            self._cancel_transition()
            if at is None:
                return
            delay = max(0.0, (at - now).total_seconds())
            self._transition_at = at.isoformat()
            self._transition_why = why
            self._pending_retry_key = key if why == "reassert_retry" else None
            self._transition_cancel = async_call_later(self._hass, delay, self._async_transition_fire)
        except Exception:  # noqa: BLE001 - unreadable evidence: no extra look, the other triggers still apply
            _LOGGER.debug("Morek transition watch not armed", exc_info=True)
        finally:
            self._transition_task = None
            again, self._watch_again = self._watch_again, False
            if again and not self._closed:
                self.request_transition_watch()

    @staticmethod
    def _retry_key(record: Any) -> tuple[Any, Any] | None:
        if not morek_schedule.rejected_reassert_of(record):
            return None
        state = record[morek_schedule.SUPERSESSION_KEY].get("reassert")
        return state.get("attempt_id"), state.get("next_at")

    @callback
    def _async_transition_fire(self, _now: datetime) -> None:
        self._transition_cancel = None
        self._transition_at = None
        why = self._transition_why
        if why == "followup":
            self._followup_at = None
        elif why == "reassert_retry":
            self._retry_looked = self._pending_retry_key
        if not self._closed:
            self.request(why)

    def note_new_attempt(self, repair: str | None = None) -> None:
        """A newer upload attempt exists: the episode and any in-flight read describe a superseded intent.

        The attempt a confirmed repair itself persists (`repair` = the confirmed attempt id) keeps its own
        confirmation token, so the repair can still revalidate it at its final pre-dispatch boundary; any other new
        attempt invalidates it."""
        keep = self._confirmation if repair and self._confirmation and self._confirmation["attempt_id"] == repair else None
        self._cancel_transition()  # it described the superseded profile; the send's outcome re-arms it
        self._end_episode("newer_attempt", "new_attempt", keep=keep)

    def note_link_down(self) -> None:
        """A link-down edge ends the episode; the next link-up edge requests the next check."""
        self._end_episode("link_down", "link_down")

    def _forget_observations(self, keep: dict[str, Any] | None = None) -> None:
        self._observations = []
        self._confirmation = keep

    def _end_episode(self, reason: str, trigger: str, keep: dict[str, Any] | None = None) -> None:
        if self._closed:
            return
        self._epoch += 1
        self._cancel_timer()
        self._rechecks = 0
        self._episode_attempt = None
        self._forget_observations(keep)
        self._rerun = False
        if self._class is not None and not (self._class == morek_schedule.CHECK_UNKNOWN
                                            and self._status.get("reason") == reason):
            self._record(morek_schedule.CHECK_UNKNOWN, reason, None, trigger)

    def close(self) -> None:
        """Unload: cancel the timer and any in-flight read; nothing is sent or cleared."""
        self._closed = True
        self._epoch += 1
        self._cancel_timer()
        self._cancel_transition()
        self._rerun = False
        self._forget_observations()
        self._followup_at = None
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # ---- timers (HA scheduling targets are @callback)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None
        self._recheck_due = False

    def _arm(self, delay: float, *, recheck: bool) -> None:
        self._cancel_timer()
        self._recheck_due = recheck
        self._timer = async_call_later(self._hass, max(0.0, delay), self._async_fire)

    def _arm_first(self) -> None:
        if self._task is not None:
            self._rerun = True  # the read in flight is already stale (epoch bumped); one more run follows it
            return
        wait: float = CHECK_SETTLE_S
        if self._last_start is not None:
            wait = max(wait, CHECK_MIN_INTERVAL_S - (self._mono() - self._last_start))
        self._arm(wait, recheck=False)

    @callback
    def _async_fire(self, _now: datetime) -> None:
        """Timer target. A `@callback`: a plain function would be run by HA as an executor job off the loop."""
        self._timer = None
        recheck, self._recheck_due = self._recheck_due, False
        if self._closed or self._task is not None:
            return
        self._task = self._hass.async_create_task(self._run(recheck))

    # ---- one check

    async def _run(self, recheck: bool) -> None:
        epoch = self._epoch
        self._last_start = self._mono()
        trigger = "recheck" if recheck else (self._trigger or "request")
        binding: tuple[Any, Any] | None = None
        conn = None
        try:
            monitor = getattr(self._worker, "link_monitor", None)
            if monitor is not None and monitor.state == "up":
                conn, binding = monitor.connection_id, self._binding()
            result = await self._check(epoch, recheck, conn, binding)
            read_mono = self._mono()
            if epoch != self._epoch or self._closed:
                pass  # an edge, a new attempt or unload happened during the read: the result is stale, discarded
            elif result is None:
                if recheck:  # superseded without an epoch change (attempt/generation): the episode ends, said so
                    self._episode_attempt = None
                    self._record(morek_schedule.CHECK_UNKNOWN, "superseded", None, trigger)
            elif binding is None or self._is_current(epoch, conn, binding):
                self._apply(result, trigger, conn=conn, read_mono=read_mono)
        except Exception as err:  # noqa: BLE001 - a failed check is Unknown, never a reason to act
            _LOGGER.debug("Morek schedule check failed: %s", type(err).__name__)
            if epoch == self._epoch and not self._closed:
                self._apply({"class": morek_schedule.CHECK_UNKNOWN, "reason": "check_failed", "readback_at": None},
                            trigger)
        finally:
            self._task = None
            if not self._closed:
                self.request_transition_watch()  # a no-op unless the late-frame risk is open
            if self._rerun and not self._closed:
                self._rerun = False
                self._arm_first()

    async def _check(self, epoch: int, recheck: bool, conn: Any, binding: tuple[Any, Any] | None) -> dict[str, Any] | None:
        worker = self._worker
        if binding is None:
            return {"class": morek_schedule.CHECK_UNKNOWN, "reason": "link_unproven", "readback_at": None}
        if worker._suspended or not worker._available():
            return {"class": morek_schedule.CHECK_UNKNOWN, "reason": "charger_unavailable", "readback_at": None}
        try:
            value = await morek_schedule.async_schedule_action(
                self._hass, self._entry_id, "fetch",
                check={"current": lambda: self._is_current(epoch, conn, binding),
                       "attempt_id": self._episode_attempt if recheck else None})
        except morek_schedule.ScheduleRefused as err:
            if err.code in _DISCARDED:
                return None
            return {"class": morek_schedule.CHECK_UNKNOWN, "reason": err.code, "readback_at": None}
        return dict(value["check"])

    def _binding(self) -> tuple[Any, Any] | None:
        """The physical connector and its owner generation this check is bound to."""
        try:
            connector = physical_connector(self._worker._identity())
            if connector is None:
                return None
            return connector, command_admission(self._hass).generation(connector)
        except Exception:  # noqa: BLE001 - no binding, no check
            return None

    def _is_current(self, epoch: int, conn: Any, binding: tuple[Any, Any] | None) -> bool:
        if self._closed or epoch != self._epoch or binding is None:
            return False
        worker = self._worker
        try:
            if worker._closed or worker._suspended or not worker._available():
                return False
            monitor = getattr(worker, "link_monitor", None)
            if monitor is None or monitor.state != "up" or monitor.connection_id != conn:
                return False
            connector, generation = binding
            admission = command_admission(self._hass)
            return (physical_connector(worker._identity()) == connector
                    and admission.generation(connector) == generation and not admission._person_stops.get(connector))
        except Exception:  # noqa: BLE001
            return False

    # ---- result

    def repair_current(self, token: dict[str, Any]) -> bool:
        """The worker's pre-dispatch revalidation of a confirmation: still the live token, link up, same connection."""
        monitor = getattr(self._worker, "link_monitor", None)
        if not (not self._closed and token is self._confirmation and monitor is not None
                and monitor.state == "up" and monitor.connection_id == token["connection_id"]):
            return False
        # Stage 15.4b: the latest readback must STILL be fresh now, on the wall and the monotonic clock, at every
        # boundary up to the wire call; storage/lock waits never carry an old read forward (only a newer check can).
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(token["readback_at"])).total_seconds()
            mono_age = self._mono() - token["mono"]
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= age <= morek_schedule.REPAIR_FRESH_S and 0 <= mono_age <= morek_schedule.REPAIR_FRESH_S

    def _confirm(self, result: dict[str, Any], conn: Any, read_mono: float | None) -> bool:
        """Record this clean covering mismatch; True when it, with an earlier one, confirms the mismatch."""
        attempt_id, readback_at = result.get("attempt_id"), result.get("readback_at")
        if conn is None or read_mono is None or not attempt_id or not readback_at:
            self._observations = []
            return False
        observation = {"attempt_id": attempt_id, "connection_id": conn, "readback_at": readback_at, "mono": read_mono}
        self._observations = [o for o in self._observations
                              if o["attempt_id"] == attempt_id and o["connection_id"] == conn][-3:]
        confirmed = morek_schedule.confirm_mismatch(
            self._observations, {**observation, "mono_age": self._mono() - read_mono})
        self._observations.append(observation)
        return confirmed

    def _apply(self, result: dict[str, Any], trigger: str, *, conn: Any = None, read_mono: float | None = None) -> None:
        state, reason = result["class"], result.get("reason")
        recheck = trigger == "recheck"
        if recheck:
            self._rechecks += 1
        if state == morek_schedule.CHECK_DIFFERS:
            if self._episode_attempt is None:
                self._episode_attempt = result.get("attempt_id")
            confirmed = self._confirm(result, conn, read_mono)
            if confirmed:
                state = morek_schedule.CHECK_CONFIRMED
            self._record(state, reason, result.get("readback_at"), trigger)
            self._followups, self._followup_at = 0, None  # a conclusive look
            if confirmed:
                # `mono` = the monotonic instant of the readback itself (the read finished `lag` wall seconds later)
                lag = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(result["readback_at"])).total_seconds())
                self._confirmation = {"attempt_id": result["attempt_id"], "connection_id": conn,
                                      "readback_at": result["readback_at"], "mono": self._mono() - lag,
                                      "facts": result.get("facts")}
                token = self._confirmation
                try:
                    self._worker.request_repair({**token, "current": lambda: self.repair_current(token)})
                except Exception:  # noqa: BLE001 - a failed request is a finding that stays recorded, never a send
                    _LOGGER.debug("Morek repair request failed", exc_info=True)
            if self._rechecks < CHECK_RECHECK_LIMIT:
                delay = CHECK_RECHECK_DELAYS[min(self._rechecks, len(CHECK_RECHECK_DELAYS) - 1)]
                self._arm(delay, recheck=True)
            return
        self._episode_attempt = None  # healthy or unknown ends the episode
        self._forget_observations()
        self._record(state, reason, result.get("readback_at"), trigger)
        self._note_followup(state, reason, trigger)
        if (state == morek_schedule.CHECK_UNKNOWN and reason == "verification_pending" and self._trigger == "post_repair"
                and self._post_waits < POST_REPAIR_WAIT_LIMIT):
            self._post_waits += 1
            self._arm(POST_REPAIR_WAIT_S, recheck=False)

    def _note_followup(self, state: str, reason: Any, trigger: str) -> None:
        """A look that could not be conclusive only because a planned change was too near (or a send's verification was
        running) is repeated shortly after, at most `FOLLOWUP_LIMIT` times in a row, so a closely spaced transition is
        never silently skipped. A conclusive result or any other kind of look restarts the count. Only a wake-up is
        armed (memory); `_arm_transition` lets the ledger decide whether the late-frame risk is open at all."""
        if state != morek_schedule.CHECK_UNKNOWN:
            self._followups, self._followup_at = 0, None
            return
        if reason not in FOLLOWUP_REASONS or self._trigger == "post_repair":
            return
        self._followups = self._followups + 1 if trigger == "followup" else 0
        self._followup_at = (None if self._followups >= FOLLOWUP_LIMIT
                             else datetime.now(timezone.utc) + timedelta(seconds=TRANSITION_SETTLE_S))

    def _record(self, state: str, reason: Any, readback_at: Any, trigger: str) -> None:
        """Status always updates; one event and one INFO line per *changed* class, a repeat only counts."""
        at = datetime.now(timezone.utc).isoformat()
        self._status = {"class": state, "at": at, "readback_at": readback_at, "reason": reason}
        if state == self._class and self.events:
            self.events[-1]["repeat"] += 1
            self.events[-1]["last_at"] = at
            return
        self._class = state
        self.events.append({"at": at, "last_at": at, "trigger": trigger, "class": state, "reason": reason,
                            "readback_at": readback_at, "repeat": 0})
        try:
            _LOGGER.info("Morek schedule check: trigger=%s class=%s reason=%s rechecks=%s (read-only; nothing sent)",
                         trigger, state, reason, self._rechecks)
        except Exception:  # noqa: BLE001
            pass

    def status(self) -> dict[str, Any]:
        """Additive `reconciliation.check`: codes and times only, no raw frames, profile data or private details."""
        return {**self._status, "rechecks": self._rechecks, "next_transition_check_at": self._transition_at,
                "events": [dict(event) for event in self.events]}
