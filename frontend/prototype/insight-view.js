import { now, prices, time, day, sampleDate, priceAt } from './sample.js';
import { history, monthlyRange, baselineRange, futureRange } from './insight-fixture.js';
import { assess, bestOpportunity, summarize } from './insights.js';
import { number } from './plan-view.js';

const pct = stat => stat ? `${(stat.coverage*100).toFixed(1)}%` : 'Unknown';
const price = value => number(value, 2, ' c/kWh');
const range = h => `${day(h)} · ${sampleDate(h)} ${time(h)}`;
const endTime = (start, end) => Math.floor(start/24) === Math.floor(end/24) ? time(end) : `${sampleDate(end)} ${time(end)}`;

export function renderInsights(missing = false) {
  // Missing scenario masks only insight inputs; chart remains the separate complete fixture.
  const historyInput = missing ? history.filter(p=>p.start >= -300 && p.end <= -24) : history;
  const futureInput = missing ? [] : prices;
  const current = missing ? null : priceAt(now)?.cents;
  const assessment = assess(current,historyInput,...baselineRange);
  const monthly = summarize(historyInput,...monthlyRange);
  const opportunity = bestOpportunity(futureInput,...futureRange);
  const b = assessment.baseline, m = monthly, o = opportunity.best;
  return `<div class="insights-intro">Fictional sample · EUR c/kWh · variable price including fees and taxes${missing ? ' · insight inputs masked for missing-data demonstration; chart remains unchanged' : ''}</div>
  <div class="insight-grid">
    <section class="insight-block" aria-labelledby="insight-current-title"><h3 id="insight-current-title">Current price</h3><div class="insight-value">${price(assessment.currentPrice)}</div><strong class="insight-status">${assessment.label}</strong><p>Compared with the preceding 30 days · ${pct(b)} coverage</p></section>
    <section class="insight-block" aria-labelledby="insight-upcoming-title"><h3 id="insight-upcoming-title">Lowest known 1-hour opportunity</h3>${o ? `<div class="insight-value">${price(o.average)}</div><strong>${range(o.start)}–${endTime(o.start,o.end)}</strong><p>Duration-weighted average · ${pct(opportunity.coverage)} of future horizon priced</p>` : `<div class="insight-value">Unknown</div><p>No complete 1-hour window in available future prices · ${pct(opportunity.coverage)} of future horizon priced</p>`}</section>
    <section class="insight-block" aria-labelledby="insight-month-title"><h3 id="insight-month-title">October 2026 · sample prices</h3><div class="insight-value">${price(m?.average)}</div><p>Duration-weighted average of available intervals · ${pct(m)} coverage</p><div class="month-range">Low <b>${price(m?.low)}</b> <span>·</span> High <b>${price(m?.high)}</b></div></section>
  </div><p class="insight-caution"><b>Price opportunity, not the proposed plan.</b> It may be outside the deadline or cap, is not necessarily selected or feasible, and does not guarantee charging. Monthly prices are not charging cost or savings.</p>
  <wa-details summary="How these sample insights work"><div class="details-body"><p>Baseline: ${sampleDate(baselineRange[0])} ${time(baselineRange[0])}–${sampleDate(baselineRange[1])} ${time(baselineRange[1])}, 2026; ${b?.count ?? 0} available intervals, ${b ? b.covered.toFixed(2) : 'Unknown'} of 720 hours (${pct(b)}). Classification requires at least 90% coverage and 24 intervals. Lower means below the duration-weighted 25th percentile (${price(b?.p25)}); higher means above the 75th (${price(b?.p75)}); values at or between are typical. These are relative to this fictional sample, not universal thresholds.</p><p>Opportunity: cheapest complete 1-hour average among starts at Now or known interval boundaries through ${sampleDate(futureRange[1])} ${time(futureRange[1])}. Gaps are excluded, not zero; unknown future beyond the shown horizon is not considered. October covers Oct 1 00:00–Nov 1 00:00, 2026: ${m?.count ?? 0} intervals, ${m ? m.covered.toFixed(2) : 'Unknown'} of 744 hours. Monthly low/high and average cover available intervals only. Fixed 24-hour sample days; no timezone/DST or same-weekday inference.</p></div></wa-details>`;
}
