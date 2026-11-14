"""Stage 15.9a: capture-only energy learning under Morek schedule ownership (mocked, no `hass` fixture, no HA/charger).

The production `AutoPlannerController` capture tick runs against a fake charging controller (the facts it reads:
`known_connected`, `plugged_in_for_count`/`plugged_in_since`, `charging`) and the real `EnergySampler` and
`LearnedEnergyStore`. Planning must never read what is captured."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav.planning import auto_controller, learned_energy
from custom_components.spotnav.planning.auto_controller import AutoPlannerController, LiveVehicleFacts
from custom_components.spotnav.planning.auto_settings import AutoSettings, DRIVER_TARGET_SOC, TargetSocIntent
from custom_components.spotnav.planning.learned_energy import (
    Capture,
    CaptureContext,
    EnergySample,
    EnergySampler,
    LearnedEnergyStore,
    ORIGIN_CAPTURE,
    SocSeen,
    clean_meta,
    parse_stored,
    target_need,
)
from custom_components.spotnav.vehicles.guest import GUEST_VEHICLE_ID

START = datetime(2026, 11, 14, 1, tzinfo=timezone.utc)
CAR = "car-one"
CAPACITY = 77.0
RATIO = CAPACITY / 0.8 / 100.0  # wall kWh per percent
ENTITY = "sensor.energy_register"


class FakeStore:
    """`homeassistant.helpers.storage.Store` stand-in: what was last saved is what loads."""

    saved: dict | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        self.data = FakeStore.saved

    async def async_load(self):
        return self.data

    def async_delay_save(self, producer, _delay) -> None:
        FakeStore.saved = producer()

    async def async_remove(self) -> None:
        FakeStore.saved = None


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    FakeStore.saved = None
    monkeypatch.setattr(learned_energy, "Store", FakeStore)


class World:
    """A charging car at one charger, looked at once a minute through the production capture tick."""

    def __init__(self, monkeypatch, *, owned=True, guest=False, soc=20.0, kw=11.0, store=None, session_store=None):
        self.now = START
        self.owned = owned
        self.soc = soc
        self.kw = kw
        self.register = 1000.0
        self.charging = True
        self.report_lag_s = 30.0
        self.time_basis = "vehicle_timestamp"
        self.estimated = False
        self.capacity = CAPACITY
        self.phases = 3
        self.vehicle = CAR
        self.identified = CAR
        self.source = "vehicle"
        self.plugged = START - timedelta(hours=1)
        self.timers: list = []
        self.created: list = []
        self.les = store or LearnedEnergyStore(MagicMock(), "entry")
        self.controller = SimpleNamespace(
            known_connected=True, plugged_in_for_count=self.plugged, plugged_in_since=self.plugged, charging=True,
            held_off_by_person=False, energy_register_entity_id=ENTITY,
        )
        self.executor = SimpleNamespace(controller=self.controller, paused=False)
        self.hass = MagicMock()
        self.hass.async_create_task = lambda coro: self.created.append(coro) or MagicMock()
        self.hass.states.get = lambda _entity: SimpleNamespace(last_changed=self.now, last_reported=self.now)
        manager = MagicMock()
        manager.schedule_at = lambda when, action: (self.timers.append((when, action)) or (lambda: self.timers.clear()))
        self.settings = AutoSettings(
            revision=1, area_id="SE3", amps=16, driver=DRIVER_TARGET_SOC,
            target=TargetSocIntent(vehicle_id=GUEST_VEHICLE_ID if guest else CAR, target_percent=80),
        )
        store_mock = MagicMock()
        store_mock.settings = lambda _entry: self.settings
        self.planner = AutoPlannerController(
            self.hass, "entry", store_mock, manager, executor=self.executor, vehicle_reader=self.facts,
            now=lambda: self.now, learned_energy=self.les, schedule_owned=self.schedule_owned,
        )
        self.recalculate = self.planner.async_recalculate = AsyncMock()
        self.sessions = session_store
        monkeypatch.setattr(auto_controller, "entry_source_for", lambda *_: None)
        monkeypatch.setattr(auto_controller, "resolved_vehicle_id", lambda *_: self.identified)
        monkeypatch.setattr(auto_controller, "read_energy_register_kwh", lambda *_: self.register)
        monkeypatch.setattr(auto_controller, "effective_phases", lambda *_: self.phases)
        monkeypatch.setattr(auto_controller, "voltage_between_phases_v", lambda *_: 400.0)
        monkeypatch.setattr(self.planner, "_held_by_spotnav", lambda *_: None)
        monkeypatch.setattr(
            auto_controller, "domain_data", lambda _hass: SimpleNamespace(session_store=self.sessions)
        )

    async def schedule_owned(self) -> bool:
        return self.owned

    def facts(self, _vehicle) -> LiveVehicleFacts:
        return LiveVehicleFacts(
            vehicle_id=self.vehicle,
            soc_percent=self.soc - (self.kw / 3600.0 / RATIO * self.report_lag_s if self.charging else 0.0),
            reported_capacity_kwh=self.capacity,
            soc_source=self.source, soc_age_s=self.report_lag_s, soc_estimated=self.estimated,
            soc_report_at=self.now - timedelta(seconds=self.report_lag_s), soc_time_basis=self.time_basis,
        )

    async def minute(self, *, charging: bool = True) -> None:
        """One minute of charging, then the tick (through the production arm/due/task path)."""
        self.now += timedelta(minutes=1)
        self.charging = self.controller.charging = charging
        if charging:
            self.register += self.kw / 60.0
            self.soc += self.kw / 60.0 / RATIO
        await self.tick()

    async def tick(self) -> None:
        self.planner._arm_capture()  # noqa: SLF001 - the publication's hook
        assert len(self.timers) <= 1
        if self.timers:
            _when, action = self.timers.pop()
            action(self.now)
        while self.created:
            await self.created.pop()

    async def run(self, minutes: int) -> None:
        for _ in range(minutes):
            await self.minute()

    def captures(self) -> tuple[Capture, ...]:
        return self.les.captures(CAR)


@pytest.mark.asyncio
async def test_capture_through_morek_ownership_with_two_measured_levels_and_provenance(monkeypatch):
    world = World(monkeypatch)
    await world.run(70)
    captures = world.captures()
    assert len(captures) == 1
    capture = captures[0]
    assert capture.as_dict()["origin"] == ORIGIN_CAPTURE
    assert capture.id == f"plug_in:{world.plugged.isoformat()}"
    assert capture.delta_percent >= 10 and capture.kwh_per_percent == pytest.approx(RATIO, rel=0.03)
    meta = capture.meta
    assert meta["soc_source"] == "vehicle" and meta["soc_time_basis"] == "vehicle_timestamp"
    assert meta["soc_end"] - meta["soc_start"] == pytest.approx(capture.delta_percent)
    assert meta["register_entity"] == ENTITY and meta["register_end_kwh"] > meta["register_start_kwh"]
    assert meta["register_basis_start"] == "interpolated" and meta["register_basis_end"] == "interpolated"
    assert (meta["capacity_kwh"], meta["phases"], meta["voltage_v"]) == (CAPACITY, 3, 400.0)
    assert meta["plug_in_basis"] == "watched"
    # No session store here: late energy is unknown, which is flagged, never clean.
    assert meta["late_energy"] == "unknown" and meta["missing"] == []
    assert meta["quality"]["gaps"] == 0 and meta["quality"]["restarts"] == 0 and meta["quality"]["looks"] > 60
    # Report times, not arrival: the endpoints are 30 s older than the looks that saw them.
    assert datetime.fromisoformat(meta["soc_end_at"]) == capture.at
    assert capture.at <= world.now - timedelta(seconds=30)
    # Capture-only: no replan, no PlanWatch decision, nothing sent; the planner reads nothing of it.
    world.recalculate.assert_not_called()
    assert world.les.learned(CAR, CAPACITY).samples == () and not world.les.learned(CAR, CAPACITY).trusted
    assert world.les.anchor is None and world.les.open is None  # the legacy stretch is never touched


@pytest.mark.asyncio
async def test_wrong_owner_runs_no_sampler_and_clears_a_stretch(monkeypatch):
    world = World(monkeypatch)
    await world.run(5)
    assert world.les.capture_anchor is not None
    world.owned = False
    await world.minute()
    assert world.les.capture_anchor is None and world.les.capture_open is None
    assert world.timers == []  # not re-armed while another owner holds the schedule
    await world.run(1)
    assert world.timers == [] and world.captures() == ()
    # Ownership returning plans again, whose publication arms the tick afresh.
    world.owned = True
    await world.tick()
    assert world.timers  # armed by the publication hook, and the next minute samples again
    await world.run(2)
    assert world.les.capture_anchor is not None


@pytest.mark.asyncio
async def test_unowned_unknown_or_unplugged_arms_nothing(monkeypatch):
    world = World(monkeypatch)
    world.controller.known_connected = None
    world.planner._arm_capture()  # noqa: SLF001
    assert world.timers == []
    world.controller.known_connected = False
    world.planner._arm_capture()  # noqa: SLF001
    assert world.timers == []
    no_store = AutoPlannerController(MagicMock(), "entry", MagicMock(), MagicMock(), executor=world.executor)
    no_store._arm_capture()  # noqa: SLF001
    assert no_store._capture_cancel is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_estimated_or_arrival_stamped_levels_make_no_capture(monkeypatch):
    estimated = World(monkeypatch)
    estimated.estimated = True
    await estimated.run(70)
    assert estimated.captures() == () and estimated.les.capture_anchor is None

    arrival = World(monkeypatch)
    arrival.time_basis = "last_updated"  # HA's state-write time: arrival, not the car's report
    await arrival.run(70)
    assert arrival.captures() == () and arrival.les.capture_anchor is None

    charger = World(monkeypatch)
    charger.source, charger.time_basis = "charger", "last_updated"  # the charger's own level is read live
    await charger.run(70)
    assert len(charger.captures()) == 1 and charger.captures()[0].meta["soc_source"] == "charger"


@pytest.mark.asyncio
async def test_late_cloud_report_pairs_with_the_register_at_its_report_time(monkeypatch):
    world = World(monkeypatch)
    await world.run(20)
    start = world.les.capture_anchor
    assert start is not None
    # The car reports (cloud) 150 s after it made the reading (the freshness limit is 180 s): the existing report-time
    # path (age counts from the report) is the endpoint, never the arrival.
    world.report_lag_s = 150.0
    await world.run(1)
    anchor = world.les.capture_anchor
    assert anchor is not None and anchor.anchor.at == start.anchor.at  # the same stretch continues
    await world.run(45)
    capture = world.captures()[0]
    assert datetime.fromisoformat(capture.meta["soc_end_at"]) == world.now - timedelta(seconds=150)
    assert capture.at == world.now - timedelta(seconds=150)
    assert capture.kwh_per_percent == pytest.approx(RATIO, rel=0.03)


@pytest.mark.asyncio
async def test_guest_changed_capacity_vehicle_or_wiring_discard_the_stretch(monkeypatch):
    guest = World(monkeypatch, guest=True)
    await guest.run(70)
    assert guest.captures() == () and guest.les.capture_anchor is None and guest.timers == []

    for change in ("capacity", "phases", "vehicle", "source"):
        world = World(monkeypatch)
        await world.run(40)
        first = world.les.capture_anchor
        assert first is not None
        if change == "capacity":
            world.capacity = 70.0
        elif change == "phases":
            world.phases = 1
        elif change == "vehicle":
            world.vehicle = world.identified = "car-two"
        else:
            world.source = "charger"
        await world.run(1)
        assert world.les.capture_anchor is None or world.les.capture_anchor.anchor.at != first.anchor.at, change
        await world.run(20)
        # The discarded stretch leaves no capture: only 20 minutes accrued after the change (< the rise needed).
        assert world.captures() == (), change


@pytest.mark.asyncio
async def test_another_car_than_the_identified_one_is_never_captured(monkeypatch):
    world = World(monkeypatch)
    world.identified = "car-two"  # the charger identified another car than the level belongs to
    await world.run(70)
    assert world.captures() == () and world.les.capture_anchor is None


@pytest.mark.asyncio
async def test_pause_hold_not_charging_and_gaps_are_recorded_in_provenance(monkeypatch):
    world = World(monkeypatch)
    await world.run(15)
    world.executor.paused = True
    await world.run(3)
    world.executor.paused = False
    monkeypatch.setattr(world.planner, "_held_by_spotnav", lambda *_: "balancing")
    await world.run(2)
    monkeypatch.setattr(world.planner, "_held_by_spotnav", lambda *_: None)
    world.now += timedelta(minutes=10)  # the tick did not run for ten minutes
    await world.run(1)
    await world.minute(charging=False)
    await world.run(60)
    quality = world.captures()[0].meta["quality"]
    assert quality["paused_looks"] == 3 and quality["held_looks"] == 2
    assert quality["gaps"] == 1 and quality["max_gap_s"] >= 600 and quality["not_charging_looks"] == 1


@pytest.mark.asyncio
async def test_restart_and_unload_do_not_duplicate_captures_or_leak_timers(monkeypatch):
    world = World(monkeypatch)
    await world.run(30)
    world.planner._arm_capture()  # noqa: SLF001
    world.planner._arm_capture()  # noqa: SLF001
    assert len(world.timers) == 1  # one appointment however often it is asked for
    # A due callback while a tick is still running does not start another.
    world.planner._capture_running = True  # noqa: SLF001
    world.planner._on_capture_due(world.now)  # noqa: SLF001
    assert world.created == []
    world.planner._capture_running = False  # noqa: SLF001
    # Restart: a new process reads what was saved; the stretch resumes once, counted as a restart.
    FakeStore.saved = world.les._to_store()  # noqa: SLF001
    world.les._store.async_delay_save = lambda *_: None  # noqa: SLF001
    reloaded = LearnedEnergyStore(MagicMock(), "entry")
    await reloaded.async_load()
    assert reloaded.capture_anchor is not None and reloaded.capture_open is not None
    assert reloaded.capture_anchor.meta["quality"]["restarts"] == 0
    fresh = World(monkeypatch, store=reloaded)
    fresh.now, fresh.register, fresh.soc = world.now, world.register, world.soc
    await fresh.run(1)
    assert fresh.les.capture_anchor is not None and fresh.les.capture_anchor.meta["quality"]["restarts"] == 1
    await fresh.run(45)
    assert len(fresh.captures()) == 1
    assert fresh.captures()[0].meta["quality"]["restarts"] == 1
    # Unload: the appointment is cancelled and a late callback does nothing.
    fresh.planner._state_only = AsyncMock()  # noqa: SLF001 - the shutdown's final snapshot needs a real executor
    fresh.planner._publish = MagicMock()  # noqa: SLF001
    await fresh.planner.async_shutdown()
    assert fresh.timers == [] and fresh.planner._capture_cancel is None  # noqa: SLF001
    count = len(fresh.les.captures(CAR))
    fresh.planner._on_capture_due(fresh.now)  # noqa: SLF001
    assert fresh.created == [] and len(fresh.les.captures(CAR)) == count
    fresh.planner._arm_capture()  # noqa: SLF001
    assert fresh.timers == []


@pytest.mark.asyncio
async def test_capture_error_never_blocks_and_the_tick_never_replans_or_sends(monkeypatch):
    world = World(monkeypatch)
    monkeypatch.setattr(world.planner, "_read_energy_register", MagicMock(side_effect=RuntimeError("boom")))
    await world.run(3)  # logged at debug, swallowed
    assert world.captures() == ()
    monkeypatch.undo()
    world.recalculate.assert_not_called()
    assert not world.planner._watch.last_check  # noqa: SLF001 - PlanWatch never ran


# --------------------------------------------------------------------------------------------- late energy metadata
def _session(start, end, late):
    return SimpleNamespace(start=start, end=end, late=late, unplaced_late_kwh=(
        late["unplaced_late_kwh"] if late and late.get("state") == "reconciled" else None
    ))


@pytest.mark.asyncio
async def test_unassigned_late_energy_is_flagged_not_clean(monkeypatch):
    def run_with(sessions):
        store = SimpleNamespace(all_sessions=lambda _entry: sessions)
        return World(monkeypatch, session_store=store)

    a, b = START, START + timedelta(hours=3)
    cases = {
        "uncertain": ([_session(a, b, {"state": "uncertain", "unplaced_late_kwh": None})], "uncertain"),
        "unplaced": ([_session(a, b, {"state": "reconciled", "unplaced_late_kwh": 2.0})], "unplaced"),
        "clean": ([_session(a, b, {"state": "consistent", "unplaced_late_kwh": 0.0})], "clean"),
        "unevaluated": ([_session(a, b, None)], "unknown"),
        "none": ([], "unknown"),
    }
    for name, (sessions, expected) in cases.items():
        world = run_with(sessions)
        assert world.planner._capture_late_energy(a, b) == expected, name  # noqa: SLF001
    # No session store at all: unknown, and a failing lookup is unknown too.
    world = World(monkeypatch)
    assert world.planner._capture_late_energy(a, b) == "unknown"  # noqa: SLF001
    bad = World(monkeypatch, session_store=SimpleNamespace(all_sessions=MagicMock(side_effect=ValueError)))
    sampler = bad.planner._capture_sampler  # noqa: SLF001
    assert isinstance(sampler, EnergySampler)
    await bad.run(70)
    assert bad.captures()[0].meta["late_energy"] == "unknown"


@pytest.mark.asyncio
async def test_capture_records_the_late_energy_state_of_its_stretch(monkeypatch):
    store = SimpleNamespace(all_sessions=lambda _entry: [
        _session(START - timedelta(hours=1), None, {"state": "uncertain", "unplaced_late_kwh": None}),
    ])
    world = World(monkeypatch, session_store=store)
    await world.run(70)
    assert world.captures()[0].meta["late_energy"] == "uncertain"


# ------------------------------------------------------------------------------ store: load, migration, retention
def _meta(**changes):
    meta = {
        "v": 1, "soc_source": "vehicle", "soc_time_basis": "vehicle_timestamp", "soc_start": 20.0, "soc_end": 35.0,
        "soc_start_at": START.isoformat(), "soc_end_at": (START + timedelta(hours=1)).isoformat(),
        "register_entity": ENTITY, "register_start_kwh": 1000.0, "register_end_kwh": 1014.5,
        "register_basis_start": "interpolated", "register_basis_end": "held", "capacity_kwh": CAPACITY, "phases": 3,
        "voltage_v": 400.0, "plug_in_basis": "watched", "late_energy": "unknown",
        "quality": {k: 0 for k in learned_energy._QUALITY_KEYS},  # noqa: SLF001
    }
    meta.update(changes)
    return meta


def _capture_dict(index=0, **meta):
    return {
        "origin": ORIGIN_CAPTURE, "id": f"plug_in:{index}", "kwh": 14.5, "delta_percent": 15.0,
        "at": (START + timedelta(days=index)).isoformat(), "meta": _meta(**meta),
    }


def _legacy(index=0):
    return {"id": f"plug_in:old{index}", "kwh": 14.5, "delta_percent": 15.0,
            "at": (START + timedelta(days=index)).isoformat()}


@pytest.mark.asyncio
async def test_old_files_load_and_captures_round_trip_beside_legacy_samples():
    FakeStore.saved = {"vehicles": {CAR: {"samples": [_legacy(0), _legacy(1), _legacy(2)], "discarded": 2}}}
    store = LearnedEnergyStore(MagicMock(), "entry")
    await store.async_load()
    legacy = store.learned(CAR, CAPACITY)
    assert len(legacy.samples) == 3 and legacy.discarded == 2 and store.captures(CAR) == ()
    assert store.capture_anchor is None and store.capture_open is None
    capture = Capture.from_stored(_capture_dict(0))
    assert capture is not None
    store.put_capture(CAR, capture, CAPACITY)
    saved = FakeStore.saved
    assert saved is not None and saved["vehicles"][CAR]["captures"][0]["origin"] == ORIGIN_CAPTURE
    again = LearnedEnergyStore(MagicMock(), "entry")
    await again.async_load()
    assert again.captures(CAR)[0].id == capture.id
    assert again.learned(CAR, CAPACITY) == legacy  # the legacy view is exactly the same


@pytest.mark.asyncio
async def test_malformed_origin_quality_and_tagged_samples_fail_closed():
    good = _capture_dict(0)
    bad_origin = {**_capture_dict(1), "origin": "legacy"}
    no_origin = {k: v for k, v in _capture_dict(2).items() if k != "origin"}
    bad_quality = _capture_dict(3, quality={"looks": "x"})
    missing_quality = _capture_dict(4)
    del missing_quality["meta"]["quality"]
    bad_version = _capture_dict(5, v=2)
    FakeStore.saved = {"vehicles": {CAR: {
        # A capture smuggled into the legacy samples (tagged) must never be trusted by the planner.
        "samples": [_legacy(0), _capture_dict(6), {**_legacy(1), "origin": None}],
        "captures": [good, bad_origin, no_origin, bad_quality, missing_quality, bad_version, "junk", None],
    }}, "capture": {"anchor": {"anchor": {"vehicle_id": CAR}, "meta": {}}, "open": {"vehicle_id": 5}}}
    store = LearnedEnergyStore(MagicMock(), "entry")
    await store.async_load()
    assert [c.id for c in store.captures(CAR)] == ["plug_in:0"]
    assert [s.id for s in store.learned(CAR, CAPACITY).samples] == ["plug_in:old0"]
    assert store.capture_anchor is None and store.capture_open is None
    assert EnergySample.from_stored({**_legacy(), "origin": ORIGIN_CAPTURE}) is None
    assert clean_meta({**_meta(), "quality": {**_meta()["quality"], "extra": 1}}) is None


def test_missing_metadata_is_allowed_but_listed_for_the_promotion_to_reject():
    meta = clean_meta(_meta(capacity_kwh=None, late_energy="surely", plug_in_basis=None, soc_end_at="nope"))
    assert meta is not None
    assert set(meta["missing"]) == {"capacity_kwh", "late_energy", "plug_in_basis", "soc_end_at"}
    # `missing` is recomputed on load, never taken from the file.
    forged = clean_meta({**_meta(capacity_kwh=None), "missing": []})
    assert forged is not None and forged["missing"] == ["capacity_kwh"]


@pytest.mark.asyncio
async def test_retention_is_bounded_by_count_and_age():
    store = LearnedEnergyStore(MagicMock(), "entry")
    for index in range(20):
        capture = Capture.from_stored(_capture_dict(index))
        assert capture is not None
        store.put_capture(CAR, capture, CAPACITY)
    kept = store.captures(CAR)
    assert len(kept) == learned_energy.MAX_CAPTURES and kept[-1].id == "plug_in:19"
    far = Capture.from_stored(_capture_dict(400))  # 400 days later: all earlier ones are older than 120 days
    assert far is not None
    store.put_capture(CAR, far, CAPACITY)
    assert [c.id for c in store.captures(CAR)] == ["plug_in:400"]
    # Out of bounds (an efficiency over 1.0 for the battery) is not kept and is counted.
    wrong = Capture.from_stored({**_capture_dict(401), "kwh": 1.0, "delta_percent": 15.0})
    assert wrong is not None
    assert store.put_capture(CAR, wrong, CAPACITY) is False
    assert store.learned(CAR, CAPACITY).discarded == 0  # the legacy counter is untouched
    assert FakeStore.saved["vehicles"][CAR]["captures_discarded"] == 1


@pytest.mark.asyncio
async def test_planner_input_is_identical_with_and_without_many_captures(monkeypatch):
    world = World(monkeypatch)
    facts = world.facts(CAR)
    # A legacy trusted figure exists; captures wildly different from it must not move anything the planner reads.
    for index in range(3):
        world.les.put(CAR, EnergySample(f"plug_in:old{index}", 14.5 + index * 0.1, 15.0, START + timedelta(days=index)),
                      CAPACITY)
    before = world.planner._learned_energy_for(facts, drop=True)  # noqa: SLF001
    need_before = target_need(before, soc_percent=30.0, capacity_kwh=CAPACITY, target_percent=80.0)
    default_before = target_need(
        world.les.learned("nobody", CAPACITY), soc_percent=30.0, capacity_kwh=CAPACITY, target_percent=80.0
    )
    for index in range(30):
        capture = Capture.from_stored({**_capture_dict(index), "kwh": 5.0 + index, "delta_percent": 15.0})
        assert capture is not None
        world.les.put_capture(CAR, capture, CAPACITY)
    await world.run(70)
    assert world.captures()
    after = world.planner._learned_energy_for(facts, drop=True)  # noqa: SLF001
    assert after == before and after.as_dict() == before.as_dict()
    assert target_need(after, soc_percent=30.0, capacity_kwh=CAPACITY, target_percent=80.0) == need_before
    # No learned figure at all: the planner keeps the default, with captures present.
    empty = World(monkeypatch)
    for index in range(10):
        capture = Capture.from_stored(_capture_dict(index))
        assert capture is not None
        empty.les.put_capture(CAR, capture, CAPACITY)
    assert empty.planner._learned_energy_for(facts) == learned_energy.learned_from(CAR, [])  # noqa: SLF001
    assert target_need(
        empty.planner._learned_energy_for(facts), soc_percent=30.0, capacity_kwh=CAPACITY, target_percent=80.0  # noqa: SLF001
    ) == default_before
    # The legacy sampler's own stretch and parse are unaffected by the capture block.
    cars, anchor, plug = parse_stored(world.les._to_store())  # noqa: SLF001
    assert anchor is None and plug is None and set(cars) == {CAR}


@pytest.mark.asyncio
async def test_capture_sampler_does_not_touch_the_legacy_sampler_path(monkeypatch):
    sampler = EnergySampler(LearnedEnergyStore(MagicMock(), "entry"))
    context = CaptureContext(ENTITY, 3, 400.0, "watched", False, False, START - timedelta(seconds=10),
                             "vehicle_timestamp")
    sampler.observe_capture(
        START, vehicle_id=CAR, session="plug_in:1",
        soc=SocSeen(30.0, 10.0, False, "vehicle"), register_kwh=5.0, register_posted_at=START,
        capacity_kwh=CAPACITY, charging=True, context=context,
    )
    store = sampler._store  # noqa: SLF001
    assert store.anchor is None and store.open is None
    assert store.capture_open == (CAR, "plug_in:1")
    assert FakeStore.saved is None or "samples" in FakeStore.saved["vehicles"].get(CAR, {"samples": []})
