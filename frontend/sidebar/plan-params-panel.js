// Stage 13.3 — the panel's wiring of the "Plan & charger parameters" area, installed on the panel's prototype. Opening or
// editing only reads. Every write is the EXISTING canonical `update_settings` replacement (compare-and-set on the wire
// revision, built from the accepted record with only the fields this area owns changed), sharing the plan form's own
// pending/unknown-outcome bookkeeping so two saves of the same record can never overlap. Once a request is dispatched only
// its own answer settles the outcome; anything else is an unknown outcome that needs an explicit reload.
import { updateSettings } from '../src/api.ts';
import { decodeSettingsAnswer, settingsErrorKey } from '../src/settings.ts';
import { decodeDashboard } from '../src/validate.ts';
import { SETTINGS_REVISION_CONFLICT, SETTINGS_RECONCILE_FAILED, SETTINGS_NOT_COMMITTED } from '../src/types.ts';
import { translate } from '../src/i18n/index.ts';
import { decodeMorekState } from '../src/morek-view.ts';
import { observationFreshness } from '../src/observation-freshness.ts';
import { planParamsModel, periodsWritePlan, currentWritePlan, departureWritePlan, paramSignature, SAVED_NOTE, MOREK_REQUIRED_AMPS } from './plan-params.js';

/** Codes a command answers with BEFORE it writes anything: the person sees "not saved". Anything else is unknown. */
const REFUSED = (code) => typeof code === 'string' && (code === 'spotnav_not_admin' || code === 'spotnav_unknown_charger' || code === 'spotnav_unsupported_api_version' || code === 'spotnav_invalid_value' || code === 'revision_conflict' || code.startsWith('invalid_'));
const dashFresh = (dashboard, failed) => observationFreshness(Date.parse(dashboard?.generated_at || ''), Date.now(), failed) === 'fresh';

export const planParamMethods = {
  initParams() {
    this.paramDirty = false; this.paramBase = null; this.paramBusy = false; this.paramConflict = false; this.paramNotice = ''; this.paramAwaitingRead = false;
  },
  resetParams() {
    this.view?.resetParamDrafts();
    this.paramDirty = false; this.paramBase = null; this.paramConflict = false; this.paramNotice = '';
  },
  paintPlanParams(adapter, dashboard, morekOwned) {
    const admin = this._hass?.user?.is_admin === true, charger = this.charger;
    const unknown = this.unknownSettingsWrites.has(charger) || this.pendingSettingsWrites.has(charger);
    if (this.paramDirty && this.paramBase && !this.paramConflict && this.settingsRecord && paramSignature(this.settingsRecord, dashboard) !== this.paramBase.signature) {
      this.paramConflict = true; this.paramNotice = 'The plan or charger parameters changed while editing. Reload before saving again.';
    }
    adapter.model.planParams = planParamsModel({
      admin, loading: this.settingsLoading, record: this.settingsRecord, dashboard, dashboardFresh: !!dashboard && dashFresh(dashboard, this.dashboardFailed), now: Date.now(), morekOwned,
      blocked: this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || unknown,
      conflict: this.paramConflict || this.settingsConflict || unknown, busy: this.paramBusy, awaitingRead: this.paramAwaitingRead,
      notice: this.paramNotice || (unknown ? 'A previous settings save has an unknown outcome. Reload to confirm it.' : this.settingsConflict ? 'Settings changed elsewhere or the record is stale. Reload before changing these parameters.' : ''),
    });
    adapter.actions.editParams = () => this.editParams();
    adapter.actions.saveParams = (kind, values) => this.saveParams(kind, values);
    adapter.actions.reloadPlanParams = () => this.reloadPlanParams();
  },
  editParams() {
    if (this.paramDirty) return;
    const decoded = decodeDashboard(this.rawDashboard);
    this.paramBase = this.settingsRecord ? { signature: paramSignature(this.settingsRecord, decoded.ok ? decoded.value : null) } : null;
    this.paramDirty = true;
  },
  reloadPlanParams() {
    const charger = this.charger;
    if (!this.connected || !charger || this.paramBusy || this.settingsBusy || this.pendingSettingsWrites.has(charger)) return;
    if (this.paramDirty && !window.confirm('Discard the unsaved parameter changes and reload?')) return;
    this.resetParams(); this.unknownSettingsWrites.delete(charger); this.settingsConflict = false; this.settingsRecord = null;
    this.paint(); void this.loadSettings(); this.refresh();
  },
  /** true / false from fresh Morek status; null when it is unknown (conservative: treated as possibly owned). */
  morekOwnedNow() {
    const st = this.rawStatus ? decodeMorekState(this.rawStatus) : null;
    return st && st.ownership && observationFreshness(this.statusAt, Date.now(), this.statusFailed) === 'fresh' ? st.ownership.recorded_owner === 'morek_schedule' : null;
  },
  paramWriteBlocked(record, allowed) {
    const charger = this.charger, hass = this._hass;
    return !this.connected || hass?.connected === false || !allowed || !charger || !record || this.paramBusy || this.settingsLoading || this.pendingSettingsWrites.has(charger) || this.unknownSettingsWrites.has(charger) || this.paramConflict || this.paramAwaitingRead || this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || this.settingsConflict;
  },
  async saveParams(kind, values) {
    const record = this.settingsRecord, hass = this._hass, charger = this.charger, generation = this.generation, permissionEpoch = this.permissionEpoch;
    const decoded = decodeDashboard(this.rawDashboard), dashboard = decoded.ok ? decoded.value : null;
    const admin = hass?.user?.is_admin === true, planAllowed = admin || dashboard?.settings?.users_change_plan === true;
    const say = (text) => { this.paramNotice = text; this.paint(); };
    const allowed = kind === 'periods' ? admin : planAllowed;
    if (this.paramWriteBlocked(record, allowed)) return say('Save unavailable: another request is running, a previous outcome is unknown or stale, or permission is missing.');
    if (!dashboard || !dashFresh(dashboard, this.dashboardFailed)) return say('The dashboard observation is stale. Wait for a fresh read or reload before saving.');
    const now = Date.now();
    const plan = kind === 'periods' ? periodsWritePlan(record, values, admin) : kind === 'current' ? currentWritePlan(record, values, planAllowed, dashboard, this.morekOwnedNow()) : kind === 'departure' ? departureWritePlan(record, values, planAllowed, dashboard, now) : { ok: false, notice: 'Unknown parameter group.' };
    if (!plan.ok) return say(plan.notice);
    if (!plan.changed) return say('No changes to save.');
    if (kind === 'current' && plan.morekBlocks && !window.confirm(`Planned current ${plan.to} A is not ${MOREK_REQUIRED_AMPS} A. It is saved as chosen, but a Morek schedule cannot be sent while the current is anything other than ${MOREK_REQUIRED_AMPS} A, and it is not known whether Morek owns the schedule now. If it does, automatic scheduling will stop. Save ${plan.to} A anyway?`)) return;
    if (kind === 'current' && record.amps !== null && plan.to > record.amps && !window.confirm(`Raise the planned current from ${record.amps} A to ${plan.to} A? The plan will assume this current. It does not change load balancing or electrical protection, and the charger and installation must really support it.`)) return;
    const label = kind === 'periods' ? 'Charging periods' : kind === 'current' ? 'Planned current' : 'Departure';
    if (this.paramWriteBlocked(this.settingsRecord, allowed) || this.settingsRecord !== record || this.generation !== generation || this.permissionEpoch !== permissionEpoch || this.charger !== charger) return say('State changed; review the values and try again.');
    const current = () => this.connected && generation === this.generation && permissionEpoch === this.permissionEpoch && charger === this.charger;
    this.paramBusy = true; this.statusEpoch++; this.statusAt = null; this.paint();
    try {
      const request = updateSettings(hass, charger, record.revision, plan.body);
      this.pendingSettingsWrites.set(charger, request);
      request.finally(() => { if (this.pendingSettingsWrites.get(charger) === request) this.pendingSettingsWrites.delete(charger); }).catch(() => {});
      this.paramNotice = 'Saving…'; this.paint();
      const unknown = (text) => { this.unknownSettingsWrites.add(charger); if (this.connected && generation === this.generation) { this.paramConflict = true; this.paramNotice = text; } };
      try {
        const answer = decodeSettingsAnswer(await this.bounded(request));
        if (!current()) { this.unknownSettingsWrites.add(charger); return; }
        if (!answer.ok) unknown('Save response unavailable; outcome unknown. Reload before retrying.');
        else if (answer.value.ok) {
          this.settingsRecord = answer.value.settings; this.settingsConflict = false; this.resetParams(); this.paramAwaitingRead = true;
          this.paramNotice = `${label} saved and confirmed by the backend. ${SAVED_NOTE}`;
        } else if (answer.value.code === SETTINGS_REVISION_CONFLICT) {
          this.paramConflict = true; this.settingsConflict = true; this.settingsNotice = 'Settings changed elsewhere. Reload settings before editing again.';
          this.paramNotice = `${label} not saved: settings were changed elsewhere; nothing was written. Reload and review the new values.`;
        } else if (answer.value.code === SETTINGS_RECONCILE_FAILED) {
          if (answer.value.settings) { this.settingsRecord = answer.value.settings; this.settingsConflict = false; }
          this.resetParams(); this.paramAwaitingRead = true; this.paramConflict = true;
          this.paramNotice = `${label} were saved, but replanning failed; reload and inspect the confirmed values before changing them again.`;
        } else if (answer.value.code === SETTINGS_NOT_COMMITTED) this.paramNotice = `${label} not saved: the backend did not commit the change.`;
        else this.paramNotice = `${label} not saved: ${translate('en', settingsErrorKey(answer.value.code))} (${answer.value.code}).`;
      } catch (error) {
        const code = error?.code;
        if (!current()) { this.unknownSettingsWrites.add(charger); return; }
        if (REFUSED(code)) this.paramNotice = `${label} not saved: ${translate('en', settingsErrorKey(code))} (${code}).`;
        else unknown('Save outcome unknown; the request may still complete. Wait, then reload before retrying.');
      }
    } finally {
      if (this.connected && generation === this.generation && charger === this.charger) { this.paramBusy = false; this.dashboardEpoch++; this.paint(); this.refresh(); }
    }
  },
};
