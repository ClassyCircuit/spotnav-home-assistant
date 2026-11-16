// @vitest-environment jsdom
// @ts-nocheck
// Stage 7.1 through the real sidebar panel: availability is read once, history only on a click, refreshes keep the
// selection, a charger change drops it, and nothing here ever writes.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
const mounted = [];
vi.mock('echarts/core', () => ({
  use: () => {},
  graphic: { clipRectByRect: r => r, clipPointsByRect: p => p, LinearGradient: class {} },
  init: dom => { const chart = { dom, options: [], setOption(o) { this.options.push(o); }, getOption() { const o = this.options.at(-1); return { ...o, dataZoom: [{ startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }] }; },
    on() {}, off() {}, dispatchAction() {}, getDom: () => dom, getWidth: () => 800, resize() {}, dispose() {}, convertToPixel: (_, v) => v, convertFromPixel: (_, v) => v }; mounted.push(chart); return chart; },
}));
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
import '../sidebar/panel.js';
import { historyAnswer, HISTORY_ZONE } from '../prototype/history-day-fixture.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const ZONE = HISTORY_ZONE; // The response fixture and HA calendar must use the same zone.
const localToday = () => new Intl.DateTimeFormat('en-CA', {timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
const shift = (day, n) => new Date(Date.parse(day + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);

function setup(hassExtra = {}, pending = null) {
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
  const calls = [];
  const hass = {connected: true, user: {is_admin: false}, config: {time_zone: ZONE}, ...hassExtra, callWS: vi.fn(msg => {
    calls.push(msg);
    if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}, {charger_id: 'b', charger_name: 'B'}]});
    if (msg.type === 'spotnav/get_dashboard') return Promise.resolve({...raw, charger: {...raw.charger, charger_id: msg.charger_id}});
    if (msg.type === 'spotnav/get_charging_history') {
      if (pending) return new Promise(resolve => pending.push({msg, resolve}));
      const answer = historyAnswer(msg.charger_id, '2026-11-09');
      // re-key the fixture day onto the requested local day (the panel asks for real calendar days)
      const text = JSON.stringify(answer).split('2026-11-09').join(msg.date).split('2026-11-10').join(shift(msg.date, 1));
      return Promise.resolve(JSON.parse(text));
    }
    return Promise.resolve({api_version: 1, schedule: {supported: false, verified: false}});
  })};
  return {raw, calls, hass};
}
async function open(hass) {
  const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
  const select = panel.shadowRoot.querySelector('#charger'); select.value = 'a'; select.dispatchEvent(new Event('change')); await tick(); await tick();
  return panel;
}
const historyCalls = calls => calls.filter(m => m.type === 'spotnav/get_charging_history');

describe('sidebar history day (7.3a) in the real panel', () => {
  it('reads one Home Assistant-local day once, keeps the chosen day across refreshes, drops it on a charger change and never writes', async () => {
    const {calls, hass} = setup(); const panel = await open(hass);
    const today = localToday();
    expect(historyCalls(calls)).toEqual([{type: 'spotnav/get_charging_history', api_version: 1, charger_id: 'a', date: today}]);
    const card = () => panel.shadowRoot.querySelector('.history-day');
    expect(card().dataset.historyState).toBe('ready');
    for (let i = 0; i < 3; i++) { panel.paint(); await tick(); }
    expect(historyCalls(calls)).toHaveLength(1);
    panel.shadowRoot.querySelector('[data-history-nav="prev"]').click(); await tick();
    expect(historyCalls(calls).map(m => m.date)).toEqual([today, shift(today, -1)]);
    // a routine dashboard refresh keeps the chosen past day and asks for nothing
    panel.rawDashboard = {...panel.rawDashboard, generated_at: new Date().toISOString()}; panel.paint(); await tick();
    expect(panel.shadowRoot.querySelector('.history-day-label').textContent).toContain(String(Number(shift(today, -1).slice(8))));
    expect(historyCalls(calls)).toHaveLength(2);
    expect(panel.historyDay).not.toBeNull();
    panel.stopObservations(false);
    expect(panel.historyDay).toBeNull();
    const reads = ['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days','spotnav/get_price_insights', 'spotnav/get_charging_history', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config'];
    const writes = calls.filter(m => !reads.includes(m.type) || (m.type === 'spotnav/morek_schedule' && m.action && m.action !== 'status'));
    expect(writes.filter(m => m.type !== 'spotnav/morek_schedule').map(m => m.type)).toEqual([]);
    expect(calls.some(m => m.type === 'spotnav/get_charging_history' && ('include_prices' in m || 'from' in m || 'to' in m))).toBe(false);
    panel.remove();
  });

  it('asks nothing while the Home Assistant time zone is unknown and says so', async () => {
    const {calls, hass} = setup({config: {}}); const panel = await open(hass);
    expect(historyCalls(calls)).toEqual([]);
    expect(panel.shadowRoot.querySelector('.history-banner')?.textContent).toContain('time zone');
    panel.remove();
  });

  it('drops an answer that arrives after the charger changed', async () => {
    const pending = [], {calls, hass} = setup({}, pending); const panel = await open(hass);
    expect(pending).toHaveLength(1);
    expect(panel.shadowRoot.querySelector('.history-day')?.dataset.historyState).toBe('loading');
    panel.stopObservations(false);
    pending[0].resolve(historyAnswer('a', '2026-11-09')); await tick();
    expect(panel.historyDay).toBeNull();
    expect(panel.shadowRoot.querySelector('.history-day[data-history-state="ready"]')).toBeNull();
    panel.remove();
  });
});
