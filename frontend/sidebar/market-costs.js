// Stage 13.2 — the advanced "Market & charging costs" area. Pure: it describes what the backend already says
// (the dashboard's market/prices/fiscal/price_source/grid_tariff blocks, the saved settings record and the market
// options) and builds the bodies of the EXISTING canonical writes (`update_settings` for area and VAT/energy
// tax/grid fee, `update_grid_tariff` for the percentage and high-load fee, `choose_price_source`). It never writes,
// switches provider, enables a fee or assumes what a price includes; the panel owns every request.
import { FISCAL_COMPONENTS, fiscalFormFrom, fiscalUnit, marketAreaLabel, marketEditable, marketIncluded, marketReplacement, marketStateKey, marketSuggestion } from '../src/market.ts';
import { gridTariffIncluded, HIGH_LOAD_MAX, sameBody, storedBody, SUGGESTED_WINDOW } from '../src/grid-tariff.ts';
import { translate } from '../src/i18n/index.ts';
import { displayPrice, priceText, priceUnit } from '../shared-dashboard/price-format.js';

/** The market list is bundled and static; reread it this often, and refuse writes on one older than the limit. */
export const OPTIONS_REFRESH_MS = 600000;
export const OPTIONS_MAX_AGE_MS = 1200000;

const ok = (n) => Number.isFinite(n);
const LABELS = { vat: 'VAT', tax: 'Energy tax', transfer: 'Grid fee (flat)' };
export const COMPONENT_LABELS = LABELS;
export const DAY_CHOICES = [['all', 'Every day'], ['weekdays', 'Monday–Friday'], ['mon_sat', 'Monday–Saturday']];
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** What the chart's raw price becomes, in words; the order is the planner's (`planning/planner.py:effective_minor_per_kwh`). */
export const BASIS_TEXT = 'How a configured variable cost is built: the raw published price, plus energy tax, plus the grid fee (the flat fee, or the high-load fee inside its hours), plus the grid fee as a percentage of the raw price (it follows the raw price’s sign), then multiplied by (1 + VAT). VAT therefore applies to the tax and fees as well. A raw price can be negative; configured fees may make the final cost positive. A price that the area list says already includes a charge is not charged for it again.';

const areaOf = (options, id) => (options && id ? options.areas.find((a) => a.area_id === id) || null : null);
const figureText = (n) => (ok(n) ? String(n) : '');
const modeOf = (form) => (!form.enabled ? 'off' : form.intent === 'suggested' ? 'suggested' : 'custom');

/** The facts a draft is compared against: any change by someone else after editing began is a conflict. */
export function costSignature(record, options, block, areaId) {
  const id = areaId ?? record?.area_id ?? null;
  const row = record ? record.overrides.find((o) => o.area_id === id) || null : null;
  return JSON.stringify([
    record?.area_id ?? null,
    row,
    options ? options.state : null,
    options && id ? marketIncluded(options, id) : null,
    block ? [block.write_revision, block.transfer_percent.policy, block.transfer_percent.explicit_value, block.transfer_high.policy, block.transfer_high.explicit_value, block.high_load_window] : null,
  ]);
}

function providerLines(dashboard) {
  if (!dashboard) return { provider: 'Price provider unknown: no dashboard observation yet.', providerNote: '', url: '' };
  const p = dashboard.prices?.provider ?? null;
  if (!p) return { provider: 'Price provider unknown (not reported by this backend).', providerNote: '', url: '' };
  const named = p.name || p.key;
  return {
    provider: named ? `Price provider: ${named}.` : 'No price provider is configured for the saved area.',
    providerNote: p.notice ? `Provider note: ${p.notice.code.replace(/_/g, ' ')}.` : '',
    url: p.url || '',
  };
}

function heldLine(dashboard) {
  const pr = dashboard?.prices;
  if (!pr) return 'Held price data: unknown.';
  const bits = [`state ${pr.state || 'unknown'}${pr.reason ? ` (${pr.reason})` : ''}`];
  bits.push(pr.interval_count > 0 ? `${pr.interval_count} held intervals${ok(pr.resolution_minutes) ? ` at ${pr.resolution_minutes} min` : ''}` : 'no held intervals');
  if (pr.waiting_for_tomorrow === true) bits.push('tomorrow not yet published');
  if (pr.unpriced === true) bits.push('some slots have no price');
  const cat = dashboard?.market?.catalogue_state;
  if (cat) bits.push(`area list ${cat}`);
  return `Held price data: ${bits.join('; ')}. These are held values, not proof the provider answered just now.`;
}

function nowLine(dashboard, now) {
  const m = dashboard?.market;
  const currency = m?.currency || null;
  const unit = priceUnit(currency);
  const hit = (dashboard?.prices?.intervals || []).find((i) => ok(i.startMs) && ok(i.endMs) && i.startMs <= now && now < i.endMs);
  if (!hit) return { text: `Current interval: no held price for this moment (unknown, not zero). Unit ${unit}.`, unit };
  const fmt = (x) => (ok(x) ? `${priceText(displayPrice(x, currency))} ${unit}` : 'unknown');
  return { text: `Current interval: raw published price ${fmt(hit.raw_price)} · configured variable cost ${fmt(hit.effective_price)}. They are different figures and are shown separately.`, unit };
}

function currencyLine(dashboard, area) {
  const m = dashboard?.market;
  const cur = area?.currency ?? m?.currency ?? null;
  const major = area?.major_unit ?? m?.major_unit ?? null;
  const minor = area?.minor_unit ?? m?.minor_unit ?? null;
  if (!cur) return 'Currency unknown for the selected area.';
  return `Currency ${cur}${major ? ` (${major}${minor ? `, minor unit ${minor}` : ''})` : ''}. Prices and the chart show ${priceUnit(cur)}; flat fees are entered in ${minor ? `${minor}/kWh` : 'the area’s minor unit (unknown)'} exactly as stored, and VAT and the grid fee percentage in %.`;
}

function feeRows(record, options, areaId, canEdit) {
  const row = record.overrides.find((o) => o.area_id === areaId) || null;
  const included = marketIncluded(options, areaId);
  const rows = [];
  for (const key of FISCAL_COMPONENTS) {
    const form = fiscalFormFrom(row, key);
    const suggestion = marketSuggestion(options, areaId, key);
    const unit = fiscalUnit(options, areaId, key) ? (key === 'vat' ? '%' : `${fiscalUnit(options, areaId, key)}/kWh`) : (key === 'vat' ? '%' : 'unit unknown');
    const stored = row ? row[key] : null;
    const base = modeOf(form);
    if (included.includes(key)) {
      rows.push({ key, label: LABELS[key], included: true, unit, mode: 'included', figure: figureText(stored?.value ?? null), modes: [], hint: `Already included in this area’s published price — nothing is added${stored && stored.value !== null ? ` (a stored figure of ${stored.value} ${unit} is kept but not used)` : ''}.`, canEdit: false });
      continue;
    }
    const modes = [{ value: 'off', text: 'Off — not added' }];
    if (suggestion !== null || base === 'suggested') modes.push({ value: 'suggested', text: suggestion !== null ? `Use the area’s suggestion (${suggestion} ${unit})` : 'Area suggestion (none published — nothing is added)' });
    modes.push({ value: 'custom', text: 'My own figure' });
    const hint = base === 'off' ? 'Not added to prices.' : base === 'suggested' ? (suggestion !== null ? `Adds the area’s suggestion, ${suggestion} ${unit} (kept as “suggested”, not copied).` : 'Set to the suggestion, but this area publishes none, so nothing is added.') : `Adds your figure, ${figureText(stored?.value)} ${unit}.`;
    rows.push({ key, label: LABELS[key], included: false, unit, mode: base, figure: form.intent === 'custom' ? form.value : '', modes, hint, canEdit });
  }
  return rows;
}

function tariffModel(block, canEdit) {
  if (!block) return null;
  const included = gridTariffIncluded(block);
  const high = block.transfer_high, pct = block.transfer_percent;
  const stored = block.high_load_window;
  const win = stored || SUGGESTED_WINDOW;
  const highUnit = high.unit;
  const edit = canEdit && block.writable === true && !included;
  const demandCount = block.demand ? block.demand.components.length : 0;
  return {
    included, canEdit: edit, writable: block.writable === true,
    percent: { mode: pct.policy === 'manual' ? 'custom' : 'off', figure: figureText(pct.explicit_value), unit: '%', policy: pct.policy },
    high: { mode: high.policy === 'manual' ? 'custom' : 'off', figure: figureText(high.explicit_value), unit: highUnit ? highUnit : 'unit unknown', unitKnown: !!highUnit, policy: high.policy },
    window: { ...win, stored: !!stored, suggested: !stored },
    notes: [
      included ? 'The area’s published price already includes the grid fee, so these rows are locked and nothing is added.' : 'Switching a row off keeps its stored figure. The high-load fee needs its hours; with none stored, common hours are only suggested and are saved only when you press Save.',
      demandCount ? `${demandCount} demand-charge component${demandCount === 1 ? '' : 's'} are kept exactly as stored (this area does not edit them).` : '',
    ].filter(Boolean),
    summary: [
      `Grid fee as % of the raw price: ${pct.policy === 'included' ? 'included in the published price' : pct.policy === 'manual' ? `${pct.explicit_value}%` : 'off'}.`,
      `High-load grid fee: ${high.policy === 'included' ? 'included in the published price' : high.policy === 'manual' ? `${high.explicit_value} ${highUnit || 'unit unknown'}` : 'off'}${stored ? ` · hours stored (${DAY_CHOICES.find((d) => d[0] === stored.days)?.[1] || stored.days}, ${MONTHS[stored.from_month - 1]}–${MONTHS[stored.to_month - 1]}, ${String(stored.from_hour).padStart(2, '0')}:00–${String(stored.to_hour % 24).padStart(2, '0')}:00)` : ' · no hours stored'}.`,
    ],
  };
}

/**
 * The area's model. `input`: {admin, loading, failed, record (saved settings), options (market options), optionsAt, now,
 * dashboard (decoded), dashboardFresh, areaDraft, blocked, conflict, busy, awaitingRead, notice}.
 */
export function marketCostsModel(input) {
  const base = { notice: input.notice || '', conflict: !!input.conflict, busy: !!input.busy };
  const dashboard = input.dashboard || null;
  const summary = { ...providerLines(dashboard), held: heldLine(dashboard), basis: BASIS_TEXT, ...nowLine(dashboard, input.now) };
  const reloadNote = (text) => ({ ...base, ...summary, state: input.loading ? 'loading' : 'unavailable', canEdit: false, notice: base.notice || text });
  if (!input.record) return reloadNote(input.loading ? 'Loading market and cost settings…' : 'Market and cost settings unavailable. Use Reload to try again.');
  if (!input.options) return reloadNote(input.loading ? 'Loading the area list…' : 'The area list is unavailable, so area and fees cannot be shown or changed. Use Reload to try again.');
  const optionsFresh = ok(input.optionsAt) && input.now - input.optionsAt <= OPTIONS_MAX_AGE_MS && !input.failed;
  const record = input.record, options = input.options;
  const editableState = marketEditable(options.state, input.admin === true);
  const dashFresh = input.dashboardFresh !== false && !!dashboard;
  const baseEdit = input.admin === true && !input.blocked && !input.conflict && !input.busy && !input.awaitingRead;
  const canEdit = baseEdit && editableState && optionsFresh && dashFresh;
  const notes = [];
  if (!input.admin) notes.push('Administrator permission is required to change the market, taxes and fees. Everything here is read-only.');
  const stateKey = marketStateKey(options.state, options.reason);
  if (stateKey) notes.push(translate('en', stateKey));
  if (!editableState && input.admin) notes.push('The area list is not held, so the saved area is shown but nothing can be changed.');
  if (input.admin && !optionsFresh) notes.push('The area list is stale or its refresh failed; changes are disabled until it is read again.');
  if (input.admin && !dashFresh) notes.push('The dashboard observation is stale; changes are disabled until it is read again.');
  if (input.awaitingRead && input.admin) notes.push('Waiting for a fresh dashboard read after the last save before another change.');
  const savedId = record.area_id;
  const areaId = input.areaDraft ?? savedId;
  const area = areaOf(options, areaId);
  const savedListed = !savedId || !!areaOf(options, savedId);
  if (savedId && !savedListed) notes.push(`The saved area ${savedId} is no longer in the area list; it is kept until you choose another.`);
  const areaOptions = [];
  if (!savedId) areaOptions.push({ value: '', text: 'No area saved — choose one…' });
  if (savedId && !savedListed) areaOptions.push({ value: savedId, text: `${savedId} (no longer listed)` });
  for (const a of options.areas) areaOptions.push({ value: a.area_id, text: `${marketAreaLabel('en', a.name, a.area_id)} · ${a.currency}` });
  const changedArea = areaId !== savedId;
  if (changedArea) notes.push(`The selected area differs from the saved one (${savedId || 'none'}). The prices, currency and provider above are for the saved area until you save. Fees start from what is stored for the new area; nothing carries over.`);
  const model = { ...base, ...summary, state: 'ready', canEdit, notes, areaDraft: changedArea, currencyText: currencyLine(dashboard, area || areaOf(options, savedId)) };
  model.area = { value: areaId || '', options: areaOptions, canEdit: canEdit && options.areas.length > 0, savedId: savedId || '', savedText: savedId ? marketAreaLabel('en', areaOf(options, savedId)?.name ?? dashboard?.market?.area_name ?? null, savedId) : 'none' };
  model.fees = areaId && area ? feeRows(record, options, areaId, canEdit) : [];
  if (!model.fees.length) model.notes.push('Choose an area to see its taxes and fees.');
  const ps = dashboard?.price_source ?? null;
  model.source = ps ? { title: ps.title, count: ps.charger_count, writable: ps.writable === true, base: ps.entry_id, choices: ps.choices.map((c) => ({ value: c.entry_id, text: c.title })), canEdit: canEdit && ps.writable === true && ps.choices.length > 1 } : null;
  model.tariff = tariffModel(dashboard?.grid_tariff ?? null, canEdit);
  model.noEntryNote = dashboard && !ps ? 'This charger prices with its own settings (no electricity price entry), so the price-source and grid-tariff controls are not offered here.' : '';
  model.shared = ps ? `Area and fees belong to the price entry “${ps.title}”, used by ${ps.charger_count} charger${ps.charger_count === 1 ? '' : 's'}; a change applies to all of them.` : '';
  return model;
}

/** What an area/VAT/tax/grid-fee save would do. `values`: {area, vat:{mode,figure}, tax:{…}, transfer:{…}}. Backend validation still decides. */
export function marketWritePlan(record, options, values, admin) {
  if (!admin) return { ok: false, notice: 'Administrator permission is required.' };
  if (!record || !options) return { ok: false, notice: 'Reload market and cost settings first.' };
  const areaId = values?.area ? values.area : null;
  const form = { areaId, vat: null, tax: null, transfer: null };
  for (const key of FISCAL_COMPONENTS) {
    const v = values?.[key] || { mode: 'off', figure: '' };
    const text = typeof v.figure === 'string' ? v.figure : '';
    if (v.mode === 'suggested') form[key] = { enabled: true, value: '', intent: 'suggested' };
    else if (v.mode === 'custom') form[key] = { enabled: true, value: text, intent: 'custom' };
    else form[key] = { enabled: false, value: text, intent: text.trim() === '' ? 'suggested' : 'custom' };
  }
  const check = marketReplacement(record, form, options);
  if (!check.ok) return { ok: false, notice: translate('en', check.errorKey) };
  if (!check.changed) return { ok: true, changed: false };
  return { ok: true, changed: true, body: check.body, areaChanged: areaId !== record.area_id, fromArea: record.area_id, toArea: areaId };
}

/** What a grid-tariff save would do, as the existing builders state it (keeps demand components and the other part as stored). */
export function tariffWritePlan(block, values) {
  if (!block) return { ok: false, notice: 'This charger has no electricity price entry, so there is no grid tariff to change.' };
  if (block.writable !== true) return { ok: false, notice: 'Administrator permission is required.' };
  if (gridTariffIncluded(block)) return { ok: false, notice: 'The published price already includes the grid fee; nothing can be added.' };
  const body = storedBody(block);
  const num = (t) => { const s = typeof t === 'string' ? t.trim().replace(',', '.') : ''; return s === '' ? null : Number(s); };
  const p = values?.percent || { mode: 'off', figure: '' };
  if (p.mode === 'custom') {
    const n = num(p.figure);
    if (n === null) return { ok: false, notice: 'Enter the grid fee percentage, or switch it off.' };
    if (!ok(n) || n < 0 || n > 1000) return { ok: false, notice: 'The grid fee percentage must be a number from 0 to 1000.' };
    body.transfer_percent = { enabled: true, value: n };
  } else body.transfer_percent = { enabled: false, value: block.transfer_percent.explicit_value };
  const h = values?.high || { mode: 'off', figure: '' };
  if (h.mode === 'custom') {
    if (!block.transfer_high.unit) return { ok: false, notice: 'The area’s unit is unknown, so the high-load fee cannot be set.' };
    const n = num(h.figure);
    if (n === null) return { ok: false, notice: 'Enter the high-load fee, or switch it off.' };
    if (!ok(n) || n < 0 || n > HIGH_LOAD_MAX) return { ok: false, notice: `The high-load fee must be a number from 0 to ${HIGH_LOAD_MAX}.` };
    const w = values?.window || {};
    const win = { days: w.days, from_month: Number(w.fromMonth), to_month: Number(w.toMonth), from_hour: Number(w.fromHour), to_hour: Number(w.toHour) };
    if (!DAY_CHOICES.some((d) => d[0] === win.days) || ![win.from_month, win.to_month].every((x) => Number.isInteger(x) && x >= 1 && x <= 12) || !Number.isInteger(win.from_hour) || win.from_hour < 0 || win.from_hour > 23 || !Number.isInteger(win.to_hour) || win.to_hour < 1 || win.to_hour > 24) return { ok: false, notice: 'Choose valid high-load days, months and hours.' };
    if (win.from_hour === win.to_hour) return { ok: false, notice: 'The high-load window must not start and end at the same hour.' };
    body.transfer_high = { enabled: true, value: n };
    body.high_load_window = win;
  } else body.transfer_high = { enabled: false, value: block.transfer_high.explicit_value };
  return sameBody(body, storedBody(block)) ? { ok: true, changed: false } : { ok: true, changed: true, body, expected: block.write_revision };
}

/** What a price-entry choice would do. The saved entry is never replaced without the person asking. */
export function sourceWritePlan(source, values) {
  if (!source) return { ok: false, notice: 'This charger has no electricity price entry.' };
  const id = typeof values?.entry === 'string' ? values.entry : '';
  if (id === source.base) return { ok: true, changed: false };
  if (!source.choices.some((c) => c.value === id)) return { ok: false, notice: 'Choose one of the offered electricity price entries.' };
  return { ok: true, changed: true, entryId: id, from: source.base, count: source.count };
}
