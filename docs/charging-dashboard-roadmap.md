# Morek autonomous charging and dashboard roadmap

Status: **in progress; manual baseline and ownership groundwork complete; autonomous mode not active**.
Updated 2026-11-12. The checklist below is the authoritative work queue.

This is the forward-looking plan for SpotNav Enhanced. Implement **one work block
at a time**, not a dashboard rewrite and controller rewrite in one release.
For existing code, HA access, hardware observations and credentials handling, read
[the development handoff](morek-development-handoff.md) and `AGENTS.md` first.
This document is not permission to deploy, restart HA, or issue hardware commands.

## Initial working-release goal

The user wants a usable installed dashboard and automatic charging, not a permanent
unarmed demo. Complete Stage 5 with the core daily frontend and backend connected to
real data, reactive planning and a safely migrated Morek schedule executor.
Historical charging comparisons, monthly analytics, savings and other later features
may remain explicitly unavailable; they are not prerequisites for this initial release.
The optional **Charge Now** override in Stage 10 is also post-installation work,
not a prerequisite for the initial release or its 5.8 live validation.

**Frontend decision:** the user chose an integration-provided HA custom sidebar panel,
using the same UI components, styling and stepped-area ECharts chart as the local sample
preview. The preview supplies fixtures and the panel supplies real HA/backend data;
they are not two independently maintained UIs. Preserve the existing integration domain
and working backend/card compatibility without requiring the old card as a second daily
interface. Comparable viewport/fixture parity is required; actual HA/mobile rendering
and its sidebar/header remain subject to integration testing, not assumed pixel-identical.

Current production dispatch is **unarmed**, not because that is the desired final
behavior, but because safe ownership transitions, lost-state/uncertainty recovery,
the existing site-regulator conflict, transaction authorization and retained-profile exit are unresolved.
The Stage 5.5–5.7 work must resolve these blockers rather than merely display them.
Do not remove the fail-closed gate before the complete reviewed activation path is safe.
If a required hardware capability or installation-specific decision prevents safe
operation, surface it and get a decision; do not label the initial release complete.

**2026-11-12 clarification:** the user says Morek handles household load protection
natively. SpotNav's requested role is scheduling fixed on/off charging windows, not
household load balancing or dynamically changing amps in response to house load.
The schedule's 0 A/allowed-current limits express those windows; they are not a
load-management algorithm. The reported native protection has not been independently
verified in this development session. Do not change or disable existing protections,
electrical limits, regulator configuration or code without explicit authorization.
Existing regulator conflicts remain an activation concern, not an instruction to
build a second load controller. Hardware checks are user-directed.

**Agreed charging controls:** the final daily sidebar has two simple controls:
**Pause / Resume Auto**, and **Charge Now**, which becomes **Return to Auto**
while its temporary override is active. Pause requests charging be held until
the person explicitly resumes; Resume returns to a fresh valid automatic plan.
Charge Now defaults to one hour with other durations. Return to Auto ends that
override early; charging may continue if the automatic plan selects the current
time. These are target semantics, not a claim that schedule-owned Pause/Resume
or Charge Now works today. Charge Now is deferred to Stage 10 after 5.8.

**BMW target and monitoring:** the user intends the BMW's own configured charge
limit to stop the car at its target (for example 80%). Morek's schedule controls
allowed charging windows; do not require a second live SOC-stop controller or
re-enable competing legacy commands. The SpotNav planning target and the limit
actually configured in the car are separate settings: do not assume they match,
that SpotNav changes the BMW limit, or that a stale SOC proves the target was met.
The app must still show whether charging and execution appear healthy using available
genuine observations, with unknown clearly shown where evidence is absent or stale.

**Complete the necessary development in order before installation.** After development
and review, the user plans to merge the branch to `main`, install it in HA and perform
deployed testing personally. 5.8 records that user-owned milestone, not an LLM task
to merge, install, activate or operate the charger. An LLM may help interpret logs or
diagnose problems if asked; HA access and live actions still require specific approval.
Local automated and mocked tests remain LLM development work. Development completion
does not prove deployed operation: real planning, schedule operation and measured
charging remain unverified until observed. ACK/readback alone is not physical-flow
evidence; never bypass an unresolved safety blocker or describe an unarmed installation
as verified automatic operation.

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
| 5 | Installable real-data daily dashboard and safe route to charging | Priority after prototype; automatic Morek dispatch remains unarmed |
| 6 | Genuine charging history | Later; not a prerequisite for initial installation |
| 7 | Extended charts, tracks and price insights | After initial real-data chart; actual track uses Stage 6 |
| 8 | Yesterday, costs and savings | Later; depends on genuine data |
| 9 | Targeted dashboard fixes | Only where needed; initial installation is in Stage 5 |
| 10 | Optional Charge Now override | After the initial 5.8 installation and user-directed validation; independent of Stages 6–9 |
| 11 | Adaptive charging estimates for Morek | Later work; reuse existing learning and genuine measurement sources |

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
    external integrations. Durable unarmed transition evidence was later added;
    active ownership transitions remain unimplemented.
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
    still refuses all sends; later unarmed transition groundwork is not activation.
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
    outcomes remain latched; no general recovery or uncertainty reset exists.
    Later unarmed transition/abort groundwork is not active ownership recovery.
  - Explain activation blockers, person Stop, protection, retained 0 A and supervised
    recovery/downgrade; neither readback nor selective removal resolves an unknown upload.

### Stage 5 — Single dashboard and daily controls (old A5 + B2)

- [ ] **5.1 Layout and shared components**
  - Build desktop/mobile browser prototype with sample data; get visual approval.
  - Local sample prototype is available in `frontend/prototype/`; browser checks
    and HA integration limitations are recorded in the development handoff. Visual
    approval remains pending; this does not complete 5.1.
  - Start with Web Awesome Core for polished shared controls and tokens; the selected
    production host is now the HA sidebar panel, not a Sections composition. Validate visual quality and HA
    compatibility. If it does not work, stop and reevaluate alternatives with the user.
- [x] **5.1a Initial prototype refinement** (sample groundwork; overall visual approval pending)
  - Refined local prototype and example ECharts are available; verification and
    unresolved limitations are in the development handoff. The user requested further
    refinement in later Stage 5 substages; don't repeat completed groundwork.
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
  - The work remains sample-only; final visual approval follows the remaining Stage 5 design work.
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
    data/components; the user subsequently chose the stepped-area chart for production.
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
    dependencies and reported limitations. Overall 5.1 visual approval remains pending;
    the user subsequently chose the stepped-area chart. No live data or hardware actions.
- [x] **5.1b3 Chart fidelity and interval navigation** (sample groundwork; visual approval pending)
  - Proposal windows now use a bottom-bright green gradient and an aligned pale plan
    track instead of dashed borders; window boundaries remain exact. Visual approval
    remains pending; see handoff.
  - Both charts now have a viewport-aligned fictional day/date band, midnight lines
    and dated interval tooltips; missing intervals are hatched. Desktop and emulated
    mobile checks are documented in the handoff. User visual approval remains pending.
    Production must verify available historical and published future prices and use the
    configured local timezone, including midnight and 23/25-hour DST days.
  - Local implementation uses anchored responsive labels, future-focused default and
    snapped navigation. Headless emulated pinch and taps worked; physical touch and
    visual approval remain unverified. 5.1b4 and 5.1b4a subsequently added plan work.
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
    card-balance follow-up in 5.1b4a. Overall 5.1 visual approval remains pending;
    the user subsequently chose the stepped-area chart.
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
- [x] **5.1b4a Balanced cards and unknown-value rendering** (sample-only; coordinator and visual review pending)
  - Shared rendering, independent unknown totals, balanced desktop cards and local
    missing/invalid/long-plan scenarios are implemented; see handoff for checks and limits.
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
- [x] **5.1c Sample price insights and monthly statistics** (sample-only; coordinator and visual review pending)
  - Local fictional insights use duration-weighted historical quartiles, a complete
    one-hour known-price opportunity and an October summary; see handoff for coverage,
    checks and limitations. The opportunity searches only Now and interval starts;
    its 5.1d label explicitly qualifies this restriction. Overall 5.1 visual
    approval remains pending; the user subsequently chose the stepped-area chart.
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
- [x] **5.1d Daily dashboard polish and visual review** (sample-only; coordinator and user visual review pending)
  - Local daily hierarchy, explicitly simulated scenarios and independent illustrative
    sent-versus-measured history are available; see handoff for checks and limitations.
    This historical comparison preceded the user's selection of the stepped-area
    chart; overall 5.1 visual approval remains pending.
  - Refine the full dark dashboard around the selected stepped-area direction: strengthen
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
- [x] **5.1e Vehicle and plan-evidence design** (sample-only; coordinator and user visual review pending)
  - Local battery estimates, separately defined low-SOC warning sample and fictional
    proposal/sent/readback/measurement freshness views are implemented; see handoff for
    checks and 5.2 source-verification needs. Overall 5.1 visual approval remains pending;
    the user subsequently chose the stepped-area chart.
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
- [x] **5.2 Overview and operation status** (implemented locally; coordinator review pending)
  - The existing card now shows an English real-dashboard overview and read-only Morek
    health, using separate, timestamped requests rather than claiming an atomic snapshot.
    Measurements without a trustworthy Morek power source are explicitly unavailable;
    sent ACK, effective readback and physical charging remain distinct. See the 2.5.31
    handoff for freshness, source and testing limitations. Planning remains backend-owned.
  - Focused lifecycle/race and action-safety tests and local desktop/mobile browser checks
    use mocked HA/OCPP boundaries. No live HA or physical charging was checked. Overall
    5.1 visual approval remains pending; the user selected the stepped-area chart.
- [x] **5.3 Plan controls and actions** (implemented locally; coordinator review pending)
  - The user chose English-only card presentation regardless of HA language; do not
    translate the 5.3 strings. The 2.5.33 work implements this and improves open-modal
    health updates and save coverage. Card tests now use English expectations while
    independent translation utility tests remain. The full suite passes; see the
    2.5.33 handoff for mocked-boundary results and limitations.
  - Bind target/minimum/cap/ready-by controls, complete windows, per-window/total
    estimated costs and policy explanations to existing backend settings/planner APIs.
  - Preserve manual Send/Refresh and their existing interlocks; do not present unimplemented
    suspension, charging pause, selective removal or mode exit as equivalent or operational.
  - Regression-test settings save → backend trigger → replan → coherent dashboard update,
    without browser-dependent planning; preserve uncapped and safety behavior.
- [x] **5.3a Phone notifications for plug-in and plan** (local implementation; coordinator review pending)
  - 2.5.34 associates notifications with the debounced connection generation, calculation
    start, current attempt/settings and resolved vehicle; a current unchanged publication
    is accepted. A persisted owed notice waits rather than using a restored proposal.
    Waiting and proposed-window updates use the existing phone choices, limits and tag.
    Mocked tests and remaining limitations are recorded in the handoff; no phone or
    charger was contacted. Morek mismatch/uncertainty phone events remain future work.
  - Reuse the existing per-charger HA mobile notification service, phone selection,
    event tracker, rate limiting and restart-safe deduplication. Inspect current
    `plan_installed` and plug-in/quiet-after-write behavior before changing it; do not
    add a parallel notifier or assume the existing message is already delivered.
  - After a recognized plug-in and settled replan, notify selected phones of the next
    proposed charging start–end with local date/time, and compactly show useful known
    estimates such as target/ready-by and total plan cost. Include estimated SOC by the
    ready-by deadline when a fresh, validated backend projection is available, clearly
    labelled as an estimate rather than a measured value or guarantee; distinguish it
    from the target and warn of a projected shortfall where supported. Reuse backend
    assumptions, account for battery versus wall energy and show unknown/omit the SOC
    estimate when inputs are missing or stale. If no valid plan or prices are available,
    give a concise truthful waiting/blocked reason rather than a stale time.
    Avoid duplicate or contradictory plug-in/plan notices; make timing bounded and test
    missed connection events, stale/replanned results, delayed inputs and restart.
  - Include high-value, bounded notices for material plan changes, minimum/deadline
    shortfall or schedule mismatch/uncertain outcome when supported; preserve existing
    person Stop, protection and phone opt-in semantics. Avoid notification storms and
    do not promise unsupported signals. No charger action is caused by notification.
  - Clearly distinguish proposed times and estimated costs from sent/ACK, effective
    readback and measured flow; never say charging has started without genuine flow
    evidence. Test actual notifier modules with mocked HA/phone delivery, unavailable
    fields, identity changes, retries/races, no phones and rate-limiting. Physical phone
    delivery and live actions require the user's separate approval and validation.
- [ ] **5.4 Shared sidebar UI and production price chart** (umbrella; 5.4a–5.4c in order)
  - One maintained dashboard UI, hosted by an HA custom sidebar panel and by the local
    sample preview. The stepped-area chart is selected; no second daily dashboard is
    required. Preserve existing 5.2/5.3 backend contracts, interlocks and compatibility.
  - 5.4a–5.4c are locally implemented; this umbrella stays open for coordinator
    review and the documented 5.4c full backend-suite gap. That offline suite may
    be deferred to 5.7b and does not block 5.5–5.7 implementation.
- [x] **5.4a Extract the tested UI into shared components** (local visual foundation; coordinator review pending)
  - The preview mounts `frontend/shared-dashboard/dashboard.js` through an explicit
    sample adapter; shared styles, dialog, stepped chart and views have lifecycle
    cleanup. Local browser checks and baseline comparisons are recorded in the handoff.
    The bar chart is an optional comparison only. No sidebar or real data is connected.
    Updates currently remount, resetting chart zoom, closing dialogs and losing drafts;
    sample-oriented EUR/cents and global CSS assumptions also need live-host adaptation.
    Real-data timestamp/DST,
    HA CSS isolation, registration and integration are 5.4b/5.4c work.
  - Refactor the existing prototype layout, styles, Web Awesome controls, modal and
    selected stepped-area chart into one production-ready shared UI code path. Local
    preview uses explicit sample fixtures via an adapter; no sample data or simulated
    actions can leak into the real adapter. Reuse the same UI source in both hosts.
  - Preserve the tested desktop/mobile appearance, dark design, interaction and English
    wording; bundle assets locally with notices. Test fixture rendering, responsive
    behavior, accessible controls, safe untrusted text and component cleanup. Compare
    old prototype and shared preview at equivalent widths; no HA deployment or commands.
- [x] **5.4b HA sidebar host and live overview/controls** (local implementation and mocked verification; coordinator review pending)
  - 5.4b1–5.4b2 are complete locally. Actual HA integration, physical touch and
    hardware behavior remain unverified; 5.4c remains a separate substage.
  - Register one integration-provided HA custom sidebar panel and mount the shared UI,
    with a practical non-destructive setup/update path. Use HA's supported panel interface;
    handle sidebar/mobile navigation, safe areas, lifecycle, access and CSS isolation.
  - Connect existing 5.2/5.3 real dashboard/settings/Morek read-only paths through a real
    adapter. Reuse revision checks, permissions, race guards and manual interlocks; never
    render mock values or cause a charger write when opening the panel. Missing measured
    power, historical data and unsupported fields remain visibly unavailable.
  - Fix the shared UI's full-remount update behavior before wiring frequent HA updates:
    preserve open dialog/focus, unsaved settings drafts, scroll and chart zoom across
    routine updates, while delivering critical health changes immediately. Handle
    lifecycle/config changes and explicit save/conflict safely without stale writes.
    Replace hardcoded sample currency/basis assumptions with authoritative values or
    Unknown; do not recalculate unavailable per-window costs in the UI.
  - Test actual-module contracts, mock HA panel lifecycle, action safety and visual parity
    with preview under identical fixture/viewport, desktop and mobile. HA-host behavior
    is not proven until installation; don't overwrite user views or remove the old card.
- [x] **5.4b1 Sidebar host and real read-only data** (local mocked-boundary implementation; coordinator review pending, not an installable final release)
  - Register an integration-provided sidebar panel and locally bundle/mount the existing
    shared UI. Connect real, decoded 5.2 dashboard and read-only Morek status data via a
    lifecycle-safe adapter with explicit selected charger and no sample fallback. Missing
    real fields and the 5.4c price chart remain unavailable; all settings/charger actions
    remain disabled in this slice. Preserve the old card and protect HA styles/assets.
  - Test actual integration registration/cleanup and panel adapter with mocked HA
    boundaries, out-of-order responses, missing data, local asset packaging, read-only
    safety and desktop/mobile mock-host parity with the shared preview. No live HA access.
- [x] **5.4b2 Real controls and stable interactive updates** (local implementation and mocked verification; coordinator review pending)
  - Local continuation adds canonical revision-checked saves, guarded Morek debug and
    admitted Pause/Resume, single Send/Clear confirmation and in-place shared/debug
    reconciliation. Bounded closure testing is documented in the handoff and matrix;
    actual HA, physical touch and charging remain unverified.
  - Verification continuation bounded stalled settings writes without retry and fixed
    read-slot overlap after actions; `frontend/sidebar/verification-matrix.md` lists
    the representative closure cases and their mocked evidence.
  - Build on 5.4b1 to wire existing 5.3 revision-checked settings and permitted manual
    debug controls, preserving all admin/interlock checks. Implement stable updates that
    preserve modal/focus, selection, draft, scroll and zoom while delivering warnings;
    invalidate stale charger/revision actions and handle save/conflict/teardown safely.
  - Coordinator review found that 5.4b1 passes epoch-millisecond windows into a sample
    hour-based active-duration calculation: a one-hour plan renders as 216,000,000 min.
    Define and test explicit time units end to end; correct real and preview durations
    without changing exact window times. Also replace the age-only timer with bounded,
    coalesced recurring real dashboard/status reads and reconnect handling: fresh backend
    changes must appear without manual Refresh or destructive UI remounts. Test slow,
    failed, stale and out-of-order requests and stop timers on teardown.
  - Test successful/rejected saves, admin/non-admin, lifecycle/races and no charger writes
    except explicitly requested and authorized existing actions. No deployment or live
    charger operation; coordinator review of both slices remains pending.
- [x] **5.4c Real stepped-area price chart and install preparation** (local implementation and mocked checks; full backend suite deferred)
  - 2.5.39 includes the published-interval binding and a coarse-interval wheel
    zoom correction. Built-panel mocked desktop and emulated-mobile pointer-tooltip,
    wheel and reset checks pass; see handoff for evidence. The full HA-plugin
    dashboard API/contract/golden suite has not run and remains a validation item,
    not a reason to halt implementation of 5.5–5.7. WSL Python 3.12 lacks
    ensurepip and the pinned HA pytest plugin requires Python 3.14 or newer; the
    isolated WSL setup attempt failed before tests ran. On a supported host with the HA
    test dependencies installed, run `python -m pytest tests/test_dashboard_api.py -q`.
    Future installation guidance is in `sidebar-installation-preparation.md`.
  - Bind the shared ECharts chart to real available prices and proposed windows, with
    correct units/basis, timezone/DST, missing/negative prices and source resolution.
    Show unavailable history honestly; defer historical tracks and monthly insights.
  - Bundle ECharts and all needed assets/notices locally, test render/interactions and
    API contracts, and document panel installation/update. Don't reimplement a second UI
    or assume local preview proves actual HA integration.
- [x] **5.5 Durable Morek ownership and recovery** (unarmed local implementation and mocked verification; coordinator review pending)
  - This completes the unarmed groundwork only. Retained-profile resolution,
    first-use versus lost-state provenance, transaction authorization, protection
    conflicts and activation remain blockers in 5.6–5.7; the full 5.4c HA-plugin
    dashboard suite is still unrun. No live behavior is claimed.
  - Umbrella only: assign 5.5a–5.5f individually, not all of 5.5 in one session.
    The checked groundwork is not active ownership or permission to send a profile.
  - **Unarmed-entry abort (2.5.43; coordinator review pending):** an internal
    explicit abort removes only a verified unarmed marker when the existing Auto
    pause is durably `until_resumed`, identity is unique, and known profile outcomes
    are not uncertain. It does not clear or claim absence of retained profiles,
    resume Auto, or recover actual Morek ownership; see handoff for crash limits.
  - **Durable unarmed entry evidence (2.5.41; coordinator review pending):** the
    internal entry path persists a versioned requested/interrupted/drained marker
    on the existing legacy binding before reporting a drain. Startup and manual
    profile admission consult it; all markers remain unarmed and block ordinary
    writes. Existing legacy records remain readable. Failure before the first marker
    lands cannot be distinguished after restart from the previous legacy document;
    lost-document and unknown-outcome recovery remain open. See the handoff.
  - **Historical person-Stop foundation (2.5.40):** an
    internal, process-local unarmed drain is interrupted by a separately classified
    Stop reservation before the Auto lock. Ordinary admission remains closed; no
    entry or owner was persisted or activated in that slice. Later 5.5b–5.5f add
    durable unarmed transition/recovery groundwork; activation remains open.
  - **Historical entry/drain blocker (2026-11-12):** the existing
    quiesce latch refuses a person's Stop at the ordinary controller guard. The
    separately classified regulator-protection path bypasses that guard. Making
    quiesce durable or wiring it into entry would therefore change person-Stop
    behavior; keep the latch unwired and production dispatch unarmed pending a
    reviewed compatible design. An actual-module mocked characterization records
    the conflict; the newer internal coordination above does not use the old latch.
  - Resolve and implement safe ownership entry/exit, producer drain and durable transitions,
    lost-document versus first-use ambiguity, uncertain in-flight outcomes, restart/reconnect
    and retained-profile handling. Do not bypass existing uncertainty or identity guards.
  - Test actual modules with mocked HA/OCPP/storage across crashes, races, migration,
    rollback and competing ordinary writers. Keep production dispatch unarmed until the
    full activation path is reviewed and all remaining blockers are resolved.
- [x] **5.5a Person-Stop and unarmed drain foundation** (2.5.40; mocked review pending)
  - Process-local drain, generation checks and a distinct reserved person-Stop path;
    no durable ownership, autonomous dispatch or physical-stop guarantee.
- [x] **5.5b Durable unarmed entry evidence** (2.5.41; mocked review pending)
  - Requested/interrupted/drained markers block ordinary and manual profile writes
    across restart. First-marker and lost-document ambiguity remain explicitly open.
- [x] **5.5c Abort of an unarmed entry** (2.5.43; mocked review pending)
  - Explicit, evidence-checked abort returns to the prior legacy binding only with
    a disk-verified until-resumed Auto pause. No profile, charger or resume action.
- [x] **5.5d Persisted ownership handover foundation** (2.5.45, unarmed; coordinator review pending)
  - The internal handover now has a mocked success case and Stop-wins save
    compensation. An uncertain save remains blocked; a later Stop stores intent
    without bypassing the owner. Coordinator review remains pending.
  - **Historical 2.5.44 partial:** legacy manual Send/Clear admission was made to
    require a valid unarmed legacy owner, including after reload. At that point the
    handover and Stop-wins protocol were not complete; 2.5.45 supersedes that state.
  - Wire and test a durable, connector-bound handover from the existing entry/drain
    evidence to a Morek-owned **unarmed** record. Prove conflicting legacy and manual
    profile writers remain excluded through persistence and restart; keep production
    owned-profile dispatch refused. This internal record does not enable schedule-mode
    operation or imply an actionable person-Stop policy for retained profiles; preserve
    the existing Stop path during entry and leave that later policy to 5.6b.
  - Model and refuse incomplete/uncertain writes and Stop races; no activation,
    automatic profile sends, clears, or user-facing mode switch. A drained connector
    alone is not proof that producers or unknown external operations are settled.
- [x] **5.5e Missing and uncertain evidence recovery** (2.5.46; unarmed, coordinator review pending)
  - Startup and control-availability recovery inspect connector-bound ownership and
    profile outcomes, report specific blocked states and may invoke the existing
    evidence-checked unarmed abort only with a disk-verified indefinite Auto pause.
    Missing/lost versus first-use provenance remains unverified and activation blocked;
    no profile inventory or physical charging is inferred. See handoff for limits.
  - Handle interrupted handovers, lost/malformed ownership documents, stale attempts
    and unknown outcomes using existing durable evidence. First use and lost state
    must not be silently conflated for activation. Expose bounded, explicit refusal
    or recovery reasons; do not add generic journaling as an automatic prerequisite.
  - Mock restart/reconnect, delayed responses, persistence failures and duplicate
    identity; do not retry uncertain writes or infer profile inventory from readback.
- [x] **5.5f Safe ownership exit and handback** (2.5.47; unarmed/mocked, coordinator review pending)
  - The internal exit persists a legacy-owned `exit_held_unarmed` interlock; ordinary
    legacy, manual profile, Resume and deletion handback stay blocked, even after
    restart. The interlock cannot be removed by entry recovery. Known profile evidence
    stays intact; a stored schedule or final 0 A is neither removed nor assumed absent.
  - Implement/test a guarded exit transition and legacy handback without silently
    removing or releasing an owned profile or its persistent 0 A limit. Keep known
    sent/unknown evidence and person Stop distinct; expose unresolved decisions rather
    than making unsafe assumptions. No live profile action or activation.
  - Include the combined actual-module crash/race and regression tests for 5.5 in
    this slice; do not add a separate test-only substage unless a real defect requires it.
- [ ] **5.6 Authorization and safe schedule-only operation**
  - Umbrella only: assign 5.6a–5.6c individually. Preserve protection and person Stop;
    Morek's reported native load protection is not a SpotNav load-management task.
  - Resolve how a new charging transaction is authorized, how person Stop and
    competing writers are respected, and how retained 0 A, invalid/no-price plans
    and leaving the mode are handled. Address any existing regulator conflict
    without implementing household load management or dynamic amp regulation.
  - The user reports Morek provides native household load protection; do not build
    a SpotNav replacement or add a load-balancing feature. Preserve existing safety
    and fail-closed activation safeguards; establish the applicable protection and
    configuration before changing any dependency or enabling a conflicting mode.
    Do not require a separate hardware-testing stage.
  - Implement only an explicitly reviewed, fail-closed policy; identify any user or
    installation-specific decisions and stop for them rather than assuming safety.
    A stored current limit cannot start or authorize charging by itself.
- [x] **5.6a Transaction authorization and connection readiness** (2.5.48 local, mocked; coordinator review pending)
  - Read-only status uses uniquely resolved OCPP connection, control availability and
    fresh connector-scoped status. Missing/stale facts remain unknown; the HA state
    timestamp can age out an unchanged but still valid status. Authorization and
    measured flow remain unknown: existing integration paths do not establish a
    trustworthy active transaction or Morek power measurement. No new active-session
    requirement was added to future schedule admission; dispatch stays unarmed.
  - Determine the installation's new-session authorization behavior and reliable
    transaction/measurement evidence in user-directed 5.8. Profile ACK, limits and
    plug-in do not prove authorization or flow. No live validation is claimed.
  - The 2.5.48 local implementation and mocked checks were reported; coordinator
    review remains pending. They do not establish live authorization or flow.
  - Reuse observed charger/transaction facts to report and gate what can actually
    be known about a new charging session. Do not change authorization settings or
    infer that a stored schedule authorizes charging. Test unknown/offline/refused
    cases with mocked boundaries; surface installation-specific decisions for the user.
- [x] **5.6b Person Stop and retained-schedule policy** (2.5.52 local, unarmed, mocked; quick coordinator review)
  - Quick review found no blocker to proceeding to 5.6c; the isolated planning and
    lifecycle suites were independently rerun (522 passed, 1 deselected; 256 passed).
    This is not a comprehensive safety audit or evidence of deployed behavior.
  - Auto's existing Stop/Pause and Resume boundaries route a unique schedule owner
    to connector-bound durable intent; the worker requests a held-off profile or the
    latest valid plan under its existing admission and uncertainty guards. Offline
    intent requires an exact physical ID or one unambiguous retained alias mapping,
    plus matching durable ownership. A persisted Resume after a process restart
    requires explicit reconfirmation before dispatch; it is never reported as done.
  - Production dispatch remains unarmed and schedule-owned sidebar controls remain
    disabled. Mock tests cover generation races, pending/rejected/uncertain outcomes,
    bounded readback and restart; ACK/readback do not prove physical flow. The held
    exit has no release path, and live validation remains user-directed in 5.8.
  - **2.5.51 partial:** the sidebar explicitly disables schedule-owned Pause/Resume
    while dispatch is unarmed and distinguishes reported intent, request, ACK,
    readback and unknown physical charging. The person-facing action, durable Resume,
    offline recording and complete mocked race verification remain unimplemented.
  - **2.5.50 partial:** an internal, versioned connector-bound pause record in the
    existing outcome ledger selects a held-off worker profile under simulated authority;
    it is not derived from legacy `until_resumed`. It is not exposed as a person-facing
    action, and Resume is not implemented. Offline pause, durable Stop/Resume races,
    bounded readback end-to-end and sidebar presentation still need work. Production
    dispatch is unarmed and this substage remains open.
  - **2.5.49 partial:** a Stop reservation invalidates older connector work and the
    worker rechecks after persistence awaits. Flat 0 A readback can match only a
    bounded one-hour interval. The held-off builder is not wired to Pause; durable
    schedule-owned Pause/Resume and its operator status remain unimplemented.
    Production dispatch remains unarmed; this substage is not complete.
  - Implement the user's agreed **Pause / Resume Auto** control under schedule
    ownership. Pause requests charging stop and remain held until explicit Resume;
    Resume returns control to the latest valid automatic plan. A failed, offline or
    unknown update is not a confirmed physical stop. Do not silently release a
    retained 0 A limit when the plan or a safe replacement is unavailable.
  - Define the necessary fail-closed behavior for person Stop and a future stored
    profile. Keep a Stop/pause, upload suspension, profile removal and mode exit
    distinct; no automatic blanket clear. Test persistence, races, restart, unknown
    outcomes and measurements without claiming physical stopping from ACK/readback.
    The optional Stage 10 **Return to Auto** cancels only Charge Now; it is not
    Pause and may allow charging immediately if the automatic plan calls for it.
- [x] **5.6c Invalid-plan and competing-writer policy** (2.5.54 local, mocked; quick coordinator review)
  - Quick review found no blocker to proceeding to 5.7a; independently reran the
    isolated planning suite (544 passed, 1 deselected) and listed lifecycle suite
    (270 passed). This is not a comprehensive safety audit or deployed verification.
  - The unarmed worker now checks process-local planner provenance against current
    selected source and revisions, authoritative per-day documents and UTC window
    coverage, relevant vehicle/settings/connection facts and the existing SOC freshness
    rules at every pre-dispatch validation. Invalid evidence leaves retained limits and
    pending Resume untouched; Pause's held-off intent is independent of prices. Manual
    preview retains its previous contract. The existing unarmed gate is unchanged.
  - Conservative scope: only target-SOC cheapest-price plans have checked provenance;
    manual-kWh and solar/hybrid proposals are blocked as `plan_input_provenance_unavailable`.
    Do not activate those cases without implementing and reviewing their energy/forecast
    evidence. This is a refusal, not a claim that such plans are intrinsically invalid.
  - Manual Send/Clear now also honor Stop generation across persistence waits; ordinary
    admission refuses work while a Stop is reserved. The separate regulator protection
    path remains unchanged. External writers and installation protection cannot be
    inventoried or controlled here; they and held-exit resolution remain 5.7 blockers.
    Tests are mocked and no physical behavior or operational mode is claimed.
  - **2.5.53 partial; not complete:** manual profile admission now rechecks the
    connector generation after the awaited ownership lookup, refusing a Stop that
    superseded it there. Existing worker and admission tests pass, but this is not
    the full invalid-plan/competing-writer policy or its requested test matrix.
    In particular, dispatch-time freshness independent of a new planner publication
    and actionable conflict reporting still need investigation and coverage.
    External/OCPP writers and installation-specific regulator interactions cannot
    be ruled out locally; composite readback is not a profile inventory.
  - Handle no/stale/invalid prices or plan and existing conflicting writers without
    silently releasing a stored limit or disabling protection. Report blockers and
    test mocked reconnection, person Stop and regulator exceptions. Do not implement
    household load balancing or dynamically adjust amps for house load.
  - Reuse 5.6b's durable Pause/Resume intent, generation checks and uncertainty
    handling. Keep the unarmed production gate; a restarted pending Resume requires
    fresh confirmation. The held-exit interlock has no release path and must not be
    bypassed; resolve or explicitly carry it as an activation blocker into 5.7.
- [ ] **5.7 Activation implementation and pre-install automated validation**
  - Umbrella only: assign 5.7a–5.7b individually; deployed activation and testing
    are the user's own 5.8 milestone, not LLM implementation tasks.
  - Replace legacy execution for the supported Morek connector with the existing
    guarded schedule worker and planner triggers, using a safe migration and durable
    evidence. Do not build a runtime switch back to the old controller. Preserve
    protections, do not retry unknown outcomes, and do not silently arm an unsafe
    migration on update. The user installs and decides when to operate it.
  - Test changed and unchanged settings/prices/SOC → backend replan → guarded schedule
    reconciliation, startup/reconnect and conflict/uncertainty cases. Show proposal,
    sent ACK, effective readback and real measured flow separately on the live dashboard.
  - Provide practical current charging and execution-health monitoring in the sidebar:
    reuse available genuine charger/vehicle status and fresh measured power or energy,
    identify the source and freshness, and show offline, waiting, mismatch, failure or
    uncertain states when supported. Distinguish a charger-reported charging state from
    measured flow; never label an ACK, offered current or proposed window as charging.
    If a trustworthy source is unavailable, show unknown and the limitation rather
    than inventing a reading or blocking development on a live hardware test.
  - Verify restart/reconnect and safe person Stop/protection behavior with automated
    coverage. Summarize useful manual checks and known limitations for the user;
    ACK or matching effective limits are not proof of physical flow. No overnight
    test is mandatory, and no live contact or operation is implied.
  - Carry forward the unrun 5.4c HA-plugin dashboard API/contract/golden suite;
    run it on a supported local host if available. If not, report the exact gap
    and evidence to the user before installation; do not claim it passed or halt
    unrelated implementation just to provision the test environment.
- [x] **5.7a Replace Morek execution with the schedule owner** (local mocked implementation; coordinator review pending)
  - **2.5.64 local verification:** a clean reconnect can revalidate
    a ticket known in the same process; Stop, identity changes, uncertain outcomes and
    stale lifecycle events fail closed. Process restart still requires an administrator
    to reconfirm completed ownership; an interrupted completion write can have landed
    and an unrecorded Stop cannot be reconstructed. Real-admission planner input
    races at both persistence boundaries and late ACK/composite readback after Stop
    have new tests. Real-admission Resume/Stop during pause-intent persistence and
    cancellation/newer-barrier contention during reconnect revalidation are covered.
    This is local mocked evidence, not proof of deployed or physical behavior.
  - **2.5.63 wired, full matrix/review outstanding:** connector-bound completion,
    a generation/lifecycle-bound process ticket, explicit admin reconfirmation after
    restart/reconnect, production owned admission and final worker persistence checks
    now have local mocked coverage. Real setup → restart/reconfirmation → real
    admission → worker → mocked OCPP succeeds. Reconfirmation itself sends nothing.
    The complete requested actual-admission safety/provenance race matrix is not yet
    established; do not mark this substage complete on the strength of that one path.
    A Stop not durably recorded before a crash cannot be recovered. Native protection,
    external writers and the present physical charger state are not established.
  - **2.5.62 safety correction, not completion:** startup/reconnect no longer
    releases its barrier for an old or unconfirmed owner. No completed evidence is
    produced yet, and production admission remains unarmed. The completion-save,
    crash/Stop recovery, actual dispatch and full mocked race matrix remain open;
    see the current handoff. External-writer absence and native protection are
    limitations to report, not universal machine-proof prerequisites.
  - **2.5.61 partial:** new unarmed entry transitions carry a versioned migration
    ID; the owner save carries the same ID as `owner_written_unconfirmed`. This
    survives a possibly-landed owner save but is deliberately not completion evidence.
    Old records remain readable and unverified. Production dispatch remains
    unconditionally unarmed. A crash/Stop-safe completion protocol and real admission
    remain to be implemented and tested; see handoff. External-writer absence need
    not be machine-proven, per the user's decision, but uncertainty is not proof of
    retained-profile safety or permission to clear a charger.
  - **2.5.60 partial:** startup now reserves the same lifecycle barrier before
    ownership initialization, and a handover is interrupted by any newer lifecycle
    revision even if an identity changes away and back. Wired reconnect tests cover
    additional Stop, duplicate callback, identity, cancellation and save-failure
    boundaries. Production dispatch stays unconditionally unarmed: an owner record
    alone does not prove handover completed after an interrupted save, and external
    writer/protection evidence is not established. Full invariants remain open.
  - **2.5.59 partial:** reconnect may release its generation-bound barrier only
    after unique schedule ownership is compared against the durable document and
    the settled outcome ledger, with lifecycle, connector and Stop rechecked under
    admission. Existing owner admission still excludes ordinary writers and
    production owned-profile admission remains unconditionally unarmed. Stale,
    uncertain, cancelled or ambiguous release attempts stay closed. This is mocked
    groundwork; the full wired migration race matrix and 5.7a remain open.
  - **2.5.58 partial:** availability callbacks synchronously reserve a target
    writer barrier before scheduling initialization. A barrier remains closed for
    the process lifetime, including failed or stale recovery; person Stop and the
    separately classified protection path retain their existing treatment. Mocked
    lifecycle tests cover the pre-task gap, a pre-admitted writer and a real setup
    path through the unarmed owner. The full requested lifecycle/race matrix and
    production admission remain open; see handoff before treating this as complete.
  - **2.5.57 partial:** charger setup now starts the existing unarmed connector
    drain before Auto startup and invokes the existing producer-locked handover.
    A unique durable legacy binding and settled connector-ledger attempt are required;
    missing ownership is not initialized on this path. Missing or uncertain ledger
    evidence leaves the entry interlocked. This is not active schedule dispatch.
    Full setup/reconnect race and failure coverage, restart provenance, and the
    remaining production admission invariants still need review; see handoff.
  - **2.5.56 partial, not complete:** startup/reconnect no longer automatically
    aborts interrupted unarmed entry markers back to legacy. It preserves the marker
    and existing held-exit interlock; owned dispatch remains unconditionally refused.
    Legacy-owned records and missing-document compatibility still need a reviewed
    safe migration, including person Stop and uncertain prior writes. The interrupted
    5.7a enable/disable draft remains in the working tree for review but its WebSocket
    actions are refused and it grants no dispatch authority; no mode switch is offered.
    The full single-owner migration and its admission/race matrix remain open.
  - **2.5.55 partial, not complete:** read-only readiness and sidebar evidence now
    explicitly report first-use/lost-state ambiguity, unresolved retained profiles,
    held handback, external writers, protection and authorization. No enable or
    disable operation was added; production admission remains unconditionally unarmed.
    An enablement intent or acknowledgement cannot establish physical facts. The
    safe migration, final-dispatch checks and their race/persistence test matrix remain.
    This historical partial predates the decision below; a dynamic legacy handback or
    separate runtime enable/disable mode is no longer a product requirement.
  - Make schedule ownership the single execution path for the supported Morek
    connector, reusing existing guarded worker and planner code. Preserve shared legacy
    behavior for other chargers and independent protection. Assess existing ownership
    and held-exit records before changing them; safely migrate known states and refuse
    ambiguous or uncertain states rather than deleting or bypassing their safeguards.
    Do not automatically restore the competing legacy controller for Morek.
  - Replace the unconditional owned-profile refusal only if the complete applicable
    admission, durable ownership, migration, restart and safety invariants are
    implemented and tested; otherwise retain it and report the exact blocker. Target-SOC
    cheapest-price plans are the only currently provenance-checked scope; do not silently
    enable manual-kWh or solar/hybrid modes. Surface supported scope and refusal reasons.
  - Disabling the HA integration is the user's chosen way to stop SpotNav; it may
    leave a schedule or 0 A limit on the charger. Explain this honestly; no automatic
    clear or runtime legacy handback is required. Resolve or retain blockers for
    unknown profile outcomes, retained-profile consequences, first-use/lost-state
    ambiguity, external writers and installation protection; do not treat the removal
    of a mode switch as evidence that the charger is in a safe state.
- [ ] **5.7b End-to-end local regression and release handoff**
  - Exercise settings/price/SOC → plan → guarded reconciliation, stable-plan
    deduplication, restart/reconnect, uncertainty and operator status with mocks;
    include the deferred 5.4c suite if a supported local host is available.
    Report exact unrun tests, known blockers and useful manual checks to the user;
    do not install or access the deployed system as part of this substage.
  - Mock-test the actual monitoring path for charging/not charging where supported,
    unavailable/stale data, offline status, errors and schedule mismatch; show what is
    known and what is not without treating status alone as measured power. Document
    available source limitations for the user's own deployed checks.

### 5.8 — User-owned installation and deployed validation milestone

This is **not an LLM implementation substage**. After 5.2–5.7 and 5.3a are
complete and reviewed, the user plans to merge the current branch to `main`, install
the release in HA, and perform deployed testing themselves. The LLM must not merge,
push, deploy, restart HA, enable charging or operate the charger as part of this plan.
The user can ask for help interpreting logs or diagnosing a problem; access or any
live operation still requires specific approval, with read-only diagnostics first.
Do not expose credentials or private household data.

Useful observations for the user's own testing include the loaded version, real
prices and vehicle/charger data, settings and notifications, replanning without an
open dashboard, and safe behavior on reconnect or errors. When the user chooses to
enable the reviewed automatic mode, distinguish the calculated proposal, sent ACK,
effective readback, transaction authorization and actual measured charging. Changed
valid intent should reconcile; unchanged or unsafe intent must not cause duplicate
or unsafe dispatch. A request, ACK or readback alone does not prove charging.

Record deployed operation as unverified until the relevant observations are actually
available; report blockers or gaps honestly. This does not make Stage 6–9 history or
optional polish a prerequisite for initial installation. The user's merge and test
plans do not themselves authorize an LLM to perform those actions.

### Stage 6 — Real history data (old B1)

Stage 6 remains open and is **not required for the initial 5.8 release**. The
repository already has `sessions/store.py`, `sessions/recorder.py`, session APIs,
energy-register discovery and `execution/power_energy.py`; inspect and reuse these
before adding storage or an importer. `debug_day.py` retains limited diagnostic
rows for debug use, not an established production charging-history source. The
existing Morek outcome record is not a complete versioned history. None of these
facts proves which historical or live measurements this installation exposes.
Use the source inventory to improve the current charging/health view as well as
history; do not defer the basic honest status and unknown indicators in 5.7 to
historical analytics.

- [ ] **6.1 Source inventory**
  - Inventory existing session, energy-register, integrated-power, OCPP and Recorder
    paths first; identify exactly what is genuinely measured, derived or unavailable,
    along with timestamps, resolution, retention, freshness and connector association.
    The 5.6a readiness view did not establish a trustworthy Morek power or active-
    transaction source; do not assume either exists from status or offered current.
  - Consider Bavarian CarData as fallback/cross-check; verify home-session association,
    battery versus wall energy, coverage and gaps before use. Repository/mock inspection
    can start locally; installed HA/Recorder or hardware checks require the user's
    specific approval and remain user-directed, not a separate hardware-testing stage.
- [ ] **6.2 Capture and provenance**
  - Extend/reuse verified existing stores as appropriate to retain immutable sent-plan
    versions and genuine measured power/energy or validated source events. Existing
    aggregate/session/debug records must not be assumed to contain a complete trace.
  - Label measurement-derived energy estimates separately from meter counters; handle
    resets, duplicates and gaps. Never substitute plans, offered limits, ACKs or
    schedule windows for observations; unknown is not zero.
- [ ] **6.3 Queries and retention**
  - Extend existing session/history APIs where suitable with bounded retention and
    queries carrying original tariff, plan, source and coverage context. Do not use
    today's plan or changed tariff to silently reconstruct older sessions.
  - Test restart/midnight, gaps, charging outside the sent plan and a planned block
    with no observed flow using deterministic fixtures and mocked boundaries.

### Stage 7 — ECharts prices and schedule tracks (old B3)

The real-data stepped-area price chart and proposal overlay, source boundaries,
negative/missing/DST mocked cases, wheel zoom, pointer tooltips, reset, snapping
and zoom-preserving updates are **already implemented locally in 5.4c**. Reuse
them; do not rebuild, rebind or repeat that work. The full HA-plugin dashboard
suite remains unrun and is tracked in 5.7b; actual HA and physical-touch behavior
remain unverified and any live checks are user-directed, not a new test stage.

- [ ] **7.1 Available-day navigation**
  - Add Yesterday/Today/available future/All shortcuts only for periods the real
    price source can actually provide. Clearly report missing history or future
    prices; do not synthesize days or assume tomorrow is always published. Reuse
    5.4c's existing horizon and source-boundary zoom behavior.
- [ ] **7.2 Practical chart interaction**
  - Fix actual usability or responsive-resize problems in the real chart, including
    source-resolution and timezone/DST changes. Preserve existing zoom, tooltip,
    wheel and reset features; no separate accessibility-polish project is needed.
    Physical touch remains unverified until the user chooses to test it.
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

This is later work, not a prerequisite for the initial 5.8 installation. Reuse the
existing session store, recorder, history and savings APIs and Stage 6's genuine
measurement/plan evidence; extend them only where needed. Existing session costs
use current settings or a stored legacy cost, so do not assume historical tariffs
were preserved. Coordinate chart tracks with 7.3 and monthly insights with 7.5
rather than implementing the same feature twice.

- [ ] **8.1 Yesterday comparison**
  - Default to yesterday with date selection; show measured charging against the
    plan actually sent, price context, actual energy, timing differences and
    out-of-plan charging where evidence exists. Reuse the shared chart.
  - Show gaps and unknown coverage separately from confirmed absence of flow;
    never use a plan or readback as a substitute for measured charging.
- [ ] **8.2 Costs**
  - Extend existing calculations for plan energy and estimated cost, per-window
    costs and measured/estimated session, day and month totals. Preserve the tariff
    context available at the time and label estimates and missing historical rates;
    do not silently price past charging using today's tariff. Test missing and
    negative prices and fee/tax changes.
- [ ] **8.3 Savings and summary cards**
  - Extend existing savings calculations using an explicit comparable baseline for
    the same energy, such as charging immediately after plugging in at comparable
    power. Distinguish forecasts from historical estimates, show coverage and
    assumptions, and report unknown when evidence is insufficient, not zero.
  - Keep totals consistent across dashboard cards and reuse 7.5 monthly insights.

### Stage 9 — Targeted dashboard fixes (old C2)

No separate themes, light/dark modes or extra accessibility-polish project is
needed for this single-user dashboard. Keep the interface usable on desktop and
mobile, with readable warnings and working essential controls. Installation and
user-directed testing belong to 5.8; this stage is not another prerequisite.

- [ ] **9.1 Fix real integration gaps when needed:** check the combined dashboard,
  empty/error states and repeated updates; fix practical layout or interaction
  problems and duplicate daily controls rather than performing a general redesign.
- [ ] **9.2 Documentation only where needed:** correct installation, migration or
  diagnostics guidance when a real gap is found; never overwrite user views or
  claim unperformed hardware tests. Reuse the existing 5.4–5.8 guidance.
- [ ] **9.3 Optional additional execution-health notifications:** consider bounded
  Morek mismatch/uncertainty phone events beyond the existing 5.3a notices if useful.
  Reuse the existing notifier, opt-in and deduplication; never equate ACK/readback
  with measured charging. Not required for 5.8.

### Stage 10 — Optional Charge Now (after initial installation)

This is a user-requested **nice-to-have after 5.8**, not a prerequisite for the
initial working release, its installation or live validation. It can be prioritized
after 5.8 independently of Stages 6–9. It is not implemented today. Implementation
and subsequent deployment or hardware actions require their own assignments and
specific approvals; this roadmap grants none.

- [ ] **10.1 Bounded override and return to Auto**
  - Implement a deliberate temporary **Charge Now** override, defaulting to one
    hour and accepting other user-selected durations/end times. Make any price-cap
    override explicit and show the current price or honestly report it unavailable;
    decide how unknown prices are handled with the user rather than inventing a rule.
  - Reuse the same Morek schedule owner, fixed-current on/off schedule builder and
    durable execution evidence as Auto. Do not use a competing legacy start/stop
    loop, household load management or dynamic amp regulation.
  - On expiry, return to the latest valid automatic plan and reconcile the schedule.
    Include the override end and feasible subsequent automatic windows in the owned
    schedule when possible, so the intended handback does not depend solely on HA
    being online at that instant. Respect actual charger block/horizon limits; never
    silently drop or broaden plan windows. Define honest degraded behavior when the
    latest plan or an upload is unavailable.
  - **Cancel Charge Now** ends the override early, recalculates the automatic plan and
    sends the new automatic schedule through the same owner. Auto's normal rules then
    control charging. If Auto selects the current time, charging may continue or
    restart immediately; do not suppress a valid current window or promise a distinct
    zero-current pulse. Cancelling Charge Now is not a persistent person Stop/pause.
  - Preserve person Stop and explicit pause as separate existing semantics. Define
    override behavior on Stop, concurrent edits, restart, disconnect, stale prices,
    missing SOC, unknown upload outcome and charger/vehicle authorization without
    weakening interlocks or automatically retrying uncertain writes. A schedule does
    not itself authorize a transaction or prove physical flow.
  - Use focused mocked actual-module tests for expiry, early cancellation, an active
    automatic window, changed plans, offline/reconnect, unknown outcomes, price/cap
    basis, selected durations, charger limits and concurrent Stop/pause. No live
    operation is authorized by these tests.
- [ ] **10.2 Dashboard controls and post-install review**
  - Add one **Charge Now** control with duration choices to the existing sidebar;
    while active, the same control becomes **Return to Auto**. The other daily
    control is **Pause / Resume Auto** from 5.6b, not an extra cancellation button.
    Show override status/end, cap implications,
    proposal versus sent/readback versus measured state, and explicitly explain that
    cancelling may leave charging active if the automatic plan selects now.
    The exact interaction of pressing Charge Now while explicitly paused still
    needs the user's decision; do not silently override a person Stop/pause.
  - Test desktop/mobile interaction, confirmation, permission, race, stale and
    unavailable states, and document the user-directed procedure. Show failed or
    unknown schedule updates as unconfirmed, not as proof that charging stopped.
    Any later deployment, restart, profile operation or physical test requires the
    user's specific approval; do not claim mocked checks verify live behavior.

### Stage 11 — Adaptive charging estimates for Morek

The user wants charging-time and target-SOC estimates to improve from actual
charging and to replan when a car falls behind. Existing `planning/learned_power.py`,
`planning/learned_energy.py` and `planning/plan_watch.py` provide learning and
behind-plan groundwork for the existing Auto path; **their operation with Morek
schedule ownership and this installation's measurements is not yet verified**.
Reuse them where suitable, not a new AI or duplicate learning system. This is later
work, not a prerequisite for 5.8; Stage 6's verified source inventory can inform it.
The BMW's own configured limit stops charging at the car's target; these estimates
and progress checks do not replace or prove that separate vehicle setting.

- [ ] **11.1 Verify and connect measured learning**
  - Inspect how the existing samplers receive genuine charger power/energy and fresh
    vehicle SOC, identify whether the Morek-owned path feeds them, and extend the
    smallest existing seam if necessary. Use trustworthy measured sources and vehicle
    association, with coverage and freshness; do not learn from scheduled current,
    profile ACK/readback, estimated SOC presented as measured, or missing data.
  - Reuse existing sample-quality, trust, bounds and persistence rules where suitable.
    Until sufficient trustworthy evidence exists, retain the normal estimates and
    show that learned values are unavailable rather than inventing a result.
- [ ] **11.2 Use learned estimates and replan safely**
  - Verify and, where needed, connect learned actual power and wall energy per SOC
    percentage to the Morek planner, so a slower-than-expected charge can receive
    more time within available windows and the configured deadline. Reuse the
    existing behind-plan checks to trigger a fresh plan when reliable observations
    show a shortfall; reconcile only through the same guarded schedule owner.
  - Respect Pause/Stop, price and minimum-SOC policy, unavailable inputs, charger
    limits and unknown write outcomes. Report when the target is infeasible; never
    promise it will be reached or claim the car is charging based on a schedule.
  - Test reliable and insufficient samples, incorrect initial estimates, slow or
    interrupted charging, stale readings, restart, vehicle changes and safe replans
    with mocked boundaries. Deployed testing remains the user's decision.

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

- **One charging dashboard in a Home Assistant custom sidebar panel.** Use the same
  UI code in the local sample preview and HA, with different data adapters. Existing
  card compatibility may remain but is not a second required daily interface.
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

## 2. Historical manual baseline, not the finished product

The baseline below describes **2.5.7**, not the current implementation. The local
manifest was 2.5.44 during this roadmap review; check Git and the handoff for ongoing
uncommitted work. Source, installed HA version and charger state are separate facts.

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

- Do not implement household load balancing or dynamic amp changes in SpotNav's
  Morek schedule-only mode. The user reports that Morek handles protection natively;
  this report is not independent verification of the installation. Do not disable
  existing protection, raise electrical limits or assume that gating a software
  actuator leaves equivalent protection. Resolve any actual dependency or conflict
  before activation, without implementing a replacement load-management system.
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

Deliver a short implementation map listing every writer and where Morek ownership
guards belong. Specify migration to the single schedule owner, what may remain
stored on the charger, and what must be approved before hardware testing.

**Done when:** there is an explicit ownership/transition design, an authorization
plan, and a test matrix showing how conflicting writes will be detected.
No live commands, mode changes or file deployment are needed for this audit.

### A2 — Enforce exclusive schedule-only mode

Use a single schedule execution path for the supported Morek connector with safe
migration from the current manual experiment. Do not silently arm unsafe control
on an integration update. Legacy live execution cannot also own that connector;
retain shared legacy support for other chargers and the ownership safeguards.

Keep **disable the integration**, **pause charging**, and **remove stored schedule**
distinct: disabling SpotNav may leave a profile installed, and removing a 0 A limit
may allow charging. Pause and Charge Now use the same schedule owner, never a hidden
return to legacy RemoteStart/RemoteStop. No runtime switch back is required.

**Done when:** automated tests prove that all applicable legacy writers emit no
conflicting commands in Morek mode, including at scheduled boundaries and reload.
Read-only diagnostics and independent protections still work. Migration and any
known or uncertain retained limits are explicit to the operator.

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

Use the HA custom sidebar panel as the intended responsive host; Sections references
in historical notes are superseded. Bundle ECharts locally with
licence/notice files; load heavy chart code only where needed. Start with Web Awesome
**Core** as the primary library for polished ready-made controls, rather than styling
all controls from scratch. Verify the selected package version, licence, bundled assets,
theme integration, dialogs/popovers, responsive behavior and compatibility with the HA
panel host. HA-native components may be used selectively where appropriate; avoid
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

**Done when:** essential interactions are usable, axes/units are clear,
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

Keep the dashboard practically usable on desktop and mobile, with readable warnings
and essential controls. Separate theme modes and extra accessibility polish are not
required. Avoid CSS overrides depending on another card's private DOM. Reuse the
Stage 5 installation guidance without overwriting the user's HA views; update it
only where a real gap is found.

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
  policy, charging pause/boost behavior and safe retained-profile migration must be resolved in
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
