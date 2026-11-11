import { test } from 'node:test';
import assert from 'node:assert/strict';
import { batteryEstimates, renderBattery } from './vehicle-view.js';
import { evidenceFixture, renderEvidence } from './evidence-view.js';

const input = {soc:48,target:80,capacityKwh:60,efficiency:.9,windows:[{start:24,end:24.625},{start:25,end:25.375}]};
test('battery and wall estimates use distinct energy bases and planned active time',()=>{
  const x=batteryEstimates(input);
  assert.ok(Math.abs(x.battery-28.8)<1e-9); assert.ok(Math.abs(x.needed-19.2)<1e-9); assert.ok(Math.abs(x.wall-21.3333333333)<1e-9); assert.equal(x.active,60);
  assert.equal(batteryEstimates({...input,soc:85}).needed,0); assert.equal(batteryEstimates({...input,soc:100}).wall,0);
  assert.equal(batteryEstimates({...input,soc:0}).battery,0);
});
test('invalid, missing or stale inputs never become fabricated values',()=>{
  for (const soc of [null,-1,101,NaN,Infinity]) assert.equal(batteryEstimates({...input,soc}).battery,null);
  for (const capacityKwh of [0,-1,null,NaN,Infinity]) assert.equal(batteryEstimates({...input,capacityKwh}).needed,null);
  for (const efficiency of [0,-1,1.1,null,NaN]) assert.equal(batteryEstimates({...input,efficiency}).wall,null);
  assert.equal(batteryEstimates({...input,target:101}).needed,null); assert.equal(batteryEstimates({...input,windows:[]}).active,null);
  assert.deepEqual(batteryEstimates({...input,stale:true}),{battery:null,needed:null,wall:null,active:null});
  const html=renderBattery({...input,stale:true,lowSocWarning:null}); assert.match(html,/stale/i); assert.match(html,/Unknown/); assert.doesNotMatch(html,/Low-SOC warning|NaN|Infinity/);
  assert.match(renderBattery({...input,soc:15,lowSocWarning:20}),/separate illustrative value/);
  assert.doesNotMatch(renderBattery({...input,lowSocWarning:101}),/Low-SOC warning/);
});
test('sample evidence keeps mismatch, stale, unavailable and match distinct',()=>{
  assert.match(evidenceFixture('mismatch').readback,/mismatch/);
  assert.match(evidenceFixture('stale').readback,/stale/);
  assert.equal(evidenceFixture('unavailable').sent,'Unknown');
  assert.match(evidenceFixture('waiting').readback,/matches last sent/);
  const html=renderEvidence('mismatch','0.0 kW',[{}]);
  for(const text of ['Proposal calculated','Last sent / ACK','Effective limits read','Vehicle / power received','not a profile inventory','does not prove physical charging','not necessarily sent']) assert.ok(html.includes(text),text);
});
