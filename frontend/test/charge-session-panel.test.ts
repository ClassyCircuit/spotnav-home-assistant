// @vitest-environment jsdom
// @ts-nocheck
// The sidebar charge-session card: painted from status only, prominent when warning, and never a writer.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

describe('sidebar charge-session card', () => {
  it('shows a readable warning for accepted-without-transaction, calm text otherwise, and writes nothing', async () => {
    const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
    raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
    const at = () => new Date(Date.now() - 5000).toISOString();
    const live = {connector_id: 1, status: {value: 'Preparing', normalized: 'connected', observed_at: at(), fresh: true},
      power_w: null, current_a: null, control_state: {value: 'off', observed_at: at(), fresh: true},
      transaction: {value: false, observed_at: at(), fresh: true, changed_at: null}};
    const make = (ss, extra = {}) => ({api_version: 1, schedule: {supported: true, verified: false, sent: null, sent_at: null, ack: null, effective: null,
      connector_id: 1, ownership: {recorded_owner: 'morek_schedule'}, outcomes: {uncertain: false},
      readiness: {control: 'available', session_start: ss, session_start_at: new Date(Date.now() - 300000).toISOString(), live}, ...extra}});
    let status = make({state: 'accepted', reason: 'no_transaction_observed'});
    const hass = {connected: true, user: {is_admin: true}, callWS: vi.fn(msg => {
      if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}]});
      if (msg.type === 'spotnav/get_dashboard') return Promise.resolve(raw);
      return Promise.resolve(status);
    })};
    const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
    const select = panel.shadowRoot.querySelector('#charger'); select.value = 'a'; select.dispatchEvent(new Event('change')); await tick();
    const card = panel.shadowRoot.querySelector('#charge-session');
    expect(card.hidden).toBe(false);
    expect(card.getAttribute('role')).toBe('alert');
    expect(card.dataset.kind).toBe('accepted_no_transaction');
    expect(card.textContent).toMatch(/accepted the request, but no transaction is confirmed/);
    expect(card.textContent).toMatch(/Morek app|plug in again/);
    expect(card.textContent).not.toMatch(/no_transaction_observed/);
    // transient: no alarm role
    panel.rawStatus = make({state: 'starting', reason: 'request_in_progress'}); panel.statusAt = Date.now();
    panel.rawStatus.schedule.readiness.session_start_at = new Date().toISOString(); panel.paint();
    expect(card.getAttribute('role')).toBe('status'); expect(card.dataset.kind).toBe('pending');
    // stale status says unknown, not a claim either way
    panel.statusAt = Date.now() - 10 * 60 * 1000; panel.paint();
    expect(card.dataset.kind).toBe('unknown'); expect(card.dataset.level).toBe('unknown');
    // unsupported charger: nothing shown
    panel.statusAt = Date.now(); panel.rawStatus = {api_version: 1, schedule: {...make({state: 'waiting', reason: 'x'}).schedule, supported: false}}; panel.paint();
    expect(card.hidden).toBe(true);
    // painting only ever reads: no write-type calls from rendering the card
    const writes = hass.callWS.mock.calls.filter(([m]) => !['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/morek_schedule'].includes(m.type) ||
      (m.type === 'spotnav/morek_schedule' && m.action && m.action !== 'status'));
    expect(writes).toHaveLength(0);
    panel.remove();
  });
});
