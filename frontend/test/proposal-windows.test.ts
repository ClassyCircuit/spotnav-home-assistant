// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.5: proposed-windows card and read-only chart linkage. ECharts is mocked (no canvas); this checks the model, the
// markup, the selection rules and that navigating the list never triggers an action. No browser check is implied.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';

const charts = [];
vi.mock('echarts/core', async () => {
  const actual = await vi.importActual('echarts/core');
  return { use: () => {}, graphic: actual.graphic, init: dom => {
    const chart = { dom, options: [], actions: [], zoom: null, disposed: false,
      setOption(o) { this.options.push(o); if (o.dataZoom) this.zoom = { startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }; },
      getOption() { return { ...this.options.at(-1), dataZoom: [{ ...this.zoom }] }; }, on() {}, off() {},
      dispatchAction(a) { this.actions.push(a); if (a.type === 'dataZoom' && a.startValue != null) this.zoom = { startValue: a.startValue, endValue: a.endValue }; },
      getDom: () => dom, getWidth: () => 800, resize() {}, dispose() { this.disposed = true; },
      convertToPixel: (_, v) => v / 60000, convertFromPixel: (_, v) => v * 60000 };
    charts.push(chart); return chart;
  } };
});
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype, 'validity', { get: () => ({ valid: true }) });
Object.defineProperty(ElementInternals.prototype, 'validationMessage', { get: () => '' });
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

import { dashboardAdapter } from '../sidebar/adapter.js';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { localDaySpan } from '../sidebar/price-chart.js';
import { buildWindowsModel, resolveSelection, windowsStatus, windowsAt } from '../shared-dashboard/windows-model.js';
import { renderWindows } from '../shared-dashboard/windows-view.js';

const ZONE = 'Europe/Stockholm';
const H = 3600000;
const status = { api_version: 1, schedule: { supported: false, verified: false, sent: null, sent_at: null, ack: null, effective: null } };
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: ZONE }).format(new Date());
const priceRows = day => Array.from({ length: 24 }, (_, i) => { const s = localDaySpan(day, ZONE)[0] + i * H; return { start: new Date(s).toISOString(), end: new Date(s + H).toISOString(), raw_price: 1 + i / 10, price: 1 + i / 10 }; });
const iso = ms => new Date(ms).toISOString();

// Windows are built relative to now so the proposal is current; `spans` are [startHoursFromBase, endHoursFromBase].
const BASE = Math.ceil(Date.now() / H) * H + H;
function build({ spans = [[0, 1], [3, 4], [6, 8]], identity = 'p1', details = true, basis = true, codes = null, draftKey = 'a:1', prices = true, priceView = null, now = Date.now() } = {}) {
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date(now).toISOString();
  if (prices) raw.prices.published_intervals = Array.from({ length: 36 }, (_, i) => { const a = BASE - 2 * H + i * H; return { start: iso(a), end: iso(a + H), raw_price: 1 + i / 10, price: 1 + i / 10 }; });
  const periods = spans.map(([a, b]) => ({ start: iso(BASE + a * H), end: iso(BASE + b * H) }));
  const rows = spans.map(([a, b], i) => ({ start: iso(BASE + a * H), end: iso(BASE + b * H), energy_kwh: 2 + i, cost: 1.5 + i }));
  const kwh = rows.reduce((s, r) => s + r.energy_kwh, 0), cost = rows.reduce((s, r) => s + r.cost, 0);
  Object.assign(raw.plan.proposal, { identity, periods, planned_kwh: kwh, cost: { currency: 'SEK', value: cost }, unpriced: false });
  if (details) raw.plan.proposal.window_details = rows;
  if (basis) raw.plan.proposal.cost_basis = 'configured_variable_cost';
  if (codes) raw.plan.price_policy = { ...(raw.plan.price_policy || {}), explanations: codes.map(code => ({ code })) };
  const adapter = dashboardAdapter(raw, status, now, now, false, false, priceView);
  adapter.draftKey = draftKey;
  return adapter;
}
const actions = () => ({ refresh: vi.fn(), save: vi.fn(), selectCharger: vi.fn(), chargeNow: vi.fn(), priceNav: vi.fn(), historyNav: vi.fn(), insightNav: vi.fn(), menu: vi.fn() });
const mount = adapter => { const root = document.createElement('main'); document.body.append(root); return { root, view: mountDashboard(root, adapter) }; };
const card = root => root.querySelector('section.windows');
const rowsOf = root => [...card(root).querySelectorAll('li.win-row')];
const click = node => node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
const selectBtn = (root, i) => rowsOf(root)[i].querySelector('.win-select');
const fmt = ms => new Intl.DateTimeFormat('en', { timeStyle: 'short', timeZone: ZONE }).format(ms);

describe('card content', () => {
  it('lists every window in proposal order with exact local times, durations and honest basis', () => {
    const { root } = mount(build({ spans: [[0, 1], [3, 4.5], [6, 8], [10, 11], [12, 13], [14, 15], [16, 17], [18, 19]] }));
    const rows = rowsOf(root);
    expect(rows).toHaveLength(8);
    expect(card(root).querySelector('.win-count').textContent).toBe('8 windows');
    expect(rows[1].querySelector('.win-time b').textContent).toBe(`${fmt(BASE + 3 * H)}–${fmt(BASE + 4.5 * H)}`);
    expect(rows[1].querySelector('.win-dur').textContent).toBe('1 h 30 min');
    expect(rows.map(r => r.querySelector('.win-ord').textContent)).toEqual(['01', '02', '03', '04', '05', '06', '07', '08']);
    expect(card(root).querySelector('.win-scroll').getAttribute('aria-label')).toBe('Proposed windows, 8 windows in total');
    expect(rows[0].querySelector('[data-tag="next"]')).not.toBeNull();
    expect(card(root).querySelector('.win-head').dataset.winStatus).toBe('proposed');
    expect(card(root).querySelector('.win-separation').textContent).toContain('Proposal only');
    expect(card(root).querySelector('#window-evidence-help').textContent).toContain('Whether it was sent, acknowledged or is in effect');
    expect(card(root).textContent).not.toMatch(/Acknowledged|Confirmed/);
  });
  it('shows energy and cost only where the validated details and basis permit', () => {
    const ok = mount(build()).root;
    expect(rowsOf(ok)[0].querySelector('.win-facts').textContent).toMatch(/2\.00 kWh.*1\.50 SEK/);
    const noDetails = mount(build({ details: false })).root;
    const facts = rowsOf(noDetails)[0].querySelector('.win-facts');
    expect(facts.textContent).not.toMatch(/kWh|SEK/);
    expect([...facts.querySelectorAll('.win-na')].length).toBeGreaterThanOrEqual(3);
    expect(card(noDetails).querySelector('.win-details-note').textContent).toMatch(/details are missing/);
    const noBasis = mount(build({ basis: false })).root;
    const f2 = rowsOf(noBasis)[0].querySelector('.win-facts').textContent;
    expect(f2).toMatch(/2\.00 kWh/); expect(f2).not.toMatch(/SEK/);
    expect(card(noBasis).querySelector('.win-details-note').textContent).toMatch(/cost basis or currency is unknown/);
  });
  it('keeps provisional, constrained, no-need, unstated-empty, stale and unavailable distinct', () => {
    const none = { windows: [], knownPlan: true };
    expect(windowsStatus({ ...none, count: 0, context: { codes: ['target_met'] } })).toBe('noneed');
    expect(windowsStatus({ ...none, count: 0, context: { codes: ['minimum_shortfall'] } })).toBe('constrained');
    expect(windowsStatus({ ...none, count: 0, context: { codes: ['block_limit', 'target_met'] } })).toBe('constrained');
    expect(windowsStatus({ ...none, count: 0, context: { codes: [] } })).toBe('empty');
    expect(windowsStatus({ ...none, count: 0, context: { codes: ['error'] } })).toBe('unavailable');
    expect(windowsStatus({ knownPlan: true, count: 2, context: { provisional: true } })).toBe('provisional');
    expect(windowsStatus({ knownPlan: false, stale: true, count: 0 })).toBe('stale');
    expect(windowsStatus({ knownPlan: false, stale: false, count: 0 })).toBe('unavailable');
    const f = build().format;
    const empty = buildWindowsModel({ windows: [], knownPlan: true, totals: undefined, context: { codes: ['target_met'] }, format: f, draftKey: 'a' });
    const html = document.createElement('div'); html.innerHTML = renderWindows(empty, { f, assumptions: {}, selected: null, notice: '' });
    expect(html.textContent).toMatch(/No charging needed/); expect(html.textContent).not.toMatch(/Error/i);
    expect(html.querySelectorAll('li').length).toBe(0);
    const stale = buildWindowsModel({ windows: null, knownPlan: false, stale: true, context: null, format: f, draftKey: 'a' });
    html.innerHTML = renderWindows(stale, { f, assumptions: {}, selected: null, notice: '' });
    expect(html.textContent).toMatch(/Stale proposal/); expect(html.querySelectorAll('li').length).toBe(0);
  });
  it('mounts a zero-window current proposal as an empty list, not an error', () => {
    const { root } = mount(build({ spans: [], codes: ['target_met'] }));
    expect(rowsOf(root)).toHaveLength(0);
    expect(card(root).querySelector('.win-head').dataset.winStatus).toBe('noneed');
    expect(card(root).querySelector('.win-count').textContent).toBe('0 windows');
  });
  it('shows an unexplained invalid window as received and never selectable', () => {
    const f = build().format;
    const model = buildWindowsModel({ windows: [{ start: 5, end: 5 }, { start: NaN, end: 9 }, { start: BASE, end: BASE + H }], knownPlan: true, context: null, format: f, draftKey: 'a', totals: undefined });
    expect(model.count).toBe(3); expect(model.rows.map(r => r.valid)).toEqual([false, false, true]);
    expect(model.totalMinutes).toBeNull();
    const d = document.createElement('div'); d.innerHTML = renderWindows(model, { f, assumptions: {}, selected: null, notice: '' });
    expect(d.querySelectorAll('.win-invalid')).toHaveLength(2);
    expect(d.querySelectorAll('[data-win-select]')).toHaveLength(1);
    expect(d.textContent).toMatch(/Interval unavailable/);
  });
});

describe('cross-day and DST', () => {
  const f = build().format;
  const model = windows => buildWindowsModel({ windows, knownPlan: true, context: null, format: f, draftKey: 'a', totals: undefined });
  it('marks a window across local midnight with both dates and keeps its elapsed duration', () => {
    const midnight = localDaySpan('2026-11-20', ZONE)[0];
    const m = model([{ start: midnight - H, end: midnight + H }, { start: midnight - 2 * H, end: midnight }]);
    expect(m.rows[0].crosses).toBe(true); expect(m.rows[0].minutes).toBe(120);
    expect(m.rows[1].crosses).toBe(false);   // ending exactly at midnight stays on its own day
  });
  it('shows offsets across the autumn change and for a repeated local hour, using real elapsed time', () => {
    const t = Date.UTC(2026, 9, 25, 0, 30);               // 02:30 CEST
    const across = model([{ start: t, end: t + 2 * H }]);  // 02:30 CEST to 03:30 CET
    expect(across.rows[0].minutes).toBe(120);
    expect(across.rows[0].startOffset).toBe('GMT+2'); expect(across.rows[0].endOffset).toBe('GMT+1');
    const repeated = model([{ start: t, end: t + H / 2 }, { start: t + H, end: t + 1.5 * H }]);
    expect(repeated.rows.map(r => [r.startText, r.startOffset])).toEqual([['2:30 AM', 'GMT+2'], ['2:30 AM', 'GMT+1']]);
    const { offset, ...noOffset } = f;
    const bare = buildWindowsModel({ windows: [{ start: t, end: t + H / 2 }, { start: t + H, end: t + 1.5 * H }], knownPlan: true, context: null, format: noOffset, draftKey: 'a', totals: undefined });
    expect(bare.rows.every(r => r.repeatedHour && r.startOffset === null)).toBe(true);
  });
  it('spring change: a 02:00-04:00 span is one real hour', () => {
    const start = Date.UTC(2026, 2, 29, 0, 30), end = Date.UTC(2026, 2, 29, 1, 30); // 01:30 CET to 03:30 CEST
    expect(model([{ start, end }]).rows[0].minutes).toBe(60);
  });
});

describe('selection and chart linkage', () => {
  it('selects by exact interval, highlights the chart span and lane, and sends nothing', () => {
    charts.length = 0;
    const adapter = build(); const act = actions(); adapter.actions = act;
    const { root } = mount(adapter);
    click(selectBtn(root, 1));
    expect(rowsOf(root)[1].dataset.selected).toBe('true');
    expect(selectBtn(root, 1).getAttribute('aria-pressed')).toBe('true');
    expect(card(root).querySelector('.win-selection').textContent).toMatch(/Window 2 selected/);
    // the same render also drew the highlight in the chart overlay and the proposal lane at the exact interval
    const spans = [...root.querySelectorAll('.proposal-selected, .track-selected')];
    expect(spans.length).toBeGreaterThan(0);
    for (const s of spans) { expect(Number(s.dataset.start)).toBe(BASE + 3 * H); expect(Number(s.dataset.end)).toBe(BASE + 4 * H); }
    click(selectBtn(root, 1));
    expect(rowsOf(root)[1].dataset.selected).toBe('false');
    expect(root.querySelector('.proposal-selected')).toBeNull();
    for (const fn of Object.values(act)) expect(fn).not.toHaveBeenCalled();
  });
  it('offers chart-to-list navigation and retains focus after selecting a window', () => {
    const { root } = mount(build());
    click(root.querySelector('[data-chart-windows]'));
    expect(root.activeElement || document.activeElement).toBe(selectBtn(root, 0));
    click(selectBtn(root, 0));
    expect(root.activeElement || document.activeElement).toBe(selectBtn(root, 0));
  });
  it('shows the window on the chart without changing anything else and keeps the selection through zoom', () => {
    charts.length = 0;
    const { root } = mount(build());
    const chart = charts.find(c => /^price-/.test(c.dom.id));
    click(selectBtn(root, 2));
    const btn = root.querySelector('#win-show-chart');
    expect(btn, 'window 3 is on the drawn chart day').not.toBeNull();
    click(btn);
    const zoom = chart.actions.filter(a => a.type === 'dataZoom').at(-1);
    expect(zoom.startValue).toBeLessThanOrEqual(BASE + 6 * H); expect(zoom.endValue).toBeGreaterThanOrEqual(BASE + 8 * H);
    expect(rowsOf(root)[2].dataset.selected).toBe('true');
  });
  it('keeps the selection across a refresh of the same proposal and clears it, with a message, when the proposal changes', () => {
    const { root, view } = mount(build());
    click(selectBtn(root, 0));
    view.update(build());                                          // routine refresh, same identity and intervals
    expect(rowsOf(root)[0].dataset.selected).toBe('true');
    view.update(build({ identity: 'p2' }));                        // new identity: never keep a "similar" row
    expect(rowsOf(root).every(r => r.dataset.selected === 'false')).toBe(true);
    expect(card(root).querySelector('[data-win-notice="cleared"]').textContent).toMatch(/proposal changed.*Nothing was sent or replanned/);
    click(selectBtn(root, 1));
    view.update(build({ spans: [[0, 1], [3.5, 4], [6, 8]] }));     // same identity, interval moved by 30 min
    expect(rowsOf(root).every(r => r.dataset.selected === 'false')).toBe(true);
    expect(card(root).querySelector('[data-win-notice="cleared"]')).not.toBeNull();
    click(selectBtn(root, 0));                                     // a new explicit selection removes the notice
    expect(card(root).querySelector('[data-win-notice="cleared"]')).toBeNull();
  });
  it('clears silently on a charger change and never carries rows or selection across', () => {
    const { root, view } = mount(build());
    click(selectBtn(root, 0));
    view.update(build({ draftKey: 'b:2', spans: [[1, 2]], identity: 'other' }));
    expect(rowsOf(root)).toHaveLength(1);
    expect(rowsOf(root)[0].dataset.selected).toBe('false');
    expect(card(root).querySelector('[data-win-notice="cleared"]')).toBeNull();
    expect(root.querySelector('.proposal-selected')).toBeNull();
  });
  it('turns a selected window into a stale message when the proposal expires', () => {
    const { root, view } = mount(build());
    click(selectBtn(root, 0));
    view.update(build({ now: BASE + 20 * H }));                    // every window has ended: stale, list unavailable
    expect(card(root).querySelector('.win-head').dataset.winStatus).toBe('stale');
    expect(rowsOf(root)).toHaveLength(0);
    expect(card(root).textContent).toMatch(/no longer current|Stale proposal/);
  });
  it('offers only enabled other price days when the window is off the chart, and only asks the host to show a day', () => {
    const nav = { selected: 'today', selectedDay: null, status: 'ready', message: '', canRetry: false, detail: '', earlier: { open: false, days: [], hint: '' }, buttons: [
      { id: 'yesterday', label: 'Yesterday', enabled: false, reason: 'Not held.' }, { id: 'today', label: 'Today', enabled: true, selected: true },
      { id: 'tomorrow', label: 'Tomorrow', enabled: true }, { id: 'all', label: 'All loaded days', enabled: true }] };
    const adapter = build({ spans: [[0, 1], [60, 61]], priceView: { nav, viewKey: 'today', range: null } }); const act = actions(); adapter.actions = act;
    const { root } = mount(adapter);
    const off = rowsOf(root)[1]; expect(off.querySelector('[data-tag="off-chart"]')).not.toBeNull();
    click(off.querySelector('.win-select'));
    const jump = card(root).querySelector('[data-win-jump]');
    expect(jump).not.toBeNull();
    expect([...jump.querySelectorAll('[data-win-nav]')].map(b => b.dataset.winNav)).toEqual(['tomorrow', 'all']);   // not the selected or disabled ones
    expect(root.querySelector('#win-show-chart')).toBeNull();
    click(jump.querySelector('[data-win-nav="all"]'));
    expect(act.priceNav).toHaveBeenCalledTimes(1); expect(act.priceNav).toHaveBeenCalledWith('all');
    for (const [name, fn] of Object.entries(act)) if (name !== 'priceNav') expect(fn, name).not.toHaveBeenCalled();
    expect(rowsOf(root)[1].dataset.selected).toBe('true');         // selection survives the day change request
  });
  it('maps a click on the proposal lane to the one window containing it and ignores gaps', () => {
    charts.length = 0;
    const { root } = mount(build());
    const chart = charts.find(c => /^price-/.test(c.dom.id));
    const bar = root.querySelector('.track-lane[data-lane="proposal"] .track-bar');
    expect(bar, 'proposal lane drawn').not.toBeNull();
    bar.getBoundingClientRect = () => ({ left: 0, width: 1000, top: 0, height: 20, right: 1000, bottom: 20 });
    const z = chart.getOption().dataZoom[0];
    const at = t => (t - z.startValue) / (z.endValue - z.startValue) * 1000;
    const pick = t => bar.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: at(t) }));
    pick(BASE + 2 * H);                                            // gap between windows 1 and 2
    expect(rowsOf(root).every(r => r.dataset.selected === 'false')).toBe(true);
    pick(BASE + 3.5 * H);
    expect(rowsOf(root)[1].dataset.selected).toBe('true');
    pick(BASE + 3.5 * H);                                          // picking again does not toggle off
    expect(rowsOf(root)[1].dataset.selected).toBe('true');
  });
  it('model helpers: exact interval and identity only, ambiguous instants select nothing', () => {
    const f = build().format;
    const m = buildWindowsModel({ windows: [{ start: 0, end: 10 }, { start: 5, end: 15 }], knownPlan: true, context: { identity: 'x' }, format: { ...f, minutesPerTimeUnit: 1 }, draftKey: 'a', totals: undefined });
    expect(windowsAt(m, 7)).toHaveLength(2); expect(windowsAt(m, 12)).toHaveLength(1); expect(windowsAt(m, 15)).toHaveLength(0);
    const sel = { draftKey: 'a', contextKey: m.contextKey, key: m.rows[0].key };
    expect(resolveSelection(sel, m).selected?.ordinal).toBe(1);
    expect(resolveSelection({ ...sel, contextKey: 'a|id:y' }, m).selected).toBeNull();
    expect(resolveSelection({ ...sel, key: '1→10' }, m).selected).toBeNull();
  });
});


it('does not claim target charging is unnecessary when only the minimum is covered', () => {
  expect(windowsStatus({ knownPlan: true, stale: false, count: 0, context: { codes: ['minimum_covered'] } })).toBe('empty');
});
