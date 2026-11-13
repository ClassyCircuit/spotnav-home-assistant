// @vitest-environment jsdom
// @ts-nocheck
import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dashboardAdapter } from '../sidebar/adapter.js';

it('labels a current partial proposal without claiming complete optimization', () => {
  const now=Date.now();
  const raw=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
  raw.generated_at=new Date(now).toISOString();
  raw.planning.historical=false;
  raw.planning.settings_revision=raw.settings.revision;
  raw.plan.proposal.settings_revision=raw.settings.revision;
  raw.plan.proposal.periods=[{start:new Date(now+3600000).toISOString(),end:new Date(now+7200000).toISOString()}];
  raw.plan.price_policy={provisional:true,price_coverage_end:new Date(now+10800000).toISOString(),target_shortfall_kwh:4.25,explanations:[{code:'within_cap'}]};
  const status={api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
  const text=dashboardAdapter(raw,status,now,now).model.vehicle.policy;
  expect(text).toContain('Provisional');
  expect(text).toContain('4.3 kWh of target energy remains unresolved');
  expect(text).toContain('Future prices and readiness are unknown');
  expect(text).toContain('not necessarily the cheapest complete plan');
});
