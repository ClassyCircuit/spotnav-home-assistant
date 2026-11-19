// Advanced "Plan & charger parameters" body (Stage 13.3). Shared by the sidebar and the local preview; it only renders
// the host's model. Opening or editing writes nothing: the host owns every request and refusal.
import { escapeText as e } from './text.js';

const opt = (value, text, selected) => `<option value="${e(value)}" ${selected ? 'selected' : ''}>${e(text)}</option>`;
const lines = (items, cls = 'pp-line') => (items || []).filter(Boolean).map((t) => `<p class="${cls}">${e(t)}</p>`).join('');

function periodsBlock(m) {
  const p = m.periods;
  return `<div class="pp-block" data-pp="periods"><h3>Maximum charging periods</h3><p class="pp-line">Saved: ${e(p.saved)}.</p><label>Charging periods <select data-psetting="periods" ${p.canEdit ? '' : 'disabled'}>${p.options.map((o) => opt(o.value, o.text, o.value === p.value)).join('')}</select></label>${lines(p.notes)}<wa-button id="save-periods" size="small" ${p.canEdit ? '' : 'disabled'}>Save charging periods</wa-button></div>`;
}

function currentBlock(m) {
  const c = m.current;
  return `<div class="pp-block" data-pp="current"><h3>Planned current</h3><label>Planned current (A) <input type="number" inputmode="numeric" step="1" min="${e(c.min)}" max="${e(c.max)}" data-psetting="current" value="${e(c.value)}" ${c.canEdit ? '' : 'disabled'}></label><p class="pp-line">${e(c.rangeText)}</p>${c.nominal ? `<p class="pp-line">${e(c.nominal)}</p>` : ''}${lines(c.warnings, 'pp-note')}${!c.warnings.includes(c.morekNote) ? `<p class="pp-help">${e(c.morekNote)}</p>` : ''}<p class="pp-help">${e(m.currentNote)}</p><wa-button id="save-current" size="small" ${c.canEdit ? '' : 'disabled'}>Save planned current</wa-button></div>`;
}

function departureBlock(m) {
  const d = m.departure;
  const lock = d.canEdit ? '' : 'disabled';
  const days = d.weekdays.map((w) => `<label class="pp-day"><input type="checkbox" value="${e(w.n)}" data-psetting="wd-${e(w.n)}" ${w.checked ? 'checked' : ''} ${lock}> ${e(w.label)}</label>`).join('');
  const range = d.dateKnown ? ` min="${e(d.dateMin)}" max="${e(d.dateMax)}"` : '';
  return `<div class="pp-block" data-pp="departure"><h3>Departure date &amp; weekdays</h3><p class="pp-line">${e(d.next)}</p><label>Departure date (blank: daily, by weekday) <input type="date" data-psetting="date"${range} value="${e(d.date)}" ${lock}></label><fieldset class="pp-days" ${lock}><legend>Weekdays with a departure</legend>${days}</fieldset>${lines(d.notes)}<wa-button id="save-departure" size="small" ${d.canEdit ? '' : 'disabled'}>Save departure</wa-button></div>`;
}

export function renderPlanParams(m) {
  if (!m) return '';
  const notes = [m.notice, ...(m.notes || [])].filter(Boolean).map((t) => `<p class="pp-note">${e(t)}</p>`).join('');
  const reload = '<button type="button" id="reload-plan-params">Reload plan &amp; charger parameters</button>';
  if (m.state !== 'ready') return `<details id="plan-params-details"><summary>Plan &amp; charger parameters</summary><div class="pp-body" role="status">${notes}${reload}</div></details>`;
  return `<details id="plan-params-details"><summary>Plan &amp; charger parameters</summary><div class="pp-body"><p class="pp-help">Each section saves independently. Review the saved values and permissions before making changes.</p><div class="pp-settings-grid">${periodsBlock(m)}${currentBlock(m)}${departureBlock(m)}</div><p class="pp-help">${e(m.savedNote)}</p><div role="status" id="plan-params-notice">${notes}</div>${reload}</div></details>`;
}
