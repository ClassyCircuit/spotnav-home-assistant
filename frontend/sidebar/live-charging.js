// Stage 5.7b2: what the charger reports and measures now. Pure: decoded Morek status plus a clock.
// Reported connector state, measured current/power and the cumulative energy register are separate
// observations. A schedule, an ACK, a readback or an effective limit is never measured flow, a missing
// reading is Unknown (not 0), and an actual measured 0 is shown as 0. Nothing here writes anything.
import { observationFreshness } from '../src/observation-freshness.ts';
import { evidence, STRICT_MAX_AGE_MS } from './evidence-freshness.js';

const NOT_CHARGING = new Set(['disconnected', 'connected', 'paused', 'finished']);
const POWER_FLOW_W = 100;     // above this a measured flow contradicts a reported not-charging state
const CURRENT_FLOW_A = 1;

// A reading counts only with a finite value, a parseable timestamp and a bounded age on this clock. Whether it is
// current is the backend's connection-aware judgement when present (15.6), else the strict bound.
function read(ready, key, now, unitCheck) {
  return evidence(ready, key, ready?.live?.[key], now, r => unitCheck ? unitCheck(r) : (typeof r.value === 'number' && Number.isFinite(r.value)));
}

const ago = ms => ms < 60000 ? `${Math.floor(ms / 1000)} s ago` : ms < 3600000 ? `${Math.floor(ms / 60000)} min ago` : `${Math.floor(ms / 3600000)} h ago`;
const clock = ms => new Date(ms).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
const num = (value, digits) => Number(value.toFixed(digits)).toString();

export function liveCharging(status, observedAt, failed, now = Date.now()) {
  const fresh = observationFreshness(observedAt, now, failed) === 'fresh';
  const ready = fresh ? status?.readiness : null;
  const unknown = reason => ({power: 'Unknown', summary: `${reason} Measured power and charging are unknown.`, mismatch: false, reported: null, measured: null});
  if (!fresh) return unknown('Morek status is unavailable or stale.');
  if (ready?.control === 'unavailable') return unknown('The charger is offline or its control is unavailable.');
  const live = ready?.live;
  if (!live || typeof live !== 'object') return unknown('No live charger observation is available.');
  const own = Number.isInteger(live.connector_id) ? live.connector_id : null;
  const expected = Number.isInteger(status?.connector_id) ? status.connector_id : null;
  // Evidence must belong to the connector this status is about; otherwise it says nothing about it.
  if (own === null || expected === null || own !== expected) return unknown('The live readings are not confirmed to belong to this connector.');

  const reported = read(ready, 'status', now, r => typeof r.value === 'string' && r.value !== '');
  const reportedFresh = reported?.fresh ? reported : null;
  const power = read(ready, 'power_w', now);
  const current = read(ready, 'current_a', now);
  const energy = read(ready, 'energy_register_kwh', now, r => typeof r.value === 'number' && Number.isFinite(r.value) && r.value >= 0);
  const flow = [power && {kind: 'power', ...power}, current && {kind: 'current', ...current}].filter(Boolean).find(item => item.fresh) || null;
  const normalized = reportedFresh && typeof live.status.normalized === 'string' ? live.status.normalized : null;

  const parts = [];
  parts.push(reportedFresh ? `Charger reports “${reportedFresh.value}” for connector ${own}, ${reportedFresh.judged === 'current' && reportedFresh.age > STRICT_MAX_AGE_MS ? `unchanged since ${clock(reportedFresh.at)}` : ago(reportedFresh.age)}; a reported state is not measured power.`
    : reported ? `Last reported connector state “${reported.value}” ${reported.judged === 'last_known' ? `is last known (${ago(reported.age)}); the charger connection is not confirmed now` : `is stale (${ago(reported.age)})`}; current state unknown.`
    : `Connector ${own} reported state unknown.`);
  let powerText = 'Unknown';
  if (power?.fresh) { powerText = power.value === 0 ? '0 W measured' : `${power.value >= 1000 ? num(power.value / 1000, 2) + ' kW' : num(power.value, 0) + ' W'} measured`; parts.push(`Measured power ${powerText}, ${ago(power.age)}.`); }
  else if (current?.fresh) { powerText = `${num(current.value, 1)} A measured (power unknown)`; parts.push(`Measured current ${num(current.value, 1)} A, ${ago(current.age)}; power is not derived from it.`); }
  else if (power || current) {
    const old = power || current; powerText = 'Unknown';
    const why = old.judged === 'idle' ? '; no reading is expected while nothing is charging' : old.judged === 'last_known' ? '; the charger connection is not confirmed now' : '';
    parts.push(`Last measured ${power ? 'power' : 'current'} is ${why ? 'old' : 'stale'} (${ago(old.age)}${why}); not shown as current.`);
  }
  else parts.push('No measured power or current source is available for this connector.');
  if (energy) parts.push(`Cumulative energy register ${num(energy.value, 2)} kWh${energy.fresh ? '' : ' (stale)'}, ${ago(energy.age)}; this is not this session’s energy.`);
  else parts.push('Energy register unavailable.');

  let mismatch = false;
  if (flow && reportedFresh && normalized) {
    const flowing = flow.kind === 'power' ? flow.value > POWER_FLOW_W : flow.value > CURRENT_FLOW_A;
    const stopped = flow.value === 0;
    if (normalized === 'charging' && stopped) mismatch = true;
    else if (NOT_CHARGING.has(normalized) && flowing) mismatch = true;
  }
  if (mismatch) parts.push('Reported state and measured flow disagree; neither is verified.');
  parts.push('A sent schedule, ACK or effective limit is not measured charging.');
  return {power: powerText, summary: parts.join(' '), mismatch, reported: reportedFresh?.value ?? null, measured: flow ? flow.kind : null};
}
