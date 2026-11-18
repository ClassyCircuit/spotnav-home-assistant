// @vitest-environment jsdom
// @ts-nocheck
// Stage 19.4: covered-span readback wording (card) and last-known offline schedule wording (sidebar notes).
// Pure and mocked: no HA, nothing is sent; none of this shows physical charging or charger behavior.
import { describe, it, expect, vi } from "vitest";
import { morekPanel } from "../src/morek-view";
import { scheduleNotes } from "../sidebar/schedule-check.js";

const NOW = Date.parse("2026-11-14T10:00:00Z");
const iso = (ms) => new Date(ms).toISOString();
const READ_AT = "2026-11-06T20:02:00Z";
const base = {
  supported: true, verified: false, sent_at: "2026-11-06T20:00:00Z", ack: "Accepted",
  sent: { chargingProfileId: 42001, chargingSchedule: { startSchedule: "2026-11-06T20:00:00Z",
    chargingSchedulePeriod: [{ startPeriod: 0, limit: 0 }, { startPeriod: 3600, limit: 16 }, { startPeriod: 7200, limit: 0 }] } },
  effective: { status: "Accepted", fetched_at: READ_AT, periods: [{ at: READ_AT, amps: 0 }] },
};
const shortRead = (extra) => ({ ...base, verification: { reason: "coverage_too_short", readback_at: READ_AT,
  coverage_start: READ_AT, coverage_end: "2026-11-07T01:00:00Z", plan_end: "2026-11-06T22:00:00Z", ...extra } });

describe("19.4b covered-span wording on the card", () => {
  it("a matching short readback says matched only until the covered end, not verified for the whole plan", () => {
    const text = morekPanel(document, shortRead({ coverage_state: "matches_covered_span", covered_until: "2026-11-07T01:00:00Z" }),
      true, false, null, vi.fn()).textContent;
    expect(text).toMatch(/matched only until/);
    expect(text).toMatch(/Not verified for the whole plan, and not proof of charging/);
  });
  it("a differing span and an unverifiable span are worded as such, never as matched", () => {
    const differs = morekPanel(document, shortRead({ coverage_state: "differs", covered_until: "2026-11-07T01:00:00Z" }),
      true, false, null, vi.fn()).textContent;
    expect(differs).toMatch(/differed within the part covered/);
    expect(differs).not.toMatch(/matched only/);
    const unknown = morekPanel(document, shortRead({ coverage_state: "not_verifiable", covered_until: "2026-11-07T01:00:00Z" }),
      true, false, null, vi.fn()).textContent;
    expect(unknown).toMatch(/not verifiable for the whole plan/);
  });
  it("an unassociated comparison never shows a covered span", () => {
    const state = shortRead({ coverage_state: "matches_covered_span", covered_until: "2026-11-07T01:00:00Z" });
    state.verification.readback_at = "2026-11-06T19:00:00Z";
    expect(morekPanel(document, state, true, false, null, vi.fn()).textContent).not.toMatch(/matched only until/);
  });
});

describe("19.4c last-known offline wording", () => {
  const horizon = (extra = {}) => ({ state: "sent", windows: 2, ack: "accepted", plan_end: iso(NOW + 3 * 3600e3),
    coverage_state: "matches", covered_until: iso(NOW + 5 * 3600e3), plan_ended: false, physical_charging: "unknown", ...extra });
  const down = (h) => ({ supported: true, verified: false, link: { state: "down", since: iso(NOW - 60e3) },
    reconciliation: { reason: "x", blocker: null, check: null, repair: {}, recovery: {}, ...(h === undefined ? {} : { horizon: h }) } });
  const lost = (s) => scheduleNotes(s, NOW).items.find((i) => i.kind === "link_lost").text;

  it("names the last-known end, the readback class and what it depends on, with no guarantee", () => {
    const text = lost(down(horizon()));
    expect(text).toMatch(/runs until/);
    expect(text).toMatch(/matched it/);
    expect(text).toMatch(/own clock, settings and authorization/);
    expect(text).toMatch(/not a guarantee/);
    expect(text).toMatch(/cannot start or change anything while the connection is down/);
    expect(text).not.toMatch(/will charge|guaranteed to|verified/i);
  });
  it("a partial or differing readback is not described as a match; an ended plan says it ended", () => {
    expect(lost(down(horizon({ coverage_state: "matches_covered_span" })))).toMatch(/matched only part of it \(compared only until .*not compared\)/);
    expect(lost(down(horizon({ coverage_state: "differs" })))).toMatch(/differed from it/);
    const ended = lost(down(horizon({ plan_end: iso(NOW - 3600e3), plan_ended: true })));
    expect(ended).toMatch(/ended at/);
    expect(ended).not.toMatch(/keeps using it/);
  });
  it("an unknown or rejected acknowledgement never implies the schedule is installed or running", () => {
    for (const ack of ["rejected", "unknown", "faulted"]) {
      const text = lost(down(horizon({ ack })));
      expect(text).toMatch(/did not confirm accepting it, so it may not be installed/);
      expect(text).toMatch(/planned to end/);
      expect(text).not.toMatch(/runs until|matched it|keeps using/);
    }
    const ended = lost(down(horizon({ ack: "rejected", plan_end: iso(NOW - 3600e3), plan_ended: true })));
    expect(ended).toMatch(/may not be installed/);
    expect(ended).not.toMatch(/ended at/);
  });
  it("without a usable horizon the old connection text stays and nothing is invented", () => {
    for (const h of [undefined, null, { state: "none" }, { state: "sent", plan_end: "garbage" }, "x"]) {
      const text = lost(down(h));
      expect(text).toMatch(/SpotNav checks the schedule again when the charger reconnects\.$/);
    }
  });
});
