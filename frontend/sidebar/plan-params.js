// Stage 13.3 — the advanced "Plan & charger parameters" area: maximum charging periods, the planned current and the
// supported departure date / weekdays. Pure: it describes the saved settings record and the dashboard's facts and builds
// the bodies of the EXISTING canonical `update_settings` replacement (the card's own builders and validators:
// `chargePeriodsReplacement`, `replacementFor('current' | 'deadline')`). Ready-by on/off and time, target, cap, minimum and
// reserve stay in "Plan controls" and are never repeated here. It never writes, raises a current or changes protection;
// the panel owns every request and the backend still has the final word on every bound.
import { chargePeriodsOptions, chargePeriodsReplacement, chargePeriodsValue, chargePeriodsLabel } from '../src/charge-periods.ts';
import { departureDays, formFromRecord, nominalPowerKw, replacementFor, PERIODS_MAX } from '../src/settings.ts';
import { DEFAULT_CURRENT_RANGE } from '../src/model.ts';
import { translate } from '../src/i18n/index.ts';

/** The executor's own limit on separate windows in one Morek plan (`planner.MOREK_MAX_BLOCKS`); applied on top of the cap. */
export const MOREK_MAX_WINDOWS = 3;
export const WEEKDAYS = [[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [7, 'Sun']];
/** The one current a Morek schedule can be sent with (`morek_schedule._validated_proposal` and the worker refuse any other: `current_must_be_16`). */
export const MOREK_REQUIRED_AMPS = 16;
export const CURRENT_NOTE = 'Planned current is the current the plan assumes when it works out how long charging takes and what schedule to send. It is a planning input, not household load balancing or electrical protection, and SpotNav never raises it by itself.';
export const SAVED_NOTE = 'Saving only stores your choice. The plan may recalculate and, if Morek owns the schedule, go through normal guarded reconciliation; it does not wake the car, send a notification, change protection or prove charging.';

const ok = (n) => Number.isFinite(n);
const pad = (n) => String(n).padStart(2, '0');

/** ISO weekday (1 Monday – 7 Sunday) of a `YYYY-MM-DD` calendar date. Pure date arithmetic, so a clock change cannot move it. */
export function isoWeekday(date) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date || '');
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.getUTCDay() === 0 ? 7 : d.getUTCDay();
}

/** The calendar date `n` days after a `YYYY-MM-DD` date (calendar arithmetic; DST-free). */
export function addDays(date, n) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date || '');
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + n));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** The current range the charger reports (`source` other than `default`), or the everyday default (named as such). */
export function currentRangeOf(dashboard) {
  const r = dashboard?.current_range ?? null;
  return r ? { minA: r.min_a, maxA: r.max_a, reported: r.source !== 'default' } : { ...DEFAULT_CURRENT_RANGE, reported: false };
}

/** The facts a draft is compared against: any change of these fields by someone else after editing began is a conflict. */
export function paramSignature(record, dashboard) {
  const r = currentRangeOf(dashboard);
  return JSON.stringify(record ? [record.max_periods, record.amps, record.departure_enabled, record.departure_time, record.departure_date, record.departure_weekdays, r.minA, r.maxA] : null);
}

function periodNotes(record, morekOwned) {
  const cap = record.max_periods;
  const effective = cap === null ? MOREK_MAX_WINDOWS : Math.min(cap, MOREK_MAX_WINDOWS);
  const limit = `Morek can carry at most ${MOREK_MAX_WINDOWS} charging windows in one plan`;
  const notes = [cap === null ? 'Automatic: the planner weighs a start cost per period and keeps each period at least half an hour.' : `A hard cap of ${cap} separate charging period${cap === 1 ? '' : 's'}; the plan may use fewer.`];
  if (morekOwned === true) notes.push(`${limit}, so while Morek owns the schedule the plan uses at most ${effective} (a higher cap does not add windows there).`);
  else if (morekOwned === false) notes.push(`Morek does not own the schedule now. ${limit}; if it takes over, at most ${effective} apply.`);
  else notes.push(`Whether Morek owns the schedule is not known right now. ${limit}; if it does, at most ${effective} apply.`);
  return notes;
}

function morekCurrentNote(amps, morekOwned) {
  const need = `A Morek schedule can only be sent while the planned current is exactly ${MOREK_REQUIRED_AMPS} A`;
  if (morekOwned === true) return amps === MOREK_REQUIRED_AMPS ? `${need}; the saved ${amps} A meets this.` : `${need}. Morek owns the schedule now and the saved current is ${amps === null ? 'not set' : `${amps} A`}, so automatic scheduling and re-sends are refused until it is ${MOREK_REQUIRED_AMPS} A. It is kept as saved; SpotNav does not change it. While Morek owns the schedule only ${MOREK_REQUIRED_AMPS} A can be saved here.`;
  if (morekOwned === false) return `${need}. Morek does not own the schedule now; another value is saved normally, but a Morek schedule cannot be sent with it.`;
  return `${need}. Whether Morek owns the schedule is not known right now, so it is treated as possibly owning it: ${amps === MOREK_REQUIRED_AMPS ? `the saved ${amps} A meets this` : `the saved ${amps === null ? 'current is not set' : `${amps} A`} would block a Morek schedule`}, and saving another value asks for confirmation.`;
}

function currentBlock(record, dashboard, canEdit, morekOwned) {
  const range = currentRangeOf(dashboard);
  const amps = record.amps;
  const warn = [];
  if (amps === null) warn.push('No planned current is saved.');
  else if (amps < range.minA || amps > range.maxA) warn.push(`The saved current ${amps} A is outside ${range.reported ? 'the charger’s reported' : 'the default'} range ${range.minA}–${range.maxA} A. It is kept exactly as saved until you change it; SpotNav never adjusts it by itself.`);
  const morek = morekCurrentNote(amps, morekOwned ?? null);
  if (amps !== MOREK_REQUIRED_AMPS && morekOwned !== false) warn.push(morek);
  const kw = amps === null ? null : nominalPowerKw(amps, record.phases);
  const nominal = amps === null ? '' : kw === null ? `Nominal power at ${amps} A is unknown: the charger’s phase count is not set.` : `About ${kw.toFixed(1)} kW nominal at ${amps} A on ${record.phases} phase${record.phases === 1 ? '' : 's'}: a planning figure, not a measurement; the car may draw less.`;
  return {
    value: amps === null ? '' : String(amps), min: range.minA, max: range.maxA, reported: range.reported, canEdit, morekOwned: morekOwned ?? null, morekNote: morek,
    ...(morekOwned === true ? { min: MOREK_REQUIRED_AMPS, max: MOREK_REQUIRED_AMPS } : {}),
    rangeText: range.reported ? `This charger accepts ${range.minA}–${range.maxA} A (the lowest limit its setup reports).` : `The charger’s range is not reported, so the everyday ${range.minA}–${range.maxA} A is shown; the backend still refuses a current above the charger’s own maximum.`,
    nominal, warnings: warn,
  };
}

/** The next departure the saved ready-by describes, in the market's local calendar; plain statements only. */
export function nextDepartureText(record, days) {
  if (!record.departure_enabled) return 'Ready-by is off, so the plan has no deadline. Turn it on in Plan controls to use a date or weekdays.';
  const time = record.departure_time;
  if (!days) return `Ready-by ${time}. The market’s time zone is not known, so the next date cannot be named here.`;
  const date = record.departure_date;
  if (date) {
    if (date < days.today) return `The saved date ${date} has passed; planning ignores it and the saved weekdays apply.`;
    if (date === days.today && days.nextOccurrence(time) !== days.today) return `Dated ready-by ${date} ${time} (market local time) — that time has already passed today.`;
    return `Dated ready-by: ${date} ${time} (market local time). A chosen date overrides the weekdays.`;
  }
  const set = new Set(record.departure_weekdays);
  let day = days.nextOccurrence(time);
  for (let i = 0; i < 8 && day; i += 1, day = addDays(day, 1)) {
    if (set.has(isoWeekday(day))) return `Next ready-by: ${day} ${time} (market local time).`;
  }
  return 'No weekday is saved, so no departure can be named.';
}

function departureBlock(record, dashboard, now, canEdit) {
  const days = departureDays(dashboard?.market?.timezone ?? '', now);
  const enabled = record.departure_enabled === true;
  const notes = [];
  if (!enabled) notes.push('Ready-by is off. Turn it on in Plan controls first; a date and weekdays only mean something with a ready-by time.');
  else notes.push(`Ready-by time ${record.departure_time} is changed in Plan controls. A date (today to 7 days ahead, in the market’s local time) overrides the weekdays; on a weekday that is not ticked there is no departure and the plan runs to the next ticked day.`);
  if (!days && enabled) notes.push('The market’s time zone is unknown, so a new date cannot be chosen safely; an existing date can still be cleared.');
  return {
    enabled, time: record.departure_time, date: record.departure_date ?? '', dateMin: days?.today ?? '', dateMax: days?.max ?? '', dateKnown: !!days,
    weekdays: WEEKDAYS.map(([n, label]) => ({ n, label, checked: record.departure_weekdays.includes(n) })),
    canEdit: canEdit && enabled, next: nextDepartureText(record, days), notes,
  };
}

/**
 * The area's model. `input`: {admin, loading, record (saved settings), dashboard (decoded), dashboardFresh, now, morekOwned
 * (true/false/null), blocked, conflict, busy, awaitingRead, notice}.
 */
export function planParamsModel(input) {
  const base = { notice: input.notice || '', conflict: !!input.conflict, busy: !!input.busy };
  const record = input.record || null, dashboard = input.dashboard || null;
  if (!record) return { ...base, state: input.loading ? 'loading' : 'unavailable', canEdit: false, notice: base.notice || (input.loading ? 'Loading plan and charger parameters…' : 'Plan and charger parameters unavailable. Use Reload to try again.') };
  const fresh = input.dashboardFresh !== false && !!dashboard;
  const admin = input.admin === true;
  const planAllowed = admin || dashboard?.settings?.users_change_plan === true;
  const open = !input.blocked && !input.conflict && !input.busy && !input.awaitingRead && fresh;
  const notes = [];
  if (!planAllowed) notes.push('You do not have permission to change the plan, so everything here is read-only.');
  else if (!admin) notes.push('Charging periods can only be changed by an administrator; the planned current and departure date and weekdays follow the charger’s “users may change the plan” setting.');
  if (planAllowed && !fresh) notes.push('The dashboard observation is stale; changes are disabled until it is read again.');
  if (input.awaitingRead && planAllowed) notes.push('Waiting for a fresh dashboard read after the last save before another change.');
  return {
    ...base, state: 'ready', canEdit: open && planAllowed, notes, currentNote: CURRENT_NOTE, savedNote: SAVED_NOTE,
    periods: { value: chargePeriodsValue(record), saved: chargePeriodsLabel('en', record.max_periods), options: chargePeriodsOptions('en').map((o) => ({ value: o.value, text: o.help ? `${o.label} — ${o.help}` : o.label })), canEdit: open && admin, notes: periodNotes(record, input.morekOwned ?? null) },
    current: currentBlock(record, dashboard, open && planAllowed, input.morekOwned ?? null),
    departure: departureBlock(record, dashboard, input.now, open && planAllowed),
  };
}

/** What a charging-periods save would do. `values.periods` is the option value (`auto` or `1`–`8`). */
export function periodsWritePlan(record, values, admin) {
  if (!admin) return { ok: false, notice: 'Administrator permission is required to change the charging periods.' };
  if (!record) return { ok: false, notice: 'Reload the settings first.' };
  const option = typeof values?.periods === 'string' ? values.periods : '';
  const check = chargePeriodsReplacement(record, option);
  if (!check.ok) return { ok: false, notice: translate('en', check.errorKey) };
  if (!check.changed) return { ok: true, changed: false };
  return { ok: true, changed: true, body: check.body, from: record.max_periods, to: check.body.max_periods };
}

/** What a planned-current save would do, judged against the charger's range by the card's own validator. */
export function currentWritePlan(record, values, allowed, dashboard, morekOwned = null) {
  if (!allowed) return { ok: false, notice: 'You do not have permission to change the plan.' };
  if (!record) return { ok: false, notice: 'Reload the settings first.' };
  const text = typeof values?.current === 'string' ? values.current.trim() : '';
  if (text === '' && record.amps === null) return { ok: true, changed: false };
  const range = currentRangeOf(dashboard);
  const check = replacementFor('current', record, { ...formFromRecord(record), current: text }, { minA: range.minA, maxA: range.maxA });
  if (!check.ok) return { ok: false, notice: `${translate('en', check.errorKey)} (allowed ${range.minA}–${range.maxA} A).` };
  if (!check.changed) return { ok: true, changed: false };
  const to = check.body.amps;
  if (to !== MOREK_REQUIRED_AMPS && morekOwned === true) return { ok: false, notice: `Not saved: Morek owns the schedule now and can only send a schedule at ${MOREK_REQUIRED_AMPS} A; ${to} A would stop automatic scheduling. Choose ${MOREK_REQUIRED_AMPS} A, or stop the Morek schedule first. The saved ${record.amps} A is unchanged.` };
  return { ok: true, changed: true, body: check.body, from: record.amps, to, morekBlocks: to !== MOREK_REQUIRED_AMPS && morekOwned !== false };
}

/** What a departure date / weekdays save would do. `values`: {date: '' | YYYY-MM-DD, weekdays: '1234567'-style digits}. */
export function departureWritePlan(record, values, allowed, dashboard, now) {
  if (!allowed) return { ok: false, notice: 'You do not have permission to change the plan.' };
  if (!record) return { ok: false, notice: 'Reload the settings first.' };
  if (!record.departure_enabled) return { ok: false, notice: 'Ready-by is off. Turn it on in Plan controls before choosing a date or weekdays.' };
  const days = departureDays(dashboard?.market?.timezone ?? '', now);
  const date = typeof values?.date === 'string' ? values.date.trim() : '';
  const weekdays = typeof values?.weekdays === 'string' ? values.weekdays : '';
  const moved = date !== (record.departure_date ?? '');
  if (moved && date !== '' && !days) return { ok: false, notice: 'The market’s time zone is unknown, so a new date cannot be chosen safely.' };
  if (moved && date === days?.today && days.nextOccurrence(record.departure_time) !== days.today) return { ok: false, notice: `${record.departure_time} has already passed today in the market’s time zone; choose a later date, or change the ready-by time in Plan controls.` };
  const check = replacementFor('deadline', record, { ...formFromRecord(record), departureDate: date, departureWeekdays: weekdays }, null, null, days);
  if (!check.ok) return { ok: false, notice: translate('en', check.errorKey) };
  if (!check.changed) return { ok: true, changed: false };
  return { ok: true, changed: true, body: check.body, dateChanged: moved, weekdaysChanged: check.body.departure_weekdays.join('') !== record.departure_weekdays.join('') };
}

export { PERIODS_MAX };
