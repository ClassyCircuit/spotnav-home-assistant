// Advanced "Market & charging costs" body (Stage 13.2). Shared by the sidebar and the local preview; it only renders
// the host's model. Opening or editing writes nothing: the host owns every request and refusal.
import { escapeText as e } from './text.js';

const opt = (value, text, selected) => `<option value="${e(value)}" ${selected ? 'selected' : ''}>${e(text)}</option>`;
const DAYS = [['all', 'Every day'], ['weekdays', 'Monday–Friday'], ['mon_sat', 'Monday–Saturday']];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

function summaryBlock(m) {
  const link = m.url ? ` <span class="mc-url">${e(m.url)}</span>` : '';
  return `<div class="mc-block" data-mc="provenance"><h3>Price provider &amp; held data</h3><p class="mc-line">${e(m.provider)}${link}</p>${m.providerNote ? `<p class="mc-note">${e(m.providerNote)}</p>` : ''}<p class="mc-line">${e(m.held)}</p><p class="mc-line">${e(m.text)}</p>${m.shared ? `<p class="mc-line">${e(m.shared)}</p>` : ''}${m.noEntryNote ? `<p class="mc-note">${e(m.noEntryNote)}</p>` : ''}</div>`;
}

function sourceBlock(m) {
  const s = m.source;
  if (!s || s.choices.length < 2) return '';
  return `<div class="mc-block" data-mc="source"><h3>Electricity price entry</h3><p class="mc-line">Using “${e(s.title)}” (${e(s.count)} charger${s.count === 1 ? '' : 's'}). Choosing another entry changes the price route for every charger on it; SpotNav never does this on its own.</p><label>Price entry <select data-msetting="entry" ${s.canEdit ? '' : 'disabled'}>${s.choices.map((c) => opt(c.value, c.text, c.value === s.base)).join('')}</select></label><wa-button id="save-price-entry" size="small" ${s.canEdit ? '' : 'disabled'}>Use this price entry</wa-button></div>`;
}

function feeRow(f) {
  if (f.included) return `<div class="mc-row" data-fee="${e(f.key)}" data-included="true"><b>${e(f.label)}</b><p class="mc-line">${e(f.hint)}</p></div>`;
  const lock = f.canEdit ? '' : 'disabled';
  return `<div class="mc-row" data-fee="${e(f.key)}"><b>${e(f.label)} <span class="mc-unit">${e(f.unit)}</span></b><label>Mode <select data-msetting="${e(f.key)}-mode" ${lock}>${f.modes.map((o) => opt(o.value, o.text, o.value === f.mode)).join('')}</select></label><label>My figure (${e(f.unit)}) <input type="number" step="any" min="0" data-msetting="${e(f.key)}-figure" value="${e(f.figure)}" ${lock}></label><p class="mc-line">${e(f.hint)}</p></div>`;
}

function marketBlock(m) {
  const a = m.area;
  const lock = a.canEdit ? '' : 'disabled';
  return `<div class="mc-block" data-mc="market"><h3>Price area, VAT, energy tax &amp; grid fee</h3><p class="mc-line">Saved area: ${e(a.savedText)}. ${e(m.currencyText)}</p><label>Price area <select data-msetting="area" ${lock}>${a.options.map((o) => opt(o.value, o.text, o.value === a.value)).join('')}</select></label>${m.fees.map(feeRow).join('')}<wa-button id="save-market" size="small" ${m.canEdit ? '' : 'disabled'}>Save area &amp; taxes</wa-button></div>`;
}

function tariffBlock(m) {
  const t = m.tariff;
  if (!t) return '';
  const lock = t.canEdit ? '' : 'disabled';
  const hl = t.high.unitKnown ? lock : 'disabled';
  const w = t.window;
  const hours = (id, from, to, v) => `<select data-msetting="${id}" ${hl}>${range(from, to).map((h) => opt(h, `${String(h % 24).padStart(2, '0')}:00`, h === v)).join('')}</select>`;
  return `<div class="mc-block" data-mc="tariff"><h3>Grid tariff</h3>${t.summary.map((x) => `<p class="mc-line">${e(x)}</p>`).join('')}${t.included ? '' : `<div class="mc-row"><b>Grid fee as % of the raw price</b><label>Mode <select data-msetting="percent-mode" ${lock}>${opt('off', 'Off — not added', t.percent.mode === 'off')}${opt('custom', 'My percentage', t.percent.mode === 'custom')}</select></label><label>Percentage (%) <input type="number" step="any" min="0" data-msetting="percent-figure" value="${e(t.percent.figure)}" ${lock}></label></div><div class="mc-row"><b>High-load grid fee <span class="mc-unit">${e(t.high.unit)}</span></b><label>Mode <select data-msetting="high-mode" ${hl}>${opt('off', 'Off — not added', t.high.mode === 'off')}${opt('custom', 'My fee inside the hours below', t.high.mode === 'custom')}</select></label><label>Fee (${e(t.high.unit)}) <input type="number" step="any" min="0" data-msetting="high-figure" value="${e(t.high.figure)}" ${hl}></label><label>Days <select data-msetting="win-days" ${hl}>${DAYS.map(([v, text]) => opt(v, text, v === w.days)).join('')}</select></label><label>From month <select data-msetting="win-from-month" ${hl}>${MONTHS.map((n, i) => opt(i + 1, n, i + 1 === w.from_month)).join('')}</select></label><label>To month (included) <select data-msetting="win-to-month" ${hl}>${MONTHS.map((n, i) => opt(i + 1, n, i + 1 === w.to_month)).join('')}</select></label><label>From hour <select data-msetting="win-from-hour" ${hl}>${range(0, 23).map((h) => opt(h, `${String(h).padStart(2, '0')}:00`, h === w.from_hour)).join('')}</select></label><label>To hour <select data-msetting="win-to-hour" ${hl}>${range(1, 24).map((h) => opt(h, `${String(h % 24).padStart(2, '0')}:00`, h === w.to_hour)).join('')}</select></label>${w.suggested ? '<p class="mc-note">No hours are stored. The hours shown are only a common suggestion and are saved only if you switch the fee on and press Save.</p>' : ''}</div>`}${t.notes.map((x) => `<p class="mc-line">${e(x)}</p>`).join('')}<wa-button id="save-tariff" size="small" ${t.canEdit ? '' : 'disabled'}>Save grid tariff</wa-button></div>`;
}

export function renderMarketCosts(m) {
  if (!m) return '';
  const notes = [m.notice, ...(m.notes || [])].filter(Boolean).map((t) => `<p class="mc-note">${e(t)}</p>`).join('');
  const reload = m.state === 'forbidden' ? '' : '<button type="button" id="reload-market-costs">Reload market &amp; costs</button>';
  if (m.state !== 'ready') return `<details id="market-costs-details"><summary>Advanced: market &amp; charging costs</summary><div class="mc-body" role="status">${notes}${summaryBlock(m)}${reload}</div></details>`;
  return `<details id="market-costs-details"><summary>Advanced: market &amp; charging costs</summary><div class="mc-body">${summaryBlock(m)}${sourceBlock(m)}${marketBlock(m)}${tariffBlock(m)}<div class="mc-block" data-mc="basis"><h3>How costs are built</h3><p class="mc-line">${e(m.basis)}</p></div><p class="mc-help">Saving only stores your choice. It may recalculate plans and cost estimates for every charger using this price entry, followed by normal guarded schedule reconciliation if Morek owns the schedule. It never changes the provider on its own, sends a notification, wakes the car or proves charging. Historical tariffs are not reconstructed or invented.</p><div role="status" id="market-costs-notice">${notes}</div>${reload}</div></details>`;
}
