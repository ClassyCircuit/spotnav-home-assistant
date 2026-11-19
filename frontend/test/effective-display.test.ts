import { describe, expect, it } from 'vitest';
import { effectiveDisplay } from '../sidebar/effective-display.js';
const now = Date.parse('2026-11-19T12:00:00Z');
const base = { status: 'Accepted', fetched_at: '2026-11-19T11:59:30Z', schedule_start: '2026-11-19T11:00:00Z', duration_s: 7200, rate_unit: 'A', periods: [{ at: '2026-11-19T11:30:00Z', amps: 0 }, { at: '2026-11-19T12:30:00Z', amps: 16 }] };
const display = (effective: any, observed = now, clock = now) => effectiveDisplay({ effective }, observed, clock);
describe('effective display', () => {
  it('never substitutes acknowledgements or sent data', () => {
    expect(effectiveDisplay({ sent: base, ack: base }, now, now).state).toBe('unknown');
    expect(display(null).state).toBe('unknown');
    expect(display({ ...base, status: 'Rejected' }).state).toBe('unknown');
  });
  it.each(['A', 'W'])('preserves zero and partial coverage in %s', unit => {
    const result = display({ ...base, rate_unit: unit });
    expect(result.state).toBe('fresh'); expect(result.unit).toBe(unit);
    expect(result.spans).toEqual([{ start: Date.parse(base.periods[0].at), end: Date.parse(base.periods[1].at), value: 0 }, { start: Date.parse(base.periods[1].at), end: Date.parse('2026-11-19T13:00:00Z'), value: 16 }]);
  });
  it('labels stale and expired data', () => {
    expect(display({ ...base, fetched_at: '2026-11-19T11:58:00Z' }).state).toBe('stale');
    expect(display(base, now, now + 3600000).state).toBe('expired');
  });
  it('rejects unknown timestamps', () => {
    expect(display(base, now + 1).state).toBe('unknown');
    expect(display({ ...base, fetched_at: 'bad' }).state).toBe('unknown');
    expect(display({ ...base, fetched_at: '2026-11-19T12:00:01Z' }).state).toBe('unknown');
  });
  it('rejects malformed units, horizons and periods', () => {
    for (const patch of [{ rate_unit: null }, { rate_unit: 'kW' }, { duration_s: 0 }, { schedule_start: 'bad' }, { periods: [] }, { periods: [...base.periods].reverse() }, { periods: [base.periods[0], base.periods[0]] }, { periods: [{ at: '2026-11-19T13:00:00Z', amps: 1 }] }, { periods: [{ at: base.periods[0].at, amps: -1 }] }]) expect(display({ ...base, ...patch }).state).toBe('invalid');
  });
});

