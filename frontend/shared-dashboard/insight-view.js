import { escapeText as e } from './text.js';

// All prose and values are supplied by the host; they are text, never markup.
export function renderInsights(insights) {
  if (!insights) return '<p>Price insights unavailable.</p>';
  const blocks = Array.isArray(insights.blocks) ? insights.blocks : [];
  return `<div class="insights-intro">${e(insights.intro)}</div><div class="insight-grid">${blocks.map(b => `<section class="insight-block"><h3>${e(b.title)}</h3><div class="insight-value">${e(b.value)}</div><strong class="insight-status">${e(b.status ?? '')}</strong><p>${e(b.detail ?? '')}</p>${b.extra ? `<div class="month-range">${e(b.extra)}</div>` : ''}</section>`).join('')}</div><p class="insight-caution">${e(insights.caution)}</p><wa-details summary="How these insights work"><div class="details-body"><p>${e(insights.method)}</p></div></wa-details>`;
}
