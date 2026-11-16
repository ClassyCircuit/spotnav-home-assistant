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
import { addDays } from '../shared-dashboard/price-days.js';
import { localDaySpan } from '../sidebar/price-chart.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', {get: () => ({valid: true})});
Object.defineProperty(ElementInternals.prototype, 'validationMessage', {get: () => ''});
window.scrollTo = () => {};
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const ZONE = 'Europe/Stockholm', TODAY = '2026-09-22';
const rows = (day, hours = 24) => Array.from({length: hours}, (_, i) => { const s = localDaySpan(day, ZONE)[0] + i * 3600000; return {start: new Date(s).toISOString(), end: new Date(s + 3600000).toISOString(), raw_price: 1 + i / 100}; });
const held = new Map([['2026-09-21', {hours: 10, complete: false}], ['2026-09-10', {hours: 24, complete: true}]]);
const facts = (day, o) => ({day, state: o.complete ? 'ready' : 'incomplete', complete: o.complete, resolution_minutes: 60, source: 'network', fetched_at: '2026-09-21T20:00:00+00:00', interval_count: o.hours});

describe('sidebar price-day navigation', () => {
  it('reads availability once, loads one bounded page on a click, keeps the selection across refreshes, drops it on a charger change and never writes', async () => {
    const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
    raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
    raw.prices.published_intervals = rows(TODAY);
    const calls = [];
    const hass = {connected: true, user: {is_admin: false}, callWS: vi.fn(msg => {
      calls.push(msg);
      if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}, {charger_id: 'b', charger_name: 'B'}]});
      if (msg.type === 'spotnav/get_dashboard') return Promise.resolve({...raw, charger: {...raw.charger, charger_id: msg.charger_id}});
      if (msg.type === 'spotnav/get_price_days') {
        const base = {api_version: 1, charger_id: msg.charger_id, area_id: 'SE4', zone: ZONE, currency: 'SEK', today: TODAY, mode: msg.mode};
        if (msg.mode === 'available') return Promise.resolve({...base, yesterday_reachable: true, days: [...held].map(([d, o]) => facts(d, o)).sort((a, b) => b.day.localeCompare(a.day))});
        const days = [];
        for (let d = msg.from; d <= msg.to; d = addDays(d, 1)) { const o = held.get(d); days.push(o ? {...facts(d, o), held: true, provenance: [], reason: null, intervals: rows(d, o.hours)} : {day: d, held: false, state: 'unavailable', complete: false, resolution_minutes: null, source: null, fetched_at: null, interval_count: null, provenance: [], reason: 'not_held', intervals: null}); }
        return Promise.resolve({...base, from: msg.from, to: msg.to, days});
      }
      return Promise.resolve({api_version: 1, schedule: {supported: false, verified: false}});
    })};
    const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
    const select = panel.shadowRoot.querySelector('#charger'); select.value = 'a'; select.dispatchEvent(new Event('change')); await tick(); await tick();
    const priceCalls = () => calls.filter(m => m.type === 'spotnav/get_price_days');
    expect(priceCalls()).toEqual([{type: 'spotnav/get_price_days', api_version: 1, charger_id: 'a', mode: 'available'}]); // metadata only
    const button = id => panel.shadowRoot.querySelector(`[data-price-nav="${id}"]`);
    expect(button('yesterday').hasAttribute('disabled')).toBe(false);
    expect(button('yesterday').textContent).toContain('(partial)');
    expect(button('tomorrow').hasAttribute('disabled')).toBe(true);
    // refreshes do not ask again
    for (let i = 0; i < 3; i++) { panel.paint(); await tick(); }
    expect(priceCalls()).toHaveLength(1);
    // Yesterday: one bounded range request, eight days at most
    button('yesterday').click(); await tick(); await tick();
    expect(priceCalls()).toHaveLength(2);
    expect(priceCalls()[1]).toMatchObject({mode: 'range', from: '2026-09-14', to: '2026-09-21'});
    expect(panel.shadowRoot.querySelector('.price-nav-note').textContent).toMatch(/partial/);
    expect(button('yesterday').getAttribute('aria-pressed')).toBe('true');
    // the chart was drawn for that day; a user zoom survives a routine refresh
    const chart = mounted.at(-1);
    const zoom = () => chart.options.at(-1).dataZoom[0];
    const [from, to] = localDaySpan('2026-09-21', ZONE);
    expect(zoom().startValue).toBeGreaterThanOrEqual(from); expect(zoom().endValue).toBeLessThanOrEqual(to);
    zoom().startValue += 3600000; const kept = [zoom().startValue, zoom().endValue];
    // routine dashboard refresh keeps the selection and range and asks for nothing
    panel.rawDashboard = {...panel.rawDashboard, generated_at: new Date().toISOString()}; panel.paint(); await tick();
    expect(button('yesterday').getAttribute('aria-pressed')).toBe('true');
    expect(priceCalls()).toHaveLength(2);
    expect([mounted.at(-1).options.at(-1).dataZoom[0].startValue, mounted.at(-1).options.at(-1).dataZoom[0].endValue]).toEqual(kept);
    // charger change: the state and its pages are gone
    expect(panel.priceDays).not.toBeNull();
    panel.stopObservations(false);
    expect(panel.priceDays).toBeNull();
    // never a write
    const writes = calls.filter(m => !['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days','spotnav/get_price_insights', 'spotnav/morek_schedule', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config'].includes(m.type) || (m.type === 'spotnav/morek_schedule' && m.action && m.action !== 'status'));
    expect(writes.map(m => m.type + ':' + (m.action || ''))).toEqual([]);
    panel.remove();
  });
});
