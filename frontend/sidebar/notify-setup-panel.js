// Stage 13.4 — the panel's wiring of the "Notifications & setup" area, installed on the panel's prototype. Opening or editing
// only reads. Every write is the EXISTING canonical `update_settings` replacement (compare-and-set on the wire revision, built
// from the accepted record with only `notifications` changed), sharing the plan form's pending/unknown-outcome bookkeeping so
// two saves of the same record can never overlap. Once a request is dispatched only its own answer settles the outcome;
// anything else is an unknown outcome that needs an explicit reload. A notification setting never proves a plan was sent.
import { updateSettings } from '../src/api.ts';
import { decodeSettingsAnswer, settingsErrorKey } from '../src/settings.ts';
import { decodeDashboard } from '../src/validate.ts';
import { SETTINGS_REVISION_CONFLICT, SETTINGS_RECONCILE_FAILED, SETTINGS_NOT_COMMITTED } from '../src/types.ts';
import { translate } from '../src/i18n/index.ts';
import { decodeMorekState } from '../src/morek-view.ts';
import { observationFreshness } from '../src/observation-freshness.ts';
import { notifyModel, notifyWritePlan, notifySignature } from './notify-setup.js';

/** Codes a command answers with BEFORE it writes anything: the person sees "not saved". Anything else is unknown. */
const REFUSED = (code) => typeof code === 'string' && (code === 'spotnav_not_admin' || code === 'spotnav_unknown_charger' || code === 'spotnav_unsupported_api_version' || code === 'spotnav_invalid_value' || code === 'revision_conflict' || code.startsWith('invalid_'));
const dashFresh = (dashboard, failed) => observationFreshness(Date.parse(dashboard?.generated_at || ''), Date.now(), failed) === 'fresh';

export const notifySetupMethods = {
  initNotify() {
    this.notifyDirty = false; this.notifyBase = null; this.notifyBusy = false; this.notifyConflict = false; this.notifyNotice = ''; this.notifyAwaitingRead = false;
  },
  resetNotify() {
    this.view?.resetNotifyDrafts();
    this.notifyDirty = false; this.notifyBase = null; this.notifyConflict = false; this.notifyNotice = '';
  },
  paintNotifySetup(adapter, dashboard) {
    const admin = this._hass?.user?.is_admin === true, charger = this.charger;
    const unknown = this.unknownSettingsWrites.has(charger) || this.pendingSettingsWrites.has(charger);
    if (this.notifyDirty && this.notifyBase && !this.notifyConflict && this.settingsRecord && notifySignature(this.settingsRecord) !== this.notifyBase.signature) {
      this.notifyConflict = true; this.notifyNotice = 'The notification settings changed while editing. Reload before saving again.';
    }
    const status = this.rawStatus ? decodeMorekState(this.rawStatus) : null;
    adapter.model.notifySetup = notifyModel({
      admin, loading: this.settingsLoading, record: this.settingsRecord, dashboard, dashboardFresh: !!dashboard && dashFresh(dashboard, this.dashboardFailed),
      status, statusFresh: !!status && observationFreshness(this.statusAt, Date.now(), this.statusFailed) === 'fresh', now: Date.now(),
      blocked: this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || this.paramBusy || unknown,
      conflict: this.notifyConflict || this.settingsConflict || unknown, busy: this.notifyBusy, awaitingRead: this.notifyAwaitingRead,
      notice: this.notifyNotice || (unknown ? 'A previous settings save has an unknown outcome. Reload to confirm it.' : this.settingsConflict ? 'Settings changed elsewhere or the record is stale. Reload before changing notifications.' : ''),
    });
    adapter.actions.editNotify = () => this.editNotify();
    adapter.actions.saveNotify = (values) => this.saveNotify(values);
    adapter.actions.reloadNotifySetup = () => this.reloadNotifySetup();
  },
  editNotify() {
    if (this.notifyDirty) return;
    this.notifyBase = this.settingsRecord ? { signature: notifySignature(this.settingsRecord) } : null;
    this.notifyDirty = true;
  },
  reloadNotifySetup() {
    const charger = this.charger;
    if (!this.connected || !charger || this.notifyBusy || this.settingsBusy || this.pendingSettingsWrites.has(charger)) return;
    if (this.notifyDirty && !window.confirm('Discard the unsaved notification changes and reload?')) return;
    this.resetNotify(); this.unknownSettingsWrites.delete(charger); this.settingsConflict = false; this.settingsRecord = null;
    this.paint(); void this.loadSettings(); this.refresh();
  },
  notifyWriteBlocked(record, admin) {
    const charger = this.charger, hass = this._hass;
    return !this.connected || hass?.connected === false || !admin || !charger || !record || this.notifyBusy || this.settingsLoading || this.pendingSettingsWrites.has(charger) || this.unknownSettingsWrites.has(charger) || this.notifyConflict || this.notifyAwaitingRead || this.settingsBusy || this.morekBusy || this.autoBusy || this.chargeBusy || this.vehicleBusy || this.costBusy || this.paramBusy || this.settingsConflict;
  },
  async saveNotify(values) {
    const record = this.settingsRecord, hass = this._hass, charger = this.charger, generation = this.generation, permissionEpoch = this.permissionEpoch;
    const decoded = decodeDashboard(this.rawDashboard), dashboard = decoded.ok ? decoded.value : null;
    const admin = hass?.user?.is_admin === true;
    const say = (text) => { this.notifyNotice = text; this.paint(); };
    if (this.notifyWriteBlocked(record, admin)) return say(admin ? 'Save unavailable: another request is running, a previous outcome is unknown or stale.' : 'Only an administrator can change notifications.');
    if (!dashboard || !dashFresh(dashboard, this.dashboardFailed)) return say('The dashboard observation is stale. Wait for a fresh read or reload before saving.');
    const plan = notifyWritePlan(record, values, admin);
    if (!plan.ok) return say(plan.notice);
    if (!plan.changed) return say('No changes to save.');
    if (this.notifyWriteBlocked(this.settingsRecord, admin) || this.settingsRecord !== record || this.generation !== generation || this.permissionEpoch !== permissionEpoch || this.charger !== charger) return say('State changed; review the values and try again.');
    const current = () => this.connected && generation === this.generation && permissionEpoch === this.permissionEpoch && charger === this.charger;
    this.notifyBusy = true; this.statusEpoch++; this.statusAt = null; this.paint();
    try {
      const request = updateSettings(hass, charger, record.revision, plan.body);
      this.pendingSettingsWrites.set(charger, request);
      request.finally(() => { if (this.pendingSettingsWrites.get(charger) === request) this.pendingSettingsWrites.delete(charger); }).catch(() => {});
      this.notifyNotice = 'Saving…'; this.paint();
      const unknown = (text) => { this.unknownSettingsWrites.add(charger); if (this.connected && generation === this.generation) { this.notifyConflict = true; this.notifyNotice = text; } };
      try {
        const answer = decodeSettingsAnswer(await this.bounded(request));
        if (!current()) { this.unknownSettingsWrites.add(charger); return; }
        if (!answer.ok) unknown('Save response unavailable; outcome unknown. Reload before retrying.');
        else if (answer.value.ok) {
          this.settingsRecord = answer.value.settings; this.settingsConflict = false; this.resetNotify(); this.notifyAwaitingRead = true;
          this.notifyNotice = `Notification settings saved and confirmed by the backend.${plan.sendsNothing ? ' With no phone or no event ticked, nothing will be sent.' : ''} This stored your choice only: no notification was sent and nothing about a plan or charging is confirmed.`;
        } else if (answer.value.code === SETTINGS_REVISION_CONFLICT) {
          this.notifyConflict = true; this.settingsConflict = true; this.settingsNotice = 'Settings changed elsewhere. Reload settings before editing again.';
          this.notifyNotice = 'Notifications not saved: settings were changed elsewhere; nothing was written. Reload and review the new values.';
        } else if (answer.value.code === SETTINGS_RECONCILE_FAILED) {
          if (answer.value.settings) { this.settingsRecord = answer.value.settings; this.settingsConflict = false; }
          this.resetNotify(); this.notifyAwaitingRead = true; this.notifyConflict = true;
          this.notifyNotice = 'Notification settings were saved, but replanning failed; reload and inspect the confirmed values before changing them again.';
        } else if (answer.value.code === SETTINGS_NOT_COMMITTED) this.notifyNotice = 'Notifications not saved: the backend did not commit the change.';
        else this.notifyNotice = `Notifications not saved: ${translate('en', settingsErrorKey(answer.value.code))} (${answer.value.code}).`;
      } catch (error) {
        const code = error?.code;
        if (!current()) { this.unknownSettingsWrites.add(charger); return; }
        if (REFUSED(code)) this.notifyNotice = `Notifications not saved: ${translate('en', settingsErrorKey(code))} (${code}).`;
        else unknown('Save outcome unknown; the request may still complete. Wait, then reload before retrying.');
      }
    } finally {
      if (this.connected && generation === this.generation && charger === this.charger) { this.notifyBusy = false; this.dashboardEpoch++; this.paint(); this.refresh(); }
    }
  },
};
