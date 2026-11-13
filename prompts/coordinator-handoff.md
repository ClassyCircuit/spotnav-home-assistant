# Initialize the SpotNav Enhanced coordinator

Read `AGENTS.md`, this file, `docs/charging-dashboard-roadmap.md` and
`docs/morek-development-handoff.md`; then inspect Git status, recent commits and
`custom_components/spotnav/manifest.json`. You are taking over as coordinator and
reviewer. The user often asks you to review another LLM's report and supply a
copyable implementation prompt, but may also directly ask you to implement a fix.
Follow the actual request rather than automatically starting new work.

## Current handoff — 2026-11-13

- At this handoff `main` was clean at commit `ebee12b5` before these documentation
  edits; source manifest was 2.5.98. Recheck on the new PC. The user says Stage 10
  is done: roadmap 10.1, 10.2 and 10.3 are checked for local implementation and
  mocked verification. Do not reassign them as unfinished or claim live success.
- Stage 9.4 (native HA Core logging and filtered viewer) and 9.5 (automatic recovery
  and visible failures) are open. Stage 5.7b2 (genuine live charging/health binding)
  and 5.7b3 (acceptance/release handoff) remain open. Follow the latest roadmap and
  the user's chosen priority, not historical version notes or a predetermined task.
- The user wants routine faults to recover automatically: retry definite failures
  with bounded cooldown, re-evaluate on reconnect/price availability, use the approved
  clean-start policy for missing history, and show genuine blockers prominently.
  Preserve explicit Pause/Stop, electrical protection, connector identity, and
  recorded pending/unknown dispatched outcomes. Never silently clear uncertainty or
  assume a composite schedule lists installed profiles. Stage 9.5 owns this review.
- A read-only live check found `resume_requires_confirmation` blocking both Auto and
  Charge Now even though ownership was authorized and a Resume-associated attempt
  was accepted. Source 2.5.98 locally recovers settled Resume evidence; interrupted
  Resume without matching settled evidence can still require confirmation. This fix
  has focused mocked tests but was not deployed or validated against the charger.
  The exact installed version and present live state must be rechecked if needed.
- Stage 10's Charge Now uses a fixed end, can be set before plug-in, defaults to one
  hour with 30/60/120/180 minutes and custom end, works with unknown price/SOC, and
  asks for Resume if paused. Pause cancels the override; Return to Auto can continue
  charging. Stage 10.3 plans available cheap slots while tomorrow's prices are
  missing, with bounded minimum-SOC urgency. See roadmap for detailed limitations.
- The user previously asked about a standalone HA app. No migration is approved.
  OCPP currently uses integration internals in places, so app migration would first
  need an API feasibility audit. Do not assume independent operation of HA services.

## Coordination preferences

- Be pragmatic and decisive. Before giving a prompt, settle genuine product choices
  with numbered questions and recommended answers. The user dislikes LLM runs that
  stop at status-only groundwork or repeatedly ask the same questions. Give a focused,
  actionable prompt and require production wiring and fast tests where appropriate.
- Do not label an accepted OCPP response or matching effective readback as physical
  charging, or readback as an inventory of profiles. Be honest about limitations;
  do not promise a system can always recover from every unknown physical state.
- Do not repeat completed work, infer authorization for live commands, spawn agents
  unless asked, commit or push, or discard other people's changes. The user chooses
  when to deploy and perform hardware tests. Preserve any in-progress work.
- The user prefers focused fast tests over browser/Playwright or large suites unless
  explicitly requested. The Windows HA pytest plugin has had an `fcntl` limitation;
  isolated runners under `tools/` test actual modules with mocked HA/OCPP boundaries.
- Keep the integration domain `spotnav` and its directory unchanged. Follow AGENTS.md
  for private-data handling, read-only diagnostics, precise operational approval,
  manifest bumps, frontend build and committed distribution verification.

## Transfer and documentation

These documentation changes are uncommitted until the user explicitly transfers or
commits them. A different PC cannot see local-only work unless it is transferred.
Do not assume its environment variables, paths, Git state or HA access are the same.
Historical entries in the roadmap and handoff record prior states; current top-level
summaries, latest checked substages, current source and Git status take precedence.
