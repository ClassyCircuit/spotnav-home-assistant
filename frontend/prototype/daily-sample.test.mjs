import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dailyStates, chooseDailyState, sentHistory, readings, historyFacts } from './daily-sample.js';
import { renderHistory } from './history-view.js';
import { renderPlan } from './plan-view.js';
import { priceWindow, prices, projectSoc, cap } from './sample.js';

test('alternate states are explicit fictional observations, not inferred from a proposal', () => {
  for (const key of ['waiting','charging','unavailable','infeasible','partial','exception','mismatch']) assert.ok(dailyStates[key]);
  assert.equal(chooseDailyState('charging').power,'6.0 kW');
  assert.equal(chooseDailyState('waiting').power,'0.0 kW');
  assert.equal(chooseDailyState('unavailable').soc,null);
  assert.match(chooseDailyState('infeasible').policy,/short/);
  assert.match(chooseDailyState('partial').policy,/01:22:30/);
  const exception=priceWindow({start:15,end:15.5,power:6},prices);
  assert.ok(exception.centsPerKwh>cap);
  assert.equal(projectSoc([exception],{startingSoc:35.5,capacityKwh:60,efficiency:.9})[0].projectedSoc,40);
  assert.match(renderPlan([{...exception,control:'minimum-exception'}],{startingSoc:35.5,capacityKwh:60,efficiency:.9}),/ABOVE-CAP MINIMUM/);
  assert.equal(chooseDailyState('missing-key'),dailyStates.mismatch);
});
test('sent plan, explicit readings, gap and out-of-plan observation stay distinct', () => {
  assert.deepEqual(sentHistory,{start:22,end:23});
  const facts=historyFacts(); assert.equal(facts.known,3); assert.equal(facts.total,4);
  assert.deepEqual(facts.outside,[{time:21.75,kw:2}]);
  assert.equal(readings.find(r=>r.time===22.5).kw,null);
  const html=renderHistory();
  for(const text of ['Last sent:','21:45–22:00','22:30–22:45','3/4 intervals · 75%','not real charger history']) assert.ok(html.includes(text),text);
  assert.match(html,/disabled/);
});
