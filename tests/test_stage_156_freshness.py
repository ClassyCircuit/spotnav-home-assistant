"""Stage 15.6: connection-aware display/readiness freshness; control flow keeps its strict bound (mocked, read-only)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.execution import morek_freshness as fresh
from custom_components.spotnav.execution.morek_freshness import LinkFacts
from custom_components.spotnav.execution.morek_link import MorekLinkMonitor
from custom_components.spotnav.execution.morek_session import MorekSessionCoordinator
from custom_components.spotnav.vehicles import ocpp_identity

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def ago(seconds):
    return NOW - timedelta(seconds=seconds)


def up(since_ago=3600):
    return LinkFacts("up", ago(since_ago), 1)


# ------------------------------------------------------------------ pure judgement
def test_idle_healthy_event_is_current_unchanged_with_no_age_cap():
    verdict = fresh.judge_event(ago(600), NOW, up())
    assert verdict["state"] == "current" and verdict["age_s"] == 600
    assert verdict["reported_at"] == ago(600).isoformat() and verdict["link"]["state"] == "up"
    assert fresh.judge_event(ago(86400), NOW, up(90000))["state"] == "current"


def test_link_break_then_reconnect_old_report_is_last_known_new_report_current():
    reconnected = LinkFacts("up", ago(120), 2)  # continuity began 2 minutes ago
    assert fresh.judge_event(ago(600), NOW, reconnected)["state"] == "last_known"  # reported before reconnect
    assert fresh.judge_event(ago(60), NOW, reconnected)["state"] == "current"      # a new report after it
    assert fresh.judge_event(ago(600), NOW, LinkFacts("down", None, 1))["state"] == "last_known"
    unseen = fresh.judge_event(ago(10), NOW, LinkFacts("unknown", None, None))
    assert unseen["state"] == "unknown"  # a restart-fresh monitor: nothing observed yet, no claim


def test_missing_invalid_and_skewed_times_are_unknown():
    assert fresh.judge_event(None, NOW, up())["state"] == "unknown"
    assert fresh.judge_event(datetime(2026, 11, 14, 11), NOW, up())["reason"] == "no_report"  # naive
    future = fresh.judge_event(NOW + timedelta(seconds=30), NOW, up())
    assert future["state"] == "unknown" and future["reason"] == "clock_skew"
    stepped_back = fresh.judge_event(ago(10), NOW, LinkFacts("up", NOW + timedelta(minutes=5), 1))
    assert stepped_back["reason"] == "clock_skew"  # the clock moved behind the link's recorded start


def test_without_a_monitor_the_strict_bound_applies_and_never_more_generous():
    assert fresh.judge_event(ago(100), NOW, None)["state"] == "current"
    assert fresh.judge_event(ago(181), NOW, None)["state"] == "unknown"
    assert fresh.judge_sampled(ago(181), NOW, None, bound_s=900, expected=False)["state"] == "unknown"


def test_sampled_adaptive_bound_idle_versus_unknown():
    link = up()
    assert fresh.judge_sampled(ago(400), NOW, link, bound_s=600, expected=True)["state"] == "current"
    silent = fresh.judge_sampled(ago(700), NOW, link, bound_s=600, expected=True)
    assert silent["state"] == "unknown" and silent["reason"] == "silent_in_transaction"
    assert fresh.judge_sampled(ago(700), NOW, link, bound_s=600, expected=None)["state"] == "unknown"
    idle = fresh.judge_sampled(ago(700), NOW, link, bound_s=600, expected=False)
    assert idle["state"] == "idle" and idle["reason"] == "no_reading_expected"
    assert fresh.judge_sampled(ago(700), NOW, LinkFacts("down", None, 1), bound_s=600, expected=False)["state"] == "unknown"
    old_link = fresh.judge_sampled(ago(100), NOW, LinkFacts("up", ago(30), 2), bound_s=600, expected=True)
    assert old_link["state"] == "last_known"  # young, but it predates this link continuity


def rows(*observed_received):
    return [{"t": ago(o).isoformat(), "r": ago(r).isoformat()} for o, r in observed_received]


def test_cadence_uses_genuine_report_times_and_ignores_duplicates_bursts_and_garbage():
    assert fresh.sampled_bound_s([]) == 180
    five_min = rows(*[(300 * n, 300 * n) for n in range(11, 0, -1)])
    assert fresh.sampled_bound_s(five_min) == 900  # 3 x 300, at the cap
    two_min = rows(*[(120 * n, 120 * n) for n in range(11, 0, -1)])
    assert fresh.sampled_bound_s(two_min) == 360
    fast = rows(*[(10 * n, 10 * n) for n in range(30, 0, -1)])  # 10 s posts seen on a 60 s tick: still the floor
    assert fresh.sampled_bound_s(fast) == 180
    # a replay burst (distinct observed times that all arrived together) and duplicates add no interval
    burst = rows(*[(1000 - 8 * n, 100) for n in range(8)]) + rows((100, 100), (100, 100))
    assert fresh.report_intervals(burst) == []
    flagged = [{**row, "q": ["out_of_order"]} for row in two_min]
    assert fresh.report_intervals(flagged) == []
    assert fresh.report_intervals([{"t": "garbage", "r": None}, {"t": None}, {}]) == []
    gap = rows((9000, 9000), (4000, 4000), (3900, 3900), (3800, 3800), (3700, 3700))  # a 5000 s outage is no cadence
    assert fresh.report_intervals(gap) == [100.0, 100.0, 100.0]


def test_expectation_never_calls_unknown_data_idle():
    cur = {"state": "current"}
    txn = lambda value, state="current": {"judgement": {"state": state}, "value": value}  # noqa: E731
    assert fresh.expectation(None, txn(True)) is True
    assert fresh.expectation({"judgement": cur, "value": "charging"}, None) is True
    assert fresh.expectation(None, txn(False)) is False
    assert fresh.expectation({"judgement": cur, "value": "disconnected"}, None) is False
    assert fresh.expectation({"judgement": cur, "value": "preparing"}, None) is None  # unknown: not idle
    assert fresh.expectation(None, txn(False, "last_known")) is None
    assert fresh.expectation(None, None) is None


# ------------------------------------------------------------------ link facts from the real monitor
def monitor_rig(readings):
    clock = [NOW]
    feed = list(readings)
    point = object()
    monitor = MorekLinkMonitor(SimpleNamespace(), "e", SimpleNamespace(trigger=Mock()),
                               read=lambda: (feed[0], point if feed[0] != "down" else None, None), now=lambda: clock[0])
    return monitor, clock, feed


def test_monitor_continuity_resets_on_drop_and_on_new_connection_and_restart_is_unknown():
    monitor, clock, feed = monitor_rig(["unknown"])
    monitor.check()
    assert fresh.link_facts(monitor) == LinkFacts("unknown", None, None)  # cold start: nothing seeded
    feed[0] = "up"
    clock[0] = NOW + timedelta(seconds=30)
    monitor.check()
    facts = fresh.link_facts(monitor)
    assert facts.state == "up" and facts.continuous_since == clock[0]
    # a report from before the process saw the link (a pre-restart report) is last_known, a later one current
    assert fresh.judge_event(NOW, clock[0], facts)["state"] == "last_known"
    assert fresh.judge_event(clock[0] + timedelta(seconds=1), clock[0] + timedelta(seconds=40), facts)["state"] == "current"
    feed[0] = "down"
    clock[0] += timedelta(seconds=30)
    monitor.check()
    assert fresh.link_facts(monitor).state == "down"
    feed[0] = "up"
    clock[0] += timedelta(seconds=60)
    monitor.check()
    assert fresh.link_facts(monitor).continuous_since == clock[0]  # continuity restarts at the reconnect
    assert fresh.link_facts(SimpleNamespace(state="up", connection_id=1)) is None  # no known start: strict fallback
    assert fresh.link_facts(None) is None


# ------------------------------------------------------------------ readiness integration
def _sensor(state, ts, **attributes):
    return SimpleNamespace(state=state, last_updated=ts, last_reported=ts, attributes=attributes,
                           last_changed=ts)


def _world(monkeypatch, states):
    monkeypatch.setattr(ocpp_identity, "connector_sensor_entity_id", lambda _h, _t, key: f"sensor.{key}")
    monkeypatch.setattr(ocpp_identity, "connector_measurand_entity",
                        lambda *_: ocpp_identity.MeasurandLookup(None, "none"))
    monkeypatch.setattr(ocpp_identity, "_classes_allow_register", lambda *_: True)
    return SimpleNamespace(states=SimpleNamespace(get=Mock(side_effect=states.get)))


def _readiness(hass, monitor, now=NOW):
    controller = SimpleNamespace(charge_control="switch.control", ocpp_target=SimpleNamespace(connector_id=1))
    return morek_schedule._session_readiness(hass, controller, {"supported": True, "match_count": 1}, True, now,
                                             monitor)


def test_idle_healthy_10_minutes_is_current_for_display_but_strict_evidence_stays_unknown(monkeypatch):
    old = ago(600)
    states = {"switch.control": _sensor("on", old), "sensor.status_connector": _sensor("Available", old),
              "sensor.transaction_id": _sensor("0", old)}
    hass = _world(monkeypatch, states)
    monitor = SimpleNamespace(state="up", since=ago(3600), connection_changed_at=None, connection_id=1)
    result = _readiness(hass, monitor)
    assert result["vehicle"] == "disconnected" and result["vehicle_observed_at"] == old.isoformat()
    assert result["freshness"]["quantities"]["status"]["state"] == "current"
    assert result["freshness"]["expected"] is False
    assert result["charging_enabled"] == {"state": "enabled", "reason": "control_on", "observed_at": old.isoformat()}
    assert result["live"]["status"]["fresh"] is False and result["live"]["transaction"]["fresh"] is False
    assert _readiness(hass, None)["vehicle"] == "unknown"  # without a monitor the display is as strict as before
    # the same evidence at the Stage 14.2/14.4 sites: still strict, an old "unplugged" never releases
    controller = SimpleNamespace(ocpp_target=object())
    assert morek_schedule.connector_evidence(hass, controller, NOW) == "unknown"
    states["sensor.status_connector"] = _sensor("Preparing", old)
    assert morek_schedule.connector_evidence(hass, controller, NOW) == "unknown"  # an old "waiting" neither
    states["sensor.status_connector"] = _sensor("Available", ago(60))
    assert morek_schedule.connector_evidence(hass, controller, NOW) == "unplugged"  # a fresh one still releases


def test_link_down_or_reconnect_without_new_report_shows_no_claim(monkeypatch):
    old = ago(600)
    states = {"switch.control": _sensor("on", old), "sensor.status_connector": _sensor("Charging", old),
              "sensor.current_import": _sensor("16", old, unit_of_measurement="A")}
    hass = _world(monkeypatch, states)
    for monitor in (SimpleNamespace(state="down", since=ago(100), connection_id=1),
                    SimpleNamespace(state="up", since=ago(60), connection_changed_at=None, connection_id=2),
                    SimpleNamespace(state="unknown", since=ago(5), connection_id=None)):
        result = _readiness(hass, monitor)
        assert result["vehicle"] == "unknown" and result["measurement"] == "unknown"
        assert result["charging_enabled"]["state"] == "not_ready"
        assert result["freshness"]["quantities"]["status"]["state"] in ("last_known", "unknown")
        assert result["freshness"]["quantities"]["current_a"]["state"] != "current"


def test_only_a_current_measurement_says_measured_and_silent_flow_in_a_transaction_is_unknown(monkeypatch):
    monitor = SimpleNamespace(state="up", since=ago(7200), connection_changed_at=None, connection_id=1)
    states = {"switch.control": _sensor("on", ago(3000)), "sensor.status_connector": _sensor("Charging", ago(3000)),
              "sensor.transaction_id": _sensor("12", ago(3000)),
              "sensor.current_import": _sensor("16", ago(700), unit_of_measurement="A")}
    result = _readiness(_world(monkeypatch, states), monitor)
    quantities = result["freshness"]["quantities"]
    assert result["freshness"]["expected"] is True
    assert quantities["current_a"]["state"] == "unknown" and quantities["current_a"]["reason"] == "silent_in_transaction"
    assert result["measurement"] == "unknown" and quantities["current_a"]["bound_s"] == 180
    states["sensor.current_import"] = _sensor("16", ago(100), unit_of_measurement="A")
    assert _readiness(_world(monkeypatch, states), monitor)["measurement"] == "measured"
    # no transaction expected: an old silent sensor is idle, never a zero value
    states = {"switch.control": _sensor("on", ago(3000)), "sensor.status_connector": _sensor("Available", ago(3000)),
              "sensor.current_import": _sensor("0", ago(700), unit_of_measurement="A")}
    quiet = _readiness(_world(monkeypatch, states), monitor)
    assert quiet["freshness"]["quantities"]["current_a"]["state"] == "idle" and quiet["measurement"] == "unknown"


def test_adaptive_bound_is_read_from_the_evidence_store(monkeypatch):
    from custom_components.spotnav.sessions import evidence

    store = SimpleNamespace(samples=lambda *_a, **_k: rows(*[(300 * n + 100, 300 * n + 100) for n in range(11, 0, -1)]))
    monkeypatch.setattr(evidence, "evidence_for", lambda _hass: store)
    monitor = SimpleNamespace(state="up", since=ago(7200), connection_changed_at=None, connection_id=1)
    states = {"switch.control": _sensor("on", ago(3000)), "sensor.status_connector": _sensor("Charging", ago(3000)),
              "sensor.transaction_id": _sensor("12", ago(3000)),
              "sensor.current_import": _sensor("16", ago(500), unit_of_measurement="A")}
    hass = _world(monkeypatch, states)
    controller = SimpleNamespace(charge_control="switch.control", ocpp_target=SimpleNamespace(connector_id=1))
    result = morek_schedule._session_readiness(hass, controller, {"supported": True, "match_count": 1}, True, NOW,
                                               monitor, "entry")
    current = result["freshness"]["quantities"]["current_a"]
    assert current["state"] == "current" and current["bound_s"] == 900
    assert result["live"]["current_a"]["fresh"] is False  # the strict flag control flow reads is unchanged


# ------------------------------------------------------------------ session observe_initial
def _session(monitor):
    session = MorekSessionCoordinator.__new__(MorekSessionCoordinator)
    session.worker = SimpleNamespace(link_monitor=monitor)
    session.observe = Mock()
    return session


def test_observe_initial_accepts_a_continuous_link_report_but_never_a_pre_seed_one():
    state = SimpleNamespace(state="Preparing", attributes={}, last_reported=ago(600), last_updated=ago(600))
    seeded = SimpleNamespace(state="up", since=ago(3600), connection_changed_at=None, connection_id=1)
    session = _session(seeded)
    session.observe_initial(state, NOW)
    session.observe.assert_called_once()
    restarted = _session(SimpleNamespace(state="up", since=ago(30), connection_changed_at=None, connection_id=1))
    restarted.hass = None
    restarted.observe_initial(state, NOW)  # pre-restart report: falls through to the corroboration path
    restarted.observe.assert_not_called()
    recent = SimpleNamespace(state="Preparing", attributes={}, last_reported=ago(30), last_updated=ago(30))
    boring = _session(None)
    boring.observe_initial(recent, NOW)
    boring.observe.assert_called_once()  # the strict bound still works without a monitor
