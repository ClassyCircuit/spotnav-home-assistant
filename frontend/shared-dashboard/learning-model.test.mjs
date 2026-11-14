import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeLearning, learningModel } from './learning-model.js';
import { renderPlan } from './plan-view.js';

const text = {title:'Estimate',unknown:'UNKNOWN',default:'DEFAULT',learned:'LEARNED',samples:'{agreeing}/{shorten} short, {lengthen} long, {valid} valid',
  effect_longer:'LONGER {minutes}',effect_shorter:'SHORTER {minutes}',effect_none:'NONE',effect_unknown:'EFFECT?',clamped:'CLAMPED',note:'NOTE',stale:'STALE',rejected:'REJ {list}'};
const block = (extra = {}) => ({mode:'morek',source:'learned',valid_samples:5,agreeing_samples:4,needed_to_lengthen:3,needed_to_shorten:5,clamped:false,effect_minutes:7,rejections:{gap:2,late_unknown:1},...extra});

test('learned display states the backend counts and effect, never client arithmetic', () => {
  const m = learningModel(block(), false, text);
  assert.equal(m.state, 'fresh');
  assert.deepEqual(m.lines, ['LEARNED', '4/5 short, 3 long, 5 valid', 'LONGER 7', 'REJ gap ×2, late unknown ×1']);
  assert.equal(learningModel(block({effect_minutes:-3}), false, text).lines[2], 'SHORTER 3');
});

test('default, unknown effect, stale and missing blocks stay truthful', () => {
  assert.deepEqual(learningModel(block({source:'default',effect_minutes:0,agreeing_samples:0,valid_samples:0,rejections:{}}), false, text).lines, ['DEFAULT', '0/5 short, 3 long, 0 valid', 'NONE']);
  assert.equal(learningModel(block({effect_minutes:null}), false, text).lines[2], 'EFFECT?');
  const stale = learningModel(block(), true, text);
  assert.equal(stale.state, 'stale');
  assert.ok(!stale.lines.some(l => l.startsWith('LONGER')) && stale.lines.includes('EFFECT?') && stale.staleText === 'STALE');
  assert.deepEqual(learningModel(undefined, false, text).lines, ['UNKNOWN']);
  assert.equal(learningModel(undefined, false, text).state, 'unknown');
  assert.equal(learningModel(null, true, text).state, 'stale');
});

test('malformed blocks are rejected strictly', () => {
  for (const bad of [[], 'x', block({source:'guess'}), block({mode:'x'}), block({valid_samples:-1}), block({agreeing_samples:9}), block({effect_minutes:'7'}), block({needed_to_shorten:0}), block({effect_minutes:Infinity})])
    assert.equal(decodeLearning(bad), null);
  assert.equal(decodeLearning(block({rejections:{'<b>':3,gap:'2',ok_reason:0}})).rejections.length, 0);
});

test('the shared plan renders the learned estimate escaped and only when given', () => {
  const f = {time:()=>'t',day:()=>'d'};
  const rows = [{start:1,end:2,energy:1,cost:2}];
  const html = renderPlan(rows, {}, false, f, undefined, undefined, learningModel(block(), false, {...text, learned:'<img src=x>'}));
  assert.ok(html.includes('plan-learning') && html.includes('&lt;img src=x&gt;') && !html.includes('<img'));
  assert.ok(!renderPlan(rows, {}, false, f).includes('plan-learning'));
});
