// Stage 15.7a: adopt the backend's connection-aware per-quantity freshness judgement (15.6, `readiness.freshness`)
// for DISPLAY. Pure and read-only; it never changes what the backend executes on.
//
// Two different questions are kept apart:
//   * `fresh`  - is the reading current enough to show as the present state? The backend judgement decides when
//                it is present (a quiet healthy connector stays current; a silent sampled value does not).
//   * `strict` - would the old strict bound (180 s and the reading's own `fresh` flag, which execution still
//                uses) accept it? Shown as a fact only; it never enables anything here.
// With no judgement (an older backend) the strict bound is the display bound, exactly as before. A judgement
// that is present but malformed, missing for a quantity, or about a different report fails closed to unknown.
export const STRICT_MAX_AGE_MS = 180000;
export const CLOCK_SKEW_MS = 5000;

// reading key (readiness.live) -> judgement key (readiness.freshness.quantities)
const JUDGED = {status: 'status', transaction: 'transaction', control_state: 'charging_control',
  power_w: 'power_w', current_a: 'current_a', energy_register_kwh: 'energy_register_kwh'};
const STATES = new Set(['current', 'last_known', 'idle', 'unknown']);

/**
 * @returns {{state: 'current'|'last_known'|'idle'|'unknown', link: string|null}|null}
 *   null = no judgement offered (legacy strict display). Otherwise always a state, unknown on any doubt.
 */
export function judgementFor(ready, key, observedAtMs) {
  const block = ready?.freshness;
  if (block === undefined || block === null) return null;
  const unknown = {state: 'unknown', link: null};
  if (typeof block !== 'object' || Array.isArray(block)) return unknown;
  const quantities = block.quantities;
  if (!quantities || typeof quantities !== 'object' || Array.isArray(quantities)) return unknown;
  const item = quantities[JUDGED[key]];
  if (!item || typeof item !== 'object' || !STATES.has(item.state)) return unknown;
  // The judgement must be about this very report, not another.
  const reported = Date.parse(item.reported_at || '');
  if (!Number.isFinite(reported) || reported !== observedAtMs) return unknown;
  if (item.age_s != null && !(typeof item.age_s === 'number' && Number.isFinite(item.age_s) && item.age_s >= 0)) return unknown;
  const link = item.link && typeof item.link === 'object' && typeof item.link.state === 'string' ? item.link.state : null;
  return {state: item.state, link};
}

/**
 * One reading as display evidence, or null when it is not evidence at all (no value, bad timestamp, a clock in
 * the future). `accept(value)` checks the type; `fresh`/`strict`/`judged` are described above.
 */
export function evidence(ready, key, reading, now, accept) {
  if (!reading || typeof reading !== 'object') return null;
  const at = Date.parse(reading.observed_at || '');
  if (!Number.isFinite(at) || !Number.isFinite(now) || !accept(reading)) return null;
  const age = now - at;
  if (age < -CLOCK_SKEW_MS) return null;                       // a future timestamp is not evidence
  const strict = age <= STRICT_MAX_AGE_MS && reading.fresh !== false;
  const judgement = judgementFor(ready, key, at);
  const fresh = judgement === null ? strict : judgement.state === 'current';
  return {value: reading.value, at, age: Math.max(0, age), fresh, strict, judged: judgement ? judgement.state : null, reading};
}
