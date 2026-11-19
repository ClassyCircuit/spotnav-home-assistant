import { escapeText as e } from './text.js';

const list = (items, render) => items.length ? `<ul class="history-list">${items.map(render).join('')}</ul>` : '';
const row = (text, detail = '', cls = '') => `<li${cls ? ` class="${cls}"` : ''}>${e(text)}${detail ? `<small>${e(detail)}</small>` : ''}</li>`;

/** The one-day navigation: read-only buttons and a date picker; the host decides what (if anything) is requested. */
export function renderHistoryNav(nav) {
  if (!nav) return '';
  const button = (id, label, enabled) => `<wa-button size="small" data-history-nav="${id}" ${enabled ? '' : 'disabled'}>${e(label)}</wa-button>`;
  const picker = nav.options?.length ? `<label class="history-date">Retained day <select data-history-date aria-label="Retained history day">${nav.options.map(o => `<option value="${e(o.day)}" ${o.selected ? 'selected' : ''}>${e(o.label)}</option>`).join('')}</select></label>` : '';
  const prices = nav.priceNote !== undefined ? button('prices', 'Show this day on the price chart', true) : '';
  const day = `<div class="history-stepper">${button('prev', '‹ Earlier day', nav.canPrev)}<div class="history-day-head"><strong class="history-day-label">${e(nav.label)}${nav.isDefault ? ' (yesterday, default)' : ''}</strong></div>${button('next', 'Later day ›', nav.canNext)}</div>`;
  const tools = `<div class="history-nav-buttons">${button('yesterday', 'Yesterday', nav.canYesterday)}${button('today', 'Today', nav.canToday)}${picker}${prices}${nav.canRetry ? button('retry', 'Retry', true) : ''}</div>`;
  return `<div class="history-nav" role="group" aria-label="History day" data-history-retention="${e(nav.retention || 'unknown')}">${day}${tools}<p class="subtext">${e(nav.zoneNote)}</p><p class="subtext history-retained-note">${e(nav.retentionNote || '')}${nav.sessionsNote ? ` ${e(nav.sessionsNote)}` : ''}</p>${nav.priceNote ? `<p class="subtext history-price-note" role="status">${e(nav.priceNote)}</p>` : ''}</div>`;
}

const chip = (text, tone, key) => `<span class="history-chip" data-tone="${e(tone)}" data-chip="${e(key)}">${e(text)}</span>`;
const group = title => `<h2 class="history-group">${e(title)}</h2>`;
const banner = (kind, text) => `<p class="history-banner" data-history-banner="${e(kind)}" role="status">${e(text)}</p>`;
const PROVENANCE = { measured: 'Measured · meter counter', estimated: 'Estimated · from power readings', unplaced: 'Measured · no known time' };
const provChip = r => r.kind && PROVENANCE[r.kind] ? `<span class="history-chip" data-provenance="${e(r.kind)}">${PROVENANCE[r.kind]}</span>` : '';
const basisValue = r => r.value === null ? 'Unavailable' : e(r.text.slice(r.label.length + 2));

/** Energy bases side by side, each with its own coverage; nothing is added up here. */
const energy = m => `<div class="history-energy" aria-label="Energy by basis">${m.energyRows.map(r => `<div class="history-basis" data-basis-value="${r.value === null ? 'null' : r.value}"><b>${e(r.label)}</b><span>${basisValue(r)}</span><small>${e(r.detail)}</small>${provChip(r)}</div>`).join('')}<div class="history-basis"><b>Recorder-placed session energy</b><span>${m.sessions.length ? 'Per session below' : 'No session overlaps this day'}</span><small>Never added to the bases beside it</small></div></div>${list(m.energyNotes, t => row(t))}`;

const costBlock = (c, cls = '') => `<div class="history-basis${cls}" data-spot-cost="${e(c.state)}"><b>${e(c.headline)}</b>${c.lines.map(l => `<small>${e(l)}</small>`).join('')}</div>`;

// Stage 8.3b: the spot cost and the historical savings estimate side by side as two cards; neither is derived from the other here.
const savingsBlock = c => `<div class="history-basis" data-spot-savings="${e(c.state)}"><b>${e(c.headline)}</b>${(c.lines || []).map(l => `<small>${e(l)}</small>`).join('')}</div>`;
const summaryCards = (cost, savings) => `<div class="history-energy history-summary" aria-label="Spot cost and estimated savings">${costBlock(cost)}${savings ? savingsBlock(savings) : ''}</div>`;

/** Spot-only cost of the closed sessions in one month (Stage 8.2b): a month selector and the backend's month and delivery-day figures. */
function renderMonthCost(m) {
  const picker = m.options?.length ? `<label class="history-date">Month <select data-history-month aria-label="Spot cost month">${m.options.map(o => `<option value="${e(o.value)}" ${o.selected ? 'selected' : ''}>${e(o.label)}</option>`).join('')}</select></label>` : '';
  let body;
  if (m.state === 'ready') {
    body = `${summaryCards(m.total, m.savings)}${m.days.length ? `<h4>Days with a recorded session (delivery day, Home Assistant time)</h4>${list(m.days, d => row(d.text, d.detail, `spot-${d.state}`))}` : ''}${m.emptyDays ? `<p class="subtext">${m.emptyDays} day(s) with no recorded session: no cost shown for them (not zero, not proof that nothing was charged).</p>` : ''}`;
  } else body = banner(m.state === 'error' ? 'error' : m.state === 'invalid' ? 'invalid' : m.state === 'legacy' ? 'legacy' : 'loading', m.message);
  const read = m.readNote ? `<p class="subtext history-month-read" data-month-read${m.refreshing ? ' data-month-refreshing' : ''}>${e(m.readNote)}</p>` : '';
  return `<section data-history-section="month-cost" data-month-cost-state="${e(m.state)}"><h3>Spot cost and estimated savings by month</h3>${picker}${read}${body}</section>`;
}

function renderDigest(d) {
  const lists = [d.flow.length ? `<h4>Flow intervals in the summary</h4>${list(d.flow, i => row(i.text, i.detail))}` : '',
    d.blocks.length ? `<h4>Sent-plan blocks in the summary</h4>${list(d.blocks, b => row(`${b.text} — ${b.verdictText}`, '', `verdict-${b.verdict}`))}` : '',
    d.outside.length ? `<h4>Flow versus plan</h4>${list(d.outside, t => row(t))}` : ''].join('');
  const facts = `${d.unknownSpans ? `${d.unknownSpans} span(s) where the plan was unknown. ` : ''}${d.gapCount !== null ? `${d.gapCount} capture gap(s), ` : ''}${d.restartCount !== null ? `${d.restartCount} restart(s).` : ''}`;
  return `<section class="history-digest" data-history-section="digest"><h3>Saved day summary</h3><p class="subtext"><b>Summary only; no per-minute data and no prices.</b> ${d.partial ? 'Raw rows were already partly pruned when this was written. ' : ''}${d.computed ? `Written ${e(d.computed)}. ` : ''}It was written once and keeps no price rows.</p>${d.coverage ? `<p>${e(d.coverage)}</p>` : ''}${d.energy.length ? `<div class="history-energy">${d.energy.map(r => `<div class="history-basis" data-basis-value="${r.value === null ? 'null' : r.value}"><b>${e(r.label)}</b><span>${basisValue(r)}</span>${provChip(r)}</div>`).join('')}</div><p class="subtext">Separate bases, never added together.</p>` : ''}${lists}<p class="subtext">${e(facts)}</p></section>`;
}

/** One local day of charging history (Stage 7.3a): states are drawn distinctly; nothing here sends or changes anything. */
export function renderHistoryDay(m) {
  const head = renderHistoryNav(m.nav);
  const month = m.monthCost ? renderMonthCost(m.monthCost) : '';
  if (m.state !== 'ready') return `<div class="history-day" data-history-state="${e(m.state)}">${head}${banner(m.state, m.message)}${month}</div>`;
  const rawBanners = { digest_only: 'digest', plan_only: 'no-power', none: 'none', partial: 'partial-raw', unknown: 'unknown-raw' };
  const parts = [head];
  if (rawBanners[m.raw]) parts.push(banner(rawBanners[m.raw], m.rawNote));
  if (m.notRetained) parts.push(banner('not-retained', m.notRetained));
  if (m.refreshFailed) parts.push(banner('refresh-failed', 'The latest refresh failed; this is the earlier read of the day.'));
  if (m.legacy) parts.push(banner('legacy', 'This integration is older than the card: it does not say when lists are cut or which rows are kept, so missing rows cannot be told from rows that never existed.'));
  if (m.partial) parts.push(`<div class="history-banner" data-history-banner="truncated" role="status"><b>Partial: some lists are cut.</b>${list(m.truncated, t => row(t))}</div>`);
  if (m.raw === 'digest_only' && m.digest) parts.push(renderDigest(m.digest));
  const measured = ['full', 'partial', 'unknown'].includes(m.raw);
  const n = m.sessions.length;
  const rawChip = { full: ['Measured rows retained', 'ok'], partial: ['Measured rows partial', 'warn'], unknown: ['Raw retention unknown', 'warn'], digest_only: ['Summary only', 'info'], plan_only: ['Plans only · no power rows', 'info'], none: ['No evidence retained', 'warn'] }[m.raw];
  const chips = [rawChip ? chip(rawChip[0], rawChip[1], 'raw') : '', chip(`${n} recorded session${n === 1 ? '' : 's'}`, 'info', 'sessions'), m.partial ? chip('Lists cut', 'warn', 'truncated') : '', m.legacy ? chip('Older integration', 'warn', 'legacy') : ''].join('');
  parts.push(`<div class="history-review" data-history-section="review" aria-label="Day review"><div class="history-chips">${chips}</div><p class="subtext">What is retained for this day, not a verdict on what happened. Energy bases, cost and sessions below keep their own coverage.</p></div>`);
  if (measured || m.sent.length) parts.push(`<section data-history-section="coverage"><p>${e(m.coverage.text)}</p></section>`);
  parts.push(group('Cost and energy'));
  parts.push(`<section data-history-section="cost"><h3>Spot cost and estimated savings of this day</h3>${summaryCards(m.cost, m.savings)}</section>`);
  if (measured) parts.push(`<section data-history-section="energy"><h3>Energy by basis</h3>${energy(m)}</section>`);
  if (m.sessions.length || m.raw !== 'digest_only') parts.push(group('Sessions'));
  if (!m.sessions.length && m.raw !== 'digest_only') parts.push('<section data-history-section="sessions"><h3>Sessions overlapping this day</h3><p class="subtext" data-history-empty="sessions">No session was recorded for this day by the Morek recorder (whether it records every session is unverified). That is not proof that the car did not charge.</p></section>');
  if (m.sessions.length) parts.push(`<section data-history-section="sessions"><h3>Sessions overlapping this day</h3><ul class="history-list history-sessions">${m.sessions.map(s => `<li class="history-session"><strong>${e(s.text)}</strong><small>${e(s.detail)}</small>${s.lines.map(l => `<small class="history-recon">${e(l)}</small>`).join('')}${s.costLines.map(l => `<small class="history-cost">${e(l)}</small>`).join('')}</li>`).join('')}</ul><p class="subtext">A session that crosses midnight appears on both days; its placed energy is not split above, but its spot cost for this day is the share that fell on this day.</p></section>`);
  if (m.sent.length || measured || m.gaps.length || m.restarts.length) parts.push(group('Plan versus measured flow'));
  if (m.sent.length || measured) {
    parts.push(`<section data-history-section="sent"><h3>Sent plan and measured flow</h3>${m.sent.length ? list(m.sent, b => row(`${b.text} — ${b.verdictText}`, b.detail, `${b.kind} verdict-${b.verdict}`)) : '<p class="subtext">No sent plan is known for this day.</p>'}<p class="subtext">${e(m.sentNote)}</p>${m.unacked ? `<p class="subtext">${m.unacked} recorded plan version(s) were not acknowledged and are not treated as sent.</p>` : ''}</section>`);
  }
  if (measured) {
    parts.push(`<section data-history-section="flow"><h3>Measured flow</h3>${m.flow.length ? list(m.flow, i => row(i.text, i.detail)) : '<p class="subtext">No flow interval was found in the measured rows that exist; the coverage line says what was not measured.</p>'}${list(m.outside, x => row(x.text, '', `outside-${x.kind}`))}${m.isolated ? `<p class="subtext">${e(m.isolated)}</p>` : ''}<p class="subtext">${e(m.flowNote)}</p></section>`);
  }
  if (m.gaps.length || m.restarts.length) parts.push(`<section data-history-section="gaps"><h3>Capture gaps and restarts</h3>${list(m.gaps.slice(0, 5), t => row(`Gap: ${t}`))}${m.gaps.length > 5 ? `<p class="subtext">${m.gaps.length - 5} more gap(s) not listed.</p>` : ''}${m.restarts.length ? `<p class="subtext">Capture (re)started at ${m.restarts.slice(0, 5).map(e).join(', ')}${m.restarts.length > 5 ? ` and ${m.restarts.length - 5} more` : ''}.</p>` : ''}</section>`);
  if (month) { parts.push(group('Month review')); parts.push(month); }
  parts.push(`<p class="subtext history-retention">${e(m.retentionNote)}${m.retention.oldestPower ? ` Measured power rows currently begin ${e(m.retention.oldestPower)}.` : ''}${m.retention.digestDays !== null ? ` ${m.retention.digestDays} day summary(ies) are kept.` : ''}</p>`);
  return `<div class="history-day" data-history-state="ready" data-history-raw="${e(m.raw)}">${parts.join('')}</div>`;
}

/**
 * `h` is the legacy placeholder model of the local preview (illustrative readings); `day` is the real one-day view.
 * With only `day`, the card shows just the evidence panel; with neither, history is unavailable.
 */
export function renderHistory(h, chartAvailable = false, day = null) {
  const panel = day ? renderHistoryDay(day) : '';
  if (!h) return panel || '<p>Charging history unavailable. A proposed window is not measured history.</p>';
  return `${panel}<div class="history-head"><div><strong>${e(h.title)}</strong><p class="subtext">${e(h.subtitle)}</p></div><label class="history-select">Session <select disabled aria-label="Session selector unavailable"><option>${e(h.session)}</option></select></label></div><div class="history-comparison"><span><b>Last sent:</b> ${e(h.sent)}</span><span><b>Observed outside sent window:</b> ${e(h.outside)}</span><span><b>Coverage in sent window:</b> ${e(h.coverage)}</span></div>${chartAvailable ? '<div id="power-chart" class="chart power" role="img" aria-label="Measured power and shaded last sent plan"></div>' : '<p>Measured power history unavailable.</p>'}<p class="subtext">${e(h.note)}</p><div class="missing"><strong>Missing session example</strong><span>Previous session: energy unknown, not 0 kWh. A proposed window is not measured history.</span></div>`;
}
