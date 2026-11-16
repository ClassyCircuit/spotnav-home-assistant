"""Stage 18.3: the sole configured eligible car is the car, with no "which car" question.

Real `resolve_target_vehicle` and a real `VehicleIdentifier` plug-in decision on a fake Home Assistant: only the
registry scan (`soc_choices`), the settings store, the notifier and the timers are faked. No HA, charger or car.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.spotnav.vehicles import identification as ident
from custom_components.spotnav.vehicles import vehicle_discovery as discovery
from custom_components.spotnav.vehicles.guest import GUEST_VEHICLE_ID
from custom_components.spotnav.vehicles.vehicle_discovery import VehicleSocChoice, resolve_target_vehicle


def choice(vehicle_id: str, *, resolved: bool = True) -> VehicleSocChoice:
    return VehicleSocChoice(vehicle_id, vehicle_id.upper(), [f"sensor.{vehicle_id}_soc"],
                            f"sensor.{vehicle_id}_soc" if resolved else None, "automatic" if resolved else None)


def cars(monkeypatch: pytest.MonkeyPatch, *found: VehicleSocChoice) -> None:
    monkeypatch.setattr(discovery, "soc_choices", lambda _hass: list(found))


# ---- the canonical resolver ------------------------------------------------------------------------

def test_sole_eligible_car_is_the_default_for_unset_or_stale_identity(monkeypatch):
    cars(monkeypatch, choice("bmw"))
    for stored in (None, "", "removed-car", 7):
        assert resolve_target_vehicle(None, stored)[0] == "bmw"
    assert resolve_target_vehicle(None, "bmw", ("bmw",))[0] == "bmw"


def test_zero_cars_stay_unknown_and_two_cars_keep_guarded_resolution(monkeypatch):
    cars(monkeypatch)
    assert resolve_target_vehicle(None, "bmw")[0] is None
    cars(monkeypatch, choice("bmw", resolved=False))  # no resolvable sensor: not an eligible car
    assert resolve_target_vehicle(None, None)[0] is None
    cars(monkeypatch, choice("bmw"), choice("kia"))
    assert resolve_target_vehicle(None, None)[0] is None, "two cars: never guessed"
    assert resolve_target_vehicle(None, "removed-car")[0] is None
    assert resolve_target_vehicle(None, "kia")[0] == "kia", "an explicit configured choice stands"
    assert resolve_target_vehicle(None, "kia", ("bmw",))[0] == "bmw", "only the charger's own cars count"


def test_explicit_guest_is_never_overwritten_by_the_sole_car(monkeypatch):
    cars(monkeypatch, choice("bmw"))
    assert resolve_target_vehicle(None, GUEST_VEHICLE_ID)[0] is None


# ---- the plug-in decision ----------------------------------------------------------------------------

class Notifier:
    def __init__(self) -> None:
        self.asked: list[object] = []

    def ask_vehicle(self, *args, **kwargs):
        self.asked.append(args)
        return ("phone",)

    def vehicle_question_settled(self) -> None: ...
    def clear_vehicle_question(self, *_): ...
    def retire_vehicle_question(self, *_): ...


def identifier(monkeypatch, mode: str, vehicle_ids=None, stored=None, ruled_out: bool = True):
    monkeypatch.setattr(ident, "Store", lambda *_a, **_k: SimpleNamespace())
    monkeypatch.setattr(ident, "SourceChanges", lambda *_a, **_k: SimpleNamespace(watch=lambda _e: None, stop=lambda: None))
    monkeypatch.setattr(ident, "async_track_state_change_event", lambda *_a, **_k: (lambda: None))
    monkeypatch.setattr(ident, "async_track_time_interval", lambda *_a, **_k: (lambda: None))
    monkeypatch.setattr(ident, "async_track_point_in_utc_time", lambda *_a, **_k: (lambda: None))
    scheduled: list[object] = []

    def create_task(coro, **_kw):
        scheduled.append(coro)
        coro.close()

    hass = SimpleNamespace(config=SimpleNamespace(language="en"), async_create_task=create_task,
                           async_create_background_task=lambda coro, _n: coro.close())
    settings = SimpleNamespace(identify_mode=mode, vehicle_ids=vehicle_ids,
                               target=SimpleNamespace(vehicle_id=stored))
    store = SimpleNamespace(settings=lambda _e: settings)
    notifier = Notifier()
    ident_ = ident.VehicleIdentifier(hass, "entry", controller=SimpleNamespace(), store=store, notifier=notifier)
    ident_.refreshed: list[str] = []
    monkeypatch.setattr(ident_, "_refresh", lambda ids: ident_.refreshed.extend(ids))
    monkeypatch.setattr(ident_, "_sources", lambda _car: (None, None))
    if ruled_out:
        # Every car's own entities say "not plugged in / away": the old trigger of the one-car question.
        monkeypatch.setattr(
            ident_, "_evidence",
            lambda session, _now: [ident.Evidence(car, None, "strong") for car in session.cars],
        )
    ident_._connected = True
    return ident_, notifier, scheduled


@pytest.mark.parametrize("mode", ["automatic", "ask"])
def test_one_car_is_never_asked_even_when_its_own_entities_rule_it_out(monkeypatch, mode):
    cars(monkeypatch, choice("bmw"))
    sole, notifier, scheduled = identifier(monkeypatch, mode, stored="removed-car")
    sole._plugged_in(ident.dt_util.utcnow())
    assert sole._session is None and sole.method == ident.METHOD_ONLY_CANDIDATE
    assert notifier.asked == [] and sole.refreshed == [], "no question, no re-read of the car"
    assert scheduled and all(c.cr_code.co_name == "_async_save" for c in scheduled), "only the history is stored"
    assert sole.dashboard() is None, "nothing to show for one car"
    entry = sole.diagnostics()["history"][-1]
    assert entry["method"] == ident.METHOD_ONLY_CANDIDATE and entry["skipped"]["reason"] == ident.SKIPPED_ONLY_CANDIDATE
    assert entry["vehicle_id"] == "bmw", "the stale stored identity resolves to the sole car without a write"
    assert sole.claims("bmw") and not sole.claims("kia")


def test_a_restart_with_the_car_plugged_in_decides_the_same_way(monkeypatch):
    cars(monkeypatch, choice("bmw"))
    sole, notifier, _ = identifier(monkeypatch, "ask")
    sole._plugged_in(ident.dt_util.utcnow(), trigger=ident.TRIGGER_RESTART)
    assert notifier.asked == [] and sole.method == ident.METHOD_ONLY_CANDIDATE


def test_a_guest_stays_a_persons_choice_and_other_cars_are_refused(monkeypatch):
    cars(monkeypatch, choice("bmw"))
    sole, _, _ = identifier(monkeypatch, "automatic")
    sole._plugged_in(ident.dt_util.utcnow())
    assert sole.answer_refusal(GUEST_VEHICLE_ID) is None
    assert sole.answer_refusal("bmw") is None
    assert sole.answer_refusal("removed-car") == ident.REFUSED_NOT_HERE


def test_zero_cars_decide_nothing_and_ask_nothing(monkeypatch):
    cars(monkeypatch)
    none, notifier, _ = identifier(monkeypatch, "ask")
    none._plugged_in(ident.dt_util.utcnow())
    assert notifier.asked == [] and none._session is None and not none.claims("bmw")


def test_two_cars_keep_their_guarded_question(monkeypatch):
    cars(monkeypatch, choice("bmw"), choice("kia"))
    pair, notifier, _ = identifier(monkeypatch, "ask")
    pair._plugged_in(ident.dt_util.utcnow())
    assert len(notifier.asked) == 1 and pair._session is not None
    assert pair.dashboard()["state"] == ident.STATE_ASKING
    assert sorted(pair.refreshed) == ["bmw", "kia"]
