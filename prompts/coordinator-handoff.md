# Initialize a SpotNav Enhanced coordinator

Use this file to start a new coordinating LLM session. You are the **coordinator
and reviewer**, not the implementation LLM. Read this entire file, then inspect
the repository before choosing the next task. Do not implement a feature merely
because you have been initialized.

Snapshot: **2026-11-09**. This is a reusable handoff, not proof of current Git,
deployment or hardware state. Update its progress section when handing off again.

## Role and working agreement

- The user gives your bounded prompts to another LLM, usually continuing the same
  implementation session. That LLM implements; you inspect its actual changes,
  review risks and tests, and provide the next continuation prompt.
- The user explicitly rejected a whole Stage 1 assignment as too large. Keep
  sessions small, with coordinator review between slices. Split further when
  call-chain complexity warrants it, but avoid repeating audits instead of making
  concrete, independently testable progress.
- When asked “quick review and next prompt,” read the actual source/diff and
  relevant tests/docs. Do not merely endorse the implementer's summary. State
  what you checked yourself versus tests only reported by the implementer.
- Provide one copyable continuation prompt for the same LLM: scope, acceptance
  criteria/tests, exclusions, deliverable and explicit stop-for-review boundary.
- Preserve unrelated/user work. Inspect Git status before edits; no resets,
  discards or unrequested commits, pushes, deployment or live changes.
- Do not spawn subagents unless explicitly authorized by the user or applicable
  repository instructions.
- Keep user-facing reviews concise, but include enough detail in prompts to avoid
  unsafe shortcuts. Open questions must not silently become implementation policy.

## Repository and reading order

Workspace: `C:\Code\spotnav-home-assistant` (Windows/PowerShell).

Read these in order, progressively rather than dumping the repository:

1. `AGENTS.md` — mandatory safety, naming and version/build instructions.
2. `docs/charging-dashboard-roadmap.md` — authoritative forward requirements,
   dependencies and acceptance criteria. Read the Stage A blocks and policies.
3. `docs/morek-execution-audit.md` — most current execution findings and incremental
   implementation notes. Later sections supersede earlier historical statements.
4. `docs/morek-development-handoff.md` — manual baseline, HA access and wire
   investigations. Its old version/branch/deployment statements are historical.
5. `docs/morek-schedule.md` — existing manual Morek behavior.
6. As relevant: `docs/architecture-state.md`, `docs/ocpp.md`, `docs/target-soc.md`,
   `docs/prices.md` and source/tests for the slice under review.

Run `git status --short --branch`, inspect recent commits and the current manifest.
Diffs may be clean because the user/implementer committed work between sessions;
inspect commit changes/source instead of assuming nothing happened.

## Product goal and non-negotiable requirements

- One modern Home Assistant charging dashboard containing multiple coordinated
  cards; no separate stock-card dashboard and no solar UI. evcc-inspired styling;
  Apache ECharts selected for later frontend work.
- Visible operational information and zoomable Nord Pool prices. Distinguish
  proposed plan, sent profile, reported effective limits and measured charging.
- Autonomous backend planning and Morek schedule uploads, independent of an open
  browser. Changes to prices, SOC, settings and ready-by time must recalculate and
  resend when effective wire intent changes. Retain manual Send/Refresh debugging.
- Exclusive ownership for the physical Morek connector: legacy SpotNav must not
  compete with stored schedules through live start/stop/current commands. Hiding
  controls or pausing Auto is not isolation. No hidden fallback to legacy control.
- Configurable optional **soft price cap**. Above-cap energy is allowed only for
  the cheapest feasible deficit needed to reach configurable **minimum SOC**
  (typically 40%) by ready-by. Higher normal target SOC uses eligible cheap slots
  only. Minimum already reached + all expensive prices means no extra charging.
  Validate minimum <= target, units/price basis, partial blocks and infeasibility.
  Use the existing planner/settings, not a second optimizer. Existing immediate
  minimum-SOC actuator is NOT this ready-by optimizer.
- Historical charging must come from genuine Morek/OCPP measurements/events or
  validated BMW Bavarian CarData records, never inferred scheduled windows.
  Investigate actual history versus live-only telemetry; BMW capability remains
  unverified. Distinguish home/public sessions, battery/grid energy, provenance,
  timestamp precision and overlapping sources. Sparse SOC is not exact history.
- No separate overnight-testing roadmap stage. The user chooses hardware testing
  timing. Automated regression remains required; do not claim physical proof.
- Preserve integration domain `spotnav` and display name **SpotNav Enhanced**.

## Safety and authorization

- Implementation/review permission does not authorize live hardware experiments.
  No profile sends/clears, charging start/stop, charger configuration changes,
  autonomous activation, HA restart, deployment or live-share edits without the
  user's specific approval for that concrete operation.
- Never disable household electrical protection or invent an emergency bypass.
  Ordinary and regulator stop/current sinks overlap; `urgent` is NOT a reliable
  safety classification because manual stops can also be urgent.
- Schedule mode must remain unavailable/unarmed until isolation and safety,
  transaction authorization and mode-transition policies are resolved. A current
  limit profile does not itself authorize a newly plugged-in transaction.
- Never expose credentials, raw household logs or auth responses. Environment
  variable `homeassistant` is a token usable as Bearer authentication: use in
  memory only, never print/save/commit its value. Confirm destination first and
  do not follow credential-bearing redirects.
- Historical verified API URL: `http://homeassistant.local/`; port 8123 previously
  refused. `\\HOMEASSISTANT\config` was readable, not authorization to write.
  For authorized read-only diagnostics, see the development handoff. Core logs
  were available through `/api/hassio/core/logs?lines=1000` and WebSocket
  `system_log/list`; `/api/error_log` returned 404. Filter private data in memory.

## Morek wire facts and limitations

- Physical station `3020002509120029`, connector `1`.
- Owned schedule profile ID `42001`; production stack level `1`.
- No automatic priority escalation; no blanket profile clearing. Selective
  cleanup must target only the owned ID through the validated existing path.
- Stack 5 was rejected; stack 4 and later stack 1 produced matching windows in
  investigations. Accepted uploads sometimes initially read back as flat 16 A,
  then later matched with drifting seconds. Root cause was not conclusively found.
- Existing verification permits 90 seconds drift and checks duration/coverage.
  CompositeSchedule is effective limits, not installed-profile inventory.
  Accepted ACK or matching readback is not proof of measured energy delivery.
- Manual sending uses actual displayed windows, including shortened final blocks,
  as fixed times. Do not promise stopping at a measured-energy threshold.
- Final 0 A limit remains installed until replacement/removal.
- Earlier physical investigations were unplugged; this is not a permanent state
  fact. Real charging/new-transaction authorization remains unproven.

## Stage sequence

The roadmap remains authoritative; practical implementation is subdivided:

1. A1 ownership/writer/authorization/safety audit.
2. A2.1 persisted unarmed ownership metadata.
3. A2.2 admission foundation, prerequisites, and incremental writer isolation.
4. A2P price-policy settings, then planner policy (separate sessions).
5. A3 reconciliation logic, then reactive triggers (separate sessions).
6. A4 restart/reconnect, bounded recovery and truthful health.
7. A5 and later dashboard/history blocks as documented in the roadmap.

Do not hand the next LLM all these stages at once. Stage A2 is still incomplete.
Autonomous scheduling and the new dashboard are not implemented by these steps.

## Progress at this snapshot

### Historical manual baseline

Versions 2.5.2–2.5.7 added alias resolution, panel/layout fixes, exact wire preview
and fingerprint, text selection, selective cleanup, delayed verification and
shortened displayed-window sending. At 2.5.7, 2,342 frontend tests and 29 isolated
Python cases were reported passing. These are historical, not latest-run results.

### Reviewed incremental implementation

- **A1:** audit completed; writer paths and unresolved policies documented.
- **2.5.8 / A2.1:** versioned persisted ownership document, bound to physical
  station/connector, read-only status, no activation API. Metadata is not control.
- **2.5.9 / A2.2a:** unwired command-admission service; physical-connector locks,
  explicit refusal reasons, identity rechecks and process-local generation tokens.
  No production writer uses it; profile writes remain refused as unarmed.
- **A2.2b initial attempt:** correctly paused without dispatch gates. Starts have
  phase/current writes, reservations and retries before adapter.start. Several
  stops record completion before dispatch. Dispatch-only gating would be unsafe.
- **2.5.10 prerequisite:** startup and charge-control availability transitions use
  serialized late initialization. Connector lock then store lock; identity
  rechecks, duplicate checks, conservative persistence verification. Status stays
  read-only. No actuator admission.
- **2.5.11 identity hardening:** resolver reports match count/protocol and prioritizes
  ambiguity. Classifier distinguishes supported target, positively unrelated
  physical connector, target with unsupported/unknown protocol, and unresolved.
  Unsupported target must never become an unrelated-charger bypass. Coordinator
  inspected these changes and ran Ruff/diff checks, but did not rerun reported
  isolated tests (37 ownership/admission/lifecycle and 37 Morek).

### Newer source discovered while writing this handoff — not yet coordinator-reviewed

At this snapshot Git is clean on `feat/dashboard`, manifest **2.5.12**.
Recent commits: `d8953006` (A2.2b), `326a68a1` (A2.2b start),
`4c1be201` (A2.2a), `1f37a367` (s1.1). Recheck instead of relying on titles.

The audit now documents a **partial ordinary-start extraction**:

- `_start_requested_amps` extracts read-only amp selection but remains AFTER
  phase preparation and possible manual target-stop persistence.
- In-memory `StartAttemptEvidence` / `_last_start_attempt` records possible
  preparation, reservations/retries and adapter dispatch outcomes. Entering a
  preparation function means it MAY have written, not a confirmed physical write.
- `_start_command_locked` still owns the command sequence/outcome handling.
  No admission gate is called; truthful session/unknown-outcome behavior is not
  solved just by adding diagnostic evidence.
- Existing cancellation/exception cleanup can still feed “not executed” despite
  possible physical action. `_last_switch_command` is not restored on false/failure.
- Audit reports nine real-controller characterization cases using a minimal
  standalone HA fixture; these are isolated, not full HA tests. It reports Ruff,
  compilation, frontend build and check-dist passing. Independently review them.

The last coordinator prompt requested a small behavior-preserving ordinary-start
preparation/dispatch/outcome refactor, NOT actual admission or stop integration.
This newer partial work needs review against that scope before choosing a follow-up.

## Critical unresolved boundaries

- Generation invalidation is process-local and not atomic with durable ownership
  mutation. It cannot cancel a command already dispatched.
- Late-init availability listener is not proven OCPP reconnect coverage. Identity
  may resolve without the watched entity transition; entries without a target at
  setup require the existing configuration/reload path.
- Duplicate contenders are in memory and must be rediscovered after restart.
  Do not claim restart-safe exclusive ownership before resolving this.
- Cancelled storage writes may outlive cancellation; initialization conservatively
  stays uncertain in that process instead of racing a retry.
- Starts can restore phases/write current, reserve headroom, mutate target state,
  set pending evidence and arm retries before adapter.start. A gate at the adapter
  alone does not isolate them.
- Several target/need-met/window-end stops record completion before dispatch.
  Target evidence versus completion notification semantics remain undecided.
  Manual stop intentionally retains pause intent even on physical failure; do not
  accidentally remove that intent while making refusal outcomes truthful.
- Regulator protection, current lowering, direct adapter/handback paths, phase and
  deferred current writes, Morek profile writers, mode transitions and startup
  enforcement still need review/integration. Do not claim exclusive control.
- Authorization, independent household safety, mode entry/exit and uncertain
  in-flight outcome policies remain unresolved. Keep hardware mode unarmed.

### Lock order constraint

Existing outer Auto/decision/controller locks precede assignment locks where used;
the connector admission lock comes last at physical dispatch. Existing Morek
profile locks also precede the connector lock. Never hold the connector lock and
then wait for controller/assignment/profile/another connector lock. Never recurse
into connector admission. Wrapping the whole start function in that lock is unsafe
because it acquires assignment locks inside. Releasing the connector lock after
one early check is not an atomic multi-write ownership protocol either.

## Source and test map

- `custom_components/spotnav/execution/execution_ownership.py`: versioned metadata,
  strict reads, durable initialization, conflict/save status.
- `custom_components/spotnav/execution/command_admission.py`: classifier, connector
  locks, admission matrix and generation tokens; currently unwired to actuators.
- `custom_components/spotnav/__init__.py`: setup ordering and metadata lifecycle.
- `custom_components/spotnav/api/morek_schedule.py`: identity resolution, manual
  profile API, preview, upload/readback and ownership status.
- `custom_components/spotnav/const.py`: shared physical Morek identity constants.
- `custom_components/spotnav/execution/controller.py`: start/stop, retries,
  preparation writes, reservations, outcome/session effects and regulator paths.
- `custom_components/spotnav/execution/chargers/`: actual adapter/current/OCPP sinks.
- `custom_components/spotnav/execution/charger_handback.py`: direct start/current
  restoration on deletion outside ordinary controller isolation.
- `custom_components/spotnav/site/site_capacity_controller.py`: protection,
  lowering, pause/resume and restore behavior.
- `custom_components/spotnav/planning/`: existing planner and future price policy.
- `tests/test_execution_ownership.py`, `tests/test_command_admission.py`,
  `tests/test_ownership_lifecycle.py`, `tests/test_morek_schedule.py`: foundation
  tests. Discover the new start-evidence/characterization tests from Git/source.
- Relevant existing controller regressions include `tests/test_core_drives.py`,
  `tests/test_core_failures.py`, plus start preparation/reservation/window retries.

## Test and build constraints

- Full HA pytest cannot collect in the known Windows environment because Unix-only
  `fcntl` is missing. Do not call stubbed/isolated runs the full HA test suite.
- Latest audit says existing WSL Ubuntu has Python 3.12, project needs Python 3.14,
  and Docker daemon was unavailable. Recheck if useful; do not install/change
  environments without authorization merely to conceal the collection blocker.
- Prefer actual controller-method assertions over helper-only or extracted-source
  tests. Report what tests prove and what remains untested.
- Integration/card changes require manifest version bump, `npm run build` in
  `frontend/` and `npm run check-dist`, per AGENTS.md. Documentation-only edits do
  not require a release bump. Do not casually rebuild for review-only work.
- Useful review checks: scoped `python -m ruff check ...`, `git diff --check`,
  relevant regressions. Compilation/build is not behavioral or physical proof.

## First action for the new coordinator

1. Read the files above and reconcile this snapshot with current Git/source.
2. If initialization is all the user asked for, acknowledge readiness and identify
   the active slice; do not launch implementation or live diagnostics.
3. When asked to review the latest implementation, inspect the 2.5.12 partial
   extraction and its tests. State what it actually achieves versus the requested
   preparation/outcome boundary. Diagnostic evidence alone is not that boundary.
4. Choose ONE small next implementation slice based on that review. Do not jump
   to shared stop gates or the entire ownership transition. Preserve unarmed mode.
5. Ask for policy decisions when required; do not assume false, refused, partial
   and unknown physical outcomes can all share a generic “not executed” result.

Maintain this handoff when substantial progress is reviewed so the next coordinator
does not need the original conversation to understand the project.
