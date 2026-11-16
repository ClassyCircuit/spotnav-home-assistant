// @ts-nocheck
// Stage 8.2b: the shared spot-only cost formatter, the day/session/month display and the month request machine, against
// backend-shaped blocks (the preview fixtures, whose keys are pinned to the real backend by tests/fixtures/sessions/*.json).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { describeSpotCost, parseSpotCost, formatMoney, parseDeliveryMonth, monthCostModel } from '../shared-dashboard/spot-cost.js';
import { createHistoryDay, buildHistoryModel } from '../shared-dashboard/history-day.js';
import { renderHistoryDay } from '../shared-dashboard/history-view.js';
import { HISTORY_TODAY, HISTORY_ZONE, historyAnswer, fixtureHistoryRequest, fixtureSessionsRequest } from '../prototype/history-day-fixture.js';
import { decodeSessions } from '../src/history';

const tick = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const ctx = (over = {}) => ({ charger: 'a', epoch: '1:0', zone: HISTORY_ZONE, marketZone: HISTORY_ZONE, today: HISTORY_TODAY, ...over });
const fixtureBlock = day => structuredClone(historyAnswer('a', day).window_spot_cost);
const fmt = { stamp: iso => iso.slice(11, 16) };
const monthAnswer = params => fixtureSessionsRequest({ charger: 'a' })(params);
const modelOf = (day, change = () => {}) => { const a = structuredClone(historyAnswer('a', day)); change(a); return buildHistoryModel(a, day, fmt); };
const make = requestSessions => createHistoryDay({ request: fixtureHistoryRequest({ charger: 'a' }), requestSessions, onChange: () => {} });

describe('spot-only cost formatter (one path for session, day and month)', () => {
  it('shows the backend amount in the major currency unit, never cents, and labels it a spot-only estimate', () => {
    const d = describeSpotCost(fixtureBlock('2026-11-09'));
    expect(d.headline).toBe('Spot cost €1.23 (estimate) for 8.20 kWh priced.');
    expect(d.state).toBe('complete');
    const text = d.lines.join(' ');
    expect(text).toContain('no fees, taxes or margin');
    expect(text).toContain('Spot price source not recorded');
    expect(text).not.toMatch(/nord ?pool/i);
    expect(text).toContain('estimate: each price interval');
    expect(formatMoney(1.5, 'EUR')).toBe('€1.50');
    expect(formatMoney(1.5, 'SEK', 'kr')).toMatch(/1\.50/);
  });

  it('negative is a valid net credit, zero is a priced zero, null is unknown and never zero', () => {
    expect(describeSpotCost(fixtureBlock('2026-11-07')).headline).toContain('-€0.10');
    expect(describeSpotCost(fixtureBlock('2026-11-07')).lines.join(' ')).toContain('net credit');
    expect(describeSpotCost({ ...fixtureBlock('2026-11-09'), amount: 0 }).headline).toContain('€0.00');
    const unknown = describeSpotCost(historyAnswer('a', '2026-11-06').sessions[0].spot_cost);
    expect(unknown.state).toBe('none');
    expect(unknown.headline).toContain('unknown');
    expect(unknown.headline).not.toContain('0.00');
    expect(formatMoney(null, 'EUR')).toBe('unknown');
    expect(formatMoney(0.001, 'EUR')).toBe('€0.0010');
  });

  it('partial says priced and missing kWh and is never a total; no sessions is not zero or "did not charge"', () => {
    const p = describeSpotCost(fixtureBlock('2026-11-08'));
    expect(p.state).toBe('partial');
    expect(p.headline).toBe('Partial spot cost €0.84 for 5.00 kWh priced; 3.20 kWh unpriced. This is not a complete total.');
    expect(p.lines.join(' ')).toContain('Unpriced because: no price slice stored 3.20 kWh');
    expect(p.lines.join(' ')).toContain('Late energy with no known time 1.40 kWh: not priced');
    const none = describeSpotCost(fixtureBlock('2026-11-04'));
    expect(none.state).toBe('no_sessions_recorded');
    expect(none.headline).toContain('not zero cost and not proof that nothing was charged');
    expect(none.amount).toBeNull();
  });

  it('reports currency exclusions and unallocated energy separately, without adding them', () => {
    const b = { ...fixtureBlock('2026-11-09'), unallocated_kwh: 2.5, currency_exclusions: { kwh: 6, sessions: 1, currencies: { SEK: 6 }, missing_currency_kwh: 1 } };
    const lines = describeSpotCost(b).lines.join(' ');
    expect(lines).toContain('Left out: 6.00 kWh in SEK (1.00 kWh with no currency)');
    expect(lines).toContain('never added or converted');
    expect(lines).toContain('2.50 kWh of a session that crosses the edge has no price interval');
  });

  it('a malformed or fiscal-labelled block is not understood, never a number', () => {
    const ok = fixtureBlock('2026-11-09');
    for (const bad of [null, {}, { ...ok, price_basis: 'fiscal' }, { ...ok, unit: 'cent' }, { ...ok, amount: 'x' }, { ...ok, currency: null }, { ...ok, priced_kwh: 0 }, { ...ok, coverage: { state: 'odd', reasons: [] } }]) {
      expect(parseSpotCost(bad)).toBeNull();
      expect(describeSpotCost(bad).state).toBe('invalid');
      expect(describeSpotCost(bad).headline).toContain('could not be understood');
    }
  });
});

describe('day review: the selected day within the window versus the whole midnight session', () => {
  it('shows the day cost from window_spot_cost and both numbers for a midnight session', () => {
    const m = modelOf('2026-11-07');
    expect(m.cost.headline).toContain('-€0.10');
    expect(m.sessions[0].costLines).toEqual(['Spot cost in this day: -€0.10 (estimate)', 'Whole session (crosses midnight; not this day’s cost): -€0.20',
      'Estimated savings in this day: -€0.10 (costs more than reference)', 'Whole session estimated savings (not this day’s): -€0.15 (costs more than reference)']);
    const html = renderHistoryDay({ ...m, nav: null, monthCost: null });
    expect(html).toContain('data-history-section="cost"');
    expect(html).toContain('Spot cost in this day: -€0.10');
  });

  it('a session inside one day shows only its own figure; an older backend shows no cost, never the fiscal one', () => {
    expect(modelOf('2026-11-09').sessions[0].costLines).toEqual(['Spot cost in this day: €1.23 (estimate)', 'Estimated savings in this day: €0.27 (18% of the reference)']);
    const old = modelOf('2026-11-09', a => { delete a.window_spot_cost; for (const s of a.sessions) { delete s.spot_cost; delete s.spot_cost_in_window; s.cost = 9.99; } });
    expect(old.cost.state).toBe('legacy');
    expect(old.cost.headline).toContain('does not report spot-only cost');
    expect(JSON.stringify(old.cost)).not.toContain('9.99');
    expect(old.sessions[0].costLines).toEqual(['Spot cost not reported by this integration (not zero).']);
  });

  it('a window block for another day is not shown', () => {
    expect(modelOf('2026-11-09', a => { a.window_spot_cost.local_day = '2026-11-08'; }).cost.state).toBe('invalid');
  });

  it('identical backend blocks give identical text in the day card and the month row (one formatter)', async () => {
    const day = describeSpotCost(fixtureBlock('2026-11-09'));
    const row = monthCostModel(parseDeliveryMonth(await monthAnswer({}), 'a'), { isCurrent: true }).days.find(d => d.day === '2026-11-09');
    expect(row.text).toBe(`09: ${day.brief}`);
  });
});

describe('month cost: one existing get_sessions read, bounded month reads, backend sums only', () => {
  it('uses the opening sessions read for the current month and shows the backend total, days and the unplaced explanation', async () => {
    const reads = [];
    const view = make(async p => { reads.push(p); return monthAnswer(p); });
    view.sync(ctx()); await tick();
    expect(reads).toEqual([{}]);
    const m = view.view().monthCost;
    expect(m.state).toBe('ready'); expect(m.isCurrent).toBe(true);
    expect(m.total.headline).toBe('Partial spot cost €1.97 for 16.2 kWh priced; 4.60 kWh unpriced. This is not a complete total.');
    expect(m.days.map(d => d.text)).toEqual(['07: -€0.10 (estimate)', '08: €0.84 partial (5.00 kWh priced)', '09: €1.23 (estimate)']);
    expect(m.emptyDays).toBe(27);
    expect(m.total.lines.join(' ')).toContain('need not add up to the month’s unpriced energy');
    const html = renderHistoryDay(view.view());
    expect(html).toContain('data-history-section="month-cost"'); expect(html).toContain('data-history-month');
    expect(html).toContain('27 day(s) with no recorded session');
  });

  it('another month is one read on choice, cached, the current month needs no read, and a selection is bound to the context', async () => {
    const reads = [];
    const view = make(async p => { reads.push(p); return monthAnswer(p); });
    view.sync(ctx()); await tick();
    expect(view.selectMonth('2025-01')).toBe(false);
    expect(view.selectMonth('2026-10')).toBe(true); await tick();
    expect(reads).toEqual([{}, { month: '2026-10' }]);
    const oct = view.view().monthCost;
    expect(oct.total.headline).toContain('-€0.35'); expect(oct.total.lines.join(' ')).toContain('Left out: 6.00 kWh in SEK');
    expect(oct.isCurrent).toBe(false);
    expect(view.selectMonth('2026-11')).toBe(true); await tick();
    expect(view.view().monthCost.total.headline).toContain('€1.97');
    expect(view.selectMonth('2026-10')).toBe(true); await tick();
    expect(reads).toHaveLength(2);
    view.sync(ctx()); view.sync(ctx()); await tick();
    expect(reads).toHaveLength(2);
    view.sync(ctx({ charger: 'b' })); await tick();
    expect(view.view().monthCost.isCurrent).toBe(true);
  });

  it('an older backend month shows a plain "not reported" note, never fiscal fields; a foreign or malformed month is not shown', async () => {
    const view = make(async p => monthAnswer(p));
    view.sync(ctx()); await tick(); view.selectMonth('2026-09'); await tick();
    const m = view.view().monthCost;
    expect(m.state).toBe('legacy'); expect(m.message).toContain('does not report spot-only cost by month');
    const bad = make(async p => p.month ? { ...(await monthAnswer(p)), month: '2026-08' } : monthAnswer(p));
    bad.sync(ctx()); await tick(); bad.selectMonth('2026-10'); await tick();
    expect(bad.view().monthCost.state).toBe('error');
    expect(parseDeliveryMonth({ ...(await monthAnswer({})), delivery_month_days: 'x' }, 'a')).toBeNull();
    expect(monthCostModel(null, { isCurrent: true }).state).toBe('invalid');
  });

  it('drops a late month answer after the selection or charger changed; a failure waits for Retry (no hidden retry)', async () => {
    const waiting = []; let who = 'a';
    const view = make(p => p.month ? new Promise((resolve, reject) => waiting.push({ p, resolve, reject })) : fixtureSessionsRequest({ charger: who })(p));
    view.sync(ctx()); await tick();
    view.selectMonth('2026-10'); view.selectMonth('2026-11'); await tick();
    waiting[0].resolve(await monthAnswer({ month: '2026-10' })); await tick();
    expect(view.view().monthCost.isCurrent).toBe(true);
    expect(view.view().monthCost.total.headline).toContain('€1.97');
    view.selectMonth('2026-10'); await tick();
    expect(waiting).toHaveLength(2);
    waiting[1].reject(new Error('timeout')); await tick();
    expect(view.view().monthCost.state).toBe('error');
    view.sync(ctx()); await tick();
    expect(waiting).toHaveLength(2);
    view.retry(); await tick();
    expect(waiting).toHaveLength(3);
    who = 'b'; view.sync(ctx({ charger: 'b' })); await tick(); waiting[2].resolve(await monthAnswer({ month: '2026-10' })); await tick();
    expect(view.view().monthCost.isCurrent).toBe(true);
    expect(view.view().monthCost.state).not.toBe('error');
  });

  it('a new local month rereads the current month once', async () => {
    const reads = [];
    const view = make(async p => { reads.push(p); return monthAnswer(p); });
    view.sync(ctx()); await tick();
    view.sync(ctx({ today: '2026-12-01' })); await tick(); view.sync(ctx({ today: '2026-12-01' })); await tick();
    expect(reads).toEqual([{}, {}]);
  });
});

describe('legacy strict decoders accept the additive 8.2a keys', () => {
  it('decodeSessions reads the committed fixtures that carry delivery and spot_cost keys', () => {
    for (const name of ['get_sessions', 'get_sessions_month']) {
      const raw = JSON.parse(readFileSync(`../tests/fixtures/sessions/${name}.json`, 'utf8'));
      expect('delivery_month_summary' in raw || 'delivery_days' in raw).toBe(true);
      expect(decodeSessions(raw).ok).toBe(true);
    }
  });
});
