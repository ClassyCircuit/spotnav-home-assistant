// @vitest-environment jsdom
// @ts-nocheck
import { it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { renderEvidence } from '../shared-dashboard/evidence-view.js';
import { morekPanel } from '../src/morek-view';
const now = Date.parse('2026-11-13T10:00:00Z');
const at = s => new Date(now-s*1000).toISOString();
const raw = () => { const d=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8')); d.generated_at=at(0); return d; };
const status = live => ({api_version:1,schedule:{supported:true,verified:false,sent:null,sent_at:null,ack:null,effective:null,connector_id:1,readiness:{control:'available',vehicle:'connected',vehicle_observed_at:at(5),live:{connector_id:1,...live}}}});
const render = (s, observed=now) => { const root=document.createElement('div'); root.innerHTML=renderEvidence(dashboardAdapter(raw(),s,observed,now).model.evidence); return root; };
const row = (root,label) => [...root.querySelectorAll('.evidence-grid > div')].find(el=>el.querySelector('small')?.textContent===label)?.textContent;
it('renders unknown, stale and conflicting observations independently', () => {
 const unknown=render(status({}));
 expect(row(unknown,'Transaction')).toMatch(/unknown/i);
 expect(row(unknown,'Measured flow')).toMatch(/no measured power/i);
 expect(unknown.textContent).toMatch(/observations are independent/i);
 const live=status({status:{value:'Charging',normalized:'charging',observed_at:at(5),fresh:true},power_w:{value:0,unit:'W',observed_at:at(5),fresh:true}});
 const mismatch=render(live);
 expect(row(mismatch,'Measured flow')).toMatch(/disagree; neither is verified/i);
 expect(row(mismatch,'Last sent / ACK')).toMatch(/not|unknown|no /i);
 const stale=render(live,now-100000);
 expect(stale.textContent).toMatch(/stale or unavailable/i);
 expect(row(stale,'Measured flow')).toMatch(/stale/i);
 expect(stale.textContent).toMatch(/readback is not profile inventory/i);
});
it('blocks sensitive dispatch for non-admin and uncertain outcome', () => {
 const act=vi.fn(); const base={supported:true,sent:null,effective:null,preview:{preview_id:'p',profile:{chargingProfileId:42001,chargingSchedule:{startSchedule:at(0),chargingSchedulePeriod:[{startPeriod:0,limit:0}]}}},cleanup_supported:true,outcomes:{uncertain:true}};
 morekPanel(document,base,false,false,null,act).querySelectorAll('button').forEach(b=>b.click());
 const panel=morekPanel(document,base,true,false,null,act);
 const send=[...panel.querySelectorAll('button')].find(b => b.textContent === 'Send current plan');
 expect(send?.disabled).toBe(true); send?.click(); expect(act).not.toHaveBeenCalled();
});


