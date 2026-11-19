// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.7: Explore price perspective is a pure view over loaded raw spot rows.
import { describe, it, expect } from 'vitest';
import { perspectiveModel, renderPerspective } from '../shared-dashboard/price-perspective-view.js';

const H = 3600000;
const f = { time: x => `t${x / H}`, day: x => `d${Math.floor(x / (24 * H))}` };
const row = (h, cents) => ({ start: h * H, end: (h + 1) * H, cents });
const html = (prices, now, o = {}) => { const unit = o.unit || 'c/kWh'; return renderPerspective(perspectiveModel({ prices, now, unit }), { f, known: true, horizon: [0, 5 * H], ...o }); };
const el = s => { const d = document.createElement('div'); d.innerHTML = s; return d; };

describe('price perspective', () => {
  it('shows current, next, band, delta and the raw-spot basis', () => {
    const d = el(html([row(0, 5), row(1, 20), row(2, 30)], 0.5 * H, { costBasis: 'configured variable cost' }));
    expect(d.querySelector('[data-pp=now] b').textContent).toBe('5 c/kWh');
    expect(d.querySelector('[data-pp=now] .pp-band').dataset.band).toBe('cheap');
    expect(d.querySelector('[data-pp=next] b').textContent).toBe('20 c/kWh');
    expect(d.querySelector('[data-pp=next] .pp-band').dataset.band).toBe('medium');
    expect(d.querySelector('.pp-change').textContent).toContain('Higher than the current interval by 15 c/kWh');
    expect(d.querySelector('[data-pp-basis]').textContent).toContain('not the variable cost');
    expect(d.querySelector('[data-pp-basis]').textContent).toContain('configured variable cost');
    expect(d.querySelector('[data-pp=high] b').textContent).toBe('30 c/kWh');
  });
  it('keeps negative sign, exactly-25 Medium and unknown never zero', () => {
    const d = el(html([row(0, -3), row(1, 25)], 0.5 * H));
    expect(d.querySelector('[data-pp=now] b').textContent).toBe('-3 c/kWh');
    expect(d.querySelector('[data-pp=now] .pp-neg')).not.toBeNull();
    expect(d.querySelector('[data-pp=next] .pp-band').dataset.band).toBe('medium');
    expect(d.querySelector('.pp-negative').textContent).toContain('1 loaded interval has');
    const none = el(html([row(0, 5)], 3 * H));
    expect(none.querySelector('[data-pp=now] b').textContent).toBe('Unknown');
    expect(none.querySelector('[data-pp=next]').dataset.known).toBe('false');
  });
  it('reports a gap instead of bridging it and no delta', () => {
    const d = el(html([row(0, 5), row(3, 9)], 0.5 * H));
    expect(d.querySelector('[data-pp=next] small').textContent).toContain('gap');
    expect(d.querySelector('.pp-change')).toBeNull();
  });
  it('classifies nothing outside c/kWh', () => {
    const d = el(html([row(0, 1.5), row(1, 2)], 0.5 * H, { unit: 'SEK/kWh' }));
    expect(d.querySelector('.pp-band')).toBeNull();
    expect(d.querySelector('.pp-neutral').textContent).toContain('SEK/kWh');
    expect(d.querySelector('[data-pp=now] b').textContent).toBe('1.5 SEK/kWh');
  });
  it('states coverage with partial days and handles unavailable data', () => {
    const nav = { buttons: [{ label: 'Today', partial: true }], message: 'Showing today.' };
    const d = el(html([row(0, 5)], 0.5 * H, { nav }));
    expect(d.querySelector('[data-pp-coverage]').textContent).toContain('partial: Today');
    expect(d.querySelector('[data-pp-coverage]').textContent).toContain('Showing today.');
    const empty = el(renderPerspective(perspectiveModel({ prices: [], now: 1, unit: 'c/kWh' }), { f, known: false }));
    expect(empty.querySelector('.pp-empty')).not.toBeNull();
    expect(empty.querySelector('[data-pp]')).toBeNull();
  });
});
