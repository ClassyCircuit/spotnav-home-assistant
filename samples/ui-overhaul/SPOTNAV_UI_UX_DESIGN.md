# SpotNav Enhanced — UI/UX Design System and Implementation Handoff

**Edition:** 1.0 · 18 November 2026  
**Deliverable:** Design direction + implementation guidance, **not** a scheduling specification  
**Product surface:** SpotNav Enhanced, a Home Assistant sidebar integration with a custom panel  
**Primary reference:** `demo/spotnav-pulse-v4-interactive.html` (unchanged, self-contained fictional-data interactive prototype)  
**Visual references:** `reference/spotnav-pulse-v4-desktop.png`, `reference/spotnav-pulse-v4-mobile.png`, `reference/approved-overview-concept.png`  
**Historical technical reference:** `source-audit/spotnav-ui-source-audit-2026.md` (source snapshot at `c720947b`, manifest `2.5.178`, **not a current contract**)

> **Read this first — the critical boundary.** The screenshots and demo are design references. They do not define the product's current charging rules, prices, schedule computation, OCPP operation, retry logic, freshness thresholds, permissions or WebSocket contracts. The development repository and its current tests are the authority. Scheduling and execution bugs have been fixed since the supplied audit/prototypes were prepared. Do **not** port the demo's fabricated charging state, sample time windows, guards, chart data or action logic into production. Reuse the real backend, current frontend service adapters and existing safety logic. This project is a **UI/UX redesign**, not a rewrite of smart charging.

---

## 1. The intended product and the feeling it should create

A premium, information-rich **energy cockpit**: a beautiful, immediately legible overview of a car's charging state, tariff environment, chosen future windows, predicted cost and actual charger evidence. It should look commercial-quality while still serving a technically demanding owner.

**Not** a generic Home Assistant Lovelace card, not a pared-back mobile app hiding all data, and not a wall of automation diagnostics. The correct model is **progressive depth, not aggressive simplification**. High-value facts appear together on one screen; less frequent but consequential details are one interaction away.

The interface should enable these glance-level answers in approximately 3 seconds:

1. Is energy **measured flowing**, or is the car simply connected / waiting / paused / unknown?
2. Where is the battery now, where is the planning target, and by when do we want it?
3. When is the next **proposed** charging window, and what are **all** selected windows?
4. Why did the planner choose these hours: what do hourly/15-minute market prices look like?
5. What is the cost outlook, and what is merely estimated rather than observed?
6. Is the schedule only proposed, acknowledged by the charger, read back, attached to a session, or backed by measured power?

The first answer should be obvious from the car illustration, state headline and measured-power metric. The full schedule should be visible in a clearly defined list—not available *only* by inspecting chart bars.

### Emotional and visual objectives

- **Premium and distinctive:** cinematic white BMW iX3 scene with realistic Morek wallbox, deep midnight-blue background, controlled colored highlights and finely layered cards.
- **Energetic but not monochromatic:** turquoise/mint for appropriate active/reassuring details, cool blue for structure, orange/amber for price/time context, coral/red for expensive price regions or actual faults **with different semantics**, and white for critical readings.
- **Dense but not busy:** concise copy, strong numeric hierarchy, compact icon + label groupings, generous spacing between major areas, tighter spacing *within* a data group.
- **Credible:** all confidence, source, timestamp, estimate and exception language matches the backend's actual evidence.
- **Calm:** no gratuitous flashing or pulsing in a dashboard that may stay open for hours.

### What to retain from v4

The product direction, primary Overview layout, cinematic car illustration, battery-over-car presentation, saturated multi-hue pricing chart, crisp right-side strategy / price / system / freshness cards, action/dialog patterns, and genuinely interactive elements. The older screenshot-slice/hotspot experiment is **not** a suitable implementation reference. v4 is the functional design reference, though it is still a throwaway mock, not production source.

### What not to copy uncritically

- Specific dates, 64% SOC, 80% target, 00:15 next slot, 7:30 deadline, 15 c/kWh cap, €1.56 forecast, 3-phase/16 A, power and price values. All are **fictional demo values**.
- The demo's assumptions about plan timing, whether a window is active, price forecasts, measured charging, schedule acceptance, permissions or action eligibility.
- UI mock actions that modify local JavaScript state rather than calling the real HA WebSocket API.
- The demo's simplistic generation of windows, colored bars, cumulative values, or any hypothetical optimization logic.
- Demo-only Home Assistant left rail on a real HA sidebar route: Home Assistant already owns global navigation; avoid a **double sidebar**.
- All screen/element labels literally, particularly wherever the sample uses a confidence claim. Improve semantic truth even when it means replacing the sample copy.

---

## 2. Scope and boundaries

**In scope now:** refresh the **Overview** of the existing SpotNav Enhanced sidebar panel; integrate a prominent **Planned charging windows** section; establish reusable UI tokens/components; keep existing interactions and safety behavior working; preserve live/preview parity. Minor host-shell refactoring is acceptable where needed to eliminate duplicate banners or mount the new Overview cleanly.

**Out of scope for the initial UI pass:** redesigning the existing Explore, History and Settings views; implementing new plan/schedule algorithms; changing Morek/OCPP ownership and authorization; introducing new retry/recovery behavior; adding new backend endpoints merely to match mock visuals; replacing historical-cost or savings calculations; moving unrelated HA functionality into SpotNav; rebuilding the legacy Lovelace card.

**Backend policy:** preserve current HA WebSocket commands, serialized data and authorization. A presentation-oriented selector/adapter may derive **display state only**, without affecting business decisions. If the desired UI needs data that isn't available, use an honest fallback or investigate with the maintainer. Never fake it or infer physical charger state from a proposal.

### Current-source verification before coding

The historical audit was based on commit `c720947b`, version `2.5.178`. Before implementation, the agent **must** inspect the current repository:

- `AGENTS.md` and current project/roadmap/handoff docs;
- `frontend/sidebar/panel.js`, `frontend/sidebar/adapter.js`, related state/action controllers;
- `frontend/shared-dashboard/dashboard.js`, view code, renderer/reconciler and CSS;
- `frontend/src/api.ts`, `frontend/src/validate.ts`, `frontend/src/morek-view.ts` or present equivalents;
- current serializers/handlers of `get_dashboard`, `morek_schedule status`, settings, history, prices;
- all current safety tests, especially around Pause/Resume, Charge Now, ownership, uncertain outcomes and schedule confirmation.

Then explicitly record **where current behavior differs from the historical audit**. Current code and tests win. A demo screenshot never wins an API-semantic disagreement.

---

## 3. Design principles — rules for future extensions

Use these rules when new data cards, actions, states or settings appear later. A coherent design system is more important than pixel-perfect imitation of any mock.

### P1. Organize by user questions, not backend modules

Top priority: **physical situation → plan → reason/cost → confidence → history**. Do not arrange the homepage around serializer objects or integration modules. Each card must answer a question; if it cannot, consider folding it into another card or placing it in a deeper view.

### P2. One fact has one canonical detailed home

A value may appear in compact contexts (e.g., next window on hero, highlighted in chart, present in schedule list), but only one place is the canonical detailed explanation. Repeated surfaces must be synchronized from the same view model and **must not contradict**. Do not repeat entire plan lists in multiple cards.

### P3. Visual encoding first; accurate words second

Use shapes, position, bright numbers, iconography and small animations to reduce *reading*. Never remove essential labels or rely on icons alone to explain ambiguous states. A user's first glance should work without opening a drawer, while the second glance should reveal exact definitions and provenance.

### P4. Separate intent, evidence, and reality

The system can calculate a future schedule without sending it; a charger can acknowledge a profile without applying it; readback can match while power is zero; a transaction needn't prove energy flow. Always keep these distinct. Render confidence as explicit words or distinct statuses, not as a continuous green "everything executed" progress bar.

### P5. Difference between zero, missing and stale is visible

`0.0 kW measured` is not the same as `Power unavailable`. `No selected windows` is not the same as `Could not load plan`. Unknown SOC must not become 0%. A stale value must be marked or suppressed according to the current data-quality logic. Provide a last-known timestamp where genuinely available.

### P6. Color is semantic, but not exclusive

Color reinforces information and price magnitude; never encodes the *only* meaning. Market-price coloring and charger-health coloring are separate conceptual systems. A red price bar does not mean charger error. An amber clock on a scheduled wait does not imply failure.

### P7. Interaction never lies

Buttons should show whether a command is **requested, accepted, observed, rejected or outcome-unknown** as supported by backend data. Unknown effect is not equivalent to failure. Never offer naive resend after a timeout or show a triumphant "Charging" status after a request ACK.

### P8. Detail on demand, but not hidden by default

Always show the battery, schedule, current price context, selected windows, cost outlook and compact technical telemetry. Morek readback, ownership ticket, mismatch reasons, session reconciliation and maintenance tools can open in the evidence drawer. Hiding *all* technical details is not the goal.

### P9. Every component must survive refresh and variable data

No hardcoded 24-hour day, two windows, one vehicle, one price source, fixed row height or a never-changing set of permissions. Preserve user interaction state during live refresh; account for DST, unpublished prices, stale responses, and plan updates.

### P10. Aesthetic fidelity comes from component discipline

Use consistent tokens for background, border, radius, type scale, spacing, icon strokes, motion and card structure. New components should inherit those tokens rather than inventing fresh colors or random glow effects.

### P11. HA-native without looking generic

Respect the host panel lifecycle, HA auth/theme/context, narrow sidebar width, safe-area insets and Shadow DOM. The rendered SpotNav dashboard should be visually distinctive, but not duplicate HA's global navigation or override the host's security/accessibility expectations.

### P12. Readability outranks ornamental accuracy

A slightly adapted responsive layout is better than a pixel-perfect desktop screenshot scaled down until text is illegible. Meet contrast and touch-target requirements and avoid full-screen saturation filters or low-opacity text.

---

## 4. Overview information architecture and placement

**Recommended desktop composition:** keep the v4 hierarchy, add the missing windows list after the main chart, and avoid forcing the entire page into a fixed viewport. Scrolling is normal for analytic detail; the above-the-fold area remains highly informative.

```text
[ SpotNav title / context ]                              [charger] [health] [refresh]

┌────────────────────────────────────────────────────┐ ┌──────────────────────────┐
│ CINEMATIC VEHICLE HERO                             │ │ CHARGING STRATEGY        │
│  State + one short explanation     Next window     │ │ target · ready-by        │
│                                                    │ │ price cap · 3φ/16A       │
│  White BMW iX3    overlay SOC + target             │ └──────────────────────────┘
│  charging port / wallbox / cable (photo scene)     │ ┌──────────────────────────┐
│                                                    │ │ PRICE PERSPECTIVE        │
│  Power · To target · Time · Forecast cost · actions│ │ Current vs planned avg    │
└────────────────────────────────────────────────────┘ └──────────────────────────┘
┌────────────────────────────────────────────────────┐ ┌──────────────────────────┐
│ ELECTRICITY PRICES & CHARGING PLAN                 │ │ CHARGING SYSTEM          │
│ raw spot-price bars · now · cap · selected windows │ │ compact evidence cells   │
│ chart tools · hover/tap price + plan details       │ └──────────────────────────┘
└────────────────────────────────────────────────────┘ ┌──────────────────────────┐
┌────────────────────────────────────────────────────┐ │ DATA FRESHNESS           │
│ PLANNED CHARGING WINDOWS  (NEW)                    │ │ by source, not one clock │
│  #   time          duration   energy   price/cost │ └──────────────────────────┘
│  01  00:15–01:00   45 min      ...      ...       │
│  02  02:15–03:00   45 min      ...      ...       │
│  ... all available windows; provisional labels   │
│  totals / feasibility / coverage at bottom         │
└────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────┐
│ RECENT CHARGING                                    │
│ last observed session, energy basis and spot cost  │
└────────────────────────────────────────────────────┘
```

**Card placement is a suggestion, not a rigid grid map.** On 1400–1600px screens: left column about 65%, right 35%; gap ~14–18px. Let card height reflect its content; don't stretch strategy to match an unrelated tall card with empty space. For 800–1100px, use flexible wrapping and move right-column cards beneath/alongside the chart. For phones, prefer this order:

1. Compact hero with car, state, prominent SOC, next window and key actions.
2. Price/plan chart (still early and substantial).
3. **Planned charging windows list** (all rows; optimized for phone scanning).
4. Strategy and price perspective.
5. System evidence and source freshness.
6. Recent charging.

Avoid a second standalone app navigation drawer inside the HA shell. Internal view navigation, if retained from current code, should be unobtrusive and consistent with existing app patterns. During this phase the other views should remain functionally unchanged.

---

## 5. Vehicle hero: cinematic without turning into a screenshot

### Layer architecture

1. **Photographic/art layer:** a realistic white BMW iX3 (2022 style), right-side charging port on the visible rear quarter, wall-mounted Morek charger, credible cable routing, modern dark garage lighting. The reference asset is illustrative and may not exactly match the real physical installation.
2. **Legibility layer:** subtle local gradient behind text and bottom metrics; do **not** place a full-page gray/dark opacity filter over the car or whole dashboard. Preserve bright white paint, amber lamps, cool blue shadows and rich garden accents.
3. **HTML semantic UI:** headline and subline at upper-left, proposed next window upper-right, transparent battery overlay centered over *usable dark vehicle area*, small connection indicator, bottom data strip and action buttons. **Not** baked into the photo.
4. **Optional state layer:** charger LED, port ring, cable pulses/energy motes only when measurement confirms real flow. The real photo cable can remain as static geometry; overlays must align with its actual routing. If an accurate cable animation cannot be made, omit motion rather than draw a misleading simplistic beam.

Do **not** simulate real plug connection on a photograph that visibly shows a plugged cable for an `unplugged` state. Use separate state-appropriate artwork, mask/remove the cable reliably, or show a neutral crop with clear textual state. Never silently leave an always-plugged cable visible while saying "Unplugged".

### Hierarchy and labels

- Upper-left: state micro-label (e.g., `SCHEDULED`) + **one** natural-language headline (`Waiting for cheaper electricity`), optional 1-line explanation.
- Upper-right: `NEXT PROPOSED WINDOW` + date/time in selected timezone. If only a proposal exists, don't call it `Confirmed start`. If none, show an explicit reason: no energy needed, no plan, unpublished prices, unavailable.
- Mid-scene overlay: large **current SOC** (`64%` as fictional sample), a clean 8–12-segment or continuous low-profile meter, target marker/annotation, last-source note. Avoid the old opaque battery block hiding the vehicle; use transparent/low-contrast underlay or carefully placed text shadow.
- Bottom strip: **Measured power**, **To target**, **Planned time** (label must match meaning), **Estimated plan cost** (with cost basis), then primary/secondary actions. Show 0 only when *measured* zero is fresh; suppress projected timing if not knowable. A user should not see a contradictory `Active charging` subtitle while actual charging is 0 and state is `Waiting`.

### States and honest animation

| Physical / control situation | Main visualization | Motion / explanation |
|---|---|---|
| Unplugged, fresh evidence | no plugged cable (if graphic supports), neutral wallbox light | static; "Not plugged in" |
| Plugged, idle without a proposed window | cable connected, steady neutral LED | static; plan state explicit |
| Waiting by selected schedule | cable connected, calm wallbox, clock / next slot | static; no energy particles |
| Measured charging now | measured kW prominent; subtle flowing light along real cable path | only with fresh measured power/current evidence from current code |
| Charger says Charging, measurement unavailable/zero | reported status visibly qualified | **no** measured-flow animation |
| Starting/request accepted | small activity indicator on state chip | no implied electricity flow |
| Paused by person | pause symbol, persistent hold label | static; pause intent vs effect separated |
| Finished | check / completion style, actual SOC if available | don't draw "100%" unless real |
| Offline / stale / uncertain | clear uncertainty treatment; retain last-known with timestamp | muted affected sensor, not whole dashboard desaturated |
| Actual fault / action needed | localized amber/red icon + explanation + owner of next step | no generic retry or fake repair button |

**Motion specification:** transitions 150–250ms; very slow ambient energy-travel motion only for confirmed flow; respect `prefers-reduced-motion`; avoid DOM replacement that restarts animation every 30s. Do not interpolate SOC forward as if it were a charging simulation.

---

## 6. Prices and plan chart

Keep the chart prominent and richly colored. It answers *why* the schedule exists, while the list below answers *exactly which times* are planned. They must remain synchronized.

### Visual anatomy

- Chart title `Electricity prices & charging plan`.
- Date selector `Today / Tomorrow / 7 days` or existing bounded date navigation; use data actually fetched by existing APIs and show partial/unavailable days.
- Price columns or stepped plot; deep crimson/coral for high market prices, orange around medium, cyan/green for lower **market prices**; avoid applying green to every UI element.
- Current-time vertical marker, price-cap line when semantically comparable and revision-valid, exact X-axis times, readable Y-axis units (`c/kWh`) and chart legend.
- Planned windows encoded distinctly (prefer bottom rail, band, hatch or overlay) so "cheap price" and "selected to charge" are not identical concepts. Never use the same undifferentiated green fill for both.
- On hover/tap/keyboard focus, show precise market-local time interval, raw spot price, selected/not selected, and estimated energy/cost only when supported by the planner data. Source freshness and price basis available via small info control.
- Chart and schedule-list selection shared: selecting a bar or window highlights the corresponding list row and timeline span. Selecting a list row scrolls or focuses the chart span **without sending a charger command**. User can clear the selection without losing zoom or day context.

### Semantics / precision

- Honor published market intervals' actual resolution (e.g. 15-minute intervals); do not fabricate slots or average away granularity without an explicit aggregate mode.
- The audited chart uses `prices.published_intervals[].raw_price` for spot-price coloring; current producers must be rechecked. `prices.intervals[].effective_price` is a **different unit** (hundredths of major unit/kWh in the audit) and a different price basis. Never mix or relabel them. Require currency/FX validity.
- If retaining the audit's price bands, treat them as **display-only absolute EUR c/kWh bands** (<8, 8–<15, 15–25 inclusive, >25), not economic truth or a controller cap. Revalidate current product configuration. The gradient visually interpolates; the actual classification and labels should be explicit in the tooltip.
- The cap may be based on Nord Pool or configured variable cost; only show a directly comparable line after verifying cap basis and settings revision. Otherwise annotate or hide it rather than draw a misleading line.
- Preserve market-zone day boundaries and DST (23/25-hour days), while session history uses HA-local time. Don't assume 96 slots/day or 24 hours/day. Show ambiguous local times with UTC offset if needed.
- Unpublished future prices should show gaps or pending coverage, **never guessed prices, zero bars or invented chart heights**.
- Plan proposal is not an applied charger schedule. Source and freshness badges should follow current backend state.

---

## 7. NEW: Planned charging windows — first-class Overview card

### The problem this solves

The chart makes the *distribution* obvious but doesn't let the user reliably scan exact start/end times, durations, cost or energy, especially on mobile. A separate, polished schedule list should provide a precise, immediately actionable reading of the **planner's current proposal**. **This is the principal new component requested for implementation.** It is **not** an editor of individual windows and must not drive the scheduling algorithm.

### Recommended card design

**Title:** `Planned charging windows` with a small `Proposed` / `Partially priced` / `Historical` / `Outdated` indicator and a total such as `3 windows`.  
**Subheading:** `Selected by SpotNav for your 80% target · ready by 07:30` **only if those fields are genuinely valid**. Otherwise state exactly which constraints are known.  
**Header utilities:** `View on chart` and optional `Plan details` (opens existing detail view/drawer). A refresh icon may read fresh observations; it must not secretly replan.

**Desktop visualization:** rows that resemble premium itinerary/energy entries, not a spreadsheet dump. Each row has an ordinal, a small vertical time rail or interval mini-bar, strongly set start–end times, supporting date if needed, duration, approximate energy, average price, projected cost, and a subtle state label. A thin, price-colored side accent references price quality but **must not indicate charger execution confidence**. Use understated row separators and modest hover fill; avoid many full-color badges.

Example (numbers below are **purely schematic; not computed or copied to production**):

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Planned charging windows             3 windows  ·  Proposal · 15-minute data│
│ Target 80% · Ready by 07:30                   [View on chart] [Plan details] │
├─────┬─────────────────┬─────────┬──────────┬────────────┬─────────────────┤
│ 01  │ 00:15 → 01:00   │ 45 min  │ 8.3 kWh  │ 5.1 c/kWh  │ €0.42 estimated │
│     │ Fri 20 Nov      │         │ forecast │ avg. spot  │ plan basis*     │
├─────┼─────────────────┼─────────┼──────────┼────────────┼─────────────────┤
│ 02  │ 02:15 → 02:45   │ 30 min  │ 5.5 kWh  │ 6.0 c/kWh  │ €0.37 estimated │
│     │ Fri 20 Nov      │         │ forecast │ avg. spot  │ plan basis*     │
├─────┼─────────────────┼─────────┼──────────┼────────────┼─────────────────┤
│ 03  │ 04:00 → 04:15   │ 15 min  │ 2.7 kWh  │ 7.2 c/kWh  │ €0.22 estimated │
├─────┴─────────────────┴─────────┴──────────┴────────────┴─────────────────┤
│ Planned energy: 16.5 kWh  · Selected time: 1h 30m · Estimate: €1.01*      │
│ * Price basis / energy estimate / coverage explicitly indicated.          │
└─────────────────────────────────────────────────────────────────────────────┘
```

Do **not** derive cost by multiplying the *display-rounded* average spot price by the energy. Use the backend-provided window estimate if available, with its proper **cost basis**, otherwise leave it unavailable. The example deliberately illustrates the need to label spot averages and variable-cost forecasts separately; it is not a verified accounting example.

### Suggested row anatomy

- **Sequence** `01`, `02`, … — stable in the currently displayed proposal; not a backend period identifier.
- **Interval** e.g., `00:15–01:00`, *and date when cross-midnight or multiple dates*. Display date/offset carefully on DST transition days.
- **Duration** from actual interval timestamps; include reserved/allowance time only if backend explicitly expresses it, and name it separately.
- **Energy** only when present in `window_details` / proposal under a known estimate meaning; else `—` with reason via tooltip. Never invent kWh from current + duration if the planner hasn't supplied a valid estimate.
- **Average price** optional, based on correct interval weighting and backend/provider source. If the backend has no reliable window-level average, do **not** compute with an unqualified formula. Display `—` or an exact observed value with `Spot`/`Variable` basis.
- **Estimated cost** only from valid backend window cost with currency/basis. If no per-window estimate exists, show total plan estimate only and leave row cost absent.
- **Exceptional marker** `Partially priced`, `Above preference`, `Reserve allowance`, `Goal shortfall`, etc., **only** if supported by current reason codes. Avoid drawing a green checkmark because the window was selected.
- **Linked location** date/span highlight in chart; row click is read-only inspection.

### Summary/footer

Summary should show **total selected duration**, **planned kWh**, **plan estimate** and a compact feasibility note (`Expected to meet target`, `Target may not be reached`, `Awaiting price publication`, `No charging necessary`) only where the planner provides authoritative supporting data. Never sum incompatible estimates or reuse history totals. When individual costs are incomplete, do not fabricate a complete total. State partial coverage explicitly.

### Rendering logic and ownership

- Canonical source of truth is the **current validated plan proposal** (`plan.proposal.periods`, `window_details`, proposal metadata, current policy/revision), or the current equivalent in the active repository. Reuse its serializer/decoder and any existing plan-row builder; inspect field semantics. Do **not** recompute, optimize, merge, split or shift windows in the UI.
- Show exactly **all proposal windows** returned, including a proposal with 0 or 8 windows; don't cap to the two windows shown in the demo screenshot. If the backend returns extra rows beyond a reasonable visual threshold, prefer an in-card scroll region with a clear row count or expand toggle; do not silently truncate.
- A `proposal` row must remain labeled proposal even if a separately rendered Morek verification card says readback matches a schedule. If current backend can safely correlate identities, the card header may add a separate confirmation indicator; never join by time alone.
- The selected price day may differ from the full plan horizon: the window list defaults to **entire relevant proposal horizon**, not just currently visible chart day. If a selected row falls on another price day, explicitly offer to jump to that day.
- A 30-second refresh may update the proposal while the user is inspecting a row. Preserve selection by stable proposal identity + interval when possible; if the schedule changes, clear the stale selection with a subtle message instead of selecting the wrong row.

### Phone design

Use one responsive card per window, never a seven-column compressed table:

```text
01   Fri 20 Nov                  45 min
     00:15 ━━━━━━━━━ 01:00      proposed
     8.3 kWh est.   5.1 c/kWh spot   €0.42 est.*
```

Wrap fields gracefully; maintain 44px+ touch targets. Avoid horizontally scrolling the whole page. If many rows, use an explicit `Show all 8 windows` action **within** this card while keeping every row accessible (not hidden in a different tab). The chart remains above this list on mobile.

### Crucial states for the new component

| Situation | UI treatment |
|---|---|
| Fresh proposal, 1+ windows | All time rows, forecast fields if valid, `Proposed` badge |
| Fresh proposal, zero windows because no energy required | Friendly `No charging needed for this target` with source-backed reason; never `Error` |
| Zero windows because cap/feasibility constraints | Concise explanation with planner's actual limitation code; not "no charging needed" |
| Awaiting tomorrow's prices / partial coverage | Show known windows; label proposal incomplete/provisional if backend says so; unpriced intervals left unknown |
| Older/stale proposal | Visible stale label, suppress misleading forecasts or mark as last-known as current app does |
| Morek sent / ACK only | Proposal list unchanged; separate evidence strip says `Acknowledged` not effective |
| Effective readback differs | Proposal list remains the proposal; relevant warning in system card, not windows silently altered |
| Physical charging occurs outside plan | Don't rewrite proposal; measured/history view explains the discrepancy |
| Current planner indicates no plan available | `Plan unavailable` with reason and refresh observation action (read only) |
| Another vehicle/charger selected | Correct charger-specific rows after identity switch; no data bleed |
| Price route/currency or settings revision changes | Avoid old price/cost labels; respect existing revision/freshness validation |
| DST boundary | Correct local date, offset if ambiguous, real elapsed duration and correct slot count |

### Acceptance criteria for schedule card

1. Each row represents a validated current backend proposal window, with unchanged start/end and order.  
2. The number of visible rows equals the actual count (except an explicitly expanded in-card presentation).  
3. Chart highlights and list rows reference the same proposal identity; all clicks are **read-only**.  
4. Zero, null, stale, incomplete, expired and missing values remain semantically distinct.  
5. Cost and price labels show the correct original units, currency, basis and estimation status.  
6. Mobile is readable with 360px width and does not require horizontal page scrolling.  
7. Switching chargers clears data from the old charger until new context is safely loaded.  
8. No additional plan calculation, OCPP command, settings write or automatic resend occurs while viewing the list.

---

## 8. Right-side compact intelligence cards

### Charging strategy

This is a **summary**, not a second plan editor. A small mode chip (`Automatic`), explanatory strategy (`Lowest-cost windows` if the current strategy actually means that), and a 2×2 grid of compact fact tiles: target, deadline, soft cap, charging current/phases. Make admin-specific values read-only with a truthful label. `Edit` opens current authorized settings surface; never invent a new unsafe global save.

### Price perspective

Strong numerical contrast between current raw spot price and selected-window average **when both are valid and comparable**. Use a horizontal divider and a small delta arrow/pill (e.g., `72% below current`) but label it explicitly as **price comparison, not actual realized savings**. Do not display such a percentage with unknown prices, different cost bases, missing FX or a zero/invalid denominator. Prefer backend price-insights for longer-term percentiles where available.

### Charging system

Compact five logical evidence indicators: `Plan`, `Sent/ACK`, `Readback`, `Transaction`, `Measured power`. Their exact mapping must use **current** serializers; status is not an ordered workflow checklist. Use `Present / Pending / Unknown / Not applicable / Differs / Confirmed` depending on evidence. A healthy readback with measured 0kW may be completely normal during a scheduled wait. Selecting it opens a technical drawer with identity, timestamps, ownership, verification reason and appropriate next actor.

### Data freshness

A compact list of BMW SOC, Morek observations, market data and schedule calculation/readback. Each has its **own** source timestamp and quality. A fresh request from HA does not turn a four-minute-old BMW reading into fresh data. The numeric age should be sourced/calculated from a trustworthy observation timestamp; unknown age is `Time unavailable`, not `just now`. When any source is stale, indicate it locally without darkening every card.

---

## 9. Interaction patterns and state feedback

### Actions

- **Charge Now**: strong green primary button only where current guard permits; opens confirmation with **absolute end time**, optional duration, price-vs-cap warning when reliable, and explanation that acknowledgement does not prove current flow. Use current `morek_schedule` path and current confirm/reconcile guards.
- **Pause automatic / Resume automatic**: secondary control with persistent intent semantics; don't label a request as physically completed until supported by fresh confirmation.
- **Return to Auto**: exits temporary override, not necessarily charging; may allow charging to continue in a current auto window.
- **Refresh**: observation read only; never silently forces sync/replan.
- **Strategy edit**: focused settings drawer, preserved drafts and per-field permissions; saving uses current revision checks and existing write controllers.
- **Schedule-row selection, chart focus, details drawer, date selection**: read-only UI interactions with no side effects on charging.

### Non-happy paths

Keep the existing `busy`, `pending`, `accepted-but-unconfirmed`, `rejected`, `unknown outcome`, `stale`, `conflict`, `forbidden`, `reconcile failed` and `user action needed` distinctions. Do not collapse them into a generic toast. A backend timeout often means the result is **unknown**, not failed. An unknown outcome should retain current action latch/guard behavior rather than enable a reckless repeat click.

### UI copy style

- Make the one-line headline a statement of fact or clearly labeled intent (`Waiting for a selected window`, `Charger reports charging`, `Measured charging at 10.8 kW`).
- Prefer short noun/value combinations in tiles: `Measured power`, `Next proposed`, `Plan estimate`, `Price source`.
- Put the source/uncertainty in a second-line caption, not a buried disclaimer.
- Avoid pseudo-certainty words like `Installed`, `Guaranteed`, `Ready` or `Saved` unless current evidence warrants them.
- If there's a blocker, show **who acts** (`SpotNav will check again` / `Check charger in Morek app`) and **when** if backend supplies this; never promise a new retry not present in current logic.

---

## 10. Design tokens and styling language

Reference look is an **electric-blue midnight cockpit**, not the older muted gray/green template. Values below are suggested **starting tokens derived visually from the approved reference**, not sacred constants. Validate in-browser against both references and adjust for contrast.

| Role | Suggested token | Use |
|---|---|---|
| Global background | `#04111F` / `#061526` | Deep cool navy canvas; no gray veil |
| Card surface | `#0B1E2D` | Primary surface; near-neutral blue-black |
| Raised tile | `#102B3B` | Data tiles and side cards |
| Card border | `#2A4A5C` | Crisp 1px, slight cool tint |
| Primary text | `#F4FAFF` | Strong readability |
| Secondary text | `#B6CEDA` | High enough contrast for meaningful subtext |
| Low-priority labels | `#8CA9B8` | Only for noncritical tiny labels |
| Brand/energy accent | `#16E9A2` | Measured flow, selected action, chart selection (context-specific) |
| Cool detail | `#78C7F2` | Informational accents, icon outlines, calm controls |
| Intentional wait | `#F3C47B` | Scheduled/paused context, not automatic fault |
| Expensive price | `#F14667` | Chart price band, not system error |
| Mid-price | `#F8A45E` | Price band |
| Actual fault | `#FF7C87` | Health/error with supporting copy |
| Focus outline | `#8DE8E5` | Keyboard visibility |

**Color hierarchy:** broad surfaces are dark blue, labels white/cool blue, chart carries multi-color spectrum, green is an accent and **not** the entire palette. A small mint action or charger LED draws attention against dark surfaces. Avoid monotonous green chip backgrounds or large dark overlays that wash out the vehicle photograph.

### Geometry and type

- Typography: Inter-like or reliable system sans; crisp 700–800 heading/primary number weight; medium 500–600 subheads; 400–500 explanatory copy.
- Base desktop scale: 28–32px app title, 23–29px hero state, 18–24px primary metrics, 15–18px card titles, 12–14px body, 11–12px auxiliary labels **only where actually legible**. Never make action-critical content 9px just to fit the screenshot.
- Numerical data: `font-variant-numeric: tabular-nums` for prices, times, percentages and kWh.
- Spacing rhythm: multiples of 4 with common 8/12/16/20/24px groups; distinguish between internal tile density and major-card separation.
- Radius: main panels ~16–20px, tiles ~11–14px, chips ~999px; border 1px; modest inset highlight and shadow.
- Icons: coherent modern 1.7–2px stroke icon set, identical visual weight and consistent semantic mapping. Do not mix emoji, random Unicode glyphs, mismatched icon libraries and photograph-embedded icons. Reuse existing project icon tooling where appropriate.
- Glow and animation: limited to charger LED, real energy flow, chart focus, primary action hover and subtle numeric transitions. Not on every card.
- Backdrop blur only where it creates legibility over the hero photo; don't apply `filter: brightness()` or `opacity` to the *entire dashboard*.

### Microinteraction specs

| Interaction | Target response |
|---|---|
| Button hover/focus | slight surface lift/highlight, ~150ms, no layout shift |
| Chart hover | exact bar highlight + tooltip, within ~100ms |
| Row/chart linkage | shared selection with gentle border/glow ~150ms |
| Drawer enter/exit | 200–260ms with focus management |
| Battery SOC update | brief width/number transition, only on real data change |
| Charger animation | low amplitude, if **measured energy flow** |
| Loading | localized skeleton/progress cue rather than full-screen spinner |

Respect reduced-motion. Do not introduce artificial countdowns that drift from backend timestamps. Use clock labels with local time/zone qualification as needed.

---

## 11. Data, API and frontend view-model architecture

**Never feed the React/JS/DOM renderer raw English strings as its only state source if structured backend reasons exist.** Introduce a presentation adapter that takes current validated API data and outputs typed, evidence-aware **display models**. This is a UI-layer concern, not a new controller.

Suggested *conceptual* types (adapt to current project; not a wire schema):

```ts
type DataQuality = 'fresh' | 'stale' | 'estimated' | 'restored'
  | 'unknown' | 'invalid' | 'unavailable';
type EvidenceStage = 'proposal' | 'sent_ack' | 'effective_readback'
  | 'transaction' | 'measured_flow';
type EvidenceState = 'confirmed' | 'pending' | 'unknown'
  | 'different' | 'not_applicable';

type Observable<T> = {
  value: T | null;
  quality: DataQuality;
  measuredAt: string | null;
  source: string | null;
};

type ProposedWindowVM = {
  key: string;                     // UI-only stable identity
  start: string; end: string;      // real timestamps from current backend
  durationMinutes: number | null; // accurate elapsed duration
  energyKwh: number | null;       // backend-validated proposal estimate only
  avgPrice: number | null;        // only when basis/source is genuinely known
  priceBasis: 'spot' | 'variable' | 'unknown';
  cost: number | null;             // backend-supplied estimate when available
  currency: string | null;
  estimateKind: string | null;     // labels/coverage, not new calculation
  reasonCodes: string[];
};

type OverviewVM = {
  chargingSituation: { kind: string; reason: string | null; whoActs: string | null };
  battery: Observable<number>;   // percent
  measuredPowerW: Observable<number>;
  targetSoc: number | null;      // planning target, NOT vehicle charge limit
  nextProposedWindow: ProposedWindowVM | null;
  proposedWindows: ProposedWindowVM[];
  proposalRevision: string | null;
  proposalQuality: DataQuality;
  evidence: Array<{ stage: EvidenceStage; state: EvidenceState; observedAt: string | null }>;
  // plus current tariff, chart, policy snapshot, history and permissions
};
```

This is an **illustrative frontend-only model**. Names and fields must be reconciled with present production DTOs. DO NOT create missing backend fields or change the wire contract solely to match the example.

### Map visible information to current backend (historical audit as leads only)

| UI destination | Historical source to verify now | Non-negotiable caution |
|---|---|---|
| SOC + provenance | `get_dashboard` `soc`, `soc_observation` | estimated/restored/old cannot masquerade as fresh |
| Plan goal and forecast | settings + `plan.proposal`, `window_details`, `plan.price_policy` | planning target is not vehicle's configured SOC limit |
| NEW windows list | same current proposal/windows model used by chart and plan detail | no frontend replanning or guessed splits |
| Price chart | `prices.published_intervals` / `get_price_days` | correct currency, units, market zone, DST, partial periods |
| Soft cap | settings `soft_price_cap` and `cap_price_basis` | compare only matching basis/revision |
| Charging scene | Morek `status.readiness.live`, connector and session state | ACK/readback/transaction alone != measured flow |
| Evidence strip | Morek `sent/ack`, `effective/verification`, transaction, measured flow | distinct evidence, no invented all-green stepper |
| Morek health | link, ownership, recovery, outcomes, reconciliation | current action guards and person/system responsibility |
| Forecast cost | proposal cost & basis | not equal to observed historical spot cost |
| Recent charging | `get_charging_history`, `get_sessions`, spot_cost | bases/cost coverage and savings context preserved |
| Freshness | each source timestamp and current freshness evaluator | a fresh fetch != fresh sensor |
| Charge Now/Pause | current `morek_schedule`, `manual_action` and UI guards | permission, ownership, uncertain-outcome latch preserved |

**Especially dangerous historical fields:** legacy `plan.installed` is a *legacy controller* schedule, **not** necessarily the effective Morek profile. `charge_progress` in the audit means a passive vehicle-not-requesting-current advisory—not a SOC progress bar. `progress.percent` has ownership-dependent semantics. Do not put any of these in the hero until reverified against real production payloads. No numeric manual SOC entry API existed in the audited sidebar. Verify present code before adding controls.

### Preserve runtime invariants

- Existing WebSocket clients, authentication and backend validation remain authoritative.
- Maintain one live shared UI renderer and matching preview fixtures; move duplicated host-only presentation into the shared layer only without changing state/action semantics.
- Continue using current `update()` reconciliation so 30s polling doesn't reset form drafts, chart zoom, selected day/window, scroll, modal/drawer or focused controls.
- Preserve charger-keyed draft state, permission/generation epochs and cancellation/response handling.
- Never equate a 10-second client timeout with a cancelled server action; keep current unknown-outcome latches.
- Preserve compare-and-set `expected_revision` settings updates and currently allowed/non-admin field subsets.
- History/price navigation is read only and bounded; no passive read should trigger planning or a Morek profile send.
- Escape untrusted strings, use text content or safe templates, and avoid trusting provider descriptions as HTML.

---

## 12. Responsive, accessibility, themes, localization

### Responsive requirements

- Test **360, 375, 390, 414px**, tablet 768/1024px and desktop 1280/1440/1600px (including HA sidebar consuming width).
- No horizontal body scrolling; window cards reflow rather than shrinking fonts to microscopic size.
- Minimum **44×44 CSS px touch hit targets** for actions and chart/row inspection on touch interfaces.
- On mobile: hero photo may crop, but keep BMW and Morek recognizable; battery must not cover the charger port or obscure the entire car. Provide text equivalents if image is hidden/reduced.
- Respect HA safe-area insets and panel width. Do not force a 1586px screenshot ratio or global scaling.

### Accessibility

- Correct button/heading semantics; keyboard reachable chart/list interaction; explicit focus-visible outlines.
- `aria-live` for material state changes but do not announce every 30-second refresh noisily.
- Screen reader description for vehicle image (photo illustrative; live data comes from separate controls).
- Contrast checks in dark mode; use color + shape/label to convey state. Don't make minuscule mint text the only indication of verified execution.
- Reduced-motion support; animations must not be necessary to understand charging.
- Tooltip info accessible by tap and keyboard (not hover only), with escape/close behavior and focus restoration.

### Host theme / language

The historical sidebar enforced `wa-dark`; native HA theme integration was not verified. First implement dark mode faithfully, but use tokens so light theme can be introduced without rewriting components. Don't accidentally apply a dark CSS mode to other HA pages. Plan copy around translation keys and reason codes even if the first implementation is English; the legacy card's nine translations do not imply the sidebar already has working localization.

---

## 13. Implementation strategy for the LLM agent

### Phase 0 — baseline and guard inventory (mandatory)

1. Read current repo `AGENTS.md` and all active safety/architecture docs; identify the actual deployed frontend version/entrypoints.
2. Identify current functional UI tests and build commands; run baseline checks if possible.
3. Inventory the actual `get_dashboard`/Morek status payloads (prefer redacted real samples) and model the proposal, window details, evidence, price bases, freshness, permissions.
4. List current scheduling / execution bugs fixed since the historical audit, without trying to reimplement them. If unknown, treat current code/tests as correct rather than guessing.
5. Record present UI's action admission and timeout/unknown handling; capture screenshots for regression comparison.

### Phase 1 — non-invasive design system

1. Introduce namespaced SpotNav Overview design tokens and consistent SVG icon primitives. Prevent global CSS leakage.
2. Build reusable semantic display components/renderer helpers: `Surface`, `Metric`, `StateChip`, `StatusIcon`, `TimeRange`, `PriceBasisLabel`, `Freshness`, `DataUnavailable`.
3. Preserve existing host, selection, refresh, settings and action controllers; **do not copy demo JavaScript** into them.
4. Make the UI rendering compatible with current preview/live fixture parity.

### Phase 2 — new Overview composition

1. Assemble the car/charger hero with DOM overlays (state, next proposed window, battery, actual measured power, estimates, commands).
2. Bring the real price/plan chart to the prominent position and apply the vibrant price styling; retain existing price-resolution and DST handling.
3. Compose strategy, price perspective, evidence, freshness and recent-session cards without independently recalculating facts.
4. Consolidate duplicated statuses/banners into one primary situation + focused warning. Preserve all blocker states and safe actions.

### Phase 3 — **planned windows list (required)**

1. Reuse the **same** validated proposal windows that feed the chart (single data source).
2. Render all relevant rows with precise interval, duration, forecast metadata and explicit missing/partial states.
3. Synchronize chart hover/selection ↔ list selection; never create side effects.
4. Add correct empty/provisional/stale/DST handling and explicit list summary.
5. Verify chart selected windows and listed windows match precisely across varying schedules and chargers.

### Phase 4 — workflows, parity and polish

1. Bind existing authorized Charge Now/Pause/Resume confirmations and settings editors; preserve current backend permission and unknown-outcome semantics.
2. Keep other views present and working. Do not replace them with a v4 imitation.
3. Verify 30s refresh preserves viewport, selected window, form drafts, dialog, scroll and chart zoom.
4. Add restrained live-motion only with measured-flow evidence; verify safe states don't animate incorrectly.
5. Check accessibility, mobile, status language, price basis, all source dates and error states.

### Phase 5 — regression and delivery

Run project-prescribed build/tests/lint/dist integrity checks. The historical audit mentions `manifest.json` version bump, `npm run build`, `npm run check-dist` and `frontend/sidebar/browser-check.mjs`, but **follow the current repository instructions**, not a stale file. Deliver before/after screenshots for desktop/mobile, a component map, source-of-truth mapping, regression results and a list of unimplemented design ideas.

**Keep PRs/commits reviewable:** separate theme/components, chart/list, hero, and workflow binding where practical; do not mix a UI facelift with Morek planner changes. If unrelated backend defects are discovered, document separately rather than fixing by speculative UI-side logic.

---

## 14. Test matrix and release gates

### Functional safety / evidence

- [ ] Charging animation appears **only** when fresh measured flow supports it.
- [ ] `reported_charging` without usable measurement is correctly qualified; no fake flow.
- [ ] Unknown/missing power is displayed differently from measured 0kW.
- [ ] A proposal, ACK, effective readback and transaction are never described as equivalent.
- [ ] No retry/send/clear/manual-start is introduced by viewing the Overview or schedule list.
- [ ] Pause/Resume/Charge Now/Return retain current guards, confirmations and unknown-outcome latches.
- [ ] Non-admin with plan-changing permissions cannot submit admin-only fields.
- [ ] Revision conflict, permission change and uncertain write results preserve drafts and truthfulness.

### Chart and windows

- [ ] 0, 1, 2, 3, 8+ windows display correctly (no screenshot-specific assumptions).
- [ ] Every window from current proposal appears exactly once and selection matches chart range.
- [ ] A current window can start yesterday/end tomorrow; dates and elapsed duration are accurate.
- [ ] 23- and 25-hour DST days, 15-minute data and partial price publication render truthfully.
- [ ] Price unit conversion, currency and cap-basis rules pass tests.
- [ ] Unknown cost or average price is not replaced with €0 or invented estimates.
- [ ] If plan identity changes, stale row selection doesn't point to a different window.
- [ ] If a chart day differs from schedule horizon, windows are still reachable and clearly dated.

### Visual/UX

- [ ] Screenshots qualitatively resemble the approved **v4** style (bright, blue-dark, vibrant bars, white car) without copying baked-in mock data.
- [ ] Car photo doesn't obscure status/battery/next slot; no opaque battery slab hiding the car.
- [ ] Icons have consistent weight; no emoji fallbacks for important controls.
- [ ] Desktop and mobile maintain scan order; no empty stretched side cards.
- [ ] Right-side cards have distinct roles rather than repeating the hero.
- [ ] No global opacity/brightness veil washes the entire interface out.
- [ ] Usable at 360px; chart/list tooltips work with touch and keyboard.
- [ ] UI retains scroll/draft/chart selection through scheduled data updates.
- [ ] No changes to other app tabs beyond unavoidable shared-shell stability.

### Evidence-backed validation

- [ ] Real redacted status/dashboard payloads or validated fixtures cover at least plugged-wait, charging, paused, reported-but-unmeasured, unplugged, stale, offline, fault, rejected/pending, uncertain outcome and schedule mismatch.
- [ ] All states display **who acts next** when remediation is necessary.
- [ ] No visual status claim exceeds available backend evidence.
- [ ] Debug and admin tools remain appropriately guarded and reachable without flooding the homepage.

---

## 15. Decision rubric for any future screen or component

When a later developer or LLM adds new information, ask in order:

1. **Which user question does this answer?** If none, don't put it on Overview.
2. **Is it current observation, proposal, configuration, estimate, or historical result?** Label that relationship.
3. **How trustworthy/fresh is it?** Show quality or don't show a number.
4. **What's the most scannable visual representation?** Number, tiny chart, rail, row, icon, diagram or one sentence.
5. **Where is the canonical explanation?** Don't duplicate it unnecessarily.
6. **Does this require an action?** Show one safe existing action and who should take it; no invented commands.
7. **How does it behave on a phone, without mouse hover, with unknown data and across refreshes?**
8. **Does it inherit the established tokens and semantic color language?** If not, revise.
9. **Can it mislead about charging, costs, permission or plan confidence?** If yes, weaken the claim.
10. **Is the change isolated to the UI and covered by regression tests?** If no, reconsider scope.

A high-quality SpotNav Overview is not a screenshot recreated pixel by pixel. It is a composable, robust information hierarchy that **continues to look and behave coherent as the backend evolves**.

---

## 16. Open decisions (do not guess)

These are legitimate implementation questions for the agent to resolve from current source or record as explicit limitations:

- Is the current UI's price-chart view already driven by the same normalized `window_details` identity needed for list ↔ chart linkage?
- What exact per-window energy, variable-cost estimate and average-price fields exist in the **current** payload? Which are nullable and for what reasons?
- Do the current Morek schedule-only statuses provide any stable, safe cross-link of proposal identity to ACK/readback identity? If not, keep separate.
- Does current scope require all 15-minute slots, grouped plan windows, or Morek OCPP periods in the list? **Default to proposal windows**; don't silently switch to installed/effective periods.
- Is the real HA timezone the same as the price market timezone? What timestamp conversions already exist?
- How should charger/vehicle selection be surfaced when multiple are configured? Reuse existing selection behavior.
- Does current `users_change_plan` policy differ from the historical audit? Inspect current backend authorization.
- Which cinematic scene asset is safe/appropriate to ship in the custom integration, and do we need a fallback for image failure or custom vehicle type?
- Which current part of the host-only status bar can move into the shared renderer without losing safety/reconciliation behavior?

When evidence is absent, **stop at a safe display fallback** and describe the gap in implementation notes; never fill it with demo-derived pseudo-logic.

---

## 17. Source and prototype authority order

1. **Highest authority:** current repository source, its tests, current operational roadmap/AGENTS, and validated live payloads.
2. **Next:** explicit desired behavior in this design handoff, limited to the UI/UX scope.
3. **Next:** historical source audit (use as navigation map and checklist; re-verify every contract and guard).
4. **Next:** unchanged interactive v4 demo (interaction/aesthetic inspiration, not code or data authority).
5. **Lowest:** approved concept screenshot (visual inspiration, some impossible/schematic details; never source of execution truth).

If these conflict, **preserve current correct charging behavior first**, explain the conflict in the implementation report, and adapt the design instead of regressing the backend.
