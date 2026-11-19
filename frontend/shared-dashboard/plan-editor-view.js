// Strategy summary and plan editor markup (20.6). Presentation only: every control keeps its `data-setting` hook, the
// shared dashboard owns drafts, and the host (panel.js) owns validation, role checks, revision compare-and-set,
// conflict and reload. Nothing here sends, saves or computes anything; the summary restates the saved record (or the
// proposed, unsaved defaults) and never the unsaved draft in the form.

// Fields an administrator alone may change (backend NON_ADMIN_FIELDS leaves them out). A non-admin who is allowed to
// change the plan sees them read-only; the host also refuses to send them (panel.js savePlan).
export const ADMIN_ONLY_FIELDS = Object.freeze(['minimum', 'cap', 'capEnabled', 'capBasis', 'reserve']);

export function renderPlanEditor({ m, settings, e, value, priceText, capUnit }) {
  const editor = m.settingsEditor === true;
  const canSave = m.canSave === true;
  const admin = m.planAdmin !== false;
  const policyOk = !editor || !!m.policySupported;
  // One disabled rule per field: the plan-wide gate, the price-policy support gate (cap/minimum) and the administrator gate.
  const locked = key => !canSave || (!policyOk && ['minimum', 'cap', 'capEnabled', 'capBasis'].includes(key)) || (!admin && ADMIN_ONLY_FIELDS.includes(key));
  const dis = key => locked(key) ? ' disabled' : '';
  const adminNote = key => !admin && ADMIN_ONLY_FIELDS.includes(key) ? '<small class="plan-admin-only">Administrator only</small>' : '';
  const vehicles = m.planVehicles || [], savedVehicle = settings.vehicleId || '';
  const vehicleOptions = vehicles.map(v => `<option value="${e(v.id)}" ${v.id === savedVehicle ? 'selected' : ''}>${e(v.name || v.id)}</option>`).join('');
  const vehicleName = savedVehicle ? (vehicles.find(v => v.id === savedVehicle)?.name || (savedVehicle === 'guest' ? 'Guest' : vehicles.find(v => v.id === savedVehicle)?.id) || 'Saved vehicle unavailable') : 'Not selected';
  const soc = settings.driver === 'target_soc';
  const input = (label, key, type, extra = '') => `<span ${editor && key === 'target' ? 'data-mode="target_soc"' : ''}><wa-input data-setting="${key}" label="${e(label)}" value="${e(value(settings[key]))}" type="${type}"${extra}${dis(key)}></wa-input>${adminNote(key)}</span>`;
  const plainFields = [['Target SOC (%)', 'target', 'number', ''], ['Minimum SOC (%)', 'minimum', 'number', ''], [`Soft cap (${capUnit})`, 'cap', 'number', ' step="any"'], ['Ready by', 'readyBy', 'time', ''], ['Extra time reserve (%)', 'reserve', 'number', ' step="1" min="0" max="50"']]
    .filter(([, key]) => key !== 'reserve' || settings.reserve !== undefined);
  const field = key => plainFields.find(f => f[1] === key);
  const one = key => field(key) ? input(...field(key)) : '';
  const group = (id, title, hint, body) => `<fieldset class="plan-group" data-group="${id}"><legend>${title}</legend><p class="plan-group-hint">${hint}</p><div class="fields">${body}</div></fieldset>`;

  const goalBody = editor
    ? `<label>Charge by <select data-setting="driver"${canSave ? '' : ' disabled'}><option value="manual_kwh" ${settings.driver === 'manual_kwh' ? 'selected' : ''}>Requested energy (kWh)</option><option value="target_soc" ${settings.driver === 'target_soc' ? 'selected' : ''}>Target SOC (%)</option></select></label><span data-mode="manual_kwh"><wa-input data-setting="energy" label="Requested energy (kWh)" type="number" step="any" value="${e(value(settings.energy))}"${canSave ? '' : ' disabled'}></wa-input></span><label data-mode="target_soc">Planning vehicle <select data-setting="vehicleId"${canSave ? '' : ' disabled'}><option value="" ${!savedVehicle ? 'selected' : ''}>No saved vehicle</option>${savedVehicle && !vehicles.some(v => v.id === savedVehicle) ? `<option value="${e(savedVehicle)}" selected>Saved vehicle unavailable${savedVehicle === 'guest' ? ' (guest)' : ''}</option>` : ''}${vehicleOptions}</select></label>${one('target')}${one('minimum')}`
    : `${one('target')}${one('minimum')}`;
  const capBody = editor
    ? `<label><input type="checkbox" data-setting="capEnabled" ${settings.capEnabled ? 'checked' : ''}${dis('capEnabled')}> Enable soft cap ${adminNote('capEnabled')}</label>${one('cap')}<label>Cap price basis <select data-setting="capBasis"${dis('capBasis')}><option value="">Not set (suggested: Nord Pool)</option><option value="nord_pool" ${settings.capBasis === 'nord_pool' ? 'selected' : ''}>Nord Pool</option><option value="configured_variable_cost" ${settings.capBasis === 'configured_variable_cost' ? 'selected' : ''}>Configured variable cost</option></select>${adminNote('capBasis')}</label>`
    : one('cap');
  const timeBody = editor
    ? `<label><input type="checkbox" data-setting="deadlineEnabled" ${settings.deadlineEnabled ? 'checked' : ''}${canSave ? '' : ' disabled'}> Enable ready-by</label>${one('readyBy')}${one('reserve')}`
    : `${one('readyBy')}${one('reserve')}`;
  const groups = group('goal', 'Charge goal', 'What to charge to, and for which vehicle. The planning target is separate from the car’s own charge limit.', goalBody)
    + group('price', 'Price limit', 'Optional soft cap. The basis decides which price is compared; it does not select the price provider.', capBody)
    + group('timing', 'Ready-by and reserve', 'When the charge should be finished, and extra allowed time on top of the planned windows.', timeBody);

  const tile = (label, text, key) => `<div class="strategy-tile" data-fact="${key}"><small>${label}</small><b>${e(text)}</b>${adminNote(key)}</div>`;
  const pct = v => v == null || v === '' ? 'Not set' : `${v}%`;
  const capText = settings.capEnabled ? `${priceText(Number(settings.cap))} ${capUnit}${settings.capBasis ? ` · ${settings.capBasis === 'nord_pool' ? 'Nord Pool' : 'configured variable cost'}` : ' · basis not set'}` : 'Off';
  const tiles = [
    tile('Vehicle', soc ? vehicleName : 'Not used (energy mode)', 'vehicle'),
    soc ? tile('Target', pct(settings.target), 'target') : tile('Requested energy', settings.energy == null || settings.energy === '' ? 'Not set' : `${settings.energy} kWh`, 'energy'),
    tile('Minimum', soc ? pct(settings.minimum) : 'Not used (energy mode)', 'minimum'),
    tile('Soft cap', capText, 'cap'),
    tile('Ready by', settings.deadlineEnabled ? String(settings.readyBy ?? 'Not set') : 'Off', 'readyBy'),
    ...(settings.reserve !== undefined ? [tile('Reserve', `${settings.reserve}% of charging time`, 'reserve')] : []),
  ].join('');
  const state = m.proposedPlanDefaults ? 'Proposed defaults · not saved' : 'Saved plan';
  const summary = editor
    ? `<div class="strategy-summary" data-state="${m.proposedPlanDefaults ? 'proposed' : 'saved'}"><div class="strategy-head"><span class="strategy-chip" data-chip="mode">${soc ? 'Charge to target SOC' : 'Charge requested energy'}</span><span class="strategy-chip" data-chip="state">${state}</span>${admin ? '' : '<span class="strategy-chip" data-chip="role">Limited to your permissions</span>'}</div><div class="strategy-tiles">${tiles}</div></div>`
    : '';
  const roleNote = editor && canSave && !admin ? '<p class="plan-role-note" role="note">You may change the charge goal, vehicle, energy, target and ready-by. Minimum SOC, soft cap, cap basis and reserve can be changed by an administrator only.</p>' : '';
  const help = editor
    ? `<div class="settings-help"><p>${m.proposedPlanDefaults ? 'Proposed defaults, not saved' : 'Saved Charge by'}: ${soc ? 'target SOC' : 'requested energy'}. ${m.proposedPlanDefaults ? 'Proposed target' : 'Saved target'}: ${e(settings.target == null ? 'not set — enter a target for SOC planning' : `${settings.target}%`)}. Minimum ready-by SOC: ${e(settings.minimum == null ? 'not set (optional)' : `${settings.minimum}%`)}.</p><p data-mode="target_soc">${e(m.vehicleHelp || '')}</p><p>Soft cap: ${settings.capEnabled ? `enabled, ${e(priceText(Number(settings.cap)))} ${e(capUnit)}` : 'off (no saved cap)'}. Enter a cap and choose its basis to enable it. The cap basis defines which price is compared; it does not select the price provider.</p><p>${m.proposedPlanDefaults ? 'Proposed ready-by' : 'Ready-by'}: ${settings.deadlineEnabled ? `enabled at ${e(settings.readyBy)}` : `off (saved time ${e(settings.readyBy)})`}. ${settings.reserve !== undefined ? `Extra time reserve: ${e(settings.reserve)}% of the charging time, at most 2 h. ` : ''}Changes are saved only when you choose Save plan.</p></div>`
    : '';
  return { summary, groups: `<div class="plan-groups">${groups}</div>`, roleNote, help };
}
