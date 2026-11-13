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

describe('Charge Now sidebar',()=>{
  it('starts with one-hour default and sends one request after one confirmation',async()=>{
    const {panel,calls}=await setup();const root=panel.shadowRoot;
    expect(root.querySelector('#charge-now').textContent).toBe('Charge Now');
    expect(root.querySelector('#charge-duration').value).toBe('60');
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    root.querySelector('#charge-now').click();await tick();
    expect(confirm).toHaveBeenCalledOnce();expect(confirm.mock.calls[0][0]).toMatch(/overrides the price-based Auto plan.*0.12 EUR\/kWh.*exceeds your cap/i);
    const actions=calls.filter(c=>c.action==='charge_now');expect(actions).toHaveLength(1);
    expect(actions[0]).toMatchObject({type:'spotnav/morek_schedule',api_version:1,charger_id:'a',action:'charge_now'});
    expect(Date.parse(actions[0].end_time)-Date.now()).toBeGreaterThan(59*60000);
    expect(confirm.mock.calls[0][0]).toContain(new Date(actions[0].end_time).toLocaleString());
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
    const confirm=vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    root.querySelector('#charge-now').click();await tick();expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(0);
    root.querySelector('#charge-now').click();await tick();expect(confirm).toHaveBeenCalledTimes(2);
    expect(calls.find(c=>c.action==='charge_now').end_time).toBe(new Date(local).toISOString());panel.remove();
  });
  it.each([[false,'does not exceed'],[true,'exceeds'],[null,'unavailable']])('displays cap/price state %s without blocking',async(above,text)=>{
    const {panel,setStatus}=await setup();const s=status();s.schedule.charge_now.above_cap=above;
    if(above===null)s.schedule.charge_now.current_price=null;setStatus(s);
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    panel.shadowRoot.querySelector('#charge-now').click();expect(confirm.mock.calls[0][0]).toContain(text);panel.remove();
  });
  it('shows a fixed active end, supports replacement and explains return',async()=>{
    const {panel,calls,setStatus,refreshStatus}=await setup();const s=status();const end=new Date(Date.now()+3600000).toISOString();
    s.schedule.charge_now={...s.schedule.charge_now,state:'active',intent:{id:'old',end},outcome:{state:'accepted',ack:'Accepted'}};setStatus(s);
    const root=panel.shadowRoot;expect(root.querySelector('#charge-now').textContent).toBe('Return to Auto');
    expect(root.querySelector('#charge-state').textContent).toMatch(/does not extend.*ACK Accepted.*does not prove charging/);
    root.querySelector('#charge-duration').value='120';const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    root.querySelector('#charge-replace').click();await tick();expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(1);
    expect(Date.parse(calls.find(c=>c.action==='charge_now').end_time)-Date.now()).toBeGreaterThan(119*60000);expect(confirm.mock.calls[0][0]).toMatch(/replaces.*from now/);
    expect(root.querySelector('#charge-now').disabled).toBe(true);
    s.schedule.charge_now.intent.id='new';await refreshStatus(s);root.querySelector('#charge-now').click();await tick();expect(calls.filter(c=>c.action==='return_to_auto')).toHaveLength(1);
    expect(confirm.mock.calls[1][0]).toMatch(/may continue.*not a persistent Pause/);panel.remove();
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
    const {panel,calls}=await setup({reply:()=>Promise.reject({code:'connection_lost'})});vi.spyOn(window,'confirm').mockReturnValue(true);
    panel.shadowRoot.querySelector('#charge-now').click();await tick();panel.refresh();await tick();
    expect(panel.shadowRoot.querySelector('#charge-notice').textContent).toMatch(/unknown.*do not retry/i);
    panel.shadowRoot.querySelector('#charge-now').click();await tick();expect(calls.filter(c=>c.action==='charge_now')).toHaveLength(1);panel.remove();
  });
  it('prevents duplicates while pending and displays rejected or uncertain outcomes',async()=>{
    let finish;const {panel,calls,setStatus}=await setup({reply:()=>new Promise(resolve=>{finish=resolve;})});
    vi.spyOn(window,'confirm').mockReturnValue(true);const root=panel.shadowRoot;
    root.querySelector('#charge-now').click();await tick();root.querySelector('#charge-now').click();await tick();
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
    const {panel}=await setup({reply:()=>Promise.reject({code:'spotnav_morek_resume_auto_first'})});vi.spyOn(window,'confirm').mockReturnValue(true);
    panel.shadowRoot.querySelector('#charge-now').click();await tick();expect(panel.shadowRoot.querySelector('#charge-notice').textContent).toMatch(/Resume Auto first/);panel.remove();
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
});
