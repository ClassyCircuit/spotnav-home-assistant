"""Stage 15.5: the guarded start after a *confirmed* charger reboot, and the enabled-charging readiness field.

Real `MorekSessionCoordinator` through the real connector-admission boundary (the `test_morek_session` harness) and
the real `MorekLinkMonitor` delivering the boot signal; HA state, OCPP and storage are the usual mocked boundaries.
Nothing here proves that the installed OCPP integration exposes `charger_generation`, that HA stamps the status or
transaction sensors after a reboot, or any physical charging.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_155_boot_start.py
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_session
from custom_components.spotnav.execution.command_admission import physical_connector
from custom_components.spotnav.execution.morek_link import MorekLinkMonitor
from .test_morek_session import IDENTITY, setup as session_setup


class Link:
    """A scripted point reading for the real monitor: (state, point object, boot counter)."""

    def __init__(self):
        self.point = object()
        self.state = "up"
        self.boot = 1

    def __call__(self):
        return self.state, self.point, self.boot


class Evidence:
    """The live connector observations `_live_measurements` would return; stamps are relative to 'now'."""

    def __init__(self):
        self.status = ("Preparing", +1)
        self.transaction = (False, +1)  # (present?, seconds relative to the boot signal) or None

    def reading(self, spec, **extra):
        if spec is None:
            return None
        value, offset = spec
        stamp = datetime.now(timezone.utc) + timedelta(seconds=offset)
        return {"value": value, "observed_at": stamp.isoformat(), "fresh": True, **extra}

    def __call__(self, hass, controller, now, entities=None):
        return {"status": self.reading(self.status), "transaction": self.reading(self.transaction)}


def world(monkeypatch, result=True):
    coordinator, point, ledger, admission = session_setup(monkeypatch, result)
    evidence = Evidence()
    monkeypatch.setattr(morek_schedule, "_live_measurements", evidence)
    link = Link()
    worker = coordinator.worker
    worker.session = coordinator
    worker.trigger = lambda **_: None
    monitor = MorekLinkMonitor(coordinator.hass, "charger", worker, read=link)
    monitor.check()  # seeds: no edge
    return SimpleNamespace(coordinator=coordinator, point=point, ledger=ledger, admission=admission,
                           evidence=evidence, link=link, monitor=monitor)


async def settle(w):
    if w.coordinator.task is not None:
        await w.coordinator.task


async def plugged_in(w):
    """A normal plug-in whose one start was accepted before the reboot."""
    w.coordinator.observe("Available", "Preparing")
    await settle(w)
    assert w.point.calls == 1


async def reboot(w, *, bump=True):
    if bump:
        w.link.boot += 1
    w.monitor.check()
    await settle(w)


@pytest.mark.asyncio
async def test_boot_rise_with_fresh_preparing_and_no_transaction_requests_exactly_once(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    await reboot(w)
    assert w.point.calls == 2
    assert w.ledger.value["session_start"]["connection"].startswith("boot:")
    for _ in range(5):  # polls, repeated callbacks and the same signal never request again
        w.monitor.check()
        w.coordinator.evaluate_boot()
        w.coordinator.observe("Preparing", "Preparing")
        await settle(w)
    assert w.point.calls == 2
    assert w.coordinator.boot_status(True)["state"] == "requested"


@pytest.mark.asyncio
async def test_boot_rise_while_session_state_never_started_still_one(monkeypatch):
    """The connector reports Preparing after the reboot and nothing was ever requested before it."""
    w = world(monkeypatch)
    w.coordinator.observe(None, "Preparing")  # initial observation: ambiguous recovery, request #1
    await settle(w)
    w.coordinator.connection = None  # no session token at all (restart-like) before the boot
    w.ledger.value.pop("session_start", None)
    await reboot(w)
    assert w.point.calls == 2


@pytest.mark.asyncio
async def test_second_genuine_boot_gets_a_second_request(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    await reboot(w)
    await reboot(w)
    assert w.point.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["same_counter_reconnect", "new_point_object", "link_down_up_new_point"])
async def test_reconnect_or_point_change_alone_is_not_a_reboot(monkeypatch, case):
    w = world(monkeypatch)
    await plugged_in(w)
    if case == "new_point_object":
        w.link.point = object()
    elif case == "link_down_up_new_point":
        w.link.state = "down"
        w.monitor.check()
        w.link.state, w.link.point = "up", object()
    await reboot(w, bump=False)
    assert w.coordinator._boot is None
    boot_tokens = [c for c in [w.ledger.value["session_start"]["connection"]] if c.startswith("boot:")]
    assert boot_tokens == []
    if case == "new_point_object":
        assert w.point.calls == 1  # nothing minted a token at all
    assert w.coordinator.boot_status(True)["state"] == "none"


@pytest.mark.asyncio
async def test_down_up_with_boot_rise_uses_only_the_existing_offline_recovery_once(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    w.link.state = "down"
    w.monitor.check()
    w.link.state, w.link.point = "up", object()
    await reboot(w)  # the boot rise is delivered first, then the reconnect's offline token
    assert w.point.calls == 2
    assert w.ledger.value["session_start"]["connection"].startswith("offline:")
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 2
    assert w.coordinator.boot_status(True)["reason"] == "covered_by_offline_recovery"


@pytest.mark.asyncio
@pytest.mark.parametrize("tx", [None, (None, +1), (False, -5), (True, +1)],
                         ids=["field_missing", "value_unknown", "stale_before_boot", "transaction_present"])
async def test_missing_unknown_stale_or_present_transaction_blocks(monkeypatch, tx):
    w = world(monkeypatch)
    await plugged_in(w)
    w.evidence.transaction = tx
    await reboot(w)
    assert w.point.calls == 1
    status = w.coordinator.boot_status(True)
    assert status["state"] == "blocked"
    assert status["reason"] in ("transaction_unknown", "transaction_not_reported_after_boot", "transaction_present")
    # The affirmative report arriving later (a later poll) releases exactly one request.
    if tx != (True, +1):
        w.evidence.transaction = (False, +1)
        w.monitor.check()
        await settle(w)
        assert w.point.calls == 2


@pytest.mark.asyncio
async def test_preparing_must_be_observed_after_the_boot_signal(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    w.evidence.status = ("Preparing", -5)  # a pre-boot report
    await reboot(w)
    assert w.point.calls == 1
    assert w.coordinator.boot_status(True) == {**w.coordinator.boot_status(True), "state": "waiting",
                                               "reason": "waiting_for_post_boot_status"}
    w.evidence.status = ("Preparing", +1)
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["event", "evidence"])
async def test_charging_or_suspended_seen_after_the_signal_blocks(monkeypatch, how):
    w = world(monkeypatch)
    await plugged_in(w)
    if how == "event":
        w.evidence.transaction = None  # the evidence is not complete yet
        await reboot(w)
        w.coordinator.observe("Preparing", "Charging")
        w.coordinator.observe("Charging", "Preparing")  # back to Preparing, but Charging was seen
        w.evidence.transaction = (False, +1)
    else:
        w.evidence.status = ("SuspendedEV", +1)
        await reboot(w)
        w.evidence.status = ("Preparing", +1)
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 1
    assert w.coordinator.boot_status(True)["reason"] == "charging_seen_after_boot"


@pytest.mark.asyncio
async def test_completion_record_and_unplug_block(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    w.evidence.transaction = None
    await reboot(w)
    w.coordinator.observe("Preparing", "Finishing")
    await settle(w)
    w.coordinator.observe("Finishing", "Preparing")
    w.evidence.transaction = (False, +1)
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 1  # finishing recorded a completion: no recovery for a boot token either

    v = world(monkeypatch)
    await plugged_in(v)
    v.evidence.transaction = None
    await reboot(v)
    v.coordinator.observe("Preparing", "Available")
    await settle(v)
    assert v.coordinator.boot_status(True)["reason"] == "unplugged_after_boot"


@pytest.mark.asyncio
@pytest.mark.parametrize("prior", ["unknown", "pending"])
async def test_pending_or_unknown_earlier_request_is_preserved_and_never_retried(monkeypatch, prior):
    w = world(monkeypatch)
    await plugged_in(w)
    w.ledger.value["session_start"]["state"] = prior
    await reboot(w)
    assert w.point.calls == 1
    assert w.ledger.value["session_start"]["state"] == prior
    assert w.coordinator.state == {"state": "uncertain", "reason": "previous_start_may_have_applied"}


@pytest.mark.asyncio
async def test_stop_pause_and_protection_win_over_a_boot_request(monkeypatch):
    for guard in ("stop", "pause", "protection"):
        w = world(monkeypatch)
        await plugged_in(w)
        if guard == "stop":
            w.admission._person_stops[physical_connector(IDENTITY)] = True
        elif guard == "pause":
            w.ledger.value["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p"}
        else:
            monkeypatch.setattr(morek_session, "controller_for", lambda *_: SimpleNamespace(
                ocpp_target=SimpleNamespace(connector_id=1), _start_cap=lambda: None))
        await reboot(w)
        assert w.point.calls == 1, guard
        assert w.coordinator.state["state"] in ("blocked", "uncertain"), guard


@pytest.mark.asyncio
async def test_stop_racing_the_request_refuses_it(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    connector = physical_connector(IDENTITY)
    real = w.admission.async_owned_boundary_current

    async def stop_during_boundary(*args, **kwargs):
        w.admission._person_stops[connector] = True  # the person Stop lands between ledger write and dispatch
        return await real(*args, **kwargs)

    monkeypatch.setattr(w.admission, "async_owned_boundary_current", stop_during_boundary)
    await reboot(w)
    assert w.point.calls == 1
    assert w.ledger.value["session_start"]["state"] in ("aborted_before_dispatch", "accepted")
    assert w.coordinator.state["state"] == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("late", [(True, +1), (None, +1), (False, -5), "charging"],
                         ids=["transaction_present", "transaction_unknown", "transaction_stale", "fresh_charging"])
@pytest.mark.parametrize("where", ["write", "read"])
async def test_evidence_changing_during_ledger_await_aborts_before_dispatch(monkeypatch, late, where):
    """The boot token was minted from clean evidence; storage awaits must not let it outlive that evidence."""
    w = world(monkeypatch)
    await plugged_in(w)
    real = getattr(w.ledger, where)
    armed = {"on": False}

    async def spoil(*args, **kwargs):
        pending = (w.ledger.value.get("session_start") or {}).get("state") == "pending"
        if armed["on"] and (where == "write" or pending):  # a read only counts once the pending attempt is stored
            armed["on"] = False
            if late == "charging":
                w.evidence.status = ("Charging", +1)
            else:
                w.evidence.transaction = late
        return await real(*args, **kwargs)

    monkeypatch.setattr(w.ledger, where, spoil)
    armed["on"] = True
    w.link.boot += 1
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 1  # no duplicate start
    assert w.ledger.value["session_start"]["state"] == "aborted_before_dispatch"
    assert w.coordinator.state["state"] == "blocked"
    assert w.coordinator.state["reason"] != "uncertain"


@pytest.mark.asyncio
async def test_rejected_boot_request_keeps_the_existing_retry_rule(monkeypatch):
    w = world(monkeypatch, result=False)
    w.coordinator.observe("Available", "Preparing")
    await settle(w)
    w.ledger.value["session_start"]["state"] = "accepted"  # the plug-in request is settled
    w.coordinator.retry = SimpleNamespace(cancel=lambda: None)  # keep the 60 s timer out of this test
    await reboot(w)
    assert w.point.calls == 2
    assert w.ledger.value["session_start"]["state"] == "rejected"
    assert w.ledger.value["session_start"]["attempts"] == 1
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 2  # no new token: the retry (60 s, max 2) belongs to the coordinator's own path


@pytest.mark.asyncio
async def test_plug_in_after_the_signal_owns_the_opportunity_and_unplug_replug_is_unchanged(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    w.evidence.transaction = None
    await reboot(w)  # waiting for evidence
    w.coordinator.observe("Preparing", "Available")
    w.coordinator.observe("Available", "Preparing")  # a genuine new plug-in
    w.evidence.transaction = (False, +1)
    await settle(w)
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 2  # exactly the plug-in's request; no extra boot request
    assert w.ledger.value["session_start"]["connection"] not in (None, "")
    assert not w.ledger.value["session_start"]["connection"].startswith("boot:")


@pytest.mark.asyncio
async def test_boot_evidence_expires(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    w.evidence.transaction = None
    await reboot(w)
    w.coordinator._boot["at"] -= timedelta(seconds=morek_session.BOOT_EVIDENCE_WINDOW_S + 1)
    w.evidence.transaction = (False, +1)
    w.monitor.check()
    await settle(w)
    assert w.point.calls == 1
    assert w.coordinator.boot_status(True)["reason"] == "boot_evidence_expired"


@pytest.mark.asyncio
async def test_boot_signal_is_delivered_on_the_event_loop_and_never_calls_the_charger(monkeypatch):
    """The monitor path creates the session task from a loop callback (no executor); evidence reads are local."""
    w = world(monkeypatch)
    await plugged_in(w)
    called = []
    monkeypatch.setattr(morek_schedule, "_live_measurements",
                        lambda *a, **k: called.append(1) or Evidence()(*a, **k))
    loop = asyncio.get_running_loop()
    done = loop.create_future()
    loop.call_soon(lambda: (w.link.__setattr__("boot", 2), w.monitor.check(), done.set_result(None)))
    await done
    await settle(w)
    assert called and w.point.calls == 2


def test_readiness_reports_boot_counter_unknown_and_charging_enabled_states():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    cases = [({"value": "on", "observed_at": now.isoformat(), "fresh": True}, "enabled", "control_on"),
             ({"value": "off", "observed_at": now.isoformat(), "fresh": True}, "not_ready", "control_off"),
             ({"value": "on", "observed_at": now.isoformat(), "fresh": False}, "not_ready", "control_unconfirmed"),
             ({"value": None, "fresh": True}, "not_ready", "control_unconfirmed"),
             (None, "not_ready", "control_unconfirmed")]
    for reading, state, reason in cases:
        result = morek_schedule._charging_enabled(reading)
        assert (result["state"], result["reason"]) == (state, reason)
    coordinator = SimpleNamespace(_boot=None)
    status = morek_session.MorekSessionCoordinator.boot_status
    assert status(coordinator, False) == {"state": "unknown", "reason": "boot_counter_unavailable"}
    assert status(coordinator, True) == {"state": "none", "reason": "no_boot_observed"}
    base = morek_schedule._session_readiness(SimpleNamespace(), SimpleNamespace(), {"supported": False}, True, now)
    assert base["charging_enabled"] == {"state": "unknown", "reason": "no_evidence"}
    assert base["boot_start"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_not_ready_switch_never_causes_a_request(monkeypatch):
    w = world(monkeypatch)
    await plugged_in(w)
    before = w.ledger.value["session_start"]
    for _ in range(3):
        w.monitor.check()
        w.coordinator.evaluate_boot()
    await settle(w)
    assert w.point.calls == 1
    assert w.ledger.value["session_start"] == before
