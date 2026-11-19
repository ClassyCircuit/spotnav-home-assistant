// Advanced "Vehicle sources & properties" body (Stage 13.1). Shared by the sidebar and the local preview; it only
// renders the host's model. Opening or editing writes nothing: the host owns every request and refusal.
import { escapeText as e } from './text.js';

const opt = (value, text, selected) => `<option value="${e(value)}" ${selected ? 'selected' : ''}>${e(text)}</option>`;

export function renderVehicleSources(m) {
  if (!m) return '';
  const notes = [m.notice, ...(m.notes || [])].filter(Boolean).map((t) => `<p class="vs-note">${e(t)}</p>`).join('');
  const reload = m.state === 'forbidden' ? '' : '<button type="button" id="reload-vehicle-sources">Reload vehicle sources</button>';
  if (m.state !== 'ready') return `<details id="vehicle-sources-details"><summary>Vehicle sources &amp; properties <span class="settings-summary-hint">Sensor, battery and onboard charger</span></summary><div class="vs-body" role="status">${notes}${reload}</div></details>`;
  const edit = m.canEdit ? '' : 'disabled';
  const picker = m.vehicles.length > 1 || !m.vehicleId
    ? `<label>Vehicle <select data-vselect="vehicle" ${m.busy ? 'disabled' : ''}>${m.vehicleId ? '' : opt('', 'Choose a vehicle…', true)}${m.vehicles.map((v) => opt(v.id, v.name || v.id, v.id === m.vehicleId)).join('')}</select></label>`
    : `<p class="vs-line"><b>Vehicle</b> ${e(m.vehicles[0].name || m.vehicles[0].id)}</p>`;
  let sensor = '', props = '';
  if (m.sensor) {
    const s = m.sensor;
    sensor = `<div class="vs-block" data-vs="sensor" data-level="${e(s.level)}" data-status="${e(s.status)}"><h3>Charge-level sensor</h3><p class="vs-line">${e(s.text)}</p><p class="vs-line"><b>Current reading</b> ${e(m.reading.text)}</p><label>Sensor <select data-vsetting="sensor" ${s.canEdit ? '' : 'disabled'}>${s.options.map((o) => opt(o.value, o.text, o.value === s.base)).join('')}</select></label><wa-button id="save-vehicle-sensor" size="small" ${s.canEdit ? '' : 'disabled'}>Save sensor</wa-button></div>`;
  }
  if (m.properties) {
    const p = m.properties, c = p.capacity, ph = p.phases;
    props = `<div class="vs-block" data-vs="properties"><h3>Planning properties</h3><p class="vs-line"><b>Usable battery capacity</b> ${e(c.display)}</p><label>Capacity override (kWh) <input type="number" step="any" min="1" max="500" data-vsetting="capacity" value="${e(c.base)}" placeholder="${c.editable ? 'enter usable kWh' : ''}" ${c.editable ? '' : 'disabled'}></label><p class="vs-line"><b>Onboard charger</b> ${e(ph.display)}</p>${ph.suggestion ? `<p class="vs-note">${e(ph.suggestion)}</p>` : ''}<label>Onboard phases <select data-vsetting="phases" ${ph.editable ? '' : 'disabled'}>${opt('3', '3-phase', ph.base === '3')}${opt('1', '1-phase', ph.base === '1')}</select></label><wa-button id="save-vehicle-props" size="small" ${c.editable || ph.editable ? '' : 'disabled'}>Save capacity &amp; phases</wa-button></div>`;
  } else if (m.sensor) {
    props = '<div class="vs-block" data-vs="properties"><h3>Planning properties</h3><p class="vs-line">Capacity and onboard phases could not be read for this car. Reload vehicle sources; an older backend does not report them.</p></div>';
  }
  return `<details id="vehicle-sources-details"><summary>Vehicle sources &amp; properties <span class="settings-summary-hint">Sensor, battery and onboard charger</span></summary><div class="vs-body"><p class="settings-intro">Choose the vehicle data used for charging plans. Each section is saved separately.</p><div class="settings-context"><span class="settings-eyebrow">Selected vehicle</span>${picker}<div class="settings-facts"><div><span>Charge level</span><strong>${e(m.reading?.text || "Unavailable")}</strong></div><div><span>Battery</span><strong>${e(m.properties?.capacity.display || "Unavailable")}</strong></div><div><span>Onboard charger</span><strong>${e(m.properties?.phases.display || "Unavailable")}</strong></div></div></div><div class="settings-editor-grid">${sensor}${props}</div><p class="vs-help">Saving only stores your choice and may recalculate plans for this car, followed by normal guarded schedule reconciliation if Morek owns the schedule. It never wakes the car, sends a notification or proves charging. A saved sensor is never replaced by detection.</p><div role="status" id="vehicle-sources-notice">${notes}</div>${reload}</div></details>`;
}
