// Local browser-test entry only; never bundled into the production panel.
import fixture from '../../tests/fixtures/dashboard/target_soc_two_vehicles.json';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { dashboardAdapter } from './adapter.js';
import './panel.js';

fixture.generated_at = new Date().toISOString();
fixture.plan.proposal.periods = [{start:new Date(Date.now()+3600000).toISOString(),end:new Date(Date.now()+7200000).toISOString()}];
fixture.planning.calculated_at = fixture.generated_at;
const status={api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
if (location.search === '?panel') {
  const panel=document.createElement('spotnav-enhanced-panel');
  panel.hass={connected:true,user:{is_admin:false},callWS:async msg=>msg.type==='spotnav/list_chargers' ? {api_version:1,chargers:[{charger_id:fixture.charger.charger_id,charger_name:'Fixture charger'}]} : msg.type==='spotnav/get_dashboard' ? fixture : status};
  document.body.append(panel);
  setTimeout(()=>{const select=panel.shadowRoot.querySelector('#charger');select.value=fixture.charger.charger_id;select.dispatchEvent(new Event('change'));},100);
} else {
  document.body.classList.add('wa-dark');
  const main=document.createElement('main'); document.body.append(main);
  mountDashboard(main,dashboardAdapter(fixture,status,Date.now()));
}
