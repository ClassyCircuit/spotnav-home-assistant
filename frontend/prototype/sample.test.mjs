import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prices, windows, total, money, time, stepSegments, stepPoints, horizon, groupBlocks, priceWindow, snapRange, initialRange, timeTicks, sampleDate, sampleDays, priceGaps, projectSoc } from './sample.js';

test('reference-derived sample and hand-authored plan arithmetic', () => {
  assert.equal(prices.length, 288);
  assert.deepEqual(horizon, [-24, 48]);
  assert.deepEqual([prices[0].start, prices.at(-1).end], [-24, 48]);
  assert.equal(windows.length, 2);
  assert.deepEqual(windows.map(w => [w.start,w.end]), [[24,24.625],[25,25.375]]);
  assert.equal(windows[0].centsPerKwh.toFixed(2),'22.61');
  assert.equal(windows[1].centsPerKwh.toFixed(2),'32.86');
  const result = total(windows);
  assert.equal(result.energy, 6);
  assert.equal(result.cost.toFixed(4), '1.5872');
  assert.equal(result.centsPerKwh.toFixed(2), '26.45');
  assert.equal(time(windows[0].end), '00:37:30');
  assert.equal(time(-1), '23:00');
});
test('initial coverage and time ticks are anchored independently of panning', () => {
  assert.deepEqual(initialRange(14.5), [13,48]);
  assert.deepEqual(initialRange(-30,[0,.25,.5]),[0,.5]);
  assert.deepEqual(initialRange(3,[0,.25,.5]),[0,.5]);
  assert.equal(initialRange(0,[]),null);
  assert.deepEqual(timeTicks(13.5,25.5,600),[14,16,18,20,22,24]);
  assert.deepEqual(timeTicks(14.25,26.25,600),[16,18,20,22,24,26]);
  assert.equal(time(24),'00:00');
});
test('negative and missing intervals remain exact segments, not zero or interpolation', () => {
  const fixture = [{start: -1, end: 0, cents: -5}, {start: 1, end: 1.5, cents: 7}];
  const segments = stepSegments(fixture);
  assert.deepEqual(segments, [[[-1,-5],[0,-5]], [[1,7],[1.5,7]]]);
  assert.ok(segments[0][1][0] < segments[1][0][0]);
  assert.deepEqual(stepPoints(fixture), [[-1,-5],[0,-5],[0.5,null],[1,7],[1.5,7]]);
  assert.deepEqual(stepSegments(prices).at(-1), [[47.75, prices.at(-1).cents], [48, prices.at(-1).cents]]);
});
test('fictional date bands and missing coverage remain explicit across midnight', () => {
  assert.equal(sampleDate(-24), 'Sun 8 Nov');
  assert.equal(sampleDate(0), 'Mon 9 Nov');
  assert.equal(sampleDate(24), 'Tue 10 Nov');
  assert.deepEqual(sampleDays(23.5,24.5).map(d => [d.start,d.end,d.label]), [[23.5,24,'Today · Mon 9 Nov'],[24,24.5,'Tomorrow · Tue 10 Nov']]);
  assert.deepEqual(priceGaps(-1,3,[{start:0,end:1},{start:2,end:2.5}]),[[-1,0],[1,2],[2.5,3]]);
  assert.deepEqual(priceGaps(0,3,[]),[[0,3]]);
});
test('grouping keeps pauses and control changes; missing tariffs are unknown', () => {
  const b = (start,end,control='a') => ({start,end,control,power:6});
  const grouped = groupBlocks([b(0,0.25), b(.25,.5), b(.5,.75,'b'), b(1,1.25)]);
  assert.deepEqual(grouped.map(w=>[w.start,w.end,w.control]), [[0,.5,'a'],[.5,.75,'b'],[1,1.25,'a']]);
  const result = priceWindow(b(0,1), [{start:0,end:.5,cents:-10},{start:.75,end:1,cents:20}]);
  assert.equal(result.energy,6); assert.equal(result.cost,null); assert.equal(result.centsPerKwh,null);
  const weighted = priceWindow(b(0,.75), [{start:0,end:.5,cents:-10},{start:.5,end:1,cents:20}]);
  assert.ok(Math.abs(weighted.cost) < 1e-10); assert.equal(weighted.centsPerKwh,0);
});
test('unknown inputs do not become zero', () => {
  assert.equal(total([{ energy: null, cost: 0 }]), null);
  assert.equal(total([{ energy: 1, cost: null }]), null);
  assert.equal(total([]), null);
  assert.equal(money(null), 'Unknown');
  assert.equal(total([{ energy: 0, cost: 0 }]).centsPerKwh, null);
});
test('viewport snapping clamps and remains usable on repeated moves without changing plan', () => {
  assert.deepEqual(snapRange(-99, 99), horizon);
  assert.deepEqual(snapRange(24.01, 24.61), [24,24.5]);
  assert.deepEqual(snapRange(48, 48), [47.75,48]);
  let range = [0, 4];
  for (let i=0;i<30;i++) range = snapRange(range[0]+.26,range[1]+.26);
  assert.deepEqual(range,[7.5,11.5]);
  assert.equal(windows[0].end,24.625);
  assert.deepEqual(snapRange(.4,1.7,[0, .5, 2]),[.5,2]);
});

test('SOC projections use cumulative wall energy and efficiency, including partial windows', () => {
  const assumptions = {startingSoc: 48, capacityKwh: 60, efficiency: .9};
  const projected = projectSoc([{energy: 3.75}, {energy: 2.25}], assumptions);
  assert.deepEqual(projected.map(r => r.projectedSoc), [53.625, 57]);
  assert.deepEqual(windows.map(r => r.projectedSoc), projected.map(r => r.projectedSoc));
  assert.equal(projectSoc([{energy: 10}], {...assumptions, efficiency: .5})[0].projectedSoc, 48 + 5 / 60 * 100);
  assert.deepEqual(projectSoc([{energy: 10}, {energy: 1}], {...assumptions, startingSoc: 99}).map(r => r.projectedSoc), [100,100]);
});
test('SOC projections refuse missing and invalid inputs and propagate missing energy', () => {
  const valid = {startingSoc: 0, capacityKwh: 60, efficiency: .9};
  for (const invalid of [{startingSoc:null},{startingSoc:-1},{startingSoc:101},{capacityKwh:0},{capacityKwh:NaN},{efficiency:0},{efficiency:1.1},{efficiency:null}])
    assert.equal(projectSoc([{energy: 1}], {...valid, ...invalid})[0].projectedSoc, null);
  for (const energy of [null, NaN, -1, Infinity]) { const result = projectSoc([{energy:1},{energy},{energy:1}], valid).map(r=>r.projectedSoc); assert.ok(Math.abs(result[0]-1.5)<1e-9); assert.deepEqual(result.slice(1), [null,null]); }
});
