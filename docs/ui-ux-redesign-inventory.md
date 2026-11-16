# SpotNav UI/UX redesign — source-grounded inventory

Research input for a complete redesign of the SpotNav Enhanced charging UI. It is an **inventory and design
input**, not a visual design, implementation roadmap or backend proposal. Nothing here changes behaviour.

## 0. Scope, basis and headline findings

| Item | Value |
| --- | --- |
| Source audited | `main` at `c720947b`, `custom_components/spotnav/manifest.json` **2.5.178** (Stage 8 complete locally; tree clean apart from this untracked document; older Stage 16.2 stash untouched) |
| Surface in scope | The **HA sidebar panel** `spotnav-enhanced-panel` (`frontend/sidebar/panel.js`, registered by `custom_components/spotnav/sidebar.py`, `require_admin=False`) rendering the **shared dashboard** (`frontend/shared-dashboard/dashboard.js`, `mountDashboard`) and its **preview twin** (`frontend/prototype/`, same `mountDashboard`, fictional fixtures) |
| Legacy surface | Lovelace card `frontend/src/card.ts` / `card-view.ts` / `editor.ts` → `custom_components/spotnav/www/spotnav-card.js` — noted separately in §2.6; not audited in depth |
| Method | **Source audit only.** Read renderer, adapter, host panel, model and API client source; WebSocket handlers' permission checks; and (second pass) the production serializers that produce every §6 candidate: `api/dashboard.py`, `api/charge_bar.py`, `execution/charge_progress.py`, `execution/morek_session.py`. **No** HA, provider, charger, env/config access; no browser, build or tests. |
| Not verified | Any visual/layout judgement, real mobile/HA theme behaviour, deployed version, live payload shapes. A serializer that *can* emit a field is not proof the installed instance does, and several values depend on Morek ownership (§6). Visual judgements are tagged *(unverified)*. No browser, live or hardware evidence anywhere in this document. |

**Authority of facts.** `AGENTS.md`, `prompts/coordinator-handoff.md` and `docs/charging-dashboard-roadmap-active.md`
§1/§5 fix: schedule-only Morek execution; evidence vocabulary *proposal → sent/ACK → effective readback → transaction →
measured flow* is never blurred; unknown ≠ 0; the BMW's own 80 % stop is an agreed assumption; nothing here is
deployed or physically verified.

### Main UX problems revealed by structure (source evidence)

1. **Controls live in a host bar outside the shared dashboard.** Charger select, Refresh, Pause/Resume Auto, Charge Now, the
   charging-status banner, schedule-check line and recovery banner are built in `SpotnavEnhancedPanel.connectedCallback`
   (`panel.js:122-139`) and `paintSession/paintCheck/paintRecovery`, not in `shared-dashboard/`. The **preview cannot show
   them**, so "same shared live/preview UI" is true only below the host bar.
2. **Six stacked status layers before any card:** `#pause-state` text, `#charge-state` text, `#charge-session` banner,
   `#schedule-check`, `#recovery-banner`, plus `#critical-live` alert. They answer overlapping questions ("will it charge?")
   with different vocabulary and colours (inline styles in `panel.js:337-340`, `:358`, `:368`).
3. **Default view mixes primary and diagnostic content.** Order (`dashboard.js:98-107`): vehicle, plan controls, price
   insights, price/plan chart(s), "Plan activity & freshness" (evidence + `#morek-debug` admin tools), history, then four
   `ADVANCED` accordions. The final cascading CSS sets grid areas `overview controls / history / insights / morek / bar / step`
   (`shared-dashboard/dark.css:38-39`), i.e. the price chart is last on both desktop and mobile *(unverified visually)*.
4. **Same fact repeated in many strings.** Plan estimate appears in the overview metrics, the Plan-controls list, the chart card
   and the modal (`renderPlan` is called 3-4×). Evidence status appears in dialog, evidence card, `#pause-state`, `#charge-state`.
5. **Sentence-shaped state.** Most state is passed as finished English prose (`adapter.js`, `charge-now.js chargeNowStatus`,
   `panel.js paintAutomatic`) rather than structured state; the sidebar is English-only (`translate('en', …)`) though
   `src/i18n/*.json` has nine languages for the legacy card.
6. **Settings are one long form** (`dashboard.js:89-94`): mode, energy, vehicle, target, minimum, cap, cap basis, ready-by,
   reserve plus enable checkboxes and help paragraphs, with a single "Save plan" for all.
7. **Advanced forms are four separately saved accordions** (vehicle sources, market & costs, plan & charger parameters,
   notifications & setup) with their own drafts, reload buttons and notices — each correct, but there is no cross-form summary.
8. **Admin/permission differences are implicit** (disabled controls with a notice) — see §2.5 for the real matrix.

## 1. Information architecture

### 1.1 Default top-to-bottom content (live sidebar)

| # | Region (source) | Content | Default open? |
| --- | --- | --- | --- |
| H | Host bar (`panel.js:125`) | ☰ menu, charger `<select>`, **Refresh observations**, Auto state text + **Pause Auto until resumed** / **Resume Auto**, **Charge Now** (+ "Duration / change end" `<details>`; **Replace Charge Now end** when active) | visible |
| H | `#charge-session` (`chargeSession`) | One-line charging posture + "What SpotNav sees" `<details>` facts | visible when Morek charger |
| H | `#schedule-check` (`scheduleNotes`) | Subdued link/boot/repair note + details | only with fresh status |
| H | `#recovery-banner` (`recoveryBanner`) | Blocker + who acts + next retry | only when a blocker exists |
| H | `.message` | "Select a charger", loading, "Dashboard refresh failed; the last observation may be stale" | transient |
| D | `#critical-live` alert | `m.warning` ("Morek health requires attention") with link to `#details` | when mismatch/uncertain |
| D1 | **Your vehicle** (`overview`) | status dot, SOC bar with target/low markers, SOC provenance line, 4 battery estimates, metrics (measured power, next window, estimated cost, until deadline), policy hint | open |
| D2 | **Plan controls** (`controls`) | settings editor + compact plan list + "View full window details" | open |
| D3 | **Price insights** | live block(s) + month block with pickers | open |
| D4 | **Prices & plan** (stepped area; `comparison:true` adds bars, preview only) | now/next/low/high strip, price-day nav, ECharts, four evidence track lanes, legend, plan list | open |
| D5 | **Plan activity & freshness** | status + 4 evidence cells, dispatch text, `<wa-details id="details">` with admin Morek tools | closed |
| D6 | **Recent charging** (history) | day nav, banners, sent plan/flow, energy bases, spot cost + savings cards, sessions, gaps, month cost | open |
| D7-10 | `ADVANCED`: Vehicle sources & properties; Market & charging costs; Plan & charger parameters; Notifications & setup check | `<details>` forms | closed |
| X | Plan dialog `#plan-dialog` | Complete proposed plan (modal) | on demand |
| X | `log-viewer` (`log-viewer.js`) | SpotNav log tail, polling | **admin only** (`hidden` otherwise) |

Order of D-regions comes from DOM order plus grid areas; see problem 3 above.

### 1.2 Layout, theme, responsive rules

* Sidebar adds class `wa-dark` unconditionally (`panel.js:124`) and ships `shared-dashboard/dark.css`; `styles.css` is a light
  base (`color-scheme:light`). HA theme following is **not implemented** *(unverified in a browser)*.
* One breakpoint, `max-width:800px` (`dark.css`): single column, plan table collapses to two columns, chart height 420-460 px
  (desktop 610), Charge Now block bleeds full width, 44 px minimum tap targets for advanced summaries.
* `handle_safe_area=True` plus `env(safe-area-inset-*)` in host bar. Shadow root isolates styles (`panel.js:125`).
* All dynamic text goes through `escapeText`/`textContent`; no HTML accepted from backend (contract in `shared-dashboard/README.md`).
* Lifecycle contract the redesign must keep: `update()` **reconciles** DOM (`shared-dashboard/reconcile.js`) so dirty inputs,
  open dialog, scroll and chart viewport survive 30 s refreshes; `draftKey` = charger id.

### 1.3 Primary tasks and where they are scattered

| User task | Where it is today |
| --- | --- |
| "Is my car going to charge / is it charging?" | `#charge-session` + `#charge-state` + `#pause-state` + overview "Measured now" + evidence card + recovery banner |
| "When will it charge and what will it cost?" | overview metrics, plan list ×3, chart overlay, modal, Plan-controls list |
| "Charge now / stop / hand back" | host bar only (Charge Now, Pause, Resume, Return to Auto); admin tools in D5 |
| "Change target / ready-by / cap / minimum" | D2 form; vehicle's own properties in D7 (advanced); departure date/weekdays and planned current in D9 |
| "Is the price good now?" | D3 insights, D4 chart context strip and bands |
| "What happened / what did it cost / saving?" | D6 (day + month) |
| "Fix a setup problem" | D10 "Setup check" (links open advanced cards), recovery banner, `#critical-live` |

## 2. Controls, labels and permissions (verified in source)

### 2.1 Plan/settings controls (`dashboard.js:89-94`, `panel.js savePlan:579`)

| Control (label) | `data-setting` | Notes / guard |
| --- | --- | --- |
| Charge by: Requested energy (kWh) / Target SOC (%) | `driver`, `energy` | `driver` ∈ `manual_kwh`/`target_soc` (`src/types.ts`); `showMode()` toggles field groups |
| Planning vehicle | `vehicleId` | options from `chargerCarsOf(dashboard)` minus `guest`; sole car is a **proposed, unsaved default** (target 80, minimum 40, 07:30) — `panel.js:297-302`, `proposedPlanDefaults` |
| Target SOC (%), Minimum SOC (%) | `target`, `minimum` | save refused if minimum > target (`panel.js:589`); target is the plan target, **not** the car's limit |
| Soft cap (EUR-derived `c/kWh`) + Enable + basis (`nord_pool` / `configured_variable_cost`) | `cap`, `capEnabled`, `capBasis` | disabled unless `policySupported`; cap line drawn on chart **only** for `nord_pool` basis and a matching revision (`panel.js:308`) |
| Ready by + Enable ready-by | `readyBy`, `deadlineEnabled` | time is HA-local text; separate departure date/weekday editor lives in D9 |
| Extra time reserve (%) | `reserve` | shown only if backend sent `time_reserve_percent`; "Extra allowed time", not extra energy |
| Save plan / Reload settings | — | `replacementFor('plan', record, form)` builds the full body; `updateSettings(expected_revision)` is compare-and-set; reload confirms before discarding draft. **Host is looser than backend:** the form is enabled for admin *or* `users_change_plan` (`panel.js:289,582`), but for a non-admin the backend refuses a body that *changes* `soft_price_cap`, `cap_price_basis`, `minimum_ready_by_soc` or `time_reserve_percent` (not in `NON_ADMIN_FIELDS`, `api/settings.py:155-168`; `spotnav_not_admin`). Unchanged values pass. |

**Manual NUMERIC SOC entry (typing a percent) is absent from the sidebar and from the backend API.** `setVehicleSoc` /
`spotnav/choose_vehicle_soc` only *selects, or forgets, the HA sensor entity* that supplies SOC
(`api/entity_config.py websocket_set_vehicle_soc`, admin); it never accepts a number. SOC otherwise comes from that
sensor or the charger. **Learning reset** exists (admin, D5: "Reset learned estimates",
`morekAction('reset_learning')`). Car-limit write (`setChargeLimit`), identification choice, guest amount, camera: **legacy card only**.

### 2.2 Charging actions

| Action | UI | Path | Gate |
| --- | --- | --- | --- |
| Pause Auto until resumed | host bar | `spotnav/manual_action` `{action:"stop", choice:"until_resumed"}` | backend: **any signed-in user** (`api/manual_action.py` has no `is_admin`; `control.can_act` is only `connection.user is not None`, `dashboard.py:3045`). Host UI is stricter by *state*, not role: fresh dashboard+status, `control.can_act`, `admittedAction`, nothing busy/uncertain |
| Resume Auto | host bar | `spotnav/manual_action` `{action:"resume"}` | same; for Morek ownership additionally `ownedResumeOffered(status)` + `completion_authorized` |
| Charge Now (30/60/120/180 min or custom ≤ 48 h), Replace end, Return to Auto | host bar | `spotnav/morek_schedule` `charge_now` / `return_to_auto` (`end_time` sent as the confirmed absolute ISO time) | **admin** (UI `chargeNowBlocker` and backend) + `window.confirm` |
| Manual `start` | **not exposed** in sidebar | `manual_action` supports it (any signed-in user) | backend open, host deliberately absent |
| Recalculate & sync schedule, Reset learned estimates, Reconfirm schedule ownership | D5 (admin) | `morek_schedule` `recalculate_sync` / `reset_learning` / `reconfirm_migration` | admin; confirm for reset/reconfirm |
| Send current plan / Refresh from Morek / selective cleanup of profile 42001 / "Recalculate preview" | D5 `morekPanel` (admin) | `morek_schedule` `send`/`fetch`/`clear`/`status` | admin; send requires `pause_until_resumed` + fresh preview + confirm; clear requires `cleanup_supported` + confirm |
| Refresh observations | host bar | re-runs `loadChargers`/`refresh` (reads only) | any |

### 2.3 Advanced forms (all own drafts; none part of "Save plan")

| Card | Writes (existing commands) | Gate in sidebar |
| --- | --- | --- |
| Vehicle sources & properties (`vehicle-sources.js`, `vehicle-sources-view.js`) | `spotnav/choose_vehicle_soc` (sensor or automatic), `spotnav/update_vehicle` (capacity, onboard phases) with `expected` compare-and-set; config read `spotnav/get_entity_config` | **admin** (`get_entity_config`, `update_entity_config`, `choose_vehicle_soc`, `update_vehicle` all check `is_admin`, `entity_config.py:732-834`); `state:'forbidden'` otherwise; 45 s config refresh (`CONFIG_REFRESH_MS = 45000`, `vehicle-sources.js:8`) |
| Market & charging costs (`market-costs*.js`) | area/VAT/energy tax/flat grid fee via `update_settings`; grid-tariff % and high-load via `update_grid_tariff`; price entry via `choose_price_source`; read `get_market_options` (any user) | admin write; confirms on area switch, entry switch, discarding edits |
| Plan & charger parameters (`plan-params*.js`) | charging periods, planned current (confirms if ≠ required Morek amps or raising), departure date/weekdays via `update_settings` | Charging periods: **admin only** (`max_periods` not in `NON_ADMIN_FIELDS`). Planned current and departure date/weekdays: admin **or** `settings.users_change_plan` (`amps`, `departure*` are in `NON_ADMIN_FIELDS`) — host and backend agree |
| Notifications & setup check (`notify-setup*.js`) | recipients/events via settings; diagnostics read-only with "Open …" goto links | admin write (recipients/events are outside `NON_ADMIN_FIELDS`); diagnostics shown regardless |

### 2.4 Read-only navigation (no writes, no replans)

Price day nav (`get_price_days`, ≤ 8 days/request), history day/month nav (`get_charging_history`, `get_sessions`), price
insights (`get_price_insights`: duration 15-720 step 15, month, comparison, Retry), "Show this day on the price chart".
These run on user action; the only automatic reads are the 30 s dashboard/status poll, plus today's history (≤ every 5 min)
and live insights (≤ every 5 min) — `panel.js refresh:767`, `history-day.js REFRESH_TODAY_MS`, `price-insights.js LIVE_REFRESH_MS`.

### 2.5 Permission matrix (backend handlers read: `is_admin` / `require_admin` per `api/*.py`)

| Capability (command) | Any signed-in user | Admin only | Host UI vs backend |
| --- | --- | --- | --- |
| `get_dashboard`, `list_chargers`, `morek_schedule` **status**, `get_settings`, `get_charging_history`, `get_sessions`, `get_price_days`, `get_price_insights`, `get_market_options`, `get_power_month` | ✔ | | equal (reads) |
| Pause / Resume / Start (`manual_action`) | ✔ | | UI stricter by state only (fresh evidence, ownership); no role gate in either; Start has no UI |
| `update_settings` | ✔ only if `users_change_plan` **and** the body moves only `NON_ADMIN_FIELDS` (strategy, requested kWh, fill, driver, target, departure fields, amps, if-not-ready) | ✔ everything | **host looser** for cap/minimum/reserve (§2.1); equal for current/departure; periods admin in both |
| `plan_preview` | ✔ only if `users_change_plan` and no price-route overrides (`plan_preview.py:113`; else `spotnav_not_admin`) | ✔ | sidebar never calls it |
| `morek_schedule` `charge_now`, `return_to_auto`, `send`, `fetch`, `clear`, `reconfirm_migration`, `recalculate_sync`, `reset_learning` | | ✔ (`morek_schedule.py:2905`) | equal (UI `is_admin` + backend) |
| `get_entity_config`, `update_entity_config`, `choose_vehicle_soc`, `update_vehicle` | | ✔ | equal |
| `update_grid_tariff`, `choose_price_source`, `answer_price_duplicate`, `update_site_settings`, `set_entsoe_key`, `dismiss_setup_item`, `suggest_import_target` | | ✔ | equal where the sidebar has UI |
| `get_logs`, `get_debug_bundle`, `send_debug_info`, `get_blueprints`, own-mode fix, `write_charge_limit`, camera | | ✔ | log viewer hidden for non-admin; rest legacy-only |
| `release_import_target`, `identify_vehicle` (`admin_only=False`) | ✔ | | legacy card only; no sidebar UI |
| `choose_vehicle_identification`, `update_guest` (`identification.py`, default `admin_only`) | | ✔ | legacy card only |

Net: no backend command the sidebar calls is *more* permissive than its host gate except the Plan-controls cap/minimum/reserve case; the sidebar is
stricter than the backend only through freshness/ownership/busy preconditions and by not exposing Start, `plan_preview`, or the open legacy commands.

### 2.6 Legacy Lovelace card (separate, not the redesign target)

`frontend/src/card.ts` + `card-view.ts` + `editor.ts` own surfaces **absent from the sidebar**: car identification
("which car?"), guest amount, camera reference pictures, car charge-limit write, solar/hybrid strategy and site settings,
own-mode fix, import-target release/suggestion, ENTSO-E key, setup dismissal, debug bundle download/send, blueprints count,
sessions CSV export, site power month. They remain reachable only through this card; the redesign must decide scope
explicitly rather than assume the sidebar replaces them. (Per-command consumers: §7 matrix.)

## 3. Data catalog by user purpose

Legend — **Shown**: Y shown, P partially, N not shown. Source = API block → frontend consumer.

### 3.1 Vehicle, SOC and provenance

| Datum | Surface | Source / symbol | Unit / zone | Freshness, unknown | Shown |
| --- | --- | --- | --- | --- | --- |
| SOC value | D1 battery card | dashboard `soc.value`, `soc_observation.raw_value` → `adapter.js` (`useRaw`) | % | `socStale` if dashboard stale, unknown report time, age > 180 s, estimated, or restored; unknown ≠ 0 (`renderBattery`) | Y |
| SOC provenance (vehicle vs charger, integration name, report age, restored, **SpotNav estimate**) | D1 `socDetail` line | `soc.source`, `soc.age_s`, `soc.estimated`, `soc_observation.{time_basis,raw_*,integration,restored}` | s → text | "Vehicle report time unavailable" is not freshness | Y (one prose line) |
| Capacity, efficiency, derived battery kWh / need / wall kWh / active minutes | D1 facts | `soc.capacity_kwh`, `soc.efficiency` → `batteryEstimates` | kWh, min | labelled "est."; need `soc.need_kwh`/`room_kwh` **not** used | P |
| Target / minimum / low-SOC marker | D1 bar | `settings.target`, `settings.minimum`, `lowSocWarning` | % | marker is plan target, not car limit | Y |
| Vehicle's stored target/minimum, car-limit write range, wake flag, consumption, car's own limit | — | `vehicles[].target_percent`, `min_percent`, `charge_limit_range`, `wake_for_reading`, `consumption_kwh_per_10km`, `max_percent`; `soc.vehicle_max_percent` (`serialize_vehicle`, `serialize_soc`; §6 row 7) | % , kWh/10 km | per-field null rules in §6; `target_percent`/`min_percent` are a person's stored vehicle properties, not car-reported | **N (A, emitted)** |
| Capacity source (`reported`/`stored`), suggested phases | D7 | `vehicles[].capacity_source`, `suggested_onboard_phases` | — | | Y (D7 only) |
| Sensor choice and detection candidates | D7 | `get_entity_config` → `vehicleSourcesModel` | entity ids | HA entity state `missing/unavailable` check via `hass.states` | Y (admin) |
| Plug / identification / guest | — | `identification`, `vehicle_choices`, `guest` blocks | — | | **N (A)**; only `guest.active` read |
| Learned energy per % / power, samples, rejections, clamping | D2/D4/modal plan block | `plan.proposal.learning` → `learning-model.js` (`decodeLearning`) | min effect | stale observation states no effect | Y |
| Reserve (requested vs granted minutes, upper-allowance kWh/cost) | plan block, window rows | `plan.proposal.reserve`, `window_details[].reserve_*` → `reserve-model.js` | min, kWh, major currency | "upper allowance, not measured use" | Y |

### 3.2 Plan, proposal and execution tracks (the four tracks)

| Track | Meaning (do not blur) | Source | Surface | Unknown handling |
| --- | --- | --- | --- | --- |
| **Proposal** | current calculated windows, not sent | dashboard `plan.proposal.periods`, `window_details`, `planned_kwh`, `cost` (`adapter.js windows`) | lists, modal, chart lane | `planStale` → plan hidden ("Last plan cost · stale"); clamped to start at now (`chart-tracks.js`) |
| **Sent / ACK** | charger answered a profile; not installed | status `sent`, `sent_at`, `ack` (`morek-view.ts morekEvidence`); history `planned_blocks` | evidence cell, chart lane (loaded history day) | "Acknowledged is not installed" in legend |
| **Effective** | `GetCompositeSchedule` readback of limits, remaining period only | status `effective`, `verification` → `effective-track.js` | evidence cell, chart lane | stale/malformed/ended readback → unknown; any bad period fails closed |
| **Measured** | observed power/current/register | status `readiness.live`, `readiness.freshness` → `live-charging.js`, `evidence-freshness.js`; history `observed.*` | D1 "Measured now", banner facts, chart lane | missing = Unknown; measured 0 is 0 |
| Legacy Auto "installed" plan | the legacy `ChargingController.plan`, **not** Morek's sent profile or readback | `plan.installed`, `plan.relation`, `planning.applied` (§6 row 3) | **not shown** in sidebar | **N (A, emitted; Morek population unverified)** |

Also available in status and used only in prose: `outcomes.{uncertain,state,attempt,removal}`, `ownership.*`,
`operator.state`, `reconciliation.{reason,blocker,recovery}`, `verification.{reason,pending,exact,max_delta_s}`,
`schedule_pause.*`, `charge_now.*`, `link.*`, `readiness.{control,vehicle,transaction,session_start,charging_enabled,boot_start}`.

### 3.3 Prices, market, provider, FX

| Datum | Surface | Source | Unit / zone | Quality cases | Shown |
| --- | --- | --- | --- | --- | --- |
| Published price intervals (raw) | D4 chart | `prices.published_intervals[].raw_price` → `price-chart.js publishedChart` | major unit → **EUR c/kWh** (`displayPrice` ×100 only for EUR) | gaps stay gaps; chart refused when stale/zone/currency invalid | Y |
| Effective (fee-inclusive) price | — | `prices.intervals[].effective_price` (`serialize_intervals` → `_row`) | **hundredths of major unit/kWh** (`effective_minor_per_kwh`; EUR c/kWh), unlike `published_intervals` (major) | planner basis; `intervals` is `[]` without market/fiscal; **not** drawn | **N (A, emitted)** |
| Absolute bands: <8 Cheap, 8–<15 Normal, 15–25 Medium (25 inclusive), >25 Expensive | chart legend/colours | `shared-dashboard/price-bands.js` | **EUR c/kWh only**; other currencies neutral | display only, not a limit | Y |
| Held days, partial days, day picker | D4 nav | `get_price_days` → `price-days.js` | market-zone local days | `(partial)`, disabled-with-reason | Y |
| Provider route, per-day held provider, fetched-at, mixed providers | D4 (as evidence/subtext) | `prices.provider`, `prices.today/tomorrow_{state,provenance,fetched_at}` → `adapter.js priceProvenance` | HA-formatted in **market zone** | "held provider unavailable" | P (prose) |
| Waiting for tomorrow / publication time / price_wait / price_state | notes | `prices.waiting_for_tomorrow`, `planning.price_wait`, `planning.publication_at`, `plan.price_policy.{provisional,price_coverage_end,tomorrow_pending,fx_note}` | instants | provisional plan from today-only prices | P (provisional text and `waiting_for_tomorrow` for price nav only); `publication_at`, `price_wait` **N (A, conditional; §6 row 4)** |
| Priced vs unpriced slot counts, resolutions | — | `prices.priced_slots/unpriced_slots/resolution_minutes/resolutions_minutes` (§6 row 5) | — | slot counts null without a planning snapshot | **N (A, emitted)** |
| Area, currency, source name/url, timezone, suggested VAT | D8 | `market.*` | — | `catalogue_state` | Y (D8) / source link N |
| FX | note only | `plan.price_policy.fx_note`; `wait_for_exchange_rate` recovery text; historical `reference_price_rate_missing` | — | EUR conversion needed for non-EUR providers | P |
| Fiscal components (VAT/tax/transfer policy, effective, unit) | D8 | `fiscal`, `price_source`, `grid_tariff` | % or minor/kWh | `policy` text | Y (D8) |
| Price insights: current vs recent baseline (absolute band **and** relative percentile separately), best published window, month stats, comparison | D3 | `get_price_insights` live/monthly → `price-insights.js parseLive/parseMonthly` | EUR c/kWh; market zone | `REASON` codes (e.g. `baseline_too_short`, `partial`, `no_price_rate`); needs ≥ 7 complete days | Y |

### 3.4 History, sessions, costs, savings

| Datum | Surface | Source | Notes | Shown |
| --- | --- | --- | --- | --- |
| Day window, retention class (`full/partial/digest_only/plan_only/none/unknown`), truncation | D6 banners | `get_charging_history` → `history-day.js buildHistoryModel` | HA-local day (`hass.config.time_zone`); ~3 days of per-minute rows, 62 digests (roadmap D3) | Y |
| Flow intervals, gaps, capture restarts, outside-plan flow, unknown-plan spans | D6, chart lanes | `observed.*`, `comparison.*` | verdicts `flow_observed/no_flow_observed/unknown` | Y |
| Energy by basis, coverage | D6 | `observed.energy`, `observed.coverage` | each basis separate, never summed | Y |
| Session list per day, register reconciliation, **unplaced late kWh**, **unassigned register kWh** | D6 session lines | `sessions[].reconciliation` (`RECON` map in `history-day.js:105`) | "session total is not certified" wording when uncertain | Y |
| Spot-only cost (day/session share/month, delivery-day) | D6 cards | `spot_cost` block → `spot-cost.js describeSpotCost` | major unit, `raw_published_spot_no_fees_no_taxes`; `amount:null` ≠ 0; coverage `complete/partial/none/no_sessions_recorded`; `priced/unpriced/unplaced/unallocated_kwh`; price source label | Y |
| Estimated savings | D6 cards | `spot_cost.savings` (`basis day_average_price`, `estimate:true`) → `describeSavings` | comparable subset only; `excluded_*`, `comparable_fraction`, `reference_days/sources`; negative savings valid; % hidden if reference ≤ 0 | Y |
| Fiscal cost, `this_month`, `month_summary`, legacy cost fields | — | `get_sessions` legacy buckets | deliberately **ignored** by new UI (`spot-cost.js` header) | N (by design) |
| Month list, `delivery_month_*`, `available_months` | D6 month section | `get_sessions(month)` | bounded, context-bound reads | Y |
| Site measured import for a month | — | `get_power_month` | any user | **N (B)** |
| Sessions CSV | — | `get_sessions format:"csv"` | filename + text | **N (B)** |
| Forecast cost (plan) vs historical spot cost | separate | plan `cost` (configured variable cost) vs `spot_cost` | **never combine** | Y (separate) |

### 3.5 Link, readiness, authorization, ownership, repair

All derive from Morek status (`spotnav/morek_schedule` `status`). Consumers: `charge-session.js`, `schedule-check.js`,
`recovery-banner.js`, `panel.js paintAutomatic`, `charge-now.js`, `morek-view.ts`.

| Group | Fields | Surfaces |
| --- | --- | --- |
| Readiness/authorization | `readiness.{control,vehicle,transaction,session_start,charging_enabled,live,freshness}`, `connector_id` | `#charge-session` posture (`authorized/waiting_on_purpose/pending/at_risk/unknown`) + facts list |
| Ownership | `ownership.{recorded_owner,completion_authorized,reconfirmation_required,blockers,recovery,legacy_admission,local_regulator,limitations}` | action enablement; `admissionDetail` text after a refusal; D5 |
| Link / reboot | `link.{state,since}`, boot-start states | `#schedule-check` |
| Repair | `reconciliation.{reason,blocker,recovery}`, check classes `healthy/unknown/differs_unconfirmed/differs_confirmed` | `#schedule-check`, `#recovery-banner` |
| Outcomes | `outcomes.{uncertain,state,attempt,removal,verified}` | warning alert, action latches |
| Pause / Charge Now | `schedule_pause.*`, `charge_now.{state,intent,outcome,uncertain,degraded,current_price,price_basis,above_cap}` | host bar |

## 4. State inventory

Treatments are what the source does today; "interpretation" is what a designer may safely say. No row implies physical
charging from an ACK, readback, schedule, switch or retained plan.

### 4.1 Plug-in/charging posture (`chargeSession`, `charge-session.js:108+`)

| `kind` → level / posture | Today | Honest meaning | Who acts | Evidence available |
| --- | --- | --- | --- | --- |
| `unknown` (stale/failed status) → unknown | "Charging status unknown … Refresh" | not known | system / user Refresh | none fresh |
| `offline` → warning | "Charger offline"; last confirmed state + time | not known until reconnect | user checks power/network | `ready.control`, last connector status |
| `last_known` → unknown | "Charger status last known" | stale | system | stamped connector reading |
| `unplugged` → info | "Not plugged in" | no car | — | connector `disconnected` |
| `fault` → error | "Charger reports a fault" | will not charge | user | connector `error` |
| `uncertain` → error | "Start request outcome unknown", no automatic retry | may or may not have applied | user checks Morek app/logs | `outcomes.uncertain`, `session_start.state` |
| `control_unavailable` → warning | switch missing/unavailable | SpotNav cannot enable charging | user | `charging_enabled.reason` |
| `charging` → ok/info | "Charging" from **fresh measured** power > 100 W or current > 1 A | flow observed | — | `live.power_w/current_a` + age |
| `reported_charging` → info | charger says charging; no/zero measurement | not confirmed as flow | — | connector status only |
| `finished` → info | "Charge finished" | car reports complete | user re-plugs for a new one | connector `finished` |
| `paused` → info | "Plugged in — Auto is paused" (user intent) | intentional hold | user Resume | `schedule_pause.intent` |
| `scheduled_wait` (hold from schedule) → info | waits until plan window; source shown (readback vs "acknowledged, not confirmed") | intentional wait | — | `scheduleLimit` source |
| `pending` → pending (`session_start.state` `starting`, or `waiting`/transient `blocked` while age < `GRACE_MS` 120 s or unknown) | "asking the charger…" / "Getting ready to ask" | request being sent or not yet sent; nothing confirmed | system re-checks blockers that end by themselves (`TRANSIENT_SESSION_BLOCKERS`; delays 5/15/30/60/120/300 s, max 12 runs, `morek_session.py:19-20,437-462`); then `start_not_sent` warning → user | `session_start.{state,reason}`, `session_start_at` |
| `accepted_waiting` → pending (`accepted`/`request_accepted`, age < 120 s) | "We asked the charger to enable charging" | charger said yes; **no transaction yet; never auto-resent** | system only waits; at 120 s or `no_transaction_observed` it becomes `accepted_no_transaction` (warning) and the user starts it in the Morek app or re-plugs | + transaction evidence |
| `rejected` → warning (`request_rejected`) | "SpotNav retries once after about a minute" | refused by charger | **bounded retry**: one more attempt after ≥ 60 s (`attempts` ≤ 2, `morek_session.py:616-628,676-681`); after the second rejection or any other reason SpotNav stops and the user acts | `session_start.attempts` is not in the UI |
| `uncertain` → error (`ss.state` or `outcomes.uncertain`; reasons incl. `previous_start_may_have_applied`, `request_interrupted`, `session_evidence_unavailable`, `outcome_storage_changed`) | "Start request outcome unknown" | may or may not have applied | **never retried** (a stored `pending`/`unknown` attempt blocks all further starts, `:612-613`); user checks Morek app/logs | `outcomes.*`, `session_start` |
| `transaction_unmatched` → pending | display-only downgrade: a transaction number cannot be tied to this plug-in and the start is `pending`/`accepted_waiting` | not confirmed | no action by either side; clears when measured flow appears | `readiness.live.transaction` + `changed_at` vs start time |
| `not_ready` → pending | charge-control switch off/unavailable/unconfirmed (`readiness.charging_enabled`), in any plugged-in state | not authorized to charge | system asks the charger to enable when its checks pass (boot-start `waiting`); otherwise user enables in the Morek app | switch readback |

**Start-request guards (backend, `morek_session.py _reconcile.validate`):** the start is issued only through the owned-profile admission after re-checking worker/charger availability, generation, person Stop, current ownership ticket, connector identity, connection id, completed/not-Preparing session, boot-start blockers, `schedule_pause` (until Resume), legacy pause, protection conflict (`_start_cap`), uncertain profile outcome, planner identity, and OCPP logging safety; refusals surface as `blocked` + reason. It deliberately does *not* require plan quality and "asserts nothing that a retained schedule is effective" (`:585-588`).

**Authorization is never inferred from a switch or a transaction number.** The UI's "authorized" posture (`charge-session.js:95-98`) is derived from evidence — a fresh reported transaction for this plug-in, measured flow, or the charger's own "Charging" status — "never from the switch alone"; the charge-control switch is explicitly "neither authorization nor a transaction" (`:38,145`), and a leftover transaction number counts only if it changed after this plug-in's start request (`:88-92`). A designer must not turn `enabled`/transaction-exists into an authorization badge; `reported_charging` also maps to the `authorized` posture although flow is unmeasured, so wording must keep "reported, not confirmed".

Exhaustive enumeration: `frontend/sidebar/charge-session.js` (`startOutcome`, `result(...)` calls), tests `frontend/test/`.

### 4.2 Overall health / banners

| Source | States (grouped) | Source file |
| --- | --- | --- |
| Recovery blocker (`recoveryBanner`) | automatic (waiting for connection/identity/planner/prices/fresh inputs/FX/logs, with next retry and retries left); person-then-automatic (`set_battery_capacity`); person needed (`upload_uncertain`, `repair_needs_person`, `check_charger_response`, ownership/protection conflicts, resume/confirm); informational (no charging needed, Charge Now active, user pause); repair notes (deferral, spacing, confirmation, release) | `frontend/sidebar/recovery-banner.js` `WHAT`, `REPAIR_NOTE`, `AUTOMATIC` |
| Schedule check / link | link up/down/unknown+since; boot `none/unknown/waiting/requested/blocked/closed`; check kinds `check_healthy/_healthy_stale/_differs/_rechecking/_deferred/_spacing/_gated/_needs_person/_repaired/_waiting/_unknown`, `link_lost/link_quiet`, `boot_*` | `frontend/sidebar/schedule-check.js` |
| Alert `#critical-live` | mismatch (`live.mismatch`), uncertain outcome, `operator.state==='mismatch'`, `verification.reason==='limits_or_transitions_differ'` | `adapter.js` `warning` |
| Evidence summary | ~15 "Current plan is not confirmed; <reason>" sentences, one "remaining plan matched effective limits" success | `frontend/src/morek-view.ts morekEvidence` |
| Dashboard staleness | `observationFreshness`: `fresh/failed/invalid/future/old` (90 s max age, 5 s skew) | `frontend/src/observation-freshness.ts` |

### 4.3 User/system intent matrix

| Situation | Today's treatment | Notes for designers |
| --- | --- | --- |
| User **Pause until resumed** (owned by Morek) | `#pause-state` "Pause requested; request …; ACK …; readback …; physical charging unknown"; Charge Now blocked ("Resume Auto first") | "Stop" semantics are `schedule_pause.intent/request/ack/readback`; `stop_pending` blocks Resume |
| **Charge Now** active | host-bar "Charge Now requested until …", intended schedule transitions, ACK/reject, readback match, session-start request state | end is fixed; later plug-in does not extend; `Return to Auto` is **not** a persistent pause |
| Return to Auto | `charge_now.state=inactive`; Auto may continue charging in current slot | confirm text says so |
| Auto, plugged in, waiting for cheap window | `scheduled_wait` | intentional hold, not a fault |
| Completed | `finished` + history | |
| Plan not feasible / target shortfall / min exception / cap block / provisional | `policy` codes → hint text (`adapter.js policy` map, `daily.policy.*` keys) | uncapped text only when revisions match |
| Plan stale / historical | proposal hidden, "stale proposal", `planStale` | still show last-known only as stale |

### 4.4 Loading / empty / error / permission / conflict

| Area | States implemented |
| --- | --- |
| Dashboard | loading message, `Dashboard unavailable or unsupported`, `refresh failed… last observation may be stale` (`this.dashboardFailed`), HA disconnected |
| Settings | loading, unavailable, **dirty**, **conflict** (newer revision / currency change / unknown prior write / permission change), saving, saved-confirmed, rejected, `spotnav_settings_reconcile_failed` ("may be saved, but replanning failed"), outcome unknown (timeout 10 s `bounded`) |
| Action writes | `chargeBusy/autoBusy/morekBusy/vehicleBusy/costBusy/paramBusy/notifyBusy` mutually blocking; `*Uncertain/*Unknown` latches survive remount (`WeakMap` per connection) and block retry |
| Price nav | `price-days.js` status per button, disabled-with-reason, Retry |
| History | `loading`, `unavailable` (zone unknown / `spotnav_history_unavailable`), `permission`, `error`, `invalid`, `ready` + `legacy`, `partial`, `not-retained`, `refresh-failed` banners (`history-day.js:302-306`, `history-view.js`) |
| Month cost / savings | `ready`, `loading`, `error`, `invalid`, `legacy` (older backend), cost `complete/partial/none/no_sessions_recorded`, savings `complete/partial/none/legacy/invalid` |
| Insights | `ready`, loading, `partial`/`missing` baseline, banners (`kind`), Retry only after failure |
| Advanced cards | `state: 'ready' / 'forbidden' / 'unsupported' / loading`, plus per-form conflict/busy/unknown notices |

### 4.5 Action error vocabulary (retain; exhaustive lists in code)

* `manual_action`: `spotnav_action_unavailable`, `spotnav_action_failed` (pre-effect), `spotnav_action_reconcile_failed` (**recorded, follow-up failed**),
  `spotnav_action_outcome_unknown`, `schedule_owner_unavailable`, `identity_unresolved/changed`, `resume_unavailable`,
  `resume_interrupted`, `ownership_blocked`, `legacy_execution_ownership_blocked`, `invalid_pause`, `no_settings`,
  `pause_unsettled`, `action_pending`; mapped in `panel.js actionFailure()` and `admissionDetail()`; **unlisted or missing codes are treated as unknown**.
* `charge_now`: `spotnav_morek_resume_auto_first`, `…invalid_time/duration`, `…identity_unresolved/changed`, `…schedule_owner_unavailable`, `spotnav_not_admin`; any other code → outcome unknown.
* Backend authority: `custom_components/spotnav/api/manual_action.py`, `api/morek_schedule.py`; frontend: `frontend/src/types.ts`, `model.ts ACTION_*`.

## 5. Action inventory and guards a redesign must retain

| Intent | Feedback today | Guards to keep (source) |
| --- | --- | --- |
| Pause / Resume | Busy → "Request in progress; state not yet confirmed" → "Accepted; waiting for a fresh confirmed state" → "Confirmed by a fresh dashboard observation" (`autoExpected` match); refusals via `actionFailure` | fresh dashboard **and** status for Morek-owned; admitted action only (`admittedAction`); no action while any other write busy/uncertain; **no retry after unknown** (`autoUncertain`); newer Stop wins |
| Charge Now / Return | `window.confirm` showing end time and current price vs cap; "Intent recorded; waiting for schedule reconciliation… does not confirm charging"; waits for fresh status with the same `intent.id` (`chargeExpected`) | `chargeNowBlocker` (admin, fresh, ownership authorized, not paused/stop-pending, no unknown outcome, no pending expectation), re-check at dispatch boundary (`panel.js:429-431`), future end ≤ 48 h |
| Save plan / advanced saves | "Saving…" → "Saved and confirmed." / conflict / reject / unknown | compare-and-set `expected_revision`; draft kept across refresh; conflict on revision/currency/permission change; confirm before discard |
| Admin Morek tools | `morekError` / `syncNotice` / `learningNotice` | re-validated after `window.confirm`; `send` needs held pause, fresh preview id unchanged, no dirty settings; `clear` never offered as a general cleanup |
| Read navigation (price/history/insights) | Retry; loading text | **no writes and no replans**; reads bounded and context-bound (charger/permission epoch); explicit user action for non-default reads |

Cross-cutting: `bounded()` 10 s timeout does **not** cancel the WS call — the slot stays occupied until it settles;
`generation`/`permissionEpoch` checks drop responses for another charger/permission; a permission flip during a write marks it unknown.
Never add "retry", "resend", "clear profile" or "repair" buttons keyed off a mismatch; the recovery text intentionally says who acts.

## 6. Existing but underused data

**Verified against producers, not decoders.** A decoder accepting a field is *not* evidence the backend emits it. Each row names the
producer and payload path, when it is non-null, and what the sidebar already consumes (grep of `frontend/sidebar`, `frontend/shared-dashboard`).
**A1** = key emitted by the current `serialize_dashboard` (`api/dashboard.py:2273`); value conditional as stated. **A2** = decoder-supported but
current production behaviour unverified or not emitted: not ranked as usable without endpoint changes. **B** = existing request handler + wrapper the
sidebar never calls. **C** = internal only. Source reading only: no live payload was seen, so "emitted" means "serializer writes the key".

### A1 — emitted keys (ranked by redesign value; values conditional)

| # | Opportunity | Producer symbol → payload path | Non-null when | Sidebar consumption | Caution |
| --- | --- | --- | --- | --- | --- |
| 1 | Charge bar: percent, ETA, power + provenance, start SOC, session kWh | `charge_bar.charge_bar` ← `dashboard.serialize_progress` → `progress.{basis,percent,ends_at,power_kw,power_source,moving,start_soc_percent,started_at,delivered_kwh}` (decoder renames to `ends_at_ms`, `validate.ts:2283`) | key always; object only while `controller.charging` (`live.charging`) and not starting up and connection not `disconnected/finished/error`; `ends_at` null unless moving, not `open`, not sun strategy; `delivered_kwh` null for an estimated session | **none**; only legacy `model.ts:959 chargeBarFor` | `basis` says what the percent is of (`target`, `energy`, `vehicle_limit`, `open`). The plan "drives" only when a **legacy** `controller.plan` window holds now (`plan_drives`); with none, the bar is level ÷ car limit, not progress to the plan target — likely the Morek case, unverified. Show `power_source` (`measured`/`planned`) and `moving`. |
| 2 | Manual-kWh delivered/remaining | `_need_progress` → `plan.delivered_kwh`, `plan.remaining_kwh` | keys always; numbers only for an energy-count need (`energy_basis` not `None`/`requested`), else null | none (chart uses `plan.proposal.planned_kwh`) | null ≠ 0; target-SOC plans do not set it |
| 3 | Legacy Auto "installed" schedule and its relation to the proposal | `_installed_section` → `plan.installed.{identity,periods,amps,phases,power_kw,active_period_index}`; `serialize_plan` → `plan.relation.{applied,applied_identity,pending_identity}`; `serialize_planning` → `planning.{applied,execution_state,execution_reason,execution_paused,pending_attempt}`; `prices.intervals[].installed_planned` | `installed` null with no `controller.plan`; `active_period_index` null outside windows; `relation.applied` null with no snapshot | none | Source is `ChargingController.plan`/`AutoExecutor`, **not** the Morek profile (that is status `sent`/`effective`). Whether a Morek-owned charger ever populates it is unverified (legacy start/stop is blocked by `async_legacy_permitted`, no ownership check seen in `_install_locked`). Do not label it "what the charger holds". |
| 4 | Price wait / publication time | `serialize_planning` → `planning.{price_wait,publication_at,must_buy_now_kwh}` (+ `price_state`, `today`, `tomorrow`, `missing`, `state`, `reason`) | `planning` null without a snapshot; `price_wait`/`publication_at` null unless the plan needed unpublished prices (`auto_controller.py:752-756`) | none of these; adapter reads only `planning.{historical,calculated_at,settings_revision,departure_at}`, `plan.price_policy.*`, and `prices.waiting_for_tomorrow` (price nav) | Morek published-only plans (Stage 16.1) are a separate path (`auto_controller.py:138`); whether they set `price_wait` is not established — ownership-dependent |
| 5 | Priced/unpriced slots and resolutions | `serialize_prices` → `prices.{priced_slots,unpriced_slots,unpriced,resolution_minutes,resolutions_minutes,interval_count}`; `_proposal_section` → `plan.proposal.{priced_slots,unpriced_slots,unpriced}` | counts null without a snapshot; resolutions from held documents (`_held_resolutions`) | only `proposal.unpriced` (`adapter.js`); price days use their own `get_price_days` rows | `unpriced` plan costs are null, never 0 |
| 6 | Fee-inclusive prices per interval | `serialize_intervals`/`_row` → `prices.intervals[].{effective_price,raw_price,duration_minutes,proposal_planned,installed_planned}` | `[]` without market/fiscal choice or documents | none: chart draws `prices.published_intervals` only (`price-chart.js:6`) | **units are hundredths of major/kWh** (not the major units of `published_intervals`); keep raw vs effective separate, bands stay on raw EUR c/kWh |
| 7 | Vehicle detail: stored target/minimum, car-limit write range, wake flag, consumption, car limit, per-vehicle SOC | `capture_vehicles` → `serialize_vehicle` → `vehicles[].{target_percent,min_percent,charge_limit_range,wake_for_reading,consumption_kwh_per_10km,max_percent,soc_percent,capacity_source,onboard_phases,suggested_onboard_phases}`; `serialize_soc` → `soc.{vehicle_max_percent,need_kwh,room_kwh,vehicle_name}` | keys always per vehicle; `target_percent`/`min_percent` null unless a person stored them (`vehicle_properties.stored_properties`); `charge_limit_range` null with no limit entity/range; `wake_for_reading` null unless the integration offers wake; `max_percent` null unless reader knows it; `consumption` falls back to a default (not evidence) | D7 only: `soc_percent` fallback text, `capacity_source`, `suggested_onboard_phases`; rest unused; `d.soc.target_percent` is already the planning target (`adapter.js:145`) | plan target ≠ car limit; no write UI (`write_charge_limit` is legacy admin) |
| 8 | Phases and current | `serialize_charging_phases` → `charging_phases.{phases,charger,vehicle,limited_by}`; `capture.phase_result.as_fields()` → `detected_phases`, `phase_detection.{source,confidence}`; `controller.current_range()` → `current_range` | `charging_phases` null when undetermined; phase detection `UNKNOWN`/`none` with no controller (advisory only) | `current_range` **is used** (`plan-params.js currentRangeOf`, min/max/reported); `charging_phases`, `detected_phases`, `phase_detection` unused; `settings.phases` already carries the effective phases (`encode_settings(..., _effective_phases)`) | detection is advisory; `limited_by:"vehicle"` explains slow kW |
| 9 | Dashboard live setpoints, vehicle-not-requesting advisory | `serialize_live` → `live.{charging,schedule_active,requested_current_a,setpoint_current_a,measured_current_a}`; `ChargeProgress.as_dict` → `charge_progress.{state,reason,since}` | `live.*` from the legacy controller (null current when unknown); `charge_progress` is `unknown/connector_status_unavailable` without a controller | none (sidebar "Measured now" comes from Morek status `readiness.live`); `charge_progress` only in legacy `model.ts:613` | **`charge_progress` is NOT charge progress**: it is a passive "started but the car requests no current" observation (`execution/charge_progress.py`), never a percent/ETA |
| 10 | Site, strategy, priority, starting-up | `serialize_site`, `serialize_strategy*`, `serialize_charger_priority`, `serialize_starting_up` | `charger_priority` null for a charger on no site; `starting_up` always an object | none | relevant to non-Morek/solar only; Morek schedule-only ignores load balancing (roadmap §1) |
| 11 | Promote already-consumed headline settings | `fiscal`, `price_source` (only with a price entry), `grid_tariff` (additive), `setup`, `market.{area_id,currency,source}` | as present | consumed by D8/D10 — not unused, only buried | surface area/currency/provider near the chart |

### A2 — decoder-supported, current producer unverified or not emitted (not ranked usable)

| Item | Why |
| --- | --- |
| `ChargeBarBlock.ends_at_ms` / `started_at_ms` (decoder names) | not wire keys: the wire carries `ends_at`/`started_at` ISO strings (`charge_bar.py`); the decoder converts |
| Anything in row 3 on a Morek-owned charger; `price_wait`/`publication_at` for Morek published-only plans; the plan-target meaning of `progress.percent` under Morek | serializers exist, but whether Morek ownership populates them is not shown in source; verify with a real redacted payload |
| `prices.index_state`, `prices.index_revision` | always `null` by design ("since 2.0 … keys stay"), `dashboard.py:1956` |

Nothing the first draft ranked was schema-only, but ranks 2 and 3 of the draft were over-stated: `charge_progress` was conflated with the progress bar, and the "installed" relation was presented as charger state.

### B — existing read, sidebar never calls (wiring only)

| # | Opportunity | Handler → wrapper | Gate and conditions | Caution |
| --- | --- | --- | --- | --- |
| B1 | Site measured import for a month | `api/power_month.py websocket_get_power_month` → `api.ts:729 getPowerMonth` (legacy card only) | any signed-in user; refused `spotnav_no_site` if the charger is in no site and `spotnav_needs_total_grid_power` if the site cannot measure import; month YYYY-MM within `ARCHIVE_MONTHS` | site import ≠ car charging |
| B2 | Sessions CSV | `sessions.py websocket_get_sessions` (`format:"csv"`, month, refused with `from`/`to`) → `api.ts:742 getSessionsCsv` | any signed-in user; returns filename + text (`csv_filename`) | legacy fiscal vs spot columns differ — label |
| B3 | Latest sessions list and open session | same handler, default JSON → `getSessions` (sidebar sends `limit:1`) | any signed-in user | legacy fiscal fields sit beside spot fields |

**Class C (not usable without backend work):** internal planner state beyond serialized `planning.*`, raw OCPP transactions, per-slice price provenance in costing (`sessions/costing.py` returns labels only), provider fetch logs; recorded-slice provider provenance for historical costs is "unknown" in the handoff.
**Not found:** a numeric manual-SOC command (only `choose_vehicle_soc` sensor selection exists), a persistent "reason I paused" history, a per-day weather/solar forecast in the sidebar (hybrid forecast exists only in site settings, legacy card).

## 7. API appendix (existing commands and consumers)

| Command (`spotnav/…`) | R/W | Gate | Response blocks used | Sidebar consumer | Legacy card |
| --- | --- | --- | --- | --- | --- |
| `list_chargers` | R | user | `chargers[]` | `panel.js loadChargers` | ✔ |
| `get_dashboard` | R | user | whole dashboard (§6) | `panel.js refresh` → `adapter.js`, `validate.ts decodeDashboard` | ✔ |
| `morek_schedule` `status` | R | user | status (§3.2/3.5) | `panel.js refresh` → `morek-view.ts`, `charge-session.js`, … | ✔ |
| `morek_schedule` `send/fetch/clear/recalculate_sync/reset_learning/reconfirm_migration/charge_now/return_to_auto` | W | admin | schedule/learning/reconciliation | `panel.js morekAction/chargeAction` | partly |
| `manual_action` | W | user | `{ok,error,action,choice}` | `automaticAction` (stop/until_resumed, resume) | ✔ (also start) |
| `get_settings` / `update_settings` | R / W | user / admin or `users_change_plan` | `SettingsRecord` | `loadSettings`, `savePlan`, advanced forms | ✔ |
| `plan_preview` | R | admin, or non-admin only with `users_change_plan` and no price-route overrides | what a save would plan | — (sidebar never calls) | ✔ |
| `get_price_days` | R | user | `available`, `range` rows | `price-days.js` | — |
| `get_price_insights` | R | user | live, monthly | `price-insights.js` | — |
| `get_charging_history` | R | user | observed/comparison/sessions/plans/digests/retention | `history-day.js` | — |
| `get_sessions` | R | user | summaries, `spot_cost`, delivery months | `history-day.js requestSessions` (`limit:1`, month) | ✔ |
| `get_power_month`, `get_market_options`, `find_region` | R | user (`get_power_month` needs a site that measures import) | monthly import / areas | market options only | ✔ |
| `get_entity_config`, `choose_vehicle_soc`, `update_vehicle`, `update_entity_config` | R/W | **admin** | vehicle rows, sensors | D7 | ✔ |
| `update_grid_tariff`, `choose_price_source`, `answer_price_duplicate`, `update_site_settings`, `set_entsoe_key`, `dismiss_setup_item` | W | admin | — | market card (first two) | ✔ |
| `identify_vehicle`, `choose_vehicle_identification`, `update_guest`, `write_charge_limit`, `fix_own_mode`, `release_import_target` (user), `suggest_import_target` (admin), camera commands | W | mixed (see §2.5) | — | — | ✔ |
| `get_logs` | R | admin | log entries, `latest_seq`, `boot_id` | `log-viewer.js` | — |
| `get_debug_bundle`, `send_debug_info`, `get_blueprints`, `get_card_info` | R/W | admin (card info: user) | — | — | ✔ |

Handlers live in `custom_components/spotnav/api/*.py` (registered in each file's `async_setup_*`); client wrappers in
`frontend/src/api.ts` (strict, `unknown` until decoded; failures become `SpotnavApiError` with a static message).

## 8. Constraints and handoff checklist for the next designer

**Hard constraints (from source and roadmap §1/§5; do not weaken):**

1. One shared UI for live and preview: any new region must be fed by the adapter model, not host-only DOM — the host bar
   is currently the exception (problem 1).
2. **Absolute EUR bands** `<8 / 8–<15 / 15–25 / >25 c/kWh` only when unit is `c/kWh`; otherwise neutral colour; never a limit.
3. **Dark and 360-400 px mobile** (single column ≤ 800 px, 44 px targets, no horizontal page scroll); HA safe area.
4. **Zones:** HA-local time for sessions/history/user-facing times; market zone for price days; carry DST (23/25-hour days,
   `localMidnightAt`, `timeTicks`); never fixed 24 h/UTC multiples.
5. **null ≠ 0.** Stale, partial, "no session recorded", "not reported by older backend" and "no data" are distinct from "no charge".
6. Show **original provider/currency**; convert only with a backend-provided display (`displayPrice`); FX missing is a
   named state.
7. **Costs are spot-only** (no fees/taxes); forecast (plan) cost, fiscal cost and measured spot cost are separate cards;
   savings compare the **same kWh** with the delivery-day average and show the compared subset.
8. **No blind repair, resend, clear-profile, retry or manual-start.** Unknown outcomes block retry; Pause/Stop and
   ownership/identity/protection always win.
9. Evidence words: proposal, sent/ACK, effective readback, transaction, measured flow — never merged into "charging".
10. Admin/permission/confirmation behaviour in §2.5 and §5; reads never write or replan; reads stay bounded and context-bound.
11. `update()` must keep drafts, open dialog, scroll and chart viewport across 30 s refreshes; one mounted instance per root.
12. If code changes: bump `manifest.json`, `npm run build`, `npm run check-dist` (AGENTS.md); Stage 14 non-regression contract applies.

**Prominence recommendations (not settled design):**

| Keep prominent (decision-critical, always visible) | Candidate for secondary/detail |
| --- | --- |
| One combined "will it charge / is it charging" status with action owner and freshness | Evidence cells' timestamps, ACK/readback detail, verification deltas |
| SOC + target + ready-by + next window + estimated cost (forecast, labelled) | Battery kWh estimates, assumptions text, reserve allowance figures |
| Pause/Resume, Charge Now/Return to Auto, with confirmed-state feedback | Recalculate/sync, learning reset, reconfirm, send/fetch/clear (admin tools) |
| Price chart with absolute bands, now marker, soft cap, window shading | Four evidence lanes (default collapsed or per-day), legend prose |
| Blockers needing a person (uncertain upload, repair needs person, offline, fault) | Automatic-retry notes, link-quiet, boot states |
| Spot-only day/month cost and savings with coverage badges | Per-session reconciliation, capture gaps/restarts, retention notes |
| — | Vehicle sources, market costs, plan parameters, notifications, log viewer (advanced/admin) |

**Checklist before design sign-off:** (a) obtain a real redacted `get_dashboard` and `morek_schedule status` payload to confirm the A1 values and settle the A2 items (§6) under Morek ownership; (b) decide scope for legacy-only functions (§2.6); (c) decide structured-state-to-copy approach (the
sidebar is English only); (d) decide whether the host bar moves into the shared model so preview parity is real;
(e) browser verification of dark/mobile order (grid-area cascade, §0 problem 3); (f) keep tests that name guards
(`frontend/test/`, `frontend/sidebar/browser-check.mjs`, `frontend/prototype/*.test.mjs`).

## 9. Inspected / not inspected

**Source audit only; no browser, HA, live, hardware, build or test run.**

**Read (first pass):** `AGENTS.md`, `prompts/coordinator-handoff.md`, `docs/morek-development-handoff.md` (top), roadmap §1/§9;
`frontend/shared-dashboard/{dashboard,plan-view,vehicle-view,evidence-view,insight-view,price-nav-view,vehicle-sources-view,plan-params-view,notify-setup-view,history-view,reserve-model,learning-model,spot-cost,price-bands,price-format,price-days,README,dark.css (grid rules)}`;
`frontend/sidebar/{panel,adapter,charge-session,recovery-banner,schedule-check (header),charge-now,live-charging,effective-track,price-chart,log-viewer}.js`;
`frontend/src/{api,morek-view,validate (interfaces),model (exports),observation-freshness}.ts`;
`custom_components/spotnav/{sidebar.py, api/manual_action.py, api/morek_schedule.py (permission + status), api/sessions.py, api/dashboard.py (can_control)}`; `is_admin` grep of every `api/*.py`.

**Read (second pass, backend producers and guards):** `api/dashboard.py` (`capture_dashboard`, `serialize_dashboard`, `serialize_progress`, `progress_facts`, `serialize_plan`, `_need_progress`, `_installed_section`, `_proposal_section`, `serialize_planning`, `serialize_prices`, `serialize_intervals`, `serialize_vehicle`, `capture_vehicles`, `serialize_soc`, `serialize_charging_phases`, `serialize_live`); `api/charge_bar.py`; `execution/charge_progress.py` (`ChargeProgress.as_dict`); `execution/morek_session.py` (`_reconcile`, `_arm_recheck`, `_arm_no_transaction`); `api/settings.py` (`NON_ADMIN_FIELDS`, `plan_only_mutator`, `get_settings`), `api/plan_preview.py`, `api/entity_config.py`, `api/import_target.py`, `api/power_month.py`, `api/sessions.py` (handler); `execution/controller.py` (`async_install`, `async_legacy_permitted` call sites); `planning/auto_controller.py` (`price_wait`, `energy_basis` fields); consumer greps over `frontend/sidebar` and `frontend/shared-dashboard`; `frontend/sidebar/{market-costs-panel,plan-params-panel,notify-setup-panel,vehicle-sources}.js` and the `history-day.js`/`price-insights.js` refresh and range constants for §2.3/§2.4.

**Not inspected / unverified:** rendered output, HA theme and phone behaviour, deployed version, any live payload (so "emitted" in §6 means the serializer writes the key), whether a Morek-owned charger populates the legacy-controller fields (§6 rows 1, 3, 4), the full bodies of `history-day.js`/`price-insights.js`/`market-costs.js`/`notify-setup.js`, `schedule-check.js` beyond its header, translations other than English, the legacy card layout, test suites, `docs/morek-schedule.md`.
