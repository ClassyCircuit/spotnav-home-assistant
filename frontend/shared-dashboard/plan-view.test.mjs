import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPlan } from './plan-view.js';
import { money } from './plan-data.js';
import { total, projectSoc } from './plan-data.js';

test('shared plan requires host formatters and escapes their output', () => {
  const rows = [{ start: 1, end: 2, energy: 1, cost: 2 }];
  assert.throws(() => renderPlan(rows), /formatters/);
  const html = renderPlan(rows, {}, false, { time: () => '<img src=x>', day: () => 'A&B' });
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;img src=x&gt;/);
  assert.match(html, /A&amp;B/);
});

test('absent and invalid plan inputs remain unknown', () => {
  assert.deepEqual(total([]), { energy: null, cost: null, centsPerKwh: null });
  assert.equal(projectSoc([{ energy: 2 }])[0].projectedSoc, null);
  const html = renderPlan([{ start: 1, end: 2, energy: NaN, cost: Infinity }], {}, false, { time: String, day: String });
  assert.match(html, /Unknown/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('explicit backend totals and currencies do not invent window costs', () => {
  const rows = [{ start: 1, end: 2, energy: null, cost: null, centsPerKwh: null }];
  const format = { time: String, day: String, currency: 'SEK' };
  const html = renderPlan(rows, {}, false, format, { energy: 3, cost: 4 });
  assert.match(html, /4\.00 SEK/);
  assert.match(html, /3\.00 kWh/);
  assert.doesNotMatch(html, /€|c\/kWh/);
  assert.equal(money(4, null), 'Unknown');
  assert.equal(money(4, 'EUR'), '€4.00');
  assert.equal(money(4, '<x>'), 'Unknown');
  assert.match(renderPlan(rows, {}, false, {...format, currency:null}, {cost:4}), /currency unknown/);
});
