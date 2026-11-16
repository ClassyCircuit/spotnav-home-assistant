// @vitest-environment jsdom
// @ts-nocheck
// Stage 7.5 through the real sidebar panel: one live read plus the current month on open, every other read an explicit
// choice, routine refreshes keep the choices, a failure waits for Retry, a stale answer is dropped, and nothing writes.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
vi.mock('echarts/core', () => ({
  use: () => {},
  graphic: { clipRectByRect: r => r, clipPointsByRect: p => p, LinearGradient: class {} },
  init: dom => { const chart = { dom, options: [], setOption(o) { this.options.push(o); }, getOption() { const o = this.options.at(-1); return { ...o, dataZoom: [{ startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }] }; },
    on() {}, off() {}, dispatchAction() {}, getDom: () => dom, getWidth: () => 800, resize() {}, dispose() {}, convertToPixel: (_, v) => v, convertFromPixel: (_, v) => v }; return chart; },
}));
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
import '../sidebar/panel.js';
import { liveAnswer, monthlyAnswer } from '../prototype/insight-fixture.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
// The dashboard fixture is SE4 / SEK with today 2026-09-22; the insight fixtures are re-keyed onto that market.
const SEK = {kind: 'published_spot', unit: 'major_per_kwh', currency: 'SEK', fees: 'none'};
const market = charger => ({charger, area: 'SE4', currency: 'SEK'});
const rekey = (answer, msg, extra = {}) => ({...answer, charger_id: msg.charger_id, area_id: 'SE4', currency: 'SEK', basis: SEK, ...extra});

function setup({failLive = false, hold = null} = {}) {
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
  const calls = [];
  const hass = {connected: true, user: {is_admin: false}, config: {time_zone: 'Europe/Stockholm'}, callWS: vi.fn(msg => {
    calls.push(msg);
    if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}, {charger_id: 'b', charger_name: 'B'}]});
    if (msg.type === 'spotnav/get_dashboard') return Promise.resolve({...raw, charger: {...raw.charger, charger_id: msg.charger_id}});
    if (msg.type === 'spotnav/get_price_insights') {
      if (hold && msg.mode === 'live') return new Promise(resolve => hold.push({msg, resolve}));
      if (failLive && msg.mode === 'live') return Promise.reject({code: 'timeout'});
      if (msg.mode === 'live') return Promise.resolve(rekey(liveAnswer(market(msg.charger_id), msg.duration_minutes), msg));
      return Promise.resolve(rekey(monthlyAnswer(market(msg.charger_id), '2026-10'), msg, {month: msg.month}));
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
const insightCalls = calls => calls.filter(m => m.type === 'spotnav/get_price_insights');
const change = (panel, selector, value) => { const el = panel.shadowRoot.querySelector(selector); el.value = String(value); el.dispatchEvent(new Event('change')); };

describe('sidebar price insights (7.5) in the real panel', () => {
  it('opens with one live read and one read of the current month (non-admin allowed), repeats nothing on repaints and never writes', async () => {
    const {calls, hass} = setup(); const panel = await open(hass);
    expect(insightCalls(calls)).toEqual([
      {type: 'spotnav/get_price_insights', api_version: 1, charger_id: 'a', mode: 'live', duration_minutes: 60},
      {type: 'spotnav/get_price_insights', api_version: 1, charger_id: 'a', mode: 'monthly', month: '2026-09'}]);
    const root = () => panel.shadowRoot.querySelector('.insights');
    expect(root().querySelector('[data-insight-block="current"] .insight-value').textContent).toMatch(/SEK\/kWh$/);
    expect(root().textContent).toMatch(/not the charging plan/); expect(root().textContent).not.toMatch(/NaN|undefined/);
    for (let i = 0; i < 4; i++) { panel.paint(); await tick(); }
    expect(insightCalls(calls)).toHaveLength(2);
    const reads = ['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days', 'spotnav/get_charging_history','spotnav/get_sessions', 'spotnav/get_price_insights', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config'];
    const writes = calls.filter(m => !reads.includes(m.type) || (m.type === 'spotnav/morek_schedule' && m.action && m.action !== 'status'));
    expect(writes.filter(m => m.type !== 'spotnav/morek_schedule').map(m => m.type)).toEqual([]);
    expect(insightCalls(calls).every(m => Object.keys(m).every(k => ['type', 'api_version', 'charger_id', 'mode', 'duration_minutes', 'month'].includes(k)))).toBe(true);
    panel.remove();
  });

  it('a window length, a month and a comparison are each one explicit read; a routine refresh keeps the choices', async () => {
    const {calls, hass} = setup(); const panel = await open(hass);
    change(panel, '[data-insight-duration]', 120); await tick();
    expect(insightCalls(calls).at(-1)).toMatchObject({mode: 'live', duration_minutes: 120});
    change(panel, '[data-insight-month]', '2026-08'); await tick();
    expect(insightCalls(calls).at(-1)).toMatchObject({mode: 'monthly', month: '2026-08'});
    panel.shadowRoot.querySelector('[data-insight-compare-previous]').click(); await tick();
    expect(insightCalls(calls).at(-1)).toMatchObject({mode: 'monthly', month: '2026-07'});
    const n = insightCalls(calls).length;
    panel.rawDashboard = {...panel.rawDashboard, generated_at: new Date().toISOString()}; panel.paint(); await tick(); panel.paint(); await tick();
    expect(insightCalls(calls)).toHaveLength(n);
    expect(panel.shadowRoot.querySelector('[data-insight-duration]').value).toBe('120');
    expect(panel.shadowRoot.querySelector('[data-insight-month]').value).toBe('2026-08');
    expect(panel.shadowRoot.querySelector('[data-insight-compare]').value).toBe('2026-07');
    expect(panel.shadowRoot.querySelector('[data-insight-compare-state="ready"] table')).not.toBeNull();
    panel.remove();
  });

  it('a failure stays until the user presses Retry, which reads once', async () => {
    const {calls, hass} = setup({failLive: true}); const panel = await open(hass);
    expect(panel.shadowRoot.querySelector('[data-insight-banner="error"]')?.textContent).toBe('Price insights could not be read.');
    for (let i = 0; i < 4; i++) { panel.paint(); await tick(); }
    const live = () => insightCalls(calls).filter(m => m.mode === 'live').length;
    expect(live()).toBe(1);
    panel.shadowRoot.querySelector('[data-insight-retry]').click(); await tick();
    expect(live()).toBe(2);
    panel.remove();
  });

  it('drops an answer that arrives after the charger changed', async () => {
    const hold = [], {hass} = setup({hold}); const panel = await open(hass);
    expect(hold).toHaveLength(1);
    expect(panel.shadowRoot.querySelector('.insights [data-insight-state]').dataset.insightState).toBe('loading');
    panel.stopObservations(false);
    expect(panel.priceInsights).toBeNull();
    hold[0].resolve(rekey(liveAnswer(market('a'), 60), {charger_id: 'a'})); await tick();
    expect(panel.priceInsights).toBeNull();
    expect(panel.shadowRoot.querySelector('.insights [data-insight-block="current"] .insight-value')?.textContent ?? 'Unavailable').toBe('Unavailable');
    panel.remove();
  });
});
