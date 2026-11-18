// Stage 20.1: the shared four-tab shell. Pure markup helpers used by the production panel and the local preview;
// nothing here owns data, actions or state beyond which tab is shown.
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

/** Four plainly named destinations; roving tabindex, automatic activation. The host keeps its own HA menu control. */
export function renderNav(active) {
  return `<nav class="sn-nav" aria-label="SpotNav sections"><div class="sn-tabs" role="tablist" aria-label="SpotNav sections">${TABS.map(([id, label]) => `<button type="button" role="tab" class="sn-tab" id="${tabButtonId(id)}" data-sn-tab="${id}" aria-controls="${tabPanelId(id)}" aria-selected="${id === active}" tabindex="${id === active ? 0 : -1}"><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20">${ICONS[id]}</svg><span>${e(label)}</span></button>`).join('')}</div></nav>`;
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
