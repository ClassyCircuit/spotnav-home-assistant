import { total, money, validSocAssumptions } from './plan-data.js';
import { summaryPriceText, priceUnit as unitFor } from './price-format.js';

export const number = (value, digits, unit = '', valid = () => true) =>
  Number.isFinite(value) && valid(value) ? `${value.toFixed(digits)}${unit}` : 'Unknown';
const energy = value => number(value, 2, ' kWh', n => n >= 0);
const soc = value => number(value, 1, '%', n => n >= 0 && n <= 100);
const escapeText = value => String(value ?? 'Unknown').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

// One renderer for the controls, comparison cards and dialog, including unavailable data.
export function renderPlan(windows, assumptions = {}, stale = false, formatters, totals) {
  if (!formatters || typeof formatters.time !== 'function' || typeof formatters.day !== 'function') throw new TypeError('Plan time and day formatters are required');
  const time = value => Number.isFinite(value) ? escapeText(formatters.time(value)) : 'Unknown';
  const day = value => Number.isFinite(value) ? escapeText(formatters.day(value)) : 'Unknown';
  const summary = totals === undefined ? total(windows) : (totals || {});
  const currency = formatters.currency;
  const priceCurrency = currency === undefined ? 'EUR' : currency;
  const displayPrice = (value, legacy) => {
    const actual = value === undefined && priceCurrency === 'EUR' ? legacy : value;
    return Number.isFinite(actual) && typeof priceCurrency==='string' && /^[A-Z]{3}$/.test(priceCurrency) ? `${summaryPriceText(actual)} ${unitFor(priceCurrency)}` : 'Unknown';
  };
  const validAssumptions = assumptions.projectionSupported === true || validSocAssumptions(assumptions);
  const rows = windows.map((w, i) => `<div class="plan-row ${i === 0 ? 'next-window' : ''}"><span><b>${time(w.start)}–${time(w.end)}</b><small>${day(w.start)}${i === 0 ? ' · NEXT' : ''}${w.control === 'minimum-exception' ? ' · ABOVE-CAP MINIMUM' : ''}</small></span><span><b>${displayPrice(w.pricePerKwh,w.centsPerKwh)}</b><small>weighted price</small></span><span><b>${energy(w.energy)}</b><small>wall energy</small></span><span><b>${money(w.cost, currency)}</b><small>cost</small></span><span><b>${soc(validAssumptions ? w.projectedSoc : null)}</b><small>projected SOC</small></span></div>`).join('');
  const start = soc(assumptions.startingSoc);
  const capacity = number(assumptions.capacityKwh, 0, ' kWh', n => n > 0);
  const efficiency = number(Number.isFinite(assumptions.efficiency) ? assumptions.efficiency * 100 : null, 0, '%', n => n > 0 && n <= 100);
  const projectionBasis=assumptions.projectionSupported ? `${start} start, ${number(assumptions.projectionKwhPerPercent, 3, ' wall kWh per SOC point', n=>n>0)}` : `${start} start, ${capacity} usable capacity, ${efficiency} efficiency`;
  return `<div class="plan-heading"><div><h3>Complete proposed plan${stale ? ` · ${escapeText(formatters.staleLabel ?? 'stale')}` : ''}</h3><p>Estimated, not measured or guaranteed · wall energy · ${escapeText(currency === undefined ? 'EUR' : currency || 'currency unknown')}${formatters.costBasis ? ` · ${escapeText(formatters.costBasis)}` : ''}</p></div><wa-badge variant="neutral" pill>${windows.length} windows</wa-badge></div><div class="plan-label"><span>Window</span><span>Weighted price</span><span>Wall energy</span><span>Cost</span><span>SOC after</span></div>${rows || '<p>No proposed windows</p>'}<div class="plan-total"><div><small>WALL ENERGY</small><strong>${energy(summary.energy)}</strong></div><div><small>TOTAL COST</small><strong>${money(summary.cost, currency)}</strong></div><div><small>WEIGHTED AVERAGE</small><strong>${displayPrice(summary.pricePerKwh,summary.centsPerKwh)}</strong></div></div><p class="projection-note">SOC projection: ${projectionBasis}. ${escapeText(assumptions.projectionNote || 'Battery energy = wall energy × efficiency; capped at 100%.')}</p>${formatters.detailsNote ? `<p class="projection-note">${escapeText(formatters.detailsNote)}</p>` : ''}`;
}
