// The backend's time-reserve block as display data. No planning or cost arithmetic: every number is the
// backend's own, a malformed value becomes null (shown as unknown), and an absent block shows nothing.
const finiteOrNull = v => Number.isFinite(v) && v >= 0 ? v : null;

// Per window: only when the backend states a reserve for it (older backend or no reserve adds nothing).
export const reserveWindow = (detail, priced) => detail && detail.reserve_minutes !== undefined
  ? {reserveMinutes:finiteOrNull(detail.reserve_minutes), reserveKwh:finiteOrNull(detail.reserve_kwh), reserveCost:priced && Number.isFinite(detail.reserve_cost) ? detail.reserve_cost : null} : {};

// `text` = {explain, limits:{two_hour_limit,no_eligible_time,window_limit,unknown}} from the host's translations.
export function reserveModel(raw, currency, text) {
  if (!raw || typeof raw !== 'object' || !Number.isFinite(raw.percent) || raw.percent <= 0) return null;
  const allowance = raw.allowance && raw.allowance.kind === 'upper_allowance' ? raw.allowance : null;
  const limitText = typeof raw.limit === 'string' ? (text.limits[raw.limit] || text.limits.unknown) : null;
  return {percent:raw.percent, minutes:finiteOrNull(raw.minutes), requestedMinutes:finiteOrNull(raw.requested_minutes), limitText, explain:text.explain,
    allowance:allowance ? {energyKwh:finiteOrNull(allowance.energy_kwh), cost:currency && allowance.cost && allowance.cost.currency===currency && Number.isFinite(allowance.cost.value) ? allowance.cost.value : null} : null};
}
