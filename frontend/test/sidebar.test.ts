// @vitest-environment jsdom
// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { renderBattery } from '../shared-dashboard/vehicle-view.js';
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
const record = () => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40});
const envelope = (settings,ok=true,error=null) => ({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };

describe('actual sidebar read-only host', () => {
  it('keeps schedule-owned controls unarmed and reports intent separately from flow', async () => {
    const raw=fixture();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
    const owned={api_version:1,schedule:{...status.schedule,supported:true,ownership:{recorded_owner:'morek_schedule'},schedule_pause:{intent:'pause_until_resumed',request:'uncertain',ack:null,readback:'unverified',measured:'unknown'}}};
    const calls=[];
    const hass={connected:true,user:{is_admin:true},callWS:vi.fn(msg=>{calls.push(msg);if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);return Promise.resolve(owned);})};
    const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
    const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();
    const root=panel.shadowRoot;
    expect(root.querySelector('#pause-state').textContent).toMatch(/Pause requested.*uncertain.*physical charging unknown.*unarmed/);
    expect(root.querySelector('#pause-auto').disabled).toBe(true);
    expect(root.querySelector('#resume-auto').disabled).toBe(true);
    panel.rawStatus={...owned,schedule:{...owned.schedule,schedule_pause:{intent:'resume_requested',request:'accepted',ack:'Accepted',readback:'bounded_match',measured:'unknown'}}};panel.paint();
    expect(root.querySelector('#pause-state').textContent).toMatch(/Resume requested; retained limit may remain.*Accepted.*bounded effective readback match.*physical charging unknown/);
    await panel.automaticAction('stop','until_resumed');
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
    expect(adapter.model.windows[0].cost).toBeUndefined();
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
    update.model.settingsEditor=true;update.model.canSave=true;update.model.targetSupported=true;update.model.policySupported=true;update.actions={save:v=>panel.savePlan(v)};
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
    finish({api_version:1,ok:false,error:'spotnav_action_failed',action:'stop',choice:'until_resumed'});await first;expect(panel.autoNotice).toMatch(/rejected/i);panel.remove();
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
