import { number } from './plan-view.js';
import { escapeText } from './text.js';

const percent = n => Number.isFinite(n) && n >= 0 && n <= 100;
const positive = n => Number.isFinite(n) && n > 0;
const showKwh = n => number(n, 1, ' kWh', x=>x>=0);

// Illustrative energy estimates from the last-known value, never telemetry.
export function batteryEstimates({soc, target, capacityKwh, efficiency, stale = false, planStale = stale, windows = [], minutesPerTimeUnit = 60}) {
  const validSoc = percent(soc), validTarget = percent(target), validCapacity = positive(capacityKwh);
  const battery = validSoc && validCapacity ? soc/100*capacityKwh : null;
  const needed = validSoc && validTarget && validCapacity ? Math.max(0,target-soc)/100*capacityKwh : null;
  const wall = needed != null && positive(efficiency) && efficiency <= 1 ? needed/efficiency : null;
  const active = !planStale && positive(minutesPerTimeUnit) && windows.length > 0 && windows.every(w=>Number.isFinite(w.start) && Number.isFinite(w.end) && w.end>w.start)
    ? windows.reduce((n,w)=>n+(w.end-w.start)*minutesPerTimeUnit,0) : null;
  return { battery: Number.isFinite(battery) ? battery : null, needed: Number.isFinite(needed) ? needed : null,
    wall: Number.isFinite(wall) ? wall : null, active: Number.isFinite(active) ? active : null };
}

export function renderBattery({soc, target, capacityKwh, efficiency, stale = false, planStale = stale, lowSocWarning, windows, minimum, deadline, sample = false, minutesPerTimeUnit = 60, socDetail = "", socEstimated = false}) {
  const s = percent(soc) ? soc : null, t = percent(target) ? target : null;
  const low = percent(lowSocWarning) ? lowSocWarning : null;
  const values = batteryEstimates({soc,target,capacityKwh,efficiency,stale,planStale,windows,minutesPerTimeUnit});
  const socText = s == null ? 'Unknown' : `${s}%`;
  const caption = s == null ? 'SOC unavailable' : socEstimated ? 'Estimated SOC - not a measurement' : stale ? `Last ${sample ? 'sample ' : ''}SOC - stale or freshness unknown` : `${sample ? 'Sample b' : 'B'}attery SOC`;
  const activeText = values.active == null ? 'Unknown' : `${Math.round(values.active)} min`;
  return `<div class="battery-card ${stale ? 'battery-stale' : ''}"><div class="battery-title"><div><span class="battery-caption">${escapeText(caption)}</span><strong>${socText}</strong></div><div class="battery-target">Target <b>${t == null ? 'Unknown' : `${t}%`}</b><small>Minimum ${number(minimum,0,'%',percent)} · by ${escapeText(deadline)}</small></div></div>${socDetail ? `<p class="battery-note">${escapeText(socDetail)}</p>` : ''}<div class="battery-track" role="img" aria-label="${stale ? 'Stale ' : ''}SOC ${socText}; target ${t == null ? 'unknown' : `${t}%`}${low == null ? '' : `; separate low SOC warning ${low}%`}">${s == null ? '' : `<span class="battery-fill" style="width:${s}%"></span>`}${t == null ? '' : `<span class="battery-marker target-marker" style="left:${t}%"></span>`}${low == null ? '' : `<span class="battery-marker low-marker" style="left:${low}%"></span>`}</div><div class="battery-legend"><span>● ${stale ? 'Stale SOC' : 'SOC'}</span><span>│ Target${t == null ? ' unknown' : ` ${t}%`}</span>${low == null ? '' : `<span class="battery-low">┊ Low-SOC warning ${low}%${s != null && !stale && s <= low ? ' · below warning' : ''}</span>`}</div>${low == null ? '' : '<p class="battery-note">Low-SOC warning is a separate illustrative value, not the ready-by minimum or a protection floor.</p>'}<div class="battery-facts"><div><small>In usable battery · est.</small><b>${showKwh(values.battery)}</b></div><div><small>To target · battery est.</small><b>${showKwh(values.needed)}</b></div><div><small>To target · wall est.</small><b>${showKwh(values.wall)}</b></div><div><small>Plan active time · est.</small><b>${activeText}</b></div></div><p class="battery-note">Assumptions: ${number(capacityKwh,0,' kWh',positive)} usable; ${number(Number.isFinite(efficiency) ? efficiency*100 : null,0,'%',n=>n>0 && n<=100)} charging efficiency. Battery energy = wall energy × efficiency. Estimates based on last-known SOC, not measurements or a guaranteed finish. The car limit is separate.${stale ? ' Battery estimates use the last-known SOC and may be inaccurate after driving. The car limit is separate.' : ''}${!positive(capacityKwh) ? ' Configure usable battery capacity in vehicle settings.' : ''}${!positive(efficiency) || efficiency > 1 ? ' Charging efficiency is unavailable.' : ''}</p></div>`;
}
