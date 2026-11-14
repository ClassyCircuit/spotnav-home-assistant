# Initialize the SpotNav Enhanced coordinator

Read `AGENTS.md`, this file, `docs/charging-dashboard-roadmap-active.md` (the only work queue; the
old large roadmap is archived under `docs/archive/` and `docs/charging-dashboard-roadmap.md` is a redirect) and
`docs/morek-development-handoff.md`; then inspect Git status, recent commits and
`custom_components/spotnav/manifest.json`. You are taking over as coordinator and
reviewer. The user often asks you to review another LLM's report and supply a
copyable implementation prompt, but may also directly ask you to implement a fix.
Follow the actual request rather than automatically starting new work.

## Current handoff — 2026-11-14

- Current source manifest is **2.5.143** after Stage 15 implementation. The coordinator committed and
  pushed each reviewed substage under the user's authorization. Recheck `git log` and `git status` for the
  exact current HEAD; a push does not install or restart Home Assistant.
- **Active roadmap items 1–15 (Stage 15) are locally implemented and coordinator-reviewed.** Stage 16
  (today-only published opportunities while tomorrow is missing) is now authorized and takes priority:
  16.1 planning, then 16.2 guarded dispatch/UI, each fresh Claude Sonnet 5.5 medium, review and commit/push.
  Later work is Stage 13.1–13.4, then 7 and 8, only when requested. The active roadmap is the only queue;
  §9 retains open decisions D1–D3, unrun acceptance and user-owned work. Do not reassign completed stages.
- **Fast focused tests only.** No full frontend/backend suites, browser/Playwright or global isolated runner.
  Use named files or selected cases with a short command timeout; stop slow checks and report them unrun.
- Stages 6.1–6.3, 9.4–9.5, 10 and 14 are locally implemented with mocked checks.
  Stage 6 captures genuine available measurements and exposes a history API, not a
  history dashboard; observed sources, cadence and flow thresholds remain unverified.
  Stage 9.5's user-accepted exception is that an ambiguous undispatched Resume after
  a crash needs a fresh Resume; preserve Stop and genuinely unknown outcomes.
- Stage 5.7b2 monitoring is locally implemented. 5.7b3 remains partial: focused
  mocked checks passed but browser acceptance and the HA-plugin suite were not run.
  The user owns 5.1 visual approval and 5.8 installation/live testing. Stages 7, 8 and 13
  remain later features; Stage 15 is locally complete. **Stage 11 is
  superseded; its scope is implemented in Stage 15.9–15.11**; umbrellas 5.4 and 5.6 are closed
  as locally implemented. Follow the user's chosen priority and the queue.
- A prior read-only HA investigation found an accepted automatic schedule but a
  plugged-in connector in Preparing without a confirmed transaction. A listener
  thread error left the session without its connection token. Local 2.5.126 fixes
  the callback and plug-in/session recovery; 2.5.128 adds a session-readiness card
  and warnings. These changes are committed and pushed, not independently verified
  as installed or physically working. Recheck live state only within current user
  authorization; never infer charging from an accepted request or readback.
- The user wants charge control automatically authorized on plug-in even if price or
  SOC is stale. Keep explicit Pause/Stop, electrical protection, connector identity,
  ownership and genuinely pending/unknown dispatched operations intact. A retained
  schedule is not proven effective; an accepted start is not a transaction or flow.
- **Stage 15 is locally complete with mocked checks (2.5.129–2.5.143), not deployed or physically verified.**
  It adds the configurable 10% reserve, local link monitor, read-only reconnect schedule checks, guarded
  repair and reboot recovery, connection-aware status, late-energy evidence, robust median learning,
  learned-estimate display/reset, and measured behind-plan checks. Stage 14 guards remain binding.
  Repair is enabled in source: repeated clean mismatches, fresh confirmation at the wire boundary,
  active-charge deferral, persisted budget and post-repair escalation. Unknown writes are never retried.
  No mandatory periodic OCPP readback. A reconnect alone is not a reboot.
- Learning uses validated completed plug-ins: three agreeing votes to lengthen, five to shorten, bounded
  median estimates before the separate reserve. Missing proof means defaults; a healthy active window's
  used power is frozen. Late receipt-only register rises cannot certify a prior session's total and remain
  unassigned/uncertain. Known harness limits and unrun checks are in the development handoff.
- The user confirms the BMW stops at its own configured 80% limit. This is an agreed operating assumption;
  SpotNav does not set that limit. Do not reopen it. Stage 11 is superseded, not a separate future queue.
- E1/E2 evidence tasks and 5.1 visual approval / 5.8 installation and physical validation remain user-directed.
- The user prefers stable charging: routine sensor updates should not interrupt an
  active window or spam uploads. Stage 14 documents the agreed interruption thresholds,
  plug-in recalculation, schedule deduplication and conservative uncertainty rules.
- Stage 10's Charge Now uses a fixed end, can be set before plug-in, defaults to one
  hour with 30/60/120/180 minutes and custom end, works with unknown price/SOC, and
  asks for Resume if paused. Pause cancels the override; Return to Auto can continue
  charging. Stage 10.3 plans available cheap slots while tomorrow's prices are
  missing, with bounded minimum-SOC urgency. See the archived roadmap (Stage 10) for detailed limitations.
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
  unless asked, commit or push without authorization, or discard other people's
  changes. When explicitly requested, the established workflow uses a fresh Claude
  Sonnet 5.5 medium delegate per substage in the shared worktree, coordinator review,
  targeted corrective prompts and commit/push when authorized. Follow the actual
  request and available orchestration instructions. The user chooses deployment and
  hardware tests. Preserve any in-progress work.
- The user prefers focused fast tests over browser/Playwright or large suites unless
  explicitly requested. The Windows HA pytest plugin has had an `fcntl` limitation;
  isolated runners under `tools/` test actual modules with mocked HA/OCPP boundaries.
- Keep the integration domain `spotnav` and its directory unchanged. Follow AGENTS.md
  for private-data handling, read-only diagnostics, precise operational approval,
  manifest bumps, frontend build and committed distribution verification.

## Delegation workflow and task briefs

Use this workflow when the user asks for delegation; do not spawn agents solely
because this file describes it. The user's current instructions and the active
orchestration rules take precedence over these preferences.

1. **Choose a bounded task.** Assign one roadmap substage at a time, in dependency
   order, unless the user specifies another scope. Use a fresh agent for each new
   substage so its context stays focused. The established preference when requested
   has been Claude Sonnet 5.5, medium effort, shared isolation on the current
   worktree and branch. Do not create a worktree unless the user asks for one.
2. **Write a self-contained brief.** Tell the agent to read `AGENTS.md`, this
   handoff, the development handoff, and the relevant roadmap section; inspect Git
   and existing implementation first; preserve unrelated and uncommitted work. State
   the desired behavior, acceptance cases, scope boundaries, relevant decisions and
   dependencies. Require actual production wiring, not just groundwork or mock-only
   helpers, and favor simple fixes over a second controller or speculative features.
3. **Set the operational boundaries.** No live HA access, charger commands, HA
   changes, restart or deployment without the user's specific authorization. For
   authorized diagnostics, start read-only, verify the intended API host before using
   a token, keep secrets and household data out of output and Git, and distinguish
   intent, acknowledgement, effective readback, transaction and measured charging.
   Preserve Pause/Stop, ownership, identity, electrical protection and genuine
   uncertain dispatched outcomes. Do not clear profiles or blindly retry unknowns.
4. **Require focused validation.** Ask for fast, meaningful tests at real module and
   guarded production boundaries, including the important failure, restart and race
   cases for the change. Skip expensive browser, Playwright, broad or long-running
   suites unless the user asks. Report precise unrun checks and harness limitations;
   do not delete a whole suite merely because a local harness fails. Follow AGENTS.md:
   integration/card changes require a manifest version bump, `npm run build` and
   `npm run check-dist` from `frontend/`, with committed distribution artifacts.
5. **Require a concise completion report.** Ask the agent to state what changed,
   what passed or failed, unrun checks, known limits and whether live behavior was
   verified. Update the roadmap and development handoff truthfully; mark a substage
   partial if its required work or acceptance is actually incomplete. Do not claim
   physical charging from mocks, a schedule, an ACK or a readback.
6. **Review and finish.** Wait for the agent's result, then do a quick independent
   review focused on important behavior, safety and acceptance gaps, not nitpicks or
   overengineering. Give a targeted corrective task when needed and review again.
   Commit and push only when the user has authorized it; for a multi-substage request,
   honor the user's requested commit/push cadence before starting the next fresh agent.
   Report the completed work, checks and material limits, then follow the user's
   requested stop point. If a requested provider is unavailable, report that rather
   than silently switching models.

## Transfer and documentation

Check Git before assuming these documentation changes are committed. A different PC
cannot see local-only work unless it is transferred.
Do not assume its environment variables, paths, Git state or HA access are the same.
Historical entries in the archived roadmap and the handoff record prior states; current top-level
summaries, latest checked substages, current source and Git status take precedence.
