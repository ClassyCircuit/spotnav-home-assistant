// @ts-nocheck
// Stage 7.1: price-day navigation. Real state machine, real renderer, real chart adapter and chart mount (echarts mocked
// as in price-bands.test.ts); only the WebSocket is a fake that answers in the backend's shapes.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';

const charts = [];
vi.mock('echarts/core', () => ({
  use: () => {},
  graphic: { clipRectByRect: r => r, clipPointsByRect: p => p, LinearGradient: class {} },
  init: dom => {
    const chart = { dom, options: [], setOption(o) { this.options.push(o); }, getOption() { const o = this.options.at(-1); return { ...o, dataZoom: [{ startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }] }; },
      on() {}, off() {}, dispatchAction() {}, getDom: () => dom, getWidth: () => 800, resize() {}, dispose() {}, convertToPixel: (_, v) => v, convertFromPixel: (_, v) => v };
    charts.push(chart);
    return chart;
  },
}));
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));

import { mountCharts } from '../shared-dashboard/charts.js';
import { createPriceDays, mergePriceRows, addDays, PAGE_DAYS } from '../shared-dashboard/price-days.js';
import { renderPriceNav } from '../shared-dashboard/price-nav-view.js';
import { publishedChart, localDaySpan } from '../sidebar/price-chart.js';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { createSampleAdapter } from '../prototype/sample-adapter.js';

const ZONE = 'Europe/Stockholm', TODAY = '2026-11-16';
const ctx = (over = {}) => ({ charger: 'c1', epoch: '1:0', area: 'SE4', currency: 'SEK', today: TODAY, span: d => localDaySpan(d, ZONE), waitingForTomorrow: true, ...over });
const hourRows = (day, hours = 24, price = 1) => Array.from({ length: hours }, (_, i) => { const s = localDaySpan(day, ZONE)[0] + i * 3600000; return { start: new Date(s).toISOString(), end: new Date(s + 3600000).toISOString(), raw_price: price + i / 100 }; });
const facts = (day, over = {}) => ({ day, state: 'ready', complete: true, resolution_minutes: 60, source: 'network', fetched_at: `${day}T20:00:00+00:00`, interval_count: 24, ...over });

/** A fake backend: held days with rows; every request is logged; `gate` holds answers until released. */
function backend(held, over = {}) {
  const log = [], waiting = [];
  const answer = params => {
    const base = { api_version: 1, charger_id: 'c1', area_id: 'SE4', zone: ZONE, currency: 'SEK', today: TODAY, ...over };
    if (params.mode === 'available') return { ...base, mode: 'available', yesterday_reachable: true, days: [...held.keys()].sort().reverse().map(d => facts(d, held.get(d).facts)), oldest: null, newest: null };
    const days = [];
    for (let d = params.from; d <= params.to; d = addDays(d, 1)) {
      const item = held.get(d);
      days.push(item ? { ...facts(d, item.facts), held: true, provenance: [], reason: null, intervals: item.rows } : { day: d, held: false, state: 'unavailable', complete: false, resolution_minutes: null, source: null, fetched_at: null, interval_count: null, provenance: [], reason: 'not_held', intervals: null });
    }
    return { ...base, mode: 'range', from: params.from, to: params.to, days };
  };
  const request = params => { log.push(params); if (!backend.gate) return Promise.resolve(answer(params)); return new Promise((resolve, reject) => waiting.push(() => { try { resolve(answer(params)); } catch (e) { reject(e); } })); };
  return { request, log, waiting, answer };
}
const settle = () => new Promise(r => setTimeout(r, 0));
const held = days => new Map(days.map(([d, o = {}]) => [d, { rows: hourRows(d, o.hours ?? 24), facts: o.facts || {} }]));
const live = () => [...hourRows(TODAY), ...hourRows(addDays(TODAY, 1), 0)];

async function ready(map, options = {}) {
  const api = backend(map, options.backend);
  let changes = 0;
  const nav = createPriceDays({ request: api.request, onChange: () => { changes++; } });
  nav.sync(ctx(options.ctx));
  await settle();
  return { api, nav, changes: () => changes };
}
beforeEach(() => { backend.gate = false; globalThis.ResizeObserver = class { observe() {} disconnect() {} }; document.body.innerHTML = ''; charts.length = 0; });

describe('merging rows by actual instant', () => {
  const r = (s, e, p = 1) => ({ start: s, end: e, raw_price: p });
  it('drops identical duplicates, even spelled with another offset, and keeps real gaps as gaps', () => {
    const a = r('2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'), same = r('2026-10-25T02:00:00+02:00', '2026-10-25T03:00:00+02:00');
    const later = r('2026-10-25T05:00:00Z', '2026-10-25T06:00:00Z', null);
    const merged = mergePriceRows([a, later], [same, a]);
    expect(merged.rows).toEqual([a, later]); // the 01:00-05:00 gap is not filled with rows or zeros
  });
  it('refuses a conflict, an overlap and a malformed row instead of choosing', () => {
    const base = r('2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z', 1);
    expect(mergePriceRows([base], [{ ...base, raw_price: 2 }]).error).toBe('conflict');
    expect(mergePriceRows([base], [r('2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z')]).error).toBe('overlap');
    expect(mergePriceRows([{ ...base, raw_price: NaN }]).error).toBe('malformed');
    expect(mergePriceRows([r('2026-10-25T01:00:00Z', '2026-10-25T01:00:00Z')]).error).toBe('malformed');
  });
});

describe('availability and buttons', () => {
  it('reads only the small availability metadata until the user navigates', async () => {
    const { api, nav } = await ready(held([['2026-11-15'], ['2026-11-10'], ['2026-11-01', { hours: 12, facts: { complete: false } }]]));
    expect(api.log).toEqual([{ mode: 'available' }]);
    const view = nav.view(live());
    expect(view.rows).toEqual(live()); // default is the dashboard's own feed
    expect(view.viewKey).toBe('today::0');
    expect(view.range).toBeNull();
    nav.sync(ctx()); nav.sync(ctx()); nav.view(live());
    expect(api.log).toHaveLength(1); // routine refreshes ask for nothing
  });
  it('enables held days, labels a partial day and says why the others are disabled', async () => {
    const { nav } = await ready(held([['2026-11-15', { facts: { complete: false } }], ['2026-11-10']]));
    const buttons = Object.fromEntries(nav.view(live()).nav.buttons.map(b => [b.id, b]));
    expect(buttons.yesterday).toMatchObject({ enabled: true, partial: true });
    expect(buttons.tomorrow).toMatchObject({ enabled: false, reason: 'Tomorrow’s prices are not published yet.' });
    expect(buttons.earlier.enabled).toBe(true);
    expect(buttons.all.enabled).toBe(true);
    const html = renderPriceNav(nav.view(live()).nav);
    expect(html).toContain('Yesterday (partial)');
    expect(html).toMatch(/data-price-nav="tomorrow" disabled/);
    expect(html).toContain('Tomorrow: Tomorrow’s prices are not published yet.'); // the reason is text, not only a tooltip
  });
  it('disables a missing yesterday with the provider-reach reason and an empty Earlier', async () => {
    const { nav } = await ready(held([]), { backend: {} });
    const view = nav.view(live());
    const buttons = Object.fromEntries(view.nav.buttons.map(b => [b.id, b]));
    expect(buttons.yesterday).toMatchObject({ enabled: false, reason: 'Yesterday’s prices are not held.' });
    expect(buttons.earlier).toMatchObject({ enabled: false, reason: 'No earlier prices are held.' });
  });
  it('enables Tomorrow only when the live feed really holds tomorrow rows', async () => {
    const { nav } = await ready(held([]));
    const both = [...hourRows(TODAY), ...hourRows('2026-11-17', 24, 2)];
    expect(nav.view(both).nav.buttons.find(b => b.id === 'tomorrow').enabled).toBe(true);
    nav.select('tomorrow');
    expect(nav.view(both).range).toEqual(localDaySpan('2026-11-17', ZONE));
  });
  it('reports a read failure as an error with an explicit retry and no hidden request loop', async () => {
    const api = backend(held([['2026-11-15']]));
    let fail = true;
    const nav = createPriceDays({ request: p => { if (fail) { api.log.push(p); return Promise.reject(new Error('x')); } return api.request(p); }, onChange: () => {} });
    nav.sync(ctx()); await settle();
    for (let i = 0; i < 5; i++) nav.sync(ctx());
    await settle();
    expect(api.log).toHaveLength(1);
    const view = nav.view(live());
    expect(view.nav).toMatchObject({ status: 'error', canRetry: true });
    expect(view.nav.buttons.find(b => b.id === 'yesterday')).toMatchObject({ enabled: false, reason: 'Held days could not be read.' });
    fail = false; nav.retry(); await settle();
    expect(nav.view(live()).nav.buttons.find(b => b.id === 'yesterday').enabled).toBe(true);
  });
});

describe('bounded pages', () => {
  const days = Array.from({ length: 30 }, (_, i) => [addDays('2026-10-15', i)]);
  it('Earlier loads one page of at most eight days ending at the chosen day and All loaded days spans only that page', async () => {
    const { api, nav } = await ready(held(days));
    nav.select('day', '2026-11-05'); await settle();
    const request = api.log.at(-1);
    expect(request).toEqual({ mode: 'range', from: addDays('2026-11-05', 1 - PAGE_DAYS), to: '2026-11-05' });
    expect(api.log.filter(p => p.mode === 'range')).toHaveLength(1);
    const view = nav.view(live());
    expect(view.range).toEqual(localDaySpan('2026-11-05', ZONE));
    expect(view.nav.selected).toBe('day');
    nav.select('all');
    const all = nav.view(live());
    expect(all.rows).toHaveLength(8 * 24 + 24);
    expect(all.range).toEqual([Date.parse(all.rows[0].start), Date.parse(all.rows.at(-1).end)]);
    expect(all.nav.detail).toMatch(/Not the full price history/);
    expect(api.log.filter(p => p.mode === 'range')).toHaveLength(1); // no further load
  });
  it('lists only held dates older than yesterday in the picker, including partial ones', async () => {
    const { nav } = await ready(held([['2026-11-15'], ['2026-11-10', { facts: { complete: false } }], ['2026-11-02']]));
    nav.select('earlier');
    const picker = nav.view(live()).nav.earlier;
    expect(picker.open).toBe(true);
    expect(picker.days.map(d => d.day)).toEqual(['2026-11-10', '2026-11-02']);
    expect(picker.days[0].partial).toBe(true);
    expect(renderPriceNav(nav.view(live()).nav)).toContain('· partial');
  });
  it('shows a held partial day with its label and provenance, and a held day it cannot price as not drawn', async () => {
    const map = held([['2026-11-15', { hours: 10, facts: { complete: false, interval_count: 10 } }]]);
    const { api, nav } = await ready(map);
    nav.select('yesterday'); await settle();
    const view = nav.view(live());
    expect(view.nav.detail).toMatch(/partial: the held prices cover only part of this day/);
    expect(view.nav.detail).toMatch(/10 intervals of 60 min · source network · fetched/);
    expect(view.rows.filter(r => Date.parse(r.start) < Date.parse(live()[0].start))).toHaveLength(10); // a partial day stays 10 rows, not 24
    expect(api.log.at(-1).to).toBe('2026-11-15');
  });
  it('merges by instant and drops identical duplicates between the page and the live feed; a conflict refuses the page', async () => {
    const { nav } = await ready(held([['2026-11-15']]));
    nav.select('yesterday'); await settle();
    const overlapping = [...hourRows('2026-11-15').slice(20), ...live()];
    expect(nav.view(overlapping).rows).toHaveLength(24 + 24); // 4 identical overlapping rows dropped once
    const conflicting = [{ ...hourRows('2026-11-15')[20], raw_price: 99 }, ...live()];
    const view = nav.view(conflicting);
    expect(view.nav.message).toMatch(/overlap or conflict/);
    expect(view.rows).toEqual(conflicting); // the page is gone, the live feed alone remains
    expect(view.nav.selected).toBe('today');
  });
  it('keeps 23- and 25-hour days and mixed 15-minute/hourly rows as real intervals', async () => {
    const short = localDaySpan('2026-03-29', ZONE), long = localDaySpan('2026-10-25', ZONE);
    expect((short[1] - short[0]) / 3600000).toBe(23);
    expect((long[1] - long[0]) / 3600000).toBe(25);
    const quarter = Array.from({ length: 4 }, (_, i) => ({ start: new Date(long[0] + i * 900000).toISOString(), end: new Date(long[0] + (i + 1) * 900000).toISOString(), raw_price: 1 }));
    const hourly = hourRows('2026-10-25', 25).slice(1);
    const merged = mergePriceRows(quarter, hourly.map(r => r)).rows; // hourly starts at +1h, so the 15-minute hour is not overlapped
    expect(merged).toHaveLength(4 + 24);
    const { chart } = publishedChart({ prices: { published_intervals: merged } }, { timezone: ZONE, currency: 'SEK' }, long[0], false);
    expect(chart.prices[0].end - chart.prices[0].start).toBe(900000);
    expect(chart.prices.at(-1).end - chart.prices.at(-1).start).toBe(3600000);
  });
});

describe('stale and changed context', () => {
  it('discards a late answer after a charger, area, currency or generation change', async () => {
    for (const change of [{ charger: 'c2' }, { area: 'SE3' }, { currency: 'EUR' }, { epoch: '2:0' }]) {
      backend.gate = true;
      const api = backend(held([['2026-11-15']]));
      let changes = 0;
      const nav = createPriceDays({ request: api.request, onChange: () => { changes++; } });
      nav.sync(ctx());
      nav.sync(ctx(change)); // the old availability request is still in flight
      api.waiting[0](); await settle(); // only the answer to the old context arrives
      expect(changes).toBe(0);
      expect(nav.view(live()).nav.buttons.find(b => b.id === 'yesterday').enabled).toBe(false); // nothing of the old market leaked in
    }
  });
  it('drops loaded pages and the selection when the market changes, and ignores a page answer that arrives afterwards', async () => {
    const { api, nav } = await ready(held([['2026-11-15'], ['2026-11-10']]));
    nav.select('yesterday'); await settle();
    expect(nav.view(live()).rows.length).toBeGreaterThan(24);
    backend.gate = true;
    nav.select('day', '2026-11-10');
    nav.sync(ctx({ currency: 'EUR' }));
    backend.gate = false;
    api.waiting.forEach(release => release()); await settle();
    const view = nav.view(live());
    expect(view.rows).toEqual(live());
    expect(view.nav.selected).toBe('today');
  });
  it('refuses answers whose context or range is not what was asked', async () => {
    for (const bad of [{ charger_id: 'other' }, { area_id: 'SE3' }, { currency: 'EUR' }, { api_version: 2 }]) {
      const { nav } = await ready(held([['2026-11-15']]), { backend: bad });
      expect(nav.view(live()).nav.status).toBe('error');
    }
    const api = backend(held([['2026-11-15'], ['2026-11-10']]));
    const nav = createPriceDays({ request: async p => p.mode === 'range' ? { ...api.answer(p), to: '2026-11-14' } : api.answer(p), onChange: () => {} });
    nav.sync(ctx()); await settle();
    nav.select('yesterday'); await settle();
    const view = nav.view(live());
    expect(view.nav).toMatchObject({ status: 'error', canRetry: true });
    expect(view.nav.selected).toBe('today');
  });
  it('a failed page keeps the current page and offers an explicit retry that asks once', async () => {
    const api = backend(held([['2026-11-15']]));
    let fail = false;
    const nav = createPriceDays({ request: p => (fail && p.mode === 'range' ? (api.log.push(p), Promise.reject(new Error('x'))) : api.request(p)), onChange: () => {} });
    nav.sync(ctx()); await settle();
    fail = true; nav.select('yesterday'); await settle();
    for (let i = 0; i < 4; i++) { nav.sync(ctx()); nav.view(live()); }
    expect(api.log.filter(p => p.mode === 'range')).toHaveLength(1);
    expect(nav.view(live()).nav).toMatchObject({ status: 'error', canRetry: true });
    fail = false; nav.retry(); await settle();
    expect(nav.view(live()).nav.selected).toBe('yesterday');
  });
});

describe('chart range intent', () => {
  const root = () => { const el = document.createElement('div'); el.innerHTML = '<div id="price-step"></div><button data-reset="step"></button><button data-zoom="step"></button>'; document.body.append(el); return el; };
  const mount = (view, rows) => {
    const built = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'SEK' }, Date.parse(rows[0].start) + 3 * 3600000, false, view);
    return { built, handle: mountCharts(root(), { ...built.chart, windows: [], deadline: null }, built.format, ['step']) };
  };
  it('a routine refresh keeps the user’s zoom and only a new navigation key sets a new range', () => {
    const rows = [...hourRows('2026-11-15'), ...hourRows(TODAY)];
    const first = mount({ key: 'yesterday:2026-11-15:1', range: localDaySpan('2026-11-15', ZONE) }, rows);
    const chart = charts[0];
    const option = () => chart.options.at(-1).dataZoom[0];
    expect([option().startValue, option().endValue]).toEqual(first.built.format.snapRange(...localDaySpan('2026-11-15', ZONE)));
    option().startValue += 6 * 3600000; // the user zoomed in
    const zoomed = [option().startValue, option().endValue];
    for (let i = 0; i < 3; i++) { const again = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'SEK' }, Date.parse(rows[0].start) + (4 + i) * 3600000, false, { key: 'yesterday:2026-11-15:1', range: localDaySpan('2026-11-15', ZONE) }); first.handle.update({ ...again.chart, windows: [] }, again.format); }
    expect([option().startValue, option().endValue]).toEqual(zoomed);
    const next = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'SEK' }, Date.parse(rows[0].start), false, { key: 'day:2026-11-16:2', range: localDaySpan(TODAY, ZONE) });
    first.handle.update({ ...next.chart, windows: [] }, next.format);
    expect([option().startValue, option().endValue]).toEqual(next.format.snapRange(...localDaySpan(TODAY, ZONE)));
  });
  it('the default view keeps the existing now-based range and key', () => {
    const rows = hourRows(TODAY);
    const { chart, format } = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'SEK' }, Date.parse(rows[5].start), false);
    expect(chart.viewKey).toBe('default');
    expect(format.initialRange(Date.parse(rows[5].start))[0]).toBe(Date.parse(rows[4].start));
  });
  it('an incomplete day stays a price gap, not a zero row', () => {
    const rows = [...hourRows('2026-11-15', 10), ...hourRows(TODAY, 2)];
    const { chart, format } = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'SEK' }, Date.parse(rows[0].start), false);
    expect(chart.prices).toHaveLength(12);
    expect(format.priceGaps(chart.horizon[0], chart.horizon[1], chart.prices).length).toBe(1);
    expect(chart.prices.every(p => p.cents > 0)).toBe(true);
  });
  it('keeps the Stage 18 absolute bands and 0..30 axis on a navigated page, and converts EUR exactly once', () => {
    const rows = hourRows('2026-11-15', 4, 0.02).map(r => ({ ...r, raw_price: 0.02 }));
    const { chart } = publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'EUR' }, Date.parse(rows[0].start), false, { key: 'yesterday:x:1', range: null });
    expect(chart.prices.map(p => p.cents)).toEqual([2, 2, 2, 2]);
    const handle = mountCharts(root(), { ...chart, windows: [], deadline: null }, publishedChart({ prices: { published_intervals: rows } }, { timezone: ZONE, currency: 'EUR' }, Date.parse(rows[0].start), false).format, ['step']);
    const y = charts.at(-1).options.at(-1).yAxis;
    expect([y.min, y.max]).toEqual([0, 30]);
    handle.dispose();
  });
});

describe('local day spans', () => {
  it('follow the price area zone rules, not UTC or the host', () => {
    expect(localDaySpan('2026-10-25', ZONE).map(ms => new Date(ms).toISOString())).toEqual(['2026-10-24T22:00:00.000Z', '2026-10-25T23:00:00.000Z']);
    expect(localDaySpan('2026-03-29', ZONE).map(ms => new Date(ms).toISOString())).toEqual(['2026-03-28T23:00:00.000Z', '2026-03-29T22:00:00.000Z']);
    expect(localDaySpan('2026-13-45', ZONE)).toBeNull();
    expect(localDaySpan('2026-11-16', 'Not/AZone')).toBeNull();
  });
});

describe('live adapter and preview use one nav shape', () => {
  const sampleNav = async () => {
    let latest;
    const adapter = createSampleAdapter(next => { latest = next; });
    await settle();
    return { adapter, current: () => latest || adapter };
  };
  it('the preview builds its nav from the same state machine and fixture shapes, and navigating changes only the range intent', async () => {
    const { current } = await sampleNav();
    expect(current().model.priceNav.buttons.map(b => b.id)).toEqual(['yesterday', 'today', 'tomorrow', 'earlier', 'all']);
    expect(current().model.chart.viewKey).toBe('today::0');
    current().actions.priceNav('earlier');
    await settle();
    expect(current().model.priceNav.earlier.days.map(d => d.day)).toContain('2026-11-07');
    current().actions.priceNav('day', '2026-11-05');
    await settle();
    expect(current().model.chart.viewKey).toMatch(/^day:2026-11-05:/);
    expect(current().model.chart.horizon[0]).toBeLessThan(-24); // earlier held days joined the sample horizon
    expect(current().model.chart.prices.some(p => p.cents <= 0)).toBe(false);
  });
  it('the live adapter hands the navigated rows to the one chart adapter and keeps the default feed otherwise', () => {
    const now = Date.now();
    const base = () => { const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8')); raw.generated_at = new Date(now).toISOString(); return raw; };
    const raw = base();
    const zone = raw.market.timezone;
    const day = new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(now);
    const today = hourRows(day).map(r => ({ ...r })), yesterday = hourRows(addDays(day, -1));
    raw.prices.published_intervals = today;
    const view = { rows: [...yesterday, ...today], range: [Date.parse(yesterday[0].start), Date.parse(yesterday.at(-1).end)], viewKey: 'yesterday:x:1', nav: { buttons: [] } };
    const navigated = dashboardAdapter(raw, null, null, now, false, false, view);
    const plain = dashboardAdapter(raw, null, null, now, false, false, null);
    expect(navigated.model.chart.prices).toHaveLength(48);
    expect(navigated.model.chart.viewKey).toBe('yesterday:x:1');
    expect(navigated.format.initialRange(now)[0]).toBe(Date.parse(yesterday[0].start));
    expect(plain.model.chart.prices).toHaveLength(24);
    expect(plain.model.chart.viewKey).toBe('default');
    expect(plain.model.priceNav).toBeNull();
  });
});
