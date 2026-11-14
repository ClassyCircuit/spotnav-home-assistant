// Stage 15.7b: the secondary "schedule check / link / reboot" notes under the charging status.
//
// Pure and read-only: decoded Morek status plus a clock, nothing is sent, requested or inferred here. These notes
// are deliberately a SEPARATE, subdued line from the primary charging state (charge-session.js). A matching
// schedule readback or an accepted repair says what the charger's schedule looks like; it never says the car is
// charging, and it never hides a Pause, Stop, fault, uncertain write or offline state shown above it.
// Every field is optional and untrusted: a malformed, future-dated or too old value is "not known", never a
// reassurance, and an older backend that sends none of them simply shows nothing.
const CLOCK_SKEW_MS = 5000;
const MAX_CHECK_AGE_MS = 86400000;   // a check older than a day is not a current statement
const CLASSES = new Set(['healthy', 'unknown', 'differs_unconfirmed', 'differs_confirmed']);
const LINK_STATES = new Set(['up', 'down', 'unknown']);
const BOOT_STATES = new Set(['none', 'unknown', 'waiting', 'requested', 'blocked', 'closed']);

const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const clock = ms => new Date(ms).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
/** A timestamp as epoch ms, or null when absent, unparseable or in the future. */
const stamp = (value, now) => {
  const ms = typeof value === 'string' ? Date.parse(value) : NaN;
  return Number.isFinite(ms) && Number.isFinite(now) && ms <= now + CLOCK_SKEW_MS ? ms : null;
};

/** @returns {{state: 'up'|'down'|'unknown', since: number|null}} the charger link as the backend monitor reports it. */
export function linkInfo(status, now) {
  const link = status?.link;
  if (!isObject(link) || !LINK_STATES.has(link.state)) return {state: 'unknown', since: null};
  return {state: link.state, since: stamp(link.since, now)};
}

const BOOT_BLOCKED = {
  transaction_present: 'the charger already reports a charging session',
  transaction_unknown: 'the charger has not said whether a session is open',
  transaction_not_reported_after_boot: 'the charger has not reported its session since restarting',
};

function checkItem(status, now, link, facts) {
  const reconciliation = status?.reconciliation;
  if (!isObject(reconciliation) || reconciliation.check === undefined || reconciliation.check === null) return null;
  const check = reconciliation.check;
  const unknown = text => ({kind: 'check_unknown', level: 'info', text});
  if (!isObject(check)) return unknown('The schedule check result isn’t readable, so it isn’t known whether the charger’s schedule matches.');
  if (check.class === null || check.class === undefined) return null;   // never checked yet: nothing to say
  const at = stamp(check.at, now);
  if (!CLASSES.has(check.class) || at === null) return unknown('The schedule check result isn’t readable, so it isn’t known whether the charger’s schedule matches.');
  facts.push(`Schedule check: ${check.class}${typeof check.reason === 'string' ? ` (${check.reason})` : ''} at ${clock(at)}`);
  if (Number.isFinite(check.rechecks) && check.rechecks > 0) facts.push(`Re-checks in this episode: ${check.rechecks}`);
  if (now - at > MAX_CHECK_AGE_MS) return unknown('The last schedule check was over a day ago, so it says nothing about the charger’s schedule now.');
  const events = Array.isArray(check.events) ? check.events : [];
  const last = events[events.length - 1];
  const afterRepair = isObject(last) && last.trigger === 'post_repair' && last.class === check.class;
  const t = clock(at);
  const repair = isObject(reconciliation.repair) ? reconciliation.repair : {};
  const blocker = isObject(reconciliation.blocker) ? reconciliation.blocker.code : null;
  switch (check.class) {
    case 'healthy':
      facts.push('A matching schedule is not proof that the car is charging.');
      if (link.state === 'down' && link.since !== null && link.since > at) {
        return {kind: 'check_healthy_stale', level: 'info', text: `Checked at ${t}, before the connection was lost. SpotNav checks again when the charger reconnects.`};
      }
      return afterRepair
        ? {kind: 'check_repaired', level: 'info', text: `SpotNav re-sent the schedule and checked it at ${t}: it now matches the plan. That doesn’t prove the car is charging.`}
        : {kind: 'check_healthy', level: 'info', text: `Checked at ${t}, nothing needed changing.`};
    case 'differs_unconfirmed':
      return {kind: 'check_rechecking', level: 'info', text: 'Checking again: one odd reading isn’t enough to act on.'};
    case 'differs_confirmed':
      if (repair.needs_person === true || blocker === 'repair_needs_person') {
        return {kind: 'check_needs_person', level: 'warning', text: 'The charger’s schedule still doesn’t match and automatic repair is paused for this attempt. Check the charger and the SpotNav logs.'};
      }
      if (blocker === 'repair_deferred') return {kind: 'check_deferred', level: 'info', text: 'The charger’s schedule differs a little. The current charge is left alone; SpotNav fixes it a bit later.'};
      if (blocker === 'repair_spacing') return {kind: 'check_spacing', level: 'info', text: 'The charger’s schedule differs. SpotNav already fixed it recently, so it waits before sending again.'};
      if (repair.gate_enabled === false) return {kind: 'check_gated', level: 'info', text: 'The charger’s schedule differs from the plan. Automatic repair is off, so nothing was sent.'};
      return {kind: 'check_differs', level: 'info', text: 'The charger’s schedule differs from the plan. SpotNav corrects it by itself when that is safe.'};
    default:   // 'unknown'
      if (check.reason === 'verification_pending' || check.reason === 'upload_pending') {
        return {kind: 'check_waiting', level: 'info', text: afterRepair || check.reason === 'verification_pending'
          ? 'Waiting for the charger’s new schedule to settle before checking it.' : 'Waiting for the schedule to be sent before checking it.'};
      }
      return {kind: 'check_unknown', level: 'info', text: `Couldn’t check the charger’s schedule at ${t}.`};
  }
}

function bootItem(status, now, facts) {
  const boot = status?.readiness?.boot_start;
  if (boot === undefined || boot === null) return null;
  if (!isObject(boot) || !BOOT_STATES.has(boot.state)) return null;
  const at = stamp(boot.at, now);
  const reason = typeof boot.reason === 'string' ? boot.reason : '';
  if (boot.state !== 'none' && boot.state !== 'unknown') facts.push(`Charger restart: ${boot.state}${reason ? ` (${reason})` : ''}${at !== null ? ` at ${clock(at)}` : ''}`);
  if (at === null) return null;   // an undated restart claim is not explained to the user
  const t = clock(at);
  if (boot.state === 'requested') {
    // boot_start.requested is an intent token minted BEFORE the request is made; it is not evidence that anything was
    // asked. Only the start-request ledger (readiness.session_start), dated at or after the restart, says what was sent.
    const ready = status.readiness;
    const ssAt = stamp(ready.session_start_at, now);
    const ss = isObject(ready.session_start) ? ready.session_start : {};
    if (ssAt === null || ssAt < at || typeof ss.state !== 'string') {
      return {kind: 'boot_pending', level: 'info', text: `The charger restarted at ${t}. Restart recovery is pending and unconfirmed: it isn’t known whether SpotNav has asked the charger to enable charging since then.`};
    }
    facts.push(`Start request after restart: ${ss.state}${typeof ss.reason === 'string' ? ` (${ss.reason})` : ''} at ${clock(ssAt)}`);
    if (ss.state === 'accepted') {
      return {kind: 'boot_requested', level: 'info', text: `The charger restarted at ${t}. SpotNav asked it to enable charging at ${clock(ssAt)} and the charger accepted the request. Only the charger can confirm that charging started.`};
    }
    if (ss.state === 'starting') return {kind: 'boot_asking', level: 'info', text: `The charger restarted at ${t}. SpotNav is asking it to enable charging now.`};
    if (ss.state === 'blocked' || ss.state === 'rejected') {
      return {kind: 'boot_withheld', level: 'warning', text: `The charger restarted at ${t}, but the request to enable charging was withheld or refused. Check the charger and the SpotNav logs for the reason before trying again.`};
    }
    return {kind: 'boot_unknown', level: 'info', text: `The charger restarted at ${t}. Whether the request to enable charging reached it isn’t known.`};
  }
  if (boot.state === 'waiting') return {kind: 'boot_waiting', level: 'info', text: `The charger restarted at ${t}. SpotNav is waiting for its reports before asking it to enable charging.`};
  if (boot.state === 'blocked') {
    const why = BOOT_BLOCKED[reason] || 'its reports do not show it is safe to ask';
    return {kind: 'boot_blocked', level: 'warning', text: `The charger restarted at ${t}, but ${why}, so SpotNav did not ask it to charge. Check the charger and the SpotNav logs for the reason before trying again.`};
  }
  return null;
}

/**
 * @returns {null | {items: {kind: string, level: 'info'|'warning', text: string}[], facts: string[]}}
 * null when the backend offers nothing here (older backend, unsupported charger). Never returns an 'ok' level.
 */
export function scheduleNotes(status, now = Date.now()) {
  if (!status || status.supported === false) return null;
  const facts = [];
  const link = linkInfo(status, now);
  if (link.state !== 'unknown') facts.push(`Link to the charger: ${link.state === 'up' ? 'up' : 'down'}${link.since !== null ? ` since ${clock(link.since)}` : ''}`);
  const items = [];
  const check = checkItem(status, now, link, facts);
  if (check) items.push(check);
  const boot = bootItem(status, now, facts);
  if (boot) items.push(boot);
  if (link.state === 'down') {
    items.push({kind: 'link_lost', level: 'info', text: `Connection lost${link.since !== null ? ` at ${clock(link.since)}` : ''}. SpotNav checks the schedule again when the charger reconnects.`});
  } else if (!items.length && link.state === 'up' && link.since !== null) {
    items.push({kind: 'link_quiet', level: 'info', text: `Link to the charger unchanged since ${clock(link.since)}.`});
  }
  return items.length ? {items, facts} : null;
}
