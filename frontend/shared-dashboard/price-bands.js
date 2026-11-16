// Absolute price classification, display only: never a planner threshold, cap or charging decision.
// The cutoffs are euro cents per kWh. They apply only to a chart whose unit is exactly that; any other
// currency is left neutral because no trusted conversion is available here and none is invented.
export const BAND_UNIT = 'c/kWh';
export const PRICE_BANDS = [
  { key: 'cheap', label: 'Cheap', range: '<8', color: '#37c48f', css: 'band-green' },
  { key: 'normal', label: 'Normal', range: '8–<15', color: '#e9b34e', css: 'band-amber' },
  { key: 'medium', label: 'Medium', range: '15–25', color: '#ef8845', css: 'band-orange' },
  { key: 'expensive', label: 'Expensive', range: '>25', color: '#ec6266', css: 'band-red' },
];
export const NEUTRAL_COLOR = '#75b8e8';
export const bandsApply = unit => unit === BAND_UNIT;
// 8 and 15 start the next band; exactly 25 is still Medium. Negative prices are Cheap.
export const priceBand = (value, unit) => !bandsApply(unit) || !Number.isFinite(value) ? null : PRICE_BANDS[value < 8 ? 0 : value < 15 ? 1 : value <= 25 ? 2 : 3];
export const bandColor = (value, unit) => priceBand(value, unit)?.color || NEUTRAL_COLOR;
// Fixed view 0..30 that only grows for the whole data horizon (never for the zoom), so a 1-3 c day stays low
// and thresholds keep their positions. Unclassified currencies keep a zero baseline with their own scale.
export function priceAxisExtent(prices, unit, extra) {
  const values = [...prices.map(p => p.cents), ...(Number.isFinite(extra) ? [extra] : [])].filter(Number.isFinite);
  const lo = values.length ? Math.min(...values) : 0, hi = values.length ? Math.max(...values) : 0;
  if (bandsApply(unit)) return { min: Math.min(0, Math.floor(lo / 10) * 10), max: Math.max(30, Math.ceil(hi / 10) * 10), interval: 10 };
  const min = Math.min(0, lo), max = Math.max(hi, 0);
  return { min, max: max > min ? max + (max - min) * 0.05 : min + 1 };
}
