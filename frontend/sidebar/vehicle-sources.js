// Stage 13.1 — the advanced "Vehicle sources & properties" area. Pure: it only describes what the backend's
// entity config (`get_entity_config`) and dashboard `vehicles` rows say. It never writes, wakes the car or
// picks a sensor on its own; the panel owns every request.
import { vehicleChoice } from '../src/entity-config.ts';
import { observationFreshness } from '../src/observation-freshness.ts';

/** How old the entity config may be before the panel reads it again (the freshness limit is 90 s). */
export const CONFIG_REFRESH_MS = 45000;

const ok = (n) => Number.isFinite(n);
const fmtKwh = (n) => `${Math.round(n * 10) / 10} kWh`;
const label = (e) => (e?.friendlyName && e.friendlyName !== e.entityId ? `${e.friendlyName} (${e.entityId})` : e?.entityId || 'unknown');

/** The facts a draft is compared against: a change by anyone else after editing began is a conflict. `props`: the config's
 * `vehicleProperties` entry (present even when the sensor is unchosen). */
export function vehicleSignature(vehicle, props) {
  return JSON.stringify([
    vehicle?.id ?? null,
    vehicle?.selected?.entityId ?? null,
    vehicle?.source ?? null,
    (vehicle?.candidates || []).map((c) => c.entityId),
    props ? [props.capacityKwh ?? null, props.capacitySource ?? null, props.storedCapacityKwh ?? null, props.reportedCapacityKwh ?? null, props.onboardPhases ?? null, props.storedOnboardPhases ?? null] : null,
  ]);
}

/** Which vehicle the area shows: the person's pick, else the plan's saved car, else the only car. Never a guess among several. */
export function chooseVehicle(vehicles, selectedId, savedId) {
  const has = (id) => typeof id === 'string' && vehicles.some((v) => v.id === id);
  if (has(selectedId)) return selectedId;
  if (has(savedId) && savedId !== 'guest') return savedId;
  return vehicles.length === 1 ? vehicles[0].id : null;
}

function sensorModel(vehicle, entityState) {
  const candidates = vehicle.candidates || [];
  const selected = vehicle.selected;
  const base = vehicleChoice(vehicle);
  let status, level, text;
  if (selected === null) {
    status = candidates.length > 1 ? 'ambiguous' : 'missing';
    level = 'warn';
    text = candidates.length > 1
      ? `Several charge-level sensors fit and none is chosen, so SpotNav has no charge reading for this car. Choose one (${candidates.length} candidates).`
      : 'No charge-level sensor was found for this car.';
  } else {
    const present = candidates.some((c) => c.entityId === selected.entityId);
    const state = typeof entityState === 'function' ? entityState(selected.entityId) : 'ok';
    status = vehicle.source === 'confirmed' ? 'confirmed' : 'automatic';
    level = 'ok';
    text = vehicle.source === 'confirmed' ? `Chosen by you: ${label(selected)}.` : `Detected automatically (the only candidate): ${label(selected)}.`;
    if (!present) { status = 'removed'; level = 'warn'; text += ' This sensor is no longer among the offered candidates.'; }
    if (state === 'missing') { status = 'removed'; level = 'warn'; text += ' Home Assistant no longer has this entity.'; }
    else if (state === 'unavailable') { level = 'warn'; text += ' It currently reports no value (unavailable or unknown).'; }
  }
  const options = [{ value: '', text: vehicle.source === 'confirmed' ? 'Return to automatic detection (clear my choice)' : selected === null ? 'Choose a sensor…' : 'Automatic (only candidate)' }];
  for (const c of candidates) options.push({ value: c.entityId, text: label(c) });
  // A saved choice stays visible even if it was removed: the select must show what is saved, not the first option.
  if (base && !candidates.some((c) => c.entityId === base)) options.push({ value: base, text: `${label(selected)} (no longer offered)` });
  return { status, level, text, base, options };
}

function propertiesModel(props, row, canWrite) {
  if (!props) return null;
  const source = props.capacitySource;
  const reported = ok(props.reportedCapacityKwh) && props.reportedCapacityKwh > 0 ? props.reportedCapacityKwh : null;
  const stored = ok(props.storedCapacityKwh) && props.storedCapacityKwh > 0 ? props.storedCapacityKwh : null;
  const parts = [];
  if (reported !== null) parts.push(`${fmtKwh(reported)} reported by the vehicle's integration (used; cannot be overridden here)`);
  else if (!props.reportedKnown) parts.push('Whether the vehicle reports a capacity is unknown until a charge-level sensor is chosen');
  else parts.push('The vehicle reports no capacity');
  if (stored !== null) parts.push(reported !== null ? `${fmtKwh(stored)} stored from you (not used while the vehicle reports one)` : `${fmtKwh(stored)} entered by you (used)`);
  else if (reported === null) parts.push('nothing entered by you');
  const display = reported === null && stored === null ? `${parts.join('; ')}. Missing — SpotNav does not guess a battery size.` : `${parts.join('; ')}.`;
  const phases = props.storedOnboardPhases;
  return {
    capacity: { display, source, known: reported !== null || stored !== null, base: stored !== null ? String(stored) : '', effective: ok(props.capacityKwh) ? props.capacityKwh : null, editable: canWrite && source !== 'reported' },
    phases: {
      base: String(props.onboardPhases === 1 ? 1 : 3),
      display: phases === 1 ? '1-phase' : phases === 3 ? '3-phase (entered by you)' : '3-phase (the default; nothing entered)',
      suggestion: row && row.suggested_onboard_phases === 1 && props.onboardPhases !== 1 ? 'Recent charges look single-phase. Nothing was changed; set 1-phase below if that is right.' : '',
      editable: canWrite,
    },
  };
}

/**
 * The area's model. `input`: {admin, loading, failed, config, configAt, now, rows (dashboard vehicles),
 * dashboardFresh, reading ({vehicleId,value,stale,detail}), savedId, selectedId, entityState(id), blocked (another
 * write is in flight), conflict, notice}.
 */
export function vehicleSourcesModel(input) {
  const base = { notice: input.notice || '', conflict: !!input.conflict, busy: !!input.busy };
  if (!input.admin) return { ...base, state: 'forbidden', canEdit: false, notice: 'Administrator permission is required to inspect or change vehicle sources.' };
  if (!input.config) return { ...base, state: input.loading ? 'loading' : 'unavailable', canEdit: false, notice: input.notice || (input.loading ? 'Loading vehicle sources…' : 'Vehicle sources unavailable. Use Reload to try again.') };
  const configFresh = observationFreshness(input.configAt ?? null, input.now, !!input.failed) === 'fresh';
  const vehicles = input.config.vehicles.map((v) => ({ id: v.id, name: v.name }));
  const vehicleId = chooseVehicle(vehicles, input.selectedId, input.savedId);
  const vehicle = vehicles.length ? input.config.vehicles.find((v) => v.id === vehicleId) : null;
  const canEdit = !input.blocked && !input.conflict && !input.busy;
  const model = { ...base, state: 'ready', stale: !configFresh, vehicles, vehicleId: vehicleId || '', canEdit };
  const notes = [];
  if (input.savedId && input.savedId !== 'guest' && !vehicles.some((v) => v.id === input.savedId)) notes.push('The vehicle saved in the plan is not currently discovered; check the car’s integration.');
  if (!vehicles.length) notes.push('No vehicle with a charge-level sensor was found.');
  else if (!vehicle) notes.push('Several vehicles are available. Choose which one to inspect; none is assumed.');
  if (!configFresh) notes.push('Sensor information is stale or its refresh failed; sensor changes are disabled until it is read again.');
  model.notes = notes;
  if (!vehicle) return { ...model, sensor: null, reading: null, properties: null };
  const sensor = sensorModel(vehicle, input.entityState);
  sensor.canEdit = canEdit && configFresh && input.dashboardFresh !== false;
  const row = (input.rows || []).find((r) => r.id === vehicle.id) || null;
  const props = (input.config.vehicleProperties || []).find((p) => p.id === vehicle.id) || null;
  const properties = propertiesModel(props, row, canEdit && configFresh);
  const r = input.reading && input.reading.vehicleId === vehicle.id ? input.reading : null;
  const reading = r && ok(r.value)
    ? { text: `${r.value}%${r.stale ? ' · stale or unconfirmed' : ''} — ${r.detail}`, stale: !!r.stale }
    : row && ok(row.soc_percent)
      ? { text: `${row.soc_percent}% · last value, age unknown — not shown as a current reading.`, stale: true }
      : { text: 'No valid reading from this car.', stale: true };
  return { ...model, sensor, reading, properties, propertiesMissing: !props };
}

/** What a sensor save would do. `null` base/choice both mean automatic. `expected` is the choice the person saw (sent so the
 * backend refuses a changed one); `null` means "no choice of mine". */
export function sensorWritePlan(vehicle, draft) {
  if (!vehicle) return { ok: false, notice: 'Choose a vehicle first.' };
  const choice = typeof draft === 'string' ? draft : '';
  const base = vehicleChoice(vehicle);
  if (choice === base) return { ok: true, changed: false };
  if (choice && !(vehicle.candidates || []).some((c) => c.entityId === choice)) return { ok: false, notice: 'Choose one of the offered sensors.' };
  return { ok: true, changed: true, entityId: choice || null, expected: base || null, replacesChoice: base !== '' };
}

/** What a capacity/phases save would send, with the compare-and-set `expected` values (the effective ones) from the properties the person saw. */
export function propertyWritePlan(props, values) {
  if (!props) return { ok: false, notice: 'Capacity and phases are unavailable for this vehicle. Reload vehicle sources.' };
  const changes = {}, expected = {};
  if (props.capacitySource !== 'reported' && typeof values.capacity === 'string') {
    const text = values.capacity.trim();
    const stored = ok(props.storedCapacityKwh) && props.storedCapacityKwh > 0 ? props.storedCapacityKwh : null;
    const baseText = stored === null ? '' : String(stored);
    if (text !== baseText) {
      const number = text === '' ? null : Number(text);
      if (number !== null && !(ok(number) && number >= 1 && number <= 500)) return { ok: false, notice: 'Battery capacity must be between 1 and 500 kWh.' };
      if (number === null || number !== stored) { changes.capacity_kwh = number; expected.capacity_kwh = props.capacityKwh ?? null; }
    }
  }
  if (values.phases !== undefined && values.phases !== '') {
    const phases = Number(values.phases);
    if (phases !== 1 && phases !== 3) return { ok: false, notice: 'The onboard charger must be 1-phase or 3-phase.' };
    if (phases !== (props.onboardPhases === 1 ? 1 : 3)) { changes.onboard_phases = phases; expected.onboard_phases = props.onboardPhases; }
  }
  return Object.keys(changes).length ? { ok: true, changed: true, changes, expected, clearsCapacity: changes.capacity_kwh === null } : { ok: true, changed: false };
}
