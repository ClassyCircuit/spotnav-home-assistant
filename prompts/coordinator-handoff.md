# Initialize the SpotNav Enhanced coordinator

Read this entire file, then inspect the repository. You are taking over as the
**coordinator/reviewer**. Another LLM implements your prompts; the user passes its
reports back to you. Do not automatically implement features on initialization.

**Snapshot: 2026-11-10, source version 2.5.30.** Recheck Git, manifest, roadmap
and source on arrival. Source version, installed HA version and physical charger
state are separate facts; no live state was checked for this handoff.

## Immediate situation and next action

- Stages **0 and 1.1–1.3** are implemented. Stages **2.1–2.3, 3.1–3.3 and
  4.1–4.3** are implemented and reviewed as **unarmed software groundwork**,
  not as a claim that autonomous Morek control is safe or active.
- The outgoing coordinator reviewed the 4.3 source and independently ran the
  isolated suites: **492 passed, 1 deselected, 2 warnings** and **26 passed,
  6 warnings**. The implementer reports 21 focused panel tests, frontend build,
  check-dist, type-check, targeted Ruff and diff check passed. These are not full
  HA integration or physical tests; Windows HA pytest collection is blocked by
  the Unix-only `fcntl` dependency.
- **Next substage: 5.1 — layout and shared components.** Assign one bounded
  implementation session: an evcc-inspired desktop/mobile browser prototype
  using sample data, shared tokens/controls and HA Sections composition. Seek
  user visual approval. Inspect existing frontend patterns first. Do not build a
  second dashboard, activate Morek mode, or implement the whole Stage 5.
- Roadmap Stage 6.1 genuine-history source inventory may also start early if the
  user prefers; do not fabricate measurements. Ask before generating images if
  an image tool is desired but not requested. The user chooses hardware tests.
- No deployment, HA restart, live charger operation, push or other remote action
  is authorized by this handoff. User-facing workflow expects the next coordinator
  to review and provide one copyable prompt when asked, not implement it itself.

## How to coordinate

- Be decisive and pragmatic: the user wants the **golden middle**, not nitpicking,
  overengineering or repeated open-ended audits. Review actual source/tests for
  serious problems and group bounded follow-up fixes into the next substage when
  sensible. Do not hide failures or ignore safety.
- Assign **one roadmap substage per session** with scope, behavior, tests,
  exclusions, deliverable and stop-for-review boundary. A new code path is not
  automatically a reason to stop; resolve concrete missing decisions explicitly.
- Distinguish checks you independently ran from implementer reports. Isolated
  actual-module tests with stubs and mocked HA/OCPP/storage are not full HA tests
  or physical proof. Do not replace actual module tests with extracted code.
- Preserve all user work. No unrequested commits, pushes or deployments; never
  reset/discard unrelated changes. Do not spawn subagents unless authorized.
- If the user asks for a prompt for a new LLM, make it self-contained with its
  required reading and safety boundaries. Keep reviews and final answers brief.

## Arrival checklist and authoritative documents

1. Run `git status --short --branch`, inspect recent commits and
   `custom_components/spotnav/manifest.json`. The previous workspace was
   `D:\spotnav-home-assistant` on Windows; do not assume the new PC uses that path.
2. Read `AGENTS.md` and `docs/charging-dashboard-roadmap.md`. The numbered
   checklist at the top of the roadmap is authoritative. Some older overview or
   historical text may lag; trust current source and recent version notes, and
   correct stale current pointers when doing relevant documentation work.
3. Read `docs/morek-development-handoff.md`, especially **2.5.30** and recent
   2.5.24–29 entries; read `docs/morek-schedule.md`. The older
   `docs/morek-execution-audit.md` is a historical writer inventory, not a new
   standalone work queue. Consult architecture docs and source as needed.
4. At the final handoff check, `feat/dashboard` and its remote both pointed to
   `f2a69181` (4.3). This handoff edit is **uncommitted** and will not appear on
   another PC until the user explicitly arranges transfer or commits/pushes it.
   Recheck Git and do not assume installed HA contains this source version.
5. The handoff is documentation only. No manifest bump/build is needed for this
   handoff itself. For integration/card changes, `AGENTS.md` requires a manifest
   bump, `npm run build` in `frontend/`, and `npm run check-dist`; bundled
   `custom_components/spotnav/www/` artifacts are committed.

## Product direction and roadmap

- Build **one Home Assistant charging dashboard with multiple coordinated cards**,
  not a second stock-card dashboard, solar UI or decorative whole-home flows.
  Use evcc-inspired styling; Apache ECharts is the selected chart library. Show
  important information by default and stack the same cards on mobile. No new
  React/Vue app is required.
- Show prices, connection, SOC/target, minimum SOC, cap, ready-by, measured
  power, next window, plan energy/cost, health and missing data. Clearly separate
  **proposal / sent ACK / effective readback / actual measured charging**.
- Price policy: charge toward the target with at/below-cap energy; above-cap
  energy is allowed only for the cheapest feasible deficit needed to reach the
  editable minimum SOC by ready-by. Typical 40% is not a forced migration default.
  The cap is not a universal limit on manual actions or protection.
- Measured history must come from genuine Morek/OCPP measurements/events or
  validated BMW **Bavarian CarData**, never inferred from a planned schedule.
  Source availability and BMW history capability remain unverified.
- Stages 5–9 remain: **5.1 layout, 5.2 overview, 5.3 plan controls; 6.1 source
  inventory, 6.2 capture/provenance, 6.3 queries/retention; 7.1 ECharts prices,
  7.2 interactions, 7.3 aligned tracks; 8.1 yesterday, 8.2 costs, 8.3 savings;
  9.1 accessibility/themes, 9.2 responsive integration, 9.3 installation/docs.**
  Check the roadmap for detailed acceptance criteria.
- Keep Home Assistant domain `spotnav`, `custom_components/spotnav/`, and display
  name **SpotNav Enhanced** unchanged. No separate overnight/hardware-test stage.

## Existing implementation and crucial limitations

### Planning and legacy execution

- Saved cap/basis and separate minimum-ready-by SOC flow through the existing
  settings/API. Cheapest-price Auto uses fresh vehicle facts, strict capped
  windows and policy stand-down; capped solar/hybrid is explicitly unavailable.
  Missing prices do not authorize unpriced capped charging. Dashboard and preview
  share policy explanations; settings, relevant SOC and price changes replan in
  the backend without a browser. Preserve uncapped behavior and immediate-SOC-floor
  and person-owned semantics.
- Stages 2.1–2.3 added connector-aware Auto and ordinary adapter guards, guarded
  manual fallbacks/handback, startup/restore checks and mocked regressions. **This
  is not complete activation-ready isolation.** Regulator current and explicitly
  classified protection stops remain permitted; they can compete with schedule
  ownership and must never be silently suppressed. External HA/OCPP writers are
  outside SpotNav. Person Stop intent and household protection must be preserved.
- A process-local admission drain is an **unwired future seam**, not a producer
  shutdown, durable transition or activation. No implementation may assume a
  dispatched command can be recalled. Follow existing lock ordering; avoid
  recursive connector admission and acquiring controller/assignment locks inside
  the connector lock.

### Morek schedule and health

- Manual preview/Send and the backend worker use shared fixed-time schedule intent
  and fingerprints, including the remaining portion of an active displayed window.
  The worker listens to backend planner publications, coalesces changes, rechecks
  identity/current intent and reconciles at startup/control-entity availability
  changes. Reconnect coverage beyond that entity is unverified.
- **Production `owned_profile` admission is unconditionally unarmed.** No
  autonomous profile dispatch or activation API is enabled. Functional worker
  tests use simulated authorization and mocks. Do not weaken the gate or describe
  the roadmap as active automatic uploads.
- Manual Send, selective removal and the worker share connector serialization and
  durable intent/attempt/ACK/readback evidence. An unknown/cancelled/interrupted
  action remains uncertain across restart and blocks sends; no reset or automatic
  retry exists. Readback or selective removal does not resolve an earlier unknown
  upload. Preserve manual admin, pause, identity, revision, preview and selective
  removal safeguards.
- Verification compares only the **observable remaining effective schedule**,
  with reported coverage, bounded read-only follow-ups and 90-second drift
  tolerance; ambiguous boundaries or no remaining transitions stay unverified.
  Attempt, planner, identity and lifecycle checks reject superseded results.
  A match is not installed-profile inventory, transaction authorization, actual
  power flow, or proof of elapsed windows.
- The current status API/panel exposes operator states, blockers and supervised
  recovery/downgrade guidance. It is not the Stage 5 dashboard redesign. An
  existing stored final **0 A** may persist after the last window, restart or
  downgrade; removing a profile can permit charging. Generic `ocpp.clear_profile`
  may clear other profiles and must never be treated as selective cleanup.

### Activation blockers and known migration constraints

- Actual schedule-mode activation requires resolved durable ownership transitions,
  lost-document recovery, electrical/load protection, transaction authorization,
  retained-profile/safe-exit policy and competing writer questions. Do not arm
  until deliberately designed, reviewed and authorized. A profile limits current;
  it does **not** authorize a new charging transaction.
- In the current **unarmed** release, a wholly missing ownership document is treated
  as first-use legacy migration. It cannot distinguish first use from lost state;
  resolving that ambiguity is mandatory before an activation-capable release. A
  missing binding in an existing document fails closed. A lost outcome document
  has a similar ambiguity. An undiscovered duplicate can only be blocked after
  discovery; offline connector-1 aliases can remain unresolved and blocked.
- Historical Morek target: station **3020002509120029**, connector **1**, owned
  profile **42001**, stack **1**. Historical uploads/readbacks had drift and
  mismatches; an Accepted reply or matching composite is not physical proof.
  No automatic priority escalation or blanket clear.

## Safety, access and tests

- Start read-only. No profile send/clear, charge start/stop, HA restart, deployment,
  share modification or charger configuration without the user's specific approval
  for that exact operation. Never disable household protection or raise limits.
- Never put credentials, auth responses, private household data or raw HA logs in
  Git, output or chat. Follow `AGENTS.md` and the development handoff before any
  attempted HA access. The historical API host `http://homeassistant.local/` and
  an SMB share are time- and machine-specific; an SMB share is not proof of API
  connectivity. Use the `homeassistant` environment variable only in memory after
  verifying the intended API host; never print it or follow credentialed redirects.
- Portable repository harness commands, if dependencies are available:
  `python tools/run_isolated_planning_tests.py` and
  `python tools/run_isolated_lifecycle_tests.py`. At this snapshot the outgoing
  coordinator independently got **492 passed, 1 deselected, 2 warnings** and
  **26 passed, 6 warnings**, respectively. Full HA pytest collection remained
  blocked on Windows by the plugin's `fcntl`; rerun on a supported host when
  available. Do not install or modify environments merely to hide this limitation.
- The implementer's reported 4.3 frontend checks are recorded in the recent
  development handoff. No physical testing was performed for these changes.

## Useful code pointers

Paths under `custom_components/spotnav/`: `planning/auto_controller.py`,
`planning/auto_settings.py`, `planning/planner.py`, `api/dashboard.py`,
`api/plan_preview.py`, `api/morek_schedule.py`, `execution/auto_execution.py`,
`execution/controller.py`, `execution/command_admission.py`,
`execution/execution_ownership.py`, `execution/morek_worker.py`,
`execution/morek_outcomes.py`, `execution/charger_handback.py` and
`site/site_capacity_controller.py`. Frontend entry points include
`frontend/src/card.ts` and `frontend/src/morek-view.ts`; inspect existing card,
styling and tests before proposing 5.1. Relevant tests include
`tests/test_morek_schedule.py`, `tests/test_morek_worker.py`,
`tests/test_morek_outcomes.py`, `tests/test_stage_23_lifecycle.py` and
`frontend/test/morek-view.test.ts`.
