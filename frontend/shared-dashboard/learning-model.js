// The backend's learned-estimate block (`plan.proposal.learning`, Stage 15.11) as display lines. No planning arithmetic:
// every number is the backend's own (the effect in minutes included), a malformed or absent block is shown as unknown,
// and a stale observation never claims an effect or precision. `text` = the host's translations (see `learningText`).
const count = v => Number.isInteger(v) && v >= 0 && v <= 1000000 ? v : null;
const fill = (template, values) => String(template).replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '');

export const LEARNING_KEYS = ['title','unknown','default','learned','samples','effect_longer','effect_shorter','effect_none','effect_unknown','clamped','note','stale','rejected'];

// Strictly decode the block; anything unexpected is `null` (the caller then shows "unknown").
export function decodeLearning(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  if (raw.source !== 'default' && raw.source !== 'learned') return null;
  if (raw.mode !== 'morek' && raw.mode !== 'legacy') return null;
  const valid = count(raw.valid_samples), agreeing = count(raw.agreeing_samples);
  const lengthen = count(raw.needed_to_lengthen), shorten = count(raw.needed_to_shorten);
  if (valid === null || agreeing === null || lengthen === null || shorten === null || lengthen < 1 || shorten < 1 || agreeing > valid) return null;
  const effect = raw.effect_minutes === null || raw.effect_minutes === undefined ? null : Number.isFinite(raw.effect_minutes) && Math.abs(raw.effect_minutes) <= 100000 ? Math.round(raw.effect_minutes) : undefined;
  if (effect === undefined) return null;
  const rejections = raw.rejections && typeof raw.rejections === 'object' && !Array.isArray(raw.rejections)
    ? Object.entries(raw.rejections).filter(([reason, n]) => /^[a-z_0-9]{1,40}$/.test(reason) && count(n) > 0).map(([reason, n]) => ({reason, count:n})).sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason)).slice(0, 5)
    : [];
  return {source:raw.source, mode:raw.mode, valid, agreeing, lengthen, shorten, effect, clamped:raw.clamped === true, rejections};
}

// `stale`: the observation is not fresh. `raw === undefined` (an older backend) and a malformed block are both unknown.
export function learningModel(raw, stale, text) {
  const state = stale ? 'stale' : 'fresh';
  const block = decodeLearning(raw);
  if (!block) return {state:stale ? 'stale' : 'unknown', lines:[text.unknown], note:text.note, stale:!!stale, staleText:stale ? text.stale : null};
  const lines = [block.source === 'learned' ? text.learned : text.default,
    fill(text.samples, {agreeing:block.agreeing, shorten:block.shorten, lengthen:block.lengthen, valid:block.valid})];
  if (block.clamped) lines.push(text.clamped);
  // A stale observation states no effect: it may no longer be the plan's.
  const effect = stale ? text.effect_unknown : block.effect === null ? text.effect_unknown : block.effect === 0 ? text.effect_none : fill(block.effect > 0 ? text.effect_longer : text.effect_shorter, {minutes:Math.abs(block.effect)});
  lines.push(effect);
  if (block.rejections.length) lines.push(fill(text.rejected, {list:block.rejections.map(r => `${r.reason.replace(/_/g, ' ')} ×${r.count}`).join(', ')}));
  return {state, source:block.source, lines, note:text.note, stale:!!stale, staleText:stale ? text.stale : null, title:text.title};
}
