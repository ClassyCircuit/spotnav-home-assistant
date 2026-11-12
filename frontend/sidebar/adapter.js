// Live adapter: no prototype modules, no calculations of financial or charger state.
import { decodeDashboard } from '../src/validate.ts';
import { decodeMorekState } from '../src/morek-view.ts';
import { healthKey } from '../src/daily-overview.ts';
import { translate } from '../src/i18n/index.ts';
import { publishedChart } from './price-chart.js';

const U = 'Unknown';
const date = (value, zone) => {
  const ms = typeof value === 'number' ? value : Date.parse(value || '');
  if (!Number.isFinite(ms)) return U;
  try { return new Intl.DateTimeFormat('en', {dateStyle:'medium', timeStyle:'short', timeZone:zone || 'UTC'}).format(ms) + (zone ? '' : ' UTC'); } catch { return U; }
};
const part = (ms, zone, options) => {
  if (!Number.isFinite(ms)) return U;
  try { return new Intl.DateTimeFormat('en', {...options,timeZone:zone || 'UTC'}).format(ms) + (zone ? '' : ' UTC'); } catch { return U; }
};

export function dashboardAdapter(raw, statusRaw, observedAt, now = Date.now(), failed = false, dashboardFailed = false) {
  const decoded = decodeDashboard(raw);
  if (!decoded.ok) return null;
  const d = decoded.value, zone = d.market?.timezone || null;
  const generated = Date.parse(d.generated_at || '');
  const stale = !Number.isFinite(generated) || generated > now || now - generated > 90000;
  const socAge = d.soc?.age_s;
  // Match the backend's target_stop.SOC_FRESH_MAX_AGE_S, not a warning threshold.
  const socStale = stale || !Number.isFinite(socAge) || socAge < 0 || socAge + (now-generated)/1000 > 180;
  const status = decodeMorekState(statusRaw);
  const health = translate('en', healthKey(status, observedAt, failed, false, now));
  const statusFresh = !failed && Number.isFinite(observedAt) && observedAt <= now && now-observedAt <= 90000;
  const ready = statusFresh ? status?.readiness : null;
  const control = ready?.control === 'available' ? 'available' : ready?.control === 'unavailable' ? 'unavailable' : 'unknown';
  const vehicleAt = Date.parse(ready?.vehicle_observed_at || '');
  const vehicleFresh = Number.isFinite(vehicleAt) && vehicleAt <= now && now-vehicleAt <= 180000;
  const vehicle = vehicleFresh && ready?.vehicle === 'connected' ? 'connected' : vehicleFresh && ready?.vehicle === 'disconnected' ? 'disconnected' : 'unknown';
  const readiness = `Control ${control} · vehicle ${vehicle} · transaction / authorization unknown · measured charging unknown. Authorization for a new session requires installation-specific verification; no active transaction is not a schedule prohibition.`;
  const proposal = d.plan.proposal;
  const planStale = stale || d.planning?.historical === true || !!(proposal?.periods.length && proposal.periods.every(p=>p.endMs<=now));
  const windows = !planStale && proposal ? proposal.periods.map(p=>({start:p.startMs,end:p.endMs})) : null;
  const nextWindow = windows?.find(w=>w.end>now) || null;
  const currency = proposal?.cost?.currency || null;
  const warning = status?.outcomes?.uncertain || status?.operator?.state === 'mismatch' || status?.verification?.reason === 'limits_or_transitions_differ';
  const published = publishedChart(raw, d.market, now, stale || dashboardFailed);
  const priceFreshness = `Today source fetched ${date(raw?.prices?.today_fetched_at,zone)}; tomorrow source fetched ${date(raw?.prices?.tomorrow_fetched_at,zone)}.`;
  return {
    draftKey: d.charger.charger_id,
    format: {currency, minutesPerTimeUnit:1/60000, time: ms=>part(ms,zone,{timeStyle:'short'}), day: ms=>part(ms,zone,{dateStyle:'medium'}), ...published?.format},
    model: {
      windows, nextWindow, chart:published?.chart, totals: !planStale && proposal ? {energy:proposal.planned_kwh,cost:proposal.unpriced ? null : proposal.cost?.value} : null,
      vehicle: {status: stale ? 'Connection unavailable · stale dashboard' : d.charger.available ? (d.connection?.state || U) : 'Charger unavailable', detail:`Dashboard observed ${date(d.generated_at,zone)}${stale ? ' · stale' : ''}`, power:'Unavailable', soc: socStale ? null : d.soc?.value, stale:socStale, policy: (d.plan.price_policy?.explanations || []).map(code=>{const keys={minimum_exception:'exception',minimum_shortfall:'minimumShortfall',target_shortfall:'targetShortfall',recalculating:'recalculating',unavailable:'unavailable',minimum_covered:'covered',within_cap:'within',target_met:'targetMet',error:'error'};return keys[code] ? translate('en',`daily.policy.${keys[code]}`) : U;}).join(' ') || U},
      settings: {target:d.soc?.target_percent, minimum:d.settings?.minimum_ready_by_soc, cap:d.settings?.soft_price_cap, readyBy:d.settings?.departure_time},
      canSave:false, untilDeadline:U, targetNote:'',
      warning:warning ? {title:'Morek health requires attention',detail:`${health}${status?.outcomes?.uncertain && (status?.operator?.state === 'mismatch' || status?.verification?.reason === 'limits_or_transitions_differ') ? ' · Effective limits mismatch the sent schedule.' : ''}`} : null,
      evidence:{status:health, context:`Morek status observed ${date(observedAt,zone)}${failed ? ' · unavailable' : ''}; separate from dashboard`,readiness,proposal:date(d.planning?.calculated_at,zone),sent:`${date(status?.sent_at,zone)} · ${status?.ack || U}`,readback:date(status?.effective?.fetched_at,zone),measurement:'SOC age and measured power unavailable when stale or unsupported',dispatch:`${status?.ownership?.completion_authorized ? 'Schedule ownership confirmed for this process.' : 'Schedule dispatch blocked; completed migration may require admin reconfirmation after restart or reconnect.'} External OCPP writers and native protection are not verified; the historical mismatch does not establish current state. A held exit or uncertain outcome remains blocked. Disabling the integration may leave a schedule or 0 A limit; no physical stop or profile removal is implied.`},
      labels:{settingsNote:'Read-only preview. Plan controls are unavailable in this slice.',saveLabel:'Save plan · unavailable',powerNote:'No verified general Morek power source',planLabel:'Backend policy:',chartIntro:'Published source price before configured fiscal additions; source-included charges may apply.',chartNote:`Held published intervals only. ${priceFreshness} Unpublished future and history are unavailable. Cap is omitted if its basis differs or is unknown.`,bands:'',dialogNote:'Proposal only; not necessarily sent.',footer:'Dashboard and Morek status are separate observations.'}
    }, actions:{}
  };
}
