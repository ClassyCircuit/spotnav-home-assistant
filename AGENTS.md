# Notes for assistants working in this fork

Read [docs/morek-development-handoff.md](docs/morek-development-handoff.md) before changing the
Morek schedule experiment or trying to reach the user's Home Assistant. It records the current
implementation, hardware limits, outstanding work, deployment/version differences, test status,
and the verified (and unverified) local access paths. The user-facing test procedure is in
[docs/morek-schedule.md](docs/morek-schedule.md).
For the approved future direction and prioritized LLM work blocks, read
[docs/charging-dashboard-roadmap.md](docs/charging-dashboard-roadmap.md): one HA
charging sidebar panel sharing its UI with the local preview, ECharts, and autonomous
Morek schedule-only execution. Guarded automatic upload code exists; consult the latest
handoff and roadmap for open recovery work and do not assume deployed behavior is verified.
It also specifies soft-cap/minimum-SOC planning and genuine measured charging
history. Hardware testing is user-directed, not a separate roadmap stage.

- This is the user's `SpotNav Enhanced` fork. Keep the Home Assistant integration domain
  `spotnav` unchanged, including the `custom_components/spotnav/` directory.
- Do not put credentials, environment-variable values, HA configuration, auth responses, or
  private household data into Git, tool output, logs, or chat. Use the `homeassistant`
  environment variable in memory only after verifying the HA API URL is the intended host;
  a read-only request can then test whether Bearer authentication works, without printing
  the value. An SMB share is **not** proof of API connectivity.
- Start with read-only diagnostics. Do not send an OCPP profile, clear profiles, start/stop a
  charge, restart Home Assistant, or modify the HA share without the user's specific approval
  for that operation. In particular, never treat `ocpp.clear_profile` as a selective cleanup.
- `GetCompositeSchedule` reports effective current limits, not an inventory of installed
  profiles; an accepted upload or a matching readback is not proof of physical charging.
- If you change the integration or card, bump `custom_components/spotnav/manifest.json`, run
  `npm run build` from `frontend/`, and verify `npm run check-dist`. The card and language
  artifacts in `custom_components/spotnav/www/` are committed; generated sources under
  `frontend/src/generated/` are not.
