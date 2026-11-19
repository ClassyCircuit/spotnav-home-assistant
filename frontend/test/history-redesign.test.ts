// @ts-nocheck
// Stage 20.8: the redesigned History day review keeps provenance, spot-only cost, coverage and unplaced-energy semantics.
import { describe, it, expect } from 'vitest';
import { createHistoryDay } from '../shared-dashboard/history-day.js';
import { renderHistory } from '../shared-dashboard/history-view.js';
import { HISTORY_TODAY, HISTORY_ZONE, fixtureHistoryRequest, fixtureSessionsRequest } from '../prototype/history-day-fixture.js';

const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
async function out(day, request = fixtureHistoryRequest({ charger: 'a' })) {
  const calls = [];
  const view = createHistoryDay({ request: a => { calls.push(a); return request(a); }, requestSessions: fixtureSessionsRequest({ charger: 'a' }), onChange: () => {} });
  view.sync({ charger: 'a', epoch: '1:0', zone: HISTORY_ZONE, marketZone: HISTORY_ZONE, today: HISTORY_TODAY });
  await tick();
  if (day !== '2026-11-08') { view.select('day', day); await tick(); }
  return { html: renderHistory(null, false, view.view()), calls };
}

describe('history redesign', () => {
  it('shows a day review with retained-evidence chips, grouped sections and provenance on every energy basis', async () => {
    const { html } = await out('2026-11-08');
    expect(html).toContain('data-history-section="review"');
    expect(html).toContain('data-chip="raw"');
    expect(html).toMatch(/data-chip="sessions"[^>]*>\d+ recorded session/);
    for (const g of ['Cost and energy', 'Sessions', 'Plan versus measured flow']) expect(html).toContain(`>${g}</h2>`);
    expect(html).toContain('data-provenance="measured"');
    expect(html).toContain('data-provenance="estimated"');
    expect(html).toContain('data-provenance="unplaced"');
    expect(html).toContain('history-session');
    expect(html).toContain('Unplaced late energy 1.40 kWh: no known time');
    expect(html).toContain('not priced');
    expect(html).toContain('Closed sessions only');
    expect(html).toContain('never added together');
  });
  it('marks partial, summary-only and absent evidence distinctly and never as zero', async () => {
    const cut = (await out('2026-11-08')).html;
    expect(cut).toContain('data-history-banner="truncated"');
    expect(cut).toContain('data-chip="truncated"');
    const partial = (await out('2026-11-07')).html;
    expect(partial).toMatch(/data-chip="raw"[^>]*>Measured rows partial/);
    expect(partial).toContain('unknown, not zero');
    const digest = (await out('2026-11-05')).html;
    expect(digest).toMatch(/data-chip="raw"[^>]*>Summary only/);
    expect(digest).not.toContain('data-history-section="energy"');
    expect(digest).toContain('data-provenance="estimated"');
    const sessionsOnly = (await out('2026-11-06')).html;
    expect(sessionsOnly).not.toContain('data-history-section="energy"');
    expect(sessionsOnly).not.toMatch(/data-chip="raw"[^>]*>Measured rows retained/);
  });
  it('navigating days is a read only: no plan or write request is made', async () => {
    const { calls } = await out('2026-11-09');
    for (const c of calls) expect(JSON.stringify(c)).not.toMatch(/replan|plan_now|profile|save|clear/i);
  });
});
