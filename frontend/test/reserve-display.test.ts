// @vitest-environment jsdom
// @ts-nocheck
// Stage 15.1b: the reserve control and display in the shared dashboard / sidebar host. Every number shown is the
// backend's; nothing here (or in the code under test) plans or prices.
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { renderPlan } from '../shared-dashboard/plan-view.js';
import { reserveModel } from '../shared-dashboard/reserve-model.js';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};

const fixture = () => JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
const status = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const record = (extra={}) => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:'vehicle_ev6',target_percent:80},soft_price_cap:null,cap_price_basis:null,minimum_ready_by_soc:40,fill_to_limit:false,...extra});
const envelope = (settings,ok=true,error=null) => ({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
beforeEach(()=>sessionStorage.clear());

// Two windows: the second holds 12 min of backend-stated reserve; baseline 3 kWh / 0.45 EUR, allowance 1.2 kWh / 0.18 EUR.
function planned(reserve=true) {
  const now=Date.now(), raw=fixture();raw.generated_at=new Date(now).toISOString();raw.charger.charger_id='a';
  raw.market.currency='EUR';raw.settings.departure_enabled=true;raw.planning.settings_revision=raw.settings.revision;
  raw.planning.calculated_at=raw.generated_at;raw.planning.departure_at=new Date(now+7200000).toISOString();
  raw.soc={...raw.soc,value:62,age_s:60,source:'vehicle',estimated:false,capacity_kwh:70,efficiency:.9};
  const periods=[{start:new Date(now+3600000).toISOString(),end:new Date(now+4200000).toISOString()},{start:new Date(now+4800000).toISOString(),end:new Date(now+6000000).toISOString()}];
  Object.assign(raw.plan.proposal,{periods,planned_kwh:3,cost:{value:.45,currency:'EUR'},unpriced:false,cost_basis:'configured_variable_cost',
    window_details:[{...periods[0],energy_kwh:1,cost:.2,projected_soc:63},{...periods[1],energy_kwh:2,cost:.25,projected_soc:65,...(reserve?{reserve_minutes:12,reserve_kwh:1.2,reserve_cost:.18}:{})}],
    projection:{starting_soc:62,kwh_per_percent:1,age_s:60,source:'vehicle',estimated:false,time_basis:'vehicle_timestamp'}});
  if (reserve) raw.plan.proposal.reserve={percent:10,minutes:12,requested_minutes:12,limit:null,periods:[{start:periods[1].end,end:periods[1].end}],allowance:{kind:'upper_allowance',energy_kwh:1.2,cost:{value:.18,currency:'EUR'}}};
  return {raw,now};
}
const render = m => renderPlan(m.model.windows,m.model.assumptions,false,m.format,m.model.totals,m.model.reserve);

describe('reserve plan display', () => {
  it('shows the backend reserve apart from the baseline, with no double count', () => {
    const {raw,now}=planned();const m=dashboardAdapter(raw,status,now,now);
    expect(m.model.totals).toMatchObject({energy:3,cost:.45});          // baseline only
    expect(m.model.windows.map(w=>w.energy)).toEqual([1,2]);              // window energy stays baseline
    expect(m.model.windows.map(w=>w.reserveMinutes)).toEqual([undefined,12]);
    const html=render(m);
    expect(html).toContain('includes 12 min reserve');
    expect(html).toContain('REQUIRED BASELINE ENERGY');expect(html).toContain('3.00 kWh');expect(html).toContain('€0.45');
    expect(html).toMatch(/Potential extra allowed reserve:<\/b> up to 1\.20 kWh · €0\.18/);
    expect(html).toMatch(/upper allowance.*not measured or expected use/);
    expect(html).toMatch(/Extra allowed time to reach the target; the car’s own limit stops it/);
    expect(html).not.toContain('4.20 kWh');expect(html).not.toContain('€0.63');
  });

  it('degrades to the old display without reserve fields, and for malformed ones', () => {
    const {raw,now}=planned(false);const m=dashboardAdapter(raw,status,now,now);
    expect(m.model.reserve).toBeNull();
    const html=render(m);expect(html).not.toMatch(/reserve/i);expect(html).toContain('WALL ENERGY');
    expect(reserveModel({percent:10,minutes:'x',allowance:{kind:'measured',energy_kwh:1}},'EUR',{explain:'',limits:{unknown:'u'}})).toMatchObject({minutes:null,allowance:null});
    expect(render({...m,model:{...m.model,reserve:reserveModel({percent:10,minutes:null},'EUR',{explain:'',limits:{}})}})).toContain('unavailable');
  });

  it('states zero and limited reserve with the backend reason, and unknown allowance as Unknown', () => {
    const {raw,now}=planned();
    raw.plan.proposal.reserve={...raw.plan.proposal.reserve,minutes:0,requested_minutes:20,limit:'no_eligible_time',allowance:{kind:'upper_allowance',energy_kwh:null,cost:null}};
    raw.plan.proposal.window_details[1]={...raw.plan.proposal.window_details[1],reserve_minutes:0};
    let html=render(dashboardAdapter(raw,status,now,now));
    expect(html).toMatch(/none in this plan \(10% asked\)\. No free cheap time/);expect(html).not.toContain('includes 0');expect(html).not.toContain('REQUIRED BASELINE');
    raw.plan.proposal.reserve={...raw.plan.proposal.reserve,minutes:6,limit:'two_hour_limit',allowance:{kind:'upper_allowance',energy_kwh:null,cost:null}};
    html=render(dashboardAdapter(raw,status,now,now));
    expect(html).toMatch(/6 min of 20 min asked/);expect(html).toContain('capped at 2 hours');expect(html).toMatch(/up to Unknown · Unknown/);expect(html).not.toMatch(/NaN|undefined/);
  });

  it('ignores a cost in another currency and a stale plan', () => {
    const {raw,now}=planned();raw.plan.proposal.reserve.allowance.cost.currency='SEK';
    expect(dashboardAdapter(raw,status,now,now).model.reserve.allowance.cost).toBeNull();
    const old=planned();old.raw.generated_at=new Date(old.now-3*3600000).toISOString();
    expect(dashboardAdapter(old.raw,status,old.now,old.now).model.reserve).toBeNull();
  });
});

describe('reserve control in the sidebar', () => {
  async function mount(saved, onWrite) {
    const {raw}=planned();const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(saved.v));if(msg.type==='spotnav/update_settings')return Promise.resolve(onWrite(msg));return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    return {panel,calls,raw};
  }
  const edit = (panel,v) => {const i=panel.shadowRoot.querySelector('[data-setting="reserve"]');i.value=v;i.dispatchEvent(new Event('input',{bubbles:true}));return i;};

  it('shows the saved value and saves an edit as a revision-checked guarded write', async () => {
    const saved={v:record({time_reserve_percent:10})};
    const {panel,calls}=await mount(saved,msg=>{saved.v={...msg.settings,revision:8};return envelope(saved.v);});
    const input=panel.shadowRoot.querySelector('[data-setting="reserve"]');expect(input.value).toBe('10');
    expect(panel.shadowRoot.querySelector('.settings-help').textContent).toContain('Extra time reserve: 10%');
    edit(panel,'25');panel.shadowRoot.querySelector('#save-plan').click();await tick();
    const write=calls.find(m=>m.type==='spotnav/update_settings');
    expect(write.expected_revision).toBe(7);expect(write.settings.time_reserve_percent).toBe(25);expect(write.settings.minimum_ready_by_soc).toBe(40);
    expect(panel.shadowRoot.querySelector('[data-setting="reserve"]').value).toBe('25');expect(panel.settingsRecord.revision).toBe(8);panel.remove();
  });

  it('refuses an out-of-range value without writing, and writes nothing when only viewing', async () => {
    const saved={v:record({time_reserve_percent:10})};
    const {panel,calls}=await mount(saved,()=>envelope(saved.v));
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);
    edit(panel,'80');panel.shadowRoot.querySelector('#save-plan').click();await tick();
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);expect(panel.settingsNotice).toMatch(/outside the allowed range/);panel.remove();
  });

  it('keeps a draft and blocks the save when the settings revision moved', async () => {
    const saved={v:record({time_reserve_percent:10})};
    const {panel,calls}=await mount(saved,()=>envelope(saved.v));
    const hass=panel.hass;edit(panel,'30');
    panel.hass={...hass,connected:false};saved.v={...saved.v,revision:8};panel.hass=hass;await tick();
    expect(panel.settingsConflict).toBe(true);expect(panel.shadowRoot.querySelector('#save-plan').disabled).toBe(true);
    expect(panel.shadowRoot.querySelector('[data-setting="reserve"]').value).toBe('30');
    panel.shadowRoot.querySelector('#save-plan').click();await tick();expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);panel.remove();
  });

  it('shows no control against a backend without the field, and never sends one', async () => {
    const saved={v:record()};
    const {panel,calls}=await mount(saved,msg=>{saved.v={...msg.settings,revision:8};return envelope(saved.v);});
    expect(panel.shadowRoot.querySelector('[data-setting="reserve"]')).toBeNull();
    const t=panel.shadowRoot.querySelector('[data-setting="target"]');t.value='75';t.dispatchEvent(new Event('input',{bubbles:true}));
    panel.shadowRoot.querySelector('#save-plan').click();await tick();
    expect('time_reserve_percent' in calls.find(m=>m.type==='spotnav/update_settings').settings).toBe(false);panel.remove();
  });
});
