// Live price insights and monthly statistics (Stage 7.5): a read-only request state machine, answer validators and the
// display model of the shared "Price insights" card, used by the live sidebar and the local preview. It only asks
// `spotnav/get_price_insights` (held prices; never a provider, never a write, never a plan). Every number is the
// backend's: the one thing done here is the single EUR major-unit -> cent display conversion (`displayPrice`) and the
// fixed absolute band label (`priceBand`). Absolute band and relative percentile are separate statements, and neither
// changes a chart colour. A request is bound to charger, generation/permission epoch, area, currency and (for the
// answer) the duration/month asked; anything else is dropped. A failure stays until `retry()`: no timed retry.

import { displayPrice, priceUnit, summaryPriceText } from './price-format.js';
import { priceBand, bandsApply } from './price-bands.js';

export const LIVE_REFRESH_MS = 300000;     // a live read is repeated at most this often
export const INTERVAL_END_GAP_MS = 60000;  // ...or once the read interval ended, but never within this of the last read
export const DEFAULT_DURATION = 60;
export const DURATIONS = Array.from({ length: 48 }, (_, i) => (i + 1) * 15);
export const HISTORY_KEEP_DAYS = 400;      // the backend's retention bound: a month starting earlier is refused
export const MAX_MONTHS = 14;              // the month picker never lists more
const MIN_DAYS = 7;
const CACHE_MONTHS = 3;                    // selected + compared + current, nothing else is kept
const DAY_MS = 86400000;
const MONTH_RE = /^(\d{4})-(0[1-9]|1[0-2])$/;
const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

const num = v => typeof v === 'number' && Number.isFinite(v);
const count = v => Number.isInteger(v) && v >= 0;
const nullableCount = v => v === null || v === undefined || count(v);
const instant = v => typeof v === 'string' ? Date.parse(v) : NaN;
const dayMs = day => { const m = DAY_RE.exec(day || ''); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : NaN; };
const zoneOk = zone => { try { new Intl.DateTimeFormat('en', { timeZone: zone }); return typeof zone === 'string' && zone !== ''; } catch { return false; } };
const words = code => String(code ?? 'unknown').replace(/_/g, ' ');

// ---- vocabulary -----------------------------------------------------------------------------------------------------
const REASON = {
  baseline_too_short: 'fewer than 7 complete recent days are held', baseline_unknown: 'the recent-days baseline is not available',
  too_few_complete_days: 'fewer than 7 complete days are held for this month', no_completed_days: 'no day of this month has completed yet',
  no_current_interval: 'no current price interval is published', no_future_prices: 'no later prices are published yet',
  no_contiguous_window: 'no unbroken published stretch of that length remains', not_held: 'the day is not held', partial: 'the day is incomplete',
  invalid_prices: 'prices are invalid', conflicting_duplicate: 'conflicting duplicate rows', overlap: 'overlapping rows', no_price_rate: 'no usable exchange rate',
  day_stale: 'the held day is stale', day_invalid: 'the held day is invalid', inconsistent: 'the answer contradicts itself',
};
export const reasonText = code => REASON[code] || words(code);
const EXCLUDED = { not_held: 'not held', partial: 'incomplete', invalid_prices: 'invalid prices', conflicting_duplicate: 'conflicting rows', overlap: 'overlapping rows', no_price_rate: 'no exchange rate' };

const monthLabel = month => { const m = MONTH_RE.exec(month || ''); return m ? new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', month: 'long', year: 'numeric' }).format(Date.UTC(+m[1], +m[2] - 1, 1)) : 'Unknown month'; };
const monthOf = day => typeof day === 'string' && DAY_RE.test(day) ? day.slice(0, 7) : null;
const prevMonth = month => { const m = MONTH_RE.exec(month); return m ? new Date(Date.UTC(+m[1], +m[2] - 2, 1)).toISOString().slice(0, 7) : null; };
const durationText = minutes => { const h = Math.floor(minutes / 60), m = minutes % 60; return h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`; };

/** The months a user may pick, newest first: the current month back to the backend's 400-day first-day bound. */
export function monthOptions(today) {
  const t = dayMs(today);
  if (!Number.isFinite(t)) return [];
  const out = [];
  for (let month = monthOf(today); month && out.length < MAX_MONTHS; month = prevMonth(month)) {
    if (dayMs(`${month}-01`) < t - HISTORY_KEEP_DAYS * DAY_MS) break;
    out.push({ value: month, label: out.length === 0 ? `${monthLabel(month)} (so far)` : monthLabel(month) });
  }
  return out;
}

// ---- answer validation: what the backend promises; anything else is `invalid`, never a partial false model ------------
const basisKey = b => b && typeof b === 'object' && b.kind === 'published_spot' && b.unit === 'major_per_kwh' && typeof b.currency === 'string' && b.fees === 'none' ? `${b.kind}|${b.unit}|${b.currency}|${b.fees}` : null;
const topOk = (a, asked, mode) => !!a && typeof a === 'object' && a.api_version === 1 && a.mode === mode && a.charger_id === asked.charger && a.area_id === asked.area
  && a.currency === asked.currency && basisKey(a.basis) === `published_spot|major_per_kwh|${asked.currency}|none` && zoneOk(a.zone) && Number.isFinite(instant(a.now));

function excluded(x) {
  if (!x || typeof x !== 'object' || !count(x.count)) return null;
  const reasons = x.reasons && typeof x.reasons === 'object' ? Object.entries(x.reasons).filter(([, n]) => count(n) && n > 0) : [];
  return { count: x.count, reasons };
}
const excludedText = x => !x || x.count === 0 ? '' : `${x.count} excluded${x.reasons.length ? ` (${x.reasons.map(([code, n]) => `${n} ${EXCLUDED[code] || words(code)}`).join(', ')})` : ''}`;
function providers(list, key) {
  const out = [];
  for (const row of Array.isArray(list) ? list : []) for (const label of key === 'providers' ? (Array.isArray(row?.providers) ? row.providers : []) : [row?.provider]) if (typeof label === 'string' && label && !out.includes(label)) out.push(label);
  return out;
}

function parseBaseline(b) {
  if (!b || typeof b !== 'object' || !['known', 'unknown'].includes(b.status)) return null;
  const min = count(b.minimum_days) && b.minimum_days > 0 ? b.minimum_days : MIN_DAYS;
  const ex = excluded(b.days_excluded);
  if (![b.days_expected, b.days_held, b.days_used].every(count) || !ex || b.days_used > b.days_held || b.days_held > b.days_expected) return { known: false, reason: 'inconsistent', min, expected: null, held: null, used: null, excluded: null };
  const known = b.status === 'known' && b.days_used >= min;
  return { known, reason: known ? null : b.status === 'known' ? 'inconsistent' : (b.unknown_reason || 'baseline_unknown'), min, expected: b.days_expected, held: b.days_held, used: b.days_used, excluded: ex };
}
function parseComparison(c, baseline) {
  if (!c || typeof c !== 'object') return { known: false, reason: 'baseline_unknown' };
  if (c.status !== 'known') return { known: false, reason: c.unknown_reason || 'baseline_unknown' };
  if (!baseline?.known) return { known: false, reason: baseline?.reason || 'baseline_unknown' };
  return num(c.percentile) && c.percentile >= 0 && c.percentile <= 100 ? { known: true, percentile: c.percentile } : { known: false, reason: 'inconsistent' };
}
function parseCurrent(cur, baseline) {
  if (!cur || typeof cur !== 'object') return { known: false, reason: 'not_reported' };
  const i = cur.interval, start = instant(i?.start), end = instant(i?.end);
  if (cur.status !== 'known') return { known: false, reason: cur.unknown_reason || 'no_current_interval' };
  if (!i || !num(i.price) || !(end > start)) return { known: false, reason: 'inconsistent' };
  return { known: true, price: i.price, start, end, comparison: parseComparison(cur.comparison, baseline) };
}
function parseWindow(w, duration, baseline) {
  if (!w || typeof w !== 'object') return { known: false, reason: 'not_reported' };
  if (w.status !== 'known') return { known: false, reason: w.unknown_reason || 'no_contiguous_window' };
  const start = instant(w.start), end = instant(w.end);
  if (!num(w.mean_price) || !(end > start) || w.duration_minutes !== duration || end - start !== duration * 60000) return { known: false, reason: 'inconsistent' };
  const h = w.horizon, from = instant(h?.from), until = instant(h?.until);
  return { known: true, price: w.mean_price, start, end, horizon: Number.isFinite(from) && Number.isFinite(until) && until > from ? { from, until } : null, comparison: parseComparison(w.comparison, baseline) };
}

/** Validate the live answer against what was asked; a bad top level is `null` (invalid), a bad block is unknown alone. */
export function parseLive(answer, asked) {
  if (!topOk(answer, asked, 'live') || answer.window_minutes !== asked.duration) return null;
  const baseline = parseBaseline(answer.baseline);
  return { zone: answer.zone, readNow: instant(answer.now), baseline, current: parseCurrent(answer.current, baseline), window: parseWindow(answer.cheapest_window, asked.duration, baseline),
    providers: { baseline: providers(answer.provenance?.baseline_providers, 'provider'), live: providers(answer.provenance?.live, 'providers') }, currency: answer.currency };
}

const STAT_KEYS = ['mean', 'min', 'max', 'p10', 'p50', 'p90'];
function parseStats(s) {
  if (!s || typeof s !== 'object' || !STAT_KEYS.every(k => num(s[k]))) return null;
  if (!(s.min <= s.p10 && s.p10 <= s.p50 && s.p50 <= s.p90 && s.p90 <= s.max && s.min <= s.mean && s.mean <= s.max)) return null;
  if (!num(s.negative_share) || s.negative_share < 0 || s.negative_share > 100 || !(num(s.negative_seconds) && s.negative_seconds >= 0)) return null;
  return { mean: s.mean, min: s.min, max: s.max, p10: s.p10, p50: s.p50, p90: s.p90, negativeShare: s.negative_share, negativeSeconds: s.negative_seconds };
}
/** Validate a monthly answer; `null` when it is malformed or contradicts itself. */
export function parseMonthly(answer, asked) {
  if (!topOk(answer, asked, 'monthly') || answer.month !== asked.month || !['complete_calendar_month', 'completed_days_to_date'].includes(answer.scope) || !['known', 'unknown'].includes(answer.status)) return null;
  const cov = answer.coverage, ex = excluded(answer.days_excluded), min = count(answer.minimum_days) && answer.minimum_days > 0 ? answer.minimum_days : MIN_DAYS;
  if (![answer.days_expected, answer.days_complete, answer.days_partial].every(count) || !nullableCount(answer.days_held) || !ex || !cov || typeof cov !== 'object') return null;
  if (answer.days_complete + answer.days_partial > answer.days_expected) return null;
  const ratio = cov.valid_ratio === null ? null : cov.valid_ratio;
  if (!nullableCount(cov.seconds_expected) || !nullableCount(cov.seconds_valid) || !nullableCount(cov.seconds_partial) || (ratio !== null && !(num(ratio) && ratio >= 0 && ratio <= 1))) return null;
  if (count(cov.seconds_expected) && count(cov.seconds_valid) && cov.seconds_valid > cov.seconds_expected) return null;
  const stats = answer.status === 'known' ? parseStats(answer.statistics) : null;
  if (answer.status === 'known' && (!stats || answer.days_complete < min || answer.comparable?.meets_minimum !== true)) return null;
  if (answer.status === 'unknown' && answer.statistics) return null;
  return { month: answer.month, scope: answer.scope, toDate: answer.scope === 'completed_days_to_date', asOf: typeof answer.as_of_day === 'string' ? answer.as_of_day : null, zone: answer.zone,
    known: answer.status === 'known', reason: answer.status === 'known' ? null : (answer.unknown_reason || 'too_few_complete_days'), min, stats, currency: answer.currency, basis: basisKey(answer.basis), area: answer.area_id,
    daysExpected: answer.days_expected, daysComplete: answer.days_complete, daysPartial: answer.days_partial, excluded: ex,
    coverage: { ratio, expected: cov.seconds_expected ?? null, valid: cov.seconds_valid ?? null }, providers: providers(answer.provenance?.providers, 'provider') };
}

// ---- display ---------------------------------------------------------------------------------------------------------
const moneyIn = (value, currency) => { const d = displayPrice(value, currency); return d === null ? 'Unavailable' : `${summaryPriceText(d)} ${priceUnit(currency)}`; };
const stamp = (ms, zone, withDate = true) => {
  try { return new Intl.DateTimeFormat('en-GB', { timeZone: zone, ...(withDate ? { weekday: 'short', day: 'numeric', month: 'short' } : {}), hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(ms); } catch { return 'unknown time'; }
};
const localDay = (ms, zone) => { try { return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(ms); } catch { return null; } };
const span = (a, b, zone) => `${stamp(a, zone)}–${stamp(b, zone, localDay(a, zone) !== localDay(b, zone))}`;
const percent = (v, digits = 0) => `${v.toFixed(digits)}%`;
const sourceLine = list => list.length ? `Provider label${list.length > 1 ? 's' : ''} on the held files: ${list.join(', ')}` : 'Provider not reported';
const BASIS_TEXT = currency => `Raw published spot price per kWh, no fees, taxes or margin${currency === 'EUR' ? '; shown in euro cents' : ''}`;

function relativeLine(comparison, baseline) {
  if (comparison?.known) {
    const used = baseline.used, expected = baseline.expected, p = comparison.percentile;
    return { label: 'Relative', text: `Compared with ${used} of the last ${expected} days: higher than about ${Math.round(p)}% of that time (relative, duration-weighted; it does not change the fixed band)` };
  }
  const why = comparison?.reason ? reasonText(comparison.reason) : 'the baseline is unavailable';
  const days = baseline && baseline.expected !== null ? ` (${baseline.used} of ${baseline.expected} recent days usable, ${baseline.min} needed${baseline.excluded?.count ? `; ${excludedText(baseline.excluded)}` : ''})` : '';
  return { label: 'Relative', text: `Unknown: ${why}${days}` };
}
const baselineDetail = (b, live) => b && b.expected !== null ? `Baseline: the last ${b.expected} completed local days; ${b.used} fully held and used, ${b.held} held${b.excluded?.count ? `, ${excludedText(b.excluded)}` : ''}. ${sourceLine(live.providers.baseline)}.` : 'Baseline unavailable.';

function currentBlock(live, nowMs) {
  const cur = live.current, cu = live.currency, zone = live.zone;
  const ended = cur.known && cur.end <= nowMs;
  const block = { id: 'current', title: ended ? 'Price at last read' : 'Current price', value: 'Unavailable', status: '', detail: '', lines: [], details: [] };
  if (!cur.known) { block.status = `Unknown: ${reasonText(cur.reason)}`; block.lines.push(relativeLine(null, live.baseline), { label: 'Basis', text: BASIS_TEXT(cu) }); return block; }
  block.value = moneyIn(cur.price, cu);
  const band = priceBand(displayPrice(cur.price, cu), priceUnit(cu));
  block.status = band ? `In the ${band.label} band (${band.range} c/kWh, fixed)` : bandsApply(priceUnit(cu)) ? '' : `No fixed band is defined for ${cu}`;
  block.band = band ? band.key : null;
  block.lines.push({ label: 'Interval', text: ended ? `${span(cur.start, cur.end, zone)} (ended; waiting for a refresh)` : span(cur.start, cur.end, zone) });
  block.lines.push(relativeLine(cur.comparison, live.baseline));
  block.lines.push({ label: 'Basis', text: BASIS_TEXT(cu) });
  block.details.push(baselineDetail(live.baseline, live));
  return block;
}

function windowBlock(live, duration, pending) {
  const w = live.window, cu = live.currency, zone = live.zone;
  const block = { id: 'window', title: `Best published ${durationText(duration)} window`, value: 'Unavailable', status: '', detail: '', lines: [], details: [] };
  if (pending) { block.status = pending; return block; }
  if (!w.known) { block.status = `Unknown: ${reasonText(w.reason)}`; block.lines.push({ label: 'Basis', text: BASIS_TEXT(cu) }); return block; }
  block.value = moneyIn(w.price, cu);
  block.status = `${span(w.start, w.end, zone)} · ${durationText(duration)}`;
  block.lines.push({ label: 'Mean', text: 'Duration-weighted mean of the published prices in this window' });
  if (w.comparison.known) block.lines.push({ label: 'Relative', text: `Assumption: this window's mean compared with single interval prices of the last ${live.baseline.expected} days, higher than about ${Math.round(w.comparison.percentile)}% of interval time` });
  else block.lines.push({ label: 'Relative', text: `Unknown: ${reasonText(w.comparison.reason)}` });
  block.lines.push({ label: 'Not a plan', text: 'Published prices only: not the charging plan. It may fall outside the deadline, cap or car availability.' });
  block.lines.push({ label: 'Basis', text: BASIS_TEXT(cu) });
  block.details.push(`Searched the unbroken published stretch${w.horizon ? ` from ${stamp(w.horizon.from, zone)} to ${stamp(w.horizon.until, zone)}` : ' ahead'}; a gap or the end of publication ends a window, ties go to the earliest. ${sourceLine(live.providers.live)}.`);
  return block;
}

function monthColumn(m) {
  const f = v => moneyIn(v, m.currency);
  return { title: `${monthLabel(m.month)}${m.toDate ? ' so far' : ''}`, rows: m.known ? [`${f(m.stats.mean)}`, `${f(m.stats.min)} – ${f(m.stats.max)}`, `${f(m.stats.p10)} · ${f(m.stats.p50)} · ${f(m.stats.p90)}`, percent(m.stats.negativeShare, 1), `${m.daysComplete} of ${m.daysExpected}`] : [] };
}
const COMPARE_ROWS = ['Weighted mean', 'Low – high', '10th · 50th · 90th percentile', 'Time below zero', 'Complete days'];

function monthBlock(entry, month) {
  const block = { id: 'month', title: `${monthLabel(month)}`, value: 'Unavailable', status: 'Loading…', detail: '', lines: [], details: [] };
  if (!entry || entry.status === 'loading') return block;
  if (entry.status === 'error') { block.status = entry.error.message; return block; }
  const m = entry.parsed, f = v => moneyIn(v, m.currency);
  block.title = `${monthLabel(m.month)}${m.toDate ? ' so far' : ''}`;
  block.status = m.toDate ? `${m.daysComplete} of ${m.daysExpected} completed days${m.asOf ? ` (through ${m.asOf})` : ''} · month not complete` : `${m.daysComplete} of ${m.daysExpected} days complete`;
  if (m.daysPartial) block.status += ` · ${m.daysPartial} partial`;
  if (m.known) {
    block.value = f(m.stats.mean);
    block.lines.push({ label: 'Range', text: `Low ${f(m.stats.min)} · high ${f(m.stats.max)}` });
    block.lines.push({ label: 'Spread', text: `10th / 50th / 90th percentile (by time): ${f(m.stats.p10)} · ${f(m.stats.p50)} · ${f(m.stats.p90)}` });
    block.lines.push({ label: 'Below zero', text: `${percent(m.stats.negativeShare, 1)} of the time (${(m.stats.negativeSeconds / 3600).toFixed(1)} h)` });
  } else block.lines.push({ label: 'Unknown', text: `${reasonText(m.reason)}${m.reason === 'too_few_complete_days' ? ` (${m.min} needed)` : ''}; no price statistics are shown rather than a misleading one` });
  block.lines.push({ label: 'Coverage', text: m.coverage.ratio === null ? 'No completed day to measure yet' : `${percent(m.coverage.ratio * 100, 1)} of the expected time has complete prices${m.daysPartial ? `; ${m.daysPartial} partial day(s) are counted apart and not in the statistics` : ''}` });
  const ex = excludedText(m.excluded);
  if (ex) block.lines.push({ label: 'Excluded days', text: ex });
  block.lines.push({ label: 'Basis', text: BASIS_TEXT(m.currency) });
  block.details.push(`Statistics use the complete days only, weighted by time (15-minute and hourly rows mix without resampling). ${sourceLine(m.providers)}.${m.toDate ? ' The current month counts completed days only; today and the future are never included.' : ''}`);
  return block;
}

/** Side by side only when both answers are known, meet the minimum and share area, currency and basis; no maths here. */
export function compareMonths(a, b) {
  if (!a || !b) return null;
  const ca = a.parsed, cb = b.parsed;
  if (!ca || !cb) return { eligible: false, text: 'The other month could not be read, so no comparison is shown.' };
  const name = m => `${monthLabel(m.month)}${m.toDate ? ' so far' : ''}`;
  for (const m of [ca, cb]) if (!m.known) return { eligible: false, text: `No comparison: ${name(m)} has no statistics (${reasonText(m.reason)}).` };
  if (ca.currency !== cb.currency || ca.basis !== cb.basis || ca.area !== cb.area) return { eligible: false, text: 'No comparison: the two months use a different area, currency or price basis.' };
  const cols = [monthColumn(ca), monthColumn(cb)];
  const partial = [ca, cb].filter(m => m.toDate).map(m => `${monthLabel(m.month)} counts completed days only (${m.daysComplete} of ${m.daysExpected})`);
  return { eligible: true, head: ['', cols[0].title, cols[1].title], rows: COMPARE_ROWS.map((label, i) => [label, cols[0].rows[i], cols[1].rows[i]]), note: partial.length ? `${partial.join('; ')}; it is not a full month.` : 'Both are full months with enough complete days. Shown side by side, not subtracted.' };
}

// ---- failures ---------------------------------------------------------------------------------------------------------
function failure(error) {
  const code = typeof error?.code === 'string' ? error.code : '';
  if (/unauthorized|permission|forbidden/i.test(code)) return { state: 'permission', message: 'You do not have permission to read price insights.' };
  if (/unknown_command|not_found|unknown_message/i.test(code)) return { state: 'unavailable', message: 'The installed integration does not provide price insights yet; update the integration and card together.' };
  if (code === 'spotnav_unsupported_api_version') return { state: 'unavailable', message: 'The installed integration does not speak this insights version; update the integration and card together.' };
  if (code === 'spotnav_no_price_area' || code === 'spotnav_unknown_price_area') return { state: 'unavailable', message: 'No price area is configured, so there are no price insights.' };
  if (error?.message === 'invalid') return { state: 'invalid', message: 'The insights answer could not be understood and was not shown.' };
  return { state: 'error', message: 'Price insights could not be read.' };
}

const CAUTION = 'Price opportunities are not the charging plan: they may fall outside the deadline, cap or car availability. Reading this card never sends a plan, replans, wakes the car or changes a setting. Prices are not charging costs or savings.';
const METHOD = 'Prices are the raw published spot price per kWh without fees, taxes or margin; euro prices are shown in cents. The baseline is the last 30 completed local days of the price area that are fully held (at least 7 are needed). "Relative" says how much of that baseline time the price was lower, weighted by duration, and never recolours the chart; the Cheap / Normal / Medium / Expensive band is a separate fixed rule on euro cents (<8, 8 to <15, 15 to 25, >25). The best window is the cheapest unbroken stretch of published prices of the chosen length from now on; unpublished prices are never guessed. Monthly statistics use complete days only; the current month counts completed days to date. A comparison is shown only when both months have enough complete days on the same basis.';

/**
 * `request(params)` resolves the backend answer (live: the WebSocket, preview: a fixture of the same shape).
 * `onChange()` fires when an asynchronous result changed what to draw. A failure is never retried on its own.
 */
export function createPriceInsights({ request, onChange = () => {}, now = () => Date.now() }) {
  let ctx = null, key = null, liveSeq = 0, monthSeq = 0;
  const initial = () => ({ duration: DEFAULT_DURATION, month: null, compare: null, today: null, live: { result: null, at: NaN, loading: false, error: null, duration: null }, months: new Map() });
  let st = initial();
  const reset = () => { liveSeq++; monthSeq++; st = initial(); };
  const keyOf = c => JSON.stringify([c.charger, c.epoch, c.area, c.currency]);
  const options = () => monthOptions(ctx.today);
  const currentMonth = () => monthOf(ctx.today);
  const shownMonth = () => st.month || currentMonth();
  const known = month => options().some(o => o.value === month);

  async function loadLive() {
    const mine = ++liveSeq, myKey = key, asked = { charger: ctx.charger, area: ctx.area, currency: ctx.currency, duration: st.duration };
    st.live.loading = true; st.live.error = null;
    try {
      const answer = await request({ mode: 'live', duration_minutes: asked.duration });
      if (mine !== liveSeq || myKey !== key) return;
      const parsed = parseLive(answer, asked);
      if (!parsed) throw new Error('invalid');
      st.live.result = parsed; st.live.at = now(); st.live.duration = asked.duration;
    } catch (error) {
      if (mine !== liveSeq || myKey !== key) return;
      st.live.error = failure(error);
    }
    st.live.loading = false;
    onChange();
  }

  async function loadMonth(month) {
    const mine = ++monthSeq, myKey = key, asked = { charger: ctx.charger, area: ctx.area, currency: ctx.currency, month };
    const entry = { status: 'loading', token: mine, parsed: null, error: null, at: NaN };
    st.months.set(month, entry);
    for (const old of [...st.months.keys()]) if (st.months.size > CACHE_MONTHS && ![shownMonth(), st.compare, month].includes(old)) st.months.delete(old);
    try {
      const answer = await request({ mode: 'monthly', month });
      if (myKey !== key || st.months.get(month) !== entry) return;
      if (month !== shownMonth() && month !== st.compare) { st.months.delete(month); return; } // no longer asked for
      const parsed = parseMonthly(answer, asked);
      if (!parsed) throw new Error('invalid');
      Object.assign(entry, { status: 'ready', parsed, at: now() });
    } catch (error) {
      if (myKey !== key || st.months.get(month) !== entry) return;
      if (month !== shownMonth() && month !== st.compare) { st.months.delete(month); return; }
      Object.assign(entry, { status: 'error', error: failure(error) });
    }
    onChange();
  }

  const liveDue = () => {
    const l = st.live, age = now() - l.at;
    if (!l.result || l.loading || l.error) return false;
    const ended = l.result.current.known && l.result.current.end <= now();
    return age > LIVE_REFRESH_MS || (ended && age > INTERVAL_END_GAP_MS);
  };
  const wanted = () => [shownMonth(), st.compare].filter(Boolean);

  const api = {
    /** Tell it who is asking. A change of charger, generation/permission epoch, area or currency drops everything. */
    sync(next) {
      const valid = !!(next && next.charger && next.epoch !== undefined && typeof next.area === 'string' && next.area && /^[A-Z]{3}$/.test(next.currency || '') && Number.isFinite(dayMs(next.today)));
      const nextKey = valid ? keyOf(next) : null;
      if (nextKey !== key) { reset(); key = nextKey; }
      ctx = valid ? next : null;
      if (!ctx) return api;
      if (st.today !== null && st.today !== ctx.today) { st.months.clear(); monthSeq++; st.live.at = Math.min(st.live.at, now() - LIVE_REFRESH_MS - 1); }
      st.today = ctx.today;
      if (st.month && !known(st.month)) st.month = null;
      if (st.compare && (!known(st.compare) || st.compare === shownMonth())) st.compare = null;
      if (!st.live.result && !st.live.loading && !st.live.error) void loadLive();
      else if (liveDue()) void loadLive();
      for (const month of wanted()) if (!st.months.has(month)) void loadMonth(month);
      return api;
    },
    /** An explicit window length (15..720 in steps of 15): one live read; nothing is saved. */
    setDuration(minutes) {
      if (!ctx || !DURATIONS.includes(minutes) || minutes === st.duration) return;
      st.duration = minutes;
      void loadLive(); onChange();
    },
    /** An explicit month from the bounded picker: one monthly read unless it is already held in memory. */
    selectMonth(month) {
      if (!ctx || !known(month)) return;
      st.month = month === currentMonth() ? null : month;
      if (st.compare === shownMonth()) st.compare = null;
      const entry = st.months.get(month);
      if (!entry || entry.status === 'error') void loadMonth(month);
      onChange();
    },
    /** An explicit second month (or '' / 'previous'): at most one more monthly read. */
    selectCompare(month) {
      if (!ctx) return;
      const target = month === 'previous' ? prevMonth(shownMonth()) : month;
      if (!target) { st.compare = null; onChange(); return; }
      if (!known(target) || target === shownMonth()) return;
      st.compare = target;
      const entry = st.months.get(target);
      if (!entry || entry.status === 'error') void loadMonth(target);
      onChange();
    },
    /** Explicit retry of whatever failed; each failed read once, never on a timer. */
    retry() {
      if (!ctx) return;
      if (st.live.error && !st.live.loading) void loadLive();
      for (const month of wanted()) if (st.months.get(month)?.status === 'error') void loadMonth(month);
      onChange();
    },
    view() {
      if (!ctx) return null;
      const nowMs = now(), l = st.live;
      const month = shownMonth(), opts = options();
      const entry = st.months.get(month), cmpEntry = st.compare ? st.months.get(st.compare) : null;
      const banners = [];
      const blocks = [];
      let currentUsable = false;
      if (l.result) {
        const refreshFailed = !!l.error;
        const stale = refreshFailed || nowMs - l.at > 2 * LIVE_REFRESH_MS;
        currentUsable = !stale;
        if (refreshFailed) banners.push({ kind: 'refresh-failed', text: `The latest refresh failed (${l.error.message}). Prices below are the earlier read from ${stamp(l.at, l.result.zone, false)}.` });
        const durationPending = l.duration !== st.duration ? (l.loading ? 'Loading…' : l.error ? l.error.message : 'Loading…') : null;
        const cur = currentBlock(l.result, nowMs);
        if (stale) cur.title = 'Price at last read';
        blocks.push(cur, windowBlock(l.result, st.duration, durationPending));
      } else {
        const text = l.error ? l.error.message : 'Loading price insights…';
        banners.push({ kind: l.error ? l.error.state : 'loading', text });
        blocks.push({ id: 'current', title: 'Current price', value: 'Unavailable', status: l.error ? 'Unavailable' : 'Loading…', lines: [], details: [] },
          { id: 'window', title: `Best published ${durationText(st.duration)} window`, value: 'Unavailable', status: l.error ? 'Unavailable' : 'Loading…', lines: [], details: [] });
      }
      const mb = monthBlock(entry, month);
      let table = null;
      if (st.compare) {
        const cmp = cmpEntry?.status === 'ready' && entry?.status === 'ready' ? compareMonths(entry, cmpEntry) : null;
        if (cmp) table = cmp;
        else table = { eligible: false, text: cmpEntry?.status === 'error' ? cmpEntry.error.message : !entry || entry.status !== 'ready' ? 'Comparison waits for the selected month.' : 'Loading the other month…' };
      }
      mb.table = table;
      blocks.push(mb);
      const unit = priceUnit(ctx.currency);
      const failed = !!l.error || [entry, cmpEntry].some(e => e?.status === 'error');
      const compareOptions = [{ value: '', label: 'No comparison' }, ...opts.filter(o => o.value !== month)];
      const previous = prevMonth(month);
      return {
        state: l.result ? 'ready' : l.error ? l.error.state : 'loading',
        intro: `Published spot prices in ${unit}, without fees or taxes. ${l.result ? `Read ${stamp(l.at, l.result.zone, false)} (${l.result.zone}).` : ''}`.trim(),
        blocks, banners, caution: CAUTION, method: METHOD, currentUsable,
        controls: { duration: { value: st.duration, options: DURATIONS.map(v => ({ value: v, label: durationText(v) })), busy: l.loading },
          month: { value: month, options: opts, busy: entry?.status === 'loading' },
          compare: { value: st.compare || '', options: compareOptions, previous: previous && known(previous) && st.compare !== previous ? { value: previous, label: monthLabel(previous) } : null, busy: cmpEntry?.status === 'loading' },
          canRetry: failed && !l.loading },
      };
    },
    dispose() { liveSeq++; monthSeq++; ctx = null; key = null; st = initial(); },
  };
  return api;
}
