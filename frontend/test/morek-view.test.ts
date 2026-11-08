import { describe, expect, it, vi } from "vitest";
import { decodeMorekState, morekPanel } from "../src/morek-view";

const state = {
  supported: true,
  sent_at: "2026-11-06T20:00:00Z",
  ack: "Accepted",
  verified: false,
  sent: { chargingProfileId: 42001, chargingSchedule: {
    startSchedule: "2026-11-06T20:00:00Z",
    chargingSchedulePeriod: [{ startPeriod: 0, limit: 0 }, { startPeriod: 3600, limit: 16 }],
  } },
  effective: { status: "Accepted", fetched_at: "2026-11-06T20:01:00Z", periods: [
    { at: "2026-11-06T20:01:00Z", amps: 0 }, { at: "2026-11-06T20:30:00Z", amps: 16 },
  ] },
};

describe("Morek manual test panel", () => {
  it("shows upload and readback as different things, never calling a mismatch verified", () => {
    const action = vi.fn();
    const decoded = decodeMorekState({ schedule: state });
    expect(decoded).not.toBeNull();
    const panel = morekPanel(document, decoded!, true, false, null, action);
    expect(panel.textContent).toContain("Last upload: Accepted");
    expect(panel.textContent).toContain("NOT verified");
    expect(panel.textContent).toContain("Sent (profile 42001)");
    expect(panel.textContent).toContain("Morek effective schedule");
    const buttons = panel.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    buttons[1]?.click();
    expect(action).toHaveBeenCalledWith("fetch");
  });

  it("does not offer upload controls to a non-admin", () => {
    expect(morekPanel(document, state, false, false, null, vi.fn()).querySelector("button")).toBeNull();
  });
});
