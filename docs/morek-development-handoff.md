# SpotNav Enhanced / Morek development handoff

Last checked: 2026-11-08. This file is a **public-repository handoff**, not a place for
passwords, access tokens, HA configuration exports, logs, or private household information.
Re-check the live system and Git state before acting; observations below may become stale.

## Repository and deployment

- Local checkout: `C:\Code\spotnav-home-assistant`; Git `main`, remote
  `https://github.com/ClassyCircuit/spotnav-home-assistant.git`.
- Fork display name: **SpotNav Enhanced**, from `hacs.json` and the integration manifest.
  Its HA domain stays `spotnav` to preserve existing integration entries and card identities.
- Source version for this handoff: **2.5.5** adds selective cleanup of test profile
  `42001`, with explicit confirmation, persisted outcome and a fresh readback.
  Version 2.5.3 added the Morek
  preview and layout fix (commit `ef483315`); 2.5.4 explicitly enables text
  selection in the card and Morek panel, preserving nonselection on the graph.
  Check Git and the installed manifest before assuming 2.5.5 is installed in HA.
  Marketplace installs this fork from the default branch; it shows commit hashes rather
  than `vX.Y.Z` because the fork has no GitHub Releases. Do not reintroduce
  `zip_release: true` into `hacs.json` while installing from `main`: Marketplace tried
  `/releases/download/main/spotnav.zip` and received HTTP 404. The existing optional
  `.github/workflows/release-zip.yml` does not make every push a release.
- **Deployment drift observed:** the first read-only SMB check on 2026-11-08 found
  HA at **2.5.1**. A later check after the user's screenshot found **2.5.3**
  installed; source is **2.5.5**. Recheck before assuming the latest version is
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
  matching the current settings revision. Unpriced plans and plans that depend on
  stopping early at an energy target are refused. The OCPP 1.6 `TxDefaultProfile`
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
