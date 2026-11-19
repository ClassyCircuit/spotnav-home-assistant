import { describe, it, expect } from 'vitest';
import { compareProposedWindows as compare } from '../shared-dashboard/windows-view.js';
describe('comparison within proposed windows', () => {
  const start = Date.parse('2026-10-25T01:15:00+03:00'), end = Date.parse('2026-10-25T01:15:00+02:00');
  const proposal = {now:start, amps:16, windows:[{start,end}]};
  const readback = {state:'fresh',unit:'A',start,end,spans:[{start,end,value:16}]};
  it('compares real DST instants and zero limits', () => {
    expect(compare(proposal,readback)).toBe('match');
    expect(compare(proposal,{...readback,spans:[{start,end,value:0}]})).toBe('different');
    expect(compare({...proposal,amps:0},readback)).toBe('unknown');
  });
  it('distinguishes partial, absent and stale coverage', () => {
    expect(compare(proposal,{...readback,spans:[{start,end:start+1000,value:16}]})).toBe('partial');
    expect(compare(proposal,{...readback,spans:[{start,end:start+1000,value:0}]})).toBe('different-partial');
    expect(compare(proposal,{...readback,spans:[]})).toBe('unknown');
    expect(compare(proposal,{...readback,state:'stale'})).toBe('stale');
    expect(compare(null,readback)).toBe('unknown');
  });
});
