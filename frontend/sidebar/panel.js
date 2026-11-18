import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { listChargers, getDashboard, getSessions, getPriceDays, getPriceInsights, getChargingHistory, morekSchedule, getSettings, updateSettings, performAction, chargeNowAction, getEntityConfig, setVehicleSoc, updateVehicle } from '../src/api.ts';
import { createPriceDays } from '../shared-dashboard/price-days.js';
import { createHistoryDay, localDate, requestDayPrices, priceReviewNote } from '../shared-dashboard/history-day.js';
import { createPriceInsights } from '../shared-dashboard/price-insights.js';
import { localDaySpan } from './price-chart.js';
import { decodeEntityAnswer, decodeVehicleWriteAnswer, entityErrorKey, fieldErrorKey, ENTITY_CONFLICT } from '../src/entity-config.ts';
import { vehicleSourcesModel, vehicleSignature, chooseVehicle, sensorWritePlan, propertyWritePlan, CONFIG_REFRESH_MS } from './vehicle-sources.js';
import { marketCostMethods } from './market-costs-panel.js';
import { planParamMethods } from './plan-params-panel.js';
import { notifySetupMethods } from './notify-setup-panel.js';
import { admittedAction, chargerCarsOf } from '../src/model.ts';
import { decodeSettingsAnswer, formFromRecord, replacementFor } from '../src/settings.ts';
import { decodeDashboard } from '../src/validate.ts';
import { translate } from '../src/i18n/index.ts';
import { decodeMorekState, morekPanel } from '../src/morek-view.ts';
import { reconcile } from '../shared-dashboard/reconcile.js';
import { dashboardAdapter } from './adapter.js';
import { createLogViewer } from './log-viewer.js';
import { recoveryBanner } from './recovery-banner.js';
import { scheduleNotes } from './schedule-check.js';
import { chargeSession } from './charge-session.js';
import { CARD_VERSION } from '../src/generated/version.ts';
import { capInput, capForSave, displayPrice } from '../shared-dashboard/price-format.js';
import { observationFreshness } from '../src/observation-freshness.ts';
import { chargeNowBlocker, chargeNowPrice, chargeNowSelection, chargeNowStatus } from './charge-now.js';

const fresh = (timestamp, failed = false) => observationFreshness(timestamp, Date.now(), failed) === 'fresh';
const dashboardFresh = (dashboard, failed) => fresh(Date.parse(dashboard?.generated_at || ''), failed);

// A dispatched write outlives its host element, including a newly mounted panel.
const settingsWritesByConnection = new WeakMap();
const chargeWritesByConnection = new WeakMap();
const vehicleWritesByConnection = new WeakMap();

function actionFailure(code, action) {
  const reasons={
    spotnav_action_unavailable:'The action is no longer available. Refresh and check the current Auto state.',
    spotnav_action_failed:'The action failed. Check the current Auto state before proceeding.',
    schedule_owner_unavailable:'Schedule ownership is unavailable. Review Morek status before proceeding.',
    identity_unresolved:'The charger identity could not be confirmed. Check the Morek connection.',
    identity_changed:'The charger identity changed. Refresh and check the Morek connection.',
    resume_unavailable:'Resume is blocked by a missing pause intent, a charger removal of unknown outcome or a pending Stop. Review Morek status.',
    resume_interrupted:'Resume was interrupted by a Stop or a state change. Refresh before deciding what to do.',
    ownership_blocked:'Connector ownership blocks this action. Review Morek status.',
    legacy_execution_ownership_blocked:`${action==='resume' ? 'Resume' : 'The action'} was refused before taking effect because legacy control is blocked by ownership or admission. Review fresh Morek status.`,
    spotnav_action_reconcile_failed:'The request was recorded, but follow-up failed or was interrupted. Check fresh status; a newer Stop may take precedence.',
    spotnav_action_outcome_unknown:'The request outcome is unknown. Check fresh status; do not retry blindly.'
  };
  return `${reasons[code] || 'The request could not be confirmed. Check fresh status before proceeding.'} (${code || 'unknown_code'})`;
}

function admissionDetail(status) {
  const reason=status?.ownership?.legacy_admission?.reason;
  const descriptions={
    ownership_missing:'The ownership record is missing. Automatic clean initialization is pending or blocked; an old profile or final 0 A may remain.',
    ownership_transition:'An ownership transition is in progress or incomplete; review migration status before a supervised recovery.',
    retained_profile_exit_held:'Legacy handover is held because a retained profile may remain; review it before any recovery.',
    lifecycle_initializing:'A startup or reconnect lifecycle barrier is active; wait for a fresh status and review recovery if it persists.',
    connector_quiescing:'Connector migration or quiescing is active; review recovery status.',
    legacy_not_owner:'The connector is not owned by legacy control; review the recorded schedule owner and recovery status.',
    stale_generation:'A Stop or connector state change interrupted admission; preserve the Stop and refresh status.',
    identity_unresolved:'The physical connector identity is unresolved; check the Morek connection.',
    ownership_unavailable:'Ownership evidence is unavailable; review the Morek diagnostics.',
    ownership_malformed:'The ownership record is malformed; seek supervised recovery without replacing it.',
    ownership_conflict:'Ownership bindings conflict; review the charger bindings.',
  };
  if (status?.ownership?.legacy_admission?.allowed === true) return 'The current read-only admission check is now allowed; it does not establish why the earlier request was refused.';
  const current=descriptions[reason] || `The current admission reason is ${reason || 'unknown'}; review Morek diagnostics before a supervised decision.`;
  const migration={
    protection_conflict_unresolved:'Automatic initialization is blocked by a linked site regulator; review the protection conflict.',
    profile_outcome_uncertain:'A recorded profile outcome is uncertain and may have applied; automatic initialization is blocked.',
    profile_outcome_unavailable:'Existing outcome evidence is unsettled or unavailable; automatic initialization is blocked.',
    legacy_profile_history_invalid:'Historical profile evidence is malformed; automatic initialization is blocked.',
    settings_unavailable:'The saved settings and pause cannot be verified.',
    pause_unavailable:'A durable active pause is required for clean initialization.',
    initialization_unavailable:'Initialization could not verify storage; review Morek diagnostics.',
    initialization_interrupted:'Initialization was interrupted by a Stop, identity or lifecycle change.'
  }[status?.ownership?.recovery?.migration_result];
  const missing=status?.ownership?.record_state==='missing' && reason!=='ownership_missing' ? ` ${descriptions.ownership_missing}` : '';
  return `${current}${migration ? ` ${migration}` : ''}${missing}`;
}

export function ownedResumeOffered(status) {
  // Stage 19.9a: while the previous upload is unknown a Resume is still selectable. It is recorded as a durable
  // pending request (the Pause stays in force) and the guarded recovery sends a fresh schedule; the backend decides.
  if (status?.ownership?.recorded_owner==='morek_schedule' && status?.schedule_pause?.resume_recoverable===true &&
      status?.schedule_pause?.intent==='pause_until_resumed' && status?.schedule_pause?.request!=='stop_pending' &&
      status?.schedule_pause?.request!=='resume_pending') return true;
  return status?.ownership?.recorded_owner==='morek_schedule' && status?.ownership?.completion_authorized===true &&
    (status?.schedule_pause?.intent==='pause_until_resumed' || (status?.schedule_pause?.intent==='resume_requested' && status?.schedule_pause?.request==='resume_requires_confirmation')) &&
    typeof status?.schedule_pause?.request==='string' && status.schedule_pause.request!=='stop_pending' &&
    status?.outcomes?.uncertain===false;
}

export function ownedResumeReason(status) {
  if (status?.schedule_pause?.request==='resume_pending') return 'Resume is requested and saved. The previous upload outcome stays unknown; SpotNav sends a fresh schedule automatically when the charger is reachable' + (status?.reconciliation?.unknown_recovery?.next_attempt_at ? ` (next attempt ${new Date(status.reconciliation.unknown_recovery.next_attempt_at).toLocaleTimeString()})` : '') + '. A later Stop or Pause cancels it.';
  if (status?.outcomes?.uncertain===true) return 'A profile outcome is uncertain and cannot be resumed from here; check the charger.';
  if (status?.outcomes?.uncertain!==false) return 'Profile outcome evidence is unavailable.';
  if (status?.schedule_pause?.request==='stop_pending') return 'A person Stop is pending.';
  if (status?.schedule_pause?.intent==='resume_requested') return 'Resume is already requested.';
  return 'No eligible schedule-owned pause is reported.';
}

export class SpotnavEnhancedPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this.generation = 0;
    this.permissionEpoch = 0;
    this.priceDays = null;
    this.historyDay = null;
    this.priceInsights = null;
    this.dashboardEpoch = 0;
    this.statusEpoch = 0;
    this.pendingSettingsWrites = new Map();
    this.unknownSettingsWrites = new Set();
    this.pendingVehicleWrites = new Map();
    this.unknownVehicleWrites = new Set();
    this.vehicleConfig = null;this.vehicleConfigAt = null;this.vehicleConfigFailed = false;this.vehicleLoading = false;
    this.vehicleSelected = null;this.vehicleBase = null;this.vehicleDirty = false;this.vehicleBusy = false;this.vehicleConflict = false;this.vehicleNotice = '';
    this.autoNotice = '';
    this.initCosts();
    this.initParams();
    this.initNotify();
    this.connected = false;
  }
  connectedCallback() {
    this.connected = true;
    this.classList.add('wa-dark');
    this.shadowRoot.innerHTML = `<link rel="stylesheet" href="/spotnav-sidebar/panel.css?v=${CARD_VERSION}"><style>:host{display:block;min-height:100%;padding-bottom:env(safe-area-inset-bottom);background:var(--sn-bg,#11151d)}.hostbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px;padding-top:max(12px,env(safe-area-inset-top));background:var(--sn-surface,#11151d);border-bottom:1px solid var(--sn-line,#25395a);color:white}.hostbar label{flex:1 1 180px}.hostbar select{max-width:100%}.hostbar button,.hostbar select{font:inherit;padding:8px}.message{padding:16px;color:white;background:var(--sn-bg,#11151d)}main[data-sn-layout="compact"]~*:last-child{margin-bottom:calc(var(--sn-nav-h,64px) + env(safe-area-inset-bottom,0px))}</style><div class="hostbar"><button id="menu" aria-label="Open navigation">☰</button><strong>SpotNav Enhanced</strong><label>Charger <select id="charger"><option value="">Select charger</option></select></label><button id="refresh">Refresh observations</button><div id="automatic-controls"><span id="pause-state">Auto state unknown.</span> <button id="pause-auto" disabled>Pause Auto until resumed</button> <button id="resume-auto" disabled>Resume Auto</button><span id="pause-notice" role="status"></span></div><section id="charge-controls" aria-label="Charge Now"><details id="charge-options"><summary>Duration / change end</summary><div class="cn-fields"><label>Duration <select id="charge-duration"><option value="30">30 minutes</option><option value="60" selected>1 hour</option><option value="120">2 hours</option><option value="180">3 hours</option><option value="custom">Custom end time</option></select></label><label id="custom-label" hidden>End time <input id="charge-end" type="datetime-local"></label><button id="charge-replace" type="button" hidden>Replace Charge Now end</button></div></details><div class="cn-actions"><button id="charge-now" disabled>Charge Now</button></div><span id="charge-state" role="status">Charge Now status unavailable.</span><span id="charge-notice" role="status"></span></section></div><section id="charge-session" hidden></section><section id="schedule-check" hidden></section><div id="recovery-banner" role="alert" hidden></div><div class="message" role="status">Select a charger.</div><main></main>`;
    const hostStyle=document.createElement('style');
    hostStyle.textContent='.hostbar label{color:#f0f3f8}.hostbar select,.hostbar input{color:#f0f3f8;background:#202b39;border:1px solid #8191a4;border-radius:8px;min-height:42px} #automatic-controls{display:flex;flex-wrap:wrap;gap:6px;min-width:0;max-width:100%} #automatic-controls button,#charge-controls button{max-width:100%;white-space:normal}';
    this.shadowRoot.append(hostStyle);
    this.shadowRoot.querySelector('#menu').onclick = () => this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));
    this.shadowRoot.querySelector('#charger').onchange = e => {if (e.target.value===this.charger) return; this.stopObservations(); this.charger = e.target.value; this.rememberCharger(); this.refresh();};
    this.shadowRoot.querySelector('#refresh').onclick = () => this.loaded ? this.refresh() : this.loadChargers();
    this.shadowRoot.querySelector('#pause-auto').onclick = () => void this.automaticAction('stop','until_resumed');
    this.shadowRoot.querySelector('#resume-auto').onclick = () => void this.automaticAction('resume',null);
    this.shadowRoot.querySelector('#charge-now').onclick = () => void this.chargeAction(this.rawStatus?.schedule?.charge_now?.state==='active' ? 'return_to_auto' : 'charge_now');
    this.shadowRoot.querySelector('#charge-replace').onclick = () => void this.chargeAction('charge_now');
    this.shadowRoot.querySelector('#charge-duration').onchange = e => {this.shadowRoot.querySelector('#custom-label').hidden=e.target.value!=='custom';};
    this.logViewer=createLogViewer(()=>this._hass);this.logViewer.hidden=this._hass?.user?.is_admin!==true;this.shadowRoot.append(this.logViewer);
    if (this._hass) this.loadChargers();
  }
  disconnectedCallback() { this.connected=false; this.stopObservations(); this.logViewer?.destroy(); }
  set hass(value) {
    if (!this.settingsWriteContext && value) {
      const key=value.connection || value;
      if (!settingsWritesByConnection.has(key)) settingsWritesByConnection.set(key,{pending:new Map(),unknown:new Set()});
      this.settingsWriteContext=settingsWritesByConnection.get(key);
      this.pendingSettingsWrites=this.settingsWriteContext.pending;
      this.unknownSettingsWrites=this.settingsWriteContext.unknown;
    }
    if (!this.vehicleWriteContext && value) {
      const key=value.connection || value;
      if (!vehicleWritesByConnection.has(key)) vehicleWritesByConnection.set(key,{pending:new Map(),unknown:new Set()});
      this.vehicleWriteContext=vehicleWritesByConnection.get(key);
      this.pendingVehicleWrites=this.vehicleWriteContext.pending;this.unknownVehicleWrites=this.vehicleWriteContext.unknown;
    }
    this.bindCostContext(value);
    if (!this.chargeWriteContext && value) {
      const key=value.connection || value;
      if (!chargeWritesByConnection.has(key)) chargeWritesByConnection.set(key,{pending:new Map(),unknown:new Set(),expected:new Map()});
      this.chargeWriteContext=chargeWritesByConnection.get(key);
      this.chargePending=this.chargeWriteContext.pending;this.chargeUnknown=this.chargeWriteContext.unknown;this.chargeExpected=this.chargeWriteContext.expected;
    }
    const was = this._hass?.connected !== false;
    const wasAdmin = this._hass?.user?.is_admin === true;
    this._hass=value;
    if (this.logViewer) this.logViewer.hidden=value?.user?.is_admin!==true;
    if (!this.connected) return;
    if (value?.connected === false) { if (was) this.stopObservations(true); this.message('Home Assistant disconnected.'); }
    else if (!this.loaded || !was) this.loadChargers();
    else if (wasAdmin !== (value?.user?.is_admin === true)) {
      this.permissionEpoch++;this.dashboardEpoch++;this.controlPermissionPending=true;
      if (this.settingsBusy) {this.settingsConflict=true;this.settingsNotice='Permission changed during save; its outcome must be checked by reloading settings.';}
      if (this.morekBusy) {if(this.morekActiveAction==='send')this.morekUncertain=true;this.morekError='Permission changed during the operation; its outcome may be unknown.';}
      if (this.vehicleBusy && this.charger) {this.unknownVehicleWrites.add(this.charger);this.vehicleConflict=true;this.vehicleNotice='Permission changed during the vehicle save; its outcome must be checked by reloading.';}
      this.vehicleConfig=null;this.vehicleConfigAt=null;this.vehicleLoading=false;
      if (this.costBusy && this.charger) {this.unknownCostWrites.add(this.charger);this.costConflict=true;this.costNotice='Permission changed during the market/cost save; its outcome must be checked by reloading.';}
      this.marketOptions=null;this.marketOptionsAt=null;
      if (this.paramBusy && this.charger) {this.unknownSettingsWrites.add(this.charger);this.paramConflict=true;this.paramNotice='Permission changed during the parameter save; its outcome must be checked by reloading.';}
      if (this.notifyBusy && this.charger) {this.unknownSettingsWrites.add(this.charger);this.notifyConflict=true;this.notifyNotice='Permission changed during the notification save; its outcome must be checked by reloading.';}
      if (this.autoBusy) {this.autoUncertain=true;this.autoNotice='Permission changed during the operation; its outcome may be unknown.';}
      if (this.chargeBusy && this.charger) {this.chargeUnknown?.add(this.charger);this.chargeNotice='Permission changed during the request; outcome unknown. Do not retry blindly.';}
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
    if (this.chargeBusy && this.charger) this.chargeUnknown?.add(this.charger);
    if (this.vehicleBusy && this.charger) this.unknownVehicleWrites.add(this.charger);
    if (this.costBusy && this.charger) this.unknownCostWrites.add(this.charger);
    if (this.paramBusy && this.charger) this.unknownSettingsWrites.add(this.charger);
    const paramDirty=preserveDraft && this.paramDirty, paramBase=preserveDraft ? this.paramBase : null;
    this.paramBusy=false;this.paramConflict=false;this.paramNotice='';this.paramAwaitingRead=false;this.paramDirty=!!paramDirty;this.paramBase=paramBase;
    if (this.notifyBusy && this.charger) this.unknownSettingsWrites.add(this.charger);
    const notifyDirty=preserveDraft && this.notifyDirty, notifyBase=preserveDraft ? this.notifyBase : null;
    this.notifyBusy=false;this.notifyConflict=false;this.notifyNotice='';this.notifyAwaitingRead=false;this.notifyDirty=!!notifyDirty;this.notifyBase=notifyBase;
    const costDirty=preserveDraft && this.costDirty, costArea=preserveDraft ? this.marketArea : null, costBase=preserveDraft ? this.costBase : null, costFee=preserveDraft && this.costFeeEdited;
    this.marketOptions=null;this.marketOptionsAt=null;this.marketOptionsFailed=false;this.marketLoading=false;this.costBusy=false;this.costConflict=false;this.costNotice='';this.costAwaitingRead=false;this.costDirty=!!costDirty;this.marketArea=costArea;this.costBase=costBase;this.costFeeEdited=!!costFee;
    const vehicleDirty=preserveDraft && this.vehicleDirty;
    this.vehicleConfig=null;this.vehicleConfigAt=null;this.vehicleConfigFailed=false;this.vehicleLoading=false;this.vehicleBusy=false;this.vehicleConflict=false;this.vehicleNotice='';this.vehicleDirty=!!vehicleDirty;
    if (!preserveDraft) {this.vehicleBase=null;this.vehicleSelected=null;}
    this.chargeBusy=false;this.chargeNotice='';this.learningNotice='';
    this.generation++;
    this.priceDays?.dispose();this.priceDays=null;
    this.historyDay?.dispose();this.historyDay=null;this.priceReview=null;
    this.priceInsights?.dispose();this.priceInsights=null;
    clearInterval(this.ageTimer); this.ageTimer=null;
    for (const cancel of this.cancellations || []) cancel();
    this.cancellations=new Set();
    this.dashboardRead=null; this.statusRead=null;
    this.rawDashboard=null; this.rawStatus=null; this.statusAt=null; this.statusFailed=false; this.dashboardFailed=false;
    this.settingsRecord=null; this.settingsLoading=false; this.settingsBusy=false; this.settingsConflict=false; this.settingsDirty=!!dirty; this.settingsNotice='';
    this.morekBusy=false; this.morekError=null; this.morekUncertain=false; this.statusEpoch=(this.statusEpoch || 0)+1; this.dashboardEpoch=(this.dashboardEpoch || 0)+1;this.autoBusy=false;this.autoUncertain=false;this.autoNotice='';this.autoRefusalAt=null;this.autoExpected=null;this.controlPermissionPending=false;
    const pause=this.shadowRoot.querySelector('#pause-state');if(pause) pause.textContent='Auto state unknown.';
    const charge=this.shadowRoot.querySelector('#charge-state');if(charge)charge.textContent='Charge Now status unavailable.';
    for(const id of ['charge-now','charge-replace']) {const button=this.shadowRoot.querySelector(`#${id}`);if(button)button.disabled=true;}
    for(const id of ['pause-auto','resume-auto']) {const button=this.shadowRoot.querySelector(`#${id}`);if(button)button.disabled=true;}
    if (!preserveDraft) {this.view?.dispose(); this.view=null;}
    const main=this.shadowRoot.querySelector('main');if(main)main.hidden=preserveDraft;
  }
  // Price-day navigation (7.1): the state machine lives across refreshes; it only reads held days, on a user action
  // (plus one small availability read per charger/area/currency), and drops itself when any of them changes.
  priceView(dashboard) {
    const raw=this.rawDashboard, zone=dashboard?.market?.timezone, area=raw?.prices?.area_id;
    if (!dashboard || !this.charger || !this._hass || !zone || typeof area!=='string' || !area) {this.priceDays?.dispose();this.priceDays=null;return null;}
    this.priceDays ||= createPriceDays({request:params=>this.bounded(getPriceDays(this._hass,this.charger,params)),onChange:()=>{if(this.connected)this.paint();}});
    const format=ms=>{try{return new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',timeZone:zone}).format(Date.parse(ms));}catch{return String(ms);}};
    const live=raw?.prices?.published_intervals;
    return this.priceDays.sync({charger:this.charger,epoch:`${this.generation}:${this.permissionEpoch}`,area,currency:dashboard.market.currency,today:typeof raw.prices.today==='string'?raw.prices.today:null,
      span:day=>localDaySpan(day,zone),waitingForTomorrow:raw.prices.waiting_for_tomorrow===true,formatInstant:format}).view(Array.isArray(live)?live:null);
  }
  // History day (7.3a): one Home Assistant-local day of retained evidence, read once per charger/permission/day, on a
  // user action afterwards; today is re-read at most every few minutes. It never writes and never asks a provider.
  historyView(dashboard) {
    const zone=this._hass?.config?.time_zone;
    const today=typeof zone==='string' && zone ? localDate(Date.now(),zone) : null;
    if (!dashboard || !this.charger || !this._hass || !today) {this.historyDay?.dispose();this.historyDay=null;this.priceReview=null;return {state:'unavailable',message:'Charging history needs the Home Assistant time zone, which is unknown here.',nav:null};}
    this.historyDay ||= createHistoryDay({request:params=>this.bounded(getChargingHistory(this._hass,this.charger,params.date)),requestSessions:params=>this.bounded(getSessions(this._hass,this.charger,1,params?.month ?? null)),onChange:()=>{if(this.connected)this.paint();}});
    const view=this.historyDay.sync({charger:this.charger,epoch:`${this.generation}:${this.permissionEpoch}`,zone,marketZone:dashboard.market?.timezone || null,today}).view();
    if (view.nav) view.nav.priceNote=priceReviewNote(this.priceReview?.charger===this.charger ? this.priceReview : null,view.nav.day);
    return view;
  }
  // 8.1: the shown history day's held prices (read-only; only on a user's choice or the explicit button, never at the default).
  reviewPrices() {
    const shown=this.historyDay?.shown(),decoded=this.rawDashboard ? decodeDashboard(this.rawDashboard) : null,marketZone=decoded?.ok ? decoded.value.market?.timezone : null;
    if (!shown || !marketZone) return;
    this.priceReview={charger:this.charger,...requestDayPrices({shown,span:localDaySpan(shown.day,shown.zone),marketZone,marketToday:this.rawDashboard?.prices?.today,priceDays:this.priceDays})};
    this.paint();
  }
  // Price insights (7.5): read-only held-price statistics, one live read plus the current month on open, then only on an
  // explicit choice (window length, month, comparison) or at most every few minutes; a failure waits for Retry.
  insightView(dashboard) {
    const raw=this.rawDashboard, area=raw?.prices?.area_id, today=raw?.prices?.today;
    if (!dashboard || !this.charger || !this._hass || typeof area!=='string' || !area || typeof today!=='string' || !dashboard.market?.currency) {this.priceInsights?.dispose();this.priceInsights=null;return null;}
    this.priceInsights ||= createPriceInsights({request:params=>this.bounded(getPriceInsights(this._hass,this.charger,params)),onChange:()=>{if(this.connected)this.paint();}});
    return this.priceInsights.sync({charger:this.charger,epoch:`${this.generation}:${this.permissionEpoch}`,area,currency:dashboard.market.currency,today}).view();
  }
  insightNav(kind,arg) {
    const insights=this.priceInsights;if(!insights)return;
    if (kind==='retry') insights.retry(); else if (kind==='duration') insights.setDuration(arg); else if (kind==='month') insights.selectMonth(arg); else if (kind==='compare') insights.selectCompare(arg);
  }
  historyNav(kind,arg) {
    const history=this.historyDay;if(!history)return;
    if (kind==='retry') history.retry(); else if (kind==='prices') this.reviewPrices(); else if (kind==='month') history.selectMonth(arg); else if (history.select(kind,arg)) this.reviewPrices();
  }
  priceNav(kind,arg) {
    if (kind==='retry') this.priceDays?.retry(); else this.priceDays?.select(kind,arg);
  }
  paint() {
    if (!this.rawDashboard) return;
    const decoded=decodeDashboard(this.rawDashboard);
    const dashboard=decoded.ok ? decoded.value : null;
    const adapter=dashboardAdapter(this.rawDashboard,this.rawStatus,this.statusAt,Date.now(),this.statusFailed,this.dashboardFailed,this.priceView(dashboard));
    if (!adapter || adapter.draftKey!==this.charger) { this.message('Dashboard unavailable or unsupported.'); return; }
    adapter.actions.priceNav=(kind,arg)=>this.priceNav(kind,arg);
    adapter.model.historyDay=this.historyView(dashboard);
    adapter.actions.historyNav=(kind,arg)=>this.historyNav(kind,arg);
    adapter.model.insights=this.insightView(dashboard);
    adapter.actions.insightNav=(kind,arg)=>this.insightNav(kind,arg);
    this.paintAutomatic(dashboard);
    this.paintChargeNow(dashboard);
    this.paintSession();
    this.paintCheck();
    this.paintRecovery();
    if (this.settingsRecord && dashboard?.settings?.revision > this.settingsRecord.revision) {this.settingsConflict=true;this.settingsNotice='Settings changed elsewhere. Reload the charger before editing again.';}
    const allowed=this._hass?.user?.is_admin===true || dashboard?.settings?.users_change_plan===true;
    if (this.settingsRecord) {
      const record=this.settingsRecord;
      const currency=dashboard?.market?.currency || null;
      if (this.settingsDirty && this.draftCurrency!==undefined && this.draftCurrency!==currency) {this.settingsConflict=true;this.settingsNotice='Price currency changed while editing. Reload settings before saving.';}
      adapter.model.capCurrency=currency;
      adapter.model.settings={driver:record.driver,energy:record.requested_kwh,vehicleId:record.target.vehicle_id || '',target:record.target.target_percent,minimum:record.minimum_ready_by_soc,cap:capInput(record.soft_price_cap,currency),readyBy:record.departure_time,...(record.time_reserve_percent===undefined?{}:{reserve:record.time_reserve_percent}),capEnabled:record.soft_price_cap!=null,capBasis:record.cap_price_basis,deadlineEnabled:record.departure_enabled};
      adapter.model.planVehicles=dashboard ? chargerCarsOf(dashboard).filter(v=>v.id && v.id!=='guest') : [];
      const discovered=dashboard?.soc?.vehicle_id, selected=record.target.vehicle_id;
      const defaultVehicle=!selected && !dashboard?.guest?.active && adapter.model.planVehicles.length===1 ? adapter.model.planVehicles[0] : null;
      if (defaultVehicle) {
        Object.assign(adapter.model.settings,{vehicleId:defaultVehicle.id,driver:'target_soc',target:80,minimum:40,readyBy:'07:30',deadlineEnabled:true});
        adapter.model.proposedPlanDefaults=true;
      }
      adapter.model.vehicleHelp=selected==='guest' || dashboard?.guest?.active ? 'Guest charging uses requested energy; choose a configured vehicle for a target-SOC plan.' : selected ? (adapter.model.planVehicles.some(v=>v.id===selected) ? 'Saved vehicle selected.' : 'Saved vehicle is not currently discovered; check vehicle configuration.') : defaultVehicle ? 'The only available vehicle is selected by default. Target 80%, minimum 40%, and ready by 07:30 are proposed, not saved; review and save the plan to apply them.' : discovered && discovered!=='guest' ? `No vehicle saved; currently discovered: ${dashboard?.soc?.vehicle_name || discovered}. Choose a vehicle.` : 'No unambiguous vehicle selected. Choose a discovered vehicle or configure vehicle discovery.';
      adapter.model.vehicleHelp+=` ${dashboard?.soc?.capacity_kwh > 0 ? 'Capacity is available for the observed vehicle.' : 'Usable battery capacity is unavailable for the observed vehicle; configure it before relying on an SOC plan.'} ${adapter.model.vehicle.socDetail} An old reading can be inaccurate after driving.`;
      // The planner's nord_pool basis compares the source's converted published
      // major-unit price, even when that source includes its own charges. A
      // configured-variable-cost cap must not be drawn on this raw series.
      if (adapter.model.chart && record.revision===dashboard?.settings?.revision && record.cap_price_basis==='nord_pool' && Number.isFinite(record.soft_price_cap)) {
        adapter.model.chart.cap=displayPrice(record.soft_price_cap,currency);
      }
      adapter.model.settingsEditor=true;
      adapter.model.policySupported=record.soft_price_cap!==undefined;
      adapter.model.canSave=allowed && !this.settingsBusy && !this.settingsConflict;
      adapter.model.settingsNotice=this.settingsNotice || (!allowed ? 'You do not have permission to change this plan.' : '');
      adapter.model.labels.settingsNote=`Charge by requested energy or a SpotNav target SOC. The planning target is separate from the car’s own charge limit. Saving a mode, target or energy change can recalculate the plan and may trigger normal guarded schedule reconciliation when ownership is armed; it does not guarantee Resume or physical charging.${record.fill_to_limit ? ' Fill-to-limit is saved separately and remains enabled; review it in the existing card if the requested energy is not being used.' : ''}`;
      adapter.model.labels.saveLabel=this.settingsBusy ? 'Saving…' : 'Save plan';
      adapter.actions.save=values=>this.savePlan(values);
      adapter.actions.reloadSettings=()=>this.reloadSettings();
      adapter.actions.edit=()=>{if(!this.settingsDirty)this.draftCurrency=currency;this.settingsDirty=true;this.paintMorek();};
    } else adapter.model.settingsNotice=this.settingsLoading ? 'Loading settings…' : (this.settingsNotice || 'Settings unavailable.');
    this.paintVehicleSources(adapter,dashboard);
    this.paintMarketCosts(adapter,dashboard);
    this.paintPlanParams(adapter,dashboard,this.morekOwnedNow());
    this.paintNotifySetup(adapter,dashboard);
    this.message(this.dashboardFailed ? 'Dashboard refresh failed; the last observation may be stale.' : '');
    if (this.view) this.view.update(adapter);
    else this.view=mountDashboard(this.shadowRoot.querySelector('main'),adapter);
    this.shadowRoot.querySelector('main').hidden=false;
    this.paintMorek();
  }
  paintSession() {
    const el=this.shadowRoot.querySelector('#charge-session');if(!el)return;
    // Rendering only reads status: the card never sends or changes anything. A missing/stale status says "unknown".
    const info=this.rawStatus ? chargeSession(decodeMorekState(this.rawStatus)||{supported:false},this.statusAt,this.statusFailed,Date.now()) : null;
    el.hidden=!info;
    if(!info){el.replaceChildren();return;}
    const colors={ok:['#12391f','#7ee2a0'],info:['#1c2a3b','#8db8e6'],unknown:['#2a2f38','#a9b4c2'],warning:['#4a3200','#ffb938'],error:['#5a1717','#ff8a8a']}[info.level]||['#2a2f38','#a9b4c2'];
    el.dataset.kind=info.kind;el.dataset.level=info.level;el.dataset.posture=info.posture;
    el.setAttribute('role',info.warning?'alert':'status');el.setAttribute('aria-label','Charging status');
    el.style.cssText=`padding:${info.warning?'16px 18px':'10px 16px'};background:${colors[0]};color:#f4f7fb;border-left:${info.warning?10:5}px solid ${colors[1]};line-height:1.4`;
    const title=document.createElement('div');title.style.cssText=`font-weight:700;font-size:${info.warning?'1.25em':'1.05em'};color:${colors[1]}`;title.textContent=(info.warning?'⚠ ':'')+info.title;
    const detail=document.createElement('div');detail.textContent=info.detail;
    const nodes=[title,detail];
    if(info.action){const action=document.createElement('div');action.style.cssText='margin-top:6px;font-weight:600';action.textContent=info.action;nodes.push(action);}
    const facts=document.createElement('details');facts.style.cssText='margin-top:6px;opacity:.85';
    const summary=document.createElement('summary');summary.textContent='What SpotNav sees';facts.append(summary);
    const list=document.createElement('ul');list.style.margin='4px 0 0';for(const fact of info.facts){const li=document.createElement('li');li.textContent=fact;list.append(li);}
    facts.append(list);nodes.push(facts);
    el.replaceChildren(...nodes);
  }
  paintCheck() {
    const el=this.shadowRoot.querySelector('#schedule-check');if(!el)return;
    // Secondary and read-only: shown only for a fresh status, subdued, and never in place of the charging state above.
    const notes=fresh(this.statusAt,this.statusFailed) ? scheduleNotes(decodeMorekState(this.rawStatus),Date.now()) : null;
    el.hidden=!notes;
    if(!notes){el.replaceChildren();return;}
    el.setAttribute('role','status');el.setAttribute('aria-label','Schedule check');el.dataset.kind=notes.items[0].kind;
    el.style.cssText='padding:8px 16px;background:#1b2028;color:#c9d2de;font-size:.92em;line-height:1.4;border-left:3px solid #55606e';
    const nodes=notes.items.map(item=>{const line=document.createElement('div');line.dataset.kind=item.kind;line.textContent=item.text;if(item.level==='warning')line.style.fontWeight='600';return line;});
    if(notes.facts.length){const d=document.createElement('details');d.style.cssText='margin-top:4px;opacity:.85';const s=document.createElement('summary');s.textContent='Schedule check details';d.append(s);const ul=document.createElement('ul');ul.style.margin='4px 0 0';for(const f of notes.facts){const li=document.createElement('li');li.textContent=f;ul.append(li);}d.append(ul);nodes.push(d);}
    el.replaceChildren(...nodes);
  }
  paintRecovery() {
    const el=this.shadowRoot.querySelector('#recovery-banner');if(!el)return;
    // Only a fresh status may speak; a stale one must not claim a blocker (or its absence).
    const banner=fresh(this.statusAt,this.statusFailed) ? recoveryBanner(decodeMorekState(this.rawStatus),Date.now()) : null;
    el.hidden=!banner;el.textContent=banner?.text||'';el.dataset.level=banner?.level||'';el.dataset.code=banner?.code||'';
    if(banner)Object.assign(el.style,{padding:'12px 16px',color:'#fff',fontWeight:'600',background:banner.level==='error'?'#8f1d1d':banner.level==='warning'?'#8a5a00':'#1f4f7a'});
  }
  paintAutomatic(dashboard) {
    const control=dashboard?.control, active=control?.pause?.choice;
    const isFresh=dashboardFresh(dashboard,this.dashboardFailed);
    const status=decodeMorekState(this.rawStatus), owner=status?.ownership?.recorded_owner;
    const notice=(this.autoNotice || '') + (this.autoRefusalAt && fresh(this.statusAt,this.statusFailed) && this.statusAt>=this.autoRefusalAt ? ` ${admissionDetail(status)}` : '');
    if(owner==='morek_schedule') {
      const statusFresh=fresh(this.statusAt,this.statusFailed);
      const pause=statusFresh ? status?.schedule_pause : null;
      const intent=pause?.intent==='pause_until_resumed' ? 'Pause requested' : pause?.intent==='resume_requested' ? 'Resume requested; retained limit may remain' : pause?.intent==='none' ? 'No schedule-owned pause reported' : 'Pause intent unknown';
      const request=typeof pause?.request==='string' ? pause.request : 'unknown';
      const ack=typeof pause?.ack==='string' ? pause.ack : 'unknown';
      const from=Date.parse(pause?.coverage_start || ''), to=Date.parse(pause?.coverage_end || '');
      const coverage=Number.isFinite(from) && Number.isFinite(to) && to>from ? ` (${new Date(from).toLocaleString()} – ${new Date(to).toLocaleString()})` : ' (coverage unavailable)';
      const readback=pause?.readback==='bounded_match' ? `bounded effective readback match${coverage}` : 'readback unconfirmed';
      const canPause=isFresh && statusFresh && !!control?.can_act && !this.controlPermissionPending && !this.autoBusy && !this.autoUncertain && !this.morekBusy && !this.morekUncertain && !this.settingsBusy && this._hass?.connected!==false;
      const can=canPause && !this.chargeBusy && (status?.ownership?.completion_authorized===true || status?.schedule_pause?.resume_recoverable===true);
      const resumeOffered=ownedResumeOffered(status);
      const blocker = !isFresh ? 'Dashboard observation unavailable or stale.' : !statusFresh ? 'Morek status unavailable or stale.' : !control?.can_act ? 'Control permission or charger availability is unavailable.' : this.controlPermissionPending ? 'Waiting for a fresh permission check.' : this.autoUncertain || this.morekUncertain ? 'A previous action outcome is unknown; do not retry blindly.' : this.autoBusy || this.morekBusy || this.settingsBusy ? 'Another request is in progress.' : status?.schedule_pause?.request==='stop_pending' ? 'A person Stop is pending.' : status?.schedule_pause?.request==='resume_pending' ? ownedResumeReason(status) : (status?.outcomes?.uncertain===true && status?.schedule_pause?.resume_recoverable!==true) ? 'A profile outcome is uncertain; check the charger.' : (status?.ownership?.completion_authorized!==true && status?.schedule_pause?.resume_recoverable!==true) ? `Schedule ownership is not currently authorized; reported recovery status: ${status?.ownership?.recovery?.automatic_recovery || status?.ownership?.recovery?.state || status?.ownership?.blockers?.[0] || 'unknown'}.` : !resumeOffered ? ownedResumeReason(status) : '';
      this.shadowRoot.querySelector('#pause-state').textContent=`${intent}; request ${request}; ACK ${ack}; ${readback}; physical charging unknown.${control?.execution_error==='pause_stop_failed' ? ' Stop request failed.' : ''}${blocker ? ` Resume unavailable: ${blocker}` : ''}`;
      this.shadowRoot.querySelector('#pause-auto').disabled=!(canPause && admittedAction(control,'stop','until_resumed'));
      this.shadowRoot.querySelector('#resume-auto').disabled=!(can && resumeOffered);
      this.shadowRoot.querySelector('#pause-notice').textContent=notice || '';
      return;
    }
    const stopFailed=control?.execution_error==='pause_stop_failed' ? ' Stop request failed; physical charging state unknown.' : '';
    this.shadowRoot.querySelector('#pause-state').textContent=control && isFresh ? (active ? `Pause intent: ${active}; physical stop not confirmed.${stopFailed}` : `No pause reported.${stopFailed}`) : 'Auto state unavailable or stale.';
    const can=isFresh && !!control?.can_act && !this.controlPermissionPending && !this.autoBusy && !this.autoUncertain && !this.morekBusy && !this.morekUncertain && !this.settingsBusy && this._hass?.connected!==false;
    this.shadowRoot.querySelector('#pause-auto').disabled=!(can && admittedAction(control,'stop','until_resumed'));
    this.shadowRoot.querySelector('#resume-auto').disabled=!(can && !this.chargeBusy && admittedAction(control,'resume',null));
    this.shadowRoot.querySelector('#pause-notice').textContent=notice || '';
  }
  chargeDashboardFresh(dashboard) { return dashboardFresh(dashboard,this.dashboardFailed); }
  chargeStatusFresh() { return fresh(this.statusAt,this.statusFailed); }
  paintChargeNow(dashboard) {
    const state=decodeMorekState(this.rawStatus), info=state?.charge_now;
    const active=info?.state==='active';
    const button=this.shadowRoot.querySelector('#charge-now'), replace=this.shadowRoot.querySelector('#charge-replace');
    const blocker=chargeNowBlocker(this,dashboard,state);
    button.textContent=active ? 'Return to Auto' : 'Charge Now';
    button.disabled=!!blocker;
    replace.hidden=!active;replace.disabled=!!blocker;
    this.shadowRoot.querySelector('#charge-state').textContent=chargeNowStatus(state,this.chargeStatusFresh()) + (blocker ? ` ${blocker}` : '');
    this.shadowRoot.querySelector('#charge-notice').textContent=this.chargeNotice || '';
  }
  async chargeAction(action) {
    const hass=this._hass, charger=this.charger, generation=this.generation, permissionEpoch=this.permissionEpoch;
    const snapshot=this.rawStatus, observedAt=this.statusAt, state=decodeMorekState(snapshot), decoded=decodeDashboard(this.rawDashboard);
    const dashboard=decoded.ok ? decoded.value : null;
    const blocker=chargeNowBlocker(this,dashboard,state);
    if (blocker || !charger || !['charge_now','return_to_auto'].includes(action) || (action==='return_to_auto' && state?.charge_now?.state!=='active')) {
      this.chargeNotice=blocker || 'Charge Now is unavailable.';this.paint();return;
    }
    let selection;
    if (action==='charge_now') {
      selection=chargeNowSelection(this.shadowRoot.querySelector('#charge-duration').value,this.shadowRoot.querySelector('#charge-end').value);
      if (selection.error) {this.chargeNotice=selection.error;this.paint();return;}
      const replacement=state.charge_now.state==='active' ? 'This replaces the existing end, calculated from now. ' : '';
      if (!window.confirm(`${replacement}Charge Now overrides the price-based Auto plan until ${new Date(selection.end).toLocaleString()}. ${chargeNowPrice(state.charge_now)} The end is fixed; plugging in later does not extend it. Continue?`)) return;
    } else if (!window.confirm('Return to Auto? Charging may continue if the Auto plan selects the current time. This is not a persistent Pause.')) return;
    const latest=decodeMorekState(this.rawStatus), latestDashboard=decodeDashboard(this.rawDashboard);
    if (!this.connected || this.generation!==generation || this.permissionEpoch!==permissionEpoch || this.charger!==charger || this.rawStatus!==snapshot || this.statusAt!==observedAt || !latestDashboard.ok || chargeNowBlocker(this,latestDashboard.value,latest) || (action==='return_to_auto' && latest?.charge_now?.state!=='active')) {this.chargeNotice='State changed; refresh and review before trying again.';this.paint();return;}
    if (selection?.options?.end_time && Date.parse(selection.options.end_time)<=Date.now()) {this.chargeNotice='Choose a future end time.';this.paint();return;}
    this.chargeBusy=true;this.chargeNotice='Request in progress; schedule and charging are not confirmed.';this.statusEpoch++;this.paint();
    const request=chargeNowAction(hass,charger,action,selection?.options);
    this.chargePending?.set(charger,request);
    request.finally(()=>{if(this.chargePending?.get(charger)===request)this.chargePending.delete(charger);}).catch(()=>{});
    try {
      const response=await this.bounded(request);
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) {this.chargeUnknown?.add(charger);return;}
      const result=response?.api_version===1 ? response.schedule : null;
      if (!result || !['pending','worker_unavailable'].includes(result.reconciliation) || !['uncertain','not_yet_confirmed'].includes(result.outcome) || (action==='charge_now' && !result.intent?.id) || (action==='return_to_auto' && result.intent!==null)) {
        this.chargeUnknown?.add(charger);this.chargeNotice='Response unavailable; outcome unknown. Do not retry blindly.';
      } else {
        if(result.outcome==='uncertain')this.chargeUnknown?.add(charger);
        this.chargeExpected?.set(charger,action==='charge_now' ? result.intent.id : null);
        this.chargeNotice=`Intent recorded; ${result.reconciliation==='pending' ? 'waiting for schedule reconciliation' : 'schedule worker unavailable'}. ${result.outcome==='uncertain' ? 'A prior profile outcome is uncertain; do not retry blindly.' : 'This does not confirm charging.'}`;
      }
    } catch (error) {
      if(this.connected && generation===this.generation && charger===this.charger) {
        const code=error?.code;
        const reasons={spotnav_morek_resume_auto_first:'Charging is paused. Resume Auto first.',spotnav_morek_charge_now_invalid_time:'Choose a valid future end time within 48 hours.',spotnav_morek_charge_now_invalid_duration:'Choose a supported duration.',spotnav_morek_identity_unresolved:'The connector identity is unresolved.',spotnav_morek_identity_changed:'The connector identity changed.',spotnav_morek_schedule_owner_unavailable:'Schedule ownership is unavailable.',spotnav_not_admin:'Administrator permission is required.'};
        if (!reasons[code]) this.chargeUnknown?.add(charger);
        this.chargeNotice=reasons[code] ? `${reasons[code]} (${code})` : `Request outcome unknown${code ? ` (${code})` : ''}; do not retry blindly.`;
      } else this.chargeUnknown?.add(charger);
    } finally {
      if(this.connected && generation===this.generation && charger===this.charger) {this.chargeBusy=false;this.statusAt=null;this.paint();this.refresh();}
    }
  }
  async automaticAction(action,choice) {
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass, decoded=decodeDashboard(this.rawDashboard);
    const morek=decodeMorekState(this.rawStatus), owner=morek?.ownership;
    const statusFresh=fresh(this.statusAt,this.statusFailed);
    if (owner?.recorded_owner==='morek_schedule' && !statusFresh) return;
    if (owner?.recorded_owner==='morek_schedule' && action!=='stop' && ((owner.completion_authorized!==true && !(action==='resume' && morek?.schedule_pause?.resume_recoverable===true)) || !statusFresh)) return;
    const offered=decoded.ok && (owner?.recorded_owner==='morek_schedule' && action==='resume'
      ? choice===null && statusFresh && ownedResumeOffered(morek)
      : admittedAction(decoded.value.control,action,choice));
    if (!this.connected || !charger || !hass || hass.connected===false || !decoded.ok || !dashboardFresh(decoded.value,this.dashboardFailed) || this.controlPermissionPending || this.autoBusy || this.autoUncertain || this.morekBusy || this.morekUncertain || this.settingsBusy || (action!=='stop' && this.chargeBusy) || !decoded.value.control.can_act || !offered) return;
    const dispatchedAt=Date.now();this.autoRefusalAt=null;this.autoBusy=true;this.autoNotice='Request in progress; state not yet confirmed.';this.dashboardEpoch++;this.statusEpoch++;this.statusAt=null;this.paint();
    try {
      const result=await this.bounded(performAction(hass,charger,action,choice));
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) return;
      this.autoExpected=result.ok ? {action,choice,dispatchedAt} : null;
      // Older backends also used action_failed for unexpected post-dispatch errors.
      if (!result.ok && (result.error==='spotnav_action_failed' || result.error==='spotnav_action_outcome_unknown' || !result.error || !['spotnav_action_unavailable','spotnav_action_reconcile_failed','schedule_owner_unavailable','identity_unresolved','identity_changed','resume_unavailable','resume_interrupted','ownership_blocked','legacy_execution_ownership_blocked','invalid_pause','no_settings','pause_unsettled','action_pending'].includes(result.error))) this.autoUncertain=true;
      this.autoNotice=result.ok ? 'Accepted; waiting for a fresh confirmed state.' : actionFailure(result.error,action);
      if (!result.ok && result.error==='legacy_execution_ownership_blocked') this.autoRefusalAt=dispatchedAt;
    } catch {if(this.connected && generation===this.generation && charger===this.charger){this.autoUncertain=true;this.autoNotice='Request failed or outcome unknown; no retry is offered in this session.';}}
    finally {if(this.connected && generation===this.generation && charger===this.charger){this.autoBusy=false;this.paint();this.refresh();}}
  }
  reloadSettings() {
    if (!this.connected || this.settingsBusy || !this.charger || this.pendingSettingsWrites.has(this.charger)) return;
    if (!window.confirm('Discard the current draft and reload the latest settings?')) return;
    this.view?.resetDrafts();this.resetCosts();this.resetParams();this.unknownCostWrites.delete(this.charger);this.draftRevision=null;this.draftCurrency=undefined;this.settingsRecord=null;this.settingsConflict=false;this.settingsDirty=false;this.unknownSettingsWrites.delete(this.charger);this.settingsNotice='Loading settings…';
    void this.loadSettings();
  }
  paintMorek() {
    const target=this.shadowRoot.querySelector('#morek-debug');
    const state=decodeMorekState(this.rawStatus);
    if (!target) return;
    if (!state) {target.querySelectorAll('button').forEach(button=>{button.disabled=true;});return;}
    const panel=morekPanel(document,state,this._hass?.user?.is_admin===true,this.morekBusy || this.settingsBusy || this.settingsDirty || this.autoBusy,this.morekError,action=>void this.morekAction(action),this.morekActiveAction,false);
    if (target.firstChild) reconcile(target.firstChild,panel);
    else target.append(panel);
    if (state.ownership?.reconfirmation_required && state.supported && this._hass?.user?.is_admin===true) {
      const button=document.createElement('button');
      button.type='button';button.textContent='Reconfirm schedule ownership';
      button.disabled=this.morekBusy || this.settingsBusy || this.autoBusy;
      button.addEventListener('click',()=>void this.morekAction('reconfirm_migration'));
      target.firstChild.append(button);
    }
    if (state.supported && this._hass?.user?.is_admin===true) {
      const button=document.createElement('button');
      button.type='button';button.textContent='Recalculate & sync schedule';
      button.disabled=this.morekBusy || this.settingsBusy || this.settingsDirty || this.autoBusy || this.chargeBusy || this.morekUncertain || this.autoUncertain || state.outcomes?.uncertain===true || !fresh(this.statusAt,this.statusFailed);
      button.addEventListener('click',()=>void this.morekAction('recalculate_sync'));
      target.firstChild.append(button);
      if (this.syncNotice) {const notice=document.createElement('p');notice.textContent=this.syncNotice;target.firstChild.append(notice);}
      const reset=document.createElement('button');
      reset.type='button';reset.textContent=translate('en',this.morekActiveAction==='reset_learning' ? 'learning.reset.busy' : 'learning.reset.button');
      reset.disabled=this.morekBusy || this.settingsBusy || this.settingsDirty || this.autoBusy || this.chargeBusy || this.morekUncertain || this.autoUncertain || state.outcomes?.uncertain===true || !fresh(this.statusAt,this.statusFailed);
      reset.addEventListener('click',()=>void this.morekAction('reset_learning'));
      target.firstChild.append(reset);
      if (this.learningNotice) {const notice=document.createElement('p');notice.textContent=this.learningNotice;target.firstChild.append(notice);}
    }
    const dashboard=decodeDashboard(this.rawDashboard);
    const send=target.querySelector('[data-morek-action="send"]');if(send && (this.morekUncertain || this.autoUncertain || !fresh(this.statusAt,this.statusFailed) || !dashboard.ok || !dashboardFresh(dashboard.value,this.dashboardFailed) || dashboard.value.control.pause?.choice!=='until_resumed' || !dashboard.value.control.pause_blocks_execution))send.disabled=true;
  }
  async morekAction(action) {
    const hass=this._hass, charger=this.charger, generation=this.generation, permissionEpoch=this.permissionEpoch, statusSnapshot=this.rawStatus, observedAt=this.statusAt, state=decodeMorekState(statusSnapshot);
    if (!this.connected || hass?.connected===false || hass?.user?.is_admin!==true || !charger || !state || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || this.paramBusy || this.notifyBusy || !['status','send','fetch','clear','reconfirm_migration','recalculate_sync','reset_learning'].includes(action)) return;
    if (action==='reconfirm_migration' && state.ownership?.reconfirmation_required!==true) return;
    if (action!=='status' && !state.supported) return;
    if (action==='clear' && state.cleanup_supported!==true) return;
    if (this.settingsBusy || (action==='send' && this.settingsDirty)) return;
    if ((action==='recalculate_sync' || action==='reset_learning') && (this.settingsDirty || this.morekUncertain || this.autoUncertain || state.outcomes?.uncertain || !fresh(this.statusAt,this.statusFailed))) return;
    if (action==='send' && (this.morekUncertain || this.autoUncertain || state.outcomes?.uncertain || !state.preview?.profile || state.preview.reason!==null || !state.preview.preview_id || !fresh(this.statusAt,this.statusFailed))) return;
    const previewId=state.preview?.preview_id, configured=state.configured_id, resolved=state.resolved_id, dashboardSnapshot=this.rawDashboard;
    // Recheck at the dispatch boundary, independently of the diagnostic view's
    // confirmation and disabled state. A request already sent cannot be recalled.
    if (action==='send' && !window.confirm('Confirm sending the current preview. The final 0 A limit may persist.')) return;
    if (action==='clear' && !window.confirm('Confirm selective removal of SpotNav profile 42001. Effective limits may increase.')) return;
    if (action==='reset_learning' && !window.confirm(translate('en','learning.reset.confirm'))) return;
    if (action==='reconfirm_migration' && !window.confirm('Reconfirm schedule ownership for this connection? This does not verify charger protection, profile inventory or physical charging. A previous schedule or 0 A limit may remain.')) return;
    const latest=decodeMorekState(this.rawStatus);
    const dashboard=decodeDashboard(this.rawDashboard);
    if (action==='send' && (this.rawDashboard!==dashboardSnapshot || !dashboard.ok || !dashboardFresh(dashboard.value,this.dashboardFailed) || dashboard.value.control.pause?.choice!=='until_resumed' || !dashboard.value.control.pause_blocks_execution)) return;
    if (!this.connected || this.generation!==generation || this.permissionEpoch!==permissionEpoch || this.charger!==charger || this.rawStatus!==statusSnapshot || this.statusAt!==observedAt || this._hass?.user?.is_admin!==true || this._hass?.connected===false || this.morekBusy || this.settingsBusy || this.autoBusy || !latest || latest.configured_id!==configured || latest.resolved_id!==resolved || (action!=='status' && !latest.supported) || (action==='send' && (this.morekUncertain || this.autoUncertain || latest.outcomes?.uncertain || !latest.preview?.preview_id || latest.preview.preview_id!==previewId || latest.preview.reason!==null || !latest.preview.profile || this.settingsDirty || !fresh(this.statusAt,this.statusFailed))) || (action==='clear' && (!latest.supported || latest.cleanup_supported!==true))) return;
    this.morekBusy=true;this.morekActiveAction=action;this.morekError=null;this.statusEpoch++;
    this.paintMorek();
    try {
      const raw=await this.bounded(morekSchedule(hass,charger,action,previewId));
      if (action==='reconfirm_migration') {this.morekError=null;return;}
      if (action==='reset_learning') {
        // The backend reset already happened; a response for another charger, connection or permission is never shown here.
        if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger || this._hass?.user?.is_admin!==true) return;
        const done=raw?.schedule?.learning_reset;
        // Only the backend's own answer is believed: both files gone and a replan asked is "done"; any other answer is said as it is.
        this.learningNotice=translate('en',done && done.energy!==false && done.power!==false && done.replan==='requested' && (done.energy===true || done.power===true) ? 'learning.reset.done' : done && (done.energy===false || done.power===false) ? 'learning.reset.partial' : 'learning.reset.failed');
        return;
      }
      if (action==='recalculate_sync') {this.syncNotice=raw?.schedule?.reconciliation==='requested' ? 'Recalculated; sync requested, not yet confirmed. The schedule sync status above shows the latest worker result.' : 'Sync response unavailable; check schedule sync status before trying again.';return;}
      const result=decodeMorekState(raw);
      if (!this.connected || generation!==this.generation || permissionEpoch!==this.permissionEpoch || charger!==this.charger) return;
      if (!result) {if(action==='send')this.morekUncertain=true;this.morekError='Response unavailable; operation outcome may be unknown.';}
      else {this.rawStatus={api_version:1,schedule:result};this.statusAt=action==='status' ? Date.now() : null;this.statusFailed=action!=='status';}
    } catch (error) {if(this.connected && generation===this.generation && charger===this.charger) {if(action==='send')this.morekUncertain=true;if(action==='reset_learning'){if(permissionEpoch===this.permissionEpoch && this._hass?.user?.is_admin===true)this.learningNotice=translate('en','learning.reset.failed');}else if(action==='recalculate_sync')this.syncNotice=`Sync not confirmed${error?.code ? ` (${error.code})` : ''}; check reconciliation status before retrying.`;else this.morekError='Request failed or outcome unknown; do not assume the operation did not apply.';}}
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
    if (!this.connected || hass?.connected===false || !charger || !record || this.settingsBusy || this.pendingSettingsWrites.has(charger) || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || this.paramBusy || this.notifyBusy || this.settingsConflict || !allowed) {this.settingsNotice='Save unavailable or permission denied.';this.paint();return;}
    const base=formFromRecord(record), driver=values.driver ?? base.driver, vehicleId=values.vehicleId ?? base.vehicleId;
    if (vehicleId!==base.vehicleId && (!decoded.ok || !chargerCarsOf(decoded.value).some(v=>v.id===vehicleId && v.id!=='guest'))) {this.settingsNotice='Choose an available discovered vehicle.';this.paint();return;}
    const form={...base,driver,energy:values.energy ?? base.energy,vehicleId,targetPercent:values.target ?? base.targetPercent,minimumReadySoc:values.minimum,capValue:capForSave(values.cap,decoded.ok ? decoded.value.market?.currency : null,record.soft_price_cap),capEnabled:values.capEnabled,capBasis:values.capBasis,deadlineEnabled:values.deadlineEnabled,deadlineTime:values.readyBy,...(base.timeReserve===undefined?{}:{timeReserve:values.reserve ?? base.timeReserve})};
    const check=replacementFor('plan',record,form);
    if (!check.ok) {this.settingsNotice=translate('en',check.errorKey);this.paint();return;}
    if (check.body.target.target_percent!=null && check.body.minimum_ready_by_soc!=null && check.body.minimum_ready_by_soc>check.body.target.target_percent) {this.settingsNotice='Minimum SOC must not exceed the planning target.';this.paint();return;}
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
  vehicleContext() {
    const config=this.vehicleConfig, decoded=decodeDashboard(this.rawDashboard), dashboard=decoded.ok ? decoded.value : null;
    if (!config) return null;
    const vehicleId=chooseVehicle(config.vehicles,this.vehicleSelected,this.settingsRecord?.target?.vehicle_id || null);
    const vehicle=config.vehicles.find(v=>v.id===vehicleId);
    if (!vehicle) return null;
    return {vehicleId,vehicle,dashboard,row:(dashboard?.vehicles||[]).find(r=>r.id===vehicleId) || null,props:(config.vehicleProperties||[]).find(p=>p.id===vehicleId) || null};
  }
  paintVehicleSources(adapter,dashboard) {
    const admin=this._hass?.user?.is_admin===true, charger=this.charger;
    const unknown=this.unknownVehicleWrites.has(charger) || this.pendingVehicleWrites.has(charger);
    const ctx=this.vehicleContext();
    // A draft is only meaningful against what it was started from; anyone else's change makes it a conflict to reload.
    if (this.vehicleDirty && this.vehicleBase && ctx && !this.vehicleConflict && (ctx.vehicleId!==this.vehicleBase.vehicleId || vehicleSignature(ctx.vehicle,ctx.props)!==this.vehicleBase.signature)) {
      this.vehicleConflict=true;this.vehicleNotice='Vehicle sources changed while editing. Reload before saving again.';
    }
    const states=this._hass?.states;
    const entityState=id=>{if(!states)return 'ok';const s=states[id];return !s ? 'missing' : ['unavailable','unknown'].includes(s.state) ? 'unavailable' : 'ok';};
    const vehicle=adapter.model.vehicle;
    adapter.model.vehicleSources=vehicleSourcesModel({admin,loading:this.vehicleLoading,failed:this.vehicleConfigFailed,config:this.vehicleConfig,configAt:this.vehicleConfigAt,now:Date.now(),rows:dashboard?.vehicles || [],
      dashboardFresh:!!dashboard && dashboardFresh(dashboard,this.dashboardFailed),reading:{vehicleId:dashboard?.soc?.vehicle_id ?? null,value:vehicle?.soc,stale:vehicle?.stale,detail:vehicle?.socDetail || ''},
      savedId:this.settingsRecord?.target?.vehicle_id || null,selectedId:this.vehicleSelected,entityState,blocked:this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.costBusy || this.paramBusy || this.notifyBusy || unknown,
      conflict:this.vehicleConflict || unknown,busy:this.vehicleBusy,notice:unknown && !this.vehicleNotice ? 'A previous vehicle save has an unknown outcome. Reload vehicle sources to confirm it.' : this.vehicleNotice});
    adapter.actions.editVehicle=()=>this.editVehicle();
    adapter.actions.selectVehicle=id=>this.selectVehicle(id);
    adapter.actions.saveVehicleSensor=values=>this.saveVehicleSensor(values);
    adapter.actions.saveVehicleProperties=values=>this.saveVehicleProperties(values);
    adapter.actions.reloadVehicleSources=()=>this.reloadVehicleSources();
  }
  editVehicle() {
    if (this.vehicleDirty) return;
    const ctx=this.vehicleContext();
    this.vehicleBase=ctx ? {vehicleId:ctx.vehicleId,signature:vehicleSignature(ctx.vehicle,ctx.props),props:ctx.props ? {...ctx.props} : null} : null;
    this.vehicleDirty=true;
  }
  selectVehicle(id) {
    if (this.vehicleBusy || id===(this.vehicleContext()?.vehicleId ?? '')) {this.paint();return;}
    if (this.vehicleDirty && !window.confirm('Discard the unsaved vehicle changes and switch vehicle?')) {this.paint();return;}
    this.view?.resetVehicleDrafts();this.vehicleDirty=false;this.vehicleBase=null;this.vehicleSelected=id || null;this.vehicleNotice='';this.paint();
  }
  reloadVehicleSources() {
    const charger=this.charger;
    if (!this.connected || !charger || this.vehicleBusy || this.pendingVehicleWrites.has(charger)) return;
    if (this.vehicleDirty && !window.confirm('Discard the unsaved vehicle changes and reload vehicle sources?')) return;
    this.view?.resetVehicleDrafts();this.vehicleDirty=false;this.vehicleBase=null;this.vehicleConflict=false;this.unknownVehicleWrites.delete(charger);this.vehicleNotice='';this.vehicleConfig=null;this.vehicleConfigAt=null;
    this.paint();void this.loadVehicleConfig();this.refresh();
  }
  async loadVehicleConfig() {
    if (this.vehicleLoading || this.vehicleBusy || !this.charger || this._hass?.user?.is_admin!==true) return;
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass;
    const current=()=>this.connected && generation===this.generation && permissionEpoch===this.permissionEpoch && charger===this.charger;
    this.vehicleLoading=true;
    try {
      const decoded=decodeEntityAnswer(await this.bounded(getEntityConfig(hass,charger)));
      if (!current()) return;
      if (!decoded.ok || !decoded.value.ok) {this.vehicleConfigFailed=true;this.vehicleNotice=decoded.ok && decoded.value.code ? translate('en',entityErrorKey(decoded.value.code)) : 'Vehicle sources unavailable.';return;}
      this.vehicleConfig=decoded.value.config;this.vehicleConfigAt=Date.now();this.vehicleConfigFailed=false;
      if (this.unknownVehicleWrites.has(charger) || this.pendingVehicleWrites.has(charger)) {this.vehicleConflict=true;this.vehicleNotice='A previous vehicle save has an unknown outcome. Reload vehicle sources to confirm it.';}
      else if (this.vehicleNotice==='Vehicle sources unavailable.') this.vehicleNotice='';
    } catch { if (current()) {this.vehicleConfigFailed=true;this.vehicleNotice=this.vehicleConfig ? this.vehicleNotice : 'Vehicle sources unavailable.';} }
    finally { if (this.connected && generation===this.generation) {this.vehicleLoading=false;this.paint();} }
  }
  vehicleWriteBlocked(ctx) {
    const charger=this.charger, hass=this._hass;
    return !this.connected || hass?.connected===false || hass?.user?.is_admin!==true || !charger || !ctx || this.vehicleBusy || this.costBusy || this.paramBusy || this.notifyBusy || this.vehicleLoading || this.pendingVehicleWrites.has(charger) || this.unknownVehicleWrites.has(charger) || this.vehicleConflict || this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy;
  }
  async finishVehicleWrite(generation,charger,body) {
    // Common shell: once dispatched, only the write's own answer settles the outcome.
    this.vehicleBusy=true;this.statusEpoch++;this.statusAt=null;this.paint();
    try { await body(); }
    finally { if (this.connected && generation===this.generation && charger===this.charger) {this.vehicleBusy=false;this.dashboardEpoch++;this.paint();this.refresh();} }
  }
  vehicleAnswer(label,ok,code,fieldErrors,config) {
    if (ok) {
      this.vehicleDirty=false;this.vehicleBase=null;this.vehicleConflict=false;this.view?.resetVehicleDrafts();
      this.vehicleNotice=`${label} saved and confirmed by the backend. Plans for this car may recalculate and, if Morek owns the schedule, go through normal guarded reconciliation; this does not wake the car, send a notification or confirm charging.`;
    } else {
      if (code===ENTITY_CONFLICT) this.vehicleConflict=true;
      const first=fieldErrors?.[0];
      this.vehicleNotice=`${label} not saved: ${translate('en',first ? fieldErrorKey(first.code) : entityErrorKey(code))}`;
    }
    if (config) {this.vehicleConfig=config;this.vehicleConfigAt=Date.now();this.vehicleConfigFailed=false;}
  }
  async saveVehicleSensor(values) {
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass, ctx=this.vehicleContext();
    if (this.vehicleWriteBlocked(ctx)) {this.vehicleNotice='Save unavailable: another request is running, the outcome of a previous save is unknown, or permission is missing.';this.paint();return;}
    if (!this.vehicleConfigAt || Date.now()-this.vehicleConfigAt>90000 || this.vehicleConfigFailed) {this.vehicleNotice='Sensor information is stale. Wait for a fresh read or reload vehicle sources.';this.paint();return;}
    const plan=sensorWritePlan(ctx.vehicle,values?.sensor);
    if (!plan.ok) {this.vehicleNotice=plan.notice;this.paint();return;}
    if (!plan.changed) {this.vehicleNotice='No changes to save.';this.paint();return;}
    if (plan.replacesChoice && !window.confirm(plan.entityId ? 'Replace the sensor you chose earlier for this car?' : 'Clear your sensor choice and return to automatic detection? With several candidates this leaves the car without a charge reading.')) return;
    const vehicle=ctx.vehicle, current=()=>this.connected && generation===this.generation && permissionEpoch===this.permissionEpoch && charger===this.charger;
    // The backend compares `expectedEntityId` with the saved choice at the write itself (under a lock): a choice made
    // elsewhere is a conflict and nothing is written, so there is no client re-read window.
    await this.finishVehicleWrite(generation,charger,async()=>{
      const request=setVehicleSoc(hass,charger,{vehicleId:vehicle.id,entityId:plan.entityId,expectedEntityId:plan.expected});
      this.pendingVehicleWrites.set(charger,request);
      request.finally(()=>{if(this.pendingVehicleWrites.get(charger)===request)this.pendingVehicleWrites.delete(charger);}).catch(()=>{});
      this.vehicleNotice='Saving…';this.paint();
      try {
        const answer=decodeEntityAnswer(await this.bounded(request));
        if (!current()) {this.unknownVehicleWrites.add(charger);return;}
        if (!answer.ok) {this.unknownVehicleWrites.add(charger);this.vehicleConflict=true;this.vehicleNotice='Save response unavailable; outcome unknown. Reload vehicle sources before retrying.';return;}
        this.vehicleAnswer('Sensor choice',answer.value.ok,answer.value.ok ? null : answer.value.code,answer.value.ok ? [] : answer.value.fieldErrors,answer.value.config);
      } catch { this.unknownVehicleWrites.add(charger);if(this.connected && generation===this.generation){this.vehicleConflict=true;this.vehicleNotice='Save outcome unknown; the request may still complete. Wait, then reload vehicle sources before retrying.';} }
    });
  }
  async saveVehicleProperties(values) {
    const generation=this.generation, permissionEpoch=this.permissionEpoch, charger=this.charger, hass=this._hass, ctx=this.vehicleContext();
    if (this.vehicleWriteBlocked(ctx)) {this.vehicleNotice='Save unavailable: another request is running, the outcome of a previous save is unknown, or permission is missing.';this.paint();return;}
    if (!this.vehicleConfigAt || Date.now()-this.vehicleConfigAt>90000 || this.vehicleConfigFailed) {this.vehicleNotice='Vehicle information is stale. Wait for a fresh read or reload vehicle sources.';this.paint();return;}
    const props=this.vehicleBase?.vehicleId===ctx.vehicleId && this.vehicleBase.props ? this.vehicleBase.props : ctx.props;
    const plan=propertyWritePlan(props,values || {});
    if (!plan.ok) {this.vehicleNotice=plan.notice;this.paint();return;}
    if (!plan.changed) {this.vehicleNotice='No changes to save.';this.paint();return;}
    if (plan.clearsCapacity && !window.confirm('Clear the battery capacity you entered? Plans that need a capacity will hold until one is available.')) return;
    const vehicleId=ctx.vehicleId, current=()=>this.connected && generation===this.generation && permissionEpoch===this.permissionEpoch && charger===this.charger;
    await this.finishVehicleWrite(generation,charger,async()=>{
      const request=updateVehicle(hass,charger,{vehicleId,changes:plan.changes,expected:plan.expected});
      this.pendingVehicleWrites.set(charger,request);
      request.finally(()=>{if(this.pendingVehicleWrites.get(charger)===request)this.pendingVehicleWrites.delete(charger);}).catch(()=>{});
      this.vehicleNotice='Saving…';this.paint();
      try {
        const answer=decodeVehicleWriteAnswer(await this.bounded(request));
        if (!current()) {this.unknownVehicleWrites.add(charger);return;}
        if (!answer.ok) {this.unknownVehicleWrites.add(charger);this.vehicleConflict=true;this.vehicleNotice='Save response unavailable; outcome unknown. Reload vehicle sources before retrying.';return;}
        this.vehicleAnswer('Capacity and phases',answer.value.ok,answer.value.ok ? null : answer.value.code,answer.value.ok ? [] : answer.value.fieldErrors,answer.value.config);
      } catch { this.unknownVehicleWrites.add(charger);if(this.connected && generation===this.generation){this.vehicleConflict=true;this.vehicleNotice='Save outcome unknown; the request may still complete. Wait, then reload vehicle sources before retrying.';} }
    });
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
    // Read-only: the bundled area list (any signed-in user may read it). Writes are admin-only and separate.
    void this.loadMarketOptions();
    // Read-only: the entity config only lists sensors; reading it never writes or wakes anything.
    if (hass.user?.is_admin===true && !this.vehicleLoading && !this.vehicleBusy && (!this.vehicleConfig || Date.now()-(this.vehicleConfigAt||0)>CONFIG_REFRESH_MS)) void this.loadVehicleConfig();
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
        this.dashboardFailed=false; this.rawDashboard=raw;this.costAwaitingRead=false;this.paramAwaitingRead=false;this.notifyAwaitingRead=false;this.controlPermissionPending=false;
        const control=decodeDashboard(raw).value?.control;
        const generated=Date.parse(raw.generated_at || '');
        if(this.autoExpected && control && fresh(generated) && generated<=Date.now() && generated>=this.autoExpected.dispatchedAt && (this.autoExpected.action==='stop' ? control.pause?.choice===this.autoExpected.choice : control.pause?.choice==null)) {this.autoNotice='Confirmed by a fresh dashboard observation.';this.autoExpected=null;}
        this.paint();
      }).catch(()=>{if(valid() && epoch===this.dashboardEpoch) {this.dashboardFailed=true;if(this.view)this.paint();else this.message('Dashboard unavailable.');}});
    }
    if (!this.statusRead && !this.morekBusy && !this.settingsBusy) {
      const epoch=this.statusEpoch;
      const pending=morekSchedule(hass,charger,'status'); this.statusRead=pending;
      pending.finally(()=>{if(this.statusRead===pending){this.statusRead=null;if(valid() && epoch!==this.statusEpoch)this.refresh();}}).catch(()=>{});
      this.bounded(pending).then(raw=>{
        if (!valid() || epoch!==this.statusEpoch) return; this.rawStatus=raw;this.statusAt=Date.now();this.statusFailed=false;
        if (this.chargeExpected?.has(charger)) {
          const expected=this.chargeExpected.get(charger), observed=raw?.schedule?.charge_now, pause=raw?.schedule?.schedule_pause;
          if ((expected===null && observed?.state==='inactive') || (expected!==null && observed?.state==='active' && observed?.intent?.id===expected) || (pause?.intent==='pause_until_resumed' && observed?.state==='inactive')) this.chargeExpected.delete(charger);
        }
        this.paint();
      }).catch(()=>{if(valid() && epoch===this.statusEpoch) {this.statusFailed=true;this.paint();}});
    }
  }
}
Object.assign(SpotnavEnhancedPanel.prototype,marketCostMethods,planParamMethods,notifySetupMethods);
if (!customElements.get('spotnav-enhanced-panel')) customElements.define('spotnav-enhanced-panel',SpotnavEnhancedPanel);
