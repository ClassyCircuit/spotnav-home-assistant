"""Shared, estimated price-policy facts for dashboard and settings preview.

These facts describe a proposal, not energy measured at the charger.  Reasons
are stable codes; callers may translate them without reproducing the policy.
"""

from __future__ import annotations

from typing import Any

from ..planning.auto_controller import AutoSnapshot
from ..planning.auto_settings import AutoSettings
from ..util import aware_iso, finite_number

_EPSILON = 1e-6


def encode_price_policy(settings: AutoSettings, snapshot: AutoSnapshot | None) -> dict[str, Any]:
    """Explain a capped calculation, including empty/refused outcomes without inventing energy."""
    current = snapshot if snapshot is not None and snapshot.settings_revision == settings.revision else None
    proposal = None if current is None else current.proposal
    planned = proposal is not None and (proposal.has_plan or proposal.reason == "no_eligible_energy")
    currency = None if current is None else current.currency
    exception_cost = None
    if planned and proposal is not None and not proposal.unpriced and currency is not None:
        exception_cost = sum(
            max(0.0, (min(slot.end, end) - max(slot.start, start)).total_seconds())
            / 3600 * proposal.power_kw * slot.effective_minor_per_kwh / 100
            for slot in proposal.slots for start, end in proposal.exception_periods
        )
    explanations: list[dict[str, Any]] = []
    if current is None:
        explanations.append({"code": "recalculating"})
    elif current.reason == "already_at_target":
        explanations.append({"code": "target_met"})
    elif proposal is None or not planned:
        explanations.append({"code": "unavailable", "reason": current.reason, "missing": list(current.missing)})
    else:
        if proposal.exception_kwh > _EPSILON:
            explanations.append({"code": "minimum_exception"})
        if proposal.minimum_shortfall_kwh is not None:
            explanations.append({"code": "minimum_shortfall" if proposal.minimum_shortfall_kwh > _EPSILON
                                 else "minimum_covered"})
        if proposal.policy_shortfall_kwh is not None and proposal.policy_shortfall_kwh > _EPSILON:
            explanations.append({"code": "target_shortfall"})
        if not explanations:
            explanations.append({"code": "uncapped" if settings.soft_price_cap is None else "within_cap"})
        if proposal.block_limit_compromise:
            # The stored Morek profile carries a few windows only: the plan was chosen within that limit.
            explanations.append({"code": "block_limit"})
    if current is not None and current.last_error_code is not None:
        explanations.append({"code": "error", "reason": current.last_error_code})
    fx = None if current is None else current.fx_provenance
    fx_states = [item.get("state") for item in fx or ()]
    # Stage 17.5: a soft cap in local currency is compared with the *converted* price, so say which rate that was.
    # `dated`: an earlier ECB table than the day's own (rate, date, age below); `missing`: the day cannot be priced
    # and the plan waits for the ECB rate, which is asked for again automatically.
    fx_state = None if not fx_states else (
        "missing" if "missing" in fx_states else "undated" if "undated" in fx_states
        else "dated" if "dated" in fx_states else "own")
    note = None
    if fx_state in ("dated", "undated", "missing"):
        used = [item for item in fx or () if item.get("state") in ("dated", "undated")]
        oldest = max(used, key=lambda item: item.get("age_days") or 0, default=None)
        if fx_state == "missing":
            note = ("Waiting for the ECB exchange rate; it is asked for again automatically. "
                    "No other day's or currency's rate is used.")
        elif fx_state == "dated" and oldest is not None:
            note = (f"Prices converted with the {oldest.get('source') or 'ECB'} rate of {oldest.get('date')}, "
                    f"{oldest.get('age_days')} day(s) before the priced day, not that day's own rate"
                    + ("; the soft cap was compared with the price converted at that rate." if settings.soft_price_cap is not None
                       else "."))
        else:
            note = "Prices converted with an exchange rate that carries no date."
    return {
        "fx_note": note,
        "fx": fx,
        "fx_state": fx_state,
        "fx_waiting": fx_state == "missing" or (current is not None and current.reason == "missing_fx_rate"),
        "basis": settings.cap_price_basis,
        # The cap may be based on raw Nord Pool; estimates always use the
        # planner's configured variable fees/taxes and are not measured costs.
        "cost_basis": "configured_variable_cost",
        "cap": finite_number(settings.soft_price_cap),
        "minimum_soc": finite_number(settings.minimum_ready_by_soc),
        "target_soc": finite_number(settings.target.target_percent),
        "ready_by_time": settings.departure.strftime("%H:%M") if settings.departure_enabled else None,
        "ready_by": None if current is None else aware_iso(current.departure_at),
        "state": None if current is None else current.state,
        "reason": None if current is None else current.reason,
        "provisional": proposal is not None and proposal.price_coverage_end is not None,
        "price_coverage_end": None if proposal is None else aware_iso(proposal.price_coverage_end),
        # Stage 16.2: tomorrow's prices are not (yet) usable. A plan made meanwhile is from published data only.
        "price_state": None if current is None else current.price_state,
        "tomorrow_pending": bool(proposal is not None and proposal.price_coverage_end is not None
                                 and current is not None and current.price_state in ("waiting_for_tomorrow", "degraded")),
        "error": None if current is None else current.last_error_code,
        "explanations": explanations,
        "minimum_shortfall_kwh": None if proposal is None else finite_number(proposal.minimum_shortfall_kwh),
        "target_shortfall_kwh": None if proposal is None else finite_number(proposal.policy_shortfall_kwh),
        "exception_kwh": None if proposal is None else finite_number(proposal.exception_kwh),
        "block_limit": None if proposal is None else proposal.block_limit,
        "unrestricted_blocks": None if proposal is None else proposal.unrestricted_blocks,
        "block_limit_extra_cost": None if proposal is None or currency is None
        else finite_number(proposal.block_limit_extra_cost),
        "block_limit_shortfall_kwh": None if proposal is None or not proposal.block_limit_compromise
        else finite_number(proposal.block_limit_shortfall_kwh),
        "exception_periods": [] if proposal is None else [
            {"start": aware_iso(start), "end": aware_iso(end)} for start, end in proposal.exception_periods
        ],
        "estimated_plan_kwh": None if not planned or proposal is None else finite_number(proposal.delivered_kwh),
        "estimated_plan_cost": None if not planned or proposal is None or proposal.unpriced or currency is None
        else {"value": finite_number(proposal.estimated_cost), "currency": currency},
        "estimated_exception_cost": None if exception_cost is None else {
            "value": finite_number(exception_cost), "currency": currency,
        },
    }
