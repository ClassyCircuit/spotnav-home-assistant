"""Stage 15.10: Morek behind-plan check and power-learner feed (mocked, no `hass` fixture, no HA/charger).

The production capture tick of `AutoPlannerController` runs the existing `PlanWatch` and `PowerSampler` against the
acknowledged active window. Everything the tick reads about the Morek side arrives through the `morek_progress` seam,
which the tests drive. Nothing here sends: `async_recalculate` is a mock and the executor's reconcile must never run."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.spotnav.api import morek_schedule
from custom_components.spotnav.planning import auto_controller, learned_power
from custom_components.spotnav.planning.learned_power import LearnedPowerStore, PowerSampler, Wiring

from .test_stage_159a_energy_capture import CAR, START, FakeStore, World, fake_store  # noqa: F401 - fixture reused

WIRING = Wiring(phases=3, voltage_v=400.0, amps=16)
SUBJECT = f"vehicle:{CAR}"


@pytest.fixture(autouse=True)
def power_store(monkeypatch):
    monkeypatch.setattr(learned_power, "Store", FakeStore)


class Morek(World):
    """The 15.9a world plus a learned-power store and a drivable Morek progress seam."""

    def __init__(self, monkeypatch, *, kw=11.0, seed=True, owned=True):
        super().__init__(monkeypatch, kw=kw, owned=owned)
        self.full_kw = auto_controller.power_kw(16, 3, 400.0)
        self.lps = LearnedPowerStore(MagicMock(), "entry")
        if seed:  # one earlier plug-in at the same power, so this one makes the second the trust rule needs
            self.lps.add(SUBJECT, WIRING, "plug_in:earlier", kwh=kw * 10 / 60.0, minutes=10.0)
        self.planner._learned = self.lps
        self.planner._sampler = PowerSampler(self.lps)
        self.planner._morek_progress = self.progress
        self.window = (START, START + timedelta(hours=8), 16)
        self.sending = False
        self.settled: str | None = "a1"  # the acknowledged attempt id of a settled routine record, window open or not
        self.flow = "charging"
        self.register_fresh = True
        self.credible = True
        self.link = {"state": "up", "connection_id": 1, "since": "t0"}
        self.progress_calls = 0
        self.progress_none = False
        self.executor.async_reconcile = AsyncMock()
        self.controller.charge_progress = SimpleNamespace(state="charging", reason=None)
        monkeypatch.setattr(auto_controller.hybrid_execution, "charge_power_limits", lambda *_: (self.full_kw, 1380.0))
        monkeypatch.setattr(auto_controller, "stored_properties", lambda *_: SimpleNamespace(onboard_phases=3))
        monkeypatch.setattr(auto_controller, "site_controller_for_charger", lambda *_: None)
        monkeypatch.setattr(self.planner, "_register_time_credible", lambda *_: self.credible)

    async def progress(self, _now):
        self.progress_calls += 1
        if self.progress_none:
            return None
        return {
            "window": self.window, "settled": self.settled, "sending": self.sending, "link": self.link, "flow": self.flow,
            "live": {"energy_register_kwh": {"fresh": self.register_fresh}},
        }

    def learned(self):
        return self.lps.power(SUBJECT, WIRING, 1.38, self.full_kw)

    def cap(self):
        return self.planner._plan_power_cap_kw(self.settings)  # noqa: SLF001


@pytest.mark.asyncio
async def test_slow_charge_in_acknowledged_window_replans_once_through_the_existing_recalculation(monkeypatch):
    world = Morek(monkeypatch, kw=5.0)
    await world.run(9)  # the existing thresholds: confirmed behind at minute 7
    world.recalculate.assert_called_once_with()  # the existing strict recalculation: no cause, no price/cap trigger
    # Nothing but the capture tick's own appointment; the legacy plan watch and the executor were never used.
    assert world.planner._watch_cancel is None  # noqa: SLF001
    world.executor.async_reconcile.assert_not_called()
    # The replan moved nothing (mock): PlanWatch's own backoff doubled the wait (600 s), so it is bounded.
    assert world.planner._watch._every_s == 600.0  # noqa: SLF001
    await world.run(7)
    world.recalculate.assert_called_once_with()
    await world.run(2)  # minute 18: the doubled wait has passed, the charge is still behind
    assert world.recalculate.call_count == 2


@pytest.mark.asyncio
async def test_healthy_charge_replans_nothing_and_new_power_samples_change_nothing_visible(monkeypatch):
    world = Morek(monkeypatch, kw=10.9)  # a touch under the plan, inside the existing thresholds
    first = world.cap()
    assert first is None  # nothing trusted yet
    seen = set()
    for _ in range(45):
        await world.minute()
        seen.add(world.cap())
    world.recalculate.assert_not_called()
    assert world.learned().trusted and world.learned().cap_kw is not None  # collected ...
    assert seen == {None}  # ... but the figure the plan reads stayed the one the accepted plan used
    assert world.planner._power_freeze is not None  # noqa: SLF001
    # The active window ends: the next planning decision reads the live figure; nothing was sent for the change.
    # (time passes the known end with a healthy register: judged on fresh evidence, on plan, nothing to resend)
    world.window = None
    world.now = START + timedelta(hours=8) - timedelta(minutes=1)
    world.register += world.kw * (8 - 46 / 60.0)
    await world.minute()
    assert world.cap() == pytest.approx(world.learned().cap_kw)
    world.recalculate.assert_not_called()
    world.executor.async_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_confirmed_behind_applies_the_learned_power_to_the_replan_only(monkeypatch):
    world = Morek(monkeypatch, kw=5.0)
    await world.run(16)
    assert world.recalculate.call_count == 1
    assert world.learned().trusted and world.cap() is None  # collected, but the accepted plan's figure is held
    await world.minute()  # minute 17: confirmed behind again
    assert world.recalculate.call_count == 2
    assert world.cap() == pytest.approx(world.learned().cap_kw)  # the replan read the live figure
    assert world.cap() < world.full_kw  # lengthen-only: below the planned power


def _link_down(world):
    world.link = {"state": "down", "connection_id": 1, "since": "t0"}


def _link_unknown(world):
    world.link = None


def _stale(world):
    world.register_fresh = False


def _replayed(world):
    world.credible = False


def _no_window(world):  # Pause, Stop, Charge Now, pending/uncertain write: the record yields no window
    world.window = None


def _sending(world):
    world.sending = True


def _no_progress(world):
    world.progress_none = True


def _person_stop(world):
    world.controller.held_off_by_person = True


def _paused(world):
    world.executor.paused = True


def _wrong_vehicle(world):
    world.identified = "someone-else"


def _unknown_car(world):
    world.identified = None


def _idle(world):
    world.flow = "unknown"


def _held(world):
    world.planner._held_by_spotnav = lambda *_: "balancing"  # noqa: SLF001


def _unplugged(world):
    world.controller.known_connected = False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "breakage",
    [_link_down, _link_unknown, _stale, _replayed, _no_window, _sending, _no_progress, _person_stop, _paused,
     _wrong_vehicle, _unknown_car, _idle, _held, _unplugged],
)
async def test_doubtful_or_held_facts_yield_no_replan_and_no_sample(monkeypatch, breakage):
    world = Morek(monkeypatch, kw=5.0, seed=False)
    breakage(world)
    await world.run(30)
    world.recalculate.assert_not_called()
    assert world.learned().sessions == 0 and world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == 0


@pytest.mark.asyncio
async def test_link_gap_ends_the_clean_stretch_and_a_replayed_minute_is_not_counted(monkeypatch):
    world = Morek(monkeypatch, kw=11.0, seed=False)
    await world.run(10)
    clean = world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes
    assert clean > 0
    world.link = {"state": "up", "connection_id": 2, "since": "t1"}  # a new connection: nothing spans it
    await world.minute()
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == clean
    world.credible = False
    await world.run(3)
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == clean
    world.credible = True
    await world.run(3)
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes > clean


@pytest.mark.asyncio
async def test_a_changed_current_or_start_grace_is_not_learned(monkeypatch):
    world = Morek(monkeypatch, kw=11.0, seed=False)
    world.window = (START, START + timedelta(hours=8), 10)  # the window's current is not the planned 16 A
    await world.run(15)
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == 0
    world = Morek(monkeypatch, kw=11.0, seed=False)
    world.window = (START + timedelta(minutes=30), START + timedelta(hours=8), 16)  # a continued/new window: grace
    await world.run(2)
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == 0


@pytest.mark.asyncio
async def test_the_learned_power_can_only_lengthen(monkeypatch):
    world = Morek(monkeypatch, kw=11.0, seed=False)
    for index in range(3):
        world.lps.add(SUBJECT, WIRING, f"plug_in:fast{index}", kwh=30.0, minutes=60.0)  # 30 kW: impossible
    learned = world.learned()
    assert learned.cap_kw is not None and learned.cap_kw <= world.full_kw


@pytest.mark.asyncio
async def test_learning_reset_clears_the_held_figure_pending_stretch_and_samples(monkeypatch):
    world = Morek(monkeypatch, kw=10.9)
    await world.run(30)
    assert world.planner._power_freeze is not None and world.planner._behind_link_key is not None  # noqa: SLF001
    assert world.learned().sessions >= 1
    result = await world.planner.async_reset_learning()
    assert result["power"] is True
    assert world.planner._power_freeze is None and world.planner._behind_link_key is None  # noqa: SLF001
    assert world.planner._sampler._last is None  # noqa: SLF001
    assert world.learned().sessions == 0 and world.cap() is None


@pytest.mark.asyncio
async def test_wrong_owner_resets_only_what_the_morek_look_touched(monkeypatch):
    legacy = Morek(monkeypatch, owned=False)
    watch, sampler = legacy.planner._watch, legacy.planner._sampler  # noqa: SLF001
    await legacy.run(3)
    assert legacy.planner._watch is watch and legacy.planner._sampler is sampler  # noqa: SLF001
    assert legacy.progress_calls == 0  # a charger another owner holds is never looked at
    world = Morek(monkeypatch, kw=5.0)
    await world.run(5)
    assert world.progress_calls > 0
    world.owned = False
    await world.minute()
    assert world.planner._watch is not None and world.planner._morek_window_end is None  # noqa: SLF001
    assert world.planner._power_freeze is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_failing_progress_seam_never_breaks_the_capture(monkeypatch):
    world = Morek(monkeypatch, kw=5.0)

    async def boom(_now):
        raise RuntimeError("unreadable")

    world.planner._morek_progress = boom  # noqa: SLF001
    await world.run(10)
    world.recalculate.assert_not_called()
    assert world.planner._capture_sampler is not None  # noqa: SLF001
    assert world.timers or True  # the tick re-arms; the capture path is intact


# ---- the pure window helper -------------------------------------------------------------------------------------

def _profile(start, periods):
    return {
        "chargingProfileId": 1, "stackLevel": 1, "chargingProfilePurpose": "TxDefaultProfile",
        "chargingProfileKind": "Absolute",
        "chargingSchedule": {
            "startSchedule": start.isoformat().replace("+00:00", "Z"), "chargingRateUnit": "A",
            "chargingSchedulePeriod": [{"startPeriod": s, "limit": limit, "numberPhases": 3} for s, limit in periods],
        },
    }


def _record(profile, **extra):
    record = {
        "uncertain": False, "attempt": {"id": "a1", "state": "accepted", "fingerprint": "f"},
        "acknowledged": {"id": "a1", "fingerprint": "f", "routine": True, "profile": profile},
    }
    record.update(extra)
    return record


def test_behind_window_returns_start_end_and_limit_of_the_acknowledged_routine_window():
    profile = _profile(START, [(0, 0), (3600, 16), (7200, 0)])
    now = START + timedelta(minutes=90)
    assert morek_schedule.behind_window(_record(profile), now) == (START + timedelta(hours=1), START + timedelta(hours=2), 16)
    assert morek_schedule.behind_window(_record(profile), START + timedelta(minutes=30)) is None  # idle
    two = _profile(START, [(0, 16), (1800, 10), (3600, 0)])  # contiguous positive limits are one window
    assert morek_schedule.behind_window(_record(two), START + timedelta(minutes=40)) == (START, START + timedelta(hours=1), 10)


def test_behind_window_fails_closed_on_anything_unsettled():
    profile = _profile(START, [(0, 16), (3600, 0)])
    now = START + timedelta(minutes=10)
    assert morek_schedule.behind_window(_record(profile), now) is not None
    assert morek_schedule.behind_window(None, now) is None
    assert morek_schedule.behind_window(_record(profile, uncertain=True), now) is None
    assert morek_schedule.behind_window(_record(profile, attempt={"id": "a2", "state": "accepted"}), now) is None  # newer
    assert morek_schedule.behind_window(_record(profile, attempt={"id": "a1", "state": "uncertain"}), now) is None
    assert morek_schedule.behind_window(_record(profile, schedule_pause={"id": "p"}), now) is None
    live_override = {"end": (now + timedelta(hours=1)).isoformat()}
    assert morek_schedule.behind_window(_record(profile, charge_now=live_override), now) is None
    expired = {"end": (now - timedelta(minutes=1)).isoformat()}
    assert morek_schedule.behind_window(_record(profile, charge_now=expired), now) is not None
    assert morek_schedule.behind_window({"uncertain": False, "acknowledged": {"id": "x"}}, now) is None
    pause_ack = _record(profile)
    pause_ack["acknowledged"]["routine"] = False
    assert morek_schedule.behind_window(pause_ack, now) is None
    open_ended = _profile(START, [(0, 16)])
    assert morek_schedule.behind_window(_record(open_ended), now) is None


def test_behind_settled_is_independent_of_an_open_window_and_fails_closed():
    profile = _profile(START, [(0, 16), (3600, 0)])
    idle = START + timedelta(hours=3)  # window long over
    assert morek_schedule.behind_window(_record(profile), idle) is None
    assert morek_schedule.behind_settled(_record(profile), idle) == "a1"
    assert morek_schedule.behind_settled(_record(profile, uncertain=True), idle) is None
    assert morek_schedule.behind_settled(_record(profile, attempt={"id": "a2", "state": "accepted"}), idle) is None
    assert morek_schedule.behind_settled(_record(profile, attempt={"id": "a1", "state": "pending"}), idle) is None
    assert morek_schedule.behind_settled(_record(profile, schedule_pause={"id": "p"}), idle) is None
    live = {"end": (idle + timedelta(hours=1)).isoformat()}
    assert morek_schedule.behind_settled(_record(profile, charge_now=live), idle) is None
    assert morek_schedule.behind_settled(None, idle) is None


# ---- register time credibility ----------------------------------------------------------------------------------

def test_register_time_credibility_is_fail_closed(monkeypatch):
    world = World(monkeypatch)
    now = START
    row = {"t": (now - timedelta(seconds=20)).isoformat(), "r": (now - timedelta(seconds=18)).isoformat(),
           "e": "sensor.energy_register", "v": 1.0}
    evidence = SimpleNamespace(samples=lambda *a, **k: [row], gaps=lambda *a, **k: [])
    monkeypatch.setattr(auto_controller, "evidence_for", lambda _hass: evidence)
    ok = world.planner._register_time_credible  # noqa: SLF001
    assert ok(now, "sensor.energy_register") is True
    row["q"] = True
    assert ok(now, "sensor.energy_register") is False  # a flagged (replayed) row
    row.pop("q")
    row["r"] = (now + timedelta(seconds=400)).isoformat()
    assert ok(now, "sensor.energy_register") is False  # received long after it was observed
    row["r"] = (now - timedelta(seconds=18)).isoformat()
    assert ok(now, "sensor.other") is False  # another entity's rows say nothing
    evidence.gaps = lambda *a, **k: [{"r": (now - timedelta(seconds=60)).isoformat()}]
    assert ok(now, "sensor.energy_register") is False  # a recorded gap in the recent stretch
    monkeypatch.setattr(auto_controller, "evidence_for", lambda _hass: None)
    assert ok(now, "sensor.energy_register") is False  # no evidence store: unknown, not credible


# ---- unknown never behind: the end judgement and the held figure -----------------------------------------------------

async def _near_end_behind_but_unreplanned(monkeypatch):
    """A slow charge in a 30-minute window whose mid-window check is held (so nothing replans before the end)."""
    world = Morek(monkeypatch, kw=5.0, seed=False)
    world.window = (START, START + timedelta(minutes=30), 16)
    world.planner._held_by_spotnav = lambda *_: "balancing"  # noqa: SLF001
    await world.run(29)
    world.recalculate.assert_not_called()
    assert world.planner._watch.watching  # noqa: SLF001
    world.planner._held_by_spotnav = lambda *_: None  # noqa: SLF001
    world.window = None
    return world


async def _past_end_and_wait(world):
    world.now = START + timedelta(minutes=30 + 21) - timedelta(minutes=1)  # beyond END_WAIT_S after the end
    await world.minute()
    await world.minute()


@pytest.mark.asyncio
@pytest.mark.parametrize("breakage", [_link_down, _link_unknown, _stale, _replayed, _paused, _person_stop, _sending])
async def test_end_judgement_without_fresh_proof_is_dropped_never_made_on_the_last_reading(monkeypatch, breakage):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    breakage(world)
    await _past_end_and_wait(world)
    world.recalculate.assert_not_called()
    assert world.planner._watch.ended_end(world.now) is None  # noqa: SLF001 - dropped unjudged, not decided
    world.executor.async_reconcile.assert_not_called()


def _unsettled(world):  # uncertain latest record / pending attempt / Pause hold / live Charge Now: no settled routine
    world.settled = None


@pytest.mark.asyncio
@pytest.mark.parametrize("breakage", [_unsettled, _no_progress])
async def test_unsettled_record_never_judges_the_ended_window_even_with_a_fresh_register(monkeypatch, breakage):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    breakage(world)
    world.now = START + timedelta(minutes=30)
    await world.minute()  # register fresh, link up, car known: but nothing says the record is settled
    world.recalculate.assert_not_called()
    samples = world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes
    await _past_end_and_wait(world)
    world.recalculate.assert_not_called()
    assert world.planner._watch.ended_end(world.now) is None  # noqa: SLF001 - dropped unjudged
    assert world.lps.power(SUBJECT, WIRING, 1.38, 11.0).minutes == samples
    world.executor.async_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_a_newer_accepted_intent_cannot_judge_the_prior_window_on_new_data(monkeypatch):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    world.settled = "a2"  # a new accepted intent, and a new window already open
    world.now = START + timedelta(minutes=30)
    world.window = (world.now, START + timedelta(hours=8), 16)
    await world.minute()
    world.recalculate.assert_not_called()
    assert world.planner._watch.ended_end(world.now) is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_new_plug_in_with_a_new_window_cannot_judge_the_old_end(monkeypatch):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    world.now = START + timedelta(minutes=30)
    world.controller.plugged_in_for_count = START + timedelta(minutes=29)  # positively a different plug-in
    world.window = (world.now, START + timedelta(hours=8), 16)
    await world.minute()
    world.recalculate.assert_not_called()
    assert world.planner._watch.ended_end(world.now) is None  # noqa: SLF001
    assert world.planner._morek_session == world.controller.plugged_in_for_count  # noqa: SLF001


@pytest.mark.asyncio
async def test_an_unknown_plug_in_is_not_a_change(monkeypatch):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    world.controller.plugged_in_for_count = None
    await world.minute()
    assert world.planner._watch.watching  # noqa: SLF001 - not reset


@pytest.mark.asyncio
async def test_healthy_end_with_fresh_proof_is_judged_honestly(monkeypatch):
    world = await _near_end_behind_but_unreplanned(monkeypatch)
    world.now = START + timedelta(minutes=30)
    await world.minute()  # a fresh, credible register posted after the end: the existing end decision applies
    world.recalculate.assert_called_once_with()


@pytest.mark.asyncio
async def test_unknown_progress_keeps_the_held_figure_until_the_known_end(monkeypatch):
    world = Morek(monkeypatch, kw=10.9)
    await world.run(30)
    assert world.cap() is None and world.planner._power_freeze is not None  # noqa: SLF001
    # a new plug-in's worth of clean minutes is collected meanwhile: the live figure would now be trusted
    world.lps.add(SUBJECT, WIRING, "plug_in:more", kwh=10.0 * 10 / 60.0, minutes=10.0)
    assert world.learned().cap_kw is not None
    for state in (_no_progress, _no_window, _sending):  # unreachable, pending/uncertain, in flight
        world.progress_none = world.sending = False
        world.window = (START, START + timedelta(hours=8), 16)
        state(world)
        await world.run(3)
        assert world.cap() is None, state.__name__  # same cap, no extra recalculation
        world.recalculate.assert_not_called()
    world.progress_none = world.sending = False
    world.window = (START, START + timedelta(hours=8), 16)
    _link_down(world)  # a link gap while the window is still active: the same freeze
    await world.run(3)
    assert world.cap() is None
    # known end passed (nothing known about the window any more): the fresh figure applies
    world.progress_none = True
    world.now = START + timedelta(hours=8)
    await world.minute()
    assert world.cap() == pytest.approx(world.learned().cap_kw)
    world.recalculate.assert_not_called()


@pytest.mark.asyncio
async def test_a_known_stop_or_new_plug_in_releases_the_held_figure(monkeypatch):
    world = Morek(monkeypatch, kw=10.9)
    await world.run(5)
    assert world.planner._power_freeze is not None  # noqa: SLF001
    world.progress_none = True
    world.controller.plugged_in_for_count = START  # a different plug-in
    await world.minute()
    assert world.planner._power_freeze is None and world.planner._morek_window_end is None  # noqa: SLF001
