// @vitest-environment jsdom
// @ts-nocheck
// Stage 13.2: market & charging-cost settings in the shared sidebar UI (pure model + the real panel, mocked backend).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import '../sidebar/panel.js';
import { marketCostsModel, marketWritePlan, tariffWritePlan, sourceWritePlan, costSignature } from '../sidebar/market-costs.js';
import { renderMarketCosts } from '../shared-dashboard/market-costs-view.js';
import { decodeMarketOptions } from '../src/market.ts';
import { decodeSettingsRecord } from '../src/settings.ts';

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

// ---- fixtures ----
const area = (over={}) => ({area_id:'SE4',name:'Malmö · SE4',countries:['SE'],timezone:'Europe/Stockholm',currency:'SEK',major_unit:'kr',minor_unit:'öre',suggestions:{vat_percent:25,tax_minor:36,transfer_minor:30},...over});
const areaV2 = (over={}) => area({market_timezone:'Europe/Stockholm',included:[],source:null,...over});
const optionsRaw = (areas=[area(),area({area_id:'NO1',name:'Oslo · NO1',currency:'NOK',minor_unit:'øre',countries:['NO']}),areaV2({area_id:'DE-LU',name:'Germany',currency:'EUR',major_unit:'€',minor_unit:'c',countries:['DE'],suggestions:{vat_percent:null,tax_minor:null,transfer_minor:null}})],over={}) => ({api_version:1,state:'ready',reason:null,areas,configured_area:'SE4',...over});
const options = (...a) => { const d=decodeMarketOptions(optionsRaw(...a)); if(!d.ok) throw new Error('options '+d.failure); return d.value; };
const recordRaw = (over={}) => ({revision:7,area_id:'SE4',overrides:[],phases:3,amps:10,requested_kwh:20,max_periods:3,departure_enabled:true,departure_time:'06:30',departure_date:null,departure_weekdays:[1,2,3,4,5,6,7],strategy:'cheapest',driver:'target_soc',target:{vehicle_id:null,target_percent:80},soft_price_cap:0.1,cap_price_basis:'nord_pool',minimum_ready_by_soc:40,...over});
const rec = (over={}) => decodeSettingsRecord(recordRaw(over));
const tariffRaw = (over={}) => ({entry_id:'price1',write_revision:3,transfer_percent:{policy:'off',explicit_value:null,effective_value:null,unit:'%'},transfer_high:{policy:'off',explicit_value:null,effective_value:null,unit:'öre/kWh'},high_load_window:null,writable:true,...over});
const win = {days:'weekdays',from_month:11,to_month:3,from_hour:7,to_hour:19};
const block = (over={}) => ({...tariffRaw(),demand:null,...over});
const iv = (raw,eff) => ({startMs:0,endMs:900000,raw_price:raw,effective_price:eff});
const dash = (over={}) => ({generated_at:new Date(1000).toISOString(),prices:{provider:{key:'nordpool',name:'Nord Pool',url:'https://example.test/np',notice:null},state:'ready',reason:null,waiting_for_tomorrow:false,unpriced:false,interval_count:1,resolution_minutes:15,intervals:[iv(0.5,0.7)]},market:{currency:'SEK',major_unit:'kr',minor_unit:'öre',area_name:'Malmö',catalogue_state:'ready'},fiscal:null,price_source:null,grid_tariff:null,...over});
const model = (over={}) => marketCostsModel({admin:true,record:rec(),options:options(),optionsAt:1000,now:2000,dashboard:dash(),dashboardFresh:true,areaDraft:null,...over});
const rows = (m) => Object.fromEntries(m.fees.map(f=>[f.key,f]));
const vals = (over={}) => ({area:'SE4',vat:{mode:'off',figure:''},tax:{mode:'off',figure:''},transfer:{mode:'off',figure:''},...over});

describe('market & costs model (pure)', () => {
  it('shows the provider, held data and currency separately from the saved area, and a missing provider as missing', () => {
    const m=model();
    expect(m.provider).toBe('Price provider: Nord Pool.');expect(m.url).toBe('https://example.test/np');
    expect(m.held).toMatch(/state ready; 1 held intervals at 15 min.*not proof the provider answered/);
    expect(m.currencyText).toMatch(/Currency SEK \(kr, minor unit öre\).*SEK\/kWh.*öre\/kWh/);
    const none=model({dashboard:dash({prices:{...dash().prices,provider:{key:null,name:null,url:null,notice:{code:'add_nordpool',params:{}}}}})});
    expect(none.provider).toMatch(/No price provider is configured/);expect(none.providerNote).toMatch(/add nordpool/);
    const unknown=model({dashboard:dash({prices:{...dash().prices,provider:null}})});expect(unknown.provider).toMatch(/unknown/);
    // provider facts never override the status notice
    expect(model({notice:'hello'}).notice).toBe('hello');
  });
  it('lists areas without choosing one, keeps an unlisted saved area visible and states an area change as unsaved', () => {
    const m=model();
    expect(m.area.options.map(o=>o.value)).toEqual(['SE4','NO1','DE-LU']);expect(m.area.value).toBe('SE4');
    const gone=model({record:rec({area_id:'XX9'})});
    expect(gone.area.options[0]).toEqual({value:'XX9',text:'XX9 (no longer listed)'});expect(gone.notes.join(' ')).toMatch(/no longer in the area list/);expect(gone.fees).toEqual([]);
    const none=model({record:rec({area_id:null})});expect(none.area.options[0].text).toMatch(/No area saved/);expect(none.fees).toEqual([]);
    const draft=model({areaDraft:'NO1'});
    expect(draft.area.value).toBe('NO1');expect(draft.areaDraft).toBe(true);expect(draft.notes.join(' ')).toMatch(/provider above are for the saved area/);
    expect(draft.currencyText).toMatch(/Currency NOK/);expect(draft.provider).toBe('Price provider: Nord Pool.');
  });
  it('needs the area list and the saved record, and reports loading and unavailable honestly', () => {
    expect(model({options:null}).state).toBe('unavailable');expect(model({options:null,loading:true}).state).toBe('loading');
    expect(model({record:null}).state).toBe('unavailable');
    const un=model({options:null});expect(un.canEdit).toBe(false);expect(renderMarketCosts(un)).toContain('id="reload-market-costs"');expect(renderMarketCosts(un)).toContain('Price provider');
  });
  it('fee rows: off, suggested (never copied), custom, retained figure, no suggestion, and included components locked', () => {
    const r=rec({overrides:[{area_id:'SE4',vat:{enabled:true,value:null},tax:{enabled:true,value:12.5},transfer:{enabled:false,value:7}}]});
    const f=rows(model({record:r}));
    expect(f.vat.mode).toBe('suggested');expect(f.vat.hint).toMatch(/suggestion, 25 %.*not copied/);expect(f.vat.figure).toBe('');
    expect(f.tax.mode).toBe('custom');expect(f.tax.figure).toBe('12.5');expect(f.tax.unit).toBe('öre/kWh');
    expect(f.transfer.mode).toBe('off');expect(f.transfer.figure).toBe('7');expect(f.transfer.hint).toMatch(/Not added/);
    const de=rows(model({record:rec({area_id:'DE-LU'})}));
    expect(de.vat.modes.map(o=>o.value)).toEqual(['off','custom']);expect(de.vat.mode).toBe('off');
    const inc=model({options:options([areaV2({included:['transfer','vat']})]),record:rec({overrides:[{area_id:'SE4',vat:{enabled:true,value:20},tax:{enabled:false,value:null},transfer:{enabled:true,value:30}}]})});
    expect(rows(inc).transfer.included).toBe(true);expect(rows(inc).transfer.canEdit).toBe(false);expect(rows(inc).transfer.hint).toMatch(/Already included.*30 öre\/kWh is kept but not used|stored figure of 30/);
    const html=renderMarketCosts(inc);expect(html).toContain('data-included="true"');expect(html).not.toContain('data-msetting="transfer-mode"');expect(html).toContain('data-msetting="tax-mode"');
  });
  it('raw published price and configured variable cost stay distinct, negative values and unknowns are kept as such, in the currency unit', () => {
    const sek=model({now:1000});expect(sek.text).toMatch(/raw published price 0\.5 SEK\/kWh · configured variable cost 0\.7 SEK\/kWh/);expect(sek.text).toMatch(/different figures/);
    const eur=model({now:1000,dashboard:dash({market:{...dash().market,currency:'EUR'},prices:{...dash().prices,intervals:[iv(-0.05,-0.04)]}})});
    expect(eur.text).toMatch(/raw published price -5 c\/kWh · configured variable cost -4 c\/kWh/);
    const nullCost=model({now:1000,dashboard:dash({prices:{...dash().prices,intervals:[iv(0.3,null)]}})});expect(nullCost.text).toMatch(/configured variable cost unknown/);
    const none=model({now:99999999});expect(none.text).toMatch(/no held price for this moment \(unknown, not zero\)/);
    expect(model().basis).toMatch(/follows the raw price’s sign.*multiplied by \(1 \+ VAT\).*fees may make the final cost positive/s);
  });
  it('permission, stale list, stale dashboard, busy, conflict and a pending post-save read all withhold editing', () => {
    expect(model().canEdit).toBe(true);
    const non=model({admin:false});expect(non.canEdit).toBe(false);expect(non.notes.join(' ')).toMatch(/Administrator permission/);expect(non.fees.length).toBe(3);
    expect(model({optionsAt:1000,now:1000+1300000}).canEdit).toBe(false);expect(model({failed:true}).canEdit).toBe(false);
    expect(model({dashboardFresh:false}).canEdit).toBe(false);expect(model({busy:true}).canEdit).toBe(false);expect(model({conflict:true}).canEdit).toBe(false);
    expect(model({blocked:true}).canEdit).toBe(false);
    const wait=model({awaitingRead:true});expect(wait.canEdit).toBe(false);expect(wait.notes.join(' ')).toMatch(/fresh dashboard read after the last save/);
    expect(model({options:options(),dashboard:null}).canEdit).toBe(false);
    const held=model({options:decodeMarketOptions(optionsRaw(undefined,{state:'unavailable',reason:'offline',areas:[]})).value});expect(held.canEdit).toBe(false);
  });
  it('a stale (older-list) market is editable but called stale; nothing held is read-only', () => {
    const stale=decodeMarketOptions(optionsRaw(undefined,{state:'stale',reason:'offline'})).value;
    const m=model({options:stale});expect(m.canEdit).toBe(true);expect(m.notes.join(' ')).toMatch(/./);
  });
  it('the grid tariff block: percentage, high-load fee, suggested hours, included lock, kept demand components, no entry', () => {
    const m=model({dashboard:dash({price_source:{entry_id:'price1',title:'Sample',charger_count:2,choices:[],writable:true,duplicate:null},grid_tariff:block({transfer_percent:{policy:'manual',explicit_value:5,effective_value:5,unit:'%'},demand:{components:[{window:null,top_n:1,price_per_kw:{winter:1,summer:null}}]}})})});
    expect(m.tariff.percent.mode).toBe('custom');expect(m.tariff.percent.figure).toBe('5');expect(m.tariff.window.suggested).toBe(true);expect(m.tariff.notes.join(' ')).toMatch(/1 demand-charge component are kept exactly as stored/);
    expect(m.shared).toMatch(/used by 2 chargers; a change applies to all/);
    const inc=model({dashboard:dash({price_source:{entry_id:'p',title:'S',charger_count:1,choices:[],writable:true,duplicate:null},grid_tariff:block({transfer_percent:{policy:'included',explicit_value:null,effective_value:null,unit:'%'},transfer_high:{policy:'included',explicit_value:null,effective_value:null,unit:'öre/kWh'}})})});
    expect(inc.tariff.included).toBe(true);expect(inc.tariff.canEdit).toBe(false);expect(renderMarketCosts(inc)).not.toContain('data-msetting="percent-mode"');
    const own=model();expect(own.tariff).toBeNull();expect(own.noEntryNote).toMatch(/own settings/);
    const ro=model({dashboard:dash({price_source:{entry_id:'p',title:'S',charger_count:1,choices:[],writable:false,duplicate:null},grid_tariff:block({writable:false})})});expect(ro.tariff.canEdit).toBe(false);
    const nounit=model({dashboard:dash({price_source:{entry_id:'p',title:'S',charger_count:1,choices:[],writable:true,duplicate:null},grid_tariff:block({transfer_high:{policy:'off',explicit_value:null,effective_value:null,unit:null}})})});
    expect(nounit.tariff.high.unitKnown).toBe(false);expect(renderMarketCosts(nounit)).toMatch(/data-msetting="high-mode"[^>]*disabled/);
  });
});

describe('market write plans', () => {
  const o=options();
  it('unchanged saves state nothing; a never-configured area with everything off is also unchanged', () => {
    expect(marketWritePlan(rec(),o,vals(),true)).toEqual({ok:true,changed:false});
    const r=rec({overrides:[{area_id:'SE4',vat:{enabled:false,value:20},tax:{enabled:true,value:null},transfer:{enabled:true,value:3}}]});
    expect(marketWritePlan(r,o,vals({vat:{mode:'off',figure:'20'},tax:{mode:'suggested',figure:''},transfer:{mode:'custom',figure:'3'}}),true)).toEqual({ok:true,changed:false});
  });
  it('states a custom figure, the suggestion as null (not a copy), off with a retained figure and area changes', () => {
    const p=marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:'25'},tax:{mode:'suggested',figure:''},transfer:{mode:'off',figure:'4'}}),true);
    expect(p.changed).toBe(true);expect(p.areaChanged).toBe(false);
    expect(p.body.overrides).toEqual([{area_id:'SE4',vat:{enabled:true,value:25},tax:{enabled:true,value:null},transfer:{enabled:false,value:4}}]);
    expect(p.body.requested_kwh).toBe(20);expect(p.body.soft_price_cap).toBe(0.1);
    const moved=marketWritePlan(rec(),o,vals({area:'NO1'}),true);
    expect(moved).toMatchObject({ok:true,changed:true,areaChanged:true,fromArea:'SE4',toArea:'NO1'});expect(moved.body.area_id).toBe('NO1');expect(moved.body.overrides).toEqual([]);
    const zero=marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:'0'}}),true);expect(zero.body.overrides[0].vat).toEqual({enabled:true,value:0});
    const comma=marketWritePlan(rec(),o,vals({tax:{mode:'custom',figure:'12,5'}}),true);expect(comma.body.overrides[0].tax).toEqual({enabled:true,value:12.5});
  });
  it('refuses missing, invalid and negative figures, an unlisted new area, no area, a non-administrator, and ignores included components', () => {
    expect(marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:''}}),true).ok).toBe(false);
    expect(marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:'abc'}}),true).ok).toBe(false);
    expect(marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:'-1'}}),true).ok).toBe(false);
    expect(marketWritePlan(rec(),o,vals({area:'ZZ'}),true).ok).toBe(false);
    expect(marketWritePlan(rec(),o,vals({area:''}),true).ok).toBe(false);
    expect(marketWritePlan(rec(),o,vals({vat:{mode:'custom',figure:'1'}}),false)).toMatchObject({ok:false});
    expect(marketWritePlan(null,o,vals(),true).ok).toBe(false);
    const inc=options([areaV2({included:['transfer']})]);
    const r=rec({overrides:[{area_id:'SE4',vat:{enabled:false,value:null},tax:{enabled:false,value:null},transfer:{enabled:true,value:30}}]});
    expect(marketWritePlan(r,inc,vals({transfer:{mode:'custom',figure:'99'}}),true)).toEqual({ok:true,changed:false});
    const dkNoSuggestion=marketWritePlan(rec({area_id:'DE-LU'}),o,vals({area:'DE-LU',vat:{mode:'suggested',figure:''}}),true);expect(dkNoSuggestion.ok).toBe(false);
  });
  it('tariff plan: unchanged, percentage, high-load fee with its hours, off keeps stored figures, demand components kept, refusals', () => {
    const b=block({transfer_percent:{policy:'manual',explicit_value:5,effective_value:5,unit:'%'},transfer_high:{policy:'off',explicit_value:40,effective_value:null,unit:'öre/kWh'},high_load_window:win,demand:{components:[{window:null,top_n:3,price_per_kw:{winter:50,summer:null}}]}});
    const same={percent:{mode:'custom',figure:'5'},high:{mode:'off',figure:'40'},window:{days:'all',fromMonth:'1',toMonth:'2',fromHour:'3',toHour:'4'}};
    expect(tariffWritePlan(b,same)).toEqual({ok:true,changed:false});
    const change=tariffWritePlan(b,{...same,percent:{mode:'off',figure:'5'},high:{mode:'custom',figure:'42'},window:{days:'mon_sat',fromMonth:'10',toMonth:'3',fromHour:'6',toHour:'22'}});
    expect(change).toMatchObject({ok:true,changed:true,expected:3});
    expect(change.body.transfer_percent).toEqual({enabled:false,value:5});expect(change.body.transfer_high).toEqual({enabled:true,value:42});
    expect(change.body.high_load_window).toEqual({days:'mon_sat',from_month:10,to_month:3,from_hour:6,to_hour:22});
    expect(change.body.demand_components).toEqual([{window:null,top_n:3,price_per_kw:{winter:50,summer:null}}]);
    const night=tariffWritePlan(block(),{percent:{mode:'off'},high:{mode:'custom',figure:'1'},window:{days:'all',fromMonth:'1',toMonth:'12',fromHour:'22',toHour:'6'}});expect(night.changed).toBe(true);expect(night.body.high_load_window.from_hour).toBe(22);
    const bad=(v)=>tariffWritePlan(block(),v);
    expect(bad({percent:{mode:'custom',figure:''},high:{mode:'off'}}).ok).toBe(false);
    expect(bad({percent:{mode:'custom',figure:'-2'},high:{mode:'off'}}).ok).toBe(false);
    expect(bad({percent:{mode:'off'},high:{mode:'custom',figure:'x'},window:{}}).ok).toBe(false);
    expect(bad({percent:{mode:'off'},high:{mode:'custom',figure:'1'},window:{days:'all',fromMonth:'1',toMonth:'2',fromHour:'5',toHour:'5'}}).ok).toBe(false);
    expect(bad({percent:{mode:'off'},high:{mode:'custom',figure:'1'},window:{days:'bogus',fromMonth:'1',toMonth:'2',fromHour:'5',toHour:'6'}}).ok).toBe(false);
    expect(bad({percent:{mode:'off'},high:{mode:'custom',figure:'1'},window:{days:'all',fromMonth:'13',toMonth:'2',fromHour:'5',toHour:'6'}}).ok).toBe(false);
    expect(tariffWritePlan(null,same).ok).toBe(false);expect(tariffWritePlan(block({writable:false}),same).ok).toBe(false);
    const inc=block({transfer_percent:{policy:'included',explicit_value:null,effective_value:null,unit:'%'},transfer_high:{policy:'included',explicit_value:null,effective_value:null,unit:'öre/kWh'}});expect(tariffWritePlan(inc,same).ok).toBe(false);
    expect(tariffWritePlan(block({transfer_high:{policy:'off',explicit_value:null,effective_value:null,unit:null}}),{percent:{mode:'off'},high:{mode:'custom',figure:'1'},window:{days:'all',fromMonth:'1',toMonth:'2',fromHour:'1',toHour:'2'}}).ok).toBe(false);
  });
  it('price-entry plan never replaces the saved entry unless another offered one is chosen', () => {
    const s={base:'a',count:2,choices:[{value:'a',text:'A'},{value:'b',text:'B'}]};
    expect(sourceWritePlan(s,{entry:'a'})).toEqual({ok:true,changed:false});
    expect(sourceWritePlan(s,{entry:'b'})).toMatchObject({ok:true,changed:true,entryId:'b',from:'a',count:2});
    expect(sourceWritePlan(s,{entry:'zzz'}).ok).toBe(false);expect(sourceWritePlan(null,{entry:'b'}).ok).toBe(false);
  });
  it('signature changes when the saved fees, area, inclusions or tariff change', () => {
    const o=options(),b=block();
    const base=costSignature(rec(),o,b,'SE4');
    expect(costSignature(rec({overrides:[{area_id:'SE4',vat:{enabled:true,value:1},tax:{enabled:false,value:null},transfer:{enabled:false,value:null}}]}),o,b,'SE4')).not.toBe(base);
    expect(costSignature(rec({area_id:'NO1'}),o,b,'NO1')).not.toBe(base);
    expect(costSignature(rec(),options([areaV2({included:['vat']})]),b,'SE4')).not.toBe(base);
    expect(costSignature(rec(),o,block({write_revision:4,transfer_percent:{policy:'manual',explicit_value:2,effective_value:2,unit:'%'}}),'SE4')).not.toBe(base);
    expect(costSignature(rec({revision:99}),o,b,'SE4')).toBe(base);
  });
  it('parity: the shared renderer escapes text, offers every control when editable, none enabled when read-only, and the preview sample uses it', () => {
    const html=renderMarketCosts(model({dashboard:dash({prices:{...dash().prices,provider:{key:'x',name:'<b>P</b>',url:'https://e.test/?a=1&b=2',notice:null}},price_source:{entry_id:'p1',title:'<i>T</i>',charger_count:1,choices:[{entry_id:'p1',title:'<i>T</i>'},{entry_id:'p2',title:'Other'}],writable:true,duplicate:null},grid_tariff:block()})}));
    expect(html).not.toContain('<b>P</b>');expect(html).not.toContain('<i>T</i>');
    for(const id of ['save-market','save-tariff','save-price-entry','reload-market-costs']) expect(html).toContain(`id="${id}"`);
    for(const name of ['area','vat-mode','vat-figure','tax-mode','transfer-mode','percent-mode','percent-figure','high-mode','high-figure','win-days','win-from-month','win-to-month','win-from-hour','win-to-hour','entry']) expect(html).toContain(`data-msetting="${name}"`);
    const ro=renderMarketCosts(model({admin:false,dashboard:dash({grid_tariff:null})}));
    expect(ro.match(/data-msetting="[^"]+"[^>]*disabled/g).length).toBeGreaterThanOrEqual(6);expect(ro).toContain('<wa-button id="save-market" size="small" disabled>');
    const preview=readFileSync('prototype/sample-adapter.js','utf8');expect(preview).toContain('marketCosts');
    expect(renderMarketCosts(null)).toBe('');
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
  if(opts.tariff!==false){raw.grid_tariff=tariffRaw(opts.tariff||{});}
  raw.price_source=opts.priceSource===null?null:{entry_id:'price1',title:'Sample market',charger_count:1,choices:[{entry_id:'price1',title:'Sample market'},{entry_id:'price2',title:'Other market'}],writable:true,duplicate:null,...(opts.priceSource||{})};
  const state:any={record:recordRaw(opts.record||{}),options:opts.options||optionsRaw()};
  const handlers:any={};
  const hass:any={connected:true,user:{is_admin:opts.admin!==false},callWS:(msg:any)=>{calls.push(msg);
    if(handlers[msg.type]) return handlers[msg.type](msg);
    if(msg.type==='spotnav/list_chargers')return Promise.resolve({api_version:1,chargers:[{charger_id:'a',charger_name:'A'}]});
    if(msg.type==='spotnav/get_dashboard')return Promise.resolve(JSON.parse(JSON.stringify(raw)));
    if(msg.type==='spotnav/get_settings')return Promise.resolve(settingsAnswer(state.record));
    if(msg.type==='spotnav/get_market_options')return Promise.resolve(state.options);
    if(msg.type==='spotnav/get_entity_config')return Promise.reject(Object.assign(new Error('n/a'),{code:'spotnav_not_admin'}));
    if(WRITES.includes(msg.type))return Promise.reject(new Error('unexpected write'));
    return Promise.resolve(morek);}};
  return {calls,hass,raw,state,handlers};
};
const open = async (hass:any) => {
  const panel:any=document.createElement('spotnav-enhanced-panel');panel.hass=hass;document.body.append(panel);await tick();
  const select=panel.shadowRoot.querySelector('#charger');select.value='a';select.dispatchEvent(new Event('change'));await tick();await tick();
  const q=(s:string)=>panel.shadowRoot.querySelector(s);
  const edit=(name:string,value:string)=>{const el=q(`[data-msetting="${name}"]`);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));};
  return {panel,q,edit};
};
const writes = (calls:any[]) => calls.filter(m=>WRITES.includes(m.type));
const text = (panel:any) => panel.shadowRoot.querySelector('.market-costs')?.textContent || '';
const updatedRecord = (msg:any,over={}) => settingsAnswer({...recordRaw(),revision:8,area_id:msg.settings.area_id,overrides:msg.settings.overrides,...over});

describe('market & costs in the real panel (mocked backend)', () => {
  it('opening and editing only read: the area list is read, provider and fees are shown, nothing is written', async () => {
    const {calls,hass}=setup();const {panel,q,edit}=await open(hass);
    expect(calls.some(m=>m.type==='spotnav/get_market_options')).toBe(true);
    expect(text(panel)).toContain('Price area, VAT, energy tax');expect(text(panel)).toContain('No price provider is configured');
    expect(q('[data-msetting="area"]').value).toBe('SE4');expect(q('[data-msetting="vat-mode"]').value).toBe('off');expect(q('[data-msetting="vat-figure"]').disabled).toBe(true);
    edit('vat-mode','custom');expect(q('[data-msetting="vat-figure"]').disabled).toBe(false);edit('vat-figure','25');edit('area','NO1');edit('percent-mode','custom');
    expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('saves VAT, energy tax and the flat grid fee with the displayed revision, once, and confirms from the backend answer', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(updatedRecord(msg));
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');edit('tax-mode','suggested');edit('transfer-mode','custom');edit('transfer-figure','12.5');
    const dashboardReads=calls.filter(m=>m.type==='spotnav/get_dashboard').length;
    q('#save-market').click();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);
    expect(w[0]).toMatchObject({type:'spotnav/update_settings',charger_id:'a',expected_revision:7});
    expect(w[0].settings.area_id).toBe('SE4');
    expect(w[0].settings.overrides).toEqual([{area_id:'SE4',vat:{enabled:true,value:25},tax:{enabled:true,value:null},transfer:{enabled:true,value:12.5}}]);
    expect(w[0].settings.requested_kwh).toBe(20);expect(w[0].settings.soft_price_cap).toBe(0.1);
    expect(text(panel)).toContain('Area and taxes saved and confirmed by the backend');expect(text(panel)).toMatch(/does not change the provider/);
    expect(panel.costDirty).toBe(false);expect(panel.settingsRecord.revision).toBe(8);
    // the plan is updated from the backend: the dashboard is read again and saving waits for it
    expect(calls.filter(m=>m.type==='spotnav/get_dashboard').length).toBeGreaterThan(dashboardReads);
    await tick();expect(panel.costAwaitingRead).toBe(false);panel.remove();
  });
  it('an unchanged save sends nothing and says so', async () => {
    const {calls,hass}=setup();const {panel,q}=await open(hass);
    q('#save-market').click();await tick();
    expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');panel.remove();
  });
  it('an invalid figure sends nothing, keeps the draft and shows the reason', async () => {
    const {calls,hass}=setup();const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','');q('#save-market').click();await tick();
    expect(writes(calls)).toHaveLength(0);expect(panel.costDirty).toBe(true);expect(q('[data-msetting="vat-mode"]').value).toBe('custom');expect(text(panel).length).toBeGreaterThan(100);panel.remove();
  });
  it('an area change is confirmed, states the provider/currency effect and sends the new area; cancelling sends nothing', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve(updatedRecord(msg));
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const {panel,q,edit}=await open(hass);
    edit('area','NO1');expect(panel.marketArea).toBe('NO1');expect(text(panel)).toContain('provider above are for the saved area');
    q('#save-market').click();await tick();
    expect(confirm).toHaveBeenCalled();expect(String(confirm.mock.calls.at(-1)[0])).toMatch(/Switch the price area from SE4 to NO1.*provider route.*not converted/s);
    expect(writes(calls)).toHaveLength(0);
    confirm.mockReturnValue(true);q('#save-market').click();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0].settings.area_id).toBe('NO1');expect(panel.marketArea).toBeNull();panel.remove();
  });
  it('switching the area after editing fees asks first and restores the area when declined', async () => {
    const {calls,hass}=setup();const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','9');edit('area','NO1');await tick();
    expect(confirm).toHaveBeenCalled();expect(panel.marketArea).toBeNull();expect(q('[data-msetting="area"]').value).toBe('SE4');expect(q('[data-msetting="vat-figure"]').value).toBe('9');
    confirm.mockReturnValue(true);edit('area','NO1');await tick();
    expect(panel.marketArea).toBe('NO1');expect(q('[data-msetting="vat-mode"]').value).toBe('off');expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('a revision conflict writes nothing, blocks further saves and keeps the draft; the plan is told the record is stale', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.resolve({api_version:1,ok:false,error:'revision_conflict',settings:{...recordRaw(),revision:9},pause});
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');q('#save-market').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toContain('nothing was written');expect(panel.costConflict).toBe(true);expect(panel.settingsConflict).toBe(true);expect(panel.settingsRecord.revision).toBe(7);
    q('#save-market').click();await tick();expect(writes(calls)).toHaveLength(1);expect(q('[data-msetting="vat-figure"]').value).toBe('25');panel.remove();
  });
  it('a reconcile failure after a durable save adopts the saved record but demands a reload before another change', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=(msg:any)=>Promise.resolve({...updatedRecord(msg),ok:false,error:'spotnav_settings_reconcile_failed'});
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');q('#save-market').click();await tick();await tick();await tick();
    expect(text(panel)).toContain('saved, but replanning failed');expect(panel.settingsRecord.revision).toBe(8);expect(panel.costConflict).toBe(true);panel.remove();
  });
  it('a refused write shows the backend reason; an unreadable or unresolved answer is an unknown outcome that blocks until reload', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>Promise.reject(Object.assign(new Error('x'),{code:'spotnav_not_admin'}));
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');q('#save-market').click();await tick();await tick();await tick();
    expect(text(panel)).toMatch(/not saved/i);expect(panel.unknownCostWrites.size).toBe(0);expect(panel.costConflict).toBe(false);
    handlers['spotnav/update_settings']=()=>Promise.reject(new Error('timeout'));
    q('#save-market').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(2);expect(panel.unknownCostWrites.has('a')).toBe(true);expect(text(panel)).toContain('outcome unknown');
    q('#save-market').click();await tick();expect(writes(calls)).toHaveLength(2);
    vi.spyOn(window,'confirm').mockReturnValue(true);q('#reload-market-costs').click();await tick();await tick();await tick();
    expect(panel.unknownCostWrites.size).toBe(0);expect(panel.costConflict).toBe(false);expect(panel.settingsRecord).not.toBeNull();panel.remove();
  });
  it('a non-administrator reads the market and fees but gets no enabled control and sends nothing', async () => {
    const {calls,hass}=setup({admin:false});const {panel,q}=await open(hass);
    expect(text(panel)).toContain('Administrator permission is required');
    expect(q('#save-market').hasAttribute('disabled')).toBe(true);expect(q('[data-msetting="area"]').disabled).toBe(true);expect(q('[data-msetting="vat-mode"]').disabled).toBe(true);
    q('#save-market').click();await tick();await panel.saveMarket(vals({vat:{mode:'custom',figure:'1'}}));await tick();
    expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('a stale dashboard or area list withholds saving even through a direct call', async () => {
    const {calls,hass}=setup();const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');
    const generated=panel.rawDashboard.generated_at;panel.rawDashboard={...panel.rawDashboard,generated_at:new Date(Date.now()-10*60000).toISOString()};
    await panel.saveMarket(vals({vat:{mode:'custom',figure:'25'}}));expect(writes(calls)).toHaveLength(0);expect(text(panel)).toMatch(/stale/);
    panel.rawDashboard={...panel.rawDashboard,generated_at:generated};panel.marketOptionsAt=Date.now()-2000000;
    await panel.saveMarket(vals({vat:{mode:'custom',figure:'25'}}));expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('drafts survive a refresh, and a change of the stored fees elsewhere while editing is flagged instead of saved over', async () => {
    const {calls,hass,state}=setup();const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','21');
    panel.statusEpoch++;panel.refresh();await tick();panel.paint();
    expect(q('[data-msetting="vat-figure"]').value).toBe('21');expect(panel.costConflict).toBe(false);
    panel.settingsRecord=decodeSettingsRecord(recordRaw({overrides:[{area_id:'SE4',vat:{enabled:true,value:1},tax:{enabled:false,value:null},transfer:{enabled:false,value:null}}]}));panel.paint();
    expect(panel.costConflict).toBe(true);expect(text(panel)).toContain('changed while editing');expect(q('[data-msetting="vat-figure"]').value).toBe('21');
    q('#save-market').click();await tick();expect(writes(calls)).toHaveLength(0);panel.remove();
  });
  it('included components are locked: no control, and a direct save states nothing for them', async () => {
    const {calls,hass}=setup({options:optionsRaw([areaV2({included:['transfer']})]),record:{overrides:[{area_id:'SE4',vat:{enabled:false,value:null},tax:{enabled:false,value:null},transfer:{enabled:true,value:30}}]}});
    const {panel,q}=await open(hass);
    expect(q('[data-msetting="transfer-mode"]')).toBeNull();expect(text(panel)).toContain('Already included');
    await panel.saveMarket(vals({transfer:{mode:'custom',figure:'99'}}));expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');panel.remove();
  });
  it('saves the grid tariff with the displayed write revision, keeps the rest, and reads the settings again', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_grid_tariff']=()=>Promise.resolve({ok:true,grid_tariff:tariffRaw({write_revision:4})});
    const {panel,q,edit}=await open(hass);
    edit('percent-mode','custom');edit('percent-figure','5');edit('high-mode','custom');edit('high-figure','40');edit('win-days','all');edit('win-from-month','1');edit('win-to-month','12');edit('win-from-hour','22');edit('win-to-hour','6');
    const settingsReads=calls.filter(m=>m.type==='spotnav/get_settings').length;
    q('#save-tariff').click();await tick();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);
    expect(w[0]).toMatchObject({type:'spotnav/update_grid_tariff',charger_id:'a',expected_write_revision:3});
    expect(w[0].grid_tariff).toEqual({transfer_percent:{enabled:true,value:5},transfer_high:{enabled:true,value:40},high_load_window:{days:'all',from_month:1,to_month:12,from_hour:22,to_hour:6}});
    expect(text(panel)).toContain('Grid tariff saved and confirmed by the backend');
    expect(calls.filter(m=>m.type==='spotnav/get_settings').length).toBeGreaterThan(settingsReads);panel.remove();
  });
  it('a tariff conflict (price changed elsewhere) writes nothing and asks for a reload; an unchanged tariff sends nothing', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_grid_tariff']=()=>Promise.reject(Object.assign(new Error('c'),{code:'revision_conflict'}));
    const {panel,q,edit}=await open(hass);
    q('#save-tariff').click();await tick();expect(writes(calls)).toHaveLength(0);expect(text(panel)).toContain('No changes to save');
    edit('percent-mode','custom');edit('percent-figure','5');q('#save-tariff').click();await tick();await tick();await tick();
    expect(writes(calls)).toHaveLength(1);expect(text(panel)).toMatch(/not saved.*changed elsewhere since it was read; nothing was written/);expect(panel.costConflict).toBe(true);
    q('#save-tariff').click();await tick();expect(writes(calls)).toHaveLength(1);panel.remove();
  });
  it('a tariff answer that is not an acceptance is an unknown outcome, not a success', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/update_grid_tariff']=()=>Promise.resolve({unexpected:true});
    const {panel,q,edit}=await open(hass);
    edit('percent-mode','custom');edit('percent-figure','5');q('#save-tariff').click();await tick();await tick();await tick();
    expect(panel.unknownCostWrites.has('a')).toBe(true);expect(text(panel)).toContain('outcome unknown');panel.remove();
  });
  it('a price-entry choice needs confirmation, names the effect, sends the chosen entry once, and the record is read again', async () => {
    const {calls,hass,handlers}=setup();
    handlers['spotnav/choose_price_source']=()=>Promise.resolve({ok:true});
    const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
    const {panel,q,edit}=await open(hass);
    edit('entry','price2');q('#save-price-entry').click();await tick();
    expect(String(confirm.mock.calls.at(-1)[0])).toMatch(/“Other market”.*provider route/s);expect(writes(calls)).toHaveLength(0);
    confirm.mockReturnValue(true);const reads=calls.filter(m=>m.type==='spotnav/get_settings').length;
    q('#save-price-entry').click();await tick();await tick();await tick();await tick();
    const w=writes(calls);expect(w).toHaveLength(1);expect(w[0]).toMatchObject({type:'spotnav/choose_price_source',entry_id:'a',price_entry_id:'price2'});
    expect(calls.filter(m=>m.type==='spotnav/get_settings').length).toBeGreaterThan(reads);panel.remove();
  });
  it('a charger without an electricity price entry shows no price-entry or tariff controls and says why', async () => {
    const {calls,hass}=setup({priceSource:null,tariff:false});const {panel,q}=await open(hass);
    expect(q('#save-tariff')).toBeNull();expect(q('#save-price-entry')).toBeNull();expect(text(panel)).toContain('prices with its own settings');expect(q('#save-market')).not.toBeNull();panel.remove();
  });
  it('a permission change during a save leaves the outcome unknown; a late answer is not applied', async () => {
    const {calls,hass,handlers}=setup();let release:any;
    handlers['spotnav/update_settings']=(msg:any)=>new Promise((r)=>{release=()=>r(updatedRecord(msg));});
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');q('#save-market').click();await tick();
    expect(panel.costBusy).toBe(true);
    panel.hass={...hass,user:{is_admin:false}};await tick();
    expect(panel.unknownCostWrites.has('a')).toBe(true);expect(panel.costConflict).toBe(true);
    release();await tick();await tick();expect(panel.settingsRecord?.revision).not.toBe(8);panel.remove();
  });
  it('does not block Pause/Stop controls while a market save is pending', async () => {
    const {hass,handlers}=setup();
    handlers['spotnav/update_settings']=()=>new Promise(()=>{});
    const {panel,q,edit}=await open(hass);
    edit('vat-mode','custom');edit('vat-figure','25');q('#save-market').click();await tick();
    expect(panel.costBusy).toBe(true);expect(!!panel.autoBusy).toBe(false);expect(panel.shadowRoot.querySelector('#pause-auto')).not.toBeNull();
    // plan, vehicle and Morek writes wait for it
    const before=panel.settingsNotice;await panel.savePlan({});expect(panel.settingsNotice).toMatch(/unavailable/);panel.remove();
  });
});
