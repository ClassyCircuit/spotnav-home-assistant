// Manual Morek profile test panel. Nothing here treats a sent profile as a confirmed schedule.
import { VISUAL_CLASSES as C } from "./visual-styles";

export interface MorekState {
  supported: boolean;
  cleanup_supported?: boolean;
  cleanup?: { requested_at: string; profile_id: number; status: string } | null;
  outcomes?: { uncertain: boolean; state?: string } | null;
  operator?: { state: string; reason?: string | null };
  ownership?: { recorded_owner?: string | null; blockers?: string[]; schedule_mode_available?: boolean };
  reason?: string | null;
  configured_id?: string | null;
  resolved_id?: string | null;
  connector_id?: number | null;
  preview?: { calculated_at: string; profile: MorekProfile | null; reason: string | null; preview_id?: string | null };
  sent_at: string | null;
  ack: string | null;
  verified: boolean;
  verification?: {
    pending?: boolean; reason?: string; exact?: boolean; tolerance_s?: number;
    max_delta_s?: number | null; coverage_start?: string | null; coverage_end?: string | null; next_check_at?: string | null;
  };
  sent: MorekProfile | null;
  effective: { status: string; fetched_at: string; periods: { at: string; amps: number }[];
    schedule_start?: string | null; duration_s?: number | null; rate_unit?: string | null } | null;
}

interface MorekProfile {
    chargingProfileId: number;
    stackLevel?: number;
    chargingSchedule: { startSchedule: string; chargingSchedulePeriod: { startPeriod: number; limit: number }[] };
}

export function decodeMorekState(raw: unknown): MorekState | null {
  if (raw === null || typeof raw !== "object") return null;
  const value = (raw as { schedule?: unknown }).schedule;
  if (value === null || typeof value !== "object") return null;
  const state = value as MorekState;
  if (typeof state.supported !== "boolean" || typeof state.verified !== "boolean") return null;
  if (state.verification !== undefined && (typeof state.verification !== "object" || state.verification === null ||
    (state.verification.pending !== undefined && typeof state.verification.pending !== "boolean") ||
    (state.verification.reason !== undefined && typeof state.verification.reason !== "string") ||
    (state.verification.max_delta_s != null && (typeof state.verification.max_delta_s !== "number" ||
      !Number.isFinite(state.verification.max_delta_s))) ||
    (state.verification.tolerance_s !== undefined && (typeof state.verification.tolerance_s !== "number" ||
      !Number.isFinite(state.verification.tolerance_s))) ||
    (state.verification.next_check_at != null && typeof state.verification.next_check_at !== "string") ||
    (state.verification.coverage_start != null && typeof state.verification.coverage_start !== "string") ||
    (state.verification.coverage_end != null && typeof state.verification.coverage_end !== "string"))) return null;
  if (state.cleanup_supported !== undefined && typeof state.cleanup_supported !== "boolean") return null;
  if (state.outcomes != null && (typeof state.outcomes !== "object" || typeof state.outcomes.uncertain !== "boolean")) return null;
  if (state.cleanup != null && (typeof state.cleanup !== "object" || state.cleanup.profile_id !== 42001 ||
    typeof state.cleanup.status !== "string" || typeof state.cleanup.requested_at !== "string")) return null;
  if (state.sent !== null && (
    typeof state.sent !== "object" || !Array.isArray(state.sent.chargingSchedule?.chargingSchedulePeriod)
  )) return null;
  if (state.effective !== null && (
    typeof state.effective !== "object" || !Array.isArray(state.effective.periods)
  )) return null;
  if (state.preview !== undefined && (
    typeof state.preview !== "object" || state.preview === null ||
    typeof state.preview.calculated_at !== "string" ||
    (state.preview.reason !== null && typeof state.preview.reason !== "string") ||
    (state.preview.profile !== null && (
      typeof state.preview.profile !== "object" ||
      !Array.isArray(state.preview.profile.chargingSchedule?.chargingSchedulePeriod)
    ))
  )) return null;
  return state;
}

function localTime(value: string | null): string {
  if (value === null) return "not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toLocaleString();
}

function transitions(doc: Document, profile: MorekProfile): HTMLUListElement {
  const start = new Date(profile.chargingSchedule.startSchedule).getTime();
  const list = doc.createElement("ul");
  for (const period of profile.chargingSchedule.chargingSchedulePeriod) {
    const line = doc.createElement("li");
    line.textContent = `${localTime(new Date(start + period.startPeriod * 1000).toISOString())}: ${period.limit} A`;
    list.append(line);
  }
  return list;
}

const PREVIEW_REFUSALS: Record<string, string> = {
  pause_auto_first: "Pause Auto 'Until I resume' before sending.",
  current_must_be_16: "Set the plan current to 16 A to preview this test.",
  no_current_plan: "No current, priced plan matches the saved settings.",
  plan_expired: "The plan has expired; the previously sent limit may still remain.",
  prices_unavailable: "Prices are missing for the current plan; no schedule will be sent.",
  prices_stale_or_unavailable: "Price data is stale or unavailable; no schedule will be sent.",
  target_stop_unsupported: "This HA backend cannot send shortened charging windows yet. Update the integration.",
  too_many_blocks: "This test supports at most three charging windows.",
  invalid_plan: "The charging windows must be valid, ordered, and within 48 hours.",
  morek_offline: "Morek is not connected through HA OCPP.",
  not_morek_connector: "This connector is not identified as the permitted Morek station.",
  preview_unavailable: "The plan could not be calculated right now. Try again shortly.",
};

export function morekPanel(
  doc: Document,
  state: MorekState,
  admin: boolean,
  busy: boolean,
  error: string | null,
  act: (action: "status" | "send" | "fetch" | "clear") => void,
  activeAction?: "status" | "send" | "fetch" | "clear" | null,
): HTMLElement {
  const section = doc.createElement("section");
  section.className = C.morekPanel;
  const heading = doc.createElement("h3");
  heading.textContent = "Morek stored schedule";
  section.append(heading);
  const health = doc.createElement("p");
  const labels: Record<string, string> = {
    waiting: "Waiting for a usable plan", not_ready: "Not ready", offline: "Offline",
    sending: "Sending — outcome not yet known", checking: "Checking readback",
    mismatch: "Mismatch — intervention may be needed", verified: "Remaining effective schedule verified at last read",
    intervention_needed: "Intervention needed — action outcome uncertain", ready: "Manual preview ready, not sent",
  };
  const sending = busy && activeAction === "send" && !state.outcomes?.uncertain;
  health.textContent = `Operator state: ${sending ? labels.sending : labels[state.operator?.state ?? ""] ?? "Unavailable — recalculate status"}` +
    (!sending && state.operator?.reason ? ` (${state.operator.reason})` : "");
  section.append(health);
  const availability = doc.createElement("p");
  availability.textContent = `Automatic Morek mode unavailable and unarmed. Recorded owner: ${state.ownership?.recorded_owner ?? "unknown"}. ` +
    "Durable ownership transitions and lost-state recovery, conflicting control and household protection, transaction authorization, and safe retained-profile exit remain unresolved.";
  section.append(availability);
  const evidence = doc.createElement("p");
  evidence.textContent = "Proposal is not sent; an upload ACK is not effective readback. A verified remaining effective schedule is not profile inventory, transaction authorization, or measured physical charging. Measured charging is not established here; check separate live measurements.";
  section.append(evidence);
  const recovery = doc.createElement("p");
  recovery.textContent = "A retained final 0 A may persist through restart or downgrade. Preserve any person Stop and household protection; do not blindly resume legacy control. For uncertain actions, keep the outcome unresolved and seek a supervised ownership and electrical recovery decision. Refresh is read-only, not inventory or recovery. Selective removal can increase allowed current and cannot resolve an earlier unknown upload; do not use a blanket profile clear.";
  section.append(recovery);
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
  const previewTitle = doc.createElement("strong");
  previewTitle.textContent = "Preview — calculated, NOT sent";
  section.append(previewTitle);
  const preview = doc.createElement("p");
  preview.textContent = state.preview === undefined
    ? "Preview unavailable from this HA version. Update the integration before sending."
    : `Calculated ${localTime(state.preview.calculated_at)}. Send recalculates from the latest plan and time; these times may shift.`;
  section.append(preview);
  if (state.preview?.profile) {
    section.append(transitions(doc, state.preview.profile));
    const endNote = doc.createElement("p");
    endNote.textContent = "These are fixed start/stop times from the displayed plan, including its estimated final stop. Morek will not adjust them based on actual energy delivered. If applied, the final 0 A limit can remain after the last window until explicitly removed.";
    section.append(endNote);
  }
  if (state.preview?.reason) {
    const refusal = doc.createElement("p");
    refusal.textContent = `Cannot send: ${PREVIEW_REFUSALS[state.preview.reason] ?? "This plan cannot be sent."}`;
    section.append(refusal);
  }
  const status = doc.createElement("p");
  const ack = state.ack === null ? "No plan sent from this card" : `Last upload: ${state.ack} at ${localTime(state.sent_at)}`;
  const verification = state.sent === null ? "" : state.verified && !state.outcomes?.uncertain
     ? state.verification?.reason === "matched_with_drift" ? " · Remaining schedule matched within tolerance, NOT exact" : " · Remaining schedule matched at last read"
    : state.verification?.pending ? " · Awaiting follow-up readback — NOT verified" : " · NOT verified";
  status.textContent = ack + verification;
  section.append(status);
  if (state.outcomes?.uncertain) {
    const warning = doc.createElement("p");
    warning.textContent = "A profile action or its stored outcome is uncertain and may have applied. Further sends are blocked; readback cannot prove which profiles are installed.";
    section.append(warning);
  }
  if (state.verification) {
    const detail = doc.createElement("p");
    const reasons: Record<string, string> = {
      limits_or_transitions_differ: "Morek's reported limits or transitions differ from the sent schedule.",
      readback_unavailable: "Morek has not returned a usable current schedule.",
      coverage_missing: "Morek did not report a duration; coverage cannot be verified.",
      coverage_too_short: "Morek's reported duration does not cover the final stop plus one hour.",
      coverage_stale: "The reported schedule coverage has already expired.",
      coverage_boundary_ambiguous: "Readback starts too close to a transition to establish the initial limit safely.",
      no_remaining_transitions: "No remaining transitions can be verified from this readback.",
      verification_superseded: "The readback belongs to an older or unavailable attempt or plan.",
      verification_interrupted: "Automatic checks were interrupted, for example by an HA restart. Refresh from Morek.",
      cleanup_requested: "The sent schedule is historical after a removal request.",
      upload_unconfirmed: "The upload was not confirmed; its effect is unknown.",
      outcome_uncertain: "An earlier profile action has an unresolved outcome; readback cannot resolve it.",
      matched: "Remaining effective limits and transitions match at the last read; past intervals and physical charging are not verified.",
      matched_with_drift: "Remaining limits match within the time tolerance; past intervals and physical charging are not verified.",
    };
    detail.textContent = reasons[state.verification.reason ?? ""] ?? "";
    if (state.verification.max_delta_s != null) {
      detail.textContent += ` Maximum transition drift: ${Math.round(state.verification.max_delta_s)} s; tolerance: ${state.verification.tolerance_s ?? 90} s.`;
    }
    if (state.verification.coverage_start) detail.textContent += ` Compared from ${localTime(state.verification.coverage_start)}.`;
    if (state.verification.coverage_end) detail.textContent += ` Readback covers through ${localTime(state.verification.coverage_end)}.`;
    if (state.verification.pending) detail.textContent += ` Automatic read-only check ${localTime(state.verification.next_check_at ?? null)}. No profile will be resent or cleared. Do not assume the sent limits are active yet.`;
    section.append(detail);
  }
  if (state.cleanup) {
    const cleanup = doc.createElement("p");
    cleanup.textContent = `Cleanup request for profile ${state.cleanup.profile_id}: ${state.cleanup.status} at ${localTime(state.cleanup.requested_at)}. ` +
      (state.cleanup.status.toLowerCase() === "accepted"
        ? "Morek acknowledged removal. Readback below shows effective limits, not proof of the stored profile inventory."
        : state.cleanup.status.toLowerCase() === "unknown"
          ? "Outcome unknown; the request may have taken effect. Do not assume the profile is removed."
          : "Morek did not acknowledge removal. Do not assume the profile is removed.");
    section.append(cleanup);
  }

  if (state.sent !== null) {
    const title = doc.createElement("strong");
    title.textContent = `Sent (profile ${state.sent.chargingProfileId})`;
    section.append(title);
    if (state.sent.stackLevel !== undefined) {
      const priority = doc.createElement("p");
      priority.textContent = `OCPP default-profile stack level: ${state.sent.stackLevel}`;
      section.append(priority);
    }
    section.append(transitions(doc, state.sent));
  }
  if (state.effective !== null) {
    const title = doc.createElement("strong");
    title.textContent = `Morek effective schedule (${state.effective.status}, read ${localTime(state.effective.fetched_at)})`;
    section.append(title);
    if (state.effective.duration_s !== undefined) {
      const coverage = doc.createElement("p");
      coverage.textContent = `Reported duration: ${state.effective.duration_s ?? "not reported"} seconds · unit: ${state.effective.rate_unit ?? "not reported"} · schedule start: ${localTime(state.effective.schedule_start ?? null)}.`;
      section.append(coverage);
    }
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
      ? [["Recalculate preview", "status"], ["Send current plan", "send"], ["Refresh from Morek", "fetch"]] as const
      : [["Check connection again", "status"]] as const;
    for (const [label, action] of choices) {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = C.button;
      button.textContent = label;
      button.disabled = busy || (action === "send" && (state.outcomes?.uncertain === true || state.preview === undefined || state.preview.reason !== null || !state.preview.profile || !state.preview.preview_id));
      button.addEventListener("click", () => {
        if (action === "send" && !doc.defaultView?.confirm(
          "Recalculate and send the CURRENT plan to Morek? Times may differ from this preview. Its final 0 A limit stays installed until explicitly cleared, even if SpotNav Auto resumes."
        )) return;
        act(action);
      });
      actions.append(button);
    }
    section.append(actions);
    if (state.supported && state.cleanup_supported === true) {
      const clear = doc.createElement("button");
      clear.type = "button";
      clear.className = C.button;
      clear.textContent = "Remove SpotNav schedule";
      clear.disabled = busy;
      clear.addEventListener("click", () => {
        if (!doc.defaultView?.confirm("Remove ONLY SpotNav schedule profile 42001 from Morek? This removes its persistent 0 A limit. Other installed profiles will not be deliberately cleared. Effective limits may increase. Auto will not be resumed.")) return;
        act("clear");
      });
      actions.append(clear);
    }
  }
  return section;
}
