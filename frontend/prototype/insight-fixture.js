import { prices, now, horizon } from './sample.js';

// Synthetic hourly Oct 1–Nov 7, joined without overlap to the chart's Nov 8 onward.
// It is fictional and not historical market retrieval. Same illustrative cost basis.
export const history = [
  ...Array.from({length: 38 * 24}, (_,i) => ({start:-936+i,end:-935+i,cents: Math.round((38 + 7*Math.sin(i*2*Math.PI/24) + 4*Math.cos(i*2*Math.PI/(24*7)) + (i%13)*.17)*100)/100})),
  ...prices.filter(p=>p.start < now)
];
export const monthlyRange = [-936,-192]; // Oct 1 00:00 to Nov 1 00:00, fictional 2026.
export const baselineRange = [now-30*24,now];
export const futureRange = [now,horizon[1]];
