// @vitest-environment jsdom
// @ts-nocheck
// Stage 7.3b: aligned evidence tracks. The pure lane model (proposal / sent / effective / measured), the history spans taken from
// the backend answer, the effective readback input and the DOM lanes drawn on the chart's own axis. ECharts is mocked (no canvas).
import { describe, it, expect, vi } from 'vitest';

const charts = [];
vi.mock('echarts/core', async () => {
  const actual = await vi.importActual('echarts/core');
  return { use: () => {}, graphic: actual.graphic, init: dom => {
    const handlers = {};
    const chart = { dom, handlers, options: [], width: 800, zoom: null,
      setOption(o) { this.options.push(o); this.zoom = { startValue: o.dataZoom[0].startValue, endValue: o.dataZoom[0].endValue }; },
      getOption() { return { ...this.options.at(-1), dataZoom: [{ ...this.zoom }] }; }, on(name, fn) { handlers[name] = fn; }, off() {},
      dispatchAction(a) { if (a.type !== 'dataZoom') return; this.zoom = { startValue: a.startValue, endValue: a.endValue }; handlers.datazoom?.(); },
      getDom: () => dom, getWidth() { return this.width; }, resize() {}, dispose() {}, convertToPixel: (_, v) => 40 + (v - 1e12) / 60000, convertFromPixel: (_, v) => 1e12 + (v - 40) * 60000 };
    charts.push(chart); return chart; } };
});
vi.mock('echarts/charts', () => ({ CustomChart: {}, LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, MarkLineComponent: {}, MarkAreaComponent: {}, MarkPointComponent: {}, DataZoomComponent: {}, VisualMapComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

import { mountCharts } from '../shared-dashboard/charts.js';
import { buildTracks, tile } from '../shared-dashboard/chart-tracks.js';
import { buildHistoryModel } from '../shared-dashboard/history-day.js';
import { historyAnswer } from '../prototype/history-day-fixture.js';
import { effectiveTrack } from '../sidebar/effective-track.js';
import { publishedChart } from '../sidebar/price-chart.js';

const H = 3600000, T = s => Date.parse(`${s}Z`);
const stamp = iso => iso.slice(11, 16);
const answerFor = (day, change = () => {}) => { const a = structuredClone(historyAnswer('a', day)); change(a); return a; };
const modelOf = (answer, day, readAt = T('2026-11-09T14:30:00')) => buildHistoryModel(answer, day, { stamp }, readAt);
const NOW = T('2026-11-09T14:30:00'), HORIZON = [T('2026-11-08T00:00:00'), T('2026-11-11T00:00:00')];
const lanes = (over = {}) => Object.fromEntries(buildTracks({ horizon: HORIZON, now: NOW, windows: [], history: null, effective: null, ...over }).lanes.map(l => [l.key, l]));
const ready = (model, extra = {}) => ({ ...model, state: 'ready', ...extra });
const kindsOf = lane => lane.segments.map(s => s.kind);
const at = (lane, ms) => lane.segments.find(s => s.start <= ms && ms < s.end);
const day9 = () => ready(modelOf(historyAnswer('a', '2026-11-09'), '2026-11-09'));
const day8 = () => ready(modelOf(historyAnswer('a', '2026-11-08'), '2026-11-08'));

describe('every lane tiles the whole horizon (nothing is silently absent)', () => {
  it('is contiguous and unknown/unloaded when there is no evidence at all', () => {
    for (const lane of Object.values(lanes())) {
      expect(lane.segments[0].start).toBe(HORIZON[0]); expect(lane.segments.at(-1).end).toBe(HORIZON[1]);
      lane.segments.forEach((s, i) => { if (i) expect(s.start).toBe(lane.segments[i - 1].end); });
    }
    const l = lanes();
    expect(kindsOf(l.proposal)).toEqual(['unknown', 'none']);
    expect(kindsOf(lanes({ windows: null }).proposal)).toEqual(['unknown']);
    expect(kindsOf(l.sent)).toEqual(['unloaded']);
    expect(kindsOf(l.effective)).toEqual(['unknown']);
    expect(kindsOf(l.measured)).toEqual(['unloaded', 'future']);
  });
  it('two different spans in the same layer are shown as unknown, never one of them', () => {
    const out = tile(0, 10, () => ({ kind: 'unknown' }), [], [{ start: 0, end: 6, layer: 1, kind: 'a' }, { start: 4, end: 10, layer: 1, kind: 'b' }]);
    expect(out.map(s => [s.start, s.end, s.kind])).toEqual([[0, 4, 'a'], [4, 6, 'unknown'], [6, 10, 'b']]);
  });
});

describe('proposal is the current plan only; sent is history; they differ', () => {
  const windows = [{ start: T('2026-11-09T22:00:00'), end: T('2026-11-09T23:00:00'), control: 'minimum-exception', reserveMinutes: 6 }, { start: T('2026-11-10T02:00:00'), end: T('2026-11-10T03:00:00') }];
  it('draws current windows from now on, marks the minimum exception and reserve, and hatches the past', () => {
    const p = lanes({ windows }).proposal;
    expect(at(p, T('2026-11-09T22:30:00')).kind).toBe('proposal-exception');
    expect(at(p, T('2026-11-09T22:30:00')).text).toContain('includes 6 min reserve');
    expect(at(p, T('2026-11-10T02:30:00')).kind).toBe('proposal');
    expect(at(p, T('2026-11-08T12:00:00')).kind).toBe('unknown');
    expect(at(p, T('2026-11-10T12:00:00')).kind).toBe('none');
  });
  it('a window already over is not drawn, and an absent current plan is unknown, not "no charging"', () => {
    expect(kindsOf(lanes({ windows: [{ start: NOW - 3 * H, end: NOW - 2 * H }] }).proposal)).toEqual(['unknown', 'none']);
    expect(kindsOf(lanes({ windows: null }).proposal)).toEqual(['unknown']);
  });
  it('proposal differs from sent: the same hour is a proposal only; the sent lane stays on what history acknowledged', () => {
    const l = lanes({ windows: [{ start: T('2026-11-09T02:00:00'), end: T('2026-11-09T03:00:00') }, ...windows], history: day9() });
    expect(at(l.sent, T('2026-11-09T02:30:00'))).toMatchObject({ kind: 'sent', version: 'p1' });
    expect(at(l.sent, T('2026-11-09T22:30:00')).kind).toBe('unknown');
    expect(at(l.sent, T('2026-11-10T02:30:00')).kind).toBe('unloaded');
    expect(at(l.proposal, T('2026-11-10T02:30:00')).kind).toBe('proposal');
  });
});

describe('sent: acknowledged versions, unknown after an uncertain write, own version ids', () => {
  it('known span until the uncertain write, then unknown (from both the block and the unknown span)', () => {
    const l = lanes({ history: day8() });
    expect(at(l.sent, T('2026-11-08T22:15:00'))).toMatchObject({ kind: 'sent', version: 'p1' });
    expect(at(l.sent, T('2026-11-08T22:45:00')).kind).toBe('unknown');
    expect(at(l.sent, T('2026-11-08T23:50:00')).kind).toBe('unknown');
  });
  it('two versions in one day follow each other, each with its own id', () => {
    const answer = answerFor('2026-11-09', a => { a.comparison.planned_blocks = [{ ...a.comparison.planned_blocks[0], version: 'p1', start: '2026-11-09T02:00:00+00:00', end: '2026-11-09T03:00:00+00:00' },
      { ...a.comparison.planned_blocks[0], version: 'p2', start: '2026-11-09T03:00:00+00:00', end: '2026-11-09T05:00:00+00:00', limit: 10 }]; });
    const sent = lanes({ history: ready(modelOf(answer, '2026-11-09')) }).sent.segments.filter(s => s.kind === 'sent');
    expect(sent.map(s => [s.version, s.start, s.end, s.label])).toEqual([['p1', T('2026-11-09T02:00:00'), T('2026-11-09T03:00:00'), 'p1 · 16 A'], ['p2', T('2026-11-09T03:00:00'), T('2026-11-09T05:00:00'), 'p2 · 10 A']]);
  });
  it('the current acknowledgement never fills the past: only the loaded day is known', () => {
    const l = lanes({ history: day9() });
    expect(at(l.sent, T('2026-11-08T12:00:00')).kind).toBe('unloaded');
    expect(l.sent.note).toContain('only');
  });
});

describe('measured: backend flow intervals, outside-plan classes, no-flow versus unknown', () => {
  it('flow with bounded and open edges, outside the sent plan and while the plan was unknown', () => {
    const m = lanes({ history: day8() }).measured;
    expect(at(m, T('2026-11-08T21:55:00')).kind).toBe('flow-outside_plan');
    expect(at(m, T('2026-11-08T23:20:00')).kind).toBe('flow-plan_unknown');
    expect(at(m, T('2026-11-08T22:03:00')).kind).toBe('flow');
    expect(m.segments.some(s => s.openEnd)).toBe(true);
  });
  it('flow with no plan evidence is its own class', () => {
    const answer = answerFor('2026-11-09', a => { a.comparison.planned_blocks = []; a.comparison.outside_plan = [{ interval: 0, start: '2026-11-09T02:05:00+00:00', end: '2026-11-09T02:55:00+00:00', seconds: 3000, kind: 'no_plan_evidence' }]; });
    expect(at(lanes({ history: ready(modelOf(answer, '2026-11-09')) }).measured, T('2026-11-09T02:30:00')).kind).toBe('flow-no_plan_evidence');
  });
  it('no flow is claimed only where the backend says so; otherwise quiet time is unknown, not zero', () => {
    const quiet = answerFor('2026-11-09', a => { a.observed.intervals = []; a.comparison.planned_blocks[0].verdict = 'no_flow_observed'; });
    const m = lanes({ history: ready(modelOf(quiet, '2026-11-09')) }).measured;
    expect(at(m, T('2026-11-09T02:30:00')).kind).toBe('no-flow');
    expect(at(m, T('2026-11-09T09:00:00')).kind).toBe('unknown');
    const full = answerFor('2026-11-09', a => { a.observed.intervals = []; a.observed.coverage = { ...a.observed.coverage, trusted_seconds: 86400, untrusted_seconds: 0, no_data_seconds: 0, window_seconds: 86400 }; });
    expect(at(lanes({ history: ready(modelOf(full, '2026-11-09')) }).measured, T('2026-11-09T09:00:00')).kind).toBe('no-flow');
  });
  it('a gap overrides flow; raw rows that begin mid-day leave the earlier part unknown', () => {
    const gap = answerFor('2026-11-09', a => { a.observed.gaps = [{ kind: 'power_w', from: '2026-11-09T02:20:00+00:00', to: '2026-11-09T02:30:00+00:00', reason: 'unreadable' }]; });
    expect(at(lanes({ history: ready(modelOf(gap, '2026-11-09')) }).measured, T('2026-11-09T02:25:00')).kind).toBe('unknown');
    const partial = modelOf(historyAnswer('a', '2026-11-07'), '2026-11-07');
    expect(partial.raw).toBe('partial');
    expect(partial.tracks.measured.unknown[0]).toMatchObject({ start: T('2026-11-07T00:00:00'), end: T('2026-11-07T09:00:00') });
  });
  it('pruned, summary-only and empty days never draw invented flow', () => {
    for (const day of ['2026-11-06', '2026-11-05', '2026-11-04']) {
      const model = modelOf(historyAnswer('a', day), day), m = lanes({ history: ready(model) }).measured;
      expect(model.tracks.measured.detail).toBe(false);
      expect(m.segments.some(s => s.kind === 'flow' || s.kind === 'no-flow' || s.kind.startsWith('flow-'))).toBe(false);
    }
    const digest = modelOf(historyAnswer('a', '2026-11-05'), '2026-11-05');
    expect(lanes({ horizon: [T('2026-11-04T00:00:00'), T('2026-11-11T00:00:00')], history: ready(digest) }).sent.segments.some(s => s.kind === 'sent-summary')).toBe(true);
  });
  it('truncated lists keep the banner state and still draw only the rows that were returned', () => {
    const model = modelOf(historyAnswer('a', '2026-11-08'), '2026-11-08');
    expect(model.partial).toBe(true);
    expect(model.tracks.measured.flow.length).toBe(2);
  });
  it('future time is not unknown history; a failed refresh marks earlier flow stale without extending it', () => {
    const m = lanes({ history: ready(modelOf(historyAnswer('a', '2026-11-09'), '2026-11-09'), { refreshFailed: true }) }).measured;
    expect(at(m, NOW + H).kind).toBe('future');
    const flow = m.segments.find(s => s.kind === 'flow');
    expect(flow.stale).toBe(true);
    expect(flow.end).toBeLessThanOrEqual(NOW);
  });
  it('loading, error, permission and invalid states draw nothing as history', () => {
    for (const state of ['loading', 'error', 'permission', 'invalid']) {
      const l = lanes({ history: { state, message: `history ${state}` } });
      expect(kindsOf(l.sent)).toEqual(['unloaded']);
      expect(l.measured.segments.every(s => ['unloaded', 'future'].includes(s.kind))).toBe(true);
      expect(l.sent.note).toBe(`history ${state}`);
    }
  });
});

describe('time zones and DST: absolute instants decide alignment, never date strings', () => {
  it('a 25-hour Stockholm day keeps its exact span; days of another zone around it stay unloaded', () => {
    const a = answerFor('2026-11-09', x => { x.window = { since: '2026-10-24T22:00:00+00:00', until: '2026-10-25T23:00:00+00:00', zone: 'Etc/UTC', local_since: '2026-10-25T00:00:00+02:00', local_until: '2026-10-26T00:00:00+01:00' };
      x.comparison.planned_blocks = [{ ...x.comparison.planned_blocks[0], start: '2026-10-25T00:30:00+00:00', end: '2026-10-25T01:30:00+00:00' }]; x.observed.intervals = []; x.comparison.outside_plan = []; });
    const model = modelOf(a, '2026-10-25', T('2026-10-26T12:00:00'));
    expect(model.tracks.coverage).toEqual([T('2026-10-24T22:00:00'), T('2026-10-25T23:00:00')]);
    expect((model.tracks.coverage[1] - model.tracks.coverage[0]) / H).toBe(25);
    const l = Object.fromEntries(buildTracks({ horizon: [T('2026-10-24T12:00:00'), T('2026-10-27T00:00:00')], now: T('2026-10-26T12:00:00'), history: ready(model) }).lanes.map(x => [x.key, x]));
    expect(at(l.sent, T('2026-10-25T01:00:00')).kind).toBe('sent');
    expect(at(l.sent, T('2026-10-24T21:00:00')).kind).toBe('unloaded');
    expect(at(l.sent, T('2026-10-25T23:30:00')).kind).toBe('unloaded');
    expect(model.tracks.coverageText).toContain('only');
  });
  it('preview parity: the same data on the sample hour axis has the same structure as on epoch milliseconds', () => {
    const EPOCH = T('2026-11-09T00:00:00'), hours = ms => (ms - EPOCH) / H;
    const hist = day9();
    const live = buildTracks({ horizon: HORIZON, now: NOW, history: hist, windows: [{ start: T('2026-11-10T02:00:00'), end: T('2026-11-10T03:00:00') }] });
    const sample = buildTracks({ horizon: HORIZON.map(hours), now: hours(NOW), toAxis: hours, history: hist, windows: [{ start: hours(T('2026-11-10T02:00:00')), end: hours(T('2026-11-10T03:00:00')) }] });
    const shape = result => result.lanes.map(l => l.segments.map(s => `${s.kind}:${s.label}:${s.version ?? ''}`));
    expect(shape(sample)).toEqual(shape(live));
    expect(sample.lanes[1].segments.find(s => s.kind === 'sent').start).toBe(2);
  });
});

describe('review corrections (7.3b)', () => {
  it('a proposal window straddling now keeps the past unknown and only the future as proposal', () => {
    const p = lanes({ windows: [{ start: NOW - 2 * H, end: NOW + 2 * H, control: 'minimum-exception', reserveMinutes: 5 }] }).proposal;
    expect(at(p, NOW - H).kind).toBe('unknown');
    expect(at(p, NOW + H)).toMatchObject({ kind: 'proposal-exception', start: NOW });
    expect(at(p, NOW + H).text).toContain('includes 5 min reserve');
  });
  const full = (change = () => {}) => answerFor('2026-11-09', a => { a.observed.intervals = []; a.observed.isolated_flow_samples = 0; a.comparison.planned_blocks = []; a.comparison.outside_plan = [];
    a.observed.coverage = { ...a.observed.coverage, trusted_seconds: 86400, untrusted_seconds: 0, no_data_seconds: 0, window_seconds: 86400 }; change(a); });
  const measured = a => lanes({ history: ready(modelOf(a, '2026-11-09')) }).measured;
  it('a fully trusted day with observed flow keeps the flow, with no conflict and no whole-day no-flow', () => {
    const m = measured(answerFor('2026-11-09', a => { a.observed.coverage = { ...a.observed.coverage, trusted_seconds: 86400, untrusted_seconds: 0, no_data_seconds: 0, window_seconds: 86400 }; }));
    expect(at(m, T('2026-11-09T02:30:00')).kind).toBe('flow');
    expect(at(m, T('2026-11-09T09:00:00')).kind).toBe('unknown');
    expect(m.segments.some(s => s.conflict)).toBe(false);
  });
  it('a fully measured day with nothing observed is no-flow; partial coverage or an isolated sample is not', () => {
    expect(at(measured(full()), T('2026-11-09T09:00:00')).kind).toBe('no-flow');
    expect(at(measured(full(a => { a.observed.coverage.trusted_seconds = 40000; })), T('2026-11-09T09:00:00')).kind).toBe('unknown');
    expect(at(measured(full(a => { a.observed.isolated_flow_samples = 1; })), T('2026-11-09T09:00:00')).kind).toBe('unknown');
  });
  describe('effective readback fails closed on malformed periods', () => {
    const T0 = Date.parse('2026-11-09T14:30:00Z'), iso = ms => new Date(ms).toISOString();
    const st = periods => ({ effective: { fetched_at: iso(T0 - 20000), schedule_start: iso(T0 - H), duration_s: 6 * 3600, rate_unit: 'A', periods }, verification: {} });
    const p = (ms, amps) => ({ at: iso(ms), amps });
    it('rejects malformed, duplicate, out-of-order, negative and out-of-range periods instead of stretching the last valid limit', () => {
      const ok = [p(T0 - H, 0), p(T0 + H, 16)];
      expect(effectiveTrack(st(ok), T0 - 5000, false, T0).state).toBe('reported');
      for (const bad of [[p(T0 - H, 0), { at: 'x', amps: 8 }, p(T0 + H, 16)], [p(T0 - H, 0), p(T0 - H, 6)], [p(T0 + H, 16), p(T0 - H, 0)], [p(T0 - H, -1)],
        [p(T0 - 2 * H, 0)], [p(T0 + 10 * H, 0)], [p(T0 - H, 0), { at: iso(T0), amps: '8' }]])
        expect(effectiveTrack(st(bad), T0 - 5000, false, T0).state).toBe('unknown');
    });
    it('keeps every span inside the schedule and not before now', () => {
      const e = effectiveTrack(st([p(T0 - H, 0), p(T0 + H, 16)]), T0 - 5000, false, T0);
      expect(Math.min(...e.spans.map(s => s.start))).toBeGreaterThanOrEqual(T0);
      expect(Math.max(...e.spans.map(s => s.end))).toBeLessThanOrEqual(T0 - H + 6 * 3600000);
    });
  });
});

describe('effective: the latest fresh readback, remaining period only', () => {
  const T0 = Date.parse('2026-11-09T14:30:00Z');
  const status = (over = {}) => ({ effective: { status: 'Accepted', fetched_at: new Date(T0 - 20000).toISOString(), schedule_start: new Date(T0 - 3600000).toISOString(), duration_s: 6 * 3600,
    rate_unit: 'A', periods: [{ at: new Date(T0 - 3600000).toISOString(), amps: 0 }, { at: new Date(T0 + 1800000).toISOString(), amps: 16 }, { at: new Date(T0 + 3600000).toISOString(), amps: 0 }] },
    verification: { readback_at: new Date(T0 - 20000).toISOString(), reason: 'ok' }, ...over });
  it('keeps only the remaining period, clipped to now and to the readback coverage', () => {
    const e = effectiveTrack(status(), T0 - 5000, false, T0);
    expect(e.state).toBe('reported');
    expect(e.spans).toEqual([{ start: T0, end: T0 + 1800000, value: 0 }, { start: T0 + 1800000, end: T0 + 3600000, value: 16 }, { start: T0 + 3600000, end: T0 - 3600000 + 6 * 3600000, value: 0 }]);
    expect(e.differs).toBe(false);
  });
  it('stale or failed status, an old readback, ended coverage or a missing readback are unknown, never current', () => {
    expect(effectiveTrack(status(), T0 - 5000, true, T0).state).toBe('unknown');
    expect(effectiveTrack(status(), T0 - 600000, false, T0).state).toBe('unknown');
    expect(effectiveTrack(status({ effective: { ...status().effective, fetched_at: new Date(T0 - 600000).toISOString() } }), T0 - 5000, false, T0).state).toBe('unknown');
    expect(effectiveTrack(status(), T0 - 5000, false, T0 + 7 * 3600000).state).toBe('unknown');
    expect(effectiveTrack(status({ effective: null }), T0 - 5000, false, T0).state).toBe('unknown');
    expect(effectiveTrack(status({ effective: { ...status().effective, duration_s: null } }), T0 - 5000, false, T0).state).toBe('unknown');
    expect(effectiveTrack(null, T0, false, T0).state).toBe('unknown');
  });
  it('a difference is reported only for the readback it was computed from', () => {
    const mismatch = status({ verification: { readback_at: status().effective.fetched_at, reason: 'limits_or_transitions_differ' } });
    expect(effectiveTrack(mismatch, T0 - 5000, false, T0).differs).toBe(true);
    expect(effectiveTrack({ ...mismatch, verification: { readback_at: 'older', reason: 'limits_or_transitions_differ' } }, T0 - 5000, false, T0).differs).toBe(false);
  });
  it('is drawn for the future only, with the reported unit (never kW), and history cannot restore it', () => {
    const e = effectiveTrack(status(), T0 - 5000, false, T0);
    const l = lanes({ effective: e, history: day9() }).effective;
    expect(at(l, T0 + 2400000)).toMatchObject({ kind: 'effective', label: '16 A' });
    expect(l.segments.every(s => !/kW/.test(s.label || ''))).toBe(true);
    expect(at(l, T0 - H).kind).toBe('unknown');
    expect(at(l, T('2026-11-09T02:30:00')).kind).toBe('unknown');
  });
  it('sent differs from effective: a readback unlike the sent schedule is a reported difference, not a charging claim', () => {
    const mismatch = status({ verification: { readback_at: status().effective.fetched_at, reason: 'limits_or_transitions_differ' } });
    const l = lanes({ effective: effectiveTrack(mismatch, T0 - 5000, false, T0) }).effective;
    expect(at(l, T0 + 2400000).kind).toBe('effective-differs');
    expect(at(l, T0 + 2400000).text).toContain('reported difference');
    expect(at(l, T0 + 2400000).text).toContain('neither power nor proof of charging');
  });
});

describe('DOM lanes share the chart axis (mocked ECharts)', () => {
  const rows = []; for (let t = HORIZON[0]; t < HORIZON[1]; t += H) rows.push({ start: new Date(t).toISOString(), end: new Date(t + H).toISOString(), raw_price: 0.1 });
  const px = v => 40 + (v - 1e12) / 60000;
  function mount(tracks) {
    charts.length = 0; document.body.innerHTML = '';
    const root = document.createElement('div');
    root.innerHTML = '<div id="price-step"></div><div class="track-lanes" data-track-lanes="step"></div><button data-reset="step"></button><button data-zoom="step"></button>';
    document.body.append(root);
    const built = publishedChart({ prices: { published_intervals: rows } }, { timezone: 'Europe/Stockholm', currency: 'EUR' }, NOW, false, null);
    const handle = mountCharts(root, { ...built.chart, windows: [], deadline: null, tracks }, built.format, ['step']);
    return { handle, chart: charts[0], root, built };
  }
  const full = () => buildTracks({ horizon: HORIZON, now: NOW, history: day9(), windows: [{ start: T('2026-11-09T20:00:00'), end: T('2026-11-09T21:00:00') }] });
  const segs = (root, lane) => [...root.querySelectorAll(`[data-lane="${lane}"] .track-seg`)];

  it('draws four lanes and positions segments from the chart axis conversion; zoom and pan move them with the prices', () => {
    const { chart, root } = mount(full());
    chart.dispatchAction({ type: 'dataZoom', startValue: T('2026-11-09T00:00:00'), endValue: T('2026-11-09T20:00:00') });
    expect([...root.querySelectorAll('.track-lane')].map(l => l.dataset.lane)).toEqual(['proposal', 'sent', 'effective', 'measured']);
    const z = chart.zoom, bar = root.querySelector('.track-bar');
    expect(bar.style.marginLeft).toBe(`${px(z.startValue)}px`);
    const sent = segs(root, 'sent').find(s => s.dataset.kind === 'sent');
    expect(parseFloat(sent.style.left)).toBeCloseTo(px(Math.max(Number(sent.dataset.start), z.startValue)) - px(z.startValue), 5);
    chart.dispatchAction({ type: 'dataZoom', startValue: T('2026-11-09T00:00:00'), endValue: T('2026-11-09T12:00:00') });
    const z2 = chart.zoom, sent2 = segs(root, 'sent').find(s => s.dataset.kind === 'sent');
    expect(parseFloat(sent2.style.left)).toBeCloseTo(px(Number(sent2.dataset.start)) - px(z2.startValue), 5);
    expect(parseFloat(sent2.style.width)).toBeCloseTo(px(Number(sent2.dataset.end)) - px(Number(sent2.dataset.start)), 5);
    const before = segs(root, 'measured').map(s => [s.dataset.start, s.style.left, s.style.width]);
    chart.handlers.finished?.();
    expect(segs(root, 'measured').map(s => [s.dataset.start, s.style.left, s.style.width])).toEqual(before);
  });
  it('a lane never changes the price chart (series, grid, axes)', () => {
    const plain = mount(null), withTracks = mount(full());
    const a = plain.chart.options[0], b = withTracks.chart.options[0];
    expect(b.yAxis).toEqual(a.yAxis); expect(b.grid).toEqual(a.grid); expect(b.series.length).toBe(a.series.length); expect(b.xAxis).toEqual(a.xAxis);
    expect(plain.root.querySelectorAll('.track-seg').length).toBe(0);
    expect(withTracks.root.querySelectorAll('.track-seg').length).toBeGreaterThan(0);
  });
  it('routine updates keep the user range and redraw the lanes from the new data', () => {
    const { handle, chart, root, built } = mount(full());
    chart.dispatchAction({ type: 'dataZoom', startValue: T('2026-11-09T00:00:00'), endValue: T('2026-11-09T12:00:00') });
    handle.update({ ...built.chart, windows: [], deadline: null, tracks: buildTracks({ horizon: HORIZON, now: NOW, history: null }) }, built.format);
    expect(segs(root, 'sent').every(s => s.dataset.kind === 'unloaded')).toBe(true);
    expect(chart.zoom.startValue).toBe(T('2026-11-09T00:00:00'));
  });
  it('titles are text and hatched kinds are named unknown', () => {
    const { root, chart } = mount(full());
    chart.dispatchAction({ type: 'dataZoom', startValue: T('2026-11-09T00:00:00'), endValue: T('2026-11-09T20:00:00') });
    expect(segs(root, 'sent').find(s => s.dataset.kind === 'sent').title).toContain('Acknowledged is not installed');
    expect(root.querySelector('[data-lane="measured"] .track-caption').textContent).toContain('Measured');
    expect(segs(root, 'effective')[0].dataset.kind).toBe('unknown');
    expect(segs(root, 'sent').find(s => s.dataset.kind === 'unknown').title).toContain('not proof that nothing was installed');
  });
});

describe('a past day on the chart (8.1)', () => {
  it('draws no current proposal and no effective limit for a day that is entirely before now, and says so', () => {
    const lanes = buildTracks({ horizon: [0, 100], now: 1000, windows: [{ start: 10, end: 20 }, { start: 900, end: 1200 }], history: null,
      effective: { state: 'reported', spans: [{ start: 10, end: 20, value: 16 }], unit: 'A', differs: false } }).lanes;
    const byKey = Object.fromEntries(lanes.map(l => [l.key, l]));
    expect(byKey.proposal.note).toMatch(/Past day/); expect(byKey.effective.note).toMatch(/Past day/);
    for (const key of ['proposal', 'effective']) expect(byKey[key].segments.every(s => !/^(proposal|effective)/.test(s.kind))).toBe(true);
  });
});
