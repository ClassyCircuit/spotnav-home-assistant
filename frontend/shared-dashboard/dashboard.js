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
import { renderVehicleSources } from './vehicle-sources-view.js';
import { renderMarketCosts } from './market-costs-view.js';
import { renderPlanParams } from './plan-params-view.js';
import { renderNotifySetup } from './notify-setup-view.js';
import { escapeText as e } from './text.js';
import { reconcile } from './reconcile.js';
import { priceText, priceUnit } from './price-format.js';
import { PRICE_BANDS, bandsApply } from './price-bands.js';

const card = (title, eyebrow, body, cls, tag) => `<section class="panel ${cls}"><header class="panel-head"><div><div class="eyebrow">${e(eyebrow)}</div><h2>${e(title)}</h2></div>${tag ? `<span class="sample-tag">${e(tag)}</span>` : ''}</header>${body}</section>`;
const metric = (label, value, note) => `<div class="metric"><div class="muted">${e(label)}</div><strong>${e(value)}</strong><div class="muted">${e(note)}</div></div>`;
const icon = '<svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="M13 2 5 13h6l-1 9 9-12h-6z" fill="currentColor"/></svg>';
const value = v => v == null || (typeof v === 'number' && !Number.isFinite(v)) ? '' : String(v);
const mounted = new WeakMap();

/** Mount one dashboard. The caller owns the model and can replace it using update(). */
export function mountDashboard(root, adapter) {
  if (!root || !adapter || !adapter.model || !adapter.format || typeof adapter.format.time !== 'function' || typeof adapter.format.day !== 'function') throw new TypeError('A root, model and explicit time/day formatters are required');
  mounted.get(root)?.dispose();
  let disposed = false, chartMount, listeners, pendingUpdate;
  const bound = new WeakSet();
  // Only values actually edited by the user are retained across observations.
  // A host must change draftKey when the charger or canonical revision changes.
  const drafts = new Map();
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
    const readings = Array.isArray(m.history?.readings) ? m.history.readings.filter(r=>Number.isFinite(r?.time)).map(r=>({time:r.time,kw:Number.isFinite(r.kw) && r.kw >= 0 ? r.kw : null})) : [];
    const sentHistory = m.history?.sentHistory;
    const historyReady = readings.length >= 2 && readings.every((r,i)=>!i || r.time > readings[i-1].time) && Number.isFinite(sentHistory?.start) && Number.isFinite(sentHistory?.end) && sentHistory.end > sentHistory.start;
    const extremes = prices.length ? [prices.reduce((a,b)=>a.cents<b.cents?a:b), prices.reduce((a,b)=>a.cents>b.cents?a:b)] : [];
    const priceAt = h => prices.find(p=>p.start<=h && h<p.end)?.cents;
    const priceCard = mode => {
      const title = mode === 'bar' ? 'Bars' : 'Stepped area';
      if (!chartReady) return card(`Prices & plan · ${title}`, labels.chartEyebrow || 'PRICES & PLAN', `<p>Price chart unavailable.</p><p class="subtext">${e(labels.chartIntro)} ${e(labels.chartNote)}</p>${plan}`, `prices prices-${mode}`, tag);
      const extremum = p => p ? `${priceNumber(p.cents)} ${e(unit)} · ${e(day(p.start))} ${e(time(p.start))}` : 'Unknown';
      return card(`Prices & plan · ${title}`, labels.chartEyebrow || 'PRICES & PLAN', `<div class="chart-intro"><div><strong>${icon} ${mode === 'bar' ? 'A · Interval bars' : (chart?.comparison ? 'B · ' : '') + 'Stepped area'}</strong><p>${e(labels.chartIntro)}</p></div><div class="chart-actions"><wa-button data-zoom="${mode}" size="small" aria-label="Zoom in ${title}">Zoom +</wa-button><wa-button data-reset="${mode}" size="small" aria-label="Reset ${title} overview">Full horizon</wa-button><span>Wheel zooms · scroll outside chart</span></div></div><div class="price-context"><span>Now <b>${priceNumber(priceAt(chart.now))} ${e(unit)}</b></span><span>Next window starts at <b>${priceNumber(m.nextPriceUnavailable ? null : priceAt(next?.start))} ${e(unit)}</b></span><span>Horizon low <b>${extremum(extremes[0])}</b></span><span>Horizon high <b>${extremum(extremes[1])}</b></span></div><div id="price-${mode}" class="chart price-chart" role="img" aria-label="Price intervals and proposed windows"></div><p class="legend">${bandsApply(unit) ? `Absolute price bands, ${e(unit)}: ${PRICE_BANDS.map(b => `<span class="${b.css}">●</span> ${b.label} ${b.range}`).join(' ')} (exactly 25 is Medium; display only, not a charging limit)` : `Neutral price color: bands are defined in euro c/kWh and no trusted conversion is available for ${e(unit)}, so nothing is classified.`} <span class="shade"></span> Proposed charging · gradient + pale track ${Number.isFinite(chart.cap) ? `<span class="cap-key"></span> Soft cap ${priceText(chart.cap)} ${e(unit)}` : ''} <span class="now-key">│</span> Now</p><p class="subtext">${e(labels.chartNote)}</p>${plan}`, `prices prices-${mode}`, tag);
    };
    const scenario = m.scenarios;
    const option = (s) => `<option value="${e(s.value)}" ${s.value === scenario.selected ? 'selected' : ''}>${e(s.label)}</option>`;
    const capCurrency = m.capCurrency === undefined ? (f.currency === undefined ? 'EUR' : f.currency) : m.capCurrency;
    const capUnit = priceUnit(capCurrency);
    const fields = [['Target SOC (%)','target','number'],['Minimum SOC (%)','minimum','number'],[`Soft cap (${capUnit})`,'cap','number'],['Ready by','readyBy','time'],['Extra time reserve (%)','reserve','number']].filter(([,key])=>key!=='reserve' || settings.reserve!==undefined).map(([label,key,type]) => `<span ${m.settingsEditor && key==='target' ? 'data-mode="target_soc"' : ''}><wa-input data-setting="${key}" label="${e(label)}" value="${e(value(settings[key]))}" type="${type}"${key === 'cap' ? ' step="any"' : ''}${key === 'reserve' ? ' step="1" min="0" max="50"' : ''}${m.canSave === true && !(m.settingsEditor && (['minimum','cap'].includes(key) && !m.policySupported)) ? '' : ' disabled'}></wa-input></span>`).join('');
    const vehicles=m.planVehicles || [], savedVehicle=settings.vehicleId || '';
    const vehicleOptions=vehicles.map(v=>`<option value="${e(v.id)}" ${v.id===savedVehicle?'selected':''}>${e(v.name || v.id)}</option>`).join('');
    const modeFields=m.settingsEditor ? `<label>Charge by <select data-setting="driver" ${m.canSave?'':'disabled'}><option value="manual_kwh" ${settings.driver==='manual_kwh'?'selected':''}>Requested energy (kWh)</option><option value="target_soc" ${settings.driver==='target_soc'?'selected':''}>Target SOC (%)</option></select></label><span data-mode="manual_kwh"><wa-input data-setting="energy" label="Requested energy (kWh)" type="number" step="any" value="${e(value(settings.energy))}" ${m.canSave?'':'disabled'}></wa-input></span><label data-mode="target_soc">Planning vehicle <select data-setting="vehicleId" ${m.canSave?'':'disabled'}><option value="" ${!savedVehicle?'selected':''}>No saved vehicle</option>${savedVehicle && !vehicles.some(v=>v.id===savedVehicle) ? `<option value="${e(savedVehicle)}" selected>Saved vehicle unavailable${savedVehicle==='guest'?' (guest)':''}</option>` : ''}${vehicleOptions}</select></label>` : '';
    const policyFields = m.settingsEditor ? `<label><input type="checkbox" data-setting="capEnabled" ${settings.capEnabled ? 'checked' : ''} ${m.canSave && m.policySupported ? '' : 'disabled'}> Enable soft cap</label><label>Cap price basis <select data-setting="capBasis" ${m.canSave && m.policySupported ? '' : 'disabled'}><option value="">Not set (suggested: Nord Pool)</option><option value="nord_pool" ${settings.capBasis === 'nord_pool' ? 'selected' : ''}>Nord Pool</option><option value="configured_variable_cost" ${settings.capBasis === 'configured_variable_cost' ? 'selected' : ''}>Configured variable cost</option></select></label><label><input type="checkbox" data-setting="deadlineEnabled" ${settings.deadlineEnabled ? 'checked' : ''} ${m.canSave ? '' : 'disabled'}> Enable ready-by</label>` : '';
    const policyHelp = m.settingsEditor ? `<div class="settings-help"><p>${m.proposedPlanDefaults ? 'Proposed defaults, not saved' : 'Saved Charge by'}: ${settings.driver==='target_soc'?'target SOC':'requested energy'}. ${m.proposedPlanDefaults ? 'Proposed target' : 'Saved target'}: ${e(settings.target == null ? 'not set — enter a target for SOC planning' : `${settings.target}%`)}. Minimum ready-by SOC: ${e(settings.minimum == null ? 'not set (optional)' : `${settings.minimum}%`)}.</p><p data-mode="target_soc">${e(m.vehicleHelp || '')}</p><p>Soft cap: ${settings.capEnabled ? `enabled, ${e(priceText(Number(settings.cap)))} ${e(capUnit)}` : 'off (no saved cap)'}. Enter a cap and choose its basis to enable it. The cap basis defines which price is compared; it does not select the price provider.</p><p>${m.proposedPlanDefaults ? 'Proposed ready-by' : 'Ready-by'}: ${settings.deadlineEnabled ? `enabled at ${e(settings.readyBy)}` : `off (saved time ${e(settings.readyBy)})`}. ${settings.reserve!==undefined ? `Extra time reserve: ${e(settings.reserve)}% of the charging time, at most 2 h. ` : ''}Changes are saved only when you choose Save plan.</p></div>` : '';
    const html = `<div class="shell"><header class="masthead"><div><div class="brand">SPOTNAV <span>ENHANCED</span></div><h1>Charging, in focus.</h1><p>A single view of your vehicle, plan and charger.</p></div>${labels.banner ? `<div class="sample-banner">${e(labels.banner)}<br><span>${e(labels.bannerDetail)}</span></div>` : ''}</header>
      ${scenario ? `<div class="scenario-picker"><label for="sample-state">${e(scenario.label)}</label><select id="sample-state">${(scenario.options || []).map(option).join('')}</select><span>${e(scenario.note)}</span></div>` : ''}
      <div id="critical-live" role="status" aria-live="polite">${m.warning ? `<div class="alert"><div><strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p></div><a href="#details">View details ↓</a></div>` : ''}</div><div class="dashboard">
      ${card('Your vehicle','OVERVIEW',`<div class="status-line"><span class="dot ${!Number.isFinite(state.soc) || state.soc < 0 || state.soc > 100 || state.stale ? 'dot-unknown' : ''}"></span> ${e(state.status)}</div>${renderBattery({soc:state.soc,target:settings.target,minimum:settings.minimum,deadline:settings.readyBy,capacityKwh:assumptions.capacityKwh,efficiency:assumptions.efficiency,stale:!!state.stale,planStale:!!(state.planStale ?? state.stale),lowSocWarning:state.lowSocWarning,windows,sample,minutesPerTimeUnit:f.minutesPerTimeUnit,socDetail:state.socDetail,socEstimated:state.socEstimated})}<p class="waiting">${e(state.detail)}</p><div class="metrics">${metric('Measured now',state.power,labels.powerNote)}<div class="metric next-metric"><div class="muted">${(state.planStale ?? state.stale) ? 'Next window · stale proposal' : 'Next proposed window'}</div><button type="button" id="open-plan" aria-haspopup="dialog">${next ? `${e(time(next.start))}–${e(time(next.end))}` : 'Unknown'} <span aria-hidden="true">↗</span></button><div class="muted">${e(next ? day(next.start) : 'Unknown')} · view complete plan</div></div>${metric((state.planStale ?? state.stale) ? 'Last plan cost · stale' : 'Estimated charge cost',money(summary.cost, f.currency),`${number(summary.energy,2,' kWh',n=>n>=0)} wall energy`)}${metric('Until deadline',m.untilDeadline,labels.deadlineNote)}</div><div class="hint"><b>${e(labels.planLabel)}</b> ${e(state.policy)} ${e(m.targetNote)}</div>`, 'overview',tag)}
      ${card('Plan controls',labels.settingsEyebrow || 'SETTINGS',`<p class="subtext">${e(labels.settingsNote)}</p><div class="fields">${modeFields}${fields}${policyFields}</div>${policyHelp}<p id="settings-notice" role="status">${e(m.settingsNotice || '')}</p><wa-button id="save-plan" variant="brand" ${typeof actions.save !== 'function' || m.canSave !== true ? 'disabled' : ''}>${e(labels.saveLabel || 'Save plan · unavailable')}</wa-button>${m.settingsEditor ? '<button type="button" id="reload-settings">Reload settings</button>' : ''}<div class="controls-plan">${plan}<button type="button" id="open-plan-details" aria-haspopup="dialog">View full window details ↗</button></div>`, 'controls',tag)}
      ${card('Price insights',labels.insightEyebrow || 'PRICE DATA',renderInsights(m.insights),'insights',tag)}
      ${modes.map(priceCard).join('')}
      ${card('Plan activity & freshness',labels.evidenceEyebrow || 'EVIDENCE',renderEvidence(m.evidence,state.power,knownPlan ? windows.length : null),'morek',tag)}
      ${card('Recent charging',labels.historyEyebrow || 'HISTORY',renderHistory(m.history,historyReady),'history',tag)}
      ${m.vehicleSources ? card('Vehicle sources & properties','ADVANCED',renderVehicleSources(m.vehicleSources),'vehicle-sources',tag) : ''}
      ${m.marketCosts ? card('Market & charging costs','ADVANCED',renderMarketCosts(m.marketCosts),'market-costs',tag) : ''}
      ${m.planParams ? card('Plan & charger parameters','ADVANCED',renderPlanParams(m.planParams),'plan-params',tag) : ''}
      ${m.notifySetup ? card('Notifications & setup check','ADVANCED',renderNotifySetup(m.notifySetup),'notify-setup',tag) : ''}
      </div><dialog id="plan-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><div><div class="eyebrow">${e(labels.dialogEyebrow || 'PROPOSAL')}</div><h2 id="dialog-title">Proposed charging plan</h2></div><button id="close-plan" type="button" aria-label="Close proposed plan">✕</button></div><p class="subtext">${e(labels.dialogNote)}</p><div role="status" aria-live="polite">${m.warning ? `<strong>${e(m.warning.title)}</strong><p>${e(m.warning.detail)}</p>` : ''}${m.evidence?.status ? `<p>${e(m.evidence.status)}</p>` : ''}</div>${plan}</dialog><footer>${e(labels.footer)}</footer></div>`;
    const template=document.createElement('template'); template.innerHTML=html;
    if (!root.firstChild) root.append(template.content);
    else reconcile(root.firstChild,template.content.firstChild,node=>drafts.has(node.dataset?.setting) || (node.dataset?.vsetting && drafts.has(`v:${node.dataset.vsetting}`)) || (node.dataset?.msetting && drafts.has(`m:${node.dataset.msetting}`)) || (node.dataset?.psetting && drafts.has(`p:${node.dataset.psetting}`)) || (node.dataset?.nsetting && drafts.has(`n:${node.dataset.nsetting}`)) || root.getRootNode().activeElement===node);
    listeners ||= new AbortController(); const signal = listeners.signal;
    const bind=(node,fn)=>{if(node && !bound.has(node)){bound.add(node);fn();}};
    const dialog = root.querySelector('#plan-dialog'); let trigger;
    root.querySelectorAll('#open-plan, #open-plan-details').forEach(button => bind(button,()=>button.addEventListener('click', () => { trigger = button; dialog.showModal(); root.querySelector('#close-plan').focus(); }, {signal})));
    bind(root.querySelector('#close-plan'),()=>root.querySelector('#close-plan').addEventListener('click', () => dialog.close(), {signal}));
    bind(dialog,()=>{dialog.addEventListener('click', event => { if (event.target !== dialog) return; const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }, {signal});
    dialog.addEventListener('close', () => {
      trigger?.focus();
      if (pendingUpdate) { const next = pendingUpdate; pendingUpdate = null; instance.update(next); }
    }, {signal});});
    const detailsLink=root.querySelector('a[href="#details"]');bind(detailsLink,()=>detailsLink.addEventListener('click', event => { event.preventDefault(); root.querySelector('#details').open = true; }, {signal}));
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
    root.querySelectorAll('[data-goto]').forEach(b=>bind(b,()=>b.addEventListener('click',()=>{const target=[...root.querySelectorAll('section.panel')].find(s=>s.classList.contains(b.dataset.goto));if(!target)return;const d=target.querySelector('details');if(d)d.open=true;target.scrollIntoView?.({block:'start'});},{signal})));
    const saveButton=root.querySelector('#save-plan');bind(saveButton,()=>saveButton.addEventListener('click', () => { if (current.model.canSave === true && typeof current.actions?.save === 'function') current.actions.save(Object.fromEntries([...root.querySelectorAll('[data-setting]')].map(input=>[input.dataset.setting,input.type === 'checkbox' ? input.checked : input.value]))); }, {signal}));
    const reloadButton=root.querySelector('#reload-settings');bind(reloadButton,()=>reloadButton.addEventListener('click', () => current.actions?.reloadSettings?.(), {signal}));
    if (chartMount && ((!chartReady && Object.keys(chartMount.priceCharts).length) || (chartReady && !Object.keys(chartMount.priceCharts).length) || (!chartReady && !historyReady))) {chartMount.dispose();chartMount=null;}
    if ((chartReady || historyReady) && !chartMount) {
      chartMount = mountCharts(root, {...chart,prices,windows:chartWindows,readings:historyReady ? readings : null,sentHistory:historyReady ? sentHistory : null,historyAxis:m.history?.axis}, f, chartReady ? modes : []);
    } else if (chartMount && chartReady) chartMount.update({...chart,prices,windows:chartWindows},f);
    return chartMount;
  }
  render();
  const instance = { update(next) {
    if (disposed) throw new Error('Dashboard disposed');
    if (!next?.model || !next.format || typeof next.format.time !== 'function' || typeof next.format.day !== 'function') throw new TypeError('Explicit model and formatters required');
    const sameDraft=current.draftKey===next.draftKey;
    const scrolls=sameDraft ? [...root.querySelectorAll('*')].filter(node=>node.scrollTop || node.scrollLeft).map(node=>[node,node.scrollTop,node.scrollLeft]) : [];
    const viewport=root.ownerDocument.defaultView, x=viewport?.scrollX, y=viewport?.scrollY;
    if (!sameDraft) {drafts.clear();cleanup();}
    pendingUpdate=null;current=next;const result=render();
    if (sameDraft) {
      for (const [node,top,left] of scrolls) if (node.isConnected) {node.scrollTop=top;node.scrollLeft=left;}
      if (viewport && (viewport.scrollX!==x || viewport.scrollY!==y)) viewport.scrollTo(x,y);
    }
    return result;
  }, resetDrafts() { drafts.clear(); }, resetVehicleDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('v:')) drafts.delete(key); }, setMarketDraft(name,value) { drafts.set(`m:${name}`,value); }, resetParamDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('p:')) drafts.delete(key); }, resetNotifyDrafts() { for (const key of [...drafts.keys()]) if (key.startsWith('n:')) drafts.delete(key); }, resetMarketDrafts(keepArea=false) { for (const key of [...drafts.keys()]) if (key.startsWith('m:') && !(keepArea && key==='m:area')) drafts.delete(key); }, get charts() { return chartMount?.priceCharts || {}; }, dispose() { if (!disposed) { disposed = true; drafts.clear(); cleanup(); if (mounted.get(root) === instance) mounted.delete(root); } } };
  mounted.set(root, instance);
  return instance;
}
