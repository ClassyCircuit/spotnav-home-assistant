// Published intervals only: the legacy presentation grid may contain planner rows.
import { localMidnightAt } from '../src/chart.ts';
import { displayPrice, priceUnit } from '../shared-dashboard/price-format.js';

export function publishedChart(raw, market, now, stale) {
  const rows = raw?.prices?.published_intervals;
  const zone = market?.timezone, currency = market?.currency;
  if (stale || !Array.isArray(rows) || !rows.length || !zone || !/^[A-Z]{3}$/.test(currency || '')) return null;
  try { new Intl.DateTimeFormat('en', {timeZone:zone}).format(0); } catch { return null; }
  const prices = [];
  let previous = -Infinity;
  for (const row of rows) {
    if (!row || typeof row.start !== 'string' || typeof row.end !== 'string' || !/(?:Z|[+-]\d\d:\d\d)$/i.test(row.start) || !/(?:Z|[+-]\d\d:\d\d)$/i.test(row.end)) return null;
    const start=Date.parse(row.start), end=Date.parse(row.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end<=start || start<previous || !(row.raw_price === null || Number.isFinite(row.raw_price))) return null;
    if (row.raw_price !== null) prices.push({start,end,cents:displayPrice(row.raw_price,currency)});
    previous=end;
  }
  if (!prices.length) return null;
  const horizon=[Date.parse(rows[0].start),Date.parse(rows.at(-1).end)];
  const boundaries=[...new Set(rows.flatMap(r=>[Date.parse(r.start),Date.parse(r.end)]))].sort((a,b)=>a-b);
  const snapRange=(a,b)=>{
    const nearest=x=>boundaries.reduce((v,n)=>Math.abs(n-x)<Math.abs(v-x)?n:v,boundaries[0]);
    let start=nearest(a), end=nearest(b);
    if (start>=end) {const i=boundaries.indexOf(start); if(i<boundaries.length-1) end=boundaries[i+1]; else start=boundaries[i-1];}
    return [start,end];
  };
  const time=ms=>new Intl.DateTimeFormat('en-GB',{timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset'}).format(ms);
  const date=ms=>new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'short',day:'numeric'}).format(ms);
  const days=(start,end)=>{const result=[]; let mid=localMidnightAt(start,zone); for(let i=0;i<5&&mid<end;i++){const next=localMidnightAt(mid+36*3600000,zone);if(next<=mid)break;result.push({start:Math.max(start,mid),end:Math.min(end,next),midnight:mid,label:date(mid)});mid=next;}return result;};
  const priceGaps=(start,end,items)=>{const gaps=[];let cursor=start;for(const p of items){if(p.end<=cursor||p.start>=end)continue;if(p.start>cursor)gaps.push([cursor,Math.min(end,p.start)]);cursor=Math.max(cursor,Math.min(end,p.end));}if(cursor<end)gaps.push([cursor,end]);return gaps;};
  const stepSegments=items=>items.map(p=>[[p.start,p.cents],[p.end,p.cents]]);
  const stepPoints=items=>items.flatMap((p,i)=>[...(i&&items[i-1].end!==p.start?[[(items[i-1].end+p.start)/2,null]]:[]),[p.start,p.cents],[p.end,p.cents]]);
  const initialRange=current=>snapRange(Math.max(horizon[0],Math.min(current-3600000,horizon[1]-1)),horizon[1]);
  const timeTicks=(start,end,width)=>{const step=[3600000,7200000,14400000,21600000,43200000,86400000].find(n=>n>=(end-start)/Math.max(1,Math.floor(width/100)))||86400000;const out=[];for(let t=Math.ceil(start/step)*step;t<end;t+=step)out.push(t);return out;};
  return {chart:{prices,now,horizon,cap:null,bands:null,unit:priceUnit(currency)}, format:{chartTime:time,date,tooltipDate:date,days,priceGaps,stepSegments,stepPoints,snapRange,initialRange,timeTicks}};
}
