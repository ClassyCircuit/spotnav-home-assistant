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
    const x = exclusionLine(b.currency_exclusions);
    if (x) lines.push(x);
  }
  return { state: state === 'no_sessions_recorded' ? state : b.amount === null ? 'none' : state, amount: b.amount, headline, brief, lines };
}

function exclusionLine(x) {
  if (!x || !(x.kwh > 0)) return '';
  return `Left out: ${kwhText(x.kwh)} in ${Object.keys(x.currencies || {}).join(', ') || 'no stored currency'}${nonneg(x.missing_currency_kwh) && x.missing_currency_kwh > 0 ? ` (${kwhText(x.missing_currency_kwh)} with no currency)` : ''}; currencies are never added or converted.`;
}

// ---- Historical day-average savings (Stage 8.3b): the backend's `spot_cost.savings` block (8.3a), shown, never recomputed. ----
export const SAVINGS_BASIS = 'day_average_price';
const TOLERANCE_KWH = 0.005;
const SAVINGS_REASON = { reference_day_not_held: 'full-day prices not held', reference_day_partial: 'full-day prices incomplete', reference_day_invalid_prices: 'full-day prices unreadable',
  reference_day_overlap: 'full-day prices overlap', reference_day_conflicting_duplicate: 'full-day prices conflict', reference_area_unknown: 'price area unknown', reference_currency_unknown: 'reference currency unknown',
  reference_currency_mismatch: 'reference currency differs', reference_price_rate_missing: 'exchange rate missing', reference_prices_unavailable: 'prices unavailable', price_source_mismatch: 'price source differs' };

/** One backend `savings` block, validated against the spot block it sits in; `null` when it is not what the contract promises. */
export function parseSavings(s, spot) {
  if (!s || typeof s !== 'object' || s.basis !== SAVINGS_BASIS || s.estimate !== true || s.unit !== 'major' || !STATES.includes(s.state)) return null;
  const orNum = v => v === null || num(v);
  if (!['amount', 'percentage', 'actual_cost', 'reference_cost'].every(k => orNum(s[k])) || !(s.currency === null || typeof s.currency === 'string')) return null;
  if (!['comparable_kwh', 'excluded_kwh', 'unpriced_kwh'].every(k => nonneg(s[k]))) return null;
  if (s.excluded_reasons !== undefined && (typeof s.excluded_reasons !== 'object' || s.excluded_reasons === null)) return null;
  if (s.excluded_days !== undefined && !(Array.isArray(s.excluded_days) && s.excluded_days.every(d => typeof d === 'string'))) return null;
  if (s.excluded_days_count !== undefined && !nonneg(s.excluded_days_count)) return null;
  if (s.reference_sources !== undefined && !(Array.isArray(s.reference_sources) && s.reference_sources.every(source => typeof source === 'string'))) return null;
  if (s.amount !== null) {
    // The compared energy is a subset of what was priced, in the same currency; anything else is not shown as a number.
    if (!s.currency || s.actual_cost === null || s.reference_cost === null || !(s.comparable_kwh > 0) || !['complete', 'partial'].includes(s.state)) return null;
    if (spot.currency && s.currency !== spot.currency) return null;
    if (s.comparable_kwh > spot.priced_kwh + TOLERANCE_KWH) return null;
  } else if (['complete', 'partial'].includes(s.state)) return null;
  return s;
}

const pctText = p => `${Number(p.toFixed(1))}%`;

/**
 * The savings of one `spot_cost` block as display text (`scope` is wording only). Returns `{state, amount, headline, brief, lines}`;
 * `state`: `invalid`, `legacy` (no savings key: an older backend), `no_sessions_recorded`, `none` (nothing comparable), `partial`, `complete`.
 * Amount and percentage are the backend's. The savings `actual_cost` covers only the compared subset and is never mixed with `spot_cost.amount`.
 */
export function describeSavings(rawSpot, scope = 'day') {
  const spot = parseSpotCost(rawSpot);
  const invalid = { state: 'invalid', amount: null, headline: 'Estimated savings not shown: the answer could not be understood.', brief: 'not shown (could not be understood)', lines: [] };
  if (!spot) return invalid;
  if (!('savings' in spot)) return { state: 'legacy', amount: null, headline: 'Estimated savings are not reported by this integration (not zero).', brief: 'not reported', lines: [] };
  const s = parseSavings(spot.savings, spot);
  if (!s) return invalid;
  if (s.state === 'no_sessions_recorded') return { state: s.state, amount: null, headline: `No session recorded for this ${scope}: no savings to show (that is not zero savings).`, brief: 'no session recorded', lines: [] };
  const lines = ['Historical estimate from recorded prices, not a supplier-bill saving and not the plan’s forecast.',
    'Baseline: the same compared energy priced at that delivery day’s full-day average spot price (duration-weighted, raw price, no fees, taxes or margin).'];
  let headline, brief;
  if (s.amount === null) {
    headline = `Estimated savings unknown: no priced energy had a full-day reference price${s.unpriced_kwh > 0 ? ` (${kwhText(s.unpriced_kwh)} unpriced)` : ''}.`; brief = 'unknown (no full-day reference)';
  } else {
    const money = formatMoney(s.amount, s.currency, spot.major_unit);
    const p = s.percentage !== null && s.reference_cost > 0 ? ` (${pctText(s.percentage)} of the reference)` : '';
    const sign = s.amount < 0 ? ': costs more than the reference' : s.amount === 0 ? ': the same as the reference' : '';
    const head = s.state === 'partial' ? `Partial estimated savings ${money}${p}${sign} for ${kwhText(s.comparable_kwh)} compared. This is not a complete comparison.` : `Estimated savings ${money}${p}${sign} for ${kwhText(s.comparable_kwh)} compared.`;
    headline = head; brief = `${s.state === 'partial' ? 'partial ' : ''}${money}${p}${s.amount < 0 ? ' (costs more than reference)' : ''}`;
    lines.push(`Compared energy ${kwhText(s.comparable_kwh)}: reference cost ${formatMoney(s.reference_cost, s.currency, spot.major_unit)}; actual spot cost of that same energy ${formatMoney(s.actual_cost, s.currency, spot.major_unit)}.`);
    if (spot.priced_kwh - s.comparable_kwh > TOLERANCE_KWH) lines.push(`The spot cost shown beside this covers ${kwhText(spot.priced_kwh)} priced; savings compare only ${kwhText(s.comparable_kwh)} of it. The two costs cover different energy: never subtract one from the other.`);
    if (s.amount < 0) lines.push('Negative savings are valid: this charging cost more than the same energy at the day-average price.');
    if (s.percentage === null || !(s.reference_cost > 0)) lines.push(`Percentage not meaningful: the reference cost is ${s.reference_cost < 0 ? 'negative' : 'zero'}, so none is shown (this is not 0%).`);
  }
  if (nonneg(s.comparable_fraction ?? NaN)) lines.push(`Comparison covers ${pct(s.comparable_fraction)} of the energy placed for this ${scope}.`);
  if (s.excluded_kwh > TOLERANCE_KWH) {
    const reasons = Object.entries(s.excluded_reasons || {}).filter(([, v]) => nonneg(v) && v > 0).map(([k, v]) => `${SAVINGS_REASON[k] || words(k)} ${kwhText(v)}`);
    const shown = s.excluded_days || [], count = nonneg(s.excluded_days_count) ? s.excluded_days_count : shown.length;
    lines.push(`Left out of the comparison: ${kwhText(s.excluded_kwh)} priced energy with no full-day reference${reasons.length ? ` (${reasons.join('; ')})` : ''}${count ? `; days: ${shown.slice(0, 5).join(', ')}${count > Math.min(5, shown.length) ? ` and ${count - Math.min(5, shown.length)} more` : ''}` : ''}.`);
  }
  if (s.unpriced_kwh > TOLERANCE_KWH) lines.push(`${kwhText(s.unpriced_kwh)} unpriced energy is not compared.`);
  if (nonneg(s.reference_days) && s.reference_days > 0) {
    const named = (s.reference_sources || []).filter(n => typeof n === 'string' && n && n !== 'unknown');
    lines.push(`Reference from ${s.reference_days} delivery day(s). ${named.length && s.reference_source_state === 'held_provider_labels' ? `Reference price source: ${named.join(', ')}.` : 'Reference price source unknown.'}`);
  }
  const x = exclusionLine(s.currency_exclusions);
  if (x) lines.push(x);
  return { state: s.amount === null ? 'none' : s.state, amount: s.amount, headline, brief, lines };
}

/** One session's share of the shown day and its whole cost, side by side; the whole session is never the day's cost. */
export function sessionCostLines(s, crossesDays) {
  const inDay = s.spot_cost_in_window === undefined ? undefined : describeSpotCost(s.spot_cost_in_window, 'day');
  const whole = s.spot_cost === undefined ? undefined : describeSpotCost(s.spot_cost, 'session');
  if (inDay === undefined && whole === undefined) return ['Spot cost not reported by this integration (not zero).'];
  const out = [];
  if (inDay) out.push(`Spot cost in this day: ${inDay.brief}`);
  const same = s.spot_cost && s.spot_cost_in_window && s.spot_cost.amount === s.spot_cost_in_window.amount && s.spot_cost.priced_kwh === s.spot_cost_in_window.priced_kwh && s.spot_cost.unpriced_kwh === s.spot_cost_in_window.unpriced_kwh;
  const showWhole = whole && (crossesDays || !inDay || !same);
  if (showWhole) out.push(`Whole session${crossesDays ? ' (crosses midnight; not this day’s cost)' : ''}: ${whole.brief}`);
  // Estimated savings (8.3b) only where the backend sent them; each line names the energy it covers (the day's share or the whole session).
  const sav = block => block && typeof block === 'object' && 'savings' in block ? describeSavings(block, 'day') : null;
  const dayS = sav(s.spot_cost_in_window), wholeS = sav(s.spot_cost);
  if (dayS) out.push(`Estimated savings in this day: ${dayS.brief}`);
  if (wholeS && showWhole) out.push(`Whole session estimated savings${crossesDays ? ' (not this day’s)' : ''}: ${wholeS.brief}`);
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
  const savings = describeSavings(parsed.month_block, 'month');
  const lines = [...total.lines];
  const b = parseSpotCost(parsed.month_block);
  if (b && (b.unpriced_kwh > 0 || b.unallocated_kwh > 0 || b.unplaced_kwh > 0)) lines.push('The month can hold energy with no recorded time; it counts for the month but for no single day, so the days below need not add up to the month’s unpriced energy.');
  if (parsed.open && isCurrent) lines.push('A charge is running now; this summary covers closed sessions only and leaves it out.');
  const rows = parsed.days.map(d => ({ day: d.period, ...describeSpotCost(d.block, 'day'), savingsBrief: describeSavings(d.block, 'day') }));
  const withSessions = rows.filter(r => r.state !== 'no_sessions_recorded');
  return { state: 'ready', month: parsed.month, total: { ...total, lines }, savings, days: withSessions.map(r => ({ day: r.day, text: `${r.day.slice(8)}: ${r.brief}`, detail: `Estimated savings: ${r.savingsBrief.brief}`, state: r.state })),
    emptyDays: rows.length - withSessions.length };
}
