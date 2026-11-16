import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPriceInsights, parseLive, parseMonthly } from '../shared-dashboard/price-insights.js';
import { renderInsights } from '../shared-dashboard/insight-view.js';
import { liveAnswer, monthlyAnswer, fixtureInsightsRequest, INSIGHT_TODAY, INSIGHT_NOW } from './insight-fixture.js';

const context = { charger: 'sample-charger', area: 'SAMPLE-1', currency: 'EUR', epoch: 'sample' };
const asked = { charger: context.charger, area: context.area, currency: 'EUR' };
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

test('preview fixtures have the backend shape and pass the live validators', () => {
  const live = parseLive(liveAnswer(context, 60), { ...asked, duration: 60 });
  assert.ok(live && live.current.known && live.window.known && live.baseline.known);
  assert.equal(live.window.end - live.window.start, 3600000);
  assert.ok(live.window.start >= INSIGHT_NOW);
  for (const month of ['2026-11', '2026-10']) assert.equal(parseMonthly(monthlyAnswer(context, month), { ...asked, month }).known, true);
  const young = parseMonthly(monthlyAnswer(context, '2026-09'), { ...asked, month: '2026-09' });
  assert.equal(young.known, false); assert.equal(young.reason, 'too_few_complete_days');
});

test('the shared state machine renders the preview card: bands and percentile apart, no fake zero, read only', async () => {
  const calls = [];
  const request = fixtureInsightsRequest(context); const insights = createPriceInsights({ request: async p => { calls.push(p); return request(p); }, now: () => INSIGHT_NOW });
  insights.sync({ ...context, today: INSIGHT_TODAY }); await settle();
  assert.deepEqual(calls.map(c => c.mode), ['live', 'monthly']);
  const html = renderInsights(insights.sync({ ...context, today: INSIGHT_TODAY }).view());
  assert.match(html, /c\/kWh/); assert.match(html, /not the charging plan/i); assert.match(html, /fixed\)/); assert.match(html, /higher than about 63% of that time/);
  assert.match(html, /8 of 8 completed days/); assert.doesNotMatch(html, /NaN|Infinity|undefined/);
  assert.equal(calls.length, 2);
  const young = createPriceInsights({ request: fixtureInsightsRequest(context, { missing: true }), now: () => INSIGHT_NOW });
  young.sync({ ...context, today: INSIGHT_TODAY }); await settle();
  const text = renderInsights(young.sync({ ...context, today: INSIGHT_TODAY }).view());
  assert.match(text, /Unknown/); assert.match(text, /Unavailable/); assert.doesNotMatch(text, /0\.00 c\/kWh|NaN/);
});
