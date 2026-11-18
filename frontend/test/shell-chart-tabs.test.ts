// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.1: charts built or refreshed while their tab is hidden are re-measured when it is shown, zoom intact.
// ECharts is mocked (no canvas); this checks the dashboard -> chart boundary, not pixels.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';

const charts = [];
const ZONE = 'Europe/Stockholm';
vi.mock('echarts/core', async () => {
  const actual = await vi.importActual('echarts/core');
  return { use: () => {}, graphic: actual.graphic, init: dom => {
    const chart = { dom, resized: 0, options: [], disposed: false, zoom: null,
      setOption(o) { this.options.push(o); if (o.dataZoom) this.zoom = { startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }; },
      getOption() { return { ...this.options.at(-1), dataZoom: [{ ...this.zoom }] }; }, on() {}, off() {}, dispatchAction() {},
      getDom: () => dom, getWidth: () => 800, resize() { this.resized++; }, dispose() { this.disposed = true; },
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
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

import { dashboardAdapter } from '../sidebar/adapter.js';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { localDaySpan } from '../sidebar/price-chart.js';

const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: ZONE }).format(new Date());
const rows = day => Array.from({ length: 24 }, (_, i) => { const s = localDaySpan(day, ZONE)[0] + i * 3600000; return { start: new Date(s).toISOString(), end: new Date(s + 3600000).toISOString(), raw_price: 1 + i / 10, price: 1 + i / 10 }; });
const price = (root) => charts.filter(c => /^price-/.test(c.dom.id) && !c.disposed);

const status = { api_version: 1, schedule: { supported: false, verified: false, sent: null, sent_at: null, ack: null, effective: null } };
const build = withPrices => {
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date().toISOString();
  if (withPrices) raw.prices.published_intervals = rows(today());
  const adapter = dashboardAdapter(raw, status, Date.now(), Date.now()); adapter.draftKey = 'a:1'; return adapter;
};
const mount = adapter => { const root = document.createElement('main'); document.body.append(root); return { root, view: mountDashboard(root, adapter) }; };

describe('charts across tab visibility', () => {
  it('re-measures the chart when its tab is shown again after a hidden refresh, keeping zoom', () => {
    charts.length = 0;
    const { root, view } = mount(build(true));
    const chart = price().at(-1); expect(chart, 'price chart mounted in Overview').toBeDefined();
    const zoom = JSON.stringify(chart.getOption().dataZoom);
    view.showTab('settings');
    expect(root.querySelector('#sn-panel-overview').hidden).toBe(true);
    const hidden = chart.resized;
    view.update(build(true));                    // routine refresh while the chart's tab is hidden
    expect(chart.resized).toBe(hidden);          // hidden: nothing measurable yet
    view.showTab('overview');
    expect(price().at(-1)).toBe(chart);
    expect(chart.resized).toBeGreaterThan(hidden);
    expect(JSON.stringify(chart.getOption().dataZoom)).toBe(zoom);
  });
  it('re-measures a chart created while its tab was hidden', () => {
    charts.length = 0;
    const { view } = mount(build(false));
    expect(price().length).toBe(0);
    view.showTab('settings');
    view.update(build(true));
    const created = price().at(-1); expect(created, 'created while hidden').toBeDefined();
    const before = created.resized;
    view.showTab('overview');
    expect(created.resized).toBeGreaterThan(before);
  });
});
