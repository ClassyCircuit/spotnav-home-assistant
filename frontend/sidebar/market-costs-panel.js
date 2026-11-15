// Stage 13.2 — the panel's wiring of the "Market & charging costs" area, installed on the panel's prototype. Opening or
// editing only reads. Every write is one of the EXISTING canonical commands (`update_settings` for the area and
// VAT/energy tax/flat grid fee, `update_grid_tariff`, `choose_price_source`), admin-only and compare-and-set; once a
// request is dispatched only its own answer settles the outcome, and anything else is an unknown outcome that needs an
// explicit reload.
import { getMarketOptions, updateSettings, updateGridTariff, choosePriceSource } from '../src/api.ts';
import { decodeMarketOptions, marketEditable } from '../src/market.ts';
import { decodeSettingsAnswer, settingsErrorKey } from '../src/settings.ts';
import { decodeDashboard } from '../src/validate.ts';
import { GRID_TARIFF_CONFLICT } from '../src/grid-tariff.ts';
import { SETTINGS_REVISION_CONFLICT, SETTINGS_RECONCILE_FAILED, SETTINGS_NOT_COMMITTED } from '../src/types.ts';
import { translate } from '../src/i18n/index.ts';
import { observationFreshness } from '../src/observation-freshness.ts';
import { marketCostsModel, marketWritePlan, tariffWritePlan, sourceWritePlan, costSignature, OPTIONS_REFRESH_MS, OPTIONS_MAX_AGE_MS } from './market-costs.js';

/** Codes a command answers with BEFORE it writes anything: the person sees "not saved". Anything else is unknown. */
const REFUSED = (code) => typeof code === 'string' && (code === 'spotnav_not_admin' || code === 'spotnav_unknown_charger' || code === 'spotnav_unsupported_api_version' || code === 'spotnav_no_price_entry' || code === 'spotnav_unknown_price_entry' || code === 'spotnav_invalid_value' || code === 'revision_conflict' || code.startsWith('invalid_'));
const SAVED_NOTE = 'Plans and cost estimates for every charger using this price entry may recalculate and, if Morek owns the schedule, go through normal guarded reconciliation; this does not change the provider, send a notification, wake the car or confirm charging.';
const dashFresh = (dashboard, failed) => observationFreshness(Date.parse(dashboard?.generated_at || ''), Date.now(), failed) === 'fresh';

export const costWritesByConnection = new WeakMap();

export const marketCostMethods = {
  initCosts() {
    this.pendingCostWrites = new Map();
    this.unknownCostWrites = new Set();
    this.marketOptions = null; this.marketOptionsAt = null; this.marketOptionsFailed = false; this.marketLoading = false;
    this.marketArea = null; this.costDirty = false; this.costFeeEdited = false; this.costBase = null; this.costBusy = false; this.costConflict = false; this.costNotice = ''; this.costAwaitingRead = false;
  },
  bindCostContext(value) {
    if (this.costWriteContext || !value) return;
    const key = value.connection || value;
    if (!costWritesByConnection.has(key)) costWritesByConnection.set(key, { pending: new Map(), unknown: new Set() });
    this.costWriteContext = costWritesByConnection.get(key);
    this.pendingCostWrites = this.costWriteContext.pending; this.unknownCostWrites = this.costWriteContext.unknown;
  },
  resetCosts() {
    this.view?.resetMarketDrafts(false);
    this.costDirty = false; this.costFeeEdited = false; this.costBase = null; this.costConflict = false; this.costNotice = ''; this.marketArea = null;
  },
  paintMarketCosts(adapter, dashboard) {
    const admin = this._hass?.user?.is_admin === true, charger = this.charger;
    const unknown = this.unknownCostWrites.has(charger) || this.pendingCostWrites.has(charger);
    const block = dashboard?.grid_tariff ?? null;
    if (this.costDirty && this.costBase && !this.costConflict && this.settingsRecord && this.marketOptions && costSignature(this.settingsRecord, this.marketOptions, block, this.costBase.areaId) !== this.costBase.signature) {
      this.costConflict = true; this.costNotice = 'Market or cost settings changed while editing. Reload before saving again.';
    }
    const staleRecord = this.settingsConflict && !this.costBusy;
    adapter.model.marketCosts = marketCostsModel({
      admin, loading: this.settingsLoading || this.marketLoading, failed: this.marketOptionsFailed, record: this.settingsRecord, options: this.marketOptions, optionsAt: this.marketOptionsAt, now: Date.now(),
      dashboard, dashboardFresh: !!dashboard && dashFresh(dashboard, this.dashboardFailed), areaDraft: this.marketArea,
      blocked: this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || staleRecord || unknown,
      conflict: this.costConflict || unknown, busy: this.costBusy, awaitingRead: this.costAwaitingRead,
      notice: this.costNotice || (unknown ? 'A previous market/cost save has an unknown outcome. Reload to confirm it.' : staleRecord ? 'Settings changed elsewhere or the record is stale. Reload before changing market or costs.' : ''),
    });
    adapter.actions.editCosts = (name) => this.editCosts(name);
    adapter.actions.selectMarketArea = (id) => this.selectMarketArea(id);
    adapter.actions.saveMarket = (values) => this.saveMarket(values);
    adapter.actions.saveTariff = (values) => this.saveTariff(values);
    adapter.actions.savePriceEntry = (values) => this.savePriceEntry(values);
    adapter.actions.reloadMarketCosts = () => this.reloadMarketCosts();
  },
  editCosts(name) {
    if (name && name !== 'area') this.costFeeEdited = true;
    if (this.costDirty) return;
    const decoded = decodeDashboard(this.rawDashboard);
    const record = this.settingsRecord;
    this.costBase = record && this.marketOptions ? { areaId: record.area_id, signature: costSignature(record, this.marketOptions, decoded.ok ? decoded.value.grid_tariff : null, record.area_id) } : null;
    this.costDirty = true;
  },
  selectMarketArea(id) {
    const saved = this.settingsRecord?.area_id || '';
    const target = !id || id === saved ? null : id;
    if (target === this.marketArea) { this.paint(); return; }
    if (this.costFeeEdited && !window.confirm('Changing the price area discards your unsaved tax and fee edits for the current one; fees for the new area start from what is stored for it. Continue?')) {
      this.view?.setMarketDraft('area', this.marketArea || saved); this.paint(); return;
    }
    this.view?.resetMarketDrafts(true); this.costFeeEdited = false; this.marketArea = target; this.costNotice = ''; this.paint();
  },
  reloadMarketCosts() {
    const charger = this.charger;
    if (!this.connected || !charger || this.costBusy || this.settingsBusy || this.pendingCostWrites.has(charger)) return;
    if (this.settingsDirty || this.settingsConflict) { this.reloadSettings(); void this.loadMarketOptions(true); return; }
    if (this.costDirty && !window.confirm('Discard the unsaved market and cost changes and reload?')) return;
    this.resetCosts(); this.unknownCostWrites.delete(charger); this.settingsRecord = null; this.marketOptions = null; this.marketOptionsAt = null;
    this.paint(); void this.loadSettings(); void this.loadMarketOptions(true); this.refresh();
  },
  async loadMarketOptions(force = false) {
    if (this.marketLoading || !this.charger || !this._hass) return;
    if (!force && this.marketOptions && Date.now() - (this.marketOptionsAt || 0) < OPTIONS_REFRESH_MS) return;
    const generation = this.generation, charger = this.charger, hass = this._hass;
    const current = () => this.connected && generation === this.generation && charger === this.charger;
    this.marketLoading = true;
    try {
      const decoded = decodeMarketOptions(await this.bounded(getMarketOptions(hass, charger)));
      if (!current()) return;
      if (!decoded.ok) { this.marketOptionsFailed = true; this.costNotice = decoded.failure === 'unsupported' ? translate('en', 'market.error.version') : translate('en', 'market.error.read'); return; }
      this.marketOptions = decoded.value; this.marketOptionsAt = Date.now(); this.marketOptionsFailed = false;
      if (this.costNotice === translate('en', 'market.error.version') || this.costNotice === translate('en', 'market.error.read') || this.costNotice === 'The area list could not be read. Use Reload to try again.') this.costNotice = '';
    } catch { if (current()) { this.marketOptionsFailed = true; if (!this.marketOptions) this.costNotice = 'The area list could not be read. Use Reload to try again.'; } }
    finally { if (this.connected && generation === this.generation) { this.marketLoading = false; this.paint(); } }
  },
  costWriteBlocked(record) {
    const charger = this.charger, hass = this._hass;
    return !this.connected || hass?.connected === false || hass?.user?.is_admin !== true || !charger || !record || this.costBusy || this.marketLoading || this.settingsLoading || this.pendingCostWrites.has(charger) || this.unknownCostWrites.has(charger) || this.costConflict || this.costAwaitingRead || this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.settingsConflict;
  },
  costReadiness(dashboard) {
    if (!dashboard || !dashFresh(dashboard, this.dashboardFailed)) return 'The dashboard observation is stale. Wait for a fresh read or reload before saving.';
    if (!this.marketOptions || this.marketOptionsFailed || Date.now() - (this.marketOptionsAt || 0) > OPTIONS_MAX_AGE_MS) return 'The area list is stale or unavailable. Reload before saving.';
    return '';
  },
  async finishCostWrite(generation, charger, body) {
    this.costBusy = true; this.statusEpoch++; this.statusAt = null; this.paint();
    try { await body(); }
    finally { if (this.connected && generation === this.generation && charger === this.charger) { this.costBusy = false; this.dashboardEpoch++; this.paint(); this.refresh(); } }
  },
  /** Run one dispatched write: its own answer is the only thing that settles the outcome. */
  async dispatchCostWrite(label, makeRequest, settle) {
    const generation = this.generation, permissionEpoch = this.permissionEpoch, charger = this.charger;
    const current = () => this.connected && generation === this.generation && permissionEpoch === this.permissionEpoch && charger === this.charger;
    await this.finishCostWrite(generation, charger, async () => {
      const request = makeRequest();
      this.pendingCostWrites.set(charger, request);
      request.finally(() => { if (this.pendingCostWrites.get(charger) === request) this.pendingCostWrites.delete(charger); }).catch(() => {});
      this.costNotice = 'Saving…'; this.paint();
      const unknown = (text) => { this.unknownCostWrites.add(charger); if (this.connected && generation === this.generation) { this.costConflict = true; this.costNotice = text; } };
      try {
        const answer = await this.bounded(request);
        if (!current()) { this.unknownCostWrites.add(charger); return; }
        settle(answer, unknown);
      } catch (error) {
        const code = error?.code;
        if (!current()) { this.unknownCostWrites.add(charger); return; }
        if (code === GRID_TARIFF_CONFLICT) { this.costConflict = true; this.settingsConflict = true; this.settingsNotice = 'Market or cost settings changed elsewhere. Reload settings before editing again.'; this.costNotice = `${label} not saved: the electricity price was changed elsewhere since it was read; nothing was written. Reload and review the new values.`; return; }
        if (REFUSED(code)) { this.costNotice = `${label} not saved: ${translate('en', settingsErrorKey(code))} (${code}).`; return; }
        unknown('Save outcome unknown; the request may still complete. Wait, then reload before retrying.');
      }
    });
  },
  async saveMarket(values) {
    const record = this.settingsRecord, options = this.marketOptions, hass = this._hass, charger = this.charger, generation = this.generation, permissionEpoch = this.permissionEpoch;
    const decoded = decodeDashboard(this.rawDashboard), dashboard = decoded.ok ? decoded.value : null;
    if (this.costWriteBlocked(record)) { this.costNotice = 'Save unavailable: another request is running, a previous outcome is unknown or stale, or permission is missing.'; this.paint(); return; }
    const notReady = this.costReadiness(dashboard);
    if (notReady || !marketEditable(options.state, true)) { this.costNotice = notReady || 'The area list is not held, so nothing can be changed.'; this.paint(); return; }
    const plan = marketWritePlan(record, options, values, true);
    if (!plan.ok) { this.costNotice = plan.notice; this.paint(); return; }
    if (!plan.changed) { this.costNotice = 'No changes to save.'; this.paint(); return; }
    if (plan.areaChanged && !window.confirm(`Switch the price area from ${plan.fromArea || 'none'} to ${plan.toArea}? This changes the prices, currency and price provider route used for planning${dashboard?.price_source ? ` by all ${dashboard.price_source.charger_count} charger(s) using “${dashboard.price_source.title}”` : ''}. Fees do not carry over, and a soft price cap is not converted between currencies — review it afterwards.`)) return;
    if (this.costWriteBlocked(this.settingsRecord) || this.settingsRecord !== record || this.generation !== generation || this.permissionEpoch !== permissionEpoch || this.charger !== charger) { this.costNotice = 'State changed; review the values and try again.'; this.paint(); return; }
    await this.dispatchCostWrite('Area and taxes', () => updateSettings(hass, charger, record.revision, plan.body), (raw, unknown) => {
      const answer = decodeSettingsAnswer(raw);
      if (!answer.ok) { unknown('Save response unavailable; outcome unknown. Reload before retrying.'); return; }
      const a = answer.value;
      if (a.ok) {
        this.settingsRecord = a.settings; this.settingsConflict = false; this.resetCosts(); this.costAwaitingRead = true;
        this.costNotice = `Area and taxes saved and confirmed by the backend. ${SAVED_NOTE}`;
      } else if (a.code === SETTINGS_REVISION_CONFLICT) {
        this.costConflict = true; this.settingsConflict = true; this.settingsNotice = 'Settings changed elsewhere. Reload settings before editing again.'; this.costNotice = 'Area and taxes not saved: settings were changed elsewhere; nothing was written. Reload and review the new values.';
      } else if (a.code === SETTINGS_RECONCILE_FAILED) {
        if (a.settings) { this.settingsRecord = a.settings; this.settingsConflict = false; }
        this.resetCosts(); this.costAwaitingRead = true; this.costConflict = true; this.costNotice = 'Area and taxes were saved, but replanning failed; reload and inspect the confirmed values before changing them again.';
      } else if (a.code === SETTINGS_NOT_COMMITTED) {
        this.costNotice = 'Area and taxes were not saved: the backend did not commit the change.';
      } else this.costNotice = `Area and taxes not saved: ${translate('en', settingsErrorKey(a.code))} (${a.code}).`;
    });
  },
  async saveTariff(values) {
    const hass = this._hass, charger = this.charger, generation = this.generation, permissionEpoch = this.permissionEpoch, record = this.settingsRecord;
    const decoded = decodeDashboard(this.rawDashboard), dashboard = decoded.ok ? decoded.value : null;
    if (this.costWriteBlocked(record)) { this.costNotice = 'Save unavailable: another request is running, a previous outcome is unknown or stale, or permission is missing.'; this.paint(); return; }
    const notReady = this.costReadiness(dashboard);
    if (notReady) { this.costNotice = notReady; this.paint(); return; }
    const block = dashboard.grid_tariff;
    const plan = tariffWritePlan(block, values);
    if (!plan.ok) { this.costNotice = plan.notice; this.paint(); return; }
    if (!plan.changed) { this.costNotice = 'No changes to save.'; this.paint(); return; }
    if (this.costWriteBlocked(this.settingsRecord) || this.settingsRecord !== record || this.generation !== generation || this.permissionEpoch !== permissionEpoch || this.charger !== charger) { this.costNotice = 'State changed; review the values and try again.'; this.paint(); return; }
    await this.dispatchCostWrite('Grid tariff', () => updateGridTariff(hass, charger, plan.expected, plan.body), (answer, unknown) => {
      if (!answer || answer.ok !== true) { unknown('Save response unavailable; outcome unknown. Reload before retrying.'); return; }
      // The price entry's write counter moved, and with it the settings record's revision: read it again.
      this.settingsRecord = null; this.settingsConflict = false; this.resetCosts(); this.costAwaitingRead = true;
      this.costNotice = `Grid tariff saved and confirmed by the backend. ${SAVED_NOTE}`;
    });
  },
  async savePriceEntry(values) {
    const hass = this._hass, charger = this.charger, generation = this.generation, permissionEpoch = this.permissionEpoch, record = this.settingsRecord;
    const decoded = decodeDashboard(this.rawDashboard), dashboard = decoded.ok ? decoded.value : null;
    if (this.costWriteBlocked(record)) { this.costNotice = 'Save unavailable: another request is running, a previous outcome is unknown or stale, or permission is missing.'; this.paint(); return; }
    const notReady = this.costReadiness(dashboard);
    if (notReady) { this.costNotice = notReady; this.paint(); return; }
    const source = dashboard.price_source && dashboard.price_source.writable ? { base: dashboard.price_source.entry_id, count: dashboard.price_source.charger_count, choices: dashboard.price_source.choices.map((c) => ({ value: c.entry_id, text: c.title })) } : null;
    const plan = sourceWritePlan(source, values);
    if (!plan.ok) { this.costNotice = plan.notice; this.paint(); return; }
    if (!plan.changed) { this.costNotice = 'No changes to save.'; this.paint(); return; }
    const title = source.choices.find((c) => c.value === plan.entryId)?.text || plan.entryId;
    if (!window.confirm(`Use the electricity price entry “${title}”? Its area, provider route and fees apply to ${plan.count} charger(s) now using the current one, and plans are recalculated. SpotNav does not copy fees between entries.`)) return;
    if (this.costWriteBlocked(this.settingsRecord) || this.settingsRecord !== record || this.generation !== generation || this.permissionEpoch !== permissionEpoch || this.charger !== charger) { this.costNotice = 'State changed; review the values and try again.'; this.paint(); return; }
    await this.dispatchCostWrite('Price entry', () => choosePriceSource(hass, charger, plan.entryId), (answer, unknown) => {
      if (!answer || answer.ok !== true) { unknown('Save response unavailable; outcome unknown. Reload before retrying.'); return; }
      this.settingsRecord = null; this.settingsConflict = false; this.resetCosts(); this.costAwaitingRead = true;
      this.costNotice = `Price entry chosen and confirmed by the backend. ${SAVED_NOTE}`;
    });
  },
};
