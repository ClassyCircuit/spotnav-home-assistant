# Active roadmap — Morek charging, HA sidebar and trustworthy history

Status: **in progress. This is the only work queue.** Created 2026-11-14 by splitting the old roadmap, which
is now frozen as a historical reference:
[archive/charging-dashboard-roadmap-2026-11-14.md](archive/charging-dashboard-roadmap-2026-11-14.md)
(“the archive”). Source basis: manifest 2.5.128, HEAD `6a50a7ae`, source reading only. Nothing below is
installed, deployed or physically verified, and this file authorizes no HA access, charger command, restart
or deployment. Read `AGENTS.md` and [the development handoff](morek-development-handoff.md) first.

How to use it: assign **one substage per session** (a fresh Claude medium session, shared worktree, in queue
order), preserve unrelated and uncommitted work, and update this file’s checklist truthfully when a
substage lands. Do not rebuild a queue from the archive or handoffs. Do not re-implement anything marked
`[x]` or listed as done in the migration map.

Markers: `[x]` implemented locally with mocked checks (never “live-verified”); `[ ]` remaining; `[~]` partly
done, remainder named; `[>]` superseded and migrated (not implemented). **◆** = the substage changes a path
that Stage 14 protects, so the **Stage 14 non-regression contract** below is mandatory acceptance, not a
formality.

## 1. Fixed product facts (do not reopen)

- **Frontend:** one integration-provided HA sidebar panel. The local preview (`frontend/prototype/`) and the
  panel share `frontend/shared-dashboard/` (`mountDashboard`); the preview supplies fixtures, the panel
  (`frontend/sidebar/adapter.js`) real data. They are not two UIs. Charts use ECharts, controls Web Awesome
  Core. Presentation and planning logic stay in the backend; JavaScript only renders host-supplied values.
- **Morek schedule-only:** SpotNav sends fixed on/off windows (profile `42001`, absolute times, final 0 A).
  Household load protection is Morek’s own (user statement, not independently verified). No load
  balancing, no dynamic amps, no change to protection, no `ocpp.clear_profile` as cleanup.
- **BMW stops itself.** The user confirmed on 2026-11-14 that the BMW stops at its configured **80%** limit:
  an agreed operating assumption (user-confirmed, not agent hardware-verified, not a blocker, do not
  reopen). SpotNav’s target and the car’s limit are separate settings; SpotNav never writes the BMW limit
  and a stale SOC never proves the target was met.
- **Evidence vocabulary** (never blurred): *proposal* (calculated), *sent / ACK* (charger answered),
  *effective readback* (`GetCompositeSchedule`; effective limits, not an inventory of profiles),
  *transaction*, *measured flow* (fresh measured power/register). An accepted request, matching readback or
  retained schedule is never physical charging. Unknown is never zero.
- **Controls:** Pause/Resume Auto and Charge Now/Return to Auto (Stages 9–10, locally done). Stop, Pause,
  ownership, identity, protection and uncertain-write latches always win over automation.
- **Autonomous start:** charge control is authorized automatically on plug-in even if price or SOC is
  stale; explicit Pause/Stop and the guards above stay intact. Hardware tests and deployment are
  user-directed.

## 2. Migration map (archive → here)

| Archived scope | Disposition |
| --- | --- |
| Stages 0–4, 5.2–5.7a, 5.7b1–b2, 6.1–6.3, 9.4–9.7, 10.1–10.3, 12.1–12.8, 14.1–14.6 | **Done locally (`[x]`, mocked).** Not repeated here. Only their unrun acceptance and user-owned verification are carried (§9). Detail stays in the archive and handoff. |
| Stage 5.1 visual approval, 5.8 install/live validation | **User-owned** (§9.C). No LLM work. |
| 5.7b3 local acceptance (browser, full worker/planning, 5.4c suites **unrun**) | §9.B, optional, runs only if the user asks. |
| “Coordinator review pending” on `[x]` items | §9.B review list, independent of the queue. |
| Stage 7.1–7.5 | **Refined and carried** into Stage 7 below (7.3 split into 7.3a/7.3b). |
| Stage 8.1–8.3 | **Refined and carried** into Stage 8 below (8.2 and 8.3 each split a/b); two product decisions flagged (§9). |
| Stage 11 (11.1/11.2) | **Superseded `[>]`**, migrated to 15.9a/15.9b, 15.10, 15.11 (exact table in §10). |
| Stage 13.1–13.4 | **Carried** into Stage 13 below, unchanged in scope. |
| Stage 15.1–15.11, E1, E2 | **Carried**, with 15.1, 15.4, 15.7, 15.9 split into sized halves (ids keep the parent number). |
| Archive B1/B2/B3/B4/C1 detail | Delivered by Stages 5–6, 12 and carried by 7–8. Obsolete wording (Sections host, A/B chart switch, per-stage “Done when”) is dropped. |
| Archive C2 “finish the product” | Covered by Stage 12/13 plus the 8.1 session rows; no separate stage. |
| Archive §6 “decisions still to settle” | Only three remain open: D1 cost display, D2 savings baseline, D3 history retention (§9). Visual approval is 5.1. |
| Research, learning rules, status wording, terminology, safe user test, 6.1 source inventory, Stage 14 detail | Kept in the archive as **reference only**; linked from the substages that need them. |

## 3. Ordered work queue

One at a time; “Needs” lists the only real dependencies. Stable parent ids; a/b are the split halves.

| # | Substage | Needs | ◆ |
| --- | --- | --- | --- |
| 1 | 15.1a Planner time reserve — backend | none | ◆ |
| 2 | 15.1b Reserve setting control and plan display | 15.1a | |
| 3 | 15.2 Link monitor and offline/reconnect signals | none | ◆ |
| 4 | 15.5 Guarded start after a confirmed reboot (boot signal); backend “charging must be enabled” | 15.2 | ◆ |
| 5 | 15.3 Reconnect/startup read-only schedule check | 15.2 | ◆ |
| 6 | 15.4a Guarded schedule repair — trigger, confirmation, budget (dispatcher gated **off**, zero writes) | 15.3 | ◆ |
| 7 | 15.4b Repair deferral, post-repair escalation, then enables the repair gate | 15.4a | ◆ |
| 8 | 15.6 Connection-aware freshness (backend) | 15.2 | ◆ |
| 9 | 15.7a Plug-in authorization UI and freshness adoption | 15.6 (shows 15.5 fields when present) | |
| 10 | 15.7b Check/repair/reboot/offline wording and banner | 15.7a (shows 15.3/15.4 fields when present) | |
| 11 | 15.8 Late cumulative-register reconciliation | none | ◆ |
| 12 | 15.9a Energy learner fed on the Morek path (capture-only, not used by planning) | none | ◆ |
| 13 | 15.9b Learner rules: exclusions, asymmetric trust, clamp, promotion of 15.9a captures | 15.9a | ◆ |
| 14 | 15.11 Learned-estimate display and reset | 15.9b | |
| 15 | 15.10 Morek behind-plan check and power feed (deferrable) | 15.9a (energy side stays capture-only until 15.9b) | ◆ |
| 16 | 13.1 Vehicle sources and planning properties | none | |
| 17 | 13.2 Market and charging-cost settings | none | |
| 18 | 13.3 Practical plan and charger parameters | 15.1b if built (no duplicate reserve control) | |
| 19 | 13.4 Notification settings and setup diagnostics | none | |
| 20 | 7.1 Available-day navigation | none | |
| 21 | 7.2 Chart interaction and DST/resolution fixes | none (may share a session with 7.1 if 7.1 needs no backend read) | |
| 22 | 7.3a History client and evidence panel | none (Stage 6.3 API exists) | |
| 23 | 7.3b Aligned tracks on the price axis | 7.3a, 7.1 | |
| 24 | 7.4 Price-insight methods (backend) | none | |
| 25 | 7.5 Live price insights and monthly statistics (UI) | 7.4 | |
| 26 | 8.1 Day review (default yesterday) | 7.3a, 7.1 | |
| 27 | 8.2a Cost of measured energy with tariff provenance (backend) | 8.1, D1 | |
| 28 | 8.2b Cost display and totals consistency | 8.2a | |
| 29 | 8.3a Savings baseline (backend) | 8.2a, D2 | |
| 30 | 8.3b Savings and summary cards | 8.3a, 7.5 | |

Items 1–15 are the committed implementation sequence (Stage 15; 15.10 may be skipped without blocking
anything). Items 16–30 are later features: none is a prerequisite for Stage 15 or for 5.8; the order is the
suggested default (13, then 7, then 8) and the user may reorder it. **Not in the queue:** §9.B reviews,
§9.C user-owned items, E1/E2.

## 4. Standard acceptance for every substage

Production wiring (no groundwork-only or mock-only helper); focused fast tests at the real module boundary
(isolated runners under `tools/` such as `run_isolated_planning_tests.py`, or the handoff’s
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 … --noconftest` harness), including the important failure, restart and race
cases; no live command; truthful updates to this checklist and the handoff; the substage’s **exclusions are
binding**. Any integration or card change also needs the `custom_components/spotnav/manifest.json` bump,
`npm run build` and `npm run check-dist` from `frontend/` (AGENTS.md), with the committed
`custom_components/spotnav/www/` artifacts. Skip browser/Playwright and long suites unless the user asks;
report every unrun check by name. **User restriction (2026-11-14, binding on every session): only FAST tests.** Run focused isolated module tests and quick Stage 14 regression files one at a time with a short timeout; never launch the full `tools/run_isolated_planning_tests.py` list, browser/Playwright or broad frontend/backend suites, even where a §5 list names a file, if it is expensive. Report each unrun check and why; do not call a ◆ substage fully regression-verified on that basis. A new i18n string needs an entry in every shipped language file (parity
tooling). A docs-only change needs none of the above. No mock test establishes installed or physical
behavior.

## 5. Stage 14 non-regression contract (binding on every ◆ substage)

Stage 15 extends the existing worker, session coordinator, planner and stores. **It adds no second
controller, no second sender and no parallel dedup or freshness path.** Every send goes through
`MorekScheduleWorker` → `_send_profile_shared` under connector admission; new triggers (`repair`, link
`recovery`) are inputs to that path, never a bypass. Source: `api/morek_schedule.py`,
`execution/morek_worker.py`, `execution/morek_session.py`, `planning/auto_controller.py` (under
`custom_components/spotnav/`). Detail and rationale: archive “Stage 14” and “Stage 14 non-regression
contract”.

| Mechanism (symbol) | Rule | Likely touched by | Regression (existing test file, `tests/`) |
| --- | --- | --- | --- |
| Protected active window — `continue_active_window`, `connector_evidence` (14.2) | Unchanged. Reserve/repair/behind-plan resends carry the acknowledged window to its end (no 0 A gap in the wire profile). Unknown evidence never releases; only a **fresh unplugged** releases. Stage 14 call sites keep their strict **180 s** bound as a named constant; 15.6 may only make them stricter (more `unknown`, never more `waiting`/`unplugged`). | 15.1a, 15.4, 15.6, 15.10 | `test_stage_142_active_continuity.py`, `test_morek_worker.py` |
| Material triggers — `window_release` (14.4) | Thresholds unchanged: price rule saving ≥ EUR 0.50 **and** ≥ 10% of the comparable remaining cost, gap ≥ 30 min, ≥ 15 min slack beyond the minimum-SOC time, EUR areas only; cap rule needs a cap strictly lower than the accepted one. **Reserve minutes are excluded from every `window_release` quantity.** A `repair`, link-`recovery` or behind-plan run never carries a price-change or cap-lowered trigger, so it cannot release a window. | 15.1a, 15.4, 15.10 | `test_stage_144_interruption_policy.py` |
| SOC end tolerance (5 min, SOC-only cause) and 2 s coalescing (14.3) | Unchanged. `repair` is strict and not coalesced away. A reserve must not turn sub-5-minute SOC drift into a resend. | 15.1a, 15.4 | `test_stage_143_recalculation_triggers.py` |
| Dedup — `same_effective_schedule`, fingerprint skip (14.3) | Unchanged for every non-repair run. `repair` bypasses **only** the two `unchanged` returns, and only when 15.4a’s confirmation holds. It does **not** bypass the uncertain-record return or the rejection cooldown. | 15.4 | `test_stage_143_recalculation_triggers.py` |
| Uncertainty and recovery — uncertain latch, `REJECTION_RETRY_DELAYS` (5, 15 min), `TRANSIENT_BLOCKERS` (9.5/14.5) | Unchanged. Checks and repairs never retry or clear an unknown outcome. `morek_offline` joining `TRANSIENT_BLOCKERS` adds one **non-sending** timer inside the existing 12-check cap. | 15.2–15.4 | `test_stage_95_recovery.py`, `test_stage_145_fresh_inputs_recovery.py` |
| Stop / Pause / Charge Now ownership (reserved person Stop, generation rechecks, durable pause intent) | Wins over every Stage 15 trigger. A repair re-checks the generation after each persistence await, resends the *current* hold/override intent and never turns a hold into a run. A refused attempt (Stop, stale generation, admission) consumes no repair budget; only a run that reached the wire call does (14.6 dispatch marker). | 15.4, 15.5 | `test_morek_worker.py`, `test_morek_session.py`, `test_morek_session_activation.py` |
| Recovery sync (14.3: never suppress a required sync because the prior ACK matches) | The 15.3 check is **additional**; it never replaces the availability-return/startup reconcile, and a Healthy check never suppresses it. The check itself sends nothing. | 15.2, 15.3 | `test_morek_worker.py`, `test_morek_schedule.py` |
| Measured progress — `measured_progress`, `vehicle_update_wait` (14.5) | Unchanged inputs. 15.8 adds additive history fields only and must not alter the session energy that accounting reads; 15.9/15.10 never feed learning into it. | 15.8, 15.9, 15.10 | `test_stage_145_progress_recovery.py` |
| Decision evidence — `_record_decision`, bounded events (14.6) | Reuse the event shape; new causes are new trigger/result codes, not a second log. A repeat increments, never adds a line. | 15.3–15.5 | `test_stage_146_decision_evidence.py` |

**Existing files every ◆ substage reruns** (isolated or the documented harness; report any that cannot run,
and do not call the substage complete on new tests alone): `tests/test_stage_141_current_interval.py`,
`test_stage_142_active_continuity.py`, `test_stage_143_recalculation_triggers.py`,
`test_stage_144_interruption_policy.py`, `test_stage_145_fresh_inputs_recovery.py`,
`test_stage_145_progress_recovery.py`, `test_stage_146_decision_evidence.py`, `test_morek_worker.py`,
`test_morek_schedule.py`, `test_morek_session.py`, `test_morek_session_activation.py`,
`test_stage_95_recovery.py`, `test_stage_103_partial.py`. These reduce regression risk; they do not guarantee
it or prove deployed behavior.

## 6. Approved policy preserved by Stage 15 (user-agreed 2026-11-14 unless marked default)

1. **Time reserve:** 10% default, configurable (*default constants:* whole percent 0–50, 0 = off, cap 2 h).
   It lengthens **time only**, never SOC target or price tolerance. **Soft cap unchanged** — no new
   above-cap exception; above-cap energy stays only for the minimum-SOC need. Reserve is extra allowed
   time to reach the target, not energy beyond it (the BMW stops at 80%).
2. **Stable active sessions:** routine sensor/price/SOC updates never interrupt an active window or spam
   uploads; only Stage 14’s explicit triggers may. Plug-in recalculates and compares, even if nothing is
   sent.
3. **Schedule survives connection loss:** offline is an expected state shown as “last known”, never as
   charging and never as a charging failure. A new plug-in while HA is down may not authorize; SpotNav
   never edits the Morek charger’s own authorization configuration.
4. **Guarded repair/start, no blind writes:** automatic repair only after *repeated* confirming checks of a
   materially wrong effective schedule (a single odd readback only rechecks; a correct active charge is
   left alone); a guarded start only after a *confirmed* reboot with affirmative no-session evidence
   (reconnect alone is not a reboot); charging *enabled* only through the existing guarded start path, never
   by toggling the charge-control switch. An accepted request is not proof; the switch is a derived OCPP
   entity whose independent authorization evidence is **unverified**. No mandatory periodic OCPP readback.
5. **Robust median learning:** conservative named constants (adjustable in code, no new settings), shortening
   only with reliable agreeing data, outlier-resilient (15.9b).
6. **Freshness is connection-aware** (15.6): silence alone proves neither health nor failure; no alert on age
   alone; only fresh measured power says “Charging”.
7. **Wording** (default): casual, specific; *Waiting / Starting / Authorized / Unknown*; the deadline stays
   “Ready by”; a merely plugged-in car is never “Ready”. No sentence promises power or says “will charge”.
8. **No guarantee:** a retained schedule improves the odds only (charger clock, firmware and authorization
   dependent). Energy comes from the cumulative register and independent measurement, never from a schedule,
   ACK or readback; spans SpotNav did not observe are *unobserved, placement unknown*. No on-demand Morek
   history is assumed (archive “Research findings”).
9. **Routine defaults (adjustable, not user decisions):** a check, age or SOC change on screen is never a
   reason to dispatch; an interrupted or unknown outcome is never blind-retried; optional hardware
   experiments (E1/E2) are evidence tasks and block nothing.

## 7. Stage 15 — resilience, connection-aware status, trustworthy learning (substages)

Every item: Standard acceptance (§4); ◆ also the §5 contract, with the **rows named** below as extra checks.
Current-behaviour claims are source reading of 2.5.128. Archive references: “Stage 15” (settled decisions,
audit table, reconnect model, per-substage text), “Learning rules”, “Status wording”, “Active charge control
while offline”.

- [x] **15.1a Planner time reserve — backend ◆.** *Locally implemented with mocked checks (2.5.129); coordinator reviewed; not installed or live-verified.* Landed as: `AutoSettings.time_reserve_percent` (stored only when ≠10), settings API/compare-and-set, `planner.with_time_reserve` (applied by the auto controller to Morek-owned plans only, after `ending_at_need`; other chargers unchanged), `PlanResult.reserve_*`/`baseline_shown_periods`/`shown_periods`, `window_release` on baseline periods, dashboard `proposal.reserve` + per-window reserve fields. The reserve is rounded up only to the dispatch resolution (1 second; the profile is sent in whole-second offsets). Reserve pieces are taken from the start of free within-cap time, never from a part-elapsed current interval unless it continues a baseline window (so nothing creeps with the clock). Stage 14 stays reserve-free: an accepted profile that carried a reserve also stores its reserve-free twin (`acknowledged.baseline`); the 5-minute SOC end tolerance (strict at ≥ 5 min, measured on the need alone) and `window_release` (accepted window and new plan) are judged on the twin/`baseline_shown_periods`, so a reserve neither turns a sub-5-minute SOC drift into a resend nor changes a release decision (a missing twin means the plain comparison). Tests: `tests/test_stage_151a_time_reserve.py`.
  *Scope:* `AutoSettings.time_reserve_percent` (int, default 10, 0–50; absent in stored records = 10;
  validated, stored and exposed through the settings API with compare-and-set). The planner multiplies the
  target-need **active time** by `1 + p/100` at the single energy→time seam, using existing partial-window
  precision, rounded **up only to the profile’s dispatch resolution** (a named constant), never to a whole
  slot; at most 2 h. Reserve goes in the cheapest eligible **within-cap** periods before the deadline, never
  above cap, never a fourth window (14.1’s three-block limit); the part that fits is kept; feasibility is
  judged **without** the reserve (it never makes a plan short). Placement is deterministic; a SOC-only update
  must not move reserve across a slot boundary beyond the 5-minute tolerance. The proposal exposes, additively,
  `reserve_minutes`, its periods, and a backend-computed **`reserve_allowance`** (energy and cost of the
  reserve periods at plan power and period prices, labelled an *upper allowance*, not measured or expected
  use). `shown_periods` and the Morek profile include the reserve so sent windows are real; every
  `window_release` quantity and the minimum-SOC slack test use the **reserve-free** periods.
  *Reuse:* settings revision, `_morek_input_evidence`, the exact cap-aware planner, 14.x worker rules.
  *Acceptance:* 0% is byte-identical to today; 10% adds a proportionally short reserve for a short need
  (asserted against whole-slot inflation); 2 h clamp; deadline, cap and minimum-SOC above-cap energy
  unchanged; unknown inputs leave the plan unchanged; partial current interval, three-block limit and DST keep
  working; generated profile equals displayed windows; old stored settings load as 10.
  *◆ rows:* protected window, `window_release`, SOC tolerance. `window_release` decisions (including
  `release_slack_too_small`, `release_gap_too_short`, `release_saving_too_small`) are **identical for 0% and
  10%** on the 14.4 fixtures; repeated SOC-only updates give the same send count at 10% as at 0%; a reserve
  edit is a settings-revision trigger (no wait, no tolerance) but cannot satisfy the cap rule; first load of an
  old install changes the next plan once through the normal compare and never interrupts an active window;
  an active window survives a reserve change.
  *Exclusions:* soft-cap rules, the Stage 1 minimum floor, Stage 14 triggers, the SOC target, learners.
- [ ] **15.1b Reserve setting control and plan display.** *Scope:* sidebar control beside cap/minimum SOC
  (canonical settings, revision checks, existing draft/conflict behaviour); plan explanation and plan modal
  show reserve minutes and where placed, the **required baseline** and, separately labelled, the *potential
  extra allowed reserve energy/cost* from 15.1a’s `reserve_allowance` (complete windows visible, reserve
  periods identified inside them, no double counting, no claim of zero use, only measured is actual); the
  wording “extra allowed time to reach the target; the car’s own limit stops it”; preview fixture parity;
  absent backend fields degrade to today’s display; i18n. *Acceptance:* values shown equal the backend’s;
  allowance never added into the baseline; opening the view writes nothing; build/check-dist/i18n parity.
  *Exclusions:* no client-side planning or cost arithmetic, no BMW-limit control.
- [ ] **15.2 Link monitor and offline/reconnect signals ◆.** *Scope:* a small in-process monitor per Morek
  entry: every 30 s (constant) and on existing entity/connector events it reads, with **no OCPP traffic**, the
  point’s connection (`status == "ok"` as `_charge_point` judges it), the **point object identity** (a new
  object is a new connection) and the boot counter if exposed (`charger_generation`, read via `getattr`; that
  the installed OCPP integration exposes it is **unverified**). In memory: `link` (up/down/unknown, since),
  `connection_id`, `boot_generation`. Edges go to existing `session.offline()`/`reconnect()` and
  `trigger(kind="recovery")`, to the evidence store as `link_down` gap rows (so Stage 6.3 reports the span
  `unobserved`), to status as `link {state, since, connection_changed_at}`, and to the 15.3 scheduler.
  `morek_offline` joins `TRANSIENT_BLOCKERS`. Cold start = `unknown`; **an HA restart is not a charger reboot**
  (boot counter compared only within one process). *Acceptance:* up→down→up with a stale-available control
  entity is detected once and each edge delivered once; a new point object alone is an edge; a drop shorter
  than the poll without a new object is a stated limit; `link_down` spans show as unobserved energy; restart
  starts `unknown`; the monitor never calls the charger; single timer, cancelled on unload.
  *◆ rows:* recovery sync, uncertainty/recovery. Flapping gives a bounded, coalesced number of recovery runs
  and **zero sends when the schedule is unchanged**; availability return with a changed plan still sends
  exactly once through the existing reconcile; the new transient blocker adds only a non-sending timer within
  the 12-check cap; a changed point object never creates a plug-in (14.3 `note_sensor` rule).
  *Exclusions:* no readback, no start, no UI beyond the status field, no boot counter persistence.
- [ ] **15.5 Guarded start after a confirmed reboot (boot signal); backend “charging must be enabled” ◆.** *Scope:* make the
  existing `boot:`/`offline:` token path reachable from reliable evidence. **Confirmed reboot** = positive boot
  evidence only: the boot counter rose within this process, **and** a fresh connector report of `Preparing`
  was observed after that signal. A failed link plus a changed connection/point object is **connection
  restoration, not a reboot**: it never mints a `boot:` token, is never inferred to be a reboot (a point
  object proves a new connection only) and gets only the read-only 15.3 validation. Fresh `Preparing` with an
  affirmative no-active-session observation after a restoration may be recovered only by the **existing
  guarded recovery path under its own approved rules** (15.5 adds no new start trigger for it); a
  pending/unknown ledger record is preserved, never retried or cleared. A check, reconnect, point-object
  change or link edge alone never starts anything. Charging/Suspended→Preparing **without** a boot signal stays “session ended or completion ambiguous” (shown, no start).
  The start stays in `MorekSessionCoordinator` (unchanged `_reconcile`: Stop/Pause/protection/identity/
  ownership/generation, pending/unknown earlier request, completion record, 60 s rejection retry, one request
  per token) and additionally requires: status fresh and observed after the edge as `Preparing`, an
  **affirmative no-session observation** after the edge (transaction explicitly absent, or a fresh report
  replacing a transaction with none; a *missing/unknown* field is not absence and blocks), no
  Charging/Suspended since the edge, no start already requested under the token. **Enabled-charging
  requirement:** on plug-in and recovery the guarded start establishes enabled charging; SpotNav never toggles
  the switch blindly; the switch and transaction are verified as evidence afterwards; an accepted request is
  not proof; switch off/unconfirmed is exposed additively in readiness evidence as `not_ready`.
  *Acceptance:* reconnect, failed-link-plus-new-point or point change alone → no `boot:` request (restoration is read-only 15.3 validation; only the existing guarded recovery rules may act, unknown ledger preserved); transaction missing/unknown after the edge → no
  request; boot-counter rise with Preparing and no transaction → exactly one request; boot-counter rise while charging reporting
  Preparing → one; a second genuine reboot → a second (existing generation rule); transaction present,
  Charging seen, completion record, pending/unknown prior request, Stop/Pause/protection, rejected-final → none;
  stale-available drop now detected; accepted-without-transaction stays shown, never repeated; unplug/replug
  and restart behaviour unchanged; switch off after an accepted start → `not_ready`, no second request.
  *◆ rows:* ownership, decision evidence. Stop racing the request refuses it; plug-in still causes exactly one
  recalculation and compared reconcile; a start never triggers a schedule send or changes `continuity`;
  `not_ready` causes no send, clear or second start; also rerun `test_morek_start_schedule_evidence.py`,
  `test_morek_readiness.py`. *Exclusions:* no retry loop, no start from unknown/stale status, no change to
  Morek’s authorization setting, no schedule send.
- [ ] **15.3 Reconnect and startup read-only schedule check ◆.** *Scope:* a `ScheduleChecker` in the worker
  lifecycle running the existing read-only `fetch` path (`async_schedule_action(..., "fetch")`, `read_only`
  admission, `compare_schedule`: remaining intervals only) after a link-up/connection-change edge, the
  existing availability-return hook, a detected boot, and HA startup once the link is up. Only an acknowledged
  intent still inside its coverage is checked (Pause hold and Charge Now profiles too). Classes, one per
  check: **Healthy** (fresh clean match; elapsed periods, creation time, equivalent representation and the 5 min
  tolerance ignored) → retain, say “checked at {time}”; **Unknown** (readback unavailable/timed out, coverage
  reasons, link unproven, uncertain/pending record, replay burst, clock doubt) → nothing sent, say what was not
  checked, never promoted; **Differs, unconfirmed** (one fresh clean `limits_or_transitions_differ`) → recheck
  at 30, 60, 120 s then every 300 s, at most 12 per episode, stopped by a link edge or new attempt;
  **Confirmed material** is decided only by 15.4a. Status `reconciliation.check {class, at, readback_at,
  reason, rechecks}` plus one INFO decision line per *changed* class. **No periodic OCPP readback.**
  *Acceptance:* match → Healthy, no send; unavailable/coverage/uncertain → Unknown, no send; one mismatch →
  recheck, no send; elapsed and equivalent representations never differ; no check while a newer upload or
  verification is pending; no storm after a flapping link; HA restart seeds one check once the link is up.
  *◆ rows:* recovery sync, decision evidence. The check never alters `last_trigger`, `continuity`, trigger
  classes, ledger acknowledged/uncertain fields, or the `verified` fields of a newer attempt (assert with a
  pending upload); uses the existing `compare_schedule`, not a new comparator; zero sends throughout.
  *Exclusions:* no resend, no start, no setting, no `clear_profile`, `get_configuration` or `TriggerMessage`.
- [ ] **15.4a Guarded schedule repair — trigger, confirmation, budget ◆.** *Scope:* worker trigger kind
  `repair` raised by the checker when a mismatch is **confirmed**: (a) the **latest** readback is fresh
  (fetched ≤ 30 s before the decision, as `session_start_schedule_evidence` requires) and an **earlier** valid
  observation from the same connection and intent attempt exists **≥ 30 s before it** (the earlier one need not
  be ≤ 30 s old); (b) both are exactly `limits_or_transitions_differ` on a covering readback; (c) link
  continuously up and `connection_id` unchanged between them; (d) same acknowledged attempt id, no
  uncertain/pending record, no rejection cooldown. The worker recalculates the *current* guarded intent
  through `_intent` (routine, Pause hold or Charge Now, each repaired as itself) and resends, bypassing **only**
  the two `unchanged` returns in `_send_profile_shared` via a new `repair` flag beside `force_sync` (which stays
  untouched). Never `clear_profile`, never repeats an unknown outcome, a repair never turns a hold into a run,
  no repair from an unknown result, all existing guards apply. Resend carries the acknowledged active window
  (14.2). **Bounds:** at most **2 repairs per rolling 24 h** per charger, the second ≥ 30 min after the first,
  counted only for runs that reached the wire call, stored as an additive bounded list in the outcome record
  (old records load unchanged; read as untrusted). After the cap the worker sends nothing further and
  exposes a blocker code for “needs a person” (wording in 15.7b). **Feature gate (binding):** 15.4a ships the
  repair dispatcher production-wired but **disabled** behind a named constant (`REPAIR_DISPATCH_ENABLED =
  False`); until 15.4b completes, a confirmed mismatch is classified, recorded and shown but makes **zero
  writes**. The gate is enabled only by 15.4b, in its last step, after deferral and post-repair escalation are
  tested. 15.4a tests drive the dispatcher with the gate patched on, and also assert zero writes with the
  default gate off. *Acceptance:* one odd readback never sends;
  fresh latest + earlier ≥ 30 s same-connection observation → exactly one profile; two readbacks under 30 s
  apart → none; Pause hold repairs only as a hold; unknown/coverage/uncertain/cooldown/Stop/ownership/identity
  → none; wire profile has no 0 A gap and the same active window; cap and spacing enforced across restart;
  repair after a rejection follows the 5/15 min bounds; send counts asserted. *◆ rows:* dedup, window_release,
  SOC tolerance, ownership, uncertainty. `repair` is strict, never carries a price/cap trigger (never returns
  `price_improvement`); an equal schedule without confirmation sends none; Stop racing a repair at each await
  sends nothing and consumes no budget; the record migration keeps `acknowledged`, `attempt`, `uncertain` and
  the 14.5 retry count; the run is a normal bounded decision event (`trigger=repair`). *Exclusions:* no change
  to Stage 14 triggers or 14.4 rules; no `clear_profile`; no repair from age, SOC delta or a replayed update;
  no start request; **no automatic wire repair in a shipped build** (gate stays off).
- [ ] **15.4b Repair deferral for a correct charge and post-repair escalation ◆.** *Scope:* when fresh measured
  power shows the car charging, the readback’s *current* limit equals the intended current and the difference is
  only a future transition more than **10 minutes** away (constant), defer the repair and recheck every
  5 minutes; proceed when the gap reaches 10 minutes, when charging or the current limit no longer matches, or
  immediately if the charger is idle or the current limit is wrong. A repair that is accepted but still reads
  back as differing escalates to the “needs a person” blocker and sends nothing more. Wire continuity is all
  this claims; uninterrupted physical charging is **not guaranteed**, and the earlier 16 A brief (E1) is
  **unverified**. *Acceptance:* correct active charge with a distant future-only difference defers then
  repairs at 10 min; idle or wrong current repairs at once; deferral timers send nothing by themselves and
  survive restart; post-repair mismatch stops automatic sends; send counts asserted. *◆ rows:* protected
  window, uncertainty. *Completion step:* flip `REPAIR_DISPATCH_ENABLED` to `True` only after the above pass, with a test that the
  gate-on path cannot send without deferral and escalation present. *Exclusions:* no new thresholds beyond the
  two constants, no UI (15.7b).
- [ ] **15.6 Connection-aware freshness (backend) ◆.** *Scope:* one shared judgement per quantity returning
  `{state: current|last_known|idle|unknown, basis, reported_at, age_s, link, reason}`, replacing the fixed
  180 s bounds at the **display/readiness** sites (`_session_readiness`, `LIVE_MAX_AGE_S` display use) and
  the coordinator’s `observe_initial`. Event-driven quantities (connector status, transaction) are `current`
  while the link has been continuously up since the report (“unchanged since {time}”, no age cap), `last_known`
  with age when the link is down/unknown. Sampled quantities (power, current, register) are `current` when
  younger than `max(180 s, 3 × the median interval of the last 10 observed posts, capped at 900 s)` while a
  transaction or flow is expected, `idle` when none is expected, `unknown` when the link is not up; cadence is
  learned from observed post times in the evidence store (no `get_configuration`). For any start-affecting use,
  `current` also needs a report observed by this process after the monitor seeded (a memory-only link never
  lets a pre-restart report count). The 120 s accepted-without-transaction wait and the 9.5/14.5 timers are
  request/recovery waits and stay. *Acceptance:* an idle healthy connector is current/unchanged, not stale;
  silent sampled values in a transaction → unknown after the adaptive bound; link loss → last known;
  reconnect → current after a new report or continuous link; restart → unknown until seeded; clock skew; no
  alert on age alone; only fresh measured power says “Charging”. *◆ rows:* protected window. A connector status
  10 minutes old with the link up is `current` for display but still `unknown` at the 14.2/14.4 sites (an old
  “unplugged” never releases, an old “waiting” never lets `window_release` run); a fresh unplugged still
  releases; 14.2/14.4 outcomes are byte-identical on the existing fixtures; a pre-restart report never
  authorizes a start; 14.6 `connector` field semantics unchanged. *Exclusions:* no frontend (15.7), no change
  to Stage 14 thresholds, no new OCPP calls.
- [ ] **15.7a Plug-in authorization UI and freshness adoption.** *Scope:* in `frontend/sidebar/charge-session.js`,
  `live-charging.js`, `recovery-banner.js` and the readiness evidence use the 15.6 judgement instead of the
  local `LIVE_MAX_AGE_MS`/`OBSERVATION_MAX_AGE_MS` limits (`GRACE_MS` stays: it matches the backend
  accepted-without-transaction wait); make *authorized / waiting on purpose / at risk of not charging* the most
  prominent element while a car is plugged in, each blocked reason paired with who acts. **Charge-control
  requirement:** the card says charging must be enabled; “missing, disabled or unavailable” → “can’t start or
  schedule charging”; **off/unconfirmed → “not yet ready to charge”** (with who acts, and “asking the charger to
  enable it” while 15.5’s guarded start is pending), never normal or ready; it shows 15.5’s `not_ready` and
  never toggles, requests or infers anything, and distinguishes the derived switch from transaction/status
  evidence. *Acceptance:* every 9.7 evidence rule holds; no sentence promises power; offline vs unknown
  distinct; an idle connector is not shown stale; absent backend fields degrade to today’s text; wording tests
  per state; i18n parity; preview fixture review (no browser suite unless asked); Pause/Resume, Charge Now and
  Send/Refresh behaviour and safety tests unchanged; opening or refreshing writes nothing. *Exclusions:* no
  backend change, no rename of “Ready by”, no theme work.
- [ ] **15.7b Check/repair/reboot/offline wording and banner.** *Scope:* the sentences for: reconnect check
  result (“checked at {time}, nothing needed changing” / “couldn’t check”), checking (“one odd reading isn’t
  enough to act on”), schedule repaired, **needs a person** (recovery-banner mapping of 15.4a’s blocker),
  reboot-asked-once, offline “last known {state}, {age}”, idle-connected (“unchanged since {time}”), unknown.
  Default copy and who-acts rules: archive “Status wording”. *Acceptance:* each state has a wording test;
  nothing claims a repair or check proves charging; offline never reads as a charging failure; absent fields
  degrade; i18n parity in every language file; no new write path. *Exclusions:* no backend change.
- [ ] **15.8 Late cumulative-register reconciliation of closed session totals ◆.** *Scope:* one bounded
  reconciliation when a session closes or a late register value arrives: total = register at close − register
  at open (the session recorder’s pair) versus energy already placed from observed samples; the remainder is
  stored as **unplaced late energy** with `placement: unknown` and a reason (gap, `link_down` once 15.2
  exists, restart, replay), as an **additive history field** beside the session total, never placed into the
  flow timeline and never counted as current power or measured progress. It must **not** change the session
  energy the recorder computes or that 14.5 reads; a replayed burst is never live flow; register read only
  (no OCPP traffic). Cases: register reset/decrease (`RESET_TOLERANCE_KWH`; skip, reason `register_reset`);
  identity mismatch (`identity`); duplicate/repeated late updates (idempotent by session id and value);
  register absent at open/close (`unknown`, not zero); late value after close and restart (persisted pair,
  one reconciliation); total below placed energy (keep placed, flag `inconsistent`). *Acceptance:* a 20.9 kWh
  total against 0.103 kWh placed yields 20.797 kWh unplaced late energy, total 20.9, timeline unchanged, no
  flow or SOC-progress effect; the cases above; old session records load. *◆ rows:* measured progress. 14.5
  outcomes identical before/after with and without a reconciled session; no replan, trigger or send results.
  *Exclusions:* no timeline backfill, no charger command, no new store beyond additive fields, no claim of when
  the energy occurred.
- [ ] **15.9a Energy learner fed on the Morek path ◆ (former 11.1, part 1).** *Scope:* under Morek schedule
  ownership nothing is sampled today (`_check_plan`, the only caller of `_sample_energy`, runs only from
  `_arm_watch` on Auto-owned windows). Add a bounded 60 s tick tied to a known plug-in that calls only
  `_sample_energy` into the **existing** `EnergySampler`/`LearnedEnergyStore`. First prove by test which
  controller facts (`plugged_in_at`, `known_connected`, `charging`) are live under Morek ownership; where one
  is not trustworthy use the session coordinator’s connection token and the evidence store’s register samples,
  and say so. Use only trustworthy measured sources, non-estimated SOC and vehicle association; never learn
  from scheduled current, ACK/readback or missing data. **Capture-only (binding):** samples from this tick
  are written to the existing store tagged additively (`origin: morek_capture`, no rule version) and
  **planning ignores them**: `_learned_energy_for` keeps using exactly the figure it uses today (legacy
  records, else the default) until 15.9b promotes captures, so weaker 15.9a trust rules can never influence a
  plan. Old records without the tag load as today. *Acceptance:* planner output is byte-identical with and without captured samples present (assert);
  samples accrue from a mocked plug-in with
  two fresh non-estimated SOC readings; lagged reports pair by report time; guest car, changed capacity/
  identity/wiring discard; fallback to the default with the existing “nothing learned” result; a learner
  error never blocks planning or sending. *◆ rows:* measured progress. The tick never runs PlanWatch,
  `async_recalculate()` or any send; the figure the planner uses is **not changed at all by 15.9a** (captures are ignored), so learning never changes `_morek_input_evidence`, a replan or a resend mid-charge
  (keep this invariant under test); no feed into 14.5; existing learner tests (`planning` runner) pass.
  *Exclusions:* no rule change (15.9b), no power learner (15.10), no new store, no UI, no planner use of
  captured samples.
- [ ] **15.9b Learner rules: exclusions, asymmetric trust, clamp ◆ (part 2).** *Scope* **(first: promotion/revalidation)** every stored `morek_capture` sample is revalidated under the rules
  below before it can influence a plan; samples lacking the metadata the exclusions need (gaps, `link_down`,
  restarts, unplaced-energy flag, SOC basis) are **discarded with a counted reason, never promoted**, so
  contaminated 15.9a data keeps no influence; promotion is explicit and one-way, and only promoted samples
  count toward trust (constants in
  `planning/learned_energy.py`, named and documented): rise **≥ 15 points** (was 10); keep the last **9** ended
  plug-ins (was 5), drop samples older than **120 days**; exclude a stretch whose register span overlaps
  recorded gaps, `link_down`, capture restarts, unobserved/replay-affected segments or sessions with unplaced
  late energy (15.8 flag when present), and one ending above **90%** SOC (taper); count every rejection by
  reason (extend `discarded`). **Use:** lengthening keeps the existing trust rule (≥ 3 samples within 10% of
  the median); a figure that would **shorten** time needs **≥ 5 agreeing samples**, judged against the default
  figure at the point of use; the used figure is clamped to **−10% / +25%** of the default
  `capacity ÷ efficiency ÷ 100`, applied before the 15.1 reserve (never reduced by it) and never below the
  Stage 1 minimum floor. No per-sample step limit, no temperature buckets. *Acceptance:* captures with a gap, restart or missing metadata never reach the planner after promotion
  (counted); four agreeing samples
  may lengthen but not shorten; five may shorten, clamped; one odd charge cannot move the median; gap,
  `link_down`, restart or unplug spans and >90% stretches yield no sample with counted reasons; an incorrect
  initial estimate moves only through trusted samples and never past the clamp; stale or estimated SOC yields no
  sample; HA restart keeps the anchor and never turns a half-observed stretch into a sample. *◆ rows:*
  `window_release`, measured progress. At plug-in end a changed figure causes at most one compared reconcile
  (equal schedule sends nothing, active window protected); shortening cannot weaken the minimum-SOC need that
  14.4’s slack test uses; 14.2/14.5 outcomes unchanged. *Exclusions:* no new store, UI or ML.
- [ ] **15.11 Learned-estimate display and reset.** *Scope:* where the plan’s time/energy explanation shows,
  state whether the estimate is learned or default, the sample count (“n of 5 needed to shorten”), the effect
  in minutes and “estimate; no guarantee”; rejection reasons in diagnostics; an administrator action resetting
  learned energy and power data for the charger (reusing the stores’ own removal) plus its sidebar control.
  Replanning after a reset goes through the existing input-evidence path. *Acceptance:* default and learned
  displays correct; “learned values unavailable, using the default” while nothing trusted exists; reset
  restores the default and replans once (equal schedule sends nothing, active window protected); non-admin
  refused; i18n parity; stale display never claims precision; opening the view writes nothing. Only the reset
  action needs the Stage 14 backend files. *Exclusions:* no new learning rule; retuning constants from user
  summaries is a separate optional review.
- [ ] **15.10 Morek behind-plan check and power-learner feed ◆ (former 11.2; deferrable).** *Scope:* run the
  existing `PlanWatch` and `PowerSampler` against the **acknowledged active window**
  (`morek_schedule.active_window`) instead of an Auto plan’s windows; a confirmed “behind” calls the existing
  `async_recalculate()`, whose changed plan reaches the worker as a strict recalculation. The power learner
  stays **lengthen-only**. *Acceptance:* a slow charge inside an acknowledged window yields one replan through
  the guarded owner (bounded by PlanWatch backoff); a healthy charge, held window (Pause/Stop/Charge Now),
  unknown evidence, stale reading, changed vehicle or restart yields none; power samples accrue only from
  clean minutes and only lengthen; an infeasible target is reported by the existing planner and never
  promised; no 0 A gap; send counts asserted. *◆ rows:* material triggers, protected window, measured
  progress. The replan is the existing strict `recalc` (no tolerance), carries no price/cap trigger (so
  `window_release` is never reached with a price event), keeps the active window, is deduplicated by the equal
  compare and does not double-count 14.5 progress. *Exclusions:* no new threshold, no shortening from power;
  skipping it blocks nothing.

Optional evidence tasks, **user-run or user-directed, block nothing:** **E1** — determine from the 9.4 log
viewer, 6.2 evidence and read-only readbacks the user approves whether an effective 16 A period around a
reconnect comes from the charger’s retained-profile evaluation, the HA OCPP integration or SpotNav (written
finding only; may tighten 15.4 constants). **E2** — controlled outage/replay test (archive “Safe user test”;
never `clear_profile`, `configure`, `set_charge_rate`, `update_firmware`, `data_transfer`); informs buffering
only, nothing depends on it.

## 8. Later feature stages

### Stage 13 — Useful configuration without the old card (13.1–13.4)

Goal: the sidebar becomes the practical daily interface without recreating the old card. Add a compact,
organized advanced-settings area to the existing shared sidebar UI; reuse canonical backend APIs, validation,
saved configuration and revision checks; inspect current source before each substage (12.5 owns target
SOC/manual mode and vehicle selection, 12.2 price provenance, 12.3 plan details, 12.4/12.7 Morek evidence).
Opening or editing a view must never write, wake the car or send a notification; a saved change may lead to
normal guarded reconciliation when the owner is armed, and the UI says so. Every substage: Standard
acceptance plus tests for permissions, revision conflicts, unchanged saves, errors, drafts and stale values.
Full requirement text: archive “Stage 13”.

- [ ] **13.1 Vehicle sources and planning properties.** Inspect the selected vehicle’s actual SOC source and
  integration; choose among ambiguous suitable sensors; configure usable battery capacity when not reported;
  choose onboard charging phases where existing settings support it. Reuse discovery/confirmation and
  vehicle-property APIs; show reported vs overridden values and missing inputs. Coordinate with 12.5, 12.6,
  12.8. Never silently choose an ambiguous source, invent capacity, overwrite a saved selection or treat an old
  reading as new. Tests: ambiguous/missing/removed sensors, reported vs overridden capacity, phases,
  stale observations.
- [ ] **13.2 Market and charging-cost settings.** Expose existing market/price-area selection and tariff
  settings (VAT, energy tax, grid fees incl. existing time-dependent/percentage options). Keep provider
  route, held-data provenance, selected market, raw price and configured variable cost distinct; never
  silently switch provider, enable fees or assume prices exclude charges; keep 12.2’s c/kWh display. Tests:
  supported/missing providers, area changes, variable/negative prices, fee basis, currencies, settings-to-plan
  updates. Do not invent historical tariffs.
- [ ] **13.3 Practical plan and charger parameters.** Maximum charging periods, planned current, supported
  departure date/weekday options not already in 12.5 (no duplicate ready-by/cap/minimum/target controls and no
  duplicate of the 15.1b reserve control). Planned current is a planning input, not load balancing; respect
  charger/electrical bounds and Morek transition/period limits; never raise current or change protection
  automatically. Tests: period counts and currents, date/weekday/deadline, DST, conflicts, backend replanning.
- [ ] **13.4 Notification settings and concise setup diagnostics.** Per-charger recipients (HA mobile apps)
  and event settings; show no-recipient, unavailable, permission and save failures; a compact actionable view
  of existing capability/setup warnings (missing/ambiguous measurement sources, pricing configuration,
  execution blockers where exposed), linking to settings and reusing 12.4/12.7 text. A notice never proves a
  plan was sent or charging measured. Tests: missing phones, selected events, persistence, permissions.

**Excluded from Stage 13:** solar/hybrid and home-energy flows, site load balancing, the legacy minimum-SOC
start controller, direct legacy Start/Stop, BMW wake or limit writes, external debug upload. Do not imply the
old card’s backend behaviour disappears when its UI is hidden.

### Stage 7 — Price chart navigation, evidence tracks, price insights (7.1–7.5)

**Audit (source reading, 2.5.128).** The real stepped-area price chart, proposal overlay, wheel zoom, tooltips,
reset and zoom-preserving updates already exist (5.4c; `frontend/shared-dashboard/charts.js`,
`frontend/sidebar/price-chart.js`) — reuse, do not rebuild. Facts that shape the substages:
(1) the sidebar chart is fed only from `raw.prices.published_intervals` in `get_dashboard`; the webhook
`price_days` serves today/tomorrow only; the repository keeps up to `HISTORY_KEEP_DAYS` = 400 day files, but
no sidebar read path for past days was found, and which days it actually holds depends on what was fetched;
(2) `get_charging_history` (6.3, `sessions/history.py`) exists with **no frontend consumer**: windows ≤ 7 days,
UTC instants, 200 rows per list, **Morek only**, raw measurements kept 7 days (4320 rows per kind), finished-
day digests 62 days **without price rows**; the 100 W / 2-sample flow thresholds and the installation’s real
entities, cadence and noise floor are **unverified**, so a first install is expected to show much `unknown`;
(3) the shared `history-view.js` takes display strings, `readings {time,kw}` and one `sentHistory {start,end}`,
and the sidebar adapter supplies **no** `history` or `insights` model, so both views render “unavailable”;
`insight-view.js` is a text-block renderer with no real data behind it; (4) `price_history.py` builds a
28-day weekday profile (needs ≥ 21 of 28 days). Honest data prerequisite for 7.3/8.x: measured evidence
exists only after capture has run on the installation; nothing may be reconstructed from plans or ACKs.

- [ ] **7.1 Available-day navigation.** *Scope:* shortcuts (Yesterday / Today / Tomorrow / All available) only
  for days the price source actually provides. First document what `published_intervals` covers. If past days
  need a backend read, add **one** read-only command returning held intervals for a requested local-day range
  from `price_repository` (bounded range, same permissions as dashboard reads, documented in `docs/api.md`, no
  new store); otherwise stay frontend-only. A day with no held file is disabled with the reason; unpublished
  tomorrow is explained; unknown future is not zero; no synthesized rows; reuse `snapRange`/`initialRange`
  and the existing horizon behaviour. *Acceptance:* shortcut availability follows held data; 23/25 h DST days
  and source-resolution (hour vs 15 min) boundaries correct; user zoom survives routine updates; preview
  fixture parity; focused vitest checks (browser suites only if asked).
- [ ] **7.2 Chart interaction and DST/resolution fixes.** *Scope:* reproduce with fixtures, then fix only
  defects found: hourly↔15-minute change inside one horizon, 23/25-hour axis ticks, container resize or
  orientation keeping the range, tooltip for negative values and gaps. Preserve zoom, tooltip, wheel and reset;
  no new features. May close as “verified, no defect” with the fixtures kept. Physical touch stays
  unverified.
- [ ] **7.3a History client and evidence panel.** *Scope:* a read-only client for `spotnav/get_charging_history`
  and an adapter mapping into an **extended shared `history` contract** (spans with states, not just one sent
  window): sent-plan spans from the history’s plan knowledge including `unknown_plan_spans`; observed flow
  intervals; planned-block status `flow_observed` / `no_flow_observed` / `unknown`; `outside_plan` and
  `no_plan_evidence` flow; measured energy by basis (meter counter vs integrated, **never summed**; a basis
  with no segment is `null` with coverage, a measured zero is 0.0; unobserved meter energy has no placement).
  Panel states for loading, permission, unavailable and “no evidence retained”. Preview fixtures use the same
  contract. No JavaScript planning or interpretation beyond rendering. *Acceptance:* each status and
  unknown/gap case renders distinctly; Morek-only and ≤ 7-day limits stated; non-admin read behaves as the API
  does; opening writes nothing; adapter and renderer tests; build/check-dist.
- [ ] **7.3b Aligned tracks on the price axis.** *Scope:* tracks aligned with the price time axis: **Proposal**
  (current plan windows incl. `minimum-exception` marking), **Sent** (last acknowledged intent spans), **Effective**
  (**latest readback only**, remaining period, labelled as such — history never restores effective knowledge)
  and **Measured** (from 7.3a). Mismatches and missing observations are drawn as unknown/hatched, never as
  absence; suggested cheap opportunities are not the plan; a reported limit is never drawn as kW. *Acceptance:*
  proposal≠sent, sent≠effective and planned-without-flow cases legible; zoom/pan keeps tracks aligned; DST
  day; preview parity; no change to the price chart’s existing interactions.
- [ ] **7.4 Price-insight methods (backend).** *Scope:* inventory what price data is held (day files,
  `price_history` profile, `market_observation`) with basis, resolution, retention and coverage, then
  implement a pure, tested, read-only module and its smallest read surface (an additive block in an existing
  read payload or one new read-only command, documented in `docs/api.md`): the current interval versus the
  held trailing window (rank/percentile with a stated minimum coverage, else `unknown`), and the cheapest
  upcoming window of a requested length inside the **published** horizon. Raw published spot price in the
  existing display unit unless the existing fiscal helpers are explicitly used and labelled. Output always
  carries baseline, coverage (days held / expected), basis and assumptions. *Acceptance:* missing history or
  future prices reported, never invented; negative prices; DST; area/currency change; no new store.
- [ ] **7.5 Live price insights and monthly statistics (UI).** *Scope:* bind 7.4 into the shared `insights`
  model (`intro`, `blocks`, `caution`, `method`; host-supplied text): current-interval assessment, best
  available windows, per-month price statistics with “n of N days held”. Opportunities are not the charging
  plan and the card says so. *Acceptance:* each block shows baseline, coverage, price basis and assumptions;
  unavailable data shows the reason; preview parity; i18n parity.

### Stage 8 — Day review, costs, savings (8.1–8.3)

**Audit (source reading, 2.5.128).** Reuse Stage 6 evidence and the existing session store; do not add stores.
(1) Evidence detail exists only 7 days (digests 62 days, no price rows); older **days** with measured data
exist only if the session store (730 days, ≤ 5000 per charger) recorded them, and **whether the Morek entry’s
session recorder opens sessions is unverified**. (2) Session cost is computed at read time from the **current**
fiscal settings (`cost_basis: current_settings`) unless a legacy stored cost; only plan versions keep a tariff
snapshot (`plan_tariff_snapshot`), so past charging must never be priced with today’s tariff silently.
(3) Existing savings are `SAVINGS_BASIS = "day_average_price"` (`sessions/summary.py`,
`ChargeSession.savings_minor`): the same priced energy at that day’s average price, labelled an estimate.
The earlier roadmap’s suggested baseline (“charge the same energy immediately after plug-in at comparable
power”) is **not implemented and not approved**. (4) `get_sessions` and `summary.py` already produce day and
month buckets and never add currencies together. Coordinate with 7.3 (tracks) and 7.5 (monthly insights);
implement nothing twice.

- [ ] **8.1 Day review (default yesterday).** *Scope:* a day selector limited to days the history/sessions
  APIs actually return (default yesterday; if nothing is retained, say so) showing, from 7.3a/7.3b: measured
  charging against the plan actually sent, planned-block status, flow outside the plan, measured energy by
  basis, coverage and unknown spans **separately from confirmed absence of flow**, price context via the 7.1
  chart, and session rows from `get_sessions` where sessions exist (source `energy_source` labelled; an empty
  state when the Morek recorder produced none). No cost. *Acceptance:* a plan or readback never fills the
  measured track; missing data is “unknown”, not “did not charge”; days beyond retention are not offered; DST
  day; midnight-spanning session; preview parity.
- [ ] **8.2a Cost of measured energy with tariff provenance (backend).** *Scope:* price measured energy per
  day/session/month using an explicit `cost_basis`: `plan_snapshot` (tariff and prices stored with the
  applying plan version), `legacy_stored`, `current_settings` (labelled estimate) or `unknown`; never today’s
  tariff silently; one applying version per priced span, otherwise `unknown`. Additive fields on the existing
  history/sessions answers; coverage reported; negative and missing prices; currencies never mixed; fee/tax
  changes tested. **Needs D1** (cost display basis). *Exclusions:* no retention change (D3), no new store.
- [ ] **8.2b Cost display and totals consistency.** *Scope:* show day/session/month cost in the 8.1 view and
  keep plan totals (existing backend `model.totals`) and historical totals consistent across cards; label
  estimate, basis, currency and missing rates. *Acceptance:* the same inputs give the same totals in every card;
  partial data, negative prices and missing baseline tested; unknown never becomes zero.
- [ ] **8.3a Savings baseline (backend).** *Scope:* apply the baseline chosen in **D2**; until the user
  chooses, keep the existing `day_average_price` and label it. Report coverage, assumptions and `unknown`
  (never zero) when evidence is insufficient; forecast savings (from a plan) are separate from historical
  estimates. If D2 selects “immediately after plug-in”, the plug-in time and comparable power sources must be
  named and tested first (not assumed). **Needs 8.2a and D2.**
- [ ] **8.3b Savings and summary cards.** *Scope:* summary cards for day/month totals reusing 7.5’s monthly
  framing; totals identical to 8.2b’s. *Acceptance:* baseline, coverage and estimate labels visible; forecast vs
  historical distinct; consistent totals; preview parity; i18n.

## 9. Open decisions, review work and ownership

**Open product decisions (none is approved; raise with the user before the named substage):**
**D1** — default cost display: the full configured variable cost (fees/taxes) with a Nord Pool-only option was an
*earlier suggestion*, not agreed (blocks 8.2a). **D2** — savings baseline: keep `day_average_price` or implement
“immediately after plug-in” (blocks 8.3a). **D3** — history retention: the earlier “90 days of detailed traces”
proposal is **not** adopted; today’s 7 days raw / 62 days digests / 730 days sessions stand (needed only if the
user wants measured traces older than 7 days in 8.1/8.2).

**A. Verification ledger (local implementation vs unrun acceptance vs user-owned).**

| Item | Local implementation (mocked) | Unrun / unverified | Owner |
| --- | --- | --- | --- |
| 5.7b2 live binding; 6.2/6.3 capture and history API; 9.4–9.7; 10.x; 12.x; 14.x | Yes, per their archive entries | Installed sources, entity set and cadence, flow thresholds, deployed and physical behaviour; 9.5’s accepted fresh-Resume exception for an ambiguous undispatched Resume stays | User (5.8) |
| 5.7b3 | Worker timezone harness, stale fixture and wording fixes | Browser rerun (desktop/emulated mobile), full worker/planning suites, 5.4c HA-plugin suite (Windows `fcntl` gap: unrun, not failed) | B below |
| Stage 14 mocked suites | Yes (focused isolated runners) | Not the suites above; no live observation | — |

**B. Outstanding local review/acceptance (not feature work; blocks nothing in the queue).** (1) **5.7b3:** run
the three unrun suites only if the user asks; report them as unrun until then. (2) **Coordinator review** of the
`[x]` items archived as “review pending” (5.x, 6.2/6.3, 9.x, 10.x, 12.x, 14.x) is independent of the queue; each
◆ substage also reruns the Stage 14 files.

**C. User-owned, never an LLM task** (any HA access needs specific approval, read-only first; never print the
`homeassistant` token): **5.1** visual approval; **5.8** merge, install and deployed validation (including whether the
2.5.126 plug-in fix, the 2.5.127/128 session card, Stage 14 stability and Stage 10 controls work on hardware, and
whether the installed OCPP integration exposes `charger_generation`); E1 and E2; any hardware test.

## 10. Closed and superseded (do not reassign)

Stage 11 is **superseded `[>]` and not implemented**. Source fact: nothing is sampled by the learners under
Morek ownership, while both stores already feed `_morek_input_evidence` (`_learned_energy_for`,
`_plan_power_cap_kw`); only the feed and safe behind-plan use are missing.

| Former Stage 11 requirement | Destination |
| --- | --- |
| 11.1 inspect how samplers get genuine power/energy and fresh SOC; does the Morek path feed them | Done as the source audit above (answer: no); connection = 15.9a |
| 11.1 extend the smallest seam; only trustworthy measured sources and vehicle association; never learn from scheduled current, ACK/readback, estimated SOC or missing data | 15.9a |
| 11.1 reuse sample-quality, trust, bounds, persistence | 15.9a (reuse) and 15.9b (rule changes) |
| 11.1 keep normal estimates and show learned as unavailable until evidence suffices | 15.9a fallback; display in 15.11 |
| 11.2 connect learned power and energy to the planner | Already wired; feed: energy 15.9a, power 15.10 |
| 11.2 slower charge gets more time; behind-plan triggers a fresh plan reconciled only through the guarded owner | Energy: 15.9b (trust rule); power and PlanWatch: 15.10 |
| 11.2 respect Pause/Stop, price/minimum-SOC policy, unavailable inputs, limits, unknown writes; report infeasible; never promise the target | 15.10 exclusions/acceptance and the §5 contract |
| 11.2 tests (reliable/insufficient samples, wrong initial estimate, interrupted or slow charging, stale readings, restart, vehicle change, safe replans) | 15.9a/15.9b/15.10 acceptance |
| Deployed testing is the user’s; the BMW limit stays separate | §1, §9.C |

Also closed as locally implemented (children all `[x]`): umbrellas 5.4 and 5.6; 9.6/9.7 recorded `[x]`.
Everything else in the archive that is not listed above is either done (§2) or carried.

## 11. Reference (archive, frozen)

[Archive](archive/charging-dashboard-roadmap-2026-11-14.md) sections to consult: “Stage 15” (settled decisions,
audit table, reconnect model, original substage text), “Learning rules”, “Status wording”, “Terminology: ready
versus waiting”, “Active charge control while offline”, “Research findings” and “Safe user test”,
“6.1 source inventory”, “Stage 14” (14.1–14.6 implementation detail), Stage 6.2/6.3 entries (data model, bounds,
limits). Rule: when this file and the archive differ, this file wins; copy requirements here before assigning
them, never assign from the archive.
