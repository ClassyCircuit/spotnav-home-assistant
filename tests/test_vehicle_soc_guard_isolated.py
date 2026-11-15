"""Real `async_set_vehicle_soc` / `async_update_vehicle` and the services' handlers, HA boundaries faked.

Runs under `tools/run_isolated_logs_tests.py` (no `hass` fixture; the HA pytest plugin cannot load on Windows).
The faked boundaries are the charger lookup, the device scan, the decision store and the planners; the lock,
compare-and-set, replan decision and refusal paths are the production code.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav import services
from custom_components.spotnav.api import entity_config as ec
from custom_components.spotnav.vehicles import vehicle_properties as vp

CAR, SOC, HEALTH = "car-a", "sensor.soc", "sensor.health"


class World:
    """One ambiguous car; the saved choice changes only after a real suspension, like the file-backed store."""

    def __init__(self) -> None:
        self.saved: str | None = None
        self.writes: list[str | None] = []
        self.hass = SimpleNamespace(data={}, async_create_task=lambda coro, **kw: asyncio.ensure_future(coro))
        self.replans = 0

    def choices(self, _hass):
        return [SimpleNamespace(id=CAR, selected_entity_id=self.saved, source="confirmed" if self.saved else None)]

    async def record(self, _hass, _store, _vid, entity_id):
        for _ in range(3):  # several suspensions, like the file-backed store's awaits
            await asyncio.sleep(0)
        self.saved = entity_id
        self.writes.append(entity_id)

    async def clear(self, _hass, _store, _vid):
        for _ in range(3):
            await asyncio.sleep(0)
        self.saved = None
        self.writes.append(None)


@pytest.fixture
def world(monkeypatch):
    w = World()
    controller = MagicMock()

    async def recalc():
        w.replans += 1

    controller.async_recalculate = recalc
    monkeypatch.setattr(ec, "_resolve_charger", lambda hass, cid: SimpleNamespace(entry_id="c1"))
    monkeypatch.setattr(ec, "read_entity_config", lambda hass, charger: {"cfg": True})
    monkeypatch.setattr(ec, "soc_choices", w.choices)
    monkeypatch.setattr(ec, "domain_data", lambda hass: SimpleNamespace(decision_store=object()))
    monkeypatch.setattr(ec, "valid_soc_choice", lambda hass, vid, eid: eid in (SOC, HEALTH))
    monkeypatch.setattr(ec, "async_record_vehicle_soc", w.record)
    monkeypatch.setattr(ec, "async_clear_vehicle_soc", w.clear)
    monkeypatch.setattr(ec, "_planner_entry_ids", lambda hass, vid: {"c1"})
    monkeypatch.setattr(ec, "preview_for", lambda hass, entry_id: controller)
    return w


async def drain():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_overlapping_guarded_saves_one_winner_one_conflict_no_second_write(world):
    results = await asyncio.gather(
        ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC, expected_entity_id=None),
        ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=HEALTH, expected_entity_id=None),
        return_exceptions=True,
    )
    assert results[0] == {"cfg": True}
    assert isinstance(results[1], ec.EntityConfigRefusal) and results[1].code == ec.ERROR_CONFLICT
    assert world.writes == [SOC] and world.saved == SOC
    await drain()
    assert world.replans == 1


async def test_matching_expectation_writes_stale_one_conflicts_malformed_is_invalid_legacy_still_writes(world):
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC, expected_entity_id=None)
    with pytest.raises(ec.EntityConfigRefusal) as stale:
        await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=HEALTH, expected_entity_id=None)
    assert stale.value.code == ec.ERROR_CONFLICT and world.writes == [SOC]
    for bad in (7, ""):
        with pytest.raises(ec.EntityConfigRefusal) as invalid:
            await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=HEALTH, expected_entity_id=bad)
        assert invalid.value.code == ec.ERROR_INVALID_VALUE
    assert world.writes == [SOC]
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=HEALTH, expected_entity_id=SOC)
    assert world.saved == HEALTH
    # Legacy caller: no expectation at all, unconditional write.
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC)
    assert world.saved == SOC and world.writes == [SOC, HEALTH, SOC]
    # Clearing is guarded the same way.
    with pytest.raises(ec.EntityConfigRefusal):
        await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=None, expected_entity_id=HEALTH)
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=None, expected_entity_id=SOC)
    assert world.saved is None


async def test_real_selection_change_replans_once_and_an_unchanged_selection_not_at_all(world):
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC)
    await drain()
    assert world.replans == 1
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC)
    await drain()
    assert world.replans == 1  # same sensor again: no replan
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=None)
    await drain()
    assert world.replans == 2
    await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=None)  # clearing nothing
    await drain()
    assert world.replans == 2


async def test_invalid_entity_writes_nothing(world):
    with pytest.raises(ec.EntityConfigRefusal) as refused:
        await ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id="sensor.other")
    assert refused.value.code == ec.ERROR_INVALID_VALUE and world.writes == []


async def test_confirm_service_takes_the_same_lock_so_it_cannot_interleave_with_a_guarded_save(world, monkeypatch):
    store = object()
    monkeypatch.setattr(services, "_decision_store_or_warn", lambda hass, call: store)
    monkeypatch.setattr(services, "valid_soc_entity_id", lambda hass, d, e: True)
    monkeypatch.setattr(services, "async_record_vehicle_soc", world.record)
    call = SimpleNamespace(data={"device_id": CAR, "entity_id": HEALTH})

    # The service starts first and suspends inside its write (holding the lock); a guarded save expecting "no
    # choice" must wait for it and then see HEALTH saved: a conflict, never a lost overwrite.
    service = asyncio.ensure_future(services._async_confirm_vehicle_soc(world.hass, call))
    await asyncio.sleep(0)
    guarded = asyncio.ensure_future(
        ec.async_set_vehicle_soc(world.hass, "c1", vehicle_id=CAR, entity_id=SOC, expected_entity_id=None)
    )
    done = await asyncio.gather(service, guarded, return_exceptions=True)
    assert isinstance(done[1], ec.EntityConfigRefusal) and done[1].code == ec.ERROR_CONFLICT
    assert world.saved == HEALTH and world.writes == [HEALTH]


# --- async_update_vehicle: compare-and-set on a vehicle with no chosen/ambiguous sensor ------------------------


@pytest.fixture
def props(monkeypatch):
    w = World()
    stored = {"p": vp.VehicleProperties()}
    updated = []

    async def fake_update(hass, store, vid, changes):
        updated.append(dict(changes))
        stored["p"] = vp.VehicleProperties(
            capacity_kwh=changes.get("capacity_kwh", stored["p"].capacity_kwh),
            onboard_phases=changes.get("onboard_phases", stored["p"].onboard_phases),
        )
        return stored["p"]

    monkeypatch.setattr(ec, "_resolve_charger", lambda hass, cid: SimpleNamespace(entry_id="c1"))
    monkeypatch.setattr(ec, "read_entity_config", lambda hass, charger: {"cfg": True})
    monkeypatch.setattr(ec, "soc_choices", w.choices)
    monkeypatch.setattr(ec, "domain_data", lambda hass: SimpleNamespace(decision_store=object()))
    monkeypatch.setattr(ec, "_vehicle_row", lambda hass, entry_id, vid: None)  # ambiguous car: no dashboard row
    monkeypatch.setattr(ec, "wake_supported", lambda hass, vid: False)
    monkeypatch.setattr(vp, "stored_properties", lambda hass, vid: stored["p"])
    monkeypatch.setattr(vp, "async_update_vehicle_properties", fake_update)
    monkeypatch.setattr(ec, "_recalculate_planners_for", AsyncMock())
    w.updated, w.stored = updated, stored
    return w


async def test_update_vehicle_without_row_compares_against_stored_values_and_writes_once(props):
    # Stored/unset: capacity None, phases None (row falls back to the stored `phases`).
    with pytest.raises(ec.EntityConfigRefusal) as stale:
        await ec.async_update_vehicle(
            props.hass, "c1", vehicle_id=CAR, changes={"capacity_kwh": 60}, expected={"capacity_kwh": 50}
        )
    assert stale.value.code == ec.ERROR_CONFLICT and props.updated == []
    config, row = await ec.async_update_vehicle(
        props.hass, "c1", vehicle_id=CAR, changes={"capacity_kwh": 60}, expected={"capacity_kwh": None}
    )
    assert config == {"cfg": True} and row is None
    assert props.updated == [{"capacity_kwh": 60}] and props.stored["p"].capacity_kwh == 60
    ec._recalculate_planners_for.assert_awaited_once()
    # The second identical-expectation write now conflicts (it moved to 60): nothing more is written.
    with pytest.raises(ec.EntityConfigRefusal):
        await ec.async_update_vehicle(
            props.hass, "c1", vehicle_id=CAR, changes={"capacity_kwh": 70}, expected={"capacity_kwh": None}
        )
    assert props.updated == [{"capacity_kwh": 60}]


async def test_update_vehicle_unknown_vehicle_and_invalid_changes_write_nothing(props):
    with pytest.raises(ec.EntityConfigRefusal):
        await ec.async_update_vehicle(props.hass, "c1", vehicle_id="nope", changes={"capacity_kwh": 60}, expected=None)
    with pytest.raises(ec.EntityConfigRefusal) as invalid:
        await ec.async_update_vehicle(props.hass, "c1", vehicle_id=CAR, changes={"capacity_kwh": -5}, expected=None)
    assert invalid.value.code == ec.ERROR_INVALID_VALUE and props.updated == []
