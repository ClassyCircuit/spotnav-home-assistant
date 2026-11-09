"""Stored price-policy inputs; no planner or charger behavior is exercised here."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from custom_components.spotnav.api.settings import decode_settings, encode_settings, replacement_mutator
from custom_components.spotnav.api import settings as settings_api
from custom_components.spotnav.planning.auto_settings import (
    AutoSettings,
    AutoSettingsError,
    AutoSettingsStore,
    TargetSocIntent,
)
from custom_components.spotnav.vehicles.vehicle_properties import VehicleProperties


def body(settings):
    return {key: value for key, value in encode_settings(settings).items() if key != "revision"}


def test_legacy_defaults_and_low_target():
    legacy = replace(AutoSettings(), target=TargetSocIntent("car", 20))
    loaded = AutoSettings.from_stored(legacy.as_dict())
    assert (loaded.soft_price_cap, loaded.cap_price_basis, loaded.minimum_ready_by_soc) == (None, None, None)
    assert loaded.target.target_percent == 20


@pytest.mark.parametrize("cap", [None, 0, -0.05, 0.10])
def test_storage_and_wire_roundtrip(cap):
    settings = replace(AutoSettings(), soft_price_cap=cap, cap_price_basis="nord_pool",
                       minimum_ready_by_soc=40, target=TargetSocIntent("car", 80)).validated()
    assert AutoSettings.from_stored(settings.as_dict()) == settings
    assert decode_settings(body(settings)).validated() == settings
    assert encode_settings(settings)["soft_price_cap"] == cap


@pytest.mark.parametrize("field,value", [
    ("soft_price_cap", True), ("soft_price_cap", float("nan")), ("soft_price_cap", float("inf")),
    ("minimum_ready_by_soc", False), ("minimum_ready_by_soc", -1), ("minimum_ready_by_soc", 101),
    ("minimum_ready_by_soc", float("-inf")), ("cap_price_basis", True), ("cap_price_basis", "unknown"),
])
def test_invalid_values_refused(field, value):
    raw = body(AutoSettings())
    raw[field] = value
    with pytest.raises(AutoSettingsError):
        decode_settings(raw)
    with pytest.raises(AutoSettingsError):
        replace(AutoSettings(), **{field: value}).validated()


def test_basis_and_target_relationships():
    with pytest.raises(AutoSettingsError):
        replace(AutoSettings(), soft_price_cap=0).validated()
    with pytest.raises(AutoSettingsError):
        replace(AutoSettings(), minimum_ready_by_soc=41, target=TargetSocIntent("car", 40)).validated()
    # An unknown vehicle target is not invented; the relationship must be checked when it becomes numeric.
    assert replace(AutoSettings(), minimum_ready_by_soc=40).validated().target.target_percent is None
    assert replace(AutoSettings(), soft_price_cap=0.1, cap_price_basis="configured_variable_cost").validated()


def test_ready_by_minimum_does_not_change_immediate_floor():
    vehicle = VehicleProperties(min_percent=25)
    settings = replace(AutoSettings(), minimum_ready_by_soc=40).validated()
    assert settings.minimum_ready_by_soc == 40
    assert vehicle.min_percent == 25


def test_api_body_omission_preserves_policy(monkeypatch):
    current = replace(AutoSettings(), soft_price_cap=0.1, cap_price_basis="nord_pool",
                      minimum_ready_by_soc=40, target=TargetSocIntent("car", 80)).validated()
    raw = body(current)
    for name in ("soft_price_cap", "cap_price_basis", "minimum_ready_by_soc"):
        raw.pop(name)
    raw["amps"] = 10
    monkeypatch.setattr(settings_api, "domain_data", lambda _: SimpleNamespace(auto_store=None))
    monkeypatch.setattr(settings_api.vehicle_properties, "stored_properties", lambda *_: SimpleNamespace(target_percent=None))
    updated = settings_api.body_mutator(None, "charger", raw, decode_settings(raw))(current).validated()
    assert (updated.soft_price_cap, updated.cap_price_basis, updated.minimum_ready_by_soc) == (0.1, "nord_pool", 40)
    assert updated.amps == 10


async def test_store_api_partial_revision_and_vehicle_resolution(hass):
    store = AutoSettingsStore(hass)
    await store.async_load()
    initial = replace(AutoSettings(), soft_price_cap=0.1, cap_price_basis="nord_pool",
                      minimum_ready_by_soc=40, target=TargetSocIntent("old", 80))
    saved = await store.async_update("charger", mutate=lambda _: initial, expected_revision=0)
    reopened = AutoSettingsStore(hass)
    await reopened.async_load()
    assert reopened.settings("charger") == saved

    raw = body(saved)
    raw.pop("cap_price_basis")
    raw.pop("minimum_ready_by_soc")
    raw["soft_price_cap"] = 0
    decoded = decode_settings(raw)
    mutate = replacement_mutator(decoded, keep_cap_price_basis=True, keep_minimum_ready_by_soc=True)
    changed = await store.async_update("charger", mutate=mutate, expected_revision=saved.revision)
    assert (changed.soft_price_cap, changed.cap_price_basis, changed.minimum_ready_by_soc) == (0, "nord_pool", 40)
    with pytest.raises(AutoSettingsError) as conflict:
        await store.async_update("charger", mutate=mutate, expected_revision=saved.revision)
    assert conflict.value.code == "revision_conflict"
    raw = body(changed)
    raw["target"]["vehicle_id"] = "new"
    switch = replacement_mutator(decode_settings(raw), vehicle_target=lambda _: 30)
    with pytest.raises(AutoSettingsError):
        await store.async_update("charger", mutate=switch, expected_revision=changed.revision)
    assert store.settings("charger") == changed
