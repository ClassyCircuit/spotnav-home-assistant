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
import { buildTracks } from './chart-tracks.js';
import { total, money } from './plan-data.js';
import { renderPlan, number } from './plan-view.js';
import { buildWindowsModel, resolveSelection, windowsAt, windowKey } from './windows-model.js';
import { renderWindows } from './windows-view.js';
import { renderBattery, batteryEstimates } from './vehicle-view.js';
import { renderEvidence } from './evidence-view.js';
import { renderHistory } from './history-view.js';
import { renderInsights } from './insight-view.js';
import { perspectiveModel, renderPerspective } from './price-perspective-view.js';
import { renderPriceNav } from './price-nav-view.js';
import { renderChartControls, renderPriceContext, renderChartLegend } from './chart-view.js';
import { renderVehicleSources } from './vehicle-sources-view.js';
import { renderMarketCosts } from './market-costs-view.js';
import { renderPlanParams } from './plan-params-view.js';
import { renderPlanEditor } from './plan-editor-view.js';
import { renderNotifySetup } from './notify-setup-view.js';
import { escapeText as e } from './text.js';
import { reconcile } from './reconcile.js';
import { priceText, priceUnit } from './price-format.js';
import { TABS, TAB_IDS, renderHeader, renderStatusStack, renderControls, renderArt, sceneOf, tabOpen, tabClose, renderRecentSummary } from './shell.js';

const card = (title, eyebrow, body, cls, tag) => `<section class="panel ${cls}"><header class="panel-head"><div><div class="eyebrow">${e(eyebrow)}</div><h2>${e(title)}</h2></div>${tag ? `<span class="sample-tag">${e(tag)}</span>` : ''}</header>${body}</section>`;
const metric = (label, value, note) => `<div class="metric"><div class="muted">${e(label)}</div><strong>${e(value)}</strong><div class="muted">${e(note)}</div></div>`;
const icon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="M13 2 5 13h6l-1 9 9-12h-6z" fill="currentColor"/></svg>';
const value = v => v == null || (typeof v === 'number' && !Number.isFinite(v)) ? '' : String(v);
const mounted = new WeakMap();

/** Mount one dashboard. The caller owns the model and can replace it using update(). */
export function mountDashboard(root, adapter) {
  if (!root || !adapter || !adapter.model || !adapter.format || typeof adapter.format.time !== 'function' || typeof adapter.format.day !== 'function') throw new TypeError('A root, model and explicit time/day formatters are required');
  mounted.get(root)?.dispose();
  let disposed = false, chartMount, listeners, pendingUpdate, layoutObserver;
  // 20.1: which tab is shown is local view state. All four panels stay mounted (hidden), so drafts, focus targets, dialogs, chart zoom and pending actions are untouched by a tab change.
  let activeTab = 'overview';
  const tabScroll = new Map();
  const bound = new WeakSet();
  // Only values actually edited by the user are retained across observations.
  // A host must change draftKey when the charger or canonical revision changes.
  const drafts = new Map();
  let confirmToken = null;
  // 20.5: the selected proposal window is local, read-only view state: charger + proposal identity + exact interval.
  let winSelection = null, winNotice = '', winModel = null;
  let current = adapter;
  function cleanup() {
    listeners?.abort();
    listeners = null;
    chartMount?.dispose();
    chartMount = null;
    const dialog = root.querySelector('#plan-dialog');
    if (dialog?.open) dialog.close();
    root.replaceChildren();
  }
  // Scrolling: the HA panel scrolls inside the host, the preview scrolls the window; restore whichever applies per tab.
  function scroller() {
    let n = root.parentNode;
    while (n) {
      const el = n.nodeType === 11 ? n.host : n;
      if (el?.nodeType === 1) { const o = root.ownerDocument.defaultView?.getComputedStyle?.(el)?.overflowY; if ((o === 'auto' || o === 'scroll') && el.scrollHeight > el.clientHeight) return el; }
      n = n.nodeType === 11 ? n.host : n.parentNode;
    }
    return null;
  }
  const scrollTop = () => { const el = scroller(); return el ? el.scrollTop : (root.ownerDocument.defaultView?.scrollY || 0); };
  const scrollSet = top => { const el = scroller(); if (el) el.scrollTop = top; else root.ownerDocument.defaultView?.scrollTo?.(0, top); };
  function paintTabs() {
    for (const status of root.querySelectorAll('[data-overview-status]')) status.hidden = activeTab !== 'overview' && status.dataset.urgent !== 'true';
    for (const id of TAB_IDS) {
      const button = root.querySelector('#sn-tab-' + id), panel = root.querySelector('#sn-panel-' + id), on = id === activeTab;
      if (button) { button.setAttribute('aria-selected', String(on)); button.tabIndex = on ? 0 : -1; }
      if (panel) panel.hidden = !on;
    }
  }
  /** Show one tab. Writes nothing and requests nothing from the host (it may only be told which tab is shown). */
  function showTab(name, { focus = false, restore = true } = {}) {
    if (disposed || !TAB_IDS.includes(name)) return false;
    if (name !== activeTab) {
      tabScroll.set(activeTab, scrollTop());
      activeTab = name;
      paintTabs();
      chartMount?.resize(); // charts built or refreshed while hidden have no size until their tab is shown
      if (restore) scrollSet(tabScroll.get(name) || 0);
      current.actions?.tabChange?.(name);
    }
    if (focus) root.querySelector('#sn-tab-' + name)?.focus();
    return true;
  }
  /** Make an element reachable from any tab (switching to its tab first), then scroll to it. */
  function reveal(el) {
    if (!el) return false;
    const id = el.closest?.('.tab-panel')?.dataset.tab;
    if (id) showTab(id, { restore: false });
    el.scrollIntoView?.({ block: 'start' });
    return true;
  }
  // 20.5 window selection: purely local; re-rendering repaints the highlight and never requests, replans or sends anything.
  function selectWindow(key, toggle = true) {
    const row = winModel?.rows.find(r => r.valid && r.key === key);
    if (!row) return;
    const same = winSelection?.key === key && winSelection.contextKey === winModel.contextKey;
    winSelection = toggle && same ? null : { draftKey: current.draftKey, contextKey: winModel.contextKey, key };
    winNotice = '';
    render();
    [...root.querySelectorAll('[data-win-select]')].find(b => b.dataset.winSelect === key)?.focus?.();
  }
  function clearWindow() {
    const key = winSelection?.key;
    winSelection = null; winNotice = '';
    render();
    if (key) [...root.querySelectorAll('[data-win-select]')].find(b => b.dataset.winSelect === key)?.focus?.();
  }
  function windowClick(event) {
    const hit = selector => event.target?.closest?.(selector);
    if (hit('[data-chart-windows]')) { const target = root.querySelector('[data-win-select]') || root.querySelector('.windows'); reveal(target); target?.focus?.(); return; }
    const pick = hit('[data-win-select]');
    if (pick) { selectWindow(pick.dataset.winSelect); return; }
    if (hit('#win-clear')) { clearWindow(); return; }
    const row = winSelection ? winModel?.rows.find(r => r.valid && r.key === winSelection.key) : null;
    if (hit('#win-show-chart')) { if (row) chartMount?.focusInterval(row.start, row.end); return; }
    const nav = hit('[data-win-nav]');
    // Only an already-offered, existing price-day view is requested; the selection stays and re-resolves once the chart shows that day.
    if (nav && row) current.actions?.priceNav?.(nav.dataset.winNav);
  }
  function measureLayout() {
    const width = root.getBoundingClientRect?.().width || 0;
    const layout = width > 0 && width < 760 ? 'compact' : 'wide';
    if (root.dataset.snLayout !== layout) root.dataset.snLayout = layout;
  }
  function render() {
    const { model: m, format: f, actions = {} } = current;
    const state = m.vehicle || {}, settings = m.settings || {}, labels = m.labels || {}, chart = m.chart;
    const knownPlan = Array.isArray(m.windows);
    const windows = knownPlan ? m.windows.map(w => w && typeof w === 'object' ? w : {}) : [];
    const chartWindows = windows.filter(w=>Number.isFinite(w.start) && Number.isFinite(w.end) && w.end > w.start);
    const assumptions = m.assumptions || {};
    const plan = knownPlan ? renderPlan(windows, assumptions, !!(state.planStale ?? state.stale), f, m.totals, m.reserve, m.learning) : '<p class="projection-note">Proposed plan unavailable.</p>';
    const summary = m.totals === undefined ? total(windows) : (m.totals || {}), next = m.nextWindow === undefined ? windows[0] : m.nextWindow;
    const time = x => Number.isFinite(x) ? f.time(x) : 'Unknown';
    const day = x => Number.isFinite(x) ? f.day(x) : 'Unknown';
    const sample = m.sample === true;
    const tag = sample ? 'SAMPLE' : '';
    const modes = chart?.comparison === true ? ['bar','step'] : ['step'];
    const prices = Array.isArray(chart?.prices) ? chart.prices.filter(p => Number.isFinite(p?.start) && Number.isFinite(p?.end) && p.end > p.start && Number.isFinite(p.cents)) : [];
    const unit = chart?.unit || 'c/kWh';
    const priceNumber = priceText;
    const chartReady = prices.length > 0 && Array.isArray(chart?.horizon) && chart.horizon.length === 2 && chart.horizon.every(Number.isFinite) && chart.horizon[0] < chart.horizon[1] && Number.isFinite(chart.now) && ['date','days','priceGaps','stepSegments','stepPoints','snapRange','initialRange','timeTicks'].every(key=>typeof f[key] === 'function');
    // 7.3b: four tracks on the chart's own axis; only the current proposal is a chart-time value here, everything else is already absolute.
    const tracks = chartReady ? buildTracks({horizon:chart.horizon,now:chart.now,toAxis:typeof f.toAxis==='function' ? f.toAxis : undefined,windows:knownPlan && !(state.planStale ?? state.stale) ? chartWindows : null,history:m.historyDay ?? null,effective:m.effectiveTrack ?? null}) : null;
    const readings = Array.isArray(m.history?.readings) ? m.history.readings.filter(r=>Number.isFinite(r?.time)).map(r=>({time:r.time,kw:Number.isFinite(r.kw) && r.kw >= 0 ? r.kw : null})) : [];
    const sentHistory = m.history?.sentHistory;
    const historyReady = readings.length >= 2 && readings.every((r,i)=>!i || r.time > readings[i-1].time) && Number.isFinite(sentHistory?.start) && Number.isFinite(sentHistory?.end) && sentHistory.end > sentHistory.start;
    const extremes = prices.length ? [prices.reduce((a,b)=>a.cents<b.cents?a:b), prices.reduce((a,b)=>a.cents>b.cents?a:b)] : [];
    const priceAt = h => prices.find(p=>p.start<=h && h<p.end)?.cents;
    const priceCard = mode => {
      const title = mode === 'bar' ? 'Bars' : 'Stepped area';
      const heading = modes.length > 1 ? `Electricity prices & plan · ${title}` : 'Electricity prices & charging plan';
      if (!chartReady) return card(heading, labels.chartEyebrow || 'PRICES & PLAN', `<p>Price chart unavailable.</p><p class="subtext">${e(labels.chartIntro)} ${e(labels.chartNote)}</p>`, `prices prices-${mode}`, tag);
      const extremum = p => p ? `${priceNumber(p.cents)} ${e(unit)} · ${e(day(p.start))} ${e(time(p.start))}` : 'Unknown';
      return card(heading, labels.chartEyebrow || 'PRICES & PLAN', `<div class="chart-intro"><div>${modes.length > 1 ? `<strong>${icon} ${mode === 'bar' ? 'Interval bars' : 'Stepped area'}</strong>` : ''}<p>${e(labels.chartIntro)}</p></div>${renderChartControls(mode,title)}</div>${renderPriceContext({now:priceAt(chart.now),next:m.nextPriceUnavailable ? null : priceAt(next?.start),low:extremum(extremes[0]),high:extremum(extremes[1]),unit})}${renderPriceNav(m.priceNav)}<div id="price-${mode}" class="chart price-chart" role="img" aria-label="Price intervals and proposed windows"></div><div class="track-lanes" data-track-lanes="${mode}" role="group" aria-label="Evidence tracks on the price time axis: proposal, sent, effective, measured"></div>${renderChartLegend({unit,cap:chart.cap})}<button type="button" data-chart-windows>Go to proposed windows</button><p class="subtext">${e(labels.chartNote)}</p>`, `prices prices-${mode}`, tag);
    };
    const scenario = m.scenarios;
    const option = (s) => `<option value="${e(s.value)}" ${s.value === scenario.selected ? 'selected' : ''}>${e(s.label)}</option>`;
    const capCurrency = m.capCurrency === undefined ? (f.currency === undefined ? 'EUR' : f.currency) : m.capCurrency;
    const capUnit = priceUnit(capCurrency);
    const editorView = renderPlanEditor({ m, settings, e, value, priceText, capUnit });
    const chartDraft = { duration: drafts.get('c:duration'), end: drafts.get('c:end') };
    const scene = sceneOf(m.scene);
    const planIsStale = !!(state.planStale ?? state.stale);
    // 20.5: the proposed-windows list uses the same validated windows as the chart; selection keeps proposal identity + exact interval.
    winModel = buildWindowsModel({ windows, knownPlan, stale: planIsStale, totals: m.totals, context: m.windowsContext, format: f, draftKey: current.draftKey, nav: m.priceNav, chartHorizon: chartReady ? chart.horizon : null });
    const resolved = resolveSelection(winSelection, winModel);
    if (winSelection && !resolved.selected) { winSelection = null; winNotice = resolved.notice; }
    const winSelected = resolved.selected;
    const nextWindowKey = next && Number.isFinite(next.start) && Number.isFinite(next.end) && next.end > next.start ? windowKey(next) : null;
    const windowsCard = card('Proposed charging windows', 'PLAN', renderWindows(winModel, { f, selected: winSelected, notice: winNotice, nextKey: nextWindowKey, assumptions, policy: state.policy, context: m.windowsContext, reserve: m.reserve, chartKnown: chartReady }), 'windows', tag);
    const selectedWindow = winSelected ? { start: winSelected.start, end: winSelected.end } : null;
    const pickWindow = instant => {
      const hits = windowsAt(winModel, instant);
      if (hits.length !== 1) return;
      selectWindow(hits[0].key);
    };
    const socValid = Number.isFinite(state.soc) && state.soc >= 0 && state.soc <= 100;
    const targetValid = Number.isFinite(settings.target) && settings.target >= 0 && settings.target <= 100;
    const socUnknown = !socValid || state.stale;
    const toTarget = socValid && targetValid ? batteryEstimates({soc:state.soc,target:settings.target,capacityKwh:assumptions.capacityKwh,efficiency:assumptions.efficiency}).needed : null;
    const header = renderHeader(m.header, activeTab, { selectCharger: typeof actions.selectCharger === 'function', refresh: typeof actions.refresh === 'function', menu: typeof actions.menu === 'function' });
    const hero = `<section class="panel overview hero" data-scene="${scene.connection}" data-stale="${scene.stale}"><div class="hero-stage">${renderArt(m.scene)}<div class="hero-top"><div class="hero-situation"><div class="eyebrow">OVERVIEW${sample ? ' · SAMPLE' : ''}</div><h2 class="hero-title"><span class="dot ${socUnknown ? 'dot-unknown' : ''}"></span> ${e(state.status)}</h2><p class="hero-chip" data-connection="${scene.connection}">${e(scene.label)}</p><p class="waiting">${e(state.detail)}</p></div><div class="metric next-metric hero-next"><div class="muted">${planIsStale ? 'Next window · stale proposal' : 'Next proposed window'}</div><button type="button" id="open-plan" aria-haspopup="dialog">${next ? `${e(time(next.start))}–${e(time(next.end))}` : 'Unknown'} <span aria-hidden="true">↗</span></button><div class="muted">${e(next ? day(next.start) : 'Unknown')} · view complete plan</div></div></div><div class="hero-soc${socUnknown ? ' hero-soc-unknown' : ''}" data-soc="${socValid ? (state.socEstimated ? 'estimated' : state.stale ? 'last-known' : 'reported') : 'unknown'}"><small>${socValid ? (state.socEstimated ? 'Estimated SOC · not a measurement' : state.stale ? 'Last known SOC · stale' : 'SOC') : 'SOC unknown'}</small><strong>${socValid ? `${state.soc}%` : 'Unknown'}</strong><span>Target ${targetValid ? `${settings.target}%` : 'unknown'}</span>${socValid || targetValid ? `<div class="hero-meter" role="img" aria-label="${socValid ? `${state.socEstimated ? 'Estimated' : state.stale ? 'Last known' : 'Current'} SOC ${state.soc}%` : 'SOC unknown'}; target ${targetValid ? `${settings.target}%` : 'unknown'}">${socValid ? `<span class="hero-meter-fill" style="width:${state.soc}%"></span>` : ''}${targetValid ? `<span class="hero-meter-target" style="left:${settings.target}%"></span>` : ''}</div>` : ''}</div></div><div class="hero-body">${m.control ? renderControls(m.control, chartDraft) : ''}<div class="metrics">${metric('Measured now',state.power,labels.powerNote)}${toTarget != null ? metric('To target · est.',`${number(toTarget,1,' kWh',n=>n>=0)}`,state.stale || state.socEstimated ? 'Battery energy from a last-known/estimated SOC; not measured' : 'Battery energy from the reported SOC; not measured') : ''}${metric(planIsStale ? 'Last plan cost · stale' : 'Estimated charge cost',money(summary.cost, f.currency),`${number(summary.energy,2,' kWh',n=>n>=0)} wall energy`)}${metric('Until deadline',m.untilDeadline,labels.deadlineNote)}</div><details class="hero-battery"><summary>Battery estimates &amp; assumptions</summary>${renderBattery({soc:state.soc,target:settings.target,minimum:settings.minimum,deadline:settings.readyBy,capacityKwh:assumptions.capacityKwh,efficiency:assumptions.efficiency,stale:!!state.stale,planStale:planIsStale,lowSocWarning:state.lowSocWarning,windows,sample,minutesPerTimeUnit:f.minutesPerTimeUnit,socDetail:state.socDetail,socEstimated:state.socEstimated})}</details><div class="hint"><b>${e(labels.planLabel)}</b> ${e(state.policy)} ${e(m.targetNote)}</div></div></section>`;
    const bareTab = (id, label) => `${tabOpen(id, activeTab)}<section class="panel sn-empty"><header class="panel-head"><div><div class="eyebrow">${e(label.toUpperCase())}</div><h2>${e(label)}</h2></div></header><p class="subtext">This section appears once a charger is selected and its dashboard has loaded. Nothing is changed while waiting.</p></section>${tabClose}`;
    const shellOpen = `<div class="shell" data-hold="${m.hold === true}">${header}${scenario ? `<div class="scenario-picker"><label for="sample-state">${e(scenario.label)}</label><select id="sample-state">${(scenario.options || []).map(option).join('')}</select><span>${e(scenario.note)}</span></div>` : ''}${renderStatusStack(m, activeTab)}`;
    const html = m.bare === true ? `${shellOpen}${TABS.map(([id, label]) => bareTab(id, label)).join('')}</div>` : `${shellOpen}${tabOpen('overview',activeTab)}
      ${hero}
      ${modes.map(priceCard).join('')}
      ${windowsCard}
      ${card('Recent charging · summary','OVERVIEW',renderRecentSummary(m.historyDay,m.history),'recent',tag)}
      ${tabClose}${tabOpen('explore',activeTab)}
      ${card('Price perspective','EXPLORE',renderPerspective(perspectiveModel({prices,now:chart?.now,unit}),{f:{time,day},nav:m.priceNav,horizon:chartReady ? chart.horizon : null,costBasis:f.costBasis,known:chartReady}),'perspective',tag)}
      ${card('Price insights',labels.insightEyebrow || 'PRICE DATA',renderInsights(m.insights),'insights',tag)}
      ${tabClose}${tabOpen('history',activeTab)}
      ${card('Recent charging',labels.historyEyebrow || 'HISTORY',renderHistory(m.history,historyReady,m.historyDay),'history',tag)}
      ${tabClose}${tabOpen('settings',activeTab)}
      ${card('Charging strategy & plan',labels.settingsEyebrow || 'SETTINGS',`<p class="subtext">${e(labels.settingsNote)}</p>${editorView.summary}${editorView.roleNote}${editorView.groups}${editorView.help}<p id="settings-notice" role="status">${e(m.settingsNotice || '')}</p><wa-button id="save-plan" variant="brand" ${typeof actions.save !== 'function' || m.canSave !== true ? 'disabled' : ''}>${e(labels.saveLabel || 'Save plan · unavailable')}</wa-button>${m.settingsEditor ? '<button type="button" id="reload-settings">Reload settings</button>' : ''}<div class="controls-plan">${plan}<button type="button" id="open-plan-details" aria-haspopup="dialog">View full window details ↗</button></div>`, 'controls',tag)}
      ${card('Plan activity & freshness',labels.evidenceEyebrow || 'EVIDENCE',renderEvidence(m.evidence,state.power,knownPlan ? windows.length : null),'morek',tag)}
      ${m.vehicleSources ? card('Vehicle sources & properties','ADVANCED',renderVehicleSources(m.vehicleSources),'vehicle-sources',tag) : ''}
      ${m.marketCosts ? card('Market & charging costs','ADVANCED',renderMarketCosts(m.marketCosts),'market-costs',tag) : ''}
      ${m.planParams ? card('Plan & charger parameters','ADVANCED',renderPlanParams(m.planParams),'plan-params',tag) : ''}
      ${m.notifySetup ? card('Notifications & setup check','ADVANCED',renderNotifySetup(m.notifySetup),'notify-setup',tag) : ''}
      ${tabClose}<dialog id="plan-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><div><div class="eyebrow">${e(labels.dialogEyebrow || 'PROPOSAL')}</div><h2 id="dialog-title">Proposed charging plan</h2></div><button id="close-plan" type="button" aria-label="Close proposed plan">✕</button></div><p class="subtext">${e(labels.dialogNote)}</p><div role="status" aria-live="polite">${m.warning ? `<strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p>` : ''}${m.evidence?.status ? `<p>${e(m.evidence.status)}</p>` : ''}</div>${plan}</dialog><footer>${e(labels.footer)}</footer></div>`;
    const template=document.createElement('template'); template.innerHTML=html;
    if (!root.firstChild) root.append(template.content);
    else reconcile(root.firstChild,template.content.firstChild,node=>drafts.has(node.dataset?.setting) || (node.dataset?.vsetting && drafts.has(`v:${node.dataset.vsetting}`)) || (node.dataset?.msetting && drafts.has(`m:${node.dataset.msetting}`)) || (node.dataset?.psetting && drafts.has(`p:${node.dataset.psetting}`)) || (node.dataset?.nsetting && drafts.has(`n:${node.dataset.nsetting}`)) || (node.dataset?.csetting && drafts.has(`c:${node.dataset.csetting}`)) || root.getRootNode().activeElement===node);
    listeners ||= new AbortController(); const signal = listeners.signal;
    const bind=(node,fn)=>{if(node && !bound.has(node)){bound.add(node);fn();}};
    bind(root.querySelector('.shell'), () => root.querySelector('.shell').addEventListener('click', windowClick, { signal }));
    const dialog = root.querySelector('#plan-dialog'); let trigger;
    root.querySelectorAll('#open-plan, #open-plan-details').forEach(button => bind(button,()=>button.addEventListener('click', () => { trigger = button; dialog.showModal(); root.querySelector('#close-plan').focus(); }, {signal})));
    bind(root.querySelector('#close-plan'),()=>root.querySelector('#close-plan').addEventListener('click', () => dialog.close(), {signal}));
    bind(dialog,()=>{dialog.addEventListener('click', event => { if (event.target !== dialog) return; const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }, {signal});
    dialog.addEventListener('close', () => {
      trigger?.focus();
      if (pendingUpdate) { const next = pendingUpdate; pendingUpdate = null; instance.update(next); }
    }, {signal});});
    // Price-day navigation (7.1): explicit user actions only; the host decides what to load and keeps the range on routine refreshes.
    root.querySelectorAll('[data-price-nav]').forEach(button=>bind(button,()=>button.addEventListener('click',()=>{if(button.hasAttribute('disabled'))return;current.actions?.priceNav?.(button.dataset.priceNav);},{signal})));
    root.querySelectorAll('[data-price-nav-day]').forEach(select=>bind(select,()=>select.addEventListener('change',()=>{if(select.value)current.actions?.priceNav?.('day',select.value);},{signal})));
    // History day (7.3a): explicit, read-only navigation; the host decides what to load and keeps the day on refreshes.
    root.querySelectorAll('[data-history-nav]').forEach(button=>bind(button,()=>button.addEventListener('click',()=>{if(button.hasAttribute('disabled'))return;current.actions?.historyNav?.(button.dataset.historyNav);if(button.dataset.historyNav==='prices')reveal(root.querySelector('section.prices'));},{signal})));
    root.querySelectorAll('[data-history-date]').forEach(input=>bind(input,()=>input.addEventListener('change',()=>{if(input.value)current.actions?.historyNav?.('day',input.value);},{signal})));
    // Price insights (7.5): explicit read-only choices (window length, month, comparison month, retry); nothing is saved.
    root.querySelectorAll('[data-insight-duration]').forEach(select=>bind(select,()=>select.addEventListener('change',()=>current.actions?.insightNav?.('duration',Number(select.value)),{signal})));
    root.querySelectorAll('[data-history-month]').forEach(select=>bind(select,()=>select.addEventListener('change',()=>{if(select.value)current.actions?.historyNav?.('month',select.value);},{signal})));
    root.querySelectorAll('[data-insight-month]').forEach(select=>bind(select,()=>select.addEventListener('change',()=>{if(select.value)current.actions?.insightNav?.('month',select.value);},{signal})));
    root.querySelectorAll('[data-insight-compare]').forEach(select=>bind(select,()=>select.addEventListener('change',()=>current.actions?.insightNav?.('compare',select.value),{signal})));
    root.querySelectorAll('[data-insight-compare-previous]').forEach(button=>bind(button,()=>button.addEventListener('click',()=>current.actions?.insightNav?.('compare','previous'),{signal})));
    root.querySelectorAll('[data-insight-retry]').forEach(button=>bind(button,()=>button.addEventListener('click',()=>current.actions?.insightNav?.('retry'),{signal})));
    // Four-tab navigation (20.1): click, arrow/Home/End keys (automatic activation), and in-page links to a destination.
    root.querySelectorAll('[data-sn-tab]').forEach(button=>bind(button,()=>{
      button.addEventListener('click',()=>showTab(button.dataset.snTab),{signal});
      button.addEventListener('keydown',event=>{
        const at=TAB_IDS.indexOf(button.dataset.snTab);
        const to={ArrowRight:(at+1)%TAB_IDS.length,ArrowLeft:(at+TAB_IDS.length-1)%TAB_IDS.length,Home:0,End:TAB_IDS.length-1}[event.key];
        if(to===undefined)return;event.preventDefault();showTab(TAB_IDS[to],{focus:true});
      },{signal});
    }));
    root.querySelectorAll('[data-open-tab]').forEach(button=>bind(button,()=>button.addEventListener('click',()=>showTab(button.dataset.openTab),{signal})));
    // Host header and charging controls (20.2): callbacks only; the host keeps every gate, latch and confirmation.
    const wireClick=(id,name)=>{const b=root.querySelector('#'+id);bind(b,()=>b.addEventListener('click',()=>{if(!b.disabled)current.actions?.[name]?.();},{signal}));};
    wireClick('refresh','refresh');wireClick('menu','menu');wireClick('pause-auto','pauseAuto');wireClick('resume-auto','resumeAuto');wireClick('charge-now','chargeNow');wireClick('charge-replace','chargeReplace');wireClick('charge-confirm-ok','chargeConfirm');wireClick('charge-confirm-cancel','chargeCancel');
    const confirmBox=root.querySelector('#charge-confirm');bind(confirmBox,()=>confirmBox.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();current.actions?.chargeCancel?.();}},{signal}));
    // Recovery text on any tab links to the one controller: switch to Overview and focus the first usable control (navigation only, no request).
    const gotoControls=root.querySelector('#recovery-goto-controls');bind(gotoControls,()=>gotoControls.addEventListener('click',()=>{const box=root.querySelector('#automatic-controls');if(!box)return;reveal(box);const target=['#resume-auto','#charge-now','#pause-auto'].map(id=>root.querySelector(id)).find(b=>b&&!b.disabled&&!b.hidden);(target||box).focus?.();},{signal}));
    const chargerSelect=root.querySelector('#charger');bind(chargerSelect,()=>chargerSelect.addEventListener('change',()=>current.actions?.selectCharger?.(chargerSelect.value),{signal}));
    const durationSelect=root.querySelector('#charge-duration');bind(durationSelect,()=>durationSelect.addEventListener('change',()=>{drafts.set('c:duration',durationSelect.value);const label=root.querySelector('#custom-label');if(label)label.hidden=durationSelect.value!=='custom';},{signal}));
    const endInput=root.querySelector('#charge-end');bind(endInput,()=>{const on=()=>drafts.set('c:end',endInput.value);endInput.addEventListener('input',on,{signal});endInput.addEventListener('change',on,{signal});});
    measureLayout();
    if (!layoutObserver && typeof ResizeObserver === 'function') { layoutObserver = new ResizeObserver(measureLayout); layoutObserver.observe(root); }
    const detailsLink=root.querySelector('a[href="#details"]');bind(detailsLink,()=>detailsLink.addEventListener('click', event => { event.preventDefault(); const d = root.querySelector('#details'); if (d) { reveal(d); d.open = true; } }, {signal}));
    const scenarioInput=root.querySelector('#sample-state');bind(scenarioInput,()=>scenarioInput.addEventListener('change', event => current.actions?.selectScenario?.(event.target.value), {signal}));
    const showMode=()=>{const mode=root.querySelector('[data-setting="driver"]')?.value;root.querySelectorAll('[data-mode]').forEach(el=>{el.hidden=el.dataset.mode!==mode;});};
    root.querySelectorAll('[data-setting]').forEach(input => {
      const get = () => input.type === 'checkbox' ? input.checked : input.value;
      if (drafts.has(input.dataset.setting)) { if (input.type === 'checkbox') {if(input.checked!==drafts.get(input.dataset.setting)) input.checked = drafts.get(input.dataset.setting);} else if(input.value!==drafts.get(input.dataset.setting)) input.value = drafts.get(input.dataset.setting); }
      bind(input,()=>{input.addEventListener('input', () => {drafts.set(input.dataset.setting, get()); current.actions?.edit?.();}, {signal});
      input.addEventListener('change', () => {drafts.set(input.dataset.setting, get()); showMode(); current.actions?.edit?.();}, {signal});});
    });
    showMode();
    // Vehicle sources (13.1): own drafts, own saves; never part of the plan save.
    root.querySelectorAll('[data-vsetting]').forEach(input => {
      const key = `v:${input.dataset.vsetting}`;
      if (drafts.has(key)) { if (input.value !== drafts.get(key)) input.value = drafts.get(key); }
      else if (input.tagName === 'SELECT') { const base = input.querySelector('option[selected]'); if (base && input.value !== base.value) input.value = base.value; }
      bind(input,()=>{const on=()=>{drafts.set(key,input.value);current.actions?.editVehicle?.(input.dataset.vsetting);};input.addEventListener('input',on,{signal});input.addEventListener('change',on,{signal});});
    });
    const vehiclePick=root.querySelector('[data-vselect="vehicle"]');if(vehiclePick){const chosen=vehiclePick.querySelector('option[selected]');if(chosen && vehiclePick.value!==chosen.value)vehiclePick.value=chosen.value;}bind(vehiclePick,()=>vehiclePick.addEventListener('change',()=>current.actions?.selectVehicle?.(vehiclePick.value),{signal}));
    const vget=name=>root.querySelector(`[data-vsetting="${name}"]`)?.value;
    const vsave=(id,fn)=>{const b=root.querySelector(id);bind(b,()=>b.addEventListener('click',()=>{if(current.model.vehicleSources?.canEdit===true && typeof current.actions?.[fn]==='function')current.actions[fn]({sensor:vget('sensor'),capacity:vget('capacity'),phases:vget('phases')});},{signal}));};
    vsave('#save-vehicle-sensor','saveVehicleSensor');vsave('#save-vehicle-props','saveVehicleProperties');
    const vreload=root.querySelector('#reload-vehicle-sources');bind(vreload,()=>vreload.addEventListener('click',()=>current.actions?.reloadVehicleSources?.(),{signal}));
    // Market & charging costs (13.2): own drafts, own saves; never part of the plan save. A mode select decides whether its figure applies.
    const syncMarket=()=>{for(const prefix of ['vat','tax','transfer','percent','high']){const mode=root.querySelector(`[data-msetting="${prefix}-mode"]`);if(!mode)continue;const custom=mode.value==='custom';const figure=root.querySelector(`[data-msetting="${prefix}-figure"]`);if(figure)figure.disabled=mode.disabled||!custom;if(prefix==='high')root.querySelectorAll('[data-msetting^="win-"]').forEach(n=>{n.disabled=mode.disabled||!custom;});}};
    root.querySelectorAll('[data-msetting]').forEach(input => {
      const key = `m:${input.dataset.msetting}`;
      if (drafts.has(key)) { if (input.value !== drafts.get(key)) input.value = drafts.get(key); }
      else if (input.tagName === 'SELECT') { const base = input.querySelector('option[selected]'); if (base && input.value !== base.value) input.value = base.value; }
      bind(input,()=>{const on=()=>{drafts.set(key,input.value);syncMarket();current.actions?.editCosts?.(input.dataset.msetting);};input.addEventListener('input',on,{signal});input.addEventListener('change',()=>{on();if(input.dataset.msetting==='area')current.actions?.selectMarketArea?.(input.value);},{signal});});
    });
    syncMarket();
    const mget=name=>root.querySelector(`[data-msetting="${name}"]`)?.value;
    const mvalues=()=>({area:mget('area'),entry:mget('entry'),vat:{mode:mget('vat-mode'),figure:mget('vat-figure')},tax:{mode:mget('tax-mode'),figure:mget('tax-figure')},transfer:{mode:mget('transfer-mode'),figure:mget('transfer-figure')},percent:{mode:mget('percent-mode'),figure:mget('percent-figure')},high:{mode:mget('high-mode'),figure:mget('high-figure')},window:{days:mget('win-days'),fromMonth:mget('win-from-month'),toMonth:mget('win-to-month'),fromHour:mget('win-from-hour'),toHour:mget('win-to-hour')}});
    for(const [id,fn] of [['#save-market','saveMarket'],['#save-tariff','saveTariff'],['#save-price-entry','savePriceEntry']]){const b=root.querySelector(id);bind(b,()=>b.addEventListener('click',()=>{if(current.model.marketCosts?.canEdit===true && typeof current.actions?.[fn]==='function')current.actions[fn](mvalues());},{signal}));}
    const mreload=root.querySelector('#reload-market-costs');bind(mreload,()=>mreload.addEventListener('click',()=>current.actions?.reloadMarketCosts?.(),{signal}));
    // Plan & charger parameters (13.3): own drafts, own saves; never part of the plan save. Checkboxes keep '1'/'0'.
    root.querySelectorAll('[data-psetting]').forEach(input => {
      const key = `p:${input.dataset.psetting}`, box = input.type === 'checkbox';
      if (drafts.has(key)) { if (box) { const on = drafts.get(key) === '1'; if (input.checked !== on) input.checked = on; } else if (input.value !== drafts.get(key)) input.value = drafts.get(key); }
      else if (box) { const base = input.hasAttribute('checked'); if (input.checked !== base) input.checked = base; }
      else if (input.tagName === 'SELECT') { const base = input.querySelector('option[selected]'); if (base && input.value !== base.value) input.value = base.value; }
      bind(input,()=>{const on=()=>{drafts.set(key,box ? (input.checked ? '1' : '0') : input.value);current.actions?.editParams?.();};input.addEventListener('input',on,{signal});input.addEventListener('change',on,{signal});});
    });
    const pget=name=>root.querySelector(`[data-psetting="${name}"]`)?.value;
    const pvalues=kind=>kind==='periods'?{periods:pget('periods')}:kind==='current'?{current:pget('current')}:{date:pget('date'),weekdays:[...root.querySelectorAll('[data-psetting^="wd-"]')].filter(c=>c.checked).map(c=>c.value).join('')};
    for(const [id,kind] of [['#save-periods','periods'],['#save-current','current'],['#save-departure','departure']]){const b=root.querySelector(id);bind(b,()=>b.addEventListener('click',()=>{if(current.model.planParams?.canEdit===true && typeof current.actions?.saveParams==='function')current.actions.saveParams(kind,pvalues(kind));},{signal}));}
    const preload=root.querySelector('#reload-plan-params');bind(preload,()=>preload.addEventListener('click',()=>current.actions?.reloadPlanParams?.(),{signal}));
    // Notifications & setup check (13.4): own drafts and save; the diagnostic links only open and scroll to a section.
    root.querySelectorAll('[data-nsetting]').forEach(input => {
      const key = `n:${input.dataset.nsetting}`;
      if (drafts.has(key)) { const on = drafts.get(key) === '1'; if (input.checked !== on) input.checked = on; }
      else { const base = input.hasAttribute('checked'); if (input.checked !== base) input.checked = base; }
      bind(input,()=>{const on=()=>{drafts.set(key,input.checked ? '1' : '0');current.actions?.editNotify?.();};input.addEventListener('change',on,{signal});});
    });
    const nvalues=()=>({targets:[...root.querySelectorAll('[data-nsetting^="tg-"]')].filter(c=>c.checked).map(c=>c.dataset.nsetting.slice(3)),events:[...root.querySelectorAll('[data-nsetting^="ev-"]')].filter(c=>c.checked).map(c=>c.dataset.nsetting.slice(3))});
    const nsave=root.querySelector('#save-notify');bind(nsave,()=>nsave.addEventListener('click',()=>{if(current.model.notifySetup?.canEdit===true && typeof current.actions?.saveNotify==='function')current.actions.saveNotify(nvalues());},{signal}));
    const nreload=root.querySelector('#reload-notify-setup');bind(nreload,()=>nreload.addEventListener('click',()=>current.actions?.reloadNotifySetup?.(),{signal}));
    root.querySelectorAll('[data-goto]').forEach(b=>bind(b,()=>b.addEventListener('click',()=>{const target=[...root.querySelectorAll('section.panel')].find(s=>s.classList.contains(b.dataset.goto));if(!target)return;const d=target.querySelector('details');if(d)d.open=true;reveal(target);},{signal})));
    const saveButton=root.querySelector('#save-plan');bind(saveButton,()=>saveButton.addEventListener('click', () => { if (current.model.canSave === true && typeof current.actions?.save === 'function') current.actions.save(Object.fromEntries([...root.querySelectorAll('[data-setting]')].map(input=>[input.dataset.setting,input.type === 'checkbox' ? input.checked : input.value]))); }, {signal}));
    const reloadButton=root.querySelector('#reload-settings');bind(reloadButton,()=>reloadButton.addEventListener('click', () => current.actions?.reloadSettings?.(), {signal}));
    if (chartMount && ((!chartReady && Object.keys(chartMount.priceCharts).length) || (chartReady && !Object.keys(chartMount.priceCharts).length) || (!chartReady && !historyReady))) {chartMount.dispose();chartMount=null;}
    if ((chartReady || historyReady) && !chartMount) {
      chartMount = mountCharts(root, {...chart,prices,windows:chartWindows,tracks,selectedWindow,onWindowPick:pickWindow,readings:historyReady ? readings : null,sentHistory:historyReady ? sentHistory : null,historyAxis:m.history?.axis}, f, chartReady ? modes : []);
    } else if (chartMount && chartReady) chartMount.update({...chart,prices,windows:chartWindows,tracks,selectedWindow,onWindowPick:pickWindow},f);
    return chartMount;
  }
  render();
  const instance = { update(next) {
    if (disposed) throw new Error('Dashboard disposed');
    if (!next?.model || !next.format || typeof next.format.time !== 'function' || typeof next.format.day !== 'function') throw new TypeError('Explicit model and formatters required');
    const sameDraft=current.draftKey===next.draftKey;
    const scrolls=sameDraft ? [...root.querySelectorAll('*')].filter(node=>node.scrollTop || node.scrollLeft).map(node=>[node,node.scrollTop,node.scrollLeft]) : [];
    const viewport=root.ownerDocument.defaultView, x=viewport?.scrollX, y=viewport?.scrollY;
    const rootNode=root.getRootNode?.(), focusId=!sameDraft && rootNode?.activeElement?.id && root.contains(rootNode.activeElement) ? rootNode.activeElement.id : '';
    const inConfirm=!!(rootNode?.activeElement && root.contains(rootNode.activeElement) && rootNode.activeElement.closest?.('#charge-confirm'));
    const priorOrigin=root.querySelector('#charge-confirm')?.dataset.origin || 'charge-now';
    if (!sameDraft) {drafts.clear();winSelection=null;winNotice='';cleanup();}
    pendingUpdate=null;current=next;const result=render();
    // Confirmation focus: a newly opened confirmation takes focus on Cancel; when it closes while focus was inside it, focus goes back
    // to the control that opened it (or the status line if that control is now disabled).
    const token=current.model.control?.confirm?.token ?? null;
    if (token!==null && token!==confirmToken) root.querySelector('#charge-confirm-cancel')?.focus?.();
    else if (token===null && inConfirm) {const origin=root.querySelector('#'+priorOrigin);(origin && !origin.disabled && !origin.hidden ? origin : root.querySelector('#charge-state'))?.focus?.();}
    confirmToken=token;
    if (focusId) root.querySelector('#'+focusId)?.focus?.();
    if (sameDraft) {
      for (const [node,top,left] of scrolls) if (node.isConnected) {node.scrollTop=top;node.scrollLeft=left;}
      if (viewport && (viewport.scrollX!==x || viewport.scrollY!==y)) viewport.scrollTo(x,y);
    }
    return result;
  }, resetDrafts() { for (const key of [...drafts.keys()]) if (!key.startsWith('c:')) drafts.delete(key); }, resetVehicleDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('v:')) drafts.delete(key); }, setMarketDraft(name,value) { drafts.set(`m:${name}`,value); }, resetParamDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('p:')) drafts.delete(key); }, resetNotifyDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('n:')) drafts.delete(key); }, resetMarketDrafts(keepArea=false) { for (const key of [...drafts.keys()]) if (key.startsWith('m:') && !(keepArea && key==='m:area')) drafts.delete(key); }, get charts() { return chartMount?.priceCharts || {}; }, get activeTab() { return activeTab; }, showTab(name) { return showTab(name); }, dispose() { if (!disposed) { disposed = true; layoutObserver?.disconnect(); layoutObserver = null; drafts.clear(); cleanup(); if (mounted.get(root) === instance) mounted.delete(root); } } };
  mounted.set(root, instance);
  return instance;
}
