// @ts-nocheck
// Stage 7.3a: the one-day history state machine, display model and renderer, against backend-shaped answers
// (the preview's own fixtures, whose wire shape is pinned to the real backend by tests/fixtures/history/answer_shape.json).
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHistoryDay, parseRetention, retainedDayMap, validateHistory, buildHistoryModel, localDate, reviewPriceTarget, priceReviewNote, REFRESH_TODAY_MS, HISTORY_DAYS_BACK } from '../shared-dashboard/history-day.js';
import { renderHistory, renderHistoryDay } from '../shared-dashboard/history-view.js';
import { HISTORY_TODAY, HISTORY_ZONE, historyAnswer, fixtureHistoryRequest, fixtureSessionsRequest } from '../prototype/history-day-fixture.js';

const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const ctx = (over = {}) => ({ charger: 'a', epoch: '1:0', zone: HISTORY_ZONE, marketZone: HISTORY_ZONE, today: HISTORY_TODAY, ...over });
async function load(day, request = fixtureHistoryRequest({ charger: 'a' }), over = {}) {
  const view = createHistoryDay({ request, requestSessions: fixtureSessionsRequest({ charger: 'a' }), onChange: () => {} });
  view.sync(ctx(over)); await tick(); // the first view is yesterday (2026-11-08); the retained list comes with its answer
  if (day !== '2026-11-08') { view.select('day', day); await tick(); }
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
    // 2026-11-04 is before the retained raw window (power rows begin 2026-11-07), so it cannot be selected; the backend's answer for it is modelled directly.
    const out = renderHistoryDay({ ...modelOf(historyAnswer('a', '2026-11-04'), '2026-11-04'), nav: null });
    expect(out).toContain('data-history-banner="none"');
    expect(out).toContain('does not mean nothing happened');
    expect(out).not.toContain('No flow interval');
  });

  it('an older integration without the 7.3a signals says rows cannot be told apart', async () => {
    // An older integration's answer for a day that is no longer selectable: the model is built straight from that backend response.
    const out = renderHistoryDay({ ...modelOf(historyAnswer('a', '2026-11-03'), '2026-11-03'), nav: null });
    expect(out).toContain('data-history-banner="legacy"');
    expect(out).toContain('data-history-banner="unknown-raw"');
    expect(out).not.toContain('data-history-banner="truncated"');
  });

  it('loading, unavailable, failed (with explicit retry), permission and invalid are separate states', async () => {
    const pending = new Promise(() => {});
    const loading = createHistoryDay({ request: () => pending }); loading.sync(ctx());
    expect(renderHistory(null, false, loading.view())).toContain('data-history-state="loading"');
    // the default first view is yesterday, so the backend's refusal and timeout are produced for that day
    expect(await html('2026-11-08', async () => { throw Object.assign(new Error('refused'), { code: 'spotnav_history_unavailable' }); })).toContain('data-history-state="unavailable"');
    const failed = await html('2026-11-08', async () => { throw new Error('timeout'); });
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
    expect(bad).not.toMatch(/data-history-section="(cost|sessions|sent|flow|energy|coverage)"/);
  });
});

describe('history day: request lifecycle', () => {
  const pendingRequest = () => { const calls = []; return { calls, request: params => new Promise((resolve, reject) => calls.push({ params, resolve, reject })) }; };

  it('asks for exactly one local day (yesterday, the default), once, with no price or provider parameter', async () => {
    const r = pendingRequest(), sessions = vi.fn(async () => ({ api_version: 1, charger_id: 'a', days: [] }));
    const view = createHistoryDay({ request: r.request, requestSessions: sessions }); view.sync(ctx()); view.sync(ctx()); view.sync(ctx());
    expect(r.calls.map(c => c.params)).toEqual([{ date: '2026-11-08' }]);
    expect(sessions).toHaveBeenCalledTimes(1);
    expect(view.view().nav.isDefault).toBe(true);
  });
  it('drops a result that arrives after a charger change, a permission change or dispose', async () => {
    for (const change of [v => v.sync(ctx({ charger: 'b' })), v => v.sync(ctx({ epoch: '1:1' })), v => v.dispose()]) {
      const r = pendingRequest(), onChange = vi.fn(), view = createHistoryDay({ request: r.request, onChange }); view.sync(ctx());
      const stale = r.calls[0]; change(view); onChange.mockClear();
      stale.resolve(historyAnswer('a', '2026-11-08')); await tick();
      const shown = view.view();
      expect(shown.state === 'ready' && r.calls.length === 1).toBe(false);
      expect(onChange).not.toHaveBeenCalled();
    }
  });
  it('drops a result for a day that is no longer the chosen one, and a late sessions answer after a charger change', async () => {
    const r = pendingRequest(), onChange = vi.fn(), late = [];
    const view = createHistoryDay({ request: r.request, requestSessions: () => new Promise(resolve => late.push(resolve)), onChange }); view.sync(ctx());
    r.calls[0].resolve(historyAnswer('a', '2026-11-08')); await tick();
    expect(view.select('day', '2026-11-07')).toBe(true); const stale = r.calls[1]; expect(view.select('day', '2026-11-05')).toBe(true); onChange.mockClear(); // 11-05 is a digest day, selectable without the (pending) sessions read
    stale.resolve(historyAnswer('a', '2026-11-07')); await tick();
    expect(onChange).not.toHaveBeenCalled(); expect(view.view().state).toBe('loading'); expect(view.view().nav.day).toBe('2026-11-05');
    view.sync(ctx({ charger: 'b' })); late[0]({ api_version: 1, charger_id: 'a', days: [{ period: '2026-08-20', sessions: 1 }] }); await tick();
    expect(view.view().nav.options.some(o => o.day === '2026-08-20')).toBe(false);
  });
  it('an answer for another charger or day is refused even when it is the newest request', async () => {
    const r = pendingRequest(), view = createHistoryDay({ request: r.request }); view.sync(ctx());
    r.calls[0].resolve(historyAnswer('other', '2026-11-08')); await tick();
    expect(view.view().state).toBe('invalid');
  });
  it('a failure stays until an explicit retry: no automatic loop', async () => {
    const request = vi.fn(async () => { throw new Error('timeout'); }), view = createHistoryDay({ request });
    view.sync(ctx()); await tick(); for (let i = 0; i < 5; i++) { view.sync(ctx()); await tick(); }
    expect(request).toHaveBeenCalledTimes(1); expect(view.view().state).toBe('error');
    expect(view.view().nav.retention).toBe('unknown'); // no metadata: nothing else is offered, nothing can be selected
    expect(view.select('prev')).toBe(false); expect(view.select('day', '2026-11-07')).toBe(false);
    view.retry(); await tick(); expect(request).toHaveBeenCalledTimes(2);
  });
  it('today is re-read only after the interval; yesterday and any past day never; a failed refresh keeps the earlier read and waits again', async () => {
    let clock = 1_000_000; const request = vi.fn(async p => historyAnswer('a', p.date));
    const view = createHistoryDay({ request, now: () => clock }); view.sync(ctx()); await tick();
    clock += REFRESH_TODAY_MS * 5; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(1); // the default yesterday is never refreshed
    view.select('today'); await tick(); expect(request).toHaveBeenCalledTimes(2);
    clock += REFRESH_TODAY_MS - 1; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(2);
    clock += 2; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(3);
    request.mockImplementationOnce(async () => { throw new Error('timeout'); });
    clock += REFRESH_TODAY_MS + 1; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(4);
    const kept = view.view(); expect(kept.state).toBe('ready'); expect(kept.refreshFailed).toBe(true);
    expect(renderHistory(null, false, kept)).toContain('data-history-banner="refresh-failed"');
    expect(kept.nav.canRetry).toBe(true);
    clock += REFRESH_TODAY_MS * 2; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(4);
    view.retry(); await tick(); expect(request).toHaveBeenCalledTimes(5);
    view.select('prev'); await tick(); expect(request).toHaveBeenCalledTimes(6);
    clock += REFRESH_TODAY_MS * 5; view.sync(ctx()); await tick(); expect(request).toHaveBeenCalledTimes(6); // a past day is never refreshed
  });
  it('only retained days can be chosen: raw window, digest dates and session days, at most 62 days back, never the future', async () => {
    const request = vi.fn(async p => historyAnswer('a', p.date)), view = createHistoryDay({ request, requestSessions: fixtureSessionsRequest({ charger: 'a' }) });
    view.sync(ctx()); expect(view.view().nav.retention).toBe('checking');
    expect(view.select('day', '2026-11-07')).toBe(false); // nothing is selectable before the metadata is known
    await tick();
    expect(view.select('day', '2026-11-10')).toBe(false); expect(view.select('day', '2026-10-29')).toBe(false); expect(view.select('day', 'junk')).toBe(false);
    expect(request).toHaveBeenCalledTimes(1);
    const nav = view.view().nav;
    expect(nav.options.map(o => o.day)).toEqual(['2026-11-09', '2026-11-08', '2026-11-07', '2026-11-06', '2026-11-05', '2026-10-12']); // raw window from the oldest power row (11-07), the digest day and the session days
    expect(nav.options.find(o => o.day === '2026-11-09').label).toContain('retained rows');
    expect(nav.canNext).toBe(true); expect(nav.canYesterday).toBe(false);
    expect(view.select('prev')).toBe(true); await tick(); expect(view.select('day', '2026-10-12')).toBe(true); await tick(); // a sessions-only day older than the raw window
    expect(view.view().nav.canPrev).toBe(false); expect(view.select('prev')).toBe(false);
    expect(request.mock.calls.map(c => c[0].date)).toEqual(['2026-11-08', '2026-11-07', '2026-10-12']);
    // today minus 62 days is the oldest offer even when the raw window reaches further back; a digest or session day outside 62 days is never offered
    const old = vi.fn(async p => { const a = structuredClone(historyAnswer('a', p.date)); a.retention.oldest_by_kind.power_w = '2026-07-01T00:00:00+00:00'; a.retention.digest_days = ['2026-08-01', '2026-09-08']; return a; });
    const deep = createHistoryDay({ request: old, requestSessions: async () => ({ api_version: 1, charger_id: 'a', days: [{ period: '2026-08-01', sessions: 1 }, { period: '2026-09-07', sessions: 0 }] }) });
    deep.sync(ctx()); await tick();
    const days = deep.view().nav.options.map(o => o.day);
    expect(days.at(-1)).toBe('2026-09-08'); expect(days).toHaveLength(63); expect(HISTORY_DAYS_BACK).toBe(62);
    expect(deep.select('day', '2026-09-07')).toBe(false); expect(deep.select('day', '2026-08-01')).toBe(false);
  });
  it('tags what each retained day has: rows, summary only, sessions only', async () => {
    const request = async p => { const a = structuredClone(historyAnswer('a', p.date)); a.retention.oldest_evidence = '2026-11-06T10:00:00+00:00'; a.retention.oldest_by_kind = { power_w: '2026-11-07T09:00:00+00:00', current_a: null, energy_register_kwh: null, status: null }; a.retention.digest_days = ['2026-11-04', '2026-11-05']; return a; };
    const view = createHistoryDay({ request, requestSessions: async () => ({ api_version: 1, charger_id: 'a', days: [{ period: '2026-11-02', sessions: 2 }, { period: '2026-11-05', sessions: 1 }] }) });
    view.sync(ctx()); await tick();
    const tag = d => view.view().nav.options.find(o => o.day === d)?.label.split(' · ').at(-1);
    expect([tag('2026-11-09'), tag('2026-11-06'), tag('2026-11-05'), tag('2026-11-04'), tag('2026-11-02'), tag('2026-11-03')]).toEqual(['retained rows', undefined, 'summary only', 'summary only', 'sessions only', undefined]);
  });
  it('an old plan or capture mark before the oldest sample row proves no raw day; the raw window starts at the oldest row of any sample kind', () => {
    const ret = parseRetention({ oldest_evidence: '2026-11-01T10:00:00+00:00', oldest_by_kind: { power_w: '2026-11-07T09:00:00+00:00', current_a: '2026-11-06T23:30:00+00:00', energy_register_kwh: null, status: null }, digest_days: [] }, 'Etc/UTC');
    expect(ret.rawFrom).toBe('2026-11-06');
    const days = [...retainedDayMap(ret, [], '2026-11-09').keys()].sort();
    expect(days).toEqual(['2026-11-06', '2026-11-07', '2026-11-08', '2026-11-09']); // 11-01..11-05 are not raw days
    expect(parseRetention({ oldest_evidence: '2026-11-01T10:00:00+00:00', oldest_by_kind: { power_w: null, current_a: null, energy_register_kwh: null, status: null }, digest_days: [] }, 'Etc/UTC').rawFrom).toBeNull();
    expect(parseRetention({ oldest_evidence: '2026-11-01T10:00:00+00:00' }, 'Etc/UTC')).toBeNull();
  });
  it('days proven by the sessions read are offered even when the retention metadata is unavailable', async () => {
    const request = async () => { throw new Error('timeout'); };
    const view = createHistoryDay({ request, requestSessions: async () => ({ api_version: 1, charger_id: 'a', days: [{ period: '2026-11-06', sessions: 1 }, { period: '2026-11-03', sessions: 0 }] }) });
    view.sync(ctx()); await tick();
    const nav = view.view().nav;
    expect(view.view().state).toBe('error'); expect(nav.options.map(o => o.day)).toEqual(['2026-11-08', '2026-11-06']); // the shown day (unconfirmed) first, then the proven session day
    expect(nav.options.find(o => o.day === '2026-11-06').label).toMatch(/sessions only/); expect(nav.retentionNote).toMatch(/only days with a recorded session/);
    expect(view.select('day', '2026-11-03')).toBe(false); expect(view.select('day', '2026-11-06')).toBe(true);
  });
  it('a failed sessions read still offers the other days, says so, and retries only on request', async () => {
    const sessions = vi.fn(async () => { throw new Error('timeout'); });
    const view = createHistoryDay({ request: fixtureHistoryRequest({ charger: 'a' }), requestSessions: sessions }); view.sync(ctx()); await tick();
    for (let i = 0; i < 3; i++) { view.sync(ctx()); await tick(); }
    expect(sessions).toHaveBeenCalledTimes(1);
    const nav = view.view().nav; expect(nav.options.map(o => o.day)).toEqual(['2026-11-09', '2026-11-08', '2026-11-07', '2026-11-05']); expect(nav.sessionsNote).toMatch(/only sessions may be missing/); expect(nav.canRetry).toBe(true);
    view.retry(); await tick(); expect(sessions).toHaveBeenCalledTimes(2);
  });
  it('the default is yesterday only on the first context: a chosen day survives refreshes, a charger change returns to yesterday', async () => {
    const request = vi.fn(async p => historyAnswer('a', p.date)), view = createHistoryDay({ request, requestSessions: fixtureSessionsRequest({ charger: 'a' }) });
    view.sync(ctx()); await tick(); view.select('day', '2026-11-06'); await tick();
    for (let i = 0; i < 3; i++) { view.sync(ctx()); await tick(); }
    expect(view.view().nav.day).toBe('2026-11-06'); expect(view.view().nav.isDefault).toBe(false); expect(request).toHaveBeenCalledTimes(2);
    view.sync(ctx({ charger: 'b' })); await tick();
    expect(view.view().nav.day).toBe('2026-11-08'); expect(view.view().nav.isDefault).toBe(true);
  });
  it('an unretained yesterday shows loading and then an explicit no-retained-data state, never "did not charge"', async () => {
    const request = async p => { const a = JSON.parse(JSON.stringify(historyAnswer('a', '2026-10-05')).split('2026-10-06').join('2026-11-09').split('2026-10-05').join(p.date)); a.retention.oldest_evidence = '2026-11-09T01:00:00+00:00'; a.retention.digest_days = []; a.retention.oldest_by_kind.power_w = null; a.retention.oldest_by_kind.energy_register_kwh = null; return a; };
    const view = createHistoryDay({ request, requestSessions: async () => ({ api_version: 1, charger_id: 'a', days: [] }) });
    view.sync(ctx()); expect(view.view().state).toBe('loading'); await tick();
    const shown = view.view(), out = renderHistory(null, false, shown);
    expect(shown.raw).toBe('none'); expect(shown.notRetained).toMatch(/not in the retained list/);
    expect(out).toContain('data-history-banner="not-retained"'); expect(out).toContain('does not mean nothing happened'); expect(out).toContain('data-history-empty="sessions"');
    expect(out).toMatch(/not proof that the car did not charge/); expect(shown.nav.options.map(o => o.day)).toEqual(['2026-11-08']); // plan evidence today (oldest_evidence) proves no raw row, so nothing is offered
  });
  it('maps a Home Assistant day onto the market calendar for the held-price request (DST, midnight, two zones)', () => {
    const span = day => { const s = Date.parse(`${day}T00:00:00Z`); return [s, s + 86400000]; };
    expect(reviewPriceTarget(span('2026-11-08'), 'Etc/UTC', '2026-11-09')).toEqual({ days: ['2026-11-08'], page: '2026-11-08', crossesMarketDays: false });
    // Helsinki-time day against a Stockholm market: 00:00 EET is 23:00 CET the day before
    const helsinki = [Date.UTC(2026, 10, 7, 22), Date.UTC(2026, 10, 8, 22)];
    expect(reviewPriceTarget(helsinki, 'Europe/Stockholm', '2026-11-09')).toEqual({ days: ['2026-11-07', '2026-11-08'], page: '2026-11-08', crossesMarketDays: true });
    // a Stockholm-time day against a market ahead of it: the later market day is today (live feed) so the page ends at the earlier one; with both days not before today no page exists
    const stockholm = [Date.UTC(2026, 10, 7, 23), Date.UTC(2026, 10, 8, 23)];
    expect(reviewPriceTarget(stockholm, 'Europe/Riga', '2026-11-09')).toEqual({ days: ['2026-11-08', '2026-11-09'], page: '2026-11-08', crossesMarketDays: true });
    expect(reviewPriceTarget(stockholm, 'Europe/Riga', '2026-11-08')).toEqual({ days: ['2026-11-08', '2026-11-09'], page: null, crossesMarketDays: true });
    // 25-hour autumn day (Europe/Stockholm, 2026-10-25) and 23-hour spring day (2026-03-29) keep their exact end instants
    const autumn = [Date.UTC(2026, 9, 24, 22), Date.UTC(2026, 9, 25, 23)], spring = [Date.UTC(2026, 2, 28, 23), Date.UTC(2026, 2, 29, 22)];
    expect(reviewPriceTarget(autumn, 'Europe/Stockholm', '2026-11-01')).toEqual({ days: ['2026-10-25'], page: '2026-10-25', crossesMarketDays: false });
    expect(reviewPriceTarget(spring, 'Europe/Stockholm', '2026-04-01')).toEqual({ days: ['2026-03-29'], page: '2026-03-29', crossesMarketDays: false });
    expect(reviewPriceTarget(null, 'Europe/Stockholm', '2026-11-09')).toBeNull();
    expect(priceReviewNote({ day: 'x', status: 'not_held', days: ['2026-11-08'], marketZone: 'Europe/Stockholm' }, 'y')).toBe('');
    // a pending request is said to be requested, never already drawn
    const pending = priceReviewNote({ day: 'x', status: 'loading', days: ['2026-11-07', '2026-11-08'], marketZone: 'Europe/Stockholm', crosses: true }, 'x');
    expect(pending).toMatch(/^Requested held prices for 2026-11-07 and 2026-11-08/); expect(pending).toMatch(/changes only after the read succeeds/); expect(pending).toMatch(/covers two market days/); expect(pending).not.toMatch(/are drawn/);
    expect(priceReviewNote({ day: 'x', status: 'shown', days: ['2026-11-08'], marketZone: 'Europe/Stockholm', crosses: false }, 'x')).toMatch(/are drawn on the chart/);
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
