"""Stage 15.2: an in-process, read-only link monitor for one Morek entry.

Every `LINK_POLL_S` seconds and on existing entity/connector events it reads, with no OCPP traffic, the point's
connection (`morek_schedule.link_reading`: `status == "ok"` as `_charge_point` judges it), the point *object*
(a new object is a new connection) and the boot counter when the point exposes one (`charger_generation`, an
attribute of the installed OCPP integration whose presence is unverified). State is memory only: a cold start is
`unknown` until the first reading seeds it, and **an HA restart is not a charger reboot** (the boot counter is
compared only within this process; nothing is persisted).

Edges go to the existing consumers, each once:

* up -> down: `session.offline()` and a `link_down` gap in the evidence store (so Stage 6.3 reports the span
  `unobserved`);
* down -> up: `session.reconnect()`, the gap's end and one rate-limited `recovery` trigger;
* a new point object while up (a connection the monitor did not see drop): the gap since the last reading and the
  same rate-limited `recovery` trigger, but **no** `session.reconnect()`: an object change proves a new
  connection, never a reboot, a plug-in or a new session.

A drop shorter than the poll that leaves the same point object is not detectable (a stated limit). The monitor
never calls the charger, sends, reads back or starts anything: a `recovery` trigger only re-runs the existing
guarded read-and-compare path, and a flapping link gives at most one such run per `LINK_RECOVERY_MIN_S`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from homeassistant.core import callback

from ..api import morek_schedule
from ..runtime import controller_for

_LOGGER = logging.getLogger(__name__)

LINK_POLL_S: Final = 30
#: Flapping coalesces: link-driven recovery runs are at least this far apart (a pending one waits for a poll).
LINK_RECOVERY_MIN_S: Final = 60
LINK_GAP_REASON: Final = "link_down"


class MorekLinkMonitor:
    """Link state, connection id and boot generation for one Morek entry (memory only)."""

    def __init__(self, hass: Any, entry_id: str, worker: Any, *,
                 read: Callable[[], tuple[str, Any, int | None]] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._worker = worker
        self._read = read or self._read_point
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cancel: Callable[[], None] | None = None
        self._closed = False
        self.state = "unknown"  # up / down / unknown
        self.since: datetime | None = None
        self.connection_id: int | None = None
        self.connection_changed_at: datetime | None = None
        self.boot_generation: int | None = None
        self.boot_changed_at: datetime | None = None
        self._last: str | None = None  # last definite reading: up / down (None until seeded)
        self._point: Any = None
        self._seq = 0
        self._up_at: datetime | None = None  # last reading that saw the link up
        self._down_ref: datetime | None = None  # where an in-progress down span starts for the evidence gap
        self._recovery_pending = False
        self._recovery_at: datetime | None = None

    # ---- lifecycle

    def start(self) -> None:
        """Seed from the first reading, then one bounded poll timer; `stop` (unload) cancels it."""
        from homeassistant.helpers.event import async_track_time_interval

        self.check()
        self._cancel = async_track_time_interval(self._hass, self._async_poll, timedelta(seconds=LINK_POLL_S))

    @callback
    def _async_poll(self, _now: datetime) -> None:
        """Timer target. It must be a `@callback`: HA classifies a plain function as an executor job, and the
        consumers `check` reaches (session, worker trigger, storage) create tasks that need the event loop."""
        self.check()

    def stop(self) -> None:
        self._closed = True
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    # ---- reading

    def _read_point(self) -> tuple[str, Any, int | None]:
        target = getattr(controller_for(self._hass, self._entry_id), "ocpp_target", None)
        if target is None:
            return "unknown", None, None
        return morek_schedule.link_reading(self._hass, target)

    def poke(self) -> None:
        """An existing entity/connector event: read again (a local read; never raises into the event bus)."""
        self.check()

    def status(self) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {"state": self.state, "since": iso(self.since), "connection_id": self.connection_id,
                "connection_changed_at": iso(self.connection_changed_at),
                "boot_generation": self.boot_generation, "boot_changed_at": iso(self.boot_changed_at)}

    # ---- the one comparison

    def check(self) -> None:
        if self._closed:
            return
        try:
            reading = self._read()
            now = self._now()
            self._compare(reading, now)
            evaluate = getattr(getattr(self._worker, "session", None), "evaluate_boot", None)
            if callable(evaluate):
                evaluate()  # a pending boot signal re-reads its local evidence on every poll/event
        except Exception as err:  # noqa: BLE001 - monitoring must never affect charging or the event bus
            _LOGGER.debug("Morek link check failed: %s", type(err).__name__)

    def _set_state(self, state: str, now: datetime) -> None:
        if state != self.state:
            self.state, self.since = state, now

    def _compare(self, reading: tuple[str, Any, int | None], now: datetime) -> None:
        state, point, boot = reading
        self._track_boot(state, boot, now)
        if state not in ("up", "down"):
            # Unreadable, ambiguous or unsupported: shown as unknown, never an edge. The last definite reading is
            # kept so a later reading is compared against what was actually observed.
            self._set_state("unknown", now)
            return
        previous = self._last
        self._last = state
        self._set_state(state, now)
        if state == "down":
            if previous == "up":
                self._down_ref = self._up_at or now
                self._deliver_offline(now)
            elif previous is None:
                self._down_ref = now  # seeded down: nothing observed to drop, no edge
            return
        # up
        last_up, self._up_at = self._up_at, now
        if previous is None:
            self._point = point
            self._seq = 1
            self.connection_id = 1  # seeded: not a change, no edge
            self._request_check("startup")  # HA startup with the link up: one read-only check (15.3), no edge
            return
        if previous == "down":
            self._new_connection(point, now)
            self._record_gap(self._down_ref or now, now)
            self._down_ref = None
            self._deliver_reconnect()
            self._request_recovery(now)
            self._request_check("link_up")
            return
        if point is not self._point:  # up -> up with a new object: a new connection, not a reboot
            self._new_connection(point, now)
            self._record_gap(last_up or now, now)
            self._request_recovery(now)
            self._request_check("connection_change")
            return
        self._deliver_pending_recovery(now)

    def _new_connection(self, point: Any, now: datetime) -> None:
        self._point = point
        self._seq += 1
        self.connection_id = self._seq
        self.connection_changed_at = now

    def _track_boot(self, state: str, boot: int | None, now: datetime) -> None:
        """A rise within this process is the only boot evidence; any other change is only recorded."""
        if state not in ("up", "down") or boot is None:
            return
        previous = self.boot_generation
        self.boot_generation = boot
        if previous is not None and boot > previous:
            self.boot_changed_at = now
            self._deliver_boot(boot)

    # ---- deliveries (each edge once)

    def _deliver_boot(self, boot: int) -> None:
        """A rise within this process opens the session's evidence window (15.5); it starts nothing itself."""
        note = getattr(getattr(self._worker, "session", None), "note_boot", None)
        if callable(note):
            try:
                note(boot)
            except Exception as err:  # noqa: BLE001 - never stop the edge deliveries that follow
                _LOGGER.debug("Morek boot signal not delivered: %s", type(err).__name__)
        self._request_check("boot")

    def _request_check(self, trigger: str) -> None:
        """Ask the read-only schedule checker (15.3) for one coalesced check; it sends nothing."""
        checker = getattr(self._worker, "checker", None)
        if checker is None:
            return
        try:
            checker.request(trigger)
        except Exception as err:  # noqa: BLE001 - never stop the edge deliveries that follow
            _LOGGER.debug("Morek schedule check not requested: %s", type(err).__name__)

    def _deliver_offline(self, now: datetime) -> None:
        checker = getattr(self._worker, "checker", None)
        if checker is not None:
            try:
                checker.note_link_down()  # a link edge ends a check episode (15.3)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Morek schedule check not ended: %s", type(err).__name__)
        session = getattr(self._worker, "session", None)
        if session is not None:
            session.offline()
        self._record_gap(self._down_ref or now, now)

    def _deliver_reconnect(self) -> None:
        session = getattr(self._worker, "session", None)
        if session is not None:
            session.reconnect()

    def _request_recovery(self, now: datetime) -> None:
        self._recovery_pending = True
        self._deliver_pending_recovery(now)

    def _deliver_pending_recovery(self, now: datetime) -> None:
        if not self._recovery_pending:
            return
        if self._recovery_at is not None and (now - self._recovery_at).total_seconds() < LINK_RECOVERY_MIN_S:
            return  # coalesced: a later poll delivers it once the interval has passed
        self._recovery_pending = False
        self._recovery_at = now
        self._worker.trigger(kind="recovery")

    def _record_gap(self, start: datetime, end: datetime) -> None:
        """The span in which measurements could not have been observed; energy there is unobserved."""
        try:
            from ..sessions.evidence import MEASURED_KINDS, evidence_for

            store = evidence_for(self._hass)
            if store is None:
                return
            for kind in MEASURED_KINDS:
                store.record_gap(self._entry_id, kind, LINK_GAP_REASON, received_at=start, source="link_monitor")
                store.record_gap(self._entry_id, kind, LINK_GAP_REASON, received_at=end, source="link_monitor")
        except Exception as err:  # noqa: BLE001 - evidence is best effort
            _LOGGER.debug("Morek link gap not recorded: %s", type(err).__name__)
