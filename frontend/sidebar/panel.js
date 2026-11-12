import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { listChargers, getDashboard, morekSchedule } from '../src/api.ts';
import { dashboardAdapter } from './adapter.js';
import { CARD_VERSION } from '../src/generated/version.ts';

export class SpotnavEnhancedPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this.generation = 0;
    this.connected = false;
  }
  connectedCallback() {
    this.connected = true;
    this.classList.add('wa-dark');
    this.shadowRoot.innerHTML = `<link rel="stylesheet" href="/spotnav-sidebar/panel.css?v=${CARD_VERSION}"><style>:host{display:block;min-height:100%;padding-bottom:env(safe-area-inset-bottom)}.hostbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px;padding-top:max(12px,env(safe-area-inset-top));background:#11151d;color:white}.hostbar label{flex:1 1 180px}.hostbar select{max-width:100%}.hostbar button,.hostbar select{font:inherit;padding:8px}.message{padding:16px;color:white;background:#11151d}</style><div class="hostbar"><button id="menu" aria-label="Open navigation">☰</button><strong>SpotNav Enhanced</strong><label>Charger <select id="charger"><option value="">Select charger</option></select></label><button id="refresh">Refresh observations</button></div><div class="message" role="status">Select a charger.</div><main></main>`;
    this.shadowRoot.querySelector('#menu').onclick = () => this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));
    this.shadowRoot.querySelector('#charger').onchange = e => {this.charger = e.target.value; this.refresh();};
    this.shadowRoot.querySelector('#refresh').onclick = () => this.refresh();
    if (this._hass) this.loadChargers();
  }
  disconnectedCallback() { this.connected=false; this.generation++; clearInterval(this.ageTimer); this.cancelStatus?.(); this.view?.dispose(); this.view=null; }
  set hass(value) {
    const was = this._hass?.connected !== false;
    this._hass=value;
    if (!this.connected) return;
    if (value?.connected === false) { this.generation++; clearInterval(this.ageTimer); this.cancelStatus?.(); this.view?.dispose(); this.view=null; this.message('Home Assistant disconnected.'); }
    else if (!this.loaded || !was) this.loadChargers();
  }
  get hass() { return this._hass; }
  message(text) { const el=this.shadowRoot.querySelector('.message'); el.textContent=text; el.hidden=!text; }
  async loadChargers() {
    const generation=++this.generation; this.loaded=true;
    try {
      const result=await listChargers(this._hass);
      if (!this.connected || generation!==this.generation) return;
      const chargers=result?.api_version===1 && Array.isArray(result.chargers) ? result.chargers.filter(c=>typeof c?.charger_id==='string' && typeof c?.charger_name==='string') : [];
      const select=this.shadowRoot.querySelector('#charger'); select.replaceChildren(new Option('Select charger',''));
      for (const charger of chargers) select.add(new Option(charger.charger_name,charger.charger_id));
      if (chargers.some(c=>c.charger_id===this.charger)) {select.value=this.charger; this.refresh();}
      else {this.charger=''; this.message(chargers.length ? 'Select a charger.' : 'No chargers available.');}
    } catch { if (this.connected && generation===this.generation) {this.loaded=false;this.message('Charger list unavailable.');} }
  }
  async refresh() {
    const generation=++this.generation, charger=this.charger, hass=this._hass;
    clearInterval(this.ageTimer);
    this.cancelStatus?.();
    this.view?.dispose(); this.view=null;
    if (!charger || !hass || hass.connected===false) {this.message('Select an available charger.');return;}
    this.message('Loading separate dashboard and Morek observations…');
    const valid=()=>this.connected && generation===this.generation && this.charger===charger && this._hass?.connected!==false;
    // Both are read-only; status never issues a composite-schedule fetch.
    const dashboardPromise=getDashboard(hass,charger);
    let timeout, cancel;
    const statusPromise=Promise.race([morekSchedule(hass,charger,'status'),new Promise((_,reject)=>{cancel=()=>{clearTimeout(timeout);reject(new Error('cancelled'));};this.cancelStatus=cancel;timeout=setTimeout(()=>reject(new Error('timeout')),10000);})]).then(value=>({value,at:Date.now(),failed:false}),()=>({value:null,at:null,failed:true})).finally(()=>{clearTimeout(timeout);if(this.cancelStatus===cancel)this.cancelStatus=null;});
    try {
      const raw=await dashboardPromise;
      if (!valid()) return;
      const initial=dashboardAdapter(raw,null,null);
      if (!initial || initial.draftKey!==charger) {this.message('Dashboard unavailable or unsupported.');return;}
      this.message(''); this.view=mountDashboard(this.shadowRoot.querySelector('main'),initial);
      const status=await statusPromise;
      if (!valid()) return;
      this.view.update(dashboardAdapter(raw,status.value,status.at,Date.now(),status.failed));
      this.ageTimer=setInterval(()=>{if(valid() && this.view) this.view.update(dashboardAdapter(raw,status.value,status.at,Date.now(),status.failed));},30000);
    } catch { if (valid()) this.message('Dashboard unavailable.'); }
  }
}
if (!customElements.get('spotnav-enhanced-panel')) customElements.define('spotnav-enhanced-panel',SpotnavEnhancedPanel);
