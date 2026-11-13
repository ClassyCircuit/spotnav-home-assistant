"""Stage 9.4: the SpotNav log viewer's backend and the new action/session log lines.

Real `SpotNavLogBuffer`, the real `spotnav/get_logs` handler and the real log call sites; only the Home Assistant
object is a thin fake (no Home Assistant, no charger, no network). The records are SpotNav's bounded buffer inside Core's
logging: these tests prove filtering, incremental polling, redaction, permission and noise bounds, not a stream.
"""

import logging
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import logs as logs_api
from custom_components.spotnav.api.morek_schedule import ScheduleRefused, _logged_action
from custom_components.spotnav.execution.morek_session import MorekSessionCoordinator
from custom_components.spotnav.log_buffer import MAX_QUERY_RECORDS, SPOTNAV_LOGGER, attach_log_buffer, detach_log_buffer
from custom_components.spotnav.runtime import domain_data

SECRET = "tok-9f8e7d6c5b4a"


@pytest.fixture
def buffer():
    logger = logging.getLogger(SPOTNAV_LOGGER)
    previous = logger.level
    logger.setLevel(logging.INFO)
    buf = attach_log_buffer()
    yield buf
    detach_log_buffer(buf)
    logger.setLevel(previous)


def say(level, message, name=SPOTNAV_LOGGER + ".test"):
    logging.getLogger(name).log(level, message)


class FakeHass:
    """Just what the handler touches: the domain store, users, entries and background tasks."""

    def __init__(self, buf):
        self.data = {}
        domain_data(self).log_buffer = buf
        self.config = SimpleNamespace(latitude=59.123456, longitude=18.654321)
        self.auth = SimpleNamespace(async_get_users=self._users)
        self.config_entries = SimpleNamespace(async_entries=lambda domain: [])
        self.tasks = []

    async def _users(self):
        return [SimpleNamespace(name="Alexandra Householder")]

    def async_create_background_task(self, coro, *args, **kwargs):
        self.tasks.append(coro)
        return SimpleNamespace()


class Conn:
    def __init__(self, admin):
        self.user = SimpleNamespace(is_admin=admin)
        self.results = []
        self.errors = []

    def send_result(self, msg_id, result=None):
        self.results.append(result)

    def send_error(self, msg_id, code, message):
        self.errors.append(code)

    def send_message(self, message):
        self.results.append(message)


async def ask(hass, admin=True, **fields):
    conn = Conn(admin)
    msg = {"id": 1, "type": "spotnav/get_logs", "api_version": 1, **fields}
    logs_api.websocket_get_logs(hass, conn, msg)
    for task in hass.tasks:
        await task
    hass.tasks.clear()
    return conn


async def test_filters_by_severity_and_text_and_orders_oldest_first(buffer):
    hass = FakeHass(buffer)
    say(logging.INFO, "Morek Resume recorded as an intent")
    say(logging.WARNING, "Morek schedule decision: rejected (upload_rejected)")
    say(logging.INFO, "Price entry refreshed")
    say(logging.ERROR, "Worker failed", name=SPOTNAV_LOGGER + ".execution.morek_worker")
    say(logging.DEBUG, "debug detail (logger is INFO, so never kept)")

    everything = (await ask(hass)).results[0]
    assert everything["ok"] and [e["message"].split()[0] for e in everything["entries"]] == ["Morek", "Morek", "Price", "Worker"]
    assert everything["entries"][0]["seq"] < everything["entries"][-1]["seq"]
    warnings = (await ask(hass, level="WARNING")).results[0]["entries"]
    assert [e["level"] for e in warnings] == ["WARNING", "ERROR"]
    both = (await ask(hass, text="MOREK decision")).results[0]["entries"]
    assert [e["message"] for e in both] == ["Morek schedule decision: rejected (upload_rejected)"]
    assert (await ask(hass, text="worker morek_worker")).results[0]["entries"][0]["level"] == "ERROR", "logger names match too"
    assert (await ask(hass, text="nonexistent")).results[0]["entries"] == []


async def test_only_spotnav_loggers_are_ever_in_the_buffer(buffer):
    hass = FakeHass(buffer)
    logging.getLogger("custom_components.ocpp").warning("raw OCPP payload")
    logging.getLogger("homeassistant.components.system_log").error("unrelated core error")
    say(logging.INFO, "ours")
    entries = (await ask(hass, level="DEBUG")).results[0]["entries"]
    assert [e["message"] for e in entries] == ["ours"]


async def test_incremental_poll_and_restart_reload(buffer):
    hass = FakeHass(buffer)
    say(logging.INFO, "one")
    first = (await ask(hass)).results[0]
    say(logging.INFO, "two")
    later = (await ask(hass, after_seq=first["latest_seq"], boot_id=first["boot_id"])).results[0]
    assert [e["message"] for e in later["entries"]] == ["two"] and later["restarted"] is False
    quiet = (await ask(hass, after_seq=later["latest_seq"], boot_id=first["boot_id"])).results[0]
    assert quiet["entries"] == [] and quiet["latest_seq"] == later["latest_seq"]
    # A viewer that last spoke to an earlier start (a different boot_id) gets everything again and is told.
    reloaded = (await ask(hass, after_seq=999, boot_id="previous-run")).results[0]
    assert reloaded["restarted"] is True and [e["message"] for e in reloaded["entries"]] == ["one", "two"]


async def test_restored_warning_is_history_not_a_new_record(buffer):
    from custom_components.spotnav.log_buffer import _warnings_from_store
    from collections import deque
    from datetime import UTC, datetime
    stored = [{"time": datetime.now(UTC).isoformat(), "level": "WARNING", "logger": SPOTNAV_LOGGER, "message": "before the restart"}]
    buffer._warnings = deque(_warnings_from_store(stored))
    say(logging.WARNING, "after the restart")
    hass = FakeHass(buffer)
    full = (await ask(hass, level="WARNING")).results[0]
    assert [e["message"] for e in full["entries"]] == ["before the restart", "after the restart"]
    assert [e["message"] for e in (await ask(hass, level="WARNING", after_seq=1)).results[0]["entries"]] == [], "poll after seq 1: neither"


async def test_records_are_scrubbed_before_leaving(buffer):
    hass = FakeHass(buffer)
    say(logging.WARNING, f"call failed for Alexandra Householder at 59.123456 Authorization: Bearer {SECRET} mail me@example.com")
    entry = (await ask(hass)).results[0]["entries"][0]
    for leaked in ("Alexandra Householder", "59.123456", SECRET, "me@example.com"):
        assert leaked not in entry["message"]


async def test_non_administrator_gets_a_code_and_no_records(buffer):
    hass = FakeHass(buffer)
    say(logging.WARNING, "private household detail")
    answer = (await ask(hass, admin=False)).results[0]
    assert answer["ok"] is False and answer["error"] == "spotnav_not_admin" and answer["entries"] == []
    assert "private" not in repr(answer)
    assert (await ask(hass, admin=None)).results[0]["error"] == "spotnav_not_admin"


@pytest.mark.parametrize("fields", [
    {"level": "TRACE"}, {"level": 5}, {"text": "x" * 101}, {"text": 7}, {"after_seq": -1}, {"after_seq": True},
    {"limit": 0}, {"limit": MAX_QUERY_RECORDS + 1}, {"boot_id": 3},
])
async def test_invalid_filters_are_refused_with_a_code(buffer, fields):
    answer = (await ask(FakeHass(buffer), **fields)).results[0]
    assert answer["ok"] is False and answer["error"] == "spotnav_logs_invalid_filter"


async def test_unsupported_version_and_missing_buffer(buffer):
    hass = FakeHass(buffer)
    conn = Conn(True)
    logs_api.websocket_get_logs(hass, conn, {"id": 1, "type": "spotnav/get_logs", "api_version": 99})
    await hass.tasks.pop()
    assert conn.errors or conn.results, "an unsupported version is answered, not ignored"
    domain_data(hass).log_buffer = None
    assert (await ask(hass)).results[0]["error"] == "spotnav_logs_unavailable"


async def test_limit_keeps_the_newest_and_says_so(buffer):
    hass = FakeHass(buffer)
    for i in range(12):
        say(logging.INFO, f"line {i}")
    answer = (await ask(hass, limit=5)).results[0]
    assert [e["message"] for e in answer["entries"]] == [f"line {i}" for i in range(7, 12)]
    assert answer["truncated"] is True and answer["matched"] == 12
    assert answer["retention"]["streaming"] is False and answer["retention"]["source"] == "spotnav_log_buffer"


async def test_debug_records_appear_only_when_debug_is_enabled(buffer):
    hass = FakeHass(buffer)
    logging.getLogger(SPOTNAV_LOGGER).setLevel(logging.DEBUG)
    say(logging.DEBUG, "verbose detail")
    assert (await ask(hass)).results[0]["entries"] == []
    assert [e["message"] for e in (await ask(hass, level="DEBUG")).results[0]["entries"]] == ["verbose detail"]


# ---- the new log lines -----------------------------------------------------------------------------

async def test_person_actions_log_one_line_with_no_identifiers(buffer):
    @_logged_action("pause/resume")
    async def record(hass, entry_id, *, resume=False):
        if entry_id == "bad":
            raise ScheduleRefused("resume_unavailable")
        return {}

    @_logged_action("Charge Now")
    async def charge(hass, entry_id, *, return_to_auto=False):
        return {}

    from custom_components.spotnav.api import morek_schedule
    logging.getLogger(morek_schedule.__name__).setLevel(logging.INFO)
    await record(None, "ENTRY-SECRET-ID", resume=True)
    await record(None, "ENTRY-SECRET-ID")
    with pytest.raises(ScheduleRefused):
        await record(None, "bad", resume=True)
    await charge(None, "ENTRY-SECRET-ID")
    await charge(None, "ENTRY-SECRET-ID", return_to_auto=True)
    messages = [r["message"] for r in buffer.records()]
    assert messages[0].startswith("Morek Resume recorded as an intent") and messages[1].startswith("Morek Pause recorded")
    assert messages[2] == "Morek Resume refused: resume_unavailable"
    assert messages[3].startswith("Morek Charge Now recorded") and messages[4].startswith("Morek Return to Auto recorded")
    assert all("ENTRY-SECRET-ID" not in m for m in messages)
    assert all("charging is not confirmed" in m for m in messages if "recorded" in m)


def test_session_start_states_log_once_per_change_and_never_claim_charging(buffer):
    session = MorekSessionCoordinator.__new__(MorekSessionCoordinator)
    waiting = {"state": "waiting", "reason": "waiting_for_vehicle"}
    starting = {"state": "starting", "reason": "request_in_progress"}

    def step(before, after):
        session.state = after
        session._log_state(before)

    step(starting, starting)  # unchanged: silent
    step(starting, waiting)  # back to waiting for a vehicle: not worth a line
    step(waiting, starting)
    step(starting, {"state": "rejected", "reason": "request_rejected"})
    step(waiting, {"state": "uncertain", "reason": "previous_start_may_have_applied"})
    step(starting, {"state": "accepted", "reason": "request_accepted"})
    lines = [(r["level"], r["message"]) for r in buffer.records()]
    assert [level for level, _ in lines] == ["INFO", "WARNING", "WARNING", "INFO"]
    assert all("not measured charging" in message for _, message in lines)
