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
from datetime import datetime, timezone
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

    def request_post_repair(self) -> None:
        """Stage 15.4b: a repair was accepted. After its own verification reads, one ordinary read-only check episode
        looks at the repaired attempt; a *confirmed* mismatch of an attempt that is itself a repair escalates to a
        person (the worker/send path decides) instead of repairing again. Nothing here sends."""
        if self._closed:
            return
        self.request("post_repair")
        if self._task is None:
            self._arm(POST_REPAIR_DELAY_S, recheck=False)

    def note_new_attempt(self, repair: str | None = None) -> None:
        """A newer upload attempt exists: the episode and any in-flight read describe a superseded intent.

        The attempt a confirmed repair itself persists (`repair` = the confirmed attempt id) keeps its own
        confirmation token, so the repair can still revalidate it at its final pre-dispatch boundary; any other new
        attempt invalidates it."""
        keep = self._confirmation if repair and self._confirmation and self._confirmation["attempt_id"] == repair else None
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
        self._rerun = False
        self._forget_observations()
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
        if (state == morek_schedule.CHECK_UNKNOWN and reason == "verification_pending" and self._trigger == "post_repair"
                and self._post_waits < POST_REPAIR_WAIT_LIMIT):
            self._post_waits += 1
            self._arm(POST_REPAIR_WAIT_S, recheck=False)

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
        return {**self._status, "rechecks": self._rechecks, "events": [dict(event) for event in self.events]}
