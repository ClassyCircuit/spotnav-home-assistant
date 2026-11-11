import '@awesome.me/webawesome/dist/components/button/button.js';
import '@awesome.me/webawesome/dist/components/badge/badge.js';
import '@awesome.me/webawesome/dist/components/progress-bar/progress-bar.js';
import '@awesome.me/webawesome/dist/components/input/input.js';
import '@awesome.me/webawesome/dist/components/details/details.js';
import { windows, total, time, money, day, now, priceAt, cap, prices, socAssumptions, scenario, dailyScenario } from './sample.js';
import { mountCharts } from './charts.js';
import { renderPlan, number } from './plan-view.js';
import { renderInsights } from './insight-view.js';
import { dailyStates, chooseDailyState } from './daily-sample.js';
import { renderHistory } from './history-view.js';
import { renderBattery } from './vehicle-view.js';
import { renderEvidence } from './evidence-view.js';

const card = (title, eyebrow, content, cls = '') => `<section class="panel ${cls}"><header class="panel-head"><div><div class="eyebrow">${eyebrow}</div><h2>${title}</h2></div><span class="sample-tag">SAMPLE</span></header>${content}</section>`;
const metric = (label, value, note) => `<div class="metric"><div class="muted">${label}</div><strong>${value}</strong><div class="muted">${note}</div></div>`;
const sampleState = chooseDailyState(dailyScenario);
const summary = total(windows);
const low = prices.reduce((a, b) => a.cents < b.cents ? a : b);
const high = prices.reduce((a, b) => a.cents > b.cents ? a : b);
const activeMinutes = windows.reduce((sum, w) => sum + (w.end - w.start) * 60, 0);
const planDetails = renderPlan(windows, socAssumptions, Boolean(sampleState.stale));
const finalSoc = windows.at(-1)?.projectedSoc;
const targetNote = Number.isFinite(finalSoc) && finalSoc >= 0 && finalSoc <= 100 ? `Projected final SOC: ${number(finalSoc, 1, '%')}; target ${finalSoc < 80 ? 'not reached' : 'reached'} in this sample.` : 'Target feasibility is unknown because the SOC projection is unavailable.';
// Original inline geometric icon; no remote icon resolver.
const icon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="M13 2 5 13h6l-1 9 9-12h-6z" fill="currentColor"/></svg>';
const priceCard = (mode, title) => card(`Prices & plan · ${title}`, 'CHART COMPARISON', `<div class="chart-intro"><div><strong>${icon} ${mode === 'bar' ? 'A · Interval bars' : 'B · Stepped area'}</strong><p>Same fictional, unverified 15-minute sample · EUR c/kWh, illustrative variable cost including fees and taxes</p></div><div class="chart-actions"><wa-button data-zoom="${mode}" size="small" aria-label="Zoom in ${title}">Zoom +</wa-button><wa-button data-reset="${mode}" size="small" aria-label="Reset ${title} overview">Full horizon</wa-button><span>Wheel zooms · scroll outside chart</span></div></div><div class="price-context"><span>Now <b>${number(priceAt(now)?.cents, 2)} c/kWh</b></span><span>Next window starts at <b>${number(scenario === 'missing' ? null : priceAt(windows[0]?.start)?.cents, 2)} c/kWh</b></span><span>Horizon low <b>${low.cents.toFixed(2)} c/kWh</b> · ${day(low.start)} ${time(low.start)}</span><span>Horizon high <b>${high.cents.toFixed(2)} c/kWh</b> · ${day(high.start)} ${time(high.start)}</span></div><div id="price-${mode}" class="chart price-chart" role="img" aria-label="Fictional price intervals, proposed windows, soft cap, now and ready-by markers"></div><p class="legend">Illustrative sample price bands: <span class="band-green">●</span> ≤30 <span class="band-amber">●</span> &gt;30–45 <span class="band-orange">●</span> &gt;45–60 <span class="band-red">●</span> &gt;60 c/kWh <span class="shade"></span> Proposed window · dashed outline <span class="cap-key"></span> Soft cap ${cap} c/kWh <span class="now-key">│</span> Now</p><p class="subtext">Pins show complete-horizon low/high prices; pins disappear when offscreen. Illustrative sample price bands only, not universal cheap/high thresholds. Below cap is not necessarily a proposed window. The hand-authored plan is not an optimized result. Quarter-hour fluctuations are synthetic around the reference hourly values, not verified market prices. Fixed example dates: 08 Nov yesterday, 09 Nov today, 10 Nov future; no timezone/DST model.</p>${planDetails}`, `prices prices-${mode}`);
document.querySelector('#app').innerHTML = `
<div class="shell"><header class="masthead"><div><div class="brand">SPOTNAV <span>ENHANCED</span></div><h1>Charging, in focus.</h1><p>A single view of your vehicle, plan and charger.</p></div><div class="sample-banner">DESIGN PROTOTYPE · SAMPLE DATA<br><span>Offline illustration — no charger connection</span></div></header>
<div class="scenario-picker"><label for="sample-state">Sample scenario</label><select id="sample-state">${Object.entries(dailyStates).map(([key,value]) => `<option value="${key}" ${value === sampleState ? 'selected' : ''}>${value.label}</option>`).join('')}</select><span>Local illustration only · no settings or charger actions</span></div>
${sampleState.warning ? `<div class="alert" role="status"><div><strong>${dailyScenario === 'mismatch' ? 'Schedule needs attention' : 'Sample state needs attention'}</strong><p>${dailyScenario === 'mismatch' ? 'Sample effective limits differ from the last sent plan. This is not proof of charging; measured power is shown separately.' : sampleState.policy}</p></div><a href="#details">View details ↓</a></div>` : ''}
<div class="dashboard">
${card('Your vehicle', 'OVERVIEW', `<div class="status-line"><span class="dot ${sampleState.soc == null || sampleState.stale ? 'dot-unknown' : ''}"></span> ${sampleState.status}</div>${renderBattery({soc:sampleState.soc,target:80,capacityKwh:socAssumptions.capacityKwh,efficiency:socAssumptions.efficiency,stale:Boolean(sampleState.stale),lowSocWarning:sampleState.lowSocWarning,windows})}<p class="waiting">${sampleState.detail}</p><div class="metrics">${metric('Measured now',sampleState.power,'Independent sample reading')}<div class="metric next-metric"><div class="muted">${sampleState.stale ? 'Next window · stale proposal' : 'Next proposed window'}</div><button type="button" id="open-plan" aria-haspopup="dialog">${time(windows[0].start)}–${time(windows[0].end)} <span aria-hidden="true">↗</span></button><div class="muted">${day(windows[0].start)} · view complete plan</div></div>${metric(sampleState.stale ? 'Last plan cost · stale' : 'Estimated charge cost',money(summary.cost),`${number(summary.energy, 2, ' kWh', n => n >= 0)} wall energy`)}${metric('Until deadline','16h 30m','07:00 deadline, not predicted finish')}</div><div class="hint"><b>Sample plan:</b> ${sampleState.policy} ${targetNote} The projection assumptions are shown with the plan.</div>`, 'overview')}
${card('Plan controls', 'SIMULATED SETTINGS', `<p class="subtext">Illustrative inputs only. Changes do not recalculate or save a plan. Soft cap enabled: 35 c/kWh (€0.35/kWh), variable price including fees and taxes. ${scenario === 'missing' ? 'Missing-data scenario: plan pricing and efficiency are unavailable; the price chart remains the separate complete sample.' : scenario === 'long' ? 'Long-plan scenario: eight sample windows.' : scenario === 'invalid' ? 'Invalid-data scenario: plan energy, cost and efficiency are unavailable.' : ''}</p><div class="fields"><wa-input label="Target SOC (%)" value="80" type="number"></wa-input><wa-input label="Minimum SOC (%)" value="40" type="number"></wa-input><wa-input label="Soft cap (€/kWh)" value="0.35" type="number" step="0.01"></wa-input><wa-input label="Ready by" value="07:00" type="time"></wa-input></div><wa-button variant="brand" disabled>Save plan · unavailable</wa-button><div class="controls-plan">${planDetails}<button type="button" id="open-plan-details" aria-haspopup="dialog">View full window details ↗</button></div>`, 'controls')}
${card('Price insights', 'ILLUSTRATIVE PRICE DATA', renderInsights(dailyScenario === 'unavailable' || new URLSearchParams(location.search).get('insights') === 'missing'), 'insights')}
${priceCard('bar', 'Bars')}
${priceCard('step', 'Stepped area')}
${card('Plan activity & freshness', 'FICTIONAL EVIDENCE', renderEvidence(dailyScenario, sampleState.power, windows), 'morek')}
${card('Recent charging', 'FICTIONAL SENT VS MEASURED', renderHistory(), 'history')}
</div><dialog id="plan-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><div><div class="eyebrow">SAMPLE ONLY</div><h2 id="dialog-title">Proposed charging plan</h2></div><button id="close-plan" type="button" aria-label="Close proposed plan">✕</button></div><p class="subtext">Hand-authored proposal, not an optimized or sent schedule.</p>${planDetails}</dialog><footer>All data and illustrations are samples · No live data, commands or Home Assistant access · Visual design awaiting approval</footer></div>`;
document.querySelectorAll('.prices .legend').forEach(el => { for (const node of el.childNodes) if (node.nodeType === Node.TEXT_NODE) node.textContent = node.textContent.replace('Proposed window · dashed outline', 'Proposed charging · gradient + pale track'); });
document.querySelectorAll('.prices .subtext').forEach(el => el.append(' Fictional dates are in 2026; hatched gaps mean price unavailable, not zero. Historical and future coverage may be missing.'));
document.querySelector('a[href="#details"]')?.addEventListener('click', () => { document.querySelector('#details').open = true; });
document.querySelector('#sample-state').addEventListener('change', event => { const url = new URL(location.href); url.searchParams.set('state', event.target.value); location.href = url.href; });
const dialog = document.querySelector('#plan-dialog');
const openPlan = document.querySelector('#open-plan');
let trigger = openPlan;
document.querySelectorAll('#open-plan, #open-plan-details').forEach(button => button.addEventListener('click', () => { trigger = button; dialog.showModal(); document.querySelector('#close-plan').focus(); }));
document.querySelector('#close-plan').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const r = dialog.getBoundingClientRect();
  if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
});
dialog.addEventListener('close', () => trigger.focus());
mountCharts();
