import { escapeText as e } from './text.js';

export function renderEvidence(data, power, count) {
  const d = data || {};
  return `<div class="evidence-status"><strong>${e(d.status)}</strong><span>${e(d.context)}</span></div><div class="evidence-grid"><div><small>Proposal calculated</small><b>${e(d.proposal)}</b></div><div><small>Last sent / ACK</small><b>${e(d.sent)}</b></div><div><small>Effective limits read</small><b>${e(d.readback)}</b></div><div><small>Measured charging</small><b>${e(d.measurement)}</b></div></div><p class="subtext">${e(d.dispatch)}</p><wa-details id="details" summary="View evidence & debug controls"><div class="details-body">${d.readiness ? `<p class="subtext">${e(d.readiness)}</p>` : ''}<div id="morek-debug"><div class="actions"><wa-button size="small" disabled>Send · unavailable</wa-button><wa-button size="small" disabled>Refresh · unavailable</wa-button></div></div></div></wa-details>`;
}
