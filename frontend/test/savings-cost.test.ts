// @ts-nocheck
// Stage 8.3b: the historical day-average savings display (backend `spot_cost.savings`), the day/month summary cards and the bounded
// read-time/refresh policy of the current month, against backend-shaped fixtures (the same ones the local preview uses).
import { describe, it, expect } from 'vitest';
import { describeSavings, describeSpotCost, parseDeliveryMonth, monthCostModel } from '../shared-dashboard/spot-cost.js';
import { createHistoryDay, buildHistoryModel } from '../shared-dashboard/history-day.js';
import { renderHistoryDay } from '../shared-dashboard/history-view.js';
import { HISTORY_TODAY, HISTORY_ZONE, historyAnswer, fixtureHistoryRequest, fixtureSessionsRequest } from '../prototype/history-day-fixture.js';

const tick = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const ctx = (over = {}) => ({ charger: 'a', epoch: '1:0', zone: HISTORY_ZONE, marketZone: HISTORY_ZONE, today: HISTORY_TODAY, ...over });
const blockOf = day => structuredClone(historyAnswer('a', day).window_spot_cost);
const monthAnswer = params => fixtureSessionsRequest({ charger: 'a' })(params);
const monthBlocks = async (month = {}) => { const p = parseDeliveryMonth(await monthAnswer(month), 'a'); return { total: p.month_block, days: Object.fromEntries(p.days.map(d => [d.period, d.block])) }; };
const text = d => [d.headline, ...d.lines].join(' ');

describe('savings formatter: amounts are the backend’s, labelled as a historical estimate', () => {
  it('positive savings show amount, the backend percentage, baseline, compared energy, reference and actual cost', () => {
    const d = describeSavings(blockOf('2026-11-09'));
    expect(d.state).toBe('complete');
    expect(d.headline).toBe('Estimated savings €0.27 (18% of the reference) for 8.20 kWh compared.');
    const t = text(d);
    expect(t).toContain('not a supplier-bill saving and not the plan’s forecast');
    expect(t).toContain('full-day average spot price');
    expect(t).toContain('no fees, taxes or margin');
    expect(t).toContain('reference cost €1.50; actual spot cost of that same energy €1.23');
    expect(t).toContain('Reference price source: Fixture provider');
    expect(t).not.toMatch(/nord ?pool/i);
    expect(t).not.toContain('never subtract'); // same energy as the spot cost: no subset warning
  });

  it('negative savings are shown as negative and described as costing more than the reference; a negative reference has no percentage (not 0%)', () => {
    const d = describeSavings(blockOf('2026-11-07'));
    expect(d.amount).toBe(-0.1);
    expect(d.headline).toContain('-€0.10');
    expect(d.headline).toContain('costs more than the reference');
    expect(text(d)).toContain('Negative savings are valid');
    expect(text(d)).toContain('Percentage not meaningful: the reference cost is negative');
    expect(d.headline).not.toMatch(/%/);
    expect(text(d)).toContain('this is not 0%');
  });

  it('a zero reference keeps the amount and says the percentage is not meaningful; zero savings is a real zero', async () => {
    const oct = await monthBlocks({ month: '2026-10' });
    const d = describeSavings(oct.total, 'month');
    expect(d.headline).toContain('€0.30');
    expect(d.headline).not.toMatch(/%/);
    expect(text(d)).toContain('the reference cost is zero');
    const zero = blockOf('2026-11-09'); zero.savings = { ...zero.savings, amount: 0, percentage: 0 };
    expect(describeSavings(zero).headline).toContain('€0.00');
    expect(describeSavings(zero).headline).toContain('the same as the reference');
  });

  it('compared energy smaller than the priced energy is labelled, and the two costs are never subtracted', async () => {
    const nov = await monthBlocks();
    const spot = describeSpotCost(nov.total, 'month'), sav = describeSavings(nov.total, 'month');
    expect(spot.headline).toContain('€1.97'); // the whole priced total, unchanged
    expect(sav.state).toBe('partial');
    expect(sav.headline).toBe('Partial estimated savings €0.17 (13.1% of the reference) for 11.2 kWh compared. This is not a complete comparison.');
    const t = text(sav);
    expect(t).toContain('covers 16.2 kWh priced; savings compare only 11.2 kWh');
    expect(t).toContain('never subtract one from the other');
    expect(t).toContain('actual spot cost of that same energy €1.13'); // the subset's own actual cost, not €1.97
    expect(t).not.toContain('€1.97');
    expect(t).toContain('Left out of the comparison: 5.00 kWh priced energy with no full-day reference (full-day prices incomplete 5.00 kWh); days: 2026-11-08');
    expect(t).toContain('4.60 kWh unpriced energy is not compared');
  });

  it('a missing full-day reference is unknown, never zero, and a session-less day is not zero savings', () => {
    const none = describeSavings(blockOf('2026-11-08'));
    expect(none.state).toBe('none');
    expect(none.amount).toBeNull();
    expect(none.headline).toBe('Estimated savings unknown: no priced energy had a full-day reference price (3.20 kWh unpriced).');
    expect(text(none)).toContain('Left out of the comparison: 5.00 kWh');
    expect(none.headline).not.toContain('0.00');
    const empty = describeSavings(blockOf('2026-11-04'));
    expect(empty.state).toBe('no_sessions_recorded');
    expect(empty.headline).toContain('that is not zero savings');
  });

  it('an older backend (no savings key) and malformed blocks never show zero or reassurance', () => {
    const old = blockOf('2026-11-09'); delete old.savings;
    expect(describeSavings(old).state).toBe('legacy');
    expect(describeSavings(old).headline).toContain('not reported by this integration (not zero)');
    const ok = blockOf('2026-11-09').savings;
    const bad = patch => { const b = blockOf('2026-11-09'); b.savings = { ...ok, ...patch }; return describeSavings(b); };
    for (const patch of [{ basis: 'other' }, { estimate: false }, { amount: 'x' }, { currency: 'SEK' }, { comparable_kwh: 99 }, { state: 'none' }, { actual_cost: null }, { comparable_kwh: -1 }, { excluded_days: 'x' }, { reference_sources: 'broken' }, { reference_sources: [null] }]) {
      expect(bad(patch).state).toBe('invalid');
      expect(bad(patch).headline).toContain('could not be understood');
    }
    expect(describeSavings(null).state).toBe('invalid');
    expect(describeSavings({ ...blockOf('2026-11-09'), price_basis: 'fiscal' }).state).toBe('invalid');
  });

  it('currency exclusions of the comparison are listed, not added or converted', async () => {
    const oct = await monthBlocks({ month: '2026-10' });
    oct.total.savings.currency_exclusions = { kwh: 6, sessions: 1, currencies: { SEK: 6 }, missing_currency_kwh: 0 };
    expect(text(describeSavings(oct.total, 'month'))).toContain('Left out: 6.00 kWh in SEK');
  });
});

describe('summary cards: totals identical to the 8.2b cost, forecast stays separate, preview renders through the same code', () => {
  it('the day card and month card keep the exact spot-cost text and add the savings card beside it', async () => {
    const m = buildHistoryModel(structuredClone(historyAnswer('a', '2026-11-09')), '2026-11-09', { stamp: iso => iso.slice(11, 16) });
    expect(m.cost.headline).toBe(describeSpotCost(blockOf('2026-11-09'), 'day').headline);
    expect(m.savings.headline).toContain('€0.27');
    const nov = await monthBlocks();
    const model = monthCostModel(parseDeliveryMonth(await monthAnswer({}), 'a'), { isCurrent: true });
    expect(model.total.headline).toBe(describeSpotCost(nov.total, 'month').headline);
    expect(model.days.map(d => `${d.text} | ${d.detail}`)).toEqual([
      '07: -€0.10 (estimate) | Estimated savings: -€0.10 (costs more than reference)',
      '08: €0.84 partial (5.00 kWh priced) | Estimated savings: unknown (no full-day reference)',
      '09: €1.23 (estimate) | Estimated savings: €0.27 (18% of the reference)']);
    const html = renderHistoryDay({ ...m, nav: null, monthCost: { ...model, options: [], readNote: 'Read at 12:00 (Home Assistant time).' } });
    expect(html).toContain('data-spot-cost="complete"');
    expect(html).toContain('data-spot-savings="complete"');
    expect(html).toContain('data-spot-savings="partial"'); // the month card
    expect(html).toContain('Plan totals elsewhere are a forecast');
    expect(html).toContain('not a supplier-bill saving');
    expect(html).toContain('data-month-read');
    expect(html).toContain('Spot cost and estimated savings by month');
  });

  it('an old-backend day shows both cards as not reported, never zero', () => {
    const m = buildHistoryModel((() => { const a = structuredClone(historyAnswer('a', '2026-11-09')); delete a.window_spot_cost; return a; })(), '2026-11-09', { stamp: iso => iso });
    expect(m.cost.state).toBe('legacy'); expect(m.savings.state).toBe('legacy');
    expect(renderHistoryDay({ ...m, nav: null, monthCost: null })).toContain('Estimated savings are not reported by this integration (not zero)');
  });
});

describe('current-month read time and bounded refresh inside the existing state machine', () => {
  const setup = (answerFor = null) => {
    let t = 1_000_000, who = 'a'; const reads = [], waiting = [];
    const view = createHistoryDay({ request: fixtureHistoryRequest({ charger: 'a' }), onChange: () => {}, now: () => t,
      requestSessions: p => { reads.push(p); return answerFor ? answerFor(p, waiting, who) : fixtureSessionsRequest({ charger: who })(p); } });
    return { view, reads, waiting, advance: ms => { t += ms; }, as: c => { who = c; } };
  };
  const cur = view => view.view().monthCost;

  it('reads once on opening and shows when; ordinary repaints inside five minutes read nothing', async () => {
    const { view, reads, advance } = setup();
    view.sync(ctx()); await tick();
    expect(reads).toEqual([{}]);
    expect(cur(view).readNote).toContain('Read at ');
    expect(cur(view).readNote).toContain('Home Assistant time');
    advance(299_000); for (let i = 0; i < 4; i++) { view.sync(ctx()); await tick(); }
    expect(reads).toHaveLength(1);
  });

  it('one refresh after five minutes on a repaint (no duplicate while pending), the old figures stay shown meanwhile', async () => {
    let n = 0; const { view, reads, advance } = setup((p, w, who) => n++ === 0 ? fixtureSessionsRequest({ charger: who })(p) : new Promise(res => w.push(res)));
    view.sync(ctx()); await tick();
    advance(300_000); view.sync(ctx()); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(2);
    expect(cur(view).state).toBe('ready'); expect(cur(view).refreshing).toBe(true);
    expect(cur(view).total.headline).toContain('€1.97');
  });

  it('a successful refresh replaces the figures and the read time, then waits another five minutes', async () => {
    let n = 0;
    const { view, reads, advance } = setup(async (p, w, who) => { const a = await fixtureSessionsRequest({ charger: who })(p); if (n++ > 0) a.delivery_month_summary.spot_cost.amount = 2.5; return a; });
    view.sync(ctx()); await tick();
    advance(300_000); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(2);
    expect(cur(view).total.headline).toContain('€2.50');
    view.sync(ctx()); advance(60_000); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(2);
    advance(240_000); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(3);
  });

  it('a failed refresh keeps the old figures as the last read, never retries by itself, and Retry reads once', async () => {
    let n = 0;
    const { view, reads, advance } = setup(async (p, w, who) => { if (n++ === 1) throw new Error('timeout'); return fixtureSessionsRequest({ charger: who })(p); });
    view.sync(ctx()); await tick();
    advance(300_000); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(2);
    expect(cur(view).state).toBe('ready');
    expect(cur(view).total.headline).toContain('€1.97');
    expect(cur(view).readNote).toContain('The latest refresh failed: these are the figures of the last successful read');
    expect(view.view().nav.canRetry).toBe(true);
    for (let i = 0; i < 5; i++) { advance(600_000); view.sync(ctx()); await tick(); }
    expect(reads).toHaveLength(2);
    view.retry(); await tick();
    expect(reads).toHaveLength(3);
    expect(cur(view).readNote).not.toContain('refresh failed');
  });

  it('a refresh answer for another charger or month is a failed refresh, not a replacement', async () => {
    let n = 0;
    const { view, reads, advance } = setup(async (p, w, who) => { const a = await fixtureSessionsRequest({ charger: who })(p); if (n++ === 1) a.month = '2026-10'; return a; });
    view.sync(ctx()); await tick(); advance(300_000); view.sync(ctx()); await tick();
    expect(cur(view).total.headline).toContain('€1.97');
    expect(cur(view).readNote).toContain('refresh failed');
    expect(reads).toHaveLength(2);
  });

  it('an answer arriving after the charger changed is dropped; the new charger reads for itself', async () => {
    const pending = []; let n = 0;
    const { view, reads, advance, as } = setup((p, w, who) => n++ === 1 ? new Promise(resolve => pending.push({ resolve })) : fixtureSessionsRequest({ charger: who })(p));
    view.sync(ctx()); await tick();
    advance(300_000); view.sync(ctx()); await tick();
    expect(pending).toHaveLength(1);
    as('b'); view.sync(ctx({ charger: 'b' })); await tick();
    pending[0].resolve(await fixtureSessionsRequest({ charger: 'a' })({}));
    await tick();
    expect(cur(view).state).toBe('ready');
    expect(reads).toHaveLength(3);
    expect(cur(view).readNote).not.toContain('refresh failed');
  });

  it('a past month is read on selection only: never refreshed with time, and the current month refreshes once when shown again', async () => {
    const { view, reads, advance } = setup();
    view.sync(ctx()); await tick();
    view.selectMonth('2026-10'); await tick();
    expect(reads).toEqual([{}, { month: '2026-10' }]);
    expect(cur(view).readNote).toContain('a past month is not refreshed on its own');
    advance(3_600_000); for (let i = 0; i < 3; i++) { view.sync(ctx()); await tick(); }
    expect(reads).toHaveLength(2);
    view.selectMonth('2026-11'); view.sync(ctx()); view.sync(ctx()); await tick();
    expect(reads).toEqual([{}, { month: '2026-10' }, {}]);
  });

  it('never writes: only the two read callbacks are used and a legacy backend is not refreshed into a number', async () => {
    const { view, reads, advance } = setup(async p => ({ api_version: 1, charger_id: 'a', days: [], month: '2026-11', available_months: ['2026-11'] }));
    view.sync(ctx()); await tick(); advance(300_000); view.sync(ctx()); await tick();
    expect(cur(view).state).toBe('legacy');
    expect(reads.every(r => Object.keys(r).every(k => k === 'month'))).toBe(true);
  });
});
