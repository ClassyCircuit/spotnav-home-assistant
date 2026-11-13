// @ts-nocheck
// Charge-session authorization/transaction status: every state, grace, stale data and the no-false-claim rules.
import { describe, it, expect } from 'vitest';
import { chargeSession, scheduleLimit, GRACE_MS } from '../sidebar/charge-session.js';

const NOW = Date.parse('2026-11-13T10:00:00Z');
const iso = ms => new Date(ms).toISOString();
const reading = (value, extra = {}, ageS = 5) => ({value, observed_at: iso(NOW - ageS * 1000), fresh: ageS <= 180, ...extra});

// A fresh status: connector `raw` (normalized from it), session request `ss` last changed `ssAgeS` ago.
function status({raw = 'Preparing', ss = {state: 'waiting', reason: 'waiting_for_vehicle'}, ssAgeS = 10, live = {}, extra = {}, control} = {}) {
  const norm = {Available: 'disconnected', Preparing: 'connected', Charging: 'charging', SuspendedEV: 'paused', SuspendedEVSE: 'paused', Finishing: 'finished', Faulted: 'error'}[raw] ?? 'unknown';
  return {supported: true, verified: false, outcomes: {uncertain: false}, schedule_pause: {intent: 'none'},
    readiness: {control: control ?? 'available', session_start: ss, session_start_at: iso(NOW - ssAgeS * 1000),
      live: {connector_id: 1, status: raw === null ? null : reading(raw, {normalized: norm}), power_w: null, current_a: null,
        control_state: reading('off', {}), transaction: reading(false, {changed_at: null}), ...live}}, ...extra};
}
const run = (s, o = {}) => chargeSession(s, 'at' in o ? o.at : NOW, o.failed ?? false, o.now ?? NOW);
const OLD = GRACE_MS / 1000 + 30;

describe('chargeSession: no false alarm and no false success', () => {
  it('is hidden for an unsupported charger and unknown when status is stale, failed or missing', () => {
    expect(run({supported: false})).toBeNull();
    for (const r of [run(null), run(status(), {at: NOW - 10 * 60000}), run(status(), {failed: true}), run(status(), {at: null})]) {
      expect(r.kind).toBe('unknown'); expect(r.warning).toBe(false);
    }
    expect(run(status({raw: null}))).toMatchObject({kind: 'unknown', warning: false});
    expect(run(status({raw: 'Unavailable'}))).toMatchObject({kind: 'unknown', warning: false});
    const old = status(); old.readiness.live.status = reading('Preparing', {normalized: 'connected'}, 400);
    expect(run(old)).toMatchObject({kind: 'unknown', warning: false});
  });
  it('unplugged is calm even if an old request state is left over', () => {
    const r = run(status({raw: 'Available', ss: {state: 'accepted', reason: 'no_transaction_observed'}, ssAgeS: OLD}));
    expect(r).toMatchObject({kind: 'unplugged', level: 'info', warning: false});
  });
  it('offline and charger fault', () => {
    expect(run(status({control: 'unavailable'}))).toMatchObject({kind: 'offline', warning: true});
    expect(run(status({ss: {state: 'offline', reason: 'charger_offline'}}))).toMatchObject({kind: 'offline'});
    expect(run(status({raw: 'Faulted'}))).toMatchObject({kind: 'fault', level: 'error'});
  });
  it('transient and grace states raise no warning, then warn once they last', () => {
    for (const ss of [{state: 'waiting', reason: 'waiting_for_vehicle'}, {state: 'blocked', reason: 'charger_unavailable'}, {state: 'blocked', reason: 'lifecycle_initializing'}, {state: 'waiting', reason: 'retry_cooldown'}]) {
      const early = run(status({ss, ssAgeS: 20}));
      expect(early.kind).toBe('pending'); expect(early.warning).toBe(false);
    }
    expect(run(status({ss: {state: 'starting', reason: 'request_in_progress'}, ssAgeS: 3}))).toMatchObject({kind: 'pending', warning: false});
    expect(run(status({ss: {state: 'blocked', reason: 'charger_unavailable'}, ssAgeS: OLD}))).toMatchObject({kind: 'start_not_sent', level: 'warning'});
    expect(run(status({ss: {state: 'waiting', reason: 'waiting_for_vehicle'}, ssAgeS: OLD}))).toMatchObject({kind: 'start_not_sent', warning: true});
    const noTime = status({ss: {state: 'blocked', reason: 'charger_unavailable'}}); delete noTime.readiness.session_start_at;
    expect(run(noTime)).toMatchObject({kind: 'pending', warning: false});   // no timestamp, no time-based alarm
  });
  it('accepted: waiting inside the grace, a prominent warning after it; never a transaction or charging claim', () => {
    const accepted = {state: 'accepted', reason: 'request_accepted'};
    const waiting = run(status({ss: accepted, ssAgeS: 30}));
    expect(waiting).toMatchObject({kind: 'accepted_waiting', level: 'info', warning: false});
    expect(waiting.summary).toMatch(/not confirmed/i); expect(waiting.title).not.toMatch(/^Charging$/);
    const flagged = run(status({ss: {state: 'accepted', reason: 'no_transaction_observed'}, ssAgeS: 5}));
    expect(flagged).toMatchObject({kind: 'accepted_no_transaction', level: 'warning', warning: true});
    expect(flagged.action).toMatch(/Morek app|unplug/i);
    expect(flagged.detail).toMatch(/not charging/i);
    expect(run(status({ss: accepted, ssAgeS: OLD})).kind).toBe('accepted_no_transaction');
    const held = status({ss: {state: 'accepted', reason: 'no_transaction_observed'}, extra: {effective: {periods: [{at: iso(NOW - 3600e3), amps: 0}, {at: iso(NOW + 3600e3), amps: 16}], fetched_at: iso(NOW)}}});
    expect(run(held).kind).toBe('accepted_no_transaction');   // a scheduled hold does not excuse a missing transaction
  });
  it('rejected, uncertain and blocked requests', () => {
    expect(run(status({ss: {state: 'rejected', reason: 'request_rejected'}}))).toMatchObject({kind: 'rejected', warning: true});
    expect(run(status({ss: {state: 'rejected', reason: 'already_requested'}})).detail).toMatch(/stopped trying/);
    expect(run(status({ss: {state: 'uncertain', reason: 'previous_start_may_have_applied'}}))).toMatchObject({kind: 'uncertain', level: 'error'});
    expect(run(status({extra: {outcomes: {uncertain: true}}}))).toMatchObject({kind: 'uncertain'});
    expect(run(status({ss: {state: 'blocked', reason: 'protection_conflict_unresolved'}}))).toMatchObject({kind: 'start_blocked', warning: true});
    expect(run(status({ss: {state: 'blocked', reason: 'ocpp_sensitive_logging_enabled'}}))).toMatchObject({kind: 'start_blocked'});
    expect(run(status({ss: {state: 'blocked', reason: 'something_new'}}))).toMatchObject({kind: 'start_blocked', warning: true});
    expect(run(status({ss: {state: 'blocked', reason: 'session_completed'}, ssAgeS: OLD}))).toMatchObject({kind: 'session_ended', warning: false});
  });
  it('Pause and Stop are informational, not faults', () => {
    const pausedByIntent = status({ss: {state: 'blocked', reason: 'paused_until_resume'}, ssAgeS: OLD, extra: {schedule_pause: {intent: 'pause_until_resumed'}}});
    expect(run(pausedByIntent)).toMatchObject({kind: 'paused', level: 'info', warning: false});
    expect(run(status({ss: {state: 'blocked', reason: 'legacy_pause_active'}, ssAgeS: OLD})).kind).toBe('paused');
    expect(run(status({ss: {state: 'blocked', reason: 'person_stop_active'}, ssAgeS: OLD})).kind).toBe('paused');
  });
  it('the unarmed/old backend default is unknown, never an alarm', () => {
    const r = run(status({ss: {state: 'blocked', reason: 'authorization_path_unimplemented'}, ssAgeS: OLD}));
    expect(r).toMatchObject({kind: 'unknown', warning: false});
  });
  it('confirmed observed transaction; a leftover id in Preparing is not tied to this plug-in', () => {
    const observed = run(status({ss: {state: 'accepted', reason: 'request_accepted'}, ssAgeS: 40,
      live: {transaction: reading(true, {changed_at: iso(NOW - 20000)})}}));
    expect(observed).toMatchObject({kind: 'transaction_observed', level: 'ok', warning: false});
    expect(observed.detail).toMatch(/not started drawing measured power|not yet measured/);
    const leftover = run(status({ss: {state: 'accepted', reason: 'no_transaction_observed'}, ssAgeS: OLD,
      live: {transaction: reading(true, {changed_at: iso(NOW - 3600e3)})}}));
    expect(leftover).toMatchObject({kind: 'accepted_no_transaction', warning: true});   // unmatched never hides the warning
    expect(leftover.detail).toMatch(/cannot be tied to this plug-in/);
    expect(leftover.title).not.toMatch(/Authorized/);
    const early = run(status({ss: {state: 'accepted', reason: 'request_accepted'}, ssAgeS: 30, live: {transaction: reading(true, {changed_at: iso(NOW - 3600e3)})}}));
    expect(early).toMatchObject({kind: 'transaction_unmatched', warning: false});
    const stale = status({ss: {state: 'accepted', reason: 'no_transaction_observed'}, live: {transaction: reading(true, {changed_at: iso(NOW - 1000)}, 500)}});
    expect(run(stale).kind).toBe('accepted_no_transaction');   // stale transaction evidence is ignored
    expect(run(status({raw: 'SuspendedEV', live: {transaction: reading(true, {changed_at: iso(NOW - 3600e3)})}})).kind).toBe('suspended');
  });
  it('normal scheduled wait is calm, with the next start', () => {
    const schedule = {effective: {periods: [{at: iso(NOW - 3600e3), amps: 0}, {at: iso(NOW + 2 * 3600e3), amps: 16}], fetched_at: iso(NOW)}};
    const r = run(status({ss: {state: 'accepted', reason: 'request_accepted'}, ssAgeS: 600,
      live: {transaction: reading(true, {changed_at: iso(NOW - 500000)})}, extra: schedule}));
    expect(r).toMatchObject({kind: 'scheduled_wait', level: 'ok', warning: false});
    expect(r.detail).toMatch(/holds charging back until about/);
    expect(r.detail).toMatch(/not guaranteed/); expect(r.detail).not.toMatch(/Power starts/);
    const live = {transaction: reading(true, {changed_at: iso(NOW - 500000)})};
    expect(run(status({raw: 'SuspendedEVSE', extra: schedule, live}))).toMatchObject({kind: 'scheduled_wait', warning: false});
    expect(run(status({raw: 'SuspendedEV'})).kind).toBe('suspended');
  });
  it('measured power is the only thing that says Charging; reported Charging alone says so honestly', () => {
    expect(run(status({raw: 'Charging', live: {power_w: reading(7400)}}))).toMatchObject({kind: 'charging', level: 'ok'});
    expect(run(status({raw: 'Charging', live: {current_a: reading(15.8)}})).kind).toBe('charging');
    const reportedOnly = run(status({raw: 'Charging'}));
    expect(reportedOnly).toMatchObject({kind: 'reported_charging', level: 'info', warning: false});
    expect(reportedOnly.title).not.toBe('Charging');
    expect(run(status({raw: 'Charging', live: {power_w: reading(7400, {}, 400)}})).kind).toBe('reported_charging');   // stale
    expect(run(status({raw: 'Charging', live: {power_w: reading(0)}})).kind).toBe('reported_charging');               // measured zero
    expect(run(status({raw: 'Preparing', live: {power_w: reading(5000)}})).detail).toMatch(/charger reports “Preparing”/);
    expect(run(status({raw: 'Finishing'})).kind).toBe('finished');
  });
  it('never exposes a raw code or identifier and does not mislabel the off switch as a fault', () => {
    const r = run(status({ss: {state: 'accepted', reason: 'no_transaction_observed'}}));
    expect(JSON.stringify([r.title, r.detail, r.action, r.facts])).not.toMatch(/no_transaction_observed|connector_id|[0-9a-f]{32}/);
    expect(r.facts.join(' ')).toMatch(/Charge-control switch: off \(normal before authorization\)/);
    expect(r.facts.join(' ')).toMatch(/Transaction: none reported/);
  });
});

describe('scheduleLimit', () => {
  it('reads the effective readback, falls back to an accepted sent schedule, and is unknown past coverage', () => {
    expect(scheduleLimit({effective: {fetched_at: iso(NOW - 1000), periods: [{at: iso(NOW - 1000), amps: 16}]}}, NOW)).toMatchObject({amps: 16, source: 'readback'});
    const sent = {ack: 'Accepted', sent_at: iso(NOW - 3600e3), sent: {chargingSchedule: {startSchedule: iso(NOW - 3600e3), duration: 86400, chargingSchedulePeriod: [{startPeriod: 0, limit: 0}, {startPeriod: 7200, limit: 16}]}}};
    expect(scheduleLimit(sent, NOW)).toMatchObject({amps: 0, source: 'sent', nextStart: NOW + 3600e3});
    expect(scheduleLimit({...sent, ack: null}, NOW)).toBeNull();
    expect(scheduleLimit({effective: {fetched_at: iso(NOW), periods: [{at: iso(NOW - 9e6), amps: 0}], schedule_start: iso(NOW - 9e6), duration_s: 60}}, NOW)).toBeNull();
    expect(scheduleLimit({}, NOW)).toBeNull();
  });
});

describe('evidence required before claiming a scheduled wait or readiness', () => {
  const periods = [{at: iso(NOW - 3600e3), amps: 0}, {at: iso(NOW + 3600e3), amps: 16}];
  const sentPlan = {chargingSchedule: {startSchedule: iso(NOW - 3600e3), duration: 86400, chargingSchedulePeriod: [{startPeriod: 0, limit: 0}, {startPeriod: 7200, limit: 16}]}};
  const observedTxn = {transaction: reading(true, {changed_at: iso(NOW - 500000)})};
  const all = r => JSON.stringify([r.title, r.detail, r.action]);

  it('paused connector without a fresh transaction is only "suspended", never a schedule promise', () => {
    const eff = {effective: {periods, fetched_at: iso(NOW)}};
    for (const live of [{}, {transaction: reading(true, {}, 500)}, {transaction: null}]) {
      const r = run(status({raw: 'SuspendedEV', extra: eff, live}));
      expect(r.kind).toBe('suspended'); expect(all(r)).not.toMatch(/Power starts|waiting for the schedule/);
    }
    expect(run(status({raw: 'SuspendedEV', extra: eff})).detail).toMatch(/reports no transaction/);
    const unknown = run(status({raw: 'SuspendedEV', extra: eff, live: {transaction: null}}));
    expect(unknown.detail).toMatch(/not currently known/); expect(unknown.detail).not.toMatch(/no transaction/);
    expect(run(status({raw: 'SuspendedEV', extra: eff, live: observedTxn})).kind).toBe('scheduled_wait');
  });
  it('a stale readback is not used; an accepted sent plan is labelled planned, not proof', () => {
    const stale = {effective: {periods, fetched_at: iso(NOW - 600e3)}};
    expect(run(status({raw: 'SuspendedEV', extra: stale, live: observedTxn})).kind).toBe('suspended');
    const planned = run(status({raw: 'SuspendedEV', live: observedTxn, extra: {ack: 'Accepted', sent_at: iso(NOW - 3600e3), sent: sentPlan}}));
    expect(planned.kind).toBe('scheduled_wait');
    expect(planned.detail).toMatch(/plan sent to the charger.*not confirmed by a readback/); expect(planned.detail).not.toMatch(/Power starts/);
  });
  it('old, unstamped, rejected, superseded or expired ACKs are not schedule evidence', () => {
    const base = {ack: 'Accepted', sent_at: iso(NOW - 3600e3), sent: sentPlan};
    expect(scheduleLimit(base, NOW)).toMatchObject({source: 'sent'});
    expect(scheduleLimit({...base, sent_at: null}, NOW)).toBeNull();
    expect(scheduleLimit({...base, ack: 'Rejected'}, NOW)).toBeNull();
    expect(scheduleLimit({...base, ack: 'NotAccepted'}, NOW)).toBeNull();
    expect(scheduleLimit({...base, verification: {reason: 'limits_or_transitions_differ'}}, NOW)).toBeNull();
    expect(scheduleLimit(base, NOW + 90000e3)).toBeNull();
    const noSpan = JSON.parse(JSON.stringify(base)); delete noSpan.sent.chargingSchedule.duration;
    expect(scheduleLimit(noSpan, NOW)).toBeNull();
    expect(scheduleLimit({effective: {periods}, ack: null}, NOW)).toBeNull();   // unstamped readback
  });
  it('Preparing with a stale hold and an observed transaction does not claim a schedule wait', () => {
    const r = run(status({ssAgeS: 40, live: {transaction: reading(true, {changed_at: iso(NOW - 2000)})}, extra: {effective: {periods, fetched_at: iso(NOW - 600e3)}}}));
    expect(r.kind).toBe('transaction_observed');
    expect(r.detail).not.toMatch(/holds charging back/);
  });
  it('an unmatched transaction never hides a rejection, a timeout or a block', () => {
    const leftover = {transaction: reading(true, {changed_at: iso(NOW - 3600e3)})};
    for (const [ss, kind] of [[{state: 'rejected', reason: 'already_requested'}, 'rejected'], [{state: 'rejected', reason: 'request_rejected'}, 'rejected'],
      [{state: 'accepted', reason: 'request_accepted'}, 'accepted_no_transaction'], [{state: 'blocked', reason: 'protection_conflict_unresolved'}, 'start_blocked'],
      [{state: 'blocked', reason: 'charger_unavailable'}, 'start_not_sent']]) {
      const r = run(status({ss, ssAgeS: OLD, live: leftover}));
      expect(r).toMatchObject({kind, warning: true}); expect(r.detail).toMatch(/cannot be tied to this plug-in/);
    }
  });
  it('unknown transaction sensor never reads as definite absence', () => {
    const r = run(status({ss: {state: 'accepted', reason: 'no_transaction_observed'}, live: {transaction: null}}));
    expect(r.kind).toBe('accepted_no_transaction');
    expect(all(r)).not.toMatch(/no charging transaction has appeared|reports no/); expect(r.detail).toMatch(/has been confirmed/);
    expect(r.facts.join(' ')).toMatch(/Transaction: unknown/);
    expect(run(status({ss: {state: 'accepted', reason: 'no_transaction_observed'}})).detail).toMatch(/reports no charging transaction/);
  });
  it('protection conflict says to resolve it, and does not suggest starting elsewhere', () => {
    const r = run(status({ss: {state: 'blocked', reason: 'protection_conflict_unresolved'}}));
    expect(r.action).toMatch(/Resolve the protection conflict/); expect(r.action).not.toMatch(/from the Morek app/i);
  });
  it('retry wording matches the real retry state', () => {
    const pending = run(status({ss: {state: 'rejected', reason: 'request_rejected'}}));
    expect(pending.action).toMatch(/retry once by itself/); expect(pending.action).not.toMatch(/will not repeat/);
    const final = run(status({ss: {state: 'rejected', reason: 'already_requested'}}));
    expect(final.action).toMatch(/will not repeat the request on its own/); expect(final.action).not.toMatch(/retry once/);
    const notSent = run(status({ss: {state: 'waiting', reason: 'waiting_for_vehicle'}, ssAgeS: OLD}));
    expect(notSent.action).not.toMatch(/will not repeat/);
  });
});
