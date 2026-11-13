// Presentation and input validation only. Status and charger operations remain backend-owned.
export function chargeNowSelection(choice, custom, now = Date.now()) {
  if (choice === 'custom') {
    const end = Date.parse(custom || '');
    if (!Number.isFinite(end) || end <= now || end - now > 48 * 3600000) {
      return {error:'Choose a valid future end time within 48 hours.'};
    }
    return {end, options:{end_time:new Date(end).toISOString()}};
  }
  const minutes = Number(choice);
  if (![30,60,120,180].includes(minutes)) return {error:'Choose a valid duration.'};
  const end=now + minutes * 60000;
  // Send the exact time the user confirmed, not a duration restarted after the dialog.
  return {end, options:{end_time:new Date(end).toISOString()}};
}

export function chargeNowPrice(info) {
  if (!Number.isFinite(info?.current_price) || typeof info?.currency !== 'string') return 'Current price: unavailable.';
  const price = `${info.current_price} ${info.currency}/kWh`;
  const basis = info.price_basis === 'configured_variable_cost' ? 'configured variable cost' : 'published price';
  const cap = info.above_cap === true ? 'This exceeds your cap.' : info.above_cap === false ? 'This does not exceed your cap.' : 'Cap comparison unavailable.';
  return `Current price: ${price} (${basis}). ${cap}`;
}

export function chargeNowBlocker(panel, dashboard, state) {
  const info=state?.charge_now;
  if (!panel.connected || panel._hass?.connected === false) return 'Home Assistant is disconnected.';
  if (panel._hass?.user?.is_admin !== true) return 'Administrator permission is required.';
  if (!dashboard || !panel.chargeDashboardFresh(dashboard)) return 'Dashboard observation is unavailable or stale.';
  if (!panel.chargeStatusFresh()) return 'Morek status is unavailable or stale; refresh observations.';
  if (!info || !['active','inactive'].includes(info.state)) return 'Charge Now is unavailable on this backend.';
  if (info.state === 'active' && (!Number.isFinite(Date.parse(info.intent?.end || '')) || Date.parse(info.intent.end) <= Date.now())) return 'The reported override end has passed or is invalid; refresh status before acting.';
  if (!state.supported) return `Charger identity or connection unavailable: ${state.reason || 'unsupported'}.`;
  if (state.operator?.state === 'offline') return 'Charger is offline; reconnect before requesting a change.';
  if (state.ownership?.recorded_owner !== 'morek_schedule' || state.ownership?.completion_authorized !== true) return `Schedule ownership unavailable: ${state.ownership?.blockers?.[0] || 'authorization required'}.`;
  if (state.schedule_pause?.intent === 'pause_until_resumed' || dashboard.control?.pause?.choice || state.schedule_pause?.request === 'stop_pending') return 'Charging is paused or Stop is pending. Resume Auto first.';
  if (panel.chargeBusy || panel.chargePending?.has(panel.charger) || panel.autoBusy || panel.morekBusy || panel.settingsBusy) return 'Another request is in progress.';
  if (panel.chargeExpected?.has(panel.charger)) return 'Waiting for fresh status confirming the recorded intent; do not repeat the request.';
  if (panel.chargeUnknown?.has(panel.charger) || panel.autoUncertain || panel.morekUncertain || info.uncertain !== false) return 'A request or profile outcome is unknown; do not retry blindly.';
  return '';
}

export function chargeNowStatus(state, fresh) {
  const info=state?.charge_now;
  if (!fresh || !info) return 'Charge Now status unavailable or stale.';
  const active=info.state === 'active';
  const end=Date.parse(info.intent?.end || '');
  const intent=active && Number.isFinite(end) && end <= Date.now() ? 'The reported override end has passed; awaiting fresh status.' : active ? `Charge Now requested until ${Number.isFinite(end) ? new Date(end).toLocaleString() : 'unknown end'}. Plugging in later does not extend this end.` : 'Charge Now is not active.';
  const transitions=info.intended?.chargingSchedule?.chargingSchedulePeriod;
  const intended=active ? `Intended schedule: ${Array.isArray(transitions) ? `${transitions.length} current-limit transitions` : 'unavailable'}.` : '';
  const attempt=info.outcome;
  const evidence=info.uncertain ? 'A schedule outcome is uncertain and may have applied.' : attempt?.state === 'accepted' ? `Schedule sent; ACK ${attempt.ack || 'accepted'}.` : attempt?.state === 'rejected' ? `Schedule rejected (${attempt.ack || 'rejected'}).` : active ? 'Schedule request pending or not confirmed.' : 'Auto reconciliation may still be pending.';
  const readback=state.verified && state.verification_target === 'charge_now' ? 'Effective limits matched within reported coverage.' : 'Effective limits not confirmed for this override.';
  const describe=code=>({too_many_blocks:'Too many windows for the charger profile; change the plan or override end.',invalid_plan:'Windows cannot be represented within the charger horizon; review the plan and end time.',charger_unavailable:'Charger unavailable; reconciliation waits for reconnect.',upload_rejected:'The charger rejected the schedule; review Morek status.',upload_uncertain:'The upload may have applied; do not retry blindly.',current_must_be_16:'The configured Morek plan current must be 16 A; review settings.',protection_conflict_unresolved:'A protection conflict blocks dispatch; review Morek diagnostics.',no_current_plan:'No usable Auto plan; the override has a bounded end and Auto will retry.'})[code] || code;
  const reason=info.reason || state.reconciliation?.reason;
  const degraded=info.degraded ? ` Auto handback degraded: ${describe(info.degraded)} (${info.degraded}).` : '';
  return `${intent} ${intended} ${evidence} ${readback} ${reason ? `Reconciliation: ${describe(reason)} (${reason}).` : ''}${degraded} Session-start request: ${state.readiness?.session_start?.state || 'unknown'}; reported session and measured charging: unknown. ACK or readback does not prove charging.`;
}
