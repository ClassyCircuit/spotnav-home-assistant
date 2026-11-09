# Initialize the SpotNav Enhanced coordinator

Read this entire file, then inspect the repository. You are taking over as the
**coordinator/reviewer**. Another LLM implements your prompts; the user passes its
reports back to you. Do not automatically implement features upon initialization.

**Snapshot: 2026-11-09, source version 2.5.20.** This file replaces the old handoff
in full. There are no older next-task instructions to follow. Recheck Git/source
on arrival: source, installed HA version and hardware state are different facts.

## 1. Immediate situation and next action

- Stage **0** groundwork and **1.1** settings/API are complete.
- Stage **1.2** is now implemented for **cheapest-price Auto**, including planner,
  fresh vehicle-energy resolution, strict executable windows, policy stand-down
  and dashboard/preview encoding. The temporary blanket cap refusal is removed
  for this supported path. Do not restart the implementation or repeat its slices.
- The implementer's latest report says 1.2 complete; the outgoing coordinator
  inspected the key source diffs and independently reran the actual-module
  isolated harness: **282 passed, one dependency deprecation warning**.
  This was not full HA pytest or physical validation.
- **Next substage: 1.3 — reactive planning and explanation.** On takeover, finish
  a proportionate review of 1.2 if needed, then provide its continuation prompt.
  Carry substantive fixes into 1.3 rather than restarting an open-ended audit.
- Stage 1.3 must connect saved cap/minimum/target/ready-by edits and relevant
  SOC/price changes to backend recalculation without a browser, reuse existing
  listeners/events, and test settings-to-plan updates plus policy explanations.
  Do not rebuild existing triggers that already work. Inspect first, fill gaps.
- **Automatic Morek uploads are Stage 3, not 1.3.** Stage 1.3 changes planning;
  it does not arm Morek scheduling or remove manual Send safeguards.
- Morek isolation/activation is still incomplete and unarmed. No deployment,
  restart, live charger command or push was authorized by this handoff.

## 2. How the user wants coordination to work

- Be decisive and pragmatic. The user explicitly said **stop overcomplicating and
  overengineering**. Aim for a good-enough tested implementation and keep moving.
- Assign **one roadmap substage per session**, not an entire stage. Include scope,
  required behavior, tests, exclusions, deliverable and stop-for-review boundary.
- The user expects implementers to finish assigned tasks. A newly discovered code
  path is implementation work, not automatically a reason to stop. Allow a stop
  for a concrete missing coordinator/user decision or external prerequisite;
  resolve it explicitly. Never require ignoring safety or concealing test failures.
- Do not accept another unused helper as completion of a functional task. Several
  sessions stalled this way before 1.2 was split and finally integrated.
- Make bounded follow-up fixes part of the next task where sensible. Do not be
  nitpicky or expand every issue into a prerequisite project.
- Review actual source/diffs/tests, not just implementer reports. Clearly separate
  checks you ran from checks the implementer reported. Never call isolated tests
  full HA/controller integration or hardware proof.
- Preserve user work. No unrequested commits/pushes/deployment. Do not reset,
  discard or overwrite unrelated changes. Do not spawn subagents unless authorized.
- Keep user-facing review brief and give one copyable prompt for the same LLM
  unless the user asks to initialize a new implementer.

## 3. Workspace and authoritative reading

Workspace: `C:\Code\spotnav-home-assistant`, Windows/PowerShell.

Read in order:
1. `AGENTS.md` — mandatory safety, naming and build/version rules.
2. `docs/charging-dashboard-roadmap.md` — **the numbered task checklist at the top
   is authoritative**; detailed old A/B/C sections below are acceptance reference.
3. `docs/morek-development-handoff.md` — current implementation/reports, especially
   the **2.5.20** entry. Older 2.5.15–19 “incomplete/guard retained” entries are
   history, superseded by 2.5.20. Old branch/deployment statements are not current.
4. `docs/morek-execution-audit.md` — writer inventory, ownership foundations and
   historical limitations. It is not permission to revive the abandoned recovery
   framework work or old A2.2 prompts.
5. `docs/morek-schedule.md` — current manual Morek workflow.
6. Relevant architecture docs/source/tests progressively; useful references are
   `docs/architecture-state.md`, `docs/ocpp.md`, `docs/target-soc.md`, `docs/prices.md`.

Inspect `git status --short --branch`, recent commits and manifest first.
At this snapshot branch is `feat/dashboard` tracking `origin/feat/dashboard`.
Latest commits include `08d6d3b8` (1.1), `3dcb9ec6` (roadmap rewrite), and
`5e40bc87` (unresolved evidence). Stage 1.2 is **uncommitted work** to preserve.

Modified tracked files at takeover:
- `custom_components/spotnav/api/dashboard.py`, `api/plan_preview.py`
- `custom_components/spotnav/execution/auto_execution.py`, `execution/controller.py`
- `custom_components/spotnav/planning/auto_controller.py`, `auto_settings.py`, `planner.py`
- `custom_components/spotnav/manifest.json`, `www/spotnav-card.js`
- `docs/charging-dashboard-roadmap.md`, `docs/morek-development-handoff.md`
- `tests/test_auto_controller.py`

New untracked tests at takeover:
- `tests/test_capped_auto_execution_isolated.py`
- `tests/test_capped_vehicle_energy.py`
- `tests/test_planner_minimum_energy.py`
- `tests/test_planner_price_cap_comparison.py`
- `tests/test_planner_price_policy_guard.py`

The handoff rewrite itself adds another intentional documentation modification.
Recheck this list instead of assuming it remains exact.

## 4. Product requirements

- **One Home Assistant charging dashboard with multiple coordinated cards.** No
  second stock-card dashboard, no solar UI, no decorative whole-home energy flows.
- Modern evcc-inspired styling; **Apache ECharts** selected. Important information
  visible by default; mobile stacks the same cards. No new React/Vue app required.
- Show Nord Pool prices and clearly separate **proposed / sent / effective readback /
  measured charging**. Include connection, SOC/target, minimum SOC, cap, ready-by,
  measured power, next window, plan energy/cost, execution health and missing data.
- Backend must eventually recalculate/resend autonomously when prices, SOC or
  settings/ready-by change. Browser activity must not drive automation. Keep
  manual Send/Refresh for diagnostics through the same eventual safeguards.
- Morek owns schedule boundaries in schedule mode; legacy HA start/stop/current
  loops must not compete. Hiding UI or merely pausing Auto is not ownership.
- Price policy: use at/below-cap energy toward target; above-cap energy only for
  the cheapest feasible deficit needed to reach minimum SOC by ready-by. Typical
  minimum 40% is editable, not a forced migration default. Never buy expensive
  extra energy merely to reach the higher target.
- Actual history must use genuine Morek/OCPP measurements/events, or validated
  BMW **Bavarian CarData** observations. No schedule-derived fake charging history.
  BMW history capability remains unverified. Distinguish home/public location,
  battery/grid energy, observed records/live-only collection and sample gaps.
- No separate overnight/hardware-testing stage. The user chooses when to test;
  continue software/UI development while clearly documenting physical uncertainty.
- Preserve integration domain `spotnav` and display name **SpotNav Enhanced**.

## 5. Current roadmap — no old A2.2 work queue

| Stage | Substages / status |
| --- | --- |
| 0 | **Done:** manual baseline; audit; ownership/identity/admission groundwork; attempt evidence |
| 1 | **1.1 done:** settings/API; **1.2 implemented:** planner + Auto; **1.3 next:** reactive planning/explanation |
| 2 | 2.1 existing execution boundary; 2.2 shared direct-write guards; 2.3 mode lifecycle/end-to-end tests |
| 3 | 3.1 shared schedule intent; 3.2 backend upload worker/triggers; 3.3 manual actions/persisted outcomes |
| 4 | 4.1 restart/reconnect; 4.2 bounded verification; 4.3 health/unresolved actions |
| 5 | 5.1 layout/shared components; 5.2 overview/status; 5.3 plan controls/actions |
| 6 | 6.1 genuine source inventory; 6.2 capture/provenance; 6.3 queries/retention |
| 7 | 7.1 ECharts prices; 7.2 zoom/interactions; 7.3 aligned schedule/measurement tracks |
| 8 | 8.1 yesterday comparison; 8.2 costs; 8.3 savings/summaries |
| 9 | 9.1 accessibility/themes; 9.2 responsive integration; 9.3 installation/docs |

Source inventory 6.1 and sample-data layout 5.1 may start early. Actual mode
activation still depends on isolation and resolved safety/authorization. Numbered
stages replace the previous broad A1/A2/A2P/A3/A4/A5/B/C assignment scheme.

## 6. Stage 1 — what exists now

### 1.1 settings/API (2.5.14)

Existing `AutoSettings` and settings API gained additive nullable fields:
- `soft_price_cap`: currency/kWh, null disables; zero and negative valid.
- `cap_price_basis`: `nord_pool` or `configured_variable_cost`, required for a cap.
- `minimum_ready_by_soc`: nullable percentage, distinct from live immediate floor.

Legacy values stay unconfigured; omitted API fields retain values; null clears.
Finite-number/percentage/minimum-target/revision validation uses existing patterns.
Minimum is also checked against the resolved vehicle target at planning time.
Do not add another settings store or redo this schema.

### 1.2 planner (2.5.17–18 work, included in current 2.5.20)

- `price_within_cap` uses existing price/fiscal arithmetic; major/minor conversion
  remains explicit. The source price may already include fiscal components; reuse
  existing included-fee handling rather than double-adding taxes.
- `PlanRequest` carries cap/basis and resolved `minimum_energy_kwh` (wall energy).
  Missing/zero minimum authorizes no expensive exception.
- `_calculate_capped` selects known eligible intervals. If feasible cheap energy
  cannot reach minimum, it searches known cheap/expensive candidates together
  under the shared period budget, bounded to minimum rather than higher target.
- Capped automatic periods have no hard run count when `max_periods=None`; this
  branch intentionally omits the uncapped start-cost/minimum-run preferences so
  it cannot pad expensive windows. Numeric period limits are enforced.
- Exact partial intervals include an expensive interval BEFORE a later cheap one.
  `exact_periods` prevents `ending_at_need`/`shown_periods` from trimming again.
  Costs and energy use actual durations. Uncapped behavior remains legacy.
- Result facts: `policy_shortfall_kwh` (target), `minimum_shortfall_kwh`,
  `exception_periods`, `exception_kwh`; `no_eligible_energy` is an explicit result.
- `plan_unpriced` still refuses capped requests. Unknown prices never authorize
  charging or get reclassified as cheap under a short-deadline guarantee.

Tested examples at 6 kW (pure planner, already-resolved wall deficits):
- Target 33 kWh/minimum 9, all expensive: select cheapest feasible 9, target short 24.
- Minimum 2.1 kWh, one cheap 15-minute interval: 1.5 cheap + 0.6 expensive over
  exactly 6 minutes, including when expensive precedes cheap. No whole-slot padding.

### 1.2c final integration (2.5.20)

- `capped_vehicle_energy` resolves fresh, actual/non-estimated SOC, usable capacity
  and effective target using existing learned wall-energy/efficiency conversion.
  It does not assume the immediate SOC floor has already charged the vehicle.
  Minimum fractional percentages are retained. Freshness uses existing rules.
- Cheapest-price Auto now consumes saved capped settings through normal calculation.
  Manual-kWh plans remain cheap-only without a minimum exception.
- Capped solar/hybrid strategies explicitly return unavailable. No solar work is
  requested; do not expand support opportunistically.
- Capped missing-price results bypass unpriced/history fallback. Stale input does
  not preserve a previous capped proposal as if it were freshly validated.
- `ChargingPlan.strict_windows` is persisted, default false for older plans.
  Capped plans cannot top off, be left to the car at vehicle limit, or defer a
  superseding plan so old windows continue outside the new permitted schedule.
- `AutoExecutor` reconciles empty/unavailable capped outcomes by standing down
  the old **Auto-owned** plan; stale attempts/settings must not clear newer work.
  Person-owned and immediate-SOC-floor charges remain separate.
- `policy_stand_down_failed` is visible as execution error; failed clearing remains
  retryable instead of pretending the old plan vanished. Existing clear/watch
  infrastructure is reused, not another recovery worker.
- Dashboard `serialize_plan` and preview `encode_preview` add `price_policy` facts:
  basis, reason, minimum/target shortfalls, exception kWh and intervals.
- The cap governs planned cheapest-price Auto charging. It is **not** a universal
  electrical limit on manual actions, the immediate floor or protection commands.
- Stage 1.3 event/trigger coverage is not yet established. None of this implements
  autonomous Morek profile uploads, isolation or activation.

## 7. Stage 2 — simplified approach and actual pause semantics

Do not revive the lengthy old A2.2 chain of standalone prerequisites. Existing
ownership/admission/evidence foundations are sufficient material to reuse.
The proposed durable pre-dispatch callback wrapper was **never assigned** and
is not required. Do not build it automatically.

The outgoing coordinator checked source: **Pause until I resume does NOT block
all writes**:
- Auto application/ordinary automatic starts: blocked.
- `AutoExecutor.automatic_allowed`: explicitly permits automatic stops under
  ordinary pause, and has person/balancing resume cases.
- `async_manual_start`: intentionally works while Auto is paused.
- Applying pause itself can call stop/clear; do not repeatedly invoke pause as a
  schedule-mode enforcement mechanism.
- `ChargingController.async_apply_regulated_current`: independent protection path.
- `charger_handback.py`: can start/restore current when an entry is deleted,
  without using the ordinary Auto pause gate.

Three implementation slices remain:
1. Extend the **existing execution boundary** with Morek ownership, blocking
   ordinary starts/stops/application/retries and conflicting manual actions BEFORE
   preparation effects. Reuse the pause infrastructure, not stop-on-pause behavior.
2. Cover direct current/phase/restore/handback bypasses with **shared guards**.
   Whole-writer coverage is a test requirement, not checks in every function.
3. Establish ownership before legacy startup/restore; quiesce old work for explicit
   handover; prefer deliberate reload over seamless hot switching; end-to-end tests.

Preserve protection. If active site regulation conflicts with schedule-only mode,
show an activation blocker rather than disabling safety or redesigning regulation.
Transaction authorization, safe entry/exit and retained 0 A profiles must be clear
before activation. Generic legacy unknown-command recovery is not a prerequisite
for planner/UI work. Do not redesign the whole charge-session core for isolation.

### Existing groundwork and cautions

- Ownership store is persisted metadata, not enforcement. Schedule owner strings
  do not arm control; no activation API exists in the foundation.
- Admission locks use physical station/connector, not friendly entry aliases.
  Identity classification distinguishes supported target, unrelated physical
  connector, target with unsupported protocol and unresolved/ambiguous identity.
- Late initialization uses the shared connector lock and rechecks identity. Its
  control-entity availability signal is not proven complete OCPP reconnect coverage.
- Duplicate contenders are partly in memory and rediscovered after restart.
- Cancelled storage writes can remain uncertain in-process. Generation invalidation
  is process-local, not an atomic durable transition and cannot undo dispatch.
- `unresolved_start.py` is a separate durable attempt-specific evidence store,
  **unwired**. It is not ownership, authorization, measured flow or a command gate.
- `_last_start_attempt`/`StartAttemptEvidence` are diagnostic only. Unknown physical
  outcomes must not silently become confirmed non-execution, but further machinery
  is only required to the extent needed by the chosen execution path.
- Existing outer decision/controller and assignment/profile locks precede the
  connector lock. Never wrap a routine that acquires assignment locks inside the
  connector lock or recursively reenter admission.
- Preserve person Stop/pause intent. Do not equate `urgent` with protection or
  silently suppress regulator stops/current lowering.

## 8. Safety, hardware and access facts

- Code implementation does not authorize live experiments. No sends/clears,
  charging start/stop, charger config, autonomous activation, HA restart, deployment
  or live-share changes without the user's specific approval for that operation.
- Never disable household protection, raise limits or assume a software actuator
  can be removed safely. Profiles impose current limits; they do not authorize a
  new charging transaction. Authorization remains unproven for the intended mode.
- Morek station **3020002509120029**, connector **1**, owned profile **42001**,
  production stack **1**. No automatic priority escalation or blanket profile clear.
- Manual builder sends displayed real windows, including shortened final stops,
  as fixed times—not measured-energy guarantees. Persistent final 0 A remains until
  replacement/removal. Removing it can permit charging; explain consequences.
- Accepted uploads sometimes read back flat 16 A before later matching with drift.
  Stack 5 was rejected; stack 4 and later stack 1 matched in historical diagnostics.
  Existing tolerance is 90 seconds with coverage checking, not exact physical proof.
- CompositeSchedule reports effective limits, not installed-profile inventory or
  measured charging. Earlier checks were unplugged; current connection is unknown.
- Never print/save/commit credentials, raw household logs or auth responses.
  Environment variable `homeassistant` was verified as a Bearer token. Use only in
  memory, only to the confirmed host, without credential-bearing redirects.
- Historical confirmed API URL: `http://homeassistant.local/`; port 8123 previously
  refused. `\\HOMEASSISTANT\config` was readable, not authorization to write.
- Read-only logs were available via `/api/hassio/core/logs?lines=1000` and WebSocket
  `system_log/list`; `/api/error_log` returned 404. Filter private data in memory.
  See the development handoff before any authorized live diagnostics.

## 9. Tests and build facts

Outgoing coordinator independently ran:
`python C:\Users\simso\AppData\Local\Temp\opencode\spotnav-planner-baseline\run.py`

Result: **282 passed, 1 warning, 2.62 seconds**, against actual repository modules.
Warning: HA HTTP application's aiohttp inheritance deprecation.

The harness uses lightweight package stubs/fixtures, not the full HA test runtime.
It now includes persisted-format settings through real calculation/preview and
real executor/controller methods with mocked charger boundaries. Inspect the
harness and tests to understand limits; do not call this a live HA end-to-end run.
Do not replace it with AST-extracted copies of implementation functions.

Implementer also reports Ruff, compileall, frontend build, check-dist and diff-check
passing. Normal HA controller tests were added but could not collect on Windows:
the HA pytest plugin imports Unix-only `fcntl`. No physical verification occurred.

Environment: local Python 3.14 is available. Earlier existing WSL Ubuntu had Python
3.12 and Docker daemon was unavailable. Recheck if useful, but do not install/change
environments or dependencies without authorization just to hide collection failure.

For integration/card changes, AGENTS.md requires manifest bump, `npm run build`
inside `frontend/`, and `npm run check-dist`. Committed bundled assets live in
`custom_components/spotnav/www/`; generated frontend sources are not committed.
Documentation-only edits do not need a version bump/build.

## 10. Source/test pointers for the next coordinator

- `planning/auto_settings.py`, `api/settings.py`: settings schema/API/persistence.
- `planning/planner.py`: cap comparison, exact window selection, minimum exception,
  energy/cost/shortfall result semantics. Keep existing optimizer for uncapped plans.
- `planning/auto_controller.py`: saved inputs, `capped_vehicle_energy`, actual
  calculation, snapshots, existing listeners/replan events (inspect for 1.3).
- `execution/auto_execution.py`: application, current-attempt/revision checks,
  strict replacements, policy stand-down and retained error state.
- `execution/controller.py`: `ChargingPlan.strict_windows`, storage compatibility,
  top-off/leave-to-car restrictions, actual command boundaries.
- `api/dashboard.py`, `api/plan_preview.py`: `price_policy` encoding.
- `execution/execution_ownership.py`, `command_admission.py`, `unresolved_start.py`:
  already-built foundations; not a queue of work to redo.
- `api/morek_schedule.py`: manual identity/profile/verification behavior; preserve
  existing safeguards. Autonomous worker is still future Stage 3 work.
- `__init__.py`, `execution/charger_handback.py`, `execution/chargers/`,
  `site/site_capacity_controller.py`: later Stage 2 startup/direct/safety paths.

Paths above are relative to `custom_components/spotnav/`.

Tests: `test_price_policy_settings.py`, `test_planner_price_cap_comparison.py`,
`test_planner_price_policy_guard.py` (name retained; now includes working capped
selection), `test_planner_minimum_energy.py`, `test_capped_vehicle_energy.py`,
`test_capped_auto_execution_isolated.py`, `test_auto_controller.py`, existing
planner/preview/dashboard/Auto tests. Discover existing trigger tests before 1.3.

## 11. Takeover checklist

1. Reconcile current Git/manifest with this snapshot; preserve unfinished changes.
2. Read the numbered roadmap, then inspect the current 1.2 implementation/test
   boundaries. The outgoing coordinator checked the key diffs and reran the harness;
   a comprehensive independent HA review has NOT occurred.
3. Tell the user briefly where we are: **1.1/1.2 implemented; 1.3 next; Morek
   isolation/activation/uploads still future**.
4. When asked for implementation continuation, give one concrete **1.3** prompt.
   Reuse existing settings/SOC/price listeners; close gaps, test browser-independent
   recalculation and policy explanation. Do not redo 1.2 or jump to uploads.
5. Keep the roadmap's overview/current-next pointers and this handoff current.
   Do not append contradictory “supersedes old instructions” blocks; edit stale
   statements directly. Historical release notes may remain clearly historical.
