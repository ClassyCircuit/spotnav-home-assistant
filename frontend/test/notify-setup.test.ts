// @vitest-environment jsdom
// @ts-nocheck
// Stage 13.4: notification recipients/events and the compact setup check in the shared sidebar UI
// (pure model + write plan, renderer/preview parity, then the real panel against a mocked backend).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';
import { notifyModel, notifyWritePlan, notifySignature, setupDiagnostics, MAX_TARGETS } from '../sidebar/notify-setup.js';
import { renderNotifySetup } from '../shared-dashboard/notify-setup-view.js';
import { decodeSettingsRecord } from '../src/settings.ts';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
beforeEach(()=>sessionStorage.clear());
afterEach(()=>vi.restoreAllMocks());

const read = (path) => JSON.parse(readFileSync(`../tests/fixtures/${path}`,'utf8'));
const tick = async () => { for(let i=0;i<30;i++) await Promise.resolve(); };
const PHONES = [{service:'mobile_app_anna',name:'Anna'},{service:'mobile_app_ben',name:'Ben'}];
const notif = (over={}) => ({targets:['mobile_app_anna'],events:['plan_stopped','plan_at_risk','charge_complete','vehicle_identify'],url:'/lovelace/car',available:PHONES,...over});
const recordRaw = (over={}) => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40,notifications:notif(),...over});
const rec = (over={}) => decodeSettingsRecord(recordRaw(over));
const recNone = () => { const r:any=recordRaw();delete r.notifications;return decodeSettingsRecord(r); };
const dash = (over={}) => ({generated_at:new Date(1000).toISOString(),setup:{items:[]},soc:{value:55},prices:{provider:{key:'nordpool',name:'Nord Pool',notice:null},state:'ready',reason:'ready',interval_count:96},...over});
const model = (over={}) => notifyModel({admin:true,record:rec(),dashboard:dash(),dashboardFresh:true,status:null,statusFresh:false,now:1000,...over});

describe('notification model (pure)', () => {
  it('lists the phones and every event with the saved choice, and says the notice proves nothing', () => {
    const m=model();
    expect(m.phones.map(p=>[p.service,p.name,p.checked,p.missing])).toEqual([['mobile_app_anna','Anna',true,false],['mobile_app_ben','Ben',false,false]]);
    expect(m.events).toHaveLength(8);expect(m.events.filter(e=>e.checked).map(e=>e.event)).toEqual(['plan_stopped','plan_at_risk','charge_complete','vehicle_identify']);
    expect(m.canEdit).toBe(true);expect(m.noticeNote).toMatch(/does not prove a plan was sent.*charging was measured/);expect(m.noticeNote).toMatch(/sends no notification and does not wake the car/);
  });
  it('flags no registered phone, a chosen phone that is gone, no recipient with events on, and no events', () => {
    const none=model({record:rec({notifications:notif({targets:[],available:[]})})});
    expect(none.problems.join(' ')).toMatch(/No Home Assistant mobile app is registered/);expect(none.problems.join(' ')).toMatch(/No recipients chosen/);expect(none.phones).toEqual([]);
    const gone=model({record:rec({notifications:notif({targets:['mobile_app_anna','mobile_app_old'],available:[PHONES[0]]})})});
    expect(gone.phones.find(p=>p.service==='mobile_app_old')).toMatchObject({checked:true,missing:true});expect(gone.problems.join(' ')).toMatch(/old is chosen but its notify service is not available.*kept, and skipped/);
    const noEv=model({record:rec({notifications:notif({events:[]})})});expect(noEv.problems.join(' ')).toMatch(/No events are ticked/);
    expect(model().problems).toEqual([]);
  });
  it('permissions, stale dashboard, busy, conflict, blocked and a pending post-save read withhold editing; states for unavailable/loading/unsupported', () => {
    const ro=model({admin:false});expect(ro.canEdit).toBe(false);expect(ro.notes.join(' ')).toMatch(/Only an administrator/);expect(ro.problems.join(' ')).toMatch(/Only an administrator/);
    for(const over of [{dashboardFresh:false},{blocked:true},{conflict:true},{busy:true},{awaitingRead:true}]) expect(model(over).canEdit,JSON.stringify(over)).toBe(false);
    expect(model({dashboardFresh:false}).notes.join(' ')).toMatch(/stale/);expect(model({awaitingRead:true}).notes.join(' ')).toMatch(/Waiting for a fresh dashboard read/);
    expect(model({record:null}).state).toBe('unavailable');expect(model({record:null,loading:true}).state).toBe('loading');
    const old=model({record:recNone()});expect(old.state).toBe('unsupported');expect(old.notice).toMatch(/does not offer notification settings/);expect(old.canEdit).toBe(false);
    expect(model({record:null}).diagnostics.length).toBeGreaterThanOrEqual(0);
  });
  it('signature follows the choice and the tap url, not the phones that exist now', () => {
    const base=notifySignature(rec());
    expect(notifySignature(rec({notifications:notif({targets:[]})}))).not.toBe(base);expect(notifySignature(rec({notifications:notif({events:['plan_stopped']})}))).not.toBe(base);expect(notifySignature(rec({notifications:notif({url:null})}))).not.toBe(base);
    expect(notifySignature(rec({notifications:notif({available:[]})}))).toBe(base);expect(notifySignature(null)).toBe('null');
  });
});

describe('setup diagnostics reuse the existing words and links', () => {
  const d = (over) => setupDiagnostics({dashboard:dash(over),status:null,statusFresh:true,now:1000});
  it('measurement rows: vehicle and car level link to the vehicle section; site/grid rows say where they are set; unrelated rows are left out', () => {
    const rows=d({setup:{items:[{id:'vehicle',dismissible:true},{id:'car_level',dismissible:false},{id:'site',dismissible:true},{id:'grid_power_sign',dismissible:false,write:{field:'grid_power_inverted',value:true}},{id:'phone',dismissible:true},{id:'app',dismissible:true},{id:'solar_forecast',dismissible:true}]}});
    const ids=rows.map(r=>r.id);expect(ids).toEqual(expect.arrayContaining(['setup-vehicle','setup-car_level','setup-site','setup-grid_power_sign']));
    expect(ids).not.toContain('setup-phone');expect(ids).not.toContain('setup-app');expect(ids).not.toContain('setup-solar_forecast');
    expect(rows.find(r=>r.id==='setup-vehicle')).toMatchObject({group:'measurement',goto:'vehicle-sources',gotoLabel:'Vehicle sources & properties'});expect(rows.find(r=>r.id==='setup-vehicle').text).toBe('Add your car, so a target in percent and the range are right.');
    expect(rows.find(r=>r.id==='setup-site')).toMatchObject({goto:null});expect(rows.find(r=>r.id==='setup-site').text).toMatch(/set up in Home Assistant/);expect(rows.find(r=>r.id==='setup-grid_power_sign').level).toBe('warning');
  });
  it('a missing or unreadable setup block and a missing dashboard are said as unknown', () => {
    expect(d({setup:null}).map(r=>r.id)).toContain('setup-unknown');
    expect(setupDiagnostics({dashboard:null,status:null,statusFresh:false,now:1}).map(r=>r.id)).toEqual(['dashboard']);
    expect(d({setup:{items:[]},soc:{value:null}}).map(r=>r.id)).toContain('soc-missing');expect(d({setup:{items:[{id:'car_level',dismissible:false}]},soc:{value:null}}).map(r=>r.id)).not.toContain('soc-missing');
  });
  it('pricing: no provider, held state not ready, no intervals; a ready held price says nothing', () => {
    const none=d({prices:{provider:{key:null,name:null,notice:{code:'add_nordpool',params:{}}},state:'ready',reason:'ready',interval_count:96}});
    expect(none.find(r=>r.id==='price-provider')).toMatchObject({group:'pricing',goto:'market-costs'});expect(none.find(r=>r.id==='price-provider').text).toMatch(/add nordpool/);
    const partial=d({prices:{provider:{key:'nordpool',name:'Nord Pool',notice:null},state:'partial',reason:'tomorrow_missing',interval_count:96}});expect(partial.find(r=>r.id==='price-state').text).toMatch(/“partial”.*tomorrow missing.*not proof the provider answered/);
    expect(d({prices:{provider:null,state:'ready',reason:null,interval_count:0}}).map(r=>r.id)).toContain('price-none');
    expect(d({}).filter(r=>r.group==='pricing')).toEqual([]);
  });
  it('execution: a stale status is unknown (never "nothing blocked"); a fresh blocker reuses the recovery wording and links to the evidence', () => {
    const stale=setupDiagnostics({dashboard:dash(),status:null,statusFresh:false,now:1000});expect(stale.find(r=>r.id==='status-stale')).toMatchObject({group:'execution',goto:'morek'});expect(stale.find(r=>r.id==='status-stale').text).toMatch(/not proof that nothing is blocked/);
    const blocked=setupDiagnostics({dashboard:dash(),status:{supported:true,outcomes:{uncertain:true},reconciliation:{}},statusFresh:true,now:1000});
    const x=blocked.find(r=>r.group==='execution');expect(x).toMatchObject({level:'error',goto:'morek'});expect(x.text).toMatch(/unknown outcome.*Charging is not confirmed/s);
    const prices=setupDiagnostics({dashboard:dash(),status:{supported:true,reconciliation:{blocker:{code:'x',action:'wait_for_prices'}}},statusFresh:true,now:1000}).find(r=>r.group==='execution');expect(prices.text).toMatch(/Prices are unavailable or incomplete/);
    expect(setupDiagnostics({dashboard:dash(),status:{supported:true,reconciliation:{}},statusFresh:true,now:1000}).filter(r=>r.group==='execution')).toEqual([]);
  });
});

describe('notification write plan', () => {
  it('unchanged states nothing; choosing a phone and events keeps the backend order and the tap url', () => {
    const r=rec();
    expect(notifyWritePlan(r,{targets:['mobile_app_anna'],events:['charge_complete','plan_stopped','plan_at_risk','vehicle_identify']},true)).toEqual({ok:true,changed:false});
    const p=notifyWritePlan(r,{targets:['mobile_app_anna','mobile_app_ben'],events:['charge_complete','plan_stopped','charge_started']},true);
    expect(p).toMatchObject({ok:true,changed:true,targets:['mobile_app_anna','mobile_app_ben'],events:['plan_stopped','charge_complete','charge_started'],sendsNothing:false});
    expect(p.body.notifications).toEqual({targets:['mobile_app_anna','mobile_app_ben'],events:['plan_stopped','charge_complete','charge_started'],url:'/lovelace/car'});
    expect(p.body.amps).toBe(10);expect(p.body.max_periods).toBe(3);expect(p.body.departure_time).toBe('06:30');
  });
  it('no phone or no event is saved and flagged as sending nothing; the other charger is never copied', () => {
    expect(notifyWritePlan(rec(),{targets:[],events:['plan_stopped']},true)).toMatchObject({ok:true,changed:true,sendsNothing:true});
    expect(notifyWritePlan(rec(),{targets:['mobile_app_anna'],events:[]},true)).toMatchObject({ok:true,changed:true,sendsNothing:true});
  });
  it('refuses a non-administrator, a phone that is not offered, too many phones, a record without notifications and no record; a vanished chosen phone may stay', () => {
    expect(notifyWritePlan(rec(),{targets:[],events:[]},false)).toMatchObject({ok:false,notice:expect.stringMatching(/Administrator/)});
    expect(notifyWritePlan(rec(),{targets:['mobile_app_zed'],events:[]},true)).toMatchObject({ok:false,notice:expect.stringMatching(/not one of the available/)});
    const many=Array.from({length:MAX_TARGETS+1},(_,i)=>`mobile_app_p${i}`);
    expect(notifyWritePlan(rec({notifications:notif({targets:[],available:many.map(s=>({service:s,name:s}))})}),{targets:many,events:['plan_stopped']},true)).toMatchObject({ok:false,notice:expect.stringMatching(/At most 10/)});
    expect(notifyWritePlan(recNone(),{targets:[],events:[]},true)).toMatchObject({ok:false});
    expect(notifyWritePlan(null,{targets:[],events:[]},true)).toMatchObject({ok:false});
    const gone=rec({notifications:notif({targets:['mobile_app_anna','mobile_app_old'],available:[PHONES[0]]})});
    expect(notifyWritePlan(gone,{targets:['mobile_app_anna','mobile_app_old'],events:['plan_stopped','plan_at_risk','charge_complete','vehicle_identify']},true)).toEqual({ok:true,changed:false});
    expect(notifyWritePlan(gone,{targets:['mobile_app_anna'],events:['plan_stopped','plan_at_risk','charge_complete','vehicle_identify']},true)).toMatchObject({ok:true,changed:true,targets:['mobile_app_anna']});
  });
});

describe('notification renderer and preview parity', () => {
  it('escapes text, offers every control when editable, none enabled when read-only, and diagnostics link only to known sections', () => {
    const m=model({admin:true});
    const html=renderNotifySetup({...m,diagnostics:[{id:'x',group:'pricing',level:'warning',text:'<b>x</b>',goto:'market-costs',gotoLabel:'Market & charging costs'},{id:'y',group:'setup',level:'info',text:'y',goto:'evil"><script>',gotoLabel:'z'}]});
    expect(html).not.toContain('<b>x</b>');expect(html).not.toContain('<script>');expect(html).toContain('data-goto="market-costs"');expect(html).not.toContain('data-goto="evil');
    for(const id of ['save-notify','reload-notify-setup']) expect(html).toContain(`id="${id}"`);
    for(const name of ['tg-mobile_app_anna','tg-mobile_app_ben','ev-plan_stopped','ev-vehicle_identify']) expect(html).toContain(`data-nsetting="${name}"`);
    const ro=renderNotifySetup(model({admin:false}));expect(ro.match(/data-nsetting="[^"]+"[^>]*disabled/g).length).toBe(10);expect(ro).toContain('<wa-button id="save-notify" size="small" disabled>');
    expect(renderNotifySetup(model({record:null}))).toContain('unavailable');expect(renderNotifySetup(null)).toBe('');
    expect(renderNotifySetup(model({diagnostics:undefined,record:rec()}))).toContain('Setup check');
  });
  it('the preview sample is rendered by the same view with the same classes, and the dark theme styles them', () => {
    const src=readFileSync('prototype/sample-adapter.js','utf8');expect(src).toContain('notifySetup');expect(src).toContain('mobile_app_sample_phone');
    const css=readFileSync('shared-dashboard/dark.css','utf8');for(const c of ['.ns-block','.ns-list','.ns-days','.notify-setup','.ns-goto']) expect(css).toContain(c);
    const dashboardSrc=readFileSync('shared-dashboard/dashboard.js','utf8');expect(dashboardSrc).toContain("renderNotifySetup(m.notifySetup)");
    const html=renderNotifySetup({state:'ready',busy:false,conflict:false,canEdit:false,notice:'',notes:[],noticeNote:'n',phones:[{service:'mobile_app_a',name:'A',checked:true,missing:false}],events:[{event:'plan_stopped',label:'L',checked:true}],problems:[],diagnostics:[]});
    expect(html).toContain('class="ns-block"');expect(html).toContain('Nothing is reported as missing or blocked. That is not proof charging works');
  });
});

// ---- the real panel with a mocked backend ----
const FIXTURE = () => read('dashboard/target_soc_two_vehicles.json');
const morek = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const pause = {choice:null,admitted_at:null,expires_at:null};
const settingsAnswer = (r) => ({api_version:1,ok:true,error:null,settings:r,pause});
const WRITES = ['spotnav/update_settings','spotnav/update_grid_tariff','spotnav/choose_price_source'];
const setup = (opts:any={}) => {
  const calls:any[]=[];
  const raw=FIXTURE();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
  const state:any={record:recordRaw(opts.record||{})};
  const handlers:any={};
  const hass:any={connected:true,user:{is_admin:opts.admin!==false},callWS:(msg:any)=>{calls.push(msg);
    if(handlers[msg.type]) return handlers[msg.type](msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(JSON.parse(JSON.stringify(raw)));
    if(msg.type==='spotnav/get_settings')return Promise.resolve(settingsAnswer(state.record));
    if(msg.type==='spotnav/get_market_options'||msg.type==='spotnav/get_entity_config')return Promise.reject(Object.assign(new Error('n/a'),{code:'spotnav_not_admin'}));
    if(WRITES.includes(msg.type))return Promise.reject(new Error('unexpected write'));
    return Promise.resolve(morek);}};
  return {calls,hass,raw,state,handlers};
};
const open = async (hass:any) => {
  const panel:any=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await tick();
  const q=(s:string)=>panel.shadowRoot.querySelector(s);
  const tickBox=(name:string,on:boolean)=>{const el=q(`[data-nsetting="${name}"]`);el.checked=on;el.dispatchEvent(new Event('change',{bubbles:true}));};
  return {panel,q,tickBox};
};
const writes = (calls:any[]) => calls.filter(m=>WRITES.includes(m.type));
const text = (panel:any) => panel.shadowRoot.querySelector('.notify-setup')?.textContent || '';
const saved = (msg:any,over={}) => settingsAnswer({...msg.settings,revision:8,notifications:{...msg.settings.notifications,available:PHONES},...over});

describe('notification settings in the real panel (mocked backend)', () => {
  it('opening and editing only read: the recipients, events and the setup check are shown, nothing is written', async () => {
    const {calls,hass}=setup();const {panel,q,tickBox}=await open(hass);
    expect(text(panel)).toContain('Recipients & events');expect(text(panel)).toContain('Setup check');expect(text(panel)).toMatch(/does not prove a plan was sent/);
    expect(q('[data-nsetting="tg-mobile_app_anna"]').checked).toBe(true);expect(q('[data-nsetting="tg-mobile_app_ben"]').checked).toBe(false);expect(q('[data-nsetting="ev-charge_complete"]').checked).toBe(true);expect(q('[data-nsetting="ev-plugged_in"]').checked).toBe(false);
    expect(text(panel)).toMatch(/No price provider is configured/);expect(q('#notify-setup-details [data-goto="market-costs"]')).not.toBeNull();
    tickBox('tg-mobile_app_ben',true);tickBox('ev-plugged_in',true);
    expect(panel.notifyDirty).toBe(true);expect(writes(calls)).toHaveLength(0);
    expect(calls.every(m=>!/^spotnav\/(update|set|clear|send|choose|confirm|perform|action)/.test(m.type))).toBe(true);panel.remove();
  });
  it('saves the chosen phones and events once with the displayed revision; only notifications change; the notice never claims a plan was sent', async () => {
    const {calls,hass,handlers}=setup();handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));
    const {panel,q,tickBox}=await open(hass);
    tickBox('tg-mobile_app_ben',true);tickBox('ev-plugged_in',true);tickBox('ev-plan_at_risk',false);const reads=calls.filter(m=>m.type==='spotnav/get_dashboard').length;
    q('#save-notify').click();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/update_settings',charger_id:'a',expected_revision:7});
    expect(w[0].settings.notifications).toEqual({targets:['mobile_app_anna','mobile_app_ben'],events:['plan_stopped','charge_complete','plugged_in','vehicle_identify'],url:'/lovelace/car'});
    expect(w[0].settings.amps).toBe(10);expect(w[0].settings.departure_time).toBe('06:30');expect(w[0].settings.max_periods).toBe(3);
    expect(text(panel)).toContain('Notification settings saved and confirmed by the backend');expect(text(panel)).toMatch(/no notification was sent and nothing about a plan or charging is confirmed/);
    expect(panel.notifyDirty).toBe(false);expect(panel.settingsRecord.revision).toBe(8);expect(calls.filter(m=>m.type==='spotnav/get_dashboard').length).toBeGreaterThan(reads);
    await tick();expect(panel.notifyAwaitingRead).toBe(false);panel.remove();
  });
  it('an unchanged save sends nothing; unticking everything is saved and said to send nothing', async () => {
    const {calls,hass,handlers}=setup();handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));
    const {panel,q,tickBox}=await open(hass);
    q('#save-notify').click();await tick();expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');
    tickBox('tg-mobile_app_anna',false);q('#save-notify').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(writes(calls)[0].settings.notifications.targets).toEqual([]);expect(text(panel)).toMatch(/nothing will be sent/);panel.remove();
  });
  it('missing phones: no registered app and a vanished chosen phone are shown with actionable text', async () => {
    const none=setup({record:{notifications:notif({targets:[],available:[]})}});const a=await open(none.hass);
    expect(text(a.panel)).toMatch(/No Home Assistant mobile app is registered/);expect(text(a.panel)).toMatch(/No phones available/);a.panel.remove();
    const gone=setup({record:{notifications:notif({targets:['mobile_app_old'],available:PHONES})}});const b=await open(gone.hass);
    expect(text(b.panel)).toMatch(/old is chosen but its notify service is not available/);expect(b.q('[data-nsetting="tg-mobile_app_old"]').checked).toBe(true);b.panel.remove();
  });
  it('a revision conflict writes nothing more, blocks further saves and keeps the draft', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.resolve({api_version:1,ok:false,error:'revision_conflict',settings:{...recordRaw(),revision:9},pause});
    const {panel,q,tickBox}=await open(hass);
    tickBox('ev-plugged_in',true);q('#save-notify').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toContain('nothing was written');expect(panel.notifyConflict).toBe(true);expect(panel.settingsConflict).toBe(true);expect(panel.settingsRecord.revision).toBe(7);
    q('#save-notify').click();await tick();expect(writes(calls)).toHaveLength(1);expect(q('[data-nsetting="ev-plugged_in"]').checked).toBe(true);expect(q('#save-notify').hasAttribute('disabled')).toBe(true);panel.remove();
  });
  it('a refused write shows the reason; an unresolved write is an unknown outcome that blocks until reload; a reconcile failure demands a reload', async () => {
    vi.spyOn(window,'confirm').mockReturnValue(true);
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.resolve({api_version:1,ok:false,error:'invalid_notifications',settings:recordRaw(),pause});
    const {panel,q,tickBox}=await open(hass);
    tickBox('ev-plugged_in',true);q('#save-notify').click();await tick();await tick();await tick();
    expect(text(panel)).toMatch(/not saved/i);expect(text(panel)).toContain('invalid_notifications');expect(panel.unknownSettingsWrites.size).toBe(0);expect(panel.notifyConflict).toBe(false);
    handlers['spotnav/update_settings']=()=>Promise.reject(new Error('timeout'));
    q('#save-notify').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(2);expect(panel.unknownSettingsWrites.has('a')).toBe(true);expect(text(panel)).toContain('outcome unknown');
    q('#save-notify').click();await tick();expect(writes(calls)).toHaveLength(2);
    q('#reload-notify-setup').click();await tick();await tick();await tick();
    expect(panel.unknownSettingsWrites.size).toBe(0);expect(panel.notifyConflict).toBe(false);expect(panel.settingsRecord).not.toBeNull();panel.remove();
    const r=setup();r.handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve({...saved(msg),ok:false,error:'spotnav_settings_reconcile_failed'});
    const b=await open(r.hass);b.tickBox('ev-plugged_in',true);b.q('#save-notify').click();await tick();await tick();await tick();
    expect(text(b.panel)).toContain('saved, but replanning failed');expect(b.panel.settingsRecord.revision).toBe(8);expect(b.panel.notifyConflict).toBe(true);b.panel.remove();
  });
  it('a non-administrator reads everything but sends nothing, even through a direct call', async () => {
    const ro=setup({admin:false});const a=await open(ro.hass);
    expect(text(a.panel)).toMatch(/Only an administrator can change notifications/);expect(a.q('#save-notify').hasAttribute('disabled')).toBe(true);expect(a.q('[data-nsetting="tg-mobile_app_anna"]').disabled).toBe(true);
    await a.panel.saveNotify({targets:[],events:[]});await tick();expect(writes(ro.calls)).toHaveLength(0);a.panel.remove();
  });
  it('a stale dashboard withholds saving even through a direct call', async () => {
    const {calls,hass}=setup();const {panel,tickBox}=await open(hass);
    tickBox('ev-plugged_in',true);panel.rawDashboard={...panel.rawDashboard,generated_at:new Date(Date.now()-10*60000).toISOString()};
    await panel.saveNotify({targets:['mobile_app_anna'],events:['plugged_in']});expect(writes(calls)).toHaveLength(0);expect(text(panel)).toMatch(/stale/);panel.remove();
  });
  it('drafts survive a refresh; another writer changing the choice while editing is flagged, an unrelated plan change is not', async () => {
    const {calls,hass}=setup();const {panel,q,tickBox}=await open(hass);
    tickBox('tg-mobile_app_ben',true);tickBox('ev-plan_stopped',false);
    panel.statusEpoch++;panel.refresh();await tick();panel.paint();
    expect(q('[data-nsetting="tg-mobile_app_ben"]').checked).toBe(true);expect(q('[data-nsetting="ev-plan_stopped"]').checked).toBe(false);expect(panel.notifyConflict).toBe(false);
    panel.settingsRecord=decodeSettingsRecord(recordRaw({revision:8,requested_kwh:33}));panel.paint();expect(panel.notifyConflict).toBe(false);
    panel.settingsRecord=decodeSettingsRecord(recordRaw({revision:9,notifications:notif({targets:[]})}));panel.paint();
    expect(panel.notifyConflict).toBe(true);expect(text(panel)).toContain('changed while editing');expect(q('[data-nsetting="tg-mobile_app_ben"]').checked).toBe(true);
    q('#save-notify').click();await tick();expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('a permission change during a save leaves the outcome unknown; a late answer is not applied; the plan form cannot save over a pending save', async () => {
    const {calls,hass,handlers}=setup();let release:any;handlers['spotnav/update_settings']=(msg:any)=>new Promise(r=>{release=()=>r(saved(msg));});
    const {panel,q,tickBox}=await open(hass);
    tickBox('ev-plugged_in',true);q('#save-notify').click();await tick();
    expect(panel.notifyBusy).toBe(true);await panel.savePlan({});await tick();expect(writes(calls)).toHaveLength(1);
    panel.hass={...hass,user:{is_admin:false}};await tick();
    expect(panel.unknownSettingsWrites.has('a')).toBe(true);expect(panel.notifyConflict).toBe(true);
    release();await tick();await tick();await tick();expect(panel.settingsRecord.revision).toBe(7);expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('the diagnostic link opens and scrolls to the existing section without writing', async () => {
    const {calls,hass}=setup();const {panel,q}=await open(hass);
    const link=q('[data-goto="market-costs"]');expect(link).not.toBeNull();const target=q('section.panel.market-costs');const scroll=vi.fn();target.scrollIntoView=scroll;
    link.click();expect(scroll).toHaveBeenCalled();expect(target.querySelector('details').open).toBe(true);expect(writes(calls)).toHaveLength(0);panel.remove();
  });
});
