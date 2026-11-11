// Hand-authored display scenarios; not planner results or live observations.
export const dailyStates = {
  waiting: { label:'Normal waiting', status:'Connected · waiting to charge', power:'0.0 kW', detail:'Sample reading: no power now. Waiting for the proposed window.', soc:48, warning:false, policy:'Minimum already met; the partial final stop is illustrative.' },
  charging: { label:'Charging', status:'Connected · charging', power:'6.0 kW', detail:'Sample power reading; independent of the future proposal.', soc:48, warning:false, policy:'Minimum already met; the sample observation is not inferred from the proposal.' },
  unavailable: { label:'Unavailable vehicle and price data', status:'Vehicle state unavailable', power:'Unknown', detail:'Vehicle and current insight price unavailable. Plan estimates and chart use a separate fictional price fixture, not current data.', soc:null, warning:true, policy:'SOC and current price are unknown; do not infer readiness.' },
  infeasible: { label:'Infeasible minimum SOC', status:'Connected · waiting to charge', power:'0.0 kW', detail:'Sample reading: no power now.', soc:15, lowSocWarning:20, warning:true, policy:'Sample projection falls short of the 40% minimum by 07:00; not a guarantee.' },
  partial: { label:'Partial final window', status:'Connected · waiting to charge', power:'0.0 kW', detail:'Sample reading: no power now.', soc:48, warning:false, policy:'The final window ends at 01:22:30, partway through a tariff interval.' },
  exception: { label:'Above-cap minimum exception', status:'Connected · waiting to charge', power:'0.0 kW', detail:'Sample reading: no power now.', soc:35.5, warning:false, policy:'Above cap: 15:00–15:30 is a hand-authored minimum-SOC exception, projected to reach 40%; not an optimized result.' },
  mismatch: { label:'Schedule mismatch', status:'Connected · waiting to charge', power:'0.0 kW', detail:'Sample reading: no power now; effective limits differ from the last sent schedule.', soc:48, warning:true, policy:'Minimum already met; the sample schedule mismatch needs attention.' },
  stale: { label:'Stale vehicle and evidence', status:'Vehicle data stale', power:'Unknown', detail:'No current power reading; the last sample SOC is stale.', soc:48, stale:true, warning:true, policy:'The prior proposal and readback are stale; do not rely on them for readiness.' }
};
export const chooseDailyState = key => dailyStates[key] || dailyStates.mismatch;

// Explicit fictional measurements and sent schedule, independent of the current proposal.
export const sentHistory = { start:22, end:23 };
export const readings = [{time:21.5,kw:0},{time:21.75,kw:2},{time:22,kw:6},{time:22.25,kw:6},{time:22.5,kw:null},{time:22.75,kw:6},{time:23,kw:0},{time:23.25,kw:0},{time:23.5,kw:0}];
export function historyFacts() {
  const inPlan = readings.filter(r => r.time >= sentHistory.start && r.time < sentHistory.end);
  return { known:inPlan.filter(r=>Number.isFinite(r.kw)).length, total:inPlan.length,
    outside:readings.filter(r=>Number.isFinite(r.kw) && r.kw>0 && (r.time<sentHistory.start || r.time>=sentHistory.end)) };
}
