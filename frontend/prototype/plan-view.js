import { total, time, day, money, validSocAssumptions } from './sample.js';

export const number = (value, digits, unit = '', valid = () => true) =>
  Number.isFinite(value) && valid(value) ? `${value.toFixed(digits)}${unit}` : 'Unknown';
const energy = value => number(value, 2, ' kWh', n => n >= 0);
const price = value => number(value, 2, ' c/kWh');
const soc = value => number(value, 1, '%', n => n >= 0 && n <= 100);

// One renderer for the controls, comparison cards and dialog, including unavailable data.
export function renderPlan(windows, assumptions = {}) {
  const summary = total(windows);
  const validAssumptions = validSocAssumptions(assumptions);
  const rows = windows.map((w, i) => `<div class="plan-row ${i === 0 ? 'next-window' : ''}"><span><b>${time(w.start)}–${time(w.end)}</b><small>${day(w.start)}${i === 0 ? ' · NEXT' : ''}</small></span><span><b>${price(w.centsPerKwh)}</b><small>weighted price</small></span><span><b>${energy(w.energy)}</b><small>wall energy</small></span><span><b>${money(w.cost)}</b><small>cost</small></span><span><b>${soc(validAssumptions ? w.projectedSoc : null)}</b><small>projected SOC</small></span></div>`).join('');
  const start = soc(assumptions.startingSoc);
  const capacity = number(assumptions.capacityKwh, 0, ' kWh', n => n > 0);
  const efficiency = number(Number.isFinite(assumptions.efficiency) ? assumptions.efficiency * 100 : null, 0, '%', n => n > 0 && n <= 100);
  return `<div class="plan-heading"><div><h3>Complete proposed plan</h3><p>Estimated, not measured or guaranteed · wall energy · EUR</p></div><wa-badge variant="neutral" pill>${windows.length} windows</wa-badge></div><div class="plan-label"><span>Window</span><span>Weighted price</span><span>Wall energy</span><span>Cost</span><span>SOC after</span></div>${rows || '<p>No proposed windows</p>'}<div class="plan-total"><div><small>WALL ENERGY</small><strong>${energy(summary.energy)}</strong></div><div><small>TOTAL COST</small><strong>${money(summary.cost)}</strong></div><div><small>WEIGHTED AVERAGE</small><strong>${price(summary.centsPerKwh)}</strong></div></div><p class="projection-note">SOC projection: ${start} start, ${capacity} usable capacity, ${efficiency} efficiency. Battery energy = wall energy × efficiency; capped at 100%.</p>`;
}
