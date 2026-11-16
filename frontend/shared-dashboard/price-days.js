// Price-day navigation (Stage 7.1): one request state machine and nav model shared by the live sidebar and the local
// preview. Read-only: it only asks `spotnav/get_price_days` (held prices, never a provider) and never writes.
// Prices stay in the backend's raw major unit here; the one display conversion happens in `price-chart.js`.

export const PAGE_DAYS = 8;
const DAY_MS = 86400000;
const FAILED = 'Held price days could not be read.';

const parse = day => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day || ''); return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : NaN; };
const format = ms => new Date(ms).toISOString().slice(0, 10);
export const addDays = (day, n) => format(parse(day) + n * DAY_MS);
export const dayLabel = day => Number.isFinite(parse(day)) ? new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }).format(parse(day)) : 'Unknown day';

/** Merge price rows by actual instant. Identical duplicates drop; any conflict, overlap or malformed row refuses the lot. */
export function mergePriceRows(...lists) {
  const byStart = new Map();
  for (const list of lists) for (const row of list || []) {
    const start = Date.parse(row?.start), end = Date.parse(row?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || !(row.raw_price === null || Number.isFinite(row.raw_price))) return { error: 'malformed' };
    const old = byStart.get(start);
    if (old) { if (old.end === end && old.row.raw_price === row.raw_price) continue; return { error: 'conflict' }; }
    byStart.set(start, { end, row });
  }
  const sorted = [...byStart.entries()].sort((a, b) => a[0] - b[0]);
  for (let i = 1; i < sorted.length; i++) if (sorted[i][0] < sorted[i - 1][1].end) return { error: 'overlap' };
  return { rows: sorted.map(([, item]) => item.row) };
}

/**
 * `request(params)` resolves the backend answer (live: the WebSocket, preview: a fixture of the same shape).
 * `onChange()` is called when an asynchronous result changed what to draw. No request is ever repeated on its own:
 * a failure stays an error until `retry()`.
 */
export function createPriceDays({ request, onChange = () => {} }) {
  let ctx = null, key = null, token = 0, pageId = 0, navSeq = 0;
  // Every explicit choice (even the same button again) is a new navigation; a default view carries no sequence.
  const chosen = selection => ({ ...selection, seq: ++navSeq });
  const initial = () => ({ available: null, status: 'idle', error: null, page: null, loading: null, selection: { kind: 'today' }, earlierOpen: false, retryDay: null });
  let st = initial();
  const reset = () => { token++; st = initial(); };
  const keyOf = c => JSON.stringify([c.charger, c.epoch, c.area, c.currency]);
  const current = (mine, myKey) => mine === token && myKey === key;

  async function loadAvailable() {
    const mine = token, myKey = key, asked = ctx;
    st.status = 'loading'; st.error = null;
    try {
      const answer = await request({ mode: 'available' });
      if (!current(mine, myKey)) return;
      const days = Array.isArray(answer?.days) ? answer.days : null;
      const valid = answer?.api_version === 1 && answer.mode === 'available' && answer.charger_id === asked.charger && answer.area_id === asked.area
        && answer.currency === asked.currency && typeof answer.today === 'string' && Number.isFinite(parse(answer.today)) && days && days.length <= 400
        && days.every(row => Number.isFinite(parse(row?.day)));
      if (!valid) throw new Error('context');
      st.available = { today: answer.today, days, byDay: new Map(days.map(row => [row.day, row])), yesterdayReachable: answer.yesterday_reachable === true };
      st.status = 'ready';
    } catch { if (!current(mine, myKey)) return; st.status = 'error'; st.error = FAILED; }
    onChange();
  }

  async function loadPage(day, selection) {
    const mine = token, myKey = key, asked = ctx;
    const oldest = st.available.days.at(-1)?.day ?? day;
    const from = parse(addDays(day, 1 - PAGE_DAYS)) < parse(oldest) ? oldest : addDays(day, 1 - PAGE_DAYS);
    st.loading = { day }; st.error = null; st.retryDay = null;
    try {
      const answer = await request({ mode: 'range', from, to: day });
      if (!current(mine, myKey)) return;
      const wanted = [];
      for (let d = from; parse(d) <= parse(day); d = addDays(d, 1)) wanted.push(d);
      const rows = Array.isArray(answer?.days) ? answer.days : null;
      const valid = answer?.api_version === 1 && answer.mode === 'range' && answer.charger_id === asked.charger && answer.area_id === asked.area
        && answer.currency === asked.currency && answer.from === from && answer.to === day && rows && rows.length === wanted.length
        && rows.every((row, i) => row?.day === wanted[i] && typeof row.held === 'boolean');
      if (!valid) throw new Error('context');
      // A held day whose rows the backend refused (overlap, no usable rate) is not drawn, and the page says so.
      const dayRows = new Map(rows.map(row => [row.day, row]));
      const merged = mergePriceRows(...rows.map(row => row.held && Array.isArray(row.intervals) ? row.intervals : []));
      if (merged.error) throw new Error('rows');
      st.page = { id: ++pageId, from, to: day, dayRows, rows: merged.rows };
      st.selection = chosen(selection);
    } catch (error) { if (!current(mine, myKey)) return; st.error = error?.message === 'rows' ? 'Held prices of this page overlap or conflict; the page was not drawn.' : FAILED; st.retryDay = { day, selection }; }
    st.loading = null;
    onChange();
  }

  const heldDay = day => st.available?.byDay.get(day);
  const liveCoversDay = (liveRows, c, day) => { const span = c.span?.(day); return !!span && (liveRows || []).some(row => { const s = Date.parse(row?.start); return s >= span[0] && s < span[1]; }); };

  return {
    /** Tell it who is asking; a change of charger, generation, area or currency drops every page and the selection. */
    sync(next) {
      const valid = !!(next && next.charger && next.area && /^[A-Z]{3}$/.test(next.currency || ''));
      const nextKey = valid ? keyOf(next) : null;
      if (nextKey !== key) { reset(); key = nextKey; }
      ctx = valid ? next : null;
      if (!ctx) return this;
      if (st.available && ctx.today && st.available.today !== ctx.today) { reset(); }
      if (st.status === 'idle') void loadAvailable();
      return this;
    },
    /** Explicit navigation. `today`/`tomorrow`/`all` need no request; the others load one bounded page. */
    select(kind, day, options) {
      if (!ctx || !st.available || st.loading) return 'busy';
      if (kind === 'earlier') { st.earlierOpen = !st.earlierOpen; onChange(); return; }
      // 8.1 day review: the held market day a page must end at (before today) and the instants of the Home Assistant-local day to show.
      if (kind === 'review') {
        if (!heldDay(day) || parse(day) >= parse(st.available.today)) return 'not_held';
        const range = Array.isArray(options?.range) && options.range.length === 2 && options.range.every(Number.isFinite) && options.range[1] > options.range[0] ? options.range : null;
        const selection = { kind: 'day', day, range, review: true };
        if (st.page?.dayRows.get(day)?.held && st.page.dayRows.get(day).intervals) { st.selection = chosen(selection); st.error = null; st.retryDay = null; onChange(); return 'shown'; }
        void loadPage(day, selection);
        onChange();
        return 'loading';
      }
      if (kind === 'today' || kind === 'tomorrow' || kind === 'all') { st.selection = chosen({ kind, explicit: true }); st.error = null; st.retryDay = null; onChange(); return; }
      const target = kind === 'yesterday' ? addDays(st.available.today, -1) : day;
      if (!heldDay(target) || (kind === 'day' && parse(target) >= parse(st.available.today))) return;
      const selection = { kind: kind === 'yesterday' ? 'yesterday' : 'day', day: target };
      if (st.page?.dayRows.get(target)?.held && st.page.dayRows.get(target).intervals) { st.selection = chosen(selection); st.error = null; st.retryDay = null; onChange(); return; }
      void loadPage(target, selection);
      onChange();
    },
    retry() {
      if (!ctx || st.loading) return;
      if (st.status === 'error') { void loadAvailable(); onChange(); return; }
      if (st.retryDay) void loadPage(st.retryDay.day, st.retryDay.selection), onChange();
    },
    /** What to draw and the nav model. `liveRows` is the dashboard's own `published_intervals` (today/tomorrow). */
    view(liveRows) {
      if (!ctx) return null;
      const today = st.available?.today ?? ctx.today, tomorrow = today ? addDays(today, 1) : null, yesterday = today ? addDays(today, -1) : null;
      let page = st.page, error = st.error, selection = st.selection;
      let all = page ? mergePriceRows(page.rows, liveRows) : null;
      if (all?.error) { // a page that disagrees with the live feed is refused, never guessed
        st.page = page = null; st.selection = selection = { kind: 'today' }; st.error = error = 'Held prices of this page overlap or conflict with the current prices; the page was not drawn.'; all = null;
      }
      const loaded = all?.rows ?? null;
      const showsPage = page && ['yesterday', 'day', 'all'].includes(selection.kind);
      const rows = showsPage ? loaded : (liveRows || null);
      let range = null;
      // Only an explicit Today is the local calendar day; the default keeps the rolling today/tomorrow horizon.
      if (selection.kind === 'today' && selection.explicit) range = ctx.span?.(today) ?? null;
      else if (selection.kind === 'tomorrow') range = ctx.span?.(tomorrow) ?? null;
      else if (selection.kind === 'yesterday' || selection.kind === 'day') range = selection.range ?? ctx.span?.(selection.day) ?? null;
      else if (selection.kind === 'all' && rows?.length) range = [Date.parse(rows[0].start), Date.parse(rows.at(-1).end)];
      const viewKey = `${selection.kind}:${selection.day || ''}:${showsPage ? page.id : 0}${selection.seq ? `:${selection.seq}` : ''}`;
      const available = st.available, checking = st.status === 'loading' || st.status === 'idle';
      const why = text => checking ? 'Checking which days are held…' : st.status === 'error' ? 'Held days could not be read.' : text;
      const held = day => available?.byDay.get(day);
      const partial = row => row && row.complete === false;
      const earlier = available ? available.days.filter(row => parse(row.day) < parse(yesterday)) : [];
      const tomorrowThere = liveCoversDay(liveRows, ctx, tomorrow);
      const buttons = [
        { id: 'yesterday', label: 'Yesterday', enabled: !!held(yesterday), partial: partial(held(yesterday)), reason: held(yesterday) ? '' : why(available && !available.yesterdayReachable ? 'Outside what the price provider keeps.' : 'Yesterday’s prices are not held.') },
        { id: 'today', label: 'Today', enabled: true, reason: '' },
        { id: 'tomorrow', label: 'Tomorrow', enabled: tomorrowThere, reason: tomorrowThere ? '' : (ctx.waitingForTomorrow ? 'Tomorrow’s prices are not published yet.' : 'Tomorrow’s prices are not held.') },
        { id: 'earlier', label: 'Earlier…', enabled: earlier.length > 0, reason: earlier.length ? '' : why('No earlier prices are held.') },
        { id: 'all', label: 'All loaded days', enabled: !!rows?.length, reason: rows?.length ? '' : 'No prices are loaded.' },
      ];
      for (const button of buttons) button.selected = button.id === 'earlier' ? (st.earlierOpen || selection.kind === 'day') : selection.kind === button.id;
      const row = selection.day ? page?.dayRows.get(selection.day) : null;
      const loadedDays = showsPage ? new Set([...(page.dayRows.values())].filter(r => r.held && r.intervals).map(r => r.day)) : new Set();
      let detail = '';
      if (selection.kind === 'all') detail = `All loaded days: ${loadedDays.size ? `${loadedDays.size} held day${loadedDays.size === 1 ? '' : 's'} of the current page of up to ${PAGE_DAYS} days plus` : ''} today and tomorrow. Not the full price history.`;
      else if (row?.held) detail = `${dayLabel(row.day)} · ${row.complete === false ? 'partial: the held prices cover only part of this day' : 'complete'} · ${row.interval_count ?? 'unknown'} intervals${row.resolution_minutes ? ` of ${row.resolution_minutes} min` : ' (mixed lengths)'} · source ${row.source || 'unknown'}${row.fetched_at ? ` · fetched ${ctx.formatInstant ? ctx.formatInstant(row.fetched_at) : row.fetched_at}` : ''}`;
      else if (selection.kind === 'tomorrow') detail = 'Tomorrow’s published prices.';
      const unusable = page ? [...page.dayRows.values()].filter(r => r.held && !r.intervals) : [];
      if (unusable.length) detail += ` ${unusable.map(r => dayLabel(r.day)).join(', ')}: held, but not drawn (${unusable.some(r => r.reason === 'no_price_rate') ? 'no usable exchange rate' : 'invalid intervals'}).`;
      const nav = {
        selected: selection.kind, selectedDay: selection.day || null,
        status: st.loading ? 'loading' : (error || st.status === 'error') ? 'error' : checking ? 'loading' : 'ready',
        message: st.loading ? `Loading held prices up to ${dayLabel(st.loading.day)}…` : error || (st.status === 'error' ? FAILED : ''),
        canRetry: !st.loading && (!!st.retryDay || st.status === 'error'),
        buttons,
        earlier: { open: st.earlierOpen && earlier.length > 0, days: earlier.map(r => ({ day: r.day, label: dayLabel(r.day), partial: partial(r) })), hint: `Pick a held day; one page of up to ${PAGE_DAYS} days ending there is loaded.` },
        detail: detail.trim(),
      };
      return { nav, rows, range, viewKey };
    },
    dispose() { token++; ctx = null; key = null; st = initial(); },
  };
}
