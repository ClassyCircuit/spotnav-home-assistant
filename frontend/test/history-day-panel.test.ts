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
import { historyAnswer, HISTORY_ZONE, fixtureSessionsRequest } from '../prototype/history-day-fixture.js';
import { localDaySpan } from '../sidebar/price-chart.js';
import { localDate } from '../shared-dashboard/history-day.js';

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

function setup(hassExtra = {}, pending = null, {sessionDays = [], priceDays = null, raw: rawEdit = null, sessions = null} = {}) {
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a'; rawEdit?.(raw);
  const calls = [];
  const hass = {connected: true, user: {is_admin: false}, config: {time_zone: ZONE}, ...hassExtra, callWS: vi.fn(msg => {
    calls.push(msg);
    if (msg.type === 'spotnav/list_chargers') return Promise.resolve({api_version: 1, chargers: [{charger_id: 'a', charger_name: 'A'}, {charger_id: 'b', charger_name: 'B'}]});
    if (msg.type === 'spotnav/get_dashboard') return Promise.resolve({...raw, charger: {...raw.charger, charger_id: msg.charger_id}});
    if (msg.type === 'spotnav/get_sessions' && sessions) return Promise.resolve(sessions(msg));
    if (msg.type === 'spotnav/get_sessions') return Promise.resolve({api_version: 1, charger_id: msg.charger_id, days: sessionDays.map(period => ({period, sessions: 1, energy_kwh: 5}))});
    if (msg.type === 'spotnav/get_price_days' && priceDays) return Promise.resolve(priceDays(msg));
    if (msg.type === 'spotnav/get_charging_history') {
      if (pending) return new Promise(resolve => pending.push({msg, resolve}));
      const answer = historyAnswer(msg.charger_id, '2026-11-09');
      // re-key the fixture day onto the requested local day (the panel asks for real calendar days)
      const text = JSON.stringify(answer).split('2026-11-09').join(msg.date).split('2026-11-10').join(shift(msg.date, 1));
      const rekeyed = JSON.parse(text);
      // the retained raw window follows the real calendar too: genuine sample rows (oldest_by_kind) begin 12 days back
      for (const k of ['power_w', 'energy_register_kwh']) rekeyed.retention.oldest_by_kind[k] = `${shift(localToday(), -12)}T09:00:00+00:00`;
      return Promise.resolve(rekeyed);
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
  it('opens on yesterday (one history read, one small sessions read), offers only retained days, keeps the chosen day across refreshes, drops it on a charger change and never writes', async () => {
    const today = localToday(), yesterday = shift(today, -1), {calls, hass} = setup({}, null, {sessionDays: [shift(today, -3)]}); const panel = await open(hass);
    expect(historyCalls(calls)).toEqual([{type: 'spotnav/get_charging_history', api_version: 1, charger_id: 'a', date: yesterday}]);
    expect(calls.filter(m => m.type === 'spotnav/get_sessions')).toEqual([{type: 'spotnav/get_sessions', api_version: 1, charger_id: 'a', limit: 1}]);
    const card = () => panel.shadowRoot.querySelector('.history-day');
    expect(card().dataset.historyState).toBe('ready');
    expect(panel.shadowRoot.querySelector('.history-day-label').textContent).toContain('yesterday, default');
    const options = () => [...panel.shadowRoot.querySelectorAll('select[data-history-date] option')].map(o => o.value);
    expect(options()[0]).toBe(today); expect(options()).toContain(yesterday); expect(options()).not.toContain(shift(today, 1)); expect(options()).not.toContain(shift(today, -63));
    for (let i = 0; i < 3; i++) { panel.paint(); await tick(); }
    expect(historyCalls(calls)).toHaveLength(1);
    panel.shadowRoot.querySelector('[data-history-nav="prev"]').click(); await tick();
    expect(historyCalls(calls).map(m => m.date)).toEqual([yesterday, shift(yesterday, -1)]);
    // a routine dashboard refresh keeps the chosen past day and asks for nothing
    panel.rawDashboard = {...panel.rawDashboard, generated_at: new Date().toISOString()}; panel.paint(); await tick();
    expect(panel.shadowRoot.querySelector('.history-day-label').textContent).toContain(String(Number(shift(yesterday, -1).slice(8))));
    expect(panel.shadowRoot.querySelector('.history-day-label').textContent).not.toContain('default');
    expect(historyCalls(calls)).toHaveLength(2);
    const picker = panel.shadowRoot.querySelector('select[data-history-date]'); picker.value = shift(today, -5); picker.dispatchEvent(new Event('change')); await tick();
    expect(historyCalls(calls).map(m => m.date).at(-1)).toBe(shift(today, -5));
    const before = historyCalls(calls).length;
    panel.historyNav('day', shift(today, -80)); await tick(); // not a retained day: nothing is requested
    expect(historyCalls(calls)).toHaveLength(before);
    expect(panel.historyDay).not.toBeNull();
    panel.stopObservations(false);
    expect(panel.historyDay).toBeNull();
    const reads = ['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days','spotnav/get_price_insights', 'spotnav/get_charging_history', 'spotnav/get_sessions', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config']
    const writes = calls.filter(m => !reads.includes(m.type) || (m.type === 'spotnav/morek_schedule' && m.action && m.action !== 'status'));
    expect(writes.filter(m => m.type !== 'spotnav/morek_schedule').map(m => m.type)).toEqual([]);
    expect(calls.some(m => m.type === 'spotnav/get_charging_history' && ('include_prices' in m || 'from' in m || 'to' in m))).toBe(false);
    panel.remove();
  });

  it('requests the held price day of a chosen history day across two zones (read-only, bounded) and never at the default', async () => {
    const today = localToday(), yesterday = shift(today, -1), marketToday = localDate(Date.now(), 'Europe/Stockholm');
    const rows = day => Array.from({length: 24}, (_, i) => { const s = localDaySpan(day, 'Europe/Stockholm')[0] + i * 3600000; return {start: new Date(s).toISOString(), end: new Date(s + 3600000).toISOString(), raw_price: 1 + i / 100}; });
    const facts = d => ({day: d, state: 'ready', complete: true, resolution_minutes: 60, source: 'network', fetched_at: '2026-09-21T20:00:00+00:00', interval_count: 24});
    const isHeld = d => d < marketToday && d >= shift(yesterday, -2); // yesterday and the two days before it are held; nothing earlier
    const priceDays = msg => {
      const base = {api_version: 1, charger_id: msg.charger_id, area_id: 'SE4', zone: 'Europe/Stockholm', currency: 'SEK', today: marketToday, mode: msg.mode};
      if (msg.mode === 'available') return {...base, yesterday_reachable: true, days: [0, 1, 2, 3].map(n => shift(yesterday, 1 - n)).filter(isHeld).map(facts)};
      const days = [];
      for (let d = msg.from; d <= msg.to; d = shift(d, 1)) days.push(isHeld(d) ? {...facts(d), held: true, provenance: [], reason: null, intervals: rows(d)} : {day: d, held: false, state: 'unavailable', complete: false, resolution_minutes: null, source: null, fetched_at: null, interval_count: null, provenance: [], reason: 'not_held', intervals: null});
      return {...base, from: msg.from, to: msg.to, days};
    };
    const {calls, hass} = setup({}, null, {priceDays, raw: raw => { raw.prices.today = marketToday; raw.prices.published_intervals = rows(marketToday); }}); const panel = await open(hass);
    const priceCalls = () => calls.filter(m => m.type === 'spotnav/get_price_days'), pages = () => priceCalls().filter(m => m.mode === 'range');
    const note = () => panel.shadowRoot.querySelector('.history-price-note')?.textContent || '';
    expect(priceCalls().map(m => m.mode)).toEqual(['available']); // the default yesterday review requests no price page
    expect(panel.shadowRoot.querySelector('[data-history-nav="prices"]')).not.toBeNull();
    // choosing the day before yesterday requests exactly the held market day(s) that cover it: HA (UTC) day D spans Stockholm days D and D+1
    panel.shadowRoot.querySelector('[data-history-nav="prev"]').click(); await tick(); await tick();
    expect(pages()).toHaveLength(1); expect(pages()[0].to).toBe(shift(yesterday, -1) < shift(marketToday, -1) ? shift(yesterday, 0) : shift(yesterday, -1));
    expect(note()).toMatch(/market calendar, Europe\/Stockholm/); expect(note()).toMatch(/covers two market days/);
    // the explicit button asks for the shown day's page again only when it is not already loaded
    panel.shadowRoot.querySelector('[data-history-nav="prices"]').click(); await tick(); await tick();
    expect(pages().length).toBeLessThanOrEqual(2);
    // a retained day whose prices are not held: the note says unknown, the chart request is never invented
    panel.historyNav('day', shift(today, -10)); await tick(); await tick();
    expect(note()).toMatch(/not available, so the price chart is unchanged: unknown, not zero/);
    expect(calls.filter(m => !['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days', 'spotnav/get_price_insights', 'spotnav/get_charging_history', 'spotnav/get_sessions', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config', 'spotnav/morek_schedule'].includes(m.type))).toEqual([]);
    panel.remove();
  });

  it('shows the spot-only month cost from the opening sessions read, reads another month only on choice, and never writes (8.2b)', async () => {
    const cur = localToday().slice(0, 7), prev = shift(`${cur}-01`, -1).slice(0, 7);
    const toFixture = text => text.split(prev).join('@@P').split(cur).join('@@C').split('@@C').join('2026-11').split('@@P').join('2026-10');
    const toReal = text => text.split('2026-11').join('@@C').split('2026-10').join('@@P').split('@@C').join(cur).split('@@P').join(prev);
    const sessions = msg => { const answer = fixtureSessionsRequest({charger: msg.charger_id})(msg.month ? {month: toFixture(msg.month)} : {}); return answer.then(a => JSON.parse(toReal(JSON.stringify(a)))); };
    const {calls, hass} = setup({}, null, {sessions}); const panel = await open(hass); await tick();
    const reads = () => calls.filter(m => m.type === 'spotnav/get_sessions');
    expect(reads()).toEqual([{type: 'spotnav/get_sessions', api_version: 1, charger_id: 'a', limit: 1}]);
    const section = () => panel.shadowRoot.querySelector('[data-history-section="month-cost"]');
    expect(section().dataset.monthCostState).toBe('ready');
    expect(section().textContent).toContain('Partial spot cost €1.97');
    expect(section().textContent).toContain('no fees, taxes or margin');
    for (let i = 0; i < 3; i++) { panel.paint(); await tick(); }
    expect(reads()).toHaveLength(1);
    const select = panel.shadowRoot.querySelector('select[data-history-month]');
    select.value = prev; select.dispatchEvent(new Event('change')); await tick(); await tick();
    expect(reads().at(-1)).toEqual({type: 'spotnav/get_sessions', api_version: 1, charger_id: 'a', limit: 1, month: prev});
    expect(reads()).toHaveLength(2);
    expect(section().textContent).toContain('-€0.35');
    const again = panel.shadowRoot.querySelector('select[data-history-month]'); again.value = cur; again.dispatchEvent(new Event('change')); await tick();
    expect(section().textContent).toContain('€1.97'); expect(reads()).toHaveLength(2);
    expect(calls.filter(m => !['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days', 'spotnav/get_price_insights', 'spotnav/get_charging_history', 'spotnav/get_sessions', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config', 'spotnav/morek_schedule'].includes(m.type))).toEqual([]);
    panel.remove();
  });

  it('shows the month savings card beside the unchanged spot cost, the read time, and refreshes the current month at most once per five minutes without writing (8.3b)', async () => {
    const cur = localToday().slice(0, 7), prev = shift(`${cur}-01`, -1).slice(0, 7);
    const toFixture = text => text.split(prev).join('@@P').split(cur).join('@@C').split('@@C').join('2026-11').split('@@P').join('2026-10');
    const toReal = text => text.split('2026-11').join('@@C').split('2026-10').join('@@P').split('@@C').join(cur).split('@@P').join(prev);
    let failNext = false;
    const sessions = msg => { if (failNext) { failNext = false; return Promise.reject(new Error('timeout')); } const answer = fixtureSessionsRequest({charger: msg.charger_id})(msg.month ? {month: toFixture(msg.month)} : {}); return answer.then(a => JSON.parse(toReal(JSON.stringify(a)))); };
    const {calls, hass} = setup({}, null, {sessions}); const panel = await open(hass); await tick();
    const reads = () => calls.filter(m => m.type === 'spotnav/get_sessions');
    const section = () => panel.shadowRoot.querySelector('[data-history-section="month-cost"]');
    expect(reads()).toHaveLength(1);
    expect(section().querySelector('[data-spot-cost]').textContent).toContain('Partial spot cost €1.97');
    const savings = section().querySelector('[data-spot-savings]');
    expect(savings.dataset.spotSavings).toBe('partial');
    expect(savings.textContent).toContain('Partial estimated savings €0.17 (13.1% of the reference) for 11.2 kWh compared');
    expect(savings.textContent).toContain('not a supplier-bill saving');
    expect(section().querySelector('[data-month-read]').textContent).toContain('Read at ');
    const real = Date.now, base = real.call(Date);
    try {
      Date.now = () => base + 240000; panel.paint(); await tick();
      expect(reads()).toHaveLength(1);
      failNext = true; Date.now = () => base + 301000; panel.paint(); await tick();
      expect(reads()).toHaveLength(2);
      expect(section().textContent).toContain('€1.97');
      expect(section().querySelector('[data-month-read]').textContent).toContain('latest refresh failed');
      Date.now = () => base + 900000; for (let i = 0; i < 3; i++) { panel.paint(); await tick(); }
      expect(reads()).toHaveLength(2);
      panel.shadowRoot.querySelector('[data-history-nav="retry"]').click(); await tick(); await tick();
      expect(reads()).toHaveLength(3);
      expect(section().querySelector('[data-month-read]').textContent).not.toContain('refresh failed');
    } finally { Date.now = real; }
    expect(calls.filter(m => !['spotnav/list_chargers', 'spotnav/get_dashboard', 'spotnav/get_settings', 'spotnav/get_price_days', 'spotnav/get_price_insights', 'spotnav/get_charging_history', 'spotnav/get_sessions', 'spotnav/get_market', 'spotnav/get_market_options', 'spotnav/get_entity_config', 'spotnav/morek_schedule'].includes(m.type))).toEqual([]);
    panel.remove();
  });

  it('an older backend (no delivery keys) says spot cost is not reported for the month and the day, never zero (8.2b)', async () => {
    const {hass} = setup(); const panel = await open(hass); await tick();
    expect(panel.shadowRoot.querySelector('[data-history-section="month-cost"]').dataset.monthCostState).toBe('legacy');
    expect(panel.shadowRoot.querySelector('[data-history-section="month-cost"]').textContent).toContain('does not report spot-only cost by month');
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
    pending[0].resolve(historyAnswer('a', pending[0].msg.date)); await tick();
    expect(panel.historyDay).toBeNull();
    expect(panel.shadowRoot.querySelector('.history-day[data-history-state="ready"]')).toBeNull();
    panel.remove();
  });
});
