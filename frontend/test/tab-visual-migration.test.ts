// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.2c: Explore, History and Settings use the same visual language as Overview. Structural checks only
// (no browser): every class the three tabs' views emit has a rule in the shared CSS, no light-theme colour is left in
// the base stylesheet, and every destination renders real content (never an empty or placeholder panel).
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { mountDashboard } from '../shared-dashboard/dashboard.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

const dir = 'shared-dashboard/';
const css = ['styles.css', 'dark.css', 'shell.css'].map(f => readFileSync(dir + f, 'utf8')).join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
const status = { api_version: 1, schedule: { supported: false, verified: false, sent: null, sent_at: null, ack: null, effective: null } };

// Classes that are state hooks / structural wrappers and deliberately inherit their parent's look.
const INHERIT = new Set(['cls', 'b', 'css', 'tk-effective', 'tk-flow', 'tk-proposal', 'tk-sent', 'tk-unknown', 'sample-tag', 'details-body', 'next-window', 'dot-unknown', 'actions', 'ns-goto', 'ns-opt', 'ns-tag', 'ns-list', 'ns-days', 'pp-day', 'pp-days', 'mc-unit', 'mc-url', 'mc-row', 'history-nav-buttons', 'history-cost', 'target-marker', 'low-marker']);

describe('tab visual migration (20.2c)', () => {
  it('has a style rule for every class emitted by the Explore, History and Settings views', () => {
    const files = readdirSync(dir).filter(f => /(view|history-day|plan-data)\.js$/.test(f) || f === 'dashboard.js');
    const classes = new Set();
    for (const f of files) for (const m of readFileSync(dir + f, 'utf8').matchAll(/class="([^"$]+)"/g)) m[1].split(/\s+/).forEach(c => c && classes.add(c));
    const missing = [...classes].filter(c => !INHERIT.has(c) && !new RegExp('\\.' + c.replace(/[-]/g, '\\-') + '(?![\\w-])').test(css));
    expect(missing).toEqual([]);
  });

  it('keeps no light-theme colour literals in the base stylesheet', () => {
    const base = readFileSync(dir + 'styles.css', 'utf8');
    const lights = (base.match(/#[0-9a-fA-F]{6}\b/g) || []).filter(h => { const n = parseInt(h.slice(1), 16); const lum = ((n >> 16) & 255) * 0.3 + ((n >> 8) & 255) * 0.59 + (n & 255) * 0.11; return lum > 200 && !['#c2f5e4', '#ffd5d5', '#ffe3a3'].includes(h.toLowerCase()); });
    expect(lights).toEqual([]);
    expect(base).not.toMatch(/background:\s*#(?:eff7f4|fff1ed|fff8e6)/i);
  });

  it('keeps the layout rules width-measured, with no named grid areas', () => {
    expect(css).not.toMatch(/grid-template-areas/);
    expect(css).not.toMatch(/@media\s*\(\s*(?:min|max)-width/);
  });

  it('renders content in every destination with no placeholder text', () => {
    const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8')); raw.generated_at = new Date().toISOString();
    const adapter = dashboardAdapter(raw, status, Date.now(), Date.now());
    const root = document.createElement('main'); document.body.append(root); mountDashboard(root, adapter);
    for (const id of ['overview', 'explore', 'history', 'settings']) {
      const panel = root.querySelector(`#sn-panel-${id}`);
      expect(panel.querySelectorAll('section.panel').length, id).toBeGreaterThan(0);
      expect(panel.textContent.trim().length, id).toBeGreaterThan(40);
      expect(panel.textContent, id).not.toMatch(/lorem|placeholder|coming soon|TODO/i);
      expect(panel.querySelector('.sn-empty'), id).toBeNull();
    }
    // Existing destinations stay reachable: the editor, evidence and settings controls are in Settings, the history card in History.
    expect(root.querySelector('#sn-panel-settings .controls')).toBeTruthy();
    expect(root.querySelector('#sn-panel-settings .morek')).toBeTruthy();
    expect(root.querySelector('#sn-panel-history .history')).toBeTruthy();
    expect(root.querySelector('#sn-panel-explore .insights')).toBeTruthy();
  });
});
