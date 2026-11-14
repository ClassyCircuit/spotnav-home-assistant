// @vitest-environment jsdom
// @ts-nocheck
// Stage 15.7b: schedule check / repair / reboot / connection wording and the recovery-banner mapping.
// Pure functions and the mocked panel renderer only: no browser, no HA, nothing is sent.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { scheduleNotes, linkInfo } from '../sidebar/schedule-check.js';
import { recoveryBanner } from '../sidebar/recovery-banner.js';
import { chargeSession } from '../sidebar/charge-session.js';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

const NOW = Date.parse('2026-11-14T10:00:00Z');
const at = s => new Date(NOW - s * 1000).toISOString();
const REPAIR_OK = {gate_enabled: true, needs_person: false, budget: {state: 'ok', used: 0, limit: 2, next_at: null}};
const st = (check, extra = {}, repair = REPAIR_OK, blocker = null) =>
  ({supported: true, verified: false, reconciliation: {reason: 'x', blocker, check, repair, recovery: {}}, ...extra});
const check = (cls, extra = {}) => ({class: cls, at: at(60), readback_at: at(61), reason: 'ok', rechecks: 0, events: [], ...extra});
const text = s => (scheduleNotes(s, NOW)?.items || []).map(i => i.text).join(' | ');
const kind = s => scheduleNotes(s, NOW)?.items[0]?.kind;

describe('15.7b schedule check wording', () => {
  it('healthy: checked at time, nothing needed changing, no charging claim', () => {
    const r = scheduleNotes(st(check('healthy')), NOW);
    expect(r.items[0]).toMatchObject({kind: 'check_healthy', level: 'info'});
    expect(r.items[0].text).toMatch(/^Checked at .*nothing needed changing\.$/);
    expect(r.items.every(i => i.level !== 'ok')).toBe(true);
    expect(r.items[0].text).not.toMatch(/charging|ready/i);
    expect(r.facts.join(' ')).toMatch(/not proof that the car is charging/);
  });
  it('unknown: couldn’t check, or waiting for the schedule to settle', () => {
    const u = text(st(check('unknown', {reason: 'readback_unavailable'})));
    expect(u).toMatch(/Couldn’t check the charger’s schedule at /);
    expect(u).not.toMatch(/try again|retry|will check/i);
    expect(kind(st(check('unknown', {reason: 'verification_pending'})))).toBe('check_waiting');
    expect(kind(st(check('unknown', {reason: 'upload_pending'})))).toBe('check_waiting');
  });
  it('one odd reading is only a recheck, never a repair', () => {
    expect(text(st(check('differs_unconfirmed', {rechecks: 1})))).toMatch(/one odd reading isn’t enough to act on/);
    expect(kind(st(check('differs_unconfirmed')))).toBe('check_rechecking');
  });
  it('confirmed difference: corrected when safe, deferred, spaced, gated, or needs a person', () => {
    expect(kind(st(check('differs_confirmed')))).toBe('check_differs');
    expect(kind(st(check('differs_confirmed'), {}, REPAIR_OK, {code: 'repair_deferred', action: 'wait_for_repair_deferral'}))).toBe('check_deferred');
    expect(text(st(check('differs_confirmed'), {}, REPAIR_OK, {code: 'repair_deferred', action: 'x'}))).toMatch(/current charge is left alone/);
    expect(kind(st(check('differs_confirmed'), {}, REPAIR_OK, {code: 'repair_spacing', action: 'x'}))).toBe('check_spacing');
    expect(kind(st(check('differs_confirmed'), {}, {gate_enabled: false}))).toBe('check_gated');
    const person = scheduleNotes(st(check('differs_confirmed'), {}, {needs_person: true}), NOW).items[0];
    expect(person).toMatchObject({kind: 'check_needs_person', level: 'warning'});
  });
  it('a repaired schedule that now matches is not proof of charging', () => {
    const r = scheduleNotes(st(check('healthy', {events: [{trigger: 'post_repair', class: 'healthy'}]})), NOW).items[0];
    expect(r.kind).toBe('check_repaired'); expect(r.text).toMatch(/doesn’t prove the car is charging/);
    expect(kind(st(check('healthy', {events: [{trigger: 'post_repair', class: 'unknown'}]})))).toBe('check_healthy');
  });
  it('a healthy check from before the connection was lost does not read as current', () => {
    const s = st(check('healthy', {at: at(600)}), {link: {state: 'down', since: at(300)}});
    expect(scheduleNotes(s, NOW).items.map(i => i.kind)).toEqual(['check_healthy_stale', 'link_lost']);
    expect(text(s)).not.toMatch(/nothing needed changing/);
  });
});

describe('15.7b reboot, link and quiet wording', () => {
  const boot = (state, reason, extra = {}) => ({readiness: {boot_start: {state, reason, at: at(120), boot_generation: 2, ...extra}}});
  const ss = (state, secs, reason = 'x') => ({readiness: {boot_start: {state: 'requested', reason: 'boot_start_requested', at: at(120), boot_generation: 2},
    session_start: {state, reason}, session_start_at: secs === null ? undefined : at(secs)}});
  it('requested token alone never claims a request; the post-boot start ledger decides', () => {
    const pend = text(st(null, boot('requested', 'boot_start_requested')));
    expect(pend).toMatch(/pending and unconfirmed/); expect(pend).not.toMatch(/asked it|accepted|won’t ask/);
    expect(kind(st(null, ss('accepted', 600)))).toBe('boot_pending');          // accepted before the restart
    expect(kind(st(null, ss('accepted', null)))).toBe('boot_pending');
    const blk = scheduleNotes(st(null, ss('blocked', 30)), NOW).items[0];
    expect(blk.kind).toBe('boot_withheld'); expect(blk.text).not.toMatch(/asked|accepted/);
    expect(kind(st(null, ss('uncertain', 30)))).toBe('boot_unknown');
    expect(text(st(null, ss('uncertain', 30)))).not.toMatch(/asked|accepted/);
    expect(kind(st(null, ss('starting', 30)))).toBe('boot_asking');
    const ok = scheduleNotes(st(null, ss('accepted', 30)), NOW).items[0];
    expect(ok.kind).toBe('boot_requested'); expect(ok.text).toMatch(/accepted the request.*Only the charger can confirm/);
  });
  it('blocked says who acts; waiting explains', () => {
    const blocked = scheduleNotes(st(null, boot('blocked', 'transaction_present')), NOW).items[0];
    expect(blocked).toMatchObject({kind: 'boot_blocked', level: 'warning'});
    expect(blocked.text).toMatch(/already reports a charging session.*did not ask.*Check the charger and the SpotNav logs/);
    expect(text(st(null, boot('blocked', 'something_new')))).toMatch(/do not show it is safe to ask/);
    expect(kind(st(null, boot('waiting', 'waiting_for_post_boot_status')))).toBe('boot_waiting');
  });
  it('none, unknown, closed, an undated or malformed boot say nothing', () => {
    for (const b of [boot('none', 'no_boot_observed'), boot('unknown', 'boot_counter_unavailable'), boot('closed', 'charging_seen_after_boot'),
      boot('requested', 'x', {at: undefined}), boot('requested', 'x', {at: at(-600)}), {readiness: {boot_start: 'requested'}}, boot('weird', 'x')]) {
      expect(scheduleNotes(st(null, b), NOW)).toBeNull();
    }
  });
  it('a quiet link says unchanged since; a lost one says connection lost, never a charging failure', () => {
    expect(text(st(null, {link: {state: 'up', since: at(7200)}}))).toMatch(/Link to the charger unchanged since/);
    const lost = text(st(null, {link: {state: 'down', since: at(60)}}));
    expect(lost).toMatch(/Connection lost at .*checks the schedule again/);
    expect(lost).not.toMatch(/fail|stopped|not charging/i);
    expect(text(st(null, {link: {state: 'unknown', since: null}}))).toBe('');
  });
});

describe('15.7b offline copy in the primary state', () => {
  const base = (ready) => ({supported: true, connector_id: 1, outcomes: {uncertain: false}, schedule_pause: {intent: 'none'},
    readiness: {control: 'available', session_start: {state: 'accepted', reason: 'request_accepted'}, session_start_at: at(30),
      live: {connector_id: 1, status: {value: 'Preparing', normalized: 'connected', observed_at: at(900), fresh: false}, transaction: {value: false, observed_at: at(900), fresh: false}}, ...ready}});
  it('offline names the last confirmed state and does not claim charging failed', () => {
    const r = chargeSession(base({control: 'unavailable'}), NOW, false, NOW);
    expect(r.kind).toBe('offline');
    expect(r.detail).toMatch(/^Connection lost; last confirmed “Preparing” at .*not known until it reconnects/);
    expect(r.summary).not.toMatch(/stopped|failed|not charging/i);
  });
  it('last known (judged by the backend) uses the same words; offline with no reading keeps the plain text', () => {
    const j = {state: 'last_known', basis: 'x', reported_at: at(900), age_s: 900, link: {state: 'down'}, reason: 'x'};
    const s = base({freshness: {expected: null, link: {state: 'down'}, quantities: {status: j, transaction: j}}});
    const r = chargeSession(s, NOW, false, NOW);
    expect(r.kind).toBe('last_known'); expect(r.detail).toMatch(/^Connection lost; last confirmed “Preparing”.*not known right now/);
    const none = base({control: 'unavailable'}); delete none.readiness.live;
    expect(chargeSession(none, NOW, false, NOW).detail).toMatch(/^Home Assistant cannot reach the charger/);
  });
  it('a healthy check beside an offline state does not change the primary state', () => {
    const s = {...base({control: 'unavailable'}), ...st(check('healthy'))};
    expect(chargeSession(s, NOW, false, NOW)).toMatchObject({kind: 'offline', posture: 'at_risk'});
  });
});

describe('15.7b recovery banner mapping of repair blockers', () => {
  const blk = (code, action, extra = {}, repair = {}) => ({supported: true, reconciliation: {reason: code, blocker: {code, action}, recovery: {}, repair, ...extra}});
  it('needs a person is an error, persistent and not a retry; it outranks timed blockers', () => {
    const b = recoveryBanner(blk('repair_needs_person', 'needs_person'), NOW);
    expect(b).toMatchObject({level: 'error', code: 'repair_needs_person'});
    expect(b.text).toMatch(/Automatic repair is paused.*check the charger and the SpotNav logs/i);
    expect(b.text).not.toMatch(/retry|re-checks automatically|Recalculate|resend|Morek app|until a person/i);
    const flagged = recoveryBanner(blk('prices_unavailable', 'wait_for_prices', {check: {class: 'differs_confirmed'}}, {needs_person: true}), NOW);
    expect(flagged.code).toBe('repair_needs_person');
    expect(recoveryBanner(blk('prices_unavailable', 'wait_for_prices', {check: {class: 'healthy'}}, {needs_person: true}), NOW).code).toBe('prices_unavailable');
    expect(recoveryBanner(blk('upload_rejected', 'check_charger_response', {}, {needs_person: true}), NOW).code).toBe('upload_rejected');
  });
  it('deferred, spacing, unconfirmed and gated are plain, calm and never ask to resend', () => {
    const d = recoveryBanner(blk('repair_deferred', 'wait_for_repair_deferral'), NOW);
    expect(d).toMatchObject({level: 'info', code: 'repair_deferred'}); expect(d.text).toMatch(/current charge is left alone/);
    const sp = recoveryBanner(blk('repair_spacing', 'wait_for_repair_spacing', {}, {budget: {next_at: new Date(NOW + 600000).toISOString()}}), NOW);
    expect(sp.level).toBe('info'); expect(sp.text).toMatch(/waits before sending again.*send again after/);
    expect(recoveryBanner(blk('repair_spacing', 'wait_for_repair_spacing', {}, {budget: {next_at: 'garbage'}}), NOW).text).not.toMatch(/send again after/);
    expect(recoveryBanner(blk('repair_unconfirmed', 'wait_for_confirmation'), NOW).text).toMatch(/one odd reading isn’t enough/);
    const g = recoveryBanner(blk('repair_gated', 'wait_for_repair_release'), NOW);
    expect(g.level).toBe('warning'); expect(g.text).toMatch(/automatic repair is off, so nothing was sent/);
    for (const x of [d, sp, g]) expect(x.text).not.toMatch(/Recalculate|Resend|unplug|replug|\(repair_/i);
  });
  it('an uncertain write still wins over everything, and old backends are unchanged', () => {
    const u = blk('repair_needs_person', 'needs_person'); u.outcomes = {uncertain: true};
    expect(recoveryBanner(u, NOW).code).toBe('upload_uncertain');
    expect(recoveryBanner({supported: true, reconciliation: {reason: 'unchanged', blocker: null, recovery: {}}}, NOW)).toBeNull();
  });
});

describe('15.7b fail closed and degrade', () => {
  it('malformed, future and ancient checks never reassure', () => {
    expect(kind(st(check('healthy', {at: at(-3600)})))).toBe('check_unknown');
    expect(kind(st(check('healthy', {at: 'nope'})))).toBe('check_unknown');
    expect(kind(st(check('weird')))).toBe('check_unknown');
    expect(kind(st('healthy'))).toBe('check_unknown');
    expect(kind(st(check('healthy', {at: at(90000)})))).toBe('check_unknown');
    expect(text(st(check('healthy', {at: at(-3600)})))).not.toMatch(/nothing needed changing/);
  });
  it('absent or never-run fields show nothing; unsupported charger shows nothing', () => {
    expect(scheduleNotes({supported: true, verified: false}, NOW)).toBeNull();
    expect(scheduleNotes(st(undefined), NOW)).toBeNull();
    expect(scheduleNotes(st(null), NOW)).toBeNull();
    expect(scheduleNotes(st({class: null, at: null}), NOW)).toBeNull();
    expect(scheduleNotes({supported: false, reconciliation: {check: check('healthy')}}, NOW)).toBeNull();
    expect(scheduleNotes(null, NOW)).toBeNull();
    expect(linkInfo({link: {state: 'sideways', since: at(5)}}, NOW)).toEqual({state: 'unknown', since: null});
    expect(linkInfo({link: {state: 'up', since: at(-900)}}, NOW)).toEqual({state: 'up', since: null});
  });
});

describe('15.7b panel (mocked renderer, writes nothing)', () => {
  it('shows the check as a separate subdued line beside the primary state, hides when stale, writes nothing', async () => {
    const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
    raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
    const now = Date.now(), ago = s => new Date(now - s * 1000).toISOString();
    const live = {connector_id: 1, status: {value: 'Preparing', normalized: 'connected', observed_at: ago(5), fresh: true}, power_w: null, current_a: null,
      control_state: {value: 'off', observed_at: ago(5), fresh: true}, transaction: {value: false, observed_at: ago(5), fresh: true, changed_at: null}};
    const status = {api_version: 1, schedule: {supported: true, verified: false, sent: null, sent_at: null, ack: null, effective: null, connector_id: 1,
      ownership: {recorded_owner: 'morek_schedule'}, outcomes: {uncertain: false}, link: {state: 'up', since: ago(7200)},
      readiness: {control: 'available', session_start: {state: 'accepted', reason: 'no_transaction_observed'}, session_start_at: ago(300), live},
      reconciliation: {reason: 'unchanged', blocker: null, recovery: {}, repair: {gate_enabled: true, needs_person: false},
        check: {class: 'healthy', at: ago(60), readback_at: ago(61), reason: 'matched', rechecks: 0, events: []}}}};
    const hass = {connected: true, user: {is_admin: true}, callWS: vi.fn(msg => {
      if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}]});
      if (msg.type === 'spotnav/get_dashboard') return Promise.resolve(raw);
      return Promise.resolve(status);
    })};
    const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
    const select = panel.shadowRoot.querySelector('#charger'); select.value = 'a'; select.dispatchEvent(new Event('change')); await tick();
    const session = panel.shadowRoot.querySelector('#charge-session'), line = panel.shadowRoot.querySelector('#schedule-check');
    expect(line.hidden).toBe(false);
    expect(line.textContent).toMatch(/Checked at .*nothing needed changing/);
    expect(session.dataset.kind).toBe('accepted_no_transaction');   // the benign check never softens the primary warning
    expect(session.getAttribute('role')).toBe('alert');
    expect(line.getAttribute('role')).toBe('status');
    expect(line.textContent).toMatch(/Schedule check details/);
    panel.statusAt = Date.now() - 10 * 60 * 1000; panel.paint();
    expect(line.hidden).toBe(true);
    const types = hass.callWS.mock.calls.map(c => c[0].type);
    expect(types.filter(t => /action|update|send|charge_now|clear/.test(t))).toEqual([]);
  });
});
