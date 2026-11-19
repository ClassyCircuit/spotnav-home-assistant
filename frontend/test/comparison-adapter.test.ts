// @vitest-environment jsdom
// @ts-nocheck
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { compareProposedWindows } from '../shared-dashboard/windows-view.js';

it('compares the current decoded proposal and rejects missing identity or inconsistent revisions', () => {
  const now = Date.parse('2026-11-19T12:00:00Z');
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date(now).toISOString();
  raw.planning.calculated_at = new Date(now - 1000).toISOString();
  raw.plan.proposal.periods = [{start: '2026-11-19T12:00:00Z', end: '2026-11-19T13:00:00Z'}];
  const status = {api_version: 1, schedule: {supported: true, verified: false, sent: null, sent_at: null, ack: null, effective: {
    status: 'Accepted', fetched_at: '2026-11-19T11:59:30Z', schedule_start: '2026-11-19T12:00:00Z', duration_s: 3600,
    rate_unit: 'A', periods: [{at: '2026-11-19T12:00:00Z', amps: 10}],
  }}};
  const result = () => {
    const m = dashboardAdapter(raw, status, now, now).model;
    return compareProposedWindows(m.comparisonProposal, m.effectiveDisplay);
  };
  expect(result()).toBe('match');
  raw.plan.proposal.identity = 'new-proposal';
  raw.plan.proposal.amps = 16;
  expect(result()).toBe('different');
  raw.plan.proposal.identity = '';
  expect(result()).toBe('unknown');
  raw.plan.proposal.identity = 'new-proposal';
  raw.settings.revision++;
  expect(result()).toBe('unknown');
  raw.plan.proposal.settings_revision = raw.settings.revision;
  expect(result()).toBe('unknown');
  raw.planning.settings_revision = raw.settings.revision;
  expect(result()).toBe('different');
});
