import { observationFreshness } from '../src/observation-freshness.ts';
const instant = v => typeof v === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(v) ? Date.parse(v) : NaN;
/** Convert a cached effective readback to bounded presentation spans, in milliseconds. */
export function effectiveDisplay(status, observedAt, now) {
  const e = status?.effective;
  if (!e || typeof e !== 'object' || e.status !== 'Accepted') return { state: 'unknown' };
  const fetchedAt = instant(e.fetched_at);
  if (!Number.isFinite(now) || !Number.isFinite(observedAt) || observedAt > now || !Number.isFinite(fetchedAt) || fetchedAt > now || fetchedAt > observedAt) return { state: 'unknown' };
  const start = instant(e.schedule_start), duration = e.duration_s, end = start + duration * 1000;
  if (!Number.isFinite(start) || typeof duration !== 'number' || !Number.isFinite(duration) || duration <= 0 || !Number.isFinite(end) || end <= start || !['A', 'W'].includes(e.rate_unit) || !Array.isArray(e.periods) || !e.periods.length) return { state: 'invalid' };
  const points = e.periods.map(p => ({ at: instant(p?.at), value: p?.amps }));
  if (points.some((p, i) => !Number.isFinite(p.at) || typeof p.value !== 'number' || !Number.isFinite(p.value) || p.value < 0 || p.at < start || p.at >= end || (i > 0 && p.at <= points[i - 1].at))) return { state: 'invalid' };
  const spans = points.map((p, i) => ({ start: p.at, end: points[i + 1]?.at ?? end, value: p.value }));
  const stale = observationFreshness(observedAt, now) !== 'fresh' || observationFreshness(fetchedAt, now) !== 'fresh';
  return { state: end <= now ? 'expired' : stale ? 'stale' : 'fresh', fetchedAt, start, end, unit: e.rate_unit, spans };
}
