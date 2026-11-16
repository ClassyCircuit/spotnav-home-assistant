// Spot-only historical cost (Stage 8.2b): one validator and one formatter for the backend's `spot_cost` block, shared by
// the sidebar panel and the local preview, for a whole session, a session's share of one day, a day and a month.
// Every amount and kWh figure is the backend's (`sessions/costing.py`); nothing is summed, converted or recomputed here.
// The block is raw published spot price only (no fees, taxes or margin) in the MAJOR currency unit (EUR, not cents).
// Unknown (`amount: null`) is never shown as zero; a partial amount is never shown as a total. The older fiscal fields
// (`cost`, `reference_cost`, `savings`, `this_month`, `month_summary`, ...) are never read here.

export const SPOT_PRICE_BASIS = 'raw_published_spot_no_fees_no_taxes';
const BASIS = { recorded_price_slices: 'recorded price slices', retained_price_intervals: 'retained price intervals', mixed: 'recorded slices and retained prices', unknown: 'unknown' };
const STATES = ['complete', 'partial', 'none', 'no_sessions_recorded'];
const REASON = { no_price_slice: 'no price slice stored', untrusted_rate: 'exchange rate not trusted', missing_currency: 'no currency stored', conflicting_slice: 'conflicting price slices',
  unpriced_energy: 'energy without a price', energy_without_placement_overlaps_period: 'energy with no recorded time overlaps this period', unplaced_late_energy_not_priced: 'late energy with no known time is not priced',
  currency_exclusions: 'energy in another currency is left out', open_session: 'a charge is still running', rows_truncated: 'the list of sessions is cut',
  conflicting_slices: 'conflicting price slices', slice_energy_exceeds_session_energy: 'price slices exceed the session energy', invalid_slices: 'unreadable price slices', duplicate_slices: 'duplicate price slices' };
const words = text => String(text ?? 'unknown').replace(/_/g, ' ');
const num = v => typeof v === 'number' && Number.isFinite(v);
const nonneg = v => num(v) && v >= 0;
export const kwhText = v => nonneg(v) ? `${v.toFixed(v < 10 ? 2 : 1)} kWh` : 'unknown';
const pct = v => `${Math.round(v * 100)}%`;

/** An amount in the MAJOR currency unit (never cents); a tiny non-zero amount keeps extra digits so it never reads as 0. */
export function formatMoney(amount, currency, majorUnit) {
  if (!num(amount)) return 'unknown';
  const digits = amount !== 0 && Math.abs(amount) < 0.005 ? 4 : 2;
  if (typeof currency === 'string' && /^[A-Z]{3}$/.test(currency)) {
    try { return new Intl.NumberFormat('en-GB', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(amount); } catch { /* unknown code: plain text below */ }
  }
  return `${amount.toFixed(digits)} ${typeof majorUnit === 'string' && majorUnit ? majorUnit : currency || '(currency unknown)'}`;
}

/** Validate one backend block; `null` when it is not what the contract promises (the caller shows "not understood", never a guess). */
export function parseSpotCost(b) {
  if (!b || typeof b !== 'object' || b.price_basis !== SPOT_PRICE_BASIS || b.unit !== 'major') return null;
  const c = b.coverage;
  if (!c || typeof c !== 'object' || !STATES.includes(c.state) || !Array.isArray(c.reasons) || !(b.basis in BASIS)) return null;
  if (!(b.amount === null || num(b.amount)) || !(b.currency === null || typeof b.currency === 'string')) return null;
  if (b.amount !== null && !b.currency) return null;
  if (!['priced_kwh', 'unpriced_kwh', 'unplaced_kwh', 'unallocated_kwh'].every(k => nonneg(b[k]))) return null;
  if (b.amount !== null && !(b.priced_kwh > 0)) return null;
  const ex = b.currency_exclusions;
  if (!(ex === null || ex === undefined || (typeof ex === 'object' && nonneg(ex.kwh)))) return null;
  return b;
}

const sourceText = b => {
  const named = typeof b.price_source === 'string' && b.price_source ? [b.price_source] : Array.isArray(b.price_sources) ? b.price_sources.filter(s => typeof s === 'string' && s) : [];
  if (named.length) return `Price source: ${named.join(', ')}.`;
  return b.price_source_state === 'not_recorded' ? 'Spot price source not recorded for these slices.' : 'Spot price source unknown.';
};

/**
 * One block as display text. `scope` is only wording (`day`, `month`, `session`): the figures never change with it.
 * Returns `{state, amount, headline, brief, lines}`; `state` is `invalid`, `no_sessions_recorded`, `none` (sessions but nothing priced),
 * `partial` or `complete`.
 */
export function describeSpotCost(raw, scope = 'day') {
  const b = parseSpotCost(raw);
  if (!b) return { state: 'invalid', amount: null, headline: 'Spot cost not shown: the answer could not be understood.', brief: 'not shown (could not be understood)', lines: [] };
  const state = b.coverage.state, money = formatMoney(b.amount, b.currency, b.major_unit);
  const total = b.priced_kwh + b.unpriced_kwh;
  const lines = [];
  let headline, brief;
  if (state === 'no_sessions_recorded') {
    headline = `No session recorded for this ${scope}: no cost to show (that is not zero cost and not proof that nothing was charged).`; brief = 'no session recorded';
  } else if (b.amount === null) {
    headline = `Spot cost unknown: no energy could be priced${b.unpriced_kwh > 0 ? ` (${kwhText(b.unpriced_kwh)} unpriced)` : ''}.`; brief = 'unknown (no priced energy)';
  } else if (state === 'partial') {
    headline = `Partial spot cost ${money} for ${kwhText(b.priced_kwh)} priced; ${kwhText(b.unpriced_kwh)} unpriced. This is not a complete total.`;
    brief = `${money} partial (${kwhText(b.priced_kwh)} priced)`;
  } else {
    headline = `Spot cost ${money}${b.allocation ? ' (estimate)' : ''} for ${kwhText(b.priced_kwh)} priced.`; brief = `${money}${b.allocation ? ' (estimate)' : ''}`;
  }
  if (b.amount !== null && b.amount < 0) lines.push('Negative: prices were below zero, so this is a net credit, not an error.');
  if (state !== 'no_sessions_recorded') {
    lines.push(`Basis: ${BASIS[b.basis]}. Spot price only: raw published price, no fees, taxes or margin. ${sourceText(b)}`);
    if (b.allocation) lines.push('Allocation is an estimate: each price interval’s energy is split by the elapsed time that falls inside the period.');
    if (b.coverage.priced_fraction !== null && b.coverage.priced_fraction !== undefined && num(b.coverage.priced_fraction)) lines.push(`Coverage: ${pct(b.coverage.priced_fraction)} of ${kwhText(total)} placed energy priced across ${b.sessions ?? '?'} session(s).`);
    const reasons = Object.entries(b.coverage.unpriced_reasons || {}).filter(([, v]) => nonneg(v) && v > 0).map(([k, v]) => `${REASON[k] || words(k)} ${kwhText(v)}`);
    if (reasons.length) lines.push(`Unpriced because: ${reasons.join('; ')}.`);
    const flags = (b.coverage.reasons || []).filter(r => REASON[r] && !/^(unpriced_energy)$/.test(r)).map(r => REASON[r]);
    if (flags.length) lines.push(`Notes: ${flags.join('; ')}.`);
    if (b.unplaced_kwh > 0) lines.push(`Late energy with no known time ${kwhText(b.unplaced_kwh)}: not priced and not in this cost.`);
    if (nonneg(b.unplaced_ambiguous_kwh) && b.unplaced_ambiguous_kwh > 0) lines.push(`Late energy ${kwhText(b.unplaced_ambiguous_kwh)} of sessions crossing the edge of this ${scope}: not summed, not priced.`);
    if (nonneg(b.unplaced_unknown_sessions) && b.unplaced_unknown_sessions > 0) lines.push(`${b.unplaced_unknown_sessions} session(s) may hold late energy of unknown size.`);
    if (b.unallocated_kwh > 0) lines.push(`${kwhText(b.unallocated_kwh)} of a session that crosses the edge has no price interval and cannot be assigned to this ${scope}: left out, not zero.`);
    const x = b.currency_exclusions;
    if (x && x.kwh > 0) lines.push(`Left out: ${kwhText(x.kwh)} in ${Object.keys(x.currencies || {}).join(', ') || 'no stored currency'}${nonneg(x.missing_currency_kwh) && x.missing_currency_kwh > 0 ? ` (${kwhText(x.missing_currency_kwh)} with no currency)` : ''}; currencies are never added or converted.`);
  }
  return { state: state === 'no_sessions_recorded' ? state : b.amount === null ? 'none' : state, amount: b.amount, headline, brief, lines };
}

/** One session's share of the shown day and its whole cost, side by side; the whole session is never the day's cost. */
export function sessionCostLines(s, crossesDays) {
  const inDay = s.spot_cost_in_window === undefined ? undefined : describeSpotCost(s.spot_cost_in_window, 'day');
  const whole = s.spot_cost === undefined ? undefined : describeSpotCost(s.spot_cost, 'session');
  if (inDay === undefined && whole === undefined) return ['Spot cost not reported by this integration (not zero).'];
  const out = [];
  if (inDay) out.push(`Spot cost in this day: ${inDay.brief}`);
  const same = s.spot_cost && s.spot_cost_in_window && s.spot_cost.amount === s.spot_cost_in_window.amount && s.spot_cost.priced_kwh === s.spot_cost_in_window.priced_kwh && s.spot_cost.unpriced_kwh === s.spot_cost_in_window.unpriced_kwh;
  if (whole && (crossesDays || !inDay || !same)) out.push(`Whole session${crossesDays ? ' (crosses midnight; not this day’s cost)' : ''}: ${whole.brief}`);
  return out;
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
export const monthKey = day => typeof day === 'string' && DAY_RE.test(day) ? day.slice(0, 7) : null;
export const monthName = month => { const m = MONTH_RE.exec(month || ''); return m ? new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(Date.UTC(+month.slice(0, 4), +month.slice(5, 7) - 1, 1)) : 'Unknown month'; };

/**
 * The month part of one `spotnav/get_sessions` answer (delivery fields, Stage 8.2a): `legacy` for an older backend (no delivery keys),
 * otherwise the validated month block and its day rows. `expected` is the asked month or null (the backend's current month).
 * Returns `null` for a malformed or foreign answer, never a partial model.
 */
export function parseDeliveryMonth(answer, charger, expected = null) {
  if (!answer || typeof answer !== 'object' || answer.api_version !== 1 || answer.charger_id !== charger) return null;
  const available = Array.isArray(answer.available_months) ? answer.available_months.filter(m => typeof m === 'string' && MONTH_RE.test(m)) : [];
  if (!('delivery_month_summary' in answer) && !('delivery_month_days' in answer)) return { legacy: true, month: MONTH_RE.test(answer.month || '') ? answer.month : expected, available };
  const month = answer.month, s = answer.delivery_month_summary, days = answer.delivery_month_days;
  if (typeof month !== 'string' || !MONTH_RE.test(month) || (expected && month !== expected) || !s || typeof s !== 'object' || s.kind !== 'delivery_month' || s.period !== month || !Array.isArray(days) || days.length > 31) return null;
  if (!days.every(d => d && d.kind === 'delivery_day' && typeof d.period === 'string' && DAY_RE.test(d.period) && d.period.startsWith(`${month}-`))) return null;
  return { legacy: false, month, available, month_block: s.spot_cost, days: days.map(d => ({ period: d.period, block: d.spot_cost })), open: answer.open !== null && answer.open !== undefined && typeof answer.open === 'object' };
}

/** The display model of one parsed month; every figure comes from the backend's blocks. */
export function monthCostModel(parsed, { isCurrent }) {
  if (!parsed) return { state: 'invalid', message: 'The month’s spot cost could not be understood and was not shown.' };
  if (parsed.legacy) return { state: 'legacy', message: 'This integration does not report spot-only cost by month, so none is shown. Its older cost fields include fees and taxes and are not shown here.' };
  const total = describeSpotCost(parsed.month_block, 'month');
  const lines = [...total.lines];
  const b = parseSpotCost(parsed.month_block);
  if (b && (b.unpriced_kwh > 0 || b.unallocated_kwh > 0 || b.unplaced_kwh > 0)) lines.push('The month can hold energy with no recorded time; it counts for the month but for no single day, so the days below need not add up to the month’s unpriced energy.');
  if (parsed.open && isCurrent) lines.push('A charge is running now; this summary covers closed sessions only and leaves it out.');
  const rows = parsed.days.map(d => ({ day: d.period, ...describeSpotCost(d.block, 'day') }));
  const withSessions = rows.filter(r => r.state !== 'no_sessions_recorded');
  return { state: 'ready', month: parsed.month, total: { ...total, lines }, days: withSessions.map(r => ({ day: r.day, text: `${r.day.slice(8)}: ${r.brief}`, state: r.state })),
    emptyDays: rows.length - withSessions.length };
}
