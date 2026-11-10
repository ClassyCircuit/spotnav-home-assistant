// Fictional fixed-hour axis: yesterday -24..0, today 0..24, tomorrow 24..48.
// This is not a planner, real timestamp handling or live data.
const intervals = [];
for (let start = -24; start < 36;) {
  if (start === 14) { start = 15; continue; } // explicitly unavailable sample interval
  const duration = (start >= 20 && start < 22) || (start >= 26 && start < 27) ? 0.5 : 1;
  const end = start + duration;
  let cents = 12 + Math.round(4 * Math.sin(start / 3));
  if (start === 22) cents = -2;
  if (start === 24) cents = 6;
  if (start === 26) cents = 9;
  intervals.push({ start, end, cents });
  start = end;
}
export const prices = intervals;
export const now = 21;
export const deadline = 31;
export const horizon = [-24, 48];
export const windows = [
  { start: 22, end: 23, energy: 6, cost: -0.12 },
  { start: 24, end: 25, energy: 6, cost: 0.36 },
  { start: 26, end: 26.5, energy: 3, cost: 0.27 },
];
export const total = rows => {
  if (!rows.length || rows.some(row => row.energy == null || row.cost == null)) return null;
  const energy = rows.reduce((s, row) => s + row.energy, 0);
  const cost = rows.reduce((s, row) => s + row.cost, 0);
  return { energy, cost, centsPerKwh: energy ? cost * 100 / energy : null };
};
export const time = h => `${String(((Math.floor(h) % 24) + 24) % 24).padStart(2, '0')}:${String(Math.round((h - Math.floor(h)) * 60)).padStart(2, '0')}`;
export const day = h => h < 0 ? 'Yesterday' : h < 24 ? 'Today' : h < 48 ? 'Tomorrow' : 'Next day';
export const money = value => value == null ? 'Unknown' : `${value < 0 ? '−' : ''}€${Math.abs(value).toFixed(2)}`;
export const priceAt = h => prices.find(p => p.start <= h && h < p.end);
// Each interval has its own segment, including the final end; gaps stay gaps.
export const stepSegments = items => items.map(p => [[p.start, p.cents], [p.end, p.cents]]);
