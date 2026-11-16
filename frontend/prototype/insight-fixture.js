// Fictional answers in the exact shape of `spotnav/get_price_insights` (api_version 1, modes live and monthly), for the
// local preview and the tests. The sample axis is Mon 9 Nov 2026, fixed UTC (no DST model); prices are the chart's own
// sample rows in raw major units, so the card agrees with the chart. Nothing here is a real market or a real baseline.
import { sampleRows } from './price-days-fixture.js';

export const INSIGHT_TODAY = '2026-11-09';
export const INSIGHT_ZONE = 'Etc/UTC';
export const INSIGHT_NOW = Date.UTC(2026, 10, 9, 14, 30);
const MIN = 60000, HOUR = 3600000;
const iso = ms => new Date(ms).toISOString();
const BASIS = currency => ({ kind: 'published_spot', unit: 'major_per_kwh', currency, fees: 'none' });
const rows = sampleRows.map(r => ({ start: Date.parse(r.start), end: Date.parse(r.end), price: r.raw_price })).sort((a, b) => a.start - b.start);

/** The cheapest unbroken stretch of `minutes` from now in the published sample rows, as the backend would answer it. */
function cheapest(minutes) {
  const need = minutes * MIN, from = INSIGHT_NOW;
  const future = rows.filter(r => r.end > from).map(r => ({ ...r, start: Math.max(r.start, from) }));
  const starts = [...new Set(future.map(r => r.start))];
  let best = null;
  for (const start of starts) {
    let at = start, sum = 0;
    for (const r of future) { if (r.end <= at) continue; if (r.start > at) break; const to = Math.min(r.end, start + need); sum += r.price * (to - at); at = to; if (at >= start + need) break; }
    if (at < start + need) continue;
    const mean = sum / need;
    if (!best || mean < best.mean - 1e-12) best = { start, end: start + need, mean };
  }
  return { best, until: future.at(-1).end };
}
const current = () => rows.find(r => r.start <= INSIGHT_NOW && INSIGHT_NOW < r.end);
const local = ms => iso(ms).replace('Z', '+00:00');

const baseline = (known, over = {}) => ({ status: known ? 'known' : 'unknown', unknown_reason: known ? null : 'baseline_too_short', window_from: '2026-10-10', window_to: '2026-11-08', days_expected: 30,
  days_held: known ? 27 : 4, days_used: known ? 26 : 4, days_excluded: known ? { count: 1, reasons: { partial: 1 } } : { count: 0, reasons: {} }, minimum_days: 7, seconds_expected: 2592000, seconds_used: known ? 2246400 : 345600, resolution_minutes: 15, ...over });

/** Backend-shaped live answer; `missing` models a young installation (no baseline, nothing published). */
export function liveAnswer(context, duration, { missing = false } = {}) {
  const cur = current(), win = missing ? { best: null } : cheapest(duration);
  const known = !missing;
  return { api_version: 1, charger_id: context.charger, mode: 'live', area_id: context.area, zone: INSIGHT_ZONE, currency: context.currency, basis: BASIS(context.currency),
    now: iso(INSIGHT_NOW), now_local: local(INSIGHT_NOW), today: INSIGHT_TODAY, window_minutes: duration, baseline: baseline(known), live_days_skipped: {}, resolution_minutes: 15,
    current: !missing && cur ? { status: 'known', unknown_reason: null, interval: { start: iso(cur.start), end: iso(cur.end), start_local: local(cur.start), end_local: local(cur.end), duration_seconds: (cur.end - cur.start) / 1000, price: cur.price, elapsed_seconds: (INSIGHT_NOW - cur.start) / 1000 },
      comparison: known ? { status: 'known', unknown_reason: null, percentile: 62.5, cheaper_seconds: 1400000, equal_seconds: 90000, baseline_seconds: 2246400 } : { status: 'unknown', unknown_reason: 'baseline_unknown', percentile: null, cheaper_seconds: null, equal_seconds: null, baseline_seconds: null } }
      : { status: 'unknown', unknown_reason: 'no_current_interval', interval: null, comparison: { status: 'unknown', unknown_reason: 'baseline_unknown', percentile: null } },
    cheapest_window: win.best ? { status: 'known', unknown_reason: null, duration_minutes: duration, start: iso(win.best.start), end: iso(win.best.end), start_local: local(win.best.start), end_local: local(win.best.end), mean_price: win.best.mean,
      comparison: known ? { status: 'known', unknown_reason: null, percentile: 9.5 } : { status: 'unknown', unknown_reason: 'baseline_unknown', percentile: null }, horizon: { from: iso(INSIGHT_NOW), until: iso(win.until), runs: 1 } }
      : { status: 'unknown', unknown_reason: missing ? 'no_future_prices' : 'no_contiguous_window', duration_minutes: duration, start: null, end: null, mean_price: null, comparison: null, horizon: null },
    assumptions: ['raw published spot price', 'trailing 30 completed local days'], unknown_reason: missing ? 'baseline_too_short' : null,
    provenance: { baseline_providers: [{ provider: 'Sample feed', files: 26 }], live: [{ day: INSIGHT_TODAY, state: 'ready', source: 'network', fetched_at: `${INSIGHT_TODAY}T12:00:00+00:00`, providers: ['Sample feed'] }] } };
}

// month -> [days_expected, complete, partial, status, stats]; fictional. 2026-11 is the current month (completed days to date).
const STATS = { mean: 0.1234, min: -0.012, max: 0.431, p10: 0.034, p50: 0.109, p90: 0.236, negative_seconds: 10800, negative_share: 1.4, population_seconds: 777600 };
const MONTHS = {
  '2026-11': { expected: 8, complete: 8, partial: 0, toDate: true, stats: STATS },
  '2026-10': { expected: 31, complete: 29, partial: 1, excluded: { count: 2, reasons: { partial: 1, not_held: 1 } }, stats: { ...STATS, mean: 0.1411, min: 0.004, max: 0.389, p10: 0.047, p50: 0.128, p90: 0.255, negative_seconds: 0, negative_share: 0 } },
  '2026-09': { expected: 30, complete: 4, partial: 2, excluded: { count: 26, reasons: { not_held: 24, partial: 2 } }, stats: null },
};
const nextDay = day => new Date(Date.parse(`${day}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);

/** Backend-shaped monthly answer; months not listed are not held at all. */
export function monthlyAnswer(context, month, { missing = false } = {}) {
  const m = !missing && MONTHS[month], toDate = month === INSIGHT_TODAY.slice(0, 7);
  const expected = toDate ? 8 : m ? m.expected : new Date(Date.UTC(+month.slice(0, 4), +month.slice(5), 0)).getUTCDate();
  const complete = m ? m.complete : 0, known = !!m?.stats && complete >= 7;
  return { api_version: 1, charger_id: context.charger, mode: 'monthly', area_id: context.area, month, scope: toDate ? 'completed_days_to_date' : 'complete_calendar_month', calendar_complete: !toDate, as_of_day: toDate ? '2026-11-08' : null,
    days_in_month: toDate ? 30 : expected, days_expected: expected, days_held: m ? m.complete + m.partial : 0, days_complete: complete, days_partial: m ? m.partial : 0,
    days_excluded: m ? (m.excluded || { count: 0, reasons: {} }) : { count: expected, reasons: expected ? { not_held: expected } : {} }, minimum_days: 7,
    coverage: { seconds_expected: expected * 86400, seconds_valid: complete * 86400, seconds_partial: (m?.partial || 0) * 43200, valid_ratio: expected ? complete / expected : null },
    status: known ? 'known' : 'unknown', unknown_reason: known ? null : expected ? 'too_few_complete_days' : 'no_completed_days', statistics: known ? m.stats : null, resolution_minutes: 15,
    comparable: { meets_minimum: known, minimum_days: 7, days_complete: complete }, assumptions: ['raw published spot price', 'complete days only'], basis: BASIS(context.currency), currency: context.currency, zone: INSIGHT_ZONE,
    now: iso(INSIGHT_NOW), now_local: local(INSIGHT_NOW), today: INSIGHT_TODAY, window_from: `${month}-01`, window_to: nextDay(`${month}-28`),
    provenance: { providers: m ? [{ provider: 'Sample feed', files: complete + m.partial }] : [] } };
}

/** `request` for `createPriceInsights`: the same answers the backend would give, with its stable error codes. */
export function fixtureInsightsRequest(context, options = {}) {
  return async params => {
    if (params.mode === 'live') return liveAnswer(context, params.duration_minutes ?? 60, options);
    if (params.mode === 'monthly') return monthlyAnswer(context, params.month ?? INSIGHT_TODAY.slice(0, 7), options);
    throw Object.assign(new Error('refused'), { code: 'spotnav_invalid_insight_request' });
  };
}
