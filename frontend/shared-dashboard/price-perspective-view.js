// Stage 20.7: the Explore "Price perspective" card. A pure view over the already validated chart price rows (raw published
// spot price, the same rows the Overview chart draws) and the existing price-day navigation model. It never requests,
// forecasts, converts a currency, plans or writes: current/next are rows that exist, the difference is plain arithmetic
// on two displayed prices, and the absolute band is the display-only classification of price-bands.js.
import { escapeText as e } from './text.js';
import { priceText } from './price-format.js';
import { priceBand, bandsApply } from './price-bands.js';

const finite = Number.isFinite;

/** Current interval and the interval that follows it, strictly from loaded rows; a gap is reported, never bridged. */
export function perspectiveModel({ prices, now, unit }) {
  const rows = (Array.isArray(prices) ? prices : []).filter(p => finite(p?.start) && finite(p?.end) && p.end > p.start && finite(p.cents)).sort((a, b) => a.start - b.start);
  const current = finite(now) ? rows.find(p => p.start <= now && now < p.end) || null : null;
  const after = current ? current.end : finite(now) ? now : null;
  const nextRow = after === null ? null : rows.find(p => p.start >= after) || null;
  const next = nextRow ? { ...nextRow, gap: current ? nextRow.start > current.end : nextRow.start > now } : null;
  const delta = current && next && !next.gap ? next.cents - current.cents : null;
  const low = rows.length ? rows.reduce((a, b) => (b.cents < a.cents ? b : a)) : null;
  const high = rows.length ? rows.reduce((a, b) => (b.cents > a.cents ? b : a)) : null;
  return { unit, count: rows.length, current, next, delta, low, high, bands: bandsApply(unit), negative: rows.filter(p => p.cents < 0).length };
}

const bandChip = (cents, unit) => {
  const b = priceBand(cents, unit);
  return b ? `<span class="pp-band" data-band="${e(b.key)}"><span class="cl-dot ${e(b.css)}" aria-hidden="true">●</span> ${e(b.label)} ${e(b.range)}</span>` : '';
};
const amount = (cents, unit) => `${priceText(cents)} ${e(unit)}`;
const negNote = cents => (finite(cents) && cents < 0 ? '<span class="pp-neg">Negative published price</span>' : '');

function tile(kind, label, row, unit, time, extra = '') {
  if (!row) return `<div class="pp-tile" data-pp="${kind}" data-known="false"><span class="pc-label">${e(label)}</span><b>Unknown</b><small>${extra}</small></div>`;
  return `<div class="pp-tile" data-pp="${kind}" data-known="true"><span class="pc-label">${e(label)}</span><b>${amount(row.cents, unit)}</b>${bandChip(row.cents, unit)}${negNote(row.cents)}<small>${e(time(row.start))}–${e(time(row.end))} ${e(extra)}</small></div>`;
}

/** `f` supplies `time(ms)`/`day(ms)`; `nav` is the existing price-day model; `costBasis` the plan's stated variable-cost basis. */
export function renderPerspective(model, { f, nav, horizon, costBasis, known }) {
  const time = f.time, day = f.day, u = model.unit;
  if (!known || !model.count) {
    return '<p class="pp-empty" role="status">No published prices are loaded, so there is no current or next price to show. Nothing is estimated in their place.</p>'
      + '<div class="pp-links"><button type="button" class="sn-link" data-open-tab="overview">Price chart on Overview <span aria-hidden="true">→</span></button></div>';
  }
  const cur = model.current, nxt = model.next;
  const nextExtra = !nxt ? 'No later price is published in the loaded days.' : nxt.gap ? 'The loaded prices have a gap before this interval.' : `${day(nxt.start)}`;
  const curExtra = cur ? day(cur.start) : 'No loaded interval covers now.';
  const change = model.delta === null ? '' : `<p class="pp-change" data-direction="${model.delta > 0 ? 'up' : model.delta < 0 ? 'down' : 'same'}">${model.delta === 0 ? 'Same as the current interval.' : `${model.delta > 0 ? 'Higher' : 'Lower'} than the current interval by ${priceText(Math.abs(model.delta))} ${e(u)}.`} Published rows only, not a forecast.</p>`;
  const range = h => finite(h?.[0]) && finite(h?.[1]) ? `${e(day(h[0]))} ${e(time(h[0]))} → ${e(day(h[1]))} ${e(time(h[1]))}` : '';
  const partial = nav?.buttons?.filter(b => b.partial).map(b => b.label) ?? [];
  const note = nav ? `${e(nav.message || nav.detail || '')}` : '';
  const bands = model.bands ? '' : `<p class="subtext pp-neutral">No absolute band is shown: bands are defined in euro c/kWh and no trusted conversion exists for ${e(u)}.</p>`;
  const neg = model.negative ? `<p class="subtext pp-negative" role="status">${model.negative} loaded interval${model.negative === 1 ? ' has' : 's have'} a negative published price; the sign is kept everywhere.</p>` : '';
  return `<div class="pp-basis" data-pp-basis="raw-spot"><b>Raw published spot price</b> in ${e(u)}, before configured fees, taxes or margin; the source may include its own charges. It is not the variable cost of charging${costBasis ? ` (the plan uses ${e(costBasis)})` : ''}, and the absolute bands are a display aid, never a charging limit.</div>`
    + `<div class="pp-tiles" role="group" aria-label="Current and next price">${tile('now', 'Current price', cur, u, time, curExtra)}${tile('next', 'Next interval', nxt, u, time, nextExtra)}${tile('low', 'Loaded low', model.low, u, time, day(model.low.start))}${tile('high', 'Loaded high', model.high, u, time, day(model.high.start))}</div>`
    + `${change}${neg}${bands}`
    + `<div class="pp-coverage" data-pp-coverage><b>Coverage</b> ${model.count} published interval${model.count === 1 ? '' : 's'} loaded${range(horizon) ? ` · ${range(horizon)}` : ''}${partial.length ? ` · partial: ${e(partial.join(', '))}` : ''}${note ? `<br>${note}` : ''}</div>`
    + '<div class="pp-links"><button type="button" class="sn-link" data-open-tab="overview">Choose price days and see the chart on Overview <span aria-hidden="true">→</span></button><span class="subtext">Live and monthly insights follow below.</span></div>';
}
