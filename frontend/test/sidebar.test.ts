// @vitest-environment jsdom
// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { renderBattery } from '../shared-dashboard/vehicle-view.js';
import { renderPlan } from '../shared-dashboard/plan-view.js';
import '../sidebar/panel.js';
import { observationFreshness } from '../src/observation-freshness.ts';

// jsdom does not implement form-associated custom-element internals.
ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};

const fixture = () => JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
const status = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const record = () => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40});
const envelope = (settings,ok=true,error=null) => ({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
beforeEach(()=>sessionStorage.clear());

describe('actual sidebar read-only host', () => {
  it.each([['manual_kwh','target_soc'],['target_soc','manual_kwh']])('saves explicit %s to %s through canonical settings', async (from,to) => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.soc.age_s=86400;raw.soc_observation={time_basis:'vehicle_timestamp',integration:'vehicle',restored:false};
    let saved={...record(),driver:from,target:{vehicle_id:'vehicle_ev6',target_percent:80},requested_kwh:20};const calls=[], planner=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(saved));if(msg.type==='spotnav/update_settings'){planner.push({driver:msg.settings.driver,requested_kwh:msg.settings.requested_kwh,target:msg.settings.target});saved={...msg.settings,revision:8};return Promise.resolve(envelope(saved));}return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot;
    expect(root.textContent).toMatch(/guarded schedule reconciliation/);expect(root.textContent).toMatch(/Vehicle report 24 h ago/);
    const mode=root.querySelector('[data-setting="driver"]');expect(mode.value).toBe(from);mode.value=to;mode.dispatchEvent(new Event('change',{bubbles:true}));
    expect(root.querySelector('[data-setting="energy"]').parentElement.hidden).toBe(to!=='manual_kwh');expect(root.querySelector('[data-setting="target"]').parentElement.hidden).toBe(to!=='target_soc');
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);
    root.querySelector('#save-plan').click();await tick();const write=calls.find(m=>m.type==='spotnav/update_settings');expect(write.expected_revision).toBe(7);expect(write.settings.driver).toBe(to);expect(write.settings.requested_kwh).toBe(20);expect(write.settings.target).toEqual({vehicle_id:'vehicle_ev6',target_percent:80});expect(write.settings.minimum_ready_by_soc).toBe(40);expect(planner).toEqual([{driver:to,requested_kwh:20,target:{vehicle_id:'vehicle_ev6',target_percent:80}}]);
    expect(panel.settingsRecord.driver).toBe(to);panel.remove();
  });
  it('validates mode inputs, preserves drafts and refuses unavailable or guest vehicle choices', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.soc.vehicle_id=null;raw.soc.vehicle_name=null;raw.soc.capacity_kwh=null;raw.soc.vehicles=[];const calls=[];
    const initial={...record(),driver:'manual_kwh',target:{vehicle_id:null,target_percent:null}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(initial):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot;
    const mode=root.querySelector('[data-setting="driver"]');mode.value='target_soc';mode.dispatchEvent(new Event('change',{bubbles:true}));expect(root.textContent).toMatch(/No unambiguous vehicle selected/);expect(root.textContent).toMatch(/capacity is unavailable/i);
    const target=root.querySelector('[data-setting="target"]');target.value='120';target.dispatchEvent(new Event('input',{bubbles:true}));root.querySelector('#save-plan').click();await tick();expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);expect(target.value).toBe('120');
    panel.refresh();await tick();expect(root.querySelector('[data-setting="driver"]').value).toBe('target_soc');expect(root.querySelector('[data-setting="target"]').value).toBe('120');
    const vals={driver:'target_soc',energy:'20',vehicleId:'guest',target:'80',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};await panel.savePlan(vals);expect(panel.settingsNotice).toMatch(/available discovered vehicle/);
    await panel.savePlan({...vals,vehicleId:'',target:'30',minimum:'40'});expect(panel.settingsNotice).toMatch(/Minimum SOC/);
    await panel.savePlan({...vals,driver:'manual_kwh',vehicleId:'',energy:'-1'});expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);panel.remove();
  });
  it.each(['denied','conflict','rejected'])('retains mode draft on %s save', async outcome => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.settings.users_change_plan=false;const calls=[];const initial={...record(),driver:'manual_kwh'};
    const hass={connected:true,user:{is_admin:outcome!=='denied'},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(initial):msg.type==='spotnav/update_settings'?envelope(initial,false,outcome==='conflict'?'revision_conflict':'invalid_settings'):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const mode=panel.shadowRoot.querySelector('[data-setting="driver"]');mode.value='target_soc';mode.dispatchEvent(new Event('change',{bubbles:true}));
    const values={driver:'target_soc',energy:'20',vehicleId:'',target:'80',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};await panel.savePlan(values);await tick();
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(outcome==='denied'?0:1);expect(panel.shadowRoot.querySelector('[data-setting="driver"]').value).toBe('target_soc');expect(panel.settingsRecord.driver).toBe('manual_kwh');expect(panel.settingsNotice).toMatch(outcome==='denied'?/permission/:outcome==='conflict'?/conflict/i:/rejected/i);panel.remove();
  });
  it('bounds observation skew and distinguishes stale causes', () => {
    const now=Date.now(), raw=fixture();
    for (const [value,reason] of [[now+100,'fresh'],[now+5000,'fresh'],[now+5001,'future'],[now-90000,'fresh'],[now-90001,'old'],[NaN,'invalid'],[null,'invalid']]) {
      expect(observationFreshness(value,now)).toBe(reason);
    }
    for (const [value,reason] of [[new Date(now+100).toISOString(),null],[new Date(now+5001).toISOString(),'future'],[new Date(now-90001).toISOString(),'too old'],['bad','invalid'],[null,'invalid']]) {
      raw.generated_at=value;
      const model=dashboardAdapter(raw,status,now,now).model;
      if (reason) expect(model.vehicle.detail).toContain(reason);
      else expect(model.vehicle.detail).not.toContain('stale');
    }
    raw.generated_at=new Date(now).toISOString();
    expect(dashboardAdapter(raw,status,now,now,false,true).model.vehicle.detail).toContain('refresh failed');
  });
  it.each(['slight','future','old','invalid','missing','failed','status_future','status_failed'])('keeps Resume display and dispatch aligned for %s', async scenario => {
    const now=Date.now(), raw=fixture();raw.generated_at=new Date(now+(scenario==='slight'?100:scenario==='future'?6000:scenario==='old'?-100000:0)).toISOString();
    if(scenario==='invalid')raw.generated_at='bad';if(scenario==='missing')raw.generated_at=null;raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,outcomes:{uncertain:false},ownership:{recorded_owner:'morek_schedule',completion_authorized:true},schedule_pause:{intent:'pause_until_resumed',request:'pending'}}};const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):msg.type==='spotnav/manual_action'?{api_version:1,ok:true,error:null,action:'resume',choice:null}:owned);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    panel.refresh();await tick();expect(calls.filter(m=>m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status'))).toHaveLength(0);
    if(scenario==='failed')panel.dashboardFailed=true;if(scenario==='status_future')panel.statusAt=Date.now()+6000;if(scenario==='status_failed')panel.statusFailed=true;
    if(scenario==='slight')panel.statusAt=Date.now()+100;
    panel.paint();expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(scenario!=='slight');
    await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(scenario==='slight'?1:0);panel.remove();
  });
  it('renders reconciled planner windows, costs, deadline and last-known SOC consistently', async () => {
    const now=Date.now(), raw=fixture();raw.generated_at=new Date(now).toISOString();raw.charger.charger_id='a';
    raw.market.currency='EUR';raw.settings.departure_enabled=true;raw.planning.settings_revision=raw.settings.revision;
    raw.planning.calculated_at=raw.generated_at;raw.planning.departure_at=new Date(now+7200000).toISOString();
    raw.soc={...raw.soc,value:62,age_s:86400,source:'vehicle',estimated:false,capacity_kwh:70,efficiency:.9};
    const periods=[{start:new Date(now+3600000).toISOString(),end:new Date(now+4200000).toISOString()},{start:new Date(now+4800000).toISOString(),end:new Date(now+6000000).toISOString()}];
    Object.assign(raw.plan.proposal,{periods,planned_kwh:3,cost:{value:.45,currency:'EUR'},unpriced:false,cost_basis:'configured_variable_cost',
      window_details:[{...periods[0],energy_kwh:1,cost:.2,projected_soc:63},{...periods[1],energy_kwh:2,cost:.25,projected_soc:65}],
      projection:{starting_soc:62,kwh_per_percent:1,age_s:86400,source:'vehicle',estimated:false,time_basis:'vehicle_timestamp'}});
    const model=dashboardAdapter(raw,status,now,now);expect(model.model.untilDeadline).toBe('120 min');
    expect(model.model.windows.map(w=>w.energy)).toEqual([1,2]);expect(model.model.totals.pricePerKwh).toBe(15);
    expect(model.model.assumptions.projectionNote).toMatch(/1440 min old.*may be inaccurate/);
    expect(model.model.assumptions.projectionNote).toMatch(/vehicle report 1440 min old/);
    const html=renderPlan(model.model.windows,model.model.assumptions,false,model.format,model.model.totals);
    expect(html).toContain('20 c/kWh');expect(html).toContain('12.5 c/kWh');expect(html).toContain('15 c/kWh');expect(html).toContain('65.0%');
    const hass={connected:true,user:{is_admin:true},callWS:msg=>Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    for(const root of [panel.shadowRoot.querySelector('.controls-plan'),panel.shadowRoot.querySelector('.prices'),panel.shadowRoot.querySelector('#plan-dialog')]) expect(root.textContent).toContain('15 c/kWh');
    panel.remove();
    raw.plan.proposal.projection.time_basis='last_updated';expect(dashboardAdapter(raw,status,now,now).model.assumptions.projectionNote).toMatch(/HA state 1440 min old; vehicle report time unavailable/);
    raw.market.currency='SEK';raw.plan.proposal.cost.currency='SEK';const sek=dashboardAdapter(raw,status,now,now);const sekHtml=renderPlan(sek.model.windows,sek.model.assumptions,false,sek.format,sek.model.totals);
    expect(sekHtml).toContain('0.15 SEK/kWh');expect(sekHtml).not.toContain('c/kWh');
    raw.plan.proposal.unpriced=true;raw.plan.proposal.cost=null;raw.plan.proposal.window_details.forEach(row=>row.cost=null);
    const unpriced=dashboardAdapter(raw,status,now,now);expect(unpriced.model.totals.cost).toBeNull();expect(unpriced.model.totals.pricePerKwh).toBeNull();expect(unpriced.format.detailsNote).toMatch(/unpriced/);
    raw.plan.proposal.unpriced=false;raw.plan.proposal.cost={value:.45,currency:'SEK'};raw.plan.proposal.cost_basis=null;
    expect(dashboardAdapter(raw,status,now,now).model.totals.pricePerKwh).toBeNull();
    raw.plan.proposal.cost_basis='configured_variable_cost';raw.plan.proposal.planned_kwh=0;
    expect(dashboardAdapter(raw,status,now,now).model.totals.pricePerKwh).toBeNull();
    raw.settings.departure_enabled=false;expect(dashboardAdapter(raw,status,now,now).model.untilDeadline).toBe('Not enabled');
    raw.settings.departure_enabled=true;raw.planning.departure_at=null;expect(dashboardAdapter(raw,status,now,now).model.untilDeadline).toBe('Unavailable');
  });
  it('selects only a sole charger, preserves a valid selection, and never writes on open', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    let chargers=[{charger_id:'a',charger_name:'A'}];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    expect(panel.charger).toBe('a');expect(panel.shadowRoot.querySelector('.shell')).toBeTruthy();
    chargers=[...chargers,{charger_id:'b',charger_name:'B'}];panel.hass={...hass,connected:false};panel.hass=hass;await tick();expect(panel.charger).toBe('a');
    panel.remove();const next=document.createElement('spotnav-enhanced-panel');next.hass=hass;document.body.append(next);await tick();expect(next.charger).toBe('a');next.remove();
    expect(calls.every(m=>['spotnav/list_chargers','spotnav/get_dashboard','spotnav/get_settings'].includes(m.type)||(m.type==='spotnav/morek_schedule'&&m.action==='status'))).toBe(true);
  });
  it('handles multiple, empty, changed and failed lists without stale dashboard', async () => {
    let chargers=[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}], fail=false;
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const hass={connected:true,callWS:msg=>msg.type==='spotnav/list_chargers'?(fail?Promise.reject(Error()):Promise.resolve({api_version:1,chargers})):Promise.resolve(msg.type==='spotnav/get_dashboard'?raw:status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();expect(panel.charger).toBe('');
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    chargers=[];panel.hass={...hass,connected:false};panel.hass=hass;await tick();expect(panel.charger).toBe('');expect(panel.shadowRoot.textContent).toContain('No chargers available.');expect(panel.shadowRoot.querySelector('.shell')).toBeNull();
    fail=true;await panel.loadChargers();expect(panel.shadowRoot.textContent).toContain('Charger list unavailable.');panel.remove();
  });
  it('ignores stale list replies after reconnect and teardown', async () => {
    const pending=[];const hass={connected:true,callWS:msg=>msg.type==='spotnav/list_chargers'?new Promise(r=>pending.push(r)):Promise.resolve(status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();panel.hass={...hass,connected:false};panel.hass=hass;await tick();
    pending[1]({api_version:1,chargers:[]});await tick();pending[0]({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});await tick();expect(panel.charger).toBe('');expect(panel.shadowRoot.textContent).toContain('No chargers available.');
    const p=panel.loadChargers();await tick();panel.remove();pending[2]({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});await p;expect(panel.charger).toBe('');
  });
  it('retains drafts across reconnect but blocks saving against a changed revision', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let saved=record();
    const hass={connected:true,user:{is_admin:true},callWS:msg=>Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(saved):status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const input=panel.shadowRoot.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));
    panel.hass={...hass,connected:false};expect(panel.shadowRoot.querySelector('main').hidden).toBe(true);saved={...saved,revision:8};panel.hass=hass;await tick();
    expect(panel.shadowRoot.querySelector('[data-setting="target"]').value).toBe('85');expect(panel.settingsConflict).toBe(true);expect(panel.shadowRoot.querySelector('#save-plan').disabled).toBe(true);panel.remove();
  });
  it('shows missing settings and keeps suggested basis out of an unrelated save', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const initial={...record(),driver:'target_soc',target:{vehicle_id:null,target_percent:null},soft_price_cap:null,cap_price_basis:null,minimum_ready_by_soc:null,departure_enabled:false};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(initial):msg.type==='spotnav/update_settings'?envelope({...msg.settings,revision:8}):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot;
    expect(root.textContent).toContain('not set (optional)');expect(root.textContent).toContain('suggested: Nord Pool');expect(root.textContent).toContain('does not select the price provider');expect(root.textContent).toContain('Ready-by: off');
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);
    await panel.savePlan({target:'',minimum:'',cap:'',capEnabled:false,capBasis:'',deadlineEnabled:true,readyBy:'06:30'});await tick();
    const write=calls.find(m=>m.type==='spotnav/update_settings');expect(write.expected_revision).toBe(7);expect(write.settings.cap_price_basis).toBeNull();expect(write.settings.target.target_percent).toBeNull();panel.remove();
  });
  it('explains manual mode and preserves saved cap basis and target on a revision-checked save', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const initial={...record(),driver:'manual_kwh',cap_price_basis:'configured_variable_cost'};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(initial):msg.type==='spotnav/update_settings'?envelope({...msg.settings,revision:8}):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot;
    expect(root.textContent).toContain('Saved Charge by: requested energy');expect(root.querySelector('[data-setting="target"]').parentElement.hidden).toBe(true);
    expect(root.querySelector('[data-setting="capBasis"]').value).toBe('configured_variable_cost');
    await panel.savePlan({target:'80',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'configured_variable_cost',deadlineEnabled:false,readyBy:'06:30'});await tick();
    const write=calls.find(m=>m.type==='spotnav/update_settings');expect(write.expected_revision).toBe(7);expect(write.settings.driver).toBe('manual_kwh');expect(write.settings.target.target_percent).toBe(80);expect(write.settings.cap_price_basis).toBe('configured_variable_cost');panel.remove();
  });
  it('shows an EUR cap in cents and saves back in EUR/kWh once', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.market.currency='EUR';const calls=[];
    const initial={...record(),soft_price_cap:0.12345};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(initial):msg.type==='spotnav/update_settings'?envelope({...msg.settings,revision:8}):status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot, cap=root.querySelector('[data-setting="cap"]');
    expect(cap.value).toBe('12.345');expect(cap.getAttribute('label')).toContain('c/kWh');
    await panel.savePlan({target:'85',minimum:'40',cap:'12.345',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'});await tick();
    expect(calls.find(m=>m.type==='spotnav/update_settings').settings.soft_price_cap).toBe(0.12345);
    await panel.savePlan({target:'85',minimum:'40',cap:'-2.125',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'});await tick();
    expect(calls.filter(m=>m.type==='spotnav/update_settings').at(-1).settings.soft_price_cap).toBe(-0.02125);expect(root.querySelector('[data-setting="cap"]').value).toBe('-2.125');panel.remove();
  });
  it('blocks a draft if the market currency changes while editing', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.market.currency='EUR';
    const hass={connected:true,user:{is_admin:true},callWS:msg=>Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const input=panel.shadowRoot.querySelector('[data-setting="cap"]');input.value='12';input.dispatchEvent(new Event('input',{bubbles:true}));
    raw.market.currency='SEK';panel.paint();expect(panel.settingsConflict).toBe(true);expect(panel.shadowRoot.querySelector('#save-plan').disabled).toBe(true);expect(input.value).toBe('12');panel.remove();
  });
  it('offers admin reconfirmation without sending on render', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,ownership:{recorded_owner:'morek_schedule',reconfirmation_required:true,completion_authorized:false}}};
    const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:vi.fn(msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);return Promise.resolve(owned);})};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    expect([...panel.shadowRoot.querySelectorAll('button')].some(button=>button.textContent==='Reconfirm schedule ownership')).toBe(true);
    expect(calls.some(m=>m.type==='spotnav/morek_schedule'&&m.action!=='status')).toBe(false);
    panel.remove();
  });
  it('keeps schedule-owned controls unarmed and reports intent separately from flow', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,ownership:{recorded_owner:'morek_schedule'},schedule_pause:{intent:'pause_until_resumed',request:'uncertain',ack:null,readback:'unverified',measured:'unknown'}}};
    const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:vi.fn(msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);return Promise.resolve(owned);})};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const root=panel.shadowRoot;
    expect(root.querySelector('#pause-state').textContent).toMatch(/Pause requested.*uncertain.*physical charging unknown.*Resume unavailable/);
    expect(root.querySelector('#pause-auto').disabled).toBe(false);
    expect(root.querySelector('#resume-auto').disabled).toBe(true);
    panel.rawStatus={...owned,schedule:{...owned.schedule,schedule_pause:{intent:'resume_requested',request:'accepted',ack:'Accepted',readback:'bounded_match',measured:'unknown'}}};panel.paint();
    expect(root.querySelector('#pause-state').textContent).toMatch(/Resume requested; retained limit may remain.*Accepted.*bounded effective readback match.*physical charging unknown/);
    expect(calls.some(m=>m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status'))).toBe(false);
    panel.remove();
  });
  it('reports readiness conservatively as observations age or fail', () => {
    const now=Date.now(), raw=fixture(); raw.generated_at=new Date(now).toISOString();
    const current={api_version:1,schedule:{...status.schedule,supported:true,readiness:{control:'available',vehicle:'disconnected',vehicle_observed_at:new Date(now).toISOString()}}};
    const text=(s,t=now,failed=false)=>dashboardAdapter(raw,s,now,t,failed).model.evidence.readiness;
    expect(text(current)).toMatch(/Control available · vehicle disconnected/);
    expect(text(current,now+90001)).toMatch(/Control unknown · vehicle unknown/);
    expect(text(current,now,true)).toMatch(/Control unknown · vehicle unknown/);
    current.schedule.readiness.vehicle_observed_at=new Date(now-180001).toISOString();
    expect(text(current)).toMatch(/vehicle unknown/);
    expect(text(current)).toMatch(/authorization unknown · measured charging unknown/);
    const dispatch=dashboardAdapter(raw,current,now).model.evidence.dispatch;
    expect(dispatch).toMatch(/0 A limit may remain/);
    expect(dispatch).toMatch(/not profile inventory/);
    expect(dispatch).toMatch(/person Stop and household protection/);
  });
  it('decodes backend fixture without sample data and fails closed on stale or unsupported data', () => {
    const raw=fixture(); raw.generated_at=new Date().toISOString();
    raw.plan.proposal.periods=[{start:new Date(Date.now()+3600000).toISOString(),end:new Date(Date.now()+7200000).toISOString()}];
    const adapter=dashboardAdapter(raw,status,Date.now());
    expect(adapter.model.evidence.status).toMatch(/unsupported/i);
    expect(adapter.model.vehicle.power).toBe('Unavailable');
    expect(adapter.model.canSave).toBe(false);
    expect(adapter.model.chart).toBeUndefined();
    expect(adapter.model.windows).toHaveLength(1);
    expect(adapter.model.totals.energy).toBe(34.5);
    expect(adapter.model.totals.cost).toBeCloseTo(62.548);
    expect(adapter.format.currency).toBe('SEK');
    expect(adapter.model.windows[0].cost).toBeNull();
    expect(renderBattery({windows:adapter.model.windows,minutesPerTimeUnit:adapter.format.minutesPerTimeUnit})).toContain('60 min');
    const start=Date.now();
    expect(renderBattery({windows:[{start,end:start+3600000},{start:start+4000000,end:start+4900000}],minutesPerTimeUnit:adapter.format.minutesPerTimeUnit})).toContain('75 min');
    expect(renderBattery({windows:[{start:2,end:3},{start:4,end:4.25}],minutesPerTimeUnit:60})).toContain('75 min');
    expect(dashboardAdapter({...raw,api_version:99},status,Date.now())).toBeNull();
    raw.generated_at='2000-01-01T00:00:00Z';
    expect(dashboardAdapter(raw,status,Date.now()).model.windows).toBeNull();
    const mismatch={api_version:1,schedule:{...status.schedule,supported:true,operator:{state:'mismatch'},outcomes:{uncertain:true}}};
    const warning=dashboardAdapter(raw,mismatch,Date.now()).model.warning;
    expect(warning.detail).toMatch(/may have applied/i);
    expect(warning.detail).toMatch(/mismatch/i);
  });
  it('withdraws cached dashboard observations immediately after a failed refresh and restores them on recovery', () => {
    const now=Date.now(), raw=fixture(); raw.generated_at=new Date(now).toISOString();
    raw.plan.proposal.periods=[{start:new Date(now+3600000).toISOString(),end:new Date(now+7200000).toISOString()}];
    const current=()=>dashboardAdapter(raw,status,now,now,false,false).model;
    expect(current().windows).toHaveLength(1);
    const failed=dashboardAdapter(raw,status,now,now,false,true).model;
    expect(failed.vehicle.status).toMatch(/unavailable.*stale/i);
    expect(failed.vehicle.soc).toBe(raw.soc.value);
    expect(failed.vehicle.stale).toBe(true);
    expect(failed.windows).toBeNull();
    expect(failed.totals).toBeNull();
    expect(current().windows).toHaveLength(1);
  });
  it('blocks cached Resume immediately after an actual failed dashboard refresh', async () => {
    const raw=fixture();raw.generated_at=new Date(Date.now()+100).toISOString();raw.charger.charger_id='a';let fail=false;const calls=[];
    const owned={api_version:1,schedule:{...status.schedule,supported:true,outcomes:{uncertain:false},ownership:{recorded_owner:'morek_schedule',completion_authorized:true},schedule_pause:{intent:'pause_until_resumed',request:'pending'}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/get_dashboard')return fail?Promise.reject(Error('private error')):Promise.resolve(raw);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_settings'?envelope(record()):owned);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(false);
    fail=true;panel.refresh();await tick();expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(true);expect(panel.shadowRoot.textContent).toMatch(/refresh failed/i);expect(panel.shadowRoot.textContent).not.toContain('private error');
    await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);panel.remove();
  });
  it('offers Resume after clean ownership with a durable manual pause, without an undefined notice', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'manual',admitted_at:raw.generated_at,expires_at:null,action:'stop',scope:'plug_in'};
    const owned={api_version:1,schedule:{...status.schedule,supported:true,outcomes:{uncertain:false},ownership:{recorded_owner:'morek_schedule',completion_authorized:true},schedule_pause:{intent:'pause_until_resumed',request:'pending',ack:null,readback:'unverified'}}};const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:true,error:null,action:'resume',choice:null});return Promise.resolve(owned);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const root=panel.shadowRoot;
    expect(root.querySelector('#pause-notice').textContent).toBe('');expect(root.querySelector('#pause-state').textContent).not.toMatch(/Resume unavailable/);expect(root.querySelector('#resume-auto').disabled).toBe(false);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);
    await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);panel.remove();
  });
  it('explains an unauthorized schedule owner without claiming a physical state', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,ownership:{recorded_owner:'morek_schedule',completion_authorized:false,recovery:{automatic_recovery:'restart_dispatch_evidence_unavailable'}},schedule_pause:{intent:'pause_until_resumed',request:'pending',ack:null,readback:'unverified'}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):owned)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();expect(panel.shadowRoot.querySelector('#pause-state').textContent).toMatch(/physical charging unknown.*not currently authorized.*restart_dispatch_evidence_unavailable/);expect(panel.shadowRoot.querySelector('#pause-notice').textContent).toBe('');expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(true);panel.remove();
  });
  it('offers schedule-owned Resume even when the legacy dashboard says Pause', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,outcomes:{uncertain:false},ownership:{recorded_owner:'morek_schedule',completion_authorized:true},schedule_pause:{intent:'pause_until_resumed',request:'pending',ack:null,readback:'unverified'}}};const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:true,error:null,action:'resume',choice:null});return Promise.resolve(owned);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(false);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);panel.remove();
  });
  it.each(['unknown','uncertain','stop_pending','unauthorized','stale','dashboard_failed'])('does not bypass %s when offering schedule-owned Resume', async reason => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const owned={api_version:1,schedule:{...status.schedule,supported:true,outcomes:{uncertain:reason==='uncertain'},ownership:{recorded_owner:'morek_schedule',completion_authorized:reason!=='unauthorized'},schedule_pause:{intent:'pause_until_resumed',request:reason==='stop_pending'?'stop_pending':'pending',ack:null,readback:'unverified'}}};if(reason==='unknown')delete owned.schedule.outcomes;
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);return Promise.resolve(msg.type==='spotnav/list_chargers'?{api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]}:msg.type==='spotnav/get_dashboard'?raw:msg.type==='spotnav/get_settings'?envelope(record()):owned);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();if(reason==='stale')panel.statusAt=Date.now()-90001;if(reason==='dashboard_failed')panel.dashboardFailed=true;panel.paint();expect(panel.shadowRoot.querySelector('#resume-auto').disabled).toBe(true);await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);panel.remove();
  });
  it('keeps last vehicle SOC visible while tracking report age, source and estimates separately', () => {
    const now=Date.now(), raw=fixture();raw.generated_at=new Date(now).toISOString();
    raw.soc={...raw.soc,value:62,age_s:30,source:'vehicle',estimated:false,capacity_kwh:70,efficiency:0.9};
    raw.soc_observation={time_basis:'vehicle_timestamp',restored:false,integration:'bavariandata',raw_value:62,raw_age_s:30,raw_time_basis:'vehicle_timestamp',raw_source:'vehicle'};
    let m=dashboardAdapter(raw,status,now,now).model;
    expect(m.vehicle.soc).toBe(62);expect(m.vehicle.stale).toBe(false);expect(m.vehicle.socDetail).toMatch(/bavariandata.*Vehicle report 30 s ago/);expect(m.assumptions.capacityKwh).toBe(70);
    m=dashboardAdapter(raw,status,now,now+300000).model;expect(m.vehicle.soc).toBe(62);expect(m.vehicle.stale).toBe(true);expect(m.vehicle.socDetail).toMatch(/5 min ago/);expect(m.assumptions.startingSoc).toBeNull();
    expect(m.targetNote).toMatch(/estimates based on the last-known SOC/);
    expect(renderBattery({soc:62,stale:true,planStale:false,windows:[{start:0,end:3600000}],minutesPerTimeUnit:1/60000})).toContain('60 min');
    raw.generated_at=new Date(now+300000).toISOString();raw.soc.age_s=330;raw.soc_observation.raw_age_s=330;
    m=dashboardAdapter(raw,status,now,now+300000).model;expect(m.vehicle.socDetail).toMatch(/5 min ago/);
    raw.soc={...raw.soc,value:68,estimated:true};m=dashboardAdapter(raw,status,now,now+300000).model;
    expect(m.vehicle.soc).toBe(62);expect(m.vehicle.socDetail).toMatch(/SpotNav estimate: 68%.*not a vehicle measurement/);expect(m.assumptions.startingSoc).toBeNull();
    raw.soc_observation={...raw.soc_observation,raw_value:null,integration:null};m=dashboardAdapter(raw,status,now,now+300000).model;
    expect(m.vehicle.soc).toBe(68);expect(m.vehicle.socEstimated).toBe(true);
    expect(renderBattery({soc:m.vehicle.soc,stale:m.vehicle.stale,socEstimated:true,socDetail:m.vehicle.socDetail})).toContain('Estimated SOC - not a measurement');
    raw.soc.estimated=false;raw.soc.value=null;m=dashboardAdapter(raw,status,now,now+300000).model;expect(m.vehicle.soc).toBeNull();expect(m.vehicle.socDetail).toMatch(/no valid reading/);
  });
  it('does not present HA state writes or restored readings as vehicle report time', () => {
    const now=Date.now(), raw=fixture();raw.generated_at=new Date(now).toISOString();raw.soc={...raw.soc,value:44,age_s:10,source:'vehicle',estimated:false};
    raw.soc_observation={time_basis:'last_updated',restored:false,integration:'other',raw_value:44,raw_age_s:10,raw_time_basis:'last_updated',raw_source:'vehicle'};
    let m=dashboardAdapter(raw,status,now,now).model;expect(m.vehicle.stale).toBe(true);expect(m.vehicle.socDetail).toMatch(/Vehicle report time unavailable; HA state updated 10 s ago/);
    raw.soc_observation={...raw.soc_observation,time_basis:'anchor',restored:true};raw.soc.age_s=3600;
    m=dashboardAdapter(raw,status,now,now).model;expect(m.vehicle.soc).toBe(44);expect(m.vehicle.socDetail).toMatch(/Restored reading; not a new vehicle report/);expect(m.vehicle.socDetail).not.toMatch(/HA state updated/);
    raw.soc.source='charger';raw.soc_observation={...raw.soc_observation,time_basis:'last_updated',restored:false,integration:'ocpp'};raw.soc.age_s=10;
    m=dashboardAdapter(raw,status,now,now).model;expect(m.vehicle.socDetail).toMatch(/Charger.*ocpp/);expect(m.vehicle.stale).toBe(false);
  });
  it('mounts shared UI, ignores old responses on switch and never sends writes', async () => {
    const a=fixture(), b=fixture(); a.generated_at=b.generated_at=new Date().toISOString();
    a.charger.charger_id='a'; b.charger.charger_id='b';
    let resolveA; const calls=[];
    const hass={connected:true,user:{is_admin:false},callWS:vi.fn(msg=>{calls.push(msg); if(msg.type==='spotnav/list_chargers') return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}]}); if(msg.type==='spotnav/get_dashboard') return msg.charger_id==='a' ? new Promise(r=>resolveA=r) : Promise.resolve(b); return Promise.resolve(status);})};
    const panel=document.createElement('spotnav-enhanced-panel'); panel.hass=hass; document.body.append(panel); await tick();
    const select=panel.shadowRoot.querySelector('#charger'); select.value='a'; select.dispatchEvent(new Event('change')); select.value='b'; select.dispatchEvent(new Event('change')); await tick();
    expect(panel.shadowRoot.querySelector('.shell')).not.toBeNull();
    expect(panel.shadowRoot.textContent).toContain('Price chart unavailable');
    expect(panel.shadowRoot.textContent).not.toContain('SAMPLE DATA');
    resolveA(a); await tick(); expect(select.value).toBe('b');
    panel.hass={...hass,connected:false}; expect(panel.shadowRoot.textContent).toContain('disconnected');
    panel.hass=hass; await tick(); expect(panel.shadowRoot.querySelector('.shell')).not.toBeNull();
    panel.remove();
    expect(calls.every(m=>m.type==='spotnav/list_chargers'||m.type==='spotnav/get_dashboard'||m.type==='spotnav/get_settings'||(m.type==='spotnav/morek_schedule' && m.action==='status'))).toBe(true);
  });
  it('rejects an old charger status after switching', async () => {
    const a=fixture(), b=fixture(); a.generated_at=b.generated_at=new Date().toISOString();
    a.charger.charger_id='a'; b.charger.charger_id='b'; let finish;
    const hass={connected:true,callWS:msg=>{
      if(msg.type==='spotnav/list_chargers') return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}]});
      if(msg.type==='spotnav/get_dashboard') return Promise.resolve(msg.charger_id==='a' ? a : b);
      return msg.charger_id==='a' ? new Promise(r=>finish=r) : Promise.resolve(status);
    }};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    select.value='b';select.dispatchEvent(new Event('change'));await tick();
    finish({api_version:1,schedule:{...status.schedule,supported:true,operator:{state:'mismatch'}}});await tick();
    expect(panel.shadowRoot.textContent).toContain('identity unsupported');
    expect(panel.shadowRoot.textContent).not.toContain('mismatch the sent');
    panel.remove();
  });
  it('refreshes independently, coalesces pending reads, and stops after teardown', async () => {
    vi.useFakeTimers();
    try {
      const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
      const calls=[];
      const hass={connected:true,callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);return new Promise(()=>{});}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
      const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
      expect(panel.shadowRoot.querySelector('.shell')).not.toBeNull();
      panel.refresh();panel.refresh();await tick();
      expect(calls.filter(m=>m.type==='spotnav/morek_schedule')).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(30000);await tick();
      expect(calls.filter(m=>m.type==='spotnav/get_dashboard').length).toBeGreaterThan(1);
      // A timed-out callWS cannot be cancelled; no further status call is
      // issued until the underlying request settles or the session changes.
      expect(calls.filter(m=>m.type==='spotnav/morek_schedule').length).toBe(1);
      panel.remove();const count=calls.length;await vi.advanceTimersByTimeAsync(90000);await tick();expect(calls).toHaveLength(count);
      expect(calls.every(m=>m.type==='spotnav/list_chargers'||m.type==='spotnav/get_dashboard'||m.type==='spotnav/get_settings'||(m.type==='spotnav/morek_schedule'&&m.action==='status'))).toBe(true);
    } finally { vi.useRealTimers(); }
  });
  it('retains the open dialog and immediately publishes critical status', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const hass={connected:true,callWS:msg=>Promise.resolve(msg.type==='spotnav/list_chargers' ? {api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]} : msg.type==='spotnav/get_dashboard' ? raw : status)};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const dialog=panel.shadowRoot.querySelector('#plan-dialog');dialog.setAttribute('open','');
    const mismatch={api_version:1,schedule:{...status.schedule,supported:true,operator:{state:'mismatch'}}};
    panel.view.update(dashboardAdapter(raw,mismatch,Date.now()));
    expect(panel.shadowRoot.querySelector('#plan-dialog')).toBe(dialog);
    expect(dialog.textContent).toContain('mismatch');
    dialog.removeAttribute('open');dialog.dispatchEvent(new Event('close'));panel.remove();
  });
  it('saves an actual edited plan with its canonical revision and no profile action', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const calls=[]; const initial=record();
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(initial));if(msg.type==='spotnav/update_settings')return Promise.resolve(envelope({...msg.settings,revision:8}));return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const input=panel.shadowRoot.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));
    const update=dashboardAdapter(raw,{api_version:1,schedule:{...status.schedule,supported:true,operator:{state:'mismatch'}}},Date.now());
    update.model.vehicle.status='Updated connection';
    update.model.settingsEditor=true;update.model.canSave=true;update.model.policySupported=true;Object.assign(update.model.settings,{driver:initial.driver,energy:initial.requested_kwh,vehicleId:''});update.actions={save:v=>panel.savePlan(v)};
    panel.view.update(update);
    expect(panel.shadowRoot.querySelector('[data-setting="target"]')).toBe(input);expect(input.value).toBe('85');expect(panel.shadowRoot.querySelector('#critical-live').textContent).toContain('mismatch');expect(panel.shadowRoot.querySelector('.status-line').textContent).toContain('Updated connection');
    panel.shadowRoot.querySelector('#save-plan').click();await tick();
    const writes=calls.filter(m=>m.type==='spotnav/update_settings');expect(writes).toHaveLength(1);expect(writes[0].expected_revision).toBe(7);expect(writes[0].settings.target.target_percent).toBe(85);
    expect(panel.shadowRoot.textContent).toContain('Saved and confirmed.');
    expect(calls.filter(m=>m.type==='spotnav/morek_schedule' && m.action!=='status')).toHaveLength(0);panel.remove();
  });
  it('allows only an explicit administrator Morek refresh and blocks non-admin dispatch', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const morek={api_version:1,schedule:{...status.schedule,supported:true}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));return Promise.resolve(morek);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    expect(calls.filter(m=>m.action==='fetch')).toHaveLength(0);
    const button=[...panel.shadowRoot.querySelectorAll('#morek-debug button')].find(b=>b.textContent==='Refresh from Morek');expect(button).toBeTruthy();button.focus();panel.rawStatus={api_version:1,schedule:{...morek.schedule,verification:{reason:'limits_or_transitions_differ'}}};panel.paint();expect([...panel.shadowRoot.querySelectorAll('#morek-debug button')].find(b=>b.textContent==='Refresh from Morek')).toBe(button);expect(panel.shadowRoot.activeElement).toBe(button);button.click();await tick();
    expect(calls.filter(m=>m.action==='fetch')).toHaveLength(1);
    panel.hass={...hass,user:{is_admin:false}};await panel.morekAction('fetch');expect(calls.filter(m=>m.action==='fetch')).toHaveLength(1);
    panel.remove();
  });
  it('refuses invalid and non-admin saves, and retains a conflicting draft', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];let conflict=false;
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return Promise.resolve(envelope({...record(),revision:8},false,conflict?'revision_conflict':'invalid_price_policy'));return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const input=panel.shadowRoot.querySelector('[data-setting="target"]');input.value='999';input.dispatchEvent(new Event('input',{bubbles:true}));panel.shadowRoot.querySelector('#save-plan').click();await tick();
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);
    input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));panel.hass={...hass,user:{is_admin:false}};await panel.savePlan({target:'85'});expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(0);
    panel.hass=hass;const values={target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};
    await panel.savePlan(values);await tick();expect(panel.shadowRoot.textContent).toContain('Settings save rejected.');
    conflict=true;await panel.savePlan(values);await tick();
    expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(2);expect(panel.shadowRoot.textContent).toContain('Settings conflict');expect(input.value).toBe('85');expect(panel.shadowRoot.querySelector('#save-plan').disabled).toBe(true);
    panel.remove();
  });
  it('does not apply a late save response to a different charger', async () => {
    const a=fixture(),b=fixture();a.generated_at=b.generated_at=new Date().toISOString();a.charger.charger_id='a';b.charger.charger_id='b';let finish;
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(msg.charger_id==='a'?a:b);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const pending=panel.savePlan({target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'});await tick();
    select.value='b';select.dispatchEvent(new Event('change'));await tick();finish(envelope({...record(),revision:8}));await pending;await tick();
    expect(panel.charger).toBe('b');expect(panel.settingsRecord.revision).toBe(7);expect(panel.shadowRoot.textContent).not.toContain('Saved and confirmed.');panel.remove();
  });
  it('does not apply a late settings answer after administrator access changes', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const pending=panel.savePlan({target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'});await tick();
    panel.hass={...hass,user:{is_admin:false}};finish(envelope({...record(),revision:8}));await pending;await tick();
    expect(panel.settingsConflict).toBe(true);expect(panel.settingsRecord.revision).toBe(7);expect(panel.shadowRoot.textContent).not.toContain('Saved and confirmed.');panel.remove();
  });
  it('requires admin, current preview and confirmation before mocked send or selective clear', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:new Date().toISOString(),expires_at:null};
    const morek={api_version:1,schedule:{...status.schedule,supported:true,cleanup_supported:true,preview:{calculated_at:new Date().toISOString(),reason:null,preview_id:'preview-1',profile:{chargingProfileId:42001,chargingSchedule:{startSchedule:new Date().toISOString(),chargingSchedulePeriod:[{startPeriod:0,limit:0}]}}}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));return Promise.resolve(morek);}};
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const button=name=>[...panel.shadowRoot.querySelectorAll('#morek-debug button')].find(b=>b.textContent===name);
    button('Send current plan').click();await tick();expect(calls.filter(m=>m.action==='send')).toHaveLength(0);expect(confirm).toHaveBeenCalledTimes(1);
    confirm.mockReturnValue(true);button('Send current plan').click();await tick();expect(calls.filter(m=>m.action==='send')[0].preview_id).toBe('preview-1');expect(confirm).toHaveBeenCalledTimes(2);
    button('Remove SpotNav schedule').click();await tick();expect(calls.filter(m=>m.action==='clear')[0].confirm_profile_id).toBe(42001);expect(confirm).toHaveBeenCalledTimes(3);
    panel.rawStatus={api_version:1,schedule:{...morek.schedule,outcomes:{uncertain:true}}};panel.statusAt=Date.now();await panel.morekAction('send');expect(calls.filter(m=>m.action==='send')).toHaveLength(1);
    panel.rawStatus=morek;panel.statusAt=Date.now();confirm.mockImplementation(()=>{panel.hass={...hass,user:{is_admin:false}};return true;});
    await panel.morekAction('send');expect(calls.filter(m=>m.action==='send')).toHaveLength(1);
    panel.hass=hass;panel.rawStatus=morek;panel.statusAt=Date.now();confirm.mockImplementation(()=>{panel.rawStatus={api_version:1,schedule:{...morek.schedule,preview:{...morek.schedule.preview,preview_id:'changed'}}};return true;});
    await panel.morekAction('send');expect(calls.filter(m=>m.action==='send')).toHaveLength(1);
    panel.remove();confirm.mockRestore();
  });
  it('only pauses or resumes through an explicitly admitted automatic action', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const hass={connected:true,user:{is_admin:false},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:true,error:null,action:msg.action,choice:msg.choice ?? null});return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);
    panel.shadowRoot.querySelector('#pause-auto').click();await tick();expect(calls.filter(m=>m.type==='spotnav/manual_action')[0]).toMatchObject({action:'stop',choice:'until_resumed'});
    await panel.automaticAction('resume',null);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);
    raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:new Date().toISOString(),expires_at:null};panel.refresh();await tick();
    panel.shadowRoot.querySelector('#resume-auto').click();await tick();expect(calls.filter(m=>m.type==='spotnav/manual_action')[1]).toMatchObject({action:'resume'});
    panel.remove();
  });
  it('treats a timed-out mocked upload as unknown and refuses another send', async () => {
    vi.useFakeTimers();const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    try {
      const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:new Date().toISOString(),expires_at:null};const calls=[];
      const morek={api_version:1,schedule:{...status.schedule,supported:true,preview:{calculated_at:new Date().toISOString(),reason:null,preview_id:'p',profile:{chargingProfileId:42001,chargingSchedule:{startSchedule:new Date().toISOString(),chargingSchedulePeriod:[{startPeriod:0,limit:0}]}}}}};
      const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.action==='send')return new Promise(()=>{});return Promise.resolve(morek);}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
      const operation=panel.morekAction('send');await vi.advanceTimersByTimeAsync(10001);await operation;await tick();expect(panel.morekUncertain).toBe(true);expect(panel.morekError).toMatch(/unknown/i);
      await panel.morekAction('send');expect(calls.filter(m=>m.action==='send')).toHaveLength(1);panel.remove();
    } finally {confirm.mockRestore();vi.useRealTimers();}
  });
  it('bounds a stalled settings write, preserves its draft, and never retries before settlement', async () => {
    vi.useFakeTimers();const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    try {
      const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;const calls=[];
      const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
      const input=panel.shadowRoot.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));panel.shadowRoot.querySelector('#save-plan').click();await tick();
      await vi.advanceTimersByTimeAsync(10001);await tick();expect(panel.settingsBusy).toBe(false);expect(panel.settingsConflict).toBe(true);expect(input.value).toBe('85');expect(panel.settingsNotice).toMatch(/may still complete/);
      panel.reloadSettings();await tick();expect(confirm).not.toHaveBeenCalled();expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(1);
      finish(envelope({...record(),revision:8}));await tick();expect(panel.settingsRecord.revision).toBe(7);expect(panel.settingsConflict).toBe(true);
      panel.reloadSettings();await tick();expect(confirm).toHaveBeenCalledTimes(1);expect(panel.settingsConflict).toBe(false);panel.remove();
    } finally {confirm.mockRestore();vi.useRealTimers();}
  });
  it('does not overlap a pending status read after an explicit action', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;const calls=[];let reads=0;
    const morek={api_version:1,schedule:{...status.schedule,supported:true}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.action==='status' && ++reads===2)return new Promise(r=>finish=r);return Promise.resolve(morek);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    panel.refresh();await tick();expect(reads).toBe(2);await panel.morekAction('fetch');await tick();expect(reads).toBe(2);
    finish({api_version:1,schedule:{...morek.schedule,operator:{state:'mismatch'}}});await tick();expect(reads).toBe(3);expect(panel.rawStatus.schedule.operator?.state).not.toBe('mismatch');panel.remove();
  });
  it.each(['malformed','reconcile'])('fails closed for %s settings responses', async mode => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return Promise.resolve(mode==='malformed'?{}:envelope({...record(),revision:8},false,'spotnav_settings_reconcile_failed'));return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const values={target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};await panel.savePlan(values);await tick();expect(panel.settingsConflict).toBe(true);await panel.savePlan(values);expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(1);panel.remove();
  });
  it('refuses automatic action from stale dashboard and coalesces double invocation', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    raw.generated_at='2000-01-01T00:00:00Z';await panel.automaticAction('stop','until_resumed');expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(0);
    raw.generated_at=new Date().toISOString();const first=panel.automaticAction('stop','until_resumed');await panel.automaticAction('stop','until_resumed');expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);
    finish({api_version:1,ok:false,error:'spotnav_action_failed',action:'stop',choice:'until_resumed'});await first;expect(panel.autoNotice).toMatch(/action failed/i);panel.remove();
  });
  it.each(['stop','resume'])('confirms %s only from a matching post-dispatch observation', async action => {
    vi.useFakeTimers();
    try {
      const raw=fixture();raw.generated_at=new Date(Date.now()-1000).toISOString();raw.charger.charger_id='a';
      if(action==='resume'){raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:raw.generated_at,expires_at:null};}
      const choice=action==='stop'?'until_resumed':null;
      const hass={connected:true,user:{is_admin:true},callWS:msg=>{if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:true,error:null,action,choice});return Promise.resolve(status);}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
      await panel.automaticAction(action,choice);await tick();expect(panel.autoNotice).toMatch(/waiting/i);
      raw.control.automatic_action=action==='stop'?'resume':'pause';raw.control.pause_choices=action==='stop'?[]:['until_resumed'];raw.control.pause_blocks_execution=action==='stop';raw.control.pause={choice,admitted_at:choice?new Date().toISOString():null,expires_at:null};panel.refresh();await tick();expect(panel.autoNotice).toMatch(/waiting/i);
      raw.generated_at=new Date().toISOString();panel.refresh();await tick();expect(panel.autoNotice).toMatch(/confirmed by a fresh/i);panel.remove();
    } finally {vi.useRealTimers();}
  });
  it('keeps an unknown settings outcome across disconnect until the old request settles and is reloaded', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const pending=panel.savePlan({target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'});panel.hass={...hass,connected:false};await pending;await tick();panel.hass=hass;await tick();expect(panel.settingsConflict).toBe(true);
    finish(envelope({...record(),revision:8}));await tick();expect(panel.settingsConflict).toBe(true);expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(1);panel.remove();
  });
  it.each(['identity','dashboard','status','charger'])('refuses send if %s changes during confirmation', async change => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:new Date().toISOString(),expires_at:null};const calls=[];
    const morek={api_version:1,schedule:{...status.schedule,supported:true,configured_id:'a',resolved_id:'b',preview:{calculated_at:new Date().toISOString(),reason:null,preview_id:'p',profile:{chargingProfileId:42001,chargingSchedule:{startSchedule:new Date().toISOString(),chargingSchedulePeriod:[{startPeriod:0,limit:0}]}}}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));return Promise.resolve(morek);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const confirm=vi.spyOn(window,'confirm').mockImplementation(()=>{if(change==='identity')panel.rawStatus.schedule.resolved_id='other';if(change==='dashboard')panel.rawDashboard={...raw};if(change==='status')panel.rawStatus={...morek};if(change==='charger')panel.charger='other';return true;});
    await panel.morekAction('send');expect(calls.filter(m=>m.action==='send')).toHaveLength(0);expect(confirm).toHaveBeenCalledTimes(1);panel.remove();confirm.mockRestore();
  });
  it('keeps a torn-down save unknown on reopening until settlement and explicit reload', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const values={target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};
    const pending=panel.savePlan(values);await tick();panel.remove();await pending;document.body.append(panel);await tick();
    expect(panel.settingsConflict).toBe(true);expect(panel.settingsNotice).toMatch(/unknown/i);panel.reloadSettings();await panel.savePlan(values);expect(confirm).not.toHaveBeenCalled();expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(1);
    finish(envelope({...record(),revision:8}));await tick();expect(panel.settingsRecord.revision).toBe(7);expect(panel.shadowRoot.textContent).not.toContain('Saved and confirmed.');expect(panel.settingsConflict).toBe(true);
    panel.reloadSettings();await tick();expect(confirm).toHaveBeenCalledTimes(1);expect(panel.settingsConflict).toBe(false);panel.remove();confirm.mockRestore();
  });
  it('does not allow a new panel to retry a save still pending from a destroyed panel', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='replacement-test';let finish;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'replacement-test',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/update_settings')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const first=document.createElement('spotnav-enhanced-panel');first.hass=hass;document.body.append(first);await tick();let select=first.shadowRoot.querySelector('#charger');select.value='replacement-test';select.dispatchEvent(new Event('change'));await tick();
    const values={target:'85',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30'};const pending=first.savePlan(values);first.remove();await pending;
    const second=document.createElement('spotnav-enhanced-panel');second.hass=hass;document.body.append(second);await tick();select=second.shadowRoot.querySelector('#charger');select.value='replacement-test';select.dispatchEvent(new Event('change'));await tick();expect(second.settingsConflict).toBe(true);await second.savePlan(values);expect(calls.filter(m=>m.type==='spotnav/update_settings')).toHaveLength(1);
    finish(envelope({...record(),revision:8}));await tick();expect(second.settingsConflict).toBe(true);expect(second.shadowRoot.textContent).not.toContain('Saved and confirmed.');second.remove();
  });
  it.each([
    ['resume_unavailable', /blocked.*resume_unavailable/i, false],
    ['legacy_execution_ownership_blocked', /Resume was refused before taking effect.*legacy_execution_ownership_blocked/i, false],
    ['spotnav_action_reconcile_failed', /recorded.*follow-up failed.*spotnav_action_reconcile_failed/i, false],
    ['spotnav_action_outcome_unknown', /outcome is unknown.*spotnav_action_outcome_unknown/i, true],
  ])('reports Resume result %s without guessing', async (code, message, uncertain) => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:raw.generated_at,expires_at:null};raw.control.execution_error='pause_stop_failed';const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:false,error:code,action:null,choice:null});return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    expect(panel.shadowRoot.querySelector('#pause-state').textContent).toMatch(/stop request failed.*physical charging state unknown/i);
    await panel.automaticAction('resume',null);await tick();expect(panel.autoNotice).toMatch(message);expect(!!panel.autoUncertain).toBe(uncertain);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);expect(calls.filter(m=>m.type==='spotnav/get_dashboard').length).toBeGreaterThan(1);panel.remove();
  });
  it('explains fresh admission evidence without retrying Resume', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:raw.generated_at,expires_at:null};const calls=[];
    const evidence={api_version:1,schedule:{...status.schedule,ownership:{record_state:'missing',legacy_admission:{allowed:false,reason:'lifecycle_initializing'}}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:false,error:'legacy_execution_ownership_blocked',action:null,choice:null});return Promise.resolve(evidence);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await panel.automaticAction('resume',null);await tick();
    expect(panel.shadowRoot.querySelector('#pause-notice').textContent).toMatch(/lifecycle barrier.*ownership record is missing.*Automatic clean initialization/i);expect(!!panel.autoUncertain).toBe(false);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);expect(calls.filter(m=>m.type==='spotnav/morek_schedule' && m.action!=='status')).toHaveLength(0);panel.remove();
  });
  it.each(['stop','resume'])('does not retry timed-out %s or accept stale confirmation', async action => {
    vi.useFakeTimers();try {
      const raw=fixture();raw.generated_at=new Date(Date.now()-1000).toISOString();raw.charger.charger_id='a';if(action==='resume'){raw.control.automatic_action='resume';raw.control.pause_choices=[];raw.control.pause_blocks_execution=true;raw.control.pause={choice:'until_resumed',admitted_at:raw.generated_at,expires_at:null};}let finish;const calls=[];
      const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return new Promise(r=>finish=r);return Promise.resolve(status);}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
      const choice=action==='stop'?'until_resumed':null;const pending=panel.automaticAction(action,choice);await vi.advanceTimersByTimeAsync(10001);await pending;expect(panel.autoNotice).toMatch(/unknown/i);await panel.automaticAction(action,choice);expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);
      finish({api_version:1,ok:true,error:null,action,choice});await tick();expect(panel.autoNotice).not.toMatch(/confirmed/i);panel.remove();
    } finally {vi.useRealTimers();}
  });
  it.each(['permission','charger'])('ignores pending automatic action after %s changes', async change => {
    const a=fixture(),b=fixture();a.generated_at=b.generated_at=new Date().toISOString();a.charger.charger_id='a';b.charger.charger_id='b';let finish;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(msg.charger_id==='a'?a:b);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.type==='spotnav/manual_action')return new Promise(r=>finish=r);return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();const pending=panel.automaticAction('stop','until_resumed');
    if(change==='permission')panel.hass={...hass,user:{is_admin:false}};else {select.value='b';select.dispatchEvent(new Event('change'));}await tick();finish({api_version:1,ok:true,error:null,action:'stop',choice:'until_resumed'});await pending;await tick();expect(panel.autoNotice).not.toMatch(/confirmed/i);expect(panel.autoExpected).toBeNull();expect(calls.filter(m=>m.type==='spotnav/manual_action')).toHaveLength(1);panel.remove();
  });
  it.each(['identity','permission','unsupported'])('refuses selective clear when %s changes at confirmation', async change => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];const morek={api_version:1,schedule:{...status.schedule,supported:true,cleanup_supported:true,configured_id:'a',resolved_id:'b'}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));return Promise.resolve(morek);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const confirm=vi.spyOn(window,'confirm').mockImplementation(()=>{if(change==='identity')panel.rawStatus.schedule.resolved_id='other';if(change==='permission')panel.hass={...hass,user:{is_admin:false}};if(change==='unsupported')panel.rawStatus.schedule.cleanup_supported=false;return true;});await panel.morekAction('clear');expect(confirm).toHaveBeenCalledTimes(1);expect(calls.filter(m=>m.action==='clear')).toHaveLength(0);panel.remove();confirm.mockRestore();
  });
  it('reports unknown selective clear after timeout without retry or removal claim', async () => {
    vi.useFakeTimers();const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);try {
      const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];let finish;const morek={api_version:1,schedule:{...status.schedule,supported:true,cleanup_supported:true}};
      const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.action==='clear')return new Promise(r=>finish=r);return Promise.resolve(morek);}};
      const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();const pending=panel.morekAction('clear');await vi.advanceTimersByTimeAsync(10001);await pending;expect(panel.morekError).toMatch(/unknown/i);expect(calls.filter(m=>m.action==='clear')).toHaveLength(1);expect(calls.find(m=>m.action==='clear').confirm_profile_id).toBe(42001);finish(morek);await tick();expect(panel.morekError).toMatch(/unknown/i);panel.remove();
    } finally {confirm.mockRestore();vi.useRealTimers();}
  });
  it('shows backend refusal of selective clear without claiming removal', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';const calls=[];const morek={api_version:1,schedule:{...status.schedule,supported:true,cleanup_supported:true}};
    const refused={api_version:1,schedule:{...morek.schedule,cleanup:{requested_at:new Date().toISOString(),profile_id:42001,status:'Rejected'}}};
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));if(msg.action==='clear')return Promise.resolve(refused);return Promise.resolve(morek);}};
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await panel.morekAction('clear');
    expect(calls.filter(m=>m.action==='clear')).toHaveLength(1);expect(calls.find(m=>m.action==='clear').confirm_profile_id).toBe(42001);expect(panel.shadowRoot.textContent).toMatch(/Rejected/);expect(panel.shadowRoot.textContent).not.toMatch(/successfully removed/i);panel.remove();confirm.mockRestore();
  });
  it('waits for a superseded dashboard read to settle before permission-change refresh', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';let finish, reads=0;const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard'){if(++reads===2)return new Promise(r=>finish=r);return Promise.resolve(raw);}if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));return Promise.resolve(status);}};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    panel.refresh();await tick();expect(reads).toBe(2);panel.hass={...hass,user:{is_admin:false}};await tick();expect(reads).toBe(2);expect(panel.controlPermissionPending).toBe(true);
    finish({...raw,generated_at:'2000-01-01T00:00:00Z'});await tick();expect(reads).toBe(3);expect(panel.controlPermissionPending).toBe(false);expect(panel.rawDashboard.generated_at).toBe(raw.generated_at);panel.remove();
  });
});
