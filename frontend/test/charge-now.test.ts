// @vitest-environment jsdom
// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';
import { chargeNowSelection } from '../sidebar/charge-now.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
const tick=async()=>{for(let i=0;i<30;i++) await Promise.resolve();};
const record=()=>({revision:7,area_id:'SE4',overrides:[],phases:3,amps:16,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40});
const envelope=()=>({api_version:1,ok:true,error:null,settings:record(),pause:{choice:null,admitted_at:null,expires_at:null}});
const status=()=>({api_version:1,schedule:{supported:true,verified:false,sent:null,sent_at:null,ack:null,effective:null,
  outcomes:{uncertain:false},operator:{state:'ready'},ownership:{recorded_owner:'morek_schedule',completion_authorized:true},
  schedule_pause:{intent:'none',request:'none'},readiness:{session_start:{state:'waiting'}},reconciliation:{reason:'unchanged'},
  charge_now:{state:'inactive',intent:null,current_price:0.12,currency:'EUR',price_basis:'nord_pool',above_cap:true,uncertain:false}}});
async function setup({admin=true, reply}={}) {
  const raw=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
  raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
  let current=status();const calls=[];
  const hass={connected:true,user:{is_admin:admin},callWS:msg=>{calls.push(msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);
    if(msg.type==='spotnav/get_settings')return Promise.resolve(envelope());
    if(msg.type==='spotnav/morek_schedule' && msg.action==='status')return Promise.resolve(current);
    if(reply)return reply(msg);
    return Promise.resolve({api_version:1,schedule:{intent:msg.action==='charge_now'?{id:'new'}:null,reconciliation:'pending',outcome:'not_yet_confirmed'}});
  }};
  const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  return {panel,raw,calls,setStatus:value=>{current=value;panel.rawStatus=value;panel.statusAt=Date.now();panel.statusFailed=false;panel.paint();},
    refreshStatus:async value=>{current=value;panel.refresh();await tick();}};
}
beforeEach(()=>{sessionStorage.clear();vi.restoreAllMocks();});
// 20.3: confirmation is in-page. open() shows it; confirm() presses its button. window.confirm must never be used.
const open=async(root,sel='#charge-now')=>{root.querySelector(sel).click();await tick();};
const confirmText=root=>root.querySelector('#charge-confirm-text')?.textContent||'';
const confirm=async root=>{root.querySelector('#charge-confirm-ok').click();await tick();};
const go=async(root,sel)=>{await open(root,sel);await confirm(root);};

describe('Charge Now sidebar',()=>{
  it('starts with one-hour default and sends one request after one confirmation',async()=>{
    const {panel,calls}=await setup();const root=panel.shadowRoot;
    expect(root.querySelector('#charge-now').textContent).toBe('Charge Now');
    expect(root.querySelector('#charge-duration').value).toBe('60');
    const native=vi.spyOn(window,'confirm');
    await open(root);
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);
    const box=root.querySelector('#charge-confirm');expect(box.getAttribute('role')).toBe('alertdialog');expect(box.getAttribute('aria-labelledby')).toBe('charge-confirm-title');
    expect(confirmText(root)).toMatch(/overrides the price-based Auto plan.*0.12 EUR\/kWh.*exceeds your cap/i);
    expect(root.querySelector('#charge-now').disabled).toBe(true);
    const text=confirmText(root);await confirm(root);
    expect(native).not.toHaveBeenCalled();expect(root.querySelector('#charge-confirm')).toBeNull();
    const actions=calls.filter(c=>c.action==='charge_now');expect(actions).toHaveLength(1);
    expect(actions[0]).toMatchObject({type:'spotnav/morek_schedule',api_version:1,charger_id:'a',action:'charge_now'});
    expect(Date.parse(actions[0].end_time)-Date.now()).toBeGreaterThan(59*60000);
    expect(text).toContain(new Date(actions[0].end_time).toLocaleString());
    expect(root.querySelector('#charge-notice').textContent).toMatch(/waiting for schedule reconciliation|not confirm charging/i);
    panel.remove();
  });
  it.each([30,60,120,180])('validates offered %s minute duration',minutes=>{
    expect(chargeNowSelection(String(minutes),'',1000)).toEqual({end:1000+minutes*60000,options:{end_time:new Date(1000+minutes*60000).toISOString()}});
  });
  it('validates custom ends and cancellation makes no action',async()=>{
    expect(chargeNowSelection('custom','not-a-date',Date.now()).error).toMatch(/future end/);
    expect(chargeNowSelection('custom','2000-01-01T12:00',Date.now()).error).toMatch(/future end/);
    expect(chargeNowSelection('custom',new Date(Date.now()+49*3600000).toISOString(),Date.now()).error).toMatch(/48 hours/);
    const {panel,calls}=await setup();const root=panel.shadowRoot;
    root.querySelector('#charge-duration').value='custom';root.querySelector('#charge-duration').dispatchEvent(new Event('change'));
    root.querySelector('#charge-end').value='';root.querySelector('#charge-now').click();await tick();
    expect(root.querySelector('#charge-notice').textContent).toMatch(/valid future/);
    const end=new Date(Date.now()+3600000);const local=new Date(end.getTime()-end.getTimezoneOffset()*60000).toISOString().slice(0,16);
    root.querySelector('#charge-end').value=local;
    await open(root);root.querySelector('#charge-confirm-cancel').click();await tick();
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);expect(root.querySelector('#charge-confirm')).toBeNull();expect(root.querySelector('#charge-notice').textContent).toMatch(/Cancelled; nothing was sent/);
    await go(root);
    expect(calls.find(c=>c.action==='charge_now').end_time).toBe(new Date(local).toISOString());panel.remove();
  });
  it.each([[false,'does not exceed'],[true,'exceeds'],[null,'unavailable']])('displays cap/price state %s without blocking',async(above,text)=>{
    const {panel,setStatus}=await setup();const s=status();s.schedule.charge_now.above_cap=above;
    if(above===null)s.schedule.charge_now.current_price=null;setStatus(s);
    await open(panel.shadowRoot);expect(confirmText(panel.shadowRoot)).toContain(text);panel.remove();
  });
  it('shows a fixed active end, supports replacement and explains return',async()=>{
    const {panel,calls,setStatus,refreshStatus}=await setup();const s=status();const end=new Date(Date.now()+3600000).toISOString();
    s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'old',end},outcome:{state:'accepted',ack:'Accepted'}};setStatus(s);
    const root=panel.shadowRoot;expect(root.querySelector('#charge-now').textContent).toBe('Return to Auto');
    expect(root.querySelector('#charge-state').textContent).toMatch(/does not extend.*ACK Accepted.*does not prove charging/);
    root.querySelector('#charge-duration').value='120';
    await open(root,'#charge-replace');expect(confirmText(root)).toMatch(/replaces.*from now/);await confirm(root);expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(1);
    expect(Date.parse(calls.find(c=>c.action==='charge_now').end_time)-Date.now()).toBeGreaterThan(119*60000);
    expect(root.querySelector('#charge-now').disabled).toBe(true);
    s.schedule.charge_now.intent.id='new';await refreshStatus(s);await open(root);expect(confirmText(root)).toMatch(/may continue.*not a persistent Pause/);await confirm(root);expect(calls.filter(c=>c.action==='return_to_auto')).toHaveLength(1);panel.remove();
  });
  it('blocks paused, stale, offline, uncertain and non-admin requests',async()=>{
    const {panel,calls,setStatus}=await setup();const root=panel.shadowRoot;const s=status();
    s.schedule.schedule_pause.intent='pause_until_resumed';setStatus(s);expect(root.querySelector('#charge-state').textContent).toMatch(/Resume Auto first/);expect(root.querySelector('#charge-now').disabled).toBe(true);
    s.schedule.schedule_pause.intent='none';s.schedule.operator.state='offline';setStatus(s);expect(root.querySelector('#charge-state').textContent).toMatch(/offline/);
    s.schedule.operator.state='ready';s.schedule.charge_now.uncertain=true;setStatus(s);expect(root.querySelector('#charge-state').textContent).toMatch(/unknown/);
    s.schedule.charge_now.uncertain=false;setStatus(s);panel.statusAt=Date.now()-200000;panel.paint();expect(root.querySelector('#charge-now').disabled).toBe(true);
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);panel.remove();
    const other=await setup({admin:false});expect(other.panel.shadowRoot.querySelector('#charge-state').textContent).toMatch(/Administrator/);other.panel.remove();
  });
  it('does not retry an unknown action or issue writes during refresh',async()=>{
    const {panel,calls}=await setup({reply:()=>Promise.reject({code:'connection_lost'})});
    await go(panel.shadowRoot);panel.refresh();await tick();
    expect(panel.shadowRoot.querySelector('#charge-notice').textContent).toMatch(/unknown.*do not retry/i);
    expect(panel.shadowRoot.querySelector('#charge-notice').getAttribute('data-kind')).toBe('uncertain');expect(panel.shadowRoot.querySelector('#charge-notice').getAttribute('role')).toBe('alert');
    await open(panel.shadowRoot);expect(panel.shadowRoot.querySelector('#charge-confirm')).toBeNull();expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(1);panel.remove();
  });
  it('prevents duplicates while pending and displays rejected or uncertain outcomes',async()=>{
    let finish;const {panel,calls,setStatus}=await setup({reply:()=>new Promise(resolve=>{finish=resolve;})});
    const root=panel.shadowRoot;
    await go(root);expect(root.querySelector('#charge-now').getAttribute('aria-busy')).toBe('true');expect(root.querySelector('#charge-notice').getAttribute('data-kind')).toBe('pending');
    root.querySelector('#charge-now').click();await tick();
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(1);
    finish({api_version:1,schedule:{intent:{id:'new'},reconciliation:'pending',outcome:'not_yet_confirmed'}});await tick();
    const s=status();s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'new',end:new Date(Date.now()+3600000).toISOString()},outcome:{state:'rejected',ack:'Rejected'}};
    s.schedule.reconciliation.reason='upload_rejected';setStatus(s);expect(root.querySelector('#charge-state').textContent).toMatch(/rejected/i);
    s.schedule.charge_now.uncertain=true;setStatus(s);expect(root.querySelector('#charge-state').textContent).toMatch(/uncertain.*may have applied/i);panel.remove();
  });
  it('reflects Pause cancellation and later Resume from backend state',async()=>{
    const {panel,setStatus}=await setup();const s=status();const root=panel.shadowRoot;
    s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'old',end:new Date(Date.now()+3600000).toISOString()}};setStatus(s);
    expect(root.querySelector('#charge-now').textContent).toBe('Return to Auto');
    s.schedule.charge_now={...s.schedule.charge_now,state:'inactive',intent:null};s.schedule.schedule_pause.intent='pause_until_resumed';setStatus(s);
    expect(root.querySelector('#charge-now').textContent).toBe('Charge Now');expect(root.querySelector('#charge-state').textContent).toMatch(/Resume Auto first/);
    s.schedule.schedule_pause.intent='resume_requested';setStatus(s);expect(root.querySelector('#charge-now').textContent).toBe('Charge Now');panel.remove();
  });
  it('shows a backend refusal without inventing success',async()=>{
    const {panel}=await setup({reply:()=>Promise.reject({code:'spotnav_morek_resume_auto_first'})});
    await go(panel.shadowRoot);expect(panel.shadowRoot.querySelector('#charge-notice').textContent).toMatch(/Resume Auto first/);panel.remove();
  });
  it.each([375,1200])('keeps the controls available in a %s px host',async width=>{
    Object.defineProperty(window,'innerWidth',{value:width,configurable:true});
    const {panel,calls}=await setup();const root=panel.shadowRoot;
    expect(root.querySelector('#charge-controls').getAttribute('aria-label')).toBe('Charge Now');
    expect(root.querySelector('#charge-duration').options).toHaveLength(5);
    expect(root.querySelector('#charge-now').disabled).toBe(false);
    expect(calls.filter(c=>c.action==='charge_now'||c.action==='return_to_auto')).toHaveLength(0);panel.remove();
  });
  it('refuses a passed or invalid reported end until fresh status arrives',async()=>{
    const {panel,setStatus}=await setup();const s=status();
    s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'old',end:new Date(Date.now()-1000).toISOString()}};setStatus(s);
    expect(panel.shadowRoot.querySelector('#charge-now').disabled).toBe(true);
    expect(panel.shadowRoot.querySelector('#charge-state').textContent).toMatch(/end has passed/);panel.remove();
  });

  // 20.3 races: the confirmation is asynchronous, so what it depended on is revalidated when shown and when confirmed.
  it('closes the confirmation and sends nothing when Pause or a permission loss arrives while it is open',async()=>{
    const {panel,calls,setStatus}=await setup();const root=panel.shadowRoot;
    await open(root);expect(root.querySelector('#charge-confirm')).not.toBeNull();
    const s=status();s.schedule.schedule_pause.intent='pause_until_resumed';setStatus(s);
    expect(root.querySelector('#charge-confirm')).toBeNull();expect(root.querySelector('#charge-notice').textContent).toMatch(/Confirmation closed; nothing was sent.*Resume Auto first/);
    s.schedule.schedule_pause.intent='none';setStatus(s);
    await open(root);expect(root.querySelector('#charge-confirm')).not.toBeNull();
    panel._hass={...panel._hass,user:{is_admin:false}};panel.paint();
    expect(root.querySelector('#charge-confirm')).toBeNull();expect(root.querySelector('#charge-notice').textContent).toMatch(/Administrator permission/);
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);panel.remove();
  });
  it('does not dispatch a stale confirmation: a new override closes it, and a double click sends at most once',async()=>{
    const {panel,calls,setStatus}=await setup();const root=panel.shadowRoot;
    const s=status();s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'old',end:new Date(Date.now()+3600000).toISOString()}};setStatus(s);
    await open(root);const ok=root.querySelector('#charge-confirm-ok');
    s.schedule.charge_now.intent={id:'other',end:new Date(Date.now()+7200000).toISOString()};setStatus(s);
    expect(root.querySelector('#charge-confirm')).toBeNull();ok.click();await tick();
    expect(calls.filter(c=>c.action==='return_to_auto'||c.action==='charge_now')).toHaveLength(0);
    await open(root);const ok2=root.querySelector('#charge-confirm-ok');ok2.click();ok2.click();await tick();
    expect(calls.filter(c=>c.action==='return_to_auto')).toHaveLength(1);panel.remove();
  });
  it('survives a routine refresh while open and is dropped by a generation change',async()=>{
    const {panel,calls,refreshStatus}=await setup();const root=panel.shadowRoot;
    await open(root);const token=root.querySelector('#charge-confirm').dataset.token;
    await refreshStatus(status());
    expect(root.querySelector('#charge-confirm')?.dataset.token).toBe(token);
    panel.stopObservations();
    expect(panel.chargeConfirm).toBeNull();expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);panel.remove();
  });
  it('moves focus to Cancel when opened and back to the opener on Escape',async()=>{
    const {panel,calls}=await setup();const root=panel.shadowRoot;
    root.querySelector('#charge-now').focus();await open(root);
    expect(root.activeElement?.id).toBe('charge-confirm-cancel');
    root.querySelector('#charge-confirm').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick();
    expect(root.querySelector('#charge-confirm')).toBeNull();expect(root.activeElement?.id).toBe('charge-now');
    expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);panel.remove();
  });
  it('offers a recovery link that switches to the controls without sending anything',async()=>{
    const {panel,calls,setStatus}=await setup();const root=panel.shadowRoot;const s=status();
    s.schedule.outcomes.uncertain=true;s.schedule.reconciliation={reason:'upload_uncertain',blocker:{code:'upload_uncertain',action:'check_charger_outcome'},recovery:{},unknown_recovery:{ambiguous:true}};setStatus(s);
    const link=root.querySelector('#recovery-goto-controls');expect(link).not.toBeNull();
    root.querySelector('[data-sn-tab="settings"]').click();expect(root.querySelector('#sn-panel-overview').hidden).toBe(true);
    const before=calls.length;link.click();await tick();
    expect(root.querySelector('#sn-panel-overview').hidden).toBe(false);expect(calls.length).toBe(before);panel.remove();
  });
});
