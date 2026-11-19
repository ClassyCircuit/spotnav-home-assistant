// Advanced "Notifications & setup" body (Stage 13.4). Shared by the sidebar and the local preview; it only renders the host's
// model. Opening or editing writes nothing: the host owns every request and refusal.
import { escapeText as e } from './text.js';

const lines = (items, cls = 'ns-line') => (items || []).filter(Boolean).map((t) => `<p class="${cls}">${e(t)}</p>`).join('');
const GOTO = new Set(['vehicle-sources', 'market-costs', 'morek', 'notify-setup']);
const LEVEL = { error: 'Problem', warning: 'Check', info: 'Note' };

function diagnostics(m) {
  const items = m.diagnostics || [];
  if (!items.length) return '<div class="ns-block" data-ns="diagnostics"><h3>Setup check</h3><p class="ns-line">Nothing is reported as missing or blocked. That is not proof charging works; it only means no listed problem was reported.</p></div>';
  const li = items.map((d) => `<li data-level="${e(d.level)}" data-group="${e(d.group)}"><span class="ns-tag">${e(LEVEL[d.level] || 'Note')}</span> ${e(d.text)}${d.goto && GOTO.has(d.goto) ? ` <button type="button" class="ns-goto" data-goto="${e(d.goto)}">Open ${e(d.gotoLabel || '')}</button>` : ''}</li>`).join('');
  return `<div class="ns-block" data-ns="diagnostics"><h3>Setup check</h3><ul class="ns-list">${li}</ul></div>`;
}

function recipients(m) {
  const lock = m.canEdit ? '' : 'disabled';
  const phones = m.phones.length
    ? m.phones.map((p) => `<label class="ns-opt"><input type="checkbox" data-nsetting="tg-${e(p.service)}" ${p.checked ? 'checked' : ''} ${lock}> ${e(p.name)}</label>`).join('')
    : '<p class="ns-line">No phones available.</p>';
  const events = m.events.map((v) => `<label class="ns-opt"><input type="checkbox" data-nsetting="ev-${e(v.event)}" ${v.checked ? 'checked' : ''} ${lock}> ${e(v.label)}</label>`).join('');
  return `<div class="ns-block" data-ns="recipients"><h3>Recipients &amp; events</h3><fieldset class="ns-days" ${lock}><legend>Phones (Home Assistant mobile apps)</legend>${phones}</fieldset><fieldset class="ns-days" ${lock}><legend>Events</legend>${events}</fieldset>${lines(m.problems, 'ns-note')}<p class="ns-help">${e(m.noticeNote)}</p><wa-button id="save-notify" size="small" ${m.canEdit ? '' : 'disabled'}>Save notifications</wa-button></div>`;
}

export function renderNotifySetup(m) {
  if (!m) return '';
  const notes = [m.notice, ...(m.notes || [])].filter(Boolean).map((t) => `<p class="ns-note">${e(t)}</p>`).join('');
  const reload = '<button type="button" id="reload-notify-setup">Reload notifications &amp; setup</button>';
  const head = '<summary>Notifications &amp; setup check</summary>';
  if (m.state !== 'ready') return `<details id="notify-setup-details">${head}<div class="ns-body" role="status">${notes}${diagnostics(m)}${reload}</div></details>`;
  return `<details id="notify-setup-details">${head}<div class="ns-body"><p class="ns-help">Review setup findings and their links, then choose which notifications to receive. Notification changes are saved separately.</p><div class="ns-settings-grid">${diagnostics(m)}${recipients(m)}</div><div role="status" id="notify-setup-notice">${notes}</div>${reload}</div></details>`;
}
