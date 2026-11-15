// @vitest-environment jsdom
// @ts-nocheck
// Stage 13.1: vehicle sources & planning properties in the shared sidebar UI (pure model + the real panel, mocked backend).
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';
import { vehicleSourcesModel, vehicleSignature, chooseVehicle, sensorWritePlan, propertyWritePlan } from '../sidebar/vehicle-sources.js';
import { renderVehicleSources } from '../shared-dashboard/vehicle-sources-view.js';
import { decodeEntityAnswer, decodeVehicleWriteAnswer } from '../src/entity-config.ts';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
beforeEach(()=>sessionStorage.clear());

const read = (path) => JSON.parse(readFileSync(`../tests/fixtures/${path}`,'utf8'));
const tick = async () => { for(let i=0;i<30;i++) await Promise.resolve(); };
const ent = (id,name=id) => ({entity_id:id,friendly_name:name});
const car = (over={}) => ({id:'vehicle_ev6',name:'EV6',selected:ent('sensor.ev6_battery','EV6 battery'),source:'automatic',candidates:[ent('sensor.ev6_battery','EV6 battery')],...over});
const ambiguous = (over={}) => car({selected:null,source:null,candidates:[ent('sensor.pack_a','Pack A'),ent('sensor.pack_b','Pack B')],...over});
const prop = (over={}) => ({id:'vehicle_ev6',capacity_kwh:77,capacity_source:'stored',reported_capacity_kwh:null,reported_known:true,stored_capacity_kwh:77,onboard_phases:3,stored_onboard_phases:null,...over});
const noCapacity = {capacity_kwh:null,capacity_source:null,stored_capacity_kwh:null};
const configOf = (vehicles, props?) => { const a=read('entity_config/v1/get_direct.json'); a.config.charger_id='a'; a.config.vehicles=vehicles; a.config.vehicle_properties=props ?? vehicles.map(v=>prop({id:v.id})); return a; };
const decode = (vehicles, props?) => decodeEntityAnswer(configOf(vehicles, props)).value.config;
const pp = (over={}) => decode([car()],[prop(over)]).vehicleProperties[0];
const dec = (vehicle) => decode([vehicle]).vehicles[0];
const row = (over={}) => ({id:'vehicle_ev6',name:'EV6',soc_entity_id:'sensor.ev6_battery',capacity_kwh:77,capacity_source:'stored',onboard_phases:3,suggested_onboard_phases:null,soc_percent:40,...over});
const model = (over:any={}) => { const {props,vehicles,...rest}=over; return vehicleSourcesModel({admin:true,config:decode(vehicles||[car()],props),configAt:1000,now:2000,rows:[row()],dashboardFresh:true,savedId:null,selectedId:null,...rest}); };

describe('vehicle sources model (pure)', () => {
  it('never picks among several vehicles or ambiguous sensors by itself', () => {
    const two=[car(),car({id:'vehicle_niro',name:'Niro'})];
    expect(chooseVehicle(two,null,null)).toBeNull();
    expect(chooseVehicle(two,null,'vehicle_niro')).toBe('vehicle_niro');
    expect(chooseVehicle(two,'vehicle_ev6','vehicle_niro')).toBe('vehicle_ev6');
    expect(chooseVehicle(two,null,'guest')).toBeNull();
    const m=model({config:decode([ambiguous()])});
    expect(m.sensor.status).toBe('ambiguous');expect(m.sensor.base).toBe('');expect(m.sensor.options[0].text).toBe('Choose a sensor…');
    expect(m.sensor.options.map(o=>o.value)).toEqual(['','sensor.pack_a','sensor.pack_b']);
    expect(m.reading.stale).toBe(true);expect(m.reading.text).toMatch(/age unknown/);
  });
  it('shows an automatic and a confirmed sensor distinctly, and keeps a removed saved one visible', () => {
    expect(model().sensor.status).toBe('automatic');expect(model().sensor.base).toBe('');
    const confirmed=model({config:decode([car({source:'confirmed'})])});
    expect(confirmed.sensor.status).toBe('confirmed');expect(confirmed.sensor.base).toBe('sensor.ev6_battery');
    const removed=model({config:decode([car({source:'confirmed',selected:ent('sensor.gone','Gone')})])});
    expect(removed.sensor.status).toBe('removed');expect(removed.sensor.options.some(o=>o.value==='sensor.gone' && /no longer offered/.test(o.text))).toBe(true);expect(removed.sensor.base).toBe('sensor.gone');
    expect(model({entityState:()=>'missing'}).sensor.status).toBe('removed');
    const unavailable=model({entityState:()=>'unavailable'});expect(unavailable.sensor.status).toBe('automatic');expect(unavailable.sensor.level).toBe('warn');expect(unavailable.sensor.text).toMatch(/reports no value/);
  });
  it('reports missing capacity, reported vs entered capacity and the phase suggestion without changing anything', () => {
    const missing=model({props:[prop(noCapacity)]});
    expect(missing.properties.capacity.display).toMatch(/Missing/);expect(missing.properties.capacity.editable).toBe(true);expect(missing.properties.capacity.base).toBe('');
    const reported=model({props:[prop({capacity_source:'reported',capacity_kwh:64.8,reported_capacity_kwh:64.8,stored_capacity_kwh:null})]});
    expect(reported.properties.capacity.display).toMatch(/64.8 kWh reported by the vehicle/);expect(reported.properties.capacity.editable).toBe(false);expect(reported.properties.capacity.base).toBe('');
    const both=model({props:[prop({capacity_source:'reported',capacity_kwh:64.8,reported_capacity_kwh:64.8,stored_capacity_kwh:77})]});
    expect(both.properties.capacity.display).toMatch(/77 kWh stored from you \(not used while the vehicle reports one\)/);expect(both.properties.capacity.base).toBe('77');expect(both.properties.capacity.editable).toBe(false);
    const stored=model();expect(stored.properties.capacity.display).toMatch(/77 kWh entered by you \(used\)/);expect(stored.properties.capacity.base).toBe('77');
    const notReported=model({props:[prop({...noCapacity})]});expect(notReported.properties.capacity.display).toMatch(/reports no capacity/);
    const phase=model({rows:[row({suggested_onboard_phases:1})]});expect(phase.properties.phases.suggestion).toMatch(/Nothing was changed/);expect(phase.properties.phases.base).toBe('3');
    expect(phase.properties.phases.display).toMatch(/nothing entered/);
    const one=model({props:[prop({onboard_phases:1,stored_onboard_phases:1})]});expect(one.properties.phases.base).toBe('1');expect(one.properties.phases.display).toBe('1-phase');
  });
  it('shows capacity and phases for a vehicle whose sensor is ambiguous or missing (no dashboard row), truthfully', () => {
    const amb=model({vehicles:[ambiguous()],rows:[],props:[prop({...noCapacity,reported_known:false})]});
    expect(amb.sensor.status).toBe('ambiguous');expect(amb.propertiesMissing).toBe(false);
    expect(amb.properties.capacity.display).toMatch(/unknown until a charge-level sensor is chosen/);expect(amb.properties.capacity.display).toMatch(/Missing/);
    expect(amb.properties.capacity.editable).toBe(true);expect(amb.properties.phases.editable).toBe(true);
    const stored=model({vehicles:[ambiguous()],rows:[],props:[prop({reported_known:false})]});
    expect(stored.properties.capacity.base).toBe('77');
    const old=model({props:[]});expect(old.properties).toBeNull();expect(old.propertiesMissing).toBe(true);
    expect(renderVehicleSources(old)).toContain('could not be read');
  });
  it('treats stale configuration or dashboard as stale and withholds editing', () => {
    const old=model({configAt:1000,now:1000+120000});expect(old.stale).toBe(true);expect(old.sensor.canEdit).toBe(false);expect(old.notes.join(' ')).toMatch(/stale/);
    expect(model({failed:true}).sensor.canEdit).toBe(false);
    const dash=model({dashboardFresh:false});expect(dash.sensor.canEdit).toBe(false);expect(dash.properties.capacity.editable).toBe(true);
    expect(old.properties.capacity.editable).toBe(false);expect(old.properties.phases.editable).toBe(false);
    const old2=model({reading:{vehicleId:'vehicle_ev6',value:63,stale:true,detail:'Vehicle · 3 h ago'}});expect(old2.reading.text).toMatch(/63%.*stale or unconfirmed/);
    const other=model({reading:{vehicleId:'someone_else',value:63,stale:false,detail:'x'}});expect(other.reading.text).toMatch(/age unknown/);expect(other.reading.stale).toBe(true);
  });
  it('permission, loading, missing and removed vehicles', () => {
    expect(model({admin:false}).state).toBe('forbidden');
    expect(model({config:null,loading:true}).state).toBe('loading');
    expect(model({config:null}).state).toBe('unavailable');
    expect(model({savedId:'vehicle_old'}).notes.join(' ')).toMatch(/saved in the plan is not currently discovered/);
    const none=model({config:decode([])});expect(none.notes.join(' ')).toMatch(/No vehicle/);expect(none.sensor).toBeNull();
    expect(model({blocked:true}).canEdit).toBe(false);expect(model({conflict:true}).sensor.canEdit).toBe(false);
  });
  it('write plans: unchanged, invalid and compare-and-set values', () => {
    const v=dec(car({source:'confirmed'})), amb=dec(ambiguous());
    expect(sensorWritePlan(v,'sensor.ev6_battery')).toEqual({ok:true,changed:false});
    expect(sensorWritePlan(amb,'')).toEqual({ok:true,changed:false});
    expect(sensorWritePlan(amb,'sensor.other').ok).toBe(false);
    expect(sensorWritePlan(amb,'sensor.pack_a')).toMatchObject({changed:true,entityId:'sensor.pack_a',replacesChoice:false,expected:null});
    expect(sensorWritePlan(v,'')).toMatchObject({changed:true,entityId:null,replacesChoice:true,expected:'sensor.ev6_battery'});
    expect(propertyWritePlan(pp(),{capacity:'77.0',phases:'3'})).toEqual({ok:true,changed:false});
    expect(propertyWritePlan(pp(),{capacity:'0.5'}).ok).toBe(false);expect(propertyWritePlan(pp(),{capacity:'501'}).ok).toBe(false);expect(propertyWritePlan(pp(),{capacity:'abc'}).ok).toBe(false);
    expect(propertyWritePlan(pp(),{capacity:'80',phases:'1'})).toMatchObject({changes:{capacity_kwh:80,onboard_phases:1},expected:{capacity_kwh:77,onboard_phases:3}});
    expect(propertyWritePlan(pp(),{capacity:''})).toMatchObject({changes:{capacity_kwh:null},clearsCapacity:true});
    expect(propertyWritePlan(pp(noCapacity),{capacity:''})).toEqual({ok:true,changed:false});
    expect(propertyWritePlan(pp(noCapacity),{capacity:'60'})).toMatchObject({changes:{capacity_kwh:60},expected:{capacity_kwh:null}});
    // a reported capacity is never overridden, even if a value is sent
    expect(propertyWritePlan(pp({capacity_source:'reported',capacity_kwh:64.8,reported_capacity_kwh:64.8,stored_capacity_kwh:null}),{capacity:'10'})).toEqual({ok:true,changed:false});
    expect(propertyWritePlan(pp(),{phases:'2'}).ok).toBe(false);
    expect(propertyWritePlan(null,{}).ok).toBe(false);
  });
  it('signature changes when sensor, candidates, capacity or phases change', () => {
    const a=vehicleSignature(dec(car()),pp());
    expect(vehicleSignature(dec(car()),pp())).toBe(a);
    for (const other of [vehicleSignature(dec(car({source:'confirmed'})),pp()),vehicleSignature(dec(ambiguous()),pp()),vehicleSignature(dec(car()),pp({capacity_kwh:70,stored_capacity_kwh:70})),vehicleSignature(dec(car()),pp({onboard_phases:1,stored_onboard_phases:1})),vehicleSignature(dec(car({candidates:[ent('sensor.ev6_battery'),ent('sensor.new')]})),pp())]) expect(other).not.toBe(a);
  });
  it('parity: the shared renderer shows the same model text in sidebar and preview, escaped, with no controls when read-only', () => {
    const html=renderVehicleSources(model({config:decode([ambiguous({name:'<b>X</b>'})])}));
    expect(html).toContain('Several charge-level sensors fit');expect(html).toContain('data-vsetting="sensor"');expect(html).not.toContain('<b>X</b>');
    const preview=readFileSync('prototype/sample-adapter.js','utf8');expect(preview).toContain('vehicleSources');
    const readonly=renderVehicleSources({...model(),canEdit:false,sensor:{...model().sensor,canEdit:false},properties:{...model().properties,capacity:{...model().properties.capacity,editable:false},phases:{...model().properties.phases,editable:false}}});
    expect(readonly.match(/disabled/g).length).toBeGreaterThanOrEqual(5);
    expect(renderVehicleSources(null)).toBe('');
  });
});

// ---- the real panel with a mocked backend ----
const FIXTURE = () => read('dashboard/target_soc_two_vehicles.json');
const record = () => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40});
const morek = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const answerOf = (config) => ({api_version:1,ok:true,error:null,field_errors:[],config});
const setup = (opts:any={}) => {
  const calls:any[]=[];
  const raw=FIXTURE();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
  if (opts.rows) raw.vehicles=opts.rows;
  const state:any={vehicles:opts.vehicles || [ambiguous()],props:opts.props};
  const handlers:any={};
  const hass:any={connected:true,user:{is_admin:opts.admin!==false},callWS:(msg:any)=>{calls.push(msg);
    if(handlers[msg.type]) return handlers[msg.type](msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(raw);
    if(msg.type==='spotnav/get_settings')return Promise.resolve({api_version:1,ok:true,error:null,settings:record(),pause:{choice:null,admitted_at:null,expires_at:null}});
    if(msg.type==='spotnav/get_entity_config')return Promise.resolve(configOf(state.vehicles,state.props));
    if(msg.type==='spotnav/choose_vehicle_soc'||msg.type==='spotnav/update_vehicle')return Promise.reject(new Error('unexpected write'));
    return Promise.resolve(morek);}};
  return {calls,hass,raw,state,handlers};
};
const open = async (hass:any) => {
  const panel:any=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await tick();
  const q=(s:string)=>panel.shadowRoot.querySelector(s);
  const edit=(sel:string,value:string,type='change')=>{const el=q(sel);el.value=value;el.dispatchEvent(new Event(type,{bubbles:true}));};
  return {panel,q,edit};
};
const writes = (calls:any[]) => calls.filter(m=>m.type==='spotnav/choose_vehicle_soc'||m.type==='spotnav/update_vehicle');
const text = (panel:any) => panel.shadowRoot.querySelector('.vehicle-sources')?.textContent || '';

describe('entity config decoding of vehicle properties', () => {
  it('decodes vehicle_properties, accepts an older backend without it, and rejects malformed rows', () => {
    expect(decode([car()]).vehicleProperties[0]).toMatchObject({id:'vehicle_ev6',capacityKwh:77,capacitySource:'stored',reportedKnown:true,storedCapacityKwh:77,onboardPhases:3,storedOnboardPhases:null});
    const old=configOf([car()]);delete old.config.vehicle_properties;expect(decodeEntityAnswer(old).value.config.vehicleProperties).toEqual([]);
    for (const bad of [{...prop(),onboard_phases:2},{...prop(),capacity_source:'guess'},{...prop(),extra:1},{...prop(),reported_known:'yes'}]) expect(decodeEntityAnswer(configOf([car()],[bad])).ok).toBe(false);
  });
  it('decodes an update_vehicle success with no dashboard row (null vehicle)', () => {
    const answer={...answerOf(configOf([ambiguous()]).config),vehicle:null};
    expect(decodeVehicleWriteAnswer(answer)).toMatchObject({ok:true,value:{ok:true}});
    expect(decodeVehicleWriteAnswer({...answer,config:null}).ok).toBe(false);
  });
});

describe('vehicle sources in the real panel (mocked backend)', () => {
  it('opening and editing write nothing; an ambiguous sensor is shown and never picked', async () => {
    const {calls,hass}=setup();const {panel,q,edit}=await open(hass);
    expect(calls.some(m=>m.type==='spotnav/get_entity_config')).toBe(true);
    expect(text(panel)).toContain('Several charge-level sensors fit');
    expect(q('[data-vsetting="sensor"]').value).toBe('');
    edit('[data-vsetting="sensor"]','sensor.pack_b');
    expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('saves a chosen sensor with the vehicle, entity and the expected prior choice, once', async () => {
    const {calls,hass,state,handlers}=setup();
    handlers['spotnav/choose_vehicle_soc']=(msg:any)=>{state.vehicles=[ambiguous({selected:ent(msg.entity_id,'Pack B'),source:'confirmed'})];return Promise.resolve(configOf(state.vehicles));};
    const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="sensor"]','sensor.pack_b');q('#save-vehicle-sensor').click();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/choose_vehicle_soc',charger_id:'a',vehicle_id:'vehicle_ev6',entity_id:'sensor.pack_b',expected_entity_id:null});
    expect(text(panel)).toContain('Chosen by you: Pack B');expect(text(panel)).toContain('Sensor choice saved');expect(panel.vehicleDirty).toBe(false);panel.remove();
  });
  it('an unchanged save sends nothing', async () => {
    const {calls,hass}=setup({vehicles:[car({source:'confirmed'})]});const {panel,q}=await open(hass);
    q('#save-vehicle-sensor').click();await tick();
    expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');panel.remove();
  });
  it('a sensor chosen elsewhere after editing began is refused by the backend guard: one request, a conflict, the draft kept', async () => {
    const {calls,hass,state,handlers}=setup();
    const elsewhere=[ambiguous({selected:ent('sensor.pack_b','Pack B'),source:'confirmed'})];
    handlers['spotnav/choose_vehicle_soc']=()=>Promise.resolve({api_version:1,ok:false,error:'spotnav_conflict',field_errors:[],config:configOf(elsewhere).config});
    const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="sensor"]','sensor.pack_a');
    q('#save-vehicle-sensor').click();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({entity_id:'sensor.pack_a',expected_entity_id:null});
    expect(panel.vehicleConflict).toBe(true);expect(text(panel)).toContain('not saved');expect(text(panel)).toContain('Chosen by you: Pack B');
    expect(q('#save-vehicle-sensor').disabled).toBe(true);
    q('#save-vehicle-sensor').click();await tick();expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('a replaced saved sensor sends the saved one as the expected choice', async () => {
    const {calls,hass,state,handlers}=setup({vehicles:[ambiguous({selected:ent('sensor.pack_a','Pack A'),source:'confirmed'})]});
    handlers['spotnav/choose_vehicle_soc']=()=>Promise.resolve(configOf(state.vehicles));
    const {panel,q,edit}=await open(hass);const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    edit('[data-vsetting="sensor"]','sensor.pack_b');q('#save-vehicle-sensor').click();await tick();await tick();
    expect(writes(calls)[0]).toMatchObject({entity_id:'sensor.pack_b',expected_entity_id:'sensor.pack_a'});confirm.mockRestore();panel.remove();
  });
  it('capacity and phases are shown, editable and written for an ambiguous vehicle that has no dashboard row', async () => {
    const props=[prop({...noCapacity,reported_known:false})];
    const {calls,hass,handlers,state}=setup({props});
    handlers['spotnav/update_vehicle']=()=>Promise.resolve({...answerOf(configOf(state.vehicles,[prop({capacity_kwh:60,stored_capacity_kwh:60,capacity_source:'stored',reported_known:false,onboard_phases:1,stored_onboard_phases:1})]).config),vehicle:null});
    const {panel,q,edit}=await open(hass);
    expect(text(panel)).toContain('Several charge-level sensors fit');expect(text(panel)).toContain('unknown until a charge-level sensor is chosen');
    expect(q('[data-vsetting="capacity"]').disabled).toBe(false);
    edit('[data-vsetting="capacity"]','60','input');edit('[data-vsetting="phases"]','1');q('#save-vehicle-props').click();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/update_vehicle',vehicle_id:'vehicle_ev6',changes:{capacity_kwh:60,onboard_phases:1},expected:{capacity_kwh:null,onboard_phases:3}});
    expect(text(panel)).toContain('Capacity and phases saved');expect(text(panel)).toContain('60 kWh entered by you');expect(panel.vehicleDirty).toBe(false);panel.remove();
  });
  it('replacing or clearing a saved sensor needs confirmation', async () => {
    const {calls,hass,state,handlers}=setup({vehicles:[ambiguous({selected:ent('sensor.pack_a','Pack A'),source:'confirmed'})]});
    handlers['spotnav/choose_vehicle_soc']=()=>Promise.resolve(configOf(state.vehicles));
    const {panel,q,edit}=await open(hass);const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    expect(q('[data-vsetting="sensor"]').value).toBe('sensor.pack_a');
    edit('[data-vsetting="sensor"]','');q('#save-vehicle-sensor').click();await tick();
    expect(confirm).toHaveBeenCalled();expect(writes(calls)).toHaveLength(0);
    confirm.mockReturnValue(true);q('#save-vehicle-sensor').click();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(writes(calls)[0].entity_id).toBeNull();confirm.mockRestore();panel.remove();
  });
  it('a refused sensor shows the backend reason and keeps the draft; an unknown outcome blocks retries until reload', async () => {
    const {calls,hass,handlers,state}=setup();
    handlers['spotnav/choose_vehicle_soc']=()=>Promise.resolve({...read('entity_config/v1/vehicle_soc_refused.json'),config:configOf(state.vehicles).config});
    const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="sensor"]','sensor.pack_a');q('#save-vehicle-sensor').click();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toContain('not saved');expect(q('[data-vsetting="sensor"]').value).toBe('sensor.pack_a');
    handlers['spotnav/choose_vehicle_soc']=()=>Promise.reject(new Error('socket closed'));
    q('#save-vehicle-sensor').click();await tick();await tick();
    expect(writes(calls)).toHaveLength(2);expect(text(panel)).toContain('outcome unknown');
    q('#save-vehicle-sensor').click();await tick();expect(writes(calls)).toHaveLength(2);
    expect(q('#save-vehicle-sensor').disabled).toBe(true);panel.remove();
  });
  it('capacity and phases: compare-and-set values sent, capacity reported is read-only, conflict blocks and keeps the draft', async () => {
    const {calls,hass,handlers}=setup({vehicles:[car()]});
    const {panel,q,edit}=await open(hass);
    expect(q('[data-vsetting="capacity"]').value).toBe('77');expect(q('[data-vsetting="capacity"]').disabled).toBe(false);
    handlers['spotnav/update_vehicle']=()=>Promise.resolve({...read('vehicle/v1/update_vehicle_conflict.json'),config:configOf([car()]).config});
    edit('[data-vsetting="capacity"]','80','input');edit('[data-vsetting="phases"]','1');
    q('#save-vehicle-props').click();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/update_vehicle',vehicle_id:'vehicle_ev6',changes:{capacity_kwh:80,onboard_phases:1},expected:{capacity_kwh:77,onboard_phases:3}});
    expect(panel.vehicleConflict).toBe(true);expect(q('[data-vsetting="capacity"]').value).toBe('80');expect(q('#save-vehicle-props').disabled).toBe(true);
    q('#save-vehicle-props').click();await tick();expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('a successful property save is confirmed by the backend answer and resets the draft', async () => {
    const {calls,hass,handlers,raw}=setup({vehicles:[car()]});
    handlers['spotnav/update_vehicle']=()=>{raw.vehicles[0].capacity_kwh=80;return Promise.resolve({...read('vehicle/v1/update_vehicle_success.json'),config:configOf([car()]).config});};
    const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="capacity"]','80','input');expect(panel.vehicleDirty).toBe(true);
    q('#save-vehicle-props').click();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toContain('Capacity and phases saved');expect(text(panel)).toContain('does not wake the car');
    expect(panel.vehicleDirty).toBe(false);panel.remove();
  });
  it('invalid capacity and unchanged values send nothing; a reported capacity is not editable', async () => {
    const {calls,hass}=setup({vehicles:[car()],props:[prop({capacity_source:'reported',capacity_kwh:64.8,reported_capacity_kwh:64.8,stored_capacity_kwh:null})]});
    const {panel,q}=await open(hass);
    expect(q('[data-vsetting="capacity"]').disabled).toBe(true);expect(text(panel)).toContain('reported by the vehicle');
    q('#save-vehicle-props').click();await tick();expect(writes(calls)).toHaveLength(0);panel.remove();
    const s2=setup({vehicles:[car()]});const o2=await open(s2.hass);
    o2.edit('[data-vsetting="capacity"]','900','input');o2.q('#save-vehicle-props').click();await tick();
    expect(writes(s2.calls)).toHaveLength(0);expect(text(o2.panel)).toContain('between 1 and 500');
    o2.q('#save-vehicle-props').click();await tick();expect(writes(s2.calls)).toHaveLength(0);o2.panel.remove();
  });
  it('drafts survive a refresh and a dashboard update', async () => {
    const {hass}=setup({vehicles:[car()]});const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="capacity"]','81','input');panel.dashboardEpoch++;panel.refresh();await tick();await tick();panel.paint();
    expect(q('[data-vsetting="capacity"]').value).toBe('81');expect(panel.vehicleDirty).toBe(true);panel.remove();
  });
  it('a change by someone else while editing flags a conflict instead of saving over it', async () => {
    const {hass,raw,calls}=setup({vehicles:[car()]});const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="capacity"]','81','input');
    panel.vehicleConfig=decode([car()],[prop({capacity_kwh:70,stored_capacity_kwh:70})]);panel.vehicleConfigAt=Date.now();panel.paint();
    expect(panel.vehicleConflict).toBe(true);q('#save-vehicle-props').click();await tick();expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('a stale vehicle read blocks property saves; a non-administrator gets no configuration read and no controls', async () => {
    const {calls,hass}=setup({vehicles:[car()]});const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="capacity"]','81','input');
    panel.vehicleConfigAt=Date.now()-120000;panel.paint();expect(q('#save-vehicle-props').disabled).toBe(true);q('#save-vehicle-props').click();await tick();expect(writes(calls)).toHaveLength(0);
    void panel.saveVehicleProperties({capacity:'81'});await tick();expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('stale');panel.remove();
    const s=setup({admin:false});const o=await open(s.hass);
    expect(s.calls.some(m=>m.type==='spotnav/get_entity_config')).toBe(false);expect(text(o.panel)).toContain('Administrator permission is required');expect(o.q('#save-vehicle-sensor')).toBeNull();o.panel.remove();
  });
  it('a permission change during a save leaves the outcome unknown and a late answer from the old charger is ignored', async () => {
    let finish:any;const {calls,hass,handlers}=setup({vehicles:[car()]});
    handlers['spotnav/update_vehicle']=()=>new Promise(r=>{finish=r;});
    const {panel,q,edit}=await open(hass);
    edit('[data-vsetting="capacity"]','81','input');q('#save-vehicle-props').click();await tick();
    expect(panel.vehicleBusy).toBe(true);
    panel.hass={...hass,user:{is_admin:false}};finish(read('vehicle/v1/update_vehicle_success.json'));await tick();await tick();
    expect(panel.unknownVehicleWrites.has('a')).toBe(true);expect(text(panel)).not.toContain('Capacity and phases saved');
    expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('does not block Stop/Pause controls while a vehicle save is pending', async () => {
    const {hass,handlers}=setup({vehicles:[car()]});handlers['spotnav/update_vehicle']=()=>new Promise(()=>{});
    const {panel,q,edit}=await open(hass);
    const pause=q('#pause-auto');const wasDisabled=pause.disabled;
    edit('[data-vsetting="capacity"]','81','input');q('#save-vehicle-props').click();await tick();
    expect(panel.vehicleBusy).toBe(true);expect(q('#pause-auto').disabled).toBe(wasDisabled);panel.remove();
  });
});
