// Stage 20.5: markup of the proposed-windows card. Pure strings from the model in windows-model.js; every control here is a
// read-only inspection (select / show on chart / clear / change the price day shown). Nothing replans, sends or saves.
import { escapeText as e } from './text.js';
import { money, validSocAssumptions } from './plan-data.js';
import { summaryPriceText, priceUnit } from './price-format.js';
import { durationText } from './windows-model.js';

const STATUS = {
  proposed: ['Proposed', 'neutral', 'Selected by the planner for the current settings. Calculated, not necessarily sent.'],
  provisional: ['Provisional', 'warning', 'Planned from the prices published so far; the proposal may change when more prices arrive.'],
  constrained: ['No windows · constrained', 'warning', 'The planner proposes no windows because of a limit or missing prices, not because charging is unnecessary.'],
  noneed: ['No charging needed', 'success', 'The planner reports no charging is needed for the current target.'],
  empty: ['No windows', 'neutral', 'The current proposal has no windows and the planner did not state why. This is not an error and not a statement that no charging is needed.'],
  stale: ['Stale proposal', 'danger', 'The proposal is stale or historical, so no windows are shown as current.'],
  unavailable: ['Plan unavailable', 'danger', 'No current proposal is available, so no windows can be listed.'],
};

const fixed = (value, digits, unit, ok = () => true) => Number.isFinite(value) && ok(value) ? `${value.toFixed(digits)}${unit}` : null;
const dash = text => text == null ? '<span class="win-na" title="Unavailable: see the note below the list">—</span>' : e(text);

function fact(label, body) { return `<div><dt>${e(label)}</dt><dd>${body}</dd></div>`; }

function row(r, ctx) {
  const { selected, nextKey, f, assumptions } = ctx;
  if (!r.valid) {
    return `<li class="win-row win-invalid" data-window-invalid="${r.ordinal}"><span class="win-ord">${String(r.ordinal).padStart(2, '0')}</span><span class="win-time"><b>Interval unavailable</b><small>This proposal row has no valid start and end. It is shown as received and is not drawn on the chart.</small></span></li>`;
  }
  const w = r.w, isSel = selected?.key === r.key, isNext = r.key === nextKey;
  const currency = f.currency, priceCurrency = currency === undefined ? 'EUR' : currency;
  const priceValue = w.pricePerKwh === undefined && priceCurrency === 'EUR' ? w.centsPerKwh : w.pricePerKwh;
  const price = Number.isFinite(priceValue) && typeof priceCurrency === 'string' && /^[A-Z]{3}$/.test(priceCurrency) ? `${summaryPriceText(priceValue)} ${priceUnit(priceCurrency)}` : null;
  const cost = Number.isFinite(w.cost) ? money(w.cost, currency) : null;
  const projection = assumptions.projectionSupported === true || validSocAssumptions(assumptions);
  const socAfter = projection ? fixed(w.projectedSoc, 1, '%', n => n >= 0 && n <= 100) : null;
  const when = `${r.startDay}${r.crosses ? ` → ${r.endDay}` : ''}`;
  const clock = `${r.startText}${r.startOffset ? ` ${r.startOffset}` : ''}–${r.endText}${r.endOffset ? ` ${r.endOffset}` : ''}`;
  const tags = [
    isNext ? '<span class="win-tag" data-tag="next">Next</span>' : '',
    r.crosses ? '<span class="win-tag" data-tag="crosses">Crosses midnight</span>' : '',
    r.repeatedHour ? '<span class="win-tag" data-tag="repeated">Repeated local hour (DST)</span>' : '',
    r.exception ? '<span class="win-tag" data-tag="exception">Above-cap minimum</span>' : '',
    r.reserve ? `<span class="win-tag" data-tag="reserve">Includes ${e(durationText(r.reserve))} reserve</span>` : '',
    !r.inChart && ctx.chartKnown ? '<span class="win-tag" data-tag="off-chart">Outside the days on the chart</span>' : '',
  ].join('');
  const label = `Window ${r.ordinal}: ${r.startDay} ${r.startText} to ${r.crosses ? `${r.endDay} ` : ''}${r.endText}, ${durationText(r.minutes)}. ${isSel ? 'Selected; activate to clear.' : 'Activate to select and highlight it on the chart. Read only.'}`;
  return `<li class="win-row${isNext ? ' win-next' : ''}" data-window="${e(r.key)}" data-selected="${isSel}">`
    + `<button type="button" class="win-select" data-win-select="${e(r.key)}" aria-pressed="${isSel}" aria-label="${e(label)}">`
    + `<span class="win-ord" aria-hidden="true">${String(r.ordinal).padStart(2, '0')}</span>`
    + `<span class="win-time"><b>${e(clock)}</b><small>${e(when)}</small></span><span class="win-dur">${e(durationText(r.minutes))}</span></button>`
    + `<dl class="win-facts">${fact('Wall energy', dash(fixed(w.energy, 2, ' kWh', n => n >= 0)))}${fact('Weighted price', dash(price))}${fact('Cost', dash(cost))}${fact('SOC after', dash(socAfter))}</dl>`
    + (tags ? `<div class="win-tags">${tags}</div>` : '') + '</li>';
}

function selectionBar(model, ctx) {
  const { selected, notice } = ctx;
  const live = `<p class="subtext win-selection" role="status" aria-live="polite" data-win-notice="${notice ? 'cleared' : selected ? 'selected' : 'none'}">${notice ? e(notice) : selected ? `Window ${selected.ordinal} selected: ${e(selected.startDay)} ${e(selected.startText)}–${e(selected.endText)}. Highlighted on the chart; nothing is sent.` : ''}</p>`;
  if (!selected) return live;
  const jump = !selected.inChart && ctx.chartKnown ? (() => {
    const buttons = (model.nav?.buttons || []).filter(b => b.enabled && !b.selected && ['today', 'tomorrow', 'all', 'yesterday'].includes(b.id));
    return `<div class="win-jump" data-win-jump><p class="subtext">This window is outside the days currently drawn on the chart.${buttons.length ? ' Show another available price day:' : ' No other price day is available to show it.'}</p>${buttons.map(b => `<wa-button size="small" data-win-nav="${e(b.id)}">${e(b.label)}</wa-button>`).join('')}</div>`;
  })() : '';
  return `${live}<div class="win-actions" role="group" aria-label="Selected window, read only">${selected.inChart ? '<wa-button size="small" id="win-show-chart">Show on chart</wa-button>' : ''}<wa-button size="small" id="win-clear">Clear selection</wa-button></div>${jump}`;
}

function comparison(model, ctx) {
  const readback = ctx.effective || { state: 'unknown' };
  const stamp = value => Number.isFinite(value) ? `${ctx.f.day(value)} ${ctx.f.time(value)}` : 'Unknown';
  const proposalRows = model.rows.filter(r => r.valid).map(r => `<tr><td>${e(stamp(r.w.start))}</td><td>${e(stamp(r.w.end))}</td></tr>`).join('');
  const spans = (readback.spans || []).map(s => `<tr><td>${e(stamp(s.start))}</td><td>${e(stamp(s.end))}</td><td>${e(`${s.value} ${readback.unit}`)}</td></tr>`).join('');
  const state = readback.failed && readback.state === 'fresh' ? 'stale' : readback.state;
  return `<div class="win-comparison"><section><h4>Proposal</h4><p>Calculated at: ${e(stamp(ctx.calculatedAt))}</p><table><thead><tr><th scope="col">Start</th><th scope="col">End</th></tr></thead><tbody>${proposalRows || '<tr><td colspan="2">No current windows available</td></tr>'}</tbody></table></section><section><h4>Fetched Morek limits</h4>${ctx.fetch ? `<button type="button" id="morek-fetch" ${ctx.fetch.enabled ? '' : 'disabled'} aria-busy="${ctx.fetch.pending ? 'true' : 'false'}">${ctx.fetch.pending ? 'Refreshing...' : 'Refresh Morek limits'}</button><p role="status" aria-live="polite">${e(ctx.fetch.notice || (ctx.fetch.enabled ? 'Read-only refresh available.' : 'Refresh unavailable: administrator access and a fresh connected charger status are required.'))}</p>` : ''}<p>Status: ${e(state)}${readback.failed ? ' · latest fetch or status refresh failed' : ''}</p><p>Fetched at: ${e(stamp(readback.fetchedAt))}</p>${Number.isFinite(readback.start) ? `<p>Reported coverage: ${e(stamp(readback.start))} – ${e(stamp(readback.end))}</p>` : ''}<table><thead><tr><th scope="col">Start</th><th scope="col">End</th><th scope="col">Limit</th></tr></thead><tbody>${spans || '<tr><td colspan="3">No valid limits available</td></tr>'}</tbody></table><p>Effective limits are not proof of physical charging.</p></section></div>`;
}

export function renderWindows(model, ctx) {
  const { f } = ctx;
  const [badge, variant, explain] = STATUS[model.status] || STATUS.unavailable;
  const currency = f.currency === undefined ? 'EUR' : f.currency || 'currency unknown';
  const count = `${model.count} window${model.count === 1 ? '' : 's'}`;
  const head = `<div class="win-head" data-win-status="${model.status}"><wa-badge variant="${variant}" pill>${e(badge)}</wa-badge><span class="win-count">${e(model.knownPlan ? count : 'No list')}</span><span class="subtext">Estimated, not measured or guaranteed · wall energy · ${e(currency)}${f.costBasis ? ` · ${e(f.costBasis)}` : ''}</span></div>`;
  const policy = ctx.policy && model.status !== 'stale' && model.status !== 'unavailable' ? `<p class="subtext win-policy">Planner: ${e(ctx.policy)}</p>` : '';
  const prices = ctx.context?.tomorrowPending === true && model.status !== 'stale' && model.status !== 'unavailable' ? '<p class="subtext">Tomorrow’s prices are pending, so unpriced intervals stay unknown.</p>' : '';
  const body = model.count ? `<div class="win-scroll" role="region" tabindex="0" aria-label="${e(`Proposed windows, ${count} in total`)}"><ol class="win-list">${model.rows.map(r => row(r, { ...ctx, nextKey: ctx.nextKey })).join('')}</ol></div>` : '';
  const s = model.summary || {};
  const hasReserve = !!ctx.reserve && Number.isFinite(ctx.reserve.minutes) && ctx.reserve.minutes > 0;
  const price = Number.isFinite(s.pricePerKwh ?? s.centsPerKwh) && (f.currency === undefined || (typeof f.currency === 'string' && /^[A-Z]{3}$/.test(f.currency))) ? `${summaryPriceText(s.pricePerKwh ?? s.centsPerKwh)} ${priceUnit(f.currency === undefined ? 'EUR' : f.currency)}` : 'Unknown';
  const footer = model.count ? `<div class="win-footer" data-win-footer><div><small>Selected time</small><strong>${e(durationText(model.totalMinutes))}</strong></div><div><small>${hasReserve ? 'Required baseline energy' : 'Plan wall energy'}</small><strong>${Number.isFinite(s.energy) ? e(`${s.energy.toFixed(2)} kWh`) : 'Unknown'}</strong></div><div><small>${hasReserve ? 'Required baseline cost' : 'Plan cost'}</small><strong>${e(money(s.cost, f.currency))}</strong></div><div><small>Weighted average</small><strong>${e(price)}</strong></div></div>` : '';
  const note = f.detailsNote && model.count ? `<p class="subtext win-details-note">${e(f.detailsNote)}</p>` : '';
  const sep = '<p class="subtext win-separation">Proposal only. Whether it was sent, acknowledged or is in effect at the charger is separate evidence: see Plan activity &amp; freshness. Opening or selecting a window never replans or sends anything.</p>';
  return `${comparison(model, ctx)}${head}<p class="subtext win-explain">${e(explain)}</p>${policy}${prices}${body}${model.count ? selectionBar(model, ctx) : ''}${footer}${note}${sep}${model.count ? '' : `<p class="subtext win-selection" role="status" aria-live="polite">${ctx.notice ? e(ctx.notice) : ''}</p>`}`;
}
