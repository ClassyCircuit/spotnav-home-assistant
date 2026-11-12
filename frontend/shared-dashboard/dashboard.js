// Custom element registries are global, even across shadow roots. Avoid throwing
// when another HA integration has already registered a Web Awesome component.
// Existing registrations win; their version/visual compatibility is not guaranteed.
await Promise.all([
  customElements.get('wa-button') ? null : import('@awesome.me/webawesome/dist/components/button/button.js'),
  customElements.get('wa-badge') ? null : import('@awesome.me/webawesome/dist/components/badge/badge.js'),
  customElements.get('wa-progress-bar') ? null : import('@awesome.me/webawesome/dist/components/progress-bar/progress-bar.js'),
  customElements.get('wa-input') ? null : import('@awesome.me/webawesome/dist/components/input/input.js'),
  customElements.get('wa-details') ? null : import('@awesome.me/webawesome/dist/components/details/details.js'),
]);
import { mountCharts } from './charts.js';
import { total, money } from './plan-data.js';
import { renderPlan, number } from './plan-view.js';
import { renderBattery } from './vehicle-view.js';
import { renderEvidence } from './evidence-view.js';
import { renderHistory } from './history-view.js';
import { renderInsights } from './insight-view.js';
import { escapeText as e } from './text.js';

const card = (title, eyebrow, body, cls, tag) => `<section class="panel ${cls}"><header class="panel-head"><div><div class="eyebrow">${e(eyebrow)}</div><h2>${e(title)}</h2></div>${tag ? `<span class="sample-tag">${e(tag)}</span>` : ''}</header>${body}</section>`;
const metric = (label, value, note) => `<div class="metric"><div class="muted">${e(label)}</div><strong>${e(value)}</strong><div class="muted">${e(note)}</div></div>`;
const icon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="M13 2 5 13h6l-1 9 9-12h-6z" fill="currentColor"/></svg>';
const value = v => v == null || (typeof v === 'number' && !Number.isFinite(v)) ? '' : String(v);
const mounted = new WeakMap();

/** Mount one dashboard. The caller owns the model and can replace it using update(). */
export function mountDashboard(root, adapter) {
  if (!root || !adapter || !adapter.model || !adapter.format || typeof adapter.format.time !== 'function' || typeof adapter.format.day !== 'function') throw new TypeError('A root, model and explicit time/day formatters are required');
  mounted.get(root)?.dispose();
  let disposed = false, chartMount, listeners;
  // Only values actually edited by the user are retained across observations.
  // A host must change draftKey when the charger or canonical revision changes.
  const drafts = new Map();
  let current = adapter;
  function cleanup() {
    listeners?.abort();
    chartMount?.dispose();
    chartMount = null;
    const dialog = root.querySelector('#plan-dialog');
    if (dialog?.open) dialog.close();
    root.replaceChildren();
  }
  function render() {
    const { model: m, format: f, actions = {} } = current;
    const state = m.vehicle || {}, settings = m.settings || {}, labels = m.labels || {}, chart = m.chart;
    const knownPlan = Array.isArray(m.windows);
    const windows = knownPlan ? m.windows.map(w => w && typeof w === 'object' ? w : {}) : [];
    const chartWindows = windows.filter(w=>Number.isFinite(w.start) && Number.isFinite(w.end) && w.end > w.start);
    const assumptions = m.assumptions || {};
    const plan = knownPlan ? renderPlan(windows, assumptions, !!state.stale, f, m.totals) : '<p class="projection-note">Proposed plan unavailable.</p>';
    const summary = m.totals === undefined ? total(windows) : (m.totals || {}), next = m.nextWindow === undefined ? windows[0] : m.nextWindow;
    const time = x => Number.isFinite(x) ? f.time(x) : 'Unknown';
    const day = x => Number.isFinite(x) ? f.day(x) : 'Unknown';
    const sample = m.sample === true;
    const tag = sample ? 'SAMPLE' : '';
    const modes = chart?.comparison === true ? ['bar','step'] : ['step'];
    const prices = Array.isArray(chart?.prices) ? chart.prices.filter(p => Number.isFinite(p?.start) && Number.isFinite(p?.end) && p.end > p.start && Number.isFinite(p.cents)) : [];
    const chartReady = prices.length > 0 && Array.isArray(chart?.horizon) && chart.horizon.length === 2 && chart.horizon.every(Number.isFinite) && chart.horizon[0] < chart.horizon[1] && Number.isFinite(chart.now) && Array.isArray(chart.bands) && chart.bands.length === 3 && chart.bands.every(Number.isFinite) && chart.bands[0] < chart.bands[1] && chart.bands[1] < chart.bands[2] && ['date','days','priceGaps','stepSegments','stepPoints','snapRange','initialRange','timeTicks'].every(key=>typeof f[key] === 'function');
    const readings = Array.isArray(m.history?.readings) ? m.history.readings.filter(r=>Number.isFinite(r?.time)).map(r=>({time:r.time,kw:Number.isFinite(r.kw) && r.kw >= 0 ? r.kw : null})) : [];
    const sentHistory = m.history?.sentHistory;
    const historyReady = readings.length >= 2 && readings.every((r,i)=>!i || r.time > readings[i-1].time) && Number.isFinite(sentHistory?.start) && Number.isFinite(sentHistory?.end) && sentHistory.end > sentHistory.start;
    const extremes = prices.length ? [prices.reduce((a,b)=>a.cents<b.cents?a:b), prices.reduce((a,b)=>a.cents>b.cents?a:b)] : [];
    const priceAt = h => prices.find(p=>p.start<=h && h<p.end)?.cents;
    const priceCard = mode => {
      const title = mode === 'bar' ? 'Bars' : 'Stepped area';
      if (!chartReady) return card(`Prices & plan · ${title}`, labels.chartEyebrow || 'PRICES & PLAN', `<p>Price chart unavailable.</p>${plan}`, `prices prices-${mode}`, tag);
      const extremum = p => p ? `${number(p.cents,2)} c/kWh · ${e(day(p.start))} ${e(time(p.start))}` : 'Unknown';
      return card(`Prices & plan · ${title}`, labels.chartEyebrow || 'PRICES & PLAN', `<div class="chart-intro"><div><strong>${icon} ${mode === 'bar' ? 'A · Interval bars' : (chart?.comparison ? 'B · ' : '') + 'Stepped area'}</strong><p>${e(labels.chartIntro)}</p></div><div class="chart-actions"><wa-button data-zoom="${mode}" size="small" aria-label="Zoom in ${title}" ${chartReady ? '' : 'disabled'}>Zoom +</wa-button><wa-button data-reset="${mode}" size="small" aria-label="Reset ${title} overview" ${chartReady ? '' : 'disabled'}>Full horizon</wa-button><span>Wheel zooms · scroll outside chart</span></div></div><div class="price-context"><span>Now <b>${number(priceAt(chart?.now),2)} c/kWh</b></span><span>Next window starts at <b>${number(m.nextPriceUnavailable ? null : priceAt(next?.start),2)} c/kWh</b></span><span>Horizon low <b>${extremum(extremes[0])}</b></span><span>Horizon high <b>${extremum(extremes[1])}</b></span></div>${chartReady ? `<div id="price-${mode}" class="chart price-chart" role="img" aria-label="Price intervals, proposed windows, soft cap, now and ready-by markers"></div>` : '<p>Price chart unavailable.</p>'}<p class="legend">${e(labels.bands)} ${chartReady ? `<span class="band-green">●</span> ≤${chart.bands[0]} <span class="band-amber">●</span> &gt;${chart.bands[0]}–${chart.bands[1]} <span class="band-orange">●</span> &gt;${chart.bands[1]}–${chart.bands[2]} <span class="band-red">●</span> &gt;${chart.bands[2]} c/kWh` : 'Price bands unavailable.'} <span class="shade"></span> Proposed charging · gradient + pale track <span class="cap-key"></span> Soft cap ${number(chart?.cap,0)} c/kWh <span class="now-key">│</span> Now</p><p class="subtext">${e(labels.chartNote)}</p>${plan}`, `prices prices-${mode}`, tag);
    };
    const scenario = m.scenarios;
    const option = (s) => `<option value="${e(s.value)}" ${s.value === scenario.selected ? 'selected' : ''}>${e(s.label)}</option>`;
    const capCurrency = f.currency === undefined ? 'EUR' : f.currency;
    const fields = [['Target SOC (%)','target','number'],['Minimum SOC (%)','minimum','number'],[`Soft cap (${typeof capCurrency === 'string' && /^[A-Z]{3}$/.test(capCurrency) ? capCurrency : 'currency unknown'}/kWh)`,'cap','number'],['Ready by','readyBy','time']].map(([label,key,type]) => `<wa-input data-setting="${key}" label="${e(label)}" value="${e(value(settings[key]))}" type="${type}"${key === 'cap' ? ' step="0.01"' : ''}${m.canSave === true ? '' : ' disabled'}></wa-input>`).join('');
    root.innerHTML = `<div class="shell"><header class="masthead"><div><div class="brand">SPOTNAV <span>ENHANCED</span></div><h1>Charging, in focus.</h1><p>A single view of your vehicle, plan and charger.</p></div>${labels.banner ? `<div class="sample-banner">${e(labels.banner)}<br><span>${e(labels.bannerDetail)}</span></div>` : ''}</header>
      ${scenario ? `<div class="scenario-picker"><label for="sample-state">${e(scenario.label)}</label><select id="sample-state">${(scenario.options || []).map(option).join('')}</select><span>${e(scenario.note)}</span></div>` : ''}
      ${m.warning ? `<div class="alert" role="status"><div><strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p></div><a href="#details">View details ↓</a></div>` : ''}<div class="dashboard">
      ${card('Your vehicle','OVERVIEW',`<div class="status-line"><span class="dot ${!Number.isFinite(state.soc) || state.soc < 0 || state.soc > 100 || state.stale ? 'dot-unknown' : ''}"></span> ${e(state.status)}</div>${renderBattery({soc:state.soc,target:settings.target,minimum:settings.minimum,deadline:settings.readyBy,capacityKwh:assumptions.capacityKwh,efficiency:assumptions.efficiency,stale:!!state.stale,lowSocWarning:state.lowSocWarning,windows,sample})}<p class="waiting">${e(state.detail)}</p><div class="metrics">${metric('Measured now',state.power,labels.powerNote)}<div class="metric next-metric"><div class="muted">${state.stale ? 'Next window · stale proposal' : 'Next proposed window'}</div><button type="button" id="open-plan" aria-haspopup="dialog">${next ? `${e(time(next.start))}–${e(time(next.end))}` : 'Unknown'} <span aria-hidden="true">↗</span></button><div class="muted">${e(next ? day(next.start) : 'Unknown')} · view complete plan</div></div>${metric(state.stale ? 'Last plan cost · stale' : 'Estimated charge cost',money(summary.cost, f.currency),`${number(summary.energy,2,' kWh',n=>n>=0)} wall energy`)}${metric('Until deadline',m.untilDeadline,labels.deadlineNote)}</div><div class="hint"><b>${e(labels.planLabel)}</b> ${e(state.policy)} ${e(m.targetNote)}</div>`, 'overview',tag)}
      ${card('Plan controls',labels.settingsEyebrow || 'SETTINGS',`<p class="subtext">${e(labels.settingsNote)}</p><div class="fields">${fields}</div><wa-button id="save-plan" variant="brand" ${typeof actions.save !== 'function' || m.canSave !== true ? 'disabled' : ''}>${e(labels.saveLabel || 'Save plan · unavailable')}</wa-button><div class="controls-plan">${plan}<button type="button" id="open-plan-details" aria-haspopup="dialog">View full window details ↗</button></div>`, 'controls',tag)}
      ${card('Price insights',labels.insightEyebrow || 'PRICE DATA',renderInsights(m.insights),'insights',tag)}
      ${modes.map(priceCard).join('')}
      ${card('Plan activity & freshness',labels.evidenceEyebrow || 'EVIDENCE',renderEvidence(m.evidence,state.power,knownPlan ? windows.length : null),'morek',tag)}
      ${card('Recent charging',labels.historyEyebrow || 'HISTORY',renderHistory(m.history,historyReady),'history',tag)}
      </div><dialog id="plan-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><div><div class="eyebrow">${e(labels.dialogEyebrow || 'PROPOSAL')}</div><h2 id="dialog-title">Proposed charging plan</h2></div><button id="close-plan" type="button" aria-label="Close proposed plan">✕</button></div><p class="subtext">${e(labels.dialogNote)}</p><div role="status" aria-live="polite">${m.warning ? `<strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p>` : ''}${m.evidence?.status ? `<p>${e(m.evidence.status)}</p>` : ''}</div>${plan}</dialog><footer>${e(labels.footer)}</footer></div>`;
    listeners = new AbortController(); const signal = listeners.signal;
    const dialog = root.querySelector('#plan-dialog'); let trigger;
    root.querySelectorAll('#open-plan, #open-plan-details').forEach(button => button.addEventListener('click', () => { trigger = button; dialog.showModal(); root.querySelector('#close-plan').focus(); }, {signal}));
    root.querySelector('#close-plan').addEventListener('click', () => dialog.close(), {signal});
    dialog.addEventListener('click', event => { if (event.target !== dialog) return; const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }, {signal});
    dialog.addEventListener('close', () => trigger?.focus(), {signal});
    root.querySelector('a[href="#details"]')?.addEventListener('click', event => { event.preventDefault(); root.querySelector('#details').open = true; }, {signal});
    root.querySelector('#sample-state')?.addEventListener('change', event => actions.selectScenario?.(event.target.value), {signal});
    root.querySelectorAll('[data-setting]').forEach(input => {
      if (drafts.has(input.dataset.setting)) input.value = drafts.get(input.dataset.setting);
      input.addEventListener('input', () => drafts.set(input.dataset.setting, input.value), {signal});
      input.addEventListener('change', () => drafts.set(input.dataset.setting, input.value), {signal});
    });
    root.querySelector('#save-plan').addEventListener('click', () => { if (m.canSave === true && typeof actions.save === 'function') actions.save(Object.fromEntries([...root.querySelectorAll('[data-setting]')].map(input=>[input.dataset.setting,input.value]))); }, {signal});
    if (chartReady || historyReady) {
      chartMount = mountCharts(root, {...chart,prices,windows:chartWindows,readings:historyReady ? readings : null,sentHistory:historyReady ? sentHistory : null,historyAxis:m.history?.axis}, f, chartReady ? modes : []);
    }
    return chartMount;
  }
  render();
  const instance = { update(next) {
    if (disposed) throw new Error('Dashboard disposed');
    if (!next?.model || !next.format || typeof next.format.time !== 'function' || typeof next.format.day !== 'function') throw new TypeError('Explicit model and formatters required');
    const sameDraft = current.draftKey === next.draftKey;
    if (!sameDraft) drafts.clear();
    const dialogOpen = sameDraft && root.querySelector('#plan-dialog')?.open;
    const active = root.getRootNode().activeElement;
    const focusSelector = active && root.contains(active) ? (active.id ? `#${CSS.escape(active.id)}` : active.dataset?.setting ? `[data-setting="${CSS.escape(active.dataset.setting)}"]` : null) : null;
    const scrolls = [...root.querySelectorAll('*')].filter(el => el.scrollTop || el.scrollLeft).map(el => [el.id, el.scrollTop, el.scrollLeft]).filter(([id]) => id);
    const windowScroll = [window.scrollX, window.scrollY];
    const zoom = Object.fromEntries(Object.entries(chartMount?.priceCharts || {}).map(([mode, chart]) => {
      const z = chart.getOption().dataZoom[0];
      return [mode, [z.startValue, z.endValue]];
    }));
    cleanup(); current = next; const result = render();
    for (const [mode, range] of Object.entries(zoom)) chartMount?.priceCharts[mode]?.dispatchAction({type:'dataZoom', startValue:range[0], endValue:range[1]});
    if (dialogOpen) root.querySelector('#plan-dialog')?.showModal();
    if (focusSelector && sameDraft) root.querySelector(focusSelector)?.focus({preventScroll:true});
    for (const [id, top, left] of scrolls) { const el = root.querySelector(`#${CSS.escape(id)}`); if (el) { el.scrollTop = top; el.scrollLeft = left; } }
    window.scrollTo(...windowScroll);
    return result;
  }, get charts() { return chartMount?.priceCharts || {}; }, dispose() { if (!disposed) { disposed = true; drafts.clear(); cleanup(); if (mounted.get(root) === instance) mounted.delete(root); } } };
  mounted.set(root, instance);
  return instance;
}
