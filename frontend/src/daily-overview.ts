// Daily facts from the dashboard and the separately observed Morek status.
// No commands, telemetry inference, HTML parsing or sample values live here.
import { formatNumber, percentAmount } from "./format";
import { translate, type Language, type TranslationKey } from "./i18n";
import type { MorekState } from "./morek-view";
import type { Dashboard } from "./validate";
import { ageSentence, connectionLabel } from "./vehicle-line";

const STATUS_MAX_AGE = 90_000;
const READBACK_MAX_AGE = 300_000;

function time(value: string | null | undefined, language: Language, zone: string | null): string | null {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  try {
    const formatted = new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short", timeZone: zone ?? "UTC" }).format(date);
    return zone === null ? `${formatted} UTC` : formatted;
  } catch { return null; }
}

/** A match is evidence of the remaining effective limits at a past read, not of the dashboard proposal. */
export function healthKey(state: MorekState | null, observedAt: number | null, failed: boolean, busy: boolean, now: number): TranslationKey {
  if (state?.outcomes?.uncertain === true) return "daily.health.uncertain";
  if (busy) return "daily.health.busy";
  if (state?.operator?.state === "offline") return "daily.health.offline";
  if (state?.operator?.state === "mismatch" || state?.verification?.reason === "limits_or_transitions_differ") return "daily.health.mismatch";
  if (failed || state === null || observedAt === null) return failed ? "daily.health.unavailable" : "daily.health.loading";
  if (!Number.isFinite(observedAt) || now < observedAt || now - observedAt > STATUS_MAX_AGE) return "daily.health.stale";
  if (!state.supported) return "daily.health.unsupported";
  if (state.verification?.reason === "verification_superseded") return "daily.health.superseded";
  if (state.operator?.state === "verified" && state.verified === true) {
    const read = Date.parse(state.effective?.fetched_at ?? "");
    const end = Date.parse(state.verification?.coverage_end ?? "");
    const start = Date.parse(state.verification?.coverage_start ?? "");
    const preview = Date.parse(state.preview?.calculated_at ?? "");
    const reason = state.verification?.reason;
    if ((reason === "matched" || reason === "matched_with_drift") && state.ack === "Accepted" &&
      state.sent !== null && Number.isFinite(Date.parse(state.sent_at ?? "")) &&
      state.effective?.status === "Accepted" && Array.isArray(state.effective.periods) && state.effective.periods.length >= 2 &&
      state.effective.periods.every((period) => period !== null && typeof period === "object" &&
        typeof period.at === "string" && Number.isFinite(Date.parse(period.at)) && Number.isFinite(period.amps)) &&
      Number.isFinite(preview) && preview <= now && now - preview <= STATUS_MAX_AGE &&
      Number.isFinite(read) && read <= now && now - read <= READBACK_MAX_AGE &&
      Number.isFinite(start) && start <= now && Number.isFinite(end) && end > now) return "daily.health.matched";
    return "daily.health.stale";
  }
  if (state.operator?.state === "checking") return "daily.health.checking";
  if (state.operator?.state === "sending" || state.operator?.state === "intervention_needed") return "daily.health.uncertain";
  if (state.operator?.state === "ready" || state.operator?.state === "waiting") return "daily.health.waiting";
  return "daily.health.unavailable";
}

export function dailyOverview(doc: Document, dashboard: Dashboard, language: Language, state: MorekState | null,
  observedAt: number | null, failed: boolean, busy: boolean, now: number): HTMLElement {
  const t = (key: TranslationKey): string => translate(language, key);
  const unknown = t("daily.unknown");
  const zone = dashboard.market?.timezone ?? null;
  const root = doc.createElement("section");
  root.className = "spotnav-daily";
  root.setAttribute("aria-label", t("daily.title"));
  const style = doc.createElement("style");
  style.textContent = `.spotnav-daily{margin:12px 0;padding:14px;border:1px solid var(--divider-color,#777);border-radius:12px;background:var(--secondary-background-color,transparent);color:var(--primary-text-color);min-width:0}.spotnav-daily h3{font-size:1em;margin:0 0 10px}.spotnav-daily-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:10px}.spotnav-daily dl{margin:0;min-width:0}.spotnav-daily dt{color:var(--secondary-text-color);font-size:.82em}.spotnav-daily dd{margin:3px 0 0;overflow-wrap:anywhere;font-weight:600}.spotnav-daily-health{border-top:1px solid var(--divider-color,#777);margin-top:12px;padding-top:10px}.spotnav-daily-health p{margin:4px 0;overflow-wrap:anywhere}.spotnav-daily-health p[data-health='daily.health.mismatch'],.spotnav-daily-health p[data-health='daily.health.uncertain'],.spotnav-daily-health p[data-health='daily.health.offline']{font-weight:700}.spotnav-daily small{color:var(--secondary-text-color)}`;
  root.append(style);
  const heading = doc.createElement("h3"); heading.textContent = t("daily.title"); root.append(heading);
  const grid = doc.createElement("div"); grid.className = "spotnav-daily-grid";
  const row = (label: TranslationKey, value: string): void => {
    const dl = doc.createElement("dl"), dt = doc.createElement("dt"), dd = doc.createElement("dd");
    dt.textContent = t(label); dd.textContent = value; dl.append(dt, dd); grid.append(dl);
  };
  const connected = dashboard.charger.available ? connectionLabel(language, dashboard.connection) : t("daily.offline");
  row("daily.connection", connected ?? unknown);
  const soc = dashboard.soc;
  const socValue = soc?.value == null ? unknown : `${percentAmount(language, soc.value)}${soc.estimated ? ` (${t("settings.soc.estimated")})` : ""}`;
  const generated = Date.parse(dashboard.generated_at ?? "");
  const age = soc?.age_s != null && Number.isFinite(soc.age_s) && soc.age_s >= 0 && Number.isFinite(generated) && generated <= now
    ? ageSentence(language, soc.age_s + (now - generated) / 1000) : unknown;
  const source = soc?.source === "charger" ? t("settings.heading.charger") : soc?.source === "vehicle" ? t("settings.soc.vehicle") : unknown;
  row("daily.soc", `${socValue} · ${source} · ${t("daily.age")}: ${age}`);
  row("daily.power", t("daily.powerUnavailable"));
  const proposal = dashboard.plan.proposal;
  const next = proposal?.periods.find((period) => period.endMs > now);
  const start = time(next?.start, language, zone), end = time(next?.end, language, zone);
  row("daily.next", start && end ? `${start} – ${end}` : unknown);
  row("daily.energy", proposal?.planned_kwh == null ? unknown : `${formatNumber(language, proposal.planned_kwh, 2)} kWh`);
  const cost = proposal?.cost;
  row("daily.cost", cost == null || cost.currency == null ? unknown : `${formatNumber(language, cost.value, 2)} ${cost.currency}`);
  const calculated = time(dashboard.planning?.calculated_at, language, zone);
  const historical = dashboard.planning?.historical;
  const calculatedMs = Date.parse(dashboard.planning?.calculated_at ?? "");
  const calculatedAge = Number.isFinite(calculatedMs) && calculatedMs <= now ? ageSentence(language, (now - calculatedMs) / 1000) : unknown;
  row("daily.calculated", `${calculated ?? unknown} · ${t("daily.age")}: ${calculatedAge} · ${historical === true ? t("daily.historical") : historical === false ? t("daily.inProcess") : unknown}`);
  root.append(grid);
  const health = doc.createElement("div"); health.className = "spotnav-daily-health";
  const title = doc.createElement("strong"); title.textContent = t("daily.health.title"); health.append(title);
  const key = healthKey(state, observedAt, failed, busy, now);
  const message = doc.createElement("p"); message.dataset["health"] = key;
  message.textContent = t(key); health.append(message);
  // Operator precedence can hide an additional independent problem (for example,
  // an unsupported identity while offline, or a mismatch during uncertainty).
  const additional: TranslationKey[] = [];
  if (state?.supported === false && key !== "daily.health.unsupported") additional.push("daily.health.unsupported");
  if (state?.operator?.state === "offline" && key !== "daily.health.offline") additional.push("daily.health.offline");
  if ((state?.operator?.state === "mismatch" || state?.verification?.reason === "limits_or_transitions_differ") && key !== "daily.health.mismatch") additional.push("daily.health.mismatch");
  for (const extra of additional) {
    const line = doc.createElement("p"); line.dataset["health"] = extra; line.textContent = t(extra); health.append(line);
  }
  const evidence = doc.createElement("small");
  const observed = observedAt === null ? unknown : time(new Date(observedAt).toISOString(), language, zone) ?? unknown;
  const sent = time(state?.sent_at, language, zone) ?? unknown;
  const read = time(state?.effective?.fetched_at, language, zone) ?? unknown;
  const ack = state?.ack === "Accepted" || state?.ack === "Rejected" ? state.ack : unknown;
  const stale = observedAt !== null && (now < observedAt || now - observedAt > STATUS_MAX_AGE || failed);
  evidence.textContent = `${t("daily.observed")}: ${observed}${stale ? ` (${t("daily.health.stale")})` : ""} · ${t("daily.sent")}: ${sent} (${ack}) · ${t("daily.readback")}: ${read}. ${t("daily.separate")}`;
  health.append(evidence); root.append(health);
  return root;
}
