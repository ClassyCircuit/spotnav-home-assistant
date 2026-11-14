import { total, money, validSocAssumptions } from './plan-data.js';
import { summaryPriceText, priceUnit as unitFor } from './price-format.js';

export const number = (value, digits, unit = '', valid = () => true) =>
  Number.isFinite(value) && valid(value) ? `${value.toFixed(digits)}${unit}` : 'Unknown';
const energy = value => number(value, 2, ' kWh', n => n >= 0);
const soc = value => number(value, 1, '%', n => n >= 0 && n <= 100);
const escapeText = value => String(value ?? 'Unknown').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

// One renderer for the controls, comparison cards and dialog, including unavailable data.
const minutesText = value => {
  if (!Number.isFinite(value) || value < 0) return 'Unknown';
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)} min`;
};
// The reserve as the backend states it: minutes, its separately labelled upper allowance, no arithmetic here.
function renderReserve(reserve, currency) {
  if (!reserve || typeof reserve !== 'object') return '';
  const text = value => escapeText(value);
  const explain = reserve.explain ? ` ${text(reserve.explain)}` : '';
  if (!Number.isFinite(reserve.minutes)) return `<div class="plan-reserve"><p><b>Extra time reserve:</b> unavailable.</p></div>`;
  if (reserve.minutes <= 0) return `<div class="plan-reserve"><p><b>Extra time reserve:</b> none in this plan${Number.isFinite(reserve.percent) ? ` (${text(reserve.percent)}% asked)` : ''}.${reserve.limitText ? ` ${text(reserve.limitText)}` : ''}</p></div>`;
  const asked = Number.isFinite(reserve.requestedMinutes) && reserve.requestedMinutes > reserve.minutes + 1e-6 ? ` of ${minutesText(reserve.requestedMinutes)} asked` : '';
  const allowance = reserve.allowance;
  return `<div class="plan-reserve"><p><b>Extra allowed time:</b> ${minutesText(reserve.minutes)}${asked}, shown inside the windows above.${explain}${reserve.limitText ? ` ${text(reserve.limitText)}` : ''}</p><p><b>Potential extra allowed reserve:</b> up to ${energy(allowance?.energyKwh)} · ${money(allowance?.cost, currency)} — an upper allowance at plan power and prices, separate from the required baseline; not measured or expected use.</p></div>`;
}

// The learned-estimate display as the model states it (lines are final text from the host's translations).
function renderLearning(learning) {
  if (!learning || !Array.isArray(learning.lines)) return '';
  const lines = learning.lines.map(line => `<p>${escapeText(line)}</p>`).join('');
  return `<div class="plan-learning"><p><b>${escapeText(learning.title ?? 'Charging-time estimate')}</b>${learning.stale && learning.staleText ? ` · ${escapeText(learning.staleText)}` : ''}</p>${lines}<p class="projection-note">${escapeText(learning.note ?? 'Estimate, not a guarantee.')}</p></div>`;
}

export function renderPlan(windows, assumptions = {}, stale = false, formatters, totals, reserve, learning) {
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
  const rows = windows.map((w, i) => `<div class="plan-row ${i === 0 ? 'next-window' : ''}"><span><b>${time(w.start)}–${time(w.end)}</b><small>${day(w.start)}${i === 0 ? ' · NEXT' : ''}${w.control === 'minimum-exception' ? ' · ABOVE-CAP MINIMUM' : ''}${Number.isFinite(w.reserveMinutes) && w.reserveMinutes > 0 ? ` · includes ${minutesText(w.reserveMinutes)} reserve` : ''}</small></span><span><b>${displayPrice(w.pricePerKwh,w.centsPerKwh)}</b><small>weighted price</small></span><span><b>${energy(w.energy)}</b><small>wall energy</small></span><span><b>${money(w.cost, currency)}</b><small>cost</small></span><span><b>${soc(validAssumptions ? w.projectedSoc : null)}</b><small>projected SOC</small></span></div>`).join('');
  const hasReserve = !!reserve && Number.isFinite(reserve.minutes) && reserve.minutes > 0;
  const start = soc(assumptions.startingSoc);
  const capacity = number(assumptions.capacityKwh, 0, ' kWh', n => n > 0);
  const efficiency = number(Number.isFinite(assumptions.efficiency) ? assumptions.efficiency * 100 : null, 0, '%', n => n > 0 && n <= 100);
  const projectionBasis=assumptions.projectionSupported ? `${start} start, ${number(assumptions.projectionKwhPerPercent, 3, ' wall kWh per SOC point', n=>n>0)}` : `${start} start, ${capacity} usable capacity, ${efficiency} efficiency`;
  return `<div class="plan-heading"><div><h3>Complete proposed plan${stale ? ` · ${escapeText(formatters.staleLabel ?? 'stale')}` : ''}</h3><p>Estimated, not measured or guaranteed · wall energy · ${escapeText(currency === undefined ? 'EUR' : currency || 'currency unknown')}${formatters.costBasis ? ` · ${escapeText(formatters.costBasis)}` : ''}</p></div><wa-badge variant="neutral" pill>${windows.length} windows</wa-badge></div><div class="plan-label"><span>Window</span><span>Weighted price</span><span>Wall energy</span><span>Cost</span><span>SOC after</span></div>${rows || '<p>No proposed windows</p>'}<div class="plan-total"><div><small>${hasReserve ? 'REQUIRED BASELINE ENERGY' : 'WALL ENERGY'}</small><strong>${energy(summary.energy)}</strong></div><div><small>${hasReserve ? 'REQUIRED BASELINE COST' : 'TOTAL COST'}</small><strong>${money(summary.cost, currency)}</strong></div><div><small>WEIGHTED AVERAGE</small><strong>${displayPrice(summary.pricePerKwh,summary.centsPerKwh)}</strong></div></div>${renderReserve(reserve, currency)}${renderLearning(learning)}<p class="projection-note">SOC projection: ${projectionBasis}. ${escapeText(assumptions.projectionNote || 'Battery energy = wall energy × efficiency; capped at 100%.')}</p>${formatters.detailsNote ? `<p class="projection-note">${escapeText(formatters.detailsNote)}</p>` : ''}`;
}
