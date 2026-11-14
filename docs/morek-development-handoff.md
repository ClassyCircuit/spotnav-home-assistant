# SpotNav Enhanced / Morek development handoff

Last updated: 2026-11-14. This file is a **public-repository handoff**, not a place for
passwords, access tokens, HA configuration exports, logs, or private household information.
Re-check the live system and Git state before acting; observations below may become stale.

## Current handoff and approved direction

**Stage 10 is done locally:** 10.1 Charge Now backend, 10.2 sidebar controls and
10.3 partial-price-horizon planning are checked in the roadmap. The user says Stage
10 is done; do not reassign it as incomplete. Local mocked tests do not establish
installed version, physical charging or future runtime success. At this handoff,
the source manifest was 2.5.98 and the latest commit was `ebee12b5`; Stage 14.1 later
raised the working-tree manifest to 2.5.99, then 2.5.100 after review and 2.5.101 after a price-wait correction (uncommitted at that time). Recheck Git
and deployed version on arrival. The current coordinator initialization is
`prompts/coordinator-handoff.md`.

**Charge-session card (2.5.127, evidence hardening 2.5.128):** the sidebar now shows whether a plugged-in car is authorized/has a transaction and warns when it may not charge (see its entry below); local mocked only.

**Open priorities:** Stage 9.5 (automatic recovery and visible blockers) and 9.4 (SpotNav log
view) are implemented locally with mocked tests (2.5.117 / 2.5.113); neither is deployed or live-verified. 9.5 is
only partly met: a never-dispatched Resume after restart needs a fresh explicit Resume (see its entry below).
5.7b2 measured charging/health binding is implemented locally (2.5.119, see its entry); 5.7b3 local acceptance is partial (see its entry); browser checks remain unrun.
Follow the current roadmap and user's selected priority rather than stale historical
directions. Preserve the user's approved one-time clean-start risk, explicit Stop,
electrical protection and actually recorded uncertain dispatched operations.

**5.7b continuation:** The user reports the sidebar is no longer blank; 5.7b1 is
complete, with the local collision fix and browser checks recorded below. The exact
deployed version and cause of the improvement were not independently checked. 2.5.67
withdraws stale dashboard data after failed refresh, but charging/power binding and
full local acceptance remain open in 5.7b2–b3. The HA-plugin suite could not start on
Windows because `fcntl` is unavailable; it remains unrun. These are local development
tasks, not permission to deploy or operate the user's charger.

**Automatic restart recovery requested:** the user does not want to press a
reconfirmation button after ordinary HA restarts. Local 2.5.98 recovers a settled
Resume from matching durable evidence, but interrupted Resume and other recovery
cases are only partly addressed by Stage 9.5 (2.5.117, see below: an undispatched Resume still needs a fresh click). Unknown outcomes remain
visible and are never blindly retried; no live action is authorized by this note.

**Single Morek execution path:** the user no longer wants a runtime switch back to
the legacy controller or a separate dynamic handback protocol. Replace Morek's old
execution behavior with the schedule owner; retain shared legacy behavior for other
chargers. The user can disable the integration in HA, which may leave a schedule or
0 A limit on the charger. Preserve and assess existing ownership/held-exit records,
uncertain outcomes and protection guards; do not delete them blindly, auto-clear a
profile, or silently arm an unsafe migration. Historical handback requirements below
are superseded as product requirements, not as permission to bypass safety evidence.

**BMW limit and current monitoring:** the user relies on the BMW's own configured
charge limit to stop charging at its target, not a second SpotNav live SOC-stop
controller. The user confirmed (2026-11-14) the BMW will stop at its configured 80%
limit: an agreed operating assumption, user-confirmed and not agent hardware-verified,
and not a blocker. The car's setting and SpotNav's planning target are separate and the
app does not set the BMW limit. Stage 15 reserve is extra allowed time to reach the
target, not intended energy beyond it; its allowance energy/cost is labelled separately
and only measured cost is actual. The app must still show useful
current charging and execution health: use genuine available status and measured
power/energy, label freshness and source, distinguish reported state from measured
flow, and show unknown/offline/mismatch/errors honestly. Basic monitoring belongs in
5.7, not only later history or Stage 11; no source or physical behavior is assumed.

**Stage 11 — adaptive Morek estimates (superseded 2026-11-14, NOT implemented):** the user's wish stands:
charging-time and target-SOC estimates should improve from actual charging and a shortfall should trigger
safe replanning, reusing the existing learned-power, learned-energy and plan-watch code. That scope was
migrated, with no loss, to roadmap Stage 15.9 (energy-per-SOC learner on the Morek path), 15.10 (behind-plan
check and power feed, deferrable) and 15.11 (display and reset); the roadmap's Stage 11 section holds the
exact mapping and is closed `[>]`. Source fact (reading only): nothing is sampled by the learners under Morek
schedule ownership, while the stores already feed the Morek planner's input evidence. Do not infer
measurements from a schedule; do not assign 11.1/11.2 or call them done. Post-installation work, not a 5.8
prerequisite.

**Stage 5 deployment clarification:** once development is complete and reviewed,
the user intends to merge the current branch to `main`, install it in HA and test
the deployed system personally. 5.8 is a user-owned milestone, not an LLM task or
authorization to merge, deploy, restart, activate or operate hardware. LLMs still
perform local automated/mocked tests in 5.6–5.7 and can help interpret logs when
asked; HA access and live actions require specific approval. Keep deployed behavior
unverified until observed, and preserve all safety and uncertainty interlocks.

**Stages 8–9 scope:** retain the desired measured-versus-sent history, costs,
savings and monthly insights, extending existing session/savings APIs and Stage 6
evidence rather than duplicating them. Existing costs are not proof of preserved
historical tariffs. The user does not need separate themes or extra accessibility
polish; keep practical desktop/mobile usability and readable warnings. Stage 9
tracks HA Core logging and focused automatic recovery; 5.8 remains the initial
installation and user-directed testing path.

**Stage 6 wording review:** genuine charging history remains later work. Existing
session store/recorder/API, energy-register discovery and power integration are
groundwork to inspect and reuse, not proof of a complete Morek measurement history.
The limited `debug_day.py` data is diagnostic, not an established production history
feed. 5.6a did not establish a trustworthy Morek power/active-transaction source.
Stage 6 remains open and is not a 5.8 installation prerequisite; installed-source
inspection or hardware access requires the user's specific approval.

**Stage 7 scope clarification:** the 5.4c real-data price chart, proposal overlay
and its locally tested interaction groundwork already exist. Stage 7 now lists only
remaining available-day navigation, practical interaction fixes, aligned evidence tracks and
real-data price insights. Do not rebuild the chart or repeat 5.4c. Its full offline
HA-plugin suite is still unrun; actual HA and physical touch remain unverified.

**2026-11-12 agreed daily controls:** use two simple sidebar controls in the final
design: **Pause / Resume Auto** and **Charge Now / Return to Auto**. Pause requests
that charging remain held until explicit Resume; Return to Auto cancels only the
temporary Charge Now override, so charging may continue when Auto selects now.
Pause/Resume under schedule ownership remains 5.6b; Charge Now remains optional
Stage 10, now locally implemented. Charge Now does not override an existing explicit pause: the
user must Resume first. Neither a request nor ACK proves physical stop.

**Historical task status:** earlier 5.5–5.8 notes below describe prior versions;
refer to the current roadmap and source for present status. No live access or
activation is authorized by this note.

**Historical 2026-11-12 roadmap consistency review (superseded by 5.5d–5.5f):** the next assigned work remained 5.5d,
not completed. The current uncommitted tree includes the 2.5.44 manual-owner
admission fix and an additional `async_handover_unarmed` store-method draft;
the latter is not called by the admission path or covered by handover tests. Preserve
and evaluate it rather than assuming either safety or completion. The roadmap now
distinguishes 5.4c's implemented real-data chart from later chart extensions, carries
the offline HA-plugin suite gap forward, and records the default-branch/update issue.
No HA access or code change was performed in this documentation review.

**Historical 2026-11-12 task sizing:** the user requested explicit, bounded substages instead
of repeatedly assigning an oversized block. The roadmap now records completed
5.5a–5.5c groundwork and splits remaining 5.5d–5.5f, 5.6a–5.6c and 5.7a–5.7b.
5.8a–5.8b describe user-directed installation/activation, not permission for live
actions or a new hardware-testing stage. Assign **5.5d only** next. The full 5.5,
5.6 and 5.7 umbrellas remain open; dispatch remains unarmed and the deferred 5.4c
HA-plugin suite remains unrun. Follow the numbered checklist rather than historical
handoff entries; do not repeat completed groundwork or bundle future substages.

**Charge Now refinement:** The user chose a fixed end with 30-minute, 1-hour,
2-hour, 3-hour and custom-end choices (1 hour default). It may be set before
plug-in; plugging in later uses the remaining time. A new request replaces the
end time from now. Show the price and whether it exceeds the cap in one
confirmation; unknown price or missing Auto-planning SOC does not block this
explicit request. An existing Pause/Stop requires Resume first. Expiry or
Return to Auto follows the latest valid plan, potentially without interrupting
charging; if no plan can be applied, end the override at its scheduled time and
resume Auto when possible. Pause/Stop during Charge Now cancels the override and
applies the pause; Resume later returns to normal Auto. These decisions do not
authorize live operations, weaken execution/protection guards or establish
implementation.

**2026-11-12 Charge Now decision:** the user wants this as an optional feature
after initial installation and user-directed testing in 5.8, not a release
prerequisite. Roadmap Stage 10 records it; it is not implemented. Default to one
hour with other durations. On expiry or **Cancel Charge Now**, return to the
latest valid automatic plan and reconcile the Morek schedule. If Auto selects
the current time, charging may continue or restart immediately; cancellation
is not a persistent Stop/pause and must not suppress that automatic window.
Use the same schedule owner; report offline/unknown results honestly. Later
implementation, deployment and physical tests require separate authorization.

**2026-11-12 user clarification:** Morek is reported to handle household load
protection natively. The requested SpotNav Morek mode only schedules charging
on/off windows; do not implement household load balancing or change amps dynamically
in response to house load. Scheduled 0 A/allowed-current limits are window controls,
not a load regulator. This is the user's report, not an independent verification of
the actual installation. Existing protection, regulator configuration, activation
blockers and electrical limits must not be changed or bypassed without explicit
authorization. Resolve any existing regulator conflict before activation; do not
turn it into a new SpotNav load-management project or a separate hardware-test stage.
Historical notes below describe previous understanding, not a competing requirement.

**2026-11-09 coordination update:** the roadmap now begins with a concise numbered
task checklist. Completed audit/ownership/admission/identity/start-evidence work
through 2.5.13 is Stage 0, not work to repeat. **Stage 1 price-policy settings,
planning and reactive explanations are implemented through 2.5.21, pending
coordinator review.** Actual isolation is Stage 2 and remains
incomplete/unarmed. The proposed additional unwired durable
pre-dispatch helper was never assigned and is not the next task. Detailed historical
versions/deployment facts below must not override current Git or the new checklist.

Read [charging-dashboard-roadmap-active.md](charging-dashboard-roadmap-active.md) (the only work queue;
historical stage text is in [archive/charging-dashboard-roadmap-2026-11-14.md](archive/charging-dashboard-roadmap-2026-11-14.md)) for the user's
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

**2026-11-14 — Stage 15 finalized (docs only; no code, version, deployment, HA access or
charger command; supersedes the three earlier same-day Stage 15 planning entries):** the
roadmap's Stage 15 is rewritten as start-ready substages 15.1–15.11 plus optional evidence
tasks E1/E2, with order and status in the roadmap. Settled with the user: a 10% configurable
time reserve (soft-cap rules unchanged; rounded only to dispatch resolution, no mandatory slot); guarded **automatic schedule repair** after repeated
confirming readbacks of a materially wrong effective schedule (a single odd readback only
rechecks; a correct active charge is left alone); a guarded **start after a confirmed reboot**
that leaves a plugged-in car clearly unauthorized, after *affirmative* no-session evidence and no
unresolved previous request (a reconnect is not a reboot; changed point object/link edges are
connection evidence only); and the user's repeated requirement that **charging must be enabled**:
SpotNav establishes it through the existing guarded start path on plug-in/recovery and verifies
evidence, never toggles the switch blindly, an accepted start is not proof, and off/unconfirmed
shows as not yet ready (backend 15.5, UI 15.7; the switch is a derived OCPP entity, independent
authorization unverified). Corrections same day: repair needs a fresh latest readback plus an
earlier valid same-connection observation ≥30 s older (not both ≤30 s old), preserves Pause/Stop,
wire continuity is not a physical guarantee, brief 16 A unverified; no mandatory periodic OCPP
readback (optional future monitor, default off); new **15.8** reconciles late cumulative register
totals of closed sessions against timeline placement (old 15.8–15.10 are now 15.9–15.11);
engineering defaults are not labelled user decisions. These replace the earlier "reconnect is read-only, never
resends" and "manual restore only / ask the person to replug" recommendations.

Source-only audit (manifest 2.5.128, **not live-verified**; the roadmap's audit table has the
classification): Stage 14 stability, the session coordinator's per-connection-token start
(including `boot:`/`offline:` tokens and its tests), the read-only `fetch` readback and compare,
the Stage 6.2 evidence store with unobserved/unknown-placement energy, and both learned stores
are reused. Gaps found: no link-level signal (reconnect handling is only the control-entity
availability edge and the connector sensor; `morek_offline` has no timer; `charger_generation`
is read with `getattr` and only the test fake sets it, so the installed integration exposing it is
unverified); no readback at reconnect, startup or periodically and no confirmed-mismatch notion;
`force_sync` cannot repair under Pause/Charge Now; fixed 180 s/90 s freshness bounds; **nothing is
sampled by the learners under Morek schedule ownership** (`_check_plan` runs only from `_arm_watch`
on Auto-owned windows); learner trust is symmetric and has no gap/age exclusion, display or reset;
no reserve exists. Research verdict kept: no supported OCPP history retrieval was found and no
on-demand Morek history storage is assumed; one earlier outage showed roughly 120 replayed
readings, otherwise buffering is uncharacterised (E2, optional). HA OCPP stamps readings at
receipt. Nothing here guarantees charging; "accepted", "reported" and "measured" stay separate.

**2026-11-14 — Roadmap audit and consolidation (docs only; no code, version, test run, HA access or
charger command; Git: edits uncommitted at HEAD `6a50a7ae`, manifest 2.5.128):** (1) The roadmap gained a
**"Canonical remaining work queue"** (A implementation, B outstanding local review/acceptance, C user-owned,
D later features, E closed) and a **"Stage 14 non-regression contract"** that binds every Stage 15 substage
to the existing worker, session coordinator and Stage 14 mechanisms (protected active windows, 14.4 price/cap
interruption, 5-minute SOC tolerance and 2 s coalescing, dedup, uncertainty and rejection retry, Stop/Pause/
Charge Now ownership, 14.5 progress accounting, 14.6 evidence), with the Stage 14 test files each ◆ substage
must rerun. (2) Three regression traps in the earlier Stage 15 text were corrected after reading
`window_release`, `connector_evidence`, `_send_profile_shared` and the learner seams: the 15.1 reserve is kept
out of `window_release`'s energy/cost/slack arithmetic and plan totals; the 15.6 freshness change does not
widen the evidence that gates 14.2/14.4; 15.8 does not alter the session energy that 14.5 reads. 15.4 now
states exactly which guards `repair` may and may not bypass. (3) Stage 15 queue order is
15.1 → 15.2 → 15.5 → 15.3 → 15.4 → 15.6 → 15.7 → 15.8 → 15.9 → 15.11 → 15.10 and unnecessary
prerequisites were removed (15.8 and 15.9 no longer wait for 15.2). (4) Stage 11 is closed as superseded and
migrated (see above); umbrellas 5.4 and 5.6 are closed as locally implemented because all children are
`[x]` (review and the unrun 5.4c suite stay open in 5.7b3); 9.6/9.7 are checked; 5.1 stays open only for
the user's visual approval; 5.7b3 stays open (browser, full worker/planning and 5.4c suites are unrun).
Nothing was marked live- or physically verified; no unrun mandatory acceptance was closed.
Follow-up correction (docs only): 15.4a kept the repair dispatcher disabled until 15.4b; 15.4b enables it locally (see its entry, uncommitted); 15.9a is capture-only with promotion/revalidation in 15.9b; 15.5's confirmed reboot requires a
boot signal (connection restoration is read-only validation).

**2026-11-14 — Roadmap split (docs only; no code, version, test run, HA access, charger command or commit):**
the ~3,800-line roadmap was moved unchanged (plus a historical banner and one corrected link) to
`docs/archive/charging-dashboard-roadmap-2026-11-14.md`; `docs/charging-dashboard-roadmap.md` is now a
redirect and **`docs/charging-dashboard-roadmap-active.md` is the only work queue** (ordered queue of 30
substages, migration map, Stage 14 non-regression contract with source and test references, approved policy,
verification ledger). 15.1, 15.4, 15.7 and 15.9 were split into a/b halves (parent numbers are the stable
ids); Stage 7 and 8 were audited against the shared sidebar, ECharts chart, `get_charging_history` (no
frontend consumer yet), the thin shared `history`/`insights` contracts and the existing `day_average_price`
savings basis, and re-cut (7.3 → 7.3a/b, 8.2 → 8.2a/b, 8.3 → 8.3a/b) with open decisions D1–D3 recorded rather
than assumed. Older entries below that say "the roadmap" mean the archived text. Edits are uncommitted.

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

**User restriction (2026-11-14): ONLY FAST tests.** No full isolated runner, browser/Playwright or broad suites; run focused
module files individually with a short timeout and report unrun checks. (Also recorded in the active roadmap §4.)

### 2026-11-14 — Stage 15.7b check/repair/reboot/offline wording and banner (2.5.138; local mocked; coordinator reviewed; no live HA/charger action)

- **15.7b review corrections (still 2.5.138, UI only):** (1) unknown check no longer promises a retry (“Couldn’t check … at {time}.”; only verification/upload-pending wait states imply a follow-up). (2) `boot_start.state==requested` is an intent token minted before the request, so it never claims SpotNav asked: `bootItem` uses `readiness.session_start` dated `session_start_at >= boot.at` — accepted ⇒ “asked and accepted”, starting ⇒ “being asked”, blocked/rejected ⇒ withheld (warning, start from Morek), other ⇒ unknown; no/pre-boot association ⇒ “restart recovery pending and unconfirmed”. `charge-session.js` no longer counts the token as “asked”. (3) `needs_person` copy (banner and check note) is now “Automatic repair is paused for this attempt … check the charger and the SpotNav logs”, no global “won’t change” promise. Tests cover all three.

- **New `frontend/sidebar/schedule-check.js`** (pure, read-only): `scheduleNotes(status, now)` returns subdued notes shown in a separate `#schedule-check` section below the primary charge-session card, so a healthy readback never softens or replaces Pause/Stop/fault/uncertain/offline/not-ready. Reads additive `reconciliation.check` (`healthy`/`unknown`/`differs_unconfirmed`/`differs_confirmed`, `at`, `events[-1].trigger==post_repair`), `reconciliation.repair` (`needs_person`, `gate_enabled`), the blocker code, `link {state, since}` and `readiness.boot_start`. Wording: “Checked at {time}, nothing needed changing”; “Couldn’t check … will try again”; “one odd reading isn’t enough to act on”; re-sent schedule “now matches the plan. That doesn’t prove the car is charging”; boot requested = asked once, blocked = did not ask and who acts; lost link = “Connection lost at {time}”; quiet link = “unchanged since {time}”. Level is never `ok`.
- **Fail closed:** a check that is malformed, unknown class, future-dated or over 24 h old shows “not readable/over a day ago”, never reassurance; a healthy check older than a lost link says it predates the loss; absent fields (older backend, never run) show nothing; the panel hides the line for a stale/failed status.
- **`recovery-banner.js`:** `repair_needs_person` (or `repair.needs_person` while the latest check is not healthy) is an error that outranks timed blockers but not an uncertain write or a rejection; `repair_deferred`, `repair_spacing` (with the budget `next_at` when valid), `repair_unconfirmed` are calm info, `repair_gated` a warning “nothing was sent”. None offers a resend or says re-plug is always needed.
- **`charge-session.js`:** offline and judged last-known copy start “Connection lost; last confirmed “{state}” at {time}” with “not known”, no failure/stopped claim; kinds, priorities, posture and the measured-flow/not-ready conflict are unchanged.
- No backend, write path or i18n change (sidebar copy is English literals as in 15.7a). Tests: `frontend/test/schedule-check.test.ts` (wording per state, malformed/future/old, older backend, panel with mocked renderer asserting no write calls); related sidebar tests pass (157). `npm run build`, `check-dist`, `type-check` pass. No browser suite, HA or charger action.

Coordinator review: truthful retry/request wording and blocked-start guidance corrected; focused 46 UI tests passed (3.07 s), final copy 19 tests passed (3.13 s), build/check-dist passed. The corrective agent also ran a full frontend suite contrary to the fast-only restriction; it was not repeated by the coordinator and is not required for later substages. No browser/live verification.

### 2026-11-14 — Stage 15.7a plug-in authorization UI and freshness adoption (2.5.137; local mocked; coordinator reviewed; no live HA/charger action)

- **Freshness:** new `frontend/sidebar/evidence-freshness.js` reads the 15.6 `readiness.freshness.quantities` per reading (`status`, `transaction`, `charging_control` for the control switch, `power_w`, `current_a`, `energy_register_kwh`). With a judgement, `fresh` means judged `current` (a quiet connector stays current; shown as "unchanged since {time}"); `strict` (old 180 s and the reading's own `fresh` flag) is kept only as a fact ("too old for automatic actions"). No `freshness` block (older backend) keeps the strict 180 s display. A present but malformed block, unknown state, missing quantity, bad `age_s` or a `reported_at` that is not this reading's `observed_at` is `unknown`. A future reading timestamp is never evidence; failed/old payload refresh still shows unknown (`observationFreshness`, unchanged).
- **Copy/state (`charge-session.js`):** result `posture` (`authorized` needs an observed transaction or measured flow; `waiting_on_purpose`; `pending`; `at_risk`; else `unknown`); "We asked the charger to enable charging. Waiting for the charger to confirm." for an accepted request; accepted without a transaction stays a warning. `charging_enabled` `not_ready` (off/unconfirmed/malformed) while plugged in without a transaction is "Not yet ready to charge" with who acts (or "asked"/"once its checks pass" while the request or 15.5 `boot_start` is pending); it adds a note to an existing warning. **Correction (same stage):** an explicit `not_ready` now also outranks an old transaction, a suspension with a schedule hold, and a bare reported "Charging" (all show "Not yet ready to charge", never `scheduled_wait`/authorized); user Pause/Stop, fault, offline and unknown still win, and fresh measured flow stays "Charging" with `conflict: true` and a note that the switch disagrees (no authorization claim). Without the field (older backend) the previous rules apply. `reason: control_unavailable` is "Charging can't be started or scheduled". Status judged `last_known` shows "Charger status last known" with no claim charging stopped; offline unchanged. The switch is never authorization.
- **Unchanged:** `GRACE_MS` 120 s, Pause/Resume/Charge Now/Send/Refresh and permissions, no new writes (opening and painting only read), per-connector identity in `live-charging.js`, backend and thresholds. `recovery-banner.js` untouched (no age limit; banner/check/reboot/offline wording is 15.7b). Sidebar copy is English literals in the sidebar modules, so no i18n keys changed (parity test unaffected).
- **Checks (fast):** new `charge-session-freshness.test.ts` (22 tests incl. off+old tx+suspended+hold, off+flow conflict, unconfirmed+old tx, Pause/Stop/fault priority; 23 with charge-session-panel: quiet 10 min current, strict-stale power, link break, offline, accepted without confirmation, switch off/unavailable/on, old backend, malformed judgements, failed/old payload, no mutation, live-charging); charge-session, panel, live-charging, recovery-banner, sidebar, sidebar-price-chart, morek-view, i18n-parity, bundle pass; `npm run build`, `check-dist`, `type-check` pass; manifest 2.5.137.
- **Limits / unrun:** no browser or preview-fixture run, full frontend suite, Python suites or live check. Whether the backend's quantity names and `reported_at` strings always match the reading's `observed_at` byte-for-instant is verified only by mocks.

Coordinator review: disabled-control priority corrected; independent focused freshness/panel tests 23 passed (3.23 s), frontend type-check passed. No browser/live verification.

### 2026-11-14 — Stage 15.6 connection-aware freshness, backend (2.5.136; local mocked; coordinator reviewed; no live HA/charger action)

- **Design:** `execution/morek_freshness.py` (pure) returns `{state: current|last_known|idle|unknown, basis, reported_at, age_s, link, reason}`. *Event* quantities (status, transaction, derived charge-control switch) are `current` when the 15.2 monitor has seen the link continuously up since the report (`continuous_since = max(since, connection_changed_at)`), no age cap; link down -> `last_known`; link unobserved, clock skew or no timestamp -> `unknown`; a report that predates the monitor's continuity (reconnect, new connection, cold start/HA restart: memory only) -> `last_known`. *Sampled* quantities (power, current, register) are `current` with link up, a post-continuity report and age <= `max(180, 3 x median of the last 10 observed report intervals, cap 900)`; beyond it `idle` only when no reading is expected (current transaction False / disconnected), else `unknown` (never idle while a transaction/charging is expected or unknown); link not up -> `unknown`. Cadence reads the evidence store (last 2 h), ignoring duplicates, replay bursts (intervals or arrival gaps < 5 s), >1 h gaps and rows flagged out_of_order/future/conflicting; fewer than 3 intervals -> the 180 s floor.
- **Wiring (additive):** `_session_readiness(..., monitor, entry_id)` adds `readiness.freshness {expected, link, quantities}`; `vehicle`, `vehicle_observed_at`, `measurement` and `charging_enabled` use the judgement, so a quiet healthy switch/status is no longer `not_ready`/unknown after 3 minutes (the switch is still not session evidence). `session.observe_initial` accepts the old strict 180 s report **or** a judgement-`current` report. Without a monitor (or an up link with no known start) everything stays at the strict 180 s bound.
- **Unchanged on purpose:** the readings' `fresh` flag (`LIVE_MAX_AGE_S`, now an alias of `STRICT_EVIDENCE_MAX_AGE_S = 180`), `connector_evidence` (14.2/14.4: an old unplugged never releases, an old waiting never lets `window_release` run, byte-identical outcomes), 15.5 `_post_boot_blocker`/`_boot_start_blocker`, 15.4b `measured_flow`, the 120 s accepted-without-transaction wait and 9.5/14.5 timers, thresholds, send triggers, repair guards. No OCPP call, no UI (15.7), no alert on age.
- **Checks (fast, one file at a time, isolated harness):** new `test_stage_156_freshness.py` 13 pass (idle 10 min current vs strict unknown, old unplugged/waiting evidence, link break/reconnect old vs new report, monitor continuity incl. cold start, clock skew, adaptive/invalid/burst cadence, store-fed bound, silent-in-transaction, idle vs unknown, observe_initial). Reruns passing: readiness 38, stage 155 (33), 152 (13), 153 (40), 154a (37), 154b (36), 146 (15), start_schedule_evidence (12), morek_schedule (106), 142 (22), 144 (50), stage 95 (14), 145 fresh-inputs (11), activation 27 of 28. Ruff clean; manifest 2.5.136; `npm run build`, `check-dist` pass.
- **Limits / unrun:** `test_morek_session.py` (6 failures) and `test_morek_session_activation.py` (1) fail identically on the untouched tree under this stub-package harness (production-setup tests need the real package: `async_track_state_change_event`), so the `observe_initial` setup path is covered only by the new direct tests; `test_morek_worker`, 141, 143, 145 progress, 151a, browser and full suites were not run. Whether the installed OCPP integration stamps `last_reported` on unchanged event states is unverified, and a drop shorter than the 30 s poll on the same point object is invisible to continuity. Live behavior unverified.

Coordinator review: strict execution versus display boundaries checked. Independent direct fast runs: freshness 13 passed (1.85 s); session and session-activation 69 passed (2.54 s), resolving the stub-harness setup failures reported above. Existing bounded ambiguous startup recovery remains unchanged. No live verification.

### 2026-11-14 — Stage 15.5 guarded start after a confirmed reboot (2.5.132; local mocked; mocked review pending; no live HA/charger action)

- **Boot token:** the link monitor's within-process boot-counter rise calls `session.note_boot()` (opens a 600 s evidence window, starts nothing, not evaluated in the same call so a following link edge is ordered first); `session.evaluate_boot()` runs on every monitor poll/event and on each connector observation. It mints exactly one `boot:` token only when, **after the signal**, HA's fresh status reading is `Preparing` and the transaction-id reading is a fresh, explicit "none" (a missing/unknown/non-numeric/pre-signal/present transaction is shown as blocked with a reason, never as absence), with no Charging/Suspended seen since (events or evidence), no completion, no plug-in/recovery/offline/Resume connection minted since, and the connector still Preparing. Unplug, window expiry, completion or active status closes it. The token then goes through the unchanged `_reconcile` (Stop/Pause/protection/identity/ownership/generation, pending/unknown and completion guards, 60 s rejection retry, one request per token); a second genuine rise opens a new window.
- **No loopholes:** `reconnect()` no longer mints `boot:` from comparing counters (the removed branch gave a start with no post-boot evidence); a link-down/up with a boot rise is covered by the existing `offline:` recovery (the boot window closes `covered_by_offline_recovery`, one request); a changed point object or HA restart is still not boot evidence. `session.boot_generation`/`_charger_boot_generation` were removed (the monitor owns the counter).
- **Pre-dispatch recheck (corrective pass):** the minted token is bound to its boot record (`boot["token"]`). `_reconcile`'s `validate()` re-runs `_boot_start_blocker` for `boot:` tokens at the initial and the final pre-wire boundary (not for `post=True` after an accepted response): same token still bound (a newer boot replaces it), window unexpired, no Charging/Suspended seen (events remain tracked after minting), and a fresh post-signal `Preparing` + affirmative no-transaction reading. A transaction, stale/unknown transaction or fresh Charging appearing during ledger awaits yields `aborted_before_dispatch` (not counted, not uncertain), no `_start`. Unverifiable evidence withholds the start. 8 new race tests; `test_stage_155_boot_start.py` now 33 passed (was 25); `test_morek_session` 41, `session_activation` 28, `link_monitor` 13 pass; ruff clean.
- **Readiness (additive, read-only):** `readiness.boot_start {state: unknown|none|waiting|blocked|requested|closed, reason, at, boot_generation}` (`unknown/boot_counter_unavailable` when the monitor has no counter) and `readiness.charging_enabled {state: enabled|not_ready|unknown, reason, observed_at}` from the derived charge-control switch (fresh `on` = enabled; `off`, stale or unreadable = `not_ready`; offline/unsupported = `unknown`). `not_ready` sends, clears or starts nothing; the switch is never toggled and is not authorization evidence. No UI (15.7).
- **Checks (fast, one file at a time, isolated bootstrap):** `test_stage_155_boot_start.py` 25 passed; `test_morek_session` 41, `test_morek_session_activation` 28, `test_stage_152_link_monitor` 13, `test_morek_readiness` 38, `test_morek_start_schedule_evidence` 12, `test_stage_146_decision_evidence` 15, `test_stage_95_recovery` 14, `test_stage_145_fresh_inputs_recovery` 11 passed; `test_morek_worker` 142 passed + the one known `Europe/Stockholm` harness failure (`test_real_planner_publications_drive_worker_without_browser`). The old session test that expected a counter-compare start on `reconnect()` was rewritten to assert none. Ruff clean; `npm run build` and `check-dist` passed. **Unrun:** Stage 14 files 141–145 progress/103 partial and `test_morek_schedule.py`, browser, full suites. Live behavior unverified.

Coordinator review: pre-dispatch transaction/status race corrected; independent 33-case boot check passed in 1.74 s. No live verification.

### 2026-11-14 — Stage 15.4b repair deferral, final freshness, post-repair escalation, gate ON (2.5.135; local mocked; coordinator reviewed; **`REPAIR_DISPATCH_ENABLED = True` locally, not committed/installed**; no live HA/charger action)

- **Gate:** `morek_schedule.REPAIR_DISPATCH_ENABLED = True` (flipped last). It sends nothing by itself: a send still needs two fresh covering mismatches (15.4a), every Stage 14 guard, the budget (2 per 24 h, 30 min apart) and the checks below. Not installed anywhere; installed behavior unverified.
- **Final pre-wire freshness:** the confirmation token now carries the readback's monotonic instant (`mono`) and the checker's facts. `checker.repair_current` additionally requires the latest readback to be 0..30 s old on **both** the wall clock and the monotonic clock, at every `validate()` up to the wire call (so lock/storage waits cannot reuse a stale confirmation). An expired token is `repair_unconfirmed`; its age is never refreshed: only a newer check (new read, new token) can repair. An abort after the attempt/budget write follows the existing refund path.
- **Facts bound to the readback:** a mismatch result carries `facts = mismatch_facts(profile, readback)`: `current_wrong` (limit in force at the readback differs from intended; `diff_in_s` 0), or `current_wrong False` + `diff_in_s` = seconds to the first differing future change, or both `None` (not stated). `compare_schedule`/`classify_check` are unchanged; no profile-inventory claim.
- **Deferral (worker `validate()`, re-evaluated at every boundary; flow read fresh):** `measured_flow` = `charging`/`idle`/`unknown` from fresh measured power (>= `MIN_FLOW_W` 100 W) / current (>= `ZERO_CURRENT_A` 0.5 A) using the existing 180 s live-reading bound; stale/missing = `unknown`, never idle. `repair_deferral`: repair at once when flow is measured **idle** or the current limit is **wrong**, or when the first differing future change is <= **600 s** (`REPAIR_DEFER_GAP_S`, minus the readback's age) away; otherwise (charging OR unknown flow with a correct limit and a distant difference, or facts not stated) the run is refused `repair_deferred` (blocker `wait_for_repair_deferral`, `repair_confirmed.state="deferred"`, `defer_reason`), nothing sent, no budget. The 5-minute recheck is the checker's existing 300 s recheck cadence and its 12-recheck cap bounds it (about 55 min per episode); a restart starts a new episode through the boot/link checks. Wire continuity is all this claims; uninterrupted physical charging is **not guaranteed** and the 16 A brief (E1) stays unverified. Known consequence: a mismatch whose facts cannot be stated is deferred while the car is not measured idle (documented, conservative).
- **Post-repair escalation (no second controller):** after an accepted repair the worker asks the checker for one read-only follow-up (`request_post_repair`, first look after 150 s, re-looking every 60 s up to 4 times while the repair's own verification is pending). A confirmed mismatch whose acknowledged attempt is itself in `repair_attempts` (or already marked) makes `_send_profile_shared` persist `repair_escalation {at, attempt_id}` and return `repair_needs_person` before any budget/attempt write: nothing is sent, no clear, no loop, restart-proof. The marker is keyed to the repaired attempt, so a later normal plan starts clean. Unknown verification/readback is never a mismatch. **Rejected repair:** a repair the charger answers `Rejected`/`NotSupported` also writes the escalation (needs a person); the existing 5/15 min rejection cooldown is unchanged and no blind second write is made. Uncertain outcomes keep the existing latch.
- **Status:** `reconciliation.repair.needs_person` is also true for the escalation; `confirmed.state` gains `deferred`. No UI (15.7b).
- **Checks (fast, one file at a time, isolated harness):** new `test_stage_154b_repair_deferral.py` (36 pass, ~2 s; verified to fail with the freshness check and the deferral call removed); `test_stage_154a_repair.py` now patches the gate off by default and its confirmation carries facts (37 pass). Reruns passing: 153 (40), 152 (13), 155 (33), morek_schedule (106), session (41), session_activation (28), stage 95 (14), 142 (22, ~22 s), 143 (22, ~21 s), 144 (50, ~24 s), 145 recovery/fresh-inputs (11 + part of 51 with readiness), 146 (15), `test_morek_worker` 142 pass with the known Stockholm test deselected. Ruff clean; manifest 2.5.135; `npm run build`, `check-dist` pass. Unrun: browser, full suites/planning runner, `test_stage_141_current_interval`, `test_stage_151a_time_reserve`, the known Stockholm-harness repro.

Coordinator review: confirmation freshness, active-charge deferral and durable escalation checked; independent 36-case repair-release check passed in 1.89 s. Enabled in local source, no live verification.

### 2026-11-14 — Stage 15.4a guarded repair: confirmation, trigger, budget (2.5.134; local mocked; coordinator reviewed (gate off); gate OFF at 2.5.134, superseded by 15.4b above; no live HA/charger action)

- **Gate:** `morek_schedule.REPAIR_DISPATCH_ENABLED = False` (named constant, **must stay False until 15.4b**, whose last step flips it after active-charge deferral and post-repair escalation exist). The dispatcher is production-wired: checker -> `worker.request_repair`. With the gate off `request_repair` raises **no run** (a strict run could otherwise send a plain SOC-drift update): it records the finding only (`repair_confirmed.state="gated"`, one bounded decision event `result=repair_gated`, blocker `wait_for_repair_release`, repeats counted). `_run` also ignores a repair request when the gate is off. Zero automatic repair writes; tests assert it, and drive the enabled path by patching the constant.
- **Confirmation (checker, pure `confirm_mismatch`):** each clean covering `limits_or_transitions_differ` (the existing 15.3 `differs_unconfirmed` result) is an observation `{attempt_id, connection_id, readback_at, monotonic}`. Confirmed (`differs_confirmed`, recorded as its own class/event) only when the latest is <= 30 s old (wall and monotonic) and an earlier observation of the same acknowledged attempt and the same `connection_id` is >= 30 s older on both the readback timestamps and the monotonic clock, the two clocks agreeing within 10 s (replay/re-stamp/clock-jump never confirm). Observations are discarded on a healthy/unknown result, link-up/connection-change request, link-down, a new attempt and unload. No pending/uncertain/newer-attempt record can reach a mismatch (15.3 candidate rules); the rejection cooldown is re-applied at the send. Missing/Unknown/coverage reasons never confirm.
- **Trigger/send (reuses the one path):** `worker.trigger(kind="repair")` (strict, urgent, ranked after `control`) -> `_reconcile` -> `_send_profile_shared(repair=<confirmed attempt id>)`. The repair flag bypasses **only** the two `unchanged` returns, after the uncertain-record return and **after** the rejection cooldown. It requires the confirmed attempt to still be the latest accepted and acknowledged one with the same intent kind (routine / pause hold / Charge Now: a hold repairs as a 0 A hold, Charge Now as its own override, a changed intent -> `repair_unconfirmed`). The current guarded intent is rebuilt by `_intent` (acknowledged active window carried, so no 0 A gap) with `cap_lowered`/`price_event` forced off for a repair run, so it never releases a window and a repair's acceptance does not end a pending price decision. `validate()` additionally re-asserts the confirmation token (`checker.repair_current`: same token, link `up`, same `connection_id`) at all three boundaries; the repair's own attempt keeps the token (`note_new_attempt(repair=...)`), any other attempt/link edge/new episode/unload drops it. Stop/generation/ownership/identity guards are the existing ones. No `clear_profile`, no start, no retry of an unknown outcome.
- **Budget:** additive ledger list `repair_attempts` `[{at, attempt_id}]`, read as untrusted by `repair_budget`: absent = empty (old records unchanged); malformed list/entry or a future-dated entry = `invalid` (no repair, `repair_needs_person`); max 2 inside a rolling 24 h, the second >= 30 min after the first (`repair_spacing`, transient); exhausted = `repair_needs_person` (blocker action `needs_person`; UI wording 15.7b). The entry is written (ledger) after the durable check and **before** the final validation and the wire call, then validated again; any refusal at that point removes it (aborted-before-dispatch consumes nothing). Admission/guard refusals earlier consume nothing. A crash between the budget write and the call counts one (conservative). The list is pruned to the rolling window on the next repair write.
- **Status (additive):** `reconciliation.repair {gate_enabled, confirmed{state gated|confirmed|sent|refused, at, readback_at, attempt_id, result}, budget{state, used, limit, next_at}, needs_person}`; checker `reconciliation.check` gains class `differs_confirmed`. No UI.
- **Limits / not verified:** a **rejected repair** is not retried (the acknowledged fingerprint still equals the intent, so the 5/15 min retry run returns `unchanged`; the rejection cooldown only guards a repair that follows); 15.4b's escalation owns that. No deferral for a correct active charge yet (the reason the gate stays off). What the installed charger answers to `GetCompositeSchedule` and whether a repaired profile changes anything is unverified. A confirmation takes >= 30 s of checks, so with the 12-recheck cap it can confirm within about 50 minutes of an episode.
- **Checks (fast, one file at a time, isolated harness):** new `test_stage_154a_repair.py` (38 pass, ~2 s: gate off zero writes and status, direct trigger with gate off still deduped, enabled exactly one profile and one budget entry, normal dedup unchanged, active window/no 0 A gap/price decision untouched, uncertain and rejection cooldown not bypassed, stale attempt, Pause hold as hold and no hold->run, Charge Now own override, budget refusals/invalid stored records/spacing/rolling window/restart cap, Stop and confirmation-lost races at the attempt and budget writes consuming nothing, rejected wire run counted once, pure confirmation cases, checker confirmation/break cases and token revalidation, gate-off real-worker integration; verified to fail with the revalidation, refund and bypass guards removed). Reruns passing: 152 (13), 153 (40), 155 (33), morek_schedule (106), session (41), session_activation (28), stage 95 (14), 142 (22), 143 (22), 144 (50), 145 both (11, 13), 146 (15), 103 partial (9), readiness (38), start_schedule_evidence (12); `test_morek_worker` 142 pass + the one known Stockholm-harness failure (`test_real_planner_publications_drive_worker_without_browser`, not re-baselined). Ruff clean; manifest 2.5.134; `npm run build`, `check-dist` pass. Unrun: browser, full suites/planning runner, `test_stage_141_current_interval`, `test_stage_151a_time_reserve` (known Stockholm failures not re-baselined). Live behavior unverified.

Coordinator review: independent 38-case repair check passed in 1.89 s. Dispatch remains disabled. Before enabling in 15.4b, confirmation freshness must be rechecked at the final wire boundary as well as connection/attempt identity.

### 2026-11-14 — Stage 15.3 read-only reconnect/startup schedule check (2.5.133; local mocked; mocked review pending; no live HA/charger action)

- **What:** `execution/morek_checker.py` `MorekScheduleChecker` (`worker.checker`; also `hass.data["spotnav_morek_checker"][entry_id]`), requested by the link monitor (HA startup with the link up, down→up, a new point object while up, a within-process boot-counter rise) and by `worker.resume_after_availability_change` (the existing availability return). All of those existing reconcile/recovery triggers are unchanged; the check is additional and a Healthy check suppresses nothing. It reuses `morek_schedule.async_schedule_action(hass, entry_id, "fetch", check={...})`: the same `read_only` admission, the same `GetCompositeSchedule` read (now the shared helpers `_composite_duration`/`_composite_readback`, also used by the old fetch) and `compare_schedule`. There is no second comparator and no sender.
- **Writeless:** the `check` branch (`_checked_readback`) writes nothing: not `data`, not the ledger, not the evidence store. A newer attempt's `verified`/`effective`/`verification`, the acknowledged/uncertain fields, `last_trigger`, trigger classes, `continuity` and the worker decision record are untouched. The old fetch path (manual Fetch, verification reads) is unchanged and still writes its verification.
- **Candidate (`check_candidate`, pure):** the latest acknowledged attempt only (routine plan, Pause hold, Charge Now own profile) while inside coverage. Unknown reasons, no read: `outcome_uncertain`, `upload_pending` (`spotnav_morek_sending`), `no_acknowledged_intent`, `newer_attempt` (any later attempt of any state), `verification_pending` (verify timer present, or this process dispatched the attempt and no readback has been recorded yet), `intent_changed` (pause/Charge Now no longer matches the attempt), `intent_expired` (last transition + 1 h passed; Charge Now ended), `profile_unavailable`. Held-off profiles are bounded at read time by `compare_schedule`.
- **Classes (`classify_check`):** `healthy` (clean match), `unknown` (readback unavailable/timeout/wrong connector, any coverage reason, `clock_doubt` = wall clock vs monotonic drift > 30 s across the read, link not up, worker unavailable) and `differs_unconfirmed` (one accepted amps readback with `limits_or_transitions_differ`). Mismatch → rechecks after 30, 60, 120 s then 300 s, at most 12 per episode; a healthy/unknown recheck ends the episode. Confirmation as material is **15.4a, not done**.
- **Bounds:** triggers coalesce (5 s settle; one pending timer; at most one check start per 60 s by a monotonic clock, so a flapping link gives one check); no periodic readback, no timer when idle. A link-up/connection-change/availability/boot request, a link-down edge, a newer attempt (`note_new_attempt`, called from `_send_profile_shared` right after the attempt is persisted) and unload (`worker.close`, `entry.async_on_unload`) bump a request epoch, cancel the timer and discard any read in flight.
- **Race binding:** each read is bound to the link monitor's `connection_id` (state must be `up`), the acknowledged attempt id (rechecks pass the episode's id), the connector's owner generation / person Stop and the epoch; checked inside the lock before and after the read and again when the result is published. Stale → `check_superseded`, discarded, nothing recorded. The HA timer target `_async_fire` is a `@callback` (verified as `HassJobType.Callback`); the read runs as a task.
- **Status:** `reconciliation.check` = `{class, at, readback_at, reason, rechecks, events}` (additive; `null` when there is no checker). `events` is a bounded (10) list of changed-class decisions (`at`, `last_at`, `trigger`, `class`, `reason`, `readback_at`, `repeat`); one INFO log line per changed class (codes only; no frames, profile data or identifiers). No UI (15.7b).
- **Limits:** the boot trigger is the monitor's counter rise (whose exposure by the installed OCPP integration is unverified), not the session's `Preparing` confirmation; a restoration with a same-object reconnect shorter than the poll is not seen (15.2 limit); Unknown after an availability return can briefly replace an earlier Healthy until the link edge/next check. 15.4a/15.4b (confirmation, repair, gate) are not implemented.
- **Tests (fast, isolated harness):** new `test_stage_153_schedule_check.py` (40 pass, about 2 s): every class sends nothing and writes nothing, Pause hold and Charge Now profiles checked, candidate refusals, no read for uncertain/pending/expired/newer attempt, startup once and no periodic traffic, link-down startup waits for the edge, burst dedupe, flap bound, availability return and boot request, no change to worker trigger/continuity/decision, recheck schedule and 12-cap, cancel on edge/new attempt/link down/unload, a real worker send ending the episode, six in-read races and four publish-time races (verified to fail with the checker's own guard removed), `HassJobType.Callback`, status shape, old fetch unchanged. Reruns passing: stage 152 (13), stage 155 (33), morek_schedule (106), morek_session (41), stage 95 (14), stage 142 (22), 143 (22), 144 (50), 145 (11), 146 (15), morek_readiness (38), morek_start_schedule_evidence (12); `test_morek_worker` 142 pass with the one known Stockholm-harness failure (`test_real_planner_publications_drive_worker_without_browser`, not re-baselined; the run takes about 28 s). `npm run build`, `npm run check-dist` pass; manifest 2.5.133. Unrun: browser, full frontend/HA suites, full isolated planning runner, `test_stage_141_current_interval`, `test_stage_151a_time_reserve` (known Stockholm failures not re-baselined).

Coordinator review: read-only path, connection/attempt binding and bounded timers checked; independent 40-case check passed in 1.87 s. No live verification.

### 2026-11-14 — Stage 15.2 link monitor (2.5.131; local mocked; coordinator reviewed; no live HA/charger action)

- **What:** `execution/morek_link.py` `MorekLinkMonitor`, one per Morek entry (`worker.link_monitor`), one `async_track_time_interval` timer (30 s) cancelled on unload whose target is the `@callback` method `_async_poll` (a plain lambda would be classified by HA as an executor job and its consumers' `async_create_task` calls would run off the event loop), plus a local re-read on the existing connector-status and charge-control entity events. It reads `morek_schedule.link_reading` (point `status == "ok"` as `_charge_point` judges it, point object identity, `charger_generation` via `getattr`). No OCPP traffic; it never sends, reads back or starts.
- **State (memory only):** cold start `unknown`, first reading seeds without edges (an HA restart is not a charger reboot; boot counter compared only within the process). Missing/ambiguous/foreign/unsupported point or non-string `status` = `unknown`, never `down`, never an edge; the last definite reading is kept for comparison.
- **Edges (each once):** up→down: `session.offline()` + `link_down` gap rows (all measured kinds, source `link_monitor`); down→up: `session.reconnect()`, gap end, one rate-limited worker `trigger(kind="recovery")` (min 60 s apart; a pending one is delivered by a later poll); up→up with a new point object: new `connection_id`, gap since last reading and the same recovery request, but **no** `session.reconnect()`, so an object change is never a reboot, plug-in or new session. Boot counter rise is only recorded (`boot_generation`, `boot_changed_at`); *(15.2 historical note, superseded by 15.5: the rise is now consumed by `session.note_boot()`/`evaluate_boot()`, see the 15.5 entry.)*
- **Status:** `link` on the Morek schedule status (`state`, `since`, `connection_id`, `connection_changed_at`, `boot_generation`, `boot_changed_at`); no UI (15.6/15.7). `morek_offline` joined `TRANSIENT_BLOCKERS` (non-sending timer inside the existing 12-run cap) and `DECISION_BLOCKERS`.
- **Limits:** a drop shorter than the poll that keeps the same point object is not detected; that the installed OCPP integration exposes `status`/`charger_generation` on the point object is source-reading, unverified in HA; gap rows are written at edges only, so a still-running down span is covered by stale-source flags until the up edge records it.
- **Tests (fast, isolated harness):** new `test_stage_152_link_monitor.py` (13 pass, incl. a real `HassJob` classification and `hass.async_run_hass_job` down/up test that asserts the timer target is `HassJobType.Callback` and that session/worker consumers are reached on the event-loop thread; verified to fail against the old lambda). Link-monitor debug logs now record only the exception type name (no `exc_info`). Reruns passing: stage 142, 143, 144, 145 (both), 146, morek_schedule, morek_session, session_activation, stage_95, stage_103, stage_62, morek_readiness; test_morek_worker 142 pass. Known failures, reproduced on the pre-change tree and attributed to the Stockholm timezone harness limitation: `test_stage_141_current_interval` (2 tests; the second not separately baselined), `test_morek_worker::test_real_planner_publications_drive_worker_without_browser`, `test_stage_151a_time_reserve::test_reserve_edit_is_a_compare_and_set_revision`. Unrun: browser, full frontend/HA suites, full isolated planning runner. `npm run build` and `check-dist` pass.

Coordinator review: HA timer callback classification corrected and independently checked; all 13 focused monitor tests passed in 2.07 s. No live verification.

### 2026-11-14 — Stage 15.1b reserve control and plan display (2.5.130; local mocked; coordinator reviewed; no live HA/charger action)

- **Control:** sidebar "Extra time reserve (%)" number field (0-50, step 1) beside cap/minimum SOC, shown only when the stored
  record carries `time_reserve_percent` (older backend: no field, never sent). It uses the existing `savePlan` path: canonical settings
  record, revision-checked `update_settings`, existing draft/conflict/permission behaviour. `settings.ts` gained `timeReserve` in the form,
  integer 0-50 validation (`outOfRange`/`invalidNumber`), changed-only write, and reapply-onto-newer-record semantics like the other fields.
- **Display (shared `plan-view.js`, used by the HA panel and the preview):** windows show `includes N min reserve` per window; when a reserve
  exists the totals are relabelled "REQUIRED BASELINE ENERGY/COST" and a separate "Potential extra allowed reserve: up to X kWh · cost" line is
  labelled an upper allowance at plan power and prices, not measured or expected use. Wording: "Extra allowed time to reach the target; the
  car's own limit stops it, so the reserve is not a higher SOC." Zero reserve states "none in this plan (N% asked)" with the backend `limit`
  reason (`two_hour_limit`, `no_eligible_time`, `window_limit`, else generic); partial shows "N min of M min asked"; null/malformed numbers
  show Unknown; an allowance cost in another currency than the plan is dropped. Absent `proposal.reserve`/per-window fields (older backend, 0 %,
  or a stale plan) leave today's display unchanged. All values are the backend's; the client sums or prices nothing, and the baseline totals
  and window energy are never increased by the allowance. `shared-dashboard/reserve-model.js` maps backend data to display data for both the live
  adapter and the sample adapter (hand-authored, fictional fixture with the same shape, 10%).
- **i18n:** the adapter-sourced sentences are keys `reserve.explain`, `reserve.limit.*` in every language file (English text copied, as for
  the existing `daily.policy.*` keys); the dashboard's own labels are English literals like its neighbours.
- **Checks (fast, no browser):** `test/reserve-display.test.ts` (8: display vs baseline, no double count, old backend, malformed, zero/limited,
  currency/stale, control save, out-of-range, revision-conflict draft, old-backend no field), `test/settings.test.ts` (+2 reserve control),
  with `sidebar`, `i18n-parity`, `i18n`, `settings-editors` (347 passed in total with the existing ones) and node tests for
  `shared-dashboard` and `prototype` (16 passed). `npm run type-check`, `npm run build` and `npm run check-dist` clean; manifest 2.5.130.
- **Unrun / limits:** browser/Playwright, the full frontend suite, backend suites (no backend change), HA-plugin suite. The non-English files carry
  English text for the new keys. The reserve control lives only in the sidebar panel (the Lovelace card has no plan editor for it). The
  allowance and reserve minutes are backend upper figures; no actual use, physical charging or BMW stop is verified. Not installed on HA.

Coordinator review: save/conflict and baseline/allowance mapping checked; independent fast UI check: 135 passed in 3.43 s. Browser/live verification remains unrun.

### 2026-11-14 — Stage 15.1a planner time reserve, backend (2.5.129; local mocked; coordinator reviewed; no live HA/charger action)

Coordinator review: reserve precision and SOC-tolerance regressions corrected; independent fast reserve check: 79 passed, one timezone-harness case deselected (10 s). No live verification.

- **Behavior:** `time_reserve_percent` (int 0–50, default 10; absent in stored records = 10, written only when ≠10; settings API
  key, optional on replacement = keep stored, compare-and-set via the settings revision; refusals use `invalid_number`).
  `planner.with_time_reserve(request, result)` (called by `AutoPlannerController` only for Morek-owned plans and only when
  no price-wait facts, after `ending_at_need`) adds `percent` of the baseline active time, rounded up only to 1 second
  (`RESERVE_RESOLUTION`, the whole-second dispatch resolution of `profile_for`), at most 2 h (`RESERVE_MAX`), into the cheapest free published within-cap time before the deadline (a part-elapsed current
  interval only where it continues a baseline window: a piece starting at `now` would creep), ties to continuing a window then earliest, respecting `max_blocks`/period limit (never a 4th window;
  what fits is kept, `reserve_limit` says why less). Unpriced, short-of-deadline and refused plans, and 0 %, are returned
  unchanged. Feasibility/soft-cap/minimum-SOC logic is untouched.
- **Data:** `PlanResult.reserve_percent/reserve_requested_minutes/reserve_pieces/reserve_limit` and properties `reserve_periods`,
  `reserve_minutes`, `reserve_energy_kwh`, `reserve_cost` (upper allowance at plan power/prices), `baseline_shown_periods`,
  `shown_periods` (= baseline + reserve, what the profile and notifier use), `periods_with_reserve` (chart shading). Baseline
  `periods/slots/delivered_kwh/estimated_cost` never include reserve. `window_release` uses `baseline_shown_periods` (getattr
  fallback for fakes). Dashboard `proposal.reserve {percent, minutes, requested_minutes, limit, periods, allowance{kind
  "upper_allowance", energy_kwh, cost}}` and per-window `reserve_minutes/kwh/cost` (only when a reserve exists; `energy_kwh/cost`
  stay baseline). `_proposal_key` includes the reserve.
- **Minimal frontend change (not the 15.1b UI):** `frontend/src/settings.ts`/`types.ts` accept and carry `time_reserve_percent`
  through replacement bodies, because the strict decoder would otherwise refuse the new backend key. No control or display.
- **Stage 14 stays reserve-free (review corrections, same 2.5.129):** an accepted profile that carried a reserve also stores its
  reserve-free twin (`acknowledged.baseline`/`attempt.baseline`, written by `_send_profile_shared` from the worker's
  `_proposed_baseline`; absent without a reserve and in older records). `same_effective_schedule(..., accepted_baseline=,
  candidate_baseline=)` judges the unchanged 5-minute SOC end tolerance on the twins (strict at ≥ 5 min of need drift, structure
  exact), then lets a reserve switch-off differ by less than that tolerance plus the change in total reserve seconds (the only other
  thing a need drift moves); a missing twin on either side is the plain comparison. Strict causes (settings, price, plug-in,
  recovery, mixed bursts) pass no tolerance and are unchanged. `window_release(..., active_baseline=)` carries the accepted
  *twin* window and compares against `baseline_shown_periods`: before this fix a reserve inside the accepted active window
  inflated the kept cost and could release on price where the reserve-free plan would not (16-19 min windows in the fixture).
  Residual, by design: if the reserve itself disappears or is re-placed beyond the tolerance sum, that is a normal resend.
- **Limits:** a reserve crossing its fragment's capacity adds a new piece (one normal resend); excluding the part-elapsed current
  interval means a reserve may use a dearer later slot instead of the rest of the current one; legacy HA entities (period
  sensors) still show baseline periods; non-Morek chargers get no reserve. Existing 14.1 test
  `test_schedule_owned_uncapped_plan_starts_now_and_stops_at_the_need` pins `time_reserve_percent=0` (it asserts the
  reserve-free baseline); the default-10 path is covered in `test_stage_151a_time_reserve.py`.
- **Checks run (fast, isolated runner bootstrap, one file at a time; after the review corrections):** `test_stage_151a_time_reserve.py` 79 passed + 1 harness failure (`test_reserve_edit_is_a_compare_and_set_revision`, `Europe/Stockholm` unknown in this Windows harness; fails the same way for the untouched 14.1 `_world` tests), each test < 5 s; mutation check (twin disabled) fails the six sub-5-minute drift cases. Earlier list: Stage 14.1, 14.2, 14.3, 14.4, 14.6, 14.5
  (both), 103_partial, 95_recovery, morek_schedule (106), morek_worker (142), planner_current_interval, planner, settings_contract,
  price_policy_settings, frontend settings tests passed. `npm run build`, `npm run check-dist`, ruff clean. Failing both before and
  after this change (verified via stash): `test_morek_session.py` production-setup tests (6), `test_morek_session_activation.py::
  test_production_listener_is_a_loop_callback_and_plugin_starts_once`, `test_capped_auto_execution_isolated.py::
  test_saved_capped_settings_reach_real_calculation_and_preview` (all missing-HA-import/harness limits). **Unrun:** full
  isolated runner list (too slow), `test_stage_13_reactive.py` (exceeded 110 s), `test_price_policy_settings` hass-fixture test,
  browser/Playwright, full frontend suite, HA-plugin suite (fcntl).

### 2026-11-13 — Charge-session status and warning (2.5.127; local mocked; no live HA/charger action)

- **What the user sees:** a `#charge-session` card in the existing sidebar host (above `#recovery-banner`, painted by
  `paintSession`, which only reads decoded status) and the same text in the dashboard `readiness` evidence. Plain
  language, one action line, a collapsed "What SpotNav sees" list; no raw codes or IDs. Warnings use `role="alert"` and
  a large amber/red card; everything else is `role="status"`.
- **Classifier:** `frontend/sidebar/charge-session.js` (`chargeSession`, `scheduleLimit`). Order: unsupported (hidden) ->
  stale/failed/missing status = unknown -> offline -> connector unknown -> unplugged -> fault -> uncertain outcome ->
  measured flow (the only "Charging") -> finished -> reported charging (power unmeasured) -> Pause/Stop (info) ->
  suspended or scheduled wait -> in Preparing: observed transaction (ok), unmatched transaction (info), then by request
  state: starting/pending (info), accepted (info within 120 s, **warning after** or when the backend says
  `no_transaction_observed`), rejected, blocked (transient reasons are info for 120 s then warn; protection/logging/unknown
  reasons warn at once; completed session is info), waiting (info 120 s then warn). No timestamp (older backend) means no
  time-based alarm. A scheduled 0 A hold never excuses a missing transaction, but a *present* transaction plus a hold is the
  calm "Authorized - waiting for the schedule" state. The hold comes from the readback limit, else an ACKed sent profile.
- **Backend evidence (additive):** `MorekSessionCoordinator.state` is now a property that stamps `state_at` only when the
  state changes (memory only: after a restart it is the restart time, so a long-accepted request is judged from the restart
  moment). `readiness.session_start_at`, `readiness.live.control_state` (`on`/`off` + freshness) and `readiness.live.transaction`
  (`True`/`False` from the connector transaction-id sensor, id never exposed, plus `changed_at`). In Preparing a present
  transaction counts as observed only if it changed after the current request-state change; otherwise it is "not tied to this
  plug-in" (a leftover id from an earlier session must not confirm this one). `readiness.transaction` is unchanged `unknown`.
- **Limits:** the transaction-id sensor's real lifecycle (sentinel, retention after a session ends, update timing) is still not
  verified on hardware; the logic only trusts a *fresh* reading and treats everything else as unknown. The switch state is
  displayed, never used as a verdict. The 120 s grace equals the backend's own bound and is judged on the browser clock against
  the backend timestamp (clock skew can shift it by seconds). `session_start_at` is not persisted. The warning does not itself
  start, repeat or clear anything and offers no new control; the advice (use the Morek app or re-plug) is generic and
  unverified on the installed system. `session_start_at` assembly in the full status path has no dedicated test (the
  card logic and the coordinator timestamp do).
- **2.5.128 evidence hardening (local mocked):** a schedule wait ("Plugged in - waiting for the schedule") is claimed only with a
  *fresh* transaction report (Preparing: matched transaction; suspended connector: fresh `true`). A suspended connector
  without it is plain "Charging suspended" and says whether the transaction is reported absent or merely unknown. The hold
  itself (`scheduleLimit`) needs a readback with a fresh `fetched_at`; otherwise only an *accepted* sent plan with a send time
  and a known, unexpired duration counts, is worded "plan sent to the charger ... not confirmed by a readback", and is dropped
  when verification says the limits differ or were superseded. No text promises power starts ("may begin ... not guaranteed").
  An unmatched transaction number no longer returns early: it only replaces the calm pending/accepted-waiting states, and is
  appended as a note to accepted-no-transaction, rejected, blocked and start-not-sent warnings. An unknown transaction sensor
  is "no transaction is confirmed", never "none". Action text follows the retry state (`request_rejected` = one retry pending;
  otherwise "will not repeat"; not-yet-sent says unplug/re-plug). `protection_conflict_unresolved` says to resolve the
  protection conflict and does not suggest starting the charge elsewhere. New tests: "evidence required before claiming a
  scheduled wait or readiness" in `charge-session.test.ts`.
- **Tests:** `frontend/test/charge-session.test.ts` (13: every state, grace, stale, leftover transaction, scheduled hold,
  measured vs reported), `frontend/test/charge-session-panel.test.ts` (card wiring, role, hide/unknown, no writes),
  `tests/test_morek_readiness.py` (transaction/control evidence), `tests/test_morek_session_activation.py` (state stamp);
  updated readiness wording in `sidebar.test.ts` and `browser-check.mjs` (browser check not run). No browser, live HA, charger,
  restart, commit or push.

### 2026-11-13 — Plug-in session activation fix (2.5.126, review of 2.5.125; local mocked; no live HA/charger action)

- **Root cause (from the installed 2.5.124 log):** `session_status_changed` in `__init__.py` was an undecorated
  function, so HA ran it as an executor job. `observe` -> `_note_schedule_evidence` -> `worker.note_plug_in` ->
  `hass.async_create_task` raised `RuntimeError` (loop-only). `observe` had already stored the new observation but
  aborted before assigning the connection token, so `Preparing` later reconciled as `stale_or_ambiguous_session` and no
  RemoteStartTransaction was sent. Existing tests called `observe` inline on the loop and never exercised job
  classification.
- **Fixes:** the listener is `@callback`; `observe` is exception-safe and settles its own state (observation, connection
  token, trigger) before the guarded worker-evidence call. A failure there is logged by class name only.
  Preparing that follows a flap (unknown/unavailable and back) re-triggers the *same* connection (reconcile stays
  idempotent: a recorded request is never repeated, a never-dispatched one proceeds); Available -> flap -> Preparing is
  one new plug-in connection, created once (`available_before_loss`), not an inherited "recovery".
- **2.5.126 review corrections:** (1) `_observe` now reports whether it created a fresh connection; that alone drives
  exactly one `note_plug_in` (so Available -> unknown/unavailable -> Preparing recalculates once, and never also as a
  sensor event). A Preparing that reuses an existing connection, or a never-seen-Available recovery, stays a sensor
  event or none; it is not a plug-in. (2) `validate()` no longer calls `worker._intent` at all (it mutated
  `continuity`/`override_degraded` and its refusals were swallowed). Audit of the gates that remain, each independent
  of plan/SOC/price freshness: person Stop reservation, explicit Pause (`paused_until_resume`), legacy pause,
  start-cap protection conflict, supported-Morek identity, current ownership ticket and generation, completed or
  ambiguous session, recorded `session_start` unknown/pending, record validation (`_outcome_record` raises on an invalid
  pause/Charge Now/binding and the start then reports `session_evidence_unavailable`), an explicit `uncertain` profile
  outcome (`profile_outcome_uncertain`; admission's `profile_outcome_unavailable` normally refuses first), and the
  planner object mismatch (`planner_changed`, timer-retried). Dropped on purpose: `current_must_be_16` for Charge Now
  and plan-quality blockers; the worker's own send path still enforces them for profile uploads. Nothing here claims the
  charger's retained schedule is effective or that charging will occur.
- **Individual blocker reasons** replace `stale_or_ambiguous_session`: `session_closed`, `worker_suspended`,
  `charger_unavailable`, `stale_generation`, `person_stop_active`, `ownership_not_current`, `identity_changed`,
  `waiting_for_new_connection`, `session_ended_or_completion_ambiguous`, `connection_changed`, `session_completed`,
  `connector_not_preparing`, plus the existing `paused_until_resume`, `legacy_pause_active`,
  `protection_conflict_unresolved`, `previous_start_may_have_applied`. Admission's `stale_generation` is reported as
  `person_stop_active` while a person Stop is reserved.
- **Bounded recovery:** transient reasons (suspended, unavailable, stale generation, ownership not current, identity
  changed, quiescing/initializing, retry cooldown, planner changed) re-evaluate on a memory-only timer
  (5, 15, 30, 60, 120, 300 s; at most 12 runs per blocked episode); events still re-evaluate at once. Person Stop/Pause,
  completion, unknown/pending earlier requests and protection conflicts are never retried by timer.
- **Authorization no longer depends on plan/SOC freshness:** `worker._intent` refusing (stale SOC, prices, no valid
  plan, too many blocks) does not withhold the start; only `planner_changed` does. The charger keeps its own schedule and
  the single worker keeps reconciling it. Attempts aborted before dispatch no longer consume the two-attempt budget and
  have no 60 s cooldown (nothing was sent). The post-dispatch re-check ignores the connector moving to Charging.
- **Accepted but no transaction:** an accepted request with the connector still Preparing after 120 s shows
  `accepted / no_transaction_observed`; it is never repeated automatically (an explicit person Resume is the only new
  request). Unknown/pending outcomes remain visible and block duplicates.
- **Deliberately unchanged:** an unknown/pending start for an *earlier* connection still blocks later starts
  (`previous_start_may_have_applied`); there is still no automatic or person-facing way to clear it. A completion record
  followed by restart/recovery without an observed unplug still blocks (`car_completion_reported`). The frontend does not
  map these codes to text (it only carries `session_start` through); the bump just rebuilds the artifacts.
- **Tests:** `tests/test_morek_session_activation.py` (21 cases: real listener `HassJob` type is Callback, an
  event-loop-thread rule on task creation with an executor-vs-callback dispatch emulation, worker-evidence failure,
  prior ended session, flaps, transient clear and bound, Stop/Pause, missing plan/SOC, accepted-no-transaction, Charging
  during the request, Stop during the request, unknown/pending). One existing assertion in `test_morek_session.py`
  changed to the new specific reason. Run on Windows, where the HA pytest plugin cannot import (`fcntl`):
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest ...`
  (session, 14.3, 9.4, 9.5 files: all passed). The stub hass is not real HA: it does not prove the installed dispatch,
  real OCPP timing, or physical charging. No browser, broad or slow suite, live HA, charger, restart, deploy, commit or push.

### 2026-11-13 — Stage 6.3 history queries (2.5.124; local mocked; coordinator review pending)

- New `sessions/history.py` and `spotnav/get_charging_history` (`api/sessions.py`); `ChargingEvidenceStore` gained
  `blobs` (per-version tariff/price snapshots, content-addressed, pruned with their versions), `days` (digests, 62 max),
  `oldest_evidence`, `digests`, `keep_digest`; `energy_segments` rows now carry `from_value`/`to_value`/`unit`.
  `_evidence_plan` records `plan_tariff_snapshot` (in `sessions/inputs.py`) with each version; failure there is
  swallowed and recorded as `unknown`. `MeasurementCapture` compacts finished days once per local day.
- Completed from the previous (out-of-tokens) session's uncommitted partial edits; kept as designed. Fixed: wall-clock
  subtraction for same-zone aware datetimes (DST days) by normalising windows to UTC.
- Tests: `python tools/run_isolated_logs_tests.py tests/test_stage_63_history.py tests/test_stage_62_evidence.py
  tests/test_morek_start_schedule_evidence.py` -> 51 passed (ruff clean); `npm run build` and `check-dist` current at 2.5.124.
  No browser, broad suite, live HA, charger, deployment, commit or push.
- 2.5.124 review fixes: `applies*` fields became `acked_intent`/`acked_at`/`intent_ended_at`/`known_until`/`unknown_from`/
  `unknown_reason`: an accepted ACK is the last acknowledged intent, ended at the next accepted ACK or removal and made
  `unknown` (not carried forward) by the first retained uncertain write (unanswered marker, conflict, ACK `unknown`, dispatch
  events of a pruned version, a version with no events older than all retained events); events are ordered by recording
  sequence. Comparison adds `unknown_plan_spans` and `plan_unknown` flow; blocks starting before retained evidence are
  `unknown`. `_energy` returns `null` (with per-basis `coverage`) when no segment lies in the window; a measured zero
  stays 0.0. External writers and restarts are not detectable (restarts only counted); readback is never inventory.
  Frontend does not consume these fields; the bump only rebuilds the artifacts.
- Unverified/limits: see the archived roadmap's 6.3 entry (thresholds, real entities/cadence, storage size, no UI, no session link).

### 2026-11-13 — Stage 6.2 capture and provenance (2.5.121; local mocked; coordinator review pending)

- New `sessions/evidence.py` (`ChargingEvidenceStore`, `MeasurementCapture`, `derive_energy`); store key
  `spotnav_charging_evidence`. Wired in `__init__.py` (`_async_start_charging_evidence`, Morek connector only,
  read-only, removal on entry delete) and in `api/morek_schedule.py` (`_evidence_plan` / `_evidence_call` hooks in
  `_send_profile_shared`, the clear action and the readback publish). Every hook swallows failures: evidence can never
  change a send, ACK, ownership or uncertainty outcome. `_live_measurements` gained an optional `entities` sink for
  provenance; the status payload is unchanged.
- Sent-plan versions are immutable and keyed by attempt id; ACK/readback/removal are separate events; measurements are
  a separate list. See the archived roadmap's 6.2 entry for the data model, bounds and 6.3 seam (`plan_versions`, `events`,
  `samples`, `gaps`, `capture_starts`, `derive_energy`).
- Review corrections (2.5.121): `derive_energy` no longer drops gap rows or ignores restart marks; callers must use
  `ChargingEvidenceStore.energy_segments` (or pass gap rows and `restarts`) to get that coverage. Recorded gaps,
  restarts and stale endpoints make power segments `unknown` and register deltas `coverage: "unobserved"`;
  source/unit change, conflicts, future and out-of-order endpoints are `unknown`. New `dispatch_started` event (written
  synchronously BEFORE the wire call, so it is only "possibly dispatched", not proof of sending) and reasoned
  `dispatch_aborted` events (including the pre-wire `upload_uncertain` returns); `dispatch_state` reads them together
  with `ack`. 2.5.122 corrected an earlier `dispatched`/`on_wire` naming that overclaimed: states are now
  `ack_received`, `dispatch_started`, `aborted_before_dispatch`, `conflicting`, `unknown`; only a received ACK shows the
  command reached the charger. Tests cover a crash before the call, unknown outcome, conflicts and a real
  fetch/readback association with the acked version. Retention is now 7 days / 4320 rows per kind (3.0 days at full 60 s rate).
- Tests: `python tools/run_isolated_logs_tests.py tests/test_stage_62_evidence.py tests/test_morek_worker.py
  tests/test_stage_95_recovery.py` -> all pass (1 skipped); ruff clean; `npm run build` and `check-dist` current at 2.5.122.
  No browser, full suite, live HA, charger, BMW, deployment, commit or push.
- Unverified: which entities the installation exposes and their cadence; that the capture tick yields useful data;
  the readback hook against the real fetch path; storage size on a real system. Not implemented: queries,
  observed-flow intervals, tariff snapshot per plan, per-session association, BMW cross-check.

### 2026-11-13 — Stage 6.1 source inventory (docs only; no version change)

- Repository inspection only; no live HA, Recorder, charger or BMW access and no code change (manifest stays 2.5.119;
  no build needed). The archived roadmap's "6.1 source inventory" section lists each source (session store/recorder, energy
  register, integrated power, live connector reading, Morek outcomes, debug day, Recorder statistics, BMW SOC and the
  BavarianData fixture) with evidence kind, timestamp, resolution, provenance, retention, association and limits.
- For 6.2/6.3: reuse `SessionStore`; genuine measurements are only HA entity states; no code reads Recorder state
  history or raw OCPP MeterValues; Morek outcomes and `debug_day` are not measured history; BMW data is a fixture
  catalogue only, and its domain (`bavariandata`) differs from the `cardata` named in `docs/supported.md`.
- Unverified: every installed source, cadence, Recorder coverage, Morek session-recorder wiring and BMW association.

### 2026-11-13 — 5.7b3 partial local acceptance (no version change; local mocked; PARTIAL)

- Scope limits: the user prohibited expensive/long-running tests including browser suites. No browser, live HA,
  deployment, charger command, commit or push happened. Integration and card are unchanged (manifest stays
  2.5.119; `npm run check-dist` still current).
- Worker timezone failure: cause was the isolated runner (`--noconftest`) skipping `tests/conftest.py`'s zone
  prewarm; `tzdata` is installed. `tools/run_isolated_logs_tests.py` now prewarms the same zones through a small
  plugin. `test_real_planner_publications_drive_worker_without_browser` now passes there.
- `test_manual_api_routes_owned_pause_without_legacy_executor` failed because its `AutoExecutor` store stub lacked
  `settings()`, which `_finish_owned_resume` reads; the stub now returns a non-admitted pause (test fixture only).
- Results: `python tools/run_isolated_logs_tests.py tests/test_morek_worker.py tests/test_stage_95_recovery.py`:
  156 passed, 1 skipped (real-planner to guarded worker, Stop, restart, stale and uncertain cases included).
  `test_morek_outcomes` and the 14.5 files: 27 passed. Frontend sidebar/live-charging/recovery-banner/morek-view
  vitest: 139 passed. Ruff clean on the changed Python.
- Pause-status browser assertion (source/jsdom only): `frontend/sidebar/browser-check.mjs` still expected
  "Controls unavailable until schedule ownership is confirmed", text no longer produced; current
  `paintAutomatic` emits "Resume unavailable: Schedule ownership is not currently authorized...", which
  `frontend/test/sidebar.test.ts` already asserts. Expectation updated; button-state and zero-write assertions kept.
  The 2.5.67 "Pause intent unknown" output was not reproduced or explained without a browser (a freshness/timing
  cause is only a hypothesis). The browser script has NOT been rerun.
- Unrun: browser check (desktop + mobile + interactions), broader planning/lifecycle runners, 5.4c HA-plugin suite
  (Windows `fcntl`), `test_morek_session.py` under the real plugin. Unverified: installed HA rendering, external
  writers, protection, physical charging.
- User checklist: install the release; open the sidebar; confirm the loaded version; check the live-charging panel
  shows reported state, measured power (or unknown) and the register separately; try Stop/Resume only when you accept
  the effect; after an HA restart confirm Morek status and that an unsent Resume asks for a fresh click; compare the
  BMW's own limit with SpotNav's plan; report anything saying unknown/uncertain.

### 2026-11-13 — Stage 9.5 recovery and visible blockers (2.5.117; local mocked; PARTIALLY met)

- Worker `_arm_blocker_timer` re-evaluates transient blockers (`morek_schedule.TRANSIENT_BLOCKERS`) after 60/180/600/900 s,
  at most 12 timer runs per episode, in addition to the existing reconnect, price, SOC and plug-in events; it only
  triggers the normal guarded reconcile. Sidebar `#recovery-banner` (`frontend/sidebar/recovery-banner.js`) from
  `reconciliation.blocker` / `.recovery.blocker_retry`.
- **Automatic recovery of an interrupted Resume was deliberately removed (2.5.117).** 2.5.115 recovered a
  never-dispatched/rejected/aborted Resume on affirmative ledger evidence and 2.5.116 added a `resume_unsettled`
  marker with a second settle write. Neither can exclude this crash window: a person Stop reserved only in memory
  while the Resume becomes durable, then a crash before the Stop's own record or the `resume_interrupted` marker.
  The ledger looks the same as an ordinary interrupted Resume, and any write ordering only narrows the window. So
  `resume_interrupted_recoverable`, `resume_unsettled` and the two-write sequence are gone. After a restart a
  `resume_requested` continues only with this process's ticket or the pre-existing 2.5.98 matching settled accepted
  attempt (id, acknowledgement, fingerprint); otherwise the person presses Resume again
  (`resume_requires_confirmation`). Kept: durable `resume_interrupted` marker (a Stop that pre-empts a committed
  Resume, written under the connector lock before the action returns), the in-process mark, uncertain-outcome
  blocking, and Stop precedence. **The race is not eliminated** (a Stop observed in memory whose record never lands
  still cannot be seen by a restart; it now only costs one explicit Resume instead of risking an unwanted one).
  9.5's "no reconfirmation after ordinary restart" goal is therefore not fully met for a never-dispatched Resume.
- Tests (isolated runner `python tools/run_isolated_logs_tests.py <paths>`): `tests/test_stage_95_recovery.py` covers
  blockers/banner status, never-dispatched/rejected/aborted Resume requiring a fresh Resume, a crash after the Resume
  commit with an unrecorded Stop, the in-process ticket, preserved matching settled recovery and recorded-Stop
  blocking; the two `test_morek_worker` tests are back to their original "requires confirmation" expectations.
  Run: stage 9.5 + worker 154 passed, with the known failures `test_manual_api_routes_owned_pause...` and
  `test_real_planner_publications...` (missing Europe/Stockholm tzdata, identical without the change). No browser,
  live HA, deployment or charger operation.

### 2026-11-13 — Stage 9.4 SpotNav log viewer (2.5.113; local mocked)

- Backend `api/logs.py` (`spotnav/get_logs`, admin only) over the existing `log_buffer.SpotNavLogBuffer`
  (added `seq`, `boot_id`, `query()`); sidebar `frontend/sidebar/log-viewer.js` mounted in `panel.js` for
  administrators. New INFO/WARNING lines: `_logged_action` on `async_record_owned_pause` /
  `async_charge_now_action`, `MorekSessionCoordinator._log_state`. Details, API findings and limitations are in the
  archived roadmap's 9.4 entry. Polling only; no stream; no live HA access.
- Tests: `tests/test_stage_94_logs.py` (20, run with `python tools/run_isolated_logs_tests.py`, which also
  accepts other test paths) and `frontend/test/log-viewer.test.ts` (7). No individual tests were removed. With the
  isolated runner `tests/test_morek_session.py` has 6 pre-existing harness failures (its fixtures patch
  `custom_components.spotnav.async_track_state_change_event`, absent from the runner's stub package); not caused by this
  change and not run with the real plugin because of the Windows `fcntl` limitation.

### 2026-11-13 — Stage 14.6 decision evidence (2.5.111; local mocked)

- Worker `_record_decision` (called when a run completes, never raises) + `morek_schedule.decision_event`,
  `decision_blocker`, `decision_status`; see the archived roadmap entry for fields and bounds. Logging goes through
  `_LOGGER` (INFO per new decision, WARNING for `upload_rejected`/`upload_uncertain`/`worker_unavailable`), so the
  existing SpotNav log buffer and debug bundle carry it; status `reconciliation.decision` / `.blocker`.
  Thresholds are unchanged (14.1-14.5); intent/ACK/readback/physical are separate stages and `physical` is
  always `not_measured`.
- Tests: `tests/test_stage_146_decision_evidence.py` (12): pure event/blocker whitelist, plug-in equal skip,
  changed send with readback states, 12 repeated SOC updates (1 send, 2 log lines), price interruption,
  unknown state preserve, unavailable charger and recovery, rejection/uncertain ACK, Stop race, event volume
  (40 alternating decisions: 10 kept, <= 42 lines) and privacy. The file zeroes the 2 s routine coalescing
  delay (fixture) so it runs in ~10 s. With the 14.3-14.5 and Morek worker files: 237 passed, 1 failed
  (`test_morek_worker::manual_api_routes_owned_pause...`, known harness failure listed above).
- 2.5.112 accuracy correction: `held` action for a blocked retry without a wire call (marker
  `spotnav_morek_dispatched`), continuity only when evaluated in that run, readback bound to the decision's
  attempt id (`superseded` otherwise); 3 production-path tests added to the file above (rejection then cooldown,
  early unavailable after prior continuation, matching/other-attempt readback). Safety behavior untouched.
  Run with the `--noconftest` recipe above; the same one known `test_morek_worker` failure remains.
- Limits: the status route itself (`reconciliation` assembly) is not exercised end to end, only the helpers and
  the worker; mocked boundaries only; no HA access, charger command, deployment or browser run.

### 2026-11-13 — Stage 14.5 fresh inputs and bounded recovery (2.5.109; local mocked)

- Planner (`auto_controller._capped_input_problem`, `soc_reading_order_problem`): on the capped Morek
  path a level for another/unknown car, dated >120 s in the future, or >5 s older than the newest one
  planned from (per vehicle and plug-in; memory only) gives `planning_unavailable`/`target_soc_stale`;
  no proposal replaces the accepted schedule. `live_vehicle_facts` drops a reading whose vehicle differs
  from the resolved one. `_vehicle_update_wait` (existing; measured register/integrated sessions only)
  now also guards this path: measured energy since the reading that covers the need holds the plan with
  `waiting_for_vehicle_update` (it also asks the car for a new level once per charge, as everywhere).
  Partial measured energy is subtracted from 2.5.109 (see corrections below); no adaptive learning added.
- Recovery (`morek_schedule.rejection_retry_at`, worker `_arm_retry_timer`): a definitely rejected
  automatic intent is retried at most 2 more times (300 s, 900 s) with `attempt.rejections` persisted;
  uncertain writes are never retried; `trigger(kind="recovery")` ranks below sensor. Status:
  `reconciliation.recovery` (accepted intent age, rejections, next retry, exhausted) and
  `reconciliation.inputs` (SOC source/age/estimated/uncertain); an acknowledgement is not proof of physical
  charging or of installed profiles.
- **2.5.109 corrections.** (1) Identity/ordering guards and progress accounting now also cover the uncapped
  Morek-owned target-SOC path (`_morek_owned`); non-Morek chargers are unchanged. (2) Partial measured energy:
  `vehicle_update_wait.measured_progress` / `AutoPlannerController._progress_adjusted` subtract measured
  session energy that began after the reading once from the need (and minimum); a newer reading rebases (the
  earlier session starts before it and no longer counts); energy covering the need gives
  `waiting_for_vehicle_update`; unattributable measured energy (session for no car, or a session that began
  before a reading older than 300 s and continues) keeps the accepted plan with
  `planning_unavailable`/`target_progress_uncertain`. Estimated-source sessions, no known plug-in and no
  charger controller change nothing (plan from the reading, as before). This replaces the earlier "partial
  measured energy is not subtracted" limit. An open session's `energy_kwh` is taken as the store reports it;
  its freshness was not verified. (3) The retry timer is armed from the durable rejection record at the start
  of every reconcile (restart-safe, even when the run sends nothing), never for uncertain/exhausted records,
  not re-armed when already due; sends still pass Stop/ownership validation. (4) Two existing
  `test_morek_worker` tests that swap in an older report as the plug-in's first level now clear the in-memory
  order memory. `_charger_controller()` is a small seam so tests drive the real wait/progress code.
- Tests: `tests/test_stage_145_fresh_inputs_recovery.py` (11) and `tests/test_stage_145_progress_recovery.py`
  (13: real controller path capped/uncapped with partial, covering, unattributable, no-meter, unknown plug-in,
  fresh rebase, wrong vehicle, future/out-of-order, non-Morek unchanged; restart timer, uncertain, exhausted,
  Stop). The earlier 11 include a stub of `_vehicle_update_wait`; the new file does not.
  (original list follows.) The controller tests need the fixture zone
  resolved (`time_zones._remember`), done by an autouse fixture; the measured-energy test stubs
  `_vehicle_update_wait` (its own logic is covered by `test_vehicle_update_wait.py`), so the capped-path
  wiring, not session accounting, is what it proves. Limits: out-of-order memory resets on restart; reading
  age has no cutoff; no sidebar text; no live/physical verification.

### 2026-11-13 — Stage 14.4 active-window interruption policy (2.5.107; local mocked)

**Review corrections (2.5.107):**

- Cap rule needs real evidence: the accepted profile's `acknowledged.cap` (`{value, basis}`, non-sensitive,
  written at acceptance) is compared with the current settings by `morek_schedule.cap_lowered`. Only a
  strictly lower cap on the same basis (or a cap where none applied) counts. An unrelated edit, a raised,
  unchanged or removed cap, a changed basis and every record without `cap` (older ledgers) preserve the
  window. `window_release(..., cap_lowered=, price_event=, ...)` replaced `edited=`.
- Price rule now checks the proposed schedule itself: price state `ready`, minimum shortfall known and 0
  when a minimum is configured, gap >= 30 min from the stop to the next resumption (no resumption: to
  ready-by), and the minimum energy (no configured minimum: the whole plan) delivered between now and
  ready-by minus 15 min at the plan's power. Same-energy cost through preserved windows as before.
  With no later window the same energy costs the same, so a no-resume stop never releases on price.
- A price event is kept in `MorekScheduleWorker._price_pending` until a run decided it (evaluated, preserved)
  or the schedule was accepted/`unchanged`. A refused/stale run, an unavailable charger, a rejected send or an
  uncertain write keeps it, and any later trigger (reconnect, retry) re-evaluates against fresh data; an
  uncertain write still blocks sends, and a rejected fingerprint is not resent. In memory only (lost on restart).
- Tests: 50 in `tests/test_stage_144_interruption_policy.py` (unrelated edit, raise, lowered, older record,
  fragmented insufficient minimum, no resume, thresholds, unavailable/rejected/uncertain price retention).
  With Stage 13/14, Morek, planner and capped suites 751 passed; the 5 failures are environmental or
  pre-existing (missing `Europe/Stockholm` tzdata x2 and the 3 listed below, identical without the change).
  Build and check-dist pass. No HA access; mocked only.

(Original 2.5.106 notes follow; where they differ, the corrections above win.)


- `morek_schedule.window_release(snapshot, settings, now, active_profile, edited=, price_event=, evidence=)`
  decides whether a replanned schedule replaces (rather than extends) the acknowledged active window;
  `MorekScheduleWorker._continued_profile` calls it after the Stage 14.2 evidence check and passes
  `active_profile=None` to `_proposed_profile` on release. `edited` = the accepted profile's
  `acknowledged_revision` differs from the current settings revision; `price_event` = the run's triggers
  (`_run_kinds`) include a `price` publication and the revision is unchanged. Nothing else can release,
  so routine SOC/recalc/plug-in/sensor runs and Pause/Stop/Charge Now/protection behave as before.
- Planner evidence: `PlanResult.current_interval` (`CurrentInterval`: the published interval holding
  `now`, its effective minor price, `within_cap`) and `PlanResult.minimum_energy_kwh`, set in
  `calculate_plan`; `AutoSnapshot.departure_at` supplies ready-by. Missing = unknown = keep.
- Thresholds (constants `RELEASE_*`, not settings): EUR 0.50 and 10% of the baseline (same energy, chronological
  through the preserved windows, configured fees via effective prices), baseline > 0, gap >= 30 min,
  slack >= 15 min beyond the minimum-energy time before ready-by; EUR areas only. Cap rule as in the archived roadmap.
  No loop: the replacement becomes the accepted profile, a repeated event is `unchanged`, and a flip between
  the two intent calculations yields `stale_work` then a non-price retrigger that preserves.
- Tests: `tests/test_stage_144_interruption_policy.py` (36: exact thresholds, negative/zero baseline, gap,
  slack, missing data, unknown state, cap rules, real planner evidence, worker send counts, uncertain write,
  Pause). Run with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin --noconftest
  -c /dev/null --rootdir . -o asyncio_mode=auto`; with Stage 14.1-14.3, Morek, planner and capped suites 748
  passed, 3 failed that also fail without this change in that harness (`test_morek_worker::manual_api_routes...`,
  `test_stage_13_reactive::...not_measured_energy`, `test_capped_auto_execution_isolated::...real_calculation`).
  Frontend build and check-dist passed (no frontend source changed). No HA/charger access; mocks do not prove
  savings, deployed behavior or physical charging.

### 2026-11-13 — Stage 14.3 recalculation triggers and send deduplication (2.5.105; local mocked)

- Cause tracking (review fix, 2.5.105): unchanged revisions alone no longer mean "SOC-only".
  `AutoPreviewController.async_recalculate(cause=None)` exposes `publication_cause` for the synchronous
  duration of the publish; only `_soc_moved` (`__init__.py`) passes `"soc"`. The worker treats a
  publication as routine (2 s burst, SOC end tolerance allowed) only when the revisions are unchanged
  AND the cause is exactly `"soc"`. Any other same-revision publication (deadline rollover, plan watch,
  unread notice, execution change, an unlabeled caller) is kind `recalc`: coalesced for 2 s but strict.
  A run that mixes causes is strict (`_strict` is sticky until a run completes unsuperseded, one run per
  burst). A price change coalesces the same way but is strict; a settings change, the first
  publication and every direct call (controls, Pause/Charge Now, sync, availability/reconnect,
  stale-work retry) use `_COALESCE_SECONDS` (0.1 s) and are strict. The wait is a shared earliest
  deadline (an urgent trigger shortens it, routine events never extend it).
- Evidence: `MorekSessionCoordinator.observe` calls `worker.note_plug_in()` only for Available to
  Preparing/Charging/Suspended. A connector sensor moving to or from unknown/unavailable calls
  `worker.note_sensor()`; a return to Preparing/Charging from unknown/unavailable is deliberately
  not a plug-in (the vehicle may have been connected all along) and initial seeding is neither. Both go
  through one coalesced `_evidence_run`: `planner.async_recalculate(kind)`, then a strict
  `trigger(kind=...)` comparison. Evidence noted during an in-flight recalculation gets another round
  (never lost, never concurrent). A failed recalculation still compares with what the planner has;
  the reconcile guards then decide (an unavailable charger or blocked plan sends nothing,
  `close()` cancels pending evidence). Nothing is sent by the evidence path itself.
- Deduplication: `morek_schedule.same_effective_schedule` (via `_send_profile_shared`, routine
  candidates only, never `force_sync`, pause or Charge Now) compares the last accepted routine
  profile (`acknowledged_profile`, planned under the same settings revision, now stored as
  `acknowledged.revision`) with the candidate from the candidate's own start: current permission,
  future absolute transitions with equal repeated limits collapsed, and attributes. Only for
  routine SOC-only runs may a 0 A instant differ, by strictly under five minutes (`_SOC_END_TOLERANCE`).
  Equal schedules return `unchanged`. The existing fingerprint dedup, `upload_uncertain` and
  rejected-attempt rules remain. A settings edit with an equal schedule is deliberately still sent once.
- Tests: `tests/test_stage_143_recalculation_triggers.py` (comparison/tolerance boundaries, actual send
  counts for repeated routine events, tolerated vs larger SOC change, same-revision deadline/unlabeled
  publications strict, mixed-cause burst strict, plug-in equal/changed, sensor loss/recovery through the
  real session with send counts, sensor loss while unavailable, failed recalculation, no plug-in inferred
  from unknown/unavailable returns, evidence coalescing, close, price, settings, sync, uncertain outcome,
  coalescing vs explicit control, Pause racing a queued routine update); the fake planner in
  `tests/test_morek_worker.py` has `publication_cause`. Isolated runner: 718 passed with the same 4
  pre-existing failures as before; the
  `test_morek_session.py` production-setup tests fail identically on HEAD in this isolated environment
  (missing HA import), 35 others pass. Ruff, `npm run build` and `check-dist` pass (frontend source
  unchanged). No HA, charger, deployment or restart was involved; deployed behavior and physical
  charging are unverified. 14.4/14.5/14.6 are not done.

### 2026-11-13 — Stage 14.2 active-window continuity (2.5.103; local mocked)

- `MorekScheduleWorker._continued_profile` (routine branch of `_intent`, not pause or Charge Now)
  takes `morek_schedule.acknowledged_profile(record)` (the durable `acknowledged` entry, which now
  stores `profile` and `routine` at acceptance; routine means no pause/Charge Now; record not
  uncertain; older records fall back to the matching accepted attempt), and `_proposed_profile(..., active_profile=)` unions its currently allowed window
  (`active_window`: now to the next 0 A change) with the planned windows via
  `continue_active_window`, then `profile_for`. A routine replan therefore cannot shorten or drop
  the allowed window, and the profile starts at 16 A with no 0 A gap. The fingerprint excludes the
  moving start as before; an unchanged merged intent is skipped as `unchanged`.
- Evidence: `connector_evidence` reads the existing OCPP connector status sensor, fresh within 180 s
  (same rule as `_session_readiness`) and returns `charging`, `waiting`, `unplugged` or `unknown`.
  Status is not measured power and nothing is inferred from the window or ACK. Only `unplugged`
  releases the window; `unknown` preserves it and the worker exposes
  `reconciliation.continuity` (`evidence`, `preserved`, `until`, `reason`) in the Morek status.
- `_verification_current` applies the same continuation for worker attempts, so a continued profile
  still verifies. Preserving would exceed three windows: refused as `active_window_block_limit`,
  nothing sent. A one-shot timer (`_continuity_timer`) retriggers 1 s after the preserved end.
- Review fix: the last accepted routine profile survives settings revisions (e.g. a raised price cap)
  and definitely rejected newer attempts, and a restart (it is in the persisted ledger), because
  `acknowledged` is only replaced by a later accepted write. Until 14.4 implements material-edit
  interruption, planning edits conservatively keep the active window. Uncertain/pending writes,
  an accepted pause or Charge Now (replaces `acknowledged`, non-routine), different current and
  unplugged evidence mean no continuation. The deployed ledger shape changed (additive). Unchanged: the immediate controls, protection, ownership,
  admission and uncertain-write guards. 14.3 (trigger/deduplication) and 14.4 (cap/price
  interruption) are not done; the sidebar does not display `continuity` yet.
- Tests: `tests/test_stage_142_active_continuity.py` (real worker with the usual mocked boundaries:
  charging/waiting/unknown preserve, unplugged release, shortening not sent, adjacent merge,
  settings edit, block limit, pause race, acknowledged-profile rules, timer, evidence freshness)
  and the changed assertion in `test_coalesce_deduplicate_and_changed_active_intent`. The isolated
  planning runner (now including the new file) passed 694 with the same 4 pre-existing failures as
  an unmodified HEAD; Ruff, `npm run build` and `check-dist` pass (frontend source unchanged,
  frontend suite not rerun). No HA, charger, deployment or restart was involved; deployed behavior
  and physical charging are unverified.

### 2026-11-13 — Stage 14.1 current interval and three-window limit (2.5.101; local mocked)

- `PlanRequest.include_current_interval` and `max_blocks` are set by the auto controller only
  for a schedule-owned (Morek) cheapest target-SOC plan (`_schedule_owned()`, now awaited before
  planning; failure or non-ownership is a legacy plan). The rest of the current published
  interval (`now` to the next grid boundary, proportional energy/cost at that interval's price)
  is a candidate in both planners. Cap-aware exact planner: a seeded optional first piece in the
  shared run budget, usable by minimum exceptions and truncated by a deadline inside the
  interval. Whole-slot planner (corrected in review): `_window(current=True)` subtracts the
  fragment's energy from the need and the run-limit searches (`_choose_auto/_capped`, `seeded`)
  start with it as an open run, so it may continue into the next slot, be a window of its own
  (counted in `max_periods`, `max_blocks` and, in automatic mode, the start cost) or alone cover
  the need. The plan with and without it are compared by energy (capped at the need) first, then
  trimmed (`ending_at_need`) cost, ties to the plain plan. It also applies to a best-effort plan
  short of its deadline (fragment plus every whole slot), to a deadline inside the current
  interval (the fragment up to the deadline, short unless it covers the need) and when later
  prices are missing at the planner level (a fragment that alone covers the need makes a plan
  without any later price), but the controller no longer installs such a plan: see the
  price-wait paragraph below. No minimum length: the old 60 s cutoff is removed.
  Not used: an unpublished current interval. A daily departure inside the current interval now
  resolves to today for these requests (`resolve_departure` referenced to `now`), both planners.
  `PlanResult.lead_kwh` carries the fragment's energy for `need_met_at`; the stored proposal
  summary counts the fragment as a slot (it failed its own consistency check before).
  Limitations: `plan_unpriced` ignores the fragment (a guarantee charges unpriced from the next
  boundary, as before); a tiny fragment can occupy one
  of the three Morek windows and may already be over when the profile is sent (`profile_for`
  drops elapsed windows); the fragment's price is assumed to apply proportionally.
- Morek plans use at most `MOREK_MAX_BLOCKS` (3, also what `profile_for` enforces) windows, including
  automatic-period mode (the whole-slot automatic search now carries runs in its state when
  limited). When an unrestricted calculation would have used more windows, the plan carries
  `block_limit`, `unrestricted_blocks`, `block_limit_extra_cost` and `block_limit_shortfall_kwh`;
  `price_policy` exposes a `block_limit` explanation shown by the sidebar. Unchanged: other chargers,
  `plan_unpriced`, history-wait estimates, and the chart's quarter-hour horizon rows (the fragment
  appears in `periods`/`slots`/`window_details`, which the chart overlays by instant).
- Price-wait with the fragment (2.5.101, review correction): `price_gap` still describes the request
  without the fragment (the unrestricted window), so a missing future price is a gap exactly as
  before. In the auto controller, an uncapped Morek request with a gap whose plan is made only of
  the current fragment (it covers the need and so requires no later price) is replaced by the
  unrestricted refusal (`include_current_interval=False`, `insufficient_price_horizon`), and then the
  existing `_plan_departure_by_history` / `_plan_while_prices_are_missing` decide as for any charger:
  `wait` (nothing charged now), `buy_now` (only what cannot wait), or `guarantee`. Urgency
  (`latest_safe_start`, `act_by`, wake-up) is unchanged. The one addition: `PriceGap.current` is the
  published rest of the current interval (`_lead_interval`, never priced from a neighbour), and
  `_known_intervals` lists it first among the intervals a `buy_now` may use, because the purchase
  plan itself (`include_current_interval` is kept) starts with it. That can turn a `guarantee`
  into a `buy_now` of a few seconds of the fragment when the publication is overdue and the part
  that cannot wait is smaller than the fragment; the remainder waits for the publication, exactly
  as for any `buy_now`. Capped plans are untouched (they never used `price_wait`; Stage 10.3's
  `partial_recheck_at` handles them). Tests: three controller cases in
  `tests/test_stage_141_current_interval.py` (wait, buy-now through the fragment, guarantee) and a
  `price_gap(...).current` case in `tests/test_planner_current_interval.py`. After this correction
  the isolated planning runner passed 674 with the same 4 failures, Ruff is clean, and `npm run build`
  and `check-dist` pass (no frontend source changed; the frontend suite was not rerun). Without the
  controller guard the wait and buy-now cases fail.
- A plan's first window now starts at the calculation instant rather than a grid boundary; the
  existing active-window path of `profile_for` treats it as already running, and the fingerprint
  excludes that moving start. Stability of repeated replans (14.2/14.3) is not addressed here.
- Tests: `tests/test_planner_current_interval.py`, `tests/test_stage_141_current_interval.py`
  (real controller with mocked ownership), `frontend/test/block-limit-policy.test.ts`. Isolated
  runners (after the review fix: planning 670 passed, the same 4 failures; frontend 2511 passed;
  check-dist and Ruff pass): earlier 656 passed with 4 failures that also fail on an unmodified HEAD export
  (`test_admission_is_reused_at_shared_boundaries_not_profile_writer`,
  `test_empty_missing_and_unavailable_are_not_measured_energy`,
  `test_saved_capped_settings_reach_real_calculation_and_preview`,
  `test_manual_api_routes_owned_pause_without_legacy_executor`); lifecycle 237 and notifier 14
  passed. Ruff on the integration is clean; frontend 2511 tests, build and check-dist pass. The
  full HA-plugin suite cannot start on Windows (`fcntl`). No HA, charger, deployment or restart
  was involved; deployed behavior and physical charging are unverified.

### 2026-11-13 — settled Resume recovery (local only)

- Read-only live status showed `resume_requires_confirmation` despite a settled
  Resume-associated worker attempt, blocking both Auto and Charge Now. The local
  worker and session coordinator can now recover that Resume from matching durable
  accepted attempt/acknowledgement evidence, subject to current ownership, identity,
  generation and person-Stop guards. Override verification uses the same evidence.
  An interrupted Resume without a settled matching dispatch still requires explicit
  confirmation; unknown outcomes remain blocked. This is a limited local fix, not
  proof every restart case is solved or that an old charger profile is absent.
- Focused mocked Resume/restart, Charge Now, session and Stop/late-ACK checks passed;
  Ruff, frontend build and check-dist passed. No profile or charger action, deployment
  or HA restart was performed. Live behavior after deployment remains unverified.

### 2026-11-13 — Stage 10.3 partial price horizon (local mocked)

- For a configured ready-by deadline, the capped planner retains eligible published
  cheap energy toward the target while future prices are missing. It computes a
  bounded urgent minimum exception from selected cheap energy before the next price
  re-evaluation and the existing derated charging capacity afterward; only known
  above-cap intervals ending by that re-evaluation may be selected. It does not use
  unknown prices. A shared period limit can prevent fitting the exception; in that
  case the existing cheap selection and explicit shortfall are retained rather than
  broadening a window. Full-horizon optimization is unchanged.
- Partial plans and empty waiting results expose the first contiguous coverage gap,
  and sidebar/card text warns that readiness and whole-horizon optimality are unknown.
  Target/minimum shortfalls are estimates, not measured energy or guarantees. The
  capped controller schedules a recheck every 15 minutes or the earlier expected
  publication; delayed publication therefore cannot leave the urgency calculation
  indefinitely unchanged. Normal price, settings and SOC events also replan.
- Uncapped price-wait remains unchanged. Its necessary known-price purchases now use
  the existing exact-end conversion for schedule-owned target-SOC plans, so the real
  Morek provenance check does not refuse a whole-slot overbuy. The worker retains its
  current-price coverage, identity, ownership, Stop, protection and uncertain-write
  gates; its bounded final 0 A is not proof of physical charging or installed profiles.
- Focused actual-module tests exercise capped and uncapped provisional proposals through
  real connector admission and mocked OCPP, publication replan, unchanged-intent
  deduplication, delayed-publication timer, minimum urgency, empty windows, price gaps,
  DST and existing guards/status/profile limits. No live HA, charger or deployment was
  accessed. The exact cause of the original installed-system report remains unknown.
- The focused selection passed 147 tests; 26 targeted frontend tests, Ruff,
  TypeScript checking, the frontend build and check-dist passed. This is not the
  full HA-plugin suite or a browser/hardware test.
- Scope: the new minimum urgency calculation applies when ready-by is configured;
  the existing no-departure 24-hour cap/minimum behavior is unchanged. Estimates assume
  planned power and the existing 0.8 feasibility margin; actual vehicle acceptance,
  electrical protection and physical charging are not established by mocks.

### 2026-11-13 — Stage 10.3 investigation (incomplete)

- No implementation was made. The capped planner already selects published slots
  without requiring a complete horizon, but if known cheap energy falls short of
  the minimum it can select above-cap slots merely because the remaining prices are
  missing. This is not the requested urgency policy. The uncapped controller has
  separate publication/history and deadline rules and must retain those semantics.
- `waiting_for_tomorrow` is already accepted by both `_proposed_profile` and
  `morek_plan_blocker`; the latter rechecks current inputs and actual listed price
  coverage of every selected window. The worker then uses connector admission,
  ownership, pause, protection and durable-outcome checks. Impaired `degraded` or
  `incomplete` combined price states are refused. This inspection does not establish
  which condition caused any particular user's missing proposal; actual end-to-end
  reproduction and the full partial-horizon implementation remain necessary.
- Focused existing mocked tests: 3 passed (known-price shortfall, minimum selection,
  and clean-start pause); 635 deselected. These characterize existing behavior,
  not Stage 10.3 acceptance. No HA, charger, deployment or physical testing occurred.

### 2026-11-13 — manual schedule sync (local only)

- The sidebar Morek panel offers **Recalculate & sync schedule** to administrators.
  It recalculates and asks the existing owned worker to send the current Auto schedule,
  including when that fingerprint was previously acknowledged. Pause, an active
  Charge Now override, uncertain outcomes, rejected identical attempts, admission
  and protection checks remain in effect. The request response is not an upload ACK;
  reconciliation status reports the later outcome. A newer planner event may
  supersede the explicit sync. No live charger action or deployment was performed.
- Focused mocked websocket/worker tests and a sidebar click test passed, as did Ruff,
  frontend type-check, build and check-dist. Physical behavior remains unverified.

### 2026-11-13 — Stage 10.2 sidebar control (2.5.95; local mocked)

- The existing sidebar presents Charge Now / Return to Auto as one daily control;
  its duration disclosure offers 30 minutes, one hour (default), two hours, three
  hours and a validated local custom end. An active override offers replacement
  inside the disclosure. The one activation confirmation gives the exact fixed end,
  price and cap comparison when available, and explains the price-plan override;
  the sent `end_time` is the same instant confirmed. Return warns that Auto may
  continue charging. Opening, rendering and refreshing issue only read requests.
- Backend status drives the displayed intent, outcome and reason; ACK, effective
  readback, session-start request and measured charging remain distinct. Existing
  Pause/Resume stays separate. Stale status, unsupported/unauthorized connectors,
  person Pause, offline state and unknown outcomes are explained and guarded. An
  in-flight or unknown request is not blindly retried. No backend defect was found
  in the contract review; no live system or charger was contacted.
- Focused mocked Charge Now sidebar tests (18), eight existing sidebar regressions,
  TypeScript checking, frontend build and check-dist passed. jsdom reported CSS
  parser warnings. Width-specific DOM checks do not establish rendered desktop or
  mobile layout, actual touch/keyboard interaction, HA compatibility or physical
  charging. No browser/Playwright or large suite was run.
- User-directed procedure after separately approved installation: inspect current
  status, choose a duration or end, review the single confirmation, then inspect the
  separate intent, ACK/readback and genuine charging observations. Return to Auto
  can continue charging, while Pause remains until Resume. This note grants no
  permission to deploy, restart or operate a charger.

### 2026-11-13 — Stage 10.1 verification and focused review (2.5.93)

- `_verification_current` now binds an accepted Charge Now attempt to the same
  connector-bound active override ID, owner ticket, lifecycle, fingerprint and
  reconstructed current intent. An old Auto attempt cannot verify a newer active
  override. Replaced, canceled, expired or paused intent cannot inherit old evidence;
  status labels a matching comparison `charge_now`. Effective readback remains a
  bounded observation, not profile inventory or proof of a session or power flow.
- Focused isolated selection: **70 passed**, including real-admission mocked OCPP
  request/readback and Stop at ledger, entry-store, admission and dispatch boundaries;
  late readback, default/selected/custom durations, restart/reconnect, offline expiry,
  missing SOC/prices, explicit pause, uncertain/rejected writes, available Auto now,
  unrelated identity, limits, and Auto/held-pause verification regressions. The
  previously failing real-admission late-ACK test now initializes its timezone and
  runs its assertions. A targeted jsdom sidebar open/no-write test passed (CSS parser
  warnings); Ruff, frontend build and check-dist passed. No browser/Playwright run.
- Stage 10.1 is locally complete for coordinator review; Stage 10.2 remains open.
  Mocks do not establish live OCPP compatibility, protection, transaction behavior,
  installed profiles or physical charging. No live HA or charger operation occurred.

### 2026-11-13 — Stage 10.1 production-path draft (2.5.92; incomplete)

- `spotnav/morek_schedule` accepts administrator `charge_now` and `return_to_auto`
  actions. Connector-bound intent is persisted in the existing ledger; the schedule
  worker uses it, sets an expiry timer even while offline, and triggers normal Auto
  reconciliation after expiry. Pause removes it; session authorization uses the
  existing coordinator. Price comparison is a read-only calculation and unavailable
  price or SOC does not itself block the bounded override. No UI was added.
- Actual-module mocked tests include real admission and durable storage through an
  OCPP mock, early return, replacement, missing plan, Pause/Resume, offline expiry,
  uncertain-upload reconnect, price comparisons and session coordinator integration.
  The focused selection passed 16 tests; Ruff, frontend build and check-dist passed.
  Existing session and ownership protections remain prerequisites, not proof of flow.
- **Remaining blocker:** `_verification_current` in `api/morek_schedule.py` still
  recomputes only ordinary Auto/held-pause fingerprints; an override attempt's distinct
  fingerprint cannot establish current readback verification and is superseded. Its
  ACK and uncertain outcome remain separately reported. Override-specific Stop/late-ACK,
  custom-end, status-read side-effect, changed-plan/restart and failure race coverage
  is also incomplete. Do not mark 10.1 complete or rely on this draft for operation
  before completing and reviewing those cases. Stage 10.2 remains open. No live HA,
  deployment or charger operation occurred; mocks do not prove physical charging.

### 2026-11-13 — Stage 10.1 partial schedule groundwork (2.5.91)

- `charge_now_profile` is an unwired builder using the existing fixed-current profile
  limits. It combines an active fixed-end interval with subsequent Auto windows,
  merging only continuous windows and refusing excess blocks or horizon. The caller
  must validate Auto provenance and all execution authority. It neither records an
  override nor sends a profile. Stage 10.1 remains incomplete: durable connector-bound
  intent, action and status API, lifecycle/restart/expiry, Stop and late-ACK races,
  session coordination, price reporting and the full focused test matrix are outstanding.
  Stage 10.2 remains open. No override is available for use.
- Two isolated actual-module builder tests passed, as did Ruff, frontend build and
  check-dist. Direct pytest could not load the HA plugin on Windows (`fcntl` missing).
  No live HA or charger operation occurred; mocks do not prove physical charging.

### 2026-11-13 — session review corrections (2.5.90; local mocked)

- A previously accepted random plug-in generation now blocks an initial Preparing
  recovery after HA restart, just like prior recovery/Resume generations. Pending
  and unknown records still block across unplug, reconnect and Resume. A genuinely
  observed unplug creates a durable, connector-owned marker; Finishing and unplug
  writes are ordered so rapid state changes do not resurrect an obsolete completion
  hold or discard a prior uncertain attempt. A new connection consumes the marker
  only when its start intent is durably recorded.
- An old, non-restored HA Preparing state can be corroborated by the uniquely
  resolved online OCPP 1.6 point's connector-scoped in-process Preparing metric.
  The tagged OCPP source exposes no timestamp for this metric, so it is last-known,
  not evidence of a fresh physical report or authorized transaction. The user
  accepted one bounded ambiguous request. Absent/conflicting metrics, restored HA
  state, an unsupported point or offline OCPP do not use this fallback. Events not
  durably recorded before a crash cannot be reconstructed; unobservable reboots and
  the 2.5.89 logging-level/interface blockers remain. No live charger was contacted.
- Focused actual-module lifecycle/session/readiness tests: 289 passed; four targeted
  worker reconnect regressions and Ruff passed. Build and check-dist were run. These
  mocks do not prove live session authorization, charging or installed compatibility.

### 2026-11-13 — observed reconnect recovery (2.5.89; local mocked)

- The user approved one recovery opportunity per observed OCPP offline-to-online
  edge without requiring a boot counter, as well as bounded ambiguous Preparing
  recovery and possible immediate charging if a schedule is ineffective. A switch
  becoming unavailable while the resolved OCPP charge point is still online is not
  treated as an offline edge. Repeated online callbacks do not create new attempts;
  durable outcome records deduplicate after HA restart, and pending/unknown outcomes
  remain blocked. Finishing holds, person Stop/Pause, ownership, connector identity
  and protection remain checked. A genuine plug-in, explicit Resume, observable
  reconnect or observed in-process boot-counter increase can supply an opportunity.
- A reboot with no observed offline transition or boot evidence cannot be separated
  from duplicate callbacks; explicit Resume or a later observable reconnect can
  supply a new opportunity, subject to the guards. The completion hold is written
  asynchronously: a crash before that write cannot be reconstructed. An accepted
  remote-start response does not establish an authorized session or measured flow.
- The local runtime blocks starts if INFO is enabled for `custom_components.ocpp`
  or the charge point's OCPP logger, or DEBUG is enabled for its websocket logger;
  unknown OCPP object/logger shapes also block. Request-task logging is filtered,
  without suppressing other tasks' diagnostics. Compatibility with the installed
  version and third-party logging remains unverified.
- Focused mocked session/readiness/lifecycle tests use the real command-admission
  boundary, a Resume action, availability callback and sentinel logging; targeted
  existing worker reconnect regressions, Ruff, build and check-dist were run.
  No browser, live HA, deployment, profile operation or charger action occurred.

### 2026-11-13 — ambiguous Preparing recovery (2.5.88; incomplete)

- The user accepted one extra request in ambiguous initial/reconnected Preparing;
  this is neither proof a prior session ended nor permission for live actions.
  Initial fresh non-restored connector status, reconnect, and explicit Resume now
  feed the coordinator. A durable fixed recovery generation prevents repeated ACKed
  starts across restarts, while a newly observed unplug/replug or explicit Resume
  has a distinct generation. Pending/unknown starts still block across generations.
  A recorded Finishing status holds recovery until new plug-in or explicit Resume.
- A reported charger boot counter increase within the same process creates a new
  generation; without that evidence, a further reboot cannot be distinguished from
  repeated callbacks and can remain blocked. Finishing is persisted asynchronously and can be lost if HA
  crashes before the write. Runtime INFO on `custom_components.ocpp` or the point's
  OCPP logger, or DEBUG on its websocket logger, blocks dispatch. No claim is made
  about unknown versions or physical charging. Full acceptance coverage and
  production review remain open; do not mark 5.6d complete.
- Local checks: isolated lifecycle, session and readiness tests 270 passed;
  Ruff, frontend build and check-dist passed. This includes a mocked real-admission
  start, but not the full requested production-wiring and crash/logging matrix.

### 2026-11-13 — initial Morek session coordinator (2.5.87; incomplete)

- The user explicitly accepts immediate charging if a schedule is absent or
  ineffective when a session is requested. No composite comparison is a start
  prerequisite; this does not authorize live operation during development.
- The worker owns a connector-status event coordinator. An observed Available to
  Preparing transition can request one start via the connected OCPP v1.6 object,
  under owned-profile admission, durable pre-dispatch outcome, person-Stop,
  ownership, identity, plan, pause and protection checks. A second definite
  rejection retry is bounded by a 60-second cooldown. Unknown/pending outcomes
  stay blocked even on replug. This is not a plan-window actuator; it never clears
  profiles or modifies current. No claim of physical flow follows an ACK.
- The request task's known OCPP and websocket logging is filtered; other tasks'
  protocol INFO and websocket DEBUG must already be disabled or the runtime path
  is refused. Runtime class and logger shape are checked. This is not a complete
  audit of future OCPP/library versions or third-party logging handlers.
- An initial Preparing status, including a vehicle connected while HA was offline,
  is still ambiguous and does not initiate a start. Surviving versus ended sessions
  after restart is not fully reconciled; retries, Resume, real admission, lifecycle,
  cancellation and late-response coverage remains incomplete. The substage stays
  open; do not infer production readiness or live behavior from mocks.

### 2026-11-13 — 5.6d drift and logging investigation (2.5.86; incomplete)

- The tagged OCPP integration requires `ocpp>=2.1.0` and `websockets>=14.1`;
  inspected OCPP 2.1.0 source logs serialized sent/received messages at INFO and
  websockets 14.1 logs frames at DEBUG. These can expose authentication material
  independently of the integration's own INFO message. Installed versions are not
  confirmed. No scoped redaction adapter has been implemented or tested, and no
  production start path, event wiring, persistence or recovery was added.
- The existing read-only schedule prerequisite now optionally allows up to 90s
  drift. It rejects a current time within tolerance of an expected or observed
  transition and a present limit that differs from intent; the status diagnostic
  uses that option. It does not associate the evidence with a validated worker
  attempt or rule out a later external limit change. It is not admission authority.
- Focused comparator tests, Ruff, frontend build and check-dist only; no browser,
  live HA or charger action. 5.6d remains incomplete and must not be marked done.

### 2026-11-13 — 5.6d tagged-source investigation (2.5.85; incomplete)

- Inspected the public v0.12.3 `switch.py`, `api.py` and `ocppv16.py`, not the
  installed system. The charge-control switch derives its on state from reported
  Charging/Suspended status; its start delegates to `start_transaction`, whose bool
  is the remote-start ACK, not proof of a transaction or flow. Preparing does not
  prove a previous transaction ended. Runtime version and compatibility remain unknown.
  The tagged start method itself logs the configured remote ID tag at INFO; the
  requested prohibition on logging that tag is not met by an unconditional call.
  Do not suppress or alter another integration's logging globally as a shortcut.
- Added a read-only same-preview schedule evidence diagnostic: at most 30 seconds
  old, exact transition comparison, bounded coverage and at most 16 A now. It is
  not a checked dispatch intent, profile inventory, authorization or protection
  proof. External writers can change limits after any read. It does not issue a
  fresh query or start. Event wiring, connector-bound start persistence, outcome
  recovery and all production start race tests remain open; 5.6d is not complete.
- Isolated lifecycle runner including the new comparator tests: 243 passed; Ruff,
  frontend build and check-dist passed. No browser, live HA, deployment, profile
  operation or charger action occurred. Mocked comparisons do not prove charging.

### 2026-11-13 — 5.6d read-only blocker groundwork (2.5.84; incomplete)

- The local checkout has no installed HA OCPP source; the screenshot demo switch
  merely changes a mock state. SpotNav's generic switch path issues blocking HA
  `switch.turn_on`/`turn_off`, returns a service-call success without an OCPP ACK,
  and cannot prove transaction authorization. The connector transaction sensor's
  sentinel, lifecycle and reconnect semantics are unverified. An effective composite
  schedule is not profile inventory and old verification does not establish safe
  limits at a future start. Installed source and trustworthy connector-bound fresh
  scheduling/electrical and session evidence are needed before dispatch can be designed.
- Read-only readiness now explicitly reports session start unimplemented or offline;
  the sidebar reports this separately from unknown transaction and measured flow.
  No automatic start/recovery, retry ledger or session action was implemented. The
  5.6d test matrix remains open; 5.7b2 owns measured-power binding. No HA contact,
  settings change, deployment, profile operation or charger command occurred.
- Local checks: isolated lifecycle runner with readiness tests (250 passed), sidebar
  tests (88 passed, plus the new focused status assertion passed separately), Ruff,
  frontend build and check-dist. Existing Python warnings and jsdom CSS warnings remain; no browser,
  full HA-plugin suite or hardware tests were run.

### 2026-11-13 — estimates, Morek target window and evidence (2.5.83; local)

- Battery energy estimates use valid last-known SOC even when old, restored or
  derived, while retaining provenance and stale/estimated labels. Missing inputs
  remain unavailable; estimates do not establish current SOC or the car's limit.
- A completed, identity-matched Morek schedule owner uses the existing partial-final-
  slot calculation for uncapped cheapest target-SOC plans. Other owners and capped
  plans retain their paths. A whole-slot target proposal with excess energy is refused
  by the Morek provenance check until replanned. Window, estimated energy/cost and
  Morek profile use the same boundaries (OCPP rounds inward to whole seconds).
  This assumes planned power and last-known SOC; neither physical charging nor an
  exact target/stop is established. Guarded reconciliation is unchanged otherwise.
- Uncapped current policy is explicitly serialized. Morek comparison coverage is
  tied to the actual readback timestamp; old records without that binding are
  unverified. Superseded and mismatched comparisons remain visible without claiming
  they describe another read. Missing errors no longer print undefined; weighted
  summary prices use two decimal places without rounding price inputs or tooltips.
- Focused mocked frontend and isolated actual-module planner/API tests plus build
  checks only. Browser, full HA-plugin suite, live HA, BMW and physical behavior are
  unverified. No HA contact, deployment, vehicle wake or charger action occurred.

### 2026-11-13 — single-car plan defaults (2.5.82)

- When no planning vehicle is saved and exactly one eligible non-guest vehicle is
  discovered, the sidebar proposes it with target-SOC mode, an 80% target, 40%
  ready-by minimum and 07:30 deadline. The UI marks these as unsaved proposals;
  only an explicit Save plan writes them and can trigger normal guarded replanning.
  An existing saved vehicle and plan are not overridden on subsequent visits, and
  ambiguous or guest vehicle cases are not automatically selected.
- Focused sidebar tests passed (85; jsdom CSS warnings). Frontend build and
  check-dist passed. No HA settings or charger action was performed, and the
  new version has not been validated in deployed HA.

### 2026-11-13 — single-vehicle planning selector (2.5.81)

- The sidebar incorrectly populated and validated planning vehicles from the SOC
  alternatives list, which may be empty when one vehicle is already resolved. It
  now reuses the old card's charger-eligible vehicle choices for both display and
  save validation. When no target is saved, the sole eligible vehicle is selected
  as a default in the form, but remains unsaved until Save plan; loading the sidebar
  does not change settings or command a charger. Multiple vehicles require a choice.
- Focused sidebar tests passed (84, with jsdom CSS warnings); frontend build and
  check-dist passed. Read-only HA diagnostics confirmed the relevant contract shape;
  no settings write, vehicle refresh or charger action was performed. Actual HA
  rendering and behavior of this new version remain unverified until deployed.

### 2026-11-13 — sidebar plan mode (2.5.80; local, review pending)

- The shared sidebar exposes explicit requested-kWh or target-SOC planning, requested
  energy, a discovered vehicle choice and target. Canonical revision-checked settings
  preserve the other mode's inputs and unrelated settings; changes remain drafts until
  saved. Missing/ambiguous/guest vehicle and observed capacity guidance reuse the
  dashboard, along with existing SOC age and source; a selected different vehicle's
  capacity is not inferred. The car's own limit remains separate. Existing fill-to-limit
  is preserved and noted rather than silently disabled.
- A saved change can trigger backend replanning and normal guarded reconciliation;
  it does not guarantee Resume or charging. Missing plan provenance is explained
  without weakening worker checks. No automatic setting, profile or charger action is
  issued by opening or editing the panel. Old SOC remains labelled and its planner
  policy is unchanged. The backend and planner remain the authority on prerequisites.
- Focused sidebar/settings mocks and an isolated actual settings-to-planner test use
  mocked HA boundaries. Browser, full HA-plugin suite, live HA, vehicle and hardware
  validation remain unrun. No HA contact, wake, deployment or charger operation.

### 2026-11-13 — sidebar clock skew (2.5.79; local, review pending)

- Dashboard and relevant Morek status freshness now accept up to five seconds of
  future clock skew, retain their existing age limits, and fail closed for missing,
  invalid, farther-future, old or failed observations. Sidebar control rendering
  and dispatch use the same freshness rules; failed dashboard reads immediately
  withdraw cached controls, including guarded manual Morek send. Messages distinguish
  failed reads, invalid timestamps, future timestamps and old observations.
- The fix does not establish that browser clock skew caused the reported failure;
  permission, ownership, Stop, uncertainty and other independent blockers remain.
  SOC freshness and worker plan provenance are unchanged. Confirmation of an action
  still requires a dashboard timestamp no earlier than dispatch and not in the future.
  Opening or refreshing only reads; no action or action retry is automatic.
- Focused mocked tests and frontend build/check-dist only; browser rendering, live HA,
  deployment and physical behavior remain unverified. No HA contact, Resume retry,
  profile operation or charger action was performed.

### 2026-11-13 — schedule-owned Resume UI (2.5.78; local, review pending)

- A reported 2.5.77 sidebar showed a pending schedule pause, unavailable Resume
  and `undefined`. The notice was uninitialized and concatenated into text. The
  sidebar also relied on the legacy dashboard's Pause/Resume axis even when the
  schedule owner had its own durable pause. It now offers explicit Resume for a
  fresh, authorized schedule-owned pause with known non-uncertain outcomes, including
  a pending request that requires confirmation after restart. It does not bypass a
  pending Stop, unknown outcome, stale status, permission or ownership check.
- The exact reason for the reported unavailable control was not supplied; the
  sidebar now distinguishes stale observations, in-flight/unknown actions,
  permission, missing owner authority and pause evidence rather than attributing
  it to one presumed cause. Failed dashboard refreshes also block cached controls.
  No action is issued on opening the panel and there is no automatic retry.
- Focused mocked sidebar/Morek tests and actual-module clean-start/Stop routing
  tests passed; frontend build and check-dist passed. Browser, full HA-plugin and
  live hardware validation remain unrun. No HA contact, deployment, Resume retry
  or charger operation was performed; a retained final 0 A may remain.

### 2026-11-13 — automatic paused clean start (2.5.77; local, review pending)

- The user accepted that missing ownership and outcome history could conceal an
  earlier action. For a uniquely identified supported Morek with a durably saved
  active pause, startup now writes a connector-bound clean-start marker and held
  schedule intent, then a completed owner. It preserves the original pause, does
  not fabricate a profile attempt, and sends or clears nothing during initialization.
  Missing history is not evidence that a charger profile is absent.
- Completion and the existing migration recovery proof are reread; a partial
  clean-start marker is reused after restart. Known pending/uncertain operations,
  malformed or conflicting ownership, held exits, ambiguous identity, active Stop
  reservations and linked site-regulator conflicts remain blocked. Landed writes
  follow the existing policy: a valid proof on disk is revalidated on restart even
  if its caller did not observe success. A Stop not durably recorded before a crash
  cannot be reconstructed. An active durable pause is required; initialization
  reports `pause_unavailable` instead of silently inventing one.
- The worker does not send the initial held schedule automatically. Explicit Resume
  records schedule-owned intent, then clears only the unchanged legacy pause and
  triggers normal guarded replanning; it never calls the legacy start/stop path.
  A linked site regulator remains a dispatch blocker. A retained old profile or
  final 0 A may remain until an explicitly authorized later operation changes it.
- Focused actual-module mocked tests cover initialization, no fake attempt, explicit
  Resume, repeated recovery, landed and interrupted writes, cancellation, Stop and
  identity/lifecycle races, pending/unknown outcomes and ownership blockers. Mocked
  sidebar and Morek tests, targeted Ruff, frontend build and check-dist passed.
  Browser, full HA-plugin suite, live HA, physical protection and charger behavior
  remain unverified. No HA contact, deployment or charger operation occurred.

### 2026-11-12 — one-time automatic migration requested (historical; superseded above)

- The user explicitly accepted the risk that absent ownership/outcome history could
  conceal an earlier operation. Missing history alone is therefore eligible for a
  one-time automatic clean start; it is **not** proof that the charger is clear.
  Recorded uncertain or in-flight operations, malformed or conflicting evidence,
  held exit, identity conflicts and unresolved protection still must block dispatch.
  This decision supersedes the earlier suggestion that missing history itself needs
  a manual recovery decision. The clean-start implementation remains open.
- The user approved automatic one-time migration without a new confirmation button,
  and specifically wants a durable completion so it does not repeat on each start.
  This changes the earlier preference for a supervised button; it does not authorize
  live HA contact, deployment or charger operations. Preserve the manual Stop, and
  continue blocking actually uncertain outcomes, identity conflicts and Stop races.
- A focused actual-module mock reproduces the reported combination: absent owner,
  no connector outcome attempt, historical accepted legacy upload and durable manual
  Stop. The accepted legacy record alone does not create a settled connector ledger;
  the existing startup deliberately leaves ownership missing. The test passes and
  makes no profile call. No migration implementation was completed in this session.
- The outstanding implementation needs crash-safe, connector-bound durable migration
  evidence without fabricating a previous attempt, and an ordered transfer of the
  existing manual Stop into schedule-owned intent. Existing handover explicitly
  refuses manual Stop and requires a settled attempt; restart recovery and profile
  admission independently enforce that same requirement. A partial shortcut would
  either lose the pause or misrepresent unknown history. The user expects this to be
  solved automatically; the old refusal remains until a complete implementation and
  focused restart, crash and Stop-race tests are reviewed.
- A further focused actual-module regression confirms the existing completed-owner
  recovery proof can be revalidated across two simulated restarts without rewriting
  ownership or outcome storage or issuing charger commands. It preserves an existing
  schedule-owned Stop. This is useful restart groundwork, **not** an implementation
  of the missing-owner migration or a test of converting the user's legacy manual Stop.

### 2026-11-12 — Resume ownership refusal (2.5.76; review pending)

- `legacy_execution_ownership_blocked` is a pre-effect refusal from the legacy
  admission boundary, not an unknown transport outcome. The sidebar now preserves
  that code without latching an unknown action. After the normal read-only refresh,
  it displays the actual current legacy admission reason and separately notes a
  missing ownership record, when reported. A later status cannot prove the exact
  cause of an earlier refusal.
- Actual-module mocks reproduce routing: an established schedule owner receives
  a durable Resume intent only with eligible pause evidence; otherwise Resume falls
  through to guarded legacy admission. Missing ownership, an unfinished transition,
  a lifecycle barrier and a person Stop can each prevent that fallback. Startup
  deliberately does not create missing ownership during migration; there is no safe
  automatic correction when first use cannot be distinguished from lost metadata.
  Seek a supervised ownership and retained-profile decision rather than assuming
  the old schedule is absent or clearing it. No profile is written by diagnosis.
- Focused actual setup/admission/outcome/routing tests and sidebar tests pass;
  frontend build and check-dist were run. Browser, full HA-plugin and live hardware
  tests remain unrun. No HA access, Resume retry, deployment, vehicle refresh or
  charger operation occurred. A final 0 A may remain; no physical behavior or
  installed-profile inventory is established.

### 2026-11-12 — Stage 12.4 Morek evidence (2.5.75; review pending)

- The shared sidebar presents a short plan-confirmation summary and separate
  proposal, sent/ACK, effective readback and measured-charging observations.
  Readback age, reported coverage, supersession, mismatch, offline and unknown
  outcomes are kept distinct. Power remains unavailable because this path does
  not have a verified Morek measurement binding. Detailed transitions, drift,
  ownership and technical controls are expandable; opening them does not write.
- Status previously could retain `verified` after the comparison coverage expired.
  It now withdraws the current verification outside that bounded interval and
  distinguishes comparisons against a held pause from comparisons against the
  current plan. The sidebar additionally treats a readback older than 90 seconds
  as historical; this is presentation freshness, not a new admission rule. An ACK
  response timestamp is not stored, so it is explicitly unavailable. No previous
  uncaptured Resume error is diagnosed by these changes.
- Focused actual-module status and mocked sidebar tests, frontend type-check,
  build and check-dist were run. Browser, mobile rendering, full HA-plugin suite,
  live HA and hardware remain unverified. No HA contact, vehicle refresh,
  deployment or charger operation occurred. A final 0 A may remain; readback is
  not profile inventory and neither it nor an ACK proves physical charging.

### 2026-11-12 — Stage 12.7 Resume and evidence (2.5.74; review pending)

- The manual-action endpoint preserves domain refusals and reports unexpected
  exceptions as unknown outcomes. Resume saved before a concurrent person Stop is
  a committed request with interrupted follow-up, not a no-effect refusal; its
  ticket is not issued. The sidebar retains codes, reports failed Stop requests
  without claiming physical flow, refreshes observations, and does not retry an
  unknown action. Older `spotnav_action_failed` answers are treated conservatively.
- The connector ledger migrates legacy evidence in memory when missing; that is not
  proof of an empty charger. Migration/restart authorization requires a valid owner,
  connector-bound completion proof and settled attempt, among other guards. Status
  previously called any missing/unsettled attempt uncertain even with `uncertain:
  false`; it now reports missing, unsettled, uncertain or unavailable separately,
  without granting admission. Recovery diagnostics retain their existing codes.
  Missing ownership routes away from owned actions and remains subject to legacy
  admission. None of these observations identifies the earlier uncaptured error.
- Focused mocked actual-module status, action, person Stop and restart tests and
  sidebar tests passed; build and check-dist passed. Existing pytest/dependency and
  jsdom CSS warnings remain. Full HA-plugin, browser and hardware tests were not
  run; no HA access, deployment or charger operation occurred. A prior final 0 A
  may remain; readback is not inventory or physical charging. Broader 12.4 evidence
  redesign remains open.

### 2026-11-12 — Stage 12.3 plan details (2.5.73; review pending)

- The dashboard API exposes the current calculation's ready-by instant and
  per-window wall energy and configured-variable cost, derived from selected
  planner slots and exact shown-window boundaries. It verifies coverage and
  reconciliation with unrounded planner totals; inconsistent details are withheld.
  Unpriced plans no longer present zero as a cost. A total weighted average is
  displayed only with a known currency, cost basis and positive energy.
- Cheapest target-SOC plans retain their calculation-time SOC and effective wall
  kWh per SOC point for per-window projections. A valid old reading is permitted
  and explicitly labelled with source/age when known; the estimate can be wrong
  after driving and is not measured charge or the BMW's own charge limit. Manual,
  hybrid, missing-input and older-backend projections remain unavailable rather
  than guessing. Historical or stale proposals remain unavailable.
- Focused planner/API and shared sidebar tests, Ruff, frontend type-check, build
  and check-dist were run; see session results. Browser, visual regression, full
  HA-plugin suite and actual HA/vehicle behavior were not tested. No HA contact,
  vehicle refresh, deployment or charger action occurred.

### 2026-11-12 — Stage 12.8 last-known SOC planning (2.5.72; review pending)

- Capped target/minimum planning accepts a valid last-known actual SOC regardless
  of age, including unknown age; it still refuses energy-derived SOC estimates,
  invalid SOC and invalid age metadata. Uncapped planning retains its existing
  estimate behavior. Morek provenance no longer refuses solely on age or because
  a reading predates plug-in; its price, ownership, lifecycle, identity, Stop and
  uncertainty checks remain. The immediate SOC protection floor keeps its own
  original freshness rules. Old readings can be inaccurate after driving.
- Vehicle report timestamps and SOC entity identity are included in the in-process
  planner evidence. The existing reader watches an unambiguous report-time sensor;
  a newer timestamp triggers recalculation, while unchanged HA state writes and
  restored values do not claim a new report. Unchanged schedule intents remain
  deduplicated. When an integration supplies no trustworthy vehicle timestamp,
  same-value HA rewrites cannot establish a genuinely new report. The sidebar
  preserves 12.6's age/source labels and warns that plan results are estimates.
- Focused actual-module planner, reader, Morek worker/admission and mocked sidebar
  checks, Ruff, frontend build and check-dist were run; see session results. The
  Python harness reports existing pytest/dependency warnings. No browser, full
  HA-plugin suite, live HA, vehicle refresh, deployment or charger action occurred.
  No physical charging or installed automatic execution is established by mocks.

### 2026-11-12 — Stage 12.6 SOC provenance (2.5.71; review pending)

- The existing selected-vehicle reader prefers a live charger SOC when available,
  otherwise the selected vehicle. It already uses an unambiguous vehicle report-time
  sensor where available; otherwise HA `last_updated` is a state-write time, not
  proof the vehicle reported. The dashboard now exposes a separate optional SOC
  observation: timestamp basis, integration, raw/retained reading and restored
  state, alongside the existing effective reading and energy-derived estimate.
  A retained anchor is shown only for the same selected vehicle. Neither an HA
  rewrite nor a dashboard refresh is described as a new vehicle report.
- The shared sidebar keeps valid old SOC visible with its source and advancing age
  when known, labels unknown report time and estimates, and shows available battery
  capacity/efficiency. Stale, estimated or unknown-time SOC is not promoted into
  fresh sidebar projections. The existing planner/execution freshness and safety
  thresholds, selection and vehicle refresh behavior are unchanged. Other SOC
  consumers of the existing contract have not been redesigned.
- Focused mocked checks: sidebar tests 51 passed; isolated actual-module SOC and
  dashboard provenance tests 4 passed; shared-plan tests 3 passed; Ruff, frontend
  type-check, build and check-dist passed. Python's isolated harness reports existing
  pytest configuration and dependency warnings. Browser, full HA-plugin suite,
  actual HA/BavarianData timestamp availability and physical behavior were not
  validated. No vehicle refresh, live HA access, deployment or charger action.

### 2026-11-12 — merge dashboard work into main (2.5.70)

- Combined the 2.5.68 Web Awesome registration/refresh work from main with the
  independently developed 12.1 and 12.2 dashboard changes. Resolved the version
  conflict with 2.5.70 and rebuilt the card and sidebar assets from merged sources;
  neither branch's generated bundle was used as a conflict resolution shortcut.
- Local checks: frontend build and check-dist passed; focused sidebar and price-chart
  tests passed 54 tests, with jsdom CSS parsing warnings. The isolated published
  interval and sidebar registration checks passed; isolated planning plus price
  provenance tests passed with one skip. Direct pytest collection failed because
  the installed HA plugin imports Unix-only `fcntl` on Windows. No live HA access,
  deployment or charger action was made for this merge; the full HA-plugin suite
  remains unrun.

### 2026-11-12 — sidebar Web Awesome collision (2.5.68; local only)

- The installed 2.5.66 blank panel's reported duplicate `wa-icon` exception was
  reproduced in a browser against the previously built sidebar by registering the
  icon first. Web Awesome 3.14.0's Lit decorators register components on module
  evaluation, including transitive dependencies; guarding only the dashboard's
  top-level imports did not protect those dependencies.
- The sidebar and shared-preview esbuild rules now guard Web Awesome's own bundled
  `wa-*` decorators individually. No global registry patch or blanket import-error
  suppression is used. An existing element wins: a different or incompatible Web
  Awesome version (or another implementation) may still have different behavior
  or appearance. The build transform is specific to the pinned 3.14.0 chunk and
  decorator format and must be rechecked when upgrading Web Awesome.
- The shipped sidebar and card contain no `sourceMappingURL` or
  `scoped-custom-element-registry` reference; the sidebar build does not emit source
  maps. A missing source-map request is normally a non-fatal developer-tools lookup,
  not a JavaScript module load. Its precise origin in the installed browser was not
  established; no 404 was concealed and no HA assets were inspected.
- Local Edge regression against the built panel covers clean registry, pre-existing
  icon, pre-existing icon plus button, repeat bundle load, and card coexistence. It
  checks mounted dashboard content, dialog use, preserved registrations, page errors,
  and mocked read-only calls. Full frontend suite: 102 files / 2,428 tests passed;
  type-check, build and check-dist passed. Desktop/mobile preview and panel browser
  checks passed in read-only mode (write interaction cases skipped); the separate
  mocked desktop/mobile price chart check passed. The existing browser check had
  stale Pause wording/disabled expectations, corrected to match current code; no
  Pause, Resume, profile or settings write was sent in the read-only runs. jsdom CSS
  parse and Git line-ending warnings remain. Initial browser attempts also encountered
  an occupied debugging port, stale cached bundle and Edge extension resources.
- No live HA, deployment or charger operation occurred. Actual HA rendering and
  compatibility with other installed component versions remain unverified. 5.7b's
  monitoring and broader acceptance work remains open; preserve its parallel edits.

### 2026-11-12 — 5.7b partial local continuation (2.5.67; not complete)

- The sidebar now treats a failed dashboard refresh as stale immediately, withdrawing
  cached connection, SOC and proposal observations until a successful refresh. A
  focused mocked adapter test covers failure and recovery. This does not add charger
  writes or establish a measured-power or reported-charging binding.
- Source inspection: `execution/power_energy.py` reads configured W/kW power
  entities and checks device class; its integration path uses `last_reported` and
  source-dependent age limits. The controller can use a smart-plug or discovered
  charger power entity, while an energy register may take precedence. The adapter's
  `charging_state()` falls back to a control state and is not proof of charging;
  `charging_observation()` also falls back when no status entity is configured.
  The live sidebar still displays measured power as unavailable. Connector association,
  source/freshness handling and charging-status display need a careful wired and
  tested implementation; availability in the user's installation is unknown.
- Planning runner: 584 passed, 1 skipped, 1 deselected. Lifecycle runner: 198
  passed; expanded ownership/admission/schedule/outcomes/readiness run: 347 passed.
  Focused actual bootstrap/worker recovery run: 7 passed, 299 deselected. Broad
  worker run stopped after 242 passed: `test_real_planner_publications_drive_worker_without_browser`
  failed because `Europe/Stockholm` was not initialized in that harness. This is
  not a passing full end-to-end regression. The HA-plugin dashboard suite fails
  before collection on Windows with `ModuleNotFoundError: No module named 'fcntl'`.
- Frontend type-check, build, check-dist and focused sidebar/Morek tests (63 passed)
  pass. The existing mocked browser check fails at the pause-status assertion: it
  expects an uncertain Pause and old unarmed wording but receives unknown intent.
  It did not complete mobile or interaction acceptance. Targeted Ruff passed.
  Pytest timeout-option and dependency deprecations, jsdom CSS parse messages and
  Git line-ending warnings remain. No live access or deployment was performed.
- 5.7b remains open: complete practical monitoring, full real-admission regression,
  browser checks and coordinator review. Older eligible owners may require one admin
  reconfirmation; a Stop not durably recorded before a crash can be lost. Unknown
  writes remain blocked. Disabling the integration may leave a stored schedule or
  0 A limit. ACK and effective readback are neither profile inventory nor physical
  charging; external writers and native protection remain unverified.
### 2026-11-12 — Stage 12.2 price display and provenance (2.5.69; review pending)

- The current provider route is not necessarily the provider of a held day file.
  Repository day snapshots now retain each contributing file's provider, market
  date, fetch time and state; the dashboard API exposes these separately from the
  current route, including split-day mixed sources. Older backends or records with
  unknown provenance show it as unavailable, rather than inferring it from a cap
  basis. Freshness includes fetch age and failed/stale state, not a guarantee that
  market data is current. Routing already prefers the loaded Nord Pool integration
  for supported areas, otherwise its existing alternatives; no selection is forced.
- EUR source prices and the cap are displayed in c/kWh, with edits converted back
  to the existing major-unit/kWh settings contract; other currencies stay in their
  major units. An unchanged saved cap keeps its exact stored value, and a market
  currency change blocks an open draft. Chart price text uses consistent rounding;
  interval boundaries and underlying planner values are unchanged. Unknown live
  per-window costs and weighted prices remain 12.3, not fabricated here.
- Fast checks: focused sidebar/price tests, isolated actual-module repository/API
  provenance tests, shared-plan tests, Ruff, frontend type-check, build and
  check-dist. No browser, visual or large-suite checks were run, per request;
  actual HA rendering and physical behavior remain unverified. The full HA-plugin
  dashboard suite remains unrun. No live HA access, deployment or charger action.

### 2026-11-12 — Stage 12.1 sidebar controls (2.5.67; review pending)

- The sidebar selects a sole charger, restores a valid session selection, handles
  list failures and stale replies, and preserves an unsaved draft on reconnect;
  a changed settings revision blocks its save until explicit reload. Opening only
  performs read requests. The shared dark controls include explicit shadow-root
  colors and clearer saved values, units, mode, ready-by and optional cap/minimum
  guidance. Nord Pool is suggested as a cap basis only; it is not selected or
  saved automatically and does not identify the actual provider. Manual energy
  mode points to the existing SpotNav card Plan settings for SOC configuration.
- A valid SOC-mode settings record with a missing target can now save an unrelated
  edit without creating a target. Existing permission, revision and Morek action
  checks remain. No planner policy or charger safety interlock changed.
- Mocked sidebar and settings tests: 170 passed; frontend type-check, build and
  check-dist passed. Existing jsdom CSS parser warnings occur. A local browser
  smoke attempt did not reach its fixture; further browser tests were not run at
  the user's request. Actual HA rendering, mobile touch and hardware remain
  unverified; no HA access, deployment or charger operation occurred. The full
  HA-plugin dashboard suite remains unrun. 12.2–12.4 and 5.7b remain open.

### 2026-11-12 — non-profile automatic recovery (2.5.66; coordinator review pending)

- The existing connector outcome store now carries a minimal versioned recovery
  proof bound to the completed owner migration ID and physical connector. Migration
  writes it after producer drain, verified completion and current lifecycle/Stop
  checks; admin reconfirmation of an eligible old completed owner writes the same
  proof. Neither operation sends or clears a profile. Recovery validates ownership,
  unique connector, settled outcome and durable Pause/Resume intent, and the worker
  still requires current planner provenance. Old records without a proof or the
  existing post-dispatch evidence require one admin reconfirmation.
- **Landed-write policy:** a valid proof on disk is accepted on restart even if the
  prior save raised or was cancelled. A Stop requested but not durably saved before
  a crash may be lost; no process can reconstruct it. A newer durable Pause remains
  authoritative and a pending Resume still requires fresh confirmation after restart.
  Unknown OCPP outcomes remain blocked, never automatically retried. The proof does
  not establish physical charging, profile inventory or installation protection.
- Actual-module mocked tests cover migration without a profile send, automatic
  restart, eligible old-owner reconfirmation, landed proof with failure/cancellation
  and Stop races, retained durable Pause, and real admission/worker execution. The
  user-reported native protection, external writers and charger behavior remain
  unverified. 5.7a is marked locally complete for coordinator review; 5.7b remains
  open for broader end-to-end regression and practical charging/health monitoring.
- Checks: `python tools/run_isolated_planning_tests.py -x` 584 passed, 1 skipped,
  1 deselected; `python tools/run_isolated_lifecycle_tests.py -x` 198 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_execution_ownership.py
  tests/test_command_admission.py tests/test_morek_schedule.py tests/test_morek_outcomes.py
  tests/test_morek_readiness.py -x` 347 passed. The actual-bootstrap focused run
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_worker.py -k
  "actual_restart_recovers_bound or landed_nonprofile_proof or actual_setup_to_real_worker_profile_send or completed_restart_requires" -x`
  passed 7. Targeted Ruff, frontend type-check/build/check-dist and sidebar/Morek
  tests (62 passed), and diff check passed. The planning runner skips the actual
  bootstrap test, which was run by the focused lifecycle command. Existing pytest
  timeout/deprecation, jsdom CSS and Git line-ending warnings remain. The full
  5.4c HA-plugin suite was not run; no live access or deployment occurred.

### 2026-11-12 — non-profile restart proof boundary (2.5.65; incomplete)

- Added an actual handover/storage/admission regression in
  `tests/test_stage_23_lifecycle.py`: the completion write lands, a Stop is
  reserved, and the save raises. Ownership and outcome bytes remain present,
  while a restarted gate refuses automatic recovery. A successful completion can
  leave the same bytes; its process-local ticket and the failed caller's exception
  or non-durable Stop do not survive restart. This test does not implement a
  non-profile proof or complete 5.7a.
- The requested distinction between an ordinary successful proof write and a
  proof write that landed before failure/cancellation is not represented by HA
  Store's atomic file contents. A further proof/commit marker has the same final
  write boundary. A durable Stop, if recorded, remains actionable; a Stop never
  recorded before a crash cannot be reconstructed. The smallest unresolved choice
  is whether to accept a landed, correctly ordered proof as sufficient even when
  its caller did not observe successful return, or require an external transactional
  mechanism that durably orders proof and Stop. Neither is assumed here. Existing
  automatic recovery after a settled migration-bound worker response is retained;
  older or never-sent completed records still need reconfirmation on restart.
- Mocked checks: `python tools/run_isolated_planning_tests.py -x` 584 passed,
  1 skipped and 1 deselected; `python tools/run_isolated_lifecycle_tests.py -x`
  194 passed; the expanded lifecycle run with `tests/test_execution_ownership.py
  tests/test_command_admission.py tests/test_morek_schedule.py tests/test_morek_outcomes.py
  tests/test_morek_readiness.py -x` 343 passed. Focused lifecycle runner with
  `tests/test_morek_worker.py -k "actual_restart_recovers_bound or
  clean_handover_and_possibly_landed_completion" -x` passed 2. Ruff on the changed
  test, frontend type-check/build/check-dist and focused frontend tests (62 passed),
  and diff check passed. Existing pytest timeout/deprecation, jsdom CSS and Git
  line-ending warnings remain. The full HA-plugin dashboard suite was not run.

### 2026-11-12 — bounded automatic restart recovery (2.5.65; partial)

- A settled OCPP response to an actual ticket-admitted worker call stores a
  connector- and migration-ID-bound dispatch witness in the outcome ledger. That
  establishes that this process issued the completion ticket and passed the final
  checks before the call; it does **not** establish profile inventory, effective
  limits or physical charging. After a process restart, startup can automatically
  revalidate that witness, durable owner, settled ledger, unique identity and
  lifecycle/Stop generation, then release the barrier. A previously durable Pause
  remains in force; a pending Resume still needs its own fresh confirmation. No
  profile is sent by migration or recovery itself.
- A process that crashes immediately after the completion marker lands but before
  issuing its ticket can leave precisely the same `completed` owner and previously
  settled ledger as one that completed normally but has not yet made a worker call.
  The marker alone is not safe automatic authority. Consequently old 2.5.64 records
  and a newly migrated owner without a settled post-handover worker response still
  need explicit admin reconfirmation. An unchanged old ACK cannot be bound to a
  migration after the fact. In particular, if no new worker call occurs after that
  reconfirmation, another restart still requires it. This does not yet satisfy the
  requested universal ordinary-restart behavior; 5.7a remains open. Resolving that
  remaining ambiguity needs either a separately reviewed non-profile ordering proof
  or a product decision allowing one-time handling of the ambiguous old state; it
  cannot be solved by treating the existing `completed` marker as sufficient.
- A Stop requested but not durably recorded before a crash cannot be reconstructed.
  In-process Stop reservations invalidate pending recovery even if identity is
  temporarily unresolved; durable Stop/Pause and uncertain profile outcomes still
  block stale Resume or retry. A real setup/worker/restart test covers automatic
  recovery with a retained Pause; a separate real-planner/production-admission test
  covers automatic restart followed by a fresh mocked profile call. Mocks do not
  prove charger protection, absence of external writers or physical charging.
- Checks: `python tools/run_isolated_planning_tests.py -x` 584 passed, 1 skipped,
  1 deselected; the skipped actual-bootstrap restart test separately passed via
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_worker.py -k
  actual_restart_recovers_bound -x` (1 passed). `python tools/run_isolated_lifecycle_tests.py
  -x` 193 passed; the expanded lifecycle run with `tests/test_execution_ownership.py
  tests/test_command_admission.py tests/test_morek_schedule.py tests/test_morek_outcomes.py
  tests/test_morek_readiness.py -x` 342 passed. Targeted Ruff and frontend
  type-check/build/check-dist plus sidebar/Morek tests (62 passed), and diff check
  passed. Two initial attempts to run the actual-bootstrap restart test failed:
  the planning runner deliberately stubs the integration bootstrap, and the
  lifecycle runner initially lacked a prewarmed timezone; the test now skips only
  in the former and prewarms the zone in the latter. Existing pytest timeout-option,
  dependency deprecation, jsdom CSS and Git line-ending warnings remain. The full
  5.4c HA-plugin suite was not run.

### 2026-11-12 — real-admission provenance and reconnect (2.5.64; coordinator review pending)

- The existing process ticket is invalidated on disconnect, but a separately held
  in-process reconnect candidate can be revalidated against durable completed owner,
  settled ledger, unique identity, lifecycle and Stop generation. Only a clean
  reconnect originating from a current ticket can restore it. A Stop, changed identity,
  uncertain outcome, unload or superseding lifecycle event prevents that recovery.
  On an HA process restart there is no candidate: an admin must use **Reconfirm
  schedule ownership**. A completion write that landed before interruption and a
  Stop never recorded before a crash cannot be ordered from the disk marker alone.
- Actual planner plus production admission and disk-backed ledger tests cover changed
  price state, authority, document, coverage, source and revision; SOC value and age,
  vehicle identity, settings and connection changes during each pre-dispatch store
  boundary. They also cover fresh replanning, unchanged-value ageing, deduplication,
  no retry after an unknown write, and late ACK and composite readback after Stop.
  Verification now rejects a worker's superseded ticket or pending Stop even when a
  late ACK is recorded as historical. None of this establishes physical charging.
- Additional actual-admission tests cover concurrent Resume/Stop during pause-intent
  persistence, cancelled reconnect revalidation and a newer barrier while its ledger
  read is pending, as well as unsupported plan modes and pending Resume after restart.
  5.7a is marked locally complete for coordinator review. 5.7b remains open for
  broader end-to-end and charging/health monitoring; mocks are not deployed evidence.
- External writers and native protection remain unverified; effective readback is not
  profile inventory or measured physical flow. Disabling SpotNav can leave a schedule
  or 0 A limit. No live HA, deployment or charger operation was performed.
- Checks: `python tools/run_isolated_planning_tests.py -x` 584 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py -x` 186 passed; the lifecycle runner
  with `tests/test_execution_ownership.py tests/test_command_admission.py
  tests/test_morek_schedule.py tests/test_morek_outcomes.py tests/test_morek_readiness.py
  -x` 335 passed. Focused real-admission worker tests reported 31 passed; focused
  reconnect tests reported 7 passed. Targeted Ruff, frontend type-check, build,
  check-dist and sidebar/Morek tests (62 passed) and `git diff --check` passed.
  Existing pytest timeout-option/deprecation, jsdom CSS and Git line-ending warnings
  remain. The full 5.4c HA-plugin suite was not run.

### 2026-11-12 — wired completion and guarded worker (2.5.63; review required)

- A versioned `completed` handover carries the original connector-bound migration
  ID. The real producer-locked handover saves and reads it back, rechecks generation,
  lifecycle and identity, and only then issues an in-process ticket. Barrier release
  and production owned-profile admission require both. The worker rereads durable
  ownership and the attempt ledger before its final synchronous checks and wire call.
- On restart the ticket is absent even if completion landed. A narrowly scoped
  admin-only **Reconfirm schedule ownership** action rereads the owner and settled
  ledger and releases only the current barrier. It sends no profile; a later worker
  trigger is needed to reconcile. Ordinary restart and reconnect require this fresh
  confirmation. Unconfirmed owners, missing documents, held exits and uncertain
  outcomes remain blocked. A Stop that never reached durable storage before a crash
  cannot be reconstructed. The reconfirmation does not verify physical charger state.
- Mocked tests use real setup, ownership, admission, ledger and worker to reach a
  mocked OCPP call after restart/reconfirmation; migration and reconfirmation do not
  themselves send. Tests also cover Stop during final worker persistence, completion
  save/readback cancellation and Stop/lifecycle races, and blocked recovery cases.
  Existing planner provenance and worker regressions include simulated admission;
  the complete requested real-admission race/provenance matrix has not been established.
  Therefore 5.7a remains open for coordinator review, and this is not a deployment
  recommendation. 5.7b remains open for end-to-end regression and monitoring.
- External OCPP writers and native protection are not proven by local mocks. The past
  mismatch is a historical unknown, not a current observation; a genuinely uncertain
  persisted outcome blocks dispatch. ACK/readback do not establish physical charging
  or profile inventory. Disabling SpotNav may leave a schedule or 0 A in place. No
  live HA, hardware or deployment was accessed.
- Local checks: `python tools/run_isolated_planning_tests.py -x` and the same
  runner with `tests/test_morek_worker.py -x` each reported 553 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py -x` reported 179 passed; the expanded
  lifecycle run with `tests/test_execution_ownership.py tests/test_command_admission.py
  tests/test_morek_schedule.py tests/test_morek_outcomes.py tests/test_morek_readiness.py
  -x` reported 328 passed. Targeted Ruff, frontend type-check/build/check-dist and
  `npm run test -- test/sidebar.test.ts test/morek-view.test.ts` (62 passed), and
  `git diff --check` passed. Initial tests exposed stale unarmed-status assertions;
  those expectations were updated and reruns passed. Pytest timeout-option and
  dependency deprecations, jsdom CSS parsing and Git line-ending warnings remain.
  The full 5.4c HA-plugin suite was not run.

### 2026-11-12 — lifecycle barrier correction (2.5.62; incomplete)

- The real startup/reconnect barrier now refuses to release for an old owner or
  `owner_written_unconfirmed`. The store does not yet produce or recognize
  `completed`, so this intentionally retains the barrier for all current records.
  Production schedule admission remains unconditionally unarmed; this is not the
  requested completed implementation and is not ready for installation.
- The missing code boundary is the completion save and restart recovery connecting
  `ExecutionOwnershipStore.async_handover_unarmed` to
  `CommandAdmission.async_release_lifecycle_barrier` and `async_execute`. A save
  can land before failing or being cancelled, and an unrecorded Stop cannot be
  reconstructed after a crash. A durable completion alone therefore cannot establish
  ordering in every such race; implement conservative restart recovery or fresh
  explicit user action, plus actual production admission and the requested race matrix.
  No further installation-specific decision or live proof is required to implement it.
- External writers and native protection remain unverified limitations, not universal
  machine-proof prerequisites. The past mismatch is historical, not a current charger
  observation; persisted uncertain outcomes must still block. Disabling the integration
  can leave a schedule or 0 A limit in place. No profile was sent or cleared.
- Local checks: isolated planning 551 passed, 1 deselected; lifecycle 162 passed;
  expanded lifecycle/ownership/admission/schedule/outcome/readiness 309 passed;
  isolated planning with worker argument 551 passed, 1 deselected. Targeted Ruff,
  frontend type-check, build, check-dist and sidebar/Morek tests (61 passed) passed.
  Initial lifecycle and expanded runs failed one setup expectation after the barrier
  change; the expectation was corrected and both reruns passed. Existing pytest
  timeout-option/deprecation and jsdom CSS warnings remain. The full HA-plugin
  dashboard suite and the requested new completion/production-send matrix were not run.

### 2026-11-12 — connector-bound unconfirmed handover witness (2.5.61; partial)

- Fresh unarmed entry transitions now use version 2 with a random migration ID,
  retained across requested/drained/interrupted states. The existing owner save
  copies that ID into a connector-bound `owner_written_unconfirmed` witness; legacy
  version-1 transitions and old owner records remain readable. An old owner without
  a witness reports unverified. The held-exit transition removes only the owner-side
  metadata as it creates its existing legacy held marker; no charger state is changed.
- This witness records that the owner save was attempted, **not** that handover
  completed. A Stop or cancellation can occur while the owner save is awaiting, and
  a save may land before that interruption is known. A restart must not treat the
  witness as completion. Production admission remains unconditionally unarmed;
  no user control or automatic dispatch was added. The product decision does not
  require impossible proof of absence of external writers; the concrete remaining
  blocker is a crash/Stop-safe durable completion protocol and its final-dispatch
  enforcement, plus the requested production-path and race matrix. Physical retained
  state and the historical mismatch remain installation-specific unknowns, not proof
  of an empty inventory or permission to clear. 5.7a and 5.7b remain open.
- Mocked coverage checks matching migration IDs after an actual unarmed handover,
  old records, malformed/unsupported evidence and after-write uncertainty. It does
  not prove the full requested completion-save matrix or real production admission.
  No HA, charger, profile, deployment or physical behavior was accessed or tested.
- Checks: `python tools/run_isolated_planning_tests.py -x` 551 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py -x` 162 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_execution_ownership.py
  tests/test_command_admission.py tests/test_morek_schedule.py tests/test_morek_outcomes.py
  tests/test_morek_readiness.py -x` 309 passed. Targeted Ruff, frontend type-check,
  build, check-dist and focused sidebar/Morek tests (61 passed), and diff check passed.
  Existing pytest timeout-option and dependency-deprecation warnings, jsdom CSS and
  Git line-ending warnings remain. Full 5.4c HA-plugin suite remains unrun.

### 2026-11-12 — startup and handover race hardening (2.5.60; partial)

- Startup reserves the existing lifecycle barrier before its first ownership await;
  it may release only through the same current, durable-owner and outcome checks
  after unarmed handover. A callback now retains an entry barrier even if the current
  identity appears unrelated, without blocking positively unrelated connectors.
  Handover captures the entry lifecycle revision and treats any change as interruption,
  including an identity changing away and back while an owner save is awaiting.
- The real reconnect callback now has mocked handover tests for Stop, duplicate
  callbacks, temporary identity change, cancellation and failure at requested,
  drained and owner-save waits. Before the first marker lands a crash can still leave
  the prior legacy document on disk; startup's new process-local barrier is not durable
  proof of completed handover or of first use. This does not close every crash/restart
  or duplicate-entry test gap, nor prove external OCPP writers settled.
- Production owned-profile admission remains unconditionally unarmed. The current
  owner record has no durable completion witness distinguishable from an interrupted
  owner save, and no enforceable installation evidence establishes external-writer
  or protection safety. Profile inventory and the historical mismatch remain unknown;
  ACK/readback do not prove physical charging. A complete evidence and final-dispatch
  protocol, including a safe way to resolve those installation facts, is still needed.
  No live HA, hardware, deployment, profile clear or charging action was performed.
  5.7a and 5.7b remain open for coordinator review.
- Checks: `python tools/run_isolated_planning_tests.py -x` 548 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py -x` 162 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 306 passed.
  Targeted Ruff, frontend type-check, build, check-dist and focused sidebar/Morek
  tests (61 passed), and diff check passed. Existing pytest timeout-option and
  dependency deprecation, jsdom CSS, and Git line-ending warnings remain. Full
  5.4c HA-plugin suite was not run.

### 2026-11-12 — verified reconnect barrier release (2.5.59; partial)

- A reconnect callback captures a per-entry barrier revision. After initialization,
  release takes connector admission, verifies the unique current schedule owner,
  rereads and compares the durable ownership document, and checks the settled outcome
  ledger. It then rechecks revision, lifecycle epoch, identity, connector generation,
  person Stop and in-process uncertainty before removing only that entry's barrier.
  Another entry's barrier is not removed. The owner admission path continues to refuse
  legacy/manual writers, and production owned-profile admission still unconditionally
  returns `schedule_mode_unarmed`; release is not a profile-write authorization.
- Wired mocked callback tests cover a successful release and refusal after a newer
  disconnect, uncertain ledger, ambiguous identity, Stop reservation or cancellation.
  They verify the actual production gate and legacy/manual exclusion. No simulated
  production activation or charger operation is claimed. Full requested callback-bound
  duplicate-contender and each persistence/Stop-boundary matrix remains unproven;
  existing lower-level handover regressions remain in place. The 2.5.58 process-lifetime
  barrier description below is historical and superseded by this bounded release.
- First-use/lost-state provenance, historical profile mismatch, unknown retained
  consequences, external writers, protection, authorization and measured flow remain
  unresolved. No live HA, profile action or deployment occurred. 5.7a and 5.7b remain open.
- Local checks: `python tools/run_isolated_planning_tests.py -x` 548 passed,
  1 deselected; `python tools/run_isolated_lifecycle_tests.py -x` 153 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 297 passed.
  Targeted Ruff, frontend type-check, build, check-dist and focused sidebar/Morek
  tests (61 passed), and diff check passed. Existing pytest timeout-option and
  dependency-deprecation, jsdom CSS and Git line-ending warnings remain. The full
  5.4c HA-plugin suite was not run.

### 2026-11-12 — reconnect writer barrier (2.5.58; partial)

- Availability callbacks now synchronously reserve a process-local entry/connector
  barrier before scheduling initialization, invalidate queued generation tokens and
  interrupt an active drain. The legacy and manual profile admissions recheck the
  barrier; already admitted work is drained through the existing connector lock.
  Positively unrelated connectors bypass it, and the separately reserved person Stop
  and regulator-protection paths are not reclassified. Unresolved identity retains
  an entry barrier rather than being treated as an unrelated connector.
- The barrier is deliberately not released in this unarmed implementation, even
  after a successful migration; no task completion or unload can reopen it. Lifecycle
  epochs suppress stale initialization after a newer availability transition or unload.
  The existing durable ownership/transition record remains necessary across restart.
  Production owned-profile dispatch stays unconditionally unarmed. Future activation
  must explicitly review barrier lifecycle and final dispatch validation.
- Mocked actual-module tests now exercise the real charger setup through ownership
  handover before the real Auto executor start boundary; a reconnect callback with
  its background coroutine held; a Stop reservation; stale reconnect completion;
  and a writer already in admission before reconnect. The full requested matrix of
  duplicate contenders, identity changes, interruption and persistence boundaries
  through the newly wired callback has not been established. Existing lower-level
  transition regressions remain; do not infer full 5.7a completion from them.
  External writers, profile inventory, native protection and physical flow remain
  unverified. No live HA, profile operation or deployment was performed.
- Validation: `python tools/run_isolated_planning_tests.py -x` 548 passed,
  1 deselected; `python tools/run_isolated_lifecycle_tests.py -x` 141 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 285 passed.
  Targeted Ruff, frontend type-check/build/check-dist and focused sidebar/Morek
  tests (61 passed), and diff check passed. Two early lifecycle runs timed out
  because the new test waited at the wrong barrier; the test was corrected. One
  subsequent run failed an existing unsubscribe identity expectation; the non-migration
  path now keeps the original callback and the rerun passed. Existing pytest timeout
  configuration and dependency deprecations, jsdom CSS and Git line-ending warnings
  remain. The full 5.4c HA-plugin suite was not run. 5.7a and 5.7b remain open.

### 2026-11-12 — 5.7a wired unarmed migration (2.5.57; partial)

- Charger setup now uses existing entry/drain and producer-locked handover before
  starting Auto. It accepts only a uniquely bound durable legacy record and, at
  handover, a connector outcome ledger containing a settled attempt; missing or
  uncertain outcomes leave the durable entry marker and ordinary writers blocked.
  A missing ownership document is not recreated on this setup path. Existing held
  exits and interrupted entry markers remain untouched. Owned-profile admission is
  still unconditionally unarmed; this is not automatic charging or physical evidence.
- Actual setup invokes the migration helpers, and mocked tests exercise the helpers
  with actual admission, store, executor and controller, as well as setup ordering
  with mocked producers. A fully wired positive setup test and the requested complete
  restart, reconnect, cancellation, duplicate contender and Stop boundary matrix
  remain outstanding. In particular, the availability callback schedules its
  initialization asynchronously; whether a legacy writer can enter before a late
  reconnect migration establishes its latch needs further investigation. Do not
  consider single-owner migration complete or deploy this as a verified release.
- Ledger evidence is not profile inventory and does not establish absence of
  external writers or resolve protection, authorization or the historical mismatch.
  No charger command, clear or live operation was performed. The preserved
  enable/disable draft stays inaccessible through WebSocket. 5.7a and 5.7b remain open.
- Checks: `python tools/run_isolated_planning_tests.py -x` 548 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py -x` 138 passed; expanded lifecycle
  with `tests/test_morek_schedule.py tests/test_morek_readiness.py
  tests/test_command_admission.py tests/test_execution_ownership.py
  tests/test_morek_outcomes.py -x` 282 passed. Targeted Ruff, frontend type-check,
  build, check-dist and focused sidebar/Morek tests (61 passed) passed. An initial
  lifecycle run failed an old expectation that startup admits two legacy writes;
  the test was changed to expect the new interlock, and the rerun passed. Existing
  pytest timeout/deprecation, jsdom CSS and Git line-ending warnings remain. Full
  5.4c HA-plugin suite was not run.

### 2026-11-12 — 5.7a single-owner direction (2.5.56; partial)

- The user's revised direction is one Morek schedule owner, not a runtime switch
  back to legacy. Startup and reconnect now preserve requested, interrupted and
  drained unarmed migration markers rather than automatically aborting them to
  legacy; held exits stay blocked. The old internal explicit guarded abort still
  exists and is not a new user control. This change does not migrate a legacy
  record to the schedule owner or prevent all legacy Morek execution today.
- An interrupted previous 5.7a draft added `schedule_request` ownership fields,
  internal request methods and WebSocket action branches. They are preserved for
  coordinator review, but the two draft WebSocket actions now unconditionally
  refuse before reaching those branches; no user-facing switch is offered. The
  draft is not an admission invariant and has not been fully race-tested. Production
  owned-profile dispatch remains unconditionally `schedule_mode_unarmed`.
- Missing ownership is still initialized as legacy for compatibility; that is not
  first-use evidence. A safe transition that preserves Stop while draining all
  producers and resolves interrupted/unknown writes remains necessary before
  claiming a sole schedule path. Held exits and retained profiles are unresolved;
  external writers, actual protection configuration, transaction authorization,
  the historical mismatch and trustworthy measured flow require installation-specific
  investigation. Neither ACK nor composite readback establishes profile inventory
  or physical charging. Do not infer authorization from the revised product direction.
  Target-SOC cheapest-price planning remains the only provenance-checked automatic scope.
- Disabling the integration can stop SpotNav activity without clearing a profile;
  a stored schedule or 0 A limit may remain. No physical stop is promised. There
  was no live HA, deployment, profile action or physical validation. 5.7a and 5.7b
  remain open; stop for coordinator review.
- Mocked checks: `python tools/run_isolated_planning_tests.py -x` 548 passed,
  1 deselected; `python tools/run_isolated_lifecycle_tests.py -x` 134 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 278 passed.
  The first expanded lifecycle run stopped at one test expecting the previous
  automatic abort; that regression now explicitly exercises failed guarded recovery
  and passes. Targeted Ruff, frontend type-check, build, check-dist and sidebar/Morek
  tests (61 passed), and `git diff --check` passed. Existing pytest timeout-option
  and dependency deprecation, jsdom CSS parsing, and Git line-ending warnings remain.
  The full 5.4c HA-plugin suite was not run.

### 2026-11-12 — 5.7a partial blocker reporting (2.5.55; review required)

- Read-only readiness adds explicit incomplete activation, first-use/lost-state and
  retained-profile blockers. Sidebar evidence explains these and the unresolved held
  exit, external writers, protection and authorization, and distinguishes disabling
  uploads, Pause and profile removal. It introduces no activation intent or action.
  Production owned-profile admission remains unconditionally `schedule_mode_unarmed`;
  schedule-owned controls remain disabled and `exit_held_unarmed` has no release.
- 5.7a is **not complete**: a durable, deliberate enable/disable protocol, proof of
  safe entry and handback, final dispatch revalidation and the requested new full
  mocked transition/race matrix remain. Missing ownership/outcome history cannot
  prove first use or absence of retained profiles; neither ACK nor composite readback
  is an inventory or physical-flow evidence. External writers and installation
  protection require an installation-specific resolution, and authorization and
  trustworthy flow measurements remain unverified. User attestation alone does not
  establish these unknowns. Only target-SOC cheapest-price provenance is supported.
  No new load controller, BMW control, profile clear or retained-limit release exists.
- Local checks: `python tools/run_isolated_planning_tests.py -x` 544 passed,
  1 deselected; `python tools/run_isolated_lifecycle_tests.py -x` 130 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 270 passed.
  `python tools/run_isolated_planning_tests.py tests/test_morek_worker.py -x`
  also reported 544 passed, 1 deselected. Targeted Ruff and frontend type-check,
  `npm run build`, `npm run check-dist` and focused sidebar/Morek tests passed
  (61 tests); `git diff --check` passed with line-ending warnings.
  Pytest reported existing timeout-option and dependency deprecation warnings;
  jsdom reported CSS parse warnings. The full 5.4c HA-plugin suite remains unrun.
  No live HA, deployment or physical charging was tested. Stop for coordinator review;
  5.7a and 5.7b remain open.

### 2026-11-12 — 5.6c invalid plans and writers (2.5.54; mocked, quick review)

- Quick coordinator review found no blocker to proceeding to 5.7a. Independently
  reran the isolated planning suite (544 passed, 1 deselected) and listed lifecycle
  suite (270 passed); existing pytest configuration/deprecation warnings remain.
  Not a comprehensive safety audit or deployed verification. Keep unsupported plan
  types refused and the production gate closed until the complete activation path and
  its blockers are actually resolved and tested.

- Automatic Morek intent now compares the calculation's process-local source,
  vehicle and connection evidence with current inputs, synchronously at each existing
  shared-send validation. It checks current per-day state/authority and actual UTC
  price intervals covering the remaining windows, including day boundaries and DST.
  It refuses stale/changed/missing evidence without clearing a retained limit; unchanged
  SOC age alone is not a change, while existing SOC freshness rules still apply.
  Pause's held-off intent does not require a plan or prices. Manual preview/send keeps
  its existing plan-validation contract. Production owned-profile admission is still
  unconditionally unarmed; schedule-owned sidebar controls stay disabled.
- This is deliberately conservative: only target-SOC cheapest-price plan provenance
  is currently supported; manual-kWh and solar/hybrid plans fail closed as
  `plan_input_provenance_unavailable`. Manual energy's mutable register/session
  accounting and hybrid forecasts do not have a demonstrated synchronous provenance
  boundary here. This restriction must be reviewed and resolved if those modes are
  needed for activation; it does not prohibit the existing manual experiment.
- Stop reservations now also invalidate manual Send/Clear across their ledger and
  entry-store awaits. A known pre-dispatch abort is recorded and prior sent evidence
  is restored; an interrupted restoration is not described as a sent attempt in
  status. Existing unknown-outcome latch, restart Resume reconfirmation, identity and
  ownership checks, and regulator-protection exception remain. The status API and
  Morek details show worker blockers without conflating ACK/readback and measurement.
- External/OCPP writers and the installation's native protection cannot be proved or
  controlled by these mocks; composite schedules are not profile inventory. Held exit
  still has no release and is an explicit 5.7 activation blocker. First-use/lost-state
  provenance, authorization and protection conflict resolution remain open. No live
  HA, charger, deployment or physical behavior was tested.
- `python tools/run_isolated_planning_tests.py -x`: 544 passed, 1 deselected.
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x`: 270 passed.
  Targeted Ruff passed; in `frontend/`, `npm run build`, `npm run check-dist`,
  `npm run type-check`, and `npm run test -- test/sidebar.test.ts
  test/morek-view.test.ts` passed (61 tests). A first run of a new DST test failed
  because `shown_periods` is computed, not an initializer field; its fixture was fixed.
  Pytest reported the existing timeout-option and dependency deprecation warnings;
  jsdom reported CSS parse warnings. Full 5.4c HA-plugin suite remains unrun.
  Stop for coordinator review; 5.7 remains open.

### 2026-11-12 — 5.6c partial investigation (2.5.53; not complete)

- Manual profile admission now checks connector generation again after its awaited
  ownership lookup. A mocked person Stop reservation at that boundary refuses the
  older operation before its callback. This does not recall an already admitted or
  external operation, or establish a complete competing-writer policy.
- Existing worker paths refuse reported unavailable/stale/unpriced/invalid plans,
  retain pending Resume confirmation across restart and latch uncertain outcomes.
  However, `snapshot_is_current` establishes latest calculation/settings identity,
  not by itself time-based price or other input freshness at dispatch. Whether all
  relevant changes reliably publish before dispatch requires further actual-module
  investigation, implementation where needed, and delayed/restart/recovery tests.
  The full requested 5.6c status and competing-writer matrix remains outstanding.
- Ordinary SpotNav writers use ownership guards; the explicitly classified regulator
  protection path is separate. External/OCPP or installation-specific writers are
  not controlled or inventoried here. Protection must not be disabled. Held exit has
  no release path and is an explicit 5.7 activation blocker; no profile removal or
  release mechanism was added. Owned dispatch remains unconditionally unarmed and
  schedule-owned sidebar controls remain disabled. No live behavior is claimed.
- Checks: `python tools/run_isolated_planning_tests.py -x` 523 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_morek_readiness.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_outcomes.py -x` 269 passed;
  `ruff check custom_components/spotnav/execution/command_admission.py
  tests/test_command_admission.py` passed. In `frontend/`, `npm run build`,
  `npm run check-dist`, `npm run type-check`, and `npm run test --
  test/sidebar.test.ts test/morek-view.test.ts` passed (60 frontend tests).
  Pytest reported existing timeout-option and dependency deprecation warnings;
  jsdom reported CSS parse warnings. Full 5.4c HA-plugin suite remains unrun.
  No live HA, hardware or deployment actions. Stop for coordinator review.

### 2026-11-12 — 5.6b Pause and Resume (2.5.52; local mocked, quick review)

- Quick coordinator review found no blocker to 5.6c. Independently reran the
  isolated planning suite (522 passed, 1 deselected) and listed lifecycle suite
  (256 passed); existing pytest configuration/deprecation warnings remain. This
  review was not a comprehensive safety audit or deployed verification. Preserve
  the restart reconfirmation limitation and unresolved held-exit interlock.
- The existing Auto person Stop, Pause and Resume entry points now route a uniquely
  identified Morek schedule owner through the connector-bound outcome ledger rather
  than issuing legacy actuator commands. Legacy owner behavior remains separate.
  A versioned `resume_requested` intent is not a confirmed replacement: the worker
  uses a fresh valid plan and binds the attempt to the intent ID; a later Stop replaces
  it with a new pause ID. Unknown outcomes remain latched, never blindly retried.
- Stop reserves the connector before the Auto lock. Worker generation checks invalidate
  old work at each pre-dispatch persistence boundary. Already-dispatched work cannot
  be recalled; status suppresses an old ACK/readback while Stop is reserved. An offline
  intent is admitted only when the configured physical ID or a single retained alias
  mapping and durable owner unambiguously agree. Unknown identity is refused.
- The Resume authorization ticket is process-local: after restart the durable request
  remains visible as `resume_requested`, but a fresh explicit Resume is required before
  it can dispatch. This deliberately fails closed if a Stop raced an interrupted save;
  a retained 0 A limit is not silently released. The schedule-owned sidebar controls
  remain disabled because production owned-profile admission is unconditionally
  unarmed. ACK and bounded effective readback are not physical charging evidence.
- Mock checks: `python tools/run_isolated_planning_tests.py -x` 522 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_command_admission.py tests/test_execution_ownership.py
  tests/test_morek_outcomes.py -x` 256 passed; targeted Ruff, `npm run type-check`,
  `npm run build`, `npm run check-dist`, `npm run test -- test/sidebar.test.ts
  test/morek-view.test.ts` (60 passed), `git diff --check`, and the local desktop/
  emulated-mobile `node sidebar/browser-check.mjs` passed. Early runs exposed an
  admission-import boundary test and a fixture lacking `_person_stops`; those were
  corrected. Pytest emitted existing timeout-option and dependency warnings, jsdom
  emitted CSS parse warnings and Git emitted line-ending warnings. The full 5.4c
  HA-plugin suite remains unrun; no HA, charger or physical touch was tested.
- 5.6c and 5.7–5.8 remain open; held exit still has no release path. The reported
  native protection is not independently verified. Stop for coordinator review.

### 2026-11-12 — 5.6b sidebar safeguard, incomplete (2.5.51)

- The sidebar now explicitly disables Pause/Resume for a reported Morek schedule
  owner while production dispatch is unarmed. It separates the last observed
  owned pause intent, request, ACK and bounded readback from unknown physical flow;
  the legacy pause label no longer implies a confirmed physical stop. The action
  method also refuses programmatic invocation for a reported schedule owner.
- The person-facing owned Pause API, durable Resume, offline identity handling and
  the complete required race/recovery test matrix remain unimplemented. Do not
  describe 5.6b as finished or use these disabled controls to operate a charger.
  The 5.4c full HA-plugin suite remains unrun; no live HA was contacted.
- Mock checks: `python tools/run_isolated_planning_tests.py` 505 passed, 1
  deselected; `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_command_admission.py tests/test_execution_ownership.py
  tests/test_morek_outcomes.py` 256 passed; targeted Ruff passed; `npm run test --
  test/sidebar.test.ts test/morek-view.test.ts` 60 passed; `npm run type-check`,
  `npm run build`, `npm run check-dist`, and `git diff --check` passed. Mock browser:
  `npm run prototype:build`, `npx esbuild sidebar/browser-fixture.js --bundle
  --format=esm --outfile=prototype/dist/sidebar-browser.js`, then `node
  sidebar/browser-check.mjs` passed desktop and emulated mobile. Pytest emitted
  existing timeout-option and dependency warnings; jsdom emitted CSS parse warnings;
  Git emitted line-ending warnings. Physical touch remains untested.

### 2026-11-12 — 5.6b explicit intent, partial (2.5.50; not complete)

- An internal `async_record_owned_pause` persists a versioned connector-bound
  `schedule_pause` in the existing outcome ledger after connector and unarmed owner
  checks. This is separate from legacy `until_resumed`. Under simulated authority,
  the worker reads that record inside connector admission, selects a one-period 0 A
  profile and binds the attempt fingerprint and readback to its intent ID. A recorded
  intent survives the mocked restart; unknown outcomes still block profile sends.
  The status API includes intent/request/ACK/bounded-readback/measurement fields.
- **This is not a completed Pause/Resume control:** the internal method is not wired
  to the person's existing API or sidebar; Resume and its durable pending/replacement
  semantics are absent. Offline identity resolution cannot yet record a pause. The
  tests do not establish the complete Stop/Resume/handover race matrix or physical
  stop. Production owned-profile admission remains unconditionally unarmed. Keep
  5.6b, 5.6c and 5.7–5.8 open. Do not expose the internal method as operational.
- Checks: `python tools/run_isolated_planning_tests.py -x` 505 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_command_admission.py tests/test_execution_ownership.py
  tests/test_morek_outcomes.py` 256 passed; targeted Ruff, frontend `npm run build`,
  `npm run type-check` and `npm run check-dist` passed. Pytest reported existing
  timeout-option and dependency deprecation warnings. The full 5.4c HA-plugin suite
  remains unrun. No live HA or charger was contacted.

### 2026-11-12 — 5.6b partial continuation (2.5.49; not complete)

- A person Stop reservation now advances the connector generation before waiting.
  The worker captures it before its first persistence await and rechecks it and
  the reservation after the shared send path's awaited persistence boundaries.
  Already dispatched commands cannot be recalled. Simulated-authority tests cover
  a queued worker and the ledger and entry-store awaits. Production owned-profile
  admission remains unconditionally unarmed.
- A one-period 0 A profile builder and a flat-readback comparator are present but
  the builder is not wired to a pause operation. A match is bounded to one observed
  hour; it does not prove infinite persistence, profile inventory or physical stop.
  Missing, short, nonzero, delayed and ambiguous observations do not match.
- **5.6b remains incomplete:** no schedule-owned durable Pause/Resume path or
  status was wired. An initial draft treated every `until_resumed` pause as an owned
  hold; mocked existing manual-workflow tests exposed that this would conflate the
  legacy pause used for manual testing with schedule ownership, so that draft was
  removed. Correct wiring still needs ownership-bound intent and serialized Resume,
  restart, uncertainty, held-exit, and full race coverage. No activation is allowed.
- Checks: `python tools/run_isolated_planning_tests.py` 502 passed, 1 deselected;
  `python tools/run_isolated_lifecycle_tests.py` 130 passed; `python
  tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py
  tests/test_command_admission.py` 232 passed; targeted Ruff, frontend `npm run
  type-check`, `npm run build` and `npm run check-dist` passed. An earlier planning
  run timed out after draft failures; `-x` identified the manual-workflow conflict.
  Pytest reported existing timeout-option and dependency deprecation warnings.
  The full 5.4c HA-plugin suite remains unrun. No live HA or charger was contacted.

### 2026-11-12 — 5.6b investigation, not implemented

- Under test-only simulated owned-profile authority, an existing Stop reservation
  does not increment the connector generation unless an entry drain is in progress.
  A worker already waiting at admission can consequently dispatch the old plan
  while Stop is reserved but before the pause is durable. Production owned-profile
  admission still unconditionally refuses dispatch. A safe implementation needs
  Stop-wins serialization and revalidation through every pre-dispatch await without
  breaking the existing handover, held-exit, unrelated-charger and protection paths.
- A single-period persistent 0 A intent also cannot use the existing readback
  comparator unchanged: it requires at least two expected transitions and a future
  transition. Its coverage and mismatch semantics must be defined without claiming
  physical stop or profile inventory. Resume must not release retained 0 A on an
  unavailable plan or uncertain outcome. No implementation or activation is claimed.
- Characterization checks: `python tools/run_isolated_planning_tests.py
  tests/test_morek_worker.py` 493 passed, 1 deselected; `python
  tools/run_isolated_lifecycle_tests.py tests/test_morek_schedule.py` 207 passed;
  `ruff check tests/test_morek_worker.py tests/test_morek_schedule.py` passed.
  Pytest reported the existing timeout-option and dependency-deprecation warnings.
  The 5.4c full HA-plugin suite remains unrun. No live HA or charger was contacted.

### 2026-11-12 — 5.6a readiness (2.5.48; local mocked, review pending)

- Morek status now includes read-only `readiness`: uniquely matched OCPP availability
  and control entity, connector-scoped vehicle state with a 180-second observation
  age, and separate unknown transaction authorization and measured flow. The sidebar
  ages out the status response and connector observation separately. A stable HA
  entity without recent reports can therefore become unknown despite still being
  correct; neither HA state timestamps nor a status read are a physical heartbeat.
- The existing connector resolver exposes a transaction-ID sensor key, but no current
  consumer establishes that sensor's lifecycle, sentinel values or freshness as proof
  of an authorized active transaction. Do not infer authorization from its mere
  presence, connector Charging, plug-in, a current limit, ACK or composite readback.
  A trustworthy Morek power measurement is likewise not established here. Determine
  new-session authorization configuration and trustworthy transaction/flow evidence
  with the user in 5.8; this is not a request to change RFID or credentials.
- No active transaction is required merely to hold a future schedule. This status
  adds no dispatch or action, and owned-profile admission remains unconditionally
  unarmed; identity, ownership, Stop, uncertainty and protection guards are unchanged.
  5.6b, 5.6c and 5.7–5.8 remain open. The 5.5f held exit still has no release path;
  retained profiles and possible 0 A remain unresolved. Native protection is a user
  report, not independently verified. The full 5.4c HA-plugin suite remains unrun.
- Mock checks: `python tools/run_isolated_lifecycle_tests.py` 130 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_morek_readiness.py
  tests/test_command_admission.py tests/test_execution_ownership.py
  tests/test_morek_schedule.py tests/test_morek_outcomes.py` 260 passed;
  `python tools/run_isolated_planning_tests.py` 492 passed, 1 deselected;
  `ruff check custom_components/spotnav/api/morek_schedule.py tests/test_morek_readiness.py`
  passed; `npm run test -- test/sidebar.test.ts test/morek-view.test.ts` 59 passed;
  `npm run type-check`, `npm run build`, `npm run check-dist` passed.
  Browser checks: `npm run prototype:build`, `npx esbuild sidebar/browser-fixture.js
  --bundle --format=esm --outfile=prototype/dist/sidebar-browser.js`, and
  `node sidebar/browser-check.mjs` passed desktop and emulated mobile with local
  fixtures; the test used an existing local Edge debugger because a new instance
  could not bind port 9248. No physical touch, live HA or charging was tested.
  Pytest emitted existing timeout-option and deprecation warnings; jsdom emitted CSS
  parsing warnings. Stop for coordinator review.

### 2026-11-12 — 5.5f held unarmed exit (2.5.47; coordinator review pending)

- The internal connector-serialized exit changes a unique, verified unarmed Morek
  record to legacy bookkeeping with a durable `exit_held_unarmed` transition. The
  transition blocks ordinary legacy writes, manual profile Send/Clear, automatic
  or explicit Resume, and deletion handback. It is not accepted by the existing
  entry-abort recovery. The read-only recovery status reports the held exit and
  unresolved retained profile. Older readers reject the new marker as malformed,
  not as permission to run legacy control. No release path is implemented here.
- Exit checks identity, contenders, connector generation and known in-process and
  durable profile uncertainty under connector admission; it checks legacy profile
  history without assuming missing history means an empty inventory. It waits for
  already admitted work, but cannot recall a dispatched or external command.
  Known accepted profile evidence, including possible persistent 0 A, is preserved.
  Failed or cancelled saves poison the current process; after restart either the
  Morek owner or the held legacy marker continues to block ordinary writes.
- A reserved person Stop interrupts the transition or, if it races the save, leaves
  the held record in place. Existing Auto handling records the Stop intent while
  refusing the unresolved retained-schedule Stop; no physical Stop is claimed.
  Regulator protection and unrelated chargers are unchanged. No Start, Stop, send,
  clear or automatic resume is issued by exit. Owned-profile dispatch remains unarmed.
- Combined mocked entry → handover → exit/recovery, durable retained evidence,
  Stop/save races, uncertain persistence, duplicate/ambiguous identity, stale work,
  unrelated chargers, protection and deletion-handback checks pass. This completes
  **5.5 unarmed local groundwork only**, not activation, actual profile resolution,
  proof of first use, transaction authorization or live hardware validation. The
  user-directed 5.6–5.8 work and deferred full 5.4c HA-plugin suite remain open.
- Checks: `python tools/run_isolated_lifecycle_tests.py`: 130 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_schedule.py
  tests/test_morek_outcomes.py`: 248 passed; `python tools/run_isolated_planning_tests.py`:
  492 passed, 1 deselected. Targeted Ruff, frontend `npm run build`, and
  `npm run check-dist` passed. Existing pytest timeout-option/deprecation warnings
  were reported. No HA or hardware was contacted. Stop for coordinator review.

### 2026-11-12 — 5.5e missing/uncertain evidence recovery (2.5.46; review pending)

- Startup and the existing control-availability callback now inspect connector,
  ownership, transition and durable Morek outcome evidence. The read-only Morek
  status includes `ownership.recovery` with a bounded state and unconditionally
  false activation permission. A missing ownership document is still migrated
  to legacy for compatibility, but neither that migration nor any existing record
  proves first-use rather than lost-state provenance; activation provenance is
  always reported unverified. The control-availability event remains only the
  existing availability proxy, not proof of every OCPP reconnect.
- For a legacy entry marker, startup/availability recovery calls the existing
  guarded abort: it requires unique identity, verified durable until-resumed Auto
  pause and no known uncertain profile outcomes, checks old manual evidence, and
  verifies the resulting ownership document. It removes only the marker and
  leaves Auto paused. Missing profile history is not evidence of absence. Unknown
  outcomes, corrupt/missing ownership, identity conflicts, active Stop and uncertain
  saves remain blocked; no uncertain ownership write is automatically retried.
  Existing process-local uncertain legacy operation evidence also blocks abort.
- No charger, profile, clear or resume operation is caused by recovery. A prior
  external command cannot be recalled. Retained profiles, missing-document
  provenance resolution for activation, safe handback, authorization and the
  retained-schedule Stop policy remain 5.5f–5.6; owned-profile dispatch stays
  unarmed. These are mocked tests, not proof of physical charging.
- Verification: `python tools/run_isolated_lifecycle_tests.py`: 113 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_schedule.py
  tests/test_morek_outcomes.py`: 231 passed; `python tools/run_isolated_planning_tests.py`:
  492 passed, 1 deselected. Targeted Ruff, frontend `npm run build`,
  `npm run check-dist` and `git diff --check` passed. The first planning run had
  one status test failure from an unmocked new admission dependency; the fixture
  was updated and the rerun passed. Pytest reports existing timeout-option and
  dependency deprecation warnings. The full 5.4c HA-plugin dashboard suite
  remains unrun. No live HA was accessed.

### 2026-11-12 — 5.5d handover (2.5.45; coordinator review pending)

- The internal handover consumes a process-local completed drain. It obtains Auto,
  settings, controller and assignment locks before connector admission and storage;
  validates identity, settings and known uncertainty evidence; then verifies the
  unarmed Morek owner on disk. It does not prove external operations or profile
  inventory. A Stop before the synchronous completion boundary interrupts entry;
  if the owner save landed, it is verified and the prior legacy binding restored
  with an interrupted marker before the Stop is admitted. Unknown owner saves or
  restorations fail closed without retry. Blocked Stops record intent using the
  existing Auto pause store without claiming physical stopping or profile removal.
- This path sends no profile or charger operation and does not arm dispatch. The
  process-local drain and uncertain-operation latch do not recover lost documents
  or prove external settlement across restart. Later recovery, retained profiles,
  exit, authorization, and retained-schedule Stop policy remain open. The 5.5d
  focused mocked checks pass; coordinator review remains pending.
- Validation: `python tools/run_isolated_lifecycle_tests.py` 95 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_schedule.py` 210 passed;
  `python tools/run_isolated_planning_tests.py` 492 passed, 1 deselected.
  Targeted Ruff, frontend `npm run build`, `npm run check-dist` and
  `git diff --check` passed. One initial focused test failed due to assigning a
  read-only test fixture property and passed after correction. Pytest reports its
  existing timeout-option and dependency warnings. The deferred 5.4c HA-plugin
  suite remains unrun; no live HA or charger was contacted.

### 2026-11-12 — 5.5d partial manual admission fix (later store draft noted above)

- Version 2.5.44 makes the existing manual profile admission require a valid,
  matching, unarmed legacy owner. Actual manual Send and selective Clear entry
  points are tested against a reloaded Morek-owned record; neither operation is
  invoked. Existing admin, pause, identity and profile checks remain in place.
- This is **not** a completed handover: the later store-method draft is unwired
  and untested, and 5.5d remains open. The user has specified Stop wins;
  the prior investigation below is historical, not a request for a new policy
  decision. The post-completion Stop intent path and uncertain save/rollback
  behavior also need implementation and actual-module race tests.
- `python tools/run_isolated_lifecycle_tests.py`: 77 passed;
  `python tools/run_isolated_lifecycle_tests.py tests/test_command_admission.py
  tests/test_execution_ownership.py tests/test_morek_schedule.py`: 192 passed;
  `python tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected.
  Targeted Ruff, `npm run build` and `npm run check-dist` passed. Pytest reports
  its existing timeout-option and dependency warnings. No live HA or charger was
  contacted. The 5.4c full HA-plugin suite remains unrun.

### 2026-11-12 — 5.5d investigation, incomplete

- No ownership handover or integration change was implemented. In
  `execution/command_admission.py`, a person Stop reserves before the Auto lock, but
  final Stop admission still requires a legacy owner. An asynchronous ownership
  save can land after a Stop reserves and before that Stop obtains the connector
  lock; simply committing `morek_schedule` would then refuse the Stop. The existing
  abort save race returns to legacy and therefore does not establish safety for
  this opposite transition. A compatible protocol and tests are still needed; this
  observation does not establish that such a protocol is impossible.
- At that historical point `async_manual_profile` did not check `recorded_owner`;
  the 2.5.44 partial fix above supersedes that finding. The entry drain also does not shut down every producer
  or prove external operations settled. Do not equate the drain with such evidence,
  require an impossible profile inventory, or interpret an empty unwired start ledger
  as proof of settled operations. 5.5d remains open and production stays unarmed.
- Baseline checks: `python tools/run_isolated_lifecycle_tests.py` passed 75;
  `python tools/run_isolated_planning_tests.py` passed 492 with 1 deselected;
  `ruff check custom_components/spotnav/execution/command_admission.py
  custom_components/spotnav/execution/execution_ownership.py
  tests/test_stage_23_lifecycle.py tests/test_command_admission.py
  tests/test_execution_ownership.py` passed. Pytest reported its existing unknown
  timeout-option and dependency-deprecation warnings. These are existing baseline
  tests, not 5.5d acceptance tests. No live HA or hardware was contacted.

### 2026-11-12 — unarmed entry abort (coordinator review pending)

- Version 2.5.43 implements `async_abort_unarmed_entry` for existing schema-1
  `requested`, `interrupted` and `drained_unarmed` markers on a unique matching
  **legacy** binding. This is an explicit internal operation, not an activation
  or user-facing button. It removes only the marker, verifies the entire ownership
  document on disk before and after the write, and leaves ownership legacy. The
  prior entry path itself never dispatches a profile or charger command or changes
  ownership. An absent first marker after a crash remains indistinguishable from no
  attempt; no detection or retry is claimed.
- Recovery requires the actual loaded Auto settings store to have no unsaved changes
  and the disk-verified settings to match memory with `until_resumed` pause. The
  settings lock is taken before the connector lock; ownership store is taken last.
  Auto remains paused until a later explicit Resume; the existing pause is the
  operator-visible state. No pause or person's Stop record is rewritten. A manual
  Stop or other pause that cannot meet this indefinite-pause check is refused, not
  silently changed. The operation sends no start/stop, profile, clear or resume.
- Existing connector-outcome uncertainty, invalid evidence, ambiguous identity,
  duplicate binding, missing/corrupt ownership and uncertain saves block recovery.
  Known accepted or retained-profile evidence is left untouched, not claimed absent.
  Missing profile history is not treated as a profile inventory. The older manual
  record is checked for known unknown send/clear outcomes and never rewritten.
  A reserved person Stop interrupts the generation; if a cancellation or Stop races
  a marker-removal write, the process remains interlocked on uncertainty and the
  previously verified indefinite pause remains durable if the write landed. On
  restart the actual stored marker governs admission; no uncertain write is retried.
  Generation checks reject already queued legacy/manual work after the abort.
- Mocked lifecycle tests cover all three successful markers, retained evidence,
  Stop race, stale work, ambiguous/duplicate identity, known unknown outcomes,
  cancellation and saves failing before/after disk write. The start of a direct
  pre-existing operation cannot be recalled, and none of these tests proves physical
  charger behavior. Full 5.5 remains open for actual Morek ownership, safe exit,
  retained 0 A/future profiles, unknown external outcomes, missing ownership document
  ambiguity and restart/reconnect. No generic legacy start journal was wired.
- Validation: `python tools/run_isolated_lifecycle_tests.py`: 75 passed;
  `python tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected. Targeted
  Ruff and frontend `npm run build` passed. A first lifecycle run found an existing
  duplicate-contender detection gap; it was fixed and the rerun passed. Check-dist
  and `git diff --check` passed. Pytest reports its existing unknown
  timeout option and dependency deprecations. The 5.4c full HA-plugin suite remains
  unrun. All boundaries were mocked; no live HA or hardware was contacted.

### 2026-11-12 — unarmed recovery check, safe abort incomplete

- Version 2.5.42 adds an internal connector-serialized abort check. It validates
  the physical binding and persisted transition, checks the actual Morek outcome
  and unresolved-start stores, and refuses missing, uncertain, conflicting or
  potentially retained profile evidence. It also refuses an apparently empty valid
  unresolved-start document as `legacy_start_evidence_not_wired`: that module's own
  contract says no controller produces or consumes these records. It therefore cannot
  establish that an earlier ordinary start had a known outcome. No safe marker-clearing
  operation is implemented; do not represent the check as recovery to legacy.
- A reserved person Stop interrupts the check and invalidates its generation. The
  check neither clears nor rewrites any evidence and never calls a charger or profile
  operation. A missing outcome document is not proof of no retained profile; even a
  clean new outcome ledger does not prove an older manual record or an external
  controller installed nothing. Composite readback cannot resolve that inventory.
- First-write boundary: before the requested marker is confirmed the entry path only
  changes its process-local latch/generation and attempts to write ownership metadata;
  it does not authorize an owner change, charger or profile action. In the mocked
  definitely-not-written case the prior valid legacy document remains; a later process
  cannot distinguish it from a normal legacy document. An uncertain write is not
  retried; after restart its actual durable contents govern admission. This does not
  prove that a pre-existing external action or retained profile is absent.
- `python tools/run_isolated_lifecycle_tests.py`: 61 passed. `python
  tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected. Targeted Ruff
  and frontend `npm run build` passed; check-dist and diff check were also run for
  this slice. Pytest reported the existing timeout-option and dependency warnings.
  Mocked tests are not live HA or physical validation; the full 5.4c HA-plugin
  suite remains unrun. The safe-abort slice and broader 5.5 remain open for review.

### 2026-11-12 — durable unarmed entry evidence (review required)

- Version 2.5.41 extends an existing schema-1 legacy record with optional
  `transition: {version: 1, state: requested|interrupted|drained_unarmed}`.
  Old records remain valid without rewriting. Older code rejects the additional
  field as malformed rather than interpreting it as legacy permission. Invalid
  markers and markers on a schedule owner are malformed; no owner is activated.
  The internal entry path closes its process-local gate, saves and rereads the
  requested marker, then drains the physical connector and writes interrupted or
  drained evidence. It does not hold the store lock while waiting for the connector
  or the connector while waiting for producer/controller/assignment locks.
- Startup initialization and ordinary physical admission consult the durable
  marker. Manual Send/Clear now also require a valid matching ownership record with
  no transition; missing/corrupt/conflicting ownership is refused, not treated as
  permission. This is intentionally stricter than the earlier manual experiment.
  A specifically reserved person Stop still checks identity and legacy ownership;
  a failed transition save retains a separately checked in-process legacy snapshot
  for that Stop only. Regulator protection is unchanged. No transition save is
  automatically retried after an uncertain result or cancellation.
- `requested` after a crash is ambiguous and remains blocked, as do interrupted
  and drained markers. A Stop during a completed drain may leave `drained_unarmed`
  as the last durable marker; it is still blocked and is not proof the Stop did not
  occur. Existing Auto persistence owns Stop intent; transition writes never erase it.
  A completed local connector drain does not prove all producers or external commands
  settled. If the **first marker never reaches disk**, a subsequent process sees the
  old legacy record and cannot infer the attempt; the in-process latch cannot survive
  that crash. No ownership activation is possible here. Solving that ambiguity and
  lost documents, durable unknown command outcomes, retained 0 A, safe exit/handback,
  restart/reconnect and person Stop with an existing future profile remains open.
- `python tools/run_isolated_lifecycle_tests.py`: 47 passed; `python
  tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected. Targeted Ruff,
  frontend `npm run build`, and `npm run check-dist` passed. The first planning run
  timed out after failures because old mocked Morek fixtures lacked the newly required
  ownership store; a subsequent `-x` run identified that fixture gap. After updating
  the mock stores the full isolated planning run passed. Pytest emitted the existing
  unknown timeout option and dependency deprecation warnings. The full 5.4c HA-plugin
  suite remains unrun. All I/O was mocked; no live HA or physical behavior was tested.
  Stop for coordinator review.

### 2026-11-12 — unarmed person-Stop coordination foundation (review required)

- Version 2.5.40 adds an internal `async_begin_unarmed_entry` experiment. It closes
  ordinary admission, invalidates the connector generation and drains the connector
  lock; it never persists an owner, sends a profile or arms dispatch. The result
  `drained_unarmed` is not ownership. A person's Stop reserves before the Auto or
  controller lock and synchronously interrupts/increments the entry generation.
  The separately classified Stop still checks the resolved physical identity and
  persisted legacy owner under connector admission; it is not an urgent or regulator
  bypass. Auto's existing Stop intent and outcome code continues to run.
- Entry never waits for Auto, controller or assignment locks while holding the
  connector lock. The Stop waits behind any already-admitted command; that command
  cannot be recalled. No reopening path exists: cancellation, interruption and
  failed/ambiguous checks leave this process's entry latch closed to ordinary work.
  Operations capture a generation before waiting for connector admission. The old
  process-local quiesce seam remains separate and its two characterization tests
  remain in place. Regulator protection and unrelated connectors are unchanged.
- This is **not durable ownership entry**. The latch and reservation do not survive
  process restart; no transition evidence is written and no unknown external outcome
  is recovered. Existing Auto Stop persistence and its existing failure behavior are
  reused, not upgraded to a crash-proof command journal. A future entry caller must
  supply trustworthy current Stop-intent state and must not arm from this drain.
  Manual profile operations, lost-document/first-use ambiguity, restart/reconnect,
  unknown outcomes and safe exit/handback still need a durable reviewed protocol.
  A current Stop does not withdraw a stored future profile, release retained 0 A, or
  prove later charging cannot occur; that policy remains unresolved.
- Mocked actual-module checks cover in-flight drain/Stop, blocked queued work,
  Stop intent with failed Stop and failed intent save, controller dispatch,
  cancellation, duplicate/failed ownership checks, unrelated connectors and
  regulator bypass. They do not prove physical stopping, a full crash matrix, or
  live HA behavior. The 5.4c full HA-plugin dashboard suite remains unrun. No HA,
  profile operation, deployment or charger operation occurred. Stop for review.
- Validation: `python tools/run_isolated_lifecycle_tests.py` 36 passed;
  `python tools/run_isolated_planning_tests.py` 492 passed, 1 deselected (includes
  Morek worker tests); targeted Ruff, frontend `npm run build`, `npm run check-dist`
  and `git diff --check` passed. The lifecycle runner with additional ownership,
  admission and worker tests had 107 passed and one failure: its harness did not
  pre-resolve `Europe/Stockholm` for the planner/worker test. The planning runner
  pre-resolves zones and passed that worker suite. A prior lifecycle run had a
  mocked HA fixture missing `states`; the test was fixed and rerun successfully.
  Pytest reports its unknown timeout option and dependency deprecations; Git reports
  Windows line-ending warnings. These results do not replace full HA-plugin tests.

### 2026-11-12 — person-Stop coordination investigation (incomplete)

- No new transition or Stop coordination was implemented. The existing unwired
  latch also causes `AutoExecutor.async_manual_action("stop")` to refuse at
  `_require_legacy`, before it records the person's intent or calls the controller.
  A new actual-module mocked characterization covers that boundary; the previous
  controller characterization is retained. This is not a defect in the normal
  production Stop path, because no production entry uses the latch.
- A controller-only Stop exception would not reach that Auto path. Conversely,
  clearing the latch to let Stop through would admit ordinary queued adapter work:
  `legacy_write_guard` does not capture a generation token. A possible design is
  a Stop-specific coordination reservation established before the Auto lock, with
  transition invalidation and identity/owner checks retained at each write boundary;
  another is to abort and fully drain/invalidate producers before reopening ordinary
  admission. Neither is implemented or proven here. Either must handle direct Stop,
  pause and cancellation/save failures without using the regulator bypass or losing
  an already dispatched operation's unknown outcome. Review lock ordering and
  durable failure semantics rather than inferring these guarantees from the latch.
- Whether a person Stop under schedule ownership or a retained future profile should
  withdraw or alter that profile remains unresolved. Stopping a current session,
  retaining 0 A, withdrawing a schedule and preventing later charging are distinct;
  no profile operation or future prevention is implied. The remaining 5.5 entry,
  exit/handback, lost-document ambiguity, retained-profile and restart/recovery work
  remains open; production autonomous dispatch is unarmed.
- `python tools/run_isolated_lifecycle_tests.py`: 28 passed. `python
  tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected. Targeted Ruff
  initially found E731 in the new test; it was corrected and rerun as recorded in
  the session. Pytest reported the existing timeout-option and dependency warnings.
  The 5.4c HA-plugin suite remains unrun. These are mocked checks, not live HA or
  hardware tests. No integration or frontend code changed and no HA, deployment or
  charger operation occurred. Stop for coordinator review.

### 2026-11-12 — Stage 5.5 entry/drain blocked for review

- No entry implementation or ownership transition was added. The process-local
  `async_quiesce_for_reload` latch refuses ordinary writes, including a person's
  urgent Stop: `ChargingController._stop_locked(by_person=True)` first calls
  `adapter.async_legacy_permitted`, and the latch rejects that check. A separately
  classified regulator-protection stop bypasses the ordinary guard. Persisting or
  wiring the latch as ownership entry would change the existing person-Stop path,
  contrary to the required safety boundary. Do not treat `urgent` as a general
  protection exemption. A reviewed compatible person-Stop/transition policy is
  needed before implementing entry; protection and manual interlocks remain unchanged.
- Current final legacy dispatch takes existing outer controller/assignment locks,
  then connector admission, then ownership-store lock. Startup installs the guard
  and awaits metadata initialization before Auto start and restore. The Morek
  manual action currently enters connector admission before its per-entry action
  lock; do not assume the historical audit's proposed reverse order describes the
  current implementation. A transition must not hold connector admission while
  waiting for producer/controller/assignment locks. The existing drain only waits
  for connector-admitted work; it cannot recall a dispatched command or prove all
  producer state or unknown external outcomes have drained.
- Manual profile admission checks the process-local latch but does not consult
  durable ownership. Any later durable transition must address manual profile writes
  and restart as well as duplicate physical identity, save/cancellation ambiguity,
  and stale queued generations; no recovery behavior is implied by this note.
  Safe exit/handback, retained profiles including persistent 0 A, lost-document
  versus first-use ambiguity, durable unknown outcomes and restart/reconnect remain
  open. Do not clear a profile or infer physical charging from a readback.
- `python tools/run_isolated_lifecycle_tests.py`: 27 passed, including the new
  real-controller/adapter mocked-boundary characterization. `python
  tools/run_isolated_planning_tests.py`: 492 passed, 1 deselected. `ruff check
  tests/test_stage_23_lifecycle.py`: passed. Pytest reported its existing unknown
  timeout-option and dependency deprecation warnings. These are mocked tests, not
  live HA/OCPP or hardware validation. The 5.4c HA-plugin dashboard suite remains
  unrun as documented below. No integration or frontend code changed, so no
  manifest bump or frontend build was performed. No HA access, deployment or
  charger operation occurred. Stop for coordinator review.

### 2026-11-12 — continue implementation before live testing

- The user wants remaining implementation completed before installing and testing
  in HA. Continue with the roadmap after coordinator review, one bounded substage
  at a time; do not contact HA, deploy or operate charging until specifically
  approved. Live installation and user-directed testing remain in 5.8.
- 5.4c is complete for local implementation and its recorded mocked checks; its
  full HA-plugin dashboard API/contract/golden suite is **not run**. That suite is
  offline automated validation, not live HA testing. Carry it to 5.7 and run it
  on a supported local environment if available; otherwise tell the user exactly
  what remains unverified before installation. Do not block 5.5–5.7 implementation
  on provisioning that environment, and do not report the suite as passed.
- This sequencing does not arm dispatch, waive authorization, resolve ownership,
  alter existing protection or grant permission to deploy. 5.5–5.7 safety and
  mocked regression requirements remain; 5.8 live actions require specific approval.

### Stage 5.4c — Linux test environment attempt

- Historical environment limitation: the full HA-plugin dashboard API/contract/golden suite has
  **not run** in Linux. WSL Ubuntu reports Python 3.12.3. The pinned
  `pytest-homeassistant-custom-component==0.13.365` declares Python >=3.14.
  No Python 3.14 executable was found in the WSL command path.
- The isolated setup attempt
  `wsl -d Ubuntu -- python3 -m venv /mnt/c/Users/simso/AppData/Local/Temp/opencode/spotnav-ha-54c-venv`
  failed: `ensurepip` is unavailable (Ubuntu reports `python3.12-venv` is needed).
  No dependencies were installed, no system Python was changed, and no suite
  tests ran in this attempt. On a supported local Linux Python >=3.14 environment
  with `requirements_test.txt` installed, run
  `python -m pytest tests/test_dashboard_api.py -q` from the repository root.
- The earlier Windows failure and local mocked verification are recorded below;
  neither is a passing Linux HA-plugin suite. Actual HA integration, physical
  touchscreen, charger behavior and charging remain unverified. No live HA or
  charger was contacted; automatic Morek dispatch remains unarmed. The sequencing
  clarification above supersedes the earlier instruction to stop before 5.5.

### Stage 5.4c — verification continuation, backend suite outstanding

- Version 2.5.39 fixes wheel zoom on coarse source intervals: the former small
  wheel step snapped back to the same range. The built-panel mock check now sends
  Chromium pointer and ordinary wheel events on desktop and emulated mobile,
  asserts the visible tooltip's exact interval dates/times, UTC offset, price and
  unit, verifies range change and full-horizon reset, and checks local-only traffic
  and no charger writes. Previously covered update, zoom retention and degraded
  transitions also pass. Physical touchscreen and real HA remain unverified.
- Screenshots inspected: `C:\Users\simso\AppData\Local\Temp\opencode\spotnav-54c\desktop.png`
  and `mobile.png` (mock fixture, not household data). The mobile image is an
  emulated viewport, not evidence of physical touch behavior.
- Final frontend Vitest: 2,423 passed across 102 files; focused chart/sidebar/
  bundle: 81 passed; shared/sample Node tests: 23 passed. Build, type-check,
  check-dist, mocked sidebar registration (2) and diff check passed. jsdom emits
  CSS parsing warnings, and Git emits Windows line-ending warnings.
- `python -m pytest tests/test_dashboard_api.py -q` failed before collection on
  Windows: `ModuleNotFoundError: No module named 'fcntl'` from HA's pytest plugin.
  Ubuntu WSL exists, but its Python 3.12 environment has no `pytest`; no packages
  were installed. Run that same command on a supported host with the repository's
  HA test dependencies, without connecting to live HA. This full suite remains
  unverified under the sequencing clarification above. The isolated serializer and planning suite
  passed locally (492 passed, 1 deselected); they are not the full plugin suite.
  The isolated run reports an unknown pytest timeout option and HA deprecation
  warning; the serializer run reports a voluptuous import-order warning.
- User reports Morek handles household protection natively; this has not been
  independently verified. No load-balancing or dynamic amp control was added.
  No HA, deployment, hardware, commit or push operation occurred; automatic
  Morek dispatch remains unarmed. Stop for coordinator review; do not start 5.5.

### Historical 5.4c implementation (superseded by verification above)

- Version 2.5.38 adds `prices.published_intervals`, separate from the unchanged
  merged rows. It exposes captured published boundaries and source prices in
  major currency/kWh (the source calculation uses 100 subdivisions regardless
  of ISO minor-unit convention). Market currency/timezone and existing per-day
  fetched timestamps are reused. Invalid or overlapping rows fail closed. Only
  held today/tomorrow documents are available; no historical coverage is promised.
- The sidebar uses the shared chart with neutral colors, explicit source-price
  basis, exact gaps and timezone offset in chart tooltips. A cap is drawn only for
  matching-revision settings with the planner's published-price basis; the
  configured-variable-cost cap is omitted from this raw-price plot. Proposal
  shading is not sent or measured charging. Chart data and overlays update in
  place while retaining valid zoom; missing/stale data shows unavailable.
- Local validation: actual serializer test 1 passed (mocked capture); registration
  tests 2 passed; focused sidebar/bundle tests 61 passed; shared/sample tests 23
  passed; full Vitest 2,423 passed before final small formatting/control changes.
  Build, type-check, check-dist and diff check passed. The initial full test run
  had 1 stale-bundle version failure before the build; the subsequent run passed.
  jsdom reported CSS parsing warnings; Python reported an HA voluptuous warning;
  Git reported CRLF warnings. The full HA-plugin dashboard/golden suite was not
  run on Windows. Its old golden comparison now checks the additive field
  separately, but that change needs execution on a supported HA test host.
- Built-panel mock browser checks passed desktop and emulated mobile for prices,
  proposal changes, formatter output, zoom/reset actions, retained zoom, shrinking
  and unavailable/restored data, no horizontal overflow, local requests and no
  implicit writes. Captures: temporary `opencode/spotnav-54c/{desktop,mobile}.png`.
  Pointer-triggered tooltips and real wheel gestures have not been verified for
  this live binding; neither have actual HA, physical touch or charger behavior.
  Do not mark 5.4c complete until those checks and the backend contract suite pass.
  No deployment or live operation occurred; autonomous dispatch remains unarmed.

### Historical 5.4c source inspection (superseded above)

- **Incomplete; coordinator review required.** No chart or backend code was changed.
  `get_dashboard.prices.intervals` is a merged presentation: the serializer may
  substitute proposal horizon rows and split published rows into quarters. It is
  therefore not always an authoritative record of source resolution. Captured
  `ChartInterval` rows originate in held published documents and retain their start,
  end and raw/effective minor-unit-per-kWh values; held documents are today and
  tomorrow only. The existing market supplies currency and timezone when available.
  An additive read-only representation of the captured source intervals is a likely
  path; validate basis, freshness, overlap and missing metadata before binding.
- The shared chart assumes sample cents and fixed bands, and chart handlers close
  over their initial data. Live binding must address units/basis, DST, source-aware
  navigation and in-place updates together; passing merged rows straight through
  would not satisfy the acceptance criteria. No browser or contract tests for the
  requested live binding were performed in this inspection.
- `docs/sidebar-installation-preparation.md` documents the future non-destructive
  update path and existing locally bundled assets and notices. It is not approval
  to install. No HA, share, charger or deployment access occurred; automatic
  Morek dispatch remains unarmed. Do not proceed to 5.5.

### Stage 5.4b2 — complete locally, coordinator review pending

- The bounded 5.4b2 closure cases pass; 5.4b is complete for local implementation
  and mocked verification. `frontend/sidebar/verification-matrix.md` maps the evidence.
  A destroyed panel could previously lose an outstanding settings write when a new
  panel was created. The pending/unknown tracking now survives panel replacement on
  the same HA connection; a pending write cannot be retried or reloaded, and its
  unknown result requires explicit reload after settlement. This is in-memory frontend
  protection, not durable recovery across browser reloads or new connections.
- Version 2.5.37: focused sidebar 37 and full Vitest 2,420/101 files passed;
  shared/sample 23, mocked registration 2 and isolated notifier 14 passed.
  Type-check, build, check-dist and diff check passed. jsdom emitted CSS parsing
  warnings; notifier pytest reported its existing unknown timeout option and HA
  deprecation warnings; Git reported Windows line-ending warnings.
- The built-panel mock browser check passed desktop and emulated mobile, including a
  desktop switch while a draft and dialog were active and an old response was pending;
  no unintended write occurred. Screenshots are in temporary `opencode/spotnav-54b1/`.
  The local check used an existing debugging browser and observed only local/data
  requests. Actual HA integration, physical touch, charger behavior and physical
  charging remain unverified. No HA, deployment or hardware action occurred. Morek
  automatic dispatch remains unarmed. Stop for coordinator review, not 5.4c.

### Historical 5.4b2 partial work (superseded above)

- Verification continuation: `frontend/sidebar/verification-matrix.md` records
  tested and still missing cases. A stalled settings write now times out visibly,
  preserves its draft, blocks retries/reload until the underlying request settles,
  and keeps an unknown-outcome latch across disconnect for explicit reload. A
  dispatched request is never cancelled or automatically retried. Action and
  permission changes no longer clear in-flight dashboard/status read slots; once
  a superseded read settles, a fresh read is requested. Pause confirmation requires
  a matching observation generated after dispatch. No HA or hardware was contacted.
- Tests: sidebar suite 25 passed; the final full suite passed 2,408 tests.
  Shared/sample tests passed 23; mocked registration 2;
  notifier 14 (existing pytest option/deprecation warnings). Type-check, build and
  check-dist passed. Built-panel browser check passed at desktop and emulated-mobile
  widths with simultaneous dirty input, open dialog and mismatch; it made local-only
  requests. Screenshots: temp `opencode/spotnav-54b1/`. Sample browser checks covered
  chart identity/zoom, dialog, text selection and scroll. Actual HA and physical
  touch remain untested. Several specific races remain listed in the matrix; do not
  mark 5.4b2 complete yet.

- Latest continuation: `frontend/sidebar/panel.js` exposes explicit Pause until
  resumed and Resume using `admittedAction` and the existing `performAction` API;
  a fresh dashboard confirms state. Send/Clear now have one confirmation at the
  sidebar boundary followed by identity, permission, preview and lifecycle checks;
  the card keeps its existing confirmation. Timeout/permission-change outcomes are
  conservatively treated as unknown. Automatic Morek dispatch remains unarmed.
- `frontend/shared-dashboard/reconcile.js` updates stable DOM regions in place,
  preserving dialog, dirty/focused inputs, Morek action nodes and chart instances;
  current overview and health continue updating during edits. Browser checks cover
  dialog/chart identity, sample zoom, text selection and scroll, and mocked sidebar
  actions and save/conflict on desktop/mobile. Real chart data updates remain 5.4c.
  Full requested action-race/interaction matrix has not been exhaustively tested;
  keep 5.4b2 open for review and further focused regression coverage.
- Validation: `npx vitest run --maxWorkers=2 --silent` passed 2,396 tests;
  focused sidebar/Morek passed 34; shared/sample Node tests 23; mocked registration
  2; notifier tests 14 (pytest option/deprecation warnings). Type-check, build and
  check-dist passed. `sidebar/browser-check.mjs` tested the built panel with mocked
  settings and Morek operations; `prototype/shared-browser-check.mjs` exercised
  shared view identity/zoom/selection at 1440×1000 and emulated 390×844. Screenshots
  are in temp `opencode/spotnav-54b1/` and `spotnav-54a/`. jsdom has CSS parsing
  warnings; no live HA, physical touch, charger operation or deployment occurred.

- Subsequent continuation: `frontend/sidebar/panel.js` loads canonical settings,
  uses `formFromRecord`/`replacementFor('plan', …)` and revision-checked
  `updateSettings`, and presents save/conflict/unknown-outcome notices. The shared
  form exposes target, minimum, cap enable/value/basis and ready-by controls;
  unsupported policy/target fields are disabled. Explicit reload discards drafts
  only after confirmation. Charger/generation guards discard late UI responses;
  a dispatched request cannot be recalled. No save directly sends a profile.
- Historical entry: the sidebar embeds the existing `morekPanel` diagnostic view and dispatches
  explicit status, fetch, send and selective clear through `morekSchedule`, with
  administrator, support, preview fingerprint, uncertainty and confirmation
  checks. Backend interlocks remain authoritative. The former duplicate prompts
  and missing Pause/Resume are superseded by the continuation above.
  No live actions were performed. These new write paths are not ready to deploy
  without further review and the remaining tests below.
- Historical entry: shared updates previously deferred remounts while a field was focused, a draft existed or the
  plan dialog is open; critical status is updated in a live region. This does not
  replace the general remount path: selection in other elements, arbitrary scroll,
  chart identity and all debug-control focus are not guaranteed. Existing Morek
  debug content was regenerated on updates. The in-place reconciliation above supersedes it.
- Current checks: full frontend Vitest passed 2,393 tests; 10 focused sidebar tests
  passed with mocked HA, including one
  successful save, conflict/invalid/non-admin cases, late save, explicit fetch and
  mocked send/clear guards; 23 shared/sample tests and 2 mocked registration tests
  passed. Type-check, build and check-dist passed; isolated notifier tests passed
  14 with existing pytest/deprecation warnings. The local built-panel mock browser check
  passed at desktop/mobile sizes with one successful and one conflicting save,
  draft retention and the one-hour display. It imports the built `www/sidebar/panel.js`
  in the mock host; it does not establish actual HA,
  physical touch or production-bundle compatibility; jsdom reports CSS warnings.

- Shared vehicle rendering now uses `format.minutesPerTimeUnit`: the live adapter
  supplies `1/60000` for epoch milliseconds; the sample supplies `60` for hours.
  Exact window boundaries are unchanged. Rendered-module tests cover one hour,
  partial and multiple windows in both representations.
- The sidebar now refreshes dashboard and Morek status independently every
  30 seconds, coalesces in-flight requests, bounds the displayed wait at ten
  seconds, invalidates on charger/disconnect/teardown, and retains a failure notice
  for a failed dashboard observation. A timed-out HA WebSocket call is not
  cancellable; its channel remains single-flight until it settles or the session
  changes, to avoid leaking repeated requests. The other channel keeps refreshing.
  Only read-only requests are scheduled. With the plan modal open, observation
  updates are deferred without detaching it, while critical health is updated in
  its live region; the newest deferred model is applied on close.
- Historical partial entry: settings and debug actions have since been connected
  as described above. The full interaction-safe lifecycle and comprehensive tests
  remain outstanding. No HA or charger access, profile action or deployment occurred.
- Version 2.5.36, `npm run build`, `npm run check-dist`, type-check, two mocked
  registration tests, five focused sidebar tests and six shared/sample tests passed.
  The local Chromium source-bundled mock-host check passed at 1440×1000 and emulated
  390×844, asserting `60 min`, unavailable chart and local-only requests; captures
  are in `opencode/spotnav-54b1/`. It does not test the shipped panel bundle in HA,
  physical touch, saves or manual actions. jsdom emitted CSS parsing warnings.

### Stage 5.4b1 — read-only sidebar foundation (coordinator review pending)

- `sidebar.py` registers a domain-wide HA `panel_custom` sidebar and local static
  route. Entry reload/unload does not re-register it; HA stop removes the panel.
  `frontend/sidebar/panel.js` mounts the actual shared dashboard in shadow DOM,
  with local versioned CSS, a charger selector and explicit read-only refresh.
  The old card and user dashboards are untouched. Registration and the new assets
  are part of integration setup; install/update requires shipping the built `www`
  assets and an approved HA restart. No installation is authorized by this note.
- `frontend/sidebar/adapter.js` uses the existing dashboard and Morek decoders and
  health logic. It makes independent dashboard and Morek status observations and
  invalidates late results on selection, disconnect or teardown. It never invokes
  Morek fetch/send/clear, settings, or charging actions. Missing general power,
  historical data, per-window cost and real prices are unavailable. Backend plan
  totals retain their own currency; no frontend cost rule or sample fallback is used.
  Historical, expired or stale proposals are suppressed. SOC freshness uses the
  existing 180-second backend threshold; dashboard observations age after 90 seconds.
- The host is read-only, including for admins. 5.4b2 must implement guarded settings
  and debug actions and truly stable incremental updates. The current shared `update`
  still closes/reopens the dialog and cannot guarantee focus, selection or scroll.
  5.4c must bind the real chart with proper timezone/DST behavior. This is not a final
  installable release. Actual HA, mobile app, physical touch and mixed Web Awesome
  versions remain unverified. Existing `wa-*` registrations win; compatibility with
  an independently installed version is not guaranteed.
- `tools/test_sidebar_registration.py`: 2 mocked-boundary tests passed (duplicate
  setup, cleanup/reload, missing bundle). `frontend/test/sidebar.test.ts` exercises
  the actual host and decoder against a backend fixture, stale/missing status,
  non-admin reads, switching and out-of-order dashboard/status responses, disconnect
  and read-only requests. jsdom reports CSS parsing warnings; it is not a browser.
  Full Vitest run passed 2,385 tests before the last additional focused race test;
  the three focused sidebar tests passed afterward. Type-check, build, check-dist,
  four shared-plan tests and diff check passed; line-ending warnings are present.
- Local Chromium mock-host/preview captures using the same backend fixture at
  1440×1000 and emulated 390×844 are in the temp directory
  `opencode/spotnav-54b1/{desktop,mobile}-{preview,panel}.png`. The panel adds a
  navigation/charger bar and has a slightly narrower content area; shared card
  layout/styles are the same. The check observed 28 local/data requests and no
  runtime exceptions. It does not prove HA compatibility or pixel identity.
- Build bundles Web Awesome and ECharts into `www/sidebar/panel.js`, isolates the
  shared styles in `panel.css`, and copies MIT/Apache/BSD and icon notices beside
  them. The mock browser used only local/data resources. No live HA, charger, phone,
  profile operation, deployment or restart occurred. Stop for coordinator review.

### Historical 5.4b partial shared-view work (superseded above)

- The shared preview can accept explicit backend-supplied plan totals and a currency;
  absent currency can be marked unknown and non-EUR totals are not labelled EUR.
  The sample price chart still assumes cents and is not suitable for real prices.
- An experimental update restores dirty input values, zoom and dialog visibility
  after a remount, and puts warning/status text in the dialog. This is not a true
  incremental update: focus/selection and all scroll positions are not guaranteed,
  and the dialog is actually closed and reopened. Hosts must change `draftKey` on
  charger/revision changes. This is not yet wired to settings or safe for production.
- `node --test shared-dashboard/plan-view.test.mjs shared-dashboard/boundaries.test.mjs`
  passed four tests. The local preview browser check passed at 1440×1000 and emulated
  390×844, including a basic draft/dialog/zoom/warning restoration check; its captures
  are in `opencode/spotnav-54a/shared-{desktop,mobile}-full.png` in the temp directory.
  These are preview captures, not panel parity screenshots. Physical touch and HA
  were not tested. An initial run attached to a browser with extensions and failed
  the local-only network assertion; a clean browser passed.
- Version bumped to 2.5.35; frontend type-check, build and check-dist passed.
  The first full frontend test run failed 29 tests on five-second timeouts when
  npm consumed the intended worker option; a direct `npx vitest run --maxWorkers=2`
  rerun passed all 2,383 tests. Isolated notifier tests passed 14 (with existing
  pytest configuration/deprecation warnings). These do not test a panel host.
- Historical entry: the absence of sidebar registration and a real adapter described
  here was superseded by 5.4b1 above. 5.4b remains open for guarded controls and
  stable updates; 5.4c remains future work.

### Stage 5.4a — shared dashboard foundation (coordinator review pending)

- `frontend/shared-dashboard/dashboard.js` exports `mountDashboard(root, adapter)`
  with `update` and `dispose`. Shared components, native modal, stepped-area
  ECharts and CSS are used by the thin `frontend/prototype/dashboard.js` host.
  `frontend/prototype/sample-adapter.js` injects all fictional scenarios, values,
  display context and the local scenario callback. Preview Save/Send/Refresh are
  disabled; no HA/OCPP client or charger action was added. The default now shows
  only the selected stepped chart; `?comparison=bar` adds the old comparison.
  The required model/format/action contract, missing-data behavior, local assets,
  licenses and lifecycle are in `frontend/shared-dashboard/README.md`.
- Run from `frontend/`: `npm run prototype:build`, then
  `python -m http.server 8765 --bind 127.0.0.1`; open
  `http://127.0.0.1:8765/prototype/`. The build copies Web Awesome MIT, ECharts
  Apache license/notice, zrender BSD license and Font Awesome inline-icon notice.
  It does not build or change the shipped integration/card.
- Focused node tests: 22 passed using the command in `frontend/prototype/README.md`.
  `shared-browser-check.mjs` passed at 1440×1000 and emulated 390×844: sample
  scenarios, unknown/invalid inputs, dialog focus/Escape/backdrop, wheel/reset,
  overlays, tooltip, fake-host mount/update/dispose/remount, unsafe text, callback
  wiring, observer/chart cleanup and 162 local/data requests. The comparison
  `browser-check.mjs` passed desktop/mobile (both chart modes, endpoints, missing
  gap, zoom/pan/reset, tooltips, emulated pinch/taps, scenarios and 156 local/data
  requests). An initial browser run contained extension resource requests and was
  rerun successfully with extensions disabled; emulation is not physical touch.
  `git diff --check` passed with Windows line-ending warnings.
- Visual comparison used the earlier 5.1d full-page mismatch baseline at the same
  desktop/mobile widths and current comparison-mode captures, plus new default
  single-chart captures. Files are under the temporary `opencode/spotnav-54a/`:
  `baseline-{desktop,mobile}-comparison.png`, `shared-{desktop,mobile}-comparison.png`,
  and `shared-{desktop,mobile}-full.png`. The dark layout, plan, stepped chart and
  hierarchy remain recognizable; default removal of the bar is intentional.
  Minor wording/formatting in insights and evidence changed when sample-specific
  prose moved into the adapter. No pixel-identity claim is made. The baseline is
  an earlier saved capture, not a fresh render of a preserved old source tree.
- Remaining: 5.4b registers the panel and maps real 5.2/5.3 sources and guarded
  actions, addressing global CSS/shadow isolation, theme, registrations, safe
  areas, asynchronous lifecycle and actual HA behavior. 5.4c supplies actual
  intervals, timezone/DST-aware dates, source-boundary navigation and real chart
  data; the current sample axis is not a live implementation. Updates currently
  close the modal and reset chart zoom. No real HA, mobile app, physical touch,
  phone, charger or physical charging was tested. Dispatch remains unarmed.
  Stop for coordinator review; do not proceed to 5.4b or 5.4c automatically.

### Stage 5.4a — partial extraction, not complete

Historical partial entry; superseded by the completed foundation above.

- `frontend/shared-dashboard/plan-view.js` and `plan-data.js` extract the existing
  plan renderer and its arithmetic. The prototype wrapper supplies its sample
  time/day formatters; formatter output is escaped. Missing or invalid estimates
  remain unknown. The renderer retains sample-specific labels and is not yet a
  complete real-data adapter or a production-ready dashboard entry point.
- `npm run prototype:build` passed; `node --test prototype/sample.test.mjs
  prototype/insights.test.mjs prototype/daily-sample.test.mjs
  prototype/vehicle-evidence.test.mjs shared-dashboard/plan-view.test.mjs` passed
  21 tests. No browser comparison, screenshots, lifecycle/network check, production
  build, HA or physical-device test was performed for this partial change.
- 5.4a remains open: dashboard layout, styles, chart, dialogs, sample-only evidence,
  insights and history still need extraction with an explicit host contract, safe
  text handling and teardown. In particular, current charts and other views directly
  import fictional fixtures and the preview still displays both comparisons. Do not
  use the existing prototype as a live host. Complete the requested browser/visual
  checks and adapter documentation before coordinator review; 5.4b/5.4c are untouched.

### 2.5.34 — 5.3a plug-in proposal notifications

- A recognized connection records an owed notification. The planner increments a
  connection generation on connection events and stamps the calculation's start time,
  settled generation and resolved vehicle identity at its start. The notifier listens to
  every publication, including unchanged plans, and checks that its calculation began
  after the plug-in, still belongs to the settled generation and current attempt/settings,
  and still matches the resolved vehicle. Unknown identity evidence fails closed. An old
  immediate listener callback, superseded attempt or prior connection cannot provide a
  proposed window. An owed notice is persisted; after restart a historical snapshot is
  not accepted, and waiting continues until a qualifying new connection calculation.
- After settling, opted-in selected phones receive the next `shown_periods` window with
  local dates and proposed wording. Available backend ready-by, target, estimated cost,
  shortfall and validated backend SOC projection are included; missing estimates are
  omitted. The existing tag, hourly and per-event limits apply. A bounded waiting notice
  is replaced by the proposal. Person Stop prevents proposal notices. The legacy
  installed-plan fallback remains for installations without a planner. Notifications
  do not send charger commands. Existing important shortfall notices remain separate.
- Portable actual-module tests: `python tools/run_isolated_notifier_tests.py`, 14 passed;
  planning 492 passed/1 deselected, lifecycle 26 passed. The test harness mocks HA
  scheduling, storage and notify boundaries, not a running HA instance. Build and
  `check-dist` passed. pytest reports an unavailable timeout option and HA/dependency
  deprecation warnings. Full HA-plugin tests on Windows are still blocked by `fcntl`.
- No physical phone, HA or charger was contacted. Morek mismatch/uncertainty is not
  connected to phone notifications; its trustworthy event and deduplication lifecycle
  remains an activation-stage follow-up. ACK/readback is not proof of charging.
  Dispatch remains unarmed. Stop for coordinator review; do not proceed to 5.4.

### 2.5.33 — 5.3 complete locally (coordinator review pending)

- Final follow-up reconciled card tests with the English-only contract, retaining
  independent translation utility tests and settings, action and accessibility
  checks. Full frontend suite: **2,383 passed across 100 files**. Type-check, build,
  check-dist and diff check passed (Windows line-ending warnings). Isolated real-module
  planning tests passed 492 with one deselected; isolated lifecycle tests passed 26.
  Mocked boundaries are not live HA or charger tests.
- The built card was tested with mocked boundaries at 1440×1000 and 390×844,
  Swedish HA language, successful and rejected/conflicting saves, refresh, dialog
  close/Escape/backdrop/focus and open-dialog mismatch/uncertainty. Unsaved edits
  and settings saves issued no Morek action. Physical touch, HA theme/Sections,
  live HA and physical charging were not tested. Per-window energy, price and cost
  remain unknown because the API does not supply them. Dispatch remains unarmed.
  Stop after 5.3 for coordinator review; do not proceed to 5.3a automatically.

- Earlier follow-up: revised the settings-editor, card lifecycle and language-loader
  expectations for English while preserving their save, accessibility and loading
  assertions. Added an open-dialog disconnect/reconnect and late-evidence test.
  Corrected a real regression: a changed HA administrator status now causes a
  card refresh even though a language change alone does not. The five focused
  suites passed 169 tests before the additional daily lifecycle test, which passed
  in its 25-test suite. An intermediate full frontend suite passed 2,274 and failed
  109 in 27 files; those failures were subsequently reconciled in the final run above.
  Build, type-check and check-dist passed;
  isolated planning passed 492 (one deselected), lifecycle 26. The built-card local
  desktop/mobile mock browser check passed, including successful/rejected saves and
  Swedish HA language. Physical touch, HA themes, live HA and charging remain untested.
- User decision: the shipped card, dashboard and dialogs use English regardless
  of HA language. Existing translation resources and backend localization are not
  deleted. The card forces English at its existing language-selection boundary.
- Open proposal dialogs now receive Morek health changes without replacement,
  including simultaneous uncertainty and mismatch, in a persistent live region.
  A focused actual-card test exercises that state and forced charger replacement.
  A policy-save test verifies revision, committed result, dashboard refresh and
  re-read. Existing backend tests exercise real settings/controller/planner with
  mocked boundaries and no open browser.
- An earlier frontend run: 2,259 passed and 122 failed across 30 files because legacy card
  tests explicitly expect non-English card text/number formats, language loads and
  language-change rerenders. These tests were subsequently revised for the English-only
  contract, not suppressed. Focused new
  policy save and health tests passed. Isolated planner 492 passed, one deselected;
  lifecycle 26 passed. A built-card browser test with Swedish HA language exercised
  desktop/mobile modal, focus, Escape/backdrop, refresh, conflict, refusal and
  successful mocked save/confirmation without a Morek action. This is not a live
  HA, physical touchscreen, theme or charger test.
- The prior instruction below to translate new strings is superseded by the English-
  only decision. Per-window energy, cost and price remain unavailable; no browser
  cost model was added. Automatic Morek dispatch remains unarmed. No HA access,
  deployment, profile operation or other hardware action occurred.

### 2.5.32 — Stage 5.3 partial implementation (not complete)

- The existing revision-checked Plan editor now decodes and preserves the policy
  fields, exposes minimum ready-by SOC, soft-cap enable/value and price basis, and
  retains its target, deadline, permissions, conflict and confirmation flow. The
  cap uses major currency units/kWh (0.10 is 10 cents); negative caps are accepted.
  Existing browser-independent backend replanning is unchanged. Manual Morek
  actions and unarmed dispatch are unchanged.
- The daily view presents all backend `shown_periods`, including seconds and
  partial ends, and opens the same list in a native dialog from the next window.
  Touching periods are grouped when no minimum exception is reported; in exception
  cases boundaries are kept rather than guessing equivalence. Backend policy reason
  codes are shown. Per-window energy, cost, price and weighted average are unknown:
  the dashboard API does not provide them. Totals are backend estimates; unpriced
  cost is hidden. The proposal is not an installed Morek profile or measurement.
- Validation: full frontend suite passed 2,379 tests; isolated planning tests
  passed 492 with one deselected and lifecycle tests 26. Type-check, build and
  check-dist passed. Earlier full runs exposed a no-settings button regression and
  stale built language hashes; both were corrected before the final run.
  The actual built card was browser-tested at 1440×1000 and 390×844 with mocked
  backend boundaries: dialog open/close, Escape, outside click, focus return,
  refresh while the dialog was open, unsaved draft, rejected revision-checked save
  and no Morek action. This does not
  test live HA, physical touch, all themes, successful save confirmation, or charging.
- **Outstanding before claiming 5.3 complete:** the new strings are English in
  non-English translation files; translate and review them. Strengthen lifecycle
  and race tests for forced card replacement and successful save, and per-policy/
  partial-data coverage. Normal card renders and daily status repaint are deferred
  while the dialog is open; a forced config change still dismisses it.
  No HA access, deployment or hardware action was performed.

### 2.5.31 — Stage 5.2 daily overview (coordinator review pending)

- The existing shipped card displays a localized daily overview from its decoded
  dashboard: connection, SOC and reading age, next remaining proposed window,
  estimated proposal energy/cost, and planner calculation time/age and historical
  flag. It uses no prototype data and does not label legacy `plan.installed` as
  Morek inventory. SOC age advances from the dashboard generation time; missing or
  future timestamps give unknown age. Dates use the market zone, or labelled UTC
  when no market zone is available. The manual Morek preview has its own separate
  calculation time and is not the planner timestamp.
- Morek status is read separately after a successful dashboard read, without waiting
  for it to render. The read coalesces, times out after 10 seconds, and is invalidated
  on config change, disconnect or a newer manual action. Late manual and follow-up
  results are guarded by lifecycle, charger and operation. Existing evidence ages on
  the normal card timer even if the next dashboard read stalls. Status updates replace only
  the overview (unless the diagnostic panel is open); no OCPP fetch is performed.
  Dashboard and status are not atomic. The summary reports observation, last send/ACK
  and effective-readback times, and expressly leaves association with the displayed
  proposal unknown. A match is shown only for internally consistent, recent accepted
  evidence with valid remaining coverage; it is a last-read fact, not a current plan
  verification or proof of physical flow. Offline, mismatch, uncertainty and stale,
  superseded, missing and unsupported states remain visible without opening details.
- There is no verified, fresh general Morek power source in this API. The overview says
  measured power unavailable, including when current is zero; it does not infer power
  from the plan or current limit. Capacity and estimated efficiency are not used for
  new projections, and no separate low-SOC warning threshold is inferred. Automatic
  dispatch remains unarmed and all existing manual authorization/interlocks remain.
- Local checks: the full frontend suite passed 2,376 tests with two workers before the
  final matching-evidence consistency check; focused daily, panel, lifecycle, ownership
  and card tests passed 91 after it. Isolated actual-module backend planning/Morek tests
  passed 492, one deselected, two warnings; the isolated lifecycle suite passed 26
  with six warnings. Desktop 1440×1000 and emulated mobile
  390×844 rendered the shipped bundle with a backend-produced dashboard fixture and
  mocked status, with only dashboard/status requests and no horizontal overflow.
  Screenshots are in the temporary `opencode/spotnav-52-{desktop,mobile}.png` files.
  A mobile overflow in the existing visually-hidden text was corrected. Physical touch,
  actual HA Sections/theme behavior, real OCPP and physical charging are unverified.
  No HA access, deployment or hardware operation occurred. Stop after 5.2 for review;
  5.1 visual approval and chart choice remain pending and 5.3 has not begun.
- Actual contracts: `get_dashboard` captures the planner, connection, SOC and plan
  together. `planning.calculated_at`, `reason` and `historical` belong to that planner
  snapshot; `morek_schedule`'s `preview.calculated_at` is instead the time its manual
  preview was built. These are separate requests, not an atomic combined snapshot.
  Proposal windows, energy and estimated cost are backend-derived; the legacy
  `plan.installed` is the controller's plan, not Morek profile inventory.
- `soc` supplies value, source, estimated flag and age in seconds, plus capacity,
  backend efficiency and wall-energy need when available. Capacity is reported or
  configured, and efficiency can be a default or learned estimate, not an independently
  measured current efficiency. An independently defined low-SOC warning threshold has
  not been established; do not substitute a ready-by minimum or the protection floor.
- Current dashboard live facts include charging and measured current, but charging is
  serialized as a boolean even without a controller, so availability/startup must be
  considered. Captured `measured_power_kw` comes from the smart-plug power entity and
  feeds progress; it is not a general Morek power reading in the live API. No verified
  source timestamp or freshness for general Morek measured power has been established.
  Do not use planned power as measured power or turn unavailable into zero.
- Morek status exposes sent profile/time/ACK, effective readback/time, coverage,
  verification and operator/uncertainty state. Backend checks attempt identity,
  current intent and supersession before reporting verification. ACK and readback do
  not establish physical charging, and composite readback is not a profile inventory.
  Status builds a preview but does not contact OCPP; the separate `fetch` does.

### Stage 5.1e — sample vehicle and evidence (review pending)

- The sample vehicle card shows a battery with a target marker, estimated usable
  battery energy, battery- and wall-side target deficits, and plan active time.
  The fictional assumptions are 60 kWh usable and 90% efficiency; estimates are not
  measurements or guaranteed completion. Only the `infeasible` fixture independently
  defines a 20% low-SOC warning; it is not the 40% minimum or a protection threshold.
  The `stale` fixture shows the last SOC with a stale label and suppresses SOC-based
  projections/estimates; its older proposal and readback are also labelled stale.
- The fictional activity view separately identifies proposal calculation/reason, last
  send and ACK, effective-readback time/coverage, and SOC/power freshness, with mismatch,
  matching, unavailable and stale examples. It explicitly leaves the association
  between the current proposal and last sent plan unknown. Readback is not a profile
  inventory and neither ACK nor readback proves charging. These fields are design
  examples, not evidence of live system capability.
- In 5.2 verify actual availability and freshness of usable capacity, efficiency,
  independently configured low-SOC warning, SOC/power timestamps, proposal time/reason,
  sent-plan/ACK times and identity, readback timestamp/coverage and comparison/association.
  Missing fields must remain unknown; do not assume this sample schema exists in the API.
- Prototype build and 19 focused tests passed. Desktop 1440×1000 and emulated mobile
  390×844 checked battery/plan/modal, missing/stale/low-SOC scenarios, evidence, both
  charts and overflow; the battery-note color contrast check passed. 156 observed
  requests were local/data only. Screenshots inspected in temporary `opencode` folder:
  `spotnav-51e-{desktop|mobile}-{vehicle|evidence}.png` and
  `spotnav-51e-{desktop|mobile}-{stale|unavailable|infeasible}-{vehicle|evidence}.png`.
  Existing debugging browser used; physical touch, complete accessibility and HA
  integration remain unverified. No HA or hardware access; dispatch remains unarmed.
  Stop for coordinator/user review before 5.2; overall 5.1 and chart choice await approval.

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

### 2026-11-13 — 5.7b2 live charging and health binding (2.5.119; local, mocked)

- `api/morek_schedule.py`: `_session_readiness` adds `readiness.live` (null when offline/unsupported):
  `{connector_id, status, current_a, power_w, energy_register_kwh}`, each `{value, unit, observed_at,
  fresh}` or null (status also has `normalized`). Sources: connector `status_connector`, `current_import`,
  power and the energy register (kWh/Wh; cumulative, not session). **No power entity name is assumed
  (2.5.119 review; the earlier `power_active_import` template guess was removed).** Power is the user-configured
  `power_entity` of this charger entry (`sources.power = configured_entity`), else
  `ocpp_identity.connector_measurand_entity`: the one enabled OCPP-platform registry sensor whose unique id
  (`ocpp.<cpid>.conn<n>.<key>.sensor` / `sensor.ocpp.<cpid>.conn<n>.<key>`, dotted/hyphenated keys normalised)
  names this charge point, this connector and `power_active_import`. A flat unique id counts only for connector 1
  of a charge point whose charge-control switch is the flat one; other measurands (`power_offered`, export),
  disabled entities and other platforms never match; two matches are `ambiguous`, none `none` (both null,
  reported in `live.sources`). The energy register uses the same strict lookup plus the existing device/state
  class check. Still requires device class power and W/kW at read time. No local OCPP integration source exists
  (`ocpp` is not installed), so whether a real install registers that exact key is **unverified**: if not, power
  simply reads Unknown, and the user can configure a power entity. Status and current still use
  `connector_sensor_entity_id` (existing convention with a default-name fallback; tests confirm connector 2 never
  reads connector 1's). Known gap, untouched: the controller's own `energy_register_entity_for` still accepts a
  flat register as connector 1 without a single-connector check.
  `readiness.measurement` becomes `measured` only for a fresh current/power reading, never for status alone;
  `transaction` and `session_start` are unchanged.
- Frontend: `frontend/sidebar/live-charging.js` (pure) feeds the adapter's "Measured now", evidence
  measurement, readiness line and a mismatch warning. Evidence must carry the status connector id; stale,
  future, malformed or failed-refresh data reads Unknown; measured 0 is shown as 0.
- Tests: `tests/test_morek_readiness.py` (+4, then +10 for the registry boundary: per-connector, ambiguity,
  absence, flat/single, other measurands, freshness, real-zero; real `RegistryEntry` objects behind a fake registry) and `frontend/test/live-charging.test.ts` (new). Run with the
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ... --noconftest` harness above (the HA plugin needs `fcntl`). Old
  `sidebar.test.ts` placeholder assertion changed from `Unavailable` to `Unknown` deliberately.
  No browser, broad or HA-plugin suites were run. No HA access, deployment or charger action.
- Limits: whether the user's charger exposes these sensors, their real update cadence, and physical
  agreement are unverified. The 5.1 visual approval was not touched. 5.7b3 remains open.
