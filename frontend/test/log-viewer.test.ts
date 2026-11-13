// @vitest-environment jsdom
// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { createLogViewer, decodeLogs, formatLine } from '../sidebar/log-viewer.js';

const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const admin = {user: {is_admin: true}, connected: true};
const entry = (seq, message, level = 'INFO', extra = {}) => ({seq, time: '2026-11-13T10:00:00+00:00', level, logger: 'custom_components.spotnav.api.morek_schedule', message, ...extra});
const answer = (entries, extra = {}) => ({api_version: 1, ok: true, error: null, boot_id: 'b1', latest_seq: entries.at(-1)?.seq ?? 0, entries, matched: entries.length, truncated: false, restarted: false, ...extra});
const timers = () => { const t = {fns: [], set: vi.fn(fn => { t.fns.push(fn); return t.fns.length; }), clear: vi.fn(id => { t.fns[id - 1] = null; })}; return t; };
const live = v => { v.querySelector('.log-live').checked = true; v.querySelector('.log-live').dispatchEvent(new Event('change')); };
const open = async (viewer) => { document.body.append(viewer); viewer.open = true; viewer.dispatchEvent(new Event('toggle')); await tick(); };

describe('SpotNav log viewer', () => {
  it('shows records as text only, with the namespace prefix shortened', async () => {
    const fetchLogs = vi.fn().mockResolvedValue(answer([entry(1, 'Morek <img src=x onerror=alert(1)> recorded', 'INFO', {exception: 'Traceback\nValueError'})]));
    const viewer = createLogViewer(() => admin, {fetchLogs});
    await open(viewer);
    const lines = viewer.querySelector('.log-lines');
    expect(lines.querySelector('img')).toBeNull();
    expect(lines.textContent).toContain('INFO api.morek_schedule: Morek <img src=x onerror=alert(1)> recorded');
    expect(lines.textContent).toContain('ValueError');
    expect(viewer.querySelector('.log-status').textContent).toMatch(/1 record/);
    expect(viewer.querySelector('.log-note').textContent).toMatch(/not a separate log and not a stream/);
  });

  it('sends the chosen filters and resets the list when they change', async () => {
    const fetchLogs = vi.fn().mockResolvedValueOnce(answer([entry(1, 'old')])).mockResolvedValueOnce(answer([entry(2, 'new warning', 'WARNING')]));
    const viewer = createLogViewer(() => admin, {fetchLogs});
    await open(viewer);
    viewer.querySelector('.log-level').value = 'WARNING';
    viewer.querySelector('.log-text').value = '  warning ';
    viewer.querySelector('.log-level').dispatchEvent(new Event('change'));
    await tick();
    expect(fetchLogs).toHaveBeenLastCalledWith(admin, {level: 'WARNING', text: 'warning', after_seq: 0, boot_id: 'b1'});
    expect(viewer.querySelector('.log-lines').textContent).toContain('new warning');
    expect(viewer.querySelector('.log-lines').textContent).not.toContain('old');
  });

  it('live mode polls incrementally while open, appends new records, and stops when closed', async () => {
    const t = timers();
    const fetchLogs = vi.fn().mockResolvedValueOnce(answer([entry(1, 'first')])).mockResolvedValueOnce(answer([entry(2, 'second')])).mockResolvedValueOnce(answer([entry(2, 'second')], {entries: []}));
    const viewer = createLogViewer(() => admin, {fetchLogs, timers: t});
    await open(viewer);
    live(viewer);
    await tick();
    expect(fetchLogs).toHaveBeenLastCalledWith(admin, {level: 'INFO', text: '', after_seq: 1, boot_id: 'b1'});
    expect(viewer.querySelector('.log-lines').textContent).toMatch(/first[\s\S]*second/);
    expect(t.set).toHaveBeenCalledTimes(1);
    viewer.open = false; viewer.dispatchEvent(new Event('toggle'));
    expect(t.clear).toHaveBeenCalled();
  });

  it('keeps what was shown when a poll fails, and recovers on the next one', async () => {
    const fetchLogs = vi.fn().mockResolvedValueOnce(answer([entry(1, 'kept')])).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(answer([entry(2, 'back')]));
    const viewer = createLogViewer(() => admin, {fetchLogs});
    await open(viewer);
    live(viewer); await tick();
    expect(viewer.querySelector('.log-status').textContent).toMatch(/unavailable; showing what was already loaded/);
    expect(viewer.querySelector('.log-lines').textContent).toContain('kept');
    live(viewer); await tick();
    expect(viewer.querySelector('.log-lines').textContent).toMatch(/kept[\s\S]*back/);
  });

  it('starts over when Home Assistant restarted (new boot id)', async () => {
    const fetchLogs = vi.fn().mockResolvedValueOnce(answer([entry(5, 'before restart')])).mockResolvedValueOnce(answer([entry(1, 'after restart')], {boot_id: 'b2', restarted: true}));
    const viewer = createLogViewer(() => admin, {fetchLogs});
    await open(viewer);
    live(viewer); await tick();
    expect(viewer.querySelector('.log-lines').textContent).not.toContain('before restart');
    expect(viewer.querySelector('.log-lines').textContent).toContain('after restart');
    expect(viewer.querySelector('.log-status').textContent).toMatch(/restarted/);
  });

  it('never asks a non-administrator or a disconnected host, and reports backend refusals', async () => {
    const fetchLogs = vi.fn();
    let hass = {user: {is_admin: false}, connected: true};
    const viewer = createLogViewer(() => hass, {fetchLogs});
    await open(viewer);
    expect(fetchLogs).not.toHaveBeenCalled();
    expect(viewer.querySelector('.log-status').textContent).toMatch(/Administrator permission/);
    hass = {user: {is_admin: true}, connected: false};
    viewer.querySelector('.log-refresh').click(); await tick();
    expect(fetchLogs).not.toHaveBeenCalled();
    expect(viewer.querySelector('.log-status').textContent).toMatch(/disconnected/);
    hass = admin;
    fetchLogs.mockResolvedValueOnce({api_version: 1, ok: false, error: 'spotnav_not_admin', entries: []});
    viewer.querySelector('.log-refresh').click(); await tick();
    expect(viewer.querySelector('.log-status').textContent).toMatch(/Administrator permission/);
  });

  it('decodes defensively', () => {
    expect(decodeLogs(null)).toBeNull();
    expect(decodeLogs({api_version: 2, ok: true})).toBeNull();
    expect(decodeLogs({api_version: 1, ok: true, entries: 'x'})).toBeNull();
    expect(decodeLogs(answer([{seq: 'x', message: 5, level: 'INFO'}, entry(3, 'ok')])).entries).toHaveLength(1);
    expect(formatLine({time: 'bad', level: 'INFO', logger: '', message: 'm', exception: ''})).toBe('- INFO : m');
  });
});
