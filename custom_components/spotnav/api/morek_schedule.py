"""Opt-in, manual Morek profile experiment through the existing HA OCPP connection.

This deliberately does not enable automatic execution: SpotNav's live controller must be
paused before a profile can be sent. The readback is an effective schedule, not an inventory
of installed profiles. OCPP's internal ChargePoint API is isolated here for easy replacement.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import functools
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, MOREK_CONNECTOR_ID, MOREK_STATION_ID
from ..execution.execution_ownership import ownership_store
from ..execution.command_admission import command_admission
from ..execution.morek_freshness import STRICT_EVIDENCE_MAX_AGE_S
from ..execution.morek_outcomes import OutcomeUnavailable, outcomes_for
from ..planning.planner import MOREK_MAX_BLOCKS
from ..runtime import domain_data, preview_for, controller_for
from .common import is_admin, lookup_charger, send_unsupported_version

API_VERSION = 1
PROFILE_ID = 42001
MAX_PERIODS = 8
MAX_HORIZON = timedelta(hours=48)
VERIFY_TOLERANCE_S = 90
REJECTION_RETRY_DELAYS = (300, 900)  # seconds before the 2nd and 3rd attempt at a definitely rejected intent
VERIFY_DELAYS = (30, 45, 45)  # Follow-up reads at approximately 30, 75 and 120 seconds.
_DATA_KEY = "spotnav_morek_schedule"
_VERIFY_KEY = "spotnav_morek_verification"
_LIFECYCLE_KEY = "spotnav_morek_verification_lifecycle"
_LOGGER = logging.getLogger(__name__)


def _logged_action(name: str):
    """Log one line for an explicit person action: recorded (an intent, not a charge) or refused with its code.

    No ids, entities or payloads; the stable refusal code is what makes the line actionable.
    """
    def wrap(func):
        @functools.wraps(func)
        async def run(*args, **kwargs):
            label = ("Resume" if kwargs.get("resume") else "Pause") if name == "pause/resume" else (
                "Return to Auto" if kwargs.get("return_to_auto") else name)
            try:
                result = await func(*args, **kwargs)
            except ScheduleRefused as err:
                _LOGGER.info("Morek %s refused: %s", label, getattr(err, "code", None) or str(err))
                raise
            _LOGGER.info("Morek %s recorded as an intent; the schedule follows by reconciliation and charging is not confirmed", label)
            return result
        return run
    return wrap


def _evidence_call(hass: HomeAssistant, entry_id: str, method: str, *args: Any, **kwargs: Any) -> None:
    """Stage 6.2: keep command evidence in the bounded evidence store. Never raises and never delays a send:
    a missing store or any failure keeps nothing, and the send path is unaffected."""
    try:
        from ..sessions.evidence import evidence_for

        store = evidence_for(hass)
        if store is not None:
            getattr(store, method)(entry_id, *args, **kwargs)
    except Exception:  # noqa: BLE001 - history must never alter the outcome of a charger operation
        _LOGGER.debug("Charging evidence was not recorded", exc_info=True)


def _evidence_plan(hass: HomeAssistant, entry_id: str, attempt: dict[str, Any], profile: dict[str, Any]) -> None:
    intent = "charge_now" if attempt.get("override_id") else "pause_resume" if attempt.get("pause_id") else "schedule"
    _evidence_call(hass, entry_id, "record_plan", plan_id=attempt.get("id"), fingerprint=attempt.get("fingerprint"),
                   profile=profile, intent_at=attempt.get("at"), source=attempt.get("source"), intent=intent,
                   revision=attempt.get("revision"), **_evidence_tariff(hass, entry_id))


def _evidence_tariff(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Stage 6.3: the tariff/price context in force when this version is made, kept with it (unknown if unreadable)."""
    context: dict[str, Any] = {"time_zone": getattr(getattr(hass, "config", None), "time_zone", None)}
    blobs: dict[str, Any] = {}
    try:
        from ..sessions.inputs import plan_tariff_snapshot

        tariff, blobs = plan_tariff_snapshot(hass, entry_id, datetime.now(timezone.utc))
        context.update(tariff)
    except Exception:  # noqa: BLE001 - history must never alter a charger operation
        _LOGGER.debug("Plan tariff context was not recorded", exc_info=True)
        context.update({"fiscal_state": "unknown", "prices_state": "none"})
    return {"context": context, "blobs": blobs}


class ScheduleRefused(Exception):
    def __init__(self, code: str):
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ScheduleRefused("invalid_plan")
    return value.astimezone(timezone.utc)


def profile_for(periods: tuple[tuple[datetime, datetime], ...], amps: int, now: datetime, *,
                allow_active: bool = False) -> dict[str, Any]:
    """Build fixed-time limits, optionally continuing an active displayed window."""
    requested_at = _utc(now)
    now = requested_at.replace(microsecond=0)
    if allow_active and requested_at.microsecond:
        now += timedelta(seconds=1)
    if not isinstance(amps, int) or isinstance(amps, bool) or not 6 <= amps <= 16:
        raise ScheduleRefused("invalid_current")
    if not periods:
        raise ScheduleRefused("no_current_plan")
    # Validate the entire original plan before discarding elapsed windows.
    normalized = []
    previous_end = None
    try:
        for start, end in periods:
            start, end = _utc(start), _utc(end)
            if end <= start or (previous_end is not None and start <= previous_end):
                raise ScheduleRefused("invalid_plan")
            normalized.append((start, end))
            previous_end = end
    except (TypeError, ValueError, AttributeError):
        raise ScheduleRefused("invalid_plan") from None
    if allow_active:
        normalized = [(start, end) for start, end in normalized if end > requested_at]
        if not normalized:
            raise ScheduleRefused("plan_expired")
    if len(normalized) > MOREK_MAX_BLOCKS:
        raise ScheduleRefused("too_many_blocks")
    active = allow_active and normalized[0][0] <= requested_at
    transitions: list[dict[str, int]] = [{"startPeriod": 0, "limit": amps if active else 0}]
    for index, (start, end) in enumerate(normalized):
        if (not (active and index == 0) and start <= requested_at) or end - now > MAX_HORIZON:
            raise ScheduleRefused("invalid_plan")
        # OCPP offsets are whole seconds: never start before or end after a displayed window.
        start_offset = math.ceil((start - now).total_seconds())
        end_offset = math.floor((end - now).total_seconds())
        if end_offset <= (0 if active and index == 0 else start_offset):
            raise ScheduleRefused("invalid_plan")
        if not (active and index == 0):
            transitions.append({"startPeriod": start_offset, "limit": amps})
        transitions.append({"startPeriod": end_offset, "limit": 0})
    if len(transitions) > MAX_PERIODS or len({p["startPeriod"] for p in transitions}) != len(transitions):
        raise ScheduleRefused("invalid_plan")
    return {
        "chargingProfileId": PROFILE_ID,
        "stackLevel": 1,
        "chargingProfilePurpose": "TxDefaultProfile",
        "chargingProfileKind": "Absolute",
        "chargingSchedule": {
            "startSchedule": now.isoformat().replace("+00:00", "Z"),
            "chargingRateUnit": "A",
            "chargingSchedulePeriod": [dict(period, numberPhases=3) for period in transitions],
        },
    }


def charge_now_profile(start: datetime, end: datetime, auto_periods: tuple, amps: int,
                       now: datetime) -> dict[str, Any]:
    """Build a bounded override and all subsequent Auto windows; never dispatch it.

    The caller must independently validate Auto provenance and execution authority.
    Overlapping or adjacent Auto windows are merged with the override only where
    their union is continuously on; subsequent disjoint windows are retained.
    """
    try:
        start, end, now = _utc(start), _utc(end), _utc(now)
        if end <= start or end <= now or start > now:
            raise ScheduleRefused("charge_now_invalid_time")
        previous_end = None
        normalized = []
        for window_start, window_end in auto_periods:
            window_start, window_end = _utc(window_start), _utc(window_end)
            if window_end <= window_start or (previous_end is not None and window_start <= previous_end):
                raise ScheduleRefused("invalid_plan")
            normalized.append((window_start, window_end))
            previous_end = window_end
    except (TypeError, ValueError, AttributeError):
        raise ScheduleRefused("invalid_plan") from None
    windows = [(start, end)]
    for window_start, window_end in normalized:
        if window_end <= end:
            continue
        if window_start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], window_end)
        else:
            windows.append((window_start, window_end))
    return profile_for(tuple(windows), amps, now, allow_active=True)


def held_off_profile(now: datetime) -> dict[str, Any]:
    """The existing profile identity, with one immediate, open-ended 0 A limit."""
    start = _utc(now).replace(microsecond=0)
    return {"chargingProfileId": PROFILE_ID, "stackLevel": 1,
            "chargingProfilePurpose": "TxDefaultProfile", "chargingProfileKind": "Absolute",
            "chargingSchedule": {"startSchedule": start.isoformat().replace("+00:00", "Z"),
                                 "chargingRateUnit": "A", "chargingSchedulePeriod": [
                                     {"startPeriod": 0, "limit": 0, "numberPhases": 3}]}}


def acknowledged_profile(record: dict[str, Any] | None, revision: Any = None) -> dict[str, Any] | None:
    """The last reliably accepted routine (no pause or Charge Now) profile, if still settled.

    `acknowledged` is only replaced by a later accepted write, so a settings revision or a
    definitely rejected newer attempt does not hide it; an uncertain write, or an accepted
    pause or Charge Now (which replaces `acknowledged`), means no continuation. `revision`
    is accepted for compatibility and deliberately ignored: whether a planning edit or price
    change may release the active window is decided separately (`window_release`, Stage 14.4).
    This is a sent intent, never proof of charging.
    """
    if not isinstance(record, dict) or record.get("uncertain") is not False:
        return None
    ack, attempt = record.get("acknowledged"), record.get("attempt")
    if not isinstance(ack, dict) or not ack.get("id") or not ack.get("fingerprint"):
        return None
    if "profile" in ack:  # durable evidence written at acceptance
        if ack.get("routine") is not True:
            return None
        profile = ack.get("profile")
    elif (isinstance(attempt, dict) and attempt.get("state") == "accepted"  # pre-2.5.103 record
            and attempt.get("id") == ack.get("id") and attempt.get("fingerprint") == ack.get("fingerprint")
            and attempt.get("pause_id") is None and attempt.get("override_id") is None):
        profile = attempt.get("profile")
    else:
        return None
    return profile if isinstance(profile, dict) else None


def acknowledged_baseline(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The reserve-free twin of the accepted routine profile (Stage 15.1a), or `None` (no reserve, or an older record).

    Written next to the profile at acceptance when the plan carried a time reserve: the same windows without the
    reserve. It lets Stage 14 judge SOC drift and window release on the need alone (see `same_effective_schedule`
    and `window_release`) without guessing which part of a window is reserve.
    """
    if acknowledged_profile(record) is None:
        return None
    baseline = (record.get("acknowledged") or {}).get("baseline")
    return baseline if isinstance(baseline, dict) else None


def active_window(profile: dict[str, Any] | None, now: datetime) -> tuple[datetime, int | float] | None:
    """End and limit of the window a fixed-time profile allows at `now`; None if idle or open-ended."""
    try:
        schedule = profile["chargingSchedule"]
        start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        changes = sorted((start + timedelta(seconds=p["startPeriod"]), p["limit"])
                         for p in schedule["chargingSchedulePeriod"])
        now = _utc(now)
        current = [limit for at, limit in changes if at <= now]
        if not current or not current[-1] or current[-1] <= 0:
            return None
        end = next((at for at, limit in changes if at > now and limit == 0), None)
        return None if end is None else (end, current[-1])
    except (KeyError, TypeError, ValueError, AttributeError, ScheduleRefused):
        return None


def _settled_profile(record: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """The acknowledged routine profile of a *settled* record, or `None`: not uncertain, the latest attempt is the
    accepted acknowledged one, no Pause intent, no live Charge Now. Independent of whether a window is open."""
    try:
        profile = acknowledged_profile(record)
        if profile is None or record.get("schedule_pause") is not None:
            return None
        ack, attempt = record["acknowledged"], record.get("attempt")
        if not isinstance(attempt, dict) or attempt.get("id") != ack.get("id") or attempt.get("state") != "accepted":
            return None
        override = record.get("charge_now")
        if override is not None and _utc(datetime.fromisoformat(override["end"])) > _utc(now):
            return None
        return profile
    except (KeyError, TypeError, ValueError, AttributeError, ScheduleRefused):
        return None


def behind_settled(record: dict[str, Any] | None, now: datetime) -> str | None:
    """Stage 15.10: the acknowledged attempt id of a settled routine record (see `_settled_profile`), else `None`.
    Says nothing about whether a window is open now; an ended window is judged only while this holds."""
    if _settled_profile(record, now) is None:
        return None
    ack_id = record["acknowledged"].get("id")
    return ack_id if isinstance(ack_id, str) else str(ack_id)


def behind_window(record: dict[str, Any] | None, now: datetime) -> tuple[datetime, datetime, int | float] | None:
    """Stage 15.10: `(start, end, limit)` of the *acknowledged routine* window open at `now`, or `None`; pure, no I/O.

    Fail closed: only a settled record counts (`_settled_profile`; fixed-time window with a known end). Anything
    pending, replaced, held or unreadable is `None`, so a behind-plan judgement is never made for it. `start` is where
    the contiguous run of positive limits that contains `now` begins (the profile's own start for a window the profile
    opens at; a continued window is re-sent from the resend, so it starts there). Reuses `active_window`."""
    try:
        profile = _settled_profile(record, now)
        if profile is None:
            return None
        active = active_window(profile, now)
        if active is None:
            return None
        schedule = profile["chargingSchedule"]
        begin = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        changes = sorted((begin + timedelta(seconds=p["startPeriod"]), p["limit"])
                         for p in schedule["chargingSchedulePeriod"])
        moment = _utc(now)
        start = None
        for at, limit in changes:
            if at > moment:
                break
            if limit and limit > 0:
                start = at if start is None else start
            else:
                start = None
        if start is None:
            return None
        return start, active[0], active[1]
    except (KeyError, TypeError, ValueError, AttributeError, ScheduleRefused):
        return None


def continue_active_window(periods: tuple[tuple[datetime, datetime], ...], amps: int, now: datetime,
                           active_profile: dict[str, Any] | None) -> tuple[tuple[tuple[datetime, datetime], ...], datetime | None]:
    """Union the acknowledged, currently allowed window with a replanned schedule.

    Returns the windows and the preserved end (None when no continuation applies). The
    window is kept from now to its existing end whatever the new plan says; every later
    planned window is retained and overlapping or adjacent ones are merged.
    """
    active = active_window(active_profile, now)
    if active is None or active[1] != amps:
        return periods, None
    now = _utc(now)
    end = active[0]
    windows = sorted([(now, end)] + [(_utc(s), _utc(e)) for s, e in periods if _utc(e) > now])
    merged = [windows[0]]
    for start, stop in windows[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return tuple(merged), end


RELEASE_MIN_SAVING_EUR = 0.50  # Stage 14.4 internal defaults, deliberately not settings
RELEASE_MIN_SAVING_FRACTION = 0.10
RELEASE_MIN_GAP = timedelta(minutes=30)
RELEASE_MIN_SLACK = timedelta(minutes=15)
_RELEASE_EPSILON = 1e-6


def cap_snapshot(settings: Any) -> dict[str, Any] | None:
    """Non-sensitive cap evidence stored with an accepted profile (`None`: not readable, so unknown later)."""
    try:
        value, basis = settings.soft_price_cap, getattr(settings, "cap_price_basis", None)
    except AttributeError:
        return None
    numeric = value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    return {"value": value, "basis": basis if isinstance(basis, str) else None} if numeric else None


def cap_lowered(record: dict[str, Any] | None, settings: Any) -> bool:
    """True only when the settings now hold a tighter cap than the last accepted routine profile was planned with.

    Needs the cap stored at acceptance (older records have none: unknown, so False) and the same price basis.
    A changed revision alone, a raised or removed cap, an unchanged cap or any unreadable value is False.
    """
    try:
        stored = (record.get("acknowledged") or {}).get("cap")
        if not isinstance(stored, dict) or "value" not in stored:
            return False
        current = cap_snapshot(settings)
        if current is None or current["value"] is None or current["basis"] != stored.get("basis"):
            return False
        old = stored["value"]
        if old is None:
            return True  # a cap now applies where none did
        return isinstance(old, (int, float)) and not isinstance(old, bool) and current["value"] < old - _RELEASE_EPSILON
    except (AttributeError, TypeError):
        return False


def _priced_cost(windows: list[tuple[datetime, datetime]], rows: list[tuple[datetime, datetime, float]],
                 power_kw: float, energy_kwh: float | None = None) -> float | None:
    """Major-unit cost of charging in `windows` (chronologically, at most `energy_kwh`), or None if any part is unpriced."""
    total, left = 0.0, energy_kwh
    for start, end in sorted(windows):
        cursor = start
        while cursor < end:
            row = next((r for r in rows if r[0] <= cursor < r[1]), None)
            if row is None:
                return None
            stop = min(end, row[1])
            kwh = (stop - cursor).total_seconds() / 3600 * power_kw
            if left is not None:
                taken = min(kwh, left)
                kwh, left = taken, left - taken
            total += kwh * row[2] / 100
            cursor = stop
            if left is not None and left <= _RELEASE_EPSILON:
                return total
    return total if left is None or left <= _RELEASE_EPSILON else None


def _energy_between(periods: tuple[tuple[datetime, datetime], ...], start: datetime, end: datetime,
                    power_kw: float) -> float:
    """kWh the periods deliver at the plan's power between `start` and `end` (nothing optimistic added)."""
    return sum(max(0.0, (min(e, end) - max(s, start)).total_seconds()) for s, e in periods) / 3600 * power_kw


def window_release(snapshot: Any, settings: Any, now: datetime, active_profile: dict[str, Any] | None, *,
                   cap_lowered: bool, price_event: bool, evidence: str,
                   active_baseline: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Whether the replanned schedule may replace (not just extend) the acknowledged active window.

    Returns (release, reason). Only two things can release it: a cap that is actually lower than the one the
    accepted profile was planned with (`cap_lowered`, see that function) or a pending price event (price rule);
    a routine update or an unrelated settings edit never does. Unknown or uncertain cost, price, currency,
    state or feasibility preserves the window. The price rule verifies the proposed schedule itself: the same
    energy, fresh known prices throughout, a real gap of at least 30 minutes (to the next resumption or, with
    none, to ready-by) and the minimum (or, with no minimum configured, the whole plan) delivered at least
    15 minutes before ready-by. Not proof of savings or of physical charging.

    Reserve-free (Stage 15.1a): the new plan's periods are its `baseline_shown_periods` and the window that is
    carried is the accepted profile's reserve-free twin (`active_baseline`, see `acknowledged_baseline`), so the
    time reserve inside the accepted window can neither create nor prevent a release. Without a twin the accepted
    profile is used as it is (an older record, which has no reserve).
    """
    if not (cap_lowered or price_event):
        return False, "active_window_preserved"  # a routine update never releases a window
    try:
        proposal = snapshot.proposal
        now = _utc(now)
        if isinstance(active_baseline, dict):
            active_profile = active_baseline
        active = active_window(active_profile, now)
        if proposal is None or active is None or not proposal.has_plan or not getattr(snapshot, "in_process", False):
            return False, "active_window_preserved"
        if evidence not in ("charging", "waiting"):
            return False, "active_window_state_unknown"
        power = float(proposal.power_kw)
        # Reserve-free (Stage 15.1a): every quantity below is judged on the periods the need itself requires, so the
        # time reserve can neither create nor prevent a release. (The fallback is for a plan without a reserve.)
        needed_periods = getattr(proposal, "baseline_shown_periods", proposal.shown_periods)
        periods = tuple(sorted((_utc(s), _utc(e)) for s, e in needed_periods if _utc(e) > now))
        if not periods or not power > 0:
            return False, "active_window_preserved"
        union, _ = continue_active_window(periods, active[1], now, active_profile)
        if union == periods:
            return False, "active_window_preserved"  # the new plan already carries the window
        interval = proposal.current_interval
        known_now = interval is not None and _utc(interval.start) <= now < _utc(interval.end)
        has_minimum = settings.minimum_ready_by_soc is not None
        if has_minimum and (proposal.minimum_energy_kwh is None or proposal.minimum_shortfall_kwh is None
                            or proposal.minimum_shortfall_kwh > _RELEASE_EPSILON):
            return False, "release_minimum_uncertain"
        if cap_lowered:
            if settings.soft_price_cap is None:
                return False, "active_window_preserved"
            if not known_now or interval.within_cap is None:
                return False, "release_price_unknown"
            if interval.within_cap:
                return False, "cap_still_covers_now"
            return True, "cap_lowered"
        if getattr(snapshot, "price_state", None) != "ready":
            return False, "release_price_unknown"
        if str(proposal.currency).upper() != "EUR":
            return False, "release_currency_unknown"
        deadline = getattr(snapshot, "departure_at", None)
        if deadline is None or _utc(deadline) <= now:
            return False, "release_ready_by_unknown"
        deadline = _utc(deadline)
        rows = [(_utc(h.utc_start), _utc(h.utc_end), float(h.effective_minor_per_kwh)) for h in proposal.horizon]
        if known_now:
            rows.append((_utc(interval.start), _utc(interval.end), float(interval.effective_minor_per_kwh)))
        energy = _energy_between(periods, now, periods[-1][1], power)
        baseline = _priced_cost(list(union), rows, power, energy)
        alternative = _priced_cost(list(periods), rows, power)
        if baseline is None or alternative is None:
            return False, "release_price_unknown"
        if baseline <= 0:
            return False, "release_baseline_not_positive"
        if periods[0][0] > now:
            gap_start, resume = now, periods[0][0]
        else:
            gap_start, resume = periods[0][1], periods[1][0] if len(periods) > 1 else None
        if (deadline if resume is None else resume) - gap_start < RELEASE_MIN_GAP:
            return False, "release_gap_too_short"
        needed = float(proposal.minimum_energy_kwh or 0.0) if has_minimum else energy
        if _energy_between(periods, now, deadline - RELEASE_MIN_SLACK, power) < needed - _RELEASE_EPSILON:
            return False, "release_slack_too_small"
        saving = round(baseline - alternative, 6)
        if saving < RELEASE_MIN_SAVING_EUR or saving < round(RELEASE_MIN_SAVING_FRACTION * baseline, 6):
            return False, "release_saving_too_small"
        return True, "price_improvement"
    except Exception:  # noqa: BLE001 - an unreadable decision never interrupts charging
        return False, "release_decision_unavailable"


def connector_evidence(hass: Any, controller: Any, now: datetime) -> str:
    """`charging`, `waiting` (plugged in, not charging), `unplugged` or `unknown`.

    Only a fresh connector status counts. A reported status is not measured power, and a
    missing, stale, unmapped or faulted observation is unknown, never assumed idle.
    """
    try:
        from ..execution.charger_connection import normalise_ocpp
        from ..vehicles.ocpp_identity import STATUS_CONNECTOR_KEY, connector_sensor_entity_id

        source = connector_sensor_entity_id(hass, controller.ocpp_target, STATUS_CONNECTOR_KEY)
        observation = hass.states.get(source)
        if observation is None or str(observation.state).lower() in ("unknown", "unavailable"):
            return "unknown"
        timestamp = getattr(observation, "last_reported", None) or getattr(observation, "last_updated", None)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            return "unknown"
        age = (_utc(now) - timestamp).total_seconds()
        if age < 0 or age > STRICT_EVIDENCE_MAX_AGE_S:  # Stage 14 bound: 15.6 display freshness never loosens it
            return "unknown"
        state = normalise_ocpp(str(observation.state))
    except Exception:  # noqa: BLE001 - unavailable evidence is unknown
        return "unknown"
    if state == "disconnected":
        return "unplugged"
    if state == "charging":
        return "charging"
    if state in ("connected", "paused", "finished"):
        return "waiting"
    return "unknown"


def _effective_schedule(profile: dict[str, Any], now: datetime) -> tuple[Any, ...]:
    """What a fixed-time profile still says from `now`: attributes, current permission, future changes.

    Absolute instants only (the moving `startSchedule`, elapsed transitions and repeated
    equal limits are not part of it), so equivalent representations compare equal.
    """
    schedule = profile["chargingSchedule"]
    start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
    now = _utc(now)
    changes = sorted(((start + timedelta(seconds=p["startPeriod"]),
                       {k: v for k, v in p.items() if k != "startPeriod"})
                      for p in schedule["chargingSchedulePeriod"]), key=lambda c: c[0])
    state = None
    future: list[tuple[datetime, dict[str, Any]]] = []
    for at, rest in changes:
        if at <= now:
            state = rest
        elif rest != (future[-1][1] if future else state):
            future.append((at, rest))
    if state is None:
        raise ValueError("no current period")
    attributes = ({k: v for k, v in profile.items() if k != "chargingSchedule"},
                  {k: v for k, v in schedule.items() if k not in ("startSchedule", "chargingSchedulePeriod")})
    return attributes, state, future


def _allowed_seconds(profile: dict[str, Any], now: datetime) -> float:
    """Seconds of permission (any non-zero limit) a profile still gives from `now`; raises if it never closes."""
    _, state, future = _effective_schedule(profile, now)
    total, opened = 0.0, now if state.get("limit") else None
    for at, rest in future:
        if rest.get("limit"):
            opened = at if opened is None else opened
        elif opened is not None:
            total += (at - opened).total_seconds()
            opened = None
    if opened is not None:
        raise ValueError("open-ended permission")
    return total


def same_effective_schedule(accepted: dict[str, Any] | None, candidate: dict[str, Any],
                            tolerance: timedelta | None = None, *,
                            accepted_baseline: dict[str, Any] | None = None,
                            candidate_baseline: dict[str, Any] | None = None) -> bool:
    """Whether `candidate` would leave the same effective future schedule as `accepted`.

    With `tolerance`, only a switch-off (0 A) instant may differ, and by less than it; every
    other future transition and the current permission must match exactly. Anything that
    cannot be parsed is different, so a doubtful comparison never suppresses a send. "From
    now" is the candidate's own start instant, which is when it was calculated.

    Time reserve (Stage 15.1a): when both profiles come with their reserve-free twins, the tolerance is judged on
    the twins, exactly as before (a SOC-only drift of the need below it, strictly), so a reserve never turns a
    sub-tolerance drift into a send. The reserve profiles must then agree structurally, and a switch-off may
    differ by less than the tolerance plus the change of the total reserve time, which is the only other thing
    a drift of the need moves. A twin missing on either side is the plain comparison.
    """
    if not isinstance(accepted, dict):
        return False
    if tolerance is not None and isinstance(accepted_baseline, dict) and isinstance(candidate_baseline, dict):
        if not same_effective_schedule(accepted_baseline, candidate_baseline, tolerance):
            return False
        try:
            at = _utc(datetime.fromisoformat(candidate["chargingSchedule"]["startSchedule"].replace("Z", "+00:00")))
            tolerance += timedelta(seconds=abs(
                (_allowed_seconds(candidate, at) - _allowed_seconds(candidate_baseline, at))
                - (_allowed_seconds(accepted, at) - _allowed_seconds(accepted_baseline, at))))
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError, ScheduleRefused):
            return False
    try:
        now = datetime.fromisoformat(candidate["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
        old_attrs, old_state, old_future = _effective_schedule(accepted, now)
        new_attrs, new_state, new_future = _effective_schedule(candidate, now)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, ScheduleRefused):
        return False
    if old_attrs != new_attrs or old_state != new_state or len(old_future) != len(new_future):
        return False
    for (old_at, old_rest), (new_at, new_rest) in zip(old_future, new_future):
        if old_rest != new_rest:
            return False
        if old_at != new_at and not (tolerance is not None and old_rest.get("limit") == 0
                                     and abs(new_at - old_at) < tolerance):
            return False
    return True


def acknowledged_revision(record: dict[str, Any] | None) -> Any:
    """The settings revision the accepted profile was planned under, or None if unknown."""
    if not isinstance(record, dict):
        return None
    ack, attempt = record.get("acknowledged") or {}, record.get("attempt") or {}
    if "revision" in ack:
        return ack["revision"]
    return attempt.get("revision") if attempt.get("id") and attempt.get("id") == ack.get("id") else None


def _schedule(response: Any) -> dict[str, Any] | None:
    schedule = getattr(response, "charging_schedule", None)
    return schedule if isinstance(schedule, dict) else None


def _status(response: Any) -> str:
    value = getattr(response, "status", "Unknown")
    return str(getattr(value, "value", value))


def readback(response: Any, now: datetime, *, requested_at: datetime | None = None) -> dict[str, Any]:
    """Decode an OCPP composite answer into absolute UTC current changes."""
    status = _status(response)
    schedule = _schedule(response)
    result: dict[str, Any] = {"status": status, "fetched_at": _utc(now).isoformat(),
                              "requested_at": _utc(requested_at or now).isoformat(), "periods": [],
                              "schedule_start": None, "duration_s": None, "rate_unit": None}
    if status.lower() != "accepted" or schedule is None:
        return result
    # OCPP 1.6 GetCompositeSchedule puts scheduleStart on the *reply*, not inside
    # chargingSchedule (SetChargingProfile puts startSchedule inside the request).
    start_text = getattr(response, "schedule_start", None) or schedule.get("startSchedule", schedule.get("start_schedule"))
    unit = schedule.get("chargingRateUnit", schedule.get("charging_rate_unit"))
    raw = schedule.get("chargingSchedulePeriod", schedule.get("charging_schedule_period"))
    result["rate_unit"] = unit
    duration = schedule.get("duration")
    if type(duration) is int and duration > 0:
        result["duration_s"] = duration
    try:
        start = _utc(datetime.fromisoformat(start_text.replace("Z", "+00:00")))
        result["schedule_start"] = start.isoformat()
        if unit != "A" or not isinstance(raw, list):
            return result
        decoded = []
        previous_offset = -1
        for period in raw:
            offset = period.get("startPeriod", period.get("start_period"))
            limit = period["limit"]
            if (type(offset) is not int or offset < 0 or offset <= previous_offset
                    or isinstance(limit, bool) or not isinstance(limit, (int, float))
                    or not math.isfinite(limit) or limit < 0):
                return result
            previous_offset = offset
            decoded.append({"at": (start + timedelta(seconds=offset)).isoformat(), "amps": limit})
        if raw and raw[0].get("startPeriod", raw[0].get("start_period")) != 0:
            return result
        result["periods"] = decoded
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        result["periods"] = []
    return result


def matches(profile: dict[str, Any], actual: dict[str, Any], *, tolerance_s: int = VERIFY_TOLERANCE_S) -> bool:
    """Compare observable limits without asserting reported coverage."""
    return _compare_remaining(profile, actual, tolerance_s=tolerance_s, require_coverage=False)["matched"]


def _compare_remaining(profile: dict[str, Any] | None, actual: dict[str, Any] | None, *,
                       tolerance_s: int, require_coverage: bool) -> dict[str, Any]:
    """Compare only the remaining observed interval, never a historical session."""
    result: dict[str, Any] = {"matched": False, "exact": False, "reason": "no_sent_profile",
                              "tolerance_s": tolerance_s, "max_delta_s": None,
                              "coverage_start": None, "coverage_end": None, "scope": "remaining"}
    if profile is None:
        return result
    if not actual or actual.get("status", "").lower() != "accepted" or not actual.get("periods"):
        result["reason"] = "readback_unavailable"
        return result
    try:
        schedule = profile["chargingSchedule"]
        start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"])
                    for p in schedule["chargingSchedulePeriod"]]
        observed = [(_utc(datetime.fromisoformat(p["at"])), p["amps"]) for p in actual["periods"]]
        coverage_start = _utc(datetime.fromisoformat(actual["schedule_start"]))
        fetched = _utc(datetime.fromisoformat(actual["fetched_at"]))
        requested = _utc(datetime.fromisoformat(actual["requested_at"]))
        if (fetched < requested or coverage_start < requested - timedelta(seconds=tolerance_s)
                or coverage_start > fetched + timedelta(seconds=tolerance_s)):
            result["reason"] = "coverage_stale"
            return result
        if not expected or observed[0][0] != coverage_start:
            raise ValueError
        if any(a[0] >= b[0] for a, b in zip(observed, observed[1:])):
            raise ValueError
        duration = actual.get("duration_s")
        if type(duration) is not int or duration <= 0:
            if require_coverage:
                result["reason"] = "coverage_missing"
                return result
            coverage_end = expected[-1][0] + timedelta(hours=1)
        else:
            coverage_end = coverage_start + timedelta(seconds=duration)
        boundary = max(coverage_start, fetched, start)
        result.update({"coverage_start": boundary.isoformat(), "coverage_end": coverage_end.isoformat()})
        if coverage_end <= boundary:
            result["reason"] = "coverage_stale"
            return result
        if len(expected) == 1 and expected[0][1] == 0:
            # Bound the claim to one hour after the observation, never forever.
            result["scope"] = "bounded_held_off"
            horizon = boundary + timedelta(hours=1)
            if ((fetched - requested).total_seconds() > tolerance_s or coverage_start > requested
                    or expected[0][0] > requested):
                result["reason"] = "coverage_boundary_ambiguous"
                return result
            if type(duration) is not int or duration <= 0:
                result["reason"] = "coverage_missing"
                return result
            if coverage_end < horizon:
                result["reason"] = "coverage_too_short"
                return result
            relevant = [(at, amps) for at, amps in observed if at <= horizon]
            if any(amps != 0 for _, amps in relevant):
                result["reason"] = "limits_or_transitions_differ"
                return result
            result.update({"matched": True, "exact": True, "reason": "matched", "max_delta_s": 0,
                           "coverage_end": horizon.isoformat()})
            return result
        if len(expected) < 2:
            raise ValueError
        horizon = expected[-1][0] + timedelta(hours=1)
        if coverage_end < horizon:
            result["reason"] = "coverage_too_short"
            return result
        wanted = [(at, amps) for at, amps in expected[1:] if at > boundary]
        if not wanted:
            result["reason"] = "no_remaining_transitions"
            return result
        if any(abs((at - boundary).total_seconds()) <= tolerance_s for at, _ in expected[1:]):
            result["reason"] = "coverage_boundary_ambiguous"
            return result
        expected_limit = next(amps for at, amps in reversed(expected) if at <= boundary)
        current = next(amps for at, amps in reversed(observed) if at <= boundary)
        if current != expected_limit:
            result["reason"] = "limits_or_transitions_differ"
            return result
        changes = []
        for at, amps in observed:
            if at <= boundary:
                continue
            if at > horizon:
                break
            if amps != current:
                changes.append((at, amps))
                current = amps
        if len(changes) != len(wanted):
            result["reason"] = "limits_or_transitions_differ"
            return result
        delta = max(abs((at - want_at).total_seconds()) for (at, _), (want_at, _) in zip(changes, wanted))
        result["max_delta_s"] = delta
        if delta > tolerance_s or any(amps != want_amps for (_, amps), (_, want_amps) in zip(changes, wanted)):
            result["reason"] = "limits_or_transitions_differ"
            return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, StopIteration, ScheduleRefused):
        result["reason"] = "readback_unavailable"
        return result
    result.update({"matched": True, "exact": delta < 1, "reason": "matched" if delta < 1 else "matched_with_drift"})
    return result


def compare_schedule(profile: dict[str, Any] | None, actual: dict[str, Any] | None) -> dict[str, Any]:
    """A match requires reported coverage through one hour beyond the last stop."""
    return _compare_remaining(profile, actual, tolerance_s=VERIFY_TOLERANCE_S, require_coverage=True)


CHECK_HEALTHY = "healthy"
CHECK_UNKNOWN = "unknown"
CHECK_DIFFERS = "differs_unconfirmed"
CHECK_CLOCK_DOUBT_S = 30  # wall clock vs monotonic clock drift across one read that makes the comparison doubtful
_DISPATCHED_KEY = "spotnav_morek_dispatched"
CHECK_CONFIRMED = "differs_confirmed"  # Stage 15.4a: a mismatch two clean readbacks agree on (see `confirm_mismatch`)
#: Stage 15.4a feature gate, flipped on by 15.4b (last step) once the active-charge deferral, the final pre-wire
#: freshness revalidation and the post-repair escalation exist and are tested. It does not by itself send anything:
#: every send still needs a confirmation (two fresh covering readbacks), every existing guard and the repair budget.
REPAIR_DISPATCH_ENABLED = True
REPAIR_CONFIRM_GAP_S = 30  # the earlier observation is at least this much older than the latest
REPAIR_FRESH_S = 30  # the latest observation is at most this old when the decision is made AND at the final pre-wire check
#: 15.4b: a correct current limit with fresh/unknown flow and a difference only this far in the future (or more) is
#: deferred; the checker's recheck cadence (300 s, `CHECK_RECHECK_DELAYS`) is the 5-minute deferral recheck.
REPAIR_DEFER_GAP_S = 600
_REPAIR_ESCALATION_KEY = "repair_escalation"
REPAIR_BUDGET_MAX = 2  # wire-reaching repairs per rolling window per charger
REPAIR_BUDGET_WINDOW = timedelta(hours=24)
REPAIR_MIN_SPACING = timedelta(minutes=30)
_REPAIR_LIST_KEY = "repair_attempts"


def confirm_mismatch(observations: list[dict[str, Any]], latest: dict[str, Any]) -> bool:
    """Stage 15.4a: whether `latest` plus an earlier observation confirm a material mismatch. Pure.

    Each observation is `{attempt_id, connection_id, readback_at (ISO), mono (monotonic s)}` from a clean covering
    `limits_or_transitions_differ` readback; `latest` also carries `mono_age` (monotonic seconds since it was read).
    The latest must be fresh (<= `REPAIR_FRESH_S` on both clocks) and an earlier one from the same connection and
    acknowledged attempt must be >= `REPAIR_CONFIRM_GAP_S` older on both the monotonic clock and the charger
    readback timestamps (a replayed or re-stamped reading, a clock jump or one odd reading never confirms)."""
    try:
        latest_at = _utc(datetime.fromisoformat(latest["readback_at"]))
        age = (datetime.now(timezone.utc) - latest_at).total_seconds()
        if not 0 <= age <= REPAIR_FRESH_S or not 0 <= latest["mono_age"] <= REPAIR_FRESH_S:
            return False
        for earlier in observations:
            if (earlier is latest or earlier["attempt_id"] != latest["attempt_id"]
                    or earlier["connection_id"] != latest["connection_id"]):
                continue
            wall = (latest_at - _utc(datetime.fromisoformat(earlier["readback_at"]))).total_seconds()
            mono = latest["mono"] - earlier["mono"]
            if wall >= REPAIR_CONFIRM_GAP_S and mono >= REPAIR_CONFIRM_GAP_S and abs(wall - mono) <= REPAIR_CONFIRM_GAP_S:
                return True
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, ScheduleRefused):
        return False
    return False


def mismatch_facts(profile: dict[str, Any] | None, actual: dict[str, Any] | None) -> dict[str, Any]:
    """Stage 15.4b: what a clean covering mismatch consists of, from the same readback. Pure; the comparison stays
    `compare_schedule`'s. `{current_wrong, diff_in_s}`: `current_wrong` True when the limit in force at the readback
    differs from the intended one (then `diff_in_s` is 0), False when it matches and only later transitions differ
    (`diff_in_s` = seconds from the readback to the first differing future change), None/None when the readback does
    not say (never treated as a wrong limit and never as a distant difference)."""
    unknown: dict[str, Any] = {"current_wrong": None, "diff_in_s": None}
    try:
        schedule = profile["chargingSchedule"]
        start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        expected = [(start + timedelta(seconds=p["startPeriod"]), p["limit"]) for p in schedule["chargingSchedulePeriod"]]
        observed = [(_utc(datetime.fromisoformat(p["at"])), p["amps"]) for p in actual["periods"]]
        boundary = max(_utc(datetime.fromisoformat(actual["schedule_start"])),
                       _utc(datetime.fromisoformat(actual["fetched_at"])), start)
        wanted = next((amps for at, amps in reversed(expected) if at <= boundary), 0)
        current = next(amps for at, amps in reversed(observed) if at <= boundary)
        if current != wanted:
            return {"current_wrong": True, "diff_in_s": 0.0}

        def changes(items: list[tuple[datetime, Any]], base: Any) -> list[tuple[datetime, Any]]:
            found = []
            for at, amps in items:
                if at > boundary and amps != base:
                    found.append((at, amps))
                    base = amps
            return found

        planned, seen = changes(expected, wanted), changes(observed, current)
        moment = None
        for (want_at, want_amps), (at, amps) in zip(planned, seen):
            if amps != want_amps or abs((at - want_at).total_seconds()) > VERIFY_TOLERANCE_S:
                moment = min(want_at, at)
                break
        else:
            extra = planned[len(seen):] + seen[len(planned):]
            moment = extra[0][0] if extra else None
        if moment is None:
            return unknown
        return {"current_wrong": False, "diff_in_s": max(0.0, (moment - boundary).total_seconds())}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, StopIteration, IndexError, ScheduleRefused):
        return unknown


def measured_flow(live: dict[str, Any] | None) -> str:
    """Stage 15.4b: `charging`, `idle` or `unknown` from *fresh measured* power/current only (the existing
    `_live_measurements` readings and flow floors). Any fresh reading showing flow is charging; idle needs a fresh
    reading and none showing flow; a missing/stale/unreadable one is unknown, never idle."""
    from ..execution.charge_progress import ZERO_CURRENT_A
    from ..sessions.history import MIN_FLOW_W

    seen: list[bool] = []
    for key, floor in (("power_w", MIN_FLOW_W), ("current_a", ZERO_CURRENT_A)):
        reading = live.get(key) if isinstance(live, dict) else None
        value = reading.get("value") if isinstance(reading, dict) else None
        if (isinstance(reading, dict) and reading.get("fresh") is True and isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value)):
            seen.append(value >= floor)
    if any(seen):
        return "charging"
    return "idle" if seen else "unknown"


def repair_deferral(facts: Any, flow: str, elapsed_s: float) -> str | None:
    """Stage 15.4b: why a confirmed repair waits (`future_difference`, `facts_unknown`) or None to proceed. Pure.

    Proceeds at once when the car is measured idle or the current limit is wrong (the charge is not correct as it
    runs), or when the first differing future change is `REPAIR_DEFER_GAP_S` or less away (`elapsed_s` = age of the
    readback). Otherwise (flow charging OR unknown) it waits: unknown flow is never permission to interrupt, and facts
    that do not say whether the limit is wrong are never permission to resend either."""
    if flow == "idle":
        return None
    if not isinstance(facts, dict):
        return "facts_unknown"
    if facts.get("current_wrong") is True:
        return None
    gap = facts.get("diff_in_s")
    if facts.get("current_wrong") is False and isinstance(gap, (int, float)) and not isinstance(gap, bool):
        return None if gap - max(0.0, elapsed_s) <= REPAIR_DEFER_GAP_S else "future_difference"
    return "facts_unknown"


def readback_age_s(readback_at: Any) -> float:
    """Seconds since an ISO readback timestamp (0 for a future one); raises on an unreadable timestamp."""
    return max(0.0, (datetime.now(timezone.utc) - _utc(datetime.fromisoformat(readback_at))).total_seconds())


def repaired_ids(record: dict[str, Any] | None) -> set[str]:
    """Attempt ids the stored repair ledger names (read as untrusted; unreadable entries are skipped)."""
    raw = record.get(_REPAIR_LIST_KEY) if isinstance(record, dict) else None
    return {e["attempt_id"] for e in raw if isinstance(e, dict) and isinstance(e.get("attempt_id"), str)} \
        if isinstance(raw, list) else set()


def repair_escalated(record: dict[str, Any] | None, attempt_id: Any) -> bool:
    """The persisted post-repair escalation names this (repaired) acknowledged attempt: a person must look."""
    marker = record.get(_REPAIR_ESCALATION_KEY) if isinstance(record, dict) else None
    return isinstance(marker, dict) and bool(attempt_id) and marker.get("attempt_id") == attempt_id


def repair_budget(record: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """Stage 15.4a: the stored repair budget, read as untrusted. No I/O.

    `{state, recent, next_at}`: `ok`; `spacing` (the newest is under `REPAIR_MIN_SPACING` old, `next_at` says when);
    `exhausted` (`REPAIR_BUDGET_MAX` inside the rolling window); `invalid` (a malformed list or entry, or one dated
    in the future: no repair, a person looks). A missing list is an old record: an empty budget."""
    raw = record.get(_REPAIR_LIST_KEY) if isinstance(record, dict) else None
    if raw is None:
        return {"state": "ok", "recent": [], "next_at": None}
    now = _utc(now)
    recent: list[dict[str, str]] = []
    try:
        if not isinstance(raw, list) or len(raw) > 16:
            raise ValueError
        for entry in raw:
            if (not isinstance(entry, dict) or not isinstance(entry.get("attempt_id"), str)
                    or not isinstance(entry.get("at"), str)):
                raise ValueError
            at = _utc(datetime.fromisoformat(entry["at"]))
            if at > now + timedelta(minutes=5):
                raise ValueError
            if now - at < REPAIR_BUDGET_WINDOW:
                recent.append({"at": at.isoformat(), "attempt_id": entry["attempt_id"]})
    except (ValueError, TypeError, OverflowError, ScheduleRefused):
        return {"state": "invalid", "recent": [], "next_at": None}
    recent.sort(key=lambda entry: entry["at"])
    if len(recent) >= REPAIR_BUDGET_MAX:
        return {"state": "exhausted", "recent": recent, "next_at": None}
    if recent:
        due = datetime.fromisoformat(recent[-1]["at"]) + REPAIR_MIN_SPACING
        if now < due:
            return {"state": "spacing", "recent": recent, "next_at": due.isoformat()}
    return {"state": "ok", "recent": recent, "next_at": None}


def check_candidate(record: dict[str, Any] | None, now: datetime, *, sending: Any = None,
                    verification_timer: bool = False, dispatched: str | None = None,
                    data: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Stage 15.3: `(profile, acknowledged attempt id, why not)` for a read-only schedule check. No I/O.

    Only the *latest acknowledged* intent that is still inside its coverage is a candidate: a routine plan, a
    Pause hold or a Charge Now profile, each exactly as its accepted attempt sent it. An uncertain record, an
    upload in flight, a newer attempt of any state, a verification that has not finished and an intent that is
    over or replaced are never checked (the reason says what was not checked)."""
    if not isinstance(record, dict):
        return None, None, "no_intent"
    ack, attempt = record.get("acknowledged"), record.get("attempt")
    ack_id = ack.get("id") if isinstance(ack, dict) else None
    if record.get("uncertain") is not False:
        return None, ack_id, "outcome_uncertain"
    if sending:
        return None, ack_id, "upload_pending"
    if not isinstance(ack, dict) or not ack_id or not ack.get("fingerprint"):
        return None, ack_id, "no_acknowledged_intent"
    if not isinstance(attempt, dict) or attempt.get("id") != ack_id or attempt.get("state") != "accepted":
        return None, ack_id, "newer_attempt"
    if verification_timer or (dispatched == ack_id and isinstance(data, dict) and not data.get("verified")
                              and not (data.get("verification") or {}).get("attempts")):
        return None, ack_id, "verification_pending"
    profile = ack["profile"] if "profile" in ack else attempt.get("profile")
    if not isinstance(profile, dict):
        return None, ack_id, "profile_unavailable"
    try:
        now = _utc(now)
        pause, override = record.get("schedule_pause"), record.get("charge_now")
        pause_id, override_id = attempt.get("pause_id"), attempt.get("override_id")
        if pause_id is not None:
            if not isinstance(pause, dict) or pause.get("id") != pause_id:
                return None, ack_id, "intent_changed"
        elif pause is not None:
            return None, ack_id, "intent_changed"
        override_live = isinstance(override, dict) and _utc(datetime.fromisoformat(override["end"])) > now
        if override_id is not None:
            if not isinstance(override, dict) or override.get("id") != override_id:
                return None, ack_id, "intent_changed"
            if not override_live:
                return None, ack_id, "intent_expired"
        elif override_live:
            return None, ack_id, "intent_changed"
        schedule = profile["chargingSchedule"]
        periods = schedule["chargingSchedulePeriod"]
        start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        held_off = len(periods) == 1 and periods[0]["limit"] == 0  # open-ended: its claim is bounded at read time
        if not held_off and start + timedelta(seconds=periods[-1]["startPeriod"] + 3600) <= now:
            return None, ack_id, "intent_expired"
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError, ScheduleRefused):
        return None, ack_id, "profile_unavailable"
    return profile, ack_id, None


def classify_check(comparison: dict[str, Any], effective: dict[str, Any] | None, *,
                   clock_doubt: bool = False) -> tuple[str, str]:
    """Class and reason of one read-only check, from the existing `compare_schedule` result (no new comparator).

    Healthy needs a clean match; Differs-unconfirmed needs one clean `limits_or_transitions_differ` from an accepted
    readback in amps; everything else (unavailable, coverage reasons, clock doubt) is Unknown and never promoted."""
    if clock_doubt:
        return CHECK_UNKNOWN, "clock_doubt"
    reason = str(comparison.get("reason") or "readback_unavailable")
    if comparison.get("matched"):
        return CHECK_HEALTHY, reason
    if (reason == "limits_or_transitions_differ" and isinstance(effective, dict)
            and str(effective.get("status", "")).lower() == "accepted" and effective.get("rate_unit") == "A"):
        return CHECK_DIFFERS, reason
    return CHECK_UNKNOWN, reason


def session_start_schedule_evidence(profile: dict[str, Any] | None, actual: dict[str, Any] | None,
                                    now: datetime, *, tolerance_s: int = 0) -> str:
    """Conservative read-only prerequisite, not authorization to dispatch.

    Require a comparison covering the remaining profile and a read at most 30
    seconds old. Optional bounded drift is never permission to start near either
    schedule's transition. External writers remain unobservable.
    """
    if profile is None:
        return "no_current_plan"
    if not actual:
        return "readback_unavailable"
    if actual.get("rate_unit") != "A":
        return "readback_unit_unavailable"
    if type(tolerance_s) is not int or not 0 <= tolerance_s <= VERIFY_TOLERANCE_S:
        return "invalid_tolerance"
    try:
        fetched = _utc(datetime.fromisoformat(actual["fetched_at"]))
        age = (_utc(now) - fetched).total_seconds()
        if not 0 <= age <= 30:
            return "readback_stale"
        comparison = _compare_remaining(profile, actual, tolerance_s=tolerance_s, require_coverage=True)
        if not comparison["matched"]:
            return comparison["reason"]
        start = _utc(datetime.fromisoformat(comparison["coverage_start"]))
        end = _utc(datetime.fromisoformat(comparison["coverage_end"]))
        if not start <= _utc(now) < end:
            return "coverage_stale"
        current = next(p["amps"] for p in reversed(actual["periods"])
                       if _utc(datetime.fromisoformat(p["at"])) <= _utc(now))
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not 0 <= current <= 16:
            return "unsafe_current_limit"
        schedule = profile["chargingSchedule"]
        profile_start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
        expected = [(profile_start + timedelta(seconds=p["startPeriod"]), p["limit"])
                    for p in schedule["chargingSchedulePeriod"]]
        observed = [(_utc(datetime.fromisoformat(p["at"])), p["amps"]) for p in actual["periods"]]
        if tolerance_s and any(abs((at - _utc(now)).total_seconds()) <= tolerance_s
                               for at, _ in expected[1:] + observed[1:]):
            return "transition_boundary_ambiguous"
        intended = next(amps for at, amps in reversed(expected) if at <= _utc(now))
        if current != intended:
            return "limits_or_transitions_differ"
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, StopIteration, ScheduleRefused):
        return "readback_unavailable"
    return "matched"


def _cancel_verification(hass: HomeAssistant, entry_id: str) -> None:
    cancel = hass.data.get(_VERIFY_KEY, {}).pop(entry_id, None)
    if cancel is not None:
        cancel()


def _verification_lifecycle(hass: HomeAssistant, entry_id: str, entry: Any) -> dict[str, Any]:
    """One unload token per entry instance, shared by immediate and delayed reads."""
    lifecycles = hass.data.setdefault(_LIFECYCLE_KEY, {})
    token = lifecycles.get(entry_id)
    if token is not None and token["entry"] is entry:
        return token
    token = {"entry": entry, "live": True}
    lifecycles[entry_id] = token
    def unload() -> None:
        token["live"] = False
        if lifecycles.get(entry_id) is token:
            _cancel_verification(hass, entry_id)
            lifecycles.pop(entry_id, None)
    entry.async_on_unload(unload)
    return token


def _schedule_verification(hass: HomeAssistant, entry_id: str, sent_at: str, attempt: int = 0,
                           attempt_id: str | None = None) -> None:
    """Only retry readback, never Set/ClearChargingProfile. No indefinite polling."""
    _cancel_verification(hass, entry_id)

    async def check(_now: datetime) -> None:
        if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not cancel_handle:
            return
        try:
            await async_schedule_action(hass, entry_id, "fetch", expected_sent_at=sent_at,
                                        verification_attempt=attempt, expected_attempt_id=attempt_id,
                                        verification_handle=cancel_handle)
        except ScheduleRefused as error:
            # Unload, identity change, or a newer send/clear invalidates the old operation.
            if error.code != "morek_offline":
                if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is cancel_handle:
                    _cancel_verification(hass, entry_id)
                return
            data, store = await _state(hass, entry_id)
            async with hass.data[_DATA_KEY][entry_id][2]:
                if (hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not cancel_handle
                        or data.get("sent_at") != sent_at or data.get("cleanup") or data.get("verified")):
                    return
                data["verified"] = False
                data["effective"] = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(),
                                     "periods": []}
                verification = data.setdefault("verification", {})
                verification.update({"reason": "readback_unavailable", "attempts": attempt + 2,
                                     "checked_at": datetime.now(timezone.utc).isoformat(),
                                     "readback_at": data["effective"]["fetched_at"], "coverage_start": None, "coverage_end": None,
                                     "pending": False, "next_check_at": None})
                if attempt + 1 < len(VERIFY_DELAYS):
                    _schedule_verification(hass, entry_id, sent_at, attempt + 1, attempt_id)
                    verification.update({"pending": True, "next_check_at": (
                        datetime.now(timezone.utc) + timedelta(seconds=VERIFY_DELAYS[attempt + 1])).isoformat()})
                else:
                    _cancel_verification(hass, entry_id)
                    _LOGGER.warning("Morek schedule still unverified after bounded readback checks: offline")
                await store.async_save(data)
        except Exception:
            if hass.data.get(_VERIFY_KEY, {}).get(entry_id) is cancel_handle:
                _cancel_verification(hass, entry_id)
            _LOGGER.exception("Morek readback verification failed")

    cancel_handle = async_call_later(hass, 0 if attempt < 0 else VERIFY_DELAYS[attempt], check)
    hass.data.setdefault(_VERIFY_KEY, {})[entry_id] = cancel_handle


def _verification_state(hass: HomeAssistant, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Persisted pending state cannot claim a timer survived a Home Assistant restart."""
    verification = dict(data.get("verification") or {})
    if verification.get("pending") and entry_id not in hass.data.get(_VERIFY_KEY, {}):
        verification.update({"pending": False, "reason": "verification_interrupted", "next_check_at": None})
    return verification


def _readback_associated(verification: dict[str, Any], effective: Any) -> bool:
    """A comparison's coverage refers only to the readback it actually compared."""
    return bool(isinstance(effective, dict) and verification.get("readback_at")
                and verification["readback_at"] == effective.get("fetched_at"))


def _verification_coverage_current(verification: dict[str, Any], now: datetime) -> bool:
    """A historical comparison cannot verify limits after its bounded coverage ends."""
    try:
        start = _utc(datetime.fromisoformat(verification["coverage_start"].replace("Z", "+00:00")))
        end = _utc(datetime.fromisoformat(verification["coverage_end"].replace("Z", "+00:00")))
        return start <= now < end
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, ScheduleRefused):
        return False


def _resume_authorized(record: dict[str, Any], worker: Any, generation: int) -> bool:
    """Recover a completed Resume from its settled, matching durable dispatch."""
    pause = record.get("schedule_pause") or {}
    if pause.get("type") != "resume_requested":
        return False
    if (getattr(worker, "resume_interrupted", None) == pause.get("id")
            or record.get("resume_interrupted") == pause.get("id")):
        return False  # a recorded Stop pre-empted this Resume: only a new person Resume continues
    if getattr(worker, "resume_ticket", None) == (pause.get("id"), generation):
        return True
    attempt = record.get("attempt") or {}
    ack = record.get("acknowledged") or {}
    return (record.get("uncertain") is False and attempt.get("state") == "accepted"
            and attempt.get("source") == "worker" and attempt.get("pause_id") == pause.get("id")
            and bool(attempt.get("id")) and attempt.get("id") == ack.get("id")
            and bool(attempt.get("fingerprint")) and attempt.get("fingerprint") == ack.get("fingerprint"))


def _owned_pause_status(outcomes: dict[str, Any], verification: dict[str, Any], verified: bool,
                        worker: Any, *, stop_pending: bool = False) -> dict[str, Any]:
    """Separate durable intent from request and bounded observation, not physical flow."""
    pause = outcomes.get("schedule_pause")
    if not isinstance(pause, dict):
        return {"intent": "unknown" if stop_pending or outcomes.get("uncertain") else "none",
                "request": "stop_pending" if stop_pending else "unknown", "ack": None, "readback": "unknown", "measured": "unknown"}
    attempt = outcomes.get("attempt") or {}
    matching = not stop_pending and attempt.get("pause_id") == pause.get("id")
    # A worker reason may describe the previous intent; never attach it to a new one.
    request = "stop_pending" if stop_pending else attempt.get("state", "unknown") if matching else "pending"
    if (not matching and not stop_pending and pause.get("type") == "resume_requested" and worker is not None
            and getattr(worker, "resume_ticket", None) is None
            and not _resume_authorized(outcomes, worker, 0)):
        request = "resume_requires_confirmation"
    return {"intent": pause.get("type", "unknown"), "request": request,
            "ack": attempt.get("ack") if matching else None,
            "readback": "bounded_match" if matching and verified and verification.get("scope") in ("bounded_held_off", "remaining")
            else "unverified", "coverage_start": verification.get("coverage_start") if matching and verified else None,
            "coverage_end": verification.get("coverage_end") if matching and verified else None,
            "measured": "unknown"}


def _matching_points(hass: HomeAssistant, target: Any) -> list[tuple[str, Any]]:
    """Resolve HA OCPP's configured charger alias to its physical WebSocket station ID."""
    found: list[tuple[str, Any]] = []
    for system in hass.data.get("ocpp", {}).values():
        points = getattr(system, "charge_points", None)
        cpids = getattr(system, "cpids", None)
        if not isinstance(points, dict) or not isinstance(cpids, dict):
            continue
        physical_id = cpids.get(target.devid, target.devid)
        point = points.get(physical_id)
        if point is not None:
            found.append((physical_id, point))
    return found


def _identity_status(hass: HomeAssistant, target: Any) -> dict[str, Any]:
    """Read-only diagnosis; an alias is valid only when HA OCPP maps it to this Morek."""
    if target is None:
        return {"supported": False, "reason": "no_ocpp_target", "configured_id": None,
                "resolved_id": None, "connector_id": None, "match_count": 0, "ocpp_version": None}
    found = _matching_points(hass, target)
    resolved = found[0][0] if len(found) == 1 else (target.devid if not found else None)
    reason = None
    if len(found) > 1:
        reason = "ambiguous_station"
    elif target.connector_id != MOREK_CONNECTOR_ID:
        reason = "wrong_connector"
    elif resolved != MOREK_STATION_ID:
        reason = "station_not_matched"
    elif found and getattr(found[0][1], "_ocpp_version", None) != "1.6":
        reason = "unsupported_ocpp_version"
    return {"supported": reason is None, "reason": reason, "configured_id": target.devid,
            "resolved_id": resolved if len(found) == 1 else None, "connector_id": target.connector_id,
            "match_count": len(found), "ocpp_version": getattr(found[0][1], "_ocpp_version", None)
             if len(found) == 1 else None}


def _intent_identity_status(hass: HomeAssistant, target: Any) -> dict[str, Any]:
    """Metadata-only offline binding from a physical ID or one retained alias mapping."""
    identity = _identity_status(hass, target)
    if target is not None and target.connector_id == MOREK_CONNECTOR_ID and identity.get("match_count") == 0:
        alias = getattr(target, "devid", None)
        mappings = [cpids[alias] for system in hass.data.get("ocpp", {}).values()
                    if isinstance((cpids := getattr(system, "cpids", None)), dict) and alias in cpids]
        direct = alias == MOREK_STATION_ID and not mappings
        mapped = len(mappings) == 1 and mappings[0] == MOREK_STATION_ID
        if direct or mapped:
            return {**identity, "supported": True, "resolved_id": MOREK_STATION_ID,
                    "reason": "offline_owned_intent", "offline_binding": "direct" if direct else "alias"}
    return identity


def _owned_intent_identity_ok(identity: dict[str, Any]) -> bool:
    from ..execution.command_admission import classify_morek_identity
    return classify_morek_identity(identity) == "supported_morek" or (
        identity.get("reason") == "offline_owned_intent" and identity.get("offline_binding") in ("direct", "alias")
        and isinstance(identity.get("configured_id"), str) and bool(identity.get("configured_id"))
        and identity.get("resolved_id") == MOREK_STATION_ID and identity.get("connector_id") == MOREK_CONNECTOR_ID
        and identity.get("match_count") == 0 and identity.get("supported") is True)


def _charge_point(hass: HomeAssistant, target: Any) -> Any:
    """Use only the one connected OCPP 1.6 physical Morek charger."""
    found = _matching_points(hass, target)
    if len(found) != 1 or found[0][0] != MOREK_STATION_ID:
        raise ScheduleRefused("morek_offline")
    point = found[0][1]
    if getattr(point, "_ocpp_version", None) != "1.6" or getattr(point, "status", None) != "ok":
        raise ScheduleRefused("morek_offline")
    return point


def link_reading(hass: HomeAssistant, target: Any) -> tuple[str, Any, int | None]:
    """Stage 15.2: the point's connection as `_charge_point` judges it, read locally (no OCPP traffic).

    Returns `(state, point, boot_generation)`. `up`/`down` only for exactly one point of the one Morek station and
    OCPP 1.6 whose `status` is a string (`"ok"` is up). A missing, ambiguous, foreign or unsupported point, or a
    `status` that is not a string, is `unknown` (never `down`). `status`/`charger_generation` are attributes of the
    installed OCPP integration's point object, read via `getattr`; that it exposes them is unverified."""
    try:
        found = _matching_points(hass, target)
    except Exception:  # noqa: BLE001 - an unreadable registry is unknown, not down
        return "unknown", None, None
    if len(found) != 1 or found[0][0] != MOREK_STATION_ID:
        return "unknown", None, None
    point = found[0][1]
    status = getattr(point, "status", None)
    if getattr(point, "_ocpp_version", None) != "1.6" or not isinstance(status, str):
        return "unknown", None, None
    boot = getattr(point, "charger_generation", None)
    return ("up" if status == "ok" else "down"), point, (boot if type(boot) is int and boot > 0 else None)


LIVE_MAX_AGE_S = STRICT_EVIDENCE_MAX_AGE_S  # the strict `fresh` flag control flow reads; display uses 15.6 judgements


def _live_reading(state: Any, now: datetime, value: Any, unit: str) -> dict[str, Any] | None:
    """One connector sensor reading with its own timestamp, or None when unreadable.

    A real 0 stays 0. A reading is stamped, never refreshed: a stale one keeps its old
    `observed_at` and `fresh: False`, so the reader can say how old it is.
    """
    if state is None or value is None:
        return None
    stamp = getattr(state, "last_reported", None) or getattr(state, "last_updated", None)
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        return None  # an unknown observation time is not evidence of anything current
    age = (now - stamp).total_seconds()
    return {"value": value, "unit": unit, "observed_at": stamp.isoformat(),
            "fresh": 0 <= age <= LIVE_MAX_AGE_S}


def _live_measurements(hass: HomeAssistant, controller: Any, now: datetime,
                       entities: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Read-only, connector-bound charger observations; nothing is inferred or written.

    `status` is the connector's *reported* state, `current_a` and `power_w` are measured flow,
    `energy_register_kwh` is the cumulative import register (not this session's energy). Each is
    None when its source is missing, unavailable or unreadable. Power and current are never derived
    from each other or from a schedule limit.

    Power has no assumed entity. It is read from (1) the user's explicitly configured power entity for this
    charger, else (2) the one enabled OCPP sensor whose registry identity names `Power.Active.Import` of
    exactly this connector (`connector_measurand_entity`); two candidates or none read as None. The energy
    register uses the same strict identity match. `sources` says which rule produced each, or why not.
    When `entities` is given, the entity id each reading was taken from is stored in it (keys `status`,
    `current_a`, `power_w`, `energy_register_kwh`; evidence capture keeps it as provenance, the status
    payload never carries it).
    """
    from ..execution.charge_progress import connector_current
    from ..execution.charger_connection import normalise_ocpp
    from ..execution.power_energy import power_w_of
    from ..vehicles.ocpp_identity import (CURRENT_IMPORT_KEY, ENERGY_REGISTER_KEY, POWER_ACTIVE_IMPORT_KEY,
                                          STATUS_CONNECTOR_KEY, TRANSACTION_ID_KEY, _classes_allow_register,
                                          connector_measurand_entity, connector_sensor_entity_id)

    target = getattr(controller, "ocpp_target", None)
    live: dict[str, Any] = {"connector_id": getattr(target, "connector_id", None), "status": None,
                            "current_a": None, "power_w": None, "energy_register_kwh": None,
                            "control_state": None, "transaction": None,
                            "sources": {"power": "none", "energy": "none"}}
    if target is None:
        return live

    def read(entity_id: str | None) -> Any:
        return hass.states.get(entity_id) if entity_id else None

    def attempt(compute: Any) -> Any:
        try:
            return compute()
        except Exception:  # noqa: BLE001 - an unreadable source is unknown, not an API failure
            return None

    sink = entities if entities is not None else {}
    sink["status"] = attempt(lambda: connector_sensor_entity_id(hass, target, STATUS_CONNECTOR_KEY))
    status_state = attempt(lambda: read(sink["status"]))
    raw = None if status_state is None or str(status_state.state).lower() in ("unknown", "unavailable", "") \
        else str(status_state.state)
    if raw is not None:
        reading = _live_reading(status_state, now, raw, "")
        if reading is not None:
            reading["normalized"] = attempt(lambda: normalise_ocpp(raw))
            live["status"] = {k: v for k, v in reading.items() if k != "unit"}
    sink["current_a"] = attempt(lambda: connector_sensor_entity_id(hass, target, CURRENT_IMPORT_KEY))
    state = attempt(lambda: read(sink["current_a"]))
    live["current_a"] = attempt(lambda: _live_reading(state, now, connector_current(state), "A"))
    configured = getattr(controller, "power_entity_id", None)
    if isinstance(configured, str) and configured:
        power_id, live["sources"]["power"] = configured, "configured_entity"
    else:
        found = attempt(lambda: connector_measurand_entity(hass, target, POWER_ACTIVE_IMPORT_KEY))
        power_id = found.entity_id if found is not None else None
        live["sources"]["power"] = "ocpp_registry" if power_id else found.status if found is not None else "none"
    sink["power_w"] = power_id
    state = attempt(lambda: read(power_id))
    live["power_w"] = attempt(lambda: _live_reading(state, now, power_w_of(state), "W"))

    def energy() -> Any:
        found = connector_measurand_entity(hass, target, ENERGY_REGISTER_KEY)
        live["sources"]["energy"] = "ocpp_registry" if found.entity_id else found.status
        sink["energy_register_kwh"] = found.entity_id
        sensor = read(found.entity_id) if found.entity_id and _classes_allow_register(hass, found.entity_id) else None
        if sensor is None or str(sensor.state).lower() in ("unknown", "unavailable", ""):
            return None
        unit = (sensor.attributes or {}).get("unit_of_measurement")
        factor = {"kWh": 1.0, "Wh": 0.001}.get(str(unit))
        value = float(sensor.state)
        if factor is None or value != value or value in (float("inf"), float("-inf")) or value < 0:
            return None
        return _live_reading(sensor, now, value * factor, "kWh")

    live["energy_register_kwh"] = attempt(energy)

    # What the charge-control switch and the transaction-id sensor report. Both are observations of the
    # charger's own state: the switch is expected to be off in Preparing before authorization, and a
    # transaction id is reduced to present/absent here (the raw id never leaves the backend).
    switch = attempt(lambda: read(getattr(controller, "charge_control", None)))
    on_off = None if switch is None else str(switch.state).lower()
    live["control_state"] = attempt(lambda: _live_reading(switch, now, on_off if on_off in ("on", "off") else None, ""))
    transaction = attempt(lambda: read(connector_sensor_entity_id(hass, target, TRANSACTION_ID_KEY)))

    def present() -> bool | None:
        if transaction is None:
            return None
        try:
            number = float(str(transaction.state))
        except ValueError:
            return None
        return None if number != number or number < 0 or number != int(number) else number > 0

    reading = attempt(lambda: _live_reading(transaction, now, present(), ""))
    if reading is not None:
        changed = getattr(transaction, "last_changed", None)
        reading["changed_at"] = changed.isoformat() if isinstance(changed, datetime) and changed.tzinfo else None
        live["transaction"] = reading
    return live


def _charging_enabled(reading: dict[str, Any] | None, judgement: dict[str, Any] | None = None) -> dict[str, Any]:
    """The charge-control switch as evidence that charging is enabled; never a command or an inference.

    Only a current `on` is `enabled`. A current `off` and an unreadable or not-current switch are both `not_ready`
    (unconfirmed is not enabled). `judgement` (15.6) says whether the quiet derived switch is still current on the
    link; without one the strict `fresh` flag decides. Even `enabled` proves neither authorization nor a transaction."""
    if not isinstance(reading, dict) or reading.get("value") not in ("on", "off"):
        return {"state": "not_ready", "reason": "control_unconfirmed"}
    base = {"observed_at": reading.get("observed_at")}
    current = reading.get("fresh") is True if judgement is None else judgement.get("state") == "current"
    if not current:
        return {"state": "not_ready", "reason": "control_unconfirmed", **base}
    if reading["value"] == "off":
        return {"state": "not_ready", "reason": "control_off", **base}
    return {"state": "enabled", "reason": "control_on", **base}


def _reading_time(reading: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(reading["observed_at"])
    except (TypeError, KeyError, ValueError):
        return None
    return stamp if stamp.tzinfo is not None else None


def _quantity_freshness(hass: Any, live: dict[str, Any], monitor: Any, entry_id: str | None,
                        now: datetime) -> dict[str, Any]:
    """Stage 15.6: the shared display/readiness judgement per quantity (additive; control flow never reads it).

    Event quantities are current while the link is continuous since the report; sampled ones within the adaptive
    cadence bound, idle only when no reading is expected. See `execution/morek_freshness`."""
    from ..execution import morek_freshness as fresh
    from ..sessions import evidence

    link = fresh.link_facts(monitor)
    now = _utc(now)
    out: dict[str, Any] = {}
    status, transaction = live.get("status"), live.get("transaction")
    for name, reading in (("status", status), ("transaction", transaction),
                          ("charging_control", live.get("control_state"))):
        out[name] = fresh.judge_event(_reading_time(reading), now, link)
        if isinstance(reading, dict) and reading.get("value") is None and out[name]["state"] == "current":
            out[name] = {**out[name], "state": "unknown", "basis": "unreadable", "reason": "unreadable"}
    expected = fresh.expectation(
        {"judgement": out["status"], "value": (status or {}).get("normalized")} if status else None,
        {"judgement": out["transaction"], "value": (transaction or {}).get("value")} if transaction else None)
    store = evidence.evidence_for(hass) if entry_id else None
    for name, kind in (("power_w", evidence.KIND_POWER), ("current_a", evidence.KIND_CURRENT),
                       ("energy_register_kwh", evidence.KIND_REGISTER)):
        rows: list[dict[str, Any]] = []
        try:
            if store is not None:
                rows = store.samples(entry_id, kind, since=now - timedelta(hours=2), until=now)
        except Exception:  # noqa: BLE001 - no cadence evidence means the 180 s floor, never a guess
            rows = []
        out[name] = fresh.judge_sampled(_reading_time(live.get(name)), now, link,
                                        bound_s=fresh.sampled_bound_s(rows), expected=expected)
    return {"expected": expected, "link": out["status"]["link"], "quantities": out}


def _session_readiness(hass: HomeAssistant, controller: Any, identity: dict[str, Any], online: bool,
                       now: datetime, monitor: Any = None, entry_id: str | None = None) -> dict[str, Any]:
    """Read connector observations only; no inference of authorization or physical flow.

    HA state timestamps are conservative evidence of freshness, not a heartbeat. With the link `monitor` (15.6) an
    unchanged event state stays current while the link has been continuous since its report and sampled values use
    an adaptive bound (`freshness`); without one the strict 180 s bound applies. Readings keep their strict `fresh`
    flag for control flow.
    """
    result: dict[str, Any] = {
        "control": "unknown", "vehicle": "unknown", "transaction": "unknown",
        "measurement": "unknown", "vehicle_observed_at": None, "live": None,
        # Stage 15.6, additive: the per-quantity connection-aware judgement (None until live evidence is read).
        "freshness": None,
        # Stage 15.5, additive and read-only: whether the charge-control switch confirms enabled charging
        # (`enabled` / `not_ready` / `unknown`). The switch is a derived OCPP entity, not authorization evidence;
        # `not_ready` sends, clears and starts nothing. `boot_start` is the guarded post-reboot start's evidence.
        "charging_enabled": {"state": "unknown", "reason": "no_evidence"},
        "boot_start": {"state": "unknown", "reason": "boot_counter_unavailable"},
        # This is not an admission decision: no session-start dispatcher exists.
        # Keep it separate from schedule upload readiness and never infer a session
        # from the control switch or a connector status.
        "session_start": {"state": "blocked", "reason": "authorization_path_unimplemented"},
        "session_start_at": None,
        "activation_blockers": ["production_dispatch_unarmed", "activation_path_incomplete",
                                "first_use_or_lost_state_unverified", "retained_profile_unresolved",
                                "transaction_authorization_unverified", "held_exit_has_no_release",
                                "external_writers_unverified", "installation_protection_conflict_unresolved"],
    }
    if not identity.get("supported") or identity.get("match_count") != 1:
        if identity.get("supported") and identity.get("match_count") == 0:
            result["control"] = "unavailable"
            result["session_start"] = {"state": "offline", "reason": "charger_offline"}
        return result
    if not online:
        result["control"] = "unavailable"
        result["session_start"] = {"state": "offline", "reason": "charger_offline"}
        return result
    try:
        control = hass.states.get(controller.charge_control)
        if control is None or str(control.state).lower() in ("unknown", "unavailable"):
            result["control"] = "unavailable"
            result["charging_enabled"] = {"state": "not_ready", "reason": "control_unavailable"}
            return result
        result["control"] = "available"
        result["live"] = _live_measurements(hass, controller, now)
        live = result["live"]
        judged = _quantity_freshness(hass, live, monitor, entry_id, now)
        result["freshness"] = judged
        quantities = judged["quantities"]
        result["charging_enabled"] = _charging_enabled(live.get("control_state"), quantities["charging_control"])
        if any(quantities[k]["state"] == "current" and live.get(k) is not None for k in ("current_a", "power_w")):
            result["measurement"] = "measured"  # flow was measured; never implies a transaction or authorization
        status = live.get("status")
        if status is None or quantities["status"]["state"] != "current":
            return result
        result["vehicle_observed_at"] = status["observed_at"]
        state = status.get("normalized")
        if state == "disconnected":
            result["vehicle"] = "disconnected"
        elif state in ("connected", "charging", "paused", "finished"):
            result["vehicle"] = "connected"
    except Exception:  # noqa: BLE001 - unavailable evidence is not an API failure
        # Missing or malformed HA evidence is not permission to assume readiness.
        pass
    return result


async def _state(hass: HomeAssistant, entry_id: str) -> tuple[dict[str, Any], Store]:
    cache = hass.data.setdefault(_DATA_KEY, {})
    data, store, lock = cache.setdefault(
        entry_id, (None, Store(hass, 1, f"{DOMAIN}.morek_schedule.{entry_id}"), asyncio.Lock())
    )
    if data is None:
        async with lock:
            data, store, _ = cache[entry_id]
            if data is None:
                saved = await store.async_load()
                data = saved if isinstance(saved, dict) else {}
                cache[entry_id] = (data, store, lock)
    return data, store


def _proposed_profile(hass: HomeAssistant, entry_id: str, now: datetime, *,
                      active_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Current fixed-time intent for preview, manual Send and future backend callers.

    Refusal means no proposed action, never permission to clear or release a limit.
    """
    settings, proposal = _validated_proposal(hass, entry_id, now)
    # The stored profile is a fixed-time snapshot of exactly what the card shows,
    # including the estimated shorter final block. It does not implement feedback-based energy stopping.
    periods = tuple(proposal.shown_periods)
    if active_profile is not None:
        periods, preserved = continue_active_window(periods, settings.amps, now, active_profile)
        if preserved is not None and len(periods) > MOREK_MAX_BLOCKS:
            # The old window is not dropped to fit the new plan; leave the accepted schedule alone.
            raise ScheduleRefused("active_window_block_limit")
    return profile_for(periods, settings.amps, now, allow_active=True)


def _proposed_baseline(hass: HomeAssistant, entry_id: str, now: datetime, *,
                       active_profile: dict[str, Any] | None = None,
                       active_baseline: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The reserve-free twin of `_proposed_profile` (same windows, no time reserve), or `None`.

    `None` when the plan has no reserve (nothing to separate), when a window is being carried but the accepted
    profile has no twin to carry (an older record), or on any refusal: a missing twin only means the plain
    comparison, never a send or a skipped send of its own.
    """
    try:
        settings, proposal = _validated_proposal(hass, entry_id, now)
        if not getattr(proposal, "reserve_pieces", ()):
            return None
        periods = tuple(proposal.baseline_shown_periods)
        if active_profile is not None:
            periods, preserved = continue_active_window(periods, settings.amps, now, active_baseline)
            if preserved is None and active_window(active_profile, now) is not None:
                return None
        return profile_for(periods, settings.amps, now, allow_active=True)
    except (ScheduleRefused, AttributeError, TypeError, ValueError):
        return None


def _validated_proposal(hass: HomeAssistant, entry_id: str, now: datetime | None = None) -> tuple[Any, Any]:
    """The current settings and the planner's current, priced proposal, or the reason there is none.

    Price admission is the planner's single judgement (`morek_price_blocker`, Stage 16.2) for manual and
    automatic callers alike and for every price state (`ready`, `waiting_for_tomorrow`, `degraded`): unchanged
    price evidence, and every scheduled minute covered by valid listed data (a degraded aggregate passes only
    when degraded by tomorrow alone).
    """
    settings = domain_data(hass).auto_store.settings(entry_id)
    if settings.amps != 16:
        raise ScheduleRefused("current_must_be_16")
    planner = preview_for(hass, entry_id)
    snapshot = planner.snapshot() if planner is not None else None
    proposal = snapshot.proposal if snapshot is not None and snapshot.in_process else None
    if proposal is None:
        if snapshot is not None and getattr(snapshot, "price_state", None) in ("stale", "unavailable", "invalid", "loading"):
            raise ScheduleRefused("prices_stale_or_unavailable")
        raise ScheduleRefused("no_current_plan")
    if (not planner.snapshot_is_current(snapshot) or snapshot.settings_revision != settings.revision
            or getattr(snapshot, "last_error_code", None) is not None):
        raise ScheduleRefused("no_current_plan")
    price_state = getattr(snapshot, "price_state", None)
    if price_state is None:
        raise ScheduleRefused("prices_unavailable")
    if price_state not in ("ready", "waiting_for_tomorrow", "degraded"):
        raise ScheduleRefused("prices_stale_or_unavailable")
    # One judgement for every admitted state: evidence unchanged since the calculation and every scheduled minute
    # covered by valid listed prices. A planner that cannot judge never authorizes a send.
    judge = getattr(planner, "morek_price_blocker", None)
    blocker = None if judge is None else judge(snapshot, now or datetime.now(timezone.utc))
    if judge is None or blocker is not None:
        raise ScheduleRefused(blocker or "prices_stale_or_unavailable")
    if proposal.unpriced:
        raise ScheduleRefused("prices_unavailable")
    if not proposal.has_plan or not proposal.shown_periods:
        raise ScheduleRefused("no_current_plan")
    return settings, proposal


def rejection_count(attempt: dict[str, Any] | None) -> int:
    """How many times the intent of this (rejected) attempt was definitely refused in a row; 0 when not."""
    if not isinstance(attempt, dict) or attempt.get("state") != "rejected":
        return 0
    count = attempt.get("rejections", 1)
    return count if type(count) is int and count >= 1 else 1


def rejection_retry_at(record: dict[str, Any] | None) -> datetime | None:
    """When a definitely rejected automatic intent may be sent again, or `None` when retries are used up
    (or the record is not a definite rejection). Bounded by `REJECTION_RETRY_DELAYS`; only ever a
    re-send of the same intent, never a profile clear."""
    if not isinstance(record, dict) or record.get("uncertain"):
        return None
    attempt = record.get("attempt")
    count = rejection_count(attempt)
    if count < 1 or count > len(REJECTION_RETRY_DELAYS) or attempt.get("source") != "worker":
        return None
    try:
        return _utc(datetime.fromisoformat(attempt["at"])) + timedelta(seconds=REJECTION_RETRY_DELAYS[count - 1])
    except (KeyError, TypeError, ValueError, AttributeError, ScheduleRefused):
        return None


def recovery_status(record: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """Non-sensitive account of the last accepted intent and of bounded rejection recovery.

    The accepted intent is what the charger acknowledged, not proof of physical charging or of the profiles
    installed on it."""
    record = record if isinstance(record, dict) else {}
    ack = record.get("acknowledged") if isinstance(record.get("acknowledged"), dict) else {}
    accepted_at = age_s = None
    try:
        at = _utc(datetime.fromisoformat(ack["at"]))
        accepted_at, age_s = at.isoformat(), max(0, int((now - at).total_seconds()))
    except (KeyError, TypeError, ValueError, AttributeError, ScheduleRefused):
        pass
    attempt = record.get("attempt") if isinstance(record.get("attempt"), dict) else {}
    count = rejection_count(attempt)
    retry_at = rejection_retry_at(record)
    return {"accepted_at": accepted_at, "accepted_age_s": age_s, "accepted_is": "acknowledged_not_measured",
            "rejections": count, "retries_left": max(0, len(REJECTION_RETRY_DELAYS) + 1 - count) if count else None,
            "next_retry_at": None if retry_at is None else retry_at.isoformat(),
            "exhausted": bool(count and retry_at is None and not record.get("uncertain"))}


#: Stage 14.6: reason code -> what the person (or time) can do about it. Codes only, no household data.
DECISION_BLOCKERS: dict[str, str] = {
    "charger_unavailable": "wait_for_charger_connection",
    "morek_offline": "wait_for_charger_connection",
    "identity_unresolved": "check_charger_identity",
    "identity_changed": "check_charger_identity",
    "stale_generation": "retry_after_stop_or_change",
    "migration_confirmation_required": "confirm_ownership",
    "protection_conflict_unresolved": "resolve_protection_conflict",
    "paused_until_resume": "resume_schedule",
    "legacy_pause_active": "resume_schedule",
    "resume_requires_confirmation": "confirm_resume",
    "charge_now_active": "wait_for_charge_now_end",
    "upload_uncertain": "check_charger_outcome",
    "upload_rejected": "check_charger_response",
    "planner_changed": "wait_for_planner",
    "worker_unavailable": "check_logs",
    "planning_unavailable": "wait_for_fresh_inputs",
    "target_soc_stale": "wait_for_fresh_inputs",
    "target_progress_uncertain": "wait_for_fresh_inputs",
    "waiting_for_vehicle_update": "wait_for_fresh_inputs",
    "active_window_block_limit": "adjust_planning_settings",
    "too_many_blocks": "adjust_planning_settings",
    "invalid_plan": "adjust_planning_settings",
}
DECISION_BLOCKERS.update({
    "prices_unavailable": "wait_for_prices", "prices_stale_or_unavailable": "wait_for_prices",
    "price_evidence_unavailable": "wait_for_prices", "price_inputs_changed": "wait_for_prices",
    "price_coverage_unavailable": "wait_for_prices",
    "vehicle_input_unavailable": "wait_for_fresh_inputs", "vehicle_input_stale": "wait_for_fresh_inputs",
    "vehicle_identity_unavailable": "wait_for_fresh_inputs", "plan_inputs_changed": "wait_for_planner",
    "no_current_plan": "wait_for_planner", "plan_input_provenance_unavailable": "adjust_planning_settings",
    "current_must_be_16": "adjust_planning_settings",
    "repair_gated": "wait_for_repair_release",  # 15.4a: a confirmed mismatch is recorded; automatic repair is off
    "repair_needs_person": "needs_person",  # 15.4a: repair budget used up or its record unreadable
    "repair_spacing": "wait_for_repair_spacing",
    "repair_unconfirmed": "wait_for_confirmation",
    "repair_deferred": "wait_for_repair_deferral",  # 15.4b: a correct charge with only a distant future difference
})
#: Stage 9.5: blockers that clear on their own (a reconnect, prices, a fresh reading, a finished Stop). The worker
#: re-evaluates them after a bounded backoff when no event arrives; every one is only a read-and-compare, a send
#: still passes every guard. Never here: an uncertain write (`upload_uncertain`), a rejection (own cooldown), a
#: person pause, an ownership or protection conflict, settings problems.
TRANSIENT_BLOCKERS = frozenset({
    "charger_unavailable", "morek_offline", "identity_unresolved", "identity_changed", "stale_generation",
    "planner_changed", "worker_unavailable", "planning_unavailable", "target_soc_stale", "target_progress_uncertain",
    "waiting_for_vehicle_update", "prices_unavailable", "prices_stale_or_unavailable", "price_evidence_unavailable",
    "price_inputs_changed", "price_coverage_unavailable", "plan_inputs_changed", "no_current_plan",
    "vehicle_input_unavailable", "vehicle_input_stale", "vehicle_identity_unavailable",
})
BLOCKER_RETRY_DELAYS = (60, 180, 600, 900)  # seconds; the last repeats
BLOCKER_RETRY_LIMIT = 12  # timer-driven re-evaluations per blocked episode (about 2.5 h); events still re-evaluate


def blocker_retry_delay(runs: int) -> int | None:
    """Seconds until the next timer-driven re-evaluation after `runs` of them, or None when used up."""
    if runs >= BLOCKER_RETRY_LIMIT:
        return None
    return BLOCKER_RETRY_DELAYS[min(runs, len(BLOCKER_RETRY_DELAYS) - 1)]


def blocker_retry_status(worker: Any) -> dict[str, Any] | None:
    """The worker's current transient blocker and its bounded re-evaluation, or None when not blocked that way."""
    state = getattr(worker, "blocker_retry", None)
    return dict(state) if isinstance(state, dict) else None


_DECISION_OK = ("upload_accepted_unverified", "unchanged")
_DECISION_SENT = ("upload_accepted_unverified", "upload_rejected", "upload_uncertain")
_DECISION_ACK = {"upload_accepted_unverified": "accepted", "upload_rejected": "rejected",
                 "upload_uncertain": "unknown", "unchanged": "accepted_earlier"}


def decision_blocker(reason: str | None) -> dict[str, str] | None:
    """The current obstacle to applying a new plan, or None. `stale_work` is a superseded run, not a blocker."""
    if not reason or reason in _DECISION_OK or reason in ("pending", "stale_work", "not_started"):
        return None
    return {"code": str(reason)[:60], "action": DECISION_BLOCKERS.get(reason, "see_reason")}


def decision_event(*, now: datetime, kinds: Any, last_trigger: str | None, reason: str | None,
                   inputs: dict[str, Any], evidence: str, continuity: dict[str, Any] | None,
                   dispatched: bool | None = None, attempt_id: str | None = None) -> dict[str, Any]:
    """One bounded, non-sensitive account of a finished reconcile run (Stage 14.6).

    Separates the stages: `intent` (a profile was handed to the charger), `ack` (what it answered),
    `readback` (filled live by `decision_status`) and `physical` (never measured here). No profile,
    price, entity id, payload or identity is included. `dispatched` says this run really made the wire call
    (None: infer from the result, for callers without that evidence). A sent-type result without a dispatch
    is an earlier attempt still blocking (cooldown, exhausted retries, unresolved outcome): no new command."""
    reason = reason or "unknown"
    sent = reason in _DECISION_SENT
    held = sent and dispatched is False
    sent = sent and not held
    action = "sent" if sent else "held" if held else "skipped" if reason == "unchanged" else "blocked"
    cont = continuity if isinstance(continuity, dict) else None
    ack = _DECISION_ACK.get(reason)
    if held:
        ack = {"upload_rejected": "rejected_earlier", "upload_uncertain": "unknown_earlier"}.get(reason, ack)
    return {
        "at": _utc(now).isoformat(), "trigger": last_trigger, "triggers": sorted(str(k) for k in kinds)[:9],
        "inputs": {key: inputs.get(key) for key in ("plan_state", "plan_reason", "soc_source", "soc_estimated",
                                                    "soc_age_s", "uncertain", "progress_unknown")},
        "evidence": evidence,
        "changed": True if sent else False if reason == "unchanged" else None,
        "continuity": None if cont is None else {key: cont.get(key) for key in ("evidence", "preserved", "reason")},
        "action": action, "result": reason[:60], "attempt_id": attempt_id,
        "stages": {"intent": "sent" if sent else "none", "ack": ack,
                   "readback": None, "physical": "not_measured"},
        "blocker": decision_blocker(reason), "repeat": 1,
    }


def repair_status(worker: Any, record: Any = None) -> dict[str, Any]:
    """Stage 15.4a (additive, codes and times only): the repair gate, the last confirmation and the budget."""
    confirmed = getattr(worker, "repair_confirmed", None)
    budget = repair_budget(record if isinstance(record, dict) else None, datetime.now(timezone.utc))
    return {"gate_enabled": bool(REPAIR_DISPATCH_ENABLED),
            "confirmed": dict(confirmed) if isinstance(confirmed, dict) else None,
            "budget": {"state": budget["state"], "used": len(budget["recent"]), "limit": REPAIR_BUDGET_MAX,
                       "next_at": budget["next_at"]},
            "needs_person": budget["state"] in ("exhausted", "invalid") or (
                isinstance(record, dict) and repair_escalated(record, (record.get("acknowledged") or {}).get("id")))}


def decision_status(worker: Any, verification: dict[str, Any], verified: bool,
                    current_attempt_id: str | None = None) -> dict[str, Any] | None:
    """The latest decision plus the few before it, with the current readback state filled in.

    The readback belongs to the decision's own attempt: when the decision names one and the current
    verification is for another, it is `superseded`, never borrowed."""
    last = getattr(worker, "decision", None)
    if not isinstance(last, dict):
        return None
    last = {**last, "stages": dict(last["stages"])}
    if last["action"] in ("sent", "skipped") and last["stages"]["ack"] in ("accepted", "accepted_earlier"):
        mine = last.get("attempt_id")
        if mine is not None and current_attempt_id is not None and mine != current_attempt_id:
            last["stages"]["readback"] = "superseded"
        else:
            last["stages"]["readback"] = ("verified" if verified else "pending" if verification.get("pending")
                                          else "mismatch" if verification.get("reason") == "limits_or_transitions_differ"
                                          else "unconfirmed")
    return {"latest": last, "recent": list(getattr(worker, "decisions", ()))[-5:]}


def _preview_id(profile: dict[str, Any], revision: Any) -> str:
    """Commit to wire attributes and absolute changes, excluding the moving initial timestamp."""
    schedule = profile["chargingSchedule"]
    start = datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00"))
    periods = schedule["chargingSchedulePeriod"]
    transitions = [{**period, "startPeriod": (start + timedelta(seconds=period["startPeriod"])).isoformat()}
                   for period in periods[1:]]
    intent = {key: value for key, value in profile.items() if key != "chargingSchedule"}
    intent["chargingSchedule"] = {key: value for key, value in schedule.items()
                                   if key not in ("startSchedule", "chargingSchedulePeriod")}
    intent["initial"] = {key: value for key, value in periods[0].items() if key != "startPeriod"}
    intent["transitions"] = transitions
    return hashlib.sha256(json.dumps([revision, intent], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _outcome_record(hass: HomeAssistant, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Load or conservatively migrate the old entry-local manual record."""
    record = await outcomes_for(hass).read()
    if record is None:
        cleanup = data.get("cleanup") or {}
        legacy_uncertain = bool((data.get("profile") and str(data.get("ack", "unknown")).lower() not in
                                 ("accepted", "rejected", "notsupported"))
                                or (cleanup and str(cleanup.get("status", "unknown")).lower() not in
                                    ("accepted", "rejected", "notsupported")))
        record = {"schema": 1, "entry_id": entry_id, "desired": None, "attempt": None,
                  "acknowledged": None, "verified": None, "uncertain": legacy_uncertain,
                  "removal": None}
    if record.get("entry_id") != entry_id or type(record.get("uncertain")) is not bool:
        raise ScheduleRefused("outcome_binding_unavailable")
    intent = record.get("schedule_pause")
    if intent is not None and (not isinstance(intent, dict)
                               or set(intent) != {"version", "type", "id", "station_id", "connector_id"}
                               or type(intent.get("version")) is not int or intent["version"] != 1
                               or intent.get("type") not in ("pause_until_resumed", "resume_requested")
                               or not isinstance(intent.get("id"), str) or not intent["id"]
                               or intent.get("station_id") != MOREK_STATION_ID
                               or type(intent.get("connector_id")) is not int
                               or intent["connector_id"] != MOREK_CONNECTOR_ID):
        raise ScheduleRefused("schedule_pause_invalid")
    override = record.get("charge_now")
    if override is not None:
        try:
            if (not isinstance(override, dict) or set(override) != {"version", "id", "station_id", "connector_id", "start", "end"}
                    or type(override["version"]) is not int or override["version"] != 1
                    or not isinstance(override["id"], str) or len(override["id"]) != 32
                    or any(c not in "0123456789abcdef" for c in override["id"])
                    or override["station_id"] != MOREK_STATION_ID
                    or type(override["connector_id"]) is not int or override["connector_id"] != MOREK_CONNECTOR_ID):
                raise ValueError
            start = _utc(datetime.fromisoformat(override["start"]))
            end = _utc(datetime.fromisoformat(override["end"]))
            if end <= start or end - start > MAX_HORIZON:
                raise ValueError
        except (TypeError, ValueError, KeyError, ScheduleRefused):
            raise ScheduleRefused("charge_now_intent_invalid") from None
    return record


@_logged_action("pause/resume")
async def async_record_owned_pause(hass: HomeAssistant, entry_id: str, *, resume: bool = False) -> dict[str, Any]:
    """Persist an explicit connector-bound pause; no charger operation is performed.

    A resume remains durable as a request, not proof that a retained limit changed.
    Production owned-profile admission remains unarmed.
    """
    from ..execution.command_admission import physical_connector

    entry, failure = lookup_charger(hass, entry_id)
    if failure or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    admission = command_admission(hass)

    def identity() -> dict[str, Any]:
        controller = controller_for(hass, entry_id)
        return _intent_identity_status(hass, getattr(controller, "ocpp_target", None))

    from contextlib import nullcontext
    with nullcontext() if resume else admission.person_stop_reservation(entry_id, identity):
        original = identity()
        connector = physical_connector(original)
        if not _owned_intent_identity_ok(original) or connector is None:
            raise ScheduleRefused("identity_unresolved")
        generation = admission.generation(connector)
        async with admission._lock_for(connector):
            current = identity()
            status = await ownership_store(hass).async_status(entry_id, current)
            if (not _owned_intent_identity_ok(current)
                    or physical_connector(current) != connector
                    or status.get("record_state") != "valid"
                    or status.get("recorded_owner") != "morek_schedule"
                    or status.get("transition_state") is not None
                    or status.get("armed") is not False
                    or (status.get("station_id"), status.get("connector_id")) !=
                       (connector.station_id, connector.connector_id)):
                raise ScheduleRefused("schedule_owner_unavailable")
            data, _ = await _state(hass, entry_id)
            record = await _outcome_record(hass, entry_id, data)
            if physical_connector(identity()) != connector:
                raise ScheduleRefused("identity_changed")
            intent = record.get("schedule_pause")
            if resume and (intent is None or record["uncertain"] or admission._person_stops.get(connector)):
                raise ScheduleRefused("resume_unavailable")
            desired = "resume_requested" if resume else "pause_until_resumed"
            committed = False
            interrupted_before = resume and intent is not None and (
                record.get("resume_interrupted") == intent["id"])
            if (intent is None or intent["type"] != desired or interrupted_before
                    or (not resume and record.get("charge_now") is not None)):
                intent = {"version": 1, "type": desired, "id": uuid4().hex,
                          "station_id": connector.station_id, "connector_id": connector.connector_id}
                record["schedule_pause"] = intent
                record.pop("resume_interrupted", None)  # a fresh intent id: a person's new Resume may continue
                if not resume:
                    record.pop("charge_now", None)
                await outcomes_for(hass).write(record)
                committed = True
            if resume and (generation != admission.generation(connector) or admission._person_stops.get(connector)):
                interrupted = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
                if interrupted is not None:
                    interrupted.resume_interrupted = intent["id"]  # a Stop took precedence: never auto-recover it
                # Durable too, before anything else can run: a restart before the Stop's own record must not
                # recover this superseded Resume. Written under the connector lock; a failed write propagates.
                record["resume_interrupted"] = intent["id"]
                await outcomes_for(hass).write(record)
                if committed:
                    from ..execution.auto_execution import AutoControlCommitted, EXECUTION_RECONCILE_FAILED
                    raise AutoControlCommitted(EXECUTION_RECONCILE_FAILED)
                raise ScheduleRefused("resume_interrupted")
            if not resume and physical_connector(identity()) == connector:
                admission.renew_ticket_for_durable_pause(entry_id, connector, generation)
    worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
    if worker is not None:
        if resume:
            worker.resume_ticket = (intent["id"], generation)
            if getattr(worker, "session", None) is not None:
                worker.session.resume(intent["id"])
        else:
            worker.hold_ticket = (intent["id"], generation)
        worker.trigger()
    return dict(intent)


@_logged_action("Charge Now")
async def async_charge_now_action(hass: HomeAssistant, entry_id: str, *, return_to_auto: bool = False,
                                  duration_minutes: int | None = None, end_time: str | None = None) -> dict[str, Any]:
    """Persist an explicit request under the owner's connector lock, then trigger reconciliation."""
    from ..execution.command_admission import physical_connector

    now = datetime.now(timezone.utc)
    if return_to_auto:
        if duration_minutes is not None or end_time is not None:
            raise ScheduleRefused("charge_now_invalid_time")
        end = None
    elif end_time is not None:
        if duration_minutes is not None:
            raise ScheduleRefused("charge_now_invalid_time")
        try:
            end = _utc(datetime.fromisoformat(end_time.replace("Z", "+00:00")))
        except (ValueError, AttributeError, TypeError, ScheduleRefused):
            raise ScheduleRefused("charge_now_invalid_time") from None
    else:
        duration = 60 if duration_minutes is None else duration_minutes
        if type(duration) is not int or duration not in (30, 60, 120, 180):
            raise ScheduleRefused("charge_now_invalid_duration")
        end = now + timedelta(minutes=duration)
    if end is not None and (end <= now or end - now > MAX_HORIZON):
        raise ScheduleRefused("charge_now_invalid_time")
    entry, failure = lookup_charger(hass, entry_id)
    if failure or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    admission = command_admission(hass)
    def identity():
        return _intent_identity_status(hass, getattr(controller_for(hass, entry_id), "ocpp_target", None))
    original = identity()
    connector = physical_connector(original)
    if not _owned_intent_identity_ok(original) or connector is None:
        raise ScheduleRefused("identity_unresolved")
    generation = admission.generation(connector)
    async with admission._lock_for(connector):
        current = identity()
        owner = await ownership_store(hass).async_status(entry_id, current)
        if (not _owned_intent_identity_ok(current) or physical_connector(current) != connector
                or owner.get("record_state") != "valid" or owner.get("recorded_owner") != "morek_schedule"
                or owner.get("transition_state") is not None or owner.get("armed") is not False
                or (owner.get("station_id"), owner.get("connector_id")) != (connector.station_id, connector.connector_id)):
            raise ScheduleRefused("schedule_owner_unavailable")
        data, _ = await _state(hass, entry_id)
        record = await _outcome_record(hass, entry_id, data)
        if physical_connector(identity()) != connector:
            raise ScheduleRefused("identity_changed")
        if not return_to_auto:
            pause = record.get("schedule_pause") or {}
            settings = domain_data(hass).auto_store.settings(entry_id)
            if (pause.get("type") == "pause_until_resumed" or getattr(getattr(settings, "pause", None), "admitted", False)
                    or admission._person_stops.get(connector) or generation != admission.generation(connector)):
                raise ScheduleRefused("resume_auto_first")
            if end <= datetime.now(timezone.utc):
                raise ScheduleRefused("charge_now_invalid_time")
            record["charge_now"] = {"version": 1, "id": uuid4().hex, "station_id": connector.station_id,
                                    "connector_id": connector.connector_id, "start": now.isoformat(), "end": end.isoformat()}
        else:
            record.pop("charge_now", None)
        await outcomes_for(hass).write(record)
    worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
    if worker is not None:
        worker.trigger()
    return {"intent": record.get("charge_now"), "reconciliation": "pending" if worker else "worker_unavailable",
            "outcome": "uncertain" if record["uncertain"] else "not_yet_confirmed"}


async def async_maybe_owned_action(hass: HomeAssistant, entry_id: str, action: str) -> bool:
    """Route an explicit Stop/Resume only when a unique Morek owner is established."""
    from contextlib import nullcontext

    controller = controller_for(hass, entry_id)
    if getattr(controller, "ocpp_target", None) is None:
        return False
    def identity():
        return _intent_identity_status(hass, getattr(controller, "ocpp_target", None))
    admission = command_admission(hass)
    scope = admission.person_stop_reservation(entry_id, identity) if action == "stop" else nullcontext()
    with scope:
        current = identity()
        if not _owned_intent_identity_ok(current):
            return False
        status = await ownership_store(hass).async_status(entry_id, current)
        if status.get("recorded_owner") != "morek_schedule":
            return False
        await async_record_owned_pause(hass, entry_id, resume=action == "resume")
        return True


def _verification_current(hass: HomeAssistant, entry_id: str, entry: Any, data: dict[str, Any],
                          record: dict[str, Any] | None, sent_at: str) -> bool:
    """Fail closed if the accepted attempt, planner, connection or lifecycle changed."""
    try:
        current_entry, failure = lookup_charger(hass, entry_id)
        if failure or current_entry is not entry or not isinstance(record, dict):
            return False
        lifecycle = hass.data.get(_LIFECYCLE_KEY, {}).get(entry_id)
        if lifecycle is None or lifecycle["entry"] is not entry or not lifecycle["live"]:
            return False
        worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
        if worker is not None and (worker._closed or worker._suspended or not worker._available()):
            return False
        target = getattr(controller_for(hass, entry_id), "ocpp_target", None)
        from ..execution.command_admission import classify_morek_identity, physical_connector
        identity = _identity_status(hass, target)
        if classify_morek_identity(identity) != "supported_morek":
            return False
        _charge_point(hass, target)
        attempt, ack = record.get("attempt") or {}, record.get("acknowledged") or {}
        admission = hass.data.get("spotnav_command_admission")
        connector = physical_connector(identity)
        if (admission is not None and connector is not None
                and (admission._person_stops.get(connector)
                     or (attempt.get("source") == "worker"
                         and not admission.owned_ticket_current(entry_id, connector)))):
            return False
        fingerprint = attempt.get("fingerprint")
        if (record.get("entry_id") != entry_id or record.get("uncertain") is not False
                or data.get("cleanup") or data.get("sent_at") != sent_at
                or data.get("ack", "").lower() != "accepted"
                or attempt.get("state") != "accepted" or attempt.get("at") != sent_at
                or not fingerprint or ack.get("fingerprint") != fingerprint or ack.get("at") != sent_at
                or not attempt.get("id") or attempt.get("id") != ack.get("id")
                or attempt.get("id") != data.get("attempt_id")):
            return False
        settings = domain_data(hass).auto_store.settings(entry_id)
        if attempt.get("revision") != settings.revision:
            return False
        sent = attempt.get("profile")
        pause_id = attempt.get("pause_id")
        pause = record.get("schedule_pause")
        override_id = attempt.get("override_id")
        override = record.get("charge_now")
        if pause_id is not None and (not isinstance(pause, dict) or pause.get("id") != pause_id):
            return False
        if pause_id is None and attempt.get("source") == "worker" and pause is not None:
            return False
        now = datetime.now(timezone.utc)
        if override_id is not None:
            if (attempt.get("source") != "worker" or worker is None or admission is None or connector is None
                    or not isinstance(override, dict)
                    or set(override) != {"version", "id", "station_id", "connector_id", "start", "end"}
                    or not isinstance(override_id, str) or len(override_id) != 32
                    or any(c not in "0123456789abcdef" for c in override_id) or override.get("id") != override_id
                    or type(override.get("version")) is not int or override.get("version") != 1
                    or override.get("station_id") != connector.station_id
                    or type(override.get("connector_id")) is not int
                    or override.get("connector_id") != connector.connector_id
                    or _utc(datetime.fromisoformat(override["start"])) > now
                    or _utc(datetime.fromisoformat(override["end"])) <= now
                    or (pause is not None and not _resume_authorized(record, worker, admission.generation(connector)))):
                return False
            fingerprint_revision = [settings.revision, override_id]
            current, current_fingerprint = worker._intent(pause, override)
            if current_fingerprint != fingerprint:
                return False
        else:
            if (attempt.get("source") == "worker" and override is not None
                    and _utc(datetime.fromisoformat(override["end"])) > now
                    and (pause is None or pause.get("type") != "pause_until_resumed")):
                return False
            fingerprint_revision = [settings.revision, pause_id] if pause_id is not None else settings.revision
            if pause_id is not None and pause.get("type") == "pause_until_resumed":
                current = held_off_profile(now)
            elif attempt.get("source") == "worker":
                # The worker may have continued an allowed window (Stage 14.2).
                current = _proposed_profile(hass, entry_id, now, active_profile=sent)
            else:
                current = _proposed_profile(hass, entry_id, now)
        if _preview_id(sent, fingerprint_revision) != fingerprint or sent != data.get("profile"):
            return False
        if ({k: v for k, v in sent.items() if k != "chargingSchedule"}
                != {k: v for k, v in current.items() if k != "chargingSchedule"}):
            return False
        if ({k: v for k, v in sent["chargingSchedule"].items() if k not in ("startSchedule", "chargingSchedulePeriod")}
                != {k: v for k, v in current["chargingSchedule"].items()
                    if k not in ("startSchedule", "chargingSchedulePeriod")}):
            return False
        def remaining(profile):
            schedule = profile["chargingSchedule"]
            start = _utc(datetime.fromisoformat(schedule["startSchedule"].replace("Z", "+00:00")))
            periods = [(start + timedelta(seconds=p["startPeriod"]),
                        {k: v for k, v in p.items() if k != "startPeriod"})
                       for p in schedule["chargingSchedulePeriod"]]
            return periods
        old, new = remaining(sent), remaining(current)
        boundary = max(now, old[0][0], new[0][0])
        def projection(periods):
            return (next(limit for at, limit in reversed(periods) if at <= boundary),
                    [(at, limit) for at, limit in periods if at > boundary])
        return projection(old) == projection(new)
    except Exception:  # noqa: BLE001 - verification must not outlive its evidence
        return False


async def _send_profile_shared(hass: HomeAssistant, entry_id: str, data: dict[str, Any], store: Any,
                               fingerprint: str, validate: Any, *, automatic: bool, pause_id: str | None = None,
                               validate_durable: Any = None, migration_id: str | None = None,
                               override_id: str | None = None, force_sync: bool = False,
                               end_tolerance: timedelta | None = None, baseline: Any = None,
                               repair: str | None = None) -> str:
    """Connector lock held. Record first, revalidate after every pre-dispatch await.

    `baseline` (optional) returns the reserve-free twin of the profile `validate` just built (Stage 15.1a).
    `repair` (Stage 15.4a) is the confirmed acknowledged attempt id being repaired: it bypasses ONLY the two
    `unchanged` returns, and only for that exact still-current acknowledged attempt of the same intent kind and
    inside the repair budget; the uncertain-record return and the rejection cooldown still apply."""
    ledger = outcomes_for(hass)
    record = await _outcome_record(hass, entry_id, data)
    profile, point, target = validate()
    # This exact wire payload is the one recorded and later dispatched. A
    # revalidation may rebuild an equivalent profile with a later startSchedule.
    wire_profile = profile
    wire_baseline = baseline() if callable(baseline) else None
    if record["uncertain"]:
        return "upload_uncertain"
    acknowledged = record.get("acknowledged") or {}
    attempt = record.get("attempt") or {}
    if automatic and not force_sync and not repair and acknowledged.get("fingerprint") == fingerprint:
        return "unchanged"
    if (automatic and not force_sync and not repair and pause_id is None and override_id is None
            and acknowledged_revision(record) == domain_data(hass).auto_store.settings(entry_id).revision
            and same_effective_schedule(acknowledged_profile(record), profile, end_tolerance,
                                        accepted_baseline=acknowledged_baseline(record),
                                        candidate_baseline=wire_baseline)):
        # The accepted routine schedule already says this from now on (a settings edit, an explicit
        # control, a pause or a needed sync is never suppressed here); a profile creation time is not a change.
        return "unchanged"
    rejections = 0
    if automatic and attempt.get("state") == "rejected" and attempt.get("fingerprint") == fingerprint:
        # A definite refusal of this very intent: tried again only a bounded number of times, each after a
        # longer pause (Stage 14.5). Never after an uncertain write (handled above), and a forced
        # sync is the person's own request.
        rejections = rejection_count(attempt)
        retry_at = rejection_retry_at(record)
        if not force_sync and (retry_at is None or datetime.now(timezone.utc) < retry_at):
            return "upload_rejected"
    if repair:
        # Stage 15.4a: the confirmed attempt must still be the latest accepted one, of the same intent kind
        # (a hold repairs as a hold, Charge Now as its own override, a plan as a plan); then the budget.
        if (attempt.get("id") != repair or attempt.get("state") != "accepted" or acknowledged.get("id") != repair
                or attempt.get("pause_id") != pause_id or attempt.get("override_id") != override_id
                or bool(acknowledged.get("routine")) != (pause_id is None and override_id is None)):
            return "repair_unconfirmed"
        if repair in repaired_ids(record) or repair_escalated(record, repair):
            # Stage 15.4b: the attempt in force IS an earlier repair and a fresh confirmation says it still differs:
            # a second automatic repair would be a blind loop. Persist the escalation (restart-proof, keyed to this
            # attempt so a later normal plan starts clean) and send nothing; no clear, no retry.
            if not repair_escalated(record, repair):
                record[_REPAIR_ESCALATION_KEY] = {"at": datetime.now(timezone.utc).isoformat(), "attempt_id": repair}
                await ledger.write(record)
            return "repair_needs_person"
        budget = repair_budget(record, datetime.now(timezone.utc))
        if budget["state"] in ("exhausted", "invalid"):
            return "repair_needs_person"
        if budget["state"] == "spacing":
            return "repair_spacing"
    now = datetime.now(timezone.utc).isoformat()
    attempt_id = uuid4().hex
    settings_now = domain_data(hass).auto_store.settings(entry_id)
    revision = settings_now.revision
    cap_evidence = cap_snapshot(settings_now)
    record.update({"desired": {"fingerprint": fingerprint, "profile": profile},
                   "attempt": {"fingerprint": fingerprint, "profile": profile, "at": now, "id": attempt_id,
                               "revision": revision,
                               "source": "worker" if automatic else "manual", "state": "uncertain",
                               **({"rejections": rejections} if rejections else {}),
                               **({} if wire_baseline is None else {"baseline": wire_baseline})},
                   "uncertain": True, "verified": None})
    if pause_id is not None:
        record["attempt"]["pause_id"] = pause_id
    if override_id is not None:
        record["attempt"]["override_id"] = override_id
    await ledger.write(record)
    # Stage 15.3: a new attempt ends any read-only check episode (its finding no longer describes what is in force).
    checker = hass.data.get("spotnav_morek_checker", {}).get(entry_id)
    if checker is not None:
        checker.note_new_attempt(repair=repair)
    # Evidence of the intent (the exact wire profile), kept after the durable attempt record and before dispatch.
    _evidence_plan(hass, entry_id, record["attempt"], wire_profile)
    # Recheck after persistence: a settings edit, new calculation, identity or
    # pause change while the disk was busy must never become an obsolete send.
    try:
        profile, point, target = validate()
    except Exception:
        record["attempt"]["state"] = "aborted_before_dispatch"
        record["uncertain"] = False
        await ledger.write(record)
        _evidence_call(hass, entry_id, "record_event", "dispatch_aborted", plan_id=attempt_id,
                       reason="validation_after_persistence")
        raise
    _cancel_verification(hass, entry_id)
    prior_data = dict(data)
    data.update({"sent_at": now, "attempt_id": attempt_id, "profile": wire_profile, "ack": "unknown", "verified": False,
                 "effective": None, "cleanup": None,
                 "verification": {"pending": False, "reason": "upload_unconfirmed",
                                  "next_check_at": None, "attempts": 0}})
    await store.async_save(data)
    durable_ok = True
    if validate_durable is not None:
        # Do not repair or overwrite changed/unknown evidence. The already
        # persisted uncertain attempt blocks retries if the last check fails.
        try:
            durable_ok = await validate_durable()
            if await ledger.read() != record:
                _evidence_call(hass, entry_id, "record_event", "dispatch_aborted", plan_id=attempt_id,
                               reason="ledger_changed")
                return "upload_uncertain"
        except Exception:  # noqa: BLE001 - leave the attempted outcome uncertain
            _evidence_call(hass, entry_id, "record_event", "dispatch_aborted", plan_id=attempt_id,
                           reason="durable_check_failed")
            return "upload_uncertain"
    try:
        profile, point, target = validate()
        if not durable_ok:
            _evidence_call(hass, entry_id, "record_event", "dispatch_aborted", plan_id=attempt_id,
                           reason="durable_check_refused")
            return "upload_uncertain"
        if repair:
            # Stage 15.4a: the budget entry is durable BEFORE the wire call (a crash cannot lose a repair), then the
            # final validation runs again after that await. A refusal below removes it: only a run that reaches
            # the wire call consumes budget.
            kept = repair_budget(record, datetime.now(timezone.utc))["recent"]
            record[_REPAIR_LIST_KEY] = [*kept, {"at": now, "attempt_id": attempt_id}]
            await ledger.write(record)
            profile, point, target = validate()
    except Exception:
        if repair:
            record[_REPAIR_LIST_KEY] = [e for e in record.get(_REPAIR_LIST_KEY, []) if e.get("attempt_id") != attempt_id]
        record["attempt"]["state"] = "aborted_before_dispatch"
        record["uncertain"] = False
        await ledger.write(record)
        _evidence_call(hass, entry_id, "record_event", "dispatch_aborted", plan_id=attempt_id,
                       reason="validation_before_dispatch")
        data.clear()
        data.update(prior_data)
        await store.async_save(data)
        raise
    from ocpp.v16 import call as ocpp_call
    sending = hass.data.setdefault("spotnav_morek_sending", {})
    sending[entry_id] = attempt_id
    # Diagnostic only (Stage 14.6): this attempt reached the wire call; a cooldown or early return never does.
    hass.data.setdefault("spotnav_morek_dispatched", {})[entry_id] = attempt_id
    # Synchronous, in-memory and failure-swallowing. It is written BEFORE the call, so it is not proof of sending
    # (a crash or cancellation right after it, or an unsaved write, leaves nothing on the wire); only an ACK is.
    _evidence_call(hass, entry_id, "record_event", "dispatch_started", plan_id=attempt_id)
    try:
        async with asyncio.timeout(30):
            response = await point.call(ocpp_call.SetChargingProfile(
                connector_id=target.connector_id, cs_charging_profiles=wire_profile))
        ack = _status(response)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - dispatch may have applied
        ack = "unknown"
    finally:
        if sending.get(entry_id) == attempt_id:
            sending.pop(entry_id, None)
    data["ack"] = ack
    state = ack.lower()
    if state == "accepted":
        record.update({"acknowledged": {
            "fingerprint": fingerprint, "at": now, "id": attempt_id, "profile": wire_profile,
            "revision": revision, "routine": pause_id is None and override_id is None,
            **({} if wire_baseline is None else {"baseline": wire_baseline}),
            **({} if cap_evidence is None else {"cap": cap_evidence})}, "uncertain": False})
        record["attempt"]["state"] = "accepted"
    elif state in ("rejected", "notsupported"):
        record["attempt"]["state"] = "rejected"
        record["attempt"]["rejections"] = rejections + 1
        record["uncertain"] = False
        if repair:
            # Stage 15.4b: a charger that refuses the repair gets no blind second write (the 5/15 min rejection
            # retries find the acknowledged intent unchanged): a person looks. Keyed to the repaired attempt.
            record[_REPAIR_ESCALATION_KEY] = {"at": now, "attempt_id": repair}
    if automatic and migration_id and state in ("accepted", "rejected", "notsupported"):
        # Written only after a real ticket-checked wire call returned a response.
        # This proves the handover was live before dispatch, not charger behavior.
        record["migration_dispatch_evidence"] = {
            "version": 1, "migration_id": migration_id, "station_id": MOREK_STATION_ID,
            "connector_id": MOREK_CONNECTOR_ID, "attempt_id": attempt_id, "ack": state,
        }
    # Unknown, cancellation, or interrupted ACK persistence stays uncertain on disk.
    record["attempt"]["ack"] = ack
    await ledger.write(record)
    # The charger's answer to the command, nothing more: not installed-profile inventory and not charging.
    _evidence_call(hass, entry_id, "record_event", "ack", plan_id=attempt_id, status=state[:32] or "unknown")
    await store.async_save(data)
    return "upload_accepted_unverified" if state == "accepted" else (
        "upload_rejected" if state in ("rejected", "notsupported") else "upload_uncertain")


def _planning_inputs(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """The state of charge the current plan was made from, labelled; never an entity id or raw payload."""
    try:
        snapshot = preview_for(hass, entry_id).snapshot()
        age = snapshot.projection_age_s
        return {"plan_state": snapshot.state, "plan_reason": snapshot.reason,
                "soc_source": snapshot.projection_source, "soc_estimated": bool(snapshot.projection_estimated),
                "soc_age_s": None if age is None else int(age),
                # Some measured energy since the reading was unattributable: the need may be overstated.
                "progress_unknown": getattr(snapshot, "progress_unknown", False) is True,
                "uncertain": bool(snapshot.projection_estimated or snapshot.projection_age_s is None
                                  or snapshot.state in ("planning_unavailable", "incomplete_settings"))}
    except Exception:  # noqa: BLE001 - diagnostics only
        return {"plan_state": "unknown", "uncertain": True}


def _preview(hass: HomeAssistant, entry_id: str, target: Any) -> dict[str, Any]:
    """Describe a proposal without contacting OCPP or changing stored charger state."""
    now = datetime.now(timezone.utc)
    profile = None
    reason = None
    preview_id = None
    try:
        profile = _proposed_profile(hass, entry_id, now)
        settings = domain_data(hass).auto_store.settings(entry_id)
        preview_id = _preview_id(profile, settings.revision)
        if settings.pause.choice != "until_resumed":
            reason = "pause_auto_first"
        elif not _identity_status(hass, target)["supported"]:
            reason = "not_morek_connector"
        else:
            try:
                _charge_point(hass, target)
            except ScheduleRefused as error:
                reason = error.code
    except ScheduleRefused as error:
        reason = error.code
    except Exception:
        # An unavailable planner must not prevent status from reporting charger identity/readback.
        profile = None
        preview_id = None
        reason = "preview_unavailable"
    return {"calculated_at": now.isoformat(), "profile": profile, "reason": reason,
            "preview_id": preview_id}


def _charge_now_price(hass: HomeAssistant, entry_id: str, now: datetime) -> dict[str, Any]:
    """Read published current price independently of the SOC-dependent plan."""
    result = {"current_price": None, "above_cap": None, "price_reason": "price_unavailable"}
    try:
        from ..planning.planner import planning_slots, price_within_cap, effective_minor_per_kwh
        planner = preview_for(hass, entry_id)
        settings = domain_data(hass).auto_store.settings(entry_id)
        manager = planner._manager
        area = manager.area_snapshot(settings.area_id)
        entry = manager.catalogue_snapshot().area(settings.area_id)
        if area is None or entry is None or area.state not in ("ready", "waiting_for_tomorrow"):
            return result
        documents = tuple(day.document for state, authority, day in (
            (area.today_state, area.today_authority, area.today_snapshot),
            (area.tomorrow_state, area.tomorrow_authority, area.tomorrow_snapshot))
            if state == "ready" and authority == "listed" and day.document is not None)
        slots = planning_slots(documents, currency=entry.currency, timezone=entry.tz)
        slot = next((slot for slot in slots if slot.start <= now < slot.start + timedelta(minutes=15)), None)
        if slot is None or not math.isfinite(slot.local_major_per_kwh):
            return result
        cap = settings.soft_price_cap
        basis = settings.cap_price_basis or "nord_pool"
        fiscal = planner._fiscal_for(settings, entry) if cap is not None or basis == "configured_variable_cost" else None
        price = (effective_minor_per_kwh(slot.local_major_per_kwh, fiscal, slot.start) / 100
                 if basis == "configured_variable_cost" else slot.local_major_per_kwh)
        above = None if cap is None else not price_within_cap(slot.local_major_per_kwh,
            cap_major_per_kwh=cap, basis=basis, fiscal=fiscal, start=slot.start)
        return {"current_price": price, "above_cap": above, "price_reason": None,
                "price_basis": basis, "currency": entry.currency, "cap": cap}
    except Exception:  # noqa: BLE001 - unavailable price never authorizes or blocks a request
        return result


def _operator_state(identity: dict[str, Any], online: bool, outcomes: dict[str, Any],
                    verification: dict[str, Any], verified: bool, preview: dict[str, Any],
                    sending_id: str | None) -> dict[str, str | None]:
    """Summarize evidence, never treating an old match or an unknown ACK as success."""
    attempt = outcomes.get("attempt") or {}
    if outcomes.get("uncertain"):
        if sending_id and sending_id == attempt.get("id") and attempt.get("state") == "uncertain":
            return {"state": "sending", "reason": "upload_in_flight"}
        return {"state": "intervention_needed", "reason": outcomes.get("state") or "outcome_uncertain"}
    if not online:
        return {"state": "offline", "reason": "charger_unavailable"}
    if not identity.get("supported"):
        return {"state": "not_ready", "reason": identity.get("reason") or "identity_unresolved"}
    if verification.get("pending"):
        return {"state": "checking", "reason": verification.get("reason")}
    if verified:
        return {"state": "verified", "reason": verification.get("reason")}
    reason = verification.get("reason")
    if reason == "limits_or_transitions_differ":
        return {"state": "mismatch", "reason": reason}
    if reason and reason not in ("cleanup_requested",):
        return {"state": "not_ready", "reason": reason}
    if preview.get("reason") or not preview.get("profile"):
        return {"state": "waiting", "reason": preview.get("reason") or "no_current_plan"}
    return {"state": "ready", "reason": "manual_preview_only"}


async def async_schedule_action(hass: HomeAssistant, entry_id: str, action: str,
                                preview_id: str | None = None, confirm_profile_id: int | None = None, *,
                                expected_sent_at: str | None = None,
                                verification_attempt: int | None = None,
                                expected_attempt_id: str | None = None,
                                verification_handle: Any = None,
                                check: dict[str, Any] | None = None) -> dict[str, Any]:
    """Manual operations share connector serialization without enabling owned mode.

    `check` (Stage 15.3) turns a fetch into the writeless reconnect/startup check: see `_checked_readback`."""
    if action not in ("send", "fetch", "clear") or (check is not None and action != "fetch"):
        raise ScheduleRefused("invalid_action")
    if action == "clear" and (type(confirm_profile_id) is not int or confirm_profile_id != PROFILE_ID):
        raise ScheduleRefused("cleanup_confirmation_required")
    if action == "send" and not preview_id:
        raise ScheduleRefused("preview_changed")
    entry, failure = lookup_charger(hass, entry_id)
    if failure or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")

    def identity() -> dict[str, Any]:
        controller = controller_for(hass, entry_id)
        return _identity_status(hass, getattr(controller, "ocpp_target", None))

    async def run() -> dict[str, Any]:
        from ..execution.command_admission import physical_connector
        admission = command_admission(hass)
        connector = physical_connector(identity()) if action != "fetch" else None
        generation = admission.generation(connector) if connector is not None else None

        def validate_manual_generation() -> None:
            if (connector is None or physical_connector(identity()) != connector
                    or admission.generation(connector) != generation
                    or admission._person_stops.get(connector)):
                raise ScheduleRefused("stale_generation")

        return await _async_schedule_action_locked(hass, entry_id, action, preview_id, confirm_profile_id,
                                                     expected_sent_at=expected_sent_at,
                                                    verification_attempt=verification_attempt,
                                                    expected_attempt_id=expected_attempt_id,
                                                    verification_handle=verification_handle,
                                                    validate_manual_generation=validate_manual_generation,
                                                    check=check)

    admission = command_admission(hass)
    if action == "fetch":
        result = await admission.async_execute(entry_id, "read_only", identity, run)
    else:
        result = await admission.async_manual_profile(entry_id, identity, run)
    if not result.allowed:
        raise ScheduleRefused(result.reason)
    return result.value


def _composite_duration(profile: Any, query_at: datetime) -> int:
    duration = 43200
    if isinstance(profile, dict):
        end = profile["chargingSchedule"]["chargingSchedulePeriod"][-1]["startPeriod"]
        start = datetime.fromisoformat(profile["chargingSchedule"]["startSchedule"].replace("Z", "+00:00"))
        duration = max(duration, min(172800, int((start + timedelta(seconds=end + 3600) - query_at).total_seconds())))
    return duration


async def _composite_readback(cp: Any, target: Any, duration: int, query_at: datetime, ocpp_call: Any) -> dict[str, Any]:
    """The one GetCompositeSchedule read (no send): shared by Fetch, the verification reads and the 15.3 check."""
    try:
        response = await asyncio.wait_for(cp.call(ocpp_call.GetCompositeSchedule(
            connector_id=target.connector_id, duration=duration, charging_rate_unit="A")), timeout=30)
        effective = readback(response, datetime.now(timezone.utc), requested_at=query_at)
        if getattr(response, "connector_id", target.connector_id) != target.connector_id:
            effective["status"] = "wrong_connector"
    except Exception:
        effective = {"status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(), "periods": []}
    return effective


async def _checked_readback(hass: HomeAssistant, entry_id: str, lifecycle: dict[str, Any], cp: Any, target: Any,
                            data: dict[str, Any], check: dict[str, Any], ocpp_call: Any) -> dict[str, Any]:
    """Stage 15.3: connector lock and data lock held. One GetCompositeSchedule, a compare, **no write of any kind**.

    Nothing in `data`, the ledger or the evidence store changes, so a newer attempt's `verified` fields, the
    acknowledged/uncertain fields and the verification state are untouched. The intent is read from the ledger,
    revalidated after the read and bound to the caller's `current()` (connection, attempt, owner generation); a
    result that is no longer current raises `check_superseded` and is discarded by the caller."""
    current = check["current"]
    wanted = check.get("attempt_id")

    async def candidate() -> tuple[dict[str, Any] | None, str | None, str | None]:
        record = await _outcome_record(hass, entry_id, data)
        return check_candidate(
            record, datetime.now(timezone.utc), sending=hass.data.get("spotnav_morek_sending", {}).get(entry_id),
            verification_timer=entry_id in hass.data.get(_VERIFY_KEY, {}),
            dispatched=hass.data.get(_DISPATCHED_KEY, {}).get(entry_id), data=data)

    profile, ack_id, reason = await candidate()
    if (wanted is not None and ack_id != wanted) or not lifecycle["live"] or not current():
        raise ScheduleRefused("check_superseded")
    if reason is not None:
        return {"check": {"class": CHECK_UNKNOWN, "reason": reason, "readback_at": None, "attempt_id": ack_id}}
    wall0, mono0 = datetime.now(timezone.utc), time.monotonic()
    try:
        duration = _composite_duration(profile, wall0)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError):
        return {"check": {"class": CHECK_UNKNOWN, "reason": "profile_unavailable", "readback_at": None,
                          "attempt_id": ack_id}}
    effective = await _composite_readback(cp, target, duration, wall0, ocpp_call)
    drift = (datetime.now(timezone.utc) - wall0).total_seconds() - (time.monotonic() - mono0)
    profile_after, ack_after, reason_after = await candidate()
    if (reason_after is not None or ack_after != ack_id or profile_after != profile
            or not lifecycle["live"] or not current()):
        raise ScheduleRefused("check_superseded")
    comparison = compare_schedule(profile, effective)
    state, why = classify_check(comparison, effective, clock_doubt=abs(drift) > CHECK_CLOCK_DOUBT_S)
    return {"check": {"class": state, "reason": why, "attempt_id": ack_id,
                      **({"facts": mismatch_facts(profile, effective)} if state == CHECK_DIFFERS else {}),
                      "readback_at": effective.get("fetched_at") if str(effective.get("status")).lower() == "accepted" else None}}


async def _async_schedule_action_locked(hass: HomeAssistant, entry_id: str, action: str,
                                        preview_id: str | None, confirm_profile_id: int | None, *,
                                        expected_sent_at: str | None,
                                        verification_attempt: int | None, expected_attempt_id: str | None,
                                        verification_handle: Any, validate_manual_generation: Any,
                                        check: dict[str, Any] | None = None) -> dict[str, Any]:
    entry, failure = lookup_charger(hass, entry_id)
    if failure is not None or entry is None:
        raise ScheduleRefused(failure or "unknown_charger")
    lifecycle = _verification_lifecycle(hass, entry_id, entry)
    controller = controller_for(hass, entry_id)
    target = getattr(controller, "ocpp_target", None)
    if not _identity_status(hass, target)["supported"]:
        raise ScheduleRefused("not_morek_connector")
    await _state(hass, entry_id)
    cache = hass.data[_DATA_KEY]
    data, store, lock = cache[entry_id]
    async with lock:
        if expected_sent_at is not None and (data.get("sent_at") != expected_sent_at or data.get("cleanup")
                                             or data.get("verified") or (expected_attempt_id is not None
                                             and data.get("attempt_id") != expected_attempt_id)):
            raise ScheduleRefused("verification_superseded")
        if not _identity_status(hass, target)["supported"]:
            raise ScheduleRefused("not_morek_connector")
        cp = _charge_point(hass, target)
        from ocpp.v16 import call as ocpp_call
        now = datetime.now(timezone.utc)
        if check is not None:
            return await _checked_readback(hass, entry_id, lifecycle, cp, target, data, check, ocpp_call)
        if action == "send":
            settings = domain_data(hass).auto_store.settings(entry_id)
            if settings.pause.choice != "until_resumed":
                raise ScheduleRefused("pause_auto_first")
            profile = _proposed_profile(hass, entry_id, now)
            if preview_id is None or preview_id != _preview_id(profile, settings.revision):
                raise ScheduleRefused("preview_changed")
            def validate():
                validate_manual_generation()
                current_controller = controller_for(hass, entry_id)
                current_target = getattr(current_controller, "ocpp_target", None)
                if not _identity_status(hass, current_target)["supported"]:
                    raise ScheduleRefused("not_morek_connector")
                current_settings = domain_data(hass).auto_store.settings(entry_id)
                if current_settings.pause.choice != "until_resumed":
                    raise ScheduleRefused("pause_auto_first")
                current_profile = _proposed_profile(hass, entry_id, datetime.now(timezone.utc))
                if preview_id != _preview_id(current_profile, current_settings.revision):
                    raise ScheduleRefused("preview_changed")
                return current_profile, _charge_point(hass, current_target), current_target

            outcome = await _send_profile_shared(hass, entry_id, data, store, preview_id, validate, automatic=False)
            if outcome == "upload_uncertain":
                raise ScheduleRefused("upload_uncertain")
            if outcome != "upload_accepted_unverified":
                raise ScheduleRefused("upload_not_confirmed")
            profile = data["profile"]
        elif action == "clear":
            _cancel_verification(hass, entry_id)
            ledger = outcomes_for(hass)
            record = await _outcome_record(hass, entry_id, data)
            was_uncertain = record["uncertain"]
            previous_acknowledged, previous_verified = record.get("acknowledged"), record.get("verified")
            record.update({"acknowledged": None, "verified": None, "uncertain": True,
                           "removal": {"at": now.isoformat(), "state": "uncertain"}})
            await ledger.write(record)
            try:
                validate_manual_generation()
            except ScheduleRefused:
                record["uncertain"] = was_uncertain
                record["removal"]["state"] = "aborted_before_dispatch"
                record["acknowledged"], record["verified"] = previous_acknowledged, previous_verified
                await ledger.write(record)
                raise
            if not _identity_status(hass, target)["supported"]:
                raise ScheduleRefused("not_morek_connector")
            cp = _charge_point(hass, target)
            # By OCPP 1.6, id alone selects this exact profile. Never send an empty
            # ClearChargingProfile request or use the generic HA clear service.
            prior_data = dict(data)
            data.update({"cleanup": {"requested_at": now.isoformat(), "profile_id": PROFILE_ID,
                                      "status": "unknown"}, "effective": None, "verified": False,
                         "verification": {"pending": False, "reason": "cleanup_requested",
                                          "next_check_at": None, "attempts": 0}})
            await store.async_save(data)
            try:
                validate_manual_generation()
            except ScheduleRefused:
                record["uncertain"] = was_uncertain
                record["removal"]["state"] = "aborted_before_dispatch"
                record["acknowledged"], record["verified"] = previous_acknowledged, previous_verified
                await ledger.write(record)
                data.clear()
                data.update(prior_data)
                await store.async_save(data)
                raise
            current_controller = controller_for(hass, entry_id)
            target = getattr(current_controller, "ocpp_target", None)
            if not _identity_status(hass, target)["supported"]:
                raise ScheduleRefused("not_morek_connector")
            cp = _charge_point(hass, target)
            try:
                response = await asyncio.wait_for(cp.call(ocpp_call.ClearChargingProfile(id=PROFILE_ID)), timeout=30)
                data["cleanup"]["status"] = _status(response)
            except Exception:
                # A timeout does not prove the station did not remove the profile.
                data["cleanup"]["status"] = "unknown"
            status = data["cleanup"]["status"].lower()
            if status in ("accepted", "rejected", "notsupported"):
                record["uncertain"] = was_uncertain
                record["removal"]["state"] = status
            record["removal"]["ack"] = data["cleanup"]["status"]
            await ledger.write(record)
            _evidence_call(hass, entry_id, "record_event", "removal", plan_id=None,
                           status=str(data["cleanup"]["status"]).lower()[:32])
            await store.async_save(data)
        query_at = datetime.now(timezone.utc)
        profile = data.get("profile")
        duration = _composite_duration(profile, query_at)
        worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
        serial = getattr(worker, "_serial", None)
        if expected_sent_at is not None:
            record = await outcomes_for(hass).read()
            if (not lifecycle["live"] or not _verification_current(hass, entry_id, entry, data, record, expected_sent_at)
                    or (expected_attempt_id is not None and data.get("attempt_id") != expected_attempt_id)
                    or (verification_handle is not None
                        and hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not verification_handle)):
                raise ScheduleRefused("verification_superseded")
        effective = await _composite_readback(cp, target, duration, query_at, ocpp_call)
        if expected_sent_at is not None and (entry_id not in hass.data.get(_VERIFY_KEY, {})
                or (verification_handle is not None and hass.data[_VERIFY_KEY].get(entry_id) is not verification_handle)):
            raise ScheduleRefused("verification_superseded")
        record = await outcomes_for(hass).read()
        sent_at = data.get("sent_at")
        current = bool(sent_at and (worker is None or worker._serial == serial)
                       and _verification_current(hass, entry_id, entry, data, record, sent_at))
        if expected_sent_at is not None and (not current or sent_at != expected_sent_at
                or (expected_attempt_id is not None and data.get("attempt_id") != expected_attempt_id)
                or entry_id not in hass.data.get(_VERIFY_KEY, {})
                or (verification_handle is not None and hass.data[_VERIFY_KEY].get(entry_id) is not verification_handle)):
            raise ScheduleRefused("verification_superseded")
        if not lifecycle["live"]:
            raise ScheduleRefused("verification_superseded")
        comparison = compare_schedule(profile, effective)
        if data.get("cleanup"):
            comparison.update({"matched": False, "exact": False, "reason": "cleanup_requested"})
        elif data.get("ack", "").lower() != "accepted":
            comparison.update({"matched": False, "exact": False, "reason": "upload_unconfirmed"})
        elif not current:
            comparison.update({"matched": False, "exact": False, "reason": "verification_superseded"})
        previous_effective = data.get("effective")
        if record is not None and record.get("entry_id") != entry_id:
            comparison.update({"matched": False, "exact": False, "reason": "outcome_uncertain"})
        elif record is not None:
            if record.get("uncertain"):
                comparison.update({"matched": False, "exact": False, "reason": "outcome_uncertain"})
            acknowledged = record.get("acknowledged") or {}
            if comparison["matched"] and acknowledged.get("fingerprint"):
                record["verified"] = {"fingerprint": acknowledged["fingerprint"],
                                      "attempt_at": sent_at, "attempt_id": acknowledged["id"],
                                      "planner_serial": serial,
                                      "at": datetime.now(timezone.utc).isoformat()}
            else:
                record["verified"] = None
            await outcomes_for(hass).write(record)
            if current and (not lifecycle["live"] or (worker is not None and worker._serial != serial)
                    or not _verification_current(hass, entry_id, entry, data, record, sent_at)
                    or (verification_handle is not None
                        and hass.data.get(_VERIFY_KEY, {}).get(entry_id) is not verification_handle)):
                record["verified"] = None
                await outcomes_for(hass).write(record)
                current = False
                comparison.update({"matched": False, "exact": False, "reason": "verification_superseded"})
        # Publish only after the persistence await and its freshness recheck.
        if current or action == "clear" or profile is None:
            data["effective"] = effective
        else:
            comparison.update({"coverage_start": None, "coverage_end": None})
        data["verified"] = comparison["matched"]
        verification = data.setdefault("verification", {})
        verification.update(comparison)
        verification["readback_at"] = effective.get("fetched_at") if data.get("effective") is effective else None
        verification["checked_at"] = datetime.now(timezone.utc).isoformat()
        if data["verified"] or action == "clear" or comparison["reason"] == "verification_superseded":
            _cancel_verification(hass, entry_id)
            verification.update({"pending": False, "next_check_at": None})
        elif action == "send" or verification_attempt is not None:
            next_attempt = 0 if action == "send" else verification_attempt + 1
            verification["attempts"] = 1 if action == "send" else verification_attempt + 2
            if next_attempt < len(VERIFY_DELAYS):
                _schedule_verification(hass, entry_id, data["sent_at"], next_attempt, data.get("attempt_id"))
                if action == "send":
                    # Entry reload/unload invalidates timers. No hardware commands on unload.
                    entry.async_on_unload(lambda: _cancel_verification(hass, entry_id))
                verification.update({"pending": True, "next_check_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=VERIFY_DELAYS[next_attempt])).isoformat()})
            else:
                _cancel_verification(hass, entry_id)
                verification.update({"pending": False, "next_check_at": None})
                _LOGGER.warning("Morek schedule still unverified after bounded readback checks: %s", comparison["reason"])
        _LOGGER.info("Morek %s: upload=%s readback=%s verified=%s reason=%s",
                     action, data.get("ack"), effective["status"], data["verified"], comparison["reason"])
        await store.async_save(data)
        if current and (not lifecycle["live"] or (worker is not None and worker._serial != serial)
                or not _verification_current(hass, entry_id, entry, data, record, sent_at)):
            _cancel_verification(hass, entry_id)
            data["verified"] = False
            data["effective"] = previous_effective
            verification.update({"matched": False, "exact": False, "reason": "verification_superseded",
                                 "readback_at": None, "coverage_start": None, "coverage_end": None,
                                 "pending": False, "next_check_at": None})
            record["verified"] = None
            await outcomes_for(hass).write(record)
            await store.async_save(data)
        # The effective limits the charger reported (not profile inventory, not flow), after every freshness
        # recheck: tied to a plan version only when it was published as that version's current readback.
        _evidence_call(hass, entry_id, "record_readback", effective,
                       plan_id=data.get("attempt_id") if data.get("effective") is effective and current
                       and action != "clear" else None)
        return {"supported": True, "sent_at": data.get("sent_at"), "ack": data.get("ack"), "verified": data.get("verified", False),
                "sent": profile, "effective": data.get("effective"), "cleanup": data.get("cleanup"),
                "cleanup_supported": True, "outcomes": record,
                "verification": _verification_state(hass, entry_id, data)}


@websocket_api.websocket_command({vol.Required("type"): "spotnav/morek_schedule", vol.Required("api_version"): int,
                                   vol.Required("charger_id"): str, vol.Required("action"): vol.In(("status", "send", "fetch", "clear", "request_enable", "disable_uploads", "reconfirm_migration", "charge_now", "return_to_auto", "recalculate_sync", "reset_learning")),
                                   vol.Optional("preview_id"): str, vol.Optional("confirm_profile_id"): int,
                                   vol.Optional("duration_minutes"): int, vol.Optional("end_time"): str})
@websocket_api.async_response
async def websocket_morek_schedule(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if msg["api_version"] != API_VERSION:
        send_unsupported_version(connection, msg, API_VERSION)
        return
    if msg["action"] != "status" and not is_admin(connection):
        connection.send_error(msg["id"], "spotnav_not_admin", "Administrator required")
        return
    if msg["action"] in ("request_enable", "disable_uploads"):
        # In-progress intent groundwork is not a supported mode switch. Keep
        # its records readable, but do not expose new runtime mode controls.
        connection.send_error(msg["id"], "spotnav_morek_action_unavailable", "Schedule mode controls are unavailable")
        return
    try:
        if msg["action"] == "status":
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            data, _ = await _state(hass, entry.entry_id)
            controller = controller_for(hass, entry.entry_id)
            target = getattr(controller, "ocpp_target", None)
            identity = _identity_status(hass, target)
            ownership = await ownership_store(hass).async_status(entry.entry_id, identity)
            admission = command_admission(hass)
            from ..execution.command_admission import physical_connector
            connector = physical_connector(identity)
            current_ticket = (connector is not None and ownership.get("record_state") == "valid"
                              and admission.owned_ticket_current(entry.entry_id, connector))
            ownership["completion_authorized"] = bool(current_ticket)
            ownership["reconfirmation_required"] = (ownership.get("handover_evidence") == "completed" and not current_ticket)
            ownership["limitations"] = ["external_writers_not_inventoried", "native_protection_not_verified",
                                        "historical_mismatch_current_state_unknown", "physical_charging_unknown"]
            ownership["local_regulator"] = ("linked_may_write" if callable(getattr(controller, "_start_cap", None))
                                              else "not_observed")
            ownership["blockers"] = [] if current_ticket else ["migration_or_reconfirmation_required"]
            previous_recovery = admission._recovery_status.get(entry.entry_id, {})
            ownership["recovery"] = await admission.async_recovery_status(
                entry.entry_id, lambda: _identity_status(hass, getattr(controller_for(hass, entry.entry_id), "ocpp_target", None))
            )
            if "recovery_result" in previous_recovery:
                ownership["recovery"]["last_recovery_result"] = previous_recovery["recovery_result"]
                admission._recovery_status[entry.entry_id]["recovery_result"] = previous_recovery["recovery_result"]
            if "migration_result" in previous_recovery:
                ownership["recovery"]["migration_result"] = previous_recovery["migration_result"]
                admission._recovery_status[entry.entry_id]["migration_result"] = previous_recovery["migration_result"]
            if "automatic_recovery" in previous_recovery:
                ownership["recovery"]["automatic_recovery"] = previous_recovery["automatic_recovery"]
                admission._recovery_status[entry.entry_id]["automatic_recovery"] = previous_recovery["automatic_recovery"]
            from ..execution.command_admission import async_auto_legacy_diagnosis
            legacy = await async_auto_legacy_diagnosis(
                admission, entry.entry_id,
                lambda: _identity_status(hass, getattr(controller_for(hass, entry.entry_id), "ocpp_target", None)),
            )
            ownership["legacy_admission"] = {"allowed": legacy.allowed, "reason": legacy.reason}
            try:
                outcomes = await _outcome_record(hass, entry.entry_id, data)
            except (OutcomeUnavailable, ScheduleRefused):
                outcomes = {"state": "storage_unavailable", "uncertain": True}
            attempt = outcomes.get("attempt")
            removal = outcomes.get("removal")
            from ..execution.morek_outcomes import clean_start_origin, clean_start_proven
            clean_start = clean_start_proven(outcomes, entry.entry_id, ownership.get("handover_id"))
            if clean_start_origin(outcomes, entry.entry_id, ownership.get("handover_id")):
                ownership["reconfirmation_required"] = False
            settled = (outcomes.get("uncertain") is False and (clean_start or (isinstance(attempt, dict)
                       and attempt.get("state") in ("accepted", "rejected", "aborted_before_dispatch")))
                       and (removal is None or (isinstance(removal, dict) and removal.get("state") in
                                                ("accepted", "rejected", "notsupported"))))
            removal_unsettled = removal is not None and (not isinstance(removal, dict) or removal.get("state") not in
                                                            ("accepted", "rejected", "notsupported"))
            evidence_blocker = ("outcome_storage_unavailable" if outcomes.get("state") == "storage_unavailable"
                                else "profile_outcome_uncertain" if outcomes.get("uncertain") is True
                                else "profile_outcome_unsettled" if removal_unsettled
                                else "profile_history_unavailable" if not isinstance(attempt, dict)
                                else "profile_outcome_unsettled")
            if not settled:
                # Reconfirmation cannot repair an uncertain profile outcome.
                current_ticket = False
                ownership["completion_authorized"] = False
                ownership["reconfirmation_required"] = False
                ownership["blockers"] = [evidence_blocker]
            verified_evidence = outcomes.get("verified") or {}
            worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
            verification = _verification_state(hass, entry.entry_id, data)
            effective = data.get("effective")
            readback_associated = _readback_associated(verification, effective)
            if not readback_associated:
                verification.update({"matched": False, "exact": False, "coverage_start": None, "coverage_end": None})
            associated = bool(data.get("verified") and verified_evidence.get("attempt_id") == data.get("attempt_id")
                            and verified_evidence.get("attempt_at") == data.get("sent_at")
                            and verified_evidence.get("fingerprint") == (outcomes.get("acknowledged") or {}).get("fingerprint")
                            and (worker is None or verified_evidence.get("planner_serial") == worker._serial)
                            and _verification_current(hass, entry.entry_id, entry, data, outcomes, data.get("sent_at")))
            verified = associated and readback_associated and _verification_coverage_current(verification, datetime.now(timezone.utc))
            if associated and not readback_associated:
                verification.update({"matched": False, "exact": False, "reason": "verification_superseded"})
            elif associated and not verified:
                verification.update({"matched": False, "exact": False, "reason": "coverage_stale"})
            elif data.get("verified") and not verified:
                verification.update({"matched": False, "exact": False, "reason": "verification_superseded"})
            compared = verification.get("reason") in (
                "limits_or_transitions_differ", "coverage_missing", "coverage_too_short", "coverage_stale",
                "coverage_boundary_ambiguous", "no_remaining_transitions", "readback_unavailable")
            if (verification.get("pending") or compared) and not _verification_current(
                    hass, entry.entry_id, entry, data, outcomes, data.get("sent_at")):
                verification.update({"pending": False, "next_check_at": None, "reason": "verification_superseded"})
            if not verified and outcomes.get("verified"):
                outcomes = {**outcomes, "verified": None}
            preview = _preview(hass, entry.entry_id, target)
            link_monitor = getattr(worker, "link_monitor", None)
            checker = getattr(worker, "checker", None)
            try:
                _charge_point(hass, target)
                online = worker is None or (not worker._suspended and worker._available() and not worker._closed)
            except ScheduleRefused:
                online = False
            operator = _operator_state(identity, online, outcomes, verification, verified, preview,
                                       hass.data.get("spotnav_morek_sending", {}).get(entry.entry_id))
            connector = physical_connector(identity)
            stop_pending = connector is not None and bool(admission._person_stops.get(connector))
            aborted_attempt = outcomes.get("attempt") or {}
            aborted_display = (aborted_attempt.get("state") == "aborted_before_dispatch"
                               and aborted_attempt.get("id") == data.get("attempt_id"))
            readiness = _session_readiness(hass, controller, identity, online, datetime.now(timezone.utc),
                                           link_monitor, entry.entry_id)
            session = getattr(worker, "session", None)
            if session is not None and online:
                readiness["session_start"] = dict(session.state)
                changed = getattr(session, "state_at", None)
                readiness["session_start_at"] = changed.isoformat() if isinstance(changed, datetime) else None
            if session is not None:
                readiness["boot_start"] = session.boot_status(
                    getattr(link_monitor, "boot_generation", None) is not None)
            # Diagnostic only: the preview is not a checked dispatch intent and
            # even a matching readback cannot itself authorize a session start.
            readiness["session_schedule_evidence"] = session_start_schedule_evidence(
                preview.get("profile"), effective, datetime.now(timezone.utc), tolerance_s=VERIFY_TOLERANCE_S)
            readiness["activation_blockers"] = [] if current_ticket else ["migration_or_reconfirmation_required"]
            if not settled:
                readiness["activation_blockers"].append(evidence_blocker)
            result = {**identity,
                      "link": link_monitor.status() if link_monitor is not None else None,
                      "readiness": readiness,
                      "schedule_pause": _owned_pause_status(outcomes, verification, verified, worker, stop_pending=stop_pending),
                      "reconciliation": {"check": checker.status() if checker is not None else None,
                                         "repair": repair_status(worker, outcomes),
                                         "reason": worker.reason if worker is not None and
                                         getattr(worker, "reason_serial", -1) == worker._serial else "pending",
                                         "continuity": getattr(worker, "continuity", None),
                                         "recovery": {**recovery_status(outcomes, datetime.now(timezone.utc)),
                                                      "blocker_retry": blocker_retry_status(worker)},
                                         "inputs": _planning_inputs(hass, entry.entry_id),
                                         "last_trigger": getattr(worker, "last_trigger", None),
                                         "blocker": decision_blocker(worker.reason if worker is not None and
                                                                     getattr(worker, "reason_serial", -1) == worker._serial
                                                                     else None),
                                         "decision": decision_status(worker, verification, verified, data.get("attempt_id"))},
                      "ownership": ownership,
                      "outcomes": outcomes,
                      "operator": operator,
                      "sent_at": None if aborted_display else data.get("sent_at"),
                      "ack": None if aborted_display else data.get("ack"), "verified": verified,
                      "verification_target": ("charge_now" if (attempt or {}).get("override_id")
                                              else "held_pause" if (attempt or {}).get("pause_id")
                                              and (outcomes.get("schedule_pause") or {}).get("type") == "pause_until_resumed"
                                              else "current_plan") if verified else None,
                      "sent": None if aborted_display else data.get("profile"), "effective": data.get("effective"),
                      "preview": preview,
                      "cleanup": data.get("cleanup"), "cleanup_supported": True,
                      "verification": verification}
            override = outcomes.get("charge_now")
            active = bool(override and datetime.fromisoformat(override["end"]) > datetime.now(timezone.utc))
            intended = None
            intent_reason = None
            if active and worker is not None:
                try:
                    intended, _ = worker._intent(outcomes.get("schedule_pause"), override)
                except ScheduleRefused as error:
                    intent_reason = error.code
            result["charge_now"] = {"state": "active" if active else "inactive", "intent": override,
                                    "intended": intended, "reason": intent_reason,
                                    "degraded": getattr(worker, "override_degraded", None),
                                    "outcome": attempt if active and (attempt or {}).get("override_id") == override["id"] else None,
                                    "previous_attempt": attempt, "uncertain": outcomes.get("uncertain"),
                                    "measured_charging": "unknown",
                                    **_charge_now_price(hass, entry.entry_id, datetime.now(timezone.utc))}
        elif msg["action"] == "recalculate_sync":
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
            planner = preview_for(hass, entry.entry_id)
            if worker is None or planner is None or worker._closed:
                raise ScheduleRefused("worker_unavailable")
            data, _ = await _state(hass, entry.entry_id)
            record = await _outcome_record(hass, entry.entry_id, data)
            if record.get("uncertain"):
                raise ScheduleRefused("upload_uncertain")
            if (record.get("schedule_pause") or {}).get("type") == "pause_until_resumed":
                raise ScheduleRefused("paused_until_resume")
            override = record.get("charge_now")
            if override and datetime.fromisoformat(override["end"]) > datetime.now(timezone.utc):
                raise ScheduleRefused("charge_now_active")
            await planner.async_recalculate()
            worker.trigger(sync=True)
            result = {"reconciliation": "requested"}
        elif msg["action"] == "reset_learning":
            # Stage 15.11: an administrator's explicit reset of the learned energy and power at this charger (the
            # admin check above ran before anything here). The planner owns the stores and samplers; replanning is the
            # one existing evidence round of the worker (recalculate once, then one compared reconcile), which keeps
            # the active window, every Pause/Stop/uncertainty guard and the equal-intent comparison. Sessions,
            # profiles and outcomes are never touched. A partial failure is reported, not hidden.
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            planner = preview_for(hass, entry.entry_id)
            if planner is None:
                raise ScheduleRefused("planner_unavailable")
            cleared = await planner.async_reset_learning()
            replan = "unavailable"
            if cleared.get("energy") is not None or cleared.get("power") is not None:
                worker = getattr(getattr(entry, "runtime_data", None), "morek_worker", None)
                if worker is not None and not worker._closed:
                    worker.note_learned_reset()
                    replan = "requested"
                else:
                    try:
                        await planner.async_recalculate("learned_reset")
                        replan = "requested"
                    except Exception:  # noqa: BLE001 - reported, the reset itself stands
                        _LOGGER.warning("Replanning after the learning reset failed", exc_info=True)
            result = {"learning_reset": {"energy": cleared.get("energy"), "power": cleared.get("power"),
                                         "replan": replan}}
        elif msg["action"] in ("charge_now", "return_to_auto"):
            result = await async_charge_now_action(hass, msg["charger_id"],
                return_to_auto=msg["action"] == "return_to_auto",
                duration_minutes=msg.get("duration_minutes"), end_time=msg.get("end_time"))
        elif msg["action"] == "reconfirm_migration":
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            admission = command_admission(hass)
            code = await admission.async_reconfirm_completed(
                entry.entry_id,
                lambda: _identity_status(hass, getattr(controller_for(hass, entry.entry_id), "ocpp_target", None)),
                persist_recovery_proof=True,
            )
            if code != "reconfirmed":
                raise ScheduleRefused(code)
            result = {"reconfirmation": code, "physical_state": "unknown"}
        elif msg["action"] in ("request_enable", "disable_uploads"):
            entry, failure = lookup_charger(hass, msg["charger_id"])
            if failure or entry is None:
                raise ScheduleRefused(failure or "unknown_charger")
            admission = command_admission(hass)
            result_code = await admission.async_schedule_request(
                entry.entry_id,
                lambda: _identity_status(hass, getattr(controller_for(hass, entry.entry_id), "ocpp_target", None)),
                requested=msg["action"] == "request_enable",
            )
            result = {"request_result": result_code, "dispatch_allowed": False,
                      "reason": "schedule_mode_unarmed"}
        else:
            result = await async_schedule_action(hass, msg["charger_id"], msg["action"], msg.get("preview_id"),
                                                 msg.get("confirm_profile_id"))
            controller = controller_for(hass, msg["charger_id"])
            target = getattr(controller, "ocpp_target", None)
            result.update(_identity_status(hass, target))
            result["preview"] = _preview(hass, msg["charger_id"], target)
        connection.send_result(msg["id"], {"api_version": API_VERSION, "schedule": result})
    except ScheduleRefused as error:
        connection.send_error(msg["id"], f"spotnav_morek_{error.code}", error.code)
    except Exception:
        _LOGGER.exception("Morek schedule request failed")
        connection.send_error(msg["id"], "spotnav_morek_unavailable", "Morek schedule request failed")


@callback
def async_setup_morek_schedule_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_morek_schedule)
