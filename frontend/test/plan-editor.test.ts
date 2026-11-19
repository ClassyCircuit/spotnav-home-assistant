// @vitest-environment jsdom
// @ts-nocheck
// 20.6: strategy summary and plan editor (presentation + role gating over the existing host controller).
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
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
const record = (over={}) => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:'vehicle_ev6',target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40,time_reserve_percent:10,...over});
const envelope = (settings,ok=true,error=null) => ({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
beforeEach(()=>sessionStorage.clear());

async function open({admin=true,usersChange=true,saved=record(),update,sole=false}={}) {
  const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';raw.settings.users_change_plan=usersChange;
  if (sole) {raw.soc.vehicles=[];raw.vehicle_choices=[{id:'vehicle_ev6',name:'Vehicle'}];raw.settings.vehicle_ids=null;}
  const calls=[];let store=saved;
  const hass={connected:true,user:{is_admin:admin},callWS:msg=>{calls.push(msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);
    if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope(store));
    if(msg.type==='spotnav/update_settings'){if(update)return Promise.resolve(update(msg));store={...msg.settings,revision:msg.expected_revision+1};return Promise.resolve(envelope(store));}
    return Promise.resolve(status);}};
  const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  return {panel,hass,calls,root:panel.shadowRoot,raw,setStore:v=>{store=v;}};
}
const q=(root,s)=>root.querySelector(s);
const updates=calls=>calls.filter(m=>m.type==='spotnav/update_settings');
const edit=(el,v)=>{el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
const full=(over={})=>({driver:'target_soc',energy:'20',vehicleId:'vehicle_ev6',target:'80',minimum:'40',cap:'0.1',capEnabled:true,capBasis:'nord_pool',deadlineEnabled:true,readyBy:'06:30',reserve:'10',...over});

describe('strategy summary and grouped editor (admin)', () => {
  it('shows the saved plan as chips, tiles and three labelled groups with every field enabled', async () => {
    const {panel,root}=await open();
    expect(q(root,'.strategy-summary').dataset.state).toBe('saved');
    expect(q(root,'[data-chip="state"]').textContent).toBe('Saved plan');
    expect(q(root,'[data-chip="mode"]').textContent).toBe('Charge to target SOC');
    expect(q(root,'[data-chip="role"]')).toBeNull();
    expect(q(root,'[data-fact="target"] b').textContent).toBe('80%');
    expect(q(root,'[data-fact="minimum"] b').textContent).toBe('40%');
    expect(q(root,'[data-fact="reserve"] b').textContent).toContain('10%');
    expect(q(root,'[data-fact="cap"] b').textContent).toContain('Nord Pool');
    expect([...root.querySelectorAll('.plan-group')].map(g=>g.dataset.group)).toEqual(['goal','price','timing']);
    for (const key of ['driver','vehicleId','target','minimum','cap','capEnabled','capBasis','deadlineEnabled','readyBy','reserve']) expect(q(root,`[data-setting="${key}"]`).hasAttribute('disabled')).toBe(false);
    expect(root.querySelectorAll('.plan-admin-only')).toHaveLength(0);
    expect(q(root,'.plan-role-note')).toBeNull();
    expect(q(root,'[data-setting="soc"]')).toBeNull(); // no manual numeric SOC input
    panel.remove();
  });
  it('keeps energy mode honest: vehicle and minimum are not claimed as used', async () => {
    const {panel,root}=await open({saved:record({driver:'manual_kwh'})});
    expect(q(root,'[data-chip="mode"]').textContent).toBe('Charge requested energy');
    expect(q(root,'[data-fact="vehicle"] b').textContent).toMatch(/Not used/);
    expect(q(root,'[data-fact="energy"] b').textContent).toBe('20 kWh');
    expect(q(root,'[data-setting="target"]').parentElement.hidden).toBe(true);
    panel.remove();
  });
  it('labels a sole-vehicle default as proposed, not saved, and writes nothing on open', async () => {
    const {panel,root,calls}=await open({sole:true,saved:record({target:{vehicle_id:null,target_percent:80}})});
    expect(q(root,'.strategy-summary').dataset.state).toBe('proposed');
    expect(q(root,'[data-chip="state"]').textContent).toMatch(/Proposed defaults · not saved/);
    expect(q(root,'[data-fact="vehicle"] b').textContent).toBe('Vehicle');
    expect(updates(calls)).toHaveLength(0);
    q(root,'#save-plan').click();await tick();
    expect(updates(calls)).toHaveLength(1);expect(updates(calls)[0].expected_revision).toBe(7);
    await tick();expect(q(root,'[data-chip="state"]').textContent).toBe('Saved plan');
    panel.remove();
  });
});

describe('non-admin restrictions', () => {
  it('disables exactly the administrator-only fields and says why, leaving the permitted subset editable', async () => {
    const {panel,root}=await open({admin:false});
    for (const key of ['minimum','cap','capEnabled','capBasis','reserve']) expect(q(root,`[data-setting="${key}"]`).hasAttribute('disabled')).toBe(true);
    for (const key of ['driver','energy','vehicleId','target','deadlineEnabled','readyBy']) expect(q(root,`[data-setting="${key}"]`).hasAttribute('disabled')).toBe(false);
    expect(root.querySelectorAll('.plan-admin-only').length).toBeGreaterThanOrEqual(5);
    expect(q(root,'[data-chip="role"]').textContent).toMatch(/permissions/);
    expect(q(root,'.plan-role-note').textContent).toMatch(/administrator only/i);
    expect(q(root,'#save-plan').hasAttribute('disabled')).toBe(false);
    panel.remove();
  });
  it('without plan permission every field and Save are disabled and no role note claims otherwise', async () => {
    const {panel,root}=await open({admin:false,usersChange:false});
    for (const el of root.querySelectorAll('[data-setting]')) expect(el.hasAttribute('disabled')).toBe(true);
    expect(q(root,'#save-plan').hasAttribute('disabled')).toBe(true);
    expect(q(root,'#settings-notice').textContent).toMatch(/permission/);
    expect(q(root,'.plan-role-note')).toBeNull();
    panel.remove();
  });
  it('never sends a change to an administrator-only field, even from a stale draft, and keeps the revision check', async () => {
    const {panel,calls}=await open({admin:false});
    await panel.savePlan(full({target:'70',minimum:'10',cap:'0.5',capEnabled:false,capBasis:'configured_variable_cost',reserve:'40'}));await tick();
    const sent=updates(calls);expect(sent).toHaveLength(1);
    const s=sent[0].settings;
    expect(sent[0].expected_revision).toBe(7);
    expect(s.target.target_percent).toBe(70);
    expect(s.minimum_ready_by_soc).toBe(40);expect(s.soft_price_cap).toBe(0.1);expect(s.cap_price_basis).toBe('nord_pool');expect(s.time_reserve_percent).toBe(10);
    panel.remove();
  });
  it('a role change while editing disables the admin-only fields and saves only the permitted subset', async () => {
    const {panel,root,calls,hass}=await open({admin:true});
    edit(q(root,'[data-setting="cap"]'),'0.2');
    panel.hass={...hass,user:{is_admin:false}};await tick();await tick();
    const root2=panel.shadowRoot;
    expect(q(root2,'[data-setting="cap"]').hasAttribute('disabled')).toBe(true);
    expect(q(root2,'[data-setting="minimum"]').hasAttribute('disabled')).toBe(true);
    await panel.savePlan(full({target:'75',cap:'0.2'}));await tick();
    for (const u of updates(calls)) expect(u.settings.soft_price_cap).toBe(0.1);
    panel.remove();
  });
});

describe('save, conflict, reload and drafts', () => {
  it('a revision conflict keeps the draft, blocks Save and offers Reload, which fetches saved values and clears the conflict', async () => {
    const {panel,root,calls,setStore}=await open({update:()=>envelope(record(),false,'revision_conflict')});
    edit(q(root,'[data-setting="target"]'),'65');
    q(root,'#save-plan').click();await tick();
    expect(updates(calls)).toHaveLength(1);expect(updates(calls)[0].expected_revision).toBe(7);
    expect(q(root,'#settings-notice').textContent).toMatch(/conflict/i);
    expect(q(root,'[data-setting="target"]').value).toBe('65');
    expect(q(root,'#save-plan').hasAttribute('disabled')).toBe(true);
    expect(q(root,'#reload-settings')).not.toBeNull();
    setStore(record({revision:9,target:{vehicle_id:'vehicle_ev6',target_percent:90}}));
    window.confirm=()=>true; // the existing discard-draft confirmation
    q(root,'#reload-settings').click();await tick();await tick();
    expect(q(root,'[data-fact="target"] b').textContent).toBe('90%');
    expect(q(root,'#save-plan').hasAttribute('disabled')).toBe(false);
    panel.remove();
  });
  it('a re-render keeps a dirty draft in the form and leaves the saved summary alone', async () => {
    const {panel,root}=await open();
    edit(q(root,'[data-setting="target"]'),'55');
    panel.hass={...panel._hass};await tick();
    expect(q(panel.shadowRoot,'[data-setting="target"]').value).toBe('55');
    expect(q(panel.shadowRoot,'[data-fact="target"] b').textContent).toBe('80%');
    panel.remove();
  });
  it('rejects a minimum above the target before any write', async () => {
    const {panel,calls}=await open();
    await panel.savePlan(full({target:'30',minimum:'40'}));
    expect(updates(calls)).toHaveLength(0);expect(panel.settingsNotice).toMatch(/Minimum SOC/);panel.remove();
  });
});
