// Manual Morek profile test panel. Nothing here treats a sent profile as a confirmed schedule.

export interface MorekState {
  supported: boolean;
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
  act: (action: "send" | "fetch") => void,
): HTMLElement {
  const section = doc.createElement("details");
  section.style.cssText = "margin: 12px 0; padding: 12px; border: 1px solid currentColor; border-radius: 8px";
  const heading = doc.createElement("summary");
  heading.textContent = "Morek stored schedule (manual test)";
  section.append(heading);
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
    for (const [label, action] of [["Send current plan", "send"], ["Refresh from Morek", "fetch"]] as const) {
      const button = doc.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.disabled = busy;
      button.style.marginRight = "8px";
      button.addEventListener("click", () => {
        if (action === "send" && !doc.defaultView?.confirm(
          "Send this plan to Morek? Its final 0 A limit stays installed until explicitly cleared, even if SpotNav Auto resumes."
        )) return;
        act(action);
      });
      section.append(button);
    }
  }
  return section;
}
