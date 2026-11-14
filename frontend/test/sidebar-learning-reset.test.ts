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

const RESET='Reset learned estimates';
const setup = (resetAnswer:any, opts:any={}) => {
  const calls:any[]=[];const a=fixture(),b=fixture();a.generated_at=b.generated_at=new Date().toISOString();a.charger.charger_id='a';b.charger.charger_id='b';
  const morek={api_version:1,schedule:{...status.schedule,supported:true}};
  const hass:any={connected:true,user:{is_admin:true},callWS:(msg:any)=>{calls.push(msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'},{charger_id:'b',charger_name:'B'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(msg.charger_id==='b'?b:a);
    if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(record()));
    if(msg.action==='reset_learning')return resetAnswer(msg);
    return Promise.resolve(morek);}};
  return {calls,hass};
};
const open = async (hass:any) => {
  const panel:any=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
  const button=()=>[...panel.shadowRoot.querySelectorAll('#morek-debug button')].find((x:any)=>x.textContent===RESET||x.textContent==='Resetting…') as any;
  return {panel,select,button};
};
const done={api_version:1,schedule:{learning_reset:{energy:true,power:true,replan:'requested'}}};

describe('sidebar learned-estimate reset (mocked)', () => {
  it('writes nothing on open and nothing without confirmation', async () => {
    const {calls,hass}=setup(()=>Promise.resolve(done));const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const {panel,button}=await open(hass);
    expect(calls.filter(m=>m.action==='reset_learning')).toHaveLength(0);
    button().click();await tick();
    expect(confirm).toHaveBeenCalled();expect(calls.filter(m=>m.action==='reset_learning')).toHaveLength(0);panel.remove();confirm.mockRestore();
  });
  it('offers no reset to a non-administrator', async () => {
    const {hass}=setup(()=>Promise.resolve(done));hass.user.is_admin=false;
    const {panel,button}=await open(hass);expect(button()).toBeUndefined();panel.remove();
  });
  it('shows the done notice once after one confirmed reset', async () => {
    const {calls,hass}=setup(()=>Promise.resolve(done));const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const {panel,button}=await open(hass);button().click();await tick();
    expect(calls.filter(m=>m.action==='reset_learning')).toHaveLength(1);
    expect(panel.shadowRoot.textContent).toContain('Learned estimates reset');panel.remove();confirm.mockRestore();
  });
  it('shows a partial or unconfirmed backend answer as it is', async () => {
    for (const [answer,text] of [[{api_version:1,schedule:{learning_reset:{energy:false,power:null,replan:'requested'}}},'could not be removed'],[{api_version:1,schedule:{}},'Reset not confirmed']] as const) {
      const {hass}=setup(()=>Promise.resolve(answer));const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
      const {panel,button}=await open(hass);button().click();await tick();
      expect(panel.shadowRoot.textContent).toContain(text);expect(panel.shadowRoot.textContent).not.toContain('Learned estimates reset;');panel.remove();confirm.mockRestore();
    }
  });
  it('ignores a late answer from the old charger after another is selected', async () => {
    let finish:any;const {calls,hass}=setup(()=>new Promise(r=>{finish=r;}));const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const {panel,select,button}=await open(hass);button().click();await tick();
    select.value='b';select.dispatchEvent(new Event('change'));await tick();
    finish(done);await tick();
    expect(panel.charger).toBe('b');expect(panel.learningNotice).toBeFalsy();expect(panel.shadowRoot.textContent).not.toContain('Learned estimates reset');
    expect(calls.filter(m=>m.action==='reset_learning')).toHaveLength(1);panel.remove();confirm.mockRestore();
  });
  it('ignores an answer after the permission changed, and after disconnect', async () => {
    let finish:any;const {hass}=setup(()=>new Promise(r=>{finish=r;}));const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const {panel,button}=await open(hass);button().click();await tick();
    panel.hass={...hass,user:{is_admin:false}};finish(done);await tick();
    expect(panel.learningNotice).toBeFalsy();expect(panel.shadowRoot.textContent).not.toContain('Learned estimates reset');
    panel.remove();finish(done);await tick();expect(panel.learningNotice).toBeFalsy();confirm.mockRestore();
  });
  it('an out-of-order failure from the old charger is not shown on the new one', async () => {
    let fail:any;const {hass}=setup(()=>new Promise((_,r)=>{fail=r;}));const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const {panel,select,button}=await open(hass);button().click();await tick();
    select.value='b';select.dispatchEvent(new Event('change'));await tick();fail(new Error('late'));await tick();
    expect(panel.learningNotice).toBeFalsy();panel.remove();confirm.mockRestore();
  });
});
