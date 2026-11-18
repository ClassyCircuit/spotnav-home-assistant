// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.4: redesigned price chart presentation. Pure markup (legend, context tiles, controls) plus the mounted chart's
// lanes/overlays with ECharts mocked except its clipping helpers; no canvas is drawn and no browser check is implied.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const charts = [];
vi.mock('echarts/core', async () => {
  const actual = await vi.importActual('echarts/core');
  return {
    use: () => {}, graphic: actual.graphic,
    init: dom => {
      const handlers = {};
      const chart = { dom, handlers, options: [], width: 800, zoom: null, actions: [],
        setOption(o) { this.options.push(o); this.zoom = { startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }; },
        getOption() { return { ...this.options.at(-1), dataZoom: [{ ...this.zoom }] }; },
        on(name, fn) { handlers[name] = fn; }, off() {},
        dispatchAction(a) { this.actions.push(a); if (a.type === 'dataZoom' && a.startValue != null) { this.zoom = { startValue: a.startValue, endValue: a.endValue }; handlers.datazoom?.(); } },
        getDom: () => dom, getWidth() { return this.width; }, resize() {}, dispose() {}, convertToPixel: (_, v) => v / 60000, convertFromPixel: (_, v) => v * 60000 };
      charts.push(chart);
      return chart;
    },
  };
});
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

import { mountCharts } from '../shared-dashboard/charts.js';
import { buildTracks } from '../shared-dashboard/chart-tracks.js';
import { renderChartLegend, renderPriceContext, renderChartControls } from '../shared-dashboard/chart-view.js';

const H = 3600000;
const T0 = Date.UTC(2026, 10, 16, 0);
const dom = html => { const d = document.createElement('div'); d.innerHTML = html; return d; };

describe('legend', () => {
  it('shows the four absolute bands only for c/kWh and names the display-only limits', () => {
    const d = dom(renderChartLegend({ unit: 'c/kWh', cap: null }));
    expect([...d.querySelectorAll('[data-legend="prices"] .cl-dot')].map(x => x.className.replace('cl-dot ', ''))).toEqual(['band-green', 'band-amber', 'band-orange', 'band-red']);
    expect(d.querySelector('[data-legend="prices"]').textContent).toMatch(/Cheap <8.*Normal 8–<15.*Medium 15–25.*Expensive >25.*exactly 25 is Medium; display only, not a charging limit/);
    expect(d.querySelector('.cap-key')).toBeNull();
  });
  it('classifies nothing for an unknown currency and draws a cap key only for a finite comparable cap', () => {
    const d = dom(renderChartLegend({ unit: 'SEK/kWh', cap: 0.5 }));
    expect(d.querySelector('[data-legend="prices"] .cl-dot')).toBeNull();
    expect(d.querySelector('[data-legend="prices"]').textContent).toContain('no trusted conversion is available for SEK/kWh');
    expect(d.querySelector('[data-legend="overlay"]').textContent).toContain('Soft cap 0.5 SEK/kWh');
    expect(dom(renderChartLegend({ unit: 'c/kWh', cap: NaN })).querySelector('.cap-key')).toBeNull();
    expect(dom(renderChartLegend({ unit: 'c/kWh', cap: undefined })).querySelector('.cap-key')).toBeNull();
  });
  it('keeps proposal, sent, effective and measured as separate keys with unknown hatched, and escapes the unit', () => {
    const d = dom(renderChartLegend({ unit: '<img onerror=x>', cap: null }));
    expect(['tk-proposal', 'tk-sent', 'tk-effective', 'tk-flow', 'tk-unknown'].every(c => d.querySelector(`[data-legend="tracks"] .${c}`))).toBe(true);
    expect(d.querySelector('[data-legend="tracks"]').textContent).toMatch(/acknowledged is not installed.*not power.*never zero/s);
    expect(d.querySelector('img')).toBeNull();
  });
});

describe('controls and context tiles', () => {
  it('keeps the zoom and reset hooks and accessible names; context shows Unknown and negative prices truthfully', () => {
    const c = dom(renderChartControls('step', 'Stepped area'));
    expect(c.querySelector('[data-zoom="step"]').getAttribute('aria-label')).toBe('Zoom in Stepped area');
    expect(c.querySelector('[data-reset="step"]').getAttribute('aria-label')).toBe('Reset Stepped area overview');
    const t = dom(renderPriceContext({ now: -1.5, next: null, low: null, high: '30 c/kWh · Mon 18:00', unit: 'c/kWh' }));
    expect([...t.querySelectorAll('.pc-tile')].map(x => x.dataset.tile)).toEqual(['now', 'next', 'low', 'high']);
    expect(t.querySelector('[data-tile="now"] b').textContent).toBe('-1.5 c/kWh');
    expect(t.querySelector('[data-tile="next"] b').textContent).toBe('Unknown c/kWh');
    expect(t.querySelector('[data-tile="low"] b').textContent).toBe('Unknown');
  });
});

function mount(opts = {}) {
  charts.length = 0;
  const root = document.createElement('div');
  const mode = opts.mode || 'step';
  root.innerHTML = `<div id="price-${mode}"></div><div data-track-lanes="${mode}"></div><button data-reset="${mode}"></button><button data-zoom="${mode}"></button>`;
  document.body.append(root);
  const horizon = [T0, T0 + 6 * H], now = T0 + 2 * H;
  const prices = opts.prices || [{ start: T0, end: T0 + H, cents: 10 }, { start: T0 + H, end: T0 + 2 * H, cents: -4 }, { start: T0 + 4 * H, end: T0 + 5 * H, cents: 30 }];
  const windows = opts.windows || [{ start: T0 + 4 * H, end: T0 + 5 * H }];
  const tracks = buildTracks({ horizon, now, windows, history: null, effective: null });
  const format = { time: x => String(x), date: x => String(x), days: () => [{ start: T0, end: T0 + 6 * H, midnight: T0, label: 'Mon' }],
    priceGaps: (a, b, av) => { const out = []; let at = a; for (const p of [...av].sort((x, y) => x.start - y.start)) { if (p.start > at) out.push([at, p.start]); at = Math.max(at, p.end); } if (at < b) out.push([at, b]); return out; },
    stepSegments: ps => ps.map(p => [[p.start, p.cents], [p.end, p.cents]]), stepPoints: () => [], snapRange: (a, b) => [a, b], initialRange: () => horizon, timeTicks: () => [T0, T0 + 3 * H] };
  const handle = mountCharts(root, { prices, windows, tracks, now, deadline: null, horizon, cap: opts.cap ?? null, unit: opts.unit || 'c/kWh', viewKey: 'k' }, format, [mode]);
  return { handle, chart: charts[0], root, option: () => charts[0].options.at(-1), tracks };
}
beforeEach(() => { document.body.innerHTML = ''; });

describe('mounted chart', () => {
  it('draws one lane per evidence track with a key chip, aligned to the axis start and width through a zoom', () => {
    const m = mount();
    const lanes = [...m.root.querySelectorAll('.track-lane')];
    expect(lanes.map(l => l.dataset.lane)).toEqual(['proposal', 'sent', 'effective', 'measured']);
    expect(lanes.every(l => l.querySelector('.track-caption .track-key'))).toBe(true);
    const bar = () => m.root.querySelector('.track-lane .track-bar');
    expect(parseFloat(bar().style.marginLeft)).toBeCloseTo(T0 / 60000);
    const full = parseFloat(bar().style.width);
    m.chart.dispatchAction({ type: 'dataZoom', startValue: T0 + H, endValue: T0 + 3 * H });
    expect(parseFloat(bar().style.marginLeft)).toBeCloseTo((T0 + H) / 60000);
    expect(parseFloat(bar().style.width)).toBeCloseTo(2 * H / 60000);
    expect(parseFloat(bar().style.width)).toBeLessThan(full);
    expect(m.root.querySelector('[data-lane="proposal"] .seg-proposal')).toBeNull(); // 04:00-05:00 lies outside the zoomed 01:00-03:00
    m.chart.dispatchAction({ type: 'dataZoom', startValue: T0 + 3 * H, endValue: T0 + 6 * H });
    const seg = m.root.querySelector('[data-lane="proposal"] .seg-proposal');
    expect(parseFloat(seg.style.left)).toBeCloseTo(H / 60000); // 04:00 is one hour after the zoom start
    expect(parseFloat(seg.style.width)).toBeCloseTo(H / 60000);
  });
  it('shows unloaded history and absent readback as hatched unknown, never as an empty or zero lane', () => {
    const m = mount();
    for (const key of ['sent', 'effective', 'measured']) {
      const kinds = [...m.root.querySelectorAll(`[data-lane="${key}"] .track-seg`)].map(s => s.dataset.kind);
      expect(kinds.some(k => ['unloaded', 'unknown', 'future'].includes(k))).toBe(true);
      expect(kinds).not.toContain('no-flow');
    }
  });
  it('marks the unpublished hours as price gaps and the proposal over its own interval, with no invented bar', () => {
    const m = mount();
    const gaps = [...m.root.querySelectorAll('.price-gap')].map(g => [Number(g.dataset.start), Number(g.dataset.end)]);
    expect(gaps).toEqual([[T0 + 2 * H, T0 + 4 * H], [T0 + 5 * H, T0 + 6 * H]]);
    expect(m.option().series[0].data).toHaveLength(3);
    expect([...m.root.querySelectorAll('.proposal-track')].map(p => [Number(p.dataset.start), Number(p.dataset.end)])).toEqual([[T0 + 4 * H, T0 + 5 * H]]);
  });
  it('draws the cap line only for a finite cap and keeps the negative-capable absolute axis', () => {
    const marks = o => o.series[1].markLine.data.map(d => d.label.formatter);
    expect(marks(mount().option()).some(x => x.includes('Cap'))).toBe(false);
    expect(marks(mount({ cap: 12 }).option())).toContain('Cap 12 c/kWh');
    expect(marks(mount({ cap: NaN }).option()).some(x => x.includes('Cap'))).toBe(false);
    const o = mount().option();
    expect(o.yAxis.min).toBe(-10);
    expect(o.yAxis.max).toBe(30);
  });
  it('rounds the outer corners of an interval bar (bottom for a negative price) and keeps its position', () => {
    const coordSys = { x: T0 / 60000 - 10, y: 0, width: 100000, height: 400 };
    const api = v => ({ value: i => v[i], coord: ([x, y]) => [x / 60000, 200 - y * 5] });
    const bar = mount({ mode: 'bar' }).option().series[0].renderItem({ coordSys }, api([T0 + H, T0 + 2 * H, -4, null]));
    expect(bar.children[0].shape.r).toEqual([0, 0, 3, 3]);
    expect(bar.children[0].shape.x).toBeCloseTo((T0 + H) / 60000);
    const pos = mount({ mode: 'bar' }).option().series[0].renderItem({ coordSys }, api([T0, T0 + H, 10, null]));
    expect(pos.children[0].shape.r).toEqual([3, 3, 0, 0]);
  });
  it('mounting and zooming only dispatch chart zoom actions (no charger or request side effect)', () => {
    const m = mount();
    m.chart.dispatchAction({ type: 'dataZoom', startValue: T0, endValue: T0 + 3 * H });
    expect(new Set(m.chart.actions.map(a => a.type))).toEqual(new Set(['dataZoom']));
  });
});
