// @vitest-environment jsdom
// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { reconcile } from '../shared-dashboard/reconcile.js';
import { perspectiveModel, renderPerspective } from '../shared-dashboard/price-perspective-view.js';
import { renderPlanEditor } from '../shared-dashboard/plan-editor-view.js';
import { renderHistoryDay } from '../shared-dashboard/history-view.js';
import { readFileSync } from 'node:fs';

describe('explanatory disclosures', () => {
  it('preserves open state and focus while refreshing price details', () => {
    const f = { time: () => 'time', day: () => 'day' };
    const render = basis => `<div>${renderPerspective(perspectiveModel({ prices: [{start: 0, end: 3600000, cents: 5}], now: 1, unit: 'c/kWh' }), { f, known: true, costBasis: basis })}</div>`;
    const host = document.createElement('div'); document.body.append(host); host.innerHTML = render('spot');
    const detail = host.querySelector('#price-basis-details'), summary = detail.querySelector('summary');
    expect(host.querySelector('[data-pp=now] b').textContent).toBe('5 c/kWh');
    detail.open = true; summary.focus();
    const next = document.createElement('div'); next.innerHTML = render('variable');
    reconcile(host.firstElementChild, next.firstElementChild);
    expect(host.querySelector('#price-basis-details')).toBe(detail); expect(detail.open).toBe(true);
    expect(document.activeElement).toBe(summary); expect(host.textContent).toContain('variable'); host.remove();
  });
  it('keeps role restrictions and vehicle explanations outside optional plan help', () => {
    const r = renderPlanEditor({m:{settingsEditor:true,canSave:true,planAdmin:false,policySupported:true,vehicleHelp:'Vehicle unavailable'},settings:{driver:'target_soc'},e:String,value:x=>x??'',priceText:String,capUnit:'c/kWh'});
    expect(r.roleNote).toContain('administrator only');
    const host=document.createElement('div');host.innerHTML=r.help;
    expect(host.querySelector('[data-mode=target_soc]').textContent).toBe('Vehicle unavailable');
    expect(host.querySelector('#plan-help').open).toBe(false);
    expect(host.querySelector('#plan-help').textContent).toContain('Changes are saved only');
  });
  it('keeps loading and failed history status exposed without a disclosure', () => {
    for (const state of ['loading', 'error']) {
      const host = document.createElement('div');
      host.innerHTML = renderHistoryDay({state, message: `${state} message`});
      const status = host.querySelector('[role=status]');
      expect(status.textContent).toContain(`${state} message`);
      expect(status.closest('details')).toBeNull();
    }
  });
  it('shares the renderer between preview and production hosts', () => {
    const panel = readFileSync('sidebar/panel.js', 'utf8');
    const preview = readFileSync('prototype/README.md', 'utf8');
    expect(panel).toContain("from '../shared-dashboard/dashboard.js'");
    expect(preview).toContain('../shared-dashboard/dashboard.js');
  });
});
