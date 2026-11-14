// @ts-nocheck
// Stage 15.7a: the sidebar adopts the backend's per-quantity freshness judgement (15.6) and the 15.5 charge-control
// reading for display only. Pure functions, mocked data, no browser.
import { describe, it, expect } from 'vitest';
import { chargeSession } from '../sidebar/charge-session.js';
import { liveCharging } from '../sidebar/live-charging.js';

const NOW = Date.parse('2026-11-14T10:00:00Z');
const iso = ms => new Date(ms).toISOString();
const at = s => iso(NOW - s * 1000);
const reading = (value, ageS = 5, extra = {}) => ({value, observed_at: at(ageS), fresh: ageS <= 180, ...extra});
const norm = {Available: 'disconnected', Preparing: 'connected', Charging: 'charging', SuspendedEVSE: 'paused'};
const judged = (state, ageS) => ({state, basis: 'x', reported_at: at(ageS), age_s: ageS, link: {state: 'up', since: null, connection_id: 1}, reason: 'x'});

// `j` = judgement state per quantity (or `all`); omitted means no freshness block, i.e. an older backend.
function status({raw = 'Preparing', ss = {state: 'accepted', reason: 'request_accepted'}, ssAgeS = 30, ages = {}, j = null, live = {}, ready = {}, extra = {}} = {}) {
  const a = {status: 5, transaction: 5, control_state: 5, ...ages};
  const lv = {connector_id: 1, status: reading(raw, a.status, {normalized: norm[raw]}), transaction: reading(false, a.transaction, {changed_at: null}),
    control_state: reading('off', a.control_state), power_w: null, current_a: null, ...live};
  const r = {control: 'available', session_start: ss, session_start_at: at(ssAgeS), live: lv, ...ready};
  if (j) {
    const q = {};
    const map = {status: 'status', transaction: 'transaction', control_state: 'charging_control', power_w: 'power_w', current_a: 'current_a'};
    for (const [key, name] of Object.entries(map)) if (lv[key]) q[name] = judged(j[key] || j.all || 'current', Math.round((NOW - Date.parse(lv[key].observed_at)) / 1000));
    r.freshness = {expected: null, link: {state: 'up'}, quantities: q};
  }
  return {supported: true, connector_id: 1, verified: false, outcomes: {uncertain: false}, schedule_pause: {intent: 'none'}, readiness: r, ...extra};
}
const run = (s, o = {}) => chargeSession(s, 'at' in o ? o.at : NOW, o.failed ?? false, NOW);
const QUIET = {status: 600, transaction: 600, control_state: 600};
const TXN = {transaction: reading(true, 5, {changed_at: at(10)})};
const OFF = {charging_enabled: {state: 'not_ready', reason: 'control_off'}};

describe('15.7a freshness adoption (display only)', () => {
  it('a quiet connector is current 10 minutes on, but unknown on an older backend', () => {
    expect(run(status({ages: QUIET})).kind).toBe('unknown');
    const r = run(status({ages: QUIET, j: {all: 'current'}}));
    expect(r.kind).toBe('accepted_waiting');
    expect(r.facts.join(' ')).toMatch(/Connector: Preparing \(unchanged since .*too old for automatic actions\)/);
    expect(r.summary).not.toMatch(/10 min ago|stale/i);
  });
  it('a judgement does not override a clock in the future', () => {
    const future = status({j: {all: 'current'}});
    future.readiness.live.status.observed_at = at(-60); future.readiness.freshness.quantities.status.reported_at = at(-60);
    expect(run(future).kind).toBe('unknown');
  });
  it('stale power is not Charging unless the backend adaptive judgement says current', () => {
    const live = {power_w: reading(7400, 400)};
    expect(run(status({raw: 'Charging', live, j: {power_w: 'unknown'}})).kind).toBe('reported_charging');
    expect(run(status({raw: 'Charging', live, j: {power_w: 'idle'}})).kind).toBe('reported_charging');
    expect(run(status({raw: 'Charging', live, j: {power_w: 'current'}})).kind).toBe('charging');
    expect(run(status({raw: 'Charging', live})).kind).toBe('reported_charging');   // older backend: strict bound
    expect(run(status({raw: 'Charging', live: {power_w: reading(0, 5)}, j: {all: 'current'}})).kind).toBe('reported_charging');   // measured 0
  });
  it('a broken link shows last known, never a claim that charging stopped', () => {
    const r = run(status({ages: {status: 900}, j: {status: 'last_known', transaction: 'last_known'}}));
    expect(r).toMatchObject({kind: 'last_known', level: 'unknown', warning: false, posture: 'unknown'});
    expect(r.detail).toMatch(/not known/); expect(r.summary).not.toMatch(/stopped|not charging/i);
  });
  it('offline stays offline, with no claim about charging', () => {
    const r = run(status({ready: {control: 'unavailable'}}));
    expect(r.kind).toBe('offline'); expect(r.summary).not.toMatch(/stopped/i);
  });
  it('an accepted request without a confirmed transaction is pending then at risk, never authorized', () => {
    const early = run(status({ssAgeS: 20}));
    expect(early).toMatchObject({kind: 'accepted_waiting', posture: 'pending', warning: false});
    expect(early.title).toBe('We asked the charger to enable charging');
    expect(early.detail).toMatch(/Waiting for the charger to confirm/);
    expect(early.title).not.toMatch(/Authorized|ready/i);
    expect(run(status({ssAgeS: 400}))).toMatchObject({kind: 'accepted_no_transaction', posture: 'at_risk', warning: true});
  });
  it('posture: authorized needs a transaction, a pause is on purpose, failures are at risk', () => {
    expect(run(status({live: TXN}))).toMatchObject({kind: 'transaction_observed', posture: 'authorized'});
    expect(run(status({ss: {state: 'blocked', reason: 'paused_until_resume'}, extra: {schedule_pause: {intent: 'pause_until_resumed'}}}))).toMatchObject({kind: 'paused', posture: 'waiting_on_purpose'});
    expect(run(status({ss: {state: 'rejected', reason: 'already_requested'}}))).toMatchObject({posture: 'at_risk'});
  });
  it('charge control off or unconfirmed is not yet ready, with who acts', () => {
    const r = run(status({ss: {state: 'blocked', reason: 'charger_unavailable'}, ssAgeS: 10, ready: OFF}));
    expect(r).toMatchObject({kind: 'not_ready', title: 'Not yet ready to charge', posture: 'pending', warning: false});
    expect(r.action).toMatch(/Morek app/);
    expect(r.facts.join(' ')).toMatch(/Charging enabled: switch is off/);
    const unconfirmed = run(status({ss: {state: 'waiting', reason: 'waiting_for_vehicle'}, ssAgeS: 10, ready: {charging_enabled: {state: 'not_ready', reason: 'control_unconfirmed'}}}));
    expect(unconfirmed.kind).toBe('not_ready'); expect(unconfirmed.facts.join(' ')).toMatch(/not confirmed/);
  });
  it('a pending guarded start or an already-asked request says so and needs nobody', () => {
    const asked = run(status({ready: OFF}));
    expect(asked).toMatchObject({kind: 'not_ready', action: ''});
    expect(asked.detail).toBe('We asked the charger to enable charging. Waiting for the charger to confirm.');
    const boot = run(status({ss: {state: 'waiting', reason: 'waiting_for_vehicle'}, ssAgeS: 10, ready: {...OFF, boot_start: {state: 'waiting'}}}));
    expect(boot.detail).toMatch(/once its checks pass/); expect(boot.action).toBe('');
  });
  it('a switch that is on is not authorization, and an off switch outranks an old transaction', () => {
    const on = run(status({ready: {charging_enabled: {state: 'enabled', reason: 'control_on'}}}));
    expect(on).toMatchObject({kind: 'accepted_waiting', posture: 'pending'});
    expect(on.facts.join(' ')).toMatch(/not proof of authorization/);
    expect(run(status({live: TXN, ready: OFF})).kind).toBe('not_ready');
    expect(run(status({live: TXN, ready: {charging_enabled: {state: 'enabled', reason: 'control_on'}}})).kind).toBe('transaction_observed');
    expect(run(status({raw: 'Available', ready: OFF})).kind).toBe('unplugged');
    expect(run(status({ready: {charging_enabled: {state: 'unknown', reason: 'no_evidence'}}})).kind).toBe('accepted_waiting');
  });
  it('switch off with an old transaction and a suspension plus schedule hold is not ready, not a schedule wait', () => {
    const hold = {effective: {fetched_at: at(10), schedule_start: at(60), duration_s: 7200, periods: [{at: at(60), amps: 0}, {at: iso(NOW + 3600000), amps: 16}]}};
    const s = status({raw: 'SuspendedEVSE', live: TXN, ready: OFF, extra: hold});
    s.readiness.live.transaction.changed_at = at(5000);
    const r = run(s);
    expect(r).toMatchObject({kind: 'not_ready', posture: 'pending', warning: false});
    expect(r.summary).not.toMatch(/waiting for the schedule|authorized/i);
    expect(r.detail).toMatch(/switch is off/);
    // the same evidence without the new field keeps the legacy rule
    expect(run(status({raw: 'SuspendedEVSE', live: TXN, extra: hold})).kind).toBe('scheduled_wait');
  });
  it('switch off with fresh measured flow stays Charging, with the conflict flagged and no authorization claim', () => {
    const live = {power_w: reading(7400, 5)};
    const r = run(status({raw: 'Charging', live, ready: OFF}));
    expect(r).toMatchObject({kind: 'charging', conflict: true});
    expect(r.detail).toMatch(/Measured power confirms/); expect(r.detail).toMatch(/switch is off or not confirmed/);
    expect(r.summary).not.toMatch(/authoriz|not charging|stopped/i);
    expect(run(status({raw: 'Charging', live})).conflict).toBe(false);
  });
  it('switch unconfirmed with an old transaction or a reported charge never counts as authorized', () => {
    const unconfirmed = {charging_enabled: {state: 'not_ready', reason: 'control_unconfirmed'}};
    expect(run(status({live: TXN, ready: unconfirmed}))).toMatchObject({kind: 'not_ready', posture: 'pending'});
    const r = run(status({raw: 'Charging', ready: unconfirmed}));
    expect(r.kind).toBe('not_ready'); expect(r.detail).toMatch(/not confirmed/);
    expect(run(status({raw: 'Charging', ready: {charging_enabled: {state: 'enabled', reason: 'control_on'}}})).kind).toBe('reported_charging');
  });
  it('explicit Pause, Stop, fault and an unknown status still outrank the off switch', () => {
    const pause = {schedule_pause: {intent: 'pause_until_resumed'}};
    expect(run(status({raw: 'SuspendedEVSE', live: TXN, ready: OFF, extra: pause})).kind).toBe('paused');
    expect(run(status({raw: 'Charging', ready: OFF, extra: pause})).kind).toBe('reported_charging');
    expect(run(status({ss: {state: 'blocked', reason: 'person_stop_active'}, ready: OFF})).kind).toBe('paused');
    const fault = status({ready: OFF}); fault.readiness.live.status.normalized = 'error';
    expect(run(fault).kind).toBe('fault');
    expect(run(status({ages: {status: 9999}, ready: OFF})).kind).toBe('unknown');
  });
  it('a lasting failure keeps its warning and gains the switch note', () => {
    const risk = run(status({ss: {state: 'rejected', reason: 'already_requested'}, ready: OFF}));
    expect(risk).toMatchObject({kind: 'rejected', warning: true}); expect(risk.detail).toMatch(/switch is also off/);
  });
  it('a missing, disabled or unavailable control cannot start or schedule charging', () => {
    const r = run(status({ready: {charging_enabled: {state: 'not_ready', reason: 'control_unavailable'}}}));
    expect(r).toMatchObject({kind: 'control_unavailable', warning: true, posture: 'at_risk'});
    expect(r.title).toMatch(/can’t be started or scheduled/); expect(r.action).toMatch(/^You:/);
  });
  it('malformed judgements and charge-control values fail closed', () => {
    const bad = [
      s => { s.readiness.freshness = 'current'; },
      s => { s.readiness.freshness = {quantities: []}; },
      s => { s.readiness.freshness = {quantities: {}}; },
      s => { s.readiness.freshness.quantities.status.state = 'fresh'; },
      s => { s.readiness.freshness.quantities.status.reported_at = at(9999); },
      s => { s.readiness.freshness.quantities.status.reported_at = 'nonsense'; },
      s => { s.readiness.freshness.quantities.status.age_s = -4; },
      s => { s.readiness.freshness.quantities.status.age_s = '4'; },
      s => { delete s.readiness.freshness.quantities.status; },
    ];
    for (const mutate of bad) {
      const s = status({ages: QUIET, j: {all: 'current'}}); mutate(s);
      expect(run(s).kind).toBe('unknown');
    }
    for (const value of ['on', 5, [], {state: 'enabled'}, {state: 'enabled', reason: 'control_off'}, {state: 'weird'}]) {
      expect(run(status({ready: {charging_enabled: value}})).kind).toBe('not_ready');
    }
  });
  it('a failed or old payload refresh is unknown even if every judgement says current', () => {
    const s = status({j: {all: 'current'}});
    expect(run(s, {failed: true}).kind).toBe('unknown');
    expect(run(s, {at: NOW - 10 * 60000}).kind).toBe('unknown');
    expect(run(s, {at: null}).kind).toBe('unknown');
  });
  it('a stale transaction judgement is not evidence of a transaction', () => {
    const s = status({live: {transaction: reading(true, 600, {changed_at: at(590)})}, ages: {transaction: 600}, j: {transaction: 'unknown'}, ssAgeS: 400});
    expect(run(s).kind).toBe('accepted_no_transaction');
  });
  it('rendering never mutates the status', () => {
    const s = status({ages: QUIET, j: {all: 'current'}, ready: OFF});
    const before = JSON.stringify(s); run(s); expect(JSON.stringify(s)).toBe(before);
  });
});

describe('15.7a live charging uses the same judgement', () => {
  const live = s => liveCharging(s, NOW, false, NOW);
  const withPower = (j, ageS = 400) => status({live: {power_w: reading(7400, ageS)}, j: {power_w: j}});
  it('quiet status is current; silent power is unknown, not zero', () => {
    const quiet = live(status({ages: QUIET, j: {all: 'current'}}));
    expect(quiet.summary).toMatch(/Charger reports “Preparing” for connector 1, unchanged since/);
    expect(quiet.reported).toBe('Preparing');
    expect(live(status({ages: QUIET})).reported).toBeNull();   // older backend: strict bound
    expect(live(withPower('unknown'))).toMatchObject({power: 'Unknown', measured: null});
    const idle = live(withPower('idle'));
    expect(idle.power).toBe('Unknown'); expect(idle.summary).toMatch(/no reading is expected/);
    expect(live(withPower('current')).power).toBe('7.4 kW measured');
  });
  it('last known after a link break is not current; a malformed judgement is unknown', () => {
    const r = live(status({ages: {status: 900}, j: {status: 'last_known'}}));
    expect(r.reported).toBeNull(); expect(r.summary).toMatch(/last known .*not confirmed now/);
    const s = status({j: {all: 'current'}}); s.readiness.freshness = {quantities: {status: {state: 'current'}}};
    expect(live(s).reported).toBeNull();
  });
});
