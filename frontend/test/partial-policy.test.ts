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

it('states plainly that a partial plan used available prices while tomorrow is pending, without claiming completion', () => {
  const now=Date.now();
  const raw=JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8'));
  raw.generated_at=new Date(now).toISOString();
  raw.planning.historical=false;
  raw.planning.settings_revision=raw.settings.revision;
  raw.plan.proposal.settings_revision=raw.settings.revision;
  raw.plan.proposal.periods=[{start:new Date(now+3600000).toISOString(),end:new Date(now+7200000).toISOString()}];
  const status={api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};
  const policy={provisional:true,price_coverage_end:new Date(now+10800000).toISOString(),target_shortfall_kwh:4.25,explanations:[{code:'within_cap'}]};
  raw.plan.price_policy={...policy,tomorrow_pending:true,price_state:'waiting_for_tomorrow'};
  const text=dashboardAdapter(raw,status,now,now).model.vehicle.policy;
  expect(text).toContain('Planned using available published prices');
  expect(text).toContain('tomorrow’s prices are pending or unusable');
  expect(text).toContain('4.3 kWh of target energy remains unresolved');
  expect(text).not.toMatch(/guaranteed|will charge/i);
  raw.plan.price_policy={...policy,tomorrow_pending:false};
  expect(dashboardAdapter(raw,status,now,now).model.vehicle.policy).not.toContain('Planned using available published prices');
});
