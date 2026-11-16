import { escapeText as e } from './text.js';

/** The price-day navigation row (Stage 7.1). Disabled days state their reason in text, not only in a tooltip. */
export function renderPriceNav(nav) {
  if (!nav || !Array.isArray(nav.buttons)) return '';
  const buttons = nav.buttons.map(b => `<wa-button size="small" data-price-nav="${e(b.id)}" ${b.enabled ? '' : 'disabled'} ${b.selected ? 'variant="brand" aria-pressed="true"' : 'aria-pressed="false"'} ${b.enabled ? '' : `title="${e(b.reason)}"`}>${e(b.label)}${b.partial ? ' (partial)' : ''}</wa-button>`).join('');
  const reasons = nav.buttons.filter(b => !b.enabled && b.reason && b.id !== 'all').map(b => `${e(b.label)}: ${e(b.reason)}`).join(' · ');
  const picker = nav.earlier?.open ? `<label class="price-nav-picker">Held day <select data-price-nav-day aria-label="Earlier held day"><option value="">Choose a day…</option>${nav.earlier.days.map(d => `<option value="${e(d.day)}" ${d.day === nav.selectedDay ? 'selected' : ''}>${e(d.label)}${d.partial ? ' · partial' : ''}</option>`).join('')}</select></label><span class="subtext">${e(nav.earlier.hint)}</span>` : '';
  const retry = nav.canRetry ? '<wa-button size="small" data-price-nav="retry">Retry</wa-button>' : '';
  return `<div class="price-nav" role="group" aria-label="Price day navigation" data-price-nav-status="${e(nav.status)}"><div class="price-nav-buttons">${buttons}${retry}</div>${picker}<p class="subtext price-nav-note" role="status">${e(nav.message || nav.detail || '')}${nav.message && nav.detail ? ` ${e(nav.detail)}` : ''}</p>${reasons ? `<p class="subtext price-nav-reasons">${reasons}</p>` : ''}</div>`;
}
