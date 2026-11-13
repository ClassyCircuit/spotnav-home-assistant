// @vitest-environment jsdom
// @ts-nocheck
import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';

function policyText(price_policy, settings = {}) {
  const now = Date.now();
  const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8'));
  raw.generated_at = new Date(now).toISOString();
  raw.planning.historical = false;
  raw.planning.settings_revision = raw.settings.revision;
  raw.plan.proposal.settings_revision = raw.settings.revision;
  raw.plan.proposal.periods = [{ start: new Date(now + 3600000).toISOString(), end: new Date(now + 7200000).toISOString() }];
  Object.assign(raw.settings, settings);
  raw.plan.price_policy = price_policy;
  const status = { api_version: 1, schedule: { supported: false, verified: false, sent: null, sent_at: null, ack: null, effective: null } };
  return dashboardAdapter(raw, status, now, now).model.vehicle.policy;
}

it('reports the three-window compromise for a capped and an uncapped plan', () => {
  const capped = policyText({ explanations: [{ code: 'within_cap' }, { code: 'block_limit' }] });
  expect(capped).toContain('at most three charging windows');
  const uncapped = policyText({ explanations: [{ code: 'uncapped' }, { code: 'block_limit' }] }, { soft_price_cap: null });
  expect(uncapped).toContain('No soft price cap is applied');
  expect(uncapped).toContain('at most three charging windows');
  expect(policyText({ explanations: [{ code: 'within_cap' }] })).not.toContain('at most three');
});
