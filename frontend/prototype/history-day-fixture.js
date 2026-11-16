// Fictional one-day answers in the exact shape of `spotnav/get_charging_history` (api_version 1, with the 7.3a
// `truncated` and `retention.oldest_by_kind/digest_days/limits` signals), for the local preview and the tests.
// Zone Etc/UTC; today is the sample's fixed day. Each day exercises one backend situation; none is real history.
export const HISTORY_TODAY = '2026-11-09';
export const HISTORY_ZONE = 'Etc/UTC';
const at = (day, hh, mm = 0) => `${day}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00+00:00`;
const next = day => new Date(Date.parse(`${day}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
const cap = (cut = 0, limit = 200) => ({ truncated: cut > 0, cut, limit });
const noCuts = () => ({ plans: cap(), intervals: cap(), gaps: cap(), restarts: cap(), planned_blocks: cap(), outside_plan: cap(),
  unknown_plan_spans: cap(), sessions: cap(), price_slices: { truncated: false, cut: 0, limit: 200, per: 'session', sessions: [] } });
const coverage = (trusted, untrusted, window = 86400) => ({ power_samples_in_retention: true, trusted_seconds: trusted, untrusted_seconds: untrusted,
  no_data_seconds: window - trusted - untrusted, window_seconds: window, resolution_note: 'samples are at most one per capture tick' });
const energy = (meter, power, unobserved = null) => ({ meter_counter_kwh: meter, meter_counter_unobserved_kwh: unobserved, power_integrated_estimate_kwh: power,
  coverage: { meter: { segments: meter === null ? 0 : 40, seconds: meter === null ? 0 : 2400 }, unobserved: { segments: unobserved === null ? 0 : 1, seconds: unobserved === null ? 0 : 900 },
    power: { segments: power === null ? 0 : 41, seconds: power === null ? 0 : 2460 } },
  unknown_segments: {}, unknown_seconds: 0, edge_segments_not_prorated: [], note: 'null means no measurement segment lay inside the window' });
const interval = (day, a, b, o = {}) => ({ first_sample: at(day, ...a), last_sample: at(day, ...b), start_earliest: at(day, a[0], Math.max(0, (a[1] || 0) - 1)), start_latest: at(day, ...a),
  end_earliest: at(day, ...b), end_latest: at(day, b[0], (b[1] || 0) + 1), start_bounded: true, end_bounded: true, samples: 41, peak_w: 6800, basis: 'measured_power', ...o });
const block = (day, a, b, verdict, o = {}) => ({ version: 'p1', start: at(day, ...a), end: at(day, ...b), limit: 16, unit: 'A', open_ended_in_profile: false,
  intent_uncertain_after: null, verdict, reasons: [], covered_fraction: 1, power_flow_overlap: verdict === 'flow_observed', meter_counter_kwh_inside: 0, meter_counter_kwh_unplaced_overlap: 0, ...o });
const prov = { basis: 'recorder_register_pair', endpoint: null, when_delivered: 'unknown', note: '', window_seconds: 21600 };
// A session evaluated against the register (late evidence kept) and one that never was (no stored record).
const recon = (state, o = {}) => ({ state, reason: null, placed_kwh: 8.2, total_kwh: null, unplaced_late_kwh: null, placement: null, placement_reasons: [], final: false,
  quality: [], register_open_kwh: 100, register_close_kwh: 108.2, unassigned_register_kwh: null, evaluated_at: at('2026-11-09', 6), provenance: prov, ...o });
const reconMissing = () => ({ state: 'unknown', reason: 'register_pair_missing', placed_kwh: 8.2, total_kwh: null, unplaced_late_kwh: null, placement: null, placement_reasons: [], final: false, provenance: prov });
const session = (day, a, b, o = {}) => ({ id: `s-${day}`, start: at(day, ...a), end: at(day, ...b), energy_kwh: 8.2, energy_source: 'register', source: 'morek', started_by: 'auto',
  area_id: 'SAMPLE-1', cost: null, cost_basis: 'not_recomputed_here', price_slices: [], price_slices_truncated: false, price_slices_cut: 0, association: 'time_overlap_only',
  reconciliation: recon('consistent', { total_kwh: 8.2 }), overlapping_observed_intervals: 1, ...o });
const retention = (oldestPower, digestDays = ['2026-11-05']) => ({ oldest_evidence: at('2026-11-02', 22), window_starts_before_oldest_evidence: false,
  oldest_by_kind: { power_w: oldestPower, current_a: null, energy_register_kwh: oldestPower, status: null }, digest_days: digestDays,
  limits: { max_samples_per_kind: 4320, max_age_days: 7, max_digest_days: 62 }, note: 'raw rows are bounded by age and count' });

function base(charger, day, over) {
  return { api_version: 1, charger_id: charger,
    window: { since: at(day, 0), until: at(next(day), 0), zone: HISTORY_ZONE, local_since: at(day, 0), local_until: at(next(day), 0) },
    retention: retention(at('2026-11-07', 9)), provenance: { flow_source: 'measured power_w samples only', min_flow_w: 100 },
    plans: [], plans_truncated: false, truncated: noCuts(), price_snapshots: {},
    observed: { intervals: [], isolated_flow_samples: 0, coverage: coverage(0, 0), energy: energy(null, null), gaps: [], capture_restarts: [] },
    comparison: { planned_blocks: [], outside_plan: [], unknown_plan_spans: [], basis: 'acknowledged_intent_known_spans_only' },
    sessions: [], digests: [], ...over };
}

const plan = id => ({ id, acked_intent: true, intent: 'schedule', dispatch_state: 'ack_received', acked_at: at('2026-11-08', 1) });
const digest = day => ({ date: day, zone: HISTORY_ZONE, computed_at: at(next(day), 0, 20), partial_retention: false, raw_prices_retained: false, plans_applied: [],
  observed_intervals: [interval(day, [2, 5], [2, 55], { start_bounded: true })], isolated_flow_samples: 0, coverage: coverage(80000, 0), energy: energy(7.9, 8.1),
  planned_blocks: [{ version: 'p1', start: at(day, 2), end: at(day, 3), limit: 16, verdict: 'flow_observed', covered_fraction: 1 }],
  outside_plan: [], unknown_plan_spans: [], gap_count: 1, restart_count: 0 });

/** The sample's days: what each one demonstrates. */
export const SCENARIOS = {
  '2026-11-09': 'full evidence, flow in a sent block',
  '2026-11-08': 'unknown plan span, flow outside the plan, truncated lists, uncertain session',
  '2026-11-07': 'raw power rows begin mid-day (partial)',
  '2026-11-06': 'plans and a session but no retained power rows',
  '2026-11-05': 'raw pruned, day summary only',
  '2026-11-04': 'nothing retained',
  '2026-11-03': 'older integration (no truncation or retention signals)',
  '2026-11-02': 'history evidence not kept',
  '2026-11-01': 'request failure',
};

export function historyAnswer(charger, day) {
  switch (day) {
    case '2026-11-09': return base(charger, day, { plans: [plan('p1')], observed: { intervals: [interval(day, [2, 5], [2, 55])], isolated_flow_samples: 0,
      coverage: coverage(52000, 0, 52800), energy: energy(7.9, 8.1), gaps: [], capture_restarts: [] },
      comparison: { planned_blocks: [block(day, [2], [3], 'flow_observed')], outside_plan: [], unknown_plan_spans: [], basis: 'acknowledged_intent_known_spans_only' },
      sessions: [session(day, [2, 3], [2, 58])] });
    case '2026-11-08': {
      const gaps = Array.from({ length: 200 }, (_, i) => ({ kind: 'power_w', from: at(day, 5, i % 60), to: null, reason: 'unreadable', source: 'ha' }));
      return base(charger, day, { plans: [plan('p1'), plan('p2')], truncated: { ...noCuts(), gaps: cap(12) },
        observed: { intervals: [interval(day, [21, 50], [22, 5], { end_bounded: false, end_latest: null, samples: 16 }), interval(day, [23, 10], [23, 40])], isolated_flow_samples: 2,
          coverage: coverage(70000, 4000), energy: energy(6.5, 6.9, 1.4), gaps, capture_restarts: [at(day, 22, 20)] },
        comparison: { planned_blocks: [block(day, [22], [23], 'unknown', { reasons: ['partial_coverage'], covered_fraction: 0.62, intent_uncertain_after: at(day, 22, 30) })],
          outside_plan: [{ interval: 0, start: at(day, 21, 50), end: at(day, 22), seconds: 600, kind: 'outside_plan', tolerance_seconds: 120 }, { interval: 1, start: at(day, 23, 10), end: at(day, 23, 40), seconds: 1800, kind: 'plan_unknown' }],
          unknown_plan_spans: [{ from: at(day, 22, 30), until: null, reason: 'dispatch_started' }], basis: 'acknowledged_intent_known_spans_only' },
        sessions: [session(day, [21, 45], [23, 45], { reconciliation: recon('uncertain', { reason: 'late_register_unassigned', unplaced_late_kwh: 1.4, unassigned_register_kwh: 0.6 }) })] });
    }
    case '2026-11-07': return base(charger, day, { retention: retention(at(day, 9), ['2026-11-05']), observed: { intervals: [interval(day, [10, 0], [10, 50])], isolated_flow_samples: 0,
      coverage: coverage(50000, 0), energy: energy(7.1, 7.3), gaps: [], capture_restarts: [] } });
    case '2026-11-06': return base(charger, day, { retention: retention(at('2026-11-07', 9)), plans: [plan('p1')],
      observed: { intervals: [], isolated_flow_samples: 0, coverage: { ...coverage(0, 0), power_samples_in_retention: true }, energy: energy(null, null), gaps: [], capture_restarts: [] },
      comparison: { planned_blocks: [block(day, [2], [3], 'unknown', { reasons: ['block_starts_before_retained_power', 'partial_coverage'], covered_fraction: 0 })], outside_plan: [], unknown_plan_spans: [], basis: 'acknowledged_intent_known_spans_only' },
      sessions: [session(day, [2, 3], [2, 58], { reconciliation: reconMissing() })] });
    case '2026-11-05': return base(charger, day, { retention: retention(at('2026-11-07', 9)), digests: [digest(day)] });
    case '2026-11-04': return base(charger, day, { retention: retention(at('2026-11-07', 9), []) });
    case '2026-11-03': { const old = base(charger, day, {}); delete old.truncated; old.retention = { oldest_evidence: at('2026-11-02', 22), window_starts_before_oldest_evidence: true, note: '' }; return old; }
    default: return base(charger, day, {});
  }
}

/** What the backend answers for `{date}` (`request` for `createHistoryDay`); failures carry the backend's stable codes. */
export function fixtureHistoryRequest(context) {
  return async params => {
    if (params.date === '2026-11-02') throw Object.assign(new Error('refused'), { code: 'spotnav_history_unavailable' });
    if (params.date === '2026-11-01') throw new Error('timeout');
    return historyAnswer(context.charger, params.date);
  };
}
