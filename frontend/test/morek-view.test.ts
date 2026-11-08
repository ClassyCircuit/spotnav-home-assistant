import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeMorekState, morekPanel } from "../src/morek-view";
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

describe("Morek manual test panel", () => {
  it("requires separate confirmation for selective cleanup and never offers it on an old backend", () => {
    const act = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const panel = morekPanel(document, { ...state, cleanup_supported: true }, true, false, null, act);
    const clear = Array.from(panel.querySelectorAll("button")).find((button) => button.textContent === "Remove test profile 42001")!;
    clear.click();
    expect(act).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    clear.click();
    expect(act).toHaveBeenCalledWith("clear");
    expect(morekPanel(document, state, true, false, null, act).textContent).not.toContain("Remove test profile 42001");
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
    expect(panel.textContent).toContain("final 0 A limit remains installed");
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
