# Active roadmap — Morek charging, HA sidebar and trustworthy history

Status: **Stage 20 UI redesign is planned; Stage 19 is locally implemented with coordinator review pending. This is the only work queue.** Created 2026-11-14 by splitting the old roadmap, which
is now frozen as a historical reference:
[archive/charging-dashboard-roadmap-2026-11-14.md](archive/charging-dashboard-roadmap-2026-11-14.md)
(“the archive”). Initial audit basis: manifest 2.5.128, HEAD `6a50a7ae`. Stage 15 is locally implemented and coordinator-reviewed through 2.5.143 with focused mocked checks; see its entries and the handoff for unrun checks. Stages 16, 17, 13 and 18 are implemented locally and committed. Stages 7 and 8 are locally implemented and coordinator-reviewed through 2.5.178 (2026-11-16), with each substage committed and pushed separately. **Stage 19 (ahead-of-time schedules and recoverable upload uncertainty, 9 substages) was planned 2026-11-18 and is implemented locally through manifest 2.5.199 (all five remaining groups, mocked/isolated tests only, coordinator review pending). It is NOT hardware-verified: charger ordering, late old frames, replacement semantics, retained-profile behavior and R1–R7 remain user-directed evidence tasks.** Earlier feature substages are recorded as locally implemented; §9 retains outstanding reviews, open research and user-owned validation. Nothing below is
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
| Stage 7.1–7.5 | **Refined and carried** into Stage 7 below (7.3 split into 7.3a/7.3b; 7.4 into 7.4a/7.4b). |
| Stage 8.1–8.3 | **Refined and carried** into Stage 8 below (8.2 and 8.3 each split a/b); D1 spot-only costs and D2 day-average savings are settled (§9). |
| Stage 11 (11.1/11.2) | **Superseded `[>]`**, migrated to 15.9a/15.9b, 15.10, 15.11 (exact table in §10). |
| Stage 13.1–13.4 | **Carried** into Stage 13 below, unchanged in scope. |
| Stage 19.1–19.9 (2026-11-18) | **Implemented locally (2.5.199), mocked tests only; hardware unverified.** Amends the §5 contract only as its own table states. |
| Stage 15.1–15.11, E1, E2 | **Stage 15 locally implemented and reviewed** through 2.5.143; E1/E2 remain optional user-directed evidence tasks. Split a/b ids stay stable. |
| Archive B1/B2/B3/B4/C1 detail | Delivered by Stages 5–6, 12 and carried by 7–8. Obsolete wording (Sections host, A/B chart switch, per-stage “Done when”) is dropped. |
| Archive C2 “finish the product” | Covered by Stage 12/13 plus the 8.1 session rows; no separate stage. |
| Archive §6 “decisions still to settle” | D1/D2 are settled; D3 preserves current retention, with any extension a separate future decision (§9). Visual approval is 5.1. |
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
| 16 | 13.1 Vehicle sources and planning properties | none | ✔ local, committed `d81c3fd8` (2.5.158) |
| 17 | 13.2 Market and charging-cost settings | none | ✔ local, committed `7e352562` (2.5.159) |
| 18 | 13.3 Practical plan and charger parameters | 15.1b if built (no duplicate reserve control) | ✔ local, committed `416529c3` (2.5.161) |
| 19 | 13.4 Notification settings and setup diagnostics | none | ✔ local, committed `e31463df` (2.5.162) |
| 20 | 7.1 Available-day navigation (one small read command + UI) | none | |
| 21 | 7.2 Chart interaction and DST/resolution fixes | 7.1 (same chart files) | |
| 22 | 7.3a History client, small backend delta (truncation/retention signals) and evidence panel | none (Stage 6.3 API exists) | |
| 23 | 7.3b Aligned tracks on the price axis | 7.3a, 7.1 | |
| 24 | 7.4a Live price-insight methods (backend) | none | |
| 25 | 7.4b Monthly price statistics (backend) | 7.4a | |
| 26 | 7.5 Live price insights and monthly statistics (UI) | 7.4a, 7.4b | |
| 27 | 8.1 Day review (default yesterday) | 7.1, 7.3b (needs 7.3a) | |
| 28 | 8.2a Spot-only cost of measured energy (backend) | 7.3a | |
| 29 | 8.2b Cost display and totals consistency | 8.2a, 8.1 | |
| 30 | 8.3a Savings baseline (backend) | 8.2a | |
| 31 | 8.3b Savings and summary cards | 8.2b, 8.3a, 7.5 | |
| 32 | 19.1 Upload-outcome classification: provably pre-dispatch vs truly ambiguous | none | ◆ |
| 33 | 19.2 Safe ordered replacement and late-response handling | 19.1 | ◆ |
| 34 | 19.3 Persistent paced retries and durable, actionable observations | 19.1, 19.2 | ◆ |
| 35 | 19.4 Ahead-of-time schedule, effective verification and offline operation | 19.1 | ◆ |
| 36 | 19.5 Planner fallbacks and active-window stability under the new triggers | 19.4 | ◆ |
| 37 | 19.6 Session start unknown and reboot recovery | 19.1, 19.2 | ◆ |
| 38 | 19.7 Storage, ownership and connection blockers | 19.3, 19.6 | ◆ |
| 39 | 19.8 Cross-cutting scenarios, evidence-wording audit, documentation closure | 19.1–19.7 | |
| 40 | 19.9 Resume recovery, blocker clarity and reconnect stability | 19.1; coordinates with 19.2/19.5 | ◆ |

Items 1–15 (Stage 15) are locally implemented and coordinator-reviewed through 2.5.143; Stage 16 and Stage 17 (below) and items 16–19 (Stage 13.1–13.4) are implemented locally and committed (2026-11-16 audit: `git log` shows 16.2 `08254d2e`, 17.1 `d9ec44cc`/`999f5fc5`, 17.2 `cc321c71`, 17.3 `e0f0d7d4`, 17.4 `7fadb671`, 17.5 `4bb08550`, 17.6 `35f5ae5f`, 13.1 `d81c3fd8`, 13.2 `7e352562`, 13.3 `416529c3`, 13.4 `e31463df`). Do not reassign any of them. **Items 20–31 (Stages 7/8) are complete locally and coordinator-reviewed through 2.5.178; items 32–40 (Stage 19) are implemented locally through 2.5.199 with coordinator review pending. Stage 20 below is the new implementation queue.** None is a prerequisite for 5.8. The order is the suggested default and the user may reorder it within the “Needs” column. **D1/D2 and the Stage 19 automatic-recovery direction are settled; D6 applies only if 19.5 finds a genuinely unresolved product choice.** No Stage 20 implementation is authorized by this planning entry. Stage 7/8 substages are not ◆ (they touch no Stage 14 path) but obey the “Binding constraints” block at the start of Stage 7. **Not in the queue:** §9.B reviews, §9.C user-owned items, E1/E2.

## Stage 20 — Complete charging sidebar UI redesign (planned, not started)

**Planning basis:** source 2.5.199, Stage 19 implemented locally but coordinator review pending; no live or hardware verification implied. Visual reference: [design handoff](../samples/spotnav-ui-handoff/SPOTNAV_UI_UX_DESIGN.md), [interactive prototype](../samples/spotnav-ui-handoff/demo/spotnav-pulse-v4-interactive.html) and reference screenshots; [source inventory](ui-ux-redesign-inventory.md) is a 2.5.178 historical lead, so recheck current code. This stage replaces the old sidebar presentation across all its workflows, not merely Overview. The prototype has four navigable views, fictional data and simulated/placeholder interactions. It contains a clean connected-car scene and other images with baked-in values; it is a visual reference, not production code. Build real responsive components. Preserve the shared panel/preview renderer, ECharts and current backend behavior; no new charging features or planner logic. Existing backend changes only where necessary to expose already-existing facts or support the redesign, with specific justification and existing guards intact.

**Navigation and artwork decisions:** Use top navigation for Overview, Explore, History and Settings on desktop and persistent bottom navigation on mobile. Use the prototype’s clean embedded BMW/Morek scene when suitable to ship, with truthful state treatment and an accessible asset-failure fallback. The two images with baked-in battery values are not live UI assets.

**Settled scope (user, 2026-11-18):** Redesign the entire custom sidebar from scratch for the user's white 2022 BMW iX3 and Morek charger only. No multi-vehicle artwork or other charger support is required by this redesign. The inherited original SpotNav Lovelace card is not needed; it is outside the sidebar redesign and must not constrain the new UI. Its exclusive functions are not a requirement to migrate into the sidebar. Do not delete the integration, change its `spotnav` domain, or remove shared backend code merely because the card is not needed. Card removal is not an implementation task in this stage; treat retirement/removal as a separate explicitly scoped change if requested. The hero must show this BMW and Morek; use state-appropriate presentation that does not falsely assert a connected cable or measured flow. Source or produce a clean usable scene without baked-in labels, verify rights, and handle asset failure accessibly.

**Design adjustments:** Extend the Overview-only proposal to history, price insights, settings, diagnostics and recovery, with a coherent new visual language throughout; preserve discoverability and existing capability. Treat its hypothetical controls, per-window metrics and animation as conditional on actual current data, permissions and evidence, not requirements to invent fields. Price and history retain existing basis, coverage, DST and navigation semantics. Keep HA shell navigation rather than duplicating the mock sidebar. Maintain accessibility, clear unknown/stale states and source timestamps. Stage 19 recovery and uncertainty wording must be audited against current source, not the older inventory. Do not replace existing action gates, draft/revision handling or lifecycle reconciliation with demo code. The existing non-admin settings mismatch must be represented accurately without broadening permissions.

**Shared acceptance for every substage:** one fresh implementation session in order, production wiring plus focused fast tests, preserve existing capabilities and unrelated work; follow §4, manifest/build/dist requirements and safety boundaries in AGENTS.md. Implementation sessions do not access or deploy to live HA; checkpoint installation is a separate user-directed operation as described below. Any change to a protected execution path is ◆ and must meet §5 including applicable Stage 19 amendments; frontend-only work must not alter those paths. Reconcile updates without losing drafts, selection, focus, scroll, chart zoom or pending/unknown actions. Test meaningful permissions, conflicts, stale/unknown values and read-only navigation where relevant. Each substage is sized for one focused session, with functionality and tests together; splitting further is allowed only if a concrete dependency makes it necessary. No browser testing unless separately authorized under the current fast-test restriction; record visual/live validation as unrun. User-directed hardware validation remains separate.

**User feedback checkpoints (planned 2026-11-18):** Implement and review one substage at a time; then prepare a deployable checkpoint for the user's visual/UX feedback. Stop after each checkpoint until the user decides to continue or requests corrections. Do not describe a partially redesigned app as complete. All visible sections use the new visual language from the combined 20.2a–20.2c release onward; later substages refine functionality and detail. No permanent parallel sidebar UI.

| Checkpoint | Substages | What the user can judge |
| --- | --- | --- |
| A — first impression | 20.1, 20.2a–20.2c | Real tab navigation and responsive shell, BMW/Morek hero, live situation and existing charging controls. All tabs and the chart use the new visual language; every existing workflow remains reachable. Judge desktop/mobile proportions, artwork, readability, navigation, status and control placement. |
| B — plan and prices | 20.4–20.6 | New price chart, proposed windows with linkage, strategy and real plan editor. Judge chart clarity, window scanning and settings interaction. |
| C — analysis | 20.7–20.8 | Redesigned Explore and History, including real data coverage and cost distinctions. Judge navigation, legibility and usefulness. |
| D — system and settings | 20.9–20.11 | Redesigned evidence/diagnostics and complete settings workflows. Judge organization and accessibility of actions and information. |
| E — completion | 20.12 | Remove temporary old presentation and verify the entire product and navigation; final visual acceptance. |

**User review after 20.1:** Navigation direction approved; live screenshots show the old host/header detached from the shell and an Overview collapsed into a narrow overlapping column. The user wants the next installed version to use the new visual language on every tab. Split the work below into individually reviewed, bounded slices; do not install an intermediate slice. A previous oversized delegate was interrupted and left uncommitted cross-cutting work: inspect and preserve it, separate or adapt it carefully, and do not assume it is complete. No live charger operations.

- [x] **20.2a Layout and host integration.** *(LOCAL, 2.5.201, 2026-11-18: implemented with focused jsdom/structural tests only; coordinator reviewed host/layout changes and reran 10 focused host tests; browser/visual, live and hardware checks NOT done; see the 20.2a report below.)* Fix the collapsed/overlapping layout at its root; integrate HA menu, charger selector, refresh, existing controls and meaningful warnings into the shared new shell with coherent spacing. Keep action controllers and guards unchanged; retain all content and functional destinations. Fast focused tests cover real host, responsive layout structure, state, warning visibility and no tab-triggered writes. No hero or wholesale tab restyling required for this slice.
**20.2a report (2.5.201).** *Layout root cause:* the legacy `styles.css`/`dark.css` still defined `.dashboard` named `grid-template-areas` (5fr/7fr) plus viewport `@media` rules; under the new tab wrappers and the narrower HA panel they collapsed and overlapped cards. They are removed; `shell.css` auto-places one column per tab from the measured `data-sn-layout` (2 columns only on wide Settings), and `charge-now-layout.test.ts` now forbids named areas and viewport width media queries. *Host integration:* the separate `.hostbar` strip is gone. `shell.js`/`dashboard.js` render one header (HA menu, charger select, Refresh) and one status stack above the tabs on every tab (host message, critical warning, charging status, schedule check, recovery; one element each; a held/disconnected shell shows only the host message, never a stale warning); `panel.js` keeps every controller and gate and only supplies models (`automaticModel`, `chargeNowModel`, `sessionModel`, `checkModel`, `recoveryModel`) plus callbacks (`hostActions`). Existing Auto Pause/Resume and Charge Now controls keep their ids, gates, durations, custom end, replace/return-to-auto, and render in the Overview hero (no longer on every tab); typed duration/end survive re-render. Fix found while testing: `selectCharger` repainted the shell with the previous charger before the new one was set. *Carried from the interrupted delegate, unreviewed and belonging to 20.2b/c:* the hero scene/artwork (`shared-dashboard/art/*.webp`, provenance and rights NOT yet recorded), SOC/target hero, restyled cards/charts/dialog and the dark/shell CSS for all tabs, the preview sample-adapter shell parity and artwork bundling in both build scripts. Not done: hero acceptance and truthful-state tests (20.2b), per-tab restyle review (20.2c), any browser check, 20.3. Fast checks only (see the final report for the exact commands/results).

- [x] **20.2b Overview and hero.** *(LOCAL, 2.5.202, 2026-11-18: implemented with focused jsdom/node tests only; coordinator review, browser/visual, live and hardware checks NOT done; see the 20.2b report below.)* Implement the white BMW/Morek hero, existing action placement and truthful state variants; restyle existing Overview chart and summaries in the new visual language without new chart features. Preserve evidence and safety semantics, existing behavior and accessibility. Fast tests cover data freshness, unknown/zero, connection states, controls and layout. No Explore/History/Settings redesign in this slice.
**20.2b report (2.5.202).** *Artwork provenance (new `shared-dashboard/art/PROVENANCE.md`):* `bmw-morek-scene.webp` is byte-identical to the first embedded WebP of the supplied prototype (sha256 prefix `b5a0591e45fe4866`; no baked text/SOC); `bmw-neutral.webp` is a re-encoded crop (x 0–930, y 40–675) of it with no charger, port or cable; the two prototype images with a baked “64%” are not used. **Rights/licence of the images could not be verified from the repo (supplied by the owner, apparently generated art): shipping them is the owner’s decision and is recorded as open.** *Truthful scene:* the cable picture is shown only for a fresh connected report (`sceneOf`: connected and not stale); unplugged, unknown and stale connected use the neutral crop, the chip text says “Not plugged in” / “Plug state unknown” / “Last reported … · stale”; images are decorative (`role="img"` + description), no animation, no flow imagery, and a missing file leaves the gradient and all text. The production adapter still derives the plug state only from a fresh Morek status (`ready.vehicle` ≤ 180 s). *Hero:* SOC and a slim meter with a target tick sit on the scene, labelled reported / “Last known SOC · stale” / “Estimated SOC · not a measurement” / unknown (nothing drawn without a valid value); metrics are Measured now (host text, 0 and Unknown stay distinct), a new “To target · est.” (existing `batteryEstimates`, only when SOC, target and capacity are valid, labelled an estimate), Estimated charge cost and Until deadline; the old battery card with its assumptions is kept but collapsed under “Battery estimates & assumptions”. Existing Auto Pause/Resume and Charge Now controls, ids, gates and the next-window dialog trigger are untouched. *Chart presentation:* card title “Electricity prices & charging plan” (the two-mode comparison keeps “· Bars/Stepped area”), ECharts axis/grid/tooltip colours moved to the shell tokens; no new chart features. *Tests:* `frontend/test/hero-overview.test.ts` (13: scene mapping incl. stale/unknown, adapter plug evidence, SOC/meter states, zero vs unknown power, To-target gating, collapsed assumptions, controls in the hero, asset identity/provenance/CSS urls) plus a rerun of shell-tabs, shell-host-integration, charge-now-layout, dark-theme, daily-overview, sidebar, sidebar-learning-reset, history-day-panel, chart-tracks, chart-render (all passed) and prototype `sample`/`daily-sample` (pass); `prototype/vehicle-evidence.test.mjs` still has its 2 failures that predate 20.1 (stale `batteryEstimates` expectations; not touched). Manifest 2.5.202, `npm run build`, `npm run check-dist` and `prototype:build` passed. **Not done / unrun:** any browser or visual check (hero text contrast over the scene, crop positions at desktop and phone widths and the 340–380 px hero height are unseen), live HA, hardware, full suites, backend tests (no backend change). *Unrelated or unfinished work still in the tree:* the 20.2c restyle of Explore/History/Settings cards (dark.css/shell.css/styles.css) is carried from the interrupted delegate and unreviewed; the 20.2a changes are uncommitted; the sample preview shows the connected scene for its fictional connected scenarios and has no unplugged scenario.
- [x] **20.2c Other tabs and combined release.** *(LOCAL, 2.5.203, 2026-11-18: restyle finished with focused structural/jsdom tests only; coordinator review of the combined 20.2a–c tree, browser/visual, live and hardware checks NOT done; commit/push/install NOT done; see the 20.2c report below.)* Restyle existing Explore, History and Settings surfaces consistently, preserving every existing workflow, drafts, permissions, cross-links and data semantics. Review all three slices together, check that no old visual presentation remains visible and no destination is empty, then commit/push/install the combined result and wait for the user's judgment. Fast focused tests, mandatory build and check-dist only; no long-running suites or browser tests. Later substages refine functionality rather than redo the visual migration.
**Coordinator review:** Reviewed the combined layout, host/controller separation, hero evidence mapping and asset route; 27 focused host/hero/tab tests passed. Actual visual and canvas behavior remain unverified. Stage 20.3 remains partial as listed below.

**20.2c report (2.5.203).** *Inspected and preserved* the interrupted delegate's restyle and 20.2a/b work (nothing reverted). *Finished:* `styles.css` base rules for history/insight banners, history verdict borders, insight table lines and price-nav notes no longer carry light-theme colours (tokens only); `shell.css` gains a 20.2c section giving History (day navigator, one-day sections, energy-basis and spot-cost/savings cards, sessions, digest, banners, chart frames), Explore (controls, insight lines/comparison/details, price navigator) and Settings (help, notices, the four advanced groups' details, evidence grid/status, track lanes) the same surfaces, radii, tokens and 44 px controls as Overview, plus `wa-button` sizing; the history power chart line/area use the mint accent. Classes that previously had no rule at all (day label, digest, retention/price/month notes, summary) are styled. No markup, controller, permission, draft, cross-link, data-semantics or backend change; no new feature. *Tests:* new `frontend/test/tab-visual-migration.test.ts` (4: every class the Explore/History/Settings views emit has a rule, no light literals left in styles.css, no named grid areas or viewport width queries, every destination renders content with no placeholder and the editor/evidence/history/insights homes are present); focused rerun of 10 files (shell-tabs, shell-host-integration, charge-now-layout, dark-theme, hero-overview, sidebar, sidebar-learning-reset, history-day-panel, chart-render, chart-tracks: 210 passed) and the 20.3-related controller files above (114 passed). Manifest 2.5.203, `npm run build`, `npm run check-dist` and `prototype:build` passed. *Not done / unrun:* any browser or visual check (so "no old visual style visible" is verified only structurally, not seen), live HA, hardware, full suites, backend tests; artwork rights remain the owner's open decision; the `vehicle-evidence` prototype test's two pre-existing failures are untouched. Nothing is committed, pushed, installed or deployed; 20.2a/b/c are one uncommitted combined tree awaiting coordinator review. **20.2c is therefore implemented locally, not accepted.** Gaps found by the 20.3 assessment (not fixed; 20.3 stays open): (1) Charge Now and Return to Auto confirm through the native `window.confirm` (panel.js:405–406), not a dialog in the new visual language (Pause/Resume Auto have no confirmation, as before). (2) Pause/Resume and Charge Now render only in the Overview hero; on Explore/History/Settings the status stack shows recovery/blocker text ("Resume Auto first", recovery banner) with no in-context link to the controls. (3) The recovery banner (status stack) and the Resume control (hero) are not visually associated, and `automaticModel` still emits one dense semicolon string (intent; request; ACK; readback; blocker) rather than structured, scannable lines. (4) Pending/unknown outcomes are plain `.sn-note` text; buttons carry no `aria-busy`, and an unknown dispatched outcome ("do not retry blindly") has no distinct persistent treatment beyond that text and the existing blocker latch. (5) The preview control model is inert by design (no fabricated success), so busy/unknown/recoverable states are not demonstrable in the preview without new fixtures. (6) No new controller-boundary tests were written for 20.3; the existing guards pass (charge-now, recovery-banner, sidebar-resume-recovery, actions, action-error, charge-session-panel, charge-session-freshness: 114 tests), and role/freshness, pending, timeout/unknown, recoverable-resume and Stop-precedence remain behaviourally unchanged but are not re-asserted against the new hero placement beyond the 20.2a/b tests.

Each slice is independently reviewed; do not promise equal effort or introduce unneeded features. Build/dist/version requirements in AGENTS.md apply to integration changes. The user explicitly prohibits long-running expensive tests; use focused short-timeout checks and report unrun validation.


**Checkpoint A implementation contract:**

- **Navigation and temporary content:** Overview opens by default. On wide layouts put Overview / Explore / History / Settings in a visible top navigation within SpotNav; on phone widths use a persistent bottom bar with all four labeled destinations, safe-area padding and no content or controls obscured. The exact breakpoint follows available panel width. Keep the HA menu control for the host's own navigation. All four destinations work from 20.1: Overview contains vehicle/charging situation, existing price/plan chart and compact recent history; Explore contains existing price insights; History contains the existing detailed history/day/month controls; Settings contains the existing plan editor, four advanced groups and diagnostics/logs. Move existing views intact where needed until their assigned redesign, preserving cross-links. No placeholder-only or dead tabs; each current sidebar capability has exactly one reachable canonical home, though concise summaries may link to it. If moving a region would break state or controls, keep it reachable via a clearly labeled link while fixing the integration before the checkpoint.
- **Appearance:** Use the v4 Overview screenshot's deep-blue surfaces, high-contrast white type, mint accents and cinematic scene as the visual target, with responsive card layout and no second HA rail. Hero hierarchy: situation and short explanation at top left, next proposed window top right when space permits; SOC/target over the car where legible; measured power, distance to target, planned time and forecast cost below, each only where supported; existing charge actions adjacent. On narrow screens reflow rather than scale the desktop. The chart and all other visible surfaces must use the new visual language by 20.2c; detailed chart features remain in checkpoint B. No mock prices or SOC. Preserve useful status and recovery messages on all tabs without repeating identical banners.
- **Artwork and truthful state:** Extract the clean embedded scene (first WebP, without a baked SOC) if suitable and record provenance; its cable is visibly connected. Use it only when current evidence supports connected presentation. For unplugged or unknown state, use a state-appropriate BMW/Morek variant or a neutral crop/treatment that does not show a connected cable; text remains authoritative. Asset failure must leave the content legible. Do not fabricate cable-flow animation; motion may be omitted entirely.
- **Actions and interaction:** Place Charge Now and Pause/Resume with the hero, with fixed-end and Return to Auto available when applicable; preserve all current choice durations, custom end, confirmation, role and safety gates and pending/unknown feedback. Tab changes and refresh must not discard editor drafts, active dialog, focus, selected chart range or relevant scroll; navigate without an action or replan. Never make a stale success message imply a charge is physically flowing.
- **Checkpoint A acceptance:** Each 20.2a–20.2c slice is independently reviewed and testable; at the checkpoint, four tabs and all previously reachable sidebar workflows work, the shared preview renders the same shell and hero from fixtures, and actual host actions stay connected to their existing controller. Focused tests cover tab switching and reconciliation, connected/unplugged/unknown plus stale/zero/flow, permission and unknown action outcomes. Build, check-dist and version bump apply. User judges appearance and interaction in HA at desktop and phone widths; screenshots or fixture tests alone do not constitute visual approval. No browser suite is implied by this plan. Record visual, live and hardware checks truthfully.

**Later design specificity:** The prototype offers examples for Explore, History and Settings, not finished specifications. Their respective substages must produce complete layouts using the same tokens and actual existing workflows, rather than copy demo-only controls or invent calculations. Checkpoint feedback can refine those layouts before their implementation; no additional product decision blocks starting 20.1.

**Checkpoint procedure:** Finish and independently review the included substages, run focused checks and required build/dist verification, then commit/push only when authorized. Confirm exactly what is installed and what version/commit would be installed: source 2.5.199 includes Stage 19 backend work not yet coordinator-reviewed or hardware-verified, so installing the current tree could change more than the UI. Do not assume a Git push or API token installs a custom integration. Establish the actual supported update route and rollback path first, beginning with read-only diagnostics against the verified HA host; never print credentials or household data. The user has proposed `ha_access_token` for future access; its presence and relationship to the documented `homeassistant` variable have not been checked, and no token should be sent until the target host is verified. Live file changes and charger operations remain subject to AGENTS.md. The user authorizes restarting HA when needed to activate an authorized integration version installation; no separate restart approval is needed in that case. User installation/visual review is distinct from an OCPP command or physical charging test. Report installed version, validation limits, and rollback procedure. Capture feedback before starting the next checkpoint.

**Detailed source/design assessment:** [UI overhaul assessment](ui-overhaul-assessment.md). Its proposal corrections supersede the proposal's Overview-only scope, hypothetical data and suggestion to leave other views unchanged. Dependencies below are sequential; each slice replaces the assigned surface in the real panel and preview, with focused tests. Temporary old sections may remain only until their assigned replacement lands; the stage is incomplete until cleanup. These slices are approximately comparable session-sized units, not claims of identical effort; split an unexpectedly large slice at a working, tested boundary and update the queue first.

- [x] **20.1 Shared shell, navigation and state contract.** *(LOCAL, 2.5.200, 2026-11-18: implemented with focused jsdom tests only; coordinator review, browser/visual, live and hardware checks NOT done; see the mapping below.)* Replace the sidebar's visual frame with the new responsive token system, HA-compatible header, plainly visible Overview/Explore/History/Settings navigation and loading/empty/error surfaces. Make switching tabs easy on desktop and mobile, preserve drafts and relevant viewport state across tab switches, and keep critical warnings reachable on every tab. Inventory current 2.5.199 host actions/status and map every old region to its destination; wire actual charger context and observation refresh in live and preview without duplicating controllers. Preserve shadow isolation and epochs. Acceptance: real and fixture hosts render the same shell; refresh, changed charger, unavailable data and keyboard navigation work; no second HA rail. Tests: focused shell/adapter and lifecycle cases. Deliver mapping for later slices.

**20.1 delivered shell and mapping for later slices (2.5.200).** Shared files: `shared-dashboard/shell.js` (tab/nav/summary markup), `shell.css` (deep-blue `--sn-*` tokens, header, nav; built into the panel CSS and preview as a third stylesheet) and `dashboard.js` (tab state, keyboard, layout measurement). The shell lives in the shared renderer, so the panel and the preview render the same header and four tabs from the same model. Tab choice, per-tab scroll and the layout class are view state only: all four panels stay mounted (the inactive ones `hidden`), so drafts, focus targets, the plan dialog, chart zoom and pending/unknown action state are untouched by a tab change or refresh; a charger change resets drafts as before but keeps the tab. A tab change sends no request and calls only the optional `actions.tabChange(name)`. Layout is chosen from the measured width of the mount root (`data-sn-layout` compact below 760 px, otherwise wide): top tab bar when wide, persistent bottom bar with safe-area padding when compact. The HA menu button stays in the host bar; no second HA rail.

| Old region | 20.1 home | Later slice |
| --- | --- | --- |
| Host bar (menu, charger select, Refresh, Auto Pause/Resume, Charge Now and its duration/change-end controls), charge-session, schedule-check and recovery banners, host message | Unchanged in `panel.js`, above the tabs on every tab (restyled with the new tokens only) | 20.2 hero / 20.3 move actions and banners into the new UI; they are the single action controller |
| Critical-live warning (`m.warning`) | Above the tabs on every tab; its details link switches to Settings and opens the evidence details | 20.2 situation headline |
| Your vehicle (SOC, next window, metrics) | Overview | 20.2 hero |
| Prices & plan chart, price day navigation, evidence tracks | Overview | 20.4 / 20.5 |
| Recent charging (day/month review, spot cost, sessions, power chart) | History (the one canonical home) plus a new Overview summary card that restates only the history model state, day label, spot-cost headline and session count and links to History | 20.8 |
| Price insights | Explore | 20.7 |
| Plan controls (plan editor) and the proposed-plan dialog | Settings (editor); the dialog is global and opens from Overview or from the editor | 20.5 / 20.6 |
| Plan activity & freshness (evidence, Morek debug controls) | Settings (diagnostics) | 20.9 |
| Vehicle sources; Market & costs; Plan & charger parameters; Notifications & setup | Settings (four advanced groups, unchanged) | 20.10 / 20.11 |
| Admin log viewer | Appended after the tabs by the host (admin only) | 20.9 / 20.11 |

Cross-links: setup-check `data-goto`, the critical-warning details link and History’s “Show this day on the price chart” switch to the destination tab before scrolling (the last one then shows the price chart on Overview). Known limits of 20.1: card visuals are still the old ones inside the new frame (no hero/artwork yet); the host bar remains a separate strip above the shell; Overview shows the full-width vehicle card until 20.2; the 760 px breakpoint and the tab layout were not seen in a browser; ECharts in hidden panels relies on the existing ResizeObserver to size on first reveal (jsdom cannot show that).
- [>] **20.2 Hero, situation and artwork — superseded by 20.2a–20.2c above.** Build clean BMW iX3/Morek visual composition, SOC/target, next proposal and measured-power/estimate fields from existing data. Provide correct connected, unplugged and unknown presentation and asset-failure fallback; no baked-in data or false flow animation. Centralize situation headline without suppressing serious warnings. Acceptance: fresh/stale/missing/zero SOC and power, disconnected, reported-only and measured-flow states are distinct; selected illustration never claims unsupported connection. Test state mapping and accessibility labels. No new backend fields.
- [x] **20.3 Charging actions and recovery feedback — *(LOCAL, 2.5.204, 2026-11-18: implemented with focused jsdom tests only; coordinator review, browser/visual, live and hardware checks NOT done; not committed/installed; see the 20.3 report below.)*** Place existing Pause/Resume, Charge Now, change end and Return to Auto in new UI, including existing durations, custom fixed end, confirmation and status. Integrate recovery and unknown outcomes in context using actual Stage 19 state. Preserve all existing admission, ownership, protection, permission, generation and pending latches; preview uses fixtures/callbacks, not fabricated live success. Acceptance: role/freshness changes, pending, timeout/unknown, recoverable resume and Stop precedence remain correct; focused controller-boundary tests.
**20.3 report (2.5.204).** *Action confirmation:* Charge Now, Replace end and Return to Auto no longer use the blocking `window.confirm`; `chargeAction` now only validates and opens an in-page, non-modal `role="alertdialog"` (`#charge-confirm`, labelled/described, Cancel and a specific confirm label, text unchanged: fixed end, price/cap, replace-from-now, “not a persistent Pause”). Pause/Resume Auto still have no confirmation (unchanged). *Race design:* the old synchronous confirm could not see a change; the async one revalidates in `chargeConfirmProblem` (charger, generation, permission epoch, connection, **every** `chargeNowBlocker` admission/identity/ownership/pause/uncertainty gate, and the Charge Now state/intent id it was opened for) at open, on every paint (so a Pause, permission loss, new override, stale status or unknown outcome closes it with “Confirmation closed; nothing was sent. <reason>”) and again at confirm time, immediately before dispatch. The polled status object identity is deliberately no longer compared (it changes every refresh); its meaning is. The confirmation is cleared synchronously before `chargeBusy` is set, so a double click sends once; `stopObservations`/charger change drops it; the duration/end chosen at open is the exact end shown and sent (an end that has lapsed by confirm time is refused, nothing sent). Cancel and Escape send nothing. Pause (Stop) is untouched and still takes precedence: it closes the confirmation via the blocker. *Focus:* opening moves focus to Cancel; closing while focus was inside returns it to the opener (`#charge-now`/`#charge-replace`) or to the status line if that control is now disabled/busy. *Feedback:* the model now carries a derived `chargeKind` (`pending` while in flight, `uncertain` while any unknown-outcome latch holds, otherwise `info`), `aria-busy` on the busy buttons, a persistent “unknown outcome; do not retry blindly” note with `role="alert"` and its own treatment instead of plain text, and the existing refusal/recorded texts unchanged. *Recovery to controls:* the recovery banner (visible on every tab) has a “Show charging controls” navigation button that switches to Overview and focuses the first usable of Resume / Charge Now / Pause (or the controls box); it sends nothing. *Preview:* `?control=confirm|pending|uncertain|recorded|refused` fixtures (fictional, display-only, no callbacks, no fake success) render the same markup in the shared preview. *Not done, explained:* (a) restructuring `automaticModel`'s dense `autoState` string into scannable lines was NOT done: its wording is asserted by the existing guard tests and the banner/blocker text already surfaces the important parts; revisit with the Stage 20.12 cleanup if the user finds it hard to read. (b) Pause/Resume are not duplicated on other tabs (one canonical home, reached by the new link). (c) No new backend field or controller. *Tests:* `charge-now.test.ts` rewritten for the in-page confirmation (23 pass, including new races: Pause / permission loss while open, stale override, double click, routine refresh, generation change, focus and Escape, recovery link) and new `charge-feedback-render.test.ts` (3); 13 focused files re-run (112 passed: shell host/tabs, hero, layout, tab-migration, recovery banner, resume recovery, schedule-check, charge-session, action-error, dark-theme) and prototype `sample`/`daily-sample` (12 pass). Manifest 2.5.204, `npm run build`, `npm run check-dist`, `prototype:build` passed. **Unrun:** browser/visual check (focus ring, confirmation placement on phone width, hero layout with the box open), live HA, hardware, full suites, backend tests (no backend change).

- [x] **20.4 Prices chart and evidence tracks.** *(LOCAL, 2.5.205, 2026-11-18: implemented with focused jsdom tests only; coordinator review, browser/visual, live and hardware checks NOT done; not committed/installed; see the 20.4 report below.)* Redesign the production ECharts chart, controls and legends to match visual direction while retaining absolute bands, comparable cap, published gaps, existing bounded date navigation and independently sourced proposal/sent/effective/measured lanes aligned through zoom and resize. Acceptance: actual 15/60 minute and DST days, negative prices, unknown currency, partial publication and unloaded or conflicting evidence display truthfully. Focused chart, track and price-navigation tests; no new read-triggered writes.
**20.4 report (2.5.205).** *Scope:* presentation only, frontend only; no backend, controller, request or action change. *Chart (`charts.js`):* ECharts colours (axis, dashed grid, grid fill, tooltip with accent border and radius, zoom slider with accent handles, past-time shade, cap label) follow the shell tokens; interval bars have rounded outer corners (top for a positive price, bottom for a negative one) and a 1 px hairline between wide bars while keeping each interval's exact start/end; the stepped-area mode is unchanged. Grid margins (48/20/82/92 px) are deliberately unchanged because the DOM day cells, gaps, proposal bands, tick labels and lanes align to them. *Markup (new `shared-dashboard/chart-view.js`, used by `dashboard.js`):* zoom controls as one grouped control with the same `data-zoom`/`data-reset` hooks and accessible names; four context tiles (Now, Next window, Horizon low/high; unknown stays the text Unknown, negative keeps its sign); one legend in three labelled groups (evidence tracks incl. hatched unknown, absolute price bands for c/kWh only or the neutral-currency note, and proposal/soft-cap/Now overlays, the cap key only for a finite cap). Existing bounded date navigation (`renderPriceNav`), price-gap and midnight overlays, published-interval handling, DST/15-60 min tick and snapping logic, `buildTracks` and the lane tiling are untouched; lanes gain a key chip and a card treatment, still positioned from the chart's own axis conversion so zoom, pan and resize keep them aligned. Dark/unit styling lives in `shell.css` (20.4 section) and the touched colours of `dark.css`. *Tests:* new `frontend/test/chart-redesign.test.ts` (10: legend bands/neutral currency/cap/unknown key and escaping, controls hooks, context tiles, lane alignment through zoom, unloaded/unknown lanes never empty or zero, price gaps and proposal span, cap line only when finite, negative axis, rounded negative bar, no non-zoom actions); focused reruns of price-chart-interaction, chart-tracks, price-bands, price-days-panel/nav, sidebar-price-chart, shell-chart-tabs, tab-visual-migration, hero-overview, shell-tabs, dark-theme, charge-now-layout, daily-overview (152 passed with the new file's neighbours), bundle test, prototype `sample`/`daily-sample`. Manifest 2.5.205, `npm run build`, `npm run check-dist` and `prototype:build` passed. *Unrun:* browser/visual check (real canvas look, bar corner radius, legend wrapping at phone width, lane captions, tooltip), live HA, hardware, full suites, backend tests. Real 15/60-minute and DST day behaviour is covered by the existing, unchanged price-chart-interaction cases, not re-seen visually. Nothing was committed, pushed or installed.
- [ ] **20.5 Proposed windows and chart linkage.** Make the full proposal list a first-class responsive card using the same validated adapter windows as the chart. Show energy/cost/average only where the current validation and price basis permit; distinguish provisional, no need, constrained, stale and unavailable. Link selection using proposal identity and exact intervals; allow jumping to another available price day and clear stale selection. Test 0/1/many, crossing days/DST, changed proposal, invalid window details and no side effects.
- [ ] **20.6 Strategy and plan editor.** Redesign summary and existing editor for charge mode, vehicle selection, target/minimum, cap and basis, ready-by and reserve. Preserve independent draft, proposed-vs-saved default, validation, revision compare-and-set, conflict and reload behavior. Verify actual allowed non-admin subset and disable or exclude forbidden changes without widening authority. Test role change, save, conflict and dirty refresh; avoid introducing manual numeric SOC.
- [ ] **20.7 Price perspective and insights.** Build the Explore tab with current/next price context and existing live/monthly insights with existing APIs, navigation and coverage; distinguish raw market price, variable cost and display-only absolute bands. Preserve insufficient-baseline, partial, currency and unavailable cases. Test request bounds, missing/negative prices and changing context; no new forecasts or planner calculations.
- [ ] **20.8 History and costs.** Build the History tab and redesign recent charging, day/month review, sessions and chart/history navigation, retaining measured/estimated energy provenance, spot-only observed cost, same-priced-energy day-average savings baseline and actual coverage/retention. No unplaced late energy assigned to a day. Test empty/partial/truncated history, midnight/DST, missing prices and basis distinction from forecast; passive reads never cause a replan.
- [ ] **20.9 System evidence and diagnostics.** Redesign source freshness, separate proposal/ACK/readback/transaction/flow evidence, Morek details and existing admin diagnostics/maintenance controls. Preserve exact action guards, confirmations and readback limitations, and explain who acts next for blocker/recovery states. Test independent unknown/stale/mismatch states, permissions and sensitive action outcomes. Do not turn evidence into a sequential all-green success indicator.
- [ ] **20.10 Vehicle and market settings.** Build the Settings tab and replace vehicle sources/properties and market/cost editors with coherent new settings screens; retain separate drafts, entity selection, capacity/phases, tariff/source options, admin access, existing confirmations and compare-and-set. Test dirty refresh, changed permissions, conflicts and source changes. Do not migrate original card-only functions.
- [ ] **20.11 Plan parameters, notifications and setup.** Redesign existing charger/plan parameters, departure settings, notifications, setup checks and admin log access. Preserve current field-level authorization, current-change confirmation, independent drafts and setup links. Test role-specific saves, cancellation, navigation and refresh; no new configuration capability.
- [ ] **20.12 Whole-product closure.** Remove superseded sidebar markup/styles and duplicate host presentation, complete responsive layouts and accessibility across every screen, and audit actual capability mapping from 20.1. Exercise focused cross-screen lifecycle, unknown-state and no-write-on-read tests, preview build, required manifest/build/dist checks and docs. Record visual/browser, live and hardware checks not run; user-directed visual approval is separate. Acceptance: one new sidebar UI, shared production/preview presentation, no orphaned existing sidebar workflow or duplicate action controller.

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

**Stage 19 amendments (2026-11-18).** For Stage 19 substages only, the rows “Uncertainty and recovery”,
“Dedup”, “Decision evidence” and the retry/cap constants are amended **exactly** as listed in the “Stage 14
contract amendments” table inside Stage 19; the protected-window, material-trigger, SOC-tolerance and
Stop/Pause/Charge Now rows keep their rules and thresholds and only gain the stated extra checks. Every
other row and every Stage 15–18 substage is unchanged, and no amendment is verified on hardware.

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

## 7. Stage 15 — locally implemented and reviewed (2.5.129–2.5.143)

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
- [x] **15.1b Reserve setting control and plan display.** *Locally implemented with mocked frontend checks (2.5.130); coordinator reviewed; not installed, browser-checked or live-verified.* *Scope:* sidebar control beside cap/minimum SOC
  (canonical settings, revision checks, existing draft/conflict behaviour); plan explanation and plan modal
  show reserve minutes and where placed, the **required baseline** and, separately labelled, the *potential
  extra allowed reserve energy/cost* from 15.1a’s `reserve_allowance` (complete windows visible, reserve
  periods identified inside them, no double counting, no claim of zero use, only measured is actual); the
  wording “extra allowed time to reach the target; the car’s own limit stops it”; preview fixture parity;
  absent backend fields degrade to today’s display; i18n. *Acceptance:* values shown equal the backend’s;
  allowance never added into the baseline; opening the view writes nothing; build/check-dist/i18n parity.
  *Exclusions:* no client-side planning or cost arithmetic, no BMW-limit control.
- [x] **15.2 Link monitor and offline/reconnect signals ◆.** *Locally implemented with mocked checks (2.5.131); coordinator reviewed; not installed or live-verified.* Landed as `execution/morek_link.py` (`MorekLinkMonitor`, started in `__init__.py` beside the worker, `worker.link_monitor`), `morek_schedule.link_reading`, status field `link` (`state`, `since`, `connection_id`, `connection_changed_at`, `boot_generation`, `boot_changed_at`), `morek_offline` in `TRANSIENT_BLOCKERS`/`DECISION_BLOCKERS`. Tests: `tests/test_stage_152_link_monitor.py`. *Scope:* a small in-process monitor per Morek
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
- [x] **15.5 Guarded start after a confirmed reboot (boot signal); backend “charging must be enabled” ◆.** *Locally implemented with mocked checks (2.5.132); coordinator reviewed; not installed or live-verified. Whether the installed OCPP integration exposes `charger_generation`, and whether HA re-stamps the status/transaction sensors after a reboot, is unverified; without them readiness says `unknown` and only the existing paths act.* Landed as `MorekSessionCoordinator.note_boot`/`evaluate_boot`/`boot_status` (the monitor delivers a within-process counter rise and re-evaluates on every poll/event; `reconnect()` no longer mints `boot:` from a counter compare), readiness `boot_start` and `charging_enabled` (`enabled`/`not_ready`/`unknown`). Tests: `tests/test_stage_155_boot_start.py`. *Scope:* make the
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
- [x] **15.3 Reconnect and startup read-only schedule check ◆.** *Locally implemented with mocked checks (2.5.133); coordinator reviewed; not installed or live-verified. What the installed charger answers to `GetCompositeSchedule` after a reconnect is unverified.* Landed as `execution/morek_checker.py` (`MorekScheduleChecker`, `worker.checker`, created in `__init__.py` before the link monitor starts), `async_schedule_action(..., "fetch", check=...)` (a writeless branch `_checked_readback`; `check_candidate`/`classify_check` in `api/morek_schedule.py`), status `reconciliation.check`. Tests: `tests/test_stage_153_schedule_check.py`. *Scope:* a `ScheduleChecker` in the worker
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
- [x] **15.4a Guarded schedule repair — trigger, confirmation, budget ◆.** *Locally implemented with mocked checks (2.5.134); coordinator reviewed (disabled dispatcher); not installed or live-verified. `REPAIR_DISPATCH_ENABLED` is `False` and stays so until 15.4b: a confirmed mismatch is classified (`differs_confirmed`), recorded and shown, and makes **zero writes**.* Landed as `morek_schedule.confirm_mismatch`/`repair_budget`/`repair_status`, checker confirmation (`MorekScheduleChecker._confirm`, `repair_current`), `MorekScheduleWorker.request_repair` and the `repair=` flag of `_send_profile_shared`; tests `tests/test_stage_154a_repair.py`. *Scope:* worker trigger kind
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
- [x] **15.4b Repair deferral for a correct charge and post-repair escalation ◆.** *Locally implemented with mocked checks (2.5.135); coordinator reviewed; **`REPAIR_DISPATCH_ENABLED = True` in committed source since 2.5.135; not installed or live-verified**. Decisions: unknown/stale flow or unknown facts defer (never permission to interrupt); a repair the charger rejects, and a confirmed mismatch of an attempt that is itself a repair, persist `repair_escalation` (needs a person, restart-proof, no further automatic repair). Handoff entry 2026-11-14 “Stage 15.4b”.* *Scope:* Before enabling dispatch, revalidate confirmation age at the final pre-wire boundary (latest readback at most 30 s old on wall and monotonic clocks); storage/lock delays must not reuse stale evidence.  when fresh measured
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
- [x] **15.6 Connection-aware freshness (backend) ◆.** *Locally implemented with mocked checks (2.5.136); coordinator reviewed; not installed or live-verified. Landed as `execution/morek_freshness.py` (pure `judge_event`/`judge_sampled`, cadence from evidence-store samples, `link_facts` from the 15.2 monitor), additive `readiness.freshness {expected, link, quantities}`; `vehicle`, `measurement`, `charging_enabled` and `observe_initial` use it; the readings' strict `fresh` flag, `connector_evidence` (now the named `STRICT_EVIDENCE_MAX_AGE_S`) and the 15.5 post-boot evidence are untouched. Without a link monitor the strict 180 s bound applies. Tests: `tests/test_stage_156_freshness.py`.* *Scope:* one shared judgement per quantity returning
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
- [x] **15.7a Plug-in authorization UI and freshness adoption.** *Locally implemented with fast mocked tests (2.5.137); coordinator reviewed; not installed, browser-checked or live-verified. Shared `sidebar/evidence-freshness.js` adopts `readiness.freshness` (fails closed on a malformed or mismatched judgement; an absent block keeps the strict 180 s display); `charge-session.js` adds `posture`, the casual asked/waiting/at-risk copy, 15.5 `charging_enabled` states (`not_ready`, `control_unavailable`) and `last_known`; `live-charging.js` uses the same judgement; `recovery-banner.js` has no age limit and is unchanged (banner copy is 15.7b). Tests: `frontend/test/charge-session-freshness.test.ts`.* *Scope:* in `frontend/sidebar/charge-session.js`,
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
- [x] **15.7b Check/repair/reboot/offline wording and banner.** *Locally implemented with fast mocked tests (2.5.138); coordinator reviewed; not installed, browser-checked or live-verified. New pure `sidebar/schedule-check.js` (separate subdued `#schedule-check` line under the primary charging state: check/rechecking/repaired/needs-person/reboot/link notes, fails closed on malformed/future/over-a-day data, older backends show nothing); `recovery-banner.js` maps `repair_needs_person`, `repair_deferred`, `repair_spacing`, `repair_unconfirmed`, `repair_gated` plainly with no resend action; `charge-session.js` offline/last-known copy is “Connection lost; last confirmed …”. No backend or write change; sidebar copy is English literals as before, so no i18n keys. Tests: `frontend/test/schedule-check.test.ts`.* *Scope:* the sentences for: reconnect check
  result (“checked at {time}, nothing needed changing” / “couldn’t check”), checking (“one odd reading isn’t
  enough to act on”), schedule repaired, **needs a person** (recovery-banner mapping of 15.4a’s blocker),
  reboot-asked-once, offline “last known {state}, {age}”, idle-connected (“unchanged since {time}”), unknown.
  Default copy and who-acts rules: archive “Status wording”. *Acceptance:* each state has a wording test;
  nothing claims a repair or check proves charging; offline never reads as a charging failure; absent fields
  degrade; i18n parity in every language file; no new write path. *Exclusions:* no backend change.
- [x] **15.8 Late cumulative-register reconciliation of closed session totals ◆.** *Locally implemented with mocked checks (2.5.139); coordinator reviewed; not installed or live-verified. Corrected before commit: only the recorder's own open/close register pair counts as association proof; a later register rise has no session/transaction binding in the evidence store, so it is shown as `unassigned_register_kwh` on an `uncertain` record with no total (the overnight 20.9 kWh case is not automatically attributable). Whether the installed charger/HA replays register values is unverified; limits are in the handoff.* Landed as `sessions/reconcile.py`, the recorder's `register_pair` and `_reconcile_late`, `ChargeSession.late`, history `sessions[].reconciliation`. Tests: `tests/test_stage_158_late_reconciliation.py`. *Scope:* one bounded
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
- [x] **15.9a Energy learner fed on the Morek path ◆ (former 11.1, part 1).** *Locally implemented, capture-only, with mocked checks (2.5.140); coordinator reviewed; not installed or live-verified. Landed as `AutoPlannerController._capture_energy` (60 s `@callback` tick, Morek-owned only), `EnergySampler.observe_capture`, `Capture`/`CaptureAnchor` in `planning/learned_energy.py`; tests `tests/test_stage_159a_energy_capture.py`. Limits in the handoff: controller facts inferred from code and a fake controller, not proven on hardware; safety-stop/protection not recorded; `late_energy` is a capture-time snapshot; `tests/test_learned_energy.py` hass-fixture tests not re-run here.* *Scope:* under Morek schedule
  ownership nothing was sampled before 15.9a (`_check_plan`, the former sole caller of `_sample_energy`, ran only from
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
- [x] **15.9b Learner rules: exclusions, asymmetric trust, clamp ◆ (part 2).** *Locally implemented with mocked checks (2.5.141); coordinator reviewed; not installed or live-verified. Landed in `planning/learned_energy.py` (`metadata_reason`, `LearnedEnergyStore.evaluate`/`checker`, `_promoted_learned`, persisted `promoted`/`rejected`/`rejection_counts`) and `AutoPlannerController._prove_capture` (proof against the retained session/evidence records) plus the minimum-SOC floor guard in `capped_vehicle_energy`; tests `tests/test_stage_159b_promotion.py`. Limits in the handoff: promotion proof depends on 15.8 session records and 3 days of evidence rows; no hardware proof; safety-stop/protection still not recorded; Stage 14 ◆ files not all re-run.* *Scope* **(first: promotion/revalidation)** every stored `morek_capture` sample is revalidated under the rules
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
- [x] **15.11 Learned-estimate display and reset.** *Locally implemented with mocked checks (2.5.142); coordinator reviewed; not installed or live-verified. Display: backend block `plan.proposal.learning` (`learned_energy.estimate_view`, effect minutes computed in `api/dashboard._learning_fields` from the planner's own `target_need` with/without the learned figure at the plan's power), rendered by `shared-dashboard/learning-model.js` + `plan-view.js` (stale: no effect claimed; absent/malformed: unknown). Reset: `spotnav/morek_schedule` action `reset_learning` (admin) → `AutoPlannerController.async_reset_learning` → both stores' `async_reset` (memory first, then the file's removal) and the samplers' memory; one `worker.note_learned_reset()` evidence round. Tests `tests/test_stage_1511_learning_display_reset.py`, `shared-dashboard/learning-model.test.mjs`. Limits in the handoff.* *Scope:* where the plan’s time/energy explanation shows,
  state whether the estimate is learned or default, the sample count (“n of 5 needed to shorten”), the effect
  in minutes and “estimate; no guarantee”; rejection reasons in diagnostics; an administrator action resetting
  learned energy and power data for the charger (reusing the stores’ own removal) plus its sidebar control.
  Replanning after a reset goes through the existing input-evidence path. *Acceptance:* default and learned
  displays correct; “learned values unavailable, using the default” while nothing trusted exists; reset
  restores the default and replans once (equal schedule sends nothing, active window protected); non-admin
  refused; i18n parity; stale display never claims precision; opening the view writes nothing. Only the reset
  action needs the Stage 14 backend files. *Exclusions:* no new learning rule; retuning constants from user
  summaries is a separate optional review.
- [x] **15.10 Morek behind-plan check and power-learner feed ◆ (former 11.2; deferrable).** *Locally implemented with mocked checks (2.5.143); coordinator reviewed; not installed or live-verified. Landed in `AutoPlannerController._async_morek_behind` on the 60 s capture tick (existing `PlanWatch`/`PowerSampler`), `morek_schedule.behind_window`, `__init__._morek_progress`, and the held power figure `_frozen_learned_cap`; tests `tests/test_stage_1510_behind_power.py`. Limits in the handoff: controller hold facts under Morek ownership and the link monitor are inferred, not hardware-proven; Stage 14 ◆ files 141/145_fresh/146, session and recovery files not re-run. Stage 15 implementation and coordinator review are locally complete; optional E1/E2 remain open.* *Scope:* run the
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

## Stage 16 — Use published charging opportunities while tomorrow is missing

**Approved 2026-11-14; implement next, one fresh Claude medium delegate per substage.** This closes the
uncapped Morek gap left by Stage 10.3. The daily ready-by may roll into tomorrow while only today's prices
exist. Missing future prices alone must not prevent a useful published-price plan, including a partial
charge when the available periods cannot cover the whole need. Keep the actual ready-by unchanged.

**Scope and decisions:** Morek schedule ownership only. Reuse the existing cheapest-period selection,
current-interval support and history comparison; introduce no fixed cheap-price threshold, price forecasts,
new setting, store or controller. With no cap, select the cheapest available published placement; a usable
history comparison may still justify waiting when it clearly favours unpublished hours under its existing
rule, but absent or inconclusive history must not force waiting. Capped planning and its minimum-SOC
exceptions remain unchanged. A provisional plan may start now if now is selected; it need not start on
every plug-in. Unknown prices never become zero or authorize an unpriced profile. Partial coverage is not
proof the real deadline is infeasible. Preserve the 10% reserve where it fits valid priced time; do not add
reserve or repeated purchases beyond the remaining need through successive recalculations.

- [x] **16.1 Published-only full and partial planning ◆.** *(Locally implemented in 2.5.144 with mocked checks; coordinator reviewed. Root focused checks: 25 passed; build/dist and lint passed. Admission/UI remain 16.2; not deployed or live-verified.)* Inspect and extend the smallest production seam
  in `AutoPlannerController`, `price_gap` and existing history/wait helpers. An uncapped schedule-owned daily
  departure with incomplete future prices can produce a provisional cheapest-known plan. Support both the
  whole remaining need and a useful smaller published portion, including a part-elapsed current interval.
  Apply existing history comparison only where supported; no usable comparison is not a veto. Keep genuine
  urgency/best-effort behaviour, the real departure, target/progress accounting, price coverage marker,
  reserve arithmetic and maximum windows intact. Do not globally change legacy/non-Morek history/wait.
  Reuse existing publication/wake events and bounded retries; verify expected publication date rolls
  correctly. *Acceptance:* daily 08:00 rolled to tomorrow; current interval selected vs cheaper later known
  slot; insufficient published capacity produces partial known charge without a false deadline-failure
  claim; no/flat/history-clearly-cheaper cases; no usable price yields no priced plan; capped/non-Morek
  unchanged; reserve and DST/deadline boundaries. Focused fast tests of real controller/planner boundaries.
  Stage 14 contract: SOC-only dedup, protected active window, progress and uncertain writes remain binding.
  *Exclusions:* no broad price-state admission change, new urgency rule, forecast or UI redesign.

- [x] **16.2 Safe dispatch, publication continuity and clear partial-plan UI ◆.** *Canonical status: implemented locally with mocked checks and committed (`08254d2e`, manifest 2.5.148); the checked entry under Stage 17 below holds the implementation record, and the acceptance text of this stage still applies. Not installed or live-verified.* Acceptance (unchanged): a degraded aggregate price state may pass only with authoritative ready, listed, valid data covering every remaining scheduled minute (including reserve), identical calculation provenance and all pre-wire checks; tomorrow missing/failed never invalidates valid today coverage while stale/invalid/untrusted/gapped used data still blocks; one coverage judgement for manual and automatic; a partial-coverage indicator; publication improves future planning without interrupting a healthy active window (Stage 14); identical publication or SOC sends nothing; partial progress is not bought twice. 2026-11-16 audit: `tests/test_stage_162_safe_dispatch.py` (27) drives the exact uncapped daily 08:00 rolled-to-tomorrow case through the real controller, planner and guarded worker, including tomorrow publishing during an active window (never a gap in the window the car charges in) and `tests/test_stage_161_published_only.py` covers measured register energy with a delayed SOC counted once.

Standard acceptance and the Stage 14 non-regression contract apply to both substages, subject to the
binding fast-tests-only restriction. After each review, commit and push before delegating the next.

## Stage 17 — Planner resilience: a useful, honest plan from imperfect inputs

**Planned 2026-11-14 (docs only; nothing below is implemented except what is marked).** Source basis at planning: manifest
**2.5.146**, HEAD `d9ec44cc` (all of 17.1–17.6 have since landed; see the queue and checked entries). One fresh Claude Sonnet 5.5 medium delegate per substage in the
queue below, shared worktree; the coordinator reviews, then commits and pushes each substage before the next
starts (no batching). Every substage: Standard acceptance (§4) with the binding **fast-tests-only** rule, the §5
contract (all are ◆ unless stated), manifest bump (next free patch, from 2.5.147) only when source or card
changes, `npm run build` + `npm run check-dist` from `frontend/` when the card/sidebar changes, a truthful update
of this checklist and a dated development-handoff entry. No HA access, deployment, charger or hardware action.

**Why:** the planner holds (`planning_unavailable`, a retained old plan) for inputs that are merely old, estimated
or partly missing, while the guards that matter (identity, Pause/Stop, protection, ownership, uncertain writes,
price coverage of every sent minute) already sit at the wire. Stage 17 narrows each hold to the cases that are
genuinely unsafe, labels what was estimated or unknown, and makes recovery automatic through the existing
input-evidence → recalculation → worker-compare path.

**Policy for every substage (binding):**
1. Plan from the best honest input and say what it was: actual reading vs energy-derived estimate vs last known;
   estimated, stale or unknown is **never shown or recorded as measured**; unknown is never zero.
2. **No invented prices.** A missing, invalid, stale-beyond-rule or gapped price never becomes a price, a zero or
   an unpriced dispatch; `proposal.unpriced` stays undispatchable. Never use an exchange rate older than
   `MAX_RATE_AGE` or from another currency.
3. **No guessed identity.** A reading for no car, another car, the future or older than one already planned from
   still holds the plan (`target_soc_stale`, Stage 14.5). Estimates are tied to the identified car and plug-in.
4. **No blind retries.** Reuse the existing bounded refresh/backoff (price refresh, ECB `BACKOFF_STEPS_SECONDS`,
   `FX_RETRY`, `REJECTION_RETRY_DELAYS`, 12-check cap). An unknown dispatched outcome is never retried or cleared.
   No new timer, controller or sender except where a substage names one non-sending wake.
5. Pause/Stop, Charge Now ownership, connector identity, electrical protection, the user’s settings (cap, minimum
   SOC, target, ready-by, reserve) and the BMW-limit assumption stay exactly as they are. The immediate SOC
   protection floor keeps its own freshness rules.
6. Recovery is the **existing** path: a changed input (`_morek_input_evidence`, price evidence, area snapshot,
   session store, reading) → `_on_area_changed`/`async_recalculate` → worker compare. A recovered plan is sent
   **once**; an equal schedule sends nothing; an active window keeps Stage 14 protection. The user never has to
   press Refresh/Send for an automatic recovery.
7. A new user-visible sentence goes into the existing status/projection/banner surfaces (no new panel, no new
   store, no new architecture). Every blocker states who acts.

**Already implemented — do not redo (source reading of 2.5.146):**

| Area | State | Owner here |
| --- | --- | --- |
| 14.5 measured-progress accounting, reading order/identity guards, `vehicle_update_wait` | Done (14.5) | reused by 17.1/17.2 |
| 16.1 published-only full/partial planning (`published_first`, `plan_published_portion`, reserve on published rows, urgency) | **Done locally, reviewed** (2.5.144) | consumed by 17.5 |
| 2.5.146 unattributable measured progress plans from the reading, `progress_unknown`, `valid_energy_kwh` | Committed `d9ec44cc`; 17.1 review done locally (2.5.147), committed | 17.1 |
| 12.8 capped planning from a last-known *actual* reading of any age | Done (2.5.72) | 17.2 extends to estimates only |
| Uncapped Morek path accepts an energy-derived estimate; `SocReader`/`soc_estimate` produce it | Done | 17.2 aligns capped path + admission |
| Uncapped path works from a trusted learned wall kWh/% with no capacity (`with_learned`); capped path now does too (`capped_vehicle_energy`) — **done locally (2.5.151), committed and pushed** | Done | 17.3 |
| Price refresh/retry/backoff, ECB retry/backoff, `wants_again` rebuild when a rate arrives, ECB table ≤ 7 days before the day | Done | reused; 17.5 only labels/guards |
| `SessionStore.add_listener`/`_notify` (close at `store.py:365`, second notify at `:443`) and recorder `_reconcile_late` | Done | 17.4 reuses; today `_on_sessions_changed` ignores target plans |
| Degraded aggregate price state blocks automatic and manual dispatch (`morek_plan_blocker` area states; `_validated_proposal`) and the partial-plan indicator | **Done locally (2.5.148), committed `08254d2e`** | 17.5/17.6 consume |

### Historical substage map (remaining execution order is the five groups above)

| # | Substage | Needs |
| --- | --- | --- |
| 1 | 17.1 Review and finish the 2.5.146 progress-uncertainty fallback — **done locally (2.5.147), committed and pushed** | none (committed) |
| 2 | **16.2** Safe dispatch, publication continuity, partial-plan UI (existing item, scope unchanged, above) | 16.1, 17.1 |
| 3 | 17.2 Stale SOC with trustworthy estimates — **done locally (2.5.149), committed and pushed** | 17.1; after 16.2 (same `morek_plan_blocker`) |
| 4 | 17.3 Missing-capacity fallback — **done locally (2.5.151), committed and pushed** | 17.2 (shares the capped-energy seam) |
| 5 | 17.4 Automatic recovery on session finalization — **done locally (2.5.153), committed and pushed** | 17.1 |
| 6 | 17.5 Exchange-rate freshness and truthful cap policy — **done locally (2.5.154), committed and pushed** | 16.2 (one coverage judgement) |
| 7 | 17.6 Clear blockers and end-to-end automatic recovery — **done locally (2.5.155), committed and pushed** | 17.2–17.5 |

- [x] **17.1 Review and finish the 2.5.146 progress-uncertainty fallback ◆.** *Reviewed and finished locally at
  manifest 2.5.147 (implementation sub-agent; **coordinator-reviewed, committed and pushed**); mocked checks only. Not
  installed or live-verified.* Review outcome: (a) was a confirmed gap and is fixed — `_planning_inputs` and the
  decision event `inputs` now carry `progress_unknown` additively (no new log line or sensitive field); (b) proved by
  test: a flag flip alone notifies state listeners once (the display text changes), repeats are silent, no
  recalculation starts, and the existing worker test shows a flip with the same plan sends nothing; notifications use
  the plan fingerprint, not the key; (c) verified — no UI/status text treats `target_progress_uncertain` as an active
  hold (only the legacy reason literal and the decision-blocker map for old stored values remain); (d) pinned by test.
  No attribution, identity, admission, dispatch or threshold change. The earlier note that it was “uncommitted” is stale.
  *Original scope:* *Scope:* review the committed diff
  (`vehicle_update_wait.measured_progress`/`valid_energy_kwh`, `auto_controller._progress_adjusted`/
  `_session_energy_since`, `AutoSnapshot.progress_unknown` in `meaningful_key`, `dashboard._proposal_section`,
  `sidebar/adapter.js`) against the handoff entry and fix only **confirmed** gaps. Candidates to verify first:
  (a) the accepted plan’s evidence (`api/morek_schedule.py` `inputs` around lines 1820/2406, which already carries
  `soc_source`/`soc_estimated`) does not record `progress_unknown`, so “sent from an unknown-progress plan” is
  invisible in decision/status evidence — add it additively (no new code or log line); (b) `progress_unknown` is
  part of `meaningful_key`: prove a flag flip alone causes no extra proposal notification, upload or recalculation
  loop; (c) no UI/banner/status text still calls `target_progress_uncertain` an active hold; (d) with a soft cap and
  a minimum SOC the above-cap exception is sized from the reading (documented limit): pin the intended behaviour
  with a test (exception never exceeds the minimum need from the reading, never past the target, flagged) — no
  new rule. Do not add a threshold or an estimate of the unknown energy. *Acceptance:* the existing 24-case
  `tests/test_stage_145_progress_recovery.py` plus any new case; plus one-at-a-time reruns of
  `test_morek_worker.py`, `test_stage_145_fresh_inputs_recovery.py`, `test_stage_142_active_continuity.py`,
  `test_stage_143_recalculation_triggers.py`, `test_review_vehicle_update_wait.py`, `test_plan_car_ended_rules.py`
  and frontend `sidebar.test.ts`; known pre-existing failures (`test_stage_103_partial::…real_morek_path`,
  `test_stage_151a_time_reserve::…baseline_and_allowance_separately`, `test_plan_details_isolated`) are reported
  as such, not “fixed” here. Mark `[x]` only after review; a docs-only outcome needs no manifest bump.
  *Exclusions:* no behaviour change to attribution rules, identity guards, admission, dispatch or Stage 14
  thresholds; no new retry; no session-finalization trigger (17.4).
- [x] **16.2 Safe dispatch, publication continuity and clear partial-plan UI ◆.** *Locally implemented with mocked checks (2.5.148; coordinator-reviewed, committed and pushed); not installed or live-verified. One judgement `AutoPlannerController.morek_price_blocker` serves the automatic worker and the manual path for a `degraded` aggregate; an uncapped Morek plan ignores a non-`ready`/`listed` tomorrow; `price_policy.tomorrow_pending` drives the sidebar/overview sentence. Tests `tests/test_stage_162_safe_dispatch.py`, `partial-policy.test.ts`. Review correction: manual Send/preview now use the same `morek_price_blocker` for every price state (`ready`, `waiting_for_tomorrow`, `degraded`); an uncapped Morek plan is built only from `ready`+`listed` days and waits (`no_prices_yet`) when none exists (no `or documents` fallback). Details and pre-existing failures in the handoff.* Unchanged scope and acceptance
  (Stage 16 above). It is the single owner of: degraded-only-by-tomorrow admission with one coverage judgement,
  and “tomorrow missing/fetch failure must not invalidate valid today coverage”. Stage 17 adds no second
  coverage rule and no price-admission change; 17.5 and 17.6 consume it.
- [x] **17.2 Stale SOC with trustworthy estimates ◆.** *Locally implemented with mocked checks (2.5.149; coordinator-reviewed, committed and pushed); not installed or live-verified. One `estimate_trusted`/`capped_planning_facts` rule (constants `ESTIMATE_MAX_ANCHOR_AGE_S` 12 h, `ESTIMATE_MAX_DELIVERED_KWH` 40; reset-flagged or unanchored estimates are not trusted) serves the capped resolver, `_energy_for` and `morek_plan_blocker`; an untrusted estimate falls back to its anchor reading; capped evidence uses the anchor identity plus the trust flag. Tests `tests/test_stage_172_stale_soc.py`; details, unrun checks and the no-timer-expiry limit in the handoff.* *Seam (verified in source):* `capped_vehicle_energy`
  refuses any `soc_estimated` level as `target_soc_stale`, and `morek_plan_blocker` returns `vehicle_input_stale`
  for a capped plan with an estimate, while the uncapped Morek path already plans from one; `_progress_adjusted`
  correctly skips subtraction for an estimate (it already counts the energy). *Scope:* one shared predicate (in
  `planning`, used by both the energy resolver and `morek_plan_blocker`, never two judgements) saying when an
  energy-derived estimate is **trustworthy**: anchored on an actual reading of this car and plug-in, valid
  register-measured delivered energy since it (`soc_estimate.delivered_since_kwh`; no register reset/gap/
  backwards), a capacity known, and anchor age and delivered energy inside named constants chosen and listed by
  the delegate. Trusted → the capped plan uses it (target need and the minimum-SOC exception, one figure,
  labelled estimated with anchor age in the existing `projection`); not trusted → fall back to the last actual
  anchor reading when `SocReader` offers it (today’s 12.8 behaviour, never worse), else the existing
  `target_soc_stale`. **Churn guard (must be proven by test):** `_morek_input_evidence` currently holds the running
  `soc_percent`, so an estimate that moves with the register would make every pre-wire check read
  `plan_inputs_changed`; evidence for an estimated level must instead use the anchor identity (reading time,
  entity, car) plus the estimated flag, so routine register ticks neither invalidate a plan nor trigger a resend
  (Stage 14.3 5-minute SOC tolerance unchanged). *Reuse:* `vehicles/soc_estimate`, `SocReader`, 14.5 order/identity
  guard (`_capped_input_problem` still applies). *Default decision (coordinator may overrule before delegating):*
  the minimum-SOC protection floor (`min_soc_floor`) keeps its own strict freshness and is untouched.
  *Acceptance (real controller + worker):* trusted estimate plans capped and dispatches once; untrusted estimate,
  register reset, missing capacity, unknown/other car identity → fallback or hold as described; a fresh reading
  rebases and clears the estimate label; register drift does not resend or block; no double subtraction of
  measured progress; stale **actual** reading still plans as in 12.8; Stop/Pause/uncertain outcome block as before.
  *Exclusions:* no new SOC source, no vehicle wake, no change to the protection floor, learner or Stage 14.5
  identity/order rules.
- [x] **17.3 Missing-capacity fallback ◆.** *Locally implemented with mocked checks (2.5.151; coordinator-reviewed, committed and pushed); not installed or live-verified. `capped_vehicle_energy` no longer refuses an unknown/invalid capacity when `learned.use_kwh_per_percent` is trusted (same `target_need`/`with_learned` arithmetic as the uncapped path; wall kWh = points × learned wall kWh/%); with neither it still holds as `target_capacity_unknown`. Plans are labelled (`projection_capacity_unknown` → `projection.capacity_unknown`, decision `inputs.capacity_unknown`, sidebar note). Tests `tests/test_stage_173_missing_capacity.py` (18). **Morek fallback (2.5.151, narrow learner change):** with no capacity today, promoted Morek votes (already proven by their retained session/evidence records) stand on the capacity they were *recorded* with (the newest vote's; votes of another size and any capture once refuted by a known different size do not count), with the unchanged 3/5-vote, spread and clamp rules; that recorded capacity (`LearnedEnergy.reference_capacity_kwh`) is only the reference for the clamp and the never-shorten minimum-SOC floor, never a current or guessed capacity. A learned figure with no capacity and no such reference (legacy samples) holds as `target_capacity_unknown` when a real minimum-SOC need exists, so the minimum allowance is never silently reduced. Without proven votes the plan still holds; not all missing capacity is recoverable. Not installed or live-verified.* *Seam (verified):* `soc_source.capacity_kwh(vehicle_id)` feeds
  `LiveVehicleFacts.reported_capacity_kwh`; the uncapped path calls `target_need` → `with_learned`, which already
  works from a **trusted learned wall kWh/%** without a capacity, but the capped path returns
  `target_capacity_unknown` before reaching it. *Scope:* make the capped path use the same `with_learned` figure
  when (and only when) a trusted learned value exists (15.9b promotion rules and clamp, unchanged); inspect first
  whether the clamp or `estimate_view`/dashboard need a capacity reference and, if so, keep the display honest
  (“estimate; capacity unknown”) instead of inventing one. With neither capacity nor a trusted learned figure the
  plan stays blocked as `target_capacity_unknown` with a clear who-acts sentence (set or enable the battery
  capacity; 13.1 owns the control, no new settings UI) and **recovers automatically** when a capacity or trusted
  figure appears (it is already in `_morek_input_evidence`). Never guess a capacity from a model name or another
  car. *Acceptance:* capped plan with learned figure and no capacity plans, labelled; no learned figure → blocked,
  wording shown, recovers on arrival without a manual action and sends once; untrusted (4-of-5) learned data not
  used; uncapped path unchanged; dashboard `soc`/learning block consistent with the plan; minimum-SOC arithmetic
  unchanged. *Exclusions:* no capacity guessing, no learner rule change, no new setting.
- [x] **17.4 Automatic recovery on session finalization ◆.** *Locally implemented with mocked checks (2.5.152; coordinator-reviewed, committed and pushed); not installed or live-verified. `_on_sessions_changed` now handles a target plan: the close of the open session the last target calculation counted or flagged (`ProgressWatch`) schedules one `async_recalculate(cause="session_finalized")`, once per closed session id, and never while Paused, person-Stopped or with a send pending. Finalization changes only the *known* energy of an identified session that began after the reading (the plan shrinks once); a straddling or car-less charge stays `progress_unknown` after its close, so there the replan is followed by one request through the existing `_ask_reading` (same wake/once-per-plug-in rules; no new wake) and the sidebar says it waits for the car's next level. A late reconciliation or sample notification is not a trigger. 2.5.153 correction: a preview no longer touches the watch; a close held by a pending send/Pause/Stop is deferred and retried once on the existing execution-change/recovery-end events (no timer; Stop release has no verified event, so that case waits for the next ordinary event; failed recalc/ask are not retried here). Tests `tests/test_stage_174_finalization_recovery.py` (18); details in the handoff.* *Seam (verified):* `AutoPlannerController.
  _on_sessions_changed` (listener on `SessionStore`, armed by `_arm_charge_watch`) returns at once for a target
  driver, so a plan made while a session was open, closing or unreconciled never replans when that session
  finalizes; today a `progress_unknown` plan persists until another trigger (reading, price, settings). *Scope:*
  for a target-SOC, Morek-owned plan whose snapshot was made with `progress_unknown` or counted an **open**
  session, a session close/finalization notification (store close and the late-reconciliation notify; verify both
  fire, add the missing notify additively if not) schedules **one** coalesced `async_recalculate` through the
  existing path (bounded: one per closed session id, none while an attempt is pending, none after Stop/Pause).
  **First prove by test whether finalization can change the classification:** a final total changes the *known*
  energy of an identified session that began after the reading (so the plan shrinks once); a session that
  straddles an old reading or has no car stays `unknown` — the only recovery for it is a newer reading, so there
  the replan may use the **existing** `reading_asker` request (same once-per-plug-in/wake settings, no new wake)
  and the sentence says “waiting for the car’s next level”; the doc and UI claim no more than the test proves.
  *Acceptance:* close of an identified later session → exactly one replan, plan shrinks, equal schedule sends
  nothing, active window protected; unknown straddle → one reading request at most, flag persists truthfully,
  no loop on repeated notifications; no flag/not Morek/not target → nothing; restart loses nothing (flag comes from
  a fresh calculation); Pause/Stop/uncertain outcome win; no send is caused by the listener itself.
  *Exclusions:* no new listener class, store or timer; no timeline backfill; 15.8’s reconciliation values are not
  read as attribution proof.
- [x] **17.5 Exchange-rate freshness and truthful cap policy ◆.** *Locally implemented with mocked checks (2.5.154; coordinator-reviewed, committed and pushed); not installed or live-verified. New pure `pricing/rate_label.py` is the one rate judgement (own / dated / undated / missing; a table after the day or older than `MAX_RATE_AGE`, a non-finite or non-positive number, or another currency is `missing`); `planner._rate_for` uses it; the controller leaves a rate-less day out of the plan and out of `morek_price_blocker` coverage (so it never invalidates the other day) and keeps the documents when none has a rate so the planner refuses `missing_fx_rate`; `price_policy` now carries `fx`, `fx_state`, `fx_waiting`, `fx_note` (rate, table date, source, age; “waiting for the ECB exchange rate; asked for again automatically”), shown by the daily overview; the English `missingFxRate` text says it waits. Rate arrival is the existing document-evidence change: one replan, no new retry/timer. EUR areas unchanged (labels `None`). Tests `tests/test_stage_175_fx_freshness.py` (6). Details in the handoff.* *Seam (verified):* producers attach the newest
  ECB table at most `MAX_RATE_AGE` (7 days) before the day with its date (`fx_src`, `fx_date`); a day built without
  a rate is asked again at most every `FX_RETRY` and rebuilt when one arrives (`wants_again`); the planner converts
  with the document’s own rate and refuses `missing_fx_rate` (`planner._rate_for`). *Scope:* (a) prove by test that
  a day rebuilt after a rate arrives reaches the planner through the existing price evidence and replans once (no
  manual refresh); (b) when the used rate is a *dated* table rather than the day’s own, the plan’s price/cap
  statement says so (rate date, source, age) in the existing price-provenance/projection text — a soft cap in local
  currency is compared against the **converted** price, so the cap decision states the rate it used and never
  presents a rate older than the rule as current; (c) a missing rate stays `missing_fx_rate` (no other day’s or
  currency’s number, no zero) with a who/what-waits sentence (“waiting for the ECB rate; asked again automatically”)
  and recovers on arrival; (d) the **16.2 coverage judgement** treats a day without its rate as not covering
  (prove; no second rule). EUR areas are unaffected. *Acceptance:* dated rate plans and labels; rate older than 7
  days or absent → blocked, recovers once on arrival; cap boundary price converted with the labelled rate; EUR
  byte-identical; no retry loop added. *Exclusions:* no new FX source, retry schedule or rate estimation.
- [x] **17.6 Clear blockers and end-to-end automatic recovery ◆.** *Locally implemented with mocked checks (2.5.155; coordinator-reviewed, committed and pushed); not installed or live-verified. Found mismatch: with no plan the worker's reason is only `no_current_plan`/`prices_*`, so the recovery banner said "The plan is being recalculated" (or "Waiting for a fresh vehicle reading") even when the planner was waiting for a battery capacity or the ECB rate. Fix: the one table `morek_schedule.PLANNING_HOLDS` (planner/blocker reason → banner action, who acts `system`/`vehicle`/`person`, existing recovery trigger) refines the generic reason through `decision_blocker(reason, plan_reason)` (additive `detail`/`who`/`recovery` on status `reconciliation.blocker` and decision events); banner gains `set_battery_capacity` and `wait_for_exchange_rate` sentences and a car-reports sentence; `target_soc_stale` gets its own status sentence (`issue.planningUnavailable.targetSocStale`, 9 languages) instead of the generic one. No new store, panel, trigger or retry. Tests `tests/test_stage_176_blockers_recovery.py` (19), banner/wording vitest. Final correction: a healthy `nothing_to_charge` now shows a truthful info banner instead of "being recalculated", and the capacity sentence says the automatic send is subject to the usual checks (frontend tests; not live-verified). Honest limits in the handoff.* *Scope:* one table in code/tests of the
  planning holds Stage 17 touches — `target_soc_unknown`, `target_soc_stale`, `target_capacity_unknown`,
  `missing_fx_rate`, `price_data_stale`, `no_prices_yet`/`no_published_prices`, `plan_inputs_changed`,
  `price_inputs_changed` — each with: who acts, the **existing** automatic recovery trigger, and the text in the
  existing status/recovery-banner surfaces (`status_compose`, `recovery-banner.js`, sidebar adapter; no new panel).
  Fix only mismatches found (a hold with no recovery trigger, wording that implies a failure of charging, a
  blocker with no who-acts). Add a production-wiring test per recovering hold: hold → input arrives → plan →
  worker uploads once; and one combined case (stale SOC + partial published prices + unknown progress) that plans,
  is labelled, dispatches once and survives restart. Update the handoff with the final Stage 17 status.
  *Acceptance:* every listed hold has a wording test and a recovery test; none claims physical charging or a
  guarantee; no manual Refresh/Send needed; Pause/Stop/Charge Now/identity/uncertain outcomes remain blocking;
  sidebar copy follows the existing English-literal convention (i18n entries only where the file already uses
  keys). *Exclusions:* no new UI container, store, status family or retry.

**Unrun and unverified (carry in every substage report):** full suites, browser/Playwright, HA-fixture tests
(`fcntl` plugin), installed behaviour, whether the installed vehicle integration reports capacity/timestamps as
assumed, and whether the ECB table cadence matches. Mocked checks never prove physical charging.

## Stage 18 — Consistent dark UI, mobile layout, single-car default and price perspective

**Locally implemented and coordinator-reviewed, 2026-11-16 (2.5.163–2.5.166); no deployment or live verification.** All four substages are complete; next unstarted features remain Stage 7/8 when requested. Implementation order was 18.1 → 18.2 → 18.3 → 18.4,
one fresh Claude Sonnet 5.5 medium per similarly sized work block. Coordinator reviews important correctness
and maintainability, requests corrections only where material, then commits/pushes each substage. Completed
items stay checked, not deleted, so decisions and verification remain traceable. Fast focused tests only;
no HA access, charging commands or deployment. UI/browser inspection is authorized for these UI fixes,
but no expensive browser suites. Reuse the shared live/preview UI and ECharts; no parallel UI or planner.

- [x] **18.1 Dark theme across all UI surfaces.** Inventory live/sidebar/shared/legacy card and preview
  styles, explicit light colors, native inputs and Web Awesome shadow/part tokens. Make Charge Now details,
  plan inputs, Morek debug/log views, every advanced expandable, dialogs/selects/buttons/disabled/focus/error
  states and other owned surfaces consistently dark with readable contrast. Reuse a small shared token set;
  don't change HA's global theme or hide warnings. Check relevant expanded states and dark preview parity.
  Preserve actions, permissions and unknown outcomes. Acceptance: no owned white/light form surface or
  unreadable text, including expanded/disabled controls; targeted styles/renderer checks and required build.
  *Status 2026-11-16: locally implemented/mocked at 2.5.163, coordinator reviewed (33 focused tests and check-dist passed); visual inspection not done (unverified); see handoff.*
- [x] **18.2 Charge Now layout and full-width mobile cards.** Match Charge Now spacing, alignment,
  duration/custom-end fields and actions to the rest of the plan controls; wrap naturally without horizontal
  overflow. At mobile width (existing breakpoint, about 800 px), remove outer horizontal gutters between
  viewport/panel edges and card borders; retain comfortable internal padding, safe-area handling and vertical
  card spacing. Desktop layout remains intentional. Check 320/375/430 px plus desktop, expanded advanced
  cards, debug and Charge Now. Don't use fixed widths or viewport hacks that overflow HA's content panel.
  Acceptance: cards reach both content edges, controls fit, keyboard/focus and all write semantics unchanged.
  *Status 2026-11-16: locally implemented/mocked at 2.5.164, coordinator reviewed (28 focused tests, build/check-dist passed); mobile edge-to-edge checked in the local preview only; host-bar Charge Now pixels not visually verified; see handoff.*
- [x] **18.3 One-car default without repeated identification prompts.** Trace why one configured car can
  still trigger "which car". Use the sole configured eligible car as the default in the canonical vehicle
  resolution path, not a hardcoded BMW name/id or UI-only guess. Preserve an explicitly chosen guest or
  explicit different identity and existing ownership/uncertain/Pause/Stop guards. Zero cars stays unknown;
  multiple cars retains existing guarded identification (no new multi-car UX). A sole-car plug-in should
  resolve consistently in planner, authorization and UI with no redundant prompt/notification. Test one/zero/
  two cars, restart, stale old identification and explicit guest; preserve sensor/source freshness rules.
  *Status 2026-11-16: locally implemented/mocked at 2.5.165, coordinator reviewed (33 focused tests and check-dist passed); see handoff.*
- [x] **18.4 Absolute price bands and stable chart scale.** Read `samples/stepline-chart.js` for visual
  inspiration and adapt existing shared ECharts options, never load its sample data or rebuild the chart.
  Classification in EUR cents/kWh: <8 green (Cheap), 8–<15 yellow (Normal), 15–25 inclusive orange (Medium),
  >25 red (Expensive). Color price line/area honestly by these absolute thresholds with a clear legend;
  no min/max-relative palette. Use a zero baseline and minimum upper axis extent 30 c/kWh so a 1–3 c day
  stays visibly low; extend the axis for negative prices and spikes without clipping, preserving threshold
  positions and no downward autoscaling on cheap days. Preserve displayed price basis, units, zoom/tooltips,
  gaps, DST/resolution, proposal overlays and update stability. Convert thresholds through existing trusted
  unit/currency metadata where supported; never apply EUR cent cutoffs blindly to another currency or invent
  an exchange rate. Unknown conversion gets neutral styling with an honest explanation. This is display
  classification only, never a planner price cap or charging decision. Test 8/15/25 boundaries, 1–3 cheap
  range, negative/spike/missing data, units, preview/live parity and range preservation; required build/dist.
  *Status 2026-11-16: locally implemented/mocked at 2.5.166, coordinator reviewed (33 focused tests, build/check-dist passed); no browser/visual inspection done (unverified); see handoff.*

For each substage bump integration version and run frontend build/check-dist when integration/card changes;
use focused fast tests, report visual and hardware limits truthfully, update this checklist and handoff.

## Stage 19 — Ahead-of-time schedules and recoverable upload uncertainty

**Stage 19 is implemented locally through 2.5.199 (all five groups closed, mocked checks only). Open work is hardware evidence (R1–R7) and coordinator review; no Stage 19 behavior is assumed hardware-verified.**
Source basis: manifest 2.5.178 by source reading; no HA access, charger command or restart was used to write
this stage. One fresh Claude medium delegate per substage, shared worktree, queue order below, coordinator
review of each substage before the next; commit/push only when authorized. Every substage: Standard acceptance
(§4) with the binding fast-tests-only rule; ◆ substages meet the §5 contract **as amended by the table in this stage**; manifest bump and `npm run build` + `npm run check-dist` when integration/card files change, a
truthful update of this checklist and a dated handoff entry. No live operation of any kind is authorized by
this stage.

**Why (user direction, 2026-11-18):** the user wants the Morek to hold a schedule that was sent *ahead of
time* and still govern the car while HA is down, to be able to verify that schedule as *effective* rather than
merely accepted, and to stop one ambiguous upload from freezing automation forever. The current uncertain-write
latch is permanent: `_send_profile_shared` (`api/morek_schedule.py`) persists `uncertain: True` before any
wire call, and several exits after that persistence but **before** the call begins (ledger changed, durable
check failed or refused) return `upload_uncertain` with the latch still set although that execution did not send; after a crash the durable record may not prove whether dispatch occurred; only an exception raised by `validate()` is recorded as
`aborted_before_dispatch`. The in-memory `dispatch_started` marker is deliberately not proof. Any non-cancel
exception from the call itself (including a 30 s timeout) is also `unknown`. Today these cases are
indistinguishable and every one blocks later automatic sends; there is no supported general resolution path. **The user approved the
direction of relaxing that permanent block (2026-11-18). This is an approved direction, not verified
behavior:** no replacement, ordering or late-response semantics have been observed on the user's charger.

### Coordinator decisions and remaining execution order (2026-11-18)

This block supersedes conflicting historical Stage 19 and §5 wording below. The user wants unattended recovery,
ahead-of-time schedules, no routine charger spam, and an active charge left alone. The existing permanent unknown
latch and disabled Resume failed those goals. **Do not stop for another product decision on the points below.**
Use a fresh Claude Sonnet 5.5 medium delegate for each remaining group, shared checkout, coordinator review and
user-authorized commit/push. No live HA, charger commands, deployment or hardware testing is authorized here.

**Primary outcome and release requirement:** restore automatic charging control, not merely retain or explain an
uncertain state. The actual legacy scenario—an old ambiguous upload plus `pause_until_resumed`—must accept the
user's Resume, automatically reconcile and send the latest guarded plan when Morek is reachable, and continue
recovering across disconnects and HA restarts without another click, manual ledger edits or an indefinite lock.
A durable pending intent, warning, readback or preserved history is only an intermediate step, never completion.
If offline, keep the current intent and retry with pacing on reconnect. Respect a later Stop/Pause and protection;
report if the charger cannot be reached or rejects a request. Acceptance asserts the real guarded wire call and
subsequent recovery, not just a saved intent or a UI message. Do not mark 19.2/19.9a complete until this passes.

**Engineering policy — converge, do not promise impossible certainty.** A timeout cannot establish whether an old
command applied, and `GetCompositeSchedule` is effective limits rather than profile inventory. Keep the old attempt
as `unknown` historical evidence. Do not invent a maximum delivery time or label a historical attempt accepted.
Instead, after confirming the intended physical connector and a usable link, automatically send the **latest**
validated absolute schedule as a new, separately identified replacement through the existing single sender. Use
profile 42001 and current intent, preserving the active window; retain ACK and readback separately. This is the
approved pragmatic approach despite unverified firmware ordering and replacement semantics, **not a proof** that a
late old frame cannot arrive. Persist the outstanding risk and keep checking effective limits on reconnect, after a
replacement and when the next planned transition requires attention; if a fresh, valid readback differs, converge
again using the existing guarded worker with paced backoff. A readback that cannot distinguish profiles is not
proof of either historical outcome. Persist retry state across restarts. Start with 2 min, 5 min, 15 min, then
30 min, 1 h and a 4 h ceiling; meaningful reconnect/plug-in wakes a guarded evaluation without resetting pace or
causing a burst. Deduplicate equal settled schedules, coalesce events and log state changes rather than every retry.
Unsupported/repeated rejections remain visible and retry slowly rather than hammering. Never use `clear_profile`.

The residual risk is real: no software-side sequence number or one hardware trial proves a charger will not apply a
late old write. Present `supersession_pending`/`last known` and alert when recovery cannot verify effective limits;
continue guarded reconciliation rather than a permanent silent lock. Never claim this guarantees safety or charging
while disconnected. Explicit Stop/Pause take precedence: durably record the newest intent, invalidate pending
Resume, recheck generation at every await, prioritize its guarded hold/stop operation and reconcile that same intent
after reconnect; never let an old ACK overwrite newer intent. A late old charger operation could still temporarily
override it; monitoring and reassertion mitigate but cannot eliminate that device/network risk. Electrical protection,
identity and ownership checks remain in force; inability to apply a control must be shown immediately.

**Resume decision.** Resume during a paused legacy-unknown record must be selectable by an authorized user. Persist
a separate pending Resume intent under connector admission; retain the Pause as effective authority until guarded
recovery can act. It must survive restart without being treated as an ACK or measured charge. A subsequent Stop or
Pause invalidates it, including persistence races; revalidate durable intent/generation before dispatch and after
awaits. Once recovery can send, reconcile the current authorized Resume automatically. Show all active blockers,
what happens next and the next retry; do not require a second click simply because HA restarted.

**Planning decision.** Reconnect by itself is not a reason to interrupt a healthy charging window or send the same
schedule. Persist a compact trustworthy comparison of the accepted plan's material price/cap/settings inputs and
compare it with the current plan after restart. Apply the existing SOC-only <5-minute tolerance only when the saved
and current evidence proves other material inputs unchanged. Unknown/missing provenance, a required sync, material
price/cap change, mismatch, or ownership change stays strict. Never infer SOC-only from similar end times. Keep the
Stage 14 price/cap thresholds and active-window continuity, and distinguish calculating a plan from sending it.

**Remaining groups, in this order:**
1. [x] **19.2 + 19.9a — recovery and Resume:** *(LOCAL, mocked: implemented locally 2026-11-18, manifest 2.5.193, mocked/isolated tests only; coordinator review pending; NOT hardware-verified. Done: durable pending Resume (`pending_resume`, bound to the Pause id, deleted by any later Stop/Pause) accepted by the UI action path while the old upload is unknown; guarded `resolve` through the production worker, `CommandAdmission` (ticket re-mint after restart permitted by a durable Resume without dispatch evidence; ambiguous records admitted to the guarded run, removal-in-doubt still blocks) and the single `_send_profile_shared`: a NEW attempt on profile 42001, the old attempt kept as bounded `unknown_history`, `supersession` risk record (`late_old_frame_not_excluded`, never cleared), persisted recovery pace 2/5/15/30/60 min then a 4 h ceiling, one wake timer, restart-safe. 2.5.194 follow-up: the standing risk now has an effective-readback look after the replacement, on reconnect (existing 15.3 triggers) and ONE look at the acknowledged profile's next planned transition (+120 s, checker-owned, armed only while the risk record exists, no polling); a confirmed mismatch converges through a paced guarded reassert (persisted `supersession.reassert`, 2/5/15/30/60 min then 4 h, not the repair budget/escalation); a pre-wire abort of a resolve restores the original ambiguous attempt (`resolve_prior`), never a settled record. 2.5.195 follow-up: a definitely rejected reassert is retried (checker look at the persisted `reassert.next_at`, two confirming reads, then the same guarded paced reassert; never a blind resend); the look watch is re-derived from the durable ledger at startup, on every check request (link edges included) and after every accepted/rejected/aborted send; a look made inconclusive only by a too-near change gets one bounded follow-up (at most 3). Not done / residual: charger ordering, late old frames and replacement semantics remain unverified, the looks are mitigation not proof, the retry/follow-up timers are memory-only (re-derived from the ledger on startup/link/send events, not a durable schedule); 19.3/19.5/19.6/19.7/19.8 remainders are separate groups; the old card has wording only.)* Wire the convergence policy, current-intent/Stop/Pause races, legacy
   uncertain records and actionable Resume through production admission and existing worker. Include durable pending
   Resume, legacy upgrade and restart; no placeholders or disabled-by-default feature gate. This is the main fix.
2. [x] **19.3 + 19.7 remainder — pacing and blockers:** *(LOCAL, mocked: implemented locally 2026-11-18, manifest 2.5.196, mocked/isolated tests only; coordinator review pending; NOT hardware-verified. Inventory found and closed only these gaps: 22 lifecycle/storage/ownership/identity reason codes had no `DECISION_BLOCKERS` entry and fell to the generic `see_reason` banner; the session-start recheck and busy-lock resolve retry stopped for good after their fast limit (a silent stop); `ownership_unavailable`/`profile_outcome_unavailable` session blocks had no timer; `OutcomeUnavailable` surfaced as `worker_unavailable`; `upload_not_sent` had no banner wording. Now: transient codes (lifecycle, quiescing, store/ledger unreadable-for-now, plan expired/unavailable) are in `TRANSIENT_BLOCKERS`, so the existing persisted 19.3 pace and observations apply (slow phase, restart-safe); the session recheck and resolve retry continue at `SLOW_RETRY_DELAYS` after the fast phase and record one observation per changed blocker; ownership/identity conflicts and an invalid ledger stay person-actionable with no timer; banner wording for the new actions and a calm fallback for an unknown reason. No send path, guard, Stop/Pause/identity/electrical check or 19.2 behaviour changed. Not done: session pace is memory-only (a restart re-evaluates at once); `schedule_mode_unarmed` after a restart stays person-actionable by the roadmap rule; no live HA/charger observation.)* extend existing persisted retry/observations to unknown recovery,
   session and lifecycle blockers, repair their actionable UI, and verify no contention or extra requests. Existing
   completed 19.3/19.7 code stays; fill gaps only.
3. [x] **19.5 + 19.9b — stable planning:** *(LOCAL, mocked: implemented locally 2026-11-18, manifest 2.5.197, mocked/isolated tests only (`tests/test_stage_195_provenance.py`, 14 cases, plus the existing worker/Stage 14/19 files); coordinator review pending; NOT hardware-verified. Root cause: after a restart the worker's first publication is classed `settings` (no previous key) and a reconnect/recovery wake is a snapshot-less `control`/`recovery` trigger; both ran strict, so a sub-5-minute SOC-only end drift was re-sent. Now an accepted routine profile stores compact `acknowledged.inputs` (`morek_schedule.material_inputs`: settings revision, price-source revision, price state, amps, cap, currency, power, ready-by instant, reading-basis flags, and the effective price rows of the calculation; no SOC value; >400 rows or any unreadable field = none). `_send_profile_shared(provenance_tolerance=)` applies the unchanged 5 min SOC-only tolerance to the startup first publication, a reconnect (`control`) and a `recovery` wake ONLY when `material_inputs_unchanged` proves every scalar equal and every still-future stored price row identical (a horizon that merely rolled over already-listed later prices is accepted; any inserted/changed/removed price in the stored coverage, or aged-out evidence, is not). Missing/older/mismatching provenance, a settings revision change, plug-in, sensor, price, recalc, a required sync, repair, pause/override and resolve stay strict; a mixed run with any such trigger is strict (`_hard`). It only suppresses a send after the plan was recalculated (`worker.dedup_basis == "soc_provenance"`, status `reconciliation.dedup_basis`); thresholds, `window_release`, cap/price rules and active-window continuity are untouched. Fallbacks: the 19.5(a) table stands; no further gap that needs no product choice was found, nothing invents SOC, price or capacity. Not done: provenance is written only at the next acceptance (existing records stay strict until one), the stored price rows age out when the whole stored horizon has elapsed (then one strict send), no UI wording, no live observation.)* implement the provenance policy above, missing fallback cases that can reuse
   known inputs, and tests for actual send counts and wire profiles. No invented SOC, prices or capacity.
4. [x] **19.6 — session start:** *(LOCAL, mocked: implemented locally 2026-11-18, manifest 2.5.198, mocked/isolated tests only (`tests/test_stage_196_g4_recovery.py`, 36 cases, plus the updated 19.6/15.5 files); coordinator review pending; NOT hardware-verified. Done: an ambiguous (`unknown`, `wire_intent`, legacy `pending`) start record is superseded only by a DIFFERENT token minted from a genuine new plug-in (Available -> Preparing) or a confirmed reboot, and only with fresh affirmative evidence postdating that event (HA-stamped Preparing and an explicit "no transaction" report; missing, stale, earlier-stamped, present-transaction or Charging seen = no start, named blocker, bounded recheck at the existing session pace, never a silent lock). The replacement is the normal guarded start (record-first, wire-intent marker, Stop/Pause/identity/protection/ownership re-validated at every boundary, plug-in evidence re-checked pre-wire); the old attempt is kept as bounded `history` (4, outcome `unknown`, never relabelled), the new attempt inherits the ambiguity until it is actually sent (an aborted replacement does NOT launder the old record), attempts are paced from the durable record (2/5/15/30/60 min then 4 h, `recoveries` counter, exact-remainder timer), the same token / reconnect / restart (`recovery`) / `offline:` / `unplug:` / `resume:` tokens never supersede, and routine sensor updates never repeat a start. Additive status `session_start_recovery` class `ambiguous_superseded` with `risk: duplicate_or_delayed_start_not_excluded`; `recovers_on` hint. Not done / residual: duplicate or delayed delivery of the old start, charger ordering/deduplication, and HA restamping the transaction sensor are unverified; an observed session never proves a specific ACK; recovery after an HA restart needs a new plug-in or reboot signal (the pace timer is memory-only); no card wording.)* reconcile an ambiguous start with fresh transaction/status evidence; preserve observation
   versus command ACK. For a genuinely new plug-in or confirmed reboot, use the normal guarded start after affirmative
   fresh Preparing/no-session evidence, keep the old ambiguity in history, and pace attempts. Treat duplicate/delayed
   start behavior as an explicit unverified device risk; never turn a Stop into a start or send repeated starts on
   ordinary sensor updates. Keep handling the same session separate from schedule replacement.
5. [x] **19.8 — integrated closure:** *(LOCAL, mocked: closed 2026-11-18, manifest 2.5.199, mocked/isolated tests only; coordinator review pending; NOT hardware-verified. Done: `tests/test_stage_198_scenarios.py` now 6 cases adding (a) the reported chain composed on the production worker/send path: legacy unknown + Pause + durable pending Resume → long offline outage (bounded wakes, nothing sent, intent kept) → restart while offline → reconnect → exactly one guarded replacement on 42001 with the active window carried and the old attempt kept `unknown` → restart → a 3 min SOC-only drift sends nothing; (b) a person Stop arriving while offline wins at reconnect and no plan is sent. **Defect found and fixed (pre-existing, affected every Resume):** a plan accepted under `resume_requested` was stored `routine: False`, so after a restart no accepted-plan comparison, provenance tolerance or continuity applied and one SOC-drift schedule was re-sent; the acknowledgement now carries `resume_plan: true` and `acknowledged_profile` and the two send-path comparisons treat a plan sent under the *current* Resume as a plan (holds, Charge Now and other pause ids unchanged; repair checks still use `routine`; records written before 2.5.199 stay strict until the next acceptance). **Closure additions (tests/docs only, no further production change):** `tests/test_stage_198_scenarios.py` now 11 cases: also (c) ~8 simulated days (400 triggers, fake clock, flapping triggers/publications) with the unknown upload + pending Resume offline: ≤ 8 INFO+ log lines, observations ≤ cap (8), ≤ 40 durable writes, no station id or profile payload in the log, a stale plan is never sent after the outage (`plan_expired` until a current plan is published) and the reconnect then sends exactly one guarded replacement with the old attempt still `unknown`; (d) a person **Pause** (not only Stop) arriving during the outage deletes the pending Resume, survives a restart and only the 0 A hold is sent once after reconnect; (e) session start and schedule recovery composed over one durable record: schedule recovery sends one profile and never rewrites the session record, the session coordinator then sends exactly one start on a genuine plug-in with fresh evidence, never a schedule, and neither old unknown attempt is relabelled; (f) a rejected horizon extension in an active window is retried at its pace, one guarded send, the window carried (no 0 A gap), an equal schedule afterwards sends nothing; (g) a wording audit test over the sidebar recovery strings and status fields (no “will charge”, “guaranteed”, “is charging”, unqualified “verified”, or a known old outcome; ACK `accepted`, readback `coverage_state` and `physical_charging: unknown` stay separate fields). Boxes 19.3, 19.5, 19.7 reviewed against the merged code and closed (see their entries). Not done / unverified: hardware R1–R7; the wording audit covers the sidebar recovery banner and the status fields, not every translated card string; session pace is memory-only (re-derived at restart); the send path stamps attempts with the wall clock, so long-outage tests age durable timestamps rather than the fake clock.)* Original scope: exercise the actual production paths, replay the reported legacy unknown + Pause →
   Resume, timeout/reconnect, restart, Stop/Pause races, active-window SOC drift, long offline periods, paced rejection
   and readback limitations. Update docs/test procedure and report exactly what is mocked and unverified.

Every group includes focused fast tests, relevant existing Stage 14 checks, required manifest bump and frontend
build/check-dist for integration/card edits. Work around a Windows harness failure only with a documented focused
runner; report real failures and unrun checks. No long or broad test suites. Mark a group partial if acceptance is
not met, but continue implementing independent work instead of stopping at diagnosis. Do not represent intermediate
planning notes or mocks as deployment or hardware proof.

### Evidence classes (binding wording and storage rule for every substage)

Never blur these. Each is a separate field/label; a higher class never implies a lower one is absent, and
none implies physical charging: **proposal** (calculated) → **pre-wire marker** (a durable record that a call
was *about* to begin; not proof it began) → **wire-started** (durable marker written after the call object was
handed to the connection, only where 19.1 can justify it) → **ACK** (Accepted/Rejected/NotSupported answer for
that attempt id, on time or **late**) → **effective readback** (`GetCompositeSchedule`: effective limits, not
an inventory of profiles, covering only its horizon) → **transaction** → **measured flow**. Also keep apart:
*observed* (a source reported it), *inferred* (SpotNav reasoned from observations) and *user-reported*.
Unknown is never zero, never “no”, never “failed”; an inferred pre-dispatch release must name its proof.

### Historical substage map (remaining execution order is the five groups above)

| # | Substage | Needs |
| --- | --- | --- |
| 1 | 19.1 Upload-outcome classification: provably pre-dispatch vs truly ambiguous | none |
| 2 | 19.2 Safe ordered replacement and late-response handling of an ambiguous upload | 19.1 |
| 3 | 19.3 Persistent paced automatic retries and durable, actionable observations | 19.1, 19.2 |
| 4 | 19.4 Ahead-of-time schedule, effective verification and offline operation | 19.1 (uses 19.2/19.3 for any ambiguous send) |
| 5 | 19.5 Planner fallbacks and active-window stability under the new triggers | 19.4 |
| 6 | 19.6 Session start unknown and reboot recovery | 19.1, 19.2 |
| 7 | 19.7 Storage, ownership and connection blockers | 19.3, 19.6 |
| 8 | 19.8 Cross-cutting scenario tests, evidence-wording audit and documentation closure | 19.1–19.7 |
| 9 | 19.9 Resume recovery, blocker clarity and reconnect stability | 19.1; coordinates with 19.2/19.5 |

### Stage 14 contract amendments (the only permitted changes to §5)

These amend §5 for **Stage 19 substages only**, are valid exactly as written, and do not loosen any row not
named. Where a row is amended, the Stage 14 regression file for it must still pass unmodified in its
existing cases (new cases may be added; an existing assertion may change **only** where the amendment states
it, with the change named in the report).

| §5 row | Amendment | Substage |
| --- | --- | --- |
| Uncertainty and recovery (uncertain latch) | The latch is no longer permanent for *every* uncertain record. It may be released **only** by (a) recorded proof that the wire call never began (19.1, named proof codes), or (b) the 19.2 resolution of a truly ambiguous record: the guarded current-intent convergence policy in the coordinator decisions above; the old attempt remains historically unknown even when a newer ACK permits forward progress. Preserve ACK and effective-readback evidence separately; lack of readback must not create a permanent deadlock. Never relabel the historical outcome based on age, readback alone, retry count, UI action, or `clear_profile`. Every other uncertain record keeps today's behavior. A release is a recorded, evidenced transition, never a silent flag flip. | 19.1, 19.2 |
| Uncertainty and recovery (`REJECTION_RETRY_DELAYS` 5, 15 min; 12-check cap of non-sending timers) | The two named delays stay exactly as they are. After them, a **slower persisted pace** (named constants chosen and listed by the delegate; each spacing ≥ the last) may continue for a definitely rejected intent and for blocker re-evaluation, surviving restart, with no per-retry log line or banner churn (19.3). The 12-check cap on *timer-driven* re-evaluation is replaced by that slow pace only for non-sending checks; a timer may initiate guarded resolution of an unknown schedule under 19.2; any send remains a guarded `_send_profile_shared` run. | 19.3 |
| Dedup (`same_effective_schedule`, fingerprint skip) | Unchanged for every run. A new trigger `resolve` (19.2) bypasses **only** the `upload_uncertain` return, only when 19.2's conditions hold, exactly as `repair` bypasses only the `unchanged` returns; it respects rejection pacing and a separate persisted recovery pacing policy; it does not bypass protection or create a permanent repair-budget lock. | 19.2 |
| Protected active window (`continue_active_window`, `connector_evidence`, 180 s) | Rule unchanged, including the strict 180 s bound and “unknown never releases”. An ahead-of-time horizon (19.4), a resolve resend and a slow retry carry the acknowledged window to its end and never produce a 0 A gap in the wire profile. | 19.2–19.5 |
| Material triggers (`window_release`) and SOC tolerance (5 min, SOC-only, 2 s coalescing) | **Numbers unchanged** (EUR 0.50, 10%, 30 min gap, 15 min slack, strictly lower cap, 5 min, 2 s). Stage 19 adds no trigger class that can release a window: `resolve`, slow retry, ahead-of-time extension and observation events carry no price-change or cap-lowered cause. 19.5 may add tests and fix a confirmed bypass; changing any threshold needs a new explicit user decision (§9). | 19.5 |
| Stop / Pause / Charge Now ownership | Unchanged and wins over every Stage 19 trigger, including a `resolve`, a slow retry and a late response. Each re-checks the generation after every persistence await; a refused run consumes no budget and records nothing as sent; a Stop never becomes a run; a Pause hold or Charge Now override is resolved or retried only as itself. Pause/Stop, protection and identity are **never** relaxed to reduce uncertainty. | all |
| Decision evidence (bounded 14.6 events) | Shape reused (new codes, repeats increment, one line per *changed* decision). Amended only so a **bounded** summary of the latest decisions/observations may be persisted through the existing ledger/evidence store (19.3) instead of memory only. No new log store, sensitive payload or per-retry line. | 19.3, 19.7 |
| Recovery sync, measured progress (14.3/14.5) | Unchanged. | — |

### Substages

- [x] **19.1 Upload-outcome classification: provably pre-dispatch vs truly ambiguous ◆.** *(Implemented locally 2026-11-18, 2.5.180, mocked/isolated tests only; coordinator review pending; see the handoff entry. Review fix: the read-side pre-wire release now runs at the real admission boundary (`async_execute` owned_profile, restart reconfirmation, barrier release) under the connector lock, and `upload_not_sent` re-evaluates through the existing bounded blocker timer. Wire-started-after-handoff marker rejected as unjustifiable: a before-call `wire_intent` marker is used and its presence stays ambiguous; call exceptions stay ambiguous because the `ocpp` source could not be inspected here.)* *Seam (source reading,
  verify first):* `_send_profile_shared` and `_outcome_record`/the ledger in `api/morek_schedule.py`, the
  `spotnav_morek_dispatched`/`dispatch_started` diagnostics, and the worker's handling of
  `upload_uncertain`/`TRANSIENT_BLOCKERS`. *Scope:* replace the single `uncertain` meaning with a small
  classification recorded on the attempt, additive and restart-safe, reusing the existing record: **provably
  not sent** (every exit after the pre-wire persistence and before the wire call is handed to the connection:
  ledger changed, durable check failed or refused, validation after persistence, cancellation before the call;
  plus a restart that finds a pre-wire marker with no wire-started marker, *only if* 19.1 shows by ordering
  of durable writes that the wire call cannot have begun — otherwise that case stays ambiguous),
  **ambiguous** (the call began and its outcome is unknown: timeout, exception from the call, interrupted ACK
  persistence, restart after a wire-started marker) and **resolved** (ACK or rejection recorded). Decide and
  document, with a test, whether a durable wire-started marker can be written before the call without
  weakening the “record first” rule or creating a window where the marker claims more than is known; if it
  cannot be justified, say so and keep those cases ambiguous (no guess). Pre-dispatch-proven attempts release
  the latch with a named proof code and **do not consume a rejection retry or a repair budget entry**; the
  next normal trigger may send. A call that raised before reaching the wire is pre-dispatch **only** where
  the OCPP library demonstrably cannot have transmitted (inspect `ocpp`/`point.call` source and record the
  conclusion); otherwise ambiguous. Existing stored `uncertain: True` records without the new field are
  treated as ambiguous (never silently released on upgrade). Surface the class in status `reconciliation`
  (additive) and the decision event. *Acceptance (real worker and send path):* each pre-wire exit → proof code,
  latch released, zero wire calls, next trigger sends once; timeout/exception/cancel-after-start/restart-after-
  start → ambiguous, still blocking, never auto-retried here; legacy records stay blocking; Stop/ownership
  races at every await; no budget consumed by a refused run; no blind retry; wording says “not sent” only
  with proof. *Exclusions:* no resolution of an ambiguous record (19.2), no timer, no UI beyond the status
  field, no `clear_profile`.
- [x] **19.2 Safe recovery from ambiguous schedule writes ◆.** *(Implemented locally 2026-11-18, manifest 2.5.193, mocked/isolated tests only; coordinator review pending; NOT hardware-verified. Done: durable pending Resume (`pending_resume`, bound to the Pause id, deleted by any later Stop/Pause) accepted by the UI action path while the old upload is unknown; guarded `resolve` through the production worker, `CommandAdmission` (ticket re-mint after restart permitted by a durable Resume without dispatch evidence; ambiguous records admitted to the guarded run, removal-in-doubt still blocks) and the single `_send_profile_shared`: a NEW attempt on profile 42001, the old attempt kept as bounded `unknown_history`, `supersession` risk record (`late_old_frame_not_excluded`, never cleared), persisted recovery pace 2/5/15/30/60 min then a 4 h ceiling, one wake timer, restart-safe. 2.5.194 follow-up: the standing risk now has an effective-readback look after the replacement, on reconnect (existing 15.3 triggers) and ONE look at the acknowledged profile's next planned transition (+120 s, checker-owned, armed only while the risk record exists, no polling); a confirmed mismatch converges through a paced guarded reassert (persisted `supersession.reassert`, 2/5/15/30/60 min then 4 h, not the repair budget/escalation); a pre-wire abort of a resolve restores the original ambiguous attempt (`resolve_prior`), never a settled record. 2.5.195 follow-up: a definitely rejected reassert is retried (checker look at the persisted `reassert.next_at`, two confirming reads, then the same guarded paced reassert; never a blind resend); the look watch is re-derived from the durable ledger at startup, on every check request (link edges included) and after every accepted/rejected/aborted send; a look made inconclusive only by a too-near change gets one bounded follow-up (at most 3). Not done / residual: charger ordering, late old frames and replacement semantics remain unverified, the looks are mitigation not proof, the retry/follow-up timers are memory-only (re-derived from the ledger on startup/link/send events, not a durable schedule); 19.3/19.5/19.6/19.7/19.8 remainders are separate groups; the old card has wording only.)* Implement group 1 above with 19.9a. Existing
  19.1 pre-wire proofs stay intact. Keep old outcomes unknown, send a fresh guarded current intent, maintain durable
  intent ordering and paced reconciliation, preserve active-window continuity and Stop/Pause precedence. Explicitly
  label unverified charger ordering as residual risk; no arbitrary expiry and no permanent lock just because proof
  of perfect delivery ordering is unavailable. Acceptance: real admission/worker tests cover legacy unknown, ACK,
  no ACK, differing/short readback, timeout/restart, late old responses, Pause/Stop races, plug-in and repeated
  reconnects; assert requests are paced, unchanged healthy schedules deduplicated, wire profile continuous, no false
  claim about old outcome or physical charging. Use the coordinator decisions above where earlier §5 text conflicts.
- [x] **19.3 Persistent paced automatic retries and durable, actionable observations ◆.** *(CLOSED locally 2026-11-18 after review of the merged code: the “not done” items below were delivered by 19.2 (timer-initiated guarded resolution, 2.5.193–195) and group 2 (session and 19.7 blocker observations, 2.5.196); flapping/long-outage log volume is pinned by `test_stage_193_paced_retries` and `test_stage_198_scenarios`. Mocked only. Original 2.5.187 note:) (PARTIAL, implemented locally 2026-11-18, 2.5.187, mocked/isolated tests only; coordinator review pending. Done: slow persisted pace (`SLOW_RETRY_DELAYS` 30 min..4 h ceiling) after the fast delays for definite rejections of a still-current intent and for non-sending blocker re-evaluation, surviving restart (rejection pace from the durable attempt count; blocker pace and a bounded newest-wins list of 8 actionable observations in the existing outcome record key `retry_state`, debounced, written only under the schedule lock); slow re-sends are counted repeats, not log lines; persistence failure visible in status `reconciliation.recovery.persistence`; ambiguous records are never retried. **Not done:** timer-initiated guarded resolution of an unknown schedule (needs the unimplemented 19.2), so the acceptance "unknown records are resolved only through the guarded paced path" is open; observations for session-start and 19.7 blockers. Named existing-assertion changes are listed in the handoff.)* *Needs 19.1, 19.2.* Review fixes in manifest 2.5.188: guarded connector+schedule lock flush, re-arm after active/failed flush, persisted next_at kept on restart (see handoff).
  *Scope:* (a) **Retries:** extend the existing retry timers (not a second scheduler): after
  `REJECTION_RETRY_DELAYS` and after the blocker-timer cap, continue at a slow, monotonically non-decreasing,
  *persisted* pace (state in the existing ledger record, restart-proof; constants chosen and listed by the
  delegate, with a ceiling) for definite rejections of a still-current intent, for `resolve` runs that are
  still allowed, and for non-sending blocker re-evaluation. Every retry is a normal guarded run; a changed
  plan restarts the pace; Stop/Pause/ownership/identity win; ambiguous records are never blindly retried; a timer may invoke 19.2’s guarded resolution. (b) **No spam:** a repeat of the same decision increments a
  counter; one INFO line per *changed* decision/observation; at most one banner state per episode; no
  notification per retry; the user-facing text shows the next automatic attempt time and the count, not a
  stream. (c) **Durable observations:** persist a *bounded* list (named cap, newest wins) through the existing
  ledger/evidence store of actionable observations — what was observed, which evidence class, who acts
  (system/vehicle/person), what happens next — so they survive restart; reuse 14.6 codes; observation,
  not command history; no payloads, ids or prices. Sidebar/recovery banner reads them through the existing
  status (no new panel). *Acceptance:* a long outage retries at the slow pace across a restart without a
  burst, the pace resets only on a changed plan/blocker, the log/observation volume is bounded under a
  flapping link, an equal schedule sends nothing, unknown records are resolved only through the guarded paced path, persistence failure is
  visible, not silent. *Exclusions:* no new store, controller, push-notification channel or periodic
  OCPP readback.
- [x] **19.4 Ahead-of-time schedule, effective verification and offline operation ◆.** *(Implemented locally 2026-11-18, 2.5.181, mocked/isolated tests only; coordinator review pending; independent of the blocked 19.2. Audit result: (a) the production profile already covered every known planned window through its end within the existing three-window/eight-period limits (`profile_for` over `proposal.shown_periods`, refusing — never truncating — a fourth window, never inventing a window for unpublished prices); no code change was needed, and a test now pins the wire profile, the partial-price day and the single compared extension. (b) Added: additive `coverage_state` (`matches` | `matches_covered_span` | `differs` | `not_verifiable`), `covered_until` and `plan_end` on the existing one-shot verification, with the card wording "matched only until …, not verified for the whole plan"; `matched`/`reason` are unchanged, so no gate (session-start evidence, Healthy check, dedup) reads a partial span as verified. (c) Added: status `reconciliation.horizon` (last sent schedule's end, window count, charger answer, coverage class; `physical_charging` always `unknown`) and the sidebar link-lost text naming the last-known end, what depends on the charger's own clock/settings/authorization, that nothing is guaranteed and that SpotNav cannot start or change anything while offline. **Not done / not claimed:** an ambiguous upload is still not resolved (19.2 blocked; 19.4 neither bypasses nor relaxes the latch); the horizon is not extended by a new send path or periodic readback; whether a retained profile governs a session while HA is down, and how the charger's clock behaves, are unobserved. Existing 15.3 reconnect check and one-shot verification remain the only readers. Review correction: `covered_until` now stops where comparison stopped (reported end minus the 90 s tolerance), and offline wording does not imply installation when the charger's answer was not `accepted`.)* *Needs 19.1.* *Scope:*
  (a) **Horizon:** audit what the dispatched profile covers versus what the planner already knows (published
  prices, the real ready-by, up to the existing three windows / seven transitions and final 0 A). The sent
  profile should cover **every known planned window through its end**, so a retained schedule can keep
  governing an authorized session while HA or the link is down; where tomorrow's prices are unpublished the
  profile covers the known part and says so (Stage 16 partial plans), and never invents a window. A later
  publication extends the horizon through the normal compared reconcile (no active-window release, no
  duplicate send for an equal result). (b) **Effective verification:** the existing post-send readback
  (`GetCompositeSchedule`) is judged against the *whole* sent horizon it can cover, with an explicit
  covered-until instant; three states — *matches over the covered span*, *differs*, *not verifiable /
  horizon shorter than the plan* — shown with the covered span, never as “verified for the whole plan” when
  coverage is shorter, and never as physical charging. No periodic readback is added; the existing
  one-shot verification and the 15.3 reconnect check are the only readers. (c) **Offline operation:** UI/status
  wording for “schedule on the charger, HA offline: last known” (existing 15.2/15.7 states) names the
  schedule's last-known end, what depends on the charger's clock/firmware/authorization, and that SpotNav
  cannot start a session or change anything while offline. **No absolute guarantee:** Morek's own protection
  (load/CT limits, its own configuration, a power cut, a clock fault, a conflicting profile) may stop or alter
  charging independently, and SpotNav says “planned/accepted/effective-readback”, never “will charge” or
  “guaranteed”. *Acceptance:* the sent profile equals the displayed windows through the covered end
  (asserted wire profile); partial-price day sends only the known part and labels it; later publication
  extends once; readback shorter than the plan → “covered until”, not verified-all; mismatch path unchanged;
  offline wording shows last-known facts; no new send path. *Exclusions:* no dynamic amps, no load
  balancing, no claim about charger clock/firmware/authorization behavior, no authorization change.
- [x] **19.5 Planner fallbacks and active-window stability under the new triggers ◆.** *(CLOSED locally 2026-11-18 after review of the merged code: `resolve` (window carried, 19.2), late response (`test_stage_192_late_frame`), slow retry in a window (`test_stage_198_scenarios::test_rejected_extension_in_an_active_window...`) and the restart/provenance case (19.9b, 2.5.197, 2.5.199 Resume-plan fix) are now tested with real send counts and wire profiles. The one remaining fallback is a product choice and is NOT implemented: a default plan with unknown SOC (§9 D6); the existing planner hold with its who-acts sentence stays. Mocked only. Original 2.5.182 note:) (PARTIAL, implemented locally 2026-11-18, 2.5.182, mocked/isolated tests only; coordinator review pending. Done: (a) every `AutoReason` is classified in `tests/test_stage_195_fallbacks_stability.py` (plans / healthy / hold / retired / internal); the 11 holds that had no who-acts (`settings_missing`, `fiscal_value_missing`, `minimum_above_target`, `price_policy_unavailable`, `solar_execution_unavailable`, `deadline_too_short` → person; `price_data_invalid`, `insufficient_price_horizon`, `publication_pending`, `waiting_for_history` → system, wait for prices; `unexpected_failure` → logs) now state who acts through `EXTRA_PLANNING_HOLDS`, reusing existing banner actions (no frontend wording change). No fallback invents a price, capacity, car or SOC; no product decision was needed, so §9 gets no new entry. (b) Real-worker tests: status/observation reads, routine publication, SOC drift inside 5 min and equal schedules send nothing in a healthy window; a horizon extension sends once with the window carried (no 0 A gap) and an equal repeat sends nothing; a planner hold clears nothing. No bypass was found; no threshold changed. **Not done:** `resolve`, late-response and slow-retry stability cannot be tested because 19.2 is blocked and 19.3 is unimplemented; rejection-retry-during-window stays covered only by the existing 14.2 test. The row-per-test proof for fallback rows that plan points to existing Stage 16/17 test files rather than new real-planner cases. Acceptance depending on 19.2/19.3 is therefore open.)* *Needs 19.4.*
  *Scope:* (a) **Planning fallbacks:** list (as one test-backed table, extending Stage 17's) every remaining
  planning hold that leaves **no** current intent or an obsolete one, state which already have a fallback
  (retain the last accepted plan; plan from an honest estimate; partial published plan; labelled unknown
  progress) and which do not, and close only gaps that need **no new product choice**: reuse an existing
  honest input and label it, or keep today's hold with a who-acts sentence. A fallback never invents a price,
  a capacity, a car identity or an SOC; anything that would need such a choice (for example a default plan
  with unknown SOC) is **not implemented** and recorded as a §9 open decision for the user. (b) **Stability:**
  prove, with the real controller and worker, that the new paths (horizon extension, `resolve`, slow retry,
  late response, observation events) cause no extra send during a healthy active window beyond the
  existing triggers: SOC-only drift inside 5 minutes, routine publication and equal schedules send nothing;
  only the Stage 14.4 cap/price rules and the 15.x repair/recovery rules may touch a window, with unchanged
  thresholds; a resolve or retry resend carries the acknowledged window. Fix a **confirmed** bypass found by
  these tests; do not tune thresholds. *Acceptance:* the fallback table with a test per row; stability cases
  (SOC drift, publication, equal schedule, late response during a window, retry during a window, horizon
  extension) assert actual send counts and wire profiles; all Stage 14 files pass as before. *Exclusions:*
  threshold changes, new settings, forecasts, invented inputs.
- [x] **19.6 Session start unknown and reboot recovery ◆ (group 4 implemented locally 2026-11-18, 2.5.198, mocked only; review pending).** Preserve the implemented pre-wire proof and
  observed-session classification. Complete group 4 above. Test fresh transaction evidence, unknown across restart,
  new plug-in and confirmed reboot with affirmative no-session evidence, missing/stale evidence, late old request,
  pacing, Stop/Pause races, no duplicate sends on routine updates and recovery without permanent silent blocking.
  Record the unverified duplicate/delayed-start risk and never claim an observed session proves a specific ACK.
- [x] **19.7 Storage, ownership and connection blockers ◆.** *Needs 19.3, 19.6.* **CLOSED locally 2026-11-18 after review of the merged code: the blocker table, wording and recovery tests were completed by group 2 (2.5.196, `test_stage_1937_blockers_pacing`, 19 + 13 frontend cases) and ownership/identity conflicts stay person-actionable and untimed; session pace is memory-only. Mocked only; hardware unverified. Original 2.5.186 note — PARTIAL (2026-11-18, 2.5.186, local, review pending):** only the independent parts exist — verified-reread recovery of a poisoned outcome ledger (internally serialized by one leaf lock; never reinitializes or overwrites an invalid/unreadable file, only a missing one; cancelled saves recover only when the late write is proven landed) and an upload-only link gate (`_upload_available`: switch OR live supported OCPP link) at the worker's reconcile/dispatch checks; a switch that *changes* to unavailable still suspends until it returns, **except (2.5.189, local, mocked tests only)** when the live supported OCPP link holds: the same owner/ticket/ledger-verified barrier release then runs and only the upload path resumes; if the link was down at the edge, **(2.5.191)** the wait is also re-evaluated at a paced 60 s→600 s backoff on the monitor's readings while the link stays up, so a transient refusal cannot strand the worker (a person Stop stays permanent); the existing link monitor's next live reading re-runs that guarded release once per link return (2.5.190, no switch event needed; see the handoff). The blocker table and some wording/recovery tests and session observations remain incomplete; 19.3 already implements slow pacing and bounded observations for supported cases. See the handoff. *Scope:* one test-backed
  table (like 17.6's `PLANNING_HOLDS`, reusing `decision_blocker`/the recovery banner) of the blockers that
  stop or stall an automatic send for reasons *outside* planning: **storage** (a ledger/store write that
  fails or is unavailable before or after the pre-wire marker, a record that cannot be read or fails
  validation), **ownership** (another controller or a migration/held-exit record owns the connector, a stale
  generation, a reserved person Stop), **identity** (charger alias unresolved, wrong or ambiguous station)
  and **connection** (link down, `morek_offline`, charger unavailable, admission busy). For each: whether
  it can be proven pre-dispatch (19.1), who acts, the existing automatic recovery trigger (and 19.3's slow
  pace where one applies), the evidence class, and the banner/status sentence. Audit and fix recoverable store poisoning by verified reread and safe reinitialization, and decouple schedule-upload availability from a misleading switch where live OCPP connection and admission evidence suffice. Fix mismatches found:
  a blocker with no recovery or no who-acts, wording that implies a charging failure, a storage failure
  after a wire-started marker mislabeled as pre-dispatch, a blocker that recovers by weakening a guard.
  **Identity, ownership, protection and Stop/Pause checks are never relaxed here**; a storage failure that
  could hide a dispatched write stays ambiguous. *Acceptance:* every listed blocker has a wording test and a
  recovery test (condition clears → one guarded re-evaluation → at most one send); storage failure before
  the marker → not sent, retried at the slow pace; after → ambiguous; ownership/identity conflicts remain
  person-actionable and are not retried by timer; observations (19.3) record each once. *Exclusions:* no new
  store, panel, retry family, or change to the physical-station check; no automatic ownership transfer.
- [x] **19.8 Cross-cutting scenario tests, evidence-wording audit and documentation closure.** *(Closed locally 2026-11-18, 2.5.199: see group 5 above; mocked only; hardware R1–R7 unverified.)* *Needs
  19.1–19.7.* *Scope:* a small set of end-to-end mocked scenarios through the real planner, worker and session
  coordinator: (1) ambiguous upload during an active window → paced guarded resolution → ACK and readback tracked separately, window never gapped; (2) pre-wire ledger failure → not sent → slow retry → one send; (3) HA down
  with a retained schedule → wording shows last-known and no guarantee; (4) unknown session start across a
  confirmed reboot; (5) the same flows with a person Stop/Pause racing each step (Stop wins, nothing marked
  sent); (6) a long outage across restart with bounded logs. Then audit every new or touched sentence and
  status field against the evidence classes (no “verified”, “charging”, “will charge”, “guaranteed” without
  the matching evidence; inferred is labelled), reconcile the roadmap checklist, handoff and
  `docs/morek-schedule.md` test procedure, and record in the handoff the *exact* list of unverified
  assumptions (§9 R1–R7). *Acceptance:* the scenarios pass with real send counts and wire profiles; wording
  audit finds no violation (or each is fixed); docs are truthful; unrun checks are named. No new feature.

**Out of scope for Stage 19 (do not add):** load balancing or dynamic amps, changes to Morek's configuration
or authorization, `ocpp.clear_profile` or any selective cleanup as automation, a second sender/controller/
scheduler, periodic OCPP polling, new settings for thresholds, a standalone HA app, hardware experiments (E1/E2
and any hardware test remain user-directed evidence tasks that block nothing here).

**Unrun and unverified (carry in every substage report):** installed behavior; whether the charger replaces a
profile by id/stack and in what order after a timed-out call; whether a late response can be received and
attributed; whether a retained profile survives charger reboot or power loss and how its clock behaves; full
suites, browser/Playwright and HA-fixture tests (`fcntl` plugin). Mocked checks never prove physical charging.

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

- [x] **13.1 Vehicle sources and planning properties.** Inspect the selected vehicle’s actual SOC source and
  integration; choose among ambiguous suitable sensors; configure usable battery capacity when not reported;
  choose onboard charging phases where existing settings support it. Reuse discovery/confirmation and
  vehicle-property APIs; show reported vs overridden values and missing inputs. Coordinate with 12.5, 12.6,
  12.8. Never silently choose an ambiguous source, invent capacity, overwrite a saved selection or treat an old
  reading as new. Tests: ambiguous/missing/removed sensors, reported vs overridden capacity, phases,
  stale observations.
  *Locally implemented with mocked checks (2.5.158); committed `d81c3fd8`; separate coordinator review not recorded; not installed or live-verified.*
  A collapsed “Advanced: vehicle sources & properties” section is added to the shared sidebar UI (also in the local
  preview as a fictional read-only sample). It reuses the existing admin-only commands `get_entity_config` (read),
  `choose_vehicle_soc` and `update_vehicle` (capacity / onboard phases, compare-and-set `expected`). 2.5.157 adds small backward-compatible
  backend pieces: `get_entity_config.config.vehicle_properties`, an optional `expected_entity_id` guard and replan on `choose_vehicle_soc`.
  It shows the selected car's sensor state (ambiguous / chosen by you / automatic / missing / removed or unavailable),
  the current reading with its age and a stale marker, capacity as reported (read-only) / entered by you / missing, and
  onboard phases with the existing single-phase suggestion (shown, never applied). Never silently picks a car or sensor,
  keeps a removed saved sensor visible, confirms replacing/clearing a saved choice, sends the choice it displayed as
  `expected_entity_id` so the backend refuses a changed one under a lock (conflict, nothing written), sends nothing for an unchanged or invalid save, keeps
  drafts across refreshes, blocks on a stale config/dashboard, treats a timeout/permission change as an unknown outcome
  that needs an explicit reload, and leaves Stop/Pause/Charge Now untouched. Opening/editing only reads.
  **Corrections (2.5.157):** capacity/phases now show for a car with an ambiguous or missing sensor (read-only
  `vehicle_properties` block; reported vs stored vs missing, a vehicle-reported capacity is “unknown” until a sensor is
  chosen) and are written with `update_vehicle` (compare-and-set against the stored values; the answer's `vehicle` is
  null there). The sensor save is server-guarded; a real change of the sensor in use runs the existing planner
  recalculation for the chargers planning that car (none for a no-op); no command or wake.
  **Limits:** (1) the `hass`-fixture Python tests for these backend changes cannot run on Windows (HA plugin needs `fcntl`); the isolated `tests/test_vehicle_soc_guard_isolated.py` (7 pass) exercises the real functions with HA boundaries faked, and nothing was run against HA; (2) the guard compares the saved choice only; the `confirm_vehicle_soc`/`unconfirm_vehicle` services share its lock (2.5.158) but do not replan, and the Repairs fix flow, config flow and dismiss are not serialized with it; (3) “removed” is judged from the candidate list and HA's entity state, so a sensor that
  exists but is unavailable is marked as reporting nothing, not removed; (4) whether a Morek owner re-uploads after the
  replan is the existing reconciliation's behaviour, unverified; (5) the 13.1 area has no i18n (English text); (6) no
  browser/Playwright, not installed.
- [x] **13.2 Market and charging-cost settings.** Expose existing market/price-area selection and tariff
  settings (VAT, energy tax, grid fees incl. existing time-dependent/percentage options). Keep provider
  route, held-data provenance, selected market, raw price and configured variable cost distinct; never
  silently switch provider, enable fees or assume prices exclude charges; keep 12.2’s c/kWh display. Tests:
  supported/missing providers, area changes, variable/negative prices, fee basis, currencies, settings-to-plan
  updates. Do not invent historical tariffs.
  *Locally implemented with mocked checks (2.5.159); committed `7e352562`; separate coordinator review not recorded; not installed or live-verified.*
  A collapsed “Advanced: market & charging costs” section is added to the shared sidebar UI (also in the local preview as
  a fictional read-only sample), new files `sidebar/market-costs.js` (pure model and write plans),
  `sidebar/market-costs-panel.js` (panel wiring) and `shared-dashboard/market-costs-view.js`. **No backend change.** It reuses
  the existing canonical commands and the old card's own builders/decoders (`src/market.ts` `marketReplacement`,
  `src/grid-tariff.ts` `storedBody`/`sameBody`): `get_market_options` (read, any signed-in user), `update_settings`
  (price area and VAT / energy tax / flat grid fee: off, the area's suggestion kept as “suggested” and never copied, or the
  person's own figure; compare-and-set on the wire revision), `update_grid_tariff` (grid fee as % of the raw price and the
  high-load fee with its days/months/hours window; compare-and-set on the price entry's write counter; demand-charge
  components are sent back exactly as stored) and `choose_price_source` (only when several entries exist, with confirmation).
  All writes are administrator-only. It shows, separately: the provider (`prices.provider`) and the held-data state
  (`prices.state`, interval count and resolution, area-list state, “held, not proof the provider answered”), the saved
  vs selected area and its currency/units (c/kWh display unchanged; flat fees in the area's minor unit/kWh exactly as stored,
  no conversion), the current interval's raw published price next to its configured variable cost (negative values and unknowns
  kept as such, `unknown` is never zero), per-component “included in the published price” locks and the planner's order of
  fee application (raw + tax + flat/high-load fee + % of raw, then × (1 + VAT)). Never silently picks a provider, area or entry,
  enables a fee, assumes what a price includes, invents hours (suggested hours are labelled and only saved with the fee on) or
  reconstructs historical tariffs. A changed area asks for confirmation and says that the provider route and currency change, fees
  do not carry over and a soft price cap is not converted. Opening/editing only reads; unchanged and invalid saves send nothing;
  drafts survive refreshes; a stale dashboard or area list, a pending post-save dashboard read, another writer's change while
  editing (signature check), a revision conflict (nothing written, reload required), a reconcile failure after a durable save, a
  permission change or timeout (unknown outcome, saving blocked until an explicit reload) are all handled. A successful tariff or
  price-entry write re-reads the settings record (the wire revision includes the price entry's write counter).
  **Limits:** (1) the area, tax and fee **replan** is the backend's existing behaviour after `update_settings` and a price-entry write;
  whether a Morek owner then re-uploads is the existing reconciliation, unverified; (2) a price-entry/area change is applied to every
  charger using that entry, said in text but not previewed per charger; (3) demand-charge components, the import target and the
  Nord Pool key/price-provider setup remain in the old card (not duplicated here); (4) English text only, no i18n for this area;
  (5) no browser/Playwright, no HA-fixture Python tests (none needed, no backend change), not installed; (6) the sidebar read-only
  host tests were extended to allow the new read-only `get_market_options` message; (7) for a selected-but-unsaved area only the
  area list's suggestions are shown, not computed per-fee amounts.
- [x] **13.3 Practical plan and charger parameters.** Maximum charging periods, planned current, supported
  departure date/weekday options not already in 12.5 (no duplicate ready-by/cap/minimum/target controls and no
  duplicate of the 15.1b reserve control). Planned current is a planning input, not load balancing; respect
  charger/electrical bounds and Morek transition/period limits; never raise current or change protection
  automatically. Tests: period counts and currents, date/weekday/deadline, DST, conflicts, backend replanning.
  *Locally implemented with mocked checks (2.5.161); committed `416529c3`; separate coordinator review not recorded; not installed or live-verified.*
  **Morek 16 A guard (2.5.161):** the Morek schedule needs exactly 16 A, so while Morek owns the schedule only 16 A can be saved here (other values refused, saved value kept and flagged); with unknown ownership a non-16 save asks first; otherwise normal. Frontend-only; the backend refusal stays final.
  A collapsed “Advanced: plan & charger parameters” section is added to the shared sidebar UI (also in the local preview as a
  fictional read-only sample); new files `sidebar/plan-params.js` (pure model and write plans), `sidebar/plan-params-panel.js` (panel
  wiring) and `shared-dashboard/plan-params-view.js`. **No backend change, no new API message.** Every write is the existing
  canonical `update_settings` replacement (compare-and-set on the wire revision), built from the accepted record with only the
  fields owned here changed, using the card's own validators (`chargePeriodsReplacement`, `replacementFor('current'|'deadline')`).
  Three groups, each with its own Save: **maximum charging periods** (Automatic or 1–8; administrator-only, as the backend requires);
  **planned current** (whole amperes, judged against the dashboard's `current_range`, with the everyday 6–32 A shown and labelled as
  such when the charger reports none; the backend still refuses a value above the charger's own maximum; a raise asks first; a stored
  out-of-range value is shown with a warning and kept exactly as saved, never adjusted); **departure date and weekdays** (date picker
  limited to today..+7 in the market's local calendar, weekday ticks; only while ready-by is on). Ready-by on/off and time, target, cap,
  minimum and reserve stay in Plan controls and are not repeated. Non-administrators can edit current and departure only where the
  charger's `users_change_plan` allows it (the backend's `NON_ADMIN_FIELDS` rule); periods stay administrator-only. The area states, as
  text, that planned current is a planning input and not load balancing or protection and that nothing raises it automatically; that
  Morek carries at most 3 windows per plan (`MOREK_MAX_BLOCKS`), so the effective limit while Morek owns the schedule is `min(cap, 3)`
  (ownership is taken from fresh Morek status, otherwise shown as “not known”); the nominal kW at the saved current and phases (a
  planning figure, not a measurement); the next departure in the market calendar; and that a save may recalculate the plan and lead to
  normal guarded reconciliation when Morek owns the schedule, without waking the car, notifying, changing protection or proving
  charging. Opening and editing only read; unchanged and invalid saves send nothing; drafts survive refreshes; a stale dashboard, a
  pending post-save dashboard read, another writer's change to these fields while editing (signature check; unrelated plan changes do
  not count), a revision conflict (nothing written, reload required), a reconcile failure after a durable save, a refused code, and a
  timeout or permission change mid-save (unknown outcome, saving blocked until an explicit Reload) are all handled. It shares the plan
  form's pending/unknown-write bookkeeping, so two `update_settings` saves of one record can never overlap.
  **Bug fixed on the way (shared with the old card's date picker):** `departureDays(...).nextOccurrence` compared the wall time with the
  *elapsed* time since local midnight, which is an hour off on a 23 h or 25 h day; it now uses the wall clock's reading (tested on both
  Stockholm clock changes).
  **Limits:** (1) a *newly chosen* date of today whose time has already passed is refused locally; whether the backend treats it
  differently is not verified; (2) a Morek owner's re-upload after the replan is the existing reconciliation's behaviour, unverified;
  (3) the section does not show the plan's *effective* window count, only the cap and Morek's limit; (4) the charger-range bound is only
  as good as the dashboard's `current_range` (the default range when none is reported); (5) English text only, no i18n for this area;
  (6) no browser/Playwright, no HA-fixture Python tests (no backend change), not installed; (7) `test/sidebar.test.ts` passes (90) but
  takes about 33 s here, so run it separately from the focused set.
- [x] **13.4 Notification settings and concise setup diagnostics.** Per-charger recipients (HA mobile apps)
  and event settings; show no-recipient, unavailable, permission and save failures; a compact actionable view
  of existing capability/setup warnings (missing/ambiguous measurement sources, pricing configuration,
  execution blockers where exposed), linking to settings and reusing 12.4/12.7 text. A notice never proves a
  plan was sent or charging measured. Tests: missing phones, selected events, persistence, permissions.
  *Implemented with mocked checks (2.5.162); committed `e31463df`; recorded as coordinator-reviewed; not installed or live-verified.*
  A collapsed “Advanced: notifications & setup check” section is added to the shared sidebar UI (also in the local preview as a
  fictional read-only sample); new files `sidebar/notify-setup.js` (pure model, diagnostics, write plan), `sidebar/notify-setup-panel.js`
  (panel wiring) and `shared-dashboard/notify-setup-view.js`. **No backend change, no new API message.** Recipients and events are saved with
  the existing canonical `update_settings` replacement through the old card's `notificationsReplacement` (compare-and-set on the wire revision;
  the tap-through `url` is kept exactly as saved; administrator-only, as the backend requires). It lists the registered `notify.mobile_app_*`
  phones (`notifications.available`) and the eight events with the saved choice, and says: no registered phone, a chosen phone whose notify
  service is gone (kept and skipped when sending until unticked), no recipient with events on, no events, read-only for a non-administrator,
  an older backend without notifications. A save with no phone or no event is stored and said to send nothing. The **setup check** is a compact
  list built only from existing data: the dashboard `setup` rows for measurement sources (vehicle, car level, site, grid sign, demand grid power;
  same words as the old card's “Get started”, the phone/app/solar/phase rows left out), a missing car reading, pricing (no provider for the saved
  area, held price state not ready, no intervals; “held, not proof the provider answered”) and execution blockers (the 9.5/17.6 recovery text from
  fresh Morek status; a stale or missing status is “unknown”, never “nothing blocked”). Rows link (open + scroll, no write) to the existing Vehicle
  sources, Market & costs and Plan activity & freshness sections; site/grid rows say they are set up outside this sidebar. The area states that
  a notification only says SpotNav noticed an event and does not prove a plan was sent or charging measured, and that saving sends no
  notification and does not wake the car. Opening/editing only reads; unchanged saves send nothing; drafts survive refreshes (`n:` drafts); a stale
  dashboard, a pending post-save read, another writer's change to the choice while editing (signature check), a revision conflict (nothing written,
  reload required), a reconcile failure after a durable save, a refused code, a timeout or a permission change mid-save (unknown outcome, saving blocked
  until an explicit Reload) are handled, sharing the plan form's pending/unknown-write bookkeeping. `notifyBusy` is added to the other panels' busy guards.
  **Limits:** (1) a notification's delivery to a phone is not checked: “available” only means the notify service exists in HA now; (2) the tap-through
  `url` is not editable here; (3) the setup check shows what the backend already reports (setup rows are administrator-only; others see “unknown”), no
  new probes; grid/site/demand setup stays outside the sidebar; (4) English text only, no i18n for this area; (5) no browser/Playwright, no HA-fixture
  Python tests (no backend change), `test/sidebar.test.ts` not rerun (about 33 s), not installed.

**Excluded from Stage 13:** solar/hybrid and home-energy flows, site load balancing, the legacy minimum-SOC
start controller, direct legacy Start/Stop, BMW wake or limit writes, external debug upload. Do not imply the
old card’s backend behaviour disappears when its UI is hidden.

### Stage 7 — Price chart navigation, evidence tracks, price insights (7.1–7.5)

**Complete locally, coordinator-reviewed (2.5.167–2.5.173, 2026-11-16).** All seven implementation substages are done. Focused mocked checks and builds passed; browser, physical and installed behavior remain unverified. The audit below records the pre-implementation basis, not the current feature gaps.

**Audit (source reading, manifest 2.5.166, HEAD `f0bb93a3`, 2026-11-16; replaces the 2.5.128 audit).** Re-verified facts, not copied claims:

1. **Chart feed.** The sidebar chart uses only `raw.prices.published_intervals`, built by `serialize_published_intervals` from
   `capture.intervals`, which comes from `_held_documents` in `api/dashboard.py`: **today and tomorrow display days only**. No past day
   reaches the UI. `PriceRepository` keeps market-day files for `HISTORY_KEEP_DAYS` = 400 and prunes older ones, but *which* days exist
   depends on fetching: `pricing/price_history.py` backfills the 28-day profile window; a year (`DEEP_DAYS` 365) only from a provider that
   answers a range in one request (ENTSO-E); a one-day-at-a-time provider (Nord Pool, reach about two months) fills the window only. So “all
   available days” is typically about 28 days plus today/tomorrow, up to about a year on ENTSO-E, never “400 days”. No-I/O reads exist:
   `day_snapshot` (display day cut from market-day files by `compose_display_day`), `file_snapshot`, `file_document`, `holds_file`.
   The price area has its own display zone (`area.tz`) and market zone (`market_tz`); the history API cuts `date` windows in **Home Assistant's
   zone** (`local_zone`). The two zones can differ, so every day a view names says which zone it uses.
2. **History API (`spotnav/get_charging_history`, `sessions/history.py`, `api/sessions.py`).** Any signed-in user may read (same as
   `get_sessions` and the dashboard; no admin gate; no write). One window ≤ 7 days (`MAX_SPAN`), UTC instants, a 25-hour DST day is 25 hours.
   `MAX_ROWS` = 200 caps every list, but **only `plans_truncated` says so**: `observed.intervals`, `gaps`, `capture_restarts`,
   `comparison.planned_blocks`, `outside_plan`, `unknown_plan_spans`, `sessions` and each session's `price_slices` are cut silently.
   `retention.oldest_evidence` is the minimum over the plans, capture marks and the first row of *every* sample kind, so a plan or capture
   mark older than the power samples makes `window_starts_before_oldest_evidence` read false for a window whose power rows were already
   pruned; `observed.coverage.no_data_seconds` is the honest signal today. Both are partial signals, not enough for a quiet UI guess:
   **7.3a carries the small backend delta below.**
3. **Actual retention (do not promise 7 days).** Measurements: one row per kind per 60 s capture tick (`MeasurementCapture.TICK_S`), at most
   `MAX_SAMPLES_PER_KIND` = 4320 rows per kind, so **4320 rows at 60 s = 3 days, not 7**; the 7-day age cap (`RETENTION_DAYS`) binds only
   for sparser rows. Plans ≤ 120, events ≤ 600, capture marks ≤ 100 (all also ≤ 7 days). Digests: `MAX_DIGEST_DAYS` = 62, written once
   (`keep_digest`, never replaced) only for a finished local day that had activity, looking back at most 14 days from the oldest evidence,
   at the first capture tick of a later local day after a 15-minute settle (so by reading the code a digest usually appears about a day
   after the day ends); digests carry no price rows and cap their lists (intervals/blocks 50). Sessions (`sessions/store.py`): 730 days,
   ≤ 5000 per charger. Therefore: measured per-minute detail ≈ last 3 days, plan-and-flow summaries up to 62 days (only for days that had
   activity while raw rows existed), session records up to two years **without** placement evidence. A day outside these is *not retained*,
   never “nothing happened”. Whether the installation's Morek entry actually opens sessions, its capture cadence, real entities and the 100 W /
   2-sample flow thresholds stay **unverified** (user-owned, §9.C); a first install is expected to show much `unknown`.
4. **Sessions API (`spotnav/get_sessions`).** JSON is by month (≤ 24 months back), `days` = the latest 62 days that have a session, `limit` ≤ 100;
   a day range exists only for CSV. Summaries attribute a session to the **local day it started** (one row for a midnight-crossing session); the
   history `sessions` list attributes by **time overlap** (the same session appears in both days). Costs there are made at read time from the
   session's stored kWh × raw spot price slices with the person's **current** fee/tax settings (`cost_basis` `current_settings`, or `stored` for an
   old record with only a stored cost). Stage 15.8 `reconciliation` is on history session rows, not on `get_sessions` rows.
5. **Frontend.** `history-view.js` takes display strings, `readings {time,kw}` and one `sentHistory {start,end}`; the sidebar adapter supplies no
   `history` or `insights` model, so both cards render “unavailable”; `insight-view.js` is a text renderer. The chart (`charts.js`, `price-chart.js`)
   keeps zoom across updates (`setPriceOption`, `snapRange`, `initialRange`); Stage 18.4 added `shared-dashboard/price-bands.js`.
6. **Profile vs backfill.** The 28-day weekday profile (needs 21 held days, ≥ 8 samples per weekday-hour) is `pricing/price_profile.py`;
   `price_history.py` is only the backfill that fills the held days. `market_observation.py` is a subscription, not a store.

**Binding constraints for every Stage 7/8 substage** (new 2026-11-16, in force with §1 and the standard acceptance):

- **Read-only.** Navigating days, opening history, day review or insights never uploads, replans, wakes the car, starts/stops, notifies or
  writes settings; a read command never fetches from a provider (`day_snapshot`/`holds_file` only). No new store; no change to the existing
  consent or permission model (any signed-in user reads, like the dashboard). No new planner, controller or sender; Stage 16/17/18 behaviour
  is not re-implemented.
- **Absolute price colours stay (Stage 18.4).** The chart and every price colour use `price-bands.js` (`priceBand`, `bandColor`,
  `priceAxisExtent`): euro cents/kWh, <8 green Cheap, 8–<15 yellow Normal, 15–25 orange Medium, >25 red Expensive; axis 0 up to at least 30,
  growing for negatives and spikes; any other unit neutral. **A relative insight (percentile, rank, “cheaper than recent days”) never recolours,
  rescales or relabels the chart and never replaces the absolute band.** There is no user-configurable “cheap” threshold in the product today:
  the only fixed classification is the display band; if a user setting ever exists it is a separate named thing. Insight wording keeps
  “cheaper than the last N days (relative)” and “in the Cheap band (<8 c/kWh, fixed)” as two different statements, never one word for both.
- **Evidence rules (Stage 15.8, 17, 12).** Measured tracks come only from `power_w` samples and register segments. A plan, ACK, readback, SOC
  reading (fresh or estimated) or `progress_unknown` (a planning fallback, not history) never fills a measured track. *Effective* is the latest
  readback's remaining period only, never a past day. Late register energy (`reconciliation.unplaced_late_kwh`, `unassigned_register_kwh`) has
  **unknown placement**: never drawn on a time axis, never priced as actual, never added to the session's `energy_kwh`; replay timestamps are
  receipts only; the session's original `energy_kwh` cannot certify a total such as ~20 kWh. A known total without a time is not a known cost.
  Three energy figures per window are shown **side by side, never summed**: meter-counter delta, power-integrated estimate, recorder-placed session
  energy (plus unplaced late energy as its own line); never priced twice or overlapped.
- **Unknown is not zero; missing is not “did not charge”.** A basis with no segment is `null` + coverage; a day or list that the backend says is
  truncated, pruned or `window_starts_before…` is shown as such. If an API answer is partial and carries no signal, assign a small backend delta
  (named in the substage), not a UI guess.
- **Bounded loading.** The UI never loads all held days at once. Default view = today/tomorrow as now (no new request), plus an optional held
  yesterday. Any other span is loaded one bounded page (≤ 8 local days) at a time, on a user action. History is requested one local day at a
  time. Every async result is checked against a request token (charger, generation, area/currency, requested range) and dropped when stale;
  a user's zoom survives routine dashboard refreshes (only an explicit navigation action changes the range).

**Engineering defaults (not user decisions; adjust in code with a note, not by asking):** baseline = trailing 30 **completed** local days
(price-area display zone) in the current market, currency and raw-published basis; a day is *fully held* only when its document is complete,
every interval has a finite price and no interval overlaps another; minimum 7 fully held days or the baseline is `unknown`; all averages and
percentiles are **duration-weighted** (seconds, absolute instants, so 15-minute/hourly mixes and 23/25-hour days need no resampling);
percentile = (time strictly cheaper + half the time equal) / baseline time; cheapest window = contiguous published intervals, default 60 minutes
(allowed 15–720 in steps of 15), exact elapsed time (the current interval counts only from now), a gap or the published end refuses the window;
ties → earliest; duplicate interval start with identical data is dropped once, conflicting data excludes that day; days of another currency
are excluded and counted, never converted; price basis = raw published spot in the area's major unit per kWh in API calculations (the chart retains its existing EUR-cent display conversion), fiscal additions
only if a helper is explicitly used **and labelled**; read-range page = 8 local days; availability list ≤ 400 dates.

- [x] **7.1 Available-day navigation (backend read + UI).** *Locally implemented 2026-11-16 (manifest 2.5.167), mocked checks only; coordinator reviewed; 23 backend and 31 focused frontend checks plus check-dist passed; not deployed or visually verified.* *Scope:* shortcuts Yesterday / Today / Tomorrow / Earlier… / All loaded days, each
  enabled only for days the repository actually holds. *Delta:* **one** read-only websocket command `spotnav/get_price_days` (new small module;
  engineering-default name, check for clashes), api_version 1, same permission and charger resolution as the dashboard, documented in
  `docs/api.md`: `mode: "available"` → `{area_id, zone, currency, today, days:[{day, state, complete, resolution_minutes, source, fetched_at,
  interval_count}], oldest, newest}` (≤ 400 small rows, newest first, nothing fetched); `mode: "range"` with `from`/`to` display dates → at most
  8 days, each day's rows in the **same shape as `published_intervals`** (refactor the row builder in `serialize_published_intervals` to take
  intervals, do not copy it), per-day provenance, refused with `spotnav_invalid_range` beyond the bound. *Reuses:* `day_snapshot`, `holds_file`,
  `serialize_published_intervals`' row shape, `publishedChart`/`snapRange`/`initialRange`, `price-bands.js`; no new store. *UI:* a day with
  no held file is disabled with the reason (not held / outside provider reach by `history_reachable` / tomorrow not yet published, using the
  existing `waiting_for_tomorrow`); a held but incomplete day is selectable and labelled partial; unknown future is never zero; rows merged by
  start instant with duplicates dropped and overlaps refusing that page; currency/area change drops pages of the other market; pages are
  fetched on demand (Earlier… = one picker bounded by `oldest`, never a 400-day load). Preview fixtures use the same shapes. *Acceptance:*
  All loaded days spans the current bounded page, never fetches all 400 days; availability follows held data; 23/25-hour days and 15-minute↔hourly boundaries; stale-response, area-change and charger-change tests;
  user zoom preserved on routine updates; `docs/api.md`; fast checks, build/check-dist. *Exclusions:* no provider fetch, no write, no history
  tracks, no insights.
- [x] **7.2 Chart interaction and DST/resolution fixes.** *Locally implemented with mocked checks (manifest 2.5.168); coordinator reviewed (50 focused tests and check-dist passed); the real ECharts canvas, touch and visuals are unverified; defects and unrun limits are in the handoff.* *Needs 7.1 (same chart files).* *Scope:* reproduce with fixtures, then fix only the
  defects found: hourly↔15-minute change inside one horizon, 23/25-hour axis ticks, container resize/orientation keeping the range, tooltip for
  negative values and gaps, the paged data of 7.1. Preserve zoom, tooltip, wheel, reset and the Stage 18.4 absolute bands/axis. May close as
  “verified, no defect” with the fixtures kept. Physical touch stays unverified.
- [x] **7.3a History client, small backend delta and evidence panel.** *Locally implemented 2026-11-16 (manifest 2.5.169), mocked checks only; coordinator reviewed (49 backend and 27 focused frontend tests; build/check-dist passed); not deployed or visually verified; see the handoff.* *Backend delta (first, small, additive; API version stays 1):* in
  `charging_history` add `truncated` (a boolean and the cut count for each capped list: intervals, gaps, restarts, planned_blocks, outside_plan,
  unknown_plan_spans, sessions, per-session price_slices), `retention.oldest_by_kind` (oldest retained row per sample kind, so a pruned power
  window is detected without guessing), and `retention.digest_days` (the ≤ 62 digest dates). Tests with > 200 rows and with plans older than power
  rows. *Client:* a read-only client for `spotnav/get_charging_history` requesting **one local day** (`date`, HA zone) per call, plus the adapter
  mapping into an **extended shared `history` contract**: sent-plan spans with `known`/`unknown` state and version id (from
  `comparison.planned_blocks` and `unknown_plan_spans`), observed flow intervals with their bounded/unbounded edges, per-block verdict
  `flow_observed`/`no_flow_observed`/`unknown`, `outside_plan`/`plan_unknown`/`no_plan_evidence` flow, energy by basis (see the evidence rules),
  session rows with reconciliation state, coverage (`trusted`/`untrusted`/`no_data` seconds), `retention` and `truncated`. Panel states: loading,
  unavailable, no evidence retained / **raw pruned, digest only** / partial (truncated), permission. Preview fixtures use the same contract; no
  JavaScript planning or interpretation beyond rendering. *Acceptance:* each status and unknown/gap/truncation case renders distinctly; Morek-only
  and retention (3 days at full cadence, not 7) stated; opening writes nothing; stale-day/charger responses dropped; adapter and renderer tests;
  build/check-dist. *Exclusions:* no tracks on the price axis (7.3b), no cost, no new store, no retention change.
- [x] **7.3b Aligned tracks on the price axis.** *Locally implemented 2026-11-16 (manifest 2.5.170), mocked checks only (ECharts mocked, no browser); coordinator reviewed (56 focused tests and check-dist passed); not deployed or visually verified; see the handoff.* *Needs 7.3a and 7.1.* *Scope:* tracks sharing the price time axis (zoom/pan stays aligned):
  **Proposal** (the *current* plan only, with `minimum-exception` marking, drawn only while the visible range reaches now/future; a past day has no
  proposal track unless the history lists that recorded version), **Sent** (spans of the acknowledged versions the history reports, **each span
  carrying its own version id**; several versions in one day appear one after another, and spans after an uncertain write are `unknown`), **Effective**
  (the latest readback's remaining period only, labelled; history never restores it, and it is never drawn for a past day) and **Measured** (7.3a flow
  intervals). Mismatches and missing observations are hatched unknown, never absent; suggested cheap opportunities are not the plan; a reported limit
  is never drawn as kW; the current plan is never used for a past day. *Acceptance:* proposal≠sent, sent≠effective and planned-without-flow cases
  legible; DST day; two versions in one day; preview parity; no change to the price chart's interactions or absolute colouring.
- [x] **7.4a Live price-insight methods (backend).** *Locally implemented 2026-11-16 (manifest 2.5.171), real-repository mocked checks only (34 new backend tests); coordinator reviewed (57 focused backend tests and check-dist passed); not deployed; see the handoff.* *Delta:* a pure module (no `hass`, no clock; suggested `pricing/price_insights.py`) and **one**
  new read-only command `spotnav/get_price_insights` (mode `live`; 7.4b adds mode `monthly` to the same command; any signed-in user; `docs/api.md`).
  *Inventory first (in the substage's notes):* the held days, basis, resolution and coverage it reads; inspect `planner.cheapest_slots` and reuse it
  only if it can answer an unconstrained contiguous window, otherwise keep the small pure function. *Methods:* (1) the current interval versus the
  trailing baseline (percentile and rank by duration, engineering defaults above; `unknown` with reason when below the 7-day minimum, when the current
  interval is missing/stale or the currency differs); (2) the cheapest contiguous window of a requested length (default 60 min) inside the published
  horizon, with exact start/end, duration-weighted average and the same baseline percentile. Output always carries `baseline` {days_expected,
  days_held, days_used, days_excluded with reason}, `basis`, `currency`, `resolution`, `assumptions`, `unknown_reason`. Never a cheap/expensive label
  (classification is the frontend's absolute band), never a future guess (tomorrow unpublished = not included), no new store, no D1 dependency (these
  are prices, not costs). *Acceptance:* missing history, partial days, duplicate/conflicting intervals, negative prices, DST 23/25 h, mixed
  15-min/hourly, area/currency change, gap refusal, ties, partially elapsed interval; fast tests at the module boundary.
- [x] **7.4b Monthly price statistics (backend).** *Locally implemented 2026-11-16 (manifest 2.5.172), real-repository mocked checks only (43 new backend tests); coordinator reviewed (100 focused backend tests and check-dist passed); not deployed; see the handoff and `docs/api.md` "Monthly price statistics".* *Needs 7.4a.* *Delta:* mode `monthly` of the same command, `month` = local `YYYY-MM` in the price
  area's zone. Per month: `days_expected` (calendar days, or completed days for the current month), `days_complete`, `days_partial`, coverage seconds
  vs expected seconds, and — only when ≥ 7 fully held days (engineering default) — duration-weighted mean, min, max, p10/p50/p90, share of time at a
  negative price; otherwise `unknown` with coverage. A month comparison is offered only when both months meet the minimum, share a currency and basis.
  No hourly/quarter-hour re-binning (no bias), no hour-of-day profile in this substage, no absolute-band shares (classification stays in the UI).
  *Acceptance:* partial month, current month, DST months (23/25 h), currency change excluded and counted, negative prices, duplicate days.
- [x] **7.5 Live price insights and monthly statistics (UI).** *Locally implemented and coordinator-reviewed 2026-11-16 (manifest 2.5.173). Root reran 35 focused frontend tests, prototype build and check-dist successfully. Earlier focused neighbour checks are recorded in the handoff. Not deployed or visually verified.* *Needs 7.4a and 7.4b.* *Scope:* bind both into the shared `insights` model (`intro`,
  `blocks`, `caution`, `method`; host-supplied text): current-interval assessment, best available window, per-month statistics with “n of N days
  held”, each block showing baseline, coverage, basis, currency and assumptions; unavailable data shows its reason. The absolute band of the current
  price (only for euro c/kWh, from `price-bands.js`) and the relative percentile are two separate lines; the card says opportunities are not the
  charging plan and a read never sends or replans. *Acceptance:* preview parity; i18n parity for new strings; read-only open; stale response dropped.

### Stage 8 — Day review, costs, savings (8.1–8.3)

**Complete locally, coordinator-reviewed (2.5.174–2.5.178, 2026-11-16).** All five substages are done. Focused tests and builds passed; no deployment, browser or physical validation. The audit below records the pre-implementation basis. Historical provider provenance remains unknown for old slices, and savings require a full held reference day; missing data stays unknown.

**Audit (source reading, manifest 2.5.166).** Reuse Stage 6/7 evidence and the existing session store; add no store and no retention.
(1) Evidence by age: per-minute flow ≈ last 3 days (see Stage 7 audit 3), digests ≤ 62 days, sessions ≤ 730 days without placement evidence.
(2) A session keeps its kWh split over price intervals with the **raw spot price and fx** of each slice (immutable, `price_slices`); no cost is stored,
it is made when read with the person's **current** fees/taxes (`cost_basis` `current_settings`; `stored` only for an old record). A plan version keeps its
own tariff at creation (`plan_tariff_snapshot`: `fiscal` and up to 300 raw price rows, `fiscal_state` `resolved`/`unknown`) for as long as the plan
survives (≤ 7 days, ≤ 120 plans); digests keep only that fiscal choice (62 days), no price rows. Changing fees today never recovers an older tariff.
(3) Existing savings = `SAVINGS_BASIS` `day_average_price` (`sessions/summary.py`, `ChargeSession.savings_minor`): the same priced energy at the day's
average price, an estimate. “Charge immediately after plug-in at comparable power” is **not implemented and not approved**, and the session record has
no plug-in time (a session starts when charging is first seen; connector samples last only as long as raw evidence). (4) `summarize_bucket` already
makes day/month buckets, never adds currencies together (but silently drops sessions whose currency is not the most recent session's — 8.2a must count
them), and savings may be negative (the reference minus the cost). (5) History session rows carry `cost: null`, `cost_basis: "not_recomputed_here"`.

**Stage 8 contracts (D1/D2 settled by the user, 2026-11-16).** Default historical cost and savings use **Nord Pool spot only**, excluding configured fees/taxes. Keep existing fiscal totals available in the existing APIs for compatibility, but never show them under the spot-only label. Preserve the selected provider; another provider's raw price must be labelled by its actual source, never falsely called Nord Pool.
The day's evidence/session rows come from `get_charging_history`; extend the existing costing path and `get_sessions` additively, never add a second store. A day review means energy delivered within that HA-local calendar day: allocate retained price-slice energy by its interval, split midnight/DST boundaries by actual elapsed overlap (label this interval allocation as an estimate). A session may appear on both overlapping days, but each allocated slice is counted once; monthly sums use the same day allocations. Existing session-start-day buckets remain compatible and may be shown only as **sessions started that day**, never as energy/cost delivered that day. Missing placement stays unknown rather than moving an entire session to its start day.
Use the same priced kWh and currency for actual cost and comparison. Savings = reference minus actual spot cost; negative amounts are valid. Aggregate amounts by summing; aggregate percentages use sum savings / sum reference, never an average of session percentages. If the reference is zero or negative, percentage savings is `null` (amount still shown), avoiding misleading percentages at negative prices. Plan totals are forecasts with their existing price basis, clearly separate from historical spot-only totals.

- [x] **8.1 Day review (default yesterday).** *Locally implemented and coordinator-reviewed (manifest 2.5.174). Root reran 95 focused tests and check-dist successfully. Raw retention uses oldest_by_kind only, not old plan timestamps; sessions-only days remain selectable. No browser, deployment or live verification; Stage 8 stays open for 8.2/8.3.* *Needs 7.1 and 7.3b (which needs 7.3a).* *Scope:* a day selector limited to the last 62 local days in
  which `retention.digest_days`, the retained raw window (`oldest_by_kind`) or the `get_sessions` `days` show something; default yesterday (a digest
  usually does not exist yet for it, so it is shown from raw rows if retained); if nothing is retained, say so. Older months are reachable only through
  the month summaries (8.3b), not this selector. For the day: measured charging against the plan actually sent (7.3b tracks), planned-block status, flow
  outside the plan, energy by basis side by side, coverage and unknown spans **separately from confirmed absence of flow**, the price chart for the day
  (7.1), session rows (`energy_source` labelled, reconciliation state, unplaced late energy as its own unplaced line) and an empty state when the Morek
  recorder produced none (unverified; empty ≠ “did not charge”). A day older than the raw rows but with a digest shows the digest facts labelled
  “summary only; no per-minute data and no prices”. No cost. *Acceptance:* a plan or readback never fills measured; missing is “unknown”; days beyond
  retention are not offered; DST day; midnight-spanning session; truncation shown; stale-day/charger responses dropped; preview parity; read-only open.
- [x] **8.2a Spot-only cost of measured energy (backend).** *Locally implemented and coordinator-reviewed (manifest 2.5.175). Root reran 78 focused cost/history/contract/summary tests successfully. No deployment or live verification; see the handoff for placement/provider limits.* *Needs 7.3a.* Extend `ChargeSession.priced` / `price_slices` through one shared calculation used by history and `get_sessions`. Add `spot_cost`, `spot_cost_basis` (`recorded_price_slices`, `retained_price_intervals` or `unknown`), `priced_kwh`, `unpriced_kwh`, `unplaced_kwh` and coverage on rows/day/month summaries. Compute Σ placed kWh × raw spot price with the stored trustworthy currency/rate basis. No VAT, grid fee, energy tax or other configured fiscal addition. Prefer recorded slices; join other genuinely placed energy to retained historical prices only with matching source, area, instants and currency. Never backfill a historical price with today's price. Missing/truncated slices or rates make the missing portion unknown; a partial amount must be labelled partial, never a complete total. Unassigned/receipt-only late energy has no cost. Report currency exclusions, never silently drop them. Reuse existing fiscal cost fields unchanged, with explicit separate labels if exposed; do not build a historical fiscal-tariff engine for this spot-only stage. Apply the calendar-day allocation contract above. *Acceptance:* fee changes do not change spot cost; negative/missing prices; partial coverage; currency/rate errors; midnight/DST; no double counting; history and summary totals agree. *Exclusions:* no tariff-setting changes, no new retention/store, no supplier-bill claim.
- [x] **8.2b Cost display and totals consistency.** *Locally implemented and coordinator-reviewed (manifest 2.5.176); root reran 53 focused cost/history/panel tests and check-dist successfully. Frontend only; mocked focused tests, build and check-dist pass; no browser, deployment or live verification; see the handoff for limits.* *Needs 8.2a and 8.1.* *Scope:* day/session/month cost in the 8.1 view; plan totals (the backend
  `model.totals`, a forecast) stay visibly separate from historical totals; one shared formatter; label estimate, basis, currency and missing prices.
  *Acceptance:* same inputs give the same totals in every card; partial data, negative prices, midnight session and unknown never becomes zero.
- [x] **8.3a Day-average spot savings (backend).** *Locally implemented and coordinator-reviewed (manifest 2.5.177); root reran 101 focused savings/cost/contract/history tests successfully; backend only, no browser/deployment/live verification; see the handoff for limits.* *Needs 8.2a; D2 settled.* Keep `day_average_price` as the baseline method, using the same charged/priced kWh at that delivery day's duration-weighted average raw spot price. Use a complete valid published local day (23/24/25 hours as appropriate); if the full-day reference is missing, report reference/savings unknown for that portion, not an average of a selectively cheap subset. Split midnight sessions by delivery day before applying the reference. Share the same cost/coverage/allocation path as 8.2a; no plug-in-time baseline or new power simulation. Return actual spot cost, reference spot cost, savings amount, nullable percentage, comparable kWh, coverage, currency and `savings_basis: day_average_price`. Negative savings are valid; zero/negative reference yields no percentage; partial aggregates explicitly identify excluded energy/days. Forecast savings stay separate from historical estimates. *Acceptance:* weighted hourly/quarter-hour/DST averages; midnight splits; same-kWh comparison; partial/missing reference; currency separation; negative/zero prices; day/month totals consistent.
- [x] **8.3b Savings and summary cards.** *Locally implemented and coordinator-reviewed (manifest 2.5.178). Root reran 71 focused savings/cost/history/panel tests plus build, check-dist and prototype build successfully. Malformed reference-source lists fail closed. No browser, deployment or live verification; see the handoff.* *Needs 8.2b, 8.3a and 7.5.* *Scope:* day/month summary cards reusing 7.5's monthly framing; totals identical to
  8.2b's. *Acceptance:* baseline, coverage and estimate labels visible; forecast vs historical distinct; negative savings shown; consistent totals; preview
  parity; i18n.

## 9. Open decisions, review work and ownership

**Settled choices and retained limits (no outstanding implementation-blocking product decisions):**

- **D1 — decided by the user, 2026-11-16:** default charging costs are **Nord Pool spot price only**, excluding configured fees/taxes. Add explicitly named spot-only fields; keep fiscal totals separate and existing APIs compatible. This is a display/accounting decision, not a change to planner cap basis or fees settings.
- **D2 — decided by the user, 2026-11-16:** compare the same charged energy against **that day's average spot price**, keeping the existing `day_average_price` method. No immediate-after-plug-in baseline. Costs and reference use the same priced energy, source and currency.
- **D3 — history retention (no gate, not a blocker).** **Preserve the verified retention** (about 3 days of per-minute evidence at the 60 s cadence,
  7 days only for sparse rows, 62 daily digests, 730 days/5000 sessions). The earlier “90 days of detailed traces” proposal is **not** adopted and
  nothing in Stage 7/8 may assume it or a new retention store. Any extension is a **future explicit user decision** with its own source change;
  until then 8.1 offers only retained days and says so.

- **D4 — user-approved direction, 2026-11-18 (not a verified behavior):** the permanent block after an
  uncertain write may be relaxed, only through Stage 19's evidenced transitions: proven pre-dispatch release
  (19.1) and ordered replacement or late-response resolution of a truly ambiguous record (19.2), with
  Stop/Pause/protection/identity/ownership untouched. Hardware testing was **not** authorized or performed.
- **D5 — settled:** automatic guarded recovery is the approved direction. Implement and enable it when its ordering boundary is justified; report unresolved device assumptions and any concrete technical limitation. Deployment and hardware operations remain user-directed.
- **D6 — open (the one remaining Stage 19 product gap, found by 19.5):** a planning fallback that needs a product choice (a default plan
  with unknown SOC) is recorded here for the user, not implemented; the existing planner hold and who-acts text apply. Retry-pace and bound
  constants (19.2/19.3) are engineering defaults chosen and listed by the delegate, adjustable in code.

**Open research (honest; all unverified; mocked tests cannot settle any of it).**

| # | Question | Effect if it differs from the assumption |
| --- | --- | --- |
| R1 | Does the Morek replace a profile by id (and stack level/purpose) on `SetChargingProfile`, in arrival order, including after an earlier call timed out? (The handoff records some stack-level facts for this unit; re-read them, don't rely on this row.) | 19.2 replacement may leave an old profile in force or stay `replacement_unconfirmed`; the implementation must avoid unsafe ordering assumptions and expose any unresolved limitation. |
| R2 | Can a response arriving after the 30 s wait reach SpotNav through the installed OCPP integration and be tied to its message/attempt id? Can `point.call` raise *before* transmitting in a distinguishable way? | Late-response and “raised before the wire” proofs are unavailable; those cases stay ambiguous. |
| R3 | Does a retained profile survive charger reboot or power loss, what clock does it use and how does it drift, and can a *new* transaction authorize while offline? | Offline wording must stay “last known, not guaranteed”; no promise beyond the user-run experiments. |
| R4 | What horizon and coverage does `GetCompositeSchedule` actually return on this unit, and does it ever reflect a stale or pending profile? | Verification may be “covered until” only, or not verifiable. |
| R5 | Does the installed OCPP integration expose a boot counter and restamp status/transaction sensors after a reboot? | 19.6 reboot recovery degrades to today's behavior. |
| R6 | Can Morek's own protection or another controller's profile override or stop a SpotNav window? | No absolute guarantee; wording and verification must stay evidence-based. |
| R7 | What do HA `Store` writes guarantee when they fail or are delayed around the pre-wire marker? | A storage failure near dispatch may have to stay ambiguous. |

**A. Verification ledger (local implementation vs unrun acceptance vs user-owned).**

| Item | Local implementation (mocked) | Unrun / unverified | Owner |
| --- | --- | --- | --- |
| 5.7b2 live binding; 6.2/6.3 capture and history API; 9.4–9.7; 10.x; 12.x; 14.x | Yes, per their archive entries | Installed sources, entity set and cadence, flow thresholds, deployed and physical behaviour; 9.5’s accepted fresh-Resume exception for an ambiguous undispatched Resume stays | User (5.8) |
| 5.7b3 | Worker timezone harness, stale fixture and wording fixes | Browser rerun (desktop/emulated mobile), full worker/planning suites, 5.4c HA-plugin suite (Windows `fcntl` gap: unrun, not failed) | B below |
| Stage 14 mocked suites | Yes (focused isolated runners) | Not the suites above; no live observation | — |
| Stage 19 (implemented locally 2026-11-18, 2.5.199) | Focused mocked/isolated tests only (real planner/worker/send path, fake clock; no HA, charger or deploy) | Everything, including R1–R7 above; replacement, late-response and offline behavior need user-directed hardware evidence | User (hardware tests); delegates only mock |

**B. Outstanding local review/acceptance (not feature work; blocks nothing in the queue).** (1) **5.7b3:** run
the three unrun suites only if the user asks; report them as unrun until then. (2) **Coordinator review** of the
`[x]` items archived as “review pending” (5.x, 6.2/6.3, 9.x, 10.x, 12.x, 14.x) is independent of the queue; each
◆ substage also reruns the Stage 14 files.

**C. User-owned, never an LLM task** (any HA access needs specific approval, read-only first; never print the
`homeassistant` token): **5.1** visual approval; **5.8** merge, install and deployed validation (including whether the
2.5.126 plug-in fix, the 2.5.127/128 session card, Stage 14 stability and Stage 10 controls work on hardware, and
whether the installed OCPP integration exposes `charger_generation`); E1 and E2; any hardware test.

## 10. Closed and superseded (do not reassign)

Stage 11 is **superseded `[>]` as a separate queue**; its carried scope is now locally implemented in Stage 15.9–15.11. At the initial audit, nothing was sampled under Morek ownership, while both stores already fed `_morek_input_evidence` (`_learned_energy_for`,
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

**Planning-resilience fix (2.5.146, mocked).** Measured energy since the reading that cannot be attributed to the identified car (a session for no car, a session straddling a reading older than 5 minutes — including one just closed whose total is not yet final — or invalid energy) no longer holds the plan (`target_progress_uncertain` is retired). The plan is made from the reading with only the genuinely attributed energy subtracted (identified sessions that began after the reading, counted once), and the snapshot is marked `progress_unknown` (dashboard `projection.progress_unknown`, sidebar note). The unattributed energy is never counted and its size is unknown, so the planned energy can be overstated, and with a minimum SOC the exception above the soft cap is still sized from the reading. The car's own limit ends a charge; that is not guaranteed by SpotNav. A newer reading rebases and clears the mark. Stale/foreign/unidentified *readings* still hold the plan (`target_soc_stale`) as in Stage 14.5. Upload admission, Pause/Stop, identity, electrical and unknown-outcome guards are unchanged. Committed as `d9ec44cc` and pushed (the earlier “uncommitted” note was stale); coordinator review done in Stage 17.1; not deployed or live-verified.
