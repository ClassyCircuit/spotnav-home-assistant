import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dailyOverview, healthKey } from "../src/daily-overview";
import { decodeMorekState } from "../src/morek-view";
import { decodeDashboard } from "../src/validate";
import { registerTranslation } from "../src/i18n";
import sv from "../src/i18n/sv.json";
import { dashboard, FakeHass, mountCard } from "./helpers";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const NOW = Date.parse("2026-11-06T20:02:00Z");
const profile = { chargingProfileId: 42001, chargingSchedule: { startSchedule: "2026-11-06T20:00:00Z", chargingSchedulePeriod: [{ startPeriod: 0, limit: 0 }, { startPeriod: 3600, limit: 16 }] } };
const status = (extra: Record<string, unknown> = {}) => ({ api_version: 1, schedule: {
  supported: true, sent_at: "2026-11-06T20:00:00Z", ack: "Accepted", sent: profile, verified: true,
  operator: { state: "verified", reason: "matched" }, outcomes: { uncertain: false },
  preview: { calculated_at: "2026-11-06T20:01:59Z", profile, reason: null, preview_id: "fingerprint" },
  verification: { reason: "matched", coverage_start: "2026-11-06T20:01:00Z", coverage_end: "2026-11-07T08:00:00Z" },
  effective: { status: "Accepted", fetched_at: "2026-11-06T20:01:00Z", periods: [{ at: "2026-11-06T20:01:00Z", amps: 0 }, { at: "2026-11-06T21:00:00Z", amps: 16 }] }, ...extra,
} });
const state = (extra: Record<string, unknown> = {}) => decodeMorekState(status(extra))!;
const tick = async () => { await vi.advanceTimersByTimeAsync(0); };
const cardText = (card: HTMLElement) => card.shadowRoot!.textContent ?? "";

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(NOW); document.body.replaceChildren(); });
afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

describe("real daily overview", () => {
  it("renders the backend serializer's target-SOC contract fixture", () => {
    const raw: unknown = JSON.parse(readFileSync(resolve("../tests/fixtures/dashboard/target_soc_two_vehicles.json"), "utf8"));
    const decoded = decodeDashboard(raw);
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    const el = dailyOverview(document, decoded.value, "en", null, null, false, false, NOW);
    expect(el.textContent).toContain("Battery SOC");
    expect(el.textContent).toContain("Measured power unavailable");
    expect(el.textContent).toContain("Proposed energy (estimate)");
    expect(el.textContent).toContain("Reading age: 45 d ago");
    const atSnapshot = dailyOverview(document, decoded.value, "en", null, null, false, false, Date.parse("2026-09-22T06:00:00Z"));
    expect(Array.from(atSnapshot.querySelectorAll("dl")).find((row) => row.textContent?.startsWith("Next proposed window"))?.querySelector("dd")?.textContent).toContain("9:15 AM");
    decoded.value.generated_at = null;
    expect(dailyOverview(document, decoded.value, "en", null, null, false, false, NOW).textContent).toContain("Reading age: Unknown");
  });
  it("renders decoded dashboard facts and never treats planned power or zero current as measured power", () => {
    const raw = dashboard();
    const decoded = decodeDashboard(raw);
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    decoded.value.live.measured_current_a = 0;
    if (decoded.value.plan.proposal) decoded.value.plan.proposal.power_kw = 11;
    const el = dailyOverview(document, decoded.value, "en", state(), NOW, false, false, NOW);
    expect(el.textContent).toContain("Measured power unavailable");
    expect(el.textContent).not.toContain("11 kW");
    expect(Array.from(el.querySelectorAll("dl")).find((row) => row.textContent?.startsWith("Measured power"))?.querySelector("dd")?.textContent).toBe("Measured power unavailable");
    decoded.value.live.measured_current_a = null;
    const missing = dailyOverview(document, decoded.value, "en", null, null, false, false, NOW);
    expect(missing.textContent).toContain("Measured power unavailable");
    expect(el.textContent).toContain("Association with the displayed proposal is unknown");
    expect(el.textContent).toContain("not profile inventory");
    expect(el.querySelector(".spotnav-daily-grid")).not.toBeNull();
  });
  it("localizes and handles missing values and historical planner data", () => {
    const decoded = decodeDashboard(dashboard());
    if (!decoded.ok) throw new Error("fixture");
    decoded.value.soc = null;
    decoded.value.plan.proposal = null;
    if (decoded.value.planning) decoded.value.planning.historical = true;
    registerTranslation("sv", sv);
    const el = dailyOverview(document, decoded.value, "sv", null, null, false, false, NOW);
    expect(el.textContent).toContain("Dagsöversikt");
    expect(el.textContent).toContain("Okänt");
    expect(el.textContent).toContain("Historisk plan");
    expect(el.textContent).toContain("Uppmätt effekt saknas");
  });
  it("keeps multiple critical observations visible rather than hiding identity or mismatch", () => {
    const decoded = decodeDashboard(dashboard());
    if (!decoded.ok) throw new Error("fixture");
    const s = state({ supported: false, outcomes: { uncertain: true }, operator: { state: "offline" }, verification: { reason: "limits_or_transitions_differ" } });
    const text = dailyOverview(document, decoded.value, "en", s, NOW, false, false, NOW).textContent;
    expect(text).toContain("Intervention needed");
    expect(text).toContain("identity unsupported");
    expect(text).toContain("Morek offline");
    expect(text).toContain("mismatch the sent schedule");
  });
  it.each([
    [{ operator: { state: "offline" } }, "daily.health.offline"],
    [{ operator: { state: "mismatch" }, verified: false }, "daily.health.mismatch"],
    [{ outcomes: { uncertain: true } }, "daily.health.uncertain"],
    [{ supported: false, operator: { state: "not_ready" } }, "daily.health.unsupported"],
    [{ verification: { reason: "verification_superseded" }, verified: false }, "daily.health.superseded"],
    [{ operator: { state: "waiting" }, verified: false }, "daily.health.waiting"],
    [{ effective: null }, "daily.health.stale"],
    [{}, "daily.health.matched"],
  ])("classifies independent status conservatively %#", (patch, expected) => {
    expect(healthKey(state(patch), NOW, false, false, NOW)).toBe(expected);
  });
  it("handles missing, failed, stale and inconsistent evidence", () => {
    expect(decodeMorekState({ ...status(), api_version: 2 })).toBeNull();
    expect(healthKey(null, null, false, false, NOW)).toBe("daily.health.loading");
    expect(healthKey(null, null, true, false, NOW)).toBe("daily.health.unavailable");
    expect(healthKey(state(), NOW - 100_000, false, false, NOW)).toBe("daily.health.stale");
    expect(healthKey(state({ verified: false }), NOW, false, false, NOW)).toBe("daily.health.unavailable");
    expect(healthKey(state({ effective: { status: "Accepted", fetched_at: "2026-11-06T20:01:00Z", periods: [] } }), NOW, false, false, NOW)).toBe("daily.health.stale");
  });
});

describe("card status lifecycle and safety", () => {
  async function setup(admin = false) {
    const transport = new FakeHass(); transport.trackMorek = true;
    const hass = transport.snapshot("reader", "en"); hass.user = { is_admin: admin };
    const card = mountCard({ type: "custom:spotnav-card", charger: "entry_a" }, hass);
    await tick(); transport.resolveNext(dashboard()); await tick();
    return { transport, card, hass };
  }
  it.each([false, true])("opens and refreshes using read requests only (admin=%s)", async (admin) => {
    const { transport, card, hass } = await setup(admin);
    expect(cardText(card)).toContain("Daily overview");
    expect(cardText(card)).toContain("Loading status");
    transport.resolveNext(status()); await tick();
    expect(cardText(card)).toContain("Remaining effective limits matched");
    for (let i = 0; i < 5; i++) card.hass = hass;
    const refresh = card.refresh(); transport.resolveNext(dashboard()); await refresh; await tick();
    expect(transport.messages.map((m) => [m.type, m.action])).toEqual([
      ["spotnav/get_dashboard", undefined], ["spotnav/morek_schedule", "status"],
      ["spotnav/get_dashboard", undefined], ["spotnav/morek_schedule", "status"],
    ]);
  });
  it("renders the dashboard during a slow status and recovers from timeout", async () => {
    const { transport, card } = await setup();
    expect(cardText(card)).toContain("Daily overview");
    expect(cardText(card)).toContain("Garage");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(cardText(card)).toContain("Status unavailable");
    transport.resolveNext(status()); await tick();
    expect(cardText(card)).toContain("Status unavailable");
  });
  it("updates status without replacing the card view", async () => {
    const { transport, card } = await setup();
    const view = card.shadowRoot!.querySelector(".spotnav-card");
    transport.resolveNext(status()); await tick();
    expect(card.shadowRoot!.querySelector(".spotnav-card")).toBe(view);
    expect(cardText(card)).toContain("Remaining effective limits matched");
  });
  it("ages a previously matched status even when the next dashboard never answers", async () => {
    const { transport, card } = await setup();
    transport.resolveNext(status()); await tick();
    expect(cardText(card)).toContain("Remaining effective limits matched");
    await vi.advanceTimersByTimeAsync(120_000);
    expect(cardText(card)).toContain("Evidence stale or incomplete; not verified");
    expect(cardText(card)).not.toContain("Remaining effective limits matched");
    expect(transport.messages.filter((m) => m.type === "spotnav/get_dashboard")).toHaveLength(2);
  });
  it("lets a newer status win when an expired request answers after it", async () => {
    const { transport, card } = await setup();
    await vi.advanceTimersByTimeAsync(10_000);
    const refresh = card.refresh(); transport.resolveAt(1, dashboard()); await refresh; await tick();
    transport.resolveAt(1, status({ operator: { state: "offline" } })); await tick();
    expect(cardText(card)).toContain("Morek offline");
    transport.resolveAt(0, status()); await tick();
    expect(cardText(card)).toContain("Morek offline");
    expect(cardText(card)).not.toContain("Remaining effective limits matched");
  });
  it("does not allow a late status from a previous charger or connection to paint", async () => {
    const { transport, card } = await setup();
    card.setConfig({ type: "custom:spotnav-card", charger: "entry_b" }); await tick();
    transport.resolveAt(0, status({ operator: { state: "mismatch" } })); await tick();
    transport.resolveNext(dashboard()); await tick();
    expect(cardText(card)).not.toContain("Effective limits mismatch");
    card.remove(); document.body.append(card); await tick();
    transport.resolveAt(0, status({ operator: { state: "offline" } })); await tick();
    transport.resolveNext(dashboard()); await tick();
    transport.resolveNext(status()); await tick();
    expect(cardText(card)).toContain("Remaining effective limits matched");
    expect(cardText(card)).not.toContain("Morek offline");
  });
  it("invalidates a pending status when a manual action starts and does not follow an old action into another charger", async () => {
    const { transport, card } = await setup(true);
    transport.resolveNext(status()); await tick();
    card.shadowRoot!.querySelector<HTMLButtonElement>(".spotnav-morek-toggle")!.click(); await tick();
    const refresh = card.refresh(); transport.resolveNext(dashboard()); await refresh; await tick();
    const send = Array.from(card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".spotnav-morek-panel button")).find((b) => b.textContent === "Send current plan")!;
    vi.spyOn(window, "confirm").mockReturnValue(true); send.click(); await tick();
    transport.resolveAt(0, status({ operator: { state: "offline" } })); await tick();
    expect(cardText(card)).not.toContain("Morek offline");
    card.setConfig({ type: "custom:spotnav-card", charger: "entry_b" }); await tick();
    const before = transport.messages.length;
    transport.resolveAt(0, status()); await tick();
    expect(transport.messages.length).toBe(before);
    vi.restoreAllMocks();
  });
  it("does not adopt a manual follow-up after disconnect and reconnect", async () => {
    const { transport, card } = await setup(true);
    transport.resolveNext(status()); await tick();
    card.shadowRoot!.querySelector<HTMLButtonElement>(".spotnav-morek-toggle")!.click(); await tick();
    const button = Array.from(card.shadowRoot!.querySelectorAll<HTMLButtonElement>(".spotnav-morek-panel button")).find((b) => b.textContent === "Refresh from Morek")!;
    button.click(); await tick();
    transport.resolveNext(status()); await tick(); // manual fetch result, now status follow-up is pending
    card.remove(); document.body.append(card); await tick();
    expect(cardText(card)).not.toContain("Morek stored schedule");
    expect(cardText(card)).not.toContain("Remaining effective limits matched");
    transport.resolveAt(0, status({ operator: { state: "offline" } })); await tick();
    transport.resolveNext(dashboard()); await tick();
    transport.resolveNext(status()); await tick();
    expect(cardText(card)).not.toContain("Morek offline");
    expect(cardText(card)).toContain("Remaining effective limits matched");
  });
});
