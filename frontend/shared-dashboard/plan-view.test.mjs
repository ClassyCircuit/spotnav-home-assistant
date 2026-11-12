import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPlan } from './plan-view.js';
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
