// @vitest-environment jsdom
// @ts-nocheck
// Stage 19.2/19.9a review: the real sidebar panel's Resume button for a legacy ambiguous upload + Pause with no
// ownership ticket. The status fields come from tests/fixtures/morek/legacy_unknown_paused_status.json, which
// tests/test_stage_192_ui_path.py pins against the REAL backend status handler; the dashboard is the committed
// backend-shaped fixture (control.can_act is `connection.user is not None`, independent of ownership).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};

const c = JSON.parse(readFileSync('../tests/fixtures/morek/legacy_unknown_paused_status.json','utf8')).consumed;
const tick = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
const settings = () => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40});

const statusFor = (over = {}) => ({api_version:1,schedule:{supported:true,verified:false,sent:null,sent_at:null,ack:null,effective:null,
  ownership:{recorded_owner:c.recorded_owner,completion_authorized:c.completion_authorized,recovery:{automatic_recovery:'restart_dispatch_evidence_unavailable'}},
  outcomes:{uncertain:c.outcomes_uncertain},
  reconciliation:{reason:'upload_uncertain',blocker:{code:'upload_uncertain',action:'check_charger_outcome'},recovery:{},unknown_recovery:{ambiguous:c.unknown_recovery_ambiguous}},
  schedule_pause:{intent:c.intent,request:'uncertain',resume_recoverable:c.resume_recoverable,resume_pending:c.resume_pending,ack:null,readback:'unverified'},...over}});

async function mount({canAct=true,status=statusFor(),admin=false}={}) {
  const raw=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
  raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
  raw.control.can_act=canAct;raw.control.automatic_action='pause';
  const calls=[];
  const hass={connected:true,user:{is_admin:admin},callWS:msg=>{calls.push(msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);
    if(msg.type==='spotnav/get_settings')return Promise.resolve({api_version:1,ok:true,error:null,settings:settings(),pause:{choice:null,admitted_at:null,expires_at:null}});
    if(msg.type==='spotnav/manual_action')return Promise.resolve({api_version:1,ok:true,error:null,action:msg.action,choice:msg.choice??null});
    return Promise.resolve(status);}};
  const panel=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  return {panel,calls,root:panel.shadowRoot,raw};
}
const actions=calls=>calls.filter(m=>m.type==='spotnav/manual_action');

describe('Resume on a legacy ambiguous upload with a Pause and no ownership ticket', () => {
  it('enables Resume for a non-admin signed-in user and a real click sends exactly one choice-less resume', async () => {
    const {panel,calls,root}=await mount();
    expect(c.completion_authorized).toBe(false);
    expect(root.querySelector('#resume-auto').disabled).toBe(false);
    expect(root.querySelector('#pause-state').textContent).not.toMatch(/Resume unavailable/);
    root.querySelector('#resume-auto').click();await tick();
    expect(actions(calls)).toHaveLength(1);
    expect(actions(calls)[0]).toMatchObject({action:'resume'});
    expect(actions(calls)[0].choice ?? null).toBeNull();
    panel.remove();
  });
  it('keeps the dashboard permission, a pending Stop, an already pending Resume and stale status blocking', async () => {
    for (const [name,opts] of [
      ['no control permission',{canAct:false}],
      ['stop pending',{status:statusFor({schedule_pause:{intent:c.intent,request:'stop_pending',resume_recoverable:false,resume_pending:false}})}],
      ['resume already pending',{status:statusFor({schedule_pause:{intent:c.intent,request:'resume_pending',resume_recoverable:false,resume_pending:true}})}],
      ['removal in doubt (not recoverable)',{status:statusFor({schedule_pause:{intent:c.intent,request:'uncertain',resume_recoverable:false,resume_pending:false}})}],
    ]) {
      const {panel,calls,root}=await mount(opts);
      expect(root.querySelector('#resume-auto').disabled,name).toBe(true);
      root.querySelector('#resume-auto').click();await panel.automaticAction('resume',null);
      expect(actions(calls),name).toHaveLength(0);
      panel.remove();
    }
    const {panel,calls,root}=await mount();
    panel.statusAt=Date.now()-90001;panel.paint();
    expect(root.querySelector('#resume-auto').disabled).toBe(true);
    await panel.automaticAction('resume',null);expect(actions(calls)).toHaveLength(0);panel.remove();
  });
  it('after the click, a pending status disables a second Resume and says it is saved, not sent', async () => {
    const {panel,root}=await mount({status:statusFor({schedule_pause:{intent:c.intent,request:'resume_pending',resume_recoverable:false,resume_pending:true}})});
    expect(root.querySelector('#resume-auto').disabled).toBe(true);
    expect(root.querySelector('#pause-state').textContent).toMatch(/Resume is requested and saved.*fresh schedule automatically/);
    expect(root.querySelector('#pause-auto').disabled).toBe(false); // Stop stays available and wins
    panel.remove();
  });
});
