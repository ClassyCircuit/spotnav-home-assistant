// The Effective track's input (Stage 7.3b): the LATEST readback's remaining period only, from the Morek status the panel
// already holds. Display only: a reported limit is neither power nor an installed-profile inventory nor proof of charging,
// and a stale, failed or unmatched read is unknown, never a green current state. History never supplies this.
import { observationFreshness } from '../src/observation-freshness.ts';

const unknown = reason => ({ state: 'unknown', reason });
const clock = (ms, zone) => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: zone || 'UTC', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(ms); } catch { return 'recently'; } };

/** @returns {{state:'unknown', reason:string} | {state:'reported', readAt:number, readAtText:string, unit:string, differs:boolean, spans:{start:number,end:number,value:number}[]}} */
export function effectiveTrack(status, observedAt, failed, now, zone = null) {
  if (!status) return unknown('Morek status is unavailable, so effective limits are unknown.');
  if (observationFreshness(observedAt, now, failed) !== 'fresh') return unknown('The Morek status read is stale or failed, so no readback is shown as current.');
  const eff = status.effective;
  if (!eff || typeof eff !== 'object' || !Array.isArray(eff.periods)) return unknown('No effective readback is available.');
  const readAt = Date.parse(eff.fetched_at || '');
  if (observationFreshness(Number.isFinite(readAt) ? readAt : null, now) !== 'fresh') return unknown('The latest readback is too old, or has no usable time, to describe the charger now.');
  const start = Date.parse(eff.schedule_start || ''), seconds = eff.duration_s;
  if (!Number.isFinite(start) || typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return unknown('The readback does not say what period it covers.');
  const end = start + seconds * 1000;
  if (end <= now) return unknown('The period covered by the latest readback has ended.');
  // Fail closed: one malformed, negative, out-of-range, duplicate or out-of-order period makes the whole readback unknown;
  // a limit is never carried across a period that could not be read.
  const points = eff.periods.map(p => ({ at: Date.parse(p?.at || ''), value: p?.amps }));
  if (!points.length) return unknown('The readback lists no limits.');
  if (points.some((p, i) => !Number.isFinite(p.at) || typeof p.value !== 'number' || !Number.isFinite(p.value) || p.value < 0 || p.at < start || p.at >= end || (i > 0 && p.at <= points[i - 1].at)))
    return unknown('The readback has a malformed or out-of-order period, so its limits are not shown.');
  const spans = [];
  points.forEach((p, i) => {
    const a = Math.max(p.at, now, start), b = Math.min(i + 1 < points.length ? points[i + 1].at : end, end);
    if (b > a) spans.push({ start: a, end: b, value: p.value });
  });
  if (!spans.length) return unknown('The readback has no remaining period.');
  const associated = !!status.verification?.readback_at && status.verification.readback_at === eff.fetched_at;
  const unit = typeof eff.rate_unit === 'string' && /^[A-Za-z/]{1,8}$/.test(eff.rate_unit) ? eff.rate_unit : 'A';
  return { state: 'reported', readAt, readAtText: clock(readAt, zone), unit, spans, differs: associated && status.verification?.reason === 'limits_or_transitions_differ' };
}
