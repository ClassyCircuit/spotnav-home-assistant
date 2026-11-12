import { test } from 'node:test';
import assert from 'node:assert/strict';
import { summarize, assess, bestOpportunity } from './insights.js';
import { history, monthlyRange, baselineRange, futureRange } from './insight-fixture.js';
import { prices, now, priceAt } from './sample.js';
import { renderInsights } from './insight-view.js';

test('duration weighting, negatives, clipped periods and gaps remain truthful', () => {
  const rows = [{start:0,end:.5,cents:-10},{start:.5,end:2,cents:30},{start:3,end:4,cents:5}];
  const s = summarize(rows,0,4);
  assert.equal(s.covered,3); assert.equal(s.coverage,.75); assert.equal(s.count,3);
  assert.equal(s.average,15); assert.equal(s.low,-10); assert.equal(s.high,30);
  assert.equal(s.p25,5); assert.equal(s.p75,30);
  assert.equal(summarize(rows,.25,1).average,50/3);
  assert.equal(summarize([{start:0,end:1,cents:1},{start:.5,end:2,cents:2}],0,2),null);
  assert.equal(summarize([{start:0,end:1,cents:NaN}],0,1).average,null);
});
test('classification uses weighted quartiles and refuses insufficient history or current price', () => {
  const h=Array.from({length:24},(_,i)=>({start:i,end:i+1,cents:i}));
  assert.equal(assess(2,h,0,24).label,'Lower than usual');
  assert.equal(assess(12,h,0,24).label,'Typical for this sample');
  assert.equal(assess(23,h,0,24).label,'Higher than usual');
  assert.equal(assess(2,h.slice(0,20),0,24).label,'Unknown');
  assert.equal(assess(null,h,0,24).label,'Unknown');
  assert.equal(assess(1,[{start:0,end:24,cents:1}],0,24).label,'Unknown');
});
test('opportunities use complete one-hour priced spans, not gaps or future invention', () => {
  const p=[{start:0,end:.5,cents:20},{start:.5,end:1.5,cents:-10},{start:2,end:3,cents:-20}];
  const result=bestOpportunity(p,0,3);
  assert.deepEqual(result.best,{start:2,end:3,average:-20}); assert.equal(result.coverage.coverage,2.5/3);
  assert.equal(bestOpportunity([{start:0,end:.5,cents:-100},{start:.75,end:1,cents:-100}],0,1).best,null);
  assert.equal(bestOpportunity([],0,10).best,null);
  assert.equal(bestOpportunity(p,3,3).best,null);
  assert.equal(bestOpportunity([{start:0,end:.5,cents:10},{start:.5,end:1,cents:30}],0,1).best.average,20);
});
test('fixture labels and rendered values match chart, historical coverage and missing state', () => {
  const b=summarize(history,...baselineRange), m=summarize(history,...monthlyRange);
  const o=bestOpportunity(prices,...futureRange).best;
  assert.equal(b.coverage,1); assert.equal(m.coverage,1); assert.equal(m.count,744);
  assert.ok(o.start>=now && o.end<=futureRange[1]);
  assert.equal(summarize(prices,o.start,o.end).average,o.average);
  const html=renderInsights();
  assert.ok(html.includes(`${priceAt(now).cents.toFixed(2)} c/kWh`));
  assert.ok(html.includes(`${o.average.toFixed(2)} c/kWh`));
  assert.ok(html.includes(`${m.average.toFixed(2)} c/kWh`));
  assert.match(html,/not the proposed plan/i); assert.match(html,/744 hours/);
  const missing=renderInsights(true); assert.match(missing,/Unknown/); assert.match(missing,/No complete 1-hour window/); assert.doesNotMatch(missing,/NaN|Infinity/);
  assert.match(html,/not every possible start/); assert.match(html,/Now or interval boundaries/);
});
