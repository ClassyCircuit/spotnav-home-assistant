// @ts-nocheck
// Stage 7.3a: the one-day history state machine, display model and renderer, against backend-shaped answers
// (the preview's own fixtures, whose wire shape is pinned to the real backend by tests/fixtures/history/answer_shape.json).
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHistoryDay, validateHistory, buildHistoryModel, localDate, REFRESH_TODAY_MS, HISTORY_DAYS_BACK } from '../shared-dashboard/history-day.js';
import { renderHistory, renderHistoryDay } from '../shared-dashboard/history-view.js';
import { HISTORY_TODAY, HISTORY_ZONE, historyAnswer, fixtureHistoryRequest } from '../prototype/history-day-fixture.js';

const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const ctx = (over = {}) => ({ charger: 'a', epoch: '1:0', zone: HISTORY_ZONE, marketZone: HISTORY_ZONE, today: HISTORY_TODAY, ...over });
async function load(day, request = fixtureHistoryRequest({ charger: 'a' }), over = {}) {
  const view = createHistoryDay({ request, onChange: () => {} });
  view.sync(ctx(over));
  if (day !== HISTORY_TODAY) { view.select('day', day); }
  await tick();
  return view;
}
const html = async (day, request) => renderHistory(null, false, (await load(day, request)).view());
const answerFor = (day, change) => { const a = structuredClone(historyAnswer('a', day)); change(a); return a; };
const modelOf = (answer, day = '2026-11-09') => buildHistoryModel(answer, day, { stamp: iso => iso.slice(11, 16) });
const normalized = value => JSON.parse(JSON.stringify(value, (_k, v) => v));

describe('history day: every backend situation renders distinctly', () => {
  it('full evidence: sent block with flow observed, bounded edges, energy bases, a reconciled session', async () => {
    const out = await html('2026-11-09');
    expect(out).toContain('data-history-raw="full"');
    expect(out).toContain('— Flow observed');
    expect(out).toContain('plan p1');
    expect(out).toMatch(/start bounded · end bounded/);
    expect(out).toContain('Register total matches placed energy');
    expect(out).not.toContain('data-history-banner="truncated"');
    expect(out).toContain('about the last 3 days at one reading per minute');
    expect(out).toContain('not a guaranteed 7 days');
  });

  it('unknown plan span, outside/unknown flow, open edge, unknown block, uncertain session, truncation', async () => {
    const out = await html('2026-11-08');
    expect(out).toContain('data-history-banner="truncated"');
    expect(out).toContain('capture gaps: first 200 shown, 12 more not shown');
    expect(out).toContain('what the charger had installed is unknown');
    expect(out).toContain('Plan unknown');
    expect(out).toContain('Flow outside the sent plan');
    expect(out).toContain('Flow while the sent plan was unknown');
    expect(out).toMatch(/end open \(data gap, restart or data start beside it\)/);
    expect(out).toMatch(/— Unknown/);
    expect(out).toContain('measured rows do not cover the whole block');
    expect(out).toContain('intent uncertain after 22:30');
    expect(out).toContain('Register total uncertain (late register unassigned)');
    expect(out).toContain('Unplaced late energy 1.40 kWh: no known time');
    expect(out).toContain('Later register rise 0.60 kWh');
    expect(out).toContain('The session total is not certified');
    expect(out).toContain('2 single reading(s)');
    expect(out).toContain('more not shown'.slice(0, 4));
    expect(out).toContain('more gap(s) not listed.');
  });

  it('partial raw: power rows begin mid-day and what is before is unknown, not zero', async () => {
    const out = await html('2026-11-07');
    expect(out).toContain('data-history-banner="partial-raw"');
    expect(out).toContain('only from 09:00');
    expect(out).toContain('unknown, not zero');
  });

  it('plans and a session without power rows: flow unknown, never no-flow, block explains why', async () => {
    const out = await html('2026-11-06');
    expect(out).toContain('data-history-banner="no-power"');
    expect(out).toContain('flow is unknown, not zero');
    expect(out).toContain('starts before the retained power rows');
    expect(out).not.toContain('No flow observed');
    expect(out).not.toContain('data-history-section="flow"');
    expect(out).not.toContain('data-history-section="energy"');
    expect(out).toContain('data-history-section="sessions"');
  });

  it('raw pruned, digest only: the saved summary facts, no invented intervals or price rows', async () => {
    const out = await html('2026-11-05');
    expect(out).toContain('data-history-banner="digest"');
    expect(out).toContain('data-history-section="digest"');
    expect(out).toContain('02:05–02:55');
    expect(out).toContain('keeps no price rows');
    expect(out).toContain('Separate bases, never added together.');
    expect(out).not.toContain('data-history-section="flow"');
    expect(out).not.toContain('data-history-section="coverage"');
  });

  it('nothing retained is not "did not charge"', async () => {
    const out = await html('2026-11-04');
    expect(out).toContain('data-history-banner="none"');
    expect(out).toContain('does not mean nothing happened');
    expect(out).not.toContain('No flow interval');
  });

  it('an older integration without the 7.3a signals says rows cannot be told apart', async () => {
    const out = await html('2026-11-03');
    expect(out).toContain('data-history-banner="legacy"');
    expect(out).toContain('data-history-banner="unknown-raw"');
    expect(out).not.toContain('data-history-banner="truncated"');
  });

  it('loading, unavailable, failed (with explicit retry), permission and invalid are separate states', async () => {
    const pending = new Promise(() => {});
    const loading = createHistoryDay({ request: () => pending }); loading.sync(ctx());
    expect(renderHistory(null, false, loading.view())).toContain('data-history-state="loading"');
    expect(await html('2026-11-02')).toContain('data-history-state="unavailable"');
    const failed = await html('2026-11-01');
    expect(failed).toContain('data-history-state="error"'); expect(failed).toContain('data-history-nav="retry"');
    const denied = await html('2026-11-08', async () => { throw Object.assign(new Error('x'), { code: 'unauthorized' }); });
    expect(denied).toContain('data-history-state="permission"'); expect(denied).toContain('permission to read charging history');
    const garbage = await html('2026-11-08', async () => ({ api_version: 1 }));
    expect(garbage).toContain('data-history-state="invalid"');
    const noZone = createHistoryDay({ request: async () => null }); noZone.sync(null);
    expect(renderHistory(null, false, noZone.view())).toContain('time zone');
  });
});

describe('history day: null versus zero, bases are never combined', () => {
  it('no segment is "Unavailable"; a measured zero is 0.00 kWh; meter and integrated stay apart', () => {
    const a = answerFor('2026-11-09', x => { x.observed.energy.meter_counter_kwh = 0; x.observed.energy.power_integrated_estimate_kwh = null; x.observed.energy.meter_counter_unobserved_kwh = null; });
    const out = renderHistoryDay({ ...modelOf(a), nav: null });
    expect(out).toMatch(/data-basis-value="0"><b>Meter-counter delta<\/b><span>0\.00 kWh/);
    expect(out).toMatch(/data-basis-value="null"><b>Power-integrated estimate<\/b><span>Unavailable/);
    expect(out).toMatch(/data-basis-value="null"><b>Meter energy with unknown placement<\/b><span>Unavailable/);
    expect(out).toContain('never added together');
  });
  it('meter delta, integrated estimate and session energy appear side by side and no sum is shown', () => {
    const a = answerFor('2026-11-09', x => { x.observed.energy.meter_counter_kwh = 5; x.observed.energy.power_integrated_estimate_kwh = 7; x.sessions[0].energy_kwh = 4; x.sessions[0].reconciliation.state = 'unknown'; });
    const out = renderHistoryDay({ ...modelOf(a), nav: null });
    for (const t of ['5.00 kWh', '7.00 kWh', 'placed energy 4.00 kWh']) expect(out).toContain(t);
    for (const sum of ['12.0', '16.0', '11.0', '9.00', '12.00', '16.00']) expect(out).not.toContain(sum);
  });
  it('late and unassigned energy never raise the session total nor certify it', () => {
    const a = answerFor('2026-11-08', () => {});
    const m = modelOf(a, '2026-11-08');
    const s = m.sessions[0];
    expect(s.text).toContain('placed energy 8.20 kWh');
    expect(s.lines.join('|')).not.toMatch(/Register total \d/); // no certified total for an uncertain session
    expect(s.lines.join('|')).toContain('not certified');
  });
});

describe('history day: validation of the wire', () => {
  const asked = { charger: 'a', day: '2026-11-09', zone: HISTORY_ZONE };
  it('accepts the fixture and refuses a wrong day, charger, version, list or an over-cap list', () => {
    expect(validateHistory(historyAnswer('a', '2026-11-09'), asked)).toBe(true);
    expect(validateHistory(historyAnswer('b', '2026-11-09'), asked)).toBe(false);
    expect(validateHistory(historyAnswer('a', '2026-11-08'), asked)).toBe(false);
    expect(validateHistory({ ...historyAnswer('a', '2026-11-09'), api_version: 2 }, asked)).toBe(false);
    expect(validateHistory(answerFor('2026-11-09', x => { x.observed.intervals = null; }), asked)).toBe(false);
    expect(validateHistory(answerFor('2026-11-09', x => { x.observed.gaps = Array(201).fill(x.observed.gaps[0] || {}); }), asked)).toBe(false);
    expect(validateHistory(answerFor('2026-11-09', x => { x.comparison.planned_blocks[0].start = 'nope'; }), asked)).toBe(false);
    expect(validateHistory(null, asked)).toBe(false);
    expect(validateHistory(answerFor('2026-11-09', x => { x.window.zone = 'Wrong/Zone'; }), asked)).toBe(false);
  });
  it('malformed rows fall back to invalid, never a partial render', async () => {
    const bad = await html('2026-11-09', async p => answerFor('2026-11-09', x => { x.sessions = [null]; }));
    expect(bad).toContain('data-history-state="invalid"');
    expect(bad).not.toContain('data-history-section');
  });
});

describe('history day: request lifecycle', () => {
  const pendingRequest = () => { const calls = []; return { calls, request: params => new Promise((resolve, reject) => calls.push({ params, resolve, reject })) }; };

  it('asks for exactly one local day, once, with no price or provider parameter', async () => {
    const r = pendingRequest(), view = createHistoryDay({ request: r.request }); view.sync(ctx()); view.sync(ctx()); view.sync(ctx());
    expect(r.calls.map(c => c.params)).toEqual([{ date: HISTORY_TODAY }]);
  });
  it('drops a result that arrives after a charger change, a permission change, a day change or dispose', async () => {
    for (const change of [v => v.sync(ctx({ charger: 'b' })), v => v.sync(ctx({ epoch: '1:1' })), v => v.select('prev'), v => v.dispose()]) {
      const r = pendingRequest(), onChange = vi.fn(), view = createHistoryDay({ request: r.request, onChange }); view.sync(ctx());
      const stale = r.calls[0]; change(view); onChange.mockClear();
      stale.resolve(historyAnswer('a', HISTORY_TODAY)); await tick();
      const shown = view.view();
      expect(shown.state === 'ready' && shown.day === HISTORY_TODAY && shown.nav?.day === HISTORY_TODAY && r.calls.length === 1).toBe(false);
      expect(onChange).not.toHaveBeenCalled();
    }
  });
  it('an answer for another charger or day is refused even when it is the newest request', async () => {
    const r = pendingRequest(), view = createHistoryDay({ request: r.request }); view.sync(ctx());
    r.calls[0].resolve(historyAnswer('other', HISTORY_TODAY)); await tick();
    expect(view.view().state).toBe('invalid');
  });
  it('a failure stays until an explicit retry: no automatic loop', async () => {
    const request = vi.fn(async () => { throw new Error('timeout'); }), view = createHistoryDay({ request });
    view.sync(ctx()); await tick(); for (let i = 0; i < 5; i++) { view.sync(ctx()); await tick(); }
    expect(request).toHaveBeenCalledTimes(1); expect(view.view().state).toBe('error');
    view.retry(); await tick(); expect(request).toHaveBeenCalledTimes(2);
  });
  it('today is re-read only after the interval; a past day never; a failed refresh keeps the earlier read and waits again', async () => {
    let clock = 1_000_000; const request = vi.fn(async p => historyAnswer('a', p.date));
    const view = createHistoryDay({ request, now: () => clock }); view.sync(ctx()); await tick();
    clock += REFRESH_TODAY_MS - 1; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(1);
    clock += 2; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(2);
    request.mockImplementationOnce(async () => { throw new Error('timeout'); });
    clock += REFRESH_TODAY_MS + 1; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(3);
    const kept = view.view(); expect(kept.state).toBe('ready'); expect(kept.refreshFailed).toBe(true);
    expect(renderHistory(null, false, kept)).toContain('data-history-banner="refresh-failed"');
    expect(kept.nav.canRetry).toBe(true);
    clock += REFRESH_TODAY_MS * 2; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(3);
    view.retry(); await tick(); expect(request).toHaveBeenCalledTimes(4);
    view.select('prev'); await tick(); expect(request).toHaveBeenCalledTimes(5);
    clock += REFRESH_TODAY_MS * 5; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(5); // a past day is never refreshed
  });
  it('selection is bounded to the retained range and each choice loads one day', async () => {
    const request = vi.fn(async p => historyAnswer('a', p.date)), view = createHistoryDay({ request });
    view.sync(ctx()); await tick();
    view.select('next'); view.select('day', '2026-11-10'); view.select('day', '2026-09-01'); view.select('day', 'junk'); await tick();
    expect(request).toHaveBeenCalledTimes(1);
    view.select('yesterday'); await tick(); view.select('prev'); await tick(); view.select('today'); await tick();
    expect(request.mock.calls.map(c => c[0])).toEqual([{ date: '2026-11-09' }, { date: '2026-11-08' }, { date: '2026-11-07' }, { date: '2026-11-09' }]);
    expect(request.mock.calls.every(c => Object.keys(c[0]).join() === 'date')).toBe(true);
    const last = `2026-09-08`; // today - 62 days
    view.select('day', last); await tick(); expect(request).toHaveBeenCalledTimes(5);
    expect(view.view().nav.canPrev).toBe(false);
    expect(HISTORY_DAYS_BACK).toBe(62);
  });
  it('a routine sync (dashboard refresh) never clobbers the selected past day', async () => {
    const request = vi.fn(async p => historyAnswer('a', p.date)), view = createHistoryDay({ request });
    view.sync(ctx()); await tick(); view.select('day', '2026-11-07'); await tick();
    for (let i = 0; i < 4; i++) { view.sync(ctx()); await tick(); }
    expect(view.view().nav.day).toBe('2026-11-07'); expect(request).toHaveBeenCalledTimes(2);
  });
  it('the zone is honest when Home Assistant and the price market differ', async () => {
    const view = createHistoryDay({ request: fixtureHistoryRequest({ charger: 'a' }) }); view.sync(ctx({ marketZone: 'Europe/Stockholm' }));
    expect(view.view().nav.zoneNote).toMatch(/Home Assistant time \(Etc\/UTC\); the price chart follows Europe\/Stockholm, so a day here is not the chart's day/);
    const same = createHistoryDay({ request: async () => null }); same.sync(ctx());
    expect(same.view().nav.zoneNote).toBe('Day in Home Assistant time (Etc/UTC).');
    expect(localDate(Date.UTC(2026, 10, 9, 23, 30), 'Europe/Stockholm')).toBe('2026-11-10');
  });
});

describe('history day: the panel is read-only and parity-checked', () => {
  it('renders no write control: only day navigation', async () => {
    const out = renderHistory(null, false, (await load('2026-11-08')).view());
    const ids = [...out.matchAll(/data-history-nav="(\w+)"/g)].map(m => m[1]);
    expect(new Set(ids)).toEqual(new Set(['prev', 'next', 'yesterday', 'today']));
    expect(out).not.toMatch(/Send|Upload|Replan|Wake|Notify|Start|Stop|Save/);
  });
  it('the preview fixtures have the real backend wire shape (pinned by the Python builder test)', () => {
    const shape = JSON.parse(readFileSync('../tests/fixtures/history/answer_shape.json', 'utf8'));
    const keys = rows => [...new Set(rows.flatMap(r => Object.keys(r)))].sort();
    const days = ['2026-11-09', '2026-11-08', '2026-11-07', '2026-11-06'].map(d => historyAnswer('a', d));
    const a = days[1];
    expect(Object.keys(a).sort()).toEqual(shape.top);
    expect(Object.keys(a.window).sort()).toEqual(shape.window);
    expect(Object.keys(a.retention).sort()).toEqual(shape.retention);
    expect(Object.keys(a.retention.oldest_by_kind).sort()).toEqual(shape.oldest_by_kind);
    expect(Object.keys(a.retention.limits).sort()).toEqual(shape.limits);
    expect(Object.keys(a.truncated).sort()).toEqual(shape.truncated);
    expect(Object.keys(a.truncated.gaps).sort()).toEqual(shape.truncated_row);
    expect(Object.keys(a.truncated.price_slices).sort()).toEqual(shape.price_slices_signal);
    expect(Object.keys(a.observed).sort()).toEqual(shape.observed);
    expect(Object.keys(a.observed.coverage).sort()).toEqual(shape.coverage);
    expect(Object.keys(a.observed.energy).sort()).toEqual(shape.energy);
    expect(keys(a.observed.intervals)).toEqual(shape.interval);
    expect(keys(a.observed.gaps)).toEqual(shape.gap);
    expect(Object.keys(a.comparison).sort()).toEqual(shape.comparison);
    expect(keys(a.comparison.planned_blocks)).toEqual(shape.block);
    expect(keys(a.comparison.outside_plan)).toEqual(shape.outside);
    expect(keys(a.comparison.unknown_plan_spans)).toEqual(shape.unknown_span);
    expect(keys(a.sessions)).toEqual(shape.session);
    expect(keys(a.sessions.map(s => s.reconciliation))).toEqual(shape.reconciliation);
  });
  it('the model is plain data: formatting only, no planning (same input, same output)', () => {
    const a = historyAnswer('a', '2026-11-08');
    expect(normalized(modelOf(a, '2026-11-08'))).toEqual(normalized(modelOf(structuredClone(a), '2026-11-08')));
  });
});
