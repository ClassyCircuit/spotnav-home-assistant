// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.1: the shared four-tab shell, in the shared renderer and in the actual panel host.
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import '../sidebar/panel.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

const fixture = () => JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
const status = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const tick = async () => { for (let i=0;i<20;i++) await Promise.resolve(); };
const record = () => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',target:{vehicle_id:'vehicle_ev6',target_percent:80},driver:'target_soc'});
const envelope = (settings,ok=true,error=null) => ({api_version:1,ok,error,settings,pause:{choice:null,admitted_at:null,expires_at:null}});
const adapterOf = raw => dashboardAdapter(raw, status, Date.now(), Date.now());

function mount(extra = {}) {
  const raw = fixture(); raw.generated_at = new Date().toISOString();
  const adapter = adapterOf(raw);
  adapter.draftKey = 'a:1';
  Object.assign(adapter.actions, extra);
  const root = document.createElement('main'); document.body.append(root);
  return { raw, adapter, root, view: mountDashboard(root, adapter) };
}
const visible = root => [...root.querySelectorAll('.tab-panel')].filter(p => !p.hidden).map(p => p.dataset.tab);
const homes = (root, id) => [...root.querySelectorAll(`#sn-panel-${id} > .dashboard > section.panel`)].map(s => s.classList[1]);

describe('four-tab shell (shared renderer)', () => {
  it('opens on Overview with four labeled tabs and exactly one visible panel', () => {
    const { root } = mount();
    const tabs = [...root.querySelectorAll('[role="tab"]')];
    expect(tabs.map(t => t.textContent.trim())).toEqual(['Overview','Explore','History','Settings']);
    expect(tabs.map(t => t.getAttribute('aria-selected'))).toEqual(['true','false','false','false']);
    expect(tabs.map(t => t.tabIndex)).toEqual([0,-1,-1,-1]);
    expect(visible(root)).toEqual(['overview']);
    for (const t of tabs) expect(root.querySelector('#' + t.getAttribute('aria-controls')).getAttribute('aria-labelledby')).toBe(t.id);
  });
  it('gives every existing card exactly one canonical tab home', () => {
    const { root } = mount();
    expect(homes(root,'overview')).toEqual(['overview','prices','recent']);
    expect(homes(root,'explore')).toEqual(['insights']);
    expect(homes(root,'history')).toEqual(['history']);
    expect(homes(root,'settings').slice(0,2)).toEqual(['controls','morek']);
    const all = [...root.querySelectorAll('section.panel')];
    expect(all.every(s => s.closest('.tab-panel'))).toBe(true);
    expect(root.querySelector('#plan-dialog').closest('.tab-panel')).toBeNull();
  });
  it('switches by click without calling any host action but tabChange', () => {
    const tabChange = vi.fn(), save = vi.fn(), priceNav = vi.fn(), historyNav = vi.fn(), edit = vi.fn();
    const { root, view } = mount({ tabChange, save, priceNav, historyNav, edit });
    root.querySelector('#sn-tab-explore').click();
    expect(visible(root)).toEqual(['explore']);
    expect(root.querySelector('#sn-tab-explore').getAttribute('aria-selected')).toBe('true');
    expect(view.activeTab).toBe('explore');
    root.querySelector('#sn-tab-settings').click();
    root.querySelector('#sn-tab-settings').click();
    expect(tabChange.mock.calls).toEqual([['explore'],['settings']]);
    for (const fn of [save, priceNav, historyNav, edit]) expect(fn).not.toHaveBeenCalled();
    expect(view.showTab('nope')).toBe(false);
    expect(visible(root)).toEqual(['settings']);
  });
  it('supports arrow, Home and End keys with roving focus', () => {
    const { root } = mount();
    const key = (id, k) => root.querySelector('#sn-tab-' + id).dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
    key('overview','ArrowLeft');
    expect(visible(root)).toEqual(['settings']);
    expect(root.querySelector('#sn-tab-settings').tabIndex).toBe(0);
    expect(root.querySelector('#sn-tab-overview').tabIndex).toBe(-1);
    key('settings','ArrowRight'); expect(visible(root)).toEqual(['overview']);
    key('overview','End'); expect(visible(root)).toEqual(['settings']);
    key('settings','Home'); expect(visible(root)).toEqual(['overview']);
    key('overview','x'); expect(visible(root)).toEqual(['overview']);
  });
  it('keeps the tab, drafts and mounted nodes through tab changes and observation refresh', () => {
    const { root, view, adapter, raw } = mount();
    const input = root.querySelector('[data-setting="target"]');
    input.value = '66'; input.dispatchEvent(new Event('input', { bubbles: true }));
    root.querySelector('#sn-tab-settings').click();
    root.querySelector('#sn-tab-history').click();
    const next = adapterOf(raw); next.draftKey = adapter.draftKey;
    view.update(next);
    expect(view.activeTab).toBe('history');
    expect(visible(root)).toEqual(['history']);
    expect(root.querySelector('[data-setting="target"]')).toBe(input);
    expect(input.value).toBe('66');
    // A changed charger resets drafts but not the destination the user is looking at.
    const other = adapterOf(raw); other.draftKey = 'b:1';
    view.update(other);
    expect(view.activeTab).toBe('history');
    expect(root.querySelector('[data-setting="target"]').value).not.toBe('66');
  });
  it('shows a truthful Overview history summary that links to History', () => {
    const { root } = mount();
    const summary = root.querySelector('section.recent');
    expect(summary.textContent).not.toMatch(/undefined|NaN/);
    summary.querySelector('[data-open-tab="history"]').click();
    expect(visible(root)).toEqual(['history']);
  });
  it('makes the critical-warning details link reach the diagnostics from any tab', () => {
    const raw = fixture(); raw.generated_at = new Date().toISOString();
    const adapter = adapterOf(raw);
    adapter.model.warning = { title: 'Attention', detail: 'Check Morek.' };
    const root = document.createElement('main'); document.body.append(root);
    const view = mountDashboard(root, adapter);
    view.showTab('explore');
    expect(root.querySelector('#critical-live').textContent).toContain('Attention');
    root.querySelector('a[href="#details"]').click();
    expect(visible(root)).toEqual(['settings']);
    expect(root.querySelector('#details').open).toBe(true);
  });
  it('uses the compact bottom-bar layout from the measured root width and not otherwise', () => {
    const raw = fixture(); raw.generated_at = new Date().toISOString();
    const root = document.createElement('main'); document.body.append(root);
    root.getBoundingClientRect = () => ({ width: 390 });
    mountDashboard(root, adapterOf(raw));
    expect(root.dataset.snLayout).toBe('compact');
    expect(root.querySelectorAll('.sn-nav [role="tab"]').length).toBe(4);
    const wide = document.createElement('main'); document.body.append(wide);
    wide.getBoundingClientRect = () => ({ width: 1200 });
    mountDashboard(wide, adapterOf(raw));
    expect(wide.dataset.snLayout).toBe('wide');
  });
});

describe('four-tab shell (actual panel host)', () => {
  it('keeps host controls outside the tabs and switching tabs sends no request', async () => {
    const raw = fixture(); raw.generated_at = new Date().toISOString(); raw.charger.charger_id = 'a';
    const calls = [];
    const hass = { connected: true, user: { is_admin: true }, callWS: msg => { calls.push(msg); return Promise.resolve(msg.type==='spotnav/list_chargers' ? {api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]} : msg.type==='spotnav/get_dashboard' ? raw : msg.type==='spotnav/get_settings' ? envelope(record()) : status); } };
    const panel = document.createElement('spotnav-enhanced-panel'); panel.hass = hass; document.body.append(panel); await tick();
    const root = panel.shadowRoot;
    expect(root.querySelectorAll('main [role="tab"]').length).toBe(4);
    expect(visible(root.querySelector('main'))).toEqual(['overview']);
    for (const id of ['#menu','#charger','#refresh','#pause-auto','#resume-auto','#charge-now','#charge-duration']) {
      const el = root.querySelector(id); expect(el, id).not.toBeNull(); expect(el.closest('main')).toBeNull();
    }
    const before = calls.length;
    for (const id of ['explore','history','settings','overview']) root.querySelector(`#sn-tab-${id}`).click();
    await tick();
    expect(calls.length).toBe(before);
    root.querySelector('#sn-tab-settings').click();
    expect(root.querySelector('#save-plan').closest('#sn-panel-settings')).not.toBeNull();
    panel.remove();
  });
});
