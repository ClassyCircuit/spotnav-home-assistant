import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { listChargers, getDashboard, morekSchedule, getSettings, updateSettings, performAction } from '../src/api.ts';
import { admittedAction } from '../src/model.ts';
import { decodeSettingsAnswer, formFromRecord, replacementFor } from '../src/settings.ts';
import { decodeDashboard } from '../src/validate.ts';
import { translate } from '../src/i18n/index.ts';
import { decodeMorekState, morekPanel } from '../src/morek-view.ts';
import { reconcile } from '../shared-dashboard/reconcile.js';
import { dashboardAdapter } from './adapter.js';
import { CARD_VERSION } from '../src/generated/version.ts';
import { capInput, capForSave, displayPrice } from '../shared-dashboard/price-format.js';

// A dispatched write outlives its host element, including a newly mounted panel.
const settingsWritesByConnection = new WeakMap();

export class SpotnavEnhancedPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this.generation = 0;
    this.permissionEpoch = 0;
    this.dashboardEpoch = 0;
    this.statusEpoch = 0;
    this.pendingSettingsWrites = new Map();
    this.unknownSettingsWrites = new Set();
    this.connected = false;
  }
  connectedCallback() {
    this.connected = true;
    this.classList.add('wa-dark');
    this.shadowRoot.innerHTML = `<link rel="stylesheet" href="/spotnav-sidebar/panel.css?v=${CARD_VERSION}"><style>:host{display:block;min-height:100%;padding-bottom:env(safe-area-inset-bottom)}.hostbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px;padding-top:max(12px,env(safe-area-inset-top));background:#11151d;color:white}.hostbar label{flex:1 1 180px}.hostbar select{max-width:100%}.hostbar button,.hostbar select{font:inherit;padding:8px}.message{padding:16px;color:white;background:#11151d}</style><div class="hostbar"><button id="menu" aria-label="Open navigation">☰</button><strong>SpotNav Enhanced</strong><label>Charger <select id="charger"><option value="">Select charger</option></select></label><button id="refresh">Refresh observations</button><div id="automatic-controls"><span id="pause-state">Auto state unknown.</span> <button id="pause-auto" disabled>Pause Auto until resumed</button> <button id="resume-auto" disabled>Resume Auto</button><span id="pause-notice" role="status"></span></div></div><div class="message" role="status">Select a charger.</div><main></main>`;
    const hostStyle=document.createElement('style');
    hostStyle.textContent='.hostbar label{color:#f0f3f8}.hostbar select{color:#f0f3f8;background:#202b39;border:1px solid #8191a4;border-radius:8px;min-height:42px} #automatic-controls{display:flex;flex-wrap:wrap;gap:6px;min-width:0;max-width:100%} #automatic-controls button{max-width:100%;white-space:normal}';
    this.shadowRoot.append(hostStyle);
    this.shadowRoot.querySelector('#menu').onclick = () => this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));
    this.shadowRoot.querySelector('#charger').onchange = e => {if (e.target.value===this.charger) return; this.stopObservations(); this.charger = e.target.value; this.rememberCharger(); this.refresh();};
    this.shadowRoot.querySelector('#refresh').onclick = () => this.loaded ? this.refresh() : this.loadChargers();
    this.shadowRoot.querySelector('#pause-auto').onclick = () => void this.automaticAction('stop','until_resumed');
    this.shadowRoot.querySelector('#resume-auto').onclick = () => void this.automaticAction('resume',null);
    if (this._hass) this.loadChargers();
  }
  disconnectedCallback() { this.connected=false; this.stopObservations(); }
  set hass(value) {
    if (!this.settingsWriteContext && value) {
      const key=value.connection || value;
      if (!settingsWritesByConnection.has(key)) settingsWritesByConnection.set(key,{pending:new Map(),unknown:new Set()});
      this.settingsWriteContext=settingsWritesByConnection.get(key);
      this.pendingSettingsWrites=this.settingsWriteContext.pending;
      this.unknownSettingsWrites=this.settingsWriteContext.unknown;
    }
    const was = this._hass?.connected !== false;
    const wasAdmin = this._hass?.user?.is_admin === true;
    this._hass=value;
    if (!this.connected) return;
    if (value?.connected === false) { if (was) this.stopObservations(true); this.message('Home Assistant disconnected.'); }
    else if (!this.loaded || !was) this.loadChargers();
    else if (wasAdmin !== (value?.user?.is_admin === true)) {
      this.permissionEpoch++;this.dashboardEpoch++;this.controlPermissionPending=true;
      if (this.settingsBusy) {this.settingsConflict=true;this.settingsNotice='Permission changed during save; its outcome must be checked by reloading settings.';}
      if (this.morekBusy) {if(this.morekActiveAction==='send')this.morekUncertain=true;this.morekError='Permission changed during the operation; its outcome may be unknown.';}
      if (this.autoBusy) {this.autoUncertain=true;this.autoNotice='Permission changed during the operation; its outcome may be unknown.';}
      this.paint();this.refresh();
    }
  }
  get hass() { return this._hass; }
  message(text) { const el=this.shadowRoot.querySelector('.message'); el.textContent=text; el.hidden=!text; }
  stopObservations(preserveDraft=false) {
    const dirty=preserveDraft && this.settingsDirty;
    if (dirty && this.settingsRecord) this.draftRevision=this.settingsRecord.revision;
    else if (!preserveDraft) {this.draftRevision=null;this.draftCurrency=undefined;}
    if (this.settingsBusy && this.charger) this.unknownSettingsWrites.add(this.charger);
    this.generation++;
    clearInterval(this.ageTimer); this.ageTimer=null;
    for (const cancel of this.cancellations || []) cancel();
    this.cancellations=new Set();
    this.dashboardRead=null; this.statusRead=null;
    this.rawDashboard=null; this.rawStatus=null; this.statusAt=null; this.statusFailed=false; this.dashboardFailed=false;
    this.settingsRecord=null; this.settingsLoading=false; this.settingsBusy=false; this.settingsConflict=false; this.settingsDirty=!!dirty; this.settingsNotice='';
    this.morekBusy=false; this.morekError=null; this.morekUncertain=false; this.statusEpoch=(this.statusEpoch || 0)+1; this.dashboardEpoch=(this.dashboardEpoch || 0)+1;this.autoBusy=false;this.autoUncertain=false;this.autoNotice='';this.autoExpected=null;this.controlPermissionPending=false;
    const pause=this.shadowRoot.querySelector('#pause-state');if(pause) pause.textContent='Auto state unknown.';
    for(const id of ['pause-auto','resume-auto']) {const button=this.shadowRoot.querySelector(`#${id}`);if(button)button.disabled=true;}
    if (!preserveDraft) {this.view?.dispose(); this.view=null;}
    const main=this.shadowRoot.querySelector('main');if(main)main.hidden=preserveDraft;
  }
  paint() {
    if (!this.rawDashboard) return;
    const adapter=dashboardAdapter(this.rawDashboard,this.rawStatus,this.statusAt,Date.now(),this.statusFailed,this.dashboardFailed);
    if (!adapter || adapter.draftKey!==this.charger) { this.message('Dashboard unavailable or unsupported.'); return; }
    const decoded=decodeDashboard(this.rawDashboard);
    const dashboard=decoded.ok ? decoded.value : null;
    this.paintAutomatic(dashboard);
    if (this.settingsRecord && dashboard?.settings?.revision > this.settingsRecord.revision) {this.settingsConflict=true;this.settingsNotice='Settings changed elsewhere. Reload the charger before editing again.';}
    const allowed=this._hass?.user?.is_admin===true || dashboard?.settings?.users_change_plan===true;
    if (this.settingsRecord) {
      const record=this.settingsRecord;
      const currency=dashboard?.market?.currency || null;
      if (this.settingsDirty && this.draftCurrency!==undefined && this.draftCurrency!==currency) {this.settingsConflict=true;this.settingsNotice='Price currency changed while editing. Reload settings before saving.';}
      adapter.model.capCurrency=currency;
      adapter.model.settings={target:record.target.target_percent,minimum:record.minimum_ready_by_soc,cap:capInput(record.soft_price_cap,currency),readyBy:record.departure_time,capEnabled:record.soft_price_cap!=null,capBasis:record.cap_price_basis,deadlineEnabled:record.departure_enabled};
      // The planner's nord_pool basis compares the source's converted published
      // major-unit price, even when that source includes its own charges. A
      // configured-variable-cost cap must not be drawn on this raw series.
      if (adapter.model.chart && record.revision===dashboard?.settings?.revision && record.cap_price_basis==='nord_pool' && Number.isFinite(record.soft_price_cap)) {
        adapter.model.chart.cap=displayPrice(record.soft_price_cap,currency);
      }
      adapter.model.settingsEditor=true;
      adapter.model.targetSupported=record.driver==='target_soc';
      adapter.model.policySupported=record.soft_price_cap!==undefined;
      adapter.model.canSave=allowed && !this.settingsBusy && !this.settingsConflict;
      adapter.model.settingsNotice=this.settingsNotice || (!allowed ? 'You do not have permission to change this plan.' : '');
      adapter.model.labels.settingsNote=record.driver === 'target_soc' ? 'SOC-based planning. The planning target is separate from the car’s charge limit.' : 'Manual energy mode uses a requested kWh amount, so target SOC cannot be edited here. In the SpotNav card’s Plan settings, choose target SOC mode and configure a vehicle and target.';
      adapter.model.labels.saveLabel=this.settingsBusy ? 'Saving…' : 'Save plan';
      adapter.actions.save=values=>this.savePlan(values);
      adapter.actions.reloadSettings=()=>this.reloadSettings();
      adapter.actions.edit=()=>{if(!this.settingsDirty)this.draftCurrency=currency;this.settingsDirty=true;this.paintMorek();};
    } else adapter.model.settingsNotice=this.settingsLoading ? 'Loading settings…' : (this.settingsNotice || 'Settings unavailable.');
    this.message(this.dashboardFailed ? 'Dashboard refresh failed; the last observation may be stale.' : '');
    if (this.view) this.view.update(adapter);
    else this.view=mountDashboard(this.shadowRoot.querySelector('main'),adapter);
    this.shadowRoot.querySelector('main').hidden=false;
    this.paintMorek();
  }
  paintAutomatic(dashboard) {
    const control=dashboard?.control, active=control?.pause?.choice;
    const observed=Date.parse(dashboard?.generated_at || ''), fresh=Number.isFinite(observed) && observed<=Date.now() && Date.now()-observed<=90000;
    const status=decodeMorekState(this.rawStatus), owner=status?.ownership?.recorded_owner;
    if(owner==='morek_schedule') {
      const statusFresh=!this.statusFailed && Number.isFinite(this.statusAt) && this.statusAt<=Date.now() && Date.now()-this.statusAt<=90000;
      const pause=statusFresh ? status?.schedule_pause : null;
      const intent=pause?.intent==='pause_until_resumed' ? 'Pause requested' : pause?.intent==='resume_requested' ? 'Resume requested; retained limit may remain' : pause?.intent==='none' ? 'No schedule-owned pause reported' : 'Pause intent unknown';
      const request=typeof pause?.request==='string' ? pause.request : 'unknown';
      const ack=typeof pause?.ack==='string' ? pause.ack : 'unknown';
      const from=Date.parse(pause?.coverage_start || ''), to=Date.parse(pause?.coverage_end || '');
      const coverage=Number.isFinite(from) && Number.isFinite(to) && to>from ? ` (${new Date(from).toLocaleString()} – ${new Date(to).toLocaleString()})` : ' (coverage unavailable)';
      const readback=pause?.readback==='bounded_match' ? `bounded effective readback match${coverage}` : 'readback unconfirmed';
      const canPause=fresh && statusFresh && !!control?.can_act && !this.controlPermissionPending && !this.autoBusy && !this.autoUncertain && !this.morekBusy && !this.morekUncertain && !this.settingsBusy && this._hass?.connected!==false;
      const can=canPause && status?.ownership?.completion_authorized===true;
      this.shadowRoot.querySelector('#pause-state').textContent=`${intent}; request ${request}; ACK ${ack}; ${readback}; physical charging unknown.${can ? '' : ' Controls unavailable until schedule ownership is confirmed.'}`;
      this.shadowRoot.querySelector('#pause-auto').disabled=!(canPause && admittedAction(control,'stop','until_resumed'));
      this.shadowRoot.querySelector('#resume-auto').disabled=!(can && admittedAction(control,'resume',null));
      this.shadowRoot.querySelector('#pause-notice').textContent=this.autoNotice || '';
      return;
    }
    this.shadowRoot.querySelector('#pause-state').textContent=control && fresh ? (active ? `Pause intent: ${active}; physical stop not confirmed.` : 'No pause reported.') : 'Auto state unavailable or stale.';
    const can=fresh && !!control?.can_act && !this.controlPermissionPending && !this.autoBusy && !this.autoUncertain && !this.morekBusy && !this.morekUncertain && !this.settingsBusy && this._hass?.connected!==false;
    this.shadowRoot.querySelector('#pause-auto').disabled=!(can && admittedAction(control,'stop','until_resumed'));
    this.shadowRoot.querySelector('#resume-auto').disabled=!(can && admittedAction(control,'resume',null));
    this.shadowRoot.querySelector('#pause-notice').textContent=this.autoNotice || '';
  }
  async automaticAction(action,choice) {
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass, decoded=decodeDashboard(this.rawDashboard);
    const owner=decodeMorekState(this.rawStatus)?.ownership;
    if (owner?.recorded_owner==='morek_schedule' && action!=='stop' && owner.completion_authorized!==true) return;
    const observed=decoded.ok ? Date.parse(decoded.value.generated_at || '') : NaN;
    if (!this.connected || !charger || !hass || hass.connected===false || !decoded.ok || !Number.isFinite(observed) || observed>Date.now() || Date.now()-observed>90000 || this.controlPermissionPending || this.autoBusy || this.autoUncertain || this.morekBusy || this.morekUncertain || this.settingsBusy || !decoded.value.control.can_act || !admittedAction(decoded.value.control,action,choice)) return;
    const dispatchedAt=Date.now();this.autoBusy=true;this.autoNotice='Request in progress; state not yet confirmed.';this.dashboardEpoch++;this.statusEpoch++;this.statusAt=null;this.paint();
    try {
      const result=await this.bounded(performAction(hass,charger,action,choice));
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) return;
      this.autoExpected=result.ok ? {action,choice,dispatchedAt} : null;
      this.autoNotice=result.ok ? 'Accepted; waiting for a fresh confirmed state.' : 'Request rejected; prior state is not changed here.';
    } catch {if(this.connected && generation===this.generation && charger===this.charger){this.autoUncertain=true;this.autoNotice='Request failed or outcome unknown; no retry is offered in this session.';}}
    finally {if(this.connected && generation===this.generation && charger===this.charger){this.autoBusy=false;this.paint();this.refresh();}}
  }
  reloadSettings() {
    if (!this.connected || this.settingsBusy || !this.charger || this.pendingSettingsWrites.has(this.charger)) return;
    if (!window.confirm('Discard the current draft and reload the latest settings?')) return;
    this.view?.resetDrafts();this.draftRevision=null;this.draftCurrency=undefined;this.settingsRecord=null;this.settingsConflict=false;this.settingsDirty=false;this.unknownSettingsWrites.delete(this.charger);this.settingsNotice='Loading settings…';
    void this.loadSettings();
  }
  paintMorek() {
    const target=this.shadowRoot.querySelector('#morek-debug');
    const state=decodeMorekState(this.rawStatus);
    if (!target) return;
    if (!state) {target.querySelectorAll('button').forEach(button=>{button.disabled=true;});return;}
    const fresh=morekPanel(document,state,this._hass?.user?.is_admin===true,this.morekBusy || this.settingsBusy || this.settingsDirty || this.autoBusy,this.morekError,action=>void this.morekAction(action),this.morekActiveAction,false);
    if (target.firstChild) reconcile(target.firstChild,fresh);
    else target.append(fresh);
    if (state.ownership?.reconfirmation_required && state.supported && this._hass?.user?.is_admin===true) {
      const button=document.createElement('button');
      button.type='button';button.textContent='Reconfirm schedule ownership';
      button.disabled=this.morekBusy || this.settingsBusy || this.autoBusy;
      button.addEventListener('click',()=>void this.morekAction('reconfirm_migration'));
      target.firstChild.append(button);
    }
    const send=target.querySelector('[data-morek-action="send"]');if(send && (this.morekUncertain || this.autoUncertain))send.disabled=true;
  }
  async morekAction(action) {
    const hass=this._hass, charger=this.charger, generation=this.generation, permissionEpoch=this.permissionEpoch, statusSnapshot=this.rawStatus, observedAt=this.statusAt, state=decodeMorekState(statusSnapshot);
    if (!this.connected || hass?.connected===false || hass?.user?.is_admin!==true || !charger || !state || this.morekBusy || this.autoBusy || !['status','send','fetch','clear','reconfirm_migration'].includes(action)) return;
    if (action==='reconfirm_migration' && state.ownership?.reconfirmation_required!==true) return;
    if (action!=='status' && !state.supported) return;
    if (action==='clear' && state.cleanup_supported!==true) return;
    if (this.settingsBusy || (action==='send' && this.settingsDirty)) return;
    if (action==='send' && (this.morekUncertain || this.autoUncertain || state.outcomes?.uncertain || !state.preview?.profile || state.preview.reason!==null || !state.preview.preview_id || !this.statusAt || Date.now()-this.statusAt>90000)) return;
    const previewId=state.preview?.preview_id, configured=state.configured_id, resolved=state.resolved_id, dashboardSnapshot=this.rawDashboard;
    // Recheck at the dispatch boundary, independently of the diagnostic view's
    // confirmation and disabled state. A request already sent cannot be recalled.
    if (action==='send' && !window.confirm('Confirm sending the current preview. The final 0 A limit may persist.')) return;
    if (action==='clear' && !window.confirm('Confirm selective removal of SpotNav profile 42001. Effective limits may increase.')) return;
    if (action==='reconfirm_migration' && !window.confirm('Reconfirm schedule ownership for this connection? This does not verify charger protection, profile inventory or physical charging. A previous schedule or 0 A limit may remain.')) return;
    const latest=decodeMorekState(this.rawStatus);
    const dashboard=decodeDashboard(this.rawDashboard);
    const generated=dashboard.ok ? Date.parse(dashboard.value.generated_at || '') : NaN;
    if (action==='send' && (this.rawDashboard!==dashboardSnapshot || !dashboard.ok || !Number.isFinite(generated) || generated>Date.now() || Date.now()-generated>90000 || dashboard.value.control.pause?.choice!=='until_resumed' || !dashboard.value.control.pause_blocks_execution)) return;
    if (!this.connected || this.generation!==generation || this.permissionEpoch!==permissionEpoch || this.charger!==charger || this.rawStatus!==statusSnapshot || this.statusAt!==observedAt || this._hass?.user?.is_admin!==true || this._hass?.connected===false || this.morekBusy || this.settingsBusy || this.autoBusy || !latest || latest.configured_id!==configured || latest.resolved_id!==resolved || (action!=='status' && !latest.supported) || (action==='send' && (this.morekUncertain || this.autoUncertain || latest.outcomes?.uncertain || !latest.preview?.preview_id || latest.preview.preview_id!==previewId || latest.preview.reason!==null || !latest.preview.profile || this.settingsDirty || !this.statusAt || Date.now()-this.statusAt>90000)) || (action==='clear' && (!latest.supported || latest.cleanup_supported!==true))) return;
    this.morekBusy=true;this.morekActiveAction=action;this.morekError=null;this.statusEpoch++;
    this.paintMorek();
    try {
      const raw=await this.bounded(morekSchedule(hass,charger,action,previewId));
      if (action==='reconfirm_migration') {this.morekError=null;return;}
      const result=decodeMorekState(raw);
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) return;
      if (!result) {if(action==='send')this.morekUncertain=true;this.morekError='Response unavailable; operation outcome may be unknown.';}
      else {this.rawStatus={api_version:1,schedule:result};this.statusAt=action==='status' ? Date.now() : null;this.statusFailed=action!=='status';}
    } catch {if(this.connected && generation===this.generation && charger===this.charger) {if(action==='send')this.morekUncertain=true;this.morekError='Request failed or outcome unknown; do not assume the operation did not apply.';}}
    finally {
      if (this.connected && generation===this.generation && charger===this.charger) {
        this.morekBusy=false;this.morekActiveAction=null;this.paint();
        this.refresh();
      }
    }
  }
  async loadSettings() {
    if (this.settingsLoading || this.settingsRecord || !this.charger) return;
    const generation=this.generation, charger=this.charger, hass=this._hass;
    this.settingsLoading=true;
    try {
      const decoded=decodeSettingsAnswer(await this.bounded(getSettings(hass,charger)));
      if (!this.connected || generation!==this.generation || charger!==this.charger) return;
      if (!decoded.ok || !decoded.value.ok || !decoded.value.settings) {this.settingsNotice='Settings unavailable.';return;}
      this.settingsRecord=decoded.value.settings;
      const unknown=this.unknownSettingsWrites.has(charger) || this.pendingSettingsWrites.has(charger);
      this.settingsConflict=unknown || (this.settingsDirty && this.draftRevision!=null && this.draftRevision!==this.settingsRecord.revision);
      this.settingsNotice=unknown ? 'A previous dispatched save has an unknown outcome. Wait for it to settle, then explicitly reload settings.' : this.settingsConflict ? 'Settings changed while disconnected. Reload settings before saving this draft.' : '';
    } catch { if (this.connected && generation===this.generation) this.settingsNotice='Settings unavailable.'; }
    finally { if (this.connected && generation===this.generation) {this.settingsLoading=false;this.paint();} }
  }
  async savePlan(values) {
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass, record=this.settingsRecord;
    const decoded=decodeDashboard(this.rawDashboard);
    const allowed=hass?.user?.is_admin===true || (decoded.ok && decoded.value.settings?.users_change_plan===true);
    if (!this.connected || hass?.connected===false || !charger || !record || this.settingsBusy || this.pendingSettingsWrites.has(charger) || this.morekBusy || this.autoBusy || this.settingsConflict || !allowed) {this.settingsNotice='Save unavailable or permission denied.';this.paint();return;}
    if (record.driver!=='target_soc' && values.target!==String(record.target.target_percent ?? '')) {this.settingsNotice='Target SOC cannot be changed in manual energy mode.';this.paint();return;}
    const form={...formFromRecord(record),targetPercent:values.target,minimumReadySoc:values.minimum,capValue:capForSave(values.cap,decoded.ok ? decoded.value.market?.currency : null,record.soft_price_cap),capEnabled:values.capEnabled,capBasis:values.capBasis,deadlineEnabled:values.deadlineEnabled,deadlineTime:values.readyBy};
    const check=replacementFor('plan',record,form);
    if (!check.ok) {this.settingsNotice=translate('en',check.errorKey);this.paint();return;}
    if (!check.changed) {this.settingsNotice='No changes to save.';this.paint();return;}
    this.settingsBusy=true;this.statusEpoch++;this.statusAt=null;this.settingsNotice='Saving…';this.paint();
    try {
      const request=updateSettings(hass,charger,record.revision,check.body);
      this.pendingSettingsWrites.set(charger,request);
      request.finally(()=>{if(this.pendingSettingsWrites.get(charger)===request)this.pendingSettingsWrites.delete(charger);}).catch(()=>{});
      const answer=decodeSettingsAnswer(await this.bounded(request));
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) return;
      if (!answer.ok) {this.settingsConflict=true;this.settingsNotice='Save response unavailable; outcome unknown. Reload before retrying.';}
      else if (answer.value.ok) {this.settingsRecord=answer.value.settings;this.settingsDirty=false;this.draftRevision=null;this.draftCurrency=undefined;this.settingsNotice='Saved and confirmed.';this.view?.resetDrafts();this.dashboardEpoch++;}
      else if (answer.value.code==='revision_conflict') {this.settingsConflict=true;this.settingsNotice='Settings conflict. Reload the charger and review the new values.';}
      else if (answer.value.code==='spotnav_settings_reconcile_failed') {this.settingsConflict=true;this.settingsNotice='Settings may be saved, but replanning failed; reload and inspect confirmed settings.';}
      else this.settingsNotice='Settings save rejected.';
    } catch {this.unknownSettingsWrites.add(charger);if(this.connected && generation===this.generation) {this.settingsConflict=true;this.settingsNotice='Save outcome unknown; the dispatched request may still complete. Wait for it to settle, then reload before retrying.';}}
    finally {if(this.connected && generation===this.generation) {this.settingsBusy=false;this.paint();this.refresh();}}
  }
  bounded(request) {
    let timer, cancel;
    const cancellations=this.cancellations ||= new Set();
    const timeout=new Promise((_,reject)=>{
      cancel=()=>reject(new Error('cancelled'));
      cancellations.add(cancel);
      timer=setTimeout(()=>reject(new Error('timeout')),10000);
    });
    return Promise.race([request,timeout]).finally(()=>{clearTimeout(timer);cancellations.delete(cancel);});
  }
  rememberCharger() {
    try { if (this.charger) sessionStorage.setItem('spotnav.sidebar.charger',this.charger); else sessionStorage.removeItem('spotnav.sidebar.charger'); } catch { /* Storage is optional. */ }
  }
  async loadChargers() {
    const generation=++this.generation; this.loaded=true;
    try {
      const result=await listChargers(this._hass);
      if (!this.connected || this._hass?.connected===false || generation!==this.generation) return;
      if (result?.api_version!==1 || !Array.isArray(result.chargers)) throw new Error('Invalid charger list');
      const chargers=result.chargers.filter(c=>typeof c?.charger_id==='string' && c.charger_id && typeof c?.charger_name==='string');
      const select=this.shadowRoot.querySelector('#charger'); select.replaceChildren(new Option('Select charger',''));
      for (const charger of chargers) select.add(new Option(charger.charger_name,charger.charger_id));
      let remembered=''; try { remembered=sessionStorage.getItem('spotnav.sidebar.charger') || ''; } catch { /* Storage is optional. */ }
      const previous=this.charger || remembered;
      const chosen=chargers.some(c=>c.charger_id===previous) ? previous : chargers.length===1 ? chargers[0].charger_id : '';
      if (chosen!==this.charger && this.view) this.stopObservations();
      this.charger=chosen; select.value=chosen;
      if (chosen) {this.rememberCharger();this.refresh();}
      else {this.rememberCharger();this.message(chargers.length ? 'Select a charger.' : 'No chargers available.');}
    } catch { if (this.connected && generation===this.generation) {this.stopObservations(true);this.loaded=false;this.message('Charger list unavailable. Use Refresh observations to retry.');} }
  }
  refresh() {
    const generation=this.generation, charger=this.charger, hass=this._hass;
    if (!charger || !hass || hass.connected===false) {this.message('Select an available charger.');return;}
    if (!this.settingsRecord && !this.settingsLoading) void this.loadSettings();
    const valid=()=>this.connected && generation===this.generation && this.charger===charger && this._hass?.connected!==false;
    if (!this.ageTimer) this.ageTimer=setInterval(()=>{if(valid()) { this.paint(); this.refresh(); }},30000);
    if (!this.rawDashboard) this.message('Loading separate dashboard and Morek observations…');
    // Independent single-flight reads: a stuck status never delays the dashboard.
    if (!this.dashboardRead) {
      // A timeout does not cancel callWS: keep its single-flight slot until the
      // underlying request settles, so repeated ticks cannot leak requests.
      const epoch=this.dashboardEpoch; const pending=getDashboard(hass,charger); this.dashboardRead=pending;
      pending.finally(()=>{if(this.dashboardRead===pending){this.dashboardRead=null;if(valid() && epoch!==this.dashboardEpoch)this.refresh();}}).catch(()=>{});
      this.bounded(pending).then(raw=>{
        if (!valid() || epoch!==this.dashboardEpoch) return;
        const decoded=dashboardAdapter(raw,this.rawStatus,this.statusAt);
        if (!decoded || decoded.draftKey!==charger) {this.dashboardFailed=true;if(this.view)this.paint();else this.message('Dashboard unavailable or unsupported.');return;}
        this.dashboardFailed=false; this.rawDashboard=raw;this.controlPermissionPending=false;
        const control=decodeDashboard(raw).value?.control;
        const generated=Date.parse(raw.generated_at || '');
        if(this.autoExpected && control && Number.isFinite(generated) && generated>=this.autoExpected.dispatchedAt && generated<=Date.now() && (this.autoExpected.action==='stop' ? control.pause?.choice===this.autoExpected.choice : control.pause?.choice==null)) {this.autoNotice='Confirmed by a fresh dashboard observation.';this.autoExpected=null;}
        this.paint();
      }).catch(()=>{if(valid() && epoch===this.dashboardEpoch) {this.dashboardFailed=true;if(this.view)this.paint();else this.message('Dashboard unavailable.');}});
    }
    if (!this.statusRead && !this.morekBusy && !this.settingsBusy) {
      const epoch=this.statusEpoch;
      const pending=morekSchedule(hass,charger,'status'); this.statusRead=pending;
      pending.finally(()=>{if(this.statusRead===pending){this.statusRead=null;if(valid() && epoch!==this.statusEpoch)this.refresh();}}).catch(()=>{});
      this.bounded(pending).then(raw=>{
        if (!valid() || epoch!==this.statusEpoch) return; this.rawStatus=raw;this.statusAt=Date.now();this.statusFailed=false;this.paint();
      }).catch(()=>{if(valid() && epoch===this.statusEpoch) {this.statusFailed=true;this.paint();}});
    }
  }
}
if (!customElements.get('spotnav-enhanced-panel')) customElements.define('spotnav-enhanced-panel',SpotnavEnhancedPanel);
