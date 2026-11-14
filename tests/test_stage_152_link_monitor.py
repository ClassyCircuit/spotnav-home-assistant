"""Stage 15.2: the read-only Morek link monitor, its edges, evidence gaps and the worker's offline blocker.

Real monitor, evidence store and Morek worker; the OCPP point registry, HA timers and storage are the usual mocked
boundaries. Nothing here proves what the installed OCPP integration exposes (`status`, `charger_generation`) or
physical behavior.
Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest
     tests/test_stage_152_link_monitor.py
"""

import asyncio
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_link
from custom_components.spotnav.execution.morek_link import LINK_POLL_S, LINK_RECOVERY_MIN_S, MorekLinkMonitor
from custom_components.spotnav.sessions import evidence as ev
from .test_morek_worker import drain, setup
from .test_stage_62_evidence import MemBackend

T0 = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeSession:
    def __init__(self):
        self.calls = []

    def offline(self):
        self.calls.append("offline")

    def reconnect(self):
        self.calls.append("reconnect")

    def note_plug_in(self):  # pragma: no cover - must never be reached
        raise AssertionError("a link edge is never a plug-in")


class FakeWorker:
    def __init__(self):
        self.session = FakeSession()
        self.triggers = []

    def trigger(self, snapshot=None, *, sync=False, kind=None):
        self.triggers.append(kind)

    def note_plug_in(self):  # pragma: no cover - must never be reached
        raise AssertionError("a link edge is never a plug-in")


class Rig:
    """A monitor whose reading is whatever the test sets; the real evidence store keeps the gaps."""

    def __init__(self, worker=None, hass=None):
        self.clock = Clock()
        self.point = object()
        self.reading = ("up", self.point, None)
        self.worker = worker or FakeWorker()
        self.hass = hass or SimpleNamespace(data={})
        self.store = ev.ChargingEvidenceStore(self.hass, store=MemBackend(), now=self.clock)
        self.hass.data[ev.DATA_KEY] = self.store
        self.monitor = MorekLinkMonitor(self.hass, "charger", self.worker, read=lambda: self.reading, now=self.clock)

    def set(self, state, point="same", boot=None):
        self.reading = (state, self.point if point == "same" else point, boot)

    def check(self, advance=LINK_POLL_S):
        self.clock.advance(advance)
        self.monitor.check()


def gaps(rig, kind=ev.KIND_REGISTER):
    return [row for row in rig.store.gaps("charger", kind) if row.get("g") == morek_link.LINK_GAP_REASON]


# ---- reading ----------------------------------------------------------------------------------------------

def hass_with(points, cpids=None):
    system = SimpleNamespace(charge_points=points, cpids=cpids or {})
    return SimpleNamespace(data={"ocpp": {"entry": system}})


def point(status="ok", version="1.6", generation=None):
    value = SimpleNamespace(status=status, _ocpp_version=version)
    if generation is not None:
        value.charger_generation = generation
    return value


TARGET = SimpleNamespace(devid=morek_schedule.MOREK_STATION_ID, connector_id=1)


def test_link_reading_follows_charge_point_and_tolerates_missing_or_ambiguous():
    station = morek_schedule.MOREK_STATION_ID
    up = point(generation=3)
    assert morek_schedule.link_reading(hass_with({station: up}), TARGET) == ("up", up, 3)
    down = point(status="unavailable")
    assert morek_schedule.link_reading(hass_with({station: down}), TARGET) == ("down", down, None)
    assert morek_schedule.link_reading(hass_with({}), TARGET)[0] == "unknown"  # no object: not "down"
    assert morek_schedule.link_reading(SimpleNamespace(data={}), TARGET)[0] == "unknown"
    assert morek_schedule.link_reading(hass_with({station: point(status=None)}), TARGET)[0] == "unknown"
    assert morek_schedule.link_reading(hass_with({station: point(version="2.0.1")}), TARGET)[0] == "unknown"
    two = SimpleNamespace(data={"ocpp": {"a": SimpleNamespace(charge_points={station: up}, cpids={}),
                                         "b": SimpleNamespace(charge_points={station: up}, cpids={})}})
    assert morek_schedule.link_reading(two, TARGET)[0] == "unknown"  # ambiguous
    other = SimpleNamespace(devid="OTHER", connector_id=1)
    assert morek_schedule.link_reading(hass_with({"OTHER": up}), other)[0] == "unknown"  # not the Morek
    assert point(generation=True).charger_generation is True
    assert morek_schedule.link_reading(hass_with({station: point(generation=True)}), TARGET)[2] is None


# ---- edges ------------------------------------------------------------------------------------------------

def test_cold_start_is_unknown_then_seeds_without_edges():
    rig = Rig()
    assert rig.monitor.status() == {"state": "unknown", "since": None, "connection_id": None,
                                    "connection_changed_at": None, "boot_generation": None, "boot_changed_at": None}
    rig.monitor.check()
    status = rig.monitor.status()
    assert status["state"] == "up" and status["connection_id"] == 1 and status["connection_changed_at"] is None
    assert rig.worker.session.calls == [] and rig.worker.triggers == []
    assert gaps(rig) == []
    down = Rig()
    down.set("down")
    down.monitor.check()
    assert down.monitor.state == "down" and down.worker.session.calls == [] and down.worker.triggers == []
    down.set("up")
    down.check()  # seeded down -> up is a restoration: delivered once
    assert down.worker.session.calls == ["reconnect"] and down.worker.triggers == ["recovery"]


def test_up_down_up_with_a_stale_available_control_entity_is_detected_once_per_edge():
    """No control-entity event is involved at all: only the point's own status moves."""
    rig = Rig()
    rig.monitor.check()
    rig.set("down")
    rig.check()
    for _ in range(5):
        rig.check()  # still down: nothing more is delivered
    assert rig.worker.session.calls == ["offline"] and rig.worker.triggers == []
    assert rig.monitor.state == "down"
    rig.set("up")
    rig.check()
    for _ in range(3):
        rig.check()
    assert rig.worker.session.calls == ["offline", "reconnect"]
    assert rig.worker.triggers == ["recovery"]
    status = rig.monitor.status()
    assert status["state"] == "up" and status["connection_id"] == 2 and status["connection_changed_at"]


def test_a_new_point_object_alone_is_an_edge_but_never_a_reconnect_reboot_or_plug_in():
    rig = Rig()
    rig.monitor.check()
    rig.set("up", point=object())
    rig.check()
    rig.check()
    assert rig.worker.session.calls == []  # no session.reconnect(): an object proves a connection, not a reboot
    assert rig.worker.triggers == ["recovery"]
    assert rig.monitor.connection_id == 2 and rig.monitor.state == "up" and rig.monitor.connection_changed_at
    assert len(gaps(rig)) >= 1  # the span since the last reading is unobserved


def test_boot_generation_rise_is_recorded_only_within_this_process_and_is_not_a_reconnect():
    rig = Rig()
    rig.set("up", boot=4)
    rig.monitor.check()
    assert rig.monitor.boot_generation == 4 and rig.monitor.boot_changed_at is None  # seeded, not a boot
    rig.set("down", boot=4)
    rig.check()
    rig.set("up", boot=4)
    rig.check()
    assert rig.monitor.boot_changed_at is None  # a reconnect alone is not boot evidence
    rig.set("up", boot=5)
    rig.check()
    assert rig.monitor.boot_generation == 5 and rig.monitor.boot_changed_at == rig.clock.now
    risen = rig.monitor.boot_changed_at
    rig.set("up", boot=2)  # a reset or a different counter is recorded, never a boot
    rig.check()
    assert rig.monitor.boot_generation == 2 and rig.monitor.boot_changed_at == risen
    restarted = MorekLinkMonitor(rig.hass, "charger", FakeWorker(), read=lambda: ("up", rig.point, 9), now=rig.clock)
    restarted.check()  # an HA restart: memory is empty, so a higher counter than before is just a seed
    assert restarted.boot_generation == 9 and restarted.boot_changed_at is None and restarted.connection_id == 1


def test_unknown_readings_make_no_edges_and_keep_the_last_definite_comparison():
    rig = Rig()
    rig.monitor.check()
    rig.set("unknown", point=None)
    rig.check()
    assert rig.monitor.state == "unknown" and rig.worker.session.calls == [] and rig.worker.triggers == []
    rig.set("up")  # same object, was up before: nothing happened as far as can be observed
    rig.check()
    assert rig.monitor.state == "up" and rig.worker.session.calls == [] and rig.worker.triggers == []
    rig.set("down")
    rig.check()
    rig.set("unknown", point=None)
    rig.check()
    rig.set("up")
    rig.check()
    assert rig.worker.session.calls == ["offline", "reconnect"] and rig.worker.triggers == ["recovery"]


def test_flapping_gives_bounded_recovery_runs_and_each_edge_once():
    rig = Rig()
    rig.monitor.check()
    for _ in range(5):  # 50 s of flapping, inside the minimum recovery interval
        rig.set("down")
        rig.check(5)
        rig.set("up")
        rig.check(5)
    assert rig.worker.session.calls.count("offline") == 5 and rig.worker.session.calls.count("reconnect") == 5
    assert rig.worker.triggers == ["recovery"]  # coalesced: one run within the minimum interval
    rig.check(LINK_RECOVERY_MIN_S)  # the next poll delivers the one pending run, exactly once
    assert rig.worker.triggers == ["recovery", "recovery"]
    rig.check(LINK_RECOVERY_MIN_S)
    assert rig.worker.triggers == ["recovery", "recovery"]


def test_link_down_spans_are_evidence_and_energy_across_them_is_unobserved():
    rig = Rig()
    rig.monitor.check()
    store, clock = rig.store, rig.clock
    store.record_sample("charger", ev.KIND_REGISTER, value=10.0, observed_at=clock.now, received_at=clock.now,
                        entity_id="sensor.energy", unit="kWh", source="configured_entity")
    rig.set("down")
    rig.check(30)
    rig.check(300)
    rig.set("up")
    rig.check(30)
    store.record_sample("charger", ev.KIND_REGISTER, value=13.0, observed_at=clock.now, received_at=clock.now,
                        entity_id="sensor.energy", unit="kWh", source="configured_entity")
    assert gaps(rig) and all(row["s"] == "link_monitor" for row in gaps(rig))
    segments = store.energy_segments("charger", ev.KIND_REGISTER)
    assert len(segments) == 1
    assert segments[0]["coverage"] == "unobserved" and segments[0]["placement"] == "unknown"
    assert "recorded_gap" in segments[0]["reasons"] and segments[0]["kwh"] == 3.0
    # without the monitor's gap the same pair would claim to be observed
    plain = ev.derive_energy([row for row in store.samples("charger", ev.KIND_REGISTER)], ev.KIND_REGISTER)
    assert plain[0]["coverage"] == "endpoints_only"


def test_a_missing_evidence_store_or_failing_consumer_never_breaks_the_monitor():
    rig = Rig()
    rig.hass.data.pop(ev.DATA_KEY)
    rig.monitor.check()
    rig.set("down")
    rig.check()
    rig.worker.session.offline = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    rig.set("up")
    rig.check()
    rig.check()  # never raises into the event bus


def test_the_monitor_never_calls_the_charger_and_has_one_timer_cancelled_on_unload(monkeypatch):
    timers = []

    def track(hass, action, interval):
        handle = SimpleNamespace(cancelled=0, action=action, interval=interval)
        handle.cancel = lambda: setattr(handle, "cancelled", handle.cancelled + 1)
        timers.append(handle)
        return handle.cancel

    import homeassistant.helpers.event as helpers_event

    monkeypatch.setattr(helpers_event, "async_track_time_interval", track)
    rig = Rig()
    rig.monitor.start()
    assert len(timers) == 1 and timers[0].interval == timedelta(seconds=LINK_POLL_S)
    assert rig.monitor.state == "up"
    rig.monitor.stop()
    rig.monitor.stop()
    assert timers[0].cancelled == 1
    rig.set("down")
    rig.monitor.poke()  # closed: no more reads, no deliveries
    assert rig.worker.session.calls == [] and rig.monitor.state == "up"
    # the module's only dependencies on the point are local reads
    source = open(morek_link.__file__, encoding="utf-8").read()
    for forbidden in ("async_call", ".call(", "fetch", "send_profile", "start_transaction"):
        assert forbidden not in source


# ---- the timer target runs on the event loop ----------------------------------------------------------------

class LoopOnlyWorker(FakeWorker):
    """Records the thread each consumer is reached on (the real ones create tasks, valid only on the loop)."""

    def __init__(self):
        super().__init__()
        self.threads = []
        offline, reconnect = self.session.offline, self.session.reconnect
        self.session.offline = lambda: (self.threads.append(threading.get_ident()), offline())
        self.session.reconnect = lambda: (self.threads.append(threading.get_ident()), reconnect())

    def trigger(self, snapshot=None, *, sync=False, kind=None):
        self.threads.append(threading.get_ident())
        super().trigger(snapshot, sync=sync, kind=kind)


@pytest.mark.asyncio
async def test_poll_timer_target_is_a_callback_job_run_on_the_event_loop_not_an_executor(monkeypatch):
    """Real HassJob classification and scheduling: a plain function would be an executor job (a worker thread)."""
    from homeassistant.core import HassJob, HassJobType, HomeAssistant
    import homeassistant.helpers.event as helpers_event

    hass = HomeAssistant(tempfile.mkdtemp())
    hass.loop = asyncio.get_running_loop()
    captured = []
    monkeypatch.setattr(helpers_event, "async_track_time_interval",
                        lambda _hass, action, interval: captured.append(action) or (lambda: None))
    rig = Rig(worker=LoopOnlyWorker())
    rig.monitor = MorekLinkMonitor(hass, "charger", rig.worker, read=lambda: rig.reading, now=rig.clock)
    rig.monitor.start()
    action = captured[0]
    assert HassJob(action).job_type is HassJobType.Callback  # what HA's timer builds from the action
    assert HassJob(lambda _now: None).job_type is HassJobType.Executor  # the regression this guards against
    loop_thread = threading.get_ident()
    for state in ("down", "up"):
        rig.set(state)
        rig.clock.advance(LINK_POLL_S)
        hass.async_run_hass_job(HassJob(action), rig.clock.now)  # the real scheduling path
        await asyncio.sleep(0.05)
    assert rig.worker.session.calls == ["offline", "reconnect"] and rig.worker.triggers == ["recovery"]
    assert rig.worker.threads and set(rig.worker.threads) == {loop_thread}
    rig.monitor.stop()


# ---- through the real worker --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unchanged_accepted_schedule_is_never_resent_by_link_flapping(monkeypatch):
    w = setup(monkeypatch)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_accepted_unverified"
    rig = Rig(worker=w.worker, hass=w.hass)
    rig.monitor.check()
    for _ in range(4):
        rig.set("down")
        rig.check(5)
        rig.set("up")
        rig.check(5)
        await drain(w.worker)
    rig.set("up", point=object())
    rig.check(LINK_RECOVERY_MIN_S)
    await drain(w.worker)
    assert w.point.call.await_count == 1  # recovery re-evaluated the same intent: no send, no readback call
    assert w.worker.reason in ("unchanged", "upload_accepted_unverified")
    w.worker.close()


@pytest.mark.asyncio
async def test_offline_send_is_a_transient_nonsending_blocker_and_sends_once_after_the_link_returns(monkeypatch):
    w = setup(monkeypatch)
    online = False
    live = w.point

    def charge_point(*_):
        if not online:
            raise morek_schedule.ScheduleRefused("morek_offline")
        return live

    monkeypatch.setattr(morek_schedule, "_charge_point", charge_point)
    assert "morek_offline" in morek_schedule.TRANSIENT_BLOCKERS
    assert morek_schedule.decision_blocker("morek_offline") == {"code": "morek_offline",
                                                                "action": "wait_for_charger_connection"}
    w.worker.start()
    await drain(w.worker)
    assert w.worker.reason == "morek_offline" and w.point.call.await_count == 0
    assert w.worker._blocker_timer is not None and w.worker.blocker_retry["code"] == "morek_offline"  # noqa: SLF001
    # the timer is inside the existing 12-run cap and every run only re-evaluates
    for _ in range(morek_schedule.BLOCKER_RETRY_LIMIT + 3):
        w.worker.trigger(kind="recovery")
        await drain(w.worker)
    assert w.worker.blocker_retry["exhausted"] and w.worker._blocker_timer is None  # noqa: SLF001
    assert w.worker.blocker_retry["attempts"] >= morek_schedule.BLOCKER_RETRY_LIMIT
    assert w.point.call.await_count == 0
    # the link returns: a link-driven recovery sends the changed plan exactly once through the normal path
    online = True
    rig = Rig(worker=w.worker, hass=w.hass)
    rig.set("down")
    rig.monitor.check()
    rig.set("up")
    rig.check()
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "upload_accepted_unverified"
    rig.set("down")
    rig.check()
    rig.set("up")
    rig.check(LINK_RECOVERY_MIN_S)
    await drain(w.worker)
    assert w.point.call.await_count == 1
    w.worker.close()
