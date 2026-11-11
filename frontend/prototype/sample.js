// Fictional fixed-hour axis: yesterday -24..0, today 0..24, tomorrow 24..48.
// This is not a planner, real timestamp handling or live data.
const hourly = [
  33.62,33.51,33.06,29.29,28.02,28.32,27.96,28.34,30.06,30.57,30.51,30.01,30.11,29.73,39.33,43.73,47.54,47.71,47.55,50.3,50.21,47.09,24.86,35.76,
  29.49,34.97,33.71,32.68,33.43,33.41,31.58,41.29,52.26,55.39,58.44,53.07,47.16,54.37,58.44,44.65,70.56,62.71,76.73,71.56,66.55,58.44,47.24,43.91,
  22.55,32.96,32.92,32.76,34.08,38.46,32.49,43.25,53.07,49.95,54.61,49.33,51.68,54.33,47.92,51.43,78.06,70.73,77.42,68.26,67.93,59.57,46.31,41.85
];
// The supplied bar sample synthesizes four fluctuations from each hourly value.
export const prices = hourly.flatMap((base, i) => [-.2,.1,.5,-.1].map((delta, j) => ({ start: i - 24 + j / 4, end: i - 24 + (j + 1) / 4, cents: Math.round((base + delta) * 100) / 100 })));
export const now = 14.5;
export const deadline = 31;
export const horizon = [-24, 48];
// Viewport boundaries come from this fixture, never from plan stops or rounded prices.
export const sampleBoundaries = [...new Set(prices.flatMap(p => [p.start, p.end]))].sort((a,b) => a-b);
export function snapRange(start, end, boundaries = sampleBoundaries) {
  const nearest = value => boundaries.reduce((best, b) => Math.abs(b-value) < Math.abs(best-value) ? b : best, boundaries[0]);
  let a = nearest(start), b = nearest(end);
  if (a >= b) { const i = boundaries.indexOf(a); if (i < boundaries.length-1) b = boundaries[i+1]; else a = boundaries[i-1]; }
  return [a,b];
}
// Fixed-hour sample only: real sources need timestamp/timezone-aware boundaries.
export function initialRange(current, boundaries = sampleBoundaries) {
  if (boundaries.length < 2) return null;
  const first = boundaries[0], last = boundaries.at(-1);
  if (current < first) return [first, last];
  if (current >= last) return snapRange(Math.max(first, last - 12), last, boundaries);
  return snapRange(Math.max(first, current - 1.5), last, boundaries);
}
export function timeTicks(start, end, width) {
  const target = (end - start) / Math.max(1, Math.floor(width / 60));
  const interval = [0.25, 0.5, 1, 2, 4, 6, 12, 24, 48].find(n => n >= target) || 48;
  const ticks = [];
  for (let h = Math.ceil((start + 1e-8) / interval) * interval; h < end - 1e-8; h += interval) ticks.push(h);
  return ticks;
}
export const cap = 35;
// Sample-only grouping: touching blocks merge only when their control is identical.
export function groupBlocks(blocks) {
  return blocks.reduce((result, block) => {
    const last = result.at(-1);
    if (last && last.end === block.start && last.power === block.power && last.control === block.control) last.end = block.end;
    else result.push({ ...block });
    return result;
  }, []);
}
export function priceWindow(window, intervals) {
  const energy = Number.isFinite(window.power) && window.power >= 0 && Number.isFinite(window.start) && Number.isFinite(window.end) && window.end > window.start ? (window.end - window.start) * window.power : null;
  let covered = window.start, cost = 0;
  for (const p of intervals) {
    const start = Math.max(window.start, p.start), end = Math.min(window.end, p.end);
    if (end <= start) continue;
    if (start !== covered || !Number.isFinite(p.cents) || energy == null) return { ...window, energy, cost: null, centsPerKwh: null };
    cost += (end - start) * window.power * p.cents / 100;
    covered = end;
  }
  if (covered !== window.end || energy == null) return { ...window, energy, cost: null, centsPerKwh: null };
  return { ...window, energy, cost, centsPerKwh: energy ? cost * 100 / energy : null };
}
// Hand-authored fixture only; the first three blocks are continuous, then a pause.
const blocks = [[24,24.25], [24.25,24.5], [24.5,24.625], [25,25.375]].map(([start,end]) => ({ start, end, power: 6, control: 'normal' }));
// Wall energy is converted to stored battery energy once; these are projections, not observations.
export const scenario = typeof location === 'undefined' ? 'default' : new URLSearchParams(location.search).get('plan') || 'default';
export const dailyScenario = typeof location === 'undefined' ? 'mismatch' : new URLSearchParams(location.search).get('state') || 'mismatch';
const sampleSoc = dailyScenario === 'unavailable' || dailyScenario === 'stale' ? null : dailyScenario === 'infeasible' ? 15 : dailyScenario === 'exception' ? 35.5 : 48;
export const socAssumptions = { startingSoc: sampleSoc, capacityKwh: 60, efficiency: scenario === 'missing' || scenario === 'invalid' ? null : 0.9 };
export const validSocAssumptions = ({ startingSoc, capacityKwh, efficiency } = {}) => Number.isFinite(startingSoc) && startingSoc >= 0 && startingSoc <= 100 && Number.isFinite(capacityKwh) && capacityKwh > 0 && Number.isFinite(efficiency) && efficiency > 0 && efficiency <= 1;
export function projectSoc(rows, { startingSoc, capacityKwh, efficiency } = {}) {
  let soc = validSocAssumptions({ startingSoc, capacityKwh, efficiency }) ? startingSoc : null;
  return rows.map(row => {
    if (soc == null || !Number.isFinite(row.energy) || row.energy < 0) soc = null;
    else soc = Math.min(100, soc + row.energy * efficiency / capacityKwh * 100);
    return { ...row, projectedSoc: soc };
  });
}
const sampleBlocks = scenario === 'long' ? Array.from({length: 8}, (_, i) => ({start: 24 + i * .5, end: 24.25 + i * .5, power: 6, control: 'normal'})) : dailyScenario === 'exception' ? [{start:15,end:15.5,power:6,control:'minimum-exception'}, ...blocks] : blocks;
const pricedWindows = groupBlocks(sampleBlocks).map((w, i) => {
  const result = priceWindow(w, scenario === 'missing' && i === 0 ? [] : prices);
  return scenario === 'invalid' && i === 0 ? { ...result, energy: NaN, cost: Infinity, centsPerKwh: NaN } : result;
});
export const windows = projectSoc(pricedWindows, socAssumptions);
export const total = rows => {
  const energy = rows.length > 0 && rows.every(row => Number.isFinite(row.energy) && row.energy >= 0) ? rows.reduce((s, row) => s + row.energy, 0) : null;
  const cost = rows.length > 0 && rows.every(row => Number.isFinite(row.cost)) ? rows.reduce((s, row) => s + row.cost, 0) : null;
  const validEnergy = Number.isFinite(energy) ? energy : null;
  const validCost = Number.isFinite(cost) ? cost : null;
  const average = validEnergy > 0 && validCost != null ? validCost * 100 / validEnergy : null;
  return { energy: validEnergy, cost: validCost, centsPerKwh: Number.isFinite(average) ? average : null };
};
export const time = h => { if (!Number.isFinite(h)) return 'Unknown'; const seconds = Math.round((((h % 24) + 24) % 24) * 3600); const hh = Math.floor(seconds / 3600), mm = Math.floor(seconds % 3600 / 60), ss = seconds % 60; return `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}${ss ? `:${String(ss).padStart(2,'0')}` : ''}`; };
export const day = h => !Number.isFinite(h) ? 'Unknown' : h < 0 ? 'Yesterday' : h < 24 ? 'Today' : h < 48 ? 'Tomorrow' : 'Next day';
// Fictional fixed calendar, not local timestamps or a DST model.
export function sampleDate(h) {
  const d = new Date(Date.UTC(2026, 10, 9 + Math.floor(h / 24)));
  const weekdays = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${weekdays[d.getUTCDay()]} ${d.getUTCDate()} ${months[d.getUTCMonth()]}`;
}
export function sampleDays(start, end) {
  const result = [];
  for (let h = Math.floor(start / 24) * 24; h < end; h += 24)
    result.push({ start: Math.max(start,h), end: Math.min(end,h+24), midnight:h, label:`${day(h)} · ${sampleDate(h)}` });
  return result;
}
export function priceGaps(start, end, items) {
  const gaps = []; let cursor = start;
  for (const p of items) {
    if (p.end <= cursor || p.start >= end) continue;
    if (p.start > cursor) gaps.push([cursor, Math.min(p.start,end)]);
    cursor = Math.max(cursor, Math.min(p.end,end));
  }
  if (cursor < end) gaps.push([cursor,end]);
  return gaps;
}
export const money = value => !Number.isFinite(value) ? 'Unknown' : `${value < 0 ? '−' : ''}€${Math.abs(value).toFixed(2)}`;
export const priceAt = h => prices.find(p => p.start <= h && h < p.end);
// Each interval has its own segment, including the final end; gaps stay gaps.
export const stepSegments = items => items.map(p => [[p.start, p.cents], [p.end, p.cents]]);
// Duplicate x coordinates express vertical transitions, nulls explicitly break gaps.
export function stepPoints(items) {
  const points = [];
  items.forEach((p, i) => {
    if (i && items[i - 1].end !== p.start) points.push([(items[i - 1].end + p.start) / 2, null]);
    points.push([p.start, p.cents], [p.end, p.cents]);
  });
  return points;
}
