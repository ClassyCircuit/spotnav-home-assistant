// Manual Morek profile test panel. Nothing here treats a sent profile as a confirmed schedule.
import { VISUAL_CLASSES as C } from "./visual-styles";

export interface MorekState {
  supported: boolean;
  reason?: string | null;
  configured_id?: string | null;
  resolved_id?: string | null;
  connector_id?: number | null;
  sent_at: string | null;
  ack: string | null;
  verified: boolean;
  sent: {
    chargingProfileId: number;
    chargingSchedule: { startSchedule: string; chargingSchedulePeriod: { startPeriod: number; limit: number }[] };
  } | null;
  effective: { status: string; fetched_at: string; periods: { at: string; amps: number }[] } | null;
}

export function decodeMorekState(raw: unknown): MorekState | null {
  if (raw === null || typeof raw !== "object") return null;
  const value = (raw as { schedule?: unknown }).schedule;
  if (value === null || typeof value !== "object") return null;
  const state = value as MorekState;
  if (typeof state.supported !== "boolean" || typeof state.verified !== "boolean") return null;
  if (state.sent !== null && (
    typeof state.sent !== "object" || !Array.isArray(state.sent.chargingSchedule?.chargingSchedulePeriod)
  )) return null;
  if (state.effective !== null && (
    typeof state.effective !== "object" || !Array.isArray(state.effective.periods)
  )) return null;
  return state;
}

function localTime(value: string | null): string {
  if (value === null) return "not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toLocaleString();
}

export function morekPanel(
  doc: Document,
  state: MorekState,
  admin: boolean,
  busy: boolean,
  error: string | null,
  act: (action: "status" | "send" | "fetch") => void,
): HTMLElement {
  const section = doc.createElement("section");
  section.className = C.morekPanel;
  const heading = doc.createElement("h3");
  heading.textContent = "Morek stored schedule (manual test)";
  section.append(heading);
  if (!state.supported) {
    const warning = doc.createElement("p");
    warning.textContent = state.reason === "no_ocpp_target"
      ? "SpotNav has not identified an OCPP connector for this charger. Check its OCPP charger setup."
      : state.reason === "wrong_connector"
        ? "SpotNav is configured for a different connector; this test requires connector 1."
        : state.reason === "ambiguous_station"
          ? "Multiple OCPP connections match this charger. No request will be sent until its identity is unambiguous."
          : state.reason === "unsupported_ocpp_version"
            ? "This test requires an OCPP 1.6 connection."
            : "HA OCPP has not matched this charger to Morek station 3020002509120029. Check its OCPP configuration and connection.";
    section.append(warning);
    const identity = doc.createElement("p");
    identity.textContent = `SpotNav OCPP ID: ${state.configured_id ?? "not found"} · connector: ${state.connector_id ?? "not found"} · HA OCPP station: ${state.resolved_id ?? "not resolved"}`;
    section.append(identity);
  }
  const note = doc.createElement("p");
  note.textContent = "SpotNav still uses live start/stop commands. Pause Auto 'Until I resume' before sending. These controls do not authorize a plugged-in car.";
  section.append(note);
  const status = doc.createElement("p");
  const ack = state.ack === null ? "No plan sent from this card" : `Last upload: ${state.ack} at ${localTime(state.sent_at)}`;
  const verification = state.sent === null ? "" : state.verified ? " · Matched at last read" : " · NOT verified";
  status.textContent = ack + verification;
  section.append(status);

  if (state.sent !== null) {
    const title = doc.createElement("strong");
    title.textContent = `Sent (profile ${state.sent.chargingProfileId})`;
    section.append(title);
    const start = new Date(state.sent.chargingSchedule.startSchedule).getTime();
    const list = doc.createElement("ul");
    for (const period of state.sent.chargingSchedule.chargingSchedulePeriod) {
      const line = doc.createElement("li");
      line.textContent = `${localTime(new Date(start + period.startPeriod * 1000).toISOString())}: ${period.limit} A`;
      list.append(line);
    }
    section.append(list);
  }
  if (state.effective !== null) {
    const title = doc.createElement("strong");
    title.textContent = `Morek effective schedule (${state.effective.status}, read ${localTime(state.effective.fetched_at)})`;
    section.append(title);
    const list = doc.createElement("ul");
    for (const period of state.effective.periods) {
      const line = doc.createElement("li");
      line.textContent = `${localTime(period.at)}: ${period.amps} A`;
      list.append(line);
    }
    section.append(list);
  }
  if (error !== null) {
    const message = doc.createElement("p");
    message.textContent = `Morek request failed: ${error}`;
    section.append(message);
  }
  if (admin) {
    const actions = doc.createElement("div");
    actions.className = C.morekActions;
    const choices = state.supported
      ? [["Send current plan", "send"], ["Refresh from Morek", "fetch"]] as const
      : [["Check connection again", "status"]] as const;
    for (const [label, action] of choices) {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = C.button;
      button.textContent = label;
      button.disabled = busy;
      button.addEventListener("click", () => {
        if (action === "send" && !doc.defaultView?.confirm(
          "Send this plan to Morek? Its final 0 A limit stays installed until explicitly cleared, even if SpotNav Auto resumes."
        )) return;
        act(action);
      });
      actions.append(button);
    }
    section.append(actions);
  }
  return section;
}
