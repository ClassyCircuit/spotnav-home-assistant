// @vitest-environment jsdom
// @ts-nocheck
// Stage 9.5: prominent blocker / retry status. Pure banner rules plus the real panel wiring (mocked HA).
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { recoveryBanner } from '../sidebar/recovery-banner.js';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};

const NOW = Date.parse('2026-11-13T10:00:00Z');
const state = (reason, blocker, recovery = {}, extra = {}) => ({supported: true, verified: false, reconciliation: {reason, blocker, recovery}, ...extra});
const later = (s) => new Date(NOW + s * 1000).toISOString();
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

describe('recoveryBanner', () => {
  it('says nothing when nothing blocks the schedule, and never claims success itself', () => {
    expect(recoveryBanner(state('upload_accepted_unverified', null), NOW)).toBeNull();
    expect(recoveryBanner(state('unchanged', null), NOW)).toBeNull();
    expect(recoveryBanner(null, NOW)).toBeNull();
  });
  it('shows a transient blocker with the next automatic check, and what to do once timed checks stop', () => {
    const waiting = recoveryBanner(state('prices_unavailable', {code: 'prices_unavailable', action: 'wait_for_prices'},
      {blocker_retry: {code: 'prices_unavailable', attempts: 1, limit: 12, next_retry_at: later(180), exhausted: false}}), NOW);
    expect(waiting.level).toBe('warning');
    expect(waiting.text).toMatch(/Prices are unavailable.*re-checks automatically at .*as soon as something changes.*prices_unavailable/);
    const done = recoveryBanner(state('charger_unavailable', {code: 'charger_unavailable', action: 'wait_for_charger_connection'},
      {blocker_retry: {code: 'charger_unavailable', attempts: 12, limit: 12, next_retry_at: null, exhausted: true}}), NOW);
    expect(done.text).toMatch(/Timed re-checks stopped.*Recalculate\/sync/);
  });
  it('separates a rejected write (bounded retry) from an unknown one (never retried)', () => {
    const retrying = recoveryBanner(state('upload_rejected', {code: 'upload_rejected', action: 'check_charger_response'},
      {next_retry_at: later(300), retries_left: 2, exhausted: false}), NOW);
    expect(retrying.text).toMatch(/refused.*Retrying automatically at .*2 attempts left/);
    const exhausted = recoveryBanner(state('upload_rejected', {code: 'upload_rejected', action: 'check_charger_response'},
      {next_retry_at: null, retries_left: 0, exhausted: true}), NOW);
    expect(exhausted.level).toBe('error');
    expect(exhausted.text).toMatch(/retries are used up.*not confirmed/);
    const unknown = recoveryBanner(state('upload_uncertain', {code: 'upload_uncertain', action: 'check_charger_outcome'}, {}, {outcomes: {uncertain: true}}), NOW);
    expect(unknown.level).toBe('error');
    expect(unknown.text).toMatch(/not retried automatically.*Charging is not confirmed.*Nothing was cleared/);
    expect(unknown.text).not.toMatch(/Retrying/);
  });
  it('marks blockers that need the person as such, and a pause as informational', () => {
    expect(recoveryBanner(state('protection_conflict_unresolved', {code: 'protection_conflict_unresolved', action: 'resolve_protection_conflict'}), NOW))
      .toMatchObject({level: 'error', text: expect.stringMatching(/does not clear by itself/)});
    expect(recoveryBanner(state('paused_until_resume', {code: 'paused_until_resume', action: 'resume_schedule'}), NOW).level).toBe('info');
  });
});

describe('sidebar recovery banner wiring', () => {
  it('is painted from fresh status only and removed when the blocker clears', async () => {
    const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
    raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
    const base = {api_version: 1, schedule: {supported: true, verified: false, sent: null, sent_at: null, ack: null, effective: null, ownership: {recorded_owner: 'morek_schedule'}}};
    const blocked = {...base, schedule: {...base.schedule, reconciliation: {reason: 'charger_unavailable',
      blocker: {code: 'charger_unavailable', action: 'wait_for_charger_connection'},
      recovery: {blocker_retry: {code: 'charger_unavailable', attempts: 0, limit: 12, next_retry_at: new Date(Date.now() + 60000).toISOString(), exhausted: false}}}}};
    const hass = {connected: true, user: {is_admin: true}, callWS: vi.fn(msg => {
      if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}]});
      if (msg.type === 'spotnav/get_dashboard') return Promise.resolve(raw);
      return Promise.resolve(blocked);
    })};
    const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
    const select = panel.shadowRoot.querySelector('#charger'); select.value = 'a'; select.dispatchEvent(new Event('change')); await tick();
    const banner = panel.shadowRoot.querySelector('#recovery-banner');
    expect(banner.hidden).toBe(false);
    expect(banner.textContent).toMatch(/not connected to Home Assistant.*re-checks automatically/);
    expect(banner.dataset.code).toBe('charger_unavailable');
    panel.statusAt = Date.now() - 10 * 60 * 1000; panel.paint();   // stale status must not keep speaking
    expect(banner.hidden).toBe(true);
    panel.statusAt = Date.now(); panel.rawStatus = {...base, schedule: {...base.schedule, reconciliation: {reason: 'unchanged', blocker: null, recovery: {}}}}; panel.paint();
    expect(banner.hidden).toBe(true);
    panel.remove();
  });
});
