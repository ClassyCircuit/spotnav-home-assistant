// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { publishedChart } from '../sidebar/price-chart.js';
import { capInput, capForSave, priceText } from '../shared-dashboard/price-format.js';
import { priceProvenance } from '../sidebar/adapter.js';

const market={timezone:'Europe/Stockholm',currency:'SEK'};
const rows=[
  {start:'2026-10-25T02:00:00+02:00',end:'2026-10-25T02:30:00+02:00',raw_price:-0.15},
  {start:'2026-10-25T02:30:00+02:00',end:'2026-10-25T02:00:00+01:00',raw_price:null},
  {start:'2026-10-25T02:00:00+01:00',end:'2026-10-25T02:17:00+01:00',raw_price:0.35},
];
const make=(r=rows,m=market,stale=false)=>publishedChart({prices:{published_intervals:r}},m,Date.parse(rows[0].start),stale);
describe('published source chart',()=>{
  it('preserves partial intervals, negative values, missing gaps and DST offsets',()=>{
    const {chart,format}=make();
    expect(chart.unit).toBe('SEK/kWh');expect(chart.bands).toBeNull();expect(chart.cap).toBeNull();
    expect(chart.prices.map(p=>p.cents)).toEqual([-0.15,0.35]);
    expect(chart.prices[1].end-chart.prices[1].start).toBe(17*60000);
    expect(format.stepPoints(chart.prices)).toContainEqual([Date.parse('2026-10-25T00:45:00Z'),null]);
    expect(format.chartTime(chart.prices[0].start)).not.toEqual(format.chartTime(chart.prices[1].start));
    expect(format.days(chart.horizon[0],chart.horizon[1])).toHaveLength(1);
  });
  it('fails closed for unknown metadata, stale, missing, or overlapping rows',()=>{
    expect(make(rows,market,true)).toBeNull();expect(make(rows,{...market,currency:null})).toBeNull();
    expect(make(rows,{...market,timezone:'invalid'})).toBeNull();expect(make([])).toBeNull();
    expect(make([rows[0],rows[0]])).toBeNull();expect(make([{...rows[0],raw_price:undefined}])).toBeNull();
  });
  it('does not fill spring-forward or unavailable future',()=>{
    const r=[{start:'2026-03-29T01:30:00+01:00',end:'2026-03-29T03:00:00+02:00',raw_price:0}];
    const v=make(r);expect(v.chart.horizon[1]).toBe(Date.parse(r[0].end));expect(v.chart.prices[0].cents).toBe(0);
    expect(v.format.days(v.chart.horizon[0],v.chart.horizon[1])[0].end).toBe(v.chart.horizon[1]);
  });
  it('converts EUR exactly once at the display boundary, without changing interval geometry',()=>{
    const chart=make(rows,{...market,currency:'EUR'}).chart;
    expect(chart.unit).toBe('c/kWh');expect(chart.prices.map(p=>p.cents)).toEqual([-15,35]);
    expect(chart.prices[1].end).toBe(Date.parse(rows[2].end));
    expect(capInput(0.12345,'EUR')).toBe('12.345');expect(capForSave('12.345','EUR',0.12345)).toBe('0.12345');
    expect(Number(capForSave('-2.125','EUR',0.1))).toBe(-0.02125);
    expect(Number(capForSave('12,5','EUR',0.1))).toBe(0.125);
    expect(capInput(0.12345,'SEK')).toBe('0.12345');expect(capForSave('0.14','SEK',0.1)).toBe('0.14');
    expect(priceText(0.1+0.2)).toBe('0.3');expect(priceText(-1.23456)).toBe('-1.2346');expect(priceText(-0.00001)).toBe('-1.000e-5');expect(priceText(null)).toBe('Unknown');
  });
  it('distinguishes current route from mixed held providers, and labels unknown provenance',()=>{
    const p={provider:{name:'Nord Pool'},today:'2026-10-25',today_state:'stale',today_provenance:[{provider:'entsoe',market_day:'2026-10-24',state:'stale',fetched_at:'2026-10-24T00:00:00Z'},{provider:'nordpool',market_day:'2026-10-25',state:'ready',fetched_at:'2026-10-25T00:00:00Z'}]};
    const text=priceProvenance(p,{area_name:'Area',area_id:'A'},'UTC');
    expect(text).toMatch(/Current provider route: Nord Pool/);expect(text).toMatch(/mixed providers/);expect(text).toMatch(/ENTSO-E.*stale/);expect(text).toMatch(/tomorrow unknown day: unknown; held provider unavailable/);
    expect(priceProvenance({},null,null,true)).toMatch(/Current provider route: Unavailable.*observation stale/);
  });
});
