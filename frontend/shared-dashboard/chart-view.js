// Stage 20.4: presentation markup around the production price chart (controls, price context, legend). Pure strings, no
// data of its own: every value comes from the validated chart model, and it never plans, converts a currency or writes.
import { escapeText as e } from './text.js';
import { priceText } from './price-format.js';
import { PRICE_BANDS, bandsApply } from './price-bands.js';

// Control hooks (`data-zoom`, `data-reset`) and their accessible names are the ones charts.js binds; navigation by day
// is rendered separately by price-nav-view.js and is untouched.
export function renderChartControls(mode, title) {
  return `<div class="chart-actions" role="group" aria-label="Chart zoom"><wa-button data-zoom="${mode}" size="small" aria-label="Zoom in ${e(title)}">Zoom +</wa-button><wa-button data-reset="${mode}" size="small" aria-label="Reset ${e(title)} overview">Full horizon</wa-button><span>Wheel or pinch zooms · scroll outside the chart</span></div>`;
}

const tile = (label, body, kind) => `<div class="pc-tile" data-tile="${kind}"><span class="pc-label">${e(label)}</span><b>${body}</b></div>`;

/** Four summary tiles. `unknown` prices stay the text Unknown (never 0); a negative price keeps its sign. */
export function renderPriceContext({ now, next, low, high, unit }) {
  const u = e(unit), at = x => `${priceText(x)} ${u}`;
  return `<div class="price-context" role="group" aria-label="Price context">${tile('Now', at(now), 'now')}${tile('Next window starts at', at(next), 'next')}${tile('Horizon low', low || 'Unknown', 'low')}${tile('Horizon high', high || 'Unknown', 'high')}</div>`;
}

const chip = (cls, text) => `<span class="cl-item">${cls}${text}</span>`;
const dot = css => `<span class="cl-dot ${css}" aria-hidden="true">●</span>`;

/**
 * One legend with three groups so "price", "plan overlay" and "evidence" are never one undifferentiated list:
 * absolute display bands (only for c/kWh), the proposal/cap/now overlays (cap only when a valid comparable cap is drawn)
 * and the four evidence lanes plus the hatched unknown/unloaded key.
 */
export function renderChartLegend({ unit, cap }) {
  const u = e(unit);
  const bands = bandsApply(unit)
    ? `<span class="cl-note">Absolute price bands, ${u}:</span>${PRICE_BANDS.map(b => chip(dot(b.css), `${e(b.label)} ${e(b.range)}`)).join('')}<span class="cl-note">exactly 25 is Medium; display only, not a charging limit</span>`
    : `<span class="cl-note">Neutral price color: bands are defined in euro c/kWh and no trusted conversion is available for ${u}, so nothing is classified.</span>`;
  const overlay = [
    chip('<span class="shade" aria-hidden="true"></span>', 'Proposed charging · gradient + pale track'),
    Number.isFinite(cap) ? chip('<span class="cap-key" aria-hidden="true"></span>', `Soft cap ${priceText(cap)} ${u}`) : '',
    chip('<span class="now-key" aria-hidden="true">│</span>', 'Now'),
  ].join('');
  const tracks = `<span class="cl-note">Tracks share the price time axis.</span>${chip('<span class="tk tk-proposal" aria-hidden="true"></span>', 'Proposal: the current calculated plan, not sent')}${chip('<span class="tk tk-sent" aria-hidden="true"></span>', 'Sent: plan versions the charger acknowledged, from the loaded history day (acknowledged is not installed)')}${chip('<span class="tk tk-effective" aria-hidden="true"></span>', 'Effective: the latest fresh readback, remaining period only; a reported limit, not power')}${chip('<span class="tk tk-flow" aria-hidden="true"></span>', 'Measured: observed power flow of the loaded history day')}${chip('<span class="tk tk-unknown" aria-hidden="true"></span>', 'Hatched: unknown or not loaded, never zero')}`;
  return `<div class="chart-legend" role="group" aria-label="Chart legend"><p class="legend track-legend" data-legend="tracks">${tracks}</p><p class="legend" data-legend="prices">${bands}</p><p class="legend" data-legend="overlay">${overlay}</p></div>`;
}
