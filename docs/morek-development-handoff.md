# SpotNav Enhanced / Morek development handoff

Last updated: 2026-11-10. This file is a **public-repository handoff**, not a place for
passwords, access tokens, HA configuration exports, logs, or private household information.
Re-check the live system and Git state before acting; observations below may become stale.

## Approved next direction (planning, not implemented)

**2026-11-09 coordination update:** the roadmap now begins with a concise numbered
task checklist. Completed audit/ownership/admission/identity/start-evidence work
through 2.5.13 is Stage 0, not work to repeat. **Stage 1 price-policy settings,
planning and reactive explanations are implemented through 2.5.21, pending
coordinator review.** Actual isolation is Stage 2 and remains
incomplete/unarmed. The proposed additional unwired durable
pre-dispatch helper was never assigned and is not the next task. Detailed historical
versions/deployment facts below must not override current Git or the new checklist.

Read [charging-dashboard-roadmap.md](charging-dashboard-roadmap.md) for the user's
latest requirements and prioritized, bounded LLM tasks. The user wants **one HA
charging dashboard with multiple cards**, not a second stock-card dashboard;
evcc-inspired styling and Apache ECharts; no solar UI. Crucially, daily operation
must become **autonomous Morek schedule sending**, with manual debug controls
retained and **no competing legacy SpotNav start/stop/current loop** for that
connector. Establish execution ownership, transaction authorization and safety
before removing the current manual-mode interlock. None of that roadmap is
implemented by this documentation change; the manual baseline below remains
accurate for current code. The first implementation block is **A1** in the roadmap.
The user subsequently clarified: **no separate overnight/hardware-testing stage**;
they decide when to test. Continue automated regression checks and document
physical uncertainties without blocking dashboard development on an overnight run.
History must use **real Morek telemetry/events**, not infer charging from planned
windows; the roadmap includes a source audit of OCPP MeterValues/status/transactions
and recorded HA measurement entities. The user also suggested **BMW CarData via
the Bavarian CarData integration** if Morek lacks history; investigate actual
history/live telemetry availability, home-session association and timestamp/energy
quality rather than assuming SOC changes reveal precise charging periods.
New P0 planning requirement: configurable
**soft price cap** (example 10 cents/kWh), overridden only for energy necessary to
reach configurable **minimum SOC** (typically 40%) by the ready-by deadline, using
the cheapest feasible periods. Higher normal targets use below-cap slots only.
Changes to ready-by time, cap or minimum SOC must trigger backend recalculation
and automatic resending when the resulting schedule changes. These are future
requirements, not features claimed implemented in the manual baseline below.

## Repository and deployment

- Local checkout: `C:\Code\spotnav-home-assistant`; Git `main`, remote
  `https://github.com/ClassyCircuit/spotnav-home-assistant.git`.
- Fork display name: **SpotNav Enhanced**, from `hacs.json` and the integration manifest.
  Its HA domain stays `spotnav` to preserve existing integration entries and card identities.
- Source version for this handoff: **2.5.7** sends displayed plan windows, including
  a shortened final block, as a fixed-time schedule. **2.5.6** added bounded, upload-owned readback
  verification and explicit coverage/timing-drift diagnostics. **2.5.5** added selective cleanup of test profile
  `42001`, with explicit confirmation, persisted outcome and a fresh readback.
  Version 2.5.3 added the Morek
  preview and layout fix (commit `ef483315`); 2.5.4 explicitly enables text
  selection in the card and Morek panel, preserving nonselection on the graph.
  Check Git and the installed manifest before assuming 2.5.7 is installed in HA.
  Marketplace installs this fork from the default branch; it shows commit hashes rather
  than `vX.Y.Z` because the fork has no GitHub Releases. Do not reintroduce
  `zip_release: true` into `hacs.json` while installing from `main`: Marketplace tried
  `/releases/download/main/spotnav.zip` and received HTTP 404. The existing optional
  `.github/workflows/release-zip.yml` does not make every push a release.
- **Deployment drift observed:** the first read-only SMB check on 2026-11-08 found
  HA at **2.5.1**. A later check after the user's screenshot found **2.5.3**
  installed; source is **2.5.7**. Recheck before assuming the latest version is
  installed. The user has seen the 2.5.3 preview/readback on HA.
  Do not assume a Git push has installed or restarted the integration on HA.

## Local Home Assistant access: verified facts and limits

- On this Windows machine `\\HOMEASSISTANT\config` was readable, including the installed
  `custom_components\spotnav\manifest.json`, backend and bundled card. The share root
  `\\HOMEASSISTANT\` did not pass a `Test-Path` check; use the `config` share. **Write
  permissions were not tested.** Do not change live files without the user's explicit request.
- An environment variable named `homeassistant` exists in the current shell and has a
  token-like shape. The user originally did not know whether it was a password or API
  token; the later authenticated `GET /api/` confirmed it works as a Bearer token
  for the user-supplied HA URL. Never print, persist, commit, or transmit its
  value to an unconfirmed host.
- `HOMEASSISTANT:8123` refused HTTP earlier; SMB access did not establish the API URL.
  The user subsequently provided `http://homeassistant.local/` (local port 80).
  On 2026-11-08, unauthenticated `GET /api/` returned 401; with the `homeassistant`
  environment variable as a Bearer token it returned HA's `API running.` message
  and HTTP 200. **The token value was not printed or saved.** Check the destination
  before any future credentialed request; do not follow redirects with credentials.
- The old `GET /api/error_log` returns 404 on this HA. Authenticated admin
  WebSocket `system_log/list` returned retained warnings/errors; authenticated
  read-only `GET /api/hassio/core/logs?lines=1000` returned the Supervisor's
  recent raw Core log. Both surfaces can contain private data: filter in memory
  and print only needed timestamps, logger names and stable diagnoses; never
  paste/export raw logs. The SMB `config` share still had only a zero-byte
  `home-assistant.log.fault`; the `share` share had no log export.
- Safe share version check, without reading credentials:

  ```powershell
  $p = '\\HOMEASSISTANT\config\custom_components\spotnav\manifest.json'
  if (Test-Path -LiteralPath $p) {
    (Get-Content -Raw -LiteralPath $p | ConvertFrom-Json) | Select-Object name, version
  }
  ```

  Do not copy `secrets.yaml`, `.storage` auth/config entries, API tokens or HA logs into this
  repository. If an API URL is provided, read the `homeassistant` environment variable only
  inside the request process and return status/necessary diagnostics, never the credential.

## What is implemented

- `custom_components/spotnav/api/morek_schedule.py`: WebSocket
  `spotnav/morek_schedule` v1 with `status` (read-only), `fetch` (OCPP
  `GetCompositeSchedule`) and `send` (`SetChargingProfile`, then readback).
  Send/fetch require an HA administrator. The feature reuses HA OCPP's connected
  ChargePoint; it does **not** start another OCPP server. HA OCPP's Python internals
  are a version-sensitive dependency.
- The only allowed physical OCPP 1.6 station is `3020002509120029`, connector `1`.
  HA OCPP may expose a friendly charger ID; `hass.data['ocpp']` contains `cpids`
  mapping that alias to the WebSocket/physical ID and `charge_points` for connected
  stations. The 2.5.1 code mistakenly compared SpotNav's alias directly to the
  physical ID. Version 2.5.2 resolves aliases and refuses ambiguous/wrong stations;
  `status` reports configured and resolved IDs plus a reason when unsupported.
  An unresolved OCPP identity remains a real blocker: do not bypass it by weakening
  the physical-station check.
- Send is intentionally manual. SpotNav Auto must be paused **Until I resume**;
  plan current must be 16 A, with 1–3 nonoverlapping future blocks within 48 hours,
  matching the current settings revision. Unpriced plans are refused. From 2.5.7,
  `proposal.shown_periods` supplies the displayed, energy-estimated shortened end
  as a fixed stop time; prior versions refused it with `target_stop_unsupported`.
  No feedback-based energy stop is promised by this stored schedule. The OCPP 1.6 `TxDefaultProfile`
  uses profile ID `42001`, stack level 1, an absolute schedule and up to seven
  0/16 A transitions with a final **persistent 0 A** period. No automatic uploads
  or authorization of a new charging transaction are implemented. Version 2.5.5
  adds *manual selective* cleanup, never automatic removal.
- Upload intent/time are stored before the OCPP call because a timed-out request
  may still have changed the charger. A response of `Accepted` is recorded separately
  from readback. The per-charger record is persisted in HA storage across restarts.
  Readback is a *composite/effective* current schedule, **not** an inventory of
  stored profile IDs. `verified` means a matching readback at that time, subject to
  the requested horizon; it is not proof of current or future physical charging.
- `frontend/src/morek-view.ts`, `frontend/src/card.ts`, `frontend/src/api.ts`:
  admin-only opt-in panel under the SpotNav card. The normal graph/period list
  displays SpotNav's calculated plan. The separate panel shows the last **Sent**
  transitions and timestamp, upload reply, Morek **effective** readback and its
  timestamp, and a mismatch warning. Version 2.5.2 styles the opener, keeps it
  visible, and provides configured/resolved ID diagnostics and a retry when the
  charger identity does not match; it does not offer Send in that case.
- In **2.5.3**, `status` also computes a read-only preview through the
  same `_proposed_profile` helper used on Send. This is a *snapshot at the reported
  calculation time*, not a sent or guaranteed-effective schedule. Send recomputes
  at its own timestamp and only then uploads. A SHA-256 preview fingerprint
  commits to the absolute ON/OFF times and settings revision; a changed plan
  refuses the upload. The 0 A start time still moves with the clock. The panel separates proposed,
  last Sent, and effective schedules, and disables Send if preview is missing or
  blocked. The ordinary Plan settings popup is **not** an OCPP profile preview.
  A manual **Recalculate preview** sends only `status`; a user hardware test is
  described below.
- `frontend/src/card-fill.ts` and `frontend/src/card-view.ts` subtract the Morek
  opener and expanded panel from the host's available chart height, rather than
  making the chart fill the added panel height. Regression coverage lives in
  `frontend/test/card-fill.test.ts`. Verify visually in HA after installation.
- The user observed an unstyled button that disappeared on 2.5.1; `d8454555`
  addressed it, and the later 2.5.3 screenshot shows the styled panel and preview.

## Safety and outstanding decisions

- Clarification requested by the user: `42001` identifies the **real SpotNav
  calculated schedule**, not a dummy schedule. Sending with the same ID replaces
  that profile; removal is not required between routine schedule updates.
  Selective cleanup is for withdrawing SpotNav's stored schedule, especially its
  persistent final 0 A limit. Other profile IDs/purposes may coexist. The UI's
  historical "test profile" wording refers to the experimental feature, not
  fake charging windows. Investigating the mismatching effective readback remains
  necessary before claiming charger-side scheduling works.

- The user authorized adding selective cleanup on 2026-11-08 and explicitly
  reported that **the car is currently unplugged**. This is a time-specific user
  observation, not a live sensor verification; recheck before further testing.
  Unplugged readback does not prove control of an ongoing charging transaction.
- Do not send a test profile until there is a deliberate way to undo it. The final
  0 A period is not cleared on Resume. HA OCPP's generic `ocpp.clear_profile`
  may clear **all** charging profiles on a connector, including other controllers'
  limits; it is not a selective cleanup. In 2.5.5, action `clear` requires admin
  and `confirm_profile_id: 42001`. It targets the same verified physical station
  and uses `ClearChargingProfile(id=42001)` only. No user-supplied arbitrary ID,
  connector-wide clear, or generic HA clear service is exposed. The request is
  persisted before calling OCPP; timeout is recorded as an unknown outcome.
  Readback follows even when cleanup is not confirmed, and `verified` stays false
  after any cleanup attempt until another Send. Sent history is retained.
  `cleanup_supported` gates the UI on older backends. Cleanup neither resumes
  Auto nor authorizes charging. It may increase effective limits; inspect the
  charger response and readback rather than claiming a profile inventory check.
  **Not yet deployed/hardware-tested at implementation time.** The user prefers
  Marketplace update + restart over editing the HA share. Do not restart HA or
  modify live files without specific approval; further Send/fetch needs the new
  cleanup backend installed first and a deliberate cleanup step after testing.
- SpotNav's usual live start/stop controller remains in the code. A stored Morek
  schedule must not compete with it; pause Auto for manual testing and do not resume
  blindly while the test profile is still present. Morek's independent CT-based
  household load protection has not been validated and must not be substituted by
  software scheduling.
- Earlier offline experiments, *before this integration*, showed OCPP transitions
  within an already authorized session but did not establish behavior across reboot
  or authorization of a new offline transaction. A previous seven-transition plan
  intended roughly **one hour** of charging but a five-transition Morek composite
  readback appeared to allow roughly **two and a half hours**. Treat mismatches as
  substantive and watch measured charging, not just an `Accepted` OCPP reply.
- **A user-initiated hardware test occurred on 2026-11-08 with 2.5.3 installed.**
  The user's screenshot and the read-only persisted SpotNav record show a 4:12 PM
  `SetChargingProfile` reply of `Accepted` for profile `42001`. The sent profile
  called for 0 A until 10:00 PM, 16 A until 11:00 PM, 0 A until 12:15 AM, 16 A
  until 1:00 AM, then persistent 0 A. A 4:19 PM `GetCompositeSchedule` reply was
  also `Accepted` but contained just one period, **16 A immediately**, so
  verification is false. `Accepted` confirms an OCPP response, **not** that the
  submitted limits are the effective ones or that the car actually draws 16 A.
  The station's profile inventory and measured charging were not verified.
- Subsequent authenticated, read-only API log inspection on 2026-11-08 found
  **no logged `SetChargingProfile`/`GetCompositeSchedule` payload** and no SpotNav
  or OCPP error at the upload time in the recent raw Core log. The retained OCPP
  warning at 16:18 local (source `ocppv16.py:760`) was **"Force Smart Charging
  feature profile"**, reflecting a configured force option, not proof of
  charger's advertised capabilities. Multiple `homeassistant.loader` warnings
  at 16:17–16:18 indicate HA integration initialization between the 16:12
  upload and 16:19 readback; this could reflect an HA restart, but does not
  prove whether Morek retained or applied a profile across the reconnect.
  A **single read-only Morek `fetch` at 16:31** returned Accepted with one
  effective 16 A period again; `verified` remains false. No profile was sent,
  cleared, or modified by this investigation. Installed HA OCPP 0.12.3 can
  create its own `TxProfile` for active transactions
  and `TxDefaultProfile` for future ones (`custom_components/ocpp/ocppv16.py`);
  competition is **one possible** explanation, not a confirmed diagnosis.
  Avoid another send, generic clear, or resuming a competing controller until
  existing profiles and measured current can be investigated safely. Consult
  HA Settings > System > Logs for additional historical startup logs if needed.
  Do not assume `GetCompositeSchedule` lists stored profiles.

## Tests, build, and next steps

### Stage 5.1d — daily sample dashboard (review pending)

- The daily area shows sample measured power, the next proposal and estimated wall
  energy/cost beside compact simulated controls. A visible mismatch warning separates
  sample effective-limit disagreement from measured power. Technical evidence stays
  available in a disclosure; duplicated cost and status cards were removed. Both
  chart alternatives remain. Above-cap exceptions are labelled in all plan displays.
- The local scenario selector demonstrates mismatch, normal waiting, charging,
  unavailable vehicle/current price, minimum shortfall, partial stop and an above-cap
  minimum exception. It changes only local sample data. The shortfall is a hand-authored
  proposal, not proof that every possible schedule is infeasible. The missing-price
  insight deliberately masks its inputs while the chart/plan retain separate fictional
  prices. Cap is explicitly enabled at 35 c/kWh (€0.35/kWh) on the stated price basis.
- Recent charging compares an independently authored last-sent 22:00–23:00 sample
  window and fictional quarter-hour readings: 21:45 sample out-of-plan flow and a
  22:30–22:45 unknown gap. Three of four sent-window readings are available; selection
  is disabled and this is not real history. The 5.1c opportunity label now explicitly
  limits the comparison to Now/interval-boundary starts, not all continuous starts.
- Prototype build and 16 focused tests passed. Desktop 1440×1000 and emulated mobile
  390×844 checked both charts, modal/focus, all six alternate states, sample selector,
  missing data, history labels and no horizontal overflow; 144 observed requests were
  local/data only. Screenshots inspected in temporary `opencode` folder:
  `spotnav-51d-{desktop|mobile}-{full|history|waiting|charging|unavailable|infeasible|partial|exception}.png`.
  Browser was an existing debugging session; emulated touch is not physical touch.
  Full accessibility, HA integration and real telemetry remain unverified. No HA or
  hardware access; dispatch remains unarmed. Stop for coordinator/user review, not 5.1e;
  overall 5.1 and chart preference remain unapproved.

### Stage 5.1c — sample price insights (review pending)

- A compact local panel compares current chart price to the preceding 30 fictional
  days. The synthetic history joins the chart's historical fixture; duration-weighted
  quartiles define lower/typical/higher, requiring 90% coverage and 24 intervals.
  One lowest-known fully priced one-hour opportunity uses starts at Now or source
  boundaries and the same future chart prices. Missing spans are not zero, and the
  opportunity is explicitly not the proposal or a feasibility/charging guarantee.
  October 2026 shows available-price duration-weighted average, range and coverage;
  it is neither charging cost nor savings. No same-weekday claim is made.
- `?insights=missing` deliberately masks insight inputs, not the unchanged chart,
  and labels the distinction. Historical samples are synthetic, fixed-day, not
  retrieved Nord Pool data; real timezone/DST, price basis and source coverage need
  Stage 7.4/7.5 validation. No live binding, planner or charger code changed.
- Prototype build and 14 focused tests passed, including gap, negative-price,
  duration, insufficient-baseline and no-future cases. Desktop 1440×1000 and
  emulated mobile 390×844 browser checks passed normal/missing states, no overflow,
  modal and chart regressions and local-only requests; 60 requests observed were
  local/data. Screenshots inspected in temporary `opencode` folder:
  `spotnav-51c-{desktop|mobile}-{insights|missing}.png`. The existing debugging
  browser was used; physical touchscreen, full accessibility and HA remain untested.
  No HA access or hardware action; dispatch remains unarmed. Overall 5.1 and chart
  choice await visual approval; stop for coordinator review before 5.1d.

### Stage 5.1b4a — balanced cards and unknown values (review pending)

- The two desktop cards use equal-width, naturally stretched grid items; mobile stacks.
  The compact list retains all windows, projected SOC and totals, with full pricing,
  energy and cost in both chart cards and a modal reachable from either card. Very long
  plans naturally stretch the overview as well; this can leave space in that card, but
  avoids clipping windows or a fixed height. The sample-only renderer shares formatting
  and keeps known wall energy separate from unknown cost and weighted price.
- `?plan=missing`, `?plan=invalid` and `?plan=long` exercise the real prototype UI;
  the missing pricing fixture is separate from the unchanged sample chart prices.
  Invalid values and missing assumptions display Unknown; target feasibility is unknown
  when the projection is unavailable. No production planner or charger code changed.
- Prototype build and ten sample tests passed. Desktop 1440×1000 and emulated mobile
  390×844 checked card alignment, four-display consistency, missing/invalid data, eight
  windows, modal keyboard/focus/inside/outside/Escape and existing chart interactions;
  48 observed requests were local/data only. Two intermediate browser checks failed
  while testing Enter via DevTools; using the existing Space-key activation passed.
  A new Edge process could not bind occupied port 9227; the existing debugging browser
  ran the checks. Physical touch, full accessibility and HA integration remain unverified.
- Inspected screenshots in the temporary `opencode` folder use
  `spotnav-51b4a-{desktop|mobile}-{cards|missing|missing-modal|long}.png`.
  No HA or hardware access; Morek dispatch remains unarmed. Overall 5.1 and chart
  choice await user visual approval; stop for coordinator review, not 5.1c.

### Stage 5.1b4 — compact controls and plan (review pending)

- The sample controls and complete shared plan sit beside the vehicle overview on
  desktop and stack on mobile. Both chart cards and the next-window modal retain
  identical windows and totals. The fictional 48% start, 60 kWh usable capacity and
  90% efficiency project 53.6% and 57.0% after the windows, using cumulative wall
  energy × efficiency for battery energy. Projections are bounded and unknown for
  invalid or missing inputs; they are not observations or guarantees.
- Prototype build and nine sample tests passed. One initial test failed because of
  floating-point precision; the corrected tolerance passes. Desktop 1440×1000 and
  emulated mobile 390×844 browser checks passed four-display consistency, overflow,
  keyboard opening, focus, Escape, close and inside/outside mouse clicks, plus the
  existing chart interactions. Twelve observed requests were local/data only. The
  check used an already-running debugging browser because port 9227 was occupied;
  a new Edge instance could not bind. Physical touch, complete accessibility and HA
  integration remain unverified. Emulated pinch/taps worked; backdrop clicks were
  mouse-emulated at mobile size, not tested on a physical touchscreen.
- Screenshots: temporary `opencode/spotnav-51b4-{desktop|mobile}-{full|modal}.png`.
  No HA access, deployment or charger action; dispatch remains unarmed. Overall 5.1
  and chart choice await visual approval; stop for coordinator review, not 5.1c.

### Stage 5.1b3 — proposal gradient (visual review pending)

- The sample charts replace dashed proposal borders with a bottom-bright green
  gradient and an aligned pale plan track, identified in the legend. Their widths
  use exact clipped window boundaries, including 00:37:30. The complete plan and
  price tooltip remain available; the gradient does not identify cheap prices as a plan.
  Earlier 5.1b3 entries describing dashed proposal borders are superseded.
- Prototype build, seven sample tests and headless Edge browser checks passed;
  the browser asserts the rendered track and gradient pixel boundaries. Desktop
  1440×1000 and emulated mobile 390×844 screenshots were inspected; narrow windows
  remain narrow on mobile. Emulated touch is not physical touchscreen validation.
  Screenshots are in the temp opencode folder as
  `spotnav-51b3-gradient-{desktop|mobile}-{bar|step}-{default|zoom}.png`.
  The prototype is local-only; no HA or hardware access occurred. Keep 5.1b3,
  overall 5.1 and chart choice pending review and visual approval.

### Stage 5.1b3 — sample day/date band (review pending)

- Both charts show a slim aligned day band and midnight lines. The fixed fictional
  dates are Sun 8, Mon 9 and Tue 10 Nov 2026; exact interval dates appear in tooltips.
  Partial day labels shorten or disappear when too narrow. Missing price spans use
  hatching, with a text label where space permits and an explanatory note on each card.
  The default fixture has all three days; separate rendered test fixtures contain gaps
  and negative prices and do not replace the surrounding plan or price summary.
- Prototype build and seven sample tests passed. Headless Edge 1440×1000 and emulated
  mobile 390×844 checked both charts, day-band and midnight pixel alignment through
  zoom/pan, dated tooltips, missing intervals, no page overflow and local-only requests.
  Emulated pinch and taps worked; physical touch remains unverified. Screenshots were
  inspected; the first capture exposed band overlap with pins/units and was corrected.
  Captures are in the temp opencode directory, named
  `spotnav-51b3-dates-{desktop|mobile}-{bar|step}-{default|zoom|missing}.png`.
- This is not timezone or DST validation. Production must use the configured local
  timezone, handle local dates/midnight and 23/25-hour DST days, and verify actual
  historical and published future price availability before binding. No HA or hardware
  access occurred; Morek dispatch remains unarmed. Keep 5.1b3 and overall 5.1 pending
  coordinator review and user visual approval; do not advance automatically.

### Stage 5.1b3 — follow-up (sample-only; coordinator and visual review pending)

- Both cards open 1.5 sample hours before Now through the available sample horizon;
  Full horizon restores all 72 hours. Anchored responsive DOM labels remain aligned to
  sample clock boundaries as the chart pans; desktop default uses two-hour ticks and
  mobile uses sparser ticks, each with a day. The 10 c/kWh axis includes negatives.
  The prior unanchored-axis limitation below is superseded. Future real data requires
  source boundaries and timezone/DST-aware labels, not this fixed-day sample.
- Black past and dark-blue future, solid blue Now, green dashed proposal areas and
  numerical horizon-extrema pins are shown with the existing price-colored bars and
  stepped line. The exact partial 00:37:30 plan end is untouched. Touch taps select
  the exact interval by horizontal coordinate; two-finger scaling uses snapped viewport
  boundaries. Chart gestures consume touch on the plot; scroll elsewhere on the page.
- Prototype build and six focused sample tests passed; one intermediate test expectation
  failed after changing the responsive cadence and was corrected. Edge headless at
  1440×1000 and emulated 390×844 exercised both charts, mouse wheel/plot/slider,
  keyboard zoom and reset, snapping, rendered labels, modal and local-only requests.
  Simulated pinch changed [13,48] to [20.25,39] for both; emulated taps showed actual
  interval tooltips without test fallback. Neither is physical-touch validation.
  Full-card screenshots for each chart/default and zoomed view are in the temp opencode
  directory as `spotnav-51b3-final-{desktop|mobile}-{bar|step}-{default|zoom}.png`.
  Captures were inspected; mobile uses sparse time ticks and narrow windows retain
  outlines. Full accessibility, HA shadow-root integration, actual source updates,
  production timezones and real devices remain unverified. No HA or hardware access;
  dispatch stays unarmed. Overall 5.1 and chart choice await user visual approval;
  stop for coordinator review before 5.1b4.

### Stage 5.1b3 — partial chart fidelity and navigation (review required)

- Both sample charts show price-colored intervals, complete-horizon low/high pins,
  and blue dashed proposed-window outlines, with exact partial stops in tooltips and
  plan. Step color uses a piecewise visual map; it is a line/area, not bars. Pins are
  offscreen when their horizon extrema are offscreen. Snapping uses fixture boundaries,
  not price, now or plan rounding. No production code, HA or hardware was touched.
- Prototype build and five sample tests pass. Existing Edge headless browser on desktop
  1440×1000 and emulated mobile 390×844 passed ordinary wheel, desktop plot drag and
  slider drag, button/keyboard zoom, reset, snapped boundary assertions, modal checks,
  and local-only requests (12). Full-card and zoom screenshots are in the temporary
  `opencode` folder, named `spotnav-51b3-{desktop|mobile}-{bar|step}[-zoom].png`.
  Desktop and mobile screenshots were inspected: overlays and colors are visible, but
  the mobile zoom capture can contain a tooltip. Emulated pinch did not zoom; narrow
  mobile touch targets needed programmatic tooltip fallback. Physical touch is untested.
- **Outstanding:** ECharts anchors ticks to the viewport edge after a pan, producing
  e.g. 21:30, 01:30 rather than the requested even-hour cadence, and midnight/day context
  can therefore disappear. The adaptive interval alone does not satisfy this request.
  Screenshots do not establish complete accessibility, production timezone/DST handling,
  or live data behavior. Keep 5.1b3 and overall 5.1 open; chart choice awaits approval.
  Do not proceed to 5.1b4 without coordinator review. Dispatch remains unarmed.

### Stage 5.1b2 — chart and sample-plan corrections (review pending)

- The local prototype keeps both full-width alternatives below side-by-side overview
  and controls. The step view now uses a continuous interval-correct line with a
  subtle gradient and explicit gap breaks. The bar renderer keeps narrow mobile
  intervals visible. Both views use the same fictional reference-derived fixture.
- Adjacent same-control, same-power blocks are grouped; a real pause separates the
  second window. Estimated window costs integrate overlapping prices, including
  partial intervals. The hand-authored two-window example totals 6.00 kWh,
  €1.59 and 26.45 c/kWh weighted. The next-window button opens a native modal
  reusing the same plan display. No production planner or charger behavior changed.
- Local prototype build, sample tests and browser checks passed. Edge headless at
  1440×1000 and 390×844 checked card layout, overflow, plan consistency, ordinary
  wheel events on each chart, slider drag, zoom/reset, desktop tooltips, modal
  keyboard activation, Escape, close, focus return and local-only requests. Rendered
  variable-width negative/missing fixtures were visually checked for both charts;
  screenshot files are in the local temporary `opencode` directory. The simulated
  pinch did not change zoom; full-overview emulated taps missed their narrow target
  and required a programmatic tooltip fallback. Physical touch, full accessibility,
  HA shadow roots and hardware remain unverified. Wheel zoom consumes page wheel
  scrolling over the plots; scroll outside the chart or use the scrollbar/keyboard.
  No HA access, deployment or hardware action occurred; dispatch stays unarmed.
  Overall 5.1 and chart choice remain pending user approval; stop for review.

### Stage 5.1b1 — full-width comparison (review pending)

- The local prototype displays bar and stepped-area alternatives concurrently with
  the same sample, markers, overview and complete hand-authored plan. Hourly values
  come from the supplied examples; their 15-minute fluctuations are synthetic and
  fictional, not verified Nord Pool data. The example is fixed-day, not DST-aware.
  The 35 c/kWh cap is separate from illustrative price bands and proposed windows.
  The three estimated windows total 3.75 kWh, €0.85 and 22.61 c/kWh weighted;
  the last ends at 00:37:30. No optimization or live price pipeline is claimed.
- Prototype build and sample unit tests passed. Edge headless desktop 1440×1000
  and mobile 390×844 checked layout, no horizontal overflow, both charts' endpoints,
  zoom/reset, focused Space-key zoom, desktop hover, disabled actions and local-only requests. Focused
  negative/missing fixtures check data segments but are not rendered browser
  fixtures. Simulated mobile touch at full overview did not reliably show a tooltip;
  the browser check falls back to a programmatic tooltip. Real touchscreen,
  pinch/drag, full keyboard navigation, HA integration and hardware remain unverified.
  Screenshots are in the local temporary `opencode` directory. No HA access,
  deployment or hardware operation occurred; production dispatch remains unarmed.
  Overall 5.1 and chart choice remain pending user approval; stop for review.

### Stage 5.1b — dark chart comparison (choice and approval pending)

- The same local prototype now offers switchable interval-width bars and a
  gradient stepped-area treatment, sharing one fictional variable-duration fixture,
  price/cap/now/deadline markers, window shading, full plan and zoom controls.
  It includes negative prices, a missing interval, partial future publication and
  a partial charging window. Sample total: 15 kWh, €0.51, 3.40 c/kWh; the
  fictional negative-price first window contributes −€0.12. Unknown is not zero.
  Time is a fixed relative-hour sample axis, not real timezone/DST handling.
- ECharts 6.1.0 and Web Awesome 3.14.0 remain locally bundled, with the existing
  Apache, zrender and Web Awesome license/notice output. No new dependency or
  production card/backend change. The stepped renderer terminates each segment at
  its interval boundary and does not bridge the sample price gap.
- Edge headless desktop 1440×1000 and mobile 390×844 rendered both variants.
  The browser check exercises switching, three plan rows, data gap/final boundary,
  negative-price mouse and emulated-touch tooltips, zoom/reset buttons, mouse drag
  of the overview, disabled charger actions and local-only requests. Four full-page
  captures are in the local temporary `opencode` folder. Real touchscreen gestures,
  keyboard chart operation, accessibility and HA integration remain unverified.
  Sample arithmetic tests and the existing TypeScript check passed; prototype JS
  is outside that check. Keep 5.1 and 5.1b pending user visual/chart choice; do
  not proceed to 5.1c without review. No HA or hardware operations occurred.

### Stage 5.1a — prototype refinement (visual approval pending)

- `frontend/prototype/` now illustrates a balanced desktop composition and the
  same mobile cards, with an immediately visible sample mismatch and expandable
  evidence, a three-window plan, per-window energy/cost and consistent totals.
  A 48% sample SOC already exceeds its 40% minimum; the 80% target is projected
  short within the 10 c/kWh sample cap. Controls are inert/simulated.
- Apache ECharts 6.1.0 (Apache-2.0) is bundled only in the prototype; its LICENSE
  and NOTICE and zrender 6.1.0 BSD license are copied into the local output. A
  custom interval-width price bar chart shows sample prices, cap and proposal;
  a separate stepped gradient chart illustrates sample measured power and a gap.
  The sample meter difference is independent of the chart and plan. Real telemetry,
  timezone/DST, production chart interactions and bindings are not implemented.
- Edge headless browser checks cover 1440×1000 and 390×844, six cards, mobile
  stacking, three windows, two canvases, no horizontal overflow, price hover,
  simulated touch, disabled actions, local input and evidence disclosure. Ten
  observed requests were local/data only. Screenshots are in the local temporary
  opencode directory; no physical touch, HA or physical charger validation.
  Sample arithmetic/missing-data node tests and existing project type-check pass;
  prototype JS is not type-checked. Build passes. npm reports Node 23 engine
  warnings and five dependency audit findings (two moderate, three high).
  5.1 and 5.1a remain unchecked for user visual approval; no 5.2 work was done.

### Stage 5.1 — isolated dashboard design study (visual approval pending)

- `frontend/prototype/` contains a local sample-only browser dashboard with
  shared tokens, reusable panel/badge/metric helpers and Web Awesome Core controls.
  It proposes a single Sections view, with a larger Prices & Plan area, the same
  cards stacked on mobile, explicit missing measurement and mismatch examples,
  and disabled actions. The chart is an illustration, not ECharts or history.
  No shipped card, integration or safety/dispatch code changed. The README covers
  startup, intended composition, local assets, licenses and HA caveats.
- Web Awesome 3.14.0 is MIT; selected components and theme are bundled locally.
  Its general icon resolver has a CDN default; no icons are used in this study.
  Actual HA shadow-root integration, theme mapping, dialogs/popovers and touch
  still require validation; this prototype is not a claim of compatibility in HA.
  Future distribution must audit transitive notices and avoid runtime CDN assets.
- Chromium Edge headless rendered 1440×1000 and 390×844; browser assertions
  check six cards, mobile order/alignment, no horizontal overflow, library input
  rendering, disabled actions, local editing and local-only requests. Screenshots
  are temporary, not committed. Type-check passed for the existing TS project;
  prototype JavaScript is not included in that type-check. Visual approval is
  outstanding; keep 5.1 unchecked and stop for coordinator review. No HA access,
  hardware operation or deployment occurred; autonomous dispatch remains unarmed.
- Prototype build and the existing focused Morek panel suite (21 tests) passed;
  `git diff --check` passed with line-ending warnings. npm reported unsupported
  engine warnings for existing test dependencies on Node 23 and five audit findings
  (two moderate, three high); the focused test still passed. npm also warned about
  forwarded test CLI options. The screenshot reflects the test's in-memory edit of
  the sample target field, not a saved setting.

### 2.5.30 — Stage 4.3 operator state (unarmed; review required)

- The existing status response derives an operator summary from current connection,
  preview, attempt and verification evidence. An in-flight upload is tracked only
  in memory and bound to its attempt; after interruption the durable uncertain record
  takes precedence over offline or stale matches. The existing panel shows manual
  readiness, sending, checking, mismatch, verified remaining effective limits and
  intervention guidance, plus the unarmed activation blockers. It requests fresh
  status after manual actions. No new outcome store or uncertainty reset was added.
- The panel and manual procedure distinguish proposal, ACK, effective readback and
  measurement. Unknown actions, possible final 0 A, person Stop, protection and
  downgrade/handback need a supervised decision; selective removal does not settle
  an earlier unknown upload. Automatic dispatch, transition and recovery are not
  enabled. No live HA, deployment, restart or charger action occurred.
- Validation: isolated actual-module planning suite 492 passed, one deselected,
  two warnings; focused Morek selection 115 passed, 378 deselected, two warnings;
  isolated lifecycle suite 26 passed, six warnings. The focused panel suite passed
  21 tests; frontend build, check-dist and type-check, targeted Ruff and diff check
  passed (diff check reported Windows line-ending warnings). HA/OCPP and storage
  boundaries are mocked; these are neither full HA nor physical validation. Full
  HA pytest collection remains blocked on Windows by the plugin's `fcntl` import.

### 2.5.29 — Stage 4.2 remaining-schedule verification (unarmed; review required)

- The existing comparator checks the remaining effective limits and transitions
  from the later of reported start, response receipt and sent-profile start.
  It refuses missing/stale/short coverage, an initial boundary within 90 seconds
  of a planned transition, or no remaining transitions. It reports coverage,
  maximum drift and the 90-second tolerance. A match says nothing about elapsed
  periods, installed-profile inventory, authorization or physical charging.
- Accepted worker uploads enter the same bounded read-only check path only after
  connector admission is released. Manual actions retain their existing admission
  and interlocks. Attempts have unique IDs and revisions; readback is checked
  against the accepted attempt, current intent, identity and entry lifecycle, with
  checks around network and storage awaits. Superseded evidence is not reported as
  verification of the current plan. Repeated publications may conservatively mark
  a previous match historical; no automatic resend, clear or uncertainty reset is
  introduced. Legacy evidence without the new attempt ID is not treated as current
  verification and requires a fresh eligible action/read.
- Production owned-profile admission remains unconditionally unarmed. Ownership
  transitions, lost-state recovery, electrical protection, transaction authorization
  and retained-profile exit remain activation blockers. Operator recovery/health is
  Stage 4.3. These changes have not been validated against live HA or hardware.
- Validation: isolated actual-module planning suite 481 passed, one deselected and
  two warnings; focused Morek selection 102 passed, 380 deselected, two warnings;
  isolated lifecycle suite 26 passed, six warnings. Focused frontend panel tests
  passed 12 tests; frontend build, check-dist and type-check, targeted Ruff,
  compileall and diff check passed (diff check reported Windows line-ending
  warnings). During development the panel test twice failed on obsolete expected
  wording; the expectations were updated and the final run passed. Tests use
  simulated worker authority and mocked HA/OCPP/persistence, not full HA or
  physical validation. No live HA, deployment, restart or charger action occurred.

### 2.5.28 — Stage 4.1 restart and reconnect (unarmed; review required)

- The startup worker subscribes to the current planner publication. The existing
  control-entity availability listener now invalidates queued worker work on both
  disconnect and reconnect, and resumes reconciliation after connector ownership
  initialization. A transition generation prevents an older initialization from
  resuming after a newer disconnect. Worker startup and pre-dispatch checks require
  the control entity to be available, and identity and current planner intent are
  rechecked through the existing connector admission and shared Send path. A later
  reconnect needs neither a browser nor another settings edit. The listener depends
  on HA OCPP exposing reconnect as a control-entity availability transition; other
  reconnect signals are not independently monitored.
- The ledger is evidence and deduplication, not a cached profile to replay or proof
  of installation. An unchanged acknowledged fingerprint is not re-sent on restart
  or reconnect; a changed valid intent can be reconciled only under simulated test
  authority. Unknown/interrupted attempts stay latched across restart; there is no
  automatic retry or reset. Identity ambiguity and duplicate discovered contenders
  fail closed. As previously documented, an unrecorded duplicate cannot be detected
  before it initializes. Lost outcome/ownership documents remain indistinguishable
  from first use; neither is solved by this substage.
- Production `owned_profile` admission remains unconditionally unarmed. Activation,
  durable ownership transitions, lost-state recovery, electrical protection,
  transaction authorization and retained-profile exit remain blockers. Stage 4.2
  active-window verification and Stage 4.3 operator recovery/health remain open.
  No composite readback is a profile inventory, and no ACK proves physical flow.
- Validation: isolated planning suite 460 passed, one deselected, two warnings;
  focused worker selection 32 passed, 429 deselected, two warnings; isolated
  lifecycle suite 26 passed, six warnings. The functional reconciliation tests
  use simulated authorization and mocked persistence/OCPP; the production gate
  is separately exercised and refuses. Frontend build and `npm run check-dist`,
  targeted Ruff and compileall passed. These are not full HA or physical tests;
  no live HA, deployment, restart or charger action was performed.

### 2.5.27 — Stage 3.3 shared manual actions and evidence (unarmed; review required)

- Manual Send and selective removal now take the existing physical connector
  admission lock; the manual-only entry point does not use or activate the
  permanently unarmed `owned_profile` gate. Admin, pause, preview fingerprint,
  settings revision and Morek identity checks remain; Send rechecks after each
  pre-dispatch persistence await. Refresh uses the connector read-only path and
  sends only `GetCompositeSchedule`, though it persists readback evidence.
- A connector-scoped atomic outcome document complements the old per-entry
  manual record. It records desired fixed-time intent, a pre-dispatch attempt,
  acknowledgement, a separately verified readback fingerprint, and removal
  outcome. It is bound to the first entry; a different entry is refused. Existing
  manual records are read conservatively: unknown legacy upload/removal outcomes
  remain uncertain, and old Accepted profiles do not supply a dedup fingerprint.
  This is not proof of installed profiles, transaction authorization or charging.
- A timed-out, unknown, cancelled or interrupted attempt remains uncertain on
  disk; automatic **and manual** sends are refused, including after restart.
  There is no automatic retry or reset. Explicit selective removal is still
  available, targets only ID 42001, invalidates deduplication and cannot clear a
  pre-existing uncertain-upload latch. Readback cannot resolve that latch. Failed
  or cancelled ledger writes poison the current process; writes are checked by
  reading the stored envelope back before dispatch. A lost entire outcome file
  remains indistinguishable from first use; missing-document recovery and robust
  transition protocols remain mandatory activation blockers, not solved here.
- The worker uses the same durable record and connector lock; manual replacement
  and removal cannot leave a stale worker success fingerprint. Status exposes the
  record or an unavailable/uncertain state, and the panel warns and disables
  Send when uncertain. No automatic sends are enabled, and no mode API, active
  readback verification, broader restart/reconnect recovery or exit policy was
  added. Electrical protection and transaction authorization remain unresolved.
- Validation: the isolated actual-module planning suite passed 451 tests with
  one deselected and two warnings; the isolated lifecycle suite passed 26 tests
  with six warnings. The focused Morek panel suite passed 12 tests. Frontend
  build, `npm run check-dist`, type-check, targeted Ruff, compileall and
  `git diff --check` passed; diff check reported Windows line-ending warnings.
  Persistence, HA and OCPP boundaries were mocked; these are not full HA or
  physical validation. No live HA, deployment or charger action was performed.

### 2.5.26 — Stage 3.2 backend worker (unarmed; review required)

- Each charger with an Auto planner attaches a worker to its calculation
  publications, including equal-result calculations. Existing planning paths
  supply settings, deadline, SOC and price updates; the current snapshot is
  delivered on subscription. The worker coalesces bursts, evaluates the 3.1
  displayed-window intent and fingerprint, and queues through the existing
  physical-connector admission lock. Inside that lock it rechecks generation,
  identity/ownership via admission, the planner instance, current intent,
  settings revision and calculation freshness before the OCPP boundary. No
  controller, assignment or profile lock is acquired inside admission.
- **Production dispatch is impossible:** `owned_profile` admission still always
  returns `schedule_mode_unarmed`, including for a purported Morek owner. No
  activation API, ownership change or weakening of manual Send was added. Tests
  use a deliberately simulated admission with mocked OCPP for the worker's
  functional send path. No active-window readback verification was added.
- Successful ACKs and definite rejections are deduplicated in process memory per
  physical connector. Before a send the worker latches uncertainty; timeout,
  unknown reply, exception or cancellation can mean the request applied, so all
  further sends for that connector are blocked in this HA process, even for a
  changed intent or entry reload. This is not durable across HA restart, does not
  reconcile manual Send/clear, and has no retry or recovery mechanism. Stage 3.3
  must establish durable attempted/ACK/verified outcomes and safe uncertainty
  handling and integrate manual actions before any activation-capable release.
- Unavailable, stale, expired or invalid intent performs no clear or replacement;
  an existing final 0 A may remain. The worker records only an in-memory reason,
  not persisted operator health. ACK is not verification, authorization or proof
  of physical charging; composite schedules are not profile inventories. Lost
  ownership state, durable transitions, electrical protection, authorization and
  safe retained-profile exit remain activation blockers. Reconnect/restart
  reconciliation and active-window verification remain Stage 4 work.
- Validation: the isolated actual-module planning suite passed 439 tests, one
  deselected and two warnings; the isolated lifecycle suite passed 26 tests with
  six warnings. The first planning run failed one existing import-inventory test
  because it did not yet name the new worker; after updating that assertion the
  suite passed. Frontend build and `npm run check-dist`, targeted Ruff and
  compileall, and `git diff --check` passed (the latter reported Windows line
  ending warnings). Tests use mocked HA/OCPP boundaries and simulated admission;
  they are not full HA integration or physical validation. No live HA, deployment,
  restart or charger action was performed.

### 2.5.25 — Stage 3.1 shared schedule intent (review required)

- The existing `_proposed_profile` is the shared current-intent entry point for
  manual preview and Send and a future backend caller. It uses the displayed
  fixed-time windows and existing profile builder; elapsed windows are dropped,
  active windows start at the request time rounded up to a whole second, and
  all ends round down. No energy is added to compensate for elapsed time; the
  original estimated kWh is not a measurement or an estimate of remaining energy.
  An active initial 16 A profile cannot be verified by the current future-only
  comparator; it remains unverified, with active readback work deferred to 4.2.
- Fingerprints include profile attributes, initial limit/phases, absolute future
  transitions and settings revision, but not the moving initial timestamp. A
  future-to-active transition changes the fingerprint and requires a new preview;
  changes to a shortened end, profile attributes or revision also invalidate it.
  Pause, admin, identity, current, revision and preview checks remain in place.
- No plan, expired plan, invalid windows, unpriced or stale/unavailable prices
  are refusals, not instructions to clear or release a limit. Only price states
  `ready` and `waiting_for_tomorrow` are accepted; `degraded` and `incomplete`
  are conservatively refused because the snapshot lacks per-window freshness.
  Freshness relies on the planner's current snapshot and price-state reporting,
  not an independent price-source fetch at Send. A retained final 0 A can persist
  after expiration. Composite readback is not a profile inventory; Accepted does
  not prove transaction authorization or physical charging.
- No worker, automatic send/retry/clear, ownership activation or durable transition
  was added. Lost-state recovery, electrical protection, authorization and safe
  retained-profile exit remain activation blockers. Stage 3.2 is next only after
  coordinator review; this intent is not itself an actuator admission protocol.
- Isolated actual-module regressions with mocked boundaries: planning suite 424
  passed, one deselected, two warnings; lifecycle suite 26 passed, six warnings.
  These are not full HA or physical tests. No live HA or charger was contacted.

### 2.5.24 — Stage 2.3 unarmed lifecycle and regression (review required)

- Shared connector admission has an internal, unexposed reload-oriented quiesce:
  it latches before waiting for the connector lock, drains admitted operations,
  refuses queued/new ordinary writes and advances the generation. Cancellation
  leaves it closed. It neither cancels an already dispatched command nor stops
  producers, persists a transition, changes owner, or arms schedule mode. A future
  handover must coordinate all producers and durable state before any reload. The
  admission service belongs to the HA process: reloading an entry does not reset
  the latch. No production path invokes this future seam.
- An existing valid ownership document missing the entry binding is no longer
  silently filled in as legacy; status reports no recorded owner. A wholly absent
  document is still migrated as first use, but absence alone cannot distinguish
  a genuinely pre-ownership installation from a deleted/lost ownership document.
  Coordinator permits this first-use migration in this release because no integration
  action can activate schedule ownership. Resolving lost-document ambiguity is a
  mandatory blocker before any activation-capable release or safe recovery claim;
  a new marker by itself cannot prove a missing document was never lost.
- Startup installs the adapter guard and awaits metadata initialization before Auto
  startup, planning and restore. The controller restore consults admission before
  its immediate re-arm decision, retaining the saved plan and later guarded timers
  if denied. An older person's Stop is preserved if its transfer to Auto settings
  fails, including across intervening controller-record saves. Ordinary target
  dispatch is refused for simulated Morek-owned, corrupt, unresolved or known
  conflicting state.
- This release only initializes the supported Morek physical connector. An unrelated
  new charger requires no Morek record and does not create the document; a first
  supported connector can still initialize when the document is absent. A valid
  document with a missing binding is left untouched as uncertain, including an empty
  document (not produced by normal initialization). A stale record for the same
  physical connector or a duplicate entry is a conflict, not a new legacy binding.
- Offline/unresolved OCPP connector identity still fails closed unless a different
  connector number is established; no new assumption about aliases or unrelated
  offline stations was introduced: a configured alias, cpids mapping or past record
  alone is not a verified current physical binding. Duplicate contenders are held
  in memory; after restart an unrecorded duplicate is rediscovered only when it
  initializes, so a command admitted before discovery cannot be recalled.
  If restore denied an already-open window while offline, late metadata initialization
  does not itself replay that immediate start; future guarded timers remain. A
  reconnect/reload recovery policy is still future work, not an automatic retry.
  Regulator protection continues unchanged and can compete with schedule control;
  external HA/OCPP actors are outside these guards.
- Schedule mode remains unavailable and unarmed. A retained profile may continue
  enforcing its final 0 A after reload, pause or exit; no automatic clear or upload
  was added. Composite readback is not a profile inventory; a profile does not
  authorize a new transaction. Electrical protection, transaction authorization,
  retained-profile handling and safe exit require separate decisions.
- Checks: `python tools/run_isolated_lifecycle_tests.py` passed 26 tests with six
  warnings; `python tools/run_isolated_planning_tests.py` passed 416 tests, with
  one deselected and two warnings. The lifecycle suite loads actual integration,
  ownership, controller, Auto and handback modules with mocked HA/storage/charger
  I/O. The actual entry setup function is exercised through restore with mocked
  collaborators, not as a real HA config-entry setup. Neither suite is full HA or
  physical testing. `python -m pytest -q
  tests/test_ownership_lifecycle.py` failed before collection because the HA
  plugin imports Unix-only `fcntl` on Windows. Targeted Ruff and compileall,
  frontend build, `npm run check-dist`, and `git diff --check` passed; diff
  check reported Windows line-ending warnings. No live system was contacted.

### 2.5.23 — Stage 2.2 shared writer guards (review required)

- Corrected controller callbacks that ignored a denied Auto turn: hold, stray,
  person-hold, battery-probe resume, owed work, final-window stop and top-off.
  A denied callback does not dispatch or feed a success; an existing person Stop
  intent is retained. Denied owed automatic work is discarded rather than
  repeatedly retried. Final-window completion recording now happens after the
  boundary admits the action, not in the earlier timer callback.
- Controller adapters now share a connector-aware admission check immediately
  around ordinary start/stop, current and phase dispatch, including deferred,
  resend, setting, solar and restore writes. Start/stop also check before their
  controller preparation. The direct button fallback checks before acting, and
  deletion handback builds a guarded adapter. The own-mode API/webhook uses the
  same guard. Refused current/phase writes are not reported as sent. The existing
  connector lock is taken after controller/assignment locks; no controller or
  assignment lock is acquired inside it.
- Regulator current writes and regulator-classified stops deliberately remain
  permitted, including protective lowering and safety stops. They can conflict
  with schedule-only operation: status includes the conservative
  `site_regulation_conflict_unresolved` activation blocker, alongside the existing
  isolation, safety and authorization blockers. It is not a live assessment.
- A positively identified different connector number is unrelated even when its
  station is offline; ambiguous stations still fail closed. An offline OCPP
  connector 1 whose physical identity cannot be established still fails closed,
  including potentially unrelated or legacy chargers: aliases or a record without
  a verified current binding are not safe proof. Non-OCPP chargers and uniquely
  resolved unrelated connectors keep their ordinary behavior.
- These guards do not establish ownership before startup in every case, quiesce
  producers for handover, atomically change ownership/generation, recall in-flight
  commands, or control external HA/OCPP actors. Stage 2.3 must cover lifecycle,
  aliases/duplicates, restore and end-to-end regression. Protection remains an
  intentional competing writer until safety is resolved. Mode remains unarmed and
  unavailable; no profile uploads or Send safeguard changes were made.
- Isolated actual-module tests with mocked charger/HA boundaries cover controller
  callbacks, write categories, manual fallback, own-mode, deletion handback,
  queued admission and protection classification. They are not full HA or
  hardware validation. `python tools/run_isolated_planning_tests.py` passed 413
  tests, with one deselected and two warnings. Ruff, compileall, frontend build,
  `npm run check-dist` and `git diff --check` passed (the latter reported only
  Windows line-ending warnings). Full HA test collection remains blocked on Windows by the
  HA plugin's Unix-only `fcntl` dependency. No HA, deployment, restart or physical
  charger operation was performed.

### 2.5.22 — Stage 2.1 Auto boundary (review required)

- The Auto executor checks connector-aware ownership using the existing identity
  classification and admission store after taking its own lock. Valid Morek
  ownership blocks ordinary plan reconciliation, pending installs/stand-down,
  automatic controller turns (including starts, stops and resumes), solar and
  immediate-SOC-floor starts/stops, and pause expiry/resume. Manual start, stop,
  cancel, follow, pause, resume and manual API actions refuse before preparation
  with `legacy_execution_ownership_blocked`. Planning and observations continue.
  A proven unrelated connector and valid legacy ownership retain their behavior;
  unresolved OCPP identity or uncertain target ownership fails closed at this
  boundary. Non-OCPP chargers retain the existing path.
- This is a preparation/boundary check, **not** final dispatch serialization: the
  admission lock is released before controller operations, and there is no owner
  transition API. Already in-flight commands cannot be recalled. Stage 2.2 must
  guard direct current/phase writes, setting and deferred/resend/restore writes,
  direct adapter/button fallback, deletion handback and other bypasses using shared
  guards. Site regulator protection remains unchanged; its conflict with
  schedule-only operation must block activation, not be silently suppressed.
  Startup/restore ordering, alias/duplicate lifecycle and full end-to-end
  regression remain Stage 2.3. External writers remain outside SpotNav.
- Schedule mode remains unarmed/unavailable and is not ready. Independent safety,
  transaction authorization, transition and stored-profile/exit policy are still
  unresolved. Manual Morek Send safeguards are unchanged; no automatic uploads.
- `python tools/run_isolated_planning_tests.py`: 355 passed, one deselected;
  real modules with mocked HA/charger boundaries, not full HA integration or
  physical testing. Full HA tests require a supported Linux environment. No HA
  access, charger command, deployment or restart was performed.

### 2.5.21 — Stage 1.3 reactive planning and explanation

- Settings API writes continue through the existing store/reconciliation path;
  price events reuse the existing subscription. For capped target-SOC plans the
  existing SOC reader now reports even small actual changes and source loss;
  uncapped plans retain their original notification threshold. No browser is
  required and no Morek upload trigger was added.
- Calculations and subscription reconciliation are ordered; new attempts
  invalidate older work before price-event pause-lock waits. Snapshots retain
  their originating attempt, publication checks the settings revision, and a
  proposal-summary write checks its revision. Stale/refused work cannot relabel
  a prior plan as a newer settings revision. The shared Morek preview/Send
  builder also refuses a snapshot while a newer calculation is pending or its
  calculation reports an error such as a failed proposal-summary save;
  its existing manual Send interlock and identity checks remain intact. Manual
  and floor behavior and protection were not changed.
- Dashboard `plan.price_policy` and preview `price_policy` share one serializer:
  cap/basis, minimum/target/deadline, reason codes, exception periods/energy,
  minimum and target shortfalls, and estimated plan/exception costs and energy.
  `minimum_covered` is a projection, not a guarantee. Exception cost is the
  estimated total cost of exception energy, not a saving or incremental cost
  against a baseline; cost uses configured variable fees/taxes even if the cap
  uses the source price. Missing/refused data stays null, never measured energy.
- `python tools/run_isolated_planning_tests.py`: 334 passed, one HA-fixture test
  deselected, with two warnings. Tests exercise actual repository modules and
  the settings API, store, controller, SOC reader, planner and real execution
  boundary with mocked transport/persistence/charger; they are not full HA tests.
  The added HA SOC wiring tests and full HA collection remain unrun on Windows:
  the HA pytest plugin imports Unix-only `fcntl`. Run them on supported Linux/HA.
- Frontend build, check-dist and type-check, Ruff and compileall passed. The full
  frontend suite passed 2,342 tests (99 files) with two workers; the earlier
  unrestricted run timed out, and its reported timer-test timeout passed alone.
  `npm ci` reported five dependency vulnerabilities (two moderate, three high).
  No HA access, deployment, Morek profile action or hardware test was performed.

### 2.5.20 — Stage 1.2c capped Auto planning

- Cheapest-price Auto now resolves fresh actual SOC and the vehicle's effective
  target into target/minimum wall-energy deficits and uses the existing capped
  planner. Manual kWh plans have no minimum exception. Unknown prices never enter
  the unpriced/history fallback. Missing inputs and zero eligible energy stand
  down the current Auto-owned plan; the executor preserves independently owned
  manual and immediate-SOC-floor charges. The immediate floor remains independent
  and the cap is not a restriction on every manual or safety action.
- Capped Auto plans persist `strict_windows`, preventing top-off, leave-to-car and
  deferred replacement outside selected windows; older stored plans default to
  the legacy behavior. Failed policy stand-down is reported and remains retryable.
  Dashboard and preview plan responses carry price-basis, shortfall and exception
  facts. Solar/hybrid with a cap is explicitly unavailable, not an unpriced bypass.
- This completes Stage 1.2 software planning and legacy Auto reconciliation, not
  Stage 1.3 triggers, Morek ownership/activation or automatic uploads. Hardware
  behavior is not established, and full HA integration tests remain to run on a
  supported host. No live action or deployment was performed.
- Checks: 282 isolated tests passed against actual repository modules, including
  persisted-format settings to real calculation/preview, and real reconciliation
  and controller methods with mocked charger boundaries. One dependency
  deprecation warning was emitted. Full `tests/test_auto_controller.py` collection
  remains blocked on Windows by the HA pytest plugin's `fcntl` import; its added
  HA integration cases were not run. Ruff, compileall, frontend build, check-dist
  and diff-check passed.

### 2.5.19 — Stage 1.2c incomplete; Auto cap guard retained

- Added capped target-energy resolution using a fresh, non-estimated actual SOC,
  usable capacity, the resolved vehicle target and existing wall-energy/learned
  conversion. Fractional minimum percentages retain their precision. The normal
  target-energy path has been prepared to pass this deficit to the planner, and
  capped requests are excluded from the unpriced price-wait/history fallback.
- **This path is not active:** the existing Auto cap refusal remains. Removing it
  safely also requires reconciling an existing installed plan when the capped
  result is empty or inputs become unavailable, suppressing vehicle-limit top-off
  and leave-to-car behavior for capped plans (including restart), and encoding
  policy facts in proposal/status APIs. Hybrid/solar interactions also need a
  deliberate safe decision. Stage 1.2 remains unchecked.
- The isolated harness passed 268 cases against actual repository modules,
  including 12 capped-energy cases, one feeding the actual planner directly;
  it does not exercise Auto reconciliation or execution. Full HA/controller pytest
  collection remains blocked on Windows because the HA plugin imports `fcntl`.
  Ruff, targeted compileall, frontend build, check-dist and diff-check passed.
  No HA, charger, deployment or restart operations were performed.

### 2.5.18 — Stage 1.2b pure minimum-energy exceptions

- `PlanRequest.minimum_energy_kwh` is an optional, validated wall-energy deficit;
  no value or zero authorizes no above-cap exception. The capped planner searches
  known cheap and expensive intervals together under the period limit if cheap
  energy cannot reach that minimum. Minimum coverage takes priority, followed by
  minimizing exception energy and configured variable cost. The exception search
  is bounded by the minimum, never the higher target; unknown prices stay excluded.
- Capped results expose `minimum_shortfall_kwh`, the existing target
  `policy_shortfall_kwh`, and actual `exception_periods`/`exception_kwh`. Exact
  selected periods and costs include partial intervals. This is pure planner work:
  Auto still refuses capped settings, and `plan_unpriced` keeps its cap guard.
- **Stage 1.2 remains incomplete.** A subsequent slice must resolve fresh vehicle
  SOC, capacity, efficiency, and the effective target, then integrate and test the
  policy in normal Auto planning without an unpriced fallback. No subscriptions,
  uploads, activation or hardware actions were added here.
- Checks: the isolated harness passed 256 cases against actual repository planner
  modules; `python -m ruff check .`, targeted compileall, frontend build,
  `npm run check-dist` and `git diff --check` passed. Full HA collection remains
  blocked on Windows by the HA plugin's `fcntl` import.

### 2.5.17 — Stage 1.2a pure cheap-only planning

- `calculate_plan` now selects only published intervals at or below the requested
  price basis, respecting a numeric run limit and real gaps. Automatic periods
  have no hard run limit in this capped-only branch; unlike the uncapped automatic
  optimizer it does not apply a start cost or minimum block length. It maximizes
  eligible energy up to the request, then minimizes variable cost, and reports
  `policy_shortfall_kwh` or `no_eligible_energy`. Actual slot/period durations
  and cost include fractional slots and a clipped deadline interval.
- This is **not** full Stage 1.2: no minimum-SOC exceptions or vehicle-energy
  resolution were added. Auto still refuses capped settings and `plan_unpriced`
  still refuses capped requests. No production execution or automatic uploads
  have been enabled. Stage 1.2 and 1.3 remain unchecked.
- Checks: 234 cases passed in the isolated harness using the repository planner
  modules; `python -m ruff check .`, targeted compileall, frontend build and
  `npm run check-dist` passed. HA/controller pytest remains blocked on Windows by
  the HA test plugin's `fcntl` import. No HA or charger operation was performed.

### 2.5.16 — Stage 1.2 remains incomplete

- Added and tested a pure price-cap comparison helper using the existing fiscal
  arithmetic, including negative prices and major/minor conversion. It is not yet
  wired into selection. The existing fail-closed guards remain in place.
- Cap-aware selection, minimum-energy calculation, partial-window consistency,
  controller integration and the requested numerical acceptance cases remain to be
  implemented. Do not treat this helper as an enforced price policy.
- Checks: the isolated harness loaded the repository's actual planner modules and
  passed 216 cases (including the existing refusal tests and nine new comparison
  cases); `python -m ruff check .`, compileall, frontend build and check-dist passed.
  `python -m pytest -q tests/test_auto_controller.py` could not collect because the
  Home Assistant test plugin imports `fcntl`, unavailable on Windows. No HA or
  charger operation was performed.

### 2.5.15 — Stage 1.2 partial fail-closed guard

- Follow-up: `PlanRequest` carries `soft_price_cap` and `cap_price_basis`, and both
  `calculate_plan` and `plan_unpriced` explicitly refuse configured caps until
  the cap-aware algorithm exists. Eleven added pure tests and 196 existing tests
  passed in the isolated actual-module harness (207 total). This is still a refusal,
  not policy enforcement or a substitute for the requested optimizer tests.
- **Stage 1.2 is not complete.** Normal Auto planning now returns
  `planning_unavailable` / `price_policy_unavailable` for a non-null cap, including
  zero and negative caps. This prevents that calculation from reaching its normal
  uncapped planner or its unpriced-price-wait fallback. A disabled cap retains the
  existing path. This is a temporary refusal, not price-policy optimization.
- This does not establish charger-side protection: previously installed schedules,
  the independent immediate SOC floor and other execution paths are not audited or
  controlled by this guard. It does not implement cheap-slot selection, minimum
  exceptions, partial intervals, shortfall facts, either price basis, or reactive
  planning. Do not present a cap as enforced, and do not mark 1.2 complete.
- A controller regression test was added for positive, zero and negative caps, but
  could not run here: HA pytest's Windows plugin imports unavailable `fcntl` before
  collection. The isolated pure-planner harness passed 196 existing tests against
  repository modules; those tests do not exercise this controller guard. Ruff and
  Python compileall passed. The frontend was rebuilt for version 2.5.15.

### Stage 1.2 investigation — not implemented

- Stage 1.2 remains **unchecked**: the cap and ready-by minimum are still stored
  inputs only and must not be presented as effective protection. No planner or
  execution behavior was changed by this investigation.
- `calculate_plan` selects whole quarter-hour slots and its normal short-deadline
  path may choose every slot. `ending_at_need` shortens only the final displayed
  window, whereas legacy Auto execution consumes `proposal.periods`; Morek's
  profile builder consumes `proposal.shown_periods`. A policy implementation must
  make the actual selected windows and their energy/cost consistent on both paths,
  including a partial above-cap exception that is not the final selected interval.
- The normal controller's missing-price handling can call `plan_unpriced`, including
  on a short deadline. A cap-aware path must not admit that fallback as though
  unpublished prices were eligible. Vehicle facts include SOC age and estimated
  status, while the existing target-energy path can plan from the immediate SOC
  floor and uses learned wall energy or efficiency; policy integration must resolve
  freshness, the vehicle's effective target, and minimum energy consistently.
- Baseline: 196 existing pure planner tests passed on Windows by copying the three
  planner test modules, their helper and scenario fixture to a temporary directory,
  disabling pytest plugin autoload, and loading the **actual repository planner and
  pricing modules** through lightweight package stubs. This did not run HA fixtures,
  controller integration, settings tests, or any Stage 1.2 policy tests. No live HA
  or charger operation was performed.

### 2.5.14 — Stage 1.1 settings and API only

- The existing charger settings store and settings API add `soft_price_cap` (nullable
  currency/kWh, e.g. 0.10 for 10 cents/kWh), `cap_price_basis` (nullable
  `nord_pool` or `configured_variable_cost`), and `minimum_ready_by_soc` (nullable
  percent). Null cap disables it; zero and negative values are valid. A non-null cap
  requires an explicit basis; a basis can remain stored when the cap is cleared.
  `nord_pool` denotes the published source price as supplied, including anything
  already included by that source; `configured_variable_cost` denotes that price
  with the existing configured variable fees and taxes, not fixed/demand charges.
  The actual price-basis calculation and currency/source compatibility remain for 1.2.
- Missing legacy fields load as null; no 40% minimum is imposed. Omitted API fields
  retain their existing values, and null clears one. The minimum is distinct from
  the vehicle's immediate `min_percent` SOC floor. It must not exceed a numeric
  normal target. An unknown target stays unknown; the comparison is deferred until
  a numeric target is committed, including a remembered target on a vehicle switch.
  A vehicle-target propagation below a configured minimum is refused for that
  charger, so its earlier target remains; no adjustment is invented.
- **No policy enforcement, automatic uploads or Morek activation are implemented.**
  The stored cap is not effective protection. No default basis has been selected;
  the user must explicitly choose one. Replanning and explanations are Stage 1.3.
- Checks: frontend `npm run build`, `npm run check-dist`, `npm run type-check`, and
  `npm test` (2,342 passed); `python -m ruff check .`, Python compileall and
  `git diff --check` passed. Isolated AST-extracted code with stubbed dependencies
  exercised legacy load, cap/wire round-trips, invalid inputs, basis/target checks,
  partial updates, vehicle target resolution, and a stubbed in-memory store's reload
  and revision conflict. This is not the full HA test suite. The requested pytest
  settings tests could not start on Windows because HA's test plugin imports `fcntl`;
  run `tests/test_price_policy_settings.py` and the existing settings tests on a
  supported HA/Linux environment. No hardware, HA or deployment actions were performed.

### 2.5.7 displayed-window Send fix

- After updating to 2.5.6, the user removed the old schedule and found Send disabled.
  Read-only `status` showed removal Accepted, but current preview reason
  `target_stop_unsupported`. This was the old shortened-final-block guard, **not**
  removal locking Send. The user requested fixing it; no live send/clear is part
  of implementing this change.
- `_proposed_profile`, shared by preview and Send, now converts **shown_periods**
  instead of the whole-slot **periods**. Shorter final blocks are accepted. All
  existing identity/current/pause/revision/future/horizon/block-count safeguards
  and the preview fingerprint remain. Changing only a shown end invalidates the
  old fingerprint. No silent fallback to whole-slot ends is allowed.
- Wire offsets are integers. Fractional start timestamps round up and ends down
  by less than one second; windows that disappear under rounding are refused.
  The UI explicitly says the sent schedule uses fixed start/stop times and will
  not adjust itself according to measured energy. Old-backend refusal messages
  now say to update rather than implying shortened windows cannot be sent.

### 2.5.6 code changes after the wire-trace investigation

- Keep stack 1 and the exact calculated ON/OFF windows. There is no automatic
  switch to stack 4, clear/reinstall workaround, or repeat upload. The original
  charger-side cause is **not proven fixed**; this release fixes the deficient
  single-read verification lifecycle and overly implicit verification claims.
- Accepted Send gets an immediate composite read, then at most three follow-up
  reads at delays 30/45/45 seconds if unverified. Timers use HA `async_call_later`,
  not browser polling. Another Send or clear cancels the previous timer; upload
  identity is checked inside the per-charger lock so a stale callback cannot
  replace newer state. Entry unload cancels the timer. A restart's persisted
  pending flag is reported as interrupted rather than claiming a live timer.
- `readback` retains reported duration/unit/scheduleStart and atomically rejects
  malformed, unsorted, duplicate, negative, nonfinite or non-zero-first-offset
  periods. Verification never substitutes requested coverage for an absent
  reported duration. Limits/transitions must match and coverage must include one
  hour after the final stop. The 90-second tolerance is now explicit in the UI,
  with maximum observed drift and a **NOT exact** label for drifting matches.
- Pending reads do not imply the sent current limits are active. Exhausted
  follow-up checks stay unverified and emit a stable warning. Summary logs
  contain action, ACK/readback status and comparison reason only, not raw frames,
  tokens or household context. The removal button now says **Remove SpotNav
  schedule**, because 42001 contains the real plan, not artificial test windows.
- No live send, clear, priority change, file deployment or restart was performed
  during this code implementation. The previous investigation's real stack-1
  profile remains installed; the user reported the car unplugged at that time.

### Follow-up after installing 2.5.5 (2026-11-08)

- The installed manifest was confirmed at 2.5.5. The user resent the calculated
  profile at **16:44:34** and fetched at **16:44:37**: upload Accepted, effective
  readback Accepted but only **16 A**, verification false. HA startup activity
  was at 16:43–16:44 **before** the send, so a restart *between* this send and
  readback does not explain this repeat. No cleanup attempt is recorded.
- The raw Core log contains no current wire frames for this send/fetch and no
  relevant SpotNav/OCPP error in that interval. Historical frames from November
  6 exist, but do not establish what happened to the November 8 request.
- Read-only HA OCPP `get_configuration` queries returned `SupportedFeatureProfiles`
  including SmartCharging, `ChargeProfileMaxStackLevel=5`,
  `ChargingScheduleMaxPeriods=8`, `MaxChargingProfilesInstalled=5`, and rate units
  reported as `Current,Power`. The five-period, stack-1 request fits the reported
  period/stack bounds. Maximum profiles is capacity, not the installed count.
- Read-only HA OCPP entity states reported connector Available, measured current
  0 A, and power 0 kW, consistent with the user's unplugged report. Current-limit
  entities also showed 16 A; do not confuse these with measured current.
- Root cause is **not established**: effective composite calculation while idle,
  another default/transaction profile taking precedence, or Morek firmware
  behavior remain possibilities. OCPP 1.6 does not provide a standard inventory
  call for retrieving the stored profile 42001. Next useful diagnostic is a
  narrowly scoped wire trace of an explicitly authorized send+immediate fetch,
  preserving response duration/unit/periods and checking any competing commands.
  This follow-up investigation performed no Send, Clear, restart or live-file edits.

### Authorized wire-trace investigation, 16:48–16:54 on 2026-11-08

- The user explicitly authorized enabling logging and triggering actions for
  investigation. OCPP INFO and integration DEBUG logging were temporarily enabled.
  Filtered request/reply payloads were analyzed in memory, not exported into Git.
  At the end these three diagnostic loggers were set to WARNING. HA was not
  restarted and live integration files were not edited.
- A fresh SpotNav Send at 16:48:48 sent the correct five-period real plan on
  connector 1; Morek's correlated wire reply was Accepted. The actual composite
  reply requested for 43,200 seconds contained one 16 A period. This confirmed
  that the initial mismatch was not frontend rendering or dropped decoder rows.
- Controlled changes to the *same ID 42001*, keeping all real ON/OFF windows,
  tried stack 2, a start timestamp two minutes earlier (offsets adjusted), and
  explicit schedule duration 43,200 seconds. Each was Accepted but initially
  returned flat 16 A. Stack **5** was rejected as NotSupported at 16:50:01;
  the user confirmed this firmware only accepts levels below 5. Do not mistake
  the advertised maximum value 5 for a usable stack level 5 on this Morek.
  The warning from `ocppv16.py:1086` was from this diagnostic probe, not the
  user's original stack-1 request. Stack **4** was Accepted and first produced
  all five expected transitions at 16:52:25. Do not assume this alone proves
  that a permanent priority increase is necessary or safe.
- Selective clears used exactly `ClearChargingProfile {"id":42001}` and received
  Accepted; no other IDs or generic clears were used. The final action restored
  the *real calculated plan through SpotNav's own Send*, stack **1**, at
  **16:53:13**. Immediate readback initially had an extra 16 A period until
  approximately 16:54, then the expected overnight transitions. At **16:54:06**
  a fresh fetch reported **0 A now**, then approximately **22:00:57 16 A,
  23:00:57 0 A, 00:15:57 16 A, 01:00:57 0 A**. SpotNav's `verified` became
  **true** under the existing 90-second transition tolerance and horizon check.
- Thus the final stored Sent record and station readback were consistent within
  tolerance at stack 1. Do not automatically change the production stack to 4
  based on the earlier probe. Root cause is still not isolated: stack selection,
  retained state and scheduler activation/recalculation may have interacted.
  Same-ID replacement/clear behavior cannot be proved from composite output.
  Observed composite transition seconds drifted with query time, and station
  `scheduleStart` lagged HA by several seconds. A strict second-accurate schedule
  has **not** been established. No concurrent non-diagnostic profile-writing
  traffic was observed in the captured request window, which does not rule out
  preexisting profiles or other controllers outside that window.
- **Final live state:** real SpotNav profile 42001 remains installed at stack 1,
  Auto was not resumed by the investigation; final persistent 0 A remains part
  of that profile. The user reports the car unplugged. This is schedule readback
  verification only, not a physical charging test. No new release/code change
  was made in response to this trace. Future work should expose timing/coverage
  and verification tolerance in the UI rather than implying exact equivalence.

### Fast preview during frontend development

- Local iteration: `cd frontend; npm exec -- vitest run test/card-fill.test.ts
  test/morek-view.test.ts`; `npm run type-check`; `npm run build` creates
  `custom_components/spotnav/www/spotnav-card.js`. This needs no HA deployment
  and tests card behavior, but jsdom does not provide real browser layout.
- To see frontend-only layout changes **in HA** without a Git commit/push or
  Marketplace refresh, a *temporary* development procedure (not yet tested):
  after **explicit permission to edit the share**, back up the installed
  `\\HOMEASSISTANT\config\custom_components\spotnav\www\spotnav-card.js`,
  copy only the locally built bundle there, and open HA in a new browser tab
  with developer tools **Disable cache** enabled and a full page reload. The
  integration serves this file at `/spotnav/spotnav-card.js` with long-lived
  cache headers and a version+digest query computed during HA setup; copying
  bytes alone does not refresh that URL. A full reload with cache disabled
  forces a fetch despite the unchanged URL, and reloads the custom element
  registry. Inspect the Network response to confirm the expected bytes. Restore
  the backup after experimenting; do not deploy by permanently editing live
  integration files. This procedure is **not yet verified on this HA install**.
- Backend changes such as the preview WebSocket response **cannot** be tested
  merely by replacing the JS bundle: the HA integration code must be installed
  and loaded, normally via Marketplace + restart. The 2.5.3 backend was confirmed
  installed at the time of the first user-initiated send; check the installed
  manifest rather than relying on this historical observation.
- Alternative fully local UI loop: exercise the DOM/tests with canned WebSocket
  responses; it is quicker but not an actual HA visual verification. Never
  point a dev server at the HA authentication token or expose the share as a
  public static directory.

- After the 2.5.2 changes: 2,331 frontend tests passed; frontend type-check,
  `npm run build`, `npm run check-dist`, Python Ruff and compile checks passed.
  Four pure Python test functions were exercised with isolated AST extraction;
  **this is not the full Home Assistant test suite**. Python pytest could not start
  with the installed HA test dependencies on Windows because `fcntl` is Linux-only;
  WSL Ubuntu on this PC had Python 3.12, not the project's Python 3.14.
- After the 2.5.3 layout/preview work: 2,335 frontend tests passed;
  type-check, build, check-dist, Ruff and Python compile checks passed. Five
  pure Python tests were exercised by isolated AST extraction (including the
  preview calculation); full HA Python pytest remains unrun on Windows.
- For 2.5.4's text-selection change: 2,336 frontend tests passed; type-check,
  build and check-dist passed. Browser/HA text selection is not yet verified.
- For 2.5.5 selective cleanup: 2,338 frontend tests passed; type-check, build,
  check-dist, Ruff and Python compilation passed. Twelve isolated Python cases
  passed, including exact-ID cleanup, readback after Accepted/Unknown/timeout,
  and refusal of missing/wrong confirmation. Full HA pytest remains unrun.
  No live send or clear was performed for this implementation.
- For 2.5.6 readback handling: **2,341 frontend tests** and **22 isolated Python
  cases** passed; type-check, build, check-dist, Ruff and Python compilation passed.
  Coverage includes delayed activation, finite read retries, timeouts/reconnect,
  coverage missing/short, drift disclosure, manual refresh, stale send callbacks,
  cleanup cancellation, unload including an in-flight read, and restart state.
  The isolated Python runner is not the full HA pytest suite. The new timer
  lifecycle has not yet been installed or hardware-tested on HA.
- For 2.5.7 displayed windows: **2,342 frontend tests** and **29 isolated Python
  cases** passed; type-check, build, check-dist, Ruff and Python compilation passed.
  Tests cover a real Send of two shown blocks with a shortened fractional-second
  end, preview/Send agreement, stale fingerprint refusal after changing that end,
  inward rounding, and retained unpriced/stale/empty/past/too-many-block safeguards.
  Full HA pytest remains unrun on Windows; the new conversion is not yet deployed
  or hardware-tested. No live schedule was sent or removed during this change.
- Tests: `tests/test_morek_schedule.py` and `frontend/test/morek-view.test.ts`.
  Run the Python tests on Linux/Python 3.14 with project test dependencies, and
  add integration tests for alias resolution, WebSocket access and OCPP responses.
- On the next HA check: confirm the **installed** manifest version. Before any
  further send, determine whether HA restarted around 16:17 on 2026-11-08,
  whether another controller has an active profile, whether the station retained
  profile ID `42001`, and whether measured charging differs from the effective
  16 A limit. Refreshing from Morek does not install a profile; generic clear
  may remove other controllers' limits, so do not use it as cleanup.
- When modifying the card, bump the manifest version, run `npm run build` from
  `frontend/`, and commit the built bundle in `custom_components/spotnav/www/`.
  A push to `main` is not an HA deployment: Marketplace checks custom forks on
  its own schedule, downloads an offered update, and HA must load the new code.
