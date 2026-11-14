// Stage 9.5: a prominent, honest account of what is blocking the Morek schedule and what happens next.
// Pure: the panel supplies decoded status and a clock. Nothing here treats an accepted request or a readback as
// measured charging, and a queued sync is never presented as an upload that succeeded.

const WHAT = {
  wait_for_charger_connection: 'The charger is not connected to Home Assistant, so no schedule was sent.',
  check_charger_identity: 'The charger identity could not be confirmed, so no schedule was sent.',
  retry_after_stop_or_change: 'A Stop or a connector change interrupted the update; nothing more was sent.',
  confirm_ownership: 'Schedule ownership needs confirmation before anything is sent.',
  resolve_protection_conflict: 'Another controller or site protection may also limit this charger; sending is blocked.',
  resume_schedule: 'Auto is paused until you press Resume.',
  confirm_resume: 'Resume cannot be continued automatically; confirm Resume again.',
  wait_for_charge_now_end: 'Charge Now is active; Auto follows when it ends or you return to Auto.',
  check_charger_outcome: 'The last schedule write has an unknown outcome. It is not retried automatically.',
  check_charger_response: 'The charger refused the schedule.',
  wait_for_planner: 'The plan is being recalculated.',
  check_logs: 'The schedule check failed unexpectedly; see SpotNav logs.',
  wait_for_fresh_inputs: 'Waiting for a fresh vehicle reading.',
  // Stage 17.6: a hold the planner names itself; who acts is stated, none of these claims charging.
  set_battery_capacity: 'No plan yet: the battery capacity is not known. Enter it in Plan; the plan is then made automatically, and sent automatically only if the usual safety checks allow it.',
  wait_for_exchange_rate: 'No plan yet: waiting for the ECB exchange rate to convert the prices. It is asked for again automatically and the plan follows.',
  adjust_planning_settings: 'The plan cannot be sent as saved; adjust the planning settings.',
  wait_for_prices: 'Prices are unavailable or incomplete for the planned window.',
  see_reason: 'The schedule is not being updated.',
  // 15.4a/b repair outcomes. Plain words, who acts; none of these asks for a blind resend.
  needs_person: 'Automatic repair is paused for this attempt: the charger’s schedule still doesn’t match, or the repair limit is used up. Check the charger and the SpotNav logs.',
  wait_for_repair_deferral: 'The charger’s schedule differs a little. The current charge is left alone and SpotNav fixes it a bit later.',
  wait_for_repair_spacing: 'SpotNav already fixed the charger’s schedule recently, so it waits before sending again. Nothing is sent now.',
  wait_for_confirmation: 'Checking the charger’s schedule again: one odd reading isn’t enough to act on.',
  wait_for_repair_release: 'The charger’s schedule differs from the plan, but automatic repair is off, so nothing was sent. Check the schedule in the Morek app.',
};
const REPAIR_NOTE = new Set(['wait_for_repair_deferral', 'wait_for_repair_spacing', 'wait_for_confirmation', 'wait_for_repair_release']);
// Only these end by themselves: the panel says so and when SpotNav checks again.
// A person's setting ends this one, then the existing recalculation sends once: no Refresh or Send needed.
const PERSON_THEN_AUTOMATIC = new Set(['set_battery_capacity']);
const AUTOMATIC = new Set(['wait_for_charger_connection', 'check_charger_identity', 'retry_after_stop_or_change', 'wait_for_planner', 'wait_for_fresh_inputs', 'wait_for_prices', 'wait_for_exchange_rate', 'check_logs']);

const time = (iso) => {
  const at = Date.parse(iso || '');
  return Number.isFinite(at) ? new Date(at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : null;
};

/** @returns {{level: 'error'|'warning'|'info', text: string, code: string}|null} */
export function recoveryBanner(state, now = Date.now()) {
  if (!state || state.supported === false) return null;
  const reconciliation = state.reconciliation || {};
  const blocker = reconciliation.blocker;
  const recovery = reconciliation.recovery || {};
  if (state.outcomes?.uncertain === true || blocker?.code === 'upload_uncertain') {
    return {level: 'error', code: 'upload_uncertain', text: `${WHAT.check_charger_outcome} Charging is not confirmed; check Morek and the SpotNav logs before acting. Nothing was cleared.`};
  }
  const repair = reconciliation.repair || {};
  const checkClass = reconciliation.check && typeof reconciliation.check === 'object' ? reconciliation.check.class : null;
  // A repair that gave up is a persistent "needs a person" until a healthy check or a new plan; it outranks the
  // timed, automatic blockers (but not an unknown write above), and is never reworded as a retry.
  if (blocker?.code === 'repair_needs_person' || (repair.needs_person === true && checkClass !== 'healthy' && blocker?.code !== 'upload_rejected')) {
    return {level: 'error', code: 'repair_needs_person', text: WHAT.needs_person};
  }
  if (!blocker) return null;
  if (REPAIR_NOTE.has(blocker.action)) {
    // Not a fault: SpotNav is waiting on purpose. Nothing here is a charging claim and no button resends anything.
    const next = blocker.action === 'wait_for_repair_spacing' ? time(repair.budget?.next_at) : null;
    const due = next && Date.parse(repair.budget.next_at) > now ? ` It can send again after ${next}.` : '';
    return {level: blocker.action === 'wait_for_repair_release' ? 'warning' : 'info', code: blocker.code, text: `${WHAT[blocker.action]}${due}`};
  }
  // A healthy planner answer, not a pending recalculation: the plan found nothing to charge. This is a statement about
  // the plan only; it is not evidence of actual power or of a stopped charge.
  const inputs = reconciliation.inputs || {};
  if (blocker.action === 'wait_for_planner' && inputs.plan_state === 'nothing_to_charge' && blocker.code !== 'plan_inputs_changed') {
    return {level: 'info', code: blocker.code, text: 'Nothing to charge right now: the plan needs no charging, so no schedule is being sent. This describes the plan, not the charger’s actual power. SpotNav plans again when the car, prices or settings change.'};
  }
  const what = WHAT[blocker.action] || WHAT.see_reason;
  const suffix = ` (${blocker.detail || blocker.code})`;
  if (blocker.code === 'upload_rejected') {
    const next = time(recovery.next_retry_at);
    if (next && Date.parse(recovery.next_retry_at) > now) {
      return {level: 'warning', code: blocker.code, text: `${what} Retrying automatically at ${next}; ${recovery.retries_left ?? 0} attempt${recovery.retries_left === 1 ? '' : 's'} left.${suffix}`};
    }
    if (recovery.exhausted) return {level: 'error', code: blocker.code, text: `${what} Automatic retries are used up; the schedule was not confirmed. Check the charger, then use Recalculate/sync.${suffix}`};
    return {level: 'warning', code: blocker.code, text: `${what} Retrying shortly.${suffix}`};
  }
  const retry = recovery.blocker_retry;
  if (PERSON_THEN_AUTOMATIC.has(blocker.action)) return {level: 'warning', code: blocker.code, text: `${what}${suffix}`};
  if (AUTOMATIC.has(blocker.action)) {
    const next = retry && !retry.exhausted ? time(retry.next_retry_at) : null;
    const when = next ? ` SpotNav re-checks automatically at ${next}, and as soon as something changes.` : retry?.exhausted ? ' Timed re-checks stopped; SpotNav re-checks when something changes. Use Recalculate/sync to check now.' : ' SpotNav re-checks when something changes.';
    const car = blocker.who === 'vehicle' ? ' The plan is made automatically when the car reports its charge level.' : '';
    return {level: 'warning', code: blocker.code, text: `${what}${car}${when}${suffix}`};
  }
  const paused = blocker.action === 'resume_schedule' || blocker.action === 'wait_for_charge_now_end';
  return {level: paused ? 'info' : 'error', code: blocker.code, text: `${what}${paused ? '' : ' Needs your attention; it does not clear by itself.'}${suffix}`};
}
