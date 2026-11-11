# Morek autonomous charging and dashboard roadmap

Status: **in progress; manual baseline and ownership groundwork complete; autonomous mode not active**.
Updated 2026-11-10. The checklist below is the authoritative work queue.

This is the forward-looking plan for SpotNav Enhanced. Implement **one work block
at a time**, not a dashboard rewrite and controller rewrite in one release.
For existing code, HA access, hardware observations and credentials handling, read
[the development handoff](morek-development-handoff.md) and `AGENTS.md` first.
This document is not permission to deploy, restart HA, or issue hardware commands.

## Task overview — start here

One **substage** is one implementation session followed by coordinator review.
Substages are intended to be comparable reviewable changes, not equal line counts.
Do not assign a whole stage in one prompt. Each substage includes its own focused
tests, documentation and required version/build checks; these are not extra stages.

`[x]` = implemented groundwork (not proof of live hardware behavior).
`[ ]` = remaining. Do not repeat checked tasks or replace working foundations.
Detailed requirements and acceptance cases follow outside this checklist.

| Stage | Outcome | Dependency / status |
| --- | --- | --- |
| 0 | Existing functionality and groundwork | Complete; reuse it |
| 1 | Price cap and minimum ready-by SOC planning | 1.1–1.3 implemented; review pending |
| 2 | Isolate Morek from legacy control | Unarmed lifecycle groundwork complete; activation blocked |
| 3 | Automatically send changed schedules | Stages 1 and 2 before activation |
| 4 | Recover and report execution health | Stage 3 |
| 5 | One usable daily dashboard | Layout may start early; live status needs 3–4 |
| 6 | Genuine charging history | Source inventory can start early |
| 7 | Interactive ECharts prices and tracks | Stage 5; actual track uses Stage 6 |
| 8 | Yesterday, costs and savings | Stages 6–7 |
| 9 | Product polish and installation | Stages 5–8 |

### Stage 0 — Completed baseline: preserve and reuse

- [x] **0.1 Manual Morek workflow:** exact displayed-window preview/send, selective
  removal, bounded readback, drift/coverage reporting and shortened final blocks.
- [x] **0.2 Writer audit:** mapped ordinary, safety, startup and handback writers;
  documented unresolved authorization/transition decisions.
- [x] **0.3 Ownership groundwork:** persisted unarmed metadata, physical connector
  admission locks, identity classification and serialized late initialization.
- [x] **0.4 Uncertainty groundwork:** partial start extraction/characterization and
  standalone durable attempt evidence. These are unwired, not isolation or recovery.

Evidence: `docs/morek-execution-audit.md`; source through **2.5.13**. Isolated
tests are documented there; full HA collection is still blocked on Windows.

### Stage 1 — Price policy (old A2P)

- [x] **1.1 Settings and API**
  - Persist optional cap and distinct minimum ready-by SOC in existing settings.
  - Validate units/minimum/target; expose price basis and preserve old behavior.
  - The saved inputs are consumed by the Stage 1.2 cheapest-price planner.
- [x] **1.2 Planner policy**
  - Use cheap slots toward target; add cheapest above-cap energy only for minimum.
  - Handle partial blocks, period limits, stale inputs and infeasible deadlines.
  - **1.2a complete:** the pure planner can select cheap-only capped intervals,
    including partial durations and shortfalls.
  - **1.2b complete:** a caller-supplied minimum wall-energy deficit permits only
    necessary above-cap energy in the pure planner.
  - **1.2c complete:** cheapest-price Auto resolves fresh vehicle facts, plans and
    reconciles strict capped windows. Capped solar/hybrid strategies are refused.
    The separate immediate SOC floor and manual actions are not governed by the cap.
- [x] **1.3 Reactive planning and explanation**
  - Replan on cap/minimum/target/SOC/ready-by changes without a browser.
  - Expose policy reasons and consistent plan energy/cost; test API-to-plan flow.

### Stage 2 — Actual Morek isolation (remaining old A2)

- [x] **2.1 Reuse the legacy execution boundary** (implemented for review; not full isolation)
  - Extend the existing Auto execution gate with explicit Morek ownership: no
    ordinary legacy starts OR stops, plan installation, retries or automatic resume.
  - Reject conflicting manual/API actions before preparation effects; keep planning,
    metering and status. Reuse pause infrastructure, not its stop-on-pause semantics.
  - Auto-boundary admission is not a final physical-writer or transition guard; see 2.2–2.3.
- [x] **2.2 Close bypasses with shared guards** (implemented for review; lifecycle remains 2.3)
  - Guard the few direct write boundaries that bypass Auto (current/phase writes,
    restore and deletion handback); reuse guards rather than gate every caller.
  - Keep protection unchanged; expose an activation blocker if live site regulation
    conflicts with schedule-only control. Do not redesign the regulator here.
  - Shared adapter admission covers ordinary dispatch, not regulator protection or
    external integrations. Durable ownership transitions remain unimplemented.
- [x] **2.3 Mode lifecycle and end-to-end regression** (unarmed scope; review required)
  - Establish and consult ownership before ordinary startup/restore writes. A process-local
    drain is a future handover seam, not a completed handover or producer shutdown.
  - Combined mocked regressions exercise startup, restore, aliases, conflicting/missing
    metadata, queued writes, ordinary adapters, deletion handback and other chargers;
    regulator protection remains an explicit exception and activation blocker.
  - A wholly missing document still migrates as legacy in this unarmed release. Resolving
    lost-document ambiguity, durable transitions, safe recovery and retained-profile exit
    is mandatory before any activation-capable release. Offline identity remains conservative.

### Stage 3 — Autonomous schedule updates (old A3)

- [x] **3.1 Shared schedule intent** (implemented for review; no worker or activation)
  - Manual preview/Send and future backend callers reuse the builder/fingerprint for
    current fixed-time intent, including the remainder of active displayed windows.
  - Expired/no-plan/unpriced/stale or unavailable prices and invalid inputs refuse
    without releasing retained limits. Active-window readback verification remains 4.2.
- [x] **3.2 Backend worker and triggers** (unarmed groundwork; review required)
  - Planner publications trigger coalesced reconciliation without a browser;
    connector admission serializes and rejects stale work, with process-local
    deduplication and an uncertainty latch. Production owned-profile admission
    still refuses all sends; no transition or activation is implemented.
- [x] **3.3 Shared manual actions and persisted outcomes** (unarmed; review required)
  - Manual actions and the worker serialize on the physical connector and share
    persisted intent/attempt/ACK/readback evidence; Refresh sends only a read.
  - An uncertain attempt blocks further sends without automatic retries; no
    activation, complete recovery or safe retained-profile exit is implied.

### Stage 4 — Recovery and health (old A4)

- [x] **4.1 Restart and reconnect** (unarmed groundwork; review required)
  - Startup and control-entity availability transitions reconcile the current valid
    planner intent and identity, not cached profiles; offline work waits for reconnect.
  - Connector admission and durable uncertainty remain in force. Simulated-authority
    tests cover stale work and duplicate identities; production dispatch stays unarmed.
- [x] **4.2 Verification** (unarmed groundwork; review required)
  - Compare the observable remaining effective schedule for active and future windows,
    including delayed replies, with bounded read-only checks and explicit coverage.
  - Attempt-bound evidence, freshness checks and conservative ambiguous-boundary
    refusals prevent a superseded readback from verifying a newer proposal.
- [x] **4.3 Operator state and unresolved actions** (unarmed scope; review required)
  - The existing status API and panel report current evidence and waiting, manual-preview
    ready, sending, checking, mismatch, offline and intervention states. Uncertain
    outcomes remain latched; no general recovery, ownership transition or reset exists.
  - Explain activation blockers, person Stop, protection, retained 0 A and supervised
    recovery/downgrade; neither readback nor selective removal resolves an unknown upload.

### Stage 5 — Single dashboard and daily controls (old A5 + B2)

- [ ] **5.1 Layout and shared components**
  - Build desktop/mobile browser prototype with sample data; get visual approval.
  - Local sample prototype is available in `frontend/prototype/`; browser checks
    and HA integration limitations are recorded in the development handoff. Visual
    approval remains pending; this does not complete 5.1.
  - Start with Web Awesome Core for polished shared controls, with shared tokens and
    HA Sections composition; no second dashboard. Validate visual quality and HA
    compatibility. If it does not work, stop and reevaluate alternatives with the user.
- [x] **5.1a Initial prototype refinement** (sample groundwork; overall visual approval pending)
  - Refined local prototype and example ECharts are available; verification and
    unresolved limitations are in the development handoff. The user requested further
    refinement in 5.1b–5.1d; don't repeat completed groundwork.
  - Balance desktop columns and eliminate unused chart-column space; review the same
    cards stacked on mobile. Improve visual hierarchy and polish without decoration.
  - Make current charging state, measured power, next window start–end, reason for
    waiting, SOC/target/minimum/deadline, plan feasibility and urgent health clear at
    a glance. Replace duplicated protocol jargon with a plain-language health summary;
    keep critical warnings visible and technical evidence and debug actions accessible.
  - Show the **entire proposed plan**, including multiple start–end windows, estimated
    energy and cost per window, and the estimated total energy, total cost and
    energy-weighted average price in c/kWh for this charge. Label estimate, currency
    and price basis; show unavailable inputs honestly. Keep the complete plan easy to
    inspect on mobile, not just the next window.
  - Demonstrate a populated, genuinely measurement-labelled sample history and separate
    missing/error examples; keep proposal, sent ACK, effective limits and measurements
    distinguishable. Make all sample values and policy explanations internally coherent,
    and distinguish measured zero from unavailable and deadline from predicted readiness.
  - Add locally bundled **ECharts** sample visualizations: a source-interval price bar
    chart with labelled units, cap, proposed-window shading and basic tooltips; and at
    least one additional useful chart concept, exploring a gradient-filled stepped area
    line. The second can illustrate recent measured power with explicit sample data and
    gaps; do not imply continuous measurements where none exist. Present the chart roles
    and visual choices for user approval, without adding charts merely as decoration.
    Preserve actual interval widths, including negative values where illustrated.
  - The work remains sample-only; final visual approval follows 5.1b–5.1d.
- [x] **5.1b Initial dark price-chart comparison** (sample groundwork; revision required)
  - Local comparison was implemented in `frontend/prototype/`; the user reviewed and
    rejected its small chart, layout gaps, monochromatic palette and visual treatment.
    Its implementation is complete as groundwork, not visually approved; revise in 5.1b1.
  - Present two Prices & Plan card variants using the same coherent sample data and
    features: interval-width bars versus a gradient-filled stepped price line/area,
    inspired by the user's example. These are temporary visual alternatives within
    one prototype, not two required live dashboards or duplicate final cards.
  - Make the whole prototype dark as the preferred visual direction. Use locally bundled
    ECharts and Web Awesome; ensure readable contrast, labels and non-colour cues.
  - Both variants show yesterday, today and all sample published future prices, without
    assuming tomorrow is always available; unknown future is not zero. Include negative
    and variable-duration intervals, cap, now, ready-by, selected windows, day boundaries,
    current and next planned prices, exact tooltips, zoom/pan and overview/reset; test
    desktop and mobile interaction. Label cap and price basis with explicit units.
  - Preserve time-interval truth in the step chart, including final interval and missing
    data gaps. Both variants show the complete multi-window plan, per-window price,
    energy and cost, plus this-charge totals and weighted average. Reuse shared sample
    data/components; ask the user which chart direction to keep.
- [x] **5.1b1 Initial full-width comparison** (implemented groundwork; not visually approved)
  - Both full-width comparison cards and the reference-derived fictional fixture exist;
    local ECharts and sample-data groundwork are in place. Review identified visually
    inadequate step rendering, undersized plot, contiguous windows wrongly presented as
    separate, and Ctrl-only wheel zoom. Corrective work began in 5.1b2, with outstanding
    visual/interaction requirements carried forward to 5.1b3–5.1b4. Synthetic fluctuations and
    the hand-authored plan are not verified market data or optimizer output.
  - Show both bar and gradient stepped-area Prices & Plan alternatives concurrently,
    one below the other, each on a full-width row with a substantially larger plot;
    remove the A/B switch. These are comparison-only, not duplicate final dashboards.
  - Use `samples/bar-chart.js` and `samples/stepline-chart.js` as direct visual and
    sample-data inspiration: neutral dark surfaces, expressive price colors, clear now
    and soft-cap markers, low/high callouts, useful window shading and overview slider.
    Reuse one shared, labelled illustrative dataset, scales and features for a fair
    comparison. The bar sample's 15-minute fluctuations are synthetic; do not present
    sample data as verified Nord Pool Latvia prices or as a calculated optimal plan.
  - Include accurate interval boundaries, negative-price and missing-data test cases,
    the full proposed plan, per-window price/energy/cost and coherent totals. Distinguish
    price opportunities from proposed windows; explain price-band thresholds and avoid
    hard-coded sample thresholds masquerading as universal real-world judgments.
  - Use gesture/slider navigation and compact accessible zoom/reset alternatives; avoid
    redundant buttons or verbose chart instructions. Check wheel scrolling versus page
    scroll, keyboard access and touch; report unverified physical-touch behavior.
  - Restructure the surrounding layout to eliminate grid-induced gaps and accommodate
    full-width charts. Improve readable contrast and introduce restrained semantic color
    and locally bundled icons; retain Web Awesome and a consistent dark design. Leave
    broader dashboard polish and alternate states to 5.1d.
  - Browser-review desktop and mobile, provide screenshots of both complete charts and
    ask the user to choose a direction. No live data, HA connection or charger actions.
- [x] **5.1b2 Initial chart, plan and layout corrections** (implemented groundwork; not visually approved)
  - Local corrections and focused checks are in place, including adjacent-window grouping,
    a plan modal, wheel zoom and the desktop two-column overview. User review identified
    remaining visual/interaction work in 5.1b3–5.1b4; this is not visually approved.
    Simulated pinch did not change zoom and touch targeting remains unreliable; see handoff.
  - Place overview and plan controls side by side at equal desktop widths, stack on
    mobile; retain both large, full-width comparison cards below and avoid empty gaps.
  - Make the step variant a visually continuous stepped line with a subtle gradient
    area, not per-interval filled bars. Preserve actual price interval boundaries,
    negative values, gaps and final interval. Bring both chart variants closer to the
    user's samples in size, visual clarity, price colors, min/max callouts, cap, now,
    window shading and overview; use truthful, labelled sample thresholds and data.
    On both charts clearly overlay the exact proposed charging windows with a distinct
    color and non-colour cue, separate from price coloring and cheap opportunities;
    match the complete plan and explain the overlay in the legend/tooltip.
  - Enable ordinary mouse-wheel zoom as requested (without Ctrl), plus slider, touch and
    keyboard-accessible navigation/reset. Test real wheel events and document the page
    scroll tradeoff; do not equate simulated touch with physical touchscreen validation.
  - Present contiguous charging intervals as one continuous window when there is no
    stop; separate windows when charging actually pauses. Do not merge across gaps,
    change planner behavior or erase genuinely different control semantics. Calculate
    per-window estimated energy/cost and energy-weighted price across tariff intervals,
    including partial intervals, and keep chart shading, next window, totals and text
    consistent. Sample fixtures should show both continuous and separated windows.
  - Make the next proposed window open an accessible modal with the same complete plan
    and cost details that remain visible in both chart cards. Provide keyboard/focus,
    close and mobile behavior; sample controls cannot contact HA or control charging.
  - Browser-review both charts, modal and desktop/mobile layouts; verify tests, local
    dependencies and reported limitations. Overall 5.1 and chart choice remain pending
    user approval; no live data, planner changes, deployment or hardware actions.
- [ ] **5.1b3 Chart fidelity and interval navigation** (sample-only; coordinator review pending)
  - Proposal windows now use a bottom-bright green gradient and an aligned pale plan
    track instead of dashed borders; window boundaries remain exact. Visual approval
    remains pending; see handoff.
  - Both charts now have a viewport-aligned fictional day/date band, midnight lines
    and dated interval tooltips; missing intervals are hatched. Desktop and emulated
    mobile checks are documented in the handoff. User visual approval remains pending.
    Production must verify available historical and published future prices and use the
    configured local timezone, including midnight and 23/25-hour DST days.
  - Local implementation now uses anchored responsive labels, future-focused default,
    exact outlined plan windows and snapped navigation. Headless emulated pinch and taps
    worked; physical touch and visual approval remain unverified. See handoff; do not
    advance to 5.1b4 automatically.
  - Bring BOTH full-width price charts much closer to `samples/bar-chart.js` and
    `samples/stepline-chart.js`: meaningful price-dependent colors on bars and stepped
    line/area, clearly visible plotted min/max callouts and a legible proposed-window
    overlay distinct from the price colors. Retain exact intervals, gaps, negative prices,
    final boundaries and a truthful legend; do not apply arbitrary sample price bands
    as real-world judgments. Place callouts at actual extrema, clarify whether they
    refer to the visible range or entire horizon, and handle offscreen extrema honestly.
    Callout pins show only the numerical price, not LOW/HIGH text; explain their meaning
    accessibly elsewhere. Use black for past plot background, dark blue for present/future,
    green for exact proposed-window background and a solid blue Now line as in the sample;
    preserve contrast, price readability and non-colour differentiation of plan windows.
  - On initial load focus on the relevant future: start approximately one or two hours
    before Now, within available data, and show the published future where feasible.
    Allow zooming out/panning to older data using the overview. Handle little/no future
    data and Now outside coverage without inventing prices or hiding known gaps. Define
    a clear full-horizon reset and preserve separate user-chosen views on updates.
  - Snap the viewed time range to 15-minute boundaries on wheel/pinch zoom, drag/pan,
    overview slider and keyboard/reset actions for the 15-minute sample; clamp at horizon
    edges, avoid feedback loops and test repeated movement. This is viewport navigation,
    NOT rounding published data, the current-time marker or partial charging windows.
    For future real data use source interval boundaries and timezone/DST-aware timestamps
    rather than assuming every dataset or charging stop is aligned to 15 minutes.
  - Anchor time ticks to even two-hour boundaries (e.g. 14:00, 16:00, 18:00) for the
    normal chart view, including after panning; keep date/midnight context. Use 5 or 10
    c/kWh price-axis increments when legible. Handle responsive widths and zoom without
    overlapping or misleading labels. Exact interval tooltips remain available.
  - Browser-test both variants with real wheel/drag and zoom/reset, boundary snapping,
    initial focus, even-hour alignment, plot coloring, visible callouts, overlay contrast
    and desktop/mobile screenshots. Investigate simulated pinch/tooltip targeting and
    improve mobile card density; report real-touch versus emulated-touch limitations.
    Keep charts and plan sample-only; ask for feedback before choosing a final chart.
- [x] **5.1b4 Compact controls and plan presentation** (sample-only; coordinator and visual review pending)
  - Implemented locally with shared cumulative SOC projections and modal backdrop dismissal;
    see handoff for checks and limitations. Review identified missing-value rendering and
    card-balance follow-up in 5.1b4a. Overall 5.1 and chart choice remain pending approval.
  - Make Plan Controls more compact and place a readable complete proposed plan below
    them within the right-hand desktop column; keep the overview beside them. Avoid
    blank gaps and preserve responsive stacking. Retain the complete plan in the chart
    cards and the existing next-window modal using a shared sample representation.
  - Show an estimated battery SOC after each proposed window where the sample starting
    SOC, usable capacity, wall energy and efficiency support it. Clearly identify it as
    a projection, not a measurement or guarantee; account for cumulative energy and
    battery-versus-wall basis, cap at feasible bounds, and show unknown if inputs are
    missing. Do not infer SOC changes from a plan as actual observed charging.
  - Clicking outside a modal closes it as well as its close button and Escape, without
    closing on clicks inside. Preserve focus trapping/return and test keyboard and mobile
    behavior. This does not authorize new charger actions or live bindings.
- [ ] **5.1b4a Balanced cards and unknown-value rendering** (sample-only; next)
  - Keep overview and controls/plan at 50% desktop width with aligned top and bottom and
    naturally similar visual weight. Stretch the shorter card without fixed heights or
    filler; preserve natural mobile stacking and accommodate longer plans accessibly.
  - Make the right-hand plan list concise, label estimates once, and retain all windows,
    projected SOC and totals; keep full per-window price, energy and cost readily
    accessible in the existing plan modal and chart cards. Do not hide important windows
    or duplicate business logic. The richer battery overview remains 5.1e.
  - Render unknown/invalid prices, window energy, costs, totals, projected SOC and other
    required inputs as unknown throughout controls, charts and modal without exceptions,
    false zeroes or fabricated estimates. Exercise a rendered missing-data fixture, not
    only the calculation helper; preserve the existing shared sample representation.
  - Test desktop/mobile layout, long plans, missing data and modal accessibility; retain
    sample-only safety and await user visual approval. No live or charger changes.
- [ ] **5.1c Sample price insights and monthly statistics** (sample-only)
  - Prototype concise, explainable assessments of current/upcoming prices against a
    stated illustrative longer-term baseline, plus best upcoming price windows and
    useful monthly statistics. Clearly distinguish cheapest opportunities from the
    actual proposed charging plan, cap exceptions and user deadline feasibility.
  - Use deterministic, labelled fictional price/history fixtures; show basis, lookback,
    coverage and missing-data states. Do not invent live data, market forecasts,
    universal cheap/high thresholds, savings or unsupported day-of-week claims.
  - Explore a useful comparison method, including same-day-of-week only if sample
    coverage supports it; make assumptions and limitations easy to inspect. Obtain
    feedback on which insights are useful, without implementing the live pipeline.
- [ ] **5.1d Daily dashboard polish and visual review** (sample-only)
  - Refine the full dark dashboard around the selected chart direction: strengthen
    hierarchy, legibility and card balance; remove duplicated cost/status content;
    keep important warnings visible and technical evidence accessible. Distinguish a
    schedule mismatch from measured charging state in clear, actionable wording. Use
    neutral dark surfaces, purposeful semantic colors and a restrained set of local
    icons instead of an overwhelmingly green interface; avoid large layout gaps.
  - Show recent sent-versus-measured history, explicit gaps and useful alternate
    scenarios: charging, normal waiting, unavailable data/prices, infeasible minimum,
    partial final window and above-cap exception. Include date/session selection,
    coverage and out-of-plan flow in the design; do not invent observations.
  - Reconcile control units/cap enablement and sample explanations, and review desktop,
    mobile and HA-like constrained widths. Coordinate final visual review with 5.1e;
    overall 5.1 remains pending user approval. No live bindings or hardware actions.
- [ ] **5.1e Vehicle and plan-evidence design** (sample-only)
  - Enrich and polish the vehicle overview without visual clutter. Show current SOC,
    target marker and, only when a separately defined valid value is available, a
    clearly labelled low-SOC warning threshold. Do not equate that threshold with the
    ready-by minimum SOC or immediate protection floor, infer battery damage, or invent
    a default. Demonstrate unknown and potentially stale values honestly.
  - Explore a compact battery visual and readable supporting values for estimated kWh
    presently in the battery, energy needed to reach target and estimated active charge
    duration, as inputs permit. Distinguish battery-side energy from wall energy and
    estimates from measurements; label assumptions and never imply a guaranteed finish.
  - Design a concise plan activity and freshness view: when and why the current proposal
    was calculated, last send/ACK, effective readback time/coverage and key measurement
    freshness as available. Present useful summaries by default; keep detailed evidence
    and less important technical explanations accessible without burying warnings.
  - Distinguish current proposal, known last sent plan and acknowledgement, effective
    current-limit readback and actual measured charging. A composite readback is NOT an
    inventory of installed plans, and ACK/readback cannot prove physical charging; show
    unknown/stale/superseded evidence rather than claiming what profile is installed.
  - Use coherent labelled sample scenarios, preserving the complete-plan modal and chart
    overlay. Review desktop/mobile visual hierarchy and ask the user to approve. No live
    bindings, new telemetry, protective behavior changes or charger actions; verify any
    eventual live source availability during 5.2 rather than assuming it exists.
- [ ] **5.2 Overview and operation status**
  - Bind connection/SOC/measured power/next window and proposal/sent/readback health.
  - Make missing data and critical failures visible without expanding details.
- [ ] **5.3 Plan controls and actions**
  - Add target/minimum/cap/ready-by controls, costs and policy explanations.
  - Keep Send/Refresh accessible; distinguish upload suspension/pause/removal/exit.

### Stage 6 — Real history data (old B1)

- [ ] **6.1 Source inventory**
  - Verify actual Morek/OCPP/Recorder measurements, resolution and retained history.
  - Check Bavarian CarData as fallback/cross-check; document association and gaps.
- [ ] **6.2 Capture and provenance**
  - Reuse existing stores; retain sent-plan versions and genuine power/energy events.
  - Handle resets/duplicates/gaps; never substitute schedule windows for observations.
- [ ] **6.3 Queries and retention**
  - Add bounded historical queries/retention with original tariff and plan context.
  - Test restart/midnight, charging outside plan and planned blocks with no flow.

### Stage 7 — ECharts prices and schedule tracks (old B3)

- [ ] **7.1 Price chart**
  - Reuse the 5.1a sample ECharts work; bundle it for the shipped card locally and bind
    real source-resolution prices, units, cap and markers.
  - Handle negative/missing prices, timezone and DST correctly.
- [ ] **7.2 Interaction**
  - Reuse prototype interactions; add Yesterday/Today/available future/All,
    touch/mouse zoom, overview/reset and exact tooltips for real data.
  - Preserve zoom on updates; snap navigation to real source interval boundaries without
    rounding underlying data or plan times. Test resize and keyboard/touch behavior in
    a browser, including timezone/DST and source-resolution changes.
- [ ] **7.3 Aligned tracks**
  - Distinguish proposal/sent/effective/measured tracks and minimum-SOC exceptions.
  - Show mismatches and missing observations honestly; reuse Stage 6 provenance.
- [ ] **7.4 Price insight sources and methods**
  - Inventory available historical/published price data and its basis, resolution,
    retention and coverage; define and test explainable comparisons and upcoming
    opportunities. Missing history or future prices must be reported, not invented.
- [ ] **7.5 Live price insights and monthly statistics**
  - Bind validated 7.4 price sources to current/upcoming assessments, best available
    windows and monthly summaries, reusing 5.1c design. Show baseline, coverage,
    price basis and assumptions; do not describe opportunities as the charging plan.

### Stage 8 — Yesterday and financial summaries (old B4 + C1)

- [ ] **8.1 Yesterday comparison**
  - Date selection, measured-versus-sent chart and out-of-plan charging.
  - Show unknown coverage separately from confirmed absence of flow.
- [ ] **8.2 Costs**
  - Extend existing calculations for per-window and session/day/month totals.
  - Preserve historical tariffs, distinguish estimates and test missing/negative data.
- [ ] **8.3 Savings and summary cards**
  - Compare the same energy against an explicit comparable charging baseline.
  - Label coverage/assumptions; keep totals consistent across dashboard cards.

### Stage 9 — Finish and installation (old C2)

- [ ] **9.1 Accessibility and themes:** light/dark, contrast, non-colour states,
  keyboard/touch, copyable text and reduced motion.
- [ ] **9.2 Responsive integration:** browser-test the whole dashboard, empty/error
  states and repeated updates; remove duplicate daily controls within the new UI.
- [ ] **9.3 Installation and documentation:** one dashboard template, migration and
  diagnostics guidance; never overwrite user views or claim unperformed hardware tests.

### Execution boundaries — avoid another prerequisite spiral

- Stage 1 and the unarmed scope of Stage 2 are implemented for coordinator review.
  Reuse the planner and Auto execution boundary; Stage 2 activation questions
  remain open. Stage 1 does not automatically upload Morek schedules.
- The previously proposed durable pre-dispatch callback wrapper was **not assigned**
  and is **not a required task**. Do not implement it automatically.
- Reuse the completed evidence store if the selected execution path needs it.
  Do not expand generic legacy-command recovery as a prerequisite for planner/UI work.
- Stage 2 uses three implementation slices, not a per-caller gating project. Reuse
  the audited writer inventory and existing execution/admission boundaries. Full
  writer coverage is a test requirement, not a requirement to scatter checks through
  every function. No new standalone design/audit session is required first.
- Code can be reviewed with mode unarmed. Actual activation requires completed
  isolation and resolved electrical/authorization blockers; do not weaken those.
- Source inventory (6.1) and sample-data layout (5.1) may start early. Hardware
  testing remains user-directed, never a separate delivery gate.

## Detailed requirements and acceptance reference

The sections below explain policy and test cases. Legacy A/B/C identifiers are
retained for links/history only; the numbered checklist above controls task scope
and progress. Do not treat an old broad block as a single implementation session.

## 1. What the user wants

- **One charging dashboard in Home Assistant, containing multiple coordinated
  cards.** No second charging dashboard for the stock SpotNav card, and no separate
  compact-dashboard deliverable. Reuse/redesign existing card components where
  useful; do not build two parallel charging interfaces.
- A comprehensive, modern, evcc-inspired charging overview: clear large values,
  useful charts, polished controls, compact status badges and tables—not long
  paragraphs or an initially hidden Morek section.
- Important information visible on opening the page. On smaller screens the same
  dashboard scrolls vertically; “visible by default” does not mean cramming every
  historical row or raw protocol detail into the first viewport.
- Nord Pool prices, cheap periods, SpotNav's proposed plan, the schedule sent to
  Morek, Morek's effective readback, and measured charging clearly distinguished.
- Car connection, battery/target, energy needed, estimated active charging time,
  elapsed time until ready, next start/stop, planned costs and savings.
- Yesterday's planned-versus-actual charging and costs, so the user can check
  whether charging actually followed the schedule. **Actual history must come
  from Morek measurements/events, never be guessed from calculated windows.**
- **Autonomous daily operation:** planning, schedule updates, verification and
  reconnect recovery without clicking Send. Keep manual Send/Refresh for debugging.
- **Schedule-only execution for the Morek connector:** SpotNav must not also run
  its legacy live start/stop/current-setting control against the same connector.
- **Soft price limit + minimum ready-by SOC:** normally exclude prices above a
  configurable cap (example: 10 cents/kWh). Override it only for the energy needed
  to reach a configurable minimum SOC (typically 40%) by the ready-by deadline,
  choosing the cheapest feasible periods. The ordinary target can be higher.
- Saving a changed ready-by time, price cap or minimum SOC must automatically
  recalculate; if the effective charging schedule changes, automatically resend
  it. No manual Send or browser refresh should be required.
- **No separate overnight/hardware-testing stage.** The goal is a great dashboard
  with an improved backend. The user decides when to test hardware; uncertainty
  must be documented, not made a prerequisite blocking dashboard development.
- No solar panels: do not spend this project's effort on solar, battery-storage
  flows or decorative whole-home energy diagrams.

The user accepted Apache ECharts after comparing it with ApexCharts. ECharts is
the selected chart library; visual similarity to evcc does not require running
evcc or another controller alongside SpotNav.

## 2. Current baseline, not the finished product

The manual baseline below describes **2.5.7**. Source has since reached **2.5.13**
with unarmed groundwork; see Stage 0 and the execution audit. Verify runtime versions.

- The manual Morek API can preview, send, fetch and selectively clear profile
  `42001`, station `3020002509120029`, connector `1`, through HA OCPP.
- The real schedule is an absolute `TxDefaultProfile`, stack level **1**, using
  0/16 A periods and a persistent final 0 A limit. Level 5 was rejected by Morek;
  level 4 was accepted during a diagnostic probe. Stack 1 also eventually matched.
  **Do not escalate priority or automatically clear profiles to hide a mismatch.**
- Send currently requires the old Auto control paused “Until I resume”. That is a
  temporary experimental interlock, **not** the intended autonomous UX. Replace
  it only after exclusive execution ownership is implemented and tested.
- 2.5.7 sends the displayed windows, including a shortened energy-estimated final
  block. These are fixed times, not a guarantee of stopping at a measured kWh/SOC.
- 2.5.6 adds immediate + bounded delayed readback checks, reported coverage and
  visible timing drift. A match currently allows up to 90 seconds' drift and
  requires reported coverage through one hour after the final stop.
- Morek has returned Accepted uploads with a flat 16 A readback, later returning
  the expected transitions with varying seconds. There is no isolated, proven
  firmware/root-cause fix. Physical charging behavior is not established by those
  readbacks; hardware testing is user-directed, not a roadmap stage.
- The user reported the car unplugged during those investigations. This is not a
  permanent fact; check its current state before a future supervised test.
- Session totals/cost/savings APIs exist. A reliable historical comparison also
  needs retained schedule versions, readback snapshots and detailed measurements;
  the current last-upload record cannot reconstruct every previous night.

## 3. Architecture and non-negotiable rules

### One plan, one execution owner

Retain SpotNav's planner; create a dedicated Morek schedule executor. A shared
backend snapshot feeds all dashboard cards. Frontend rendering must not be needed
for automation, and must never itself trigger uploads just by opening the page.

For the connector in Morek schedule mode:

1. **Plan -> validate -> SetChargingProfile -> read back -> compare -> report.**
2. Time boundaries are enforced by Morek's stored profile, not HA timers sending
   RemoteStart/RemoteStop or number/current writes at each boundary.
3. Disable/gate all conflicting SpotNav legacy execution paths for that connector:
   timed start/stop, direct current writes, normal action buttons, session runner
   side effects, reconnect/bootstrap writes and applicable site-control writes.
   Inspect actual paths; hiding buttons alone does not establish ownership.
4. Preserve read-only status, metering, planning and diagnostics. Do not remove
   unrelated integrations or globally break legacy support for other chargers.
5. Do not run another charger controller (including evcc/Gridio) against the same
   connector during tests. They are UI references, not additional executors.

### Safety and authorization

- Do not disable household load protection, raise electrical limits, or assume
  that disabling a SpotNav software actuator leaves equivalent protection.
  Audit any dependency on live software load management before gating its writes;
  if independent protection is not established, block schedule-only daily readiness.
- OCPP current limits **do not authorize a charging transaction**. Establish how
  a newly plugged-in car becomes authorized without legacy start commands. Do not
  silently change charger authorization mode, credentials, RFID or vehicle settings.
  If this requires another configuration decision, surface it and get approval.
- Keep the physical station/connector identity guard. Never use blanket profile
  clears; removal targets only the owned ID. Keep stack 1 unless a separately
  justified, approved change is made.
- Same-ID updates are intended to replace the owned schedule, not all charger
  profiles. Persistent final 0 A, rollback/removal and leaving schedule mode need
  deliberate behavior; do not assume Resume or HA restart clears them.
- No stale/unpriced/invalid plan upload and no unbounded retries. Unknown upload
  outcome means “may have applied”, not permission for a rapid resend loop.
- Make unavailable SoC/metering explicit. Never show missing data as zero or claim
  a precise completion estimate without sufficient inputs.

### Soft price limit and minimum SOC policy

These are **planning inputs**, not another live charger controller. Persist them
and use the same backend policy for chart proposals, cost estimates, automatic
uploads and manual Send.

- Settings: optional soft price cap in the configured currency/kWh, minimum
  ready-by SOC (suggested initial default 40%, editable), normal target SOC, and
  ready-by time. Validate `0 <= minimum SOC <= normal target SOC <= 100`.
  Represent 10 cents/kWh explicitly as 0.10 currency units/kWh, not 10 units/kWh.
- Price **at or below** the cap is allowed for ordinary charging toward the
  normal target. Price **above** it is excluded unless the minimum-SOC exception
  is needed. The cap is a maximum per interval, not an average-price threshold.
- First determine whether available below-cap periods before departure can
  deliver enough energy to meet the minimum. If they cannot, add only the
  necessary above-cap energy using the cheapest feasible remaining intervals.
  Continue toward the normal target only in below-cap periods. Do not waive the
  cap for the entire plan merely because the minimum is not yet reached.
- Optimize the combined plan under real power/energy estimates and charger
  period/block constraints. Do not independently select two conflicting plans,
  silently drop periods, or broaden an expensive period to fill a whole slot
  when a partial block suffices. Preserve the shortened final stop behavior.
- If SOC is already at/above minimum, expensive slots stay excluded even when
  the normal target cannot be reached. Say “minimum met; target limited by
  price cap”, rather than quietly charging expensively to the higher target.
- If there is insufficient time/known data to reach the minimum, calculate a
  bounded best-effort feasible plan and clearly report the shortfall. Never
  imply the ready-by minimum is guaranteed, use unknown future prices as cheap,
  or extend beyond departure without a separately approved policy.
- Missing/stale SOC, usable capacity or charging-power data must produce an
  explicit degraded/refused-policy state. Do not invent the energy deficit or
  silently grant the expensive-price exception without adequate information.
- Use and label one consistent cap price basis (Nord Pool-only or configured
  variable cost including fees/taxes). Confirm the default with the user. The
  price chart, cap marker, optimizer and explanation must agree on that basis;
  negative prices and currency/unit conversions must work correctly.
- Explain exception windows in the UI: **“Above price cap: needed for 40% by
  07:00”**, with the actual configured SOC/deadline and extra cost. Distinguish
  minimum SOC from the normal target everywhere.

Example: SOC 25%, minimum 40%, normal target 80%, cap 10 cents/kWh, ready 07:00.
If all known periods before 07:00 are above the cap, select the cheapest feasible
time needed for **40%, not 80%**. If cheap periods suffice for 40%, no expensive
override is allowed; use additional eligible cheap time toward 80% if available.
If SOC is already 45% and everything is expensive, schedule no extra charging.

Saving a new deadline must recompute the eligible horizon, minimum-energy
feasibility, selected windows and cost immediately through the normal backend
update path. The executor replaces the owned schedule when those windows change,
including removing no-longer-needed future blocks. Coalesce rapid edits; unchanged
wire intent must not cause upload spam. Do not assume this reactive behavior
already exists in the current manual experiment.

### Separate operational meanings

Do not conflate these in APIs, UI, history or tests:

| Data | Meaning |
| --- | --- |
| Prices / cheap slots | Published tariff data and selectable low-cost opportunities |
| Proposal | What SpotNav calculates now; may not be installed |
| Last sent | The exact outgoing profile and its version/time |
| Upload ACK | Morek's response; Accepted alone does not verify behavior |
| Effective readback | Composite limits returned at a particular time and horizon |
| Actual charging | Measured current/power/energy; not inferred from a 16 A limit |

`GetCompositeSchedule` is not a profile inventory. “Configured in Morek” must be
presented as the known sent schedule plus effective readback, not invented proof
of every stored profile or its absence.

## 4. Detailed backend, dashboard and history acceptance

Use these descriptions to implement the corresponding numbered substage above,
not as a second work queue. The first autonomous release requires price policy,
actual isolation, automatic updates, recovery and daily controls. No overnight run
is a prerequisite for software development or dashboard work.

### A1 — Audit the existing execution paths (documentation + tests/design)

Inspect the planner, `execution/session_runner.py`, OCPP adapter/actions, Auto
pause/resume, direct current/number writes, startup/reconnect and site-control
paths. Inspect—not assume—current charger transaction authorization behavior.

Deliver a short implementation map listing every writer and where Morek-mode
gates belong. Specify how to enter/leave schedule-only mode, what existing
profile remains installed, and what must be approved before hardware testing.

**Done when:** there is an explicit ownership/transition design, an authorization
plan, and a test matrix showing how conflicting writes will be detected.
No live commands, mode changes or file deployment are needed for this audit.

### A2 — Enforce exclusive schedule-only mode

Add a persisted per-connector execution mode with safe migration from the current
manual experiment. Do not silently arm autonomous control on an integration update.
After deliberate setup, Morek mode is the user's normal path; legacy live
execution cannot also own that connector. Replace the temporary “pause old Auto
forever” requirement with this ownership interlock, not with a deleted safeguard.

Define separate semantics for **suspend automatic uploads**, **pause charging**,
**remove stored schedule**, and **leave schedule mode**. They are not equivalent:
stopping uploads leaves a profile installed, and removing a 0 A limit may allow
charging. If pause/charge-now controls are included, express them through the same
owned profile/executor, never a hidden return to legacy RemoteStart/RemoteStop.
Do not ship an ambiguous “Auto” button whose meaning depends on a hidden mode.

**Done when:** automated tests prove that all applicable legacy writers emit no
conflicting commands in Morek mode, including at scheduled boundaries and reload.
Read-only diagnostics and independent protections still work. Entry/exit policy
and the remaining stored limits are explicit to the operator.

### A2P — Soft price cap, minimum ready-by SOC and reactive planning

Implement the policy in section 3 in the existing planner/settings system. Audit
existing price/target/departure support before adding parallel settings or a
second optimizer. Price cap and minimum SOC are **P0 backend requirements**, not
late cosmetic chart options.

Expose cap on/off and value, minimum SOC, normal target and ready-by time as
distinct persisted inputs. Confirm and label the cap's cost basis. A disabled cap
retains normal optimization behavior; an enabled cap filters expensive intervals
except for the explicitly calculated minimum-SOC deficit.

Choose the cheapest feasible plan before departure, respecting both the minimum
exception and the charger's period capacity. Surface why a target cannot be met;
do not silently relax the cap for extra energy above the minimum. Keep estimated
energy/cost and the shown/sent times consistent, including partial final windows.

**Done when:** deterministic tests cover all prices above cap, all below cap,
price exactly equal to cap, enough/insufficient cheap energy for minimum, SOC
already at minimum, minimum below the normal target, disabled cap, negative
prices, currency/fee basis, missing/stale SOC, infeasible departure, partial slots,
and charger block limits. Saving deadline/cap/minimum changes produces a fresh
plan event without requiring a browser or charger state change. A3 tests prove
that a changed plan is then automatically resent, rather than only redrawn.

### A3 — Autonomous, idempotent schedule reconciliation

Implement one backend worker that sends the latest valid plan when needed, not
on every HA state update. Triggers include published prices, relevant saved
settings/target/departure/**soft-cap/minimum-SOC** changes, material changes in the planned windows, and
the charger becoming available. Include a deliberate initial reconciliation.

- Use the same displayed-window builder for automatic and manual Send.
- A saved ready-by/departure change must trigger planning and reconciliation
  even if no charger entity changed. Apply the same rule to cap/minimum/target
  edits and relevant SOC updates. If selected windows change, replace the owned
  schedule automatically; if identical, report the new plan state without a
  duplicate upload. No dashboard-open dependency or extra Send click.
- Fingerprint absolute ON/OFF windows, amperage, relevant profile attributes and
  revision/ownership; exclude the moving initial 0 A timestamp. Debounce/coalesce
  changes and serialize per connector. Ignore stale generations/results.
- Keep Send/Refresh as debugging tools using that same worker and state machine.
  Manual Send cannot bypass identity, ownership, electrical or freshness checks.
- Bound retries/backoff and keep desired, attempted, acknowledged and verified
  versions separate. A refresh or dashboard reload never forces an upload.
- Continue only the remainder of **currently active windows** (3.1), without
   extending the original end. Never resend an old expired plan on reconnect.
- Define expired/no-plan/unpriced-data behavior and how pending 0 A limits are
  handled. Do not silently release all limits when tomorrow's prices are absent.

**Done when:** deterministic tests cover stable-plan deduplication, concurrent
triggers, changed plans, refusal, unknown upload outcomes, active-window updates,
stale responses, manual debugging, deadline moved earlier/later, cap/minimum edits,
and finite retry behavior. Persist enough
version/event metadata to explain which schedule was supposed to run overnight.

### A4 — Recovery and truthful execution health

Extend verification/recovery for autonomous ownership. Recheck on HA restart and
charger reconnect; decide whether to reapply only from current valid intent, not
from stale cached ACK. Keep readback retries bounded and independent of open UI.

Compare the relevant remaining schedule when a charging window is already active;
the current experimental comparator cannot reconstruct past behavior from a
composite reply. Do not label that a verified historical session. Retain reported
duration, timing drift, data freshness and last attempt/error reason.

Provide states such as disabled, waiting for prices, ready, sending, checking,
matched, mismatch, offline and intervention needed. Persistent mismatch must be
prominent, with bounded notifications—not silent priority escalation or clears.

**Done when:** tests simulate restart, disconnect/reconnect, missing/short
coverage, delayed activation, drift, malformed replies, missing measurements and
an active transaction. Recovery cannot revive a cancelled/older upload or enable
the legacy controller. A user can understand what remains installed while HA is
offline and what has not been proved.

### A5 — Minimum daily operations UI (before the big redesign)

Make the existing Morek overview visible without opening “schedule details”.
Use a small set of compact panels/status chips and a window table, not another
wall of explanation. Keep it on the path toward the **single** final dashboard.

Always show: current execution owner/mode, plugged-in/charging state, measured
kW/current, next start/end, proposed versus sent version, upload/readback health,
last checked time, and a visible reason when any action is disabled. Keep target,
minimum SOC, soft cap, departure and estimated plan energy/cost visible where
supported. Show whether the price cap is active and why any expensive window
is required to meet minimum SOC. Distinguish
time spent charging from elapsed time until ready.

Keep manual Send and Refresh accessible for debugging. Removal has a separate
confirmation and clear consequences. Critical mismatches cannot hide in a menu.

**Done when:** operators can tell whether the car is charging, why it is waiting,
when it will next charge, who controls it, and whether the schedule matches
without opening settings. This block need not include a new chart library.

### B1 — Durable plan, event and measurement history

**First find out what Morek actually reports.** Make a read-only source inventory
of the installed HA OCPP integration, entity history/Recorder/statistics, and any
existing SpotNav stores. Document exact entity/message fields, connector binding,
units, sample frequency, timestamps, freshness, reset behavior and retained
history. Do not assume session start/end equals continuous charging.

Candidate evidence, to validate against this station:

- OCPP **MeterValues**: measured `Power.Active.Import`, `Current.Import` and
  cumulative `Energy.Active.Import.Register`, if this charger exposes them.
  Power/current samples support observed flow; meter-counter increments support
  delivered energy. `Current.Offered` and configured limits are **not** flow.
- **StatusNotification** (Charging, SuspendedEV/EVSE, Available, etc.) explains
  charger/session state, but a Charging label alone is not an accurate kWh trace.
- **StartTransaction/StopTransaction** delimit a session and may carry meter
  start/stop values. One transaction can span several scheduled pauses; do not
  paint its entire duration as physical charging.
- HA OCPP measurement entities and Recorder can supply historical samples if
  those entities were recorded. Existing SpotNav measured-energy/session stores
  may already supply some data. Verify quality/provenance before reuse.
- **BMW CarData through the user's Bavarian CarData HA integration** is an
  alternative/complementary source to investigate, especially if Morek provides
  no retrievable history. Audit the installed integration/API rather than assuming
  BMW exposes historical charging intervals. Check for genuine charging-history
  records, timestamped charging-state transitions, measured charging power/energy,
  and whether available live telemetry can be retained in HA going forward.
  Distinguish remotely retrievable past history from data collected only after
  Recorder/SpotNav starts storing it. Sparse SOC changes or a predicted finish
  time alone cannot establish exact charging periods.

Compare the coverage and timestamp precision of Morek/OCPP and BMW observations
before choosing the history source. Prefer fresh, connector-specific charger
metering for home charging when available; use validated BMW charging records as
a fallback or cross-check, with source/confidence visible in the UI. BMW sessions
can include public/other-location charging, and battery-side energy is not
necessarily grid-side energy. Verify the vehicle and home-charger association,
do not double-count overlapping sources, and do not silently use battery energy
as exact billed electricity consumption. Respect API rate limits and use the
existing authenticated integration rather than embedding BMW credentials in
SpotNav or adding aggressive vehicle polling.

Prefer the existing OCPP ingestion/HA data paths; do not parse permanently enabled
debug logs as the production history feed, invent a Morek cloud API, or install a
second OCPP server. If useful telemetry is missing, explicitly document the gap
and any proposed configuration change for approval rather than fabricating it.

Retain immutable versions of the plan actually sent, upload ACK, readback samples,
mode/setting changes and execution failures with timestamps. Record/retrieve
charger power/energy at useful resolution through the existing HA data paths;
do not invent past measurements or wake vehicle APIs at excessive frequency.

Define observed charging intervals from fresh measured flow/energy evidence,
with an explicit noise threshold/debounce and sample-resolution uncertainty.
Keep status-only evidence labelled separately. Integrating sampled measured power
is a **measurement-derived estimate**, not meter-exact energy; label it and prefer
valid meter-counter deltas where available. Preserve gaps instead of bridging
them with the proposed/sent schedule or interpolating an entire offline session.
Handle delayed/out-of-order messages, duplicate samples, counter resets/rollovers,
and charger clock drift; preserve measurement and HA receipt times where possible.

Keep meter provenance, gaps, quality flags, price/tariff context and timezone.
Check existing session/price/history stores before adding duplicate storage.
Add retention/aggregation and an API that can reconstruct a specific night's
plan-versus-actual story after HA restart. Storage size must remain bounded.

**Done when:** tests reconstruct an overnight session across midnight and a
restart, preserving the original plan despite later replanning, and render gaps
as unknown. This uses recorded/synthetic measurement fixtures; it does **not**
require the user to run an overnight test before development proceeds. Include a
case where charging occurs **outside** the plan and one where a planned block has
no observed flow. The history must show the measured behavior in both cases.
Older days cannot silently use today's plan or changed tariff. Deliver the source
inventory alongside the implementation so future LLMs know what is real evidence.
Include BMW fallback/cross-check availability, source disagreements and
location/energy-basis limitations; missing Morek history is not permission to
substitute the calculated plan for actual observations.

### B2 — Dashboard prototype and visual building blocks

Build a browser-rendered prototype with sample data first, then obtain visual
approval. Do not require HA update/restart for every spacing adjustment. Use
desktop and mobile layouts with the same cards and shared design tokens.

Use HA Sections as the intended responsive layout. Bundle ECharts locally with
licence/notice files; load heavy chart code only where needed. Start with Web Awesome
**Core** as the primary library for polished ready-made controls, rather than styling
all controls from scratch. Verify the selected package version, licence, bundled assets,
theme integration, dialogs/popovers, responsive behavior and compatibility with HA
custom cards. HA-native components may be used selectively where appropriate; avoid
depending on undocumented internals. Do not require paid Pro components or runtime
CDN access. If Web Awesome does not work technically or visually, stop and reevaluate
alternatives with the user, including React-based libraries if appropriate, rather than
silently falling back to hand-built controls or undertaking a framework rewrite.

**Done when:** the single-dashboard composition, responsive layout, controls,
status vocabulary, chart colours/patterns and empty/error states are approved.
No second stock-card dashboard is introduced.

### B3 — Interactive Nord Pool prices and schedule tracks

Implement ECharts in the approved Prices & Plan card. Show the entire day and all
available published data, with Today/Tomorrow/All available, drag/touch zoom,
overview slider, reset, “now” and departure markers, and exact tooltip values.
Include a labelled soft-cap line and visually distinguish ordinary below-cap
windows from above-cap minimum-SOC exception windows, with the reason on tap/hover.

Use source-resolution bars/steps, including negative prices; do not smooth away
price changes. Mark unavailable future prices honestly. Support local timezone,
midnight and DST days with 23/25 hours. Preserve zoom across routine updates.

Align labelled tracks for proposal, last sent, effective readback and actual
charging with the price time axis. Shade planned windows lightly on the chart
without making prices unreadable. Suggested cheap opportunities are not the
same thing as a selected plan. Never imply a reported 16 A limit is measured kW.

**Done when:** interactions work on touch/mouse/keyboard, axes/units are clear,
plan/readback mismatches remain legible, and browser tests cover resize, zoom,
missing prices, repeated updates and time-boundary cases. Do not rely solely on
jsdom for visual or layout acceptance.

### B4 — Yesterday and planned-versus-actual review

Add an always-visible recent-history section with a date selector defaulting to
yesterday. Show measured power against the plan sent that day, price context,
actual energy, start/stop differences, and charging outside intended windows.
Keep latest readback separate from historical measured charging. Missing meter
data means unknown, not “did not charge”. Use shared ECharts components.
Use only the genuine observed data established in B1 for the actual-charging
track; a calculated schedule or Accepted upload may never populate that track.

**Done when:** the next morning the user can answer “did it charge when intended,
how much, what did it cost, and where did it differ?” without reading raw logs.

### C1 — Costs, savings and summaries

Show estimated total plan cost and energy-weighted price, per-window costs, and
measured/estimated session/day/month totals. Extend existing session/savings APIs
rather than recalculating business rules separately in each card.

Suggested savings baseline: charging the **same energy** immediately after
plugging in at comparable power. Label the baseline, coverage, tariff basis and
whether the value is an estimate. Distinguish future estimated savings from
historical results; unknown cost/savings must not become a fabricated zero.

**Done when:** consistent inputs produce consistent totals across cards, and
tests cover partial data, fee/tax changes, negative prices and missing baseline.

### C2 — Finish the product, not another interface

Refine the vehicle/target panel, inline plan controls, clear feedback for actions,
session table and lightweight diagnostic event list. Raw OCPP/JSON, rare setup
and destructive actions may use a details drawer; everyday information may not.

Ensure HA light/dark theme support, accessible contrast, non-colour-only states,
copyable text, touch targets, reduced motion and keyboard navigation. Avoid
CSS overrides depending on another card's private DOM. Provide a documented
single-dashboard installation/template without overwriting the user's HA views.

**Done when:** the full dashboard works as one coherent, responsive product with
no solar clutter, no duplicate charging dashboard, no hidden critical status and
no accidental controller competition.

## 5. Intended final page layout

This is information architecture, not a pixel-approved design:

1. **Overview / vehicle:** connection, battery -> target, measured power, next
   action, minimum ready-by SOC, charge-time needed, estimated ready time,
   execution health and missing-data indicators.
2. **Prices & plan (largest panel):** zoomable Nord Pool graph and aligned tracks;
   compact per-block energy/price/cost table.
3. **Plan controls + Morek status:** inline target/minimum SOC/soft price cap/
   ready-by/current settings,
   autonomous status, manual debugging controls, ACK/readback freshness and drift.
4. **Yesterday / recent charging:** measured-versus-sent chart and session rows.
5. **Costs & savings:** estimated plan totals plus historical summaries.

Desktop can place smaller panels beside the chart. Mobile stacks the same
sections in this order. No essential Morek section is collapsed by default.

## 6. Decisions still to settle, without blocking A1

- Primary screen/device sizes and final visual mockup approval.
- Default cost display: suggested full configured variable cost (fees/taxes)
  with a Nord Pool-only option; confirm available inputs and the user's preference.
- History retention: proposed 90 days detailed traces plus longer-term aggregates;
  confirm storage impact and preference before treating that as agreed policy.
- New-transaction authorization, active-window update policy, invalid/no-price
  policy, charging pause/boost behavior and safe mode exit must be resolved in
  A1–A4/A2P. The soft-cap/minimum-SOC requirement is agreed; only precise cost
  basis/defaults, missing-data and infeasible-case behavior remain to specify.
  Do not improvise these while drawing widgets.
- The extent to which parts of the original stock card are repurposed inside the
  one dashboard. Backward compatibility can be retained without making a second
  dashboard a required user workflow.

## 7. Instructions for the LLM executing a block

1. Read `AGENTS.md`, this roadmap, the handoff and applicable existing architecture
   docs. Inspect Git state; preserve unrelated user work.
2. State the single block being implemented and its dependencies. Do not assume
   the existence of an entity, sensor, API field or authorization behavior.
3. Add regression tests, including failure/race/restart cases for executor work.
   Use browser-rendered tests for chart interaction/layout. State any unrun tests.
4. Keep planner and executor semantics separate; do not reimplement cost/planning
   logic in JavaScript or grant unrestricted raw OCPP requests to a browser.
5. Record changed files, checks/results, known limits and next block in this file
   or the handoff. Update the progress checklist truthfully.
6. Follow version/build rules for integration/frontend changes. Publish/deploy or
   perform a hardware test only within the user's current authorization. Never
   copy credentials/raw household logs into documentation or commits.
7. A task is not complete merely because a button renders or OCPP says Accepted.
   Meet its acceptance criteria before calling it operational.

### Progress updates

Update the numbered checklist at the top; do not maintain a duplicate checklist.
Record detailed implementation/test evidence in `morek-execution-audit.md` or the
relevant handoff. Completing groundwork is not completing actuator isolation.

## 8. Research references

- [evcc dynamic prices and charging-plan UI](https://docs.evcc.io/en/features/dynamic-prices)
  — price bars, cheap periods and goal/departure planning.
- [Gridio](https://www.gridio.io/) and [FAQ](https://www.gridio.io/faq)
  — charging overview and savings comparison inspiration; do not copy marketing
  savings percentages or assume their tariff treatment matches this household.
- [HA custom-card API](https://contributors.home-assistant.io/frontend/custom-ui/card/)
  — coordinated cards within a dashboard, not a new standalone controller.
- [Apache ECharts](https://echarts.apache.org/) and
  [licence](https://github.com/apache/echarts/blob/master/LICENSE)
  — chosen chart engine, Apache-2.0 plus applicable notices.
- [Web Awesome Core](https://webawesome.com/) — candidate UI widgets; check the
  exact package licence/assets and avoid a paid-Pro dependency.
- [ApexCharts licensing](https://apexcharts.com/license/)
  — not the chosen engine; do not assume the current library is unrestricted MIT
  merely because the HA ApexCharts wrapper has an MIT licence.
