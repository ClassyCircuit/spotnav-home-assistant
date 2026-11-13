// @ts-nocheck
// Stage 5.7b2: reported state, measured flow and the energy register stay separate; unknown is not 0.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { liveCharging } from '../sidebar/live-charging.js';
import { dashboardAdapter } from '../sidebar/adapter.js';

const NOW = Date.parse('2026-11-13T10:00:00Z');
const at = s => new Date(NOW - s * 1000).toISOString();
const reading = (value, unit, s = 5, fresh = true) => ({value, unit, observed_at: at(s), fresh});
const status = (live, extra = {}, readiness = {}) => ({api_version: 1, schedule: {supported: true, verified: false, sent: null, sent_at: null, ack: null, effective: null,
  connector_id: 1, readiness: {control: 'available', vehicle: 'connected', vehicle_observed_at: at(5), live: {connector_id: 1, status: null, current_a: null, power_w: null, energy_register_kwh: null, ...live}, ...readiness}, ...extra}});
const state = s => s.schedule;
const run = (live, o = {}) => liveCharging(state(status(live, o.extra, o.readiness)), o.observedAt ?? NOW, o.failed ?? false, o.now ?? NOW);
const rep = (value, normalized, s = 5) => ({value, normalized, observed_at: at(s), fresh: s <= 180});

describe('live charging binding', () => {
  it('shows reported state and measured power separately, with connector and age', () => {
    const r = run({status: rep('Charging', 'charging'), power_w: reading(3680, 'W'), energy_register_kwh: reading(1234.5, 'kWh')});
    expect(r.power).toBe('3.68 kW measured');
    expect(r.summary).toMatch(/reports “Charging” for connector 1, 5 s ago; a reported state is not measured power/);
    expect(r.summary).toMatch(/Cumulative energy register 1234.5 kWh.*not this session/);
    expect(r.summary).toMatch(/schedule, ACK or effective limit is not measured charging/);
    expect(r.mismatch).toBe(false);
  });
  it('reports status alone as reported, never as measured power', () => {
    const r = run({status: rep('Charging', 'charging')});
    expect(r.power).toBe('Unknown');
    expect(r.summary).toMatch(/No measured power or current source/);
    expect(r.measured).toBeNull();
  });
  it('keeps an actual measured zero distinct from unknown', () => {
    expect(run({power_w: reading(0, 'W')}).power).toBe('0 W measured');
    expect(run({}).power).toBe('Unknown');
  });
  it('current is shown as current and never converted to power', () => {
    const r = run({current_a: reading(15.5, 'A')});
    expect(r.power).toBe('15.5 A measured (power unknown)');
    expect(r.summary).toMatch(/power is not derived from it/);
  });
  it('never presents stale, future or malformed readings as current', () => {
    expect(run({power_w: reading(3000, 'W', 400)}).power).toBe('Unknown');
    expect(run({power_w: reading(3000, 'W', 5, false)}).power).toBe('Unknown');
    expect(run({power_w: reading(3000, 'W', -60)}).power).toBe('Unknown');
    expect(run({power_w: {value: 'x', unit: 'W', observed_at: at(1)}}).power).toBe('Unknown');
    expect(run({power_w: {value: 5, unit: 'W', observed_at: 'bad'}}).power).toBe('Unknown');
    expect(run({status: rep('Charging', 'charging', 400)}).summary).toMatch(/stale.*current state unknown/);
    expect(run({energy_register_kwh: reading(-1, 'kWh')}).summary).toMatch(/Energy register unavailable/);
  });
  it('is unknown when the status is stale, failed, offline or lacks live data', () => {
    const live = {power_w: reading(3000, 'W')};
    expect(run(live, {observedAt: NOW - 95000}).power).toBe('Unknown');
    expect(run(live, {failed: true}).summary).toMatch(/stale/);
    expect(run(live, {readiness: {control: 'unavailable'}}).summary).toMatch(/offline/);
    expect(liveCharging(null, NOW, false, NOW).power).toBe('Unknown');
    expect(liveCharging({supported: true, readiness: {control: 'available'}}, NOW, false, NOW).summary).toMatch(/No live charger observation/);
  });
  it('requires the evidence to belong to the status connector', () => {
    expect(run({power_w: reading(3000, 'W'), connector_id: 2}).summary).toMatch(/not confirmed to belong/);
    expect(run({power_w: reading(3000, 'W'), connector_id: null}).power).toBe('Unknown');
    expect(run({power_w: reading(3000, 'W')}, {extra: {connector_id: null}}).power).toBe('Unknown');
  });
  it('flags a mismatch between reported state and measured flow without resolving it', () => {
    const a = run({status: rep('Charging', 'charging'), power_w: reading(0, 'W')});
    expect(a.mismatch).toBe(true);
    expect(a.summary).toMatch(/disagree; neither is verified/);
    expect(run({status: rep('SuspendedEV', 'paused'), current_a: reading(12, 'A')}).mismatch).toBe(true);
    expect(run({status: rep('Charging', 'charging'), power_w: reading(0, 'W', 400)}).mismatch).toBe(false);
    expect(run({status: rep('Available', 'disconnected'), power_w: reading(20, 'W')}).mismatch).toBe(false);
  });
});

describe('sidebar adapter live binding', () => {
  const raw = () => { const r = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json', 'utf8')); r.generated_at = new Date(NOW).toISOString(); return r; };
  it('feeds the vehicle metric, evidence and a mismatch warning from live data only', () => {
    const ok = dashboardAdapter(raw(), status({status: rep('Charging', 'charging'), power_w: reading(7000, 'W')}), NOW, NOW).model;
    expect(ok.vehicle.power).toBe('7 kW measured');
    expect(ok.evidence.measurement).toMatch(/Measured power 7 kW/);
    expect(ok.evidence.readiness).toMatch(/measured power observed/);
    expect(ok.warning).toBeNull();
    const bad = dashboardAdapter(raw(), status({status: rep('Charging', 'charging'), power_w: reading(0, 'W')}), NOW, NOW).model;
    expect(bad.warning.detail).toMatch(/Reported charger state and measured flow disagree/);
    expect(bad.vehicle.power).toBe('0 W measured');
  });
  it('withdraws live values when the status refresh failed or went stale', () => {
    const live = status({power_w: reading(7000, 'W')});
    for (const m of [dashboardAdapter(raw(), live, NOW, NOW, true).model, dashboardAdapter(raw(), live, NOW - 100000, NOW).model, dashboardAdapter(raw(), null, null, NOW).model]) {
      expect(m.vehicle.power).toBe('Unknown');
      expect(m.evidence.readiness).toMatch(/measured charging unknown/);
    }
  });
});
