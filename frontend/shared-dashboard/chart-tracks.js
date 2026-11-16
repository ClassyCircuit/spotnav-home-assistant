// Aligned evidence tracks under the price chart (Stage 7.3b). Pure: it only arranges what other models already say on the
// chart's own time axis, so zoom and pan stay aligned by construction. It never plans, classifies or reads a charger.
//
// Four lanes, each a complete tiling of the chart horizon so that no moment is ever "absent":
//   Proposal  - the CURRENT calculated plan, future/now only (nothing is invented for the past).
//   Sent      - plan versions the charger acknowledged, only where the loaded history day knows them; unknown after an
//               uncertain write; nothing outside the loaded day.
//   Effective - the latest FRESH readback's remaining period only (a reported limit, not power, not inventory, not history).
//   Measured  - the backend's observed power-flow intervals of the loaded history day, with bounded/open edges and gaps.
// Anything not known is `unknown` / `unloaded` (hatched), never empty. All times here are axis units (live: epoch ms;
// preview: the sample's hours); `toAxis` converts the absolute instants (ms) of history and readback.

const finite = Number.isFinite;
const sameKey = (a, b) => a.kind === b.kind && a.text === b.text && a.label === b.label && a.version === b.version && !!a.stale === !!b.stale && !!a.differs === !!b.differs;

/**
 * Tile [h0,h1]. `baseAt(mid)` is the layer-0 piece; `cuts` are the base's own boundaries. A higher `layer` wins;
 * two different spans in the same layer disagree, which is shown as unknown rather than picking one.
 */
export function tile(h0, h1, baseAt, cuts, segments) {
  const valid = segments.filter(s => finite(s.start) && finite(s.end) && s.end > s.start && s.end > h0 && s.start < h1);
  const points = new Set([h0, h1]);
  for (const c of cuts) if (finite(c) && c > h0 && c < h1) points.add(c);
  for (const s of valid) { if (s.start > h0) points.add(s.start); if (s.end < h1) points.add(s.end); }
  const xs = [...points].sort((a, b) => a - b), out = [];
  for (let i = 0; i < xs.length - 1; i++) {
    const a = xs[i], b = xs[i + 1], mid = (a + b) / 2;
    const cover = valid.filter(s => s.start <= mid && mid < s.end);
    let piece;
    if (!cover.length) piece = { ...baseAt(mid) };
    else {
      const top = Math.max(...cover.map(s => s.layer || 1)), hit = cover.filter(s => (s.layer || 1) === top);
      piece = hit.every(s => sameKey(s, hit[0])) ? { ...hit[0] } : { kind: 'unknown', label: 'conflict', text: 'Conflicting evidence: spans overlap here, so this time is unknown.', conflict: true };
      piece.openStart = hit.some(s => s.openStart && s.start === a);
      piece.openEnd = hit.some(s => s.openEnd && s.end === b);
    }
    delete piece.layer;
    piece.start = a; piece.end = b;
    const last = out.at(-1);
    if (last && last.end === a && sameKey(last, piece) && !last.openEnd && !piece.openStart) { last.end = b; last.openEnd = piece.openEnd; }
    else out.push(piece);
  }
  return out;
}

const piece = (kind, label, text) => ({ kind, label, text });
const peak = w => finite(w) ? `${(w / 1000).toFixed(1)} kW` : 'unknown';

function proposalLane({ horizon: [h0, h1], now, windows }) {
  const known = Array.isArray(windows);
  const segments = known ? windows.filter(w => w && finite(w.start) && finite(w.end) && w.end > w.start && w.end > now).map(w => {
    const exception = w.control === 'minimum-exception', reserve = finite(w.reserveMinutes) && w.reserveMinutes > 0;
    return { start: Math.max(w.start, now), end: w.end, layer: 1, kind: exception ? 'proposal-exception' : 'proposal', label: exception ? 'above-cap minimum' : 'proposal',
      text: `Proposed charging (calculated, not sent)${exception ? ' · above-cap minimum' : ''}${reserve ? ` · includes ${Math.round(w.reserveMinutes)} min reserve` : ''}` };
  }) : [];
  const baseAt = mid => !known ? piece('unknown', 'no proposal', 'No current proposal: it is stale, unavailable or not calculated.')
    : mid < now ? piece('unknown', 'past', 'Past time: the current proposal does not describe it.') : piece('none', '', 'No proposed charging here.');
  return { key: 'proposal', caption: 'Proposal · current calculated plan',
    note: h1 <= now ? 'Past day: the current proposal never describes it, so no proposal is drawn.' : known ? 'Not sent; for now and later only. Past time is hatched, not “no plan”.' : 'No current proposal to show.', segments: tile(h0, h1, baseAt, [now], segments) };
}

function sentLane({ horizon: [h0, h1], toAxis, tracks, message }) {
  if (!tracks) return { key: 'sent', caption: 'Sent · acknowledged plan versions', note: message || 'Charging history is not loaded; nothing is known about what was sent.',
    segments: tile(h0, h1, () => piece('unloaded', 'not loaded', 'Charging history is not loaded for this time.'), [], []) };
  const [c0, c1] = tracks.coverage.map(toAxis);
  const segments = [
    ...tracks.sent.known.map(b => ({ start: toAxis(b.start), end: toAxis(b.end), layer: 1, kind: b.summary ? 'sent-summary' : 'sent', version: b.version ?? null,
      label: `${b.version ?? 'plan ?'}${finite(b.limit) ? ` · ${b.limit}${b.unit ? ` ${b.unit}` : ''}` : ''}`,
      text: `${b.summary ? 'Saved day summary: ' : ''}Plan version ${b.version ?? 'unknown'} was acknowledged by the charger${finite(b.limit) ? ` with limit ${b.limit}${b.unit ? ` ${b.unit}` : ''}` : ''}. Acknowledged is not installed and not charging.` })),
    ...tracks.sent.unknown.map(u => ({ start: toAxis(u.start), end: toAxis(u.end), layer: 2, kind: 'unknown', label: 'unknown', text: `What the charger had installed is unknown here (${String(u.reason || 'uncertain write').replace(/_/g, ' ')}).` })),
  ];
  const baseAt = mid => mid >= c0 && mid < c1 ? piece('unknown', 'no known plan', 'No acknowledged plan span is known here; that is not proof that nothing was installed.')
    : piece('unloaded', 'not loaded', 'The loaded history day does not cover this time, so it is unknown.');
  return { key: 'sent', caption: 'Sent · acknowledged plan versions', note: `${tracks.coverageText}. Each span names its own plan version.`, segments: tile(h0, h1, baseAt, [c0, c1], segments) };
}

function effectiveLane({ horizon: [h0, h1], now, toAxis, effective }) {
  const base = () => piece('unknown', 'unknown', effective?.state === 'reported' ? 'Outside the latest readback’s remaining period: unknown.' : (effective?.reason || 'No fresh readback.'));
  const ok = effective?.state === 'reported';
  const segments = ok ? effective.spans.map(s => ({ start: Math.max(toAxis(s.start), now), end: toAxis(s.end), layer: 1, kind: effective.differs ? 'effective-differs' : 'effective', differs: !!effective.differs,
    label: `${s.value} ${effective.unit || 'A'}`, text: `Reported effective limit ${s.value} ${effective.unit || 'A'} in the latest readback${effective.differs ? ' · the readback differs from the last sent schedule (reported difference)' : ''}. A reported limit is neither power nor proof of charging.` })) : [];
  return { key: 'effective', caption: 'Effective · latest readback, remaining period only',
    note: h1 <= now ? 'Past day: the latest readback never describes it, so no effective limit is drawn.' : ok ? `Read ${effective.readAtText || 'recently'}; never restored for past time. Not installed-profile inventory.` : (effective?.reason || 'No fresh readback; effective limits are unknown.'),
    segments: tile(h0, h1, base, [], segments) };
}

function measuredLane({ horizon: [h0, h1], now, toAxis, tracks, message, refreshFailed }) {
  if (!tracks) return { key: 'measured', caption: 'Measured · observed power flow', note: message || 'Charging history is not loaded; nothing is known about measured flow.',
    segments: tile(h0, h1, mid => mid < now ? piece('unloaded', 'not loaded', 'Charging history is not loaded for this time.') : piece('future', 'not yet', 'This time has not happened yet.'), [now], []) };
  const [c0, c1] = tracks.coverage.map(toAxis), M = tracks.measured, stale = !!refreshFailed;
  const fit = (a, b) => ({ start: toAxis(a), end: Math.min(toAxis(b), now) });
  const mk = (list, extra) => list.map(x => ({ ...fit(x.start, x.end), stale, ...extra(x) })).filter(s => s.end > s.start);
  const segments = M.detail ? [
    ...mk(M.noFlow, () => ({ layer: 1, kind: 'no-flow', label: 'no flow observed', text: 'No flow observed: measured readings cover this time and show none.' })),
    ...mk(M.flow, x => ({ layer: 1, kind: 'flow', label: peak(x.peakW), openStart: !x.startBounded, openEnd: !x.endBounded,
      text: `Flow observed (measured power, peak ${peak(x.peakW)})${x.startBounded ? '' : ' · start is open (a data gap, restart or the data start is beside it)'}${x.endBounded ? '' : ' · end is open'}.` })),
    ...mk(M.outside, x => ({ layer: 2, kind: `flow-${x.kind}`, label: { outside_plan: 'outside plan', plan_unknown: 'plan unknown', no_plan_evidence: 'no plan evidence' }[x.kind] || x.kind,
      text: { outside_plan: 'Flow outside the sent plan', plan_unknown: 'Flow while the sent plan was unknown', no_plan_evidence: 'Flow with no plan evidence' }[x.kind] || `Flow: ${x.kind}` })),
    ...mk(M.unknown, () => ({ layer: 3, kind: 'unknown', label: 'not measured', text: 'Not measured here (capture gap or rows no longer kept): unknown, not zero.' })),
  ] : [];
  const baseAt = mid => mid >= now ? piece('future', 'not yet', 'This time has not happened yet.')
    : mid >= c0 && mid < c1 ? piece('unknown', 'unknown', M.detail ? 'No measured classification here: unknown, not zero.' : `Detailed power is not kept for this day: unknown. ${M.note || ''}`.trim())
      : piece('unloaded', 'not loaded', 'The loaded history day does not cover this time, so it is unknown.');
  return { key: 'measured', caption: 'Measured · observed power flow',
    note: `${tracks.coverageText}.${stale ? ' Earlier read; the latest refresh failed.' : ''}${M.detail ? '' : ` ${M.note || 'No detailed power is drawn.'}`}`, segments: tile(h0, h1, baseAt, [c0, c1, now], segments) };
}

/**
 * @param {{horizon:[number,number], now:number, toAxis?:(ms:number)=>number, windows:Array|null, history:object|null, effective:object|null}} input
 * `history` is the 7.3a view (only `state==='ready'` carries `tracks`); `windows` is null when no CURRENT proposal exists.
 */
export function buildTracks({ horizon, now, toAxis = x => x, windows = null, history = null, effective = null }) {
  if (!Array.isArray(horizon) || horizon.length !== 2 || !horizon.every(finite) || !(horizon[0] < horizon[1]) || !finite(now)) return null;
  const tracks = history?.state === 'ready' && history.tracks ? history.tracks : null;
  const message = history?.message || (history ? '' : 'Charging history is not part of this view.');
  const ctx = { horizon, now, toAxis, tracks, message, refreshFailed: history?.refreshFailed === true };
  return { lanes: [proposalLane({ horizon, now, windows }), sentLane(ctx), effectiveLane({ horizon, now, toAxis, effective }), measuredLane(ctx)] };
}
