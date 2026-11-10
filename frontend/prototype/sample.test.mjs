import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prices, windows, total, money, time, priceAt, stepSegments, horizon } from './sample.js';

test('sample plan agrees with interval prices, cap and totals', () => {
  for (const w of windows) {
    const p = priceAt(w.start);
    assert.ok(p && p.end >= w.end && p.cents <= 10);
    assert.equal(w.energy, (w.end - w.start) * 6);
    assert.ok(Math.abs(w.cost - w.energy * p.cents / 100) < 1e-10);
  }
  const result = total(windows);
  assert.equal(result.energy, 15);
  assert.ok(Math.abs(result.cost - 0.51) < 1e-10);
  assert.equal(result.centsPerKwh.toFixed(2), '3.40');
  assert.equal(money(windows[0].cost), '−€0.12');
  assert.equal(time(-1), '23:00');
});
test('variable-duration intervals, negative values, gap and final endpoint remain distinct', () => {
  assert.ok(prices.some(p => p.end - p.start === 0.5));
  assert.ok(prices.some(p => p.end - p.start === 1));
  assert.ok(prices.some(p => p.cents < 0));
  assert.equal(priceAt(14), undefined);
  assert.equal(priceAt(36), undefined);
  assert.equal(priceAt(47), undefined);
  assert.deepEqual(horizon, [-24, 48]);
  const segments = stepSegments(prices);
  assert.equal(segments.length, prices.length);
  assert.deepEqual(segments.at(-1), [[35, prices.at(-1).cents], [36, prices.at(-1).cents]]);
  assert.ok(segments.some((segment, i) => i > 0 && segments[i - 1][1][0] < segment[0][0]));
});
test('unknown energy or cost is never reported as zero', () => {
  assert.equal(total([{ energy: null, cost: 0 }]), null);
  assert.equal(total([{ energy: 1, cost: null }]), null);
  assert.equal(total([]), null);
  assert.equal(money(null), 'Unknown');
  assert.equal(total([{ energy: 0, cost: 0 }]).centsPerKwh, null);
});
