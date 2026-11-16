// Fictional held price days in the exact shapes of `spotnav/get_price_days` (api_version 1), for the local preview.
// The sample axis is hours from Mon 9 Nov 2026 00:00 (a fixed UTC calendar, no DST model). Yesterday's rows are the
// sample's own, so merging them with the sample feed exercises the "identical duplicates drop" rule.
import { prices as samplePrices } from './sample.js';

export const SAMPLE_TODAY = '2026-11-09';
export const EPOCH = Date.UTC(2026, 10, 9);
const HOUR = 3600000;
const iso = hours => new Date(EPOCH + hours * HOUR).toISOString();
const row = (start, end, cents) => ({ start: iso(start), end: iso(end), raw_price: Math.round(cents) / 100 });
/** Sample intervals as backend rows (major unit, so euro cents / 100). */
export const sampleRows = samplePrices.map(p => ({ start: iso(p.start), end: iso(p.end), raw_price: p.cents / 100 }));
const hourlyDay = (offset, count = 24, base = 30) => Array.from({ length: count }, (_, i) => row(offset + i, offset + i + 1, (base + 6 * Math.sin(i / 3 + offset)) * 100));
const dayFacts = (day, rows, extra = {}) => ({ day, held: true, state: 'ready', complete: true, resolution_minutes: 60, source: 'network', fetched_at: `${day}T22:00:00+00:00`, interval_count: rows.length, provenance: [{ market_day: day, provider: 'sample', fetched_at: `${day}T22:00:00+00:00`, state: 'ready' }], reason: null, intervals: rows, ...extra });
const yesterdayRows = sampleRows.filter(r => Date.parse(r.start) >= EPOCH - 24 * HOUR && Date.parse(r.end) <= EPOCH);
// day -> its rows (offset hours from today 00:00): 11-08 is the sample's own; 11-07 is partial; 11-06 is not held.
const held = new Map([
  ['2026-11-08', dayFacts('2026-11-08', yesterdayRows, { resolution_minutes: 15 })],
  ['2026-11-07', dayFacts('2026-11-07', hourlyDay(-48, 12), { complete: false, state: 'incomplete' })],
  ...[5, 4, 3, 2, 1].map(d => [`2026-11-0${d}`, dayFacts(`2026-11-0${d}`, hourlyDay((d - 9) * 24))]),
]);
const facts = ({ intervals, provenance, held: _held, reason, ...rest }) => rest;

/** What the backend answers, from the same held days (`request` for `createPriceDays`). */
export function fixtureRequest(context) {
  return async params => {
    const base = { api_version: 1, charger_id: context.charger, area_id: context.area, zone: 'Etc/UTC', currency: context.currency, today: SAMPLE_TODAY };
    if (params.mode === 'available') {
      const days = [{ ...facts(dayFacts('2026-11-10', [])), complete: true, interval_count: 96, resolution_minutes: 15 }, ...[...held.values()].map(facts)].sort((a, b) => b.day.localeCompare(a.day));
      return { ...base, mode: 'available', yesterday_reachable: true, days: [...days.filter(d => d.day === '2026-11-10' || d.day <= '2026-11-08')], oldest: days.at(-1).day, newest: days[0].day };
    }
    const out = [];
    for (let t = Date.parse(params.from); t <= Date.parse(params.to); t += 24 * HOUR) {
      const day = new Date(t).toISOString().slice(0, 10);
      out.push(held.get(day) ?? { day, held: false, state: 'unavailable', complete: false, resolution_minutes: null, source: null, fetched_at: null, interval_count: null, provenance: [], reason: 'not_held', intervals: null });
    }
    return { ...base, mode: 'range', from: params.from, to: params.to, days: out };
  };
}
