// Stage 20.5: view model for the proposed-windows card. Presentation only: it reads the same validated adapter windows the
// chart draws (never recomputes, merges, splits, shifts or prices a window) and never writes, plans or contacts a charger.
// A window is identified by the proposal context plus its exact start/end; the ordinal is display order, not a backend id.
import { total } from './plan-data.js';

const finite = Number.isFinite;
const validInterval = w => !!w && finite(w.start) && finite(w.end) && w.end > w.start;
export const windowKey = w => `${w.start}→${w.end}`;

/** `identity` is the backend proposal identity. Without one, the exact interval list stands in so any change still clears. */
export function contextKeyOf(draftKey, context, windows) {
  const identity = typeof context?.identity === 'string' && context.identity ? `id:${context.identity}` : `fp:${(windows || []).map(w => `${w?.start}-${w?.end}`).join(',')}`;
  return `${draftKey ?? ''}|${identity}`;
}

const minutes = (w, f) => validInterval(w) && finite(f.minutesPerTimeUnit) && f.minutesPerTimeUnit > 0 ? (w.end - w.start) * f.minutesPerTimeUnit : null;
export const durationText = value => {
  if (!finite(value) || value < 0) return 'Unknown';
  const m = Math.round(value);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`;
};

const CONSTRAINED = ['minimum_shortfall', 'target_shortfall', 'block_limit', 'minimum_exception'];
const NO_NEED = ['target_met'];
const UNAVAILABLE = ['recalculating', 'unavailable', 'error'];

/**
 * status: proposed | provisional | constrained | noneed | empty | stale | unavailable
 * `empty` = a current proposal with no windows whose reason the planner did not state; it is never presented as "no need".
 */
export function windowsStatus({ knownPlan, stale, count, context }) {
  const codes = Array.isArray(context?.codes) ? context.codes : [];
  if (!knownPlan) return stale ? 'stale' : 'unavailable';
  if (count > 0) return context?.provisional === true ? 'provisional' : 'proposed';
  if (codes.some(c => UNAVAILABLE.includes(c))) return 'unavailable';
  if (codes.some(c => CONSTRAINED.includes(c)) || context?.provisional === true) return 'constrained';
  if (codes.some(c => NO_NEED.includes(c))) return 'noneed';
  return 'empty';
}

export function buildWindowsModel({ windows, knownPlan, stale = false, totals, context, format: f, draftKey, nav = null, chartHorizon = null }) {
  const list = knownPlan && Array.isArray(windows) ? windows : [];
  const eps = finite(f.minutesPerTimeUnit) && f.minutesPerTimeUnit > 0 ? 0.001 / f.minutesPerTimeUnit : 0;
  const text = x => finite(x) ? f.time(x) : 'Unknown';
  const dayOf = x => finite(x) ? f.day(x) : 'Unknown';
  const offsetOf = x => typeof f.offset === 'function' && finite(x) ? f.offset(x) : null;
  // A local clock time that appears for two different instants (the repeated DST hour) is ambiguous without an offset.
  const seen = new Map(), ambiguous = new Set();
  for (const w of list) for (const x of [w?.start, w?.end]) if (finite(x)) {
    const k = `${dayOf(x)} ${text(x)}`;
    if (seen.has(k) && seen.get(k) !== x) ambiguous.add(k); else seen.set(k, x);
  }
  const rows = list.map((w, i) => {
    const valid = validInterval(w);
    const crosses = valid && dayOf(w.start) !== dayOf(w.end - eps);
    const a = valid ? offsetOf(w.start) : null, b = valid ? offsetOf(w.end) : null;
    const clash = valid && (ambiguous.has(`${dayOf(w.start)} ${text(w.start)}`) || ambiguous.has(`${dayOf(w.end)} ${text(w.end)}`));
    const showOffset = !!(a && b && (a !== b || clash));
    const exception = w?.control === 'minimum-exception';
    const reserve = finite(w?.reserveMinutes) && w.reserveMinutes > 0 ? w.reserveMinutes : null;
    const inChart = valid && Array.isArray(chartHorizon) && chartHorizon.length === 2 && w.start >= chartHorizon[0] && w.end <= chartHorizon[1];
    return {
      ordinal: i + 1, key: valid ? windowKey(w) : null, valid, start: w?.start, end: w?.end,
      startText: text(w?.start), endText: text(w?.end), startDay: dayOf(w?.start), endDay: valid ? dayOf(w.end - eps) : 'Unknown',
      crosses, startOffset: showOffset ? a : null, endOffset: showOffset ? b : null, repeatedHour: clash && !showOffset,
      minutes: minutes(w, f), exception, reserve, w, inChart,
    };
  });
  const status = windowsStatus({ knownPlan, stale, count: rows.length, context });
  const summary = totals === undefined ? total(list) : (totals || {});
  const durations = rows.map(r => r.minutes);
  const totalMinutes = rows.length > 0 && durations.every(finite) ? durations.reduce((s, v) => s + v, 0) : null;
  return { status, rows, summary, totalMinutes, count: rows.length, contextKey: contextKeyOf(draftKey, context, list), draftKey, nav, knownPlan };
}

/**
 * Keep the user's selection only for the same charger, the same proposal identity and an exactly identical interval.
 * Anything else clears it; a charger change is silent, a changed proposal says so. Never selects a nearby or "similar" row.
 */
export function resolveSelection(sel, model) {
  if (!sel) return { selected: null, notice: '' };
  if (sel.draftKey !== model.draftKey) return { selected: null, notice: '' };
  const row = model.contextKey === sel.contextKey ? model.rows.find(r => r.valid && r.key === sel.key) : null;
  if (row) return { selected: row, notice: '' };
  return { selected: null, notice: model.knownPlan ? 'The proposal changed, so the selected window was cleared. Nothing was sent or replanned.' : 'The proposal is no longer current, so the selected window was cleared.' };
}

/** Rows whose exact interval contains the instant: used only to map a chart click to a window; ambiguity selects nothing. */
export function windowsAt(model, instant) {
  return finite(instant) ? model.rows.filter(r => r.valid && r.start <= instant && instant < r.end) : [];
}
