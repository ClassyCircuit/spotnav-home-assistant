// @vitest-environment jsdom
// @ts-nocheck
import { it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { buildWindowsModel } from '../shared-dashboard/windows-model.js';
import { renderWindows } from '../shared-dashboard/windows-view.js';
const now=Date.parse('2026-11-19T12:00:00Z');
const effective={status:'Accepted',fetched_at:'2026-11-19T11:59:30Z',schedule_start:'2026-11-19T11:00:00Z',duration_s:7200,rate_unit:'A',periods:[{at:'2026-11-19T11:30:00Z',amps:0}]};
function render(e, {failed=false,sent=null,ack=null}={}) {
 const raw=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8')); raw.generated_at=new Date(now).toISOString(); raw.planning.calculated_at='2026-11-19T11:58:00Z';
 const a=dashboardAdapter(raw,{api_version:1,schedule:{supported:true,verified:false,sent,sent_at:null,ack,effective:e}},now,now,failed), m=a.model, f=a.format;
 const model=buildWindowsModel({windows:m.windows,knownPlan:!!m.windows,totals:m.totals,context:m.windowsContext,format:f,draftKey:a.draftKey});
 const action=vi.fn(); a.actions={refresh:action,priceNav:action,save:action};
 const root=document.createElement('div'); root.innerHTML=renderWindows(model,{f,assumptions:m.assumptions,effective:m.effectiveDisplay,calculatedAt:m.calculatedAt}); expect(action).not.toHaveBeenCalled();
 return {text:root.querySelector('.win-comparison').textContent,f};
}
it('renders accepted cached limits and both timestamps',()=>{
 const {text,f}=render(effective); expect(text).toContain('0 A'); expect(text).toContain('Status: fresh');
 for(const t of [Date.parse(effective.fetched_at),Date.parse('2026-11-19T11:58:00Z')]) expect(text).toContain(`${f.day(t)} ${f.time(t)}`);
 expect(text).toContain('not proof of physical charging');
});
it('never substitutes sent or ACK evidence',()=>{
 const {text}=render(null,{sent:{chargingSchedule:{chargingSchedulePeriod:[{startPeriod:0,limit:16}]}},ack:'Accepted'});
 expect(text).toContain('Status: unknown'); expect(text).toContain('Fetched at: Unknown'); expect(text).toContain('No valid limits available'); expect(text).not.toContain('16 A');
});
it('qualifies stale, failed and malformed readbacks',()=>{
 expect(render({...effective,fetched_at:'2026-11-19T11:58:00Z'}).text).toContain('Status: stale');
 expect(render(effective,{failed:true}).text).toContain('Status: stale · latest status refresh failed');
 const text=render({...effective,periods:[{at:effective.periods[0].at,amps:-1}]}).text;
 expect(text).toContain('Status: invalid'); expect(text).toContain('No valid limits available'); expect(text).not.toContain('-1 A');
});
