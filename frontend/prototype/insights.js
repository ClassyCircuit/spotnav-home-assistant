// Pure sample analytics. All times are fictional relative hours, not real timezones.
export function summarize(intervals, start, end) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  const entries = intervals.filter(p => Number.isFinite(p.start) && Number.isFinite(p.end) && p.end > p.start && Number.isFinite(p.cents) && p.end > start && p.start < end)
    .map(p => ({ start: Math.max(start,p.start), end: Math.min(end,p.end), cents:p.cents })).sort((a,b) => a.start-b.start);
  let covered = 0, weighted = 0, previousEnd = start;
  for (const p of entries) {
    // Overlapping input is ambiguous; do not double count or silently choose a tariff.
    if (p.start < previousEnd - 1e-9) return null;
    const duration = p.end-p.start;
    covered += duration; weighted += duration*p.cents; previousEnd = p.end;
  }
  const sorted = [...entries].sort((a,b)=>a.cents-b.cents);
  const percentile = fraction => {
    if (!covered) return null;
    let sum = 0;
    for (const p of sorted) { sum += p.end-p.start; if (sum >= covered*fraction - 1e-9) return p.cents; }
    return null;
  };
  return { count:entries.length, covered, expected:end-start, coverage:covered/(end-start), average:covered ? weighted/covered : null,
    low:sorted[0]?.cents ?? null, high:sorted.at(-1)?.cents ?? null, p25:percentile(.25), p75:percentile(.75) };
}

export function assess(current, history, start, end) {
  const baseline = summarize(history,start,end);
  const currentPrice = Number.isFinite(current) ? current : null;
  let label = 'Unknown';
  if (currentPrice != null && baseline && baseline.coverage >= .9 && baseline.count >= 24) {
    label = currentPrice < baseline.p25 ? 'Lower than usual' : currentPrice > baseline.p75 ? 'Higher than usual' : 'Typical for this sample';
  }
  return { currentPrice, baseline, label };
}

// Lowest complete one-hour price among starts at known interval boundaries or now.
// Partial future coverage is explicitly reported, so this is best among known windows only.
export function bestOpportunity(intervals, now, horizonEnd, duration = 1) {
  if (!Number.isFinite(now) || !Number.isFinite(horizonEnd) || horizonEnd <= now || !Number.isFinite(duration) || duration <= 0) return { best:null, coverage:null };
  const coverage = summarize(intervals,now,horizonEnd);
  if (!coverage) return {best:null, coverage:null};
  const starts = [...new Set([now,...intervals.map(p=>p.start).filter(t=>Number.isFinite(t) && t>=now && t<horizonEnd)])].sort((a,b)=>a-b);
  let best = null;
  for (const start of starts) {
    if (start + duration > horizonEnd + 1e-9) continue;
    const stat = summarize(intervals,start,start+duration);
    if (stat && stat.coverage >= 1 - 1e-9 && stat.average != null && (!best || stat.average < best.average - 1e-9)) best = {start,end:start+duration,average:stat.average};
  }
  return { best, coverage };
}
