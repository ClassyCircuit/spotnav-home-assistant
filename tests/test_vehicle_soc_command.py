"""`spotnav/choose_vehicle_soc`: the card's way to choose (or forget) a vehicle's state-of-charge
sensor, recorded as the very same discovery decision the `confirm_vehicle_soc` service and the
config flow's `resolve_vehicle` step record -- one store, one payload shape.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.spotnav.const import DOMAIN
from custom_components.spotnav.vehicles.discovery_decisions import DECISION_DOMAIN_VEHICLE
from custom_components.spotnav.api.entity_config import ENTITY_CONFIG_API_VERSION
from custom_components.spotnav.vehicles.vehicle_discovery import (
    discover_ambiguous_vehicles,
    discover_vehicles,
)
from tests.helpers import add_ambiguous_vehicle_device
from tests.messages import field, get_message
from tests.world import setup_charger_and_site
from tests.world import admin, non_admin, ws_call
from custom_components.spotnav.runtime import domain_data


def set_message(
    charger_id: Any, vehicle_id: Any, entity_id: Any, api_version: Any = ENTITY_CONFIG_API_VERSION
) -> dict[str, Any]:
    return {
        "type": "spotnav/choose_vehicle_soc",
        "api_version": api_version,
        "charger_id": charger_id,
        "vehicle_id": vehicle_id,
        "entity_id": entity_id,
    }


def confirmed(hass: HomeAssistant, device_id: str) -> dict[str, Any] | None:
    return domain_data(hass).decision_store.confirmed_payload(DECISION_DOMAIN_VEHICLE, device_id)


async def test_get_lists_each_vehicle_with_its_candidates_and_says_it_is_settable(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    client = await admin(hass, hass_ws_client)

    result = (await ws_call(client, get_message(charger.entry_id)))["result"]

    assert field(result, "vehicle_soc")["writable"] is False  # still not an `update_entity_config` field
    assert result["config"]["vehicles"] == [
        {
            "id": device_id,
            "name": "Volvo",
            "selected": None,
            "source": None,
            "candidates": [
                {"entity_id": soc, "friendly_name": "pack a"},
                {"entity_id": health, "friendly_name": "pack b"},
            ],
        }
    ]


async def test_a_confirmation_is_the_discovery_decision_and_makes_the_vehicle_readable(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(
        hass, unique_id="car-a", name="Volvo", soc_percent="42", health_percent="96"
    )
    assert [c.id for c in discover_ambiguous_vehicles(hass)] == [device_id]
    assert discover_vehicles(hass) == []
    client = await admin(hass, hass_ws_client)

    result = (await ws_call(client, set_message(charger.entry_id, device_id, soc)))["result"]

    assert result["ok"] is True and result["error"] is None
    assert confirmed(hass, device_id) == {"soc_entity_id": soc}
    (vehicle,) = result["config"]["vehicles"]
    assert vehicle["source"] == "confirmed" and vehicle["selected"]["entity_id"] == soc
    assert [v.soc_percent for v in discover_vehicles(hass)] == [42.0]
    assert discover_ambiguous_vehicles(hass) == []


async def test_the_service_and_the_command_write_the_same_decision(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    await hass.services.async_call(
        DOMAIN, "confirm_vehicle_soc", {"device_id": device_id, "entity_id": soc}, blocking=True
    )
    by_service = confirmed(hass, device_id)
    await domain_data(hass).decision_store.async_unconfirm(DECISION_DOMAIN_VEHICLE, device_id)

    await ws_call(await admin(hass, hass_ws_client), set_message(charger.entry_id, device_id, soc))

    assert confirmed(hass, device_id) == by_service == {"soc_entity_id": soc}


async def test_null_returns_a_vehicle_to_automatic_detection(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    client = await admin(hass, hass_ws_client)
    await ws_call(client, set_message(charger.entry_id, device_id, soc))

    result = (await ws_call(client, set_message(charger.entry_id, device_id, None)))["result"]

    assert result["ok"] is True
    assert confirmed(hass, device_id) is None
    (vehicle,) = result["config"]["vehicles"]
    assert vehicle["selected"] is None and vehicle["source"] is None
    assert [c.id for c in discover_ambiguous_vehicles(hass)] == [device_id]


async def test_a_vehicle_that_already_reads_can_be_changed_and_two_vehicles_are_independent(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    first, first_soc, first_health = add_ambiguous_vehicle_device(
        hass, unique_id="car-a", name="Volvo"
    )
    second, second_soc, _ = add_ambiguous_vehicle_device(hass, unique_id="car-b", name="Tesla")
    client = await admin(hass, hass_ws_client)
    await ws_call(client, set_message(charger.entry_id, first, first_soc))

    changed = (await ws_call(client, set_message(charger.entry_id, first, first_health)))["result"]

    assert confirmed(hass, first) == {"soc_entity_id": first_health}
    row = next(v for v in changed["config"]["vehicles"] if v["id"] == first)
    assert row["selected"]["entity_id"] == first_health and row["source"] == "confirmed"
    assert confirmed(hass, second) is None

    await ws_call(client, set_message(charger.entry_id, second, second_soc))
    assert confirmed(hass, first) == {"soc_entity_id": first_health}
    assert confirmed(hass, second) == {"soc_entity_id": second_soc}


async def test_refusals_carry_a_field_code_and_write_nothing(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    other, other_soc, _ = add_ambiguous_vehicle_device(hass, unique_id="car-b", name="Tesla")
    range_id = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("sensor")
        if entity_id.endswith("_range") or entity_id == "sensor.range"
    )
    client = await admin(hass, hass_ws_client)

    for vehicle, entity, code in (
        ("no-such-device", soc, "unknown_vehicle"),
        (None, soc, "unknown_vehicle"),
        (device_id, range_id, "entity_not_found"),
        (device_id, "sensor.ghost", "entity_not_found"),
        (device_id, 7, "entity_not_found"),
    ):
        result = (await ws_call(client, set_message(charger.entry_id, vehicle, entity)))["result"]
        assert result["ok"] is False and result["error"] == "spotnav_invalid_value"
        assert result["field_errors"] == [{"field": "vehicle_soc", "code": code}]
    assert confirmed(hass, device_id) is None
    assert other != device_id and other_soc


async def test_a_dismissed_vehicle_is_not_offered_and_not_writable(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    await domain_data(hass).decision_store.async_dismiss(DECISION_DOMAIN_VEHICLE, device_id)
    client = await admin(hass, hass_ws_client)

    listed = (await ws_call(client, get_message(charger.entry_id)))["result"]
    result = (await ws_call(client, set_message(charger.entry_id, device_id, soc)))["result"]

    assert listed["config"]["vehicles"] == []
    assert result["field_errors"] == [{"field": "vehicle_soc", "code": "unknown_vehicle"}]


async def test_only_an_administrator_may_choose_and_the_charger_must_exist(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token: str
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")

    denied = (
        await ws_call(
            await non_admin(hass, hass_ws_client, hass_read_only_access_token),
            set_message(charger.entry_id, device_id, soc),
        )
    )["result"]
    assert denied["error"] == "spotnav_not_admin" and denied["config"] is None
    assert confirmed(hass, device_id) is None

    missing = (
        await ws_call(await admin(hass, hass_ws_client), set_message("nope", device_id, soc))
    )["result"]
    assert missing["ok"] is False and missing["error"] == "spotnav_unknown_charger"
    assert confirmed(hass, device_id) is None


async def test_an_unsupported_version_is_refused(hass: HomeAssistant, hass_ws_client) -> None:
    charger, _ = await setup_charger_and_site(hass)
    frame = await ws_call(
        await admin(hass, hass_ws_client), set_message(charger.entry_id, "x", None, api_version=9)
    )
    assert frame["success"] is False
    assert frame["error"]["code"] == "spotnav_unsupported_api_version"


async def test_expected_selection_guard_conflicts_without_writing_and_legacy_callers_still_write(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    client = await admin(hass, hass_ws_client)

    # Expecting "no choice" while one exists is a conflict; nothing is written.
    first = (await ws_call(client, {**set_message(charger.entry_id, device_id, soc), "expected_entity_id": None}))["result"]
    assert first["ok"] is True and confirmed(hass, device_id) == {"soc_entity_id": soc}
    stale = (await ws_call(client, {**set_message(charger.entry_id, device_id, health), "expected_entity_id": None}))["result"]
    assert stale["ok"] is False and stale["error"] == "spotnav_conflict"
    assert confirmed(hass, device_id) == {"soc_entity_id": soc}
    # The matching expectation writes; a malformed one is invalid; omitting it keeps the legacy write.
    match = (await ws_call(client, {**set_message(charger.entry_id, device_id, health), "expected_entity_id": soc}))["result"]
    assert match["ok"] is True and confirmed(hass, device_id) == {"soc_entity_id": health}
    bad = (await ws_call(client, {**set_message(charger.entry_id, device_id, soc), "expected_entity_id": 7}))["result"]
    assert bad["error"] == "spotnav_invalid_value" and confirmed(hass, device_id) == {"soc_entity_id": health}
    legacy = (await ws_call(client, set_message(charger.entry_id, device_id, soc)))["result"]
    assert legacy["ok"] is True and confirmed(hass, device_id) == {"soc_entity_id": soc}


async def test_two_interleaved_guarded_writes_leave_one_winner_and_one_conflict(hass: HomeAssistant) -> None:
    import asyncio

    from custom_components.spotnav.api.entity_config import EntityConfigRefusal, async_set_vehicle_soc

    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")

    results = await asyncio.gather(
        async_set_vehicle_soc(hass, charger.entry_id, vehicle_id=device_id, entity_id=soc, expected_entity_id=None),
        async_set_vehicle_soc(hass, charger.entry_id, vehicle_id=device_id, entity_id=health, expected_entity_id=None),
        return_exceptions=True,
    )

    assert sum(isinstance(r, EntityConfigRefusal) and r.code == "spotnav_conflict" for r in results) == 1
    assert sum(isinstance(r, dict) for r in results) == 1
    assert confirmed(hass, device_id) == {"soc_entity_id": soc}  # the first to take the lock


async def test_an_actual_selection_change_replans_planners_and_a_no_op_does_not(hass: HomeAssistant) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.spotnav.api import entity_config
    from custom_components.spotnav.api.entity_config import async_set_vehicle_soc

    charger, _ = await setup_charger_and_site(hass)
    device_id, soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    controller = MagicMock()
    controller.async_recalculate = AsyncMock()
    with patch.object(entity_config, "preview_for", return_value=controller), patch.object(
        entity_config, "_planner_entry_ids", return_value={charger.entry_id}
    ):
        await async_set_vehicle_soc(hass, charger.entry_id, vehicle_id=device_id, entity_id=soc)
        await hass.async_block_till_done()
        assert controller.async_recalculate.await_count == 1
        await async_set_vehicle_soc(hass, charger.entry_id, vehicle_id=device_id, entity_id=soc)
        await hass.async_block_till_done()
        assert controller.async_recalculate.await_count == 1  # same sensor again: nothing to replan


async def test_properties_are_listed_and_writable_for_a_vehicle_without_a_chosen_sensor(
    hass: HomeAssistant, hass_ws_client
) -> None:
    charger, _ = await setup_charger_and_site(hass)
    device_id, _soc, _health = add_ambiguous_vehicle_device(hass, unique_id="car-a", name="Volvo")
    client = await admin(hass, hass_ws_client)

    config = (await ws_call(client, get_message(charger.entry_id)))["result"]["config"]
    assert config["vehicle_properties"] == [
        {
            "id": device_id,
            "capacity_kwh": None,
            "capacity_source": None,
            "reported_capacity_kwh": None,
            "reported_known": False,
            "stored_capacity_kwh": None,
            "onboard_phases": 3,
            "stored_onboard_phases": None,
        }
    ]
    update = {
        "type": "spotnav/update_vehicle",
        "api_version": ENTITY_CONFIG_API_VERSION,
        "charger_id": charger.entry_id,
        "vehicle_id": device_id,
        "changes": {"capacity_kwh": 60, "onboard_phases": 1},
        "expected": {"capacity_kwh": None, "onboard_phases": 3},
    }
    stale = (await ws_call(client, {**update, "expected": {"capacity_kwh": 50}}))["result"]
    assert stale["error"] == "spotnav_conflict"
    ok = (await ws_call(client, update))["result"]
    assert ok["ok"] is True
    row = ok["config"]["vehicle_properties"][0]
    assert row["stored_capacity_kwh"] == 60 and row["capacity_source"] == "stored" and row["stored_onboard_phases"] == 1
