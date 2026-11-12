// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { publishedChart } from '../sidebar/price-chart.js';

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
});
