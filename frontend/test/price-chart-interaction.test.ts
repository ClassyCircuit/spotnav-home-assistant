// @vitest-environment jsdom
// @ts-nocheck
// Stage 7.2: the shared price chart (options, renderItem, tooltip, event handlers) and the 7.1 navigation, driven with
// fixtures. ECharts itself is mocked except its pure `graphic` clipping helpers; no canvas is drawn or verified here.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const charts = [];
const resizers = [];
vi.mock('echarts/core', async () => {
  const actual = await vi.importActual('echarts/core');
  return {
    use: () => {},
    graphic: actual.graphic,
    init: dom => {
      const handlers = {};
      const chart = { dom, handlers, options: [], width: 800, zoom: null, resized: 0, actions: [],
        setOption(o) { this.options.push(o); this.zoom = { startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }; },
        getOption() { return { ...this.options.at(-1), dataZoom: [{ ...this.zoom }] }; },
        on(name, fn) { handlers[name] = fn; }, off() {},
        dispatchAction(a) {
          this.actions.push(a);
          if (a.type !== 'dataZoom') return;
          const { min, max } = this.options.at(-1).xAxis; // percent actions are relative to the axis extent, as in ECharts
          this.zoom = a.startValue != null ? { startValue: a.startValue, endValue: a.endValue } : { startValue: min + (max - min) * a.start / 100, endValue: min + (max - min) * a.end / 100 };
          handlers.datazoom?.();
        },
        getDom: () => dom, getWidth() { return this.width; }, resize() { this.resized++; }, dispose() {}, convertToPixel: (_, v) => v / 60000, convertFromPixel: (_, v) => v * 60000 };
      charts.push(chart);
      return chart;
    },
  };
});
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
globalThis.ResizeObserver = class { constructor(fn) { resizers.push(fn); } observe() {} disconnect() {} };

import { mountCharts } from '../shared-dashboard/charts.js';
import { createPriceDays } from '../shared-dashboard/price-days.js';
import { publishedChart, localDaySpan } from '../sidebar/price-chart.js';

const H = 3600000, Q = 900000;
const STOCKHOLM = 'Europe/Stockholm', RIGA = 'Europe/Riga';
const iso = ms => new Date(ms).toISOString();
const row = (start, minutes, raw) => ({ start: iso(start), end: iso(start + minutes * 60000), raw_price: raw });
const dayRows = (day, zone, raw = 0.05) => { const [a, b] = localDaySpan(day, zone); const out = []; for (let t = a; t < b; t += H) out.push(row(t, 60, raw)); return out; };
const wall = (ms, zone) => new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(ms);
const build = (rows, zone, currency, now, view) => publishedChart({ prices: { published_intervals: rows } }, { timezone: zone, currency }, now, false, view);
function mount(built, windows = []) {
  charts.length = 0;
  const root = document.createElement('div');
  root.innerHTML = '<div id="price-step"></div><button data-reset="step"></button><button data-zoom="step"></button>';
  document.body.append(root);
  const handle = mountCharts(root, { ...built.chart, windows, deadline: null }, built.format, ['step']);
  return { handle, chart: charts[0], root, option: () => charts[0].options.at(-1) };
}
beforeEach(() => { document.body.innerHTML = ''; resizers.length = 0; });

describe('explicit Today / Tomorrow versus the default horizon', () => {
  const today = '2026-11-16', tomorrow = '2026-11-17';
  const live = [...dayRows(today, STOCKHOLM), ...dayRows(tomorrow, STOCKHOLM)];
  const noon = Date.parse('2026-11-16T11:00:00Z');
  const ctx = { charger: 'c', epoch: '1:0', area: 'SE3', currency: 'SEK', today, span: d => localDaySpan(d, STOCKHOLM), waitingForTomorrow: false };
  async function ready() {
    const pd = createPriceDays({ request: async () => ({ api_version: 1, mode: 'available', charger_id: 'c', area_id: 'SE3', currency: 'SEK', today, days: [{ day: today }, { day: tomorrow }] }) });
    pd.sync(ctx); await new Promise(r => setTimeout(r, 0));
    return pd;
  }
  const rangeOf = pd => { const v = pd.view(live); const b = build(live, STOCKHOLM, 'SEK', noon, { key: v.viewKey, range: v.range }); return { v, b, start: b.format.initialRange(noon) }; };

  it('keeps the rolling horizon by default but shows only local today for an explicit Today and only tomorrow for Tomorrow', async () => {
    const pd = await ready();
    const [t0, t1] = localDaySpan(today, STOCKHOLM), [, u1] = localDaySpan(tomorrow, STOCKHOLM);
    const def = rangeOf(pd);
    expect(def.v.range).toBeNull();
    expect(def.start[1]).toBe(u1); // default still runs to the end of the published horizon (includes tomorrow)
    pd.select('today');
    const explicit = rangeOf(pd);
    expect(explicit.v.range).toEqual([t0, t1]);
    expect(explicit.start).toEqual([t0, t1]);
    expect(explicit.v.viewKey).not.toBe(def.v.viewKey);
    pd.select('tomorrow');
    expect(rangeOf(pd).start).toEqual([t1, u1]);
  });

  it('a routine refresh keeps the user zoom, while explicit Today (even pressed again) resets to the day', async () => {
    const pd = await ready();
    pd.select('today');
    let { b } = rangeOf(pd);
    const m = mount(b);
    const [t0, t1] = localDaySpan(today, STOCKHOLM);
    expect(m.chart.zoom).toEqual({ startValue: t0, endValue: t1 });
    m.chart.dispatchAction({ type: 'dataZoom', startValue: t0 + 6 * H, endValue: t0 + 12 * H }); // user zoom
    const zoomed = { ...m.chart.zoom };
    for (let i = 0; i < 3; i++) { const again = rangeOf(pd).b; m.handle.update({ ...again.chart, windows: [] }, again.format); } // routine refreshes
    expect(m.chart.zoom).toEqual(zoomed);
    pd.select('today'); // same button again is a new explicit navigation
    const reset = rangeOf(pd).b; m.handle.update({ ...reset.chart, windows: [] }, reset.format);
    expect(m.chart.zoom).toEqual({ startValue: t0, endValue: t1 });
  });

  it('clamps a user zoom that falls partly outside a new horizon and resets one that falls entirely outside', () => {
    const rows = dayRows(today, STOCKHOLM), [t0, t1] = localDaySpan(today, STOCKHOLM);
    const m = mount(build(rows, STOCKHOLM, 'SEK', noon));
    m.chart.zoom = { startValue: t0 - 5 * H, endValue: t0 + 3 * H };
    const next = build(rows, STOCKHOLM, 'SEK', noon);
    m.handle.update({ ...next.chart, windows: [] }, next.format);
    expect(m.chart.zoom).toEqual({ startValue: t0, endValue: t0 + 3 * H });
    m.chart.zoom = { startValue: t1 + 2 * H, endValue: t1 + 5 * H };
    m.handle.update({ ...next.chart, windows: [] }, next.format);
    expect(m.chart.zoom.endValue).toBe(t1);
  });
});

describe('23/25-hour days (Europe/Stockholm, Europe/Riga)', () => {
  for (const [zone, spring, autumn] of [[STOCKHOLM, '2026-03-29', '2026-10-25'], [RIGA, '2026-03-29', '2026-10-25']]) {
    it(`${zone}: local day bounds, multi-hour ticks on local hours and a date only at local midnight`, () => {
      for (const [day, length] of [[spring, 23], [autumn, 25]]) {
        const [a, b] = localDaySpan(day, zone);
        expect((b - a) / H).toBe(length);
        const { format } = build(dayRows(day, zone), zone, 'EUR', a);
        const ticks = format.timeTicks(a, b, 800); // 100 px per tick -> 4 h steps
        expect(ticks.map(t => wall(t, zone))).toEqual(['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']);
        expect(format.tickLabel(ticks[0])).toContain(format.date(a));
        expect(format.tickLabel(ticks[1])).not.toContain(format.date(a));
        const days = format.days(a, b);
        expect(days).toHaveLength(1);
        expect([days[0].start, days[0].end]).toEqual([a, b]);
      }
    });
  }

  it('hourly ticks on the 25-hour day keep both 03:00 hours apart, and the spring-forward day has no 03:00-02:00 duplicate', () => {
    const [a, b] = localDaySpan('2026-10-25', STOCKHOLM);
    const { format } = build(dayRows('2026-10-25', STOCKHOLM), STOCKHOLM, 'EUR', a);
    const hourly = format.timeTicks(a, b, 3000);
    expect(hourly).toHaveLength(25);
    const twos = hourly.filter(t => wall(t, STOCKHOLM) === '02:00').map(t => format.tickLabel(t));
    expect(twos).toHaveLength(2);
    expect(new Set(twos).size).toBe(2); // the GMT+2 / GMT+1 offset tells the repeated hour apart
    const [s, e] = localDaySpan('2026-03-29', STOCKHOLM);
    const spring = build(dayRows('2026-03-29', STOCKHOLM), STOCKHOLM, 'EUR', s).format.timeTicks(s, e, 3000);
    expect(spring).toHaveLength(23);
    // a 2-hour step never invents the non-existent 02:00 local hour
    expect(build(dayRows('2026-03-29', STOCKHOLM), STOCKHOLM, 'EUR', s).format.timeTicks(s, e, 1200).map(t => wall(t, STOCKHOLM))).not.toContain('02:00');
  });

  it('draws a day cell for every day of a 10-day paged view, not only the first five', () => {
    const [a] = localDaySpan('2026-10-20', STOCKHOLM), [, b] = localDaySpan('2026-10-29', STOCKHOLM);
    const { format } = build(dayRows('2026-10-25', STOCKHOLM), STOCKHOLM, 'EUR', a);
    const cells = format.days(a, b);
    expect(cells).toHaveLength(10);
    expect(cells.map(c => (c.end - c.start) / H)).toEqual([24, 24, 24, 24, 24, 25, 24, 24, 24, 24]);
  });

  it('the chart renders tick labels through the zone-aware label, so mid-day ticks carry no date', () => {
    const [a, b] = localDaySpan('2026-10-25', STOCKHOLM);
    const built = build(dayRows('2026-10-25', STOCKHOLM), STOCKHOLM, 'EUR', a, { key: 'k', range: [a, b] });
    const m = mount(built);
    const labels = [...m.root.querySelectorAll('.time-ticks span')].map(s => s.textContent);
    expect(labels.length).toBeGreaterThan(2);
    expect(labels.filter(t => t.includes('\n'))).toHaveLength(1);
  });
});

describe('mixed hourly / quarter-hour data, gaps, negatives and EUR conversion', () => {
  const t = Date.UTC(2026, 10, 16, 0);
  // 2 hourly rows, 4 quarter-hours, a null (unknown) hour, then 1 hourly row.
  const rows = [row(t, 60, 0.10), row(t + H, 60, -0.015), row(t + 2 * H, 15, 0.20), row(t + 2 * H + Q, 15, 0.30), row(t + 2 * H + 2 * Q, 15, 0.05), row(t + 2 * H + 3 * Q, 15, 0.05), row(t + 3 * H, 60, null), row(t + 4 * H, 60, 0.12)];
  const m = () => mount(build(rows, 'UTC', 'EUR', t + H));

  it('converts EUR to cents once, joins only contiguous steps, never bridges the unknown hour, and snaps inside the quarter-hour region', () => {
    const chart = m(), data = chart.option().series[0].data;
    expect(data.map(d => d[2])).toEqual([10, -1.5, 20, 30, 5, 5, 12]);
    expect(data.map(d => d[3])).toEqual([null, 10, -1.5, 20, 30, 5, null]); // last row follows the gap: no joint
    const { format, chart: built } = build(rows, 'UTC', 'EUR', t + H);
    expect(format.snapRange(t + 2 * H + 20 * 60000, t + 2 * H + 40 * 60000)).toEqual([t + 2 * H + Q, t + 2 * H + 3 * Q]);
    expect(format.priceGaps(t, t + 5 * H, built.prices)).toEqual([[t + 3 * H, t + 4 * H]]);
  });

  it('keeps the Stage 18.4 absolute axis (negative extends below zero) and band colours', () => {
    const y = m().option().yAxis;
    expect(y.min).toBe(-10);
    expect(y.max).toBe(30);
  });

  it('tooltip names each exact interval, handles negative values, escapes text and returns nothing for a mark (non-interval) value', () => {
    const chart = m(), f = chart.option().tooltip.formatter;
    expect(f({ value: [1, 2] })).toBe('');
    const html = f({ seriesType: 'custom', value: [t + H, t + 2 * H, -1.5, 10] });
    expect(html).toContain('-1.5 c/kWh');
    expect(html).toContain('Cheap');
    expect(html).not.toMatch(/NaN|undefined|Invalid/);
    expect(f({ seriesType: 'custom', value: [t + 2 * H + Q, t + 2 * H + 2 * Q, 30, 20] })).toContain('Expensive');
    expect(f({ value: 12.5 })).toBe(''); // markPoint/markLine hit: value is a number, not an interval
    expect(f({ value: [NaN, 1, 2] })).toBe('');
    expect(chart.option().series[1].markPoint.silent).toBe(true);
    const unsafe = mount({ ...build(rows, 'UTC', 'EUR', t), chart: { ...build(rows, 'UTC', 'EUR', t).chart, unit: '<img onerror=x>' } });
    expect(unsafe.option().tooltip.formatter({ value: [t, t + H, 5, null] })).not.toContain('<img');
  });
});

describe('renderItem with the real ECharts clipping helpers', () => {
  const coordSys = { x: 100, y: 80, width: 600, height: 200 }; // y axis -10..30 -> 200 px
  const item = (opts, values) => {
    const m = mount(build(opts, 'UTC', 'EUR', Date.UTC(2026, 10, 16, 0)));
    const series = m.option().series[0];
    const px = (x, y) => [100 + (x - Date.UTC(2026, 10, 16, 0)) / (6 * H) * 600, 80 + (30 - y) / 40 * 200];
    return values.map(v => series.renderItem({ coordSys }, { value: i => v[i], coord: ([x, y]) => px(x, y) }));
  };
  const t = Date.UTC(2026, 10, 16, 0);
  const ten = [row(t, 60, 0.1), row(t + H, 60, 0.1)];

  it('draws negative values below the zero line and clips a spike at the plot edge', () => {
    const [neg, spike] = item(ten, [[t, t + H, -5, null], [t + H, t + 2 * H, 80, null]]);
    const rect = neg.children[0].shape;
    expect(rect.y).toBeCloseTo(80 + 30 / 40 * 200); // starts at the zero baseline
    expect(rect.height).toBeCloseTo(25);
    expect(spike.children[0].shape.y).toBeGreaterThanOrEqual(coordSys.y);
    expect(spike.children[0].shape.y + spike.children[0].shape.height).toBeLessThanOrEqual(coordSys.y + coordSys.height);
  });

  it('draws a joint only where the boundary is on screen and the neighbour is contiguous; an interval wholly outside draws nothing', () => {
    const [joined, noJoint, leftEdge, outside] = item(ten, [[t + H, t + 2 * H, 20, 5], [t + H, t + 2 * H, 20, null], [t - 3 * H, t + H, 20, 5], [t - 9 * H, t - 8 * H, 20, 5]]);
    expect(joined.children.filter(c => c.type === 'line')).toHaveLength(2); // top edge + joint
    expect(noJoint.children.filter(c => c.type === 'line')).toHaveLength(1);
    expect(leftEdge.children.filter(c => c.type === 'line')).toHaveLength(1); // boundary is off screen: no stray vertical line at the plot edge
    expect(outside).toBeNull();
  });
});

describe('resize and interaction handlers', () => {
  it('a container resize resizes the chart and redraws ticks for the new width without touching the range or the options', () => {
    const [a, b] = localDaySpan('2026-11-16', STOCKHOLM);
    const m = mount(build(dayRows('2026-11-16', STOCKHOLM), STOCKHOLM, 'EUR', a, { key: 'k', range: [a, b] }));
    const before = m.chart.options.length, zoom = { ...m.chart.zoom }, ticks = () => m.root.querySelectorAll('.time-ticks span').length, narrow = ticks();
    m.chart.width = 1600; // orientation change to a wider container
    resizers.forEach(fn => fn());
    m.chart.handlers.finished(); // ECharts repaints after resize
    expect(m.chart.resized).toBe(1);
    expect(m.chart.options).toHaveLength(before);
    expect(m.chart.actions).toEqual([]);
    expect(m.chart.zoom).toEqual(zoom);
    expect(ticks()).toBeGreaterThan(narrow);
  });

  it('reset restores the full horizon through the same snapping handler', () => {
    const rows = [...dayRows('2026-11-16', STOCKHOLM), ...dayRows('2026-11-17', STOCKHOLM)];
    const m = mount(build(rows, STOCKHOLM, 'EUR', Date.parse(rows[3].start)));
    m.root.querySelector('[data-reset="step"]').click();
    expect(m.chart.actions.at(-1)).toMatchObject({ type: 'dataZoom', start: 0, end: 100 });
  });
});
