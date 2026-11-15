// Stage 13.4 — the advanced "Notifications & setup" area: per-charger recipients (Home Assistant mobile apps) and event
// settings, plus a compact list of the setup problems the dashboard and Morek status already report. Pure: it describes the
// saved settings record and the observations and builds the body of the EXISTING canonical `update_settings` replacement
// (`notificationsReplacement`, the old card's own builder). It never writes; the panel owns every request and the backend
// keeps the final word. A notification only says SpotNav noticed an event: it never proves a plan was sent or that charging
// was measured, and saving here sends nothing, wakes nothing and notifies nobody.
import { notificationsReplacement } from '../src/settings.ts';
import { eventOptions, phoneOptions, noRecipientsHint } from '../src/notifications.ts';
import { setupRowsOf, setupRowText } from '../src/setup-checklist.ts';
import { translate } from '../src/i18n/index.ts';
import { recoveryBanner } from './recovery-banner.js';

export const MAX_TARGETS = 10; // `notifications.settings.MAX_TARGETS`
export const NOTICE_NOTE = 'A notification only says SpotNav noticed an event. It does not prove a plan was sent to the charger or that charging was measured; check Plan activity & freshness for that. Saving here only stores your choice: it sends no notification and does not wake the car.';
/** Where a diagnostic row can take the person: the sections of this sidebar (a section the sidebar does not have gets no link). */
export const GOTO = { 'vehicle-sources': 'Vehicle sources & properties', 'market-costs': 'Market & charging costs', morek: 'Plan activity & freshness', 'notify-setup': 'Notifications' };

// The setup rows that concern measurement sources, and where each is fixed. A site or grid meter is not set up in this
// sidebar, so those rows say so instead of linking.
const MEASUREMENT_ROWS = { vehicle: 'vehicle-sources', car_level: 'vehicle-sources', site: null, grid_power_sign: null, grid_current_sign: null, demand_grid_power: null };

/** The facts a draft is compared against: another writer changing the choice after editing began is a conflict (the phones that exist now are not part of it). */
export function notifySignature(record) {
  const n = record?.notifications;
  return JSON.stringify(n ? [n.targets, n.events, n.url] : null);
}

const row = (id, group, level, text, goto = null) => ({ id, group, level, text, goto, gotoLabel: goto ? GOTO[goto] : null });

/** Existing setup, pricing and execution problems, each worded by the existing text; nothing is invented and unknown is said as unknown. */
export function setupDiagnostics({ dashboard, status, statusFresh, now }) {
  const out = [];
  if (!dashboard) return [row('dashboard', 'setup', 'info', 'No dashboard observation yet, so setup problems are unknown.')];
  const rows = setupRowsOf(dashboard.setup ?? null);
  if (dashboard.setup == null) out.push(row('setup-unknown', 'setup', 'info', 'The backend did not report what is left to set up, so that is unknown (it is shown to administrators only).'));
  for (const r of rows) {
    if (!(r.id in MEASUREMENT_ROWS)) continue;
    const goto = MEASUREMENT_ROWS[r.id];
    out.push(row(`setup-${r.id}`, 'measurement', r.id === 'grid_power_sign' || r.id === 'grid_current_sign' ? 'warning' : 'info', `${setupRowText('en', r.id)}${goto ? '' : ' This is set up in Home Assistant (the SpotNav card or the site settings), not here.'}`, goto));
  }
  const soc = dashboard.soc;
  if (soc && (soc.value == null) && !rows.some((r) => r.id === 'car_level' || r.id === 'vehicle')) out.push(row('soc-missing', 'measurement', 'info', 'The car’s charge level has no valid reading now, so an SOC plan relies on the last known or an estimated level. Choose or check the level sensor.', 'vehicle-sources'));
  const prices = dashboard.prices;
  if (prices) {
    if (prices.provider && !prices.provider.name) out.push(row('price-provider', 'pricing', 'warning', `No price provider is configured for the saved area${prices.provider.notice ? ` (${prices.provider.notice.code.replace(/_/g, ' ')})` : ''}. Prices may be missing or held from before.`, 'market-costs'));
    if (typeof prices.state === 'string' && prices.state !== 'ready') out.push(row('price-state', 'pricing', 'warning', `Held price data is “${prices.state.replace(/_/g, ' ')}”${prices.reason ? ` (${String(prices.reason).replace(/_/g, ' ')})` : ''}, so plans may use incomplete prices. Held data is not proof the provider answered just now.`, 'market-costs'));
    else if (prices.interval_count === 0) out.push(row('price-none', 'pricing', 'warning', 'No price intervals are held, so a price-based plan cannot be made.', 'market-costs'));
  }
  if (!statusFresh) out.push(row('status-stale', 'execution', 'info', 'Morek status is unavailable or stale, so execution blockers are unknown. This is not proof that nothing is blocked.', 'morek'));
  else {
    const banner = recoveryBanner(status, now);
    if (banner) out.push(row(`exec-${banner.code || 'blocker'}`, 'execution', banner.level === 'error' ? 'error' : banner.level === 'warning' ? 'warning' : 'info', banner.text, 'morek'));
  }
  return out;
}

function recipientProblems(n, can) {
  const out = [];
  const available = new Set(n.available.map((a) => a.service));
  if (n.available.length === 0) out.push('No Home Assistant mobile app is registered for notifications. Install the Home Assistant Companion app on a phone and sign in (or use the SpotNav app), then Reload.');
  const missing = n.targets.filter((t) => !available.has(t));
  for (const t of missing) out.push(`${t.replace(/^mobile_app_/, '').replace(/_/g, ' ')} is chosen but its notify service is not available now (the phone may be offline or re-registered). It is kept, and skipped when sending, until you untick it.`);
  const hint = noRecipientsHint('en', n);
  if (hint) out.push(`${hint} Tick at least one phone to receive the ticked events.`);
  if (n.events.length === 0 && n.targets.length > 0) out.push('No events are ticked, so nothing is sent even to the chosen phones.');
  if (!can) out.push('Only an administrator can change notifications.');
  return out;
}

/**
 * The area's model. `input`: {admin, loading, record (saved settings record), dashboard (decoded), dashboardFresh, status (decoded
 * Morek state or null), statusFresh, now, blocked, conflict, busy, awaitingRead, notice}.
 */
export function notifyModel(input) {
  const base = { notice: input.notice || '', conflict: !!input.conflict, busy: !!input.busy };
  const diagnostics = setupDiagnostics({ dashboard: input.dashboard || null, status: input.status || null, statusFresh: input.statusFresh === true, now: input.now ?? Date.now() });
  const record = input.record || null, n = record?.notifications;
  if (!record) return { ...base, state: input.loading ? 'loading' : 'unavailable', canEdit: false, diagnostics, notice: base.notice || (input.loading ? 'Loading notification settings…' : 'Notification settings unavailable. Use Reload to try again.') };
  if (!n) return { ...base, state: 'unsupported', canEdit: false, diagnostics, notice: base.notice || 'This backend does not offer notification settings; nothing can be chosen here.' };
  const fresh = input.dashboardFresh !== false && !!input.dashboard;
  const admin = input.admin === true;
  const open = !input.blocked && !input.conflict && !input.busy && !input.awaitingRead && fresh && admin;
  const notes = [];
  if (!admin) notes.push('Only an administrator can change notifications; they are shown read-only.');
  if (admin && !fresh) notes.push('The dashboard observation is stale; changes are disabled until it is read again.');
  if (input.awaitingRead && admin) notes.push('Waiting for a fresh dashboard read after the last save before another change.');
  const phones = phoneOptions('en', n).map((o) => ({ service: o.value, name: o.label, checked: n.targets.includes(o.value), missing: !n.available.some((a) => a.service === o.value) }));
  const events = eventOptions('en').map((o) => ({ event: o.value, label: o.label, checked: n.events.includes(o.value) }));
  return { ...base, state: 'ready', canEdit: open, notes, phones, events, problems: recipientProblems(n, admin), diagnostics, noticeNote: NOTICE_NOTE };
}

/** What a notifications save would do. `values`: {targets: [service…], events: [event…]}. The tap-through `url` is kept exactly as saved. */
export function notifyWritePlan(record, values, admin) {
  if (!admin) return { ok: false, notice: 'Administrator permission is required to change notifications.' };
  const n = record?.notifications;
  if (!record) return { ok: false, notice: 'Reload the settings first.' };
  if (!n) return { ok: false, notice: 'This backend does not offer notification settings.' };
  const targets = Array.isArray(values?.targets) ? values.targets.filter((t) => typeof t === 'string') : [];
  const events = Array.isArray(values?.events) ? values.events.filter((t) => typeof t === 'string') : [];
  const allowed = new Set([...n.available.map((a) => a.service), ...n.targets]);
  if (targets.some((t) => !allowed.has(t))) return { ok: false, notice: 'A chosen phone is not one of the available phones. Reload and choose again.' };
  if (new Set(targets).size > MAX_TARGETS) return { ok: false, notice: `At most ${MAX_TARGETS} phones can be chosen.` };
  const check = notificationsReplacement(record, { targets, events, url: n.url });
  if (!check.ok) return { ok: false, notice: translate('en', check.errorKey) };
  if (!check.changed) return { ok: true, changed: false };
  const sent = check.body.notifications;
  return { ok: true, changed: true, body: check.body, targets: sent.targets, events: sent.events, sendsNothing: sent.targets.length === 0 || sent.events.length === 0 };
}
