// Fixed fictional timestamps; this is a presentation fixture, not backend evidence.
export function evidenceFixture(state) {
  if (state === 'unavailable') return {proposal:'Sample proposal · calculation time unknown',sent:'Unknown',readback:'Unavailable',measurement:'Unavailable',status:'Evidence unavailable' };
  if (state === 'stale') return {proposal:'Mon 9 Nov 09:05 · settings changed · stale',sent:'Mon 9 Nov 09:10 · Accepted 09:11 · stale',readback:'Mon 9 Nov 09:15 · stale · covers 09:15–Tue 10 Nov 08:00',measurement:'SOC Mon 9 Nov 09:00 · stale; current power unknown',status:'Evidence is stale'};
  return {proposal:'Mon 9 Nov 14:15 · sample settings changed',sent:'Mon 9 Nov 14:20 · Accepted 14:21',
    readback: state === 'mismatch' ? 'Mon 9 Nov 14:28 · mismatch with last sent · covers 14:28–Tue 10 Nov 08:00' : 'Mon 9 Nov 14:28 · matches last sent · covers 14:28–Tue 10 Nov 08:00',
    measurement:'SOC Mon 9 Nov 14:27 · power 14:29',status:state === 'mismatch' ? 'Reported limits differ from last sent' : 'Readback matches last sent within coverage'};
}

export function renderEvidence(state, power, windows) {
  const e = evidenceFixture(state);
  return `<div class="evidence-status"><strong>${e.status}</strong><span>Fictional sample · Now Mon 9 Nov 14:30</span></div><div class="evidence-grid"><div><small>Proposal calculated</small><b>${e.proposal}</b></div><div><small>Last sent / ACK</small><b>${e.sent}</b></div><div><small>Effective limits read</small><b>${e.readback}</b></div><div><small>Vehicle / power received</small><b>${e.measurement}</b></div></div><p class="subtext">Whether the current proposal was sent is unknown. Readback is effective limits, not a profile inventory. An ACK or match does not prove physical charging; power is a separate sample observation. Autonomous dispatch is unarmed.</p><wa-details id="details" summary="View sample evidence & debug controls"><div class="details-body"><p><b>Current proposal:</b> ${windows.length} sample windows; not necessarily sent. The fixture does not establish whether the last sent plan is the current proposal.</p><p><b>Last sent and acknowledgement:</b> ${e.sent} · response only.</p><p><b>Effective readback:</b> ${e.readback} · starts at read time; not an inventory.</p><p><b>Measured power:</b> ${power} · ${e.measurement}.</p><p>Missing, stale and superseded evidence must not be treated as current.</p><div class="actions"><wa-button size="small" disabled>Send · unavailable</wa-button><wa-button size="small" disabled>Refresh · unavailable</wa-button></div></div></wa-details>`;
}
