// SpotNav log viewer: recent records of SpotNav's own log buffer inside Home Assistant Core's logging.
// Presentation only: filtering, redaction and permission are backend-owned (`spotnav/get_logs`, admin only).
// "Live" is polling while the section is open; there is no push stream. Text is always set as textContent.
import { getLogs } from '../src/api.ts';

const MAX_SHOWN = 300;
const ERRORS = {
  spotnav_not_admin: 'Administrator permission is required to view logs.',
  spotnav_logs_unavailable: 'The SpotNav log buffer is not available.',
  spotnav_logs_invalid_filter: 'The filter was not accepted.',
};

export function decodeLogs(raw) {
  if (!raw || typeof raw !== 'object' || raw.api_version !== 1 || typeof raw.ok !== 'boolean') return null;
  if (!raw.ok) return {ok: false, error: typeof raw.error === 'string' ? raw.error : 'unknown', entries: []};
  if (!Array.isArray(raw.entries) || !Number.isInteger(raw.latest_seq) || typeof raw.boot_id !== 'string') return null;
  const entries = raw.entries.filter(e => e && typeof e.message === 'string' && typeof e.level === 'string').map(e => ({
    seq: Number.isInteger(e.seq) ? e.seq : 0,
    time: typeof e.time === 'string' ? e.time : '',
    level: e.level,
    logger: typeof e.logger === 'string' ? e.logger.replace(/^custom_components\.spotnav\.?/, '') || 'spotnav' : '',
    message: e.message,
    exception: typeof e.exception === 'string' ? e.exception : '',
  }));
  return {ok: true, entries, latestSeq: raw.latest_seq, bootId: raw.boot_id, matched: Number(raw.matched) || 0,
    truncated: raw.truncated === true, restarted: raw.restarted === true};
}

export function formatLine(e) {
  const when = Date.parse(e.time);
  const time = Number.isFinite(when) ? new Date(when).toLocaleString() : '-';
  return `${time} ${e.level} ${e.logger}: ${e.message}${e.exception ? `\n${e.exception}` : ''}`;
}

const MARKUP = `<summary>SpotNav logs</summary>
<div class="log-controls">
  <label>Severity <select class="log-level"><option value="INFO">Info and above</option><option value="WARNING">Warnings and errors</option><option value="ERROR">Errors only</option><option value="DEBUG">Everything kept (incl. debug)</option></select></label>
  <label>Text <input class="log-text" type="search" maxlength="100" placeholder="e.g. Morek, refused"></label>
  <button type="button" class="log-refresh">Refresh</button>
  <label><input type="checkbox" class="log-live"> Live (polls every 5 s)</label>
</div>
<div class="log-status" role="status"></div>
<pre class="log-lines" tabindex="0"></pre>
<p class="log-note">Source: SpotNav records kept in memory by this Home Assistant Core integration (recent records only; not a separate log and not a stream). Older records and other integrations: Settings, System, Logs.</p>`;

/** The viewer element; `getHass` returns the current hass object (or null); fetch and timers are injectable for tests. */
export function createLogViewer(getHass, {fetchLogs = getLogs, intervalMs = 5000, timers = {set: setInterval, clear: clearInterval}} = {}) {
  const root = document.createElement('details');
  root.id = 'log-viewer';
  root.innerHTML = MARKUP;
  const q = s => root.querySelector(s);
  const state = {lines: [], after: 0, boot: null, timer: null, busy: false, epoch: 0};
  const status = text => {q('.log-status').textContent = text;};
  const paint = () => {q('.log-lines').textContent = state.lines.map(l => l.text).join('\n');};
  const stop = () => {if (state.timer !== null) {timers.clear(state.timer); state.timer = null;}};

  async function load(reset) {
    const hass = getHass();
    if (!hass || hass.connected === false) {status('Home Assistant is disconnected; showing what was already loaded.'); return;}
    if (hass.user?.is_admin !== true) {status(ERRORS.spotnav_not_admin); return;}
    if (state.busy && !reset) return;
    if (reset) {state.after = 0; state.lines = []; state.epoch++;}
    state.busy = true;
    const epoch = state.epoch;
    let decoded = null;
    let failed = false;
    try {
      decoded = decodeLogs(await fetchLogs(hass, {level: q('.log-level').value, text: q('.log-text').value.trim(), after_seq: state.after, boot_id: state.boot}));
    } catch (err) {
      failed = err?.code || true;
    }
    if (epoch !== state.epoch) return;
    state.busy = false;
    if (failed || !decoded) {
      status(typeof failed === 'string' && ERRORS[failed] ? ERRORS[failed] : 'Logs unavailable; showing what was already loaded. Retrying while Live is on.');
      return;
    }
    if (!decoded.ok) {
      status(ERRORS[decoded.error] || 'Logs unavailable.');
      if (decoded.error === 'spotnav_not_admin') stop();
      return;
    }
    if (state.boot !== null && decoded.bootId !== state.boot) state.lines = [];
    state.boot = decoded.bootId;
    state.after = decoded.latestSeq;
    const seen = new Set(state.lines.map(l => l.seq).filter(Boolean));
    for (const e of decoded.entries) if (!e.seq || !seen.has(e.seq)) state.lines.push({seq: e.seq, text: formatLine(e)});
    if (state.lines.length > MAX_SHOWN) state.lines = state.lines.slice(-MAX_SHOWN);
    paint();
    status(`${state.lines.length ? `${state.lines.length} record(s) shown` : 'No matching records in the kept window'}${decoded.truncated ? '; older matches are not shown' : ''}${decoded.restarted ? '; Home Assistant restarted, reloaded' : ''}.`);
  }

  const restartTimer = () => {
    stop();
    if (root.open && q('.log-live').checked) state.timer = timers.set(() => void load(false), intervalMs);
  };
  q('.log-refresh').onclick = () => void load(true);
  q('.log-level').onchange = () => void load(true);
  q('.log-text').onchange = () => void load(true);
  q('.log-live').onchange = () => {restartTimer(); if (q('.log-live').checked) void load(false);};
  root.addEventListener('toggle', () => {restartTimer(); if (root.open && !state.lines.length) void load(true);});
  root.destroy = stop;
  root.refresh = () => load(true);
  root.state = state;
  return root;
}
