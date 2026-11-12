// @vitest-environment jsdom
// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import '../sidebar/panel.js';

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
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };

describe('actual sidebar read-only host', () => {
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
    expect(adapter.model.windows[0].cost).toBeUndefined();
    expect(dashboardAdapter({...raw,api_version:99},status,Date.now())).toBeNull();
    raw.generated_at='2000-01-01T00:00:00Z';
    expect(dashboardAdapter(raw,status,Date.now()).model.windows).toBeNull();
    const mismatch={api_version:1,schedule:{...status.schedule,supported:true,operator:{state:'mismatch'},outcomes:{uncertain:true}}};
    const warning=dashboardAdapter(raw,mismatch,Date.now()).model.warning;
    expect(warning.detail).toMatch(/may have applied/i);
    expect(warning.detail).toMatch(/mismatch/i);
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
    expect(calls.every(m=>m.type==='spotnav/list_chargers'||m.type==='spotnav/get_dashboard'||(m.type==='spotnav/morek_schedule' && m.action==='status'))).toBe(true);
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
});
