// One local day of charging history (Stage 7.3a): a read-only request state machine and a display model, shared by
// the live sidebar and the local preview. It only asks `spotnav/get_charging_history` for ONE Home Assistant-local day,
// never writes, never plans and never interprets: every verdict, status and number below is the backend's, only
// validated, labelled and formatted. A request is bound to charger, generation/permission epoch, zone, day and a
// per-request sequence; any other answer is dropped. There is no automatic retry: a failure stays until `retry()`.

export const HISTORY_DAYS_BACK = 62;       // the digest limit; older days have no evidence (sessions live elsewhere)
export const REFRESH_TODAY_MS = 300000;    // the default day is re-read at most this often; a past day never is
const PARTIAL_AFTER_S = 660;               // MAX_POWER_GAP_S: power rows starting later than this after midnight are partial
const MINUTE = 60000;
const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ZONE_FAILED = 'Charging history needs the Home Assistant time zone, which is unknown here.';
const LISTS = [['intervals', 'measured flow intervals'], ['gaps', 'capture gaps'], ['restarts', 'capture restarts'],
  ['planned_blocks', 'sent-plan blocks'], ['outside_plan', 'flow-versus-plan rows'], ['unknown_plan_spans', 'unknown-plan spans'],
  ['sessions', 'sessions'], ['plans', 'plan versions']];

const ms = day => { const m = DAY_RE.exec(day || ''); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : NaN; };
export const addDays = (day, n) => new Date(ms(day) + n * 86400000).toISOString().slice(0, 10);
export const dayLabel = day => Number.isFinite(ms(day)) ? new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }).format(ms(day)) : 'Unknown day';
/** The calendar date of an instant in `zone`, `YYYY-MM-DD` (null when the zone or instant is unusable). */
export function localDate(at, zone) {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(at); } catch { return null; }
}

const num = v => typeof v === 'number' && Number.isFinite(v);
const nonneg = v => num(v) && v >= 0;
const kwh = v => nonneg(v) ? `${v.toFixed(v < 10 ? 2 : 1)} kWh` : 'unknown';
const duration = s => { if (!nonneg(s)) return 'unknown'; const m = Math.round(s / 60), h = Math.floor(m / 60); return h ? `${h} h ${m % 60} min` : `${m} min`; };
const instant = v => { const t = Date.parse(v); return Number.isFinite(t) ? t : NaN; };

/** What the backend promises about the answer's shape; anything else is `invalid`, never guessed at. */
export function validateHistory(answer, asked) {
  const w = answer?.window, o = answer?.observed, c = answer?.comparison, r = answer?.retention;
  const arrays = [o?.intervals, o?.gaps, o?.capture_restarts, c?.planned_blocks, c?.outside_plan, c?.unknown_plan_spans, answer?.sessions, answer?.plans, answer?.digests];
  const ok = answer?.api_version === 1 && answer.charger_id === asked.charger && w?.zone === asked.zone
    && typeof w.local_since === 'string' && w.local_since.startsWith(`${asked.day}T00:00`) && w.local_until?.startsWith?.(addDays(asked.day, 1))
    && Number.isFinite(instant(w.since)) && Number.isFinite(instant(w.until)) && instant(w.until) > instant(w.since)
    && arrays.every(Array.isArray) && o.coverage && typeof o.coverage === 'object' && o.energy && typeof o.energy === 'object' && r && typeof r === 'object'
    && arrays.slice(0, 7).every(list => list.length <= 200)
    && arrays[0].every(i => Number.isFinite(instant(i?.first_sample)) && Number.isFinite(instant(i?.last_sample)))
    && arrays[3].every(b => Number.isFinite(instant(b?.start)) && Number.isFinite(instant(b?.end)) && typeof b.verdict === 'string')
    && arrays[4].every(x => Number.isFinite(instant(x?.start)) && Number.isFinite(instant(x?.end)) && typeof x.kind === 'string')
    && arrays[6].every(s => s && typeof s === 'object' && Number.isFinite(instant(s.start)) && Number.isFinite(instant(s.end)));
  return !!ok;
}

const VERDICT = { flow_observed: 'Flow observed', no_flow_observed: 'No flow observed', unknown: 'Unknown' };
const OUTSIDE = { outside_plan: 'Flow outside the sent plan', plan_unknown: 'Flow while the sent plan was unknown', no_plan_evidence: 'Flow with no plan evidence' };
const REASON = { block_starts_before_retained_evidence: 'starts before the retained evidence', block_starts_before_retained_power: 'starts before the retained power rows',
  no_power_samples: 'no measured power rows', partial_coverage: 'measured rows do not cover the whole block', unplaced_meter_energy: 'meter energy with no known time overlaps it' };
const RECON = { reconciled: 'Register total reconciled', consistent: 'Register total matches placed energy', inconsistent: 'Register total disagrees with placed energy',
  unknown: 'Register total unknown', uncertain: 'Register total uncertain', skipped: 'Register total not checked' };
const words = text => String(text ?? 'unknown').replace(/_/g, ' ');


const bounded = (a, b, lo, hi) => { const s = Math.max(a, lo), e = Math.min(b, hi); return Number.isFinite(s) && Number.isFinite(e) && e > s ? { start: s, end: e } : null; };
/**
 * Numeric spans for the aligned price-axis tracks (7.3b): validated absolute instants (ms) straight from the backend answer,
 * clipped to the loaded day window; never parsed from the display strings above. Flow and its verdicts are the backend's.
 */
export function historyTracks(answer, { raw, since, until, oldestPower, digest, readAt, zone, day }) {
  const o = answer.observed, c = answer.comparison, cov = o.coverage;
  const known = [], unknown = [];
  const addBlock = (b, summary) => {
    const a = instant(b.start), e = instant(b.end), u = instant(b.intent_uncertain_after);
    const limit = num(b.limit) ? b.limit : null, unit = typeof b.unit === 'string' ? b.unit : '';
    const cut = Number.isFinite(u) && u < e ? Math.max(a, u) : e;
    const k = bounded(a, cut, since, until);
    if (k) known.push({ ...k, version: b.version ?? null, limit, unit, summary });
    const rest = cut < e ? bounded(cut, e, since, until) : null;
    if (rest) unknown.push({ ...rest, reason: 'intent_uncertain' });
  };
  if (raw === 'digest_only' && digest) (digest.planned_blocks || []).forEach(b => addBlock(b, true));
  else c.planned_blocks.forEach(b => addBlock(b, false));
  for (const u of c.unknown_plan_spans) {
    const span = bounded(instant(u.from), u.until ? instant(u.until) : until, since, until);
    if (span) unknown.push({ ...span, reason: u.reason });
  }
  const detail = raw === 'full' || raw === 'partial';
  const measured = { detail, note: '', flow: [], outside: [], noFlow: [], unknown: [] };
  if (!detail) measured.note = raw === 'digest_only' ? 'Only the saved day summary remains, so no measured flow is drawn (see the history panel).' : 'No measured power rows are kept for this day.';
  else {
    const upto = Number.isFinite(readAt) ? Math.min(until, readAt) : until;
    for (const i of o.intervals) {
      const a = instant(i.first_sample), b = Math.max(instant(i.last_sample), a + 60000), span = bounded(a, b, since, until);
      if (span) measured.flow.push({ ...span, startBounded: i.start_bounded === true, endBounded: i.end_bounded === true, peakW: num(i.peak_w) ? i.peak_w : null });
    }
    for (const x of c.outside_plan) { const span = bounded(instant(x.start), instant(x.end), since, until); if (span) measured.outside.push({ ...span, kind: x.kind }); }
    for (const b of c.planned_blocks) if (b.verdict === 'no_flow_observed') { const span = bounded(instant(b.start), instant(b.end), since, upto); if (span) measured.noFlow.push(span); }
    // Whole-window quiet only when the backend reports NO observed flow at all (no interval, outside-plan row or isolated sample)
    // and its coverage says the entire window was measured and trusted; otherwise quiet time stays unknown, never invented.
    const wholeWindow = nonneg(cov.window_seconds) && cov.window_seconds > 0 && cov.trusted_seconds >= cov.window_seconds && cov.window_seconds * 1000 >= upto - since - MINUTE;
    if (cov.no_data_seconds === 0 && cov.untrusted_seconds === 0 && wholeWindow && o.intervals.length === 0 && c.outside_plan.length === 0 && o.isolated_flow_samples === 0
      && Number.isFinite(upto) && upto > since) measured.noFlow.push({ start: since, end: upto });
    // A gap row with no end is one unreadable reading (a single capture tick), not an open-ended outage.
    for (const g of o.gaps) { const span = bounded(instant(g.from), g.to ? instant(g.to) : instant(g.from) + 60000, since, until); if (span) measured.unknown.push(span); }
    if (raw === 'partial' && Number.isFinite(oldestPower)) { const span = bounded(since, oldestPower, since, until); if (span) measured.unknown.push(span); }
  }
  const when = ms => { try { return new Intl.DateTimeFormat('en-GB', { timeZone: zone, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(ms); } catch { return 'unknown'; } };
  return { day, zone, coverage: [since, until], readAt, raw, sent: { known, unknown }, measured,
    coverageText: `History loaded for ${dayLabel(day)} only (${when(since)}–${when(until)}, ${zone}); other times are unknown` };
}

/** The display model of one validated answer; `fmt.stamp(iso)` formats an instant in the day's zone. */
export function buildHistoryModel(answer, day, fmt, readAt = NaN) {
  const since = instant(answer.window.since), until = instant(answer.window.until);
  const r = answer.retention, kinds = r.oldest_by_kind && typeof r.oldest_by_kind === 'object' ? r.oldest_by_kind : null;
  const signals = !!kinds && Array.isArray(r.digest_days) && answer.truncated && typeof answer.truncated === 'object';
  const oldestPower = kinds ? instant(kinds.power_w) : NaN;
  const digest = answer.digests.find(d => d?.date === day) || null;
  const o = answer.observed, cov = o.coverage;
  const stamp = iso => fmt.stamp(iso);
  const span = (a, b) => `${stamp(a)}–${stamp(b)}`;
  const limits = r.limits && nonneg(r.limits.max_samples_per_kind) ? r.limits : { max_samples_per_kind: 4320, max_age_days: 7, max_digest_days: 62 };
  const rawDays = Math.round(limits.max_samples_per_kind / 1440 * 10) / 10;
  const retentionNote = `Measured detail is kept for about the last ${rawDays} days at one reading per minute (${limits.max_samples_per_kind} rows per kind; the ${limits.max_age_days}-day age limit only applies to sparser rows), not a guaranteed ${limits.max_age_days} days. Day summaries are kept up to ${limits.max_digest_days} days, without price rows. Session records last longer but carry no per-minute evidence.`;

  // What raw measured flow can exist for this day: from the oldest retained power row, not from any plan or digest.
  let raw, rawNote;
  if (!kinds) { raw = 'unknown'; rawNote = 'This Home Assistant integration does not report which measured rows are retained, so what is missing cannot be told apart from what did not happen.'; }
  else if (!Number.isFinite(oldestPower) || oldestPower >= until) {
    const sent = answer.comparison.planned_blocks.length || answer.comparison.unknown_plan_spans.length || answer.plans.length || answer.sessions.length;
    raw = digest ? 'digest_only' : sent ? 'plan_only' : 'none';
    rawNote = digest ? 'The measured rows of this day are no longer kept; only its saved summary remains (no price rows, lists cut at 50 rows). The summary below is not live evidence.'
      : sent ? 'No measured power rows are kept for this day, so flow is unknown, not zero. Plans and sessions below are what was recorded.'
        : 'No charging evidence is kept for this day. That does not mean nothing happened.';
  } else if (oldestPower > since + PARTIAL_AFTER_S * 1000) { raw = 'partial'; rawNote = `Measured power rows are kept only from ${stamp(kinds.power_w)}; flow before that is unknown, not zero.`; }
  else raw = 'full';

  const truncated = [];
  if (signals) for (const [name, label] of LISTS) {
    const t = answer.truncated[name];
    if (t?.truncated === true && nonneg(t.cut)) truncated.push(`${label}: first ${t.limit ?? 200} shown, ${t.cut} more not shown`);
  }
  if (signals && answer.truncated.price_slices?.truncated === true) truncated.push(`price slices of ${answer.truncated.price_slices.sessions?.length ?? 'some'} session(s): ${answer.truncated.price_slices.cut} not shown`);
  if (!signals && answer.plans_truncated === true) truncated.push('plan versions: the list is cut');

  // The sent plan: acknowledged intent only (known), with spans the events no longer support shown as unknown.
  const blocks = answer.comparison.planned_blocks.map(b => ({ kind: 'known', start: instant(b.start), version: b.version ?? null,
    text: `${span(b.start, b.end)} · limit ${b.limit}${b.unit ? ` ${b.unit}` : ''} · plan ${b.version ?? 'unknown'}`, verdict: b.verdict,
    verdictText: VERDICT[b.verdict] || 'Unknown',
    detail: [...(b.reasons || []).map(x => REASON[x] || words(x)), b.intent_uncertain_after ? `intent uncertain after ${stamp(b.intent_uncertain_after)}` : '',
      b.open_ended_in_profile ? 'open-ended in the profile' : '', nonneg(b.covered_fraction) ? `measured rows cover ${Math.round(b.covered_fraction * 100)}% of the block` : ''].filter(Boolean).join(' · ') }));
  const unknown = answer.comparison.unknown_plan_spans.map(u => ({ kind: 'unknown', start: instant(u.from), version: null,
    text: `${stamp(u.from)}–${u.until ? stamp(u.until) : 'end of day'} · what the charger had installed is unknown`, verdict: 'unknown', verdictText: 'Plan unknown',
    detail: words(u.reason) }));
  const sent = [...blocks, ...unknown].sort((a, b) => a.start - b.start);

  const edge = bounded => bounded === true ? 'bounded' : 'open (data gap, restart or data start beside it)';
  const flow = o.intervals.map(i => ({ text: `${span(i.first_sample, i.last_sample)} · ${i.samples ?? '?'} readings · peak ${num(i.peak_w) ? `${(i.peak_w / 1000).toFixed(1)} kW` : 'unknown'}`,
    detail: `start ${edge(i.start_bounded)} · end ${edge(i.end_bounded)}` }));
  const outside = answer.comparison.outside_plan.map(x => ({ kind: x.kind, text: `${OUTSIDE[x.kind] || words(x.kind)}: ${span(x.start, x.end)} · ${duration(x.seconds)}` }));

  const energy = o.energy, cvg = energy.coverage || {};
  const basis = (label, value, key, note) => ({ label, value: value === null || value === undefined ? null : value, text: value === null || value === undefined
    ? `${label}: unavailable (no measurement segment in this day)` : `${label}: ${kwh(value)}`,
    detail: `${cvg[key]?.segments ?? 0} segment(s), ${duration(cvg[key]?.seconds)}${note ? ` · ${note}` : ''}` });
  const energyRows = [
    basis('Meter-counter delta', energy.meter_counter_kwh, 'meter', 'placed in time by observed readings'),
    basis('Power-integrated estimate', energy.power_integrated_estimate_kwh, 'power', 'an estimate from power readings'),
    basis('Meter energy with unknown placement', energy.meter_counter_unobserved_kwh, 'unobserved', 'happened while capture was not watching; no known time'),
  ];
  const energyNotes = [`These bases are separate measurements of the same charging and are never added together.`,
    nonneg(energy.unknown_seconds) && energy.unknown_seconds > 0 ? `${duration(energy.unknown_seconds)} of energy could not be measured (${Object.entries(energy.unknown_segments || {}).map(([k, n]) => `${words(k)} ×${n}`).join(', ') || 'unknown cause'}).` : '',
    Array.isArray(energy.edge_segments_not_prorated) && energy.edge_segments_not_prorated.length ? `${energy.edge_segments_not_prorated.length} segment(s) cross the day boundary and are not counted here.` : ''].filter(Boolean);

  const sessions = answer.sessions.map(s => {
    const rec = s.reconciliation && typeof s.reconciliation === 'object' ? s.reconciliation : null;
    const lines = [];
    if (rec) {
      lines.push(`${RECON[rec.state] || `Register total ${words(rec.state)}`}${rec.reason ? ` (${words(rec.reason)})` : ''}`);
      if (nonneg(rec.total_kwh) && ['reconciled', 'consistent'].includes(rec.state)) lines.push(`Register total ${kwh(rec.total_kwh)} against ${kwh(rec.placed_kwh)} placed in time`);
      if (nonneg(rec.unplaced_late_kwh) && rec.unplaced_late_kwh > 0) lines.push(`Unplaced late energy ${kwh(rec.unplaced_late_kwh)}: no known time, not part of the placed energy above, not priced`);
      if (nonneg(rec.unassigned_register_kwh) && rec.unassigned_register_kwh > 0) lines.push(`Later register rise ${kwh(rec.unassigned_register_kwh)}: seen by receipt time only, not assigned to this session`);
      if (['uncertain', 'unknown', 'skipped', 'inconsistent'].includes(rec.state) || (nonneg(rec.unassigned_register_kwh) && rec.unassigned_register_kwh > 0)) lines.push('The session total is not certified');
    } else lines.push('Register reconciliation unavailable');
    return { text: `${span(s.start, s.end)} · placed energy ${kwh(s.energy_kwh)} (source: ${words(s.energy_source)})`, lines,
      detail: `${words(s.source)} · started by ${words(s.started_by)}${s.price_slices_truncated === true ? ` · ${s.price_slices_cut} price slice(s) not shown` : ''}` };
  });

  const gaps = o.gaps.map(g => `${words(g.kind)} ${stamp(g.from)}${g.to ? `–${stamp(g.to)}` : ''}${g.reason ? ` (${words(g.reason)})` : ''}`);
  const restarts = o.capture_restarts.map(stamp);
  const unacked = answer.plans.filter(p => p?.acked_intent !== true).length;

  const digestModel = digest ? {
    partial: digest.partial_retention === true, computed: digest.computed_at ? stamp(digest.computed_at) : null,
    flow: (digest.observed_intervals || []).map(i => ({ text: `${span(i.first_sample, i.last_sample)} · ${i.samples ?? '?'} readings · peak ${num(i.peak_w) ? `${(i.peak_w / 1000).toFixed(1)} kW` : 'unknown'}`, detail: `start ${edge(i.start_bounded)} · end ${edge(i.end_bounded)}` })),
    blocks: (digest.planned_blocks || []).map(b => ({ text: `${span(b.start, b.end)} · limit ${b.limit} · plan ${b.version ?? 'unknown'}`, verdictText: VERDICT[b.verdict] || 'Unknown', verdict: b.verdict })),
    outside: (digest.outside_plan || []).map(x => `${OUTSIDE[x.kind] || words(x.kind)}: ${span(x.start, x.end)}`),
    unknownSpans: (digest.unknown_plan_spans || []).length, gapCount: digest.gap_count ?? null, restartCount: digest.restart_count ?? null,
    coverage: digest.coverage ? `${duration(digest.coverage.trusted_seconds)} measured, ${duration(digest.coverage.untrusted_seconds)} untrusted, ${duration(digest.coverage.no_data_seconds)} no data` : null,
    energy: digest.energy ? [basis('Meter-counter delta', digest.energy.meter_counter_kwh, 'meter'), basis('Power-integrated estimate', digest.energy.power_integrated_estimate_kwh, 'power')].map(row => ({ ...row, detail: '' })) : [],
  } : null;

  return {
    state: 'ready', day, zone: answer.window.zone, raw, rawNote, retentionNote, legacy: !signals, truncated, partial: truncated.length > 0,
    retention: { oldestPower: kinds?.power_w ? stamp(kinds.power_w) : null, oldestRegister: kinds?.energy_register_kwh ? stamp(kinds.energy_register_kwh) : null,
      digestDays: signals ? r.digest_days.length : null, newestDigest: signals && r.digest_days.length ? r.digest_days.at(-1) : null },
    coverage: { text: `Measured power covers ${duration(cov.trusted_seconds)} of ${duration(cov.window_seconds)}; ${duration(cov.untrusted_seconds)} untrusted; ${duration(cov.no_data_seconds)} with no data (unknown, not zero).`,
      none: !nonneg(cov.trusted_seconds) },
    sent, flow, outside, energyRows, energyNotes, sessions, gaps, restarts, unacked, digest: digestModel,
    tracks: historyTracks(answer, { raw, since, until, oldestPower, digest, readAt, zone: answer.window.zone, day }),
    isolated: nonneg(o.isolated_flow_samples) && o.isolated_flow_samples > 0 ? `${o.isolated_flow_samples} single reading(s) above the flow threshold were not enough to count as charging.` : '',
    flowNote: 'Flow comes only from measured power readings (threshold about 100 W, unverified for the installed charger). A plan, its acknowledgement, a limit read back, the battery level or the charger status never counts as flow.',
    sentNote: 'Sent means the charger answered a plan version as accepted, not that it was installed or that charging happened. After an uncertain write the plan is unknown.',
  };
}

/**
 * `request(params)` resolves the backend answer (live: the WebSocket, preview: a fixture of the same shape).
 * `onChange()` fires when an asynchronous result changed what to draw.
 */
export function createHistoryDay({ request, onChange = () => {}, now = () => Date.now() }) {
  let ctx = null, key = null, seq = 0;
  const initial = () => ({ sel: { kind: 'today' }, loading: null, result: null, error: null });
  let st = initial();
  const reset = () => { seq++; st = initial(); };
  const keyOf = c => JSON.stringify([c.charger, c.epoch, c.zone]);
  const effective = () => st.sel.kind === 'today' ? ctx.today : st.sel.day;
  const fmtFor = c => ({ stamp: iso => {
    const t = instant(iso); if (!Number.isFinite(t)) return 'unknown time';
    try {
      const time = new Intl.DateTimeFormat('en-GB', { timeZone: c.zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(t);
      const date = localDate(t, c.zone);
      return date === (c.shownDay || date) ? time : `${time} (${new Intl.DateTimeFormat('en-GB', { timeZone: c.zone, day: 'numeric', month: 'short' }).format(t)})`;
    } catch { return String(iso); }
  } });
  const failure = error => {
    const code = typeof error?.code === 'string' ? error.code : '';
    if (/unauthorized|permission|forbidden/i.test(code)) return { state: 'permission', message: 'You do not have permission to read charging history.' };
    if (code === 'spotnav_history_unavailable') return { state: 'unavailable', message: 'Charging evidence is not kept for this installation, so there is no history to show.' };
    if (code === 'spotnav_unsupported_api_version') return { state: 'error', message: 'The installed integration does not speak this history version; update the integration and card together.' };
    if (error?.message === 'invalid') return { state: 'invalid', message: 'The history answer could not be understood and was not shown.' };
    return { state: 'error', message: 'Charging history could not be read.' };
  };

  async function load(day, { silent = false } = {}) {
    const mine = ++seq, myKey = key, asked = { charger: ctx.charger, day, zone: ctx.zone }, asCtx = { ...ctx, shownDay: day };
    if (!silent) { st.result = null; st.loading = { day }; }
    st.error = null;
    try {
      const answer = await request({ date: day });
      if (mine !== seq || myKey !== key) return;
      if (!validateHistory(answer, asked)) throw new Error('invalid');
      const at = now();
      st.result = { day, at, model: buildHistoryModel(answer, day, fmtFor(asCtx), at) };
    } catch (error) {
      if (mine !== seq || myKey !== key) return;
      // A failed refresh keeps the earlier read clearly stale and waits for an explicit retry.
      if (silent && st.result) { st.result = { ...st.result, refreshFailed: true }; st.error = { day, ...failure(error) }; }
      else { st.error = { day, ...failure(error) }; st.result = null; }
    }
    st.loading = null;
    onChange();
  }

  return {
    /** Tell it who is asking. A change of charger, generation/permission epoch or zone drops everything. */
    sync(next) {
      const valid = !!(next && next.charger && typeof next.zone === 'string' && next.zone && Number.isFinite(ms(next.today)));
      const nextKey = valid ? keyOf(next) : null;
      if (nextKey !== key) { reset(); key = nextKey; }
      ctx = valid ? next : null;
      if (!ctx) return this;
      const day = effective();
      if (st.loading) return this;
      if (st.error?.day === day) return this; // never repeats on its own
      if (st.result?.day !== day) void load(day);
      else if (st.sel.kind === 'today' && now() - st.result.at > REFRESH_TODAY_MS) void load(day, { silent: true });
      return this;
    },
    /** `today`, `yesterday`, `prev`, `next` or an explicit `day`; only days inside the retained range are accepted. */
    select(kind, day) {
      if (!ctx) return;
      const shown = effective();
      const target = kind === 'today' ? ctx.today : kind === 'yesterday' ? addDays(ctx.today, -1) : kind === 'prev' ? addDays(shown, -1) : kind === 'next' ? addDays(shown, 1) : day;
      if (!Number.isFinite(ms(target)) || ms(target) > ms(ctx.today) || ms(target) < ms(addDays(ctx.today, -HISTORY_DAYS_BACK))) return;
      st.sel = target === ctx.today ? { kind: 'today' } : { kind: 'day', day: target };
      st.error = null; st.loading = null; st.result = null;
      void load(target);
      onChange();
    },
    retry() {
      if (!ctx || st.loading || !st.error) return;
      void load(effective());
      onChange();
    },
    view() {
      if (!ctx) return { state: 'unavailable', message: ZONE_FAILED, nav: null };
      const shown = effective(), oldest = addDays(ctx.today, -HISTORY_DAYS_BACK);
      const nav = { day: shown, label: dayLabel(shown), isToday: shown === ctx.today, min: oldest, max: ctx.today, zone: ctx.zone,
        zoneNote: ctx.marketZone && ctx.marketZone !== ctx.zone ? `Days follow Home Assistant time (${ctx.zone}); the price chart follows ${ctx.marketZone}, so a day here is not the chart's day.` : `Day in Home Assistant time (${ctx.zone}).`,
        canPrev: ms(shown) > ms(oldest), canNext: ms(shown) < ms(ctx.today), canRetry: !!st.error && !st.loading, loading: !!st.loading };
      if (st.loading) return { state: 'loading', message: `Loading charging history for ${dayLabel(shown)}…`, nav };
      if (st.error && st.result?.day === shown && st.result.refreshFailed) return { ...st.result.model, refreshFailed: true, nav };
      if (st.error) return { state: st.error.state, message: st.error.message, nav };
      if (st.result?.day === shown) return { ...st.result.model, refreshFailed: st.result.refreshFailed === true, nav };
      return { state: 'loading', message: `Loading charging history for ${dayLabel(shown)}…`, nav };
    },
    dispose() { seq++; ctx = null; key = null; st = initial(); },
  };
}
