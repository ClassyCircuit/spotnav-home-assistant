import { renderEvidence as sharedEvidence } from '../shared-dashboard/evidence-view.js';
// Fixed fictional timestamps; this is a presentation fixture, not backend evidence.
export function evidenceFixture(state) {
  if (state === 'unavailable') return {proposal:'Sample proposal · calculation time unknown',sent:'Unknown',readback:'Unavailable',measurement:'Unavailable',status:'Evidence unavailable' };
  if (state === 'stale') return {proposal:'Mon 9 Nov 09:05 · settings changed · stale',sent:'Mon 9 Nov 09:10 · Accepted 09:11 · stale',readback:'Mon 9 Nov 09:15 · stale · covers 09:15–Tue 10 Nov 08:00',measurement:'SOC Mon 9 Nov 09:00 · stale; current power unknown',status:'Evidence is stale'};
  return {proposal:'Mon 9 Nov 14:15 · sample settings changed',sent:'Mon 9 Nov 14:20 · Accepted 14:21',
    readback: state === 'mismatch' ? 'Mon 9 Nov 14:28 · mismatch with last sent · covers 14:28–Tue 10 Nov 08:00' : 'Mon 9 Nov 14:28 · matches last sent · covers 14:28–Tue 10 Nov 08:00',
    measurement:'SOC Mon 9 Nov 14:27 · power 14:29',status:state === 'mismatch' ? 'Reported limits differ from last sent' : 'Readback matches last sent within coverage'};
}

export function renderEvidence(state, power, windows) {
  return sharedEvidence({...evidenceFixture(state),context:'Fictional sample · Now Mon 9 Nov 14:30',dispatch:'Autonomous dispatch is unarmed.'},power,windows.length);
}
