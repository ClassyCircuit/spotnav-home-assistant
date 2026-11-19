import { escapeText as e } from './text.js';
import { PRICE_BANDS } from './price-bands.js';

// All prose and values are supplied by the host (see `price-insights.js`); they are text, never markup.
// Controls only name a read (`data-insight-*`); the host decides what, if anything, is requested.
const options = (list, value) => list.map(o => `<option value="${e(o.value)}"${String(o.value) === String(value) ? ' selected' : ''}>${e(o.label)}</option>`).join('');
const lines = block => (block.lines || []).length ? `<ul class="insight-lines">${block.lines.map(l => `<li><b>${e(l.label)}</b> ${e(l.text)}</li>`).join('')}</ul>` : '';
const details = block => (block.details || []).length ? `<wa-details summary="Basis and baseline" class="insight-details"><div class="details-body">${block.details.map(t => `<p>${e(t)}</p>`).join('')}</div></wa-details>` : '';
const table = t => !t ? '' : t.eligible
  ? `<div class="insight-compare" data-insight-compare-state="ready"><table><thead><tr>${t.head.map(h => `<th scope="col">${e(h)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(r => `<tr>${r.map((c, i) => i ? `<td>${e(c)}</td>` : `<th scope="row">${e(c)}</th>`).join('')}</tr>`).join('')}</tbody></table><p>${e(t.note)}</p></div>`
  : `<p class="insight-compare" data-insight-compare-state="none" role="status">${e(t.text)}</p>`;

function controls(block, c) {
  if (!c) return '';
  if (block.id === 'window') return `<label class="insight-control">Window length <select data-insight-duration aria-label="Window length"${c.duration.busy ? ' disabled' : ''}>${options(c.duration.options, c.duration.value)}</select></label>`;
  if (block.id !== 'month') return '';
  const previous = c.compare.previous ? `<wa-button size="small" data-insight-compare-previous>Compare with ${e(c.compare.previous.label)}</wa-button>` : '';
  return `<div class="insight-controls"><label class="insight-control">Month <select data-insight-month aria-label="Month"${c.month.busy ? ' disabled' : ''}>${options(c.month.options, c.month.value)}</select></label>`
    + `<label class="insight-control">Compare with <select data-insight-compare aria-label="Compare with another month"${c.compare.busy ? ' disabled' : ''}>${options(c.compare.options, c.compare.value)}</select></label>${previous}</div>`;
}

const bandDot = key => { const b = PRICE_BANDS.find(x => x.key === key); return b ? `<span class="cl-dot ${e(b.css)}" aria-hidden="true">●</span> ` : ''; };
const block = (b, c) => `<section class="insight-block"${b.id ? ` data-insight-block="${e(b.id)}"` : ''}${b.band ? ` data-insight-band="${e(b.band)}"` : ''}><h3>${e(b.title)}</h3><div class="insight-value">${bandDot(b.band)}${e(b.value)}</div><strong class="insight-status">${e(b.status ?? '')}</strong>${b.detail ? `<p>${e(b.detail)}</p>` : ''}${lines(b)}${b.extra ? `<div class="month-range">${e(b.extra)}</div>` : ''}${controls(b, c)}${table(b.table)}${details(b)}</section>`;

export function renderInsights(insights) {
  if (!insights) return '<p>Price insights unavailable.</p>';
  const blocks = Array.isArray(insights.blocks) ? insights.blocks : [];
  const banners = (insights.banners || []).map(x => `<p class="insight-banner" data-insight-banner="${e(x.kind)}" role="status">${e(x.text)}</p>`).join('');
  const retry = insights.controls?.canRetry ? '<wa-button size="small" data-insight-retry>Retry</wa-button>' : '';
  return `<div class="insights-intro" data-insight-state="${e(insights.state ?? 'ready')}">${e(insights.intro)}</div>${banners}${retry}<div class="insight-grid">${blocks.map(b => block(b, insights.controls)).join('')}</div><p class="insight-caution">${e(insights.caution)}</p><wa-details summary="How these insights work"><div class="details-body"><p>${e(insights.method)}</p></div></wa-details>`;
}
