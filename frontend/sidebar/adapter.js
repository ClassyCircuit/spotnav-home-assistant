// Live adapter: no prototype modules, no calculations of financial or charger state.
import { decodeDashboard } from '../src/validate.ts';
import { decodeMorekState, morekEvidence } from '../src/morek-view.ts';
import { healthKey } from '../src/daily-overview.ts';
import { translate } from '../src/i18n/index.ts';
import { reserveModel, reserveWindow } from '../shared-dashboard/reserve-model.js';
import { learningModel, LEARNING_KEYS } from '../shared-dashboard/learning-model.js';
import { publishedChart } from './price-chart.js';
import { displayPrice } from '../shared-dashboard/price-format.js';
import { observationFreshness } from '../src/observation-freshness.ts';
import { liveCharging } from './live-charging.js';
import { chargeSession } from './charge-session.js';

const U = 'Unknown';
const reserveText = () => ({explain:translate('en','reserve.explain'), limits:Object.fromEntries(['two_hour_limit','no_eligible_time','window_limit','unknown'].map(k=>[k,translate('en',`reserve.limit.${k}`)]))});
const learningText = () => Object.fromEntries(LEARNING_KEYS.map(k=>[k,translate('en',`learning.${k}`)]));
const date = (value, zone) => {
  const ms = typeof value === 'number' ? value : Date.parse(value || '');
  if (!Number.isFinite(ms)) return U;
  try { return new Intl.DateTimeFormat('en', {dateStyle:'medium', timeStyle:'short', timeZone:zone || 'UTC'}).format(ms) + (zone ? '' : ' UTC'); } catch { return U; }
};
const part = (ms, zone, options) => {
  if (!Number.isFinite(ms)) return U;
  try { return new Intl.DateTimeFormat('en', {...options,timeZone:zone || 'UTC'}).format(ms) + (zone ? '' : ' UTC'); } catch { return U; }
};
const providerName = key => ({nordpool:'Nord Pool',entsoe:'ENTSO-E',pvpc:'PVPC',octopus:'Octopus Energy',zonneplan:'Zonneplan',relay:'Legacy relay'})[key] || (typeof key === 'string' && key ? key : 'unknown provider');
export function priceProvenance(prices, market, zone, stale = false, now = Date.now()) {
  const selected=prices?.provider?.name || (prices?.provider?.key ? providerName(prices.provider.key) : 'Unavailable');
  const area=[market?.area_name,market?.area_id].filter(Boolean).join(' · ') || 'Unknown';
  const fetched = value => {
    const ms=Date.parse(value || '');
    if (!Number.isFinite(ms) || ms>now) return 'unknown or future timestamp';
    const hours=(now-ms)/3600000;
    return `${date(value,zone)} (${hours<1 ? 'less than 1 hour ago' : `${Math.floor(hours)} hours ago`})`;
  };
  const describe = prefix => {
    const day=typeof prices?.[prefix] === 'string' ? prices[prefix] : 'unknown day';
    const state=typeof prices?.[`${prefix}_state`] === 'string' ? prices[`${prefix}_state`] : 'unknown';
    const facts=prices?.[`${prefix}_provenance`];
    if (!Array.isArray(facts) || !facts.length) return `${prefix} ${day}: ${state}; held provider unavailable; fetched ${fetched(prices?.[`${prefix}_fetched_at`])}.`;
    const names=new Set(facts.map(f=>providerName(f?.provider)));
    const detail=facts.map(f=>`${providerName(f?.provider)} (market day ${typeof f?.market_day==='string' ? f.market_day : 'unknown'}, ${typeof f?.state==='string' ? f.state : 'unknown'}, fetched ${fetched(f?.fetched_at)})`).join('; ');
    return `${prefix} ${day}: ${state}${names.size>1 ? ' · mixed providers' : ''}; ${detail}.`;
  };
  return `Current provider route: ${selected}; market/area: ${area}. ${describe('today')} ${describe('tomorrow')} ${stale ? 'Dashboard observation stale or unavailable.' : 'Provider route may differ from held files.'}`;
}

export function dashboardAdapter(raw, statusRaw, observedAt, now = Date.now(), failed = false, dashboardFailed = false) {
  const decoded = decodeDashboard(raw);
  if (!decoded.ok) return null;
  const d = decoded.value, zone = d.market?.timezone || null;
  const generated = Date.parse(d.generated_at || '');
  const freshness = observationFreshness(generated, now, dashboardFailed);
  const stale = freshness !== 'fresh';
  const staleReason = {failed:'refresh failed',invalid:'invalid or missing timestamp',future:'timestamp too far in the future',old:'observation too old'}[freshness];
  const meta=raw?.soc_observation && typeof raw.soc_observation==='object' ? raw.soc_observation : null;
  const validPercent=v=>Number.isFinite(v) && v>=0 && v<=100;
  const useRaw=(d.soc?.estimated===true || d.soc?.value==null) && validPercent(meta?.raw_value);
  const soc=useRaw ? meta.raw_value : d.soc?.value;
  const basis=useRaw ? meta?.raw_time_basis : meta?.time_basis;
  const restored=meta?.restored===true || (useRaw && meta?.raw_retained===true);
  const rawAge=useRaw && !(restored && basis==='last_updated') ? meta?.raw_age_s : d.soc?.age_s;
  const age=Number.isFinite(rawAge) && rawAge>=0 && Number.isFinite(generated) && generated<=now ? rawAge+(now-generated)/1000 : null;
  const vehicleSource=useRaw ? meta?.raw_source : d.soc?.source;
  const knownReport=basis==='vehicle_timestamp' && vehicleSource==='vehicle';
  // Unknown vehicle report time is not evidence of freshness, even if HA just wrote the state.
  const knownTime=knownReport || (vehicleSource==='charger' && basis==='last_updated');
  const socStale=stale || !knownTime || age==null || age>180 || (!useRaw && d.soc?.estimated===true) || restored;
  const elapsed=age==null ? 'age unknown' : age<60 ? `${Math.floor(age)} s ago` : age<3600 ? `${Math.floor(age/60)} min ago` : `${Math.floor(age/3600)} h ago`;
  const source=vehicleSource==='vehicle' ? 'Vehicle' : vehicleSource==='charger' ? 'Charger' : 'Source unknown';
  const integration=typeof meta?.integration==='string' && meta.integration && (useRaw || !d.soc?.estimated) ? ` · ${meta.integration}` : '';
  const estimateAge=Number.isFinite(d.soc?.age_s) && d.soc.age_s>=0 && Number.isFinite(generated) && generated<=now ? Math.floor((d.soc.age_s+(now-generated)/1000)/60) : null;
  const estimate=d.soc?.estimated && validPercent(d.soc.value) ? `SpotNav estimate: ${d.soc.value}% (derived, not a vehicle measurement; anchor ${estimateAge==null ? 'age unknown' : `${estimateAge} min old`}).` : '';
  const report=knownReport ? `Vehicle report ${elapsed}.` : vehicleSource==='vehicle' ? `Vehicle report time unavailable${basis==='last_updated' && !restored ? `; HA state updated ${elapsed}` : ''}.` : `Reading age: ${elapsed}.`;
  const socDetail=validPercent(soc) ? `${source}${integration} · ${report}${restored ? ' Restored reading; not a new vehicle report.' : ''} ${estimate}` : `SOC unavailable: no valid reading. ${estimate}`;
  const status = decodeMorekState(statusRaw);
  const health = translate('en', healthKey(status, observedAt, failed, false, now));
  const statusFresh = observationFreshness(observedAt, now, failed) === 'fresh';
  const evidence = morekEvidence(status, observedAt, failed, now);
  const ready = statusFresh ? status?.readiness : null;
  const control = ready?.control === 'available' ? 'available' : ready?.control === 'unavailable' ? 'unavailable' : 'unknown';
  const vehicleAt = Date.parse(ready?.vehicle_observed_at || '');
  const vehicleFresh = Number.isFinite(vehicleAt) && vehicleAt <= now && now-vehicleAt <= 180000;
  const vehicle = vehicleFresh && ready?.vehicle === 'connected' ? 'connected' : vehicleFresh && ready?.vehicle === 'disconnected' ? 'disconnected' : 'unknown';
  const live = liveCharging(status, observedAt, failed, now);
  const session = chargeSession(status, observedAt, failed, now);
  const readiness = `Control ${control} · vehicle ${vehicle} · ${live.measured ? `measured ${live.measured} observed` : 'measured charging unknown'} · ${session ? `${session.summary} ${session.action} Evidence: ${session.facts.join('; ')}.` : 'Charge session not applicable.'} A start request ACK is not a transaction or charging; no active transaction is not a schedule prohibition.`;
  const proposal = d.plan.proposal;
  const planStale = stale || d.planning?.historical === true || !!(proposal?.periods.length && proposal.periods.every(p=>p.endMs<=now));
  const rawProposal=raw?.plan?.proposal;
  const details=rawProposal?.window_details;
  const rawProjection=rawProposal?.projection;
  const validDetails=Array.isArray(details) && proposal && details.length===proposal.periods.length && details.every((item,i)=>
    item && Date.parse(item.start)===proposal.periods[i].startMs && Date.parse(item.end)===proposal.periods[i].endMs &&
    Number.isFinite(item.energy_kwh) && item.energy_kwh>=0 && (item.cost===null || Number.isFinite(item.cost)) &&
    (item.projected_soc===undefined || validPercent(item.projected_soc))) &&
    Number.isFinite(proposal.planned_kwh) && Math.abs(details.reduce((sum,row)=>sum+row.energy_kwh,0)-proposal.planned_kwh)<Math.max(1e-6,Math.abs(proposal.planned_kwh)*1e-8) &&
    (proposal.unpriced || !proposal.cost || (details.every(row=>Number.isFinite(row.cost)) && Math.abs(details.reduce((sum,row)=>sum+row.cost,0)-proposal.cost.value)<Math.max(1e-6,Math.abs(proposal.cost.value)*1e-8)));
  const planCurrency=proposal?.cost?.currency || d.market?.currency || null;
  const pricedBasis=rawProposal?.cost_basis==='configured_variable_cost' && !proposal?.unpriced && proposal?.cost?.currency===planCurrency && /^[A-Z]{3}$/.test(planCurrency || '');
  const projectionValid=!planStale && validPercent(rawProjection?.starting_soc) && Number.isFinite(rawProjection?.kwh_per_percent) && rawProjection.kwh_per_percent>0;
  const windows = !planStale && proposal ? proposal.periods.map((p,i)=>{
    const detail=validDetails ? details[i] : null;
    return {start:p.startMs,end:p.endMs,energy:detail?.energy_kwh,cost:pricedBasis ? detail?.cost : null,
      pricePerKwh:pricedBasis && detail?.energy_kwh>0 && Number.isFinite(detail?.cost) ? displayPrice(detail.cost/detail.energy_kwh,planCurrency) : null,
      projectedSoc:projectionValid ? detail?.projected_soc : null,
      ...reserveWindow(detail,pricedBasis)};
  }) : null;
  const nextWindow = windows?.find(w=>w.end>now) || null;
  const currency = planCurrency;
  const avg=pricedBasis && proposal?.planned_kwh>0 && Number.isFinite(proposal?.cost?.value) ? displayPrice(proposal.cost.value/proposal.planned_kwh,currency) : null;
  const computed=Date.parse(d.planning?.calculated_at || '');
  const projectionAge=Number.isFinite(rawProjection?.age_s) && rawProjection.age_s>=0 && Number.isFinite(computed) && computed<=now ? Math.floor((rawProjection.age_s+(now-computed)/1000)/60) : null;
  const ageText=projectionAge==null ? 'age unavailable' : `${projectionAge} min old`;
  const projectionTime=rawProjection?.time_basis==='vehicle_timestamp' ? `vehicle report ${ageText}` : rawProjection?.time_basis==='last_updated' ? `HA state ${ageText}${rawProjection?.source==='vehicle' ? '; vehicle report time unavailable' : ''}` : `anchor/time basis unknown, ${ageText}; vehicle report time unavailable`;
  const projectionNote=projectionValid ? `Estimated end and SOC use assumed charging power and the plan's last-known ${rawProjection?.source==='charger' ? 'charger' : rawProjection?.source==='vehicle' ? 'vehicle' : 'unknown-source'} SOC${rawProjection?.estimated ? ' estimate' : ''} (${projectionTime}), capacity/efficiency or learned energy; it may be inaccurate after driving. Actual delivered energy and the car's separate charge limit are unverified; no exact SOC or physical stop is guaranteed.` : 'SOC projection unavailable: target-SOC planning, a valid SOC and usable capacity or a trusted energy-per-percent estimate are required.';
  const progressNote=!planStale && rawProjection?.progress_unknown===true ? ' Charging progress since this reading is unknown: some measured energy could not be attributed to this car, so it is not subtracted and the planned energy may be overestimated, including energy planned above the soft price cap to reach the minimum SOC. Not measured; the car itself ends the charge at its own limit and a newer reading corrects the plan.' : '';
  const capacityNote=!planStale && rawProjection?.capacity_unknown===true ? ' Battery capacity is unknown: this is an estimate from the car\'s own learned energy per percent, not from a stated capacity. Set the battery capacity of the car (vehicle settings) so the plan can also check this figure against it.' : '';
  const projectionNoteFull=projectionNote+progressNote+capacityNote;
  const deadlineText=raw?.planning?.departure_at;
  const deadline=typeof deadlineText==='string' && /(?:Z|[+-]\d\d:\d\d)$/i.test(deadlineText) ? Date.parse(deadlineText) : NaN;
  const deadlineCurrent=!stale && !d.planning?.historical;
  const untilDeadline=d.settings?.departure_enabled===false ? 'Not enabled' : deadlineCurrent && Number.isFinite(deadline) ? (deadline>now ? `${Math.ceil((deadline-now)/60000)} min` : 'Deadline passed') : 'Unavailable';
  const policy=d.plan.price_policy?.explanations || [];
  const uncapped=!planStale && !!proposal && d.settings?.soft_price_cap===null && d.planning?.settings_revision!=null && d.planning.settings_revision===d.settings?.revision && proposal.settings_revision===d.settings.revision && policy.includes('uncapped');
  const blockNote=policy.includes('block_limit') ? ` ${translate('en','daily.policy.blockLimit')}` : '';
  const policyBase=(uncapped ? 'No soft price cap is applied to this current plan.' : policy.map(code=>{const keys={block_limit:'blockLimit',minimum_exception:'exception',minimum_shortfall:'minimumShortfall',target_shortfall:'targetShortfall',recalculating:'recalculating',unavailable:'unavailable',minimum_covered:'covered',within_cap:'within',target_met:'targetMet',error:'error'};return keys[code] ? translate('en',`daily.policy.${keys[code]}`) : U;}).join(' ') || U)+(uncapped ? blockNote : '');
  const unresolved=raw?.plan?.price_policy?.target_shortfall_kwh;
  const policyText=!planStale && raw?.plan?.price_policy?.provisional === true ? `${policyBase}${raw.plan.price_policy.tomorrow_pending===true ? ' Planned using available published prices; tomorrow’s prices are pending or unusable, so this plan may change when they arrive.' : ''} Provisional: contiguous published prices end ${date(raw.plan.price_policy.price_coverage_end,zone)}. ${Number.isFinite(unresolved) && unresolved>0 ? `${unresolved.toFixed(1)} kWh of target energy remains unresolved. ` : ''}Future prices and readiness are unknown; this is not necessarily the cheapest complete plan.` : policyBase;
  const warning = live.mismatch || status?.outcomes?.uncertain || status?.operator?.state === 'mismatch' || status?.verification?.reason === 'limits_or_transitions_differ';
  const published = publishedChart(raw, d.market, now, stale || dashboardFailed);
  const priceFreshness = priceProvenance(raw?.prices,d.market,zone,stale || dashboardFailed,now);
  return {
    draftKey: d.charger.charger_id,
    format: {currency, costBasis:pricedBasis ? 'configured variable cost, including configured additions' : null,
      detailsNote:!validDetails ? 'Window energy and costs are unavailable because reconciled planner details are missing.' : proposal?.unpriced ? 'Window costs and prices are unavailable for an unpriced plan.' : !pricedBasis ? 'Window prices and weighted average are unavailable because the cost basis or currency is unknown.' : null,
      minutesPerTimeUnit:1/60000, time: ms=>part(ms,zone,{timeStyle:'short'}), day: ms=>part(ms,zone,{dateStyle:'medium'}), ...published?.format},
    model: {
      windows, nextWindow, learning:proposal ? learningModel(rawProposal?.learning,planStale,learningText()) : null, reserve:!planStale && proposal ? reserveModel(rawProposal?.reserve,pricedBasis ? planCurrency : null,reserveText()) : null, chart:published?.chart, totals: !planStale && proposal ? {energy:proposal.planned_kwh,cost:proposal.unpriced ? null : proposal.cost?.value,pricePerKwh:avg} : null,
      vehicle: {status: stale ? 'Connection unavailable · stale dashboard' : d.charger.available ? (d.connection?.state || U) : 'Charger unavailable', detail:`Dashboard observed ${date(d.generated_at,zone)}${stale ? ` · stale: ${staleReason}` : ''}`, power:live.power,live:live.summary,liveMismatch:live.mismatch, soc:validPercent(soc) ? soc : null, stale:socStale, planStale, socDetail, socEstimated:!useRaw && d.soc?.estimated===true, policy:policyText},
      assumptions:{startingSoc:projectionValid ? rawProjection.starting_soc : null,capacityKwh:d.soc?.capacity_kwh,efficiency:d.soc?.efficiency,projectionSupported:projectionValid,projectionKwhPerPercent:rawProjection?.kwh_per_percent,projectionNote:projectionNoteFull},
      settings: {target:d.soc?.target_percent, minimum:d.settings?.minimum_ready_by_soc, cap:d.settings?.soft_price_cap, readyBy:d.settings?.departure_time},
      canSave:false, untilDeadline, targetNote:d.settings?.driver==='target_soc' && d.soc?.value!=null ? `Plan energy, projected SOC and cost are estimates based on the last-known SOC${d.soc.estimated ? ' and an energy-derived SOC estimate' : ''}; an old reading may not reflect driving since then.` : '',
      warning:warning ? {title:'Morek health requires attention',detail:`${health}${status?.outcomes?.uncertain && (status?.operator?.state === 'mismatch' || status?.verification?.reason === 'limits_or_transitions_differ') ? ' · Effective limits mismatch the sent schedule.' : ''}${live.mismatch ? ' · Reported charger state and measured flow disagree.' : ''}`} : null,
      evidence:{status:evidence.summary, context:`Morek status observed ${date(observedAt,zone)}${statusFresh ? '' : ' · stale or unavailable'}`,readiness,proposal:evidence.proposal,sent:evidence.sent,readback:evidence.readback,measurement:live.summary,dispatch:`${statusFresh && status?.reconciliation?.reason==='plan_input_provenance_unavailable' ? 'Plan input provenance unavailable: review mode, target, vehicle, SOC and capacity. The checked schedule path requires a cheapest-price target-SOC plan; switching does not guarantee Resume or charging. ' : ''}${status?.outcomes?.uncertain && status?.outcomes?.state!=='storage_unavailable' ? 'A recorded uncertain action may have applied; do not retry blindly. ' : ''}A final 0 A limit may remain. Readback is not profile inventory; ACK or readback does not prove physical charging. Preserve person Stop and household protection.`},
      labels:{settingsNote:'Read-only preview. Plan controls are unavailable in this slice.',saveLabel:'Save plan · unavailable',powerNote:live.reported ? `Charger reports “${live.reported}”${live.mismatch ? ' · mismatch with measurement' : ''}` : 'Reported state unknown; not measured power',deadlineNote:d.settings?.departure_enabled===false ? 'Ready-by is off' : deadlineCurrent && Number.isFinite(deadline) ? `Ready by ${date(deadline,zone)}; not a predicted finish` : 'Ready-by time or current plan unavailable',planLabel:'Backend policy:',chartIntro:'Published source price before configured fiscal additions; source-included charges may apply.',chartNote:`Held published intervals only. ${priceFreshness} Unpublished future and history are unavailable. Cap is omitted if its basis differs or is unknown.`,bands:'',dialogNote:'Proposal only; not necessarily sent.',footer:'Dashboard and Morek status are separate observations.'}
    }, actions:{}
  };
}
