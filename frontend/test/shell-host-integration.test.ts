// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.2a: the host header, status stack and charging controls are rendered by the shared shell from models and
// callbacks. Nothing here touches a network or a controller: callbacks are spies, and a click on a disabled control must
// not reach the host.
import { describe, expect, it, vi } from 'vitest';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { renderHeader, renderStatusStack, renderControls } from '../shared-dashboard/shell.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
window.scrollTo = () => {};

const bare = (actions = {}, model = {}) => ({ draftKey: null, format: { time: () => '', day: () => '' }, actions, model: { bare: true, header: { chargers: [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }], selected: 'a' }, hostMessage: '', hold: false, ...model } });
const mount = (adapter) => { const root = document.createElement('main'); document.body.append(root); return { root, view: mountDashboard(root, adapter) }; };

describe('header', () => {
  it('shows host controls only when the host supplies them', () => {
    const none = renderHeader({ chargers: [{ id: 'a', name: 'A' }], selected: 'a' }, 'overview', {});
    expect(none).not.toContain('id="refresh"'); expect(none).not.toContain('id="menu"'); expect(none).toMatch(/id="charger" disabled/);
    const all = renderHeader({ chargers: [{ id: 'a', name: 'A' }], selected: 'a' }, 'overview', { selectCharger: true, refresh: true, menu: true });
    expect(all).toContain('id="refresh"'); expect(all).toContain('id="menu"'); expect(all).not.toMatch(/id="charger" disabled/);
    expect(all).toContain('<option value="a" selected>A</option>');
  });
  it('escapes charger names', () => {
    expect(renderHeader({ chargers: [{ id: 'x"', name: '<b>' }] }, 'overview', {})).not.toContain('<b>');
  });
});

describe('status stack', () => {
  it('has exactly one element per banner and hides empty ones', () => {
    const html = renderStatusStack({ banners: {} });
    for (const id of ['charge-session', 'schedule-check', 'recovery-banner']) expect(html.match(new RegExp(`id="${id}"`, 'g'))).toHaveLength(1);
    expect(html).toMatch(/id="recovery-banner"[^>]* hidden/);
  });
  it('keeps the critical warning and recovery alert visible when present', () => {
    const html = renderStatusStack({ warning: { title: 'Attention', detail: 'Check Morek.' }, banners: { recovery: { level: 'error', code: 'x', text: 'Blocked' } } });
    expect(html).toContain('Attention'); expect(html).toMatch(/id="recovery-banner"[^>]*role="alert"/); expect(html).toContain('Blocked');
  });
  it('a held (disconnected) shell shows no stale warning or banners, only the host message', () => {
    const html = renderStatusStack({ hold: true, hostMessage: 'Reconnecting', warning: { title: 'Attention', detail: 'x' }, banners: { recovery: { level: 'error', code: 'x', text: 'Blocked' } } });
    expect(html).not.toContain('Attention'); expect(html).not.toContain('Blocked'); expect(html).toContain('Reconnecting');
  });
});

describe('controls', () => {
  it('escapes host text and keeps a typed custom end', () => {
    const html = renderControls({ autoState: '<i>x</i>', chargeNotice: '<u>' }, { duration: 'custom', end: '2026-11-19T07:00' });
    expect(html).not.toContain('<i>'); expect(html).not.toContain('<u>');
    expect(html).toContain('value="2026-11-19T07:00"'); expect(html).toMatch(/id="custom-label"(?! hidden)/);
  });
});

describe('bare shell (no charger / loading / failure)', () => {
  it('renders header, four tabs and a message, with no data cards or action controls', () => {
    const { root } = mount(bare({ selectCharger() {}, refresh() {}, menu() {} }, { hostMessage: 'Select a charger.' }));
    expect(root.querySelectorAll('.sn-header [role="tab"]').length).toBe(4);
    expect(root.querySelector('.sn-notice').textContent).toBe('Select a charger.');
    expect(root.querySelector('.hero')).toBeNull(); expect(root.querySelector('#charge-now')).toBeNull();
    expect(root.querySelectorAll('.tab-panel').length).toBe(4);
    for (const p of root.querySelectorAll('.tab-panel')) expect(p.textContent.length).toBeGreaterThan(20);
  });
  it('routes header clicks to host callbacks and sends nothing on tab changes', () => {
    const a = { selectCharger: vi.fn(), refresh: vi.fn(), menu: vi.fn(), tabChange: vi.fn() };
    const { root } = mount(bare(a));
    root.querySelector('#refresh').click(); root.querySelector('#menu').click();
    const sel = root.querySelector('#charger'); sel.value = 'b'; sel.dispatchEvent(new Event('change'));
    expect(a.refresh).toHaveBeenCalledTimes(1); expect(a.menu).toHaveBeenCalledTimes(1); expect(a.selectCharger).toHaveBeenCalledWith('b');
    for (const id of ['explore', 'history', 'settings', 'overview']) root.querySelector(`#sn-tab-${id}`).click();
    expect(a.refresh).toHaveBeenCalledTimes(1); expect(a.selectCharger).toHaveBeenCalledTimes(1);
    expect(a.tabChange).toHaveBeenCalled();
  });
  it('keeps the selected tab and picked charger across a host re-render', () => {
    const adapter = bare({ selectCharger() {} });
    const { root, view } = mount(adapter);
    view.showTab('history');
    view.update(bare({ selectCharger() {} }, { header: { chargers: [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }], selected: 'b' } }));
    expect(view.activeTab).toBe('history'); expect(root.querySelector('#charger').value).toBe('b');
  });
  it('uses measured width for compact vs wide layout', () => {
    const root = document.createElement('main'); document.body.append(root); root.getBoundingClientRect = () => ({ width: 360 });
    mountDashboard(root, bare());
    expect(root.dataset.snLayout).toBe('compact');
  });
});
