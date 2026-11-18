// Stage 20.1/20.2: the shared SpotNav shell. Pure markup helpers used by the production panel and the local preview;
// nothing here owns data, actions or state beyond which tab is shown. The host (panel.js) owns every controller and only
// hands this module plain models plus callbacks, so the real panel and the preview render the very same header, status
// stack, hero and charging controls.
import { escapeText as e } from './text.js';

export const TABS = [['overview', 'Overview'], ['explore', 'Explore'], ['history', 'History'], ['settings', 'Settings']];
export const TAB_IDS = TABS.map(([id]) => id);

const ICONS = {
  overview: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" fill="currentColor"/>',
  explore: '<path d="M4 20V10h4v10zm6 0V4h4v16zm6 0v-7h4v7z" fill="currentColor"/>',
  history: '<path d="M13 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-7-7V3zm-1 5v5l4 2 .8-1.6-3.2-1.6V8z" fill="currentColor"/>',
  settings: '<path d="M4 7h10V5h2v2h4v2h-4v2h-2V9H4zm0 8h4v-2h2v2h10v2H10v2H8v-2H4z" fill="currentColor"/>',
};

export const tabButtonId = id => `sn-tab-${id}`;
export const tabPanelId = id => `sn-panel-${id}`;

/** Four plainly named destinations; roving tabindex, automatic activation. */
export function renderNav(active) {
  return `<nav class="sn-nav" aria-label="SpotNav sections"><div class="sn-tabs" role="tablist" aria-label="SpotNav sections">${TABS.map(([id, label]) => `<button type="button" role="tab" class="sn-tab" id="${tabButtonId(id)}" data-sn-tab="${id}" aria-controls="${tabPanelId(id)}" aria-selected="${id === active}" tabindex="${id === active ? 0 : -1}"><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20">${ICONS[id]}</svg><span>${e(label)}</span></button>`).join('')}</div></nav>`;
}

/**
 * The one SpotNav header: HA menu control, brand, charger choice and observation refresh, then the four-tab navigation
 * (top bar when wide, persistent bottom bar when compact, by CSS). Controls appear only when the host supplies the
 * callback or model for them, so a fixture host shows exactly what it can really do.
 */
export function renderHeader(header, active, can = {}) {
  const h = header || {};
  const chargers = Array.isArray(h.chargers) ? h.chargers : null;
  const select = chargers ? `<label class="sn-field sn-charger"><span>Charger</span><select id="charger" ${can.selectCharger ? '' : 'disabled'}>${[`<option value="">Select charger</option>`, ...chargers.map(c => `<option value="${e(c.id)}"${c.id === h.selected ? ' selected' : ''}>${e(c.name)}</option>`)].join('')}</select></label>` : '';
  const refresh = can.refresh ? '<button type="button" id="refresh" class="sn-btn sn-btn-quiet">Refresh observations</button>' : '';
  const menu = can.menu ? '<button type="button" id="menu" class="sn-icon-btn" aria-label="Open navigation"><svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22"><path d="M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z" fill="currentColor"/></svg></button>' : '';
  return `<header class="sn-header"><div class="sn-bar">${menu}<div class="sn-brand"><h1>SPOTNAV <span>ENHANCED</span></h1><p>${e(h.subtitle || 'White BMW iX3 · Morek charger')}</p></div>${renderNav(active)}<div class="sn-host-tools">${select}${refresh}</div></div></header>`;
}

const LEVEL_ICON = { error: '⛔', warning: '⚠', info: 'ℹ', ok: '✓', unknown: '?' };

/** Charging-status banner (charge-session evidence). A warning speaks as an alert, anything else as a calm status. */
export function renderSessionBanner(info) {
  if (!info) return '<section id="charge-session" class="sn-banner" hidden></section>';
  const lines = (info.facts || []).map(f => `<li>${e(f)}</li>`).join('');
  return `<section id="charge-session" class="sn-banner${info.warning ? ' sn-banner-strong' : ''}" role="${info.warning ? 'alert' : 'status'}" aria-label="Charging status" data-kind="${e(info.kind)}" data-level="${e(info.level)}" data-posture="${e(info.posture)}"><div class="sn-banner-title"><span aria-hidden="true">${LEVEL_ICON[info.level] || ''}</span> ${e(info.title)}</div><div class="sn-banner-detail">${e(info.detail)}</div>${info.action ? `<div class="sn-banner-action">${e(info.action)}</div>` : ''}<details class="sn-banner-facts"><summary>What SpotNav sees</summary><ul>${lines}</ul></details></section>`;
}

/** Secondary read-only schedule-check lines; never replaces the charging state above it. */
export function renderCheckBanner(notes) {
  if (!notes || !Array.isArray(notes.items) || !notes.items.length) return '<section id="schedule-check" class="sn-banner sn-banner-quiet" hidden></section>';
  const lines = notes.items.map(i => `<div data-kind="${e(i.kind)}"${i.level === 'warning' ? ' class="sn-strong"' : ''}>${e(i.text)}</div>`).join('');
  const facts = (notes.facts || []).length ? `<details class="sn-banner-facts"><summary>Schedule check details</summary><ul>${notes.facts.map(f => `<li>${e(f)}</li>`).join('')}</ul></details>` : '';
  return `<section id="schedule-check" class="sn-banner sn-banner-quiet" role="status" aria-label="Schedule check" data-kind="${e(notes.items[0].kind)}">${lines}${facts}</section>`;
}

/** Recovery/blocker message from a fresh status only (the host decides freshness). */
export function renderRecoveryBanner(banner) {
  if (!banner) return '<div id="recovery-banner" class="sn-banner sn-banner-recovery" role="alert" hidden></div>';
  return `<div id="recovery-banner" class="sn-banner sn-banner-recovery sn-banner-strong" role="alert" data-level="${e(banner.level)}" data-code="${e(banner.code)}"><span aria-hidden="true">${LEVEL_ICON[banner.level] || ''}</span> ${e(banner.text)} <button type="button" id="recovery-goto-controls" class="sn-link" data-goto-controls>Show charging controls <span aria-hidden="true">→</span></button></div>`;
}

/**
 * Status stack, visible on every tab: host message, critical live warning (details link), charging status, schedule check
 * and recovery. Identical banners are never repeated: each has exactly one element here.
 */
export function renderStatusStack(m) {
  // A held shell (disconnected, drafts kept) must not speak for a charger it can no longer observe: no stale warning or status.
  const held = m.hold === true;
  const b = held ? {} : (m.banners || {});
  const warning = !held && m.warning ? `<div class="alert sn-alert"><div><strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p></div><a href="#details">View details ↓</a></div>` : '';
  return `<div class="sn-status"><p class="message sn-notice" role="status"${m.hostMessage ? '' : ' hidden'}>${e(m.hostMessage || '')}</p><div id="critical-live" role="status" aria-live="polite">${warning}</div>${renderSessionBanner(b.session)}${renderCheckBanner(b.check)}${renderRecoveryBanner(b.recovery)}</div>`;
}

const DURATIONS = [['30', '30 minutes'], ['60', '1 hour'], ['120', '2 hours'], ['180', '3 hours'], ['custom', 'Custom end time']];

/**
 * Existing Auto pause/resume and Charge Now controls, in the hero. The host computes every label, disabled flag and notice
 * from its own gates; this markup holds no logic. `draft` holds only what the person typed (duration, custom end).
 */
export function renderControls(c, draft = {}) {
  const x = c || {};
  const duration = draft.duration ?? '60';
  const custom = duration === 'custom';
  const dis = on => (on ? ' disabled' : '');
  const busy = x.chargeBusy === true ? ' aria-busy="true"' : '', autoBusy = x.autoBusy === true ? ' aria-busy="true"' : '';
  const kind = ['pending', 'uncertain', 'info'].includes(x.chargeKind) ? x.chargeKind : '';
  const cf = x.confirm;
  // In-page, non-modal confirmation (replaces window.confirm): focus moves to Cancel, Escape cancels, nothing is sent until Confirm.
  const confirm = cf ? `<div id="charge-confirm" class="sn-confirm" role="alertdialog" aria-modal="false" aria-labelledby="charge-confirm-title" aria-describedby="charge-confirm-text" tabindex="-1" data-action="${e(cf.action)}" data-origin="${e(cf.origin || '')}" data-token="${e(cf.token)}"><strong id="charge-confirm-title">${e(cf.title)}</strong><p id="charge-confirm-text">${e(cf.text)}</p><div class="sn-btnrow"><button type="button" id="charge-confirm-cancel" class="sn-btn">Cancel</button><button type="button" id="charge-confirm-ok" class="sn-btn sn-btn-primary">${e(cf.confirmLabel || 'Confirm')}</button></div></div>` : '';
  return `<div class="sn-actions"><div id="automatic-controls" class="sn-auto" tabindex="-1"><span id="pause-state" class="sn-state">${e(x.autoState || 'Auto state unknown.')}</span><div class="sn-btnrow"><button type="button" id="pause-auto" class="sn-btn"${autoBusy}${dis(x.pauseDisabled !== false)}>Pause Auto until resumed</button><button type="button" id="resume-auto" class="sn-btn"${autoBusy}${dis(x.resumeDisabled !== false)}>Resume Auto</button></div><span id="pause-notice" class="sn-note" role="status">${e(x.pauseNotice || '')}</span></div><section id="charge-controls" class="sn-charge" aria-label="Charge Now"><details id="charge-options"><summary>Duration / change end</summary><div class="cn-fields"><label>Duration <select id="charge-duration" data-csetting="duration">${DURATIONS.map(([v, t]) => `<option value="${v}"${v === duration ? ' selected' : ''}>${t}</option>`).join('')}</select></label><label id="custom-label"${custom ? '' : ' hidden'}>End time <input id="charge-end" type="datetime-local" data-csetting="end" value="${e(draft.end ?? '')}"></label><button type="button" id="charge-replace" class="sn-btn"${busy}${x.replaceVisible ? '' : ' hidden'}${dis(x.replaceDisabled !== false)}>Replace Charge Now end</button></div></details><div class="cn-actions"><button type="button" id="charge-now" class="sn-btn sn-btn-primary"${busy}${dis(x.chargeDisabled !== false)}>${e(x.chargeLabel || 'Charge Now')}</button></div>${confirm}<span id="charge-state" class="sn-state" role="status" tabindex="-1">${e(x.chargeState || 'Charge Now status unavailable.')}</span><span id="charge-notice" class="sn-note" role="${kind === 'uncertain' ? 'alert' : 'status'}" data-kind="${kind}">${e(x.chargeNotice || '')}</span></section></div>`;
}

/**
 * Honest scene: the connected artwork (cable visibly plugged in) is shown only when the host's fresh evidence says the car
 * is connected. Unplugged and unknown use a neutral crop that shows no cable. Text stays authoritative either way, and the
 * artwork never animates or claims power flow.
 */
export function sceneOf(scene) {
  const s = scene || {};
  const connection = s.connection === 'connected' || s.connection === 'disconnected' ? s.connection : 'unknown';
  const stale = s.stale === true;
  // A stale observation is last-known, never a present fact: the cable picture is shown only for a fresh connected report.
  const label = connection === 'connected' ? (stale ? 'Last reported connected · stale' : 'Car reported connected') : connection === 'disconnected' ? (stale ? 'Last reported unplugged · stale' : 'Not plugged in') : 'Plug state unknown';
  const art = connection === 'connected' && !stale ? 'connected' : 'neutral';
  const description = art === 'connected'
    ? 'Illustration of a white BMW iX3 plugged into a Morek charger. The picture is decorative: the connection and any charging are stated in text only.'
    : `Illustration of a white BMW iX3 without a cable. The picture is decorative: ${label.toLowerCase()} is stated in text.`;
  return { connection, label, art, stale, description };
}

/** Hero artwork layer: pure CSS background so a missing image leaves a legible gradient and all text intact. */
export function renderArt(scene) {
  const s = sceneOf(scene);
  return `<div class="sn-art" data-art="${s.art}" data-art-stale="${s.stale}" role="img" aria-label="${e(s.description)}"></div>`;
}

export const tabOpen = (id, active) => `<div class="tab-panel" role="tabpanel" id="${tabPanelId(id)}" data-tab="${id}" aria-labelledby="${tabButtonId(id)}" tabindex="-1"${id === active ? '' : ' hidden'}><div class="dashboard">`;
export const tabClose = '</div></div>';

/**
 * Compact Overview summary of the retained-history day the History tab shows in full. It only restates what the
 * history model already says (state, label, spot-cost headline, session count); it adds no figure of its own.
 */
export function renderRecentSummary(day, legacy) {
  const link = '<button type="button" class="sn-link" data-open-tab="history">Open History <span aria-hidden="true">→</span></button>';
  let body;
  if (day && day.state === 'ready') {
    const cost = day.cost && typeof day.cost.headline === 'string' ? day.cost : null;
    const count = Array.isArray(day.sessions) ? day.sessions.length : null;
    body = `<p class="subtext">${e(day.nav?.label || 'Retained day')}${count === null ? '' : ` · ${count} recorded session${count === 1 ? '' : 's'} overlap this day`}. Full evidence, energy bases and coverage are in History.</p>${cost ? `<div class="history-basis"><b>${e(cost.headline)}</b>${(cost.lines || []).slice(0, 1).map(l => `<small>${e(l)}</small>`).join('')}</div>` : ''}`;
  } else if (day && day.message) {
    body = `<p class="history-banner" data-history-banner="${e(day.state || 'unavailable')}" role="status">${e(day.message)}</p>`;
  } else if (legacy && legacy.title) {
    body = `<p class="subtext">${e(legacy.title)}${legacy.subtitle ? ` — ${e(legacy.subtitle)}` : ''}</p>`;
  } else body = '<p class="subtext">Charging history is unavailable. A proposed window is not measured history.</p>';
  return `${body}${link}`;
}
