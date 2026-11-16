// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';

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
import { priceBand, bandColor, PRICE_BANDS, priceAxisExtent } from '../shared-dashboard/price-bands.js';
import { publishedChart } from '../sidebar/price-chart.js';

const H = 3600000;
const rowsFor = (values, currency = 'EUR', scale = 0.01) => values.map((v, i) => ({ start: new Date(Date.UTC(2026, 10, 16, i)).toISOString(), end: new Date(Date.UTC(2026, 10, 16, i + 1)).toISOString(), raw_price: v == null ? null : v * scale }));
const live = (values, currency = 'EUR', scale = 0.01) => publishedChart({ prices: { published_intervals: rowsFor(values, currency, scale) } }, { timezone: 'UTC', currency }, Date.UTC(2026, 10, 16, 1), false);
const mount = (values, currency, scale) => {
  const { chart, format } = live(values, currency, scale);
  charts.length = 0;
  const root = document.createElement('div');
  root.innerHTML = '<div id="price-step"></div><button data-reset="step"></button><button data-zoom="step"></button>';
  document.body.append(root);
  const handle = mountCharts(root, { ...chart, windows: [{ start: chart.horizon[0] + H, end: chart.horizon[0] + 2 * H }], deadline: null }, format, ['step']);
  return { handle, chart: charts[0], data, series: n => charts[0].options.at(-1).series[n] };
  function data() { return charts[0].options.at(-1); }
};
const colorsOf = (m, expected = null) => {
  const out = [];
  const api = { value: i => m.series(0).data[out.length][i], coord: p => p };
  // Use the real renderItem to read the colour it paints for each interval.
  for (const _ of m.series(0).data) { const g = m.series(0).renderItem({ coordSys: {} }, api); out.push(g.children[0].style.fill); }
  return out;
};

beforeEach(() => { globalThis.ResizeObserver = class { observe() {} disconnect() {} }; document.body.innerHTML = ''; });

describe('absolute price bands', () => {
  it('uses exact 8/15/25 boundaries and greens negatives', () => {
    const k = v => priceBand(v, 'c/kWh')?.key;
    expect([-5, 0, 7.999, 8, 14.999, 15, 25, 25.001, 80].map(k)).toEqual(['cheap', 'cheap', 'cheap', 'normal', 'normal', 'medium', 'medium', 'expensive', 'expensive']);
    expect(PRICE_BANDS.map(b => b.range)).toEqual(['<8', '8–<15', '15–25', '>25']);
  });
  it('colours stepped intervals by value through the live chart and shows a 1–3 c day low on a 0..30 axis', () => {
    const m = mount([1, 2, 3, 2]);
    const y = m.data().yAxis;
    expect([y.min, y.max, y.interval]).toEqual([0, 30, 10]);
    expect(m.series(0).data.map(d => d[2])).toEqual([1, 2, 3, 2]);
    expect(m.series(0).data.map(d => d[3])).toEqual([null, 1, 2, 3]);
    expect(m.data().visualMap).toBeUndefined();
    expect(m.series(1).markPoint.data.map(p => p.itemStyle.color)).toEqual(['#37c48f', '#37c48f']);
  });
  it('paints each interval with its own absolute band, including boundaries', () => {
    const m = mount([7.99, 8, 15, 25, 25.5]);
    expect(colorsOf(m)).toEqual(['#37c48f', '#e9b34e', '#ef8845', '#ef8845', '#ec6266']);
  });
  it('keeps thresholds stable across zoom/refresh and extends for negatives and spikes unclipped', () => {
    const m = mount([2, -12, 63, 4]);
    expect(m.data().yAxis.min).toBe(-20);
    expect(m.data().yAxis.max).toBe(70);
    const before = m.data().yAxis;
    m.chart.options.at(-1).dataZoom[0].startValue = m.chart.options.at(-1).dataZoom[0].startValue + H;
    const cheap = live([1, 2, 3]);
    m.handle.update({ ...cheap.chart, windows: [], deadline: null }, cheap.format);
    expect([m.data().yAxis.min, m.data().yAxis.max]).toEqual([0, 30]);
    expect([before.min, before.max]).toEqual([-20, 70]);
  });
  it('leaves missing intervals out instead of drawing zero', () => {
    const m = mount([5, null, 6]);
    expect(m.series(0).data.map(d => [d[2], d[3]])).toEqual([[5, null], [6, null]]);
  });
  it('does not classify other currencies and says so', () => {
    const m = mount([0.08, 0.4], 'SEK', 1);
    expect(m.chart.options.at(-1).yAxis.name).toBe('SEK/kWh');
    expect(priceBand(0.08, 'SEK/kWh')).toBeNull();
    expect(colorsOf(m)).toEqual(['#75b8e8', '#75b8e8']);
    const ext = priceAxisExtent([{ cents: 0.08 }, { cents: 0.4 }], 'SEK/kWh');
    expect(ext.min).toBe(0); expect(ext.max).toBeGreaterThan(0.4); expect(ext.max).toBeLessThan(1);
    expect(bandColor(5, 'currency unknown/kWh')).toBe('#75b8e8');
  });
  it('includes a soft cap in the axis so it is not clipped', () => {
    expect(priceAxisExtent([{ cents: 10 }], 'c/kWh', 45).max).toBe(50);
    expect(mount([30, 40]).series(1).markPoint.data.map(p => p.itemStyle.color)).toEqual(['#ec6266', '#ec6266']);
  });
});
