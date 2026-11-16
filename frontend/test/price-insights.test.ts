// @ts-nocheck
// Stage 7.5: live price insights and monthly statistics. Real validators, request state machine and renderer; only the
// request function is fake and answers in the backend's shapes (the preview fixtures are the same shapes).
import { describe, it, expect } from 'vitest';
import { createPriceInsights, parseLive, parseMonthly, compareMonths, monthOptions, DURATIONS, LIVE_REFRESH_MS } from '../shared-dashboard/price-insights.js';
import { renderInsights } from '../shared-dashboard/insight-view.js';
import { liveAnswer, monthlyAnswer, INSIGHT_TODAY, INSIGHT_NOW } from '../prototype/insight-fixture.js';

const ctx = { charger: 'c1', epoch: '1:0', area: 'SAMPLE-1', currency: 'EUR' };
const sync = { ...ctx, today: INSIGHT_TODAY };
const asked = { charger: 'c1', area: 'SAMPLE-1', currency: 'EUR' };
const tick = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const clone = x => JSON.parse(JSON.stringify(x));
const live = (over = {}, duration = 60) => ({ ...clone(liveAnswer(ctx, duration)), ...over });
const month = (m, over = {}) => ({ ...clone(monthlyAnswer(ctx, m)), ...over });
const answerFor = params => params.mode === 'live' ? liveAnswer(ctx, params.duration_minutes) : monthlyAnswer(ctx, params.month);

function harness(handler = answerFor, start = INSIGHT_NOW) {
  const calls = [], waiting = [], clock = { t: start }; let changes = 0;
  const request = params => { calls.push(params); const r = handler(params, calls.length); return r instanceof Promise ? r : Promise.resolve().then(() => { if (r instanceof Error) throw r; return r; }); };
  const insights = createPriceInsights({ request, onChange: () => { changes++; }, now: () => clock.t });
  return { insights, calls, clock, waiting, changes: () => changes };
}
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const block = (view, id) => view.blocks.find(b => b.id === id);
const line = (b, label) => b.lines.find(l => l.label === label)?.text;

describe('answer validators (the backend contract, nothing guessed)', () => {
  it('accepts a good live answer and refuses a wrong charger, area, currency, mode, basis, duration or malformed top level', () => {
    expect(parseLive(live(), { ...asked, duration: 60 })).not.toBeNull();
    for (const bad of [{ charger_id: 'other' }, { area_id: 'SE3' }, { currency: 'SEK' }, { mode: 'monthly' }, { api_version: 2 }, { zone: 'Not/AZone' }, { now: 'x' },
      { basis: { kind: 'published_spot', unit: 'major_per_kwh', currency: 'EUR', fees: 'included' } }, { basis: null }, { window_minutes: 90 }]) expect(parseLive(live(bad), { ...asked, duration: 60 })).toBeNull();
    expect(parseLive(null, { ...asked, duration: 60 })).toBeNull();
    expect(parseLive(live({}, 60), { ...asked, duration: 90 })).toBeNull();
  });

  it('a malformed optional block becomes unknown on its own; the other block and the price still show (never a partial false model)', () => {
    const noWindow = live(); delete noWindow.cheapest_window;
    const p = parseLive(noWindow, { ...asked, duration: 60 });
    expect(p.current.known).toBe(true); expect(p.window.known).toBe(false);
    const badWindow = live(); badWindow.cheapest_window.end = badWindow.cheapest_window.start; // zero length
    expect(parseLive(badWindow, { ...asked, duration: 60 }).window.known).toBe(false);
    const wrongLength = live(); wrongLength.cheapest_window.duration_minutes = 30;
    expect(parseLive(wrongLength, { ...asked, duration: 60 }).window.reason).toBe('inconsistent');
    const noCurrent = live(); delete noCurrent.current;
    const q = parseLive(noCurrent, { ...asked, duration: 60 });
    expect(q.current.known).toBe(false); expect(q.window.known).toBe(true);
    const nullPrice = live(); nullPrice.current.interval.price = null;
    expect(parseLive(nullPrice, { ...asked, duration: 60 }).current.known).toBe(false);
  });

  it('a contradicting baseline or percentile makes only the comparison unknown', () => {
    const short = live(); short.baseline.days_used = 3; // "known" with fewer than the 7-day minimum
    const a = parseLive(short, { ...asked, duration: 60 });
    expect(a.current.known).toBe(true); expect(a.current.comparison.known).toBe(false); expect(a.baseline.known).toBe(false);
    const over = live(); over.baseline.days_used = 40;
    expect(parseLive(over, { ...asked, duration: 60 }).baseline.known).toBe(false);
    const bad = live(); bad.current.comparison.percentile = 140;
    expect(parseLive(bad, { ...asked, duration: 60 }).current.comparison.known).toBe(false);
    const nullPercent = live(); nullPercent.current.comparison.percentile = null;
    expect(parseLive(nullPercent, { ...asked, duration: 60 }).current.comparison.known).toBe(false);
  });

  it('monthly: valid answers parse, unknown months keep their counts, contradictions are refused', () => {
    const ok = parseMonthly(month('2026-10'), { ...asked, month: '2026-10' });
    expect(ok.known).toBe(true); expect(ok.daysComplete).toBe(29); expect(ok.toDate).toBe(false);
    const young = parseMonthly(month('2026-11'), { ...asked, month: '2026-11' });
    expect(young.toDate).toBe(true); expect(young.asOf).toBe('2026-11-08');
    const first = parseMonthly(month('2026-11', { days_expected: 0, days_complete: 0, days_partial: 0, status: 'unknown', unknown_reason: 'no_completed_days', statistics: null, coverage: { seconds_expected: 0, seconds_valid: 0, seconds_partial: 0, valid_ratio: null } }), { ...asked, month: '2026-11' });
    expect(first.known).toBe(false); expect(first.coverage.ratio).toBeNull(); expect(first.reason).toBe('no_completed_days');
    const bads = [month('2026-10', { month: '2026-09' }), month('2026-10', { currency: 'SEK' }), month('2026-10', { scope: 'weekly' }), month('2026-10', { days_complete: 40 }),
      month('2026-10', { days_partial: 30 }), month('2026-10', { days_expected: 'x' }), month('2026-10', { statistics: null }), month('2026-10', { comparable: { meets_minimum: false } }), month('2026-10', { days_complete: 5, days_partial: 0 })];
    for (const bad of bads) expect(parseMonthly(bad, { ...asked, month: '2026-10' })).toBeNull();
    const unorder = month('2026-10'); unorder.statistics.p10 = unorder.statistics.p90 + 1;
    expect(parseMonthly(unorder, { ...asked, month: '2026-10' })).toBeNull();
    const share = month('2026-10'); share.statistics.negative_share = 120;
    expect(parseMonthly(share, { ...asked, month: '2026-10' })).toBeNull();
    const cover = month('2026-10'); cover.coverage.seconds_valid = cover.coverage.seconds_expected + 1;
    expect(parseMonthly(cover, { ...asked, month: '2026-10' })).toBeNull();
    const phantom = month('2026-09'); phantom.statistics = { ...month('2026-10').statistics };
    expect(parseMonthly(phantom, { ...asked, month: '2026-09' })).toBeNull();
  });
});

describe('display: absolute band and relative percentile are two statements; unknown is never zero', () => {
  async function viewWith(answerOver, currency = 'EUR') {
    const h = harness(p => p.mode === 'live' ? answerOver : monthlyAnswer(ctx, p.month));
    h.insights.sync({ ...sync, currency }); await tick();
    return h.insights.sync({ ...sync, currency }).view();
  }

  it('converts euro to cents exactly once and uses the fixed bands at their boundaries', async () => {
    const cases = [[0.0733, '7.33 c/kWh', 'cheap'], [0.08, '8 c/kWh', 'normal'], [0.1499, '14.99 c/kWh', 'normal'], [0.15, '15 c/kWh', 'medium'], [0.25, '25 c/kWh', 'medium'], [0.2501, '25.01 c/kWh', 'expensive'], [-0.012, '-1.2 c/kWh', 'cheap'], [0, '0 c/kWh', 'cheap']];
    for (const [raw, text, band] of cases) {
      const a = live(); a.current.interval.price = raw; a.current.interval.start = new Date(INSIGHT_NOW - 600000).toISOString(); a.current.interval.end = new Date(INSIGHT_NOW + 600000).toISOString();
      const view = await viewWith(a), cur = block(view, 'current');
      expect(cur.value).toBe(text); expect(cur.band).toBe(band);
      expect(cur.status).toMatch(/band \(.* c\/kWh, fixed\)/);
    }
  });

  it('keeps the absolute band and the relative percentile on separate lines, and never labels cheap from the rank', async () => {
    const view = await viewWith(live()), cur = block(view, 'current');
    expect(cur.status).toMatch(/^In the \w+ band/);
    expect(line(cur, 'Relative')).toMatch(/Compared with 26 of the last 30 days: higher than about 63% of that time/);
    expect(line(cur, 'Relative')).not.toMatch(/Cheap|Normal|Medium|Expensive/);
    const w = block(view, 'window');
    expect(line(w, 'Relative')).toMatch(/^Assumption: .*single interval prices.*about 10% of interval time/);
    expect(w.status).toMatch(/1 h$/); expect(line(w, 'Not a plan')).toMatch(/not the charging plan/);
  });

  it('a non-euro currency is neutral: its own unit, raw numbers, no band', async () => {
    const a = live({ currency: 'SEK', basis: { kind: 'published_spot', unit: 'major_per_kwh', currency: 'SEK', fees: 'none' } });
    const h = harness(p => p.mode === 'live' ? a : { ...monthlyAnswer(ctx, p.month), currency: 'SEK', basis: a.basis });
    h.insights.sync({ ...sync, currency: 'SEK' }); await tick();
    const cur = block(h.insights.sync({ ...sync, currency: 'SEK' }).view(), 'current');
    expect(cur.value).toMatch(/SEK\/kWh$/); expect(cur.band).toBeNull(); expect(cur.status).toMatch(/No fixed band is defined for SEK/);
    expect(cur.value).not.toMatch(/c\/kWh/);
  });

  it('a missing baseline leaves the known price visible and the comparison unknown with the reason; no price is Unavailable, never 0', async () => {
    const a = live(); a.baseline = { ...a.baseline, status: 'unknown', unknown_reason: 'baseline_too_short', days_used: 4 }; a.current.comparison = { status: 'unknown', unknown_reason: 'baseline_unknown', percentile: null };
    const cur = block(await viewWith(a), 'current');
    expect(cur.value).toMatch(/c\/kWh/); expect(line(cur, 'Relative')).toMatch(/^Unknown: .*(fewer than 7|baseline)/); expect(line(cur, 'Relative')).toMatch(/4 of 30 recent days usable, 7 needed/);
    const none = live(); none.current = { status: 'unknown', unknown_reason: 'no_current_interval', interval: null, comparison: null };
    const view = await viewWith(none), c2 = block(view, 'current');
    expect(c2.value).toBe('Unavailable'); expect(c2.status).toMatch(/no current price interval/);
    const html = renderInsights(view); expect(html).not.toMatch(/NaN|Infinity|undefined|>0 c\/kWh/);
  });

  it('shows no window rather than an invented one when nothing contiguous is published', async () => {
    const a = live(); a.cheapest_window = { status: 'unknown', unknown_reason: 'no_contiguous_window', duration_minutes: 60, start: null, end: null, mean_price: null, comparison: null, horizon: null };
    const w = block(await viewWith(a), 'window');
    expect(w.value).toBe('Unavailable'); expect(w.status).toMatch(/no unbroken published stretch/);
  });

  it('after the read interval ended, "current" wording is dropped (price at last read)', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.clock.t = INSIGHT_NOW + 20 * 60000; // 14:50: the 14:30-14:45 interval has ended
    const cur = block(h.insights.view(), 'current');
    expect(cur.title).toBe('Price at last read'); expect(line(cur, 'Interval')).toMatch(/ended; waiting for a refresh/);
  });

  it('monthly: n of N complete, partial, excluded, coverage, mean, range, percentiles, negative share, to-date wording', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    let m = block(h.insights.view(), 'month');
    expect(m.title).toBe('November 2026 so far'); expect(m.status).toMatch(/8 of 8 completed days \(through 2026-11-08\) · month not complete/);
    expect(m.value).toBe('12.34 c/kWh'); expect(line(m, 'Range')).toBe('Low -1.2 c/kWh · high 43.1 c/kWh');
    expect(line(m, 'Spread')).toMatch(/3\.4 c\/kWh · 10\.9 c\/kWh · 23\.6 c\/kWh/); expect(line(m, 'Below zero')).toBe('1.4% of the time (3.0 h)');
    h.insights.selectMonth('2026-10'); await tick();
    m = block(h.insights.view(), 'month');
    expect(m.status).toBe('29 of 31 days complete · 1 partial'); expect(line(m, 'Excluded days')).toBe('2 excluded (1 incomplete, 1 not held)');
    expect(line(m, 'Coverage')).toMatch(/93\.5% of the expected time.*1 partial day\(s\) are counted apart/);
  });

  it('monthly: too few complete days and the first day of a month are unknown with a reason, never a zero price', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.insights.selectMonth('2026-09'); await tick();
    let m = block(h.insights.view(), 'month');
    expect(m.value).toBe('Unavailable'); expect(line(m, 'Unknown')).toMatch(/fewer than 7 complete days.*\(7 needed\)/); expect(m.status).toBe('4 of 30 days complete · 2 partial');
    const first = harness(p => p.mode === 'live' ? liveAnswer(ctx, 60) : month('2026-11', { days_expected: 0, days_complete: 0, days_partial: 0, status: 'unknown', unknown_reason: 'no_completed_days', statistics: null, days_excluded: { count: 0, reasons: {} }, coverage: { seconds_expected: 0, seconds_valid: 0, seconds_partial: 0, valid_ratio: null } }));
    first.insights.sync(sync); await tick();
    m = block(first.insights.view(), 'month');
    expect(m.value).toBe('Unavailable'); expect(line(m, 'Unknown')).toMatch(/no day of this month has completed yet/); expect(line(m, 'Coverage')).toBe('No completed day to measure yet');
  });

  it('text from the host is escaped, never markup', () => {
    const html = renderInsights({ intro: '<img src=x onerror=1>', blocks: [{ id: 'x', title: '<b>t</b>', value: '1', status: '"s"', lines: [{ label: '<l>', text: '<script>' }], details: ['<i>d</i>'] }], banners: [{ kind: 'e"', text: '<u>' }], caution: '<c>', method: '<m>' });
    expect(html).not.toMatch(/<img|<script|<b>t|<u>|<i>d/); expect(html).toContain('&lt;script&gt;');
  });
});

describe('month comparison (side by side, only when both qualify)', () => {
  const entry = (m, over = {}) => ({ status: 'ready', parsed: parseMonthly(month(m, over), { ...asked, month: m }) });
  it('shows both columns with their coverage and no computed difference', () => {
    const t = compareMonths(entry('2026-10'), entry('2026-11'));
    expect(t.eligible).toBe(true); expect(t.head).toEqual(['', 'October 2026', 'November 2026 so far']);
    expect(t.rows.map(r => r[0])).toEqual(['Weighted mean', 'Low – high', '10th · 50th · 90th percentile', 'Time below zero', 'Complete days']);
    expect(t.note).toMatch(/November 2026 counts completed days only \(8 of 8\); it is not a full month/);
    expect(JSON.stringify(t)).not.toMatch(/saving|%.*change/i);
  });
  it('refuses when a month has too few days, another currency or another basis, or could not be read', () => {
    expect(compareMonths(entry('2026-10'), entry('2026-09')).text).toMatch(/September 2026 has no statistics \(fewer than 7 complete days/);
    const sek = { status: 'ready', parsed: { ...entry('2026-10').parsed, currency: 'SEK' } };
    expect(compareMonths(entry('2026-10'), sek).eligible).toBe(false);
    const other = { status: 'ready', parsed: { ...entry('2026-10').parsed, basis: 'x' } };
    expect(compareMonths(entry('2026-10'), other).text).toMatch(/different area, currency or price basis/);
    expect(compareMonths(entry('2026-10'), { status: 'ready', parsed: null }).eligible).toBe(false);
    expect(compareMonths(null, entry('2026-10'))).toBeNull();
  });
});

describe('month picker bound', () => {
  it('lists the current month back to the 400-day first-day bound, at most 14', () => {
    const o = monthOptions('2026-11-09');
    expect(o[0]).toEqual({ value: '2026-11', label: 'November 2026 (so far)' }); expect(o.at(-1).value).toBe('2025-11'); expect(o).toHaveLength(13);
    expect(monthOptions('2026-11-09').some(x => x.value === '2025-10')).toBe(false);
    expect(monthOptions('2026-11-09').length).toBeLessThanOrEqual(14); expect(monthOptions('nonsense')).toEqual([]);
  });
});

describe('request state machine', () => {
  it('opens with one live read and one read of the current month, then nothing on repeated paints', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    expect(h.calls).toEqual([{ mode: 'live', duration_minutes: 60 }, { mode: 'monthly', month: '2026-11' }]);
    for (let i = 0; i < 5; i++) h.insights.sync(sync);
    await tick(); expect(h.calls).toHaveLength(2);
  });

  it('a duration is bounded 15..720 in steps of 15 and is one explicit read; invalid values read nothing', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    for (const bad of [0, 14, 20, 735, 725, 60, '90', NaN, null]) h.insights.setDuration(bad);
    await tick(); expect(h.calls).toHaveLength(2);
    h.insights.setDuration(90); await tick();
    expect(h.calls.at(-1)).toEqual({ mode: 'live', duration_minutes: 90 });
    const w = block(h.insights.view(), 'window'); expect(w.title).toBe('Best published 1 h 30 min window'); expect(w.status).toMatch(/1 h 30 min$/);
    expect(DURATIONS[0]).toBe(15); expect(DURATIONS.at(-1)).toBe(720); expect(DURATIONS).toHaveLength(48);
  });

  it('a month is read once on choice and kept in memory; the cache holds at most the selected, compared and current months', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.insights.selectMonth('2026-10'); await tick(); expect(h.calls.at(-1)).toEqual({ mode: 'monthly', month: '2026-10' });
    h.insights.selectMonth('2026-11'); h.insights.selectMonth('2026-10'); await tick();
    expect(h.calls.filter(c => c.mode === 'monthly')).toHaveLength(2);
    for (const m of ['2026-08', '2026-07', '2026-06', '2026-05']) { h.insights.selectMonth(m); await tick(); }
    h.insights.selectCompare('2026-04'); await tick();
    expect(h.calls.filter(c => c.mode === 'monthly').length).toBeLessThanOrEqual(8);
    // a month outside the bounded picker is ignored
    const n = h.calls.length; h.insights.selectMonth('2024-01'); h.insights.selectMonth('2026-12'); h.insights.selectMonth('x'); await tick(); expect(h.calls).toHaveLength(n);
  });

  it('comparison is an explicit action and one more read; "previous" picks the month before the shown one', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    expect(block(h.insights.view(), 'month').table).toBeNull();
    h.insights.selectCompare('previous'); await tick();
    expect(h.calls.at(-1)).toEqual({ mode: 'monthly', month: '2026-10' });
    const t = block(h.insights.view(), 'month').table; expect(t.eligible).toBe(true);
    h.insights.selectCompare(''); expect(block(h.insights.view(), 'month').table).toBeNull();
    h.insights.selectCompare('2026-11'); // the shown month cannot be compared with itself
    expect(block(h.insights.view(), 'month').table).toBeNull();
  });

  it('a live read repeats at most every 5 minutes, and once the read interval ended only after a minute', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.clock.t += 4 * 60000; h.insights.sync(sync); await tick(); expect(h.calls.filter(c => c.mode === 'live')).toHaveLength(1);
    h.clock.t = INSIGHT_NOW + LIVE_REFRESH_MS + 1000; h.insights.sync(sync); await tick();
    expect(h.calls.filter(c => c.mode === 'live')).toHaveLength(2);
    h.insights.sync(sync); h.insights.sync(sync); await tick(); expect(h.calls.filter(c => c.mode === 'live')).toHaveLength(2);
    // the month answer is not refreshed with it
    expect(h.calls.filter(c => c.mode === 'monthly')).toHaveLength(1);
  });

  it('a failure stops everything until an explicit Retry (no storm); Retry reads the failed parts once', async () => {
    let failing = true;
    const h = harness(p => failing ? Object.assign(new Error('x'), { code: 'timeout' }) : answerFor(p));
    h.insights.sync(sync); await tick();
    let v = h.insights.view(); expect(v.state).toBe('error'); expect(v.controls.canRetry).toBe(true);
    expect(v.banners[0].text).toBe('Price insights could not be read.');
    for (let i = 0; i < 6; i++) { h.clock.t += 600000; h.insights.sync(sync); } await tick();
    expect(h.calls).toHaveLength(2);
    failing = false; h.insights.retry(); await tick();
    expect(h.calls).toHaveLength(4); expect(h.insights.view().state).toBe('ready'); expect(h.insights.view().controls.canRetry).toBe(false);
    h.insights.retry(); await tick(); expect(h.calls).toHaveLength(4);
  });

  it('a failed refresh keeps the earlier read, clearly labelled, with Retry and no timed retry', async () => {
    let fail = false;
    const h = harness(p => fail && p.mode === 'live' ? Object.assign(new Error('x'), { code: 'timeout' }) : answerFor(p));
    h.insights.sync(sync); await tick();
    fail = true; h.clock.t = INSIGHT_NOW + LIVE_REFRESH_MS + 1000; h.insights.sync(sync); await tick();
    const v = h.insights.view();
    expect(v.state).toBe('ready'); expect(v.banners[0]).toEqual({ kind: 'refresh-failed', text: expect.stringMatching(/latest refresh failed.*earlier read from 14:30/) });
    expect(block(v, 'current').title).toBe('Price at last read'); expect(v.controls.canRetry).toBe(true);
    const n = h.calls.length; h.clock.t += 3600000; h.insights.sync(sync); await tick(); expect(h.calls).toHaveLength(n);
  });

  it('error codes: an old backend, a missing area, a permission refusal and an unreadable answer each say so', async () => {
    const cases = [[Object.assign(new Error('x'), { code: 'unknown_command' }), 'unavailable', /does not provide price insights/], [Object.assign(new Error('x'), { code: 'spotnav_no_price_area' }), 'unavailable', /No price area/],
      [Object.assign(new Error('x'), { code: 'unauthorized' }), 'permission', /permission/], [{ api_version: 1, junk: true }, 'invalid', /could not be understood/]];
    for (const [response, state, text] of cases) {
      const h = harness(() => response); h.insights.sync(sync); await tick();
      const v = h.insights.view(); expect(v.state).toBe(state); expect(v.banners[0].text).toMatch(text);
      expect(block(v, 'current').value).toBe('Unavailable');
    }
  });

  it('drops answers that arrive after the charger, area, currency or permission epoch changed', async () => {
    const gate = deferred(), h = harness((p, n) => p.mode === 'live' ? (n === 1 ? gate.promise : new Promise(() => {})) : answerFor(p));
    h.insights.sync(sync); await tick();
    h.insights.sync({ ...sync, charger: 'c2' }); gate.resolve(liveAnswer(ctx, 60)); await tick();
    expect(block(h.insights.view(), 'current').value).toBe('Unavailable'); expect(h.insights.view().state).toBe('loading');
    for (const change of [{ epoch: '1:1' }, { area: 'SE3' }, { currency: 'SEK' }]) {
      const g = deferred(), k = harness((p, n) => p.mode === 'live' ? (n === 1 ? g.promise : new Promise(() => {})) : answerFor(p)); k.insights.sync(sync); await tick();
      k.insights.sync({ ...sync, ...change }); g.resolve(liveAnswer(ctx, 60)); await tick();
      expect(k.insights.view().blocks.find(b => b.id === 'current').value).toBe('Unavailable');
    }
  });

  it('an answer for a charger that is not the asked one is invalid, whatever its content', async () => {
    const h = harness(p => p.mode === 'live' ? liveAnswer({ ...ctx, charger: 'other' }, 60) : answerFor(p));
    h.insights.sync(sync); await tick();
    expect(h.insights.view().state).toBe('invalid');
  });

  it('a late answer for a replaced duration or a month no longer chosen is ignored, and the month can be chosen again', async () => {
    const gates = {}, h = harness(p => { if (p.mode === 'live' && p.duration_minutes === 90) return (gates.d = deferred()).promise; if (p.mode === 'monthly' && p.month === '2026-10') return (gates.m ||= deferred()).promise; return answerFor(p); });
    h.insights.sync(sync); await tick();
    h.insights.setDuration(90); h.insights.setDuration(120); await tick();
    gates.d.resolve(liveAnswer(ctx, 90)); await tick();
    const w = block(h.insights.view(), 'window'); expect(w.title).toBe('Best published 2 h window'); expect(w.status).not.toMatch(/1 h 30/);
    h.insights.selectMonth('2026-10'); h.insights.selectMonth('2026-11'); gates.m.resolve(monthlyAnswer(ctx, '2026-10')); await tick();
    expect(block(h.insights.view(), 'month').title).toBe('November 2026 so far');
    gates.m = null; const n = h.calls.length; h.insights.selectMonth('2026-10'); await tick();
    expect(h.calls).toHaveLength(n + 1); // not stuck "loading": it is read again
  });

  it('routine refreshes keep the chosen duration, month and comparison; a context change resets them', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.insights.setDuration(120); h.insights.selectMonth('2026-10'); h.insights.selectCompare('previous'); await tick();
    h.insights.sync(sync); h.insights.sync({ ...sync, today: INSIGHT_TODAY }); await tick();
    let v = h.insights.view(); expect(v.controls.duration.value).toBe(120); expect(v.controls.month.value).toBe('2026-10'); expect(v.controls.compare.value).toBe('2026-09');
    h.insights.sync({ ...sync, epoch: '2:0' }); await tick();
    v = h.insights.view(); expect(v.controls.duration.value).toBe(60); expect(v.controls.month.value).toBe('2026-11'); expect(v.controls.compare.value).toBe('');
  });

  it('a new day clears the month memory and reads the new current month once', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    h.insights.sync({ ...sync, today: '2026-11-10' }); await tick();
    expect(h.calls.filter(c => c.mode === 'monthly')).toHaveLength(2);
    expect(h.calls.filter(c => c.mode === 'live').length).toBeLessThanOrEqual(2);
  });

  it('an invalid context asks nothing and shows nothing; dispose drops pending answers', async () => {
    const h = harness();
    expect(h.insights.sync({ ...ctx, today: 'x' }).view()).toBeNull(); expect(h.insights.sync({ ...ctx, area: '', today: INSIGHT_TODAY }).view()).toBeNull(); await tick(); expect(h.calls).toHaveLength(0);
    h.insights.sync(sync); h.insights.dispose(); await tick(); expect(h.insights.view()).toBeNull();
  });

  it('renders the controls and a read-only caution; the whole view is plain data', async () => {
    const h = harness(); h.insights.sync(sync); await tick();
    const html = renderInsights(h.insights.view());
    for (const marker of ['data-insight-duration', 'data-insight-month', 'data-insight-compare', 'data-insight-compare-previous', 'data-insight-block="current"', 'data-insight-block="window"', 'data-insight-block="month"']) expect(html).toContain(marker);
    expect(html).toMatch(/never sends a plan, replans, wakes the car or changes a setting/); expect(html).toMatch(/How these insights work/);
    expect(html).not.toContain('data-insight-retry');
    expect(renderInsights(null)).toBe('<p>Price insights unavailable.</p>');
  });
});
