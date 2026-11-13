import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeMorekState, morekEvidence, morekPanel } from "../src/morek-view";
import { dashboard, FakeHass, mountCard } from "./helpers";

const state = {
  supported: true,
  preview: { calculated_at: "2026-11-06T20:00:00Z", preview_id: "preview-matches-windows", reason: null, profile: {
    chargingProfileId: 42001, chargingSchedule: {
      startSchedule: "2026-11-06T20:00:00Z",
      chargingSchedulePeriod: [{ startPeriod: 0, limit: 0 }, { startPeriod: 3600, limit: 16 }, { startPeriod: 5400, limit: 0 }],
    },
  } },
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

describe("daily Morek evidence", () => {
  const now = Date.parse("2026-11-06T20:02:00Z");
  const current = { ...state, verified: true, verification_target: "current_plan" as const,
    verification: {readback_at: state.effective.fetched_at},
    effective: { ...state.effective, schedule_start: "2026-11-06T20:01:00Z", duration_s: 3600 } };
  it.each([
    [current, now, false, /remaining plan matched/i],
    [current, now-100000, false, /status.*stale/i],
    [{...current, verification:{reason:"verification_superseded"}}, now, false, /older or unavailable/i],
    [{...current, verified:false, verification:{reason:"limits_or_transitions_differ",readback_at:state.effective.fetched_at}}, now, false, /limits at the last read differed/i],
    [{...current, effective:null}, now, false, /readback is unavailable/i],
    [{...current, operator:{state:"offline"}}, now, false, /offline/i],
    [{...current, outcomes:{uncertain:true}}, now, false, /may have applied/i],
    [{...current, verification_target:"held_pause" as const}, now, false, /held pause/i],
    [current, now, true, /stale/i],
  ])("reports only supported evidence", (sample, observed, failed, expected) => {
    expect(morekEvidence(sample, observed, failed, now).summary).toMatch(expected);
  });
  it("keeps technical details collapsed and opens without writes", () => {
    const act=vi.fn();const panel=morekPanel(document,current,true,false,null,act);
    const details=panel.querySelector("details")!;
    expect(details.open).toBe(false);expect(details.textContent).toContain("Sent (profile 42001)");
    details.open=true;expect(details.open).toBe(true);expect(act).not.toHaveBeenCalled();
  });
});

describe("Morek manual test panel", () => {
  it("keeps unmatched comparison coverage separate and shows only real errors", () => {
    const act=vi.fn();
    const mismatch={...state,verified:true,verification:{reason:'matched',readback_at:'2026-11-06T20:02:00Z',coverage_end:'2026-11-07T08:00:00Z'}};
    const panel=morekPanel(document,mismatch,true,false,undefined as unknown as null,act);
    expect(panel.textContent).not.toContain('Morek request failed');expect(panel.textContent).not.toContain('Readback covers through');expect(panel.textContent).toContain('not associated');expect(panel.textContent).toContain('NOT verified');
    expect(morekPanel(document,mismatch,true,false,'offline',act).textContent).toContain('Morek request failed: offline');expect(act).not.toHaveBeenCalled();
  });
  it("shows an automatic reconciliation blocker without issuing any action", () => {
    const act = vi.fn();
    const panel = morekPanel(document, { ...state, reconciliation: { reason: "price_coverage_unavailable" } }, true, false, null, act);
    expect(panel.textContent).toContain("Published prices do not cover the proposed windows");
    expect(panel.textContent).toContain("retained limit may remain");
    expect(panel.querySelector("details")?.textContent).not.toContain("Published prices do not cover the proposed windows");
    expect(act).not.toHaveBeenCalled();
  });
  it("shows an unknown worker reason outside the collapsed diagnostics", () => {
    const panel = morekPanel(document, { ...state, reconciliation: { reason: "new_blocker" } }, true, false, null, vi.fn());
    expect(panel.textContent).toContain("(new_blocker)");
    expect(panel.querySelector("details")?.textContent).not.toContain("(new_blocker)");
  });
  it.each([
    ["waiting", "Waiting for a usable plan"], ["offline", "Offline"],
    ["sending", "Sending — outcome not yet known"], ["checking", "Checking readback"],
    ["mismatch", "Mismatch"], ["verified", "Remaining effective schedule verified at last read"],
    ["intervention_needed", "Intervention needed"], ["not_ready", "Not ready"],
  ])("shows operator state %s and activation blockers", (status, label) => {
    const panel = morekPanel(document, { ...state, operator: { state: status }, ownership: { recorded_owner: "legacy" } }, true, false, null, vi.fn());
    expect(panel.textContent).toContain(label);
    expect(panel.textContent).toContain("Schedule sending is blocked; review ownership and recovery status");
    expect(panel.textContent).toContain("household protection");
    expect(panel.textContent).toContain("transaction authorization");
    expect(panel.textContent).toContain("not profile inventory");
    expect(panel.textContent).toContain("do not blindly resume legacy control");
    expect(panel.textContent).toContain("person Stop");
  });
  it("does not display an old verified flag as a match when outcome is uncertain", () => {
    const panel = morekPanel(document, { ...state, verified: true, outcomes: { uncertain: true } }, true, false, null, vi.fn());
    expect(panel.textContent).not.toContain("Remaining schedule matched at last read");
    expect(panel.textContent).toContain("NOT verified");
  });
  it("exposes uncertain stored outcomes and blocks send without blocking readback", () => {
    const panel = morekPanel(document, { ...state, outcomes: { uncertain: true } }, true, false, null, vi.fn());
    expect(panel.textContent).toContain("may have applied");
    expect(panel.textContent).toContain("readback cannot prove which profiles are installed");
    const buttons = Array.from(panel.querySelectorAll("button"));
    expect(buttons.find((button) => button.textContent === "Send current plan")?.disabled).toBe(true);
    expect(buttons.find((button) => button.textContent === "Refresh from Morek")?.disabled).toBe(false);
  });
  it("explains that shortened plan windows are sent as fixed times, not live energy control", () => {
    const panel = morekPanel(document, state, true, false, null, vi.fn());
    expect(panel.textContent).toContain("fixed start/stop times from the displayed plan");
    expect(panel.textContent).toContain("will not adjust them based on actual energy delivered");
    expect(Array.from(panel.querySelectorAll("button")).find((button) => button.textContent === "Send current plan")?.disabled).toBe(false);
  });
  it("distinguishes delayed verification from a confirmed or silently applied schedule", () => {
    const act = vi.fn();
    const panel = morekPanel(document, { ...state, verification: {
      pending: true, reason: "limits_or_transitions_differ", next_check_at: "2026-11-06T20:01:30Z",
    } }, true, false, null, act);
    expect(panel.textContent).toContain("Awaiting follow-up readback — NOT verified");
    expect(panel.textContent).toContain("No profile will be resent or cleared");
    expect(panel.textContent).toContain("Do not assume the sent limits are active yet");
    expect(act).not.toHaveBeenCalled();
  });

  it("discloses the timing tolerance and coverage rather than calling drift an exact match", () => {
    const panel = morekPanel(document, { ...state, verified: true, verification: {
      pending: false, reason: "matched_with_drift", max_delta_s: 57, tolerance_s: 90,
      readback_at: state.effective.fetched_at,
      coverage_end: "2026-11-07T08:00:00Z",
    } }, true, false, null, vi.fn());
    expect(panel.textContent).toContain("Remaining schedule matched within tolerance, NOT exact");
    expect(panel.textContent).toContain("past intervals and physical charging are not verified");
    expect(panel.textContent).toContain("Maximum transition drift: 57 s; tolerance: 90 s");
    expect(panel.textContent).toContain("Readback covers through");
  });

  it("reports interrupted and missing-coverage checks without claiming verification", () => {
    const interrupted = morekPanel(document, { ...state, verification: {
      pending: false, reason: "verification_interrupted",
    } }, true, false, null, vi.fn());
    expect(interrupted.textContent).toContain("Automatic checks were interrupted");
    const missing = morekPanel(document, { ...state, verification: {
      pending: false, reason: "coverage_missing",
    } }, true, false, null, vi.fn());
    expect(missing.textContent).toContain("duration; coverage cannot be verified");
    expect(decodeMorekState({ schedule: { ...state, verification: { pending: "yes" } } })).toBeNull();
    expect(decodeMorekState({ schedule: { ...state, verification: { max_delta_s: NaN } } })).toBeNull();
  });
  it("requires separate confirmation for selective cleanup and never offers it on an old backend", () => {
    const act = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const panel = morekPanel(document, { ...state, cleanup_supported: true }, true, false, null, act);
    const clear = Array.from(panel.querySelectorAll("button")).find((button) => button.textContent === "Remove SpotNav schedule")!;
    clear.click();
    expect(act).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    clear.click();
    expect(act).toHaveBeenCalledWith("clear");
    expect(morekPanel(document, state, true, false, null, act).textContent).not.toContain("Remove SpotNav schedule");
    confirm.mockRestore();
  });

  it("labels cleanup acknowledgement separately from readback and physical charging", () => {
    const panel = morekPanel(document, { ...state, cleanup: {
      requested_at: "2026-11-06T20:02:00Z", profile_id: 42001, status: "Accepted",
    } }, true, false, null, vi.fn());
    expect(panel.textContent).toContain("Morek acknowledged removal");
    expect(panel.textContent).toContain("not proof of the stored profile inventory");
    expect(panel.textContent).toContain("Sent (profile 42001)");
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.replaceChildren();
  });

  it("shows upload and readback as different things, never calling a mismatch verified", () => {
    const action = vi.fn();
    const decoded = decodeMorekState({ schedule: state });
    expect(decoded).not.toBeNull();
    const panel = morekPanel(document, decoded!, true, false, null, action);
    expect(panel.textContent).toContain("Last upload: Accepted");
    expect(panel.textContent).toContain("NOT verified");
    expect(panel.textContent).toContain("Sent (profile 42001)");
    expect(panel.textContent).toContain("Preview — calculated, NOT sent");
    expect(panel.textContent).toContain("final 0 A limit can remain");
    expect(panel.textContent).toContain("Morek effective schedule");
    const buttons = panel.querySelectorAll("button");
    expect(buttons).toHaveLength(3);
    buttons[2]?.click();
    expect(action).toHaveBeenCalledWith("fetch");
  });

  it("refuses send when preview is stale, unavailable, or Auto is not paused", () => {
    const noPreview = morekPanel(document, { ...state, preview: undefined }, true, false, null, vi.fn());
    expect(noPreview.textContent).toContain("Preview unavailable");
    expect(Array.from(noPreview.querySelectorAll("button")).find((button) => button.textContent === "Send current plan")?.disabled).toBe(true);
    const paused = morekPanel(document, { ...state, preview: { ...state.preview, reason: "pause_auto_first" } }, true, false, null, vi.fn());
    expect(paused.textContent).toContain("Cannot send: Pause Auto");
    expect(Array.from(paused.querySelectorAll("button")).find((button) => button.textContent === "Send current plan")?.disabled).toBe(true);
  });

  it("does not offer upload controls to a non-admin", () => {
    expect(morekPanel(document, state, false, false, null, vi.fn()).querySelector("button")).toBeNull();
  });

  it("keeps the styled opener and a useful diagnosis when the station does not match", async () => {
    vi.useFakeTimers();
    const transport = new FakeHass();
    transport.trackMorek = true;
    const hass = transport.snapshot("admin", "en");
    hass.user = { is_admin: true };
    const card = mountCard({ type: "custom:spotnav-card", charger: "entry_a" }, hass);
    await vi.advanceTimersByTimeAsync(0);
    transport.resolveNext(dashboard());
    await vi.advanceTimersByTimeAsync(0);
    const root = card.shadowRoot!;
    const opener = root.querySelector<HTMLButtonElement>(".spotnav-morek-toggle")!;
    expect(opener.classList.contains("spotnav-button")).toBe(true);
    opener.click();
    expect(transport.messages.at(-1)?.action).toBe("status");
    transport.resolveNext({ api_version: 1, schedule: {
      ...state, supported: false, reason: "station_not_matched", configured_id: "garage",
      resolved_id: null, connector_id: 1,
    } });
    await vi.advanceTimersByTimeAsync(0);
    expect(root.querySelector(".spotnav-morek-toggle")).not.toBeNull();
    expect(root.textContent).toContain("SpotNav OCPP ID: garage");
    expect(root.textContent).toContain("not resolved");
    expect(root.textContent).toContain("Check connection again");
    expect(root.textContent).not.toContain("Send current plan");
    root.querySelector<HTMLButtonElement>(".spotnav-morek-panel button")!.click();
    expect(transport.messages.at(-1)?.action).toBe("status");
  });

  it("will not enable Send for a preview without a backend plan fingerprint", () => {
    const panel = morekPanel(document, { ...state, preview: { ...state.preview, preview_id: null } }, true, false, null, vi.fn());
    expect(Array.from(panel.querySelectorAll("button")).find((button) => button.textContent === "Send current plan")?.disabled).toBe(true);
  });
});
