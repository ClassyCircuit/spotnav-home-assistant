// Whether a plugged-in car is actually going to charge: charge-session authorization and transaction
// status, as one calm, honest summary. Pure: decoded Morek status plus a clock; nothing here writes anything.
//
// Evidence is kept apart on purpose. A start request ACK, the charge-control switch, a transaction
// observation and measured power are different things:
//   * the switch is expected to be off, and no transaction expected, in Preparing before authorization;
//   * an accepted start request alone is not a transaction, and a transaction is not charging;
//   * only fresh measured power or current is measured flow.
// A warning is raised only for a lasting problem on a fresh status, never during a short transient
// (grace), a scheduled wait, a Pause, an unplug, or stale/unknown data.
import { observationFreshness } from '../src/observation-freshness.ts';
import { evidence, STRICT_MAX_AGE_MS } from './evidence-freshness.js';

export const GRACE_MS = 120000;       // matches the backend's accepted-without-transaction bound
const CLOCK_SKEW_MS = 5000;
const POWER_FLOW_W = 100;
const CURRENT_FLOW_A = 1;

const TRANSIENT = new Set(['worker_suspended', 'charger_unavailable', 'stale_generation', 'ownership_not_current',
  'identity_changed', 'connector_quiescing', 'lifecycle_initializing', 'retry_cooldown', 'planner_changed',
  'ownership_recheck_failed', 'waiting_for_new_connection', 'connection_changed', 'connector_not_preparing',
  'newer_stop_or_connection_change', 'charger_connection_changed', 'vehicle_event_recorded']);
const PAUSED = new Set(['paused_until_resume', 'legacy_pause_active']);
const FINISHED = new Set(['session_completed', 'car_completion_reported', 'session_ended_or_completion_ambiguous']);
const DISAGREES = new Set(['limits_or_transitions_differ', 'verification_superseded']);
const LOGGING = new Set(['ocpp_sensitive_logging_enabled', 'unsupported_ocpp_logging_or_interface']);

const ago = ms => ms < 60000 ? `${Math.max(0, Math.floor(ms / 1000))} s ago` : ms < 3600000 ? `${Math.floor(ms / 60000)} min ago` : `${Math.floor(ms / 3600000)} h ago`;
const clock = ms => new Date(ms).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
const num = (value, digits) => Number(value.toFixed(digits)).toString();

// A reading as display evidence: current per the backend's connection-aware judgement when it offers one (15.6),
// else the strict bound. `strict` keeps the old bound visible; nothing here acts on either.
const stamped = (ready, key, reading, now, accept) => evidence(ready, key, reading, now, r => accept(r.value));
/**
 * The backend's charge-control reading (15.5): {state: 'enabled'|'not_ready', reason} or null when it says nothing
 * (absent, offline/unknown). A present but malformed value is "not confirmed", never enabled. The switch is a
 * derived entity: even `enabled` is neither authorization nor a transaction.
 */
function chargingEnabled(ready) {
  const value = ready?.charging_enabled;
  if (value === undefined || value === null) return null;
  if (typeof value !== 'object' || Array.isArray(value)) return {state: 'not_ready', reason: 'control_unconfirmed'};
  if (value.state === 'unknown') return null;
  const reason = typeof value.reason === 'string' ? value.reason : '';
  if (value.state === 'enabled' && reason === 'control_on') return {state: 'enabled', reason};
  return {state: 'not_ready', reason: ['control_off', 'control_unavailable'].includes(reason) ? reason : 'control_unconfirmed'};
}
const isNumber = v => typeof v === 'number' && Number.isFinite(v);

/**
 * The current limit from the charger's own schedule: {amps, nextStart, source} or null when not credible.
 * 'readback' = a fresh effective-schedule readback. 'sent' = only a plan SpotNav sent that the charger
 * acknowledged: it is a plan, not proof of what is installed, and is never used once a readback disagrees or
 * the plan's own coverage has ended. A stale or unstamped readback is not evidence.
 */
export function scheduleLimit(status, now) {
  const points = [];
  let source = null;
  const eff = status?.effective;
  const readbackFresh = !!eff && observationFreshness(Date.parse(eff.fetched_at || ''), now, false) === 'fresh';
  if (readbackFresh && Array.isArray(eff.periods) && eff.periods.length) {
    for (const p of eff.periods) { const at = Date.parse(p?.at || ''); if (Number.isFinite(at) && isNumber(p?.amps)) points.push({at, amps: p.amps}); }
    const start = Date.parse(eff.schedule_start || ''), span = eff.duration_s;
    if (points.length && Number.isFinite(start) && isNumber(span) && now > start + span * 1000) return null;
    source = 'readback';
  } else if (status?.sent && /^accepted$/i.test(String(status.ack || '').trim()) && !DISAGREES.has(status.verification?.reason)) {
    const schedule = status.sent.chargingSchedule, start = Date.parse(schedule?.startSchedule || '');
    const sentAt = Date.parse(status.sent_at || '');
    // An ACK with no send time, or a plan with no known end, cannot be shown to still apply.
    if (Number.isFinite(start) && Number.isFinite(sentAt) && sentAt <= now + CLOCK_SKEW_MS && isNumber(schedule?.duration) && now <= start + schedule.duration * 1000 && Array.isArray(schedule?.chargingSchedulePeriod)) {
      for (const p of schedule.chargingSchedulePeriod) if (isNumber(p?.startPeriod) && isNumber(p?.limit)) points.push({at: start + p.startPeriod * 1000, amps: p.limit});
      source = 'sent';
    }
  }
  points.sort((a, b) => a.at - b.at);
  const current = [...points].reverse().find(p => p.at <= now);
  if (!current) return null;
  const next = points.find(p => p.at > now && p.amps > 0);
  return {amps: current.amps, nextStart: next ? next.at : null, source};
}

function transactionEvidence(ready, now, norm, startAt) {
  const r = stamped(ready, 'transaction', ready?.live?.transaction, now, v => typeof v === 'boolean');
  if (!r || !r.fresh) return {kind: 'unknown'};
  if (r.value === false) return {kind: 'none', age: r.age};
  if (norm === 'charging' || norm === 'paused') return {kind: 'observed', age: r.age};
  // In Preparing a leftover transaction number may belong to an earlier session: it counts only when it
  // changed after this plug-in's start request.
  const changed = Date.parse(r.reading.changed_at || '');
  if (Number.isFinite(startAt) && Number.isFinite(changed) && changed >= startAt - CLOCK_SKEW_MS) return {kind: 'observed', age: r.age};
  return {kind: 'unmatched', age: r.age};
}

// `posture` is the one-glance answer while plugged in: authorized / waiting_on_purpose / at_risk / pending
// (asked, not confirmed) / unknown. Derived from the evidence rules above, never from the switch alone.
const POSTURE = {transaction_observed: 'authorized', charging: 'authorized', reported_charging: 'authorized', scheduled_wait: 'waiting_on_purpose', paused: 'waiting_on_purpose',
  pending: 'pending', accepted_waiting: 'pending', transaction_unmatched: 'pending', not_ready: 'pending'};
const result = (kind, level, title, detail, extra = {}) => {
  const warning = level === 'warning' || level === 'error';
  return {kind, level, warning, title, detail, action: '', facts: [], summary: `${title}. ${detail}`,
    posture: warning ? 'at_risk' : POSTURE[kind] || 'unknown', ...extra};
};
// How long ago, or for a quiet event the backend still judges current, since when it has been unchanged.
const when = item => item.judged === 'current' && item.age > STRICT_MAX_AGE_MS ? `unchanged since ${clock(item.at)}` : ago(item.age);

/**
 * @returns {null | {kind: string, level: 'ok'|'info'|'warning'|'error'|'unknown', warning: boolean,
 *   title: string, detail: string, action: string, facts: string[], summary: string}}
 * null only when the charger is not a Morek schedule charger (nothing to say).
 */
export function chargeSession(status, observedAt, failed, now = Date.now()) {
  if (status && status.supported === false) return null;
  const fresh = observationFreshness(observedAt, now, failed) === 'fresh';
  if (!status || !fresh) {
    return result('unknown', 'unknown', 'Charging status unknown', 'Morek status is unavailable or out of date, so whether the car will charge is not known. Refresh to check.');
  }
  const ready = status.readiness || {};
  const live = ready.live && typeof ready.live === 'object' ? ready.live : null;
  const ss = ready.session_start || {};
  const startAt = Date.parse(ready.session_start_at || '');
  const age = Number.isFinite(startAt) ? Math.max(0, now - startAt) : null;
  const reported = stamped(ready, 'status', live?.status, now, v => typeof v === 'string' && v !== '');
  const reportedFresh = reported && reported.fresh ? reported : null;
  const normRaw = reportedFresh && typeof reportedFresh.reading.normalized === 'string' ? reportedFresh.reading.normalized : null;
  const norm = normRaw === 'unknown' ? null : normRaw;   // Unavailable/Reserved say nothing about a vehicle
  const raw = reportedFresh ? reportedFresh.value : null;

  const power = stamped(ready, 'power_w', live?.power_w, now, isNumber), current = stamped(ready, 'current_a', live?.current_a, now, isNumber);
  const flow = [power && {kind: 'power', ...power}, current && {kind: 'current', ...current}].filter(Boolean).find(item => item.fresh) || null;
  const flowing = !!flow && (flow.kind === 'power' ? flow.value > POWER_FLOW_W : flow.value > CURRENT_FLOW_A);
  const txn = transactionEvidence(ready, now, norm, startAt);
  const control = stamped(ready, 'control_state', live?.control_state, now, v => v === 'on' || v === 'off');
  const paused = status.schedule_pause?.intent === 'pause_until_resumed' || PAUSED.has(ss.reason);
  const hold = scheduleLimit(status, now);

  const facts = [];
  if (raw) facts.push(`Connector: ${raw}${reportedFresh ? ` (${when(reportedFresh)}${reportedFresh.strict ? '' : '; too old for automatic actions'})` : ''}`);
  if (ss.state && ss.reason !== 'authorization_path_unimplemented') {
    const when = age !== null ? `, ${ago(age)}` : '';
    facts.push(`Start request: ${ss.state === 'accepted' ? 'accepted by the charger' : ss.state === 'starting' ? 'being sent' : ss.state === 'waiting' ? 'not sent yet' : ss.state === 'rejected' ? 'rejected' : ss.state === 'uncertain' ? 'outcome unknown' : ss.state}${when}`);
  }
  facts.push(txn.kind === 'observed' ? 'Transaction: reported by the charger' : txn.kind === 'none' ? 'Transaction: none reported' : txn.kind === 'unmatched' ? 'Transaction: a number is reported but is not tied to this plug-in' : 'Transaction: unknown');
  const enabled = chargingEnabled(ready);
  if (enabled) facts.push(`Charging enabled: ${enabled.state === 'enabled' ? 'switch is on (not proof of authorization)' : enabled.reason === 'control_off' ? 'switch is off' : enabled.reason === 'control_unavailable' ? 'switch missing or unavailable' : 'not confirmed'}`);
  else if (control?.fresh) facts.push(`Charge-control switch: ${control.value}${control.value === 'off' && txn.kind !== 'observed' ? ' (normal before authorization)' : ''}`);
  if (flow?.fresh) facts.push(`Measured ${flow.kind === 'power' ? (flow.value >= 1000 ? `${num(flow.value / 1000, 2)} kW` : `${num(flow.value, 0)} W`) : `${num(flow.value, 1)} A`} (${when(flow)})`);
  else facts.push('Measured power: unknown');
  const done = r => { r.facts = facts; return r; };

  if (enabled?.reason === 'control_unavailable' && ss.state !== 'offline') {
    return done(result('control_unavailable', 'warning', 'Charging can’t be started or scheduled', 'The charger’s charge-control switch is missing, disabled or unavailable in Home Assistant, so SpotNav can’t enable charging.',
      {action: 'You: check that the charger’s charge-control switch is enabled in Home Assistant.'}));
  }
  // Offline / lost connection is "not known", never a charging failure: say what was last confirmed, and when.
  const lastSeen = reported ? `Connection lost; last confirmed “${reported.value}” at ${clock(reported.at)}. ` : '';
  if (ready.control === 'unavailable' || ss.state === 'offline') {
    return done(result('offline', 'warning', 'Charger offline', `${lastSeen}Home Assistant cannot reach the charger or its control, so it cannot start or follow a charge. Whether the car is charging is not known until it reconnects.`,
      {action: 'Check the charger’s power and network connection. SpotNav re-checks automatically.'}));
  }
  if (reported && !reportedFresh && reported.judged === 'last_known') {
    return done(result('last_known', 'unknown', 'Charger status last known', `${lastSeen}Whether the car is charging is not known right now.`));
  }
  if (!norm) {
    return done(result('unknown', 'unknown', 'Charging status unknown', 'The charger’s connector state is not currently known, so whether the car will charge cannot be told.'));
  }
  if (norm === 'disconnected') return done(result('unplugged', 'info', 'Not plugged in', 'No car is connected. SpotNav requests charging authorization when a car is plugged in.'));
  if (norm === 'error') {
    return done(result('fault', 'error', 'Charger reports a fault', 'The connector is in a fault state and will not charge.', {action: 'Check the charger and the Morek app; unplug and re-plug once it clears.'}));
  }
  if (status.outcomes?.uncertain === true || ss.state === 'uncertain') {
    return done(result('uncertain', 'error', 'Start request outcome unknown', 'A request to the charger may or may not have applied. SpotNav does not repeat it on its own, so the car may not charge.',
      {action: 'Check the Morek app and the SpotNav logs before acting.'}));
  }
  if (flowing) {
    const agrees = norm === 'charging';
    const conflict = enabled?.state === 'not_ready';   // measured flow wins; the disagreeing switch is flagged, not hidden
    return done(result('charging', conflict ? 'info' : 'ok', 'Charging', `${flow.kind === 'power' ? 'Measured power' : 'Measured current'} confirms the car is drawing energy${agrees ? '' : `, although the charger reports “${raw}”`}.${conflict ? ' Note: the charge-control switch is off or not confirmed, which does not match this.' : ''}`, {conflict}));
  }
  if (norm === 'finished') return done(result('finished', 'info', 'Charge finished', 'The car reports the session as finished; plug in again to start a new one.'));
  if (norm === 'charging' && !(enabled?.state === 'not_ready' && !paused)) {
    return done(result('reported_charging', 'info', 'Charger reports charging', flow ? 'The charger reports charging but measures no power at the moment. This is normal while it ramps up or between windows.' : 'The charger reports charging; power is not measured, so the actual flow is not confirmed.'));
  }
  // A hold is shown only with its provenance: a fresh readback, or a plan the charger acknowledged (not proof).
  const waitNote = hold && hold.amps === 0
    ? (hold.source === 'readback'
      ? `The charger’s schedule holds charging back${hold.nextStart ? ` until about ${clock(hold.nextStart)}` : ''}.`
      : `The plan sent to the charger holds charging back${hold.nextStart ? ` until about ${clock(hold.nextStart)}` : ''} (acknowledged by the charger, not confirmed by a readback).`)
    : '';
  const notPromised = 'Charging may begin then if the car and charger allow it; that is not guaranteed.';
  if (paused) {
    return done(result('paused', 'info', 'Plugged in — Auto is paused', 'Charging will not start until you Resume Auto. This is your pause, not a fault.'));
  }
  const guidance = 'The car may not charge. Start the charge from the Morek app, or unplug and plug in again so SpotNav can retry. SpotNav will not repeat the request on its own.';
  const retryPending = 'SpotNav will retry once by itself. If it is rejected again, start the charge from the Morek app, or unplug and plug in again.';
  const young = age !== null && age < GRACE_MS;
  const reason = ss.reason || '';
  const hasStart = !!ss.state && reason !== 'authorization_path_unimplemented';
  const outcome = hasStart ? startOutcome(ss.state, reason, {age, young, raw, waitNote, txn, guidance, retryPending}) : null;
  if (enabled?.state === 'not_ready') {
    // Charging must be enabled before a car can charge. Off or unconfirmed is "not ready" in every plugged-in state:
    // a suspension, a reported "charging" or an older transaction number is not proof, and not a schedule wait.
    const note = ' The charger’s charge-control switch is also off or not confirmed.';
    if (norm === 'connected' && outcome?.warning) { outcome.detail += note; outcome.summary += note; return done(outcome); }
    const startPending = !outcome || outcome.kind === 'pending' || outcome.kind === 'accepted_waiting';
    if (norm !== 'connected' || txn.kind === 'observed' || startPending) {
      const boot = ready.boot_start?.state;
      const asked = ss.state === 'starting' || ss.state === 'accepted';   // the boot 'requested' token is intent, not proof of a request
      const off = enabled.reason === 'control_off' ? 'off' : 'not confirmed';
      const detail = norm !== 'connected' || txn.kind === 'observed'
        ? `The charger reports ${norm === 'connected' ? 'a transaction' : `“${raw}”`}, but the charge-control switch is ${off}, so charging and any schedule wait are not confirmed. A transaction number may be left over from an earlier session.`
        : asked ? 'We asked the charger to enable charging. Waiting for the charger to confirm.'
        : boot === 'waiting' ? 'Charging isn’t enabled on the charger yet. SpotNav will ask the charger once its checks pass.'
        : 'Charging isn’t enabled on the charger yet, so it can’t start.';
      return done(result('not_ready', 'info', 'Not yet ready to charge', detail,
        {action: asked || boot === 'waiting' ? '' : 'SpotNav asks the charger to enable it when it can. If that doesn’t happen, enable charging in the Morek app.'}));
    }
  }
  if (norm === 'paused') {
    // A schedule hold explains a suspension only with a fresh transaction report; otherwise it is just suspended.
    if (waitNote && txn.kind === 'observed') {
      return done(result('scheduled_wait', 'info', 'Plugged in — waiting for the schedule', `${waitNote} ${notPromised}`));
    }
    const known = txn.kind === 'none' ? ' The charger reports no transaction, so a schedule hold is not shown as the reason.'
      : txn.kind === 'unknown' ? ' Whether a charging transaction exists is not currently known.' : '';
    return done(result('suspended', 'info', 'Charging suspended', `The car or charger has paused charging (suspended). It resumes when either side allows it.${known}`));
  }

  // From here on the connector is Preparing: plugged in, not yet charging.
  if (txn.kind === 'observed') {
    return done(result(waitNote ? 'scheduled_wait' : 'transaction_observed', 'ok',
      waitNote ? 'Authorized — waiting for the schedule' : 'Authorized — waiting for power',
      waitNote ? `The charger reports a charging transaction. ${waitNote} Power flow is not yet measured; ${notPromised.charAt(0).toLowerCase()}${notPromised.slice(1)}` : 'The charger reports a charging transaction; the car has not started drawing measured power yet.'));
  }
  if (!outcome) {
    return done(result('unknown', 'unknown', 'Plugged in — start status unknown', 'SpotNav does not report whether a charge request was made, so whether the car will charge is not known.'));
  }
  if (txn.kind !== 'unmatched') return done(outcome);
  // A transaction number that is not tied to this plug-in never confirms anything and never hides a warning.
  const note = ' The charger also shows a transaction number that cannot be tied to this plug-in, so it is not counted as confirmation.';
  if (outcome.warning) {
    outcome.detail += note; outcome.summary += note;
    return done(outcome);
  }
  if (outcome.kind === 'pending' || outcome.kind === 'accepted_waiting') {
    return done(result('transaction_unmatched', 'info', 'Plugged in — transaction unconfirmed', 'The charger shows a transaction number that cannot be tied to this plug-in. Charging is not confirmed; this clears once the car draws power.'));
  }
  return done(outcome);
}

function startOutcome(state, reason, {age, young, raw, waitNote, txn, guidance, retryPending}) {
  switch (state) {
    case 'starting':
      return result('pending', 'info', 'We’re asking the charger to enable charging', 'The request is being sent. Waiting for the charger to confirm; nothing is confirmed yet.');
    case 'accepted':
      if (reason === 'no_transaction_observed' || (age !== null && !young)) {
        const seen = txn.kind === 'none' ? 'the charger reports no charging transaction' : 'no charging transaction has been confirmed';
        return result('accepted_no_transaction', 'warning', 'The charger said yes, but charging isn’t confirmed',
          `The charger said yes${age !== null ? ` ${ago(age)}` : ''}, yet ${seen}${raw ? ` (still “${raw}”)` : ''}. ${waitNote ? 'The schedule alone does not explain this. ' : ''}A request being accepted is not charging.`, {action: guidance});
      }
      return result('accepted_waiting', 'info', 'We asked the charger to enable charging', 'Waiting for the charger to confirm. It accepted the request, but a transaction usually opens within a few seconds; charging is not confirmed yet.');
    case 'rejected': {
      const retrying = reason === 'request_rejected';
      return result('rejected', 'warning', 'Charger rejected the start request',
        retrying ? 'The charger refused the request. SpotNav retries once after about a minute.' : 'The charger refused the request and SpotNav has stopped trying, so the car will not start charging by itself.',
        {action: retrying ? `The car may not charge yet. ${retryPending}` : guidance});
    }
    case 'blocked': {
      if (FINISHED.has(reason)) return result('session_ended', 'info', 'Previous session ended', 'The car reported its last session as finished. Unplug and plug in again to start a new one.');
      if (reason === 'person_stop_active') return result('paused', 'info', 'Plugged in — stopped', 'A Stop is in progress, so charging is not being started. Resume Auto when you want charging again.');
      if (TRANSIENT.has(reason)) {
        if (young || age === null) return result('pending', 'info', 'Getting ready to ask the charger', 'SpotNav is waiting briefly before it asks the charger to start. It re-checks automatically.');
        return result('start_not_sent', 'warning', 'Charging has not been started', 'SpotNav has not been able to ask the charger to start for a while, so the car may not charge.', {action: 'SpotNav keeps re-checking. If this stays, check the charger connection and the SpotNav logs, or start the charge from the Morek app.'});
      }
      if (reason === 'protection_conflict_unresolved') return result('start_blocked', 'warning', 'Charging start is blocked', 'Another controller or site protection may also limit this charger, so SpotNav does not start it. The car may not charge.', {action: 'Resolve the protection conflict first; SpotNav will not start the charge while it is unresolved. Do not work around it by starting the charge elsewhere.'});
      if (LOGGING.has(reason)) return result('start_blocked', 'warning', 'Charging start is blocked', 'Automatic start is turned off by the charger-logging setup, so the car may not charge.', {action: 'See the SpotNav logs, or start the charge from the Morek app.'});
      return result('start_blocked', 'warning', 'Charging has not been started', 'SpotNav did not start the charge and it will not clear by itself, so the car may not charge.', {action: 'Check the SpotNav logs, or start the charge from the Morek app.'});
    }
    case 'waiting':
    case 'session_observed':
    default:
      if (young || age === null) return result('pending', 'info', 'Plugged in — deciding whether to ask for charging', 'SpotNav has just seen the car and is deciding whether to request charging. Nothing is confirmed yet.');
      return result('start_not_sent', 'warning', 'Plugged in, but charging has not been requested', 'The car is connected and no charge request has been sent for a while, so it may not charge.', {action: 'Unplug and plug in again so SpotNav can retry, or check the SpotNav logs.'});
  }
}
