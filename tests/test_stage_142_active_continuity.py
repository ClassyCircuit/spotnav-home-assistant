"""Stage 14.2: an acknowledged, currently allowed Morek window survives routine replans.

Real worker and profile builder; HA, OCPP and ownership are the usual boundaries.
Evidence is the connector status only, never measured power.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api import morek_schedule
from .test_morek_worker import IDENTITY, NOW, drain, setup

H = timedelta(hours=1)


def sent_profiles(w):
    return [call.args[0].payload["cs_charging_profiles"] for call in w.point.call.await_args_list]


def limits(profile):
    return [(p["startPeriod"], p["limit"]) for p in profile["chargingSchedule"]["chargingSchedulePeriod"]]


def plan(w, *windows):
    w.planner.current.proposal.shown_periods = tuple(windows)
    w.planner.publish()


def evidence(monkeypatch, state):
    box = {"state": state}
    monkeypatch.setattr(morek_schedule, "connector_evidence", lambda *_: box["state"])
    return box


async def started(monkeypatch, state="charging"):
    w = setup(monkeypatch, active=True)  # window NOW-1min .. NOW+2h
    box = evidence(monkeypatch, state)
    w.worker.start()
    await drain(w.worker)
    assert w.point.call.await_count == 1
    return w, box


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["charging", "waiting", "unknown"])
async def test_routine_replan_keeps_the_allowed_window_and_adds_the_future_one(monkeypatch, state):
    w, _ = await started(monkeypatch, state)
    # A SOC update moves the cheapest window to later; the current one would simply vanish.
    plan(w, (NOW + 3 * H, NOW + 4 * H))
    await drain(w.worker)
    assert w.point.call.await_count == 2
    # Preserved to its end, then the future window; no 0 A at the start (no gap).
    assert limits(sent_profiles(w)[1]) == [(0, 16), (7200, 0), (10800, 16), (14400, 0)]
    reason = "active_window_state_unknown" if state == "unknown" else "active_window_preserved"
    assert w.worker.continuity["preserved"] is True and w.worker.continuity["reason"] == reason
    assert w.worker.continuity["evidence"] == state
    w.worker.close()


@pytest.mark.asyncio
async def test_shortened_active_window_is_not_sent_but_extension_and_adjacent_window_merge(monkeypatch):
    w, _ = await started(monkeypatch)
    plan(w, (NOW - 1 * H, NOW + H))  # SOC progress shortens the current window
    await drain(w.worker)
    assert w.point.call.await_count == 1 and w.worker.reason == "unchanged"
    plan(w, (NOW - 1 * H, NOW + H), (NOW + 2 * H, NOW + 3 * H))  # a future window touching its end
    await drain(w.worker)
    assert limits(sent_profiles(w)[1]) == [(0, 16), (10800, 0)]
    w.worker.close()


@pytest.mark.asyncio
async def test_unplugged_releases_the_window_and_the_new_plan_applies(monkeypatch):
    w, box = await started(monkeypatch, "charging")
    box["state"] = "unplugged"  # active-to-idle: fresh evidence that the car is gone
    plan(w, (NOW + 3 * H, NOW + 4 * H))
    await drain(w.worker)
    assert limits(sent_profiles(w)[1]) == [(0, 0), (10800, 16), (14400, 0)]
    assert w.worker.continuity == {"evidence": "unplugged", "preserved": False,
                                   "until": (NOW + 2 * H).isoformat(), "reason": "vehicle_unplugged"}
    w.worker.close()


@pytest.mark.asyncio
async def test_a_planning_settings_edit_keeps_the_active_window(monkeypatch):
    # Until 14.4 implements material-edit interruption, a raised price cap (any revision
    # bump) must not interrupt an accepted, currently allowed window.
    w, _ = await started(monkeypatch)
    w.settings.revision = 5
    w.planner.current.settings_revision = 5
    plan(w, (NOW + 3 * H, NOW + 4 * H))
    await drain(w.worker)
    assert limits(sent_profiles(w)[1]) == [(0, 16), (7200, 0), (10800, 16), (14400, 0)]
    assert w.worker.continuity["preserved"] is True
    w.worker.close()


@pytest.mark.asyncio
async def test_definite_rejection_of_a_newer_attempt_keeps_the_last_accepted_window(monkeypatch):
    w, _ = await started(monkeypatch)
    plan(w, (NOW + 3 * H, NOW + 4 * H))
    w.point.call.return_value = SimpleNamespace(status="Rejected")
    await drain(w.worker)
    assert w.ledger.value["attempt"]["state"] == "rejected"
    assert morek_schedule.acknowledged_profile(w.ledger.value) is not None
    w.point.call.return_value = SimpleNamespace(status="Accepted")
    plan(w, (NOW + 5 * H, NOW + 6 * H))
    await drain(w.worker)
    assert limits(sent_profiles(w)[-1])[0] == (0, 16)  # still continued, no 0 A gap
    w.worker.close()


@pytest.mark.asyncio
async def test_continuity_survives_a_restart_from_the_durable_record(monkeypatch):
    w, _ = await started(monkeypatch)
    ack = w.ledger.value["acknowledged"]
    assert ack["routine"] is True and ack["profile"] == w.ledger.value["attempt"]["profile"]
    w.ledger.value["attempt"] = None  # nothing but the durable acknowledgement remains
    w.settings.revision = 9
    assert morek_schedule.acknowledged_profile(w.ledger.value) == ack["profile"]
    w.worker.close()


@pytest.mark.asyncio
async def test_uncertain_write_pause_and_override_do_not_continue(monkeypatch):
    w, _ = await started(monkeypatch)
    record = w.ledger.value
    assert morek_schedule.acknowledged_profile(record) is not None
    for change in ({"uncertain": True}, {"acknowledged": None},
                   {"acknowledged": {**record["acknowledged"], "routine": False}}):
        assert morek_schedule.acknowledged_profile({**record, **change}) is None
    w.worker.close()


@pytest.mark.asyncio
async def test_preservation_never_exceeds_the_three_window_limit(monkeypatch):
    w, _ = await started(monkeypatch)
    plan(w, *[(NOW + (3 + 2 * i) * H, NOW + (4 + 2 * i) * H) for i in range(3)])
    await drain(w.worker)
    assert w.point.call.await_count == 1  # the accepted schedule stays; nothing is dropped
    assert w.worker.reason == "active_window_block_limit"
    w.worker.close()


@pytest.mark.asyncio
async def test_pause_wins_immediately_over_a_preserved_window(monkeypatch):
    w, _ = await started(monkeypatch)
    record = w.ledger.value
    record["schedule_pause"] = {"version": 1, "type": "pause_until_resumed", "id": "p",
                                "station_id": IDENTITY["resolved_id"], "connector_id": 1}
    w.worker.hold_ticket = ("p", w.admission.generation(
        morek_schedule_connector(w)))
    w.worker.trigger()
    await drain(w.worker)
    assert limits(sent_profiles(w)[1]) == [(0, 0)]
    assert w.worker.continuity is None
    w.worker.close()


def morek_schedule_connector(w):
    from custom_components.spotnav.execution.command_admission import physical_connector
    return physical_connector(w.identity)


@pytest.mark.asyncio
async def test_timer_replans_after_the_preserved_window_ends(monkeypatch):
    w, _ = await started(monkeypatch)
    plan(w, (NOW + 3 * H, NOW + 4 * H))
    await drain(w.worker)
    assert w.worker._continuity_timer is not None
    w.worker.close()
    assert w.worker._continuity_timer is None


def profile(start, *changes):
    return {"chargingSchedule": {"startSchedule": start.isoformat().replace("+00:00", "Z"),
            "chargingSchedulePeriod": [{"startPeriod": o, "limit": a} for o, a in changes]}}


def test_active_window_and_merge_helpers():
    sent = profile(NOW - H, (0, 0), (1800, 16), (3 * 3600, 0), (4 * 3600, 16), (5 * 3600, 0))
    assert morek_schedule.active_window(sent, NOW) == (NOW + 2 * H, 16)
    assert morek_schedule.active_window(sent, NOW - H) is None          # idle
    assert morek_schedule.active_window(sent, NOW + 2 * H) is None      # past the end
    assert morek_schedule.active_window(sent, NOW + 3 * H) == (NOW + 4 * H, 16)
    assert morek_schedule.active_window(profile(NOW, (0, 16)), NOW) is None  # open-ended
    assert morek_schedule.active_window({"junk": 1}, NOW) is None
    future = ((NOW + 90 * timedelta(minutes=1), NOW + 4 * H),)
    windows, end = morek_schedule.continue_active_window(future, 16, NOW, sent)
    assert end == NOW + 2 * H and windows == ((NOW, NOW + 4 * H),)  # overlapping merges
    gone = ((NOW - 2 * H, NOW - H),)  # elapsed windows are dropped
    assert morek_schedule.continue_active_window(gone, 16, NOW, sent) == (((NOW, NOW + 2 * H),), NOW + 2 * H)
    assert morek_schedule.continue_active_window(future, 10, NOW, sent) == (future, None)  # other current
    assert morek_schedule.continue_active_window(future, 16, NOW, None) == (future, None)
    built = morek_schedule.profile_for(
        morek_schedule.continue_active_window(((NOW + 3 * H, NOW + 4 * H),), 16, NOW, sent)[0],
        16, NOW, allow_active=True)
    assert limits(built) == [(0, 16), (7200, 0), (10800, 16), (14400, 0)]


def fake_hass(state, reported):
    states = {"sensor.status": SimpleNamespace(state=state, last_reported=reported, last_updated=reported)}
    return SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: states.get(entity_id)))


@pytest.mark.parametrize("state, age, expected", [
    ("Charging", 10, "charging"), ("Preparing", 10, "waiting"), ("SuspendedEV", 10, "waiting"),
    ("Finishing", 10, "waiting"), ("Available", 10, "unplugged"),
    ("Charging", 600, "unknown"),       # stale is unknown, never idle
    ("Faulted", 10, "unknown"), ("unavailable", 10, "unknown"), ("Charging", -60, "unknown"),
])
def test_connector_evidence_is_fresh_status_or_unknown(monkeypatch, state, age, expected):
    import custom_components.spotnav.vehicles.ocpp_identity as identity
    monkeypatch.setattr(identity, "connector_sensor_entity_id", lambda *_: "sensor.status")
    hass = fake_hass(state, NOW - timedelta(seconds=age))
    controller = SimpleNamespace(ocpp_target=object())
    assert morek_schedule.connector_evidence(hass, controller, NOW) == expected
    assert morek_schedule.connector_evidence(SimpleNamespace(states=SimpleNamespace(get=lambda _: None)),
                                             controller, NOW) == "unknown"
    assert morek_schedule.connector_evidence(SimpleNamespace(), controller, NOW) == "unknown"
