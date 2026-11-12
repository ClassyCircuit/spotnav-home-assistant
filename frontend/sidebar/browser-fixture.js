// Local browser-test entry only; never bundled into the production panel.
import fixture from '../../tests/fixtures/dashboard/target_soc_two_vehicles.json';

fixture.generated_at = new Date().toISOString();
fixture.plan.proposal.periods = [{start:new Date(Date.now()+3600000).toISOString(),end:new Date(Date.now()+7200000).toISOString()}];
fixture.planning.calculated_at = fixture.generated_at;
if (location.search.includes('prices')) {
  const base=Date.now()-3600000;
  fixture.prices.published_intervals=[
    {start:new Date(base).toISOString(),end:new Date(base+1800000).toISOString(),raw_price:-0.15},
    {start:new Date(base+2700000).toISOString(),end:new Date(base+6300000).toISOString(),raw_price:0.35},
    {start:new Date(base+6300000).toISOString(),end:new Date(base+14400000).toISOString(),raw_price:0.42},
  ];
}
const status={api_version:1,schedule:{supported:true,cleanup_supported:true,verified:false,sent:null,sent_at:null,ack:null,effective:null,preview:{calculated_at:new Date().toISOString(),reason:null,preview_id:'fixture-preview',profile:{chargingProfileId:42001,chargingSchedule:{startSchedule:new Date().toISOString(),chargingSchedulePeriod:[{startPeriod:0,limit:0}]}}}}};
status.schedule.readiness={control:'available',vehicle:'disconnected',vehicle_observed_at:new Date().toISOString(),transaction:'unknown',measurement:'unknown'};
if (location.search.startsWith('?panel')) {
  // Exercise the exact production bundle served by the local test server.
  const panelUrl='/spotnav-sidebar/panel.js';
  if (location.search.includes('prior-panel')) await import(`${panelUrl}?prior`);
  if (location.search.includes('with-card')) { const cardUrl='/spotnav-card.js'; await import(cardUrl); }
  await import(panelUrl);
  const panel=document.createElement('spotnav-enhanced-panel');
  let record={revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40};
  const envelope=(settings,ok=true,error=null)=>({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
  window.panelMessages=[];window.saveMode='success';
  panel.hass={connected:true,user:{is_admin:true},callWS:async msg=>{
    window.panelMessages.push(msg);
    if (location.search.includes('readonly') && (msg.type==='spotnav/manual_action' || msg.type==='spotnav/update_settings' || (msg.type==='spotnav/morek_schedule' && msg.action!=='status'))) throw Error('Write forbidden in rendering regression');
    if(msg.type==='spotnav/list_chargers')return {api_version:1,chargers:[{charger_id:fixture.charger.charger_id,charger_name:'Fixture charger'},{charger_id:'second-fixture',charger_name:'Second fixture'}]};
    if(msg.type==='spotnav/get_dashboard') {
      const answer=structuredClone(fixture);answer.charger.charger_id=msg.charger_id;
      if(window.deferDashboard && msg.charger_id===fixture.charger.charger_id)return new Promise(resolve=>window.finishDashboard=()=>resolve(answer));
      return answer;
    }
    if(msg.type==='spotnav/get_settings')return envelope(record);
    if(msg.type==='spotnav/update_settings') {if(window.saveMode==='conflict')return envelope({...record,revision:8},false,'revision_conflict');record={...msg.settings,revision:8};return envelope(record);}
    if(msg.type==='spotnav/manual_action') {
      if(msg.action==='stop'&&msg.choice==='until_resumed') {fixture.control.automatic_action='resume';fixture.control.pause_choices=[];fixture.control.pause_blocks_execution=true;fixture.control.pause={choice:'until_resumed',admitted_at:new Date().toISOString(),expires_at:null};}
      if(msg.action==='resume') {fixture.control.automatic_action='pause';fixture.control.pause_choices=['until_resumed'];fixture.control.pause_blocks_execution=false;fixture.control.pause={choice:null,admitted_at:null,expires_at:null};}
      fixture.generated_at=new Date().toISOString();return {api_version:1,ok:true,error:null,action:msg.action,choice:msg.choice ?? null};
    }
    if(msg.type==='spotnav/morek_schedule')return status;
    throw Error('Unexpected mock operation');
  }};
  document.body.append(panel);
  setTimeout(()=>{const select=panel.shadowRoot.querySelector('#charger');select.value=fixture.charger.charger_id;select.dispatchEvent(new Event('change'));},100);
} else {
  const { mountDashboard } = await import('../shared-dashboard/dashboard.js');
  const { dashboardAdapter } = await import('./adapter.js');
  document.body.classList.add('wa-dark');
  const main=document.createElement('main'); document.body.append(main);
  mountDashboard(main,dashboardAdapter(fixture,status,Date.now()));
}
