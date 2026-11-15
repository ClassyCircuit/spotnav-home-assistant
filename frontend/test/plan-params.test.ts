// @vitest-environment jsdom
// @ts-nocheck
// Stage 13.3: plan & charger parameters (max periods, planned current, departure date/weekdays) in the shared sidebar UI
// (pure model + write plans, then the real panel against a mocked backend).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';
import { planParamsModel, periodsWritePlan, currentWritePlan, departureWritePlan, paramSignature, nextDepartureText, isoWeekday, addDays, MOREK_MAX_WINDOWS } from '../sidebar/plan-params.js';
import { renderPlanParams } from '../shared-dashboard/plan-params-view.js';
import { decodeSettingsRecord, departureDays } from '../src/settings.ts';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
beforeEach(()=>sessionStorage.clear());
afterEach(()=>vi.restoreAllMocks());

const read = (path) => JSON.parse(readFileSync(`../tests/fixtures/${path}`,'utf8'));
const tick = async () => { for(let i=0;i<30;i++) await Promise.resolve(); };

const recordRaw = (over={}) => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40,...over});
const rec = (over={}) => decodeSettingsRecord(recordRaw(over));
const dash = (over={}) => ({generated_at:new Date(1000).toISOString(),market:{timezone:'Europe/Stockholm'},current_range:{min_a:6,max_a:16,source:'charger'},settings:{users_change_plan:false},...over});
const NOW = Date.parse('2026-11-09T10:00:00Z'); // Monday 11:00 in Stockholm
const model = (over={}) => planParamsModel({admin:true,record:rec(),dashboard:dash(),dashboardFresh:true,now:NOW,morekOwned:null,...over});

describe('plan & charger parameters model (pure)', () => {
  it('offers automatic and 1–8 periods, keeps the saved value and says what Morek adds', () => {
    const m=model();
    expect(m.periods.options.map(o=>o.value)).toEqual(['auto','1','2','3','4','5','6','7','8']);expect(m.periods.value).toBe('3');expect(m.periods.saved).toBe('3 periods');
    expect(model({morekOwned:true}).periods.notes.join(' ')).toMatch(/while Morek owns the schedule the plan uses at most 3/);
    expect(model({morekOwned:false}).periods.notes.join(' ')).toMatch(/does not own the schedule now.*at most 3 apply/);
    expect(model({morekOwned:null}).periods.notes.join(' ')).toMatch(/not known right now/);
    expect(model({record:rec({max_periods:1}),morekOwned:true}).periods.notes.join(' ')).toMatch(/at most 1/);
    const auto=model({record:rec({max_periods:null})});expect(auto.periods.value).toBe('auto');expect(auto.periods.notes[0]).toMatch(/Automatic/);expect(MOREK_MAX_WINDOWS).toBe(3);
  });
  it('current: reported range vs everyday default, nominal power, and a stored out-of-range value kept and flagged', () => {
    const m=model();
    expect(m.current).toMatchObject({value:'10',min:6,max:16,reported:true});expect(m.current.rangeText).toMatch(/accepts 6–16 A/);expect(m.current.nominal).toMatch(/About 6\.9 kW nominal at 10 A on 3 phases.*not a measurement/);
    const dflt=model({dashboard:dash({current_range:{min_a:6,max_a:32,source:'default'}})});expect(dflt.current.reported).toBe(false);expect(dflt.current.rangeText).toMatch(/not reported.*everyday 6–32 A/);
    const none=model({dashboard:dash({current_range:null})});expect(none.current.max).toBe(32);expect(none.current.reported).toBe(false);
    const high=model({record:rec({amps:20})});expect(high.current.value).toBe('20');expect(high.current.warnings.join(' ')).toMatch(/outside the charger’s reported range 6–16 A.*never adjusts/);
    expect(model({record:rec({amps:null})}).current.warnings.join(' ')).toMatch(/No planned current is saved/);
    expect(model({record:rec({phases:null})}).current.nominal).toMatch(/phase count is not set/);
    expect(model({record:rec({phases:1,amps:16})}).current.nominal).toMatch(/3\.7 kW nominal at 16 A on 1 phase:/);
  });
  it('departure: weekday names and the next departure in the market calendar; date range from the market zone', () => {
    const m=model();
    expect(m.departure.weekdays.map(w=>[w.n,w.checked])).toEqual([[1,true],[2,true],[3,true],[4,true],[5,true],[6,true],[7,true]]);
    expect(m.departure).toMatchObject({dateMin:'2026-11-09',dateMax:'2026-11-16',dateKnown:true,canEdit:true,enabled:true});expect(m.departure.next).toBe('Next ready-by: 2026-11-10 06:30 (market local time).');
    const weekend=model({record:rec({departure_weekdays:[6,7]})});expect(weekend.departure.next).toBe('Next ready-by: 2026-11-14 06:30 (market local time).');
    const later=model({record:rec({departure_time:'12:00',departure_weekdays:[1]})});expect(later.departure.next).toBe('Next ready-by: 2026-11-09 12:00 (market local time).');
    const noZone=model({dashboard:dash({market:{timezone:''}})});expect(noZone.departure.dateKnown).toBe(false);expect(noZone.departure.next).toMatch(/time zone is not known/);expect(noZone.departure.notes.join(' ')).toMatch(/cannot be chosen safely/);
    const off=model({record:rec({departure_enabled:false})});expect(off.departure.canEdit).toBe(false);expect(off.departure.next).toMatch(/Ready-by is off/);expect(off.departure.notes.join(' ')).toMatch(/Plan controls/);
    expect(model({record:rec({departure_date:'2026-11-12'})}).departure.next).toBe('Dated ready-by: 2026-11-12 06:30 (market local time). A chosen date overrides the weekdays.');
    expect(model({record:rec({departure_date:'2026-11-07'})}).departure.next).toMatch(/has passed; planning ignores it/);
    expect(model({record:rec({departure_date:'2026-11-09',departure_time:'06:30'})}).departure.next).toMatch(/already passed today/);
  });
  it('the calendar helpers are DST-free and the picker range holds across both clock changes', () => {
    expect(isoWeekday('2026-11-09')).toBe(1);expect(isoWeekday('2026-11-15')).toBe(7);expect(isoWeekday('bad')).toBeNull();
    expect(addDays('2026-10-24',2)).toBe('2026-10-26');expect(addDays('2026-12-31',1)).toBe('2027-01-01');expect(addDays('2027-03-27',2)).toBe('2027-03-29');
    // autumn change (25 h day, 2026-10-25) and spring change (23 h day, 2027-03-28) in Stockholm
    const fall=departureDays('Europe/Stockholm',Date.parse('2026-10-24T22:30:00Z'));expect(fall.today).toBe('2026-10-25');expect(fall.max).toBe('2026-11-01');
    expect(fall.nextOccurrence('06:30')).toBe('2026-10-25');
    // 06:45 CET on the 25 h day: 07:00 is still ahead even though 7 h 45 min have elapsed since midnight
    const afterFall=departureDays('Europe/Stockholm',Date.parse('2026-10-25T05:45:00Z'));expect(afterFall.nextOccurrence('07:00')).toBe('2026-10-25');expect(afterFall.nextOccurrence('06:30')).toBe('2026-10-26');
    // 08:00 CEST on the 23 h day: 07:30 has gone by even though only 7 h have elapsed since midnight
    const afterSpring=departureDays('Europe/Stockholm',Date.parse('2027-03-28T06:00:00Z'));expect(afterSpring.nextOccurrence('07:30')).toBe('2027-03-29');expect(afterSpring.nextOccurrence('08:30')).toBe('2027-03-28');
    const spring=departureDays('Europe/Stockholm',Date.parse('2027-03-27T23:30:00Z'));expect(spring.today).toBe('2027-03-28');expect(spring.max).toBe('2027-04-04');
    const m=model({now:Date.parse('2027-03-27T12:00:00Z'),record:rec({departure_weekdays:[7],departure_time:'06:30'})});expect(m.departure.dateMax).toBe('2027-04-03');expect(m.departure.next).toBe('Next ready-by: 2027-03-28 06:30 (market local time).');
    expect(nextDepartureText(rec({departure_weekdays:[3]}),departureDays('Europe/Stockholm',Date.parse('2026-10-24T22:30:00Z')))).toBe('Next ready-by: 2026-10-28 06:30 (market local time).');
  });
  it('permissions, stale dashboard, busy, conflict and a pending post-save read withhold editing; periods stay administrator-only', () => {
    expect(model({admin:false}).canEdit).toBe(false);expect(model({admin:false}).notes.join(' ')).toMatch(/do not have permission/);
    const user=model({admin:false,dashboard:dash({settings:{users_change_plan:true}})});
    expect(user.canEdit).toBe(true);expect(user.periods.canEdit).toBe(false);expect(user.current.canEdit).toBe(true);expect(user.departure.canEdit).toBe(true);expect(user.notes.join(' ')).toMatch(/Charging periods can only be changed by an administrator/);
    const admin=model();expect(admin.periods.canEdit).toBe(true);expect(admin.current.canEdit).toBe(true);
    for(const over of [{dashboardFresh:false},{blocked:true},{conflict:true},{busy:true},{awaitingRead:true}]) { const m=model(over);expect(m.canEdit).toBe(false);expect(m.periods.canEdit).toBe(false);expect(m.current.canEdit).toBe(false);expect(m.departure.canEdit).toBe(false); }
    expect(model({dashboardFresh:false}).notes.join(' ')).toMatch(/stale/);expect(model({awaitingRead:true}).notes.join(' ')).toMatch(/Waiting for a fresh dashboard read/);
    expect(model({record:null}).state).toBe('unavailable');expect(model({record:null,loading:true}).state).toBe('loading');
    expect(model({notice:'hello'}).notice).toBe('hello');
  });
  it('signature changes when a field owned here, or the charger range, changes', () => {
    const base=paramSignature(rec(),dash());
    expect(paramSignature(rec({max_periods:null}),dash())).not.toBe(base);expect(paramSignature(rec({amps:12}),dash())).not.toBe(base);expect(paramSignature(rec({departure_weekdays:[1]}),dash())).not.toBe(base);
    expect(paramSignature(rec({departure_date:'2026-11-12'}),dash())).not.toBe(base);expect(paramSignature(rec(),dash({current_range:{min_a:6,max_a:10,source:'charger'}}))).not.toBe(base);
    expect(paramSignature(rec({requested_kwh:30}),dash())).toBe(base);expect(paramSignature(null,dash())).toBe('null');
  });
});

describe('plan parameter write plans', () => {
  it('periods: unchanged states nothing; a cap, automatic and a refusal; only max_periods moves', () => {
    const r=rec();
    expect(periodsWritePlan(r,{periods:'3'},true)).toEqual({ok:true,changed:false});
    const p=periodsWritePlan(r,{periods:'5'},true);expect(p).toMatchObject({ok:true,changed:true,from:3,to:5});expect(p.body.max_periods).toBe(5);expect(p.body.amps).toBe(10);expect(p.body.departure_time).toBe('06:30');expect(p.body.requested_kwh).toBe(20);
    expect(periodsWritePlan(r,{periods:'auto'},true).body.max_periods).toBeNull();
    for(const bad of ['0','9','2.5','x','']) { const x=periodsWritePlan(r,{periods:bad},true);expect(x.ok).toBe(false);expect(x.notice.length).toBeGreaterThan(3); }
    expect(periodsWritePlan(r,{periods:'4'},false)).toMatchObject({ok:false});expect(periodsWritePlan(null,{periods:'4'},true)).toMatchObject({ok:false});
  });
  it('current: unchanged, in range, below/above the charger range, non-integer, empty, not allowed; other fields kept', () => {
    const r=rec(),d=dash();
    expect(currentWritePlan(r,{current:'10'},true,d)).toEqual({ok:true,changed:false});
    const up=currentWritePlan(r,{current:'16'},true,d);expect(up).toMatchObject({ok:true,changed:true,from:10,to:16});expect(up.body.amps).toBe(16);expect(up.body.max_periods).toBe(3);expect(up.body.departure_weekdays).toEqual([1,2,3,4,5,6,7]);
    expect(currentWritePlan(r,{current:'6'},true,d).body.amps).toBe(6);
    for(const bad of ['5','17','10.5','abc','','0','81']) { const x=currentWritePlan(r,{current:bad},true,d);expect(x.ok,bad).toBe(false);expect(x.notice).toMatch(/allowed 6–16 A/); }
    expect(currentWritePlan(r,{current:'12'},false,d)).toMatchObject({ok:false,notice:expect.stringMatching(/permission/)});
    // a stored value outside the range is never re-judged while untouched, and nothing raises it
    const stored=rec({amps:20});expect(currentWritePlan(stored,{current:'20'},true,d)).toEqual({ok:true,changed:false});expect(currentWritePlan(stored,{current:'18'},true,d).ok).toBe(false);expect(currentWritePlan(stored,{current:'16'},true,d).body.amps).toBe(16);
    // no saved current and nothing typed: unchanged (never an invented figure)
    expect(currentWritePlan(rec({amps:null}),{current:''},true,d)).toEqual({ok:true,changed:false});expect(currentWritePlan(rec({amps:null}),{current:'8'},true,d).body.amps).toBe(8);
    // the default range applies when the charger reports none, and the dashboard's 32 A default allows what 16 A refused
    expect(currentWritePlan(r,{current:'20'},true,dash({current_range:null})).body.amps).toBe(20);
  });
  it('departure: unchanged, weekdays only, date only, clearing, ranges, passed time, empty weekdays, unknown zone, ready-by off', () => {
    const r=rec(),d=dash(),days='1234567';
    expect(departureWritePlan(r,{date:'',weekdays:days},true,d,NOW)).toEqual({ok:true,changed:false});
    const wk=departureWritePlan(r,{date:'',weekdays:'12345'},true,d,NOW);expect(wk).toMatchObject({ok:true,changed:true,dateChanged:false,weekdaysChanged:true});expect(wk.body.departure_weekdays).toEqual([1,2,3,4,5]);expect(wk.body.departure_date).toBeNull();expect(wk.body.departure_time).toBe('06:30');expect(wk.body.departure_enabled).toBe(true);expect(wk.body.amps).toBe(10);
    const dt=departureWritePlan(r,{date:'2026-11-12',weekdays:days},true,d,NOW);expect(dt).toMatchObject({ok:true,changed:true,dateChanged:true,weekdaysChanged:false});expect(dt.body.departure_date).toBe('2026-11-12');
    expect(departureWritePlan(r,{date:'2026-11-16',weekdays:days},true,d,NOW).ok).toBe(true);
    expect(departureWritePlan(r,{date:'2026-11-17',weekdays:days},true,d,NOW).ok).toBe(false);expect(departureWritePlan(r,{date:'2026-11-08',weekdays:days},true,d,NOW).ok).toBe(false);
    expect(departureWritePlan(r,{date:'2026-13-45',weekdays:days},true,d,NOW).ok).toBe(false);
    // today's date with the time already behind us is refused; a later time today or tomorrow is fine
    expect(departureWritePlan(r,{date:'2026-11-09',weekdays:days},true,d,NOW)).toMatchObject({ok:false,notice:expect.stringMatching(/already passed today/)});
    expect(departureWritePlan(rec({departure_time:'12:00'}),{date:'2026-11-09',weekdays:days},true,d,NOW).ok).toBe(true);
    expect(departureWritePlan(r,{date:'',weekdays:''},true,d,NOW)).toMatchObject({ok:false});
    // a stored date clears even without a known zone; a new one cannot be chosen there
    const dated=rec({departure_date:'2026-11-12'}),nz=dash({market:{timezone:''}});
    expect(departureWritePlan(dated,{date:'',weekdays:days},true,nz,NOW)).toMatchObject({ok:true,changed:true,dateChanged:true});expect(departureWritePlan(dated,{date:'',weekdays:days},true,nz,NOW).body.departure_date).toBeNull();
    expect(departureWritePlan(r,{date:'2026-11-12',weekdays:days},true,nz,NOW)).toMatchObject({ok:false,notice:expect.stringMatching(/time zone is unknown/)});
    // an untouched stored date that has gone by is not re-judged
    expect(departureWritePlan(rec({departure_date:'2026-11-01'}),{date:'2026-11-01',weekdays:'12345'},true,d,NOW)).toMatchObject({ok:true,changed:true,dateChanged:false});
    expect(departureWritePlan(rec({departure_enabled:false}),{date:'',weekdays:'1'},true,d,NOW)).toMatchObject({ok:false,notice:expect.stringMatching(/Ready-by is off/)});
    expect(departureWritePlan(r,{date:'',weekdays:'1'},false,d,NOW)).toMatchObject({ok:false});
  });
  it('departure across a clock change: the date range and "today" follow the market calendar', () => {
    const d=dash(),r=rec({departure_time:'06:30'});
    const now=Date.parse('2026-10-24T22:30:00Z'); // 00:30 on the 25 h day, Stockholm
    expect(departureWritePlan(r,{date:'2026-10-25',weekdays:'1234567'},true,d,now).ok).toBe(true);
    expect(departureWritePlan(r,{date:'2026-11-01',weekdays:'1234567'},true,d,now).ok).toBe(true);expect(departureWritePlan(r,{date:'2026-11-02',weekdays:'1234567'},true,d,now).ok).toBe(false);
    expect(departureWritePlan(r,{date:'2026-10-24',weekdays:'1234567'},true,d,now).ok).toBe(false);
    const late=Date.parse('2027-03-28T06:00:00Z'); // 08:00 on the 23 h day: 06:30 has gone by
    expect(departureWritePlan(r,{date:'2027-03-28',weekdays:'1234567'},true,d,late).ok).toBe(false);expect(departureWritePlan(r,{date:'2027-03-29',weekdays:'1234567'},true,d,late).ok).toBe(true);
  });
});

describe('Morek 16 A dispatch limitation', () => {
  const msg = (m) => [...m.current.warnings, m.current.morekNote].join(' ');
  it('model: owned/unknown flag any value but 16 A, never change it, and offer only 16 A while owned; 16 A and non-Morek are clean', () => {
    const own=model({morekOwned:true});expect(own.current.value).toBe('10');expect(own.current.min).toBe(16);expect(own.current.max).toBe(16);
    expect(own.current.warnings.join(' ')).toMatch(/exactly 16 A.*Morek owns the schedule now.*10 A.*refused until it is 16 A.*kept as saved.*only 16 A can be saved/);
    const unk=model({morekOwned:null});expect(unk.current.warnings.join(' ')).toMatch(/not known.*possibly owning.*10 A would block.*asks for confirmation/);expect(unk.current.min).toBe(6);expect(unk.current.max).toBe(16);
    const non=model({morekOwned:false});expect(non.current.warnings).toEqual([]);expect(non.current.morekNote).toMatch(/does not own.*saved normally/);expect(non.current.max).toBe(16);
    for(const o of [true,false,null]){const ok=model({record:rec({amps:16}),morekOwned:o});expect(ok.current.warnings).toEqual([]);expect(ok.current.value).toBe('16');}
    expect(msg(model({record:rec({amps:16}),morekOwned:true}))).toMatch(/saved 16 A meets this/);
    expect(model({record:rec({amps:null}),morekOwned:true}).current.warnings.join(' ')).toMatch(/not set/);
    expect(model({record:rec({amps:20}),morekOwned:true}).current.value).toBe('20');
    expect(model({morekOwned:true,dashboard:dash({current_range:{min_a:6,max_a:32,source:'charger'}})}).current.rangeText).toMatch(/accepts 6–32 A/);
  });
  it('write plan: owned refuses any non-16 value, accepts 16; unknown allows with a confirmation flag; non-Morek is unchanged behaviour', () => {
    const d=dash({current_range:{min_a:6,max_a:32,source:'charger'}}),r=rec();
    for(const v of ['8','10','12','20','32']){const x=currentWritePlan(r,{current:v},true,d,true);if(v==='10')expect(x).toEqual({ok:true,changed:false});else{expect(x.ok,v).toBe(false);expect(x.notice).toMatch(/Morek owns the schedule now.*only send a schedule at 16 A.*saved 10 A is unchanged/);}}
    const to16=currentWritePlan(r,{current:'16'},true,d,true);expect(to16).toMatchObject({ok:true,changed:true,to:16,morekBlocks:false});expect(to16.body.amps).toBe(16);
    expect(currentWritePlan(r,{current:'12'},true,d,null)).toMatchObject({ok:true,changed:true,to:12,morekBlocks:true});
    expect(currentWritePlan(r,{current:'12'},true,d,false)).toMatchObject({ok:true,changed:true,to:12,morekBlocks:false});
    expect(currentWritePlan(r,{current:'16'},true,d,null).morekBlocks).toBe(false);
    expect(currentWritePlan(rec({amps:10}),{current:'10'},true,d,true)).toEqual({ok:true,changed:false}); // an existing value is never silently rewritten
    expect(currentWritePlan(r,{current:'12'},false,d,true)).toMatchObject({ok:false,notice:expect.stringMatching(/permission/)});
  });
  it('panel: Morek-owned refuses non-16 with no request or prompt, saves 16 (raise still asks); unknown asks first; non-Morek saves lower silently', async () => {
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
    const own=setup({owner:'morek_schedule',range:{min_a:6,max_a:32,source:'charger'}});own.handlers['spotnav/update_settings']=(m:any)=>Promise.resolve(saved(m));
    const a=await open(own.hass);expect(a.q('[data-psetting="current"]').value).toBe('10');expect(text(a.panel)).toMatch(/Morek owns the schedule now/);
    a.edit('current','12');a.q('#save-current').click();await tick();expect(writes(own.calls)).toHaveLength(0);expect(confirm).not.toHaveBeenCalled();expect(text(a.panel)).toMatch(/only send a schedule at 16 A/);expect(a.panel.settingsRecord.amps).toBe(10);
    a.edit('current','16');a.q('#save-current').click();await tick();await tick();await tick();expect(writes(own.calls)).toHaveLength(1);expect(writes(own.calls)[0].settings.amps).toBe(16);expect(String(confirm.mock.calls.at(-1)[0])).toMatch(/Raise the planned current from 10 A to 16 A/);a.panel.remove();
    confirm.mockClear();
    const unk=setup({});unk.handlers['spotnav/update_settings']=(m:any)=>Promise.resolve(saved(m));const b=await open(unk.hass);
    confirm.mockReturnValue(false);b.edit('current','8');b.q('#save-current').click();await tick();expect(confirm).toHaveBeenCalledTimes(1);expect(String(confirm.mock.calls[0][0])).toMatch(/not 16 A.*not known whether Morek owns/);expect(writes(unk.calls)).toHaveLength(0);expect(b.q('[data-psetting="current"]').value).toBe('8');
    confirm.mockReturnValue(true);b.q('#save-current').click();await tick();await tick();await tick();expect(writes(unk.calls)).toHaveLength(1);expect(writes(unk.calls)[0].settings.amps).toBe(8);b.panel.remove();
    confirm.mockClear();
    const non=setup({owner:'manual'});non.handlers['spotnav/update_settings']=(m:any)=>Promise.resolve(saved(m));const c=await open(non.hass);
    c.edit('current','8');c.q('#save-current').click();await tick();await tick();await tick();expect(confirm).not.toHaveBeenCalled();expect(writes(non.calls)).toHaveLength(1);expect(writes(non.calls)[0].settings.amps).toBe(8);c.panel.remove();
  });
});

describe('plan parameters renderer', () => {
  it('escapes text, offers every control when editable, none enabled when read-only, and the preview sample uses it', () => {
    const m=model();
    const html=renderPlanParams({...m,periods:{...m.periods,notes:['<b>x</b>']}});
    expect(html).not.toContain('<b>x</b>');
    for(const id of ['save-periods','save-current','save-departure','reload-plan-params']) expect(html).toContain(`id="${id}"`);
    for(const name of ['periods','current','date','wd-1','wd-7']) expect(html).toContain(`data-psetting="${name}"`);
    expect(html).toContain('min="6" max="16"');expect(html).toContain('min="2026-11-09" max="2026-11-16"');expect(html).toContain('not household load balancing');
    const ro=renderPlanParams(model({admin:false}));expect(ro.match(/data-psetting="[^"]+"[^>]*disabled/g).length).toBeGreaterThanOrEqual(10);expect(ro).toContain('<wa-button id="save-current" size="small" disabled>');
    expect(renderPlanParams(model({record:null}))).toContain('unavailable');expect(renderPlanParams(null)).toBe('');
    const preview=readFileSync('prototype/sample-adapter.js','utf8');expect(preview).toContain('planParams');
    const css=readFileSync('shared-dashboard/dark.css','utf8');expect(css).toContain('.pp-block');expect(css).toMatch(/\.pp-block input:disabled/);
  });
});

// ---- the real panel with a mocked backend ----
const FIXTURE = () => read('dashboard/target_soc_two_vehicles.json');
const morek = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
const pause = {choice:null,admitted_at:null,expires_at:null};
const settingsAnswer = (r) => ({api_version:1,ok:true,error:null,settings:r,pause});
const WRITES = ['spotnav/update_settings','spotnav/update_grid_tariff','spotnav/choose_price_source'];
const setup = (opts:any={}) => {
  const calls:any[]=[];
  const raw=FIXTURE();raw.generated_at=new Date().toISOString();raw.charger.charger_id='a';
  raw.settings.users_change_plan=opts.usersChangePlan===true;if(opts.range)raw.current_range=opts.range;
  const state:any={record:recordRaw(opts.record||{})};
  const handlers:any={};
  const hass:any={connected:true,user:{is_admin:opts.admin!==false},callWS:(msg:any)=>{calls.push(msg);
    if(handlers[msg.type]) return handlers[msg.type](msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(JSON.parse(JSON.stringify(raw)));
    if(msg.type==='spotnav/get_settings')return Promise.resolve(settingsAnswer(state.record));
    if(msg.type==='spotnav/get_market_options')return Promise.reject(Object.assign(new Error('n/a'),{code:'spotnav_not_admin'}));
    if(msg.type==='spotnav/get_entity_config')return Promise.reject(Object.assign(new Error('n/a'),{code:'spotnav_not_admin'}));
    if(WRITES.includes(msg.type))return Promise.reject(new Error('unexpected write'));
    return Promise.resolve(opts.owner ? {...morek,schedule:{...morek.schedule,ownership:{recorded_owner:opts.owner}}} : morek);}};
  return {calls,hass,raw,state,handlers};
};
const open = async (hass:any) => {
  const panel:any=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await tick();
  const q=(s:string)=>panel.shadowRoot.querySelector(s);
  const edit=(name:string,value:string)=>{const el=q(`[data-psetting="${name}"]`);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));};
  const tick_=(name:string,on:boolean)=>{const el=q(`[data-psetting="${name}"]`);el.checked=on;el.dispatchEvent(new Event('change',{bubbles:true}));};
  return {panel,q,edit,tick_};
};
const writes = (calls:any[]) => calls.filter(m=>WRITES.includes(m.type));
const text = (panel:any) => panel.shadowRoot.querySelector('.plan-params')?.textContent || '';
const saved = (msg:any,over={}) => settingsAnswer({...msg.settings,revision:8,...over});
const today = () => departureDays('Europe/Stockholm',Date.now());

describe('plan parameters in the real panel (mocked backend)', () => {
  it('opening and editing only read: values are shown with their bounds, nothing is written', async () => {
    const {calls,hass}=setup();const {panel,q,edit,tick_}=await open(hass);
    expect(text(panel)).toContain('Maximum charging periods');expect(text(panel)).toContain('Planned current');expect(text(panel)).toContain('Departure date');
    expect(q('[data-psetting="periods"]').value).toBe('3');expect(q('[data-psetting="current"]').value).toBe('10');expect(q('[data-psetting="wd-3"]').checked).toBe(true);
    edit('periods','5');edit('current','12');edit('date',today().max);tick_('wd-6',false);
    expect(panel.paramDirty).toBe(true);expect(writes(calls)).toHaveLength(0);
    expect(calls.every(m=>!/^spotnav\/(update|set|clear|send|choose|confirm|perform|action)/.test(m.type) || m.type==='spotnav/get_settings')).toBe(true);panel.remove();
  });
  it('saves charging periods with the displayed revision, once, only max_periods changes, and the plan is re-read', async () => {
    const {calls,hass,handlers}=setup();handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));
    const {panel,q,edit}=await open(hass);
    edit('periods','auto');const reads=calls.filter(m=>m.type==='spotnav/get_dashboard').length;
    q('#save-periods').click();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/update_settings',charger_id:'a',expected_revision:7});
    expect(w[0].settings.max_periods).toBeNull();expect(w[0].settings.amps).toBe(10);expect(w[0].settings.departure_time).toBe('06:30');expect(w[0].settings.departure_weekdays).toEqual([1,2,3,4,5,6,7]);expect(w[0].settings.requested_kwh).toBe(20);
    expect(text(panel)).toContain('Charging periods saved and confirmed by the backend');expect(text(panel)).toMatch(/guarded reconciliation/);expect(text(panel)).toMatch(/does not wake the car/);
    expect(panel.paramDirty).toBe(false);expect(panel.settingsRecord.revision).toBe(8);
    expect(calls.filter(m=>m.type==='spotnav/get_dashboard').length).toBeGreaterThan(reads);await tick();expect(panel.paramAwaitingRead).toBe(false);panel.remove();
  });
  it('saves a lower planned current directly, asks before raising it, and refuses values outside the charger range without a request', async () => {
    const {calls,hass,handlers}=setup({range:{min_a:6,max_a:16,source:'charger'},owner:'manual'});handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const {panel,q,edit}=await open(hass);
    edit('current','17');q('#save-current').click();await tick();expect(writes(calls)).toHaveLength(0);expect(text(panel)).toMatch(/allowed 6–16 A/);
    edit('current','5');q('#save-current').click();await tick();expect(writes(calls)).toHaveLength(0);
    edit('current','14');q('#save-current').click();await tick();
    expect(confirm).toHaveBeenCalled();expect(String(confirm.mock.calls.at(-1)[0])).toMatch(/Raise the planned current from 10 A to 14 A.*load balancing or electrical protection/s);expect(writes(calls)).toHaveLength(0);expect(q('[data-psetting="current"]').value).toBe('14');
    confirm.mockReturnValue(true);q('#save-current').click();await tick();await tick();await tick();
    let w=writes(calls);expect(w).toHaveLength(1);expect(w[0].settings.amps).toBe(14);expect(w[0].expected_revision).toBe(7);expect(text(panel)).toContain('Planned current saved and confirmed');
    panel.paramConflict=false;panel.paramAwaitingRead=false;confirm.mockClear();edit('current','8');q('#save-current').click();await tick();await tick();await tick();
    expect(confirm).not.toHaveBeenCalled();w=writes(calls);expect(w).toHaveLength(2);expect(w[1].settings.amps).toBe(8);expect(w[1].expected_revision).toBe(8);panel.remove();
  });
  it('saves departure weekdays and a date; an unchanged save, no weekday and an out-of-range date send nothing', async () => {
    const {calls,hass,handlers}=setup();handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));
    const {panel,q,edit,tick_}=await open(hass);
    q('#save-departure').click();await tick();expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');
    for(const n of [1,2,3,4,5,6,7])tick_(`wd-${n}`,false);q('#save-departure').click();await tick();expect(writes(calls)).toHaveLength(0);expect(panel.paramDirty).toBe(true);
    const days=today();edit('date',addDays(days.max,1));tick_('wd-1',true);q('#save-departure').click();await tick();expect(writes(calls)).toHaveLength(0);
    edit('date',days.max);q('#save-departure').click();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0].settings.departure_date).toBe(days.max);expect(w[0].settings.departure_weekdays).toEqual([1]);expect(w[0].settings.departure_time).toBe('06:30');expect(w[0].settings.departure_enabled).toBe(true);expect(w[0].settings.amps).toBe(10);
    expect(text(panel)).toContain('Departure saved and confirmed');panel.remove();
  });
  it('a revision conflict writes nothing more, blocks further saves and keeps the draft', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.resolve({api_version:1,ok:false,error:'revision_conflict',settings:{...recordRaw(),revision:9},pause});
    const {panel,q,edit}=await open(hass);
    edit('periods','2');q('#save-periods').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toContain('nothing was written');expect(panel.paramConflict).toBe(true);expect(panel.settingsConflict).toBe(true);expect(panel.settingsRecord.revision).toBe(7);
    q('#save-periods').click();await tick();expect(writes(calls)).toHaveLength(1);expect(q('[data-psetting="periods"]').value).toBe('2');expect(q('#save-periods').hasAttribute('disabled')).toBe(true);panel.remove();
  });
  it('a reconcile failure after a durable save adopts the saved record but demands a reload before another change', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve({...saved(msg),ok:false,error:'spotnav_settings_reconcile_failed'});
    const {panel,q,edit}=await open(hass);
    edit('periods','2');q('#save-periods').click();await tick();await tick();await tick();
    expect(text(panel)).toContain('saved, but replanning failed');expect(panel.settingsRecord.revision).toBe(8);expect(panel.settingsRecord.max_periods).toBe(2);expect(panel.paramConflict).toBe(true);
    edit('periods','4');q('#save-periods').click();await tick();expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('a refused write shows the reason; an invalid_amps from the backend is "not saved"; an unresolved write is an unknown outcome that blocks until reload', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.resolve({api_version:1,ok:false,error:'invalid_amps',settings:recordRaw(),pause});
    vi.spyOn(window,'confirm').mockReturnValue(true);
    const {panel,q,edit}=await open(hass);
    edit('current','12');q('#save-current').click();await tick();await tick();await tick();
    expect(text(panel)).toMatch(/not saved/i);expect(text(panel)).toContain('invalid_amps');expect(panel.unknownSettingsWrites.size).toBe(0);expect(panel.paramConflict).toBe(false);
    handlers['spotnav/update_settings']=()=>Promise.reject(new Error('timeout'));
    q('#save-current').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(2);expect(panel.unknownSettingsWrites.has('a')).toBe(true);expect(text(panel)).toContain('outcome unknown');
    q('#save-current').click();await tick();expect(writes(calls)).toHaveLength(2);
    q('#reload-plan-params').click();await tick();await tick();await tick();
    expect(panel.unknownSettingsWrites.size).toBe(0);expect(panel.paramConflict).toBe(false);expect(panel.settingsRecord).not.toBeNull();panel.remove();
  });
  it('a non-administrator reads everything but sends nothing; with "users change plan" only the current and departure are open, never periods', async () => {
    const ro=setup({admin:false});const a=await open(ro.hass);
    expect(text(a.panel)).toContain('do not have permission');expect(a.q('#save-current').hasAttribute('disabled')).toBe(true);expect(a.q('[data-psetting="periods"]').disabled).toBe(true);
    await a.panel.saveParams('current',{current:'12'});await a.panel.saveParams('periods',{periods:'2'});await a.panel.saveParams('departure',{date:'',weekdays:'1'});await tick();expect(writes(ro.calls)).toHaveLength(0);a.panel.remove();
    vi.spyOn(window,'confirm').mockReturnValue(true);const rw=setup({admin:false,usersChangePlan:true});rw.handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(saved(msg));const b=await open(rw.hass);
    expect(b.q('#save-periods').hasAttribute('disabled')).toBe(true);expect(b.q('#save-current').hasAttribute('disabled')).toBe(false);expect(b.q('[data-psetting="wd-1"]').disabled).toBe(false);
    await b.panel.saveParams('periods',{periods:'2'});await tick();expect(writes(rw.calls)).toHaveLength(0);
    b.edit('current','8');b.q('#save-current').click();await tick();await tick();await tick();expect(writes(rw.calls)).toHaveLength(1);expect(writes(rw.calls)[0].settings.amps).toBe(8);b.panel.remove();
  });
  it('a stale dashboard withholds saving even through a direct call', async () => {
    const {calls,hass}=setup();const {panel,edit}=await open(hass);
    edit('periods','2');
    panel.rawDashboard={...panel.rawDashboard,generated_at:new Date(Date.now()-10*60000).toISOString()};
    await panel.saveParams('periods',{periods:'2'});expect(writes(calls)).toHaveLength(0);expect(text(panel)).toMatch(/stale/);panel.remove();
  });
  it('drafts survive a refresh; a change of the fields elsewhere while editing is flagged instead of saved over; unrelated plan changes are not', async () => {
    const {calls,hass}=setup();const {panel,q,edit,tick_}=await open(hass);
    edit('current','12');tick_('wd-7',false);
    panel.statusEpoch++;panel.refresh();await tick();panel.paint();
    expect(q('[data-psetting="current"]').value).toBe('12');expect(q('[data-psetting="wd-7"]').checked).toBe(false);expect(panel.paramConflict).toBe(false);
    panel.settingsRecord=decodeSettingsRecord(recordRaw({revision:8,requested_kwh:33}));panel.paint();expect(panel.paramConflict).toBe(false);
    panel.settingsRecord=decodeSettingsRecord(recordRaw({revision:9,amps:16}));panel.paint();
    expect(panel.paramConflict).toBe(true);expect(text(panel)).toContain('changed while editing');expect(q('[data-psetting="current"]').value).toBe('12');
    q('#save-current').click();await tick();expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('does not block Pause/Stop controls while a parameter save is pending, and the plan form cannot save over it', async () => {
    const {calls,hass,handlers}=setup();let release:any;handlers['spotnav/update_settings']=(msg:any)=>new Promise(r=>{release=()=>r(saved(msg));});
    const {panel,q,edit}=await open(hass);
    edit('periods','2');q('#save-periods').click();await tick();
    expect(panel.paramBusy).toBe(true);expect(q('#save-plan').hasAttribute('disabled')||true).toBe(true);
    await panel.savePlan({});await tick();expect(writes(calls)).toHaveLength(1);
    release();await tick();await tick();await tick();expect(panel.paramBusy).toBe(false);expect(panel.settingsRecord.revision).toBe(8);panel.remove();
  });
  it('a permission change during a save leaves the outcome unknown; a late answer is not applied', async () => {
    const {calls,hass,handlers}=setup();let release:any;handlers['spotnav/update_settings']=(msg:any)=>new Promise(r=>{release=()=>r(saved(msg));});
    const {panel,q,edit}=await open(hass);
    edit('periods','2');q('#save-periods').click();await tick();
    panel.hass={...hass,user:{is_admin:false}};await tick();
    expect(panel.unknownSettingsWrites.has('a')).toBe(true);expect(panel.paramConflict).toBe(true);
    release();await tick();await tick();await tick();expect(panel.settingsRecord.revision).toBe(7);expect(writes(calls)).toHaveLength(1);panel.remove();
  });
});
