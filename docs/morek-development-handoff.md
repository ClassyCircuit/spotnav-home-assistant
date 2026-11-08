# SpotNav Enhanced / Morek development handoff

Last checked: 2026-11-08. This file is a **public-repository handoff**, not a place for
passwords, access tokens, HA configuration exports, logs, or private household information.
Re-check the live system and Git state before acting; observations below may become stale.

## Repository and deployment

- Local checkout: `C:\Code\spotnav-home-assistant`; Git `main`, remote
  `https://github.com/ClassyCircuit/spotnav-home-assistant.git`.
- Fork display name: **SpotNav Enhanced**, from `hacs.json` and the integration manifest.
  Its HA domain stays `spotnav` to preserve existing integration entries and card identities.
- Source version for this handoff: **2.5.4**. Version 2.5.3 added the Morek
  preview and layout fix (commit `ef483315`); 2.5.4 explicitly enables text
  selection in the card and Morek panel, preserving nonselection on the graph.
  Check Git and the installed manifest before assuming 2.5.4 is installed in HA.
  Marketplace installs this fork from the default branch; it shows commit hashes rather
  than `vX.Y.Z` because the fork has no GitHub Releases. Do not reintroduce
  `zip_release: true` into `hacs.json` while installing from `main`: Marketplace tried
  `/releases/download/main/spotnav.zip` and received HTTP 404. The existing optional
  `.github/workflows/release-zip.yml` does not make every push a release.
- **Deployment drift observed:** the read-only SMB check on 2026-11-08 found the HA share's
  `custom_components/spotnav/manifest.json` at **2.5.1**, while the fork was **2.5.2**.
  Source is now 2.5.4; update via Marketplace and recheck before evaluating the
  alias diagnostics, preview, or layout fix.
  Do not assume a Git push has installed or restarted the integration on HA.

## Local Home Assistant access: verified facts and limits

- On this Windows machine `\\HOMEASSISTANT\config` was readable, including the installed
  `custom_components\spotnav\manifest.json`, backend and bundled card. The share root
  `\\HOMEASSISTANT\` did not pass a `Test-Path` check; use the `config` share. **Write
  permissions were not tested.** Do not change live files without the user's explicit request.
- An environment variable named `homeassistant` exists in the current shell and has a
  token-like shape. The user believes it contains HA API authentication material, but
  **its meaning and validity are unverified**. Never print, persist, commit, or transmit
  its value to an unconfirmed host. A long-lived token would normally use a Bearer header;
  a login password is *not* an API Bearer token.
- `HOMEASSISTANT` resolved as a host, but a read-only attempt to reach
  `http://HOMEASSISTANT:8123/api/config` could not establish a connection, and a direct
  `curl` attempt to `http://HOMEASSISTANT:8123/api/` was also refused. There was **no
  authentication verdict** and no confirmed API base URL. SMB access does not establish
  the address, protocol or port of HA's API. Ask the user for the URL they use in a
  browser before trying another API address; verify the destination and use only read-only
  calls (for example `GET /api/`) first. Do not publish the user's URL if private.
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
  0/16 A transitions with a final **persistent 0 A** period. No automatic uploads,
  profile cleanup, or authorization of a new charging transaction are implemented.
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
  A manual **Recalculate preview** sends only `status`. No hardware test yet.
- `frontend/src/card-fill.ts` and `frontend/src/card-view.ts` subtract the Morek
  opener and expanded panel from the host's available chart height, rather than
  making the chart fill the added panel height. Regression coverage lives in
  `frontend/test/card-fill.test.ts`. Verify visually in HA after installation.
- The latest user-reported HA experience before 2.5.2 was an unstyled text button
  that disappeared after reporting the station unsupported. That was observed with
  2.5.1 and motivated `d8454555`; **the user has not yet confirmed the fix on HA**.

## Safety and outstanding decisions

- Do not send a test profile until there is a deliberate way to undo it. The final
  0 A period is not cleared on Resume. HA OCPP's generic `ocpp.clear_profile`
  may clear **all** charging profiles on a connector, including other controllers'
  limits; it is not a selective cleanup. A future safe enhancement would selectively
  clear **only** profile ID `42001`, with confirmation and readback. Confirm the
  charger response and effect before calling cleanup successful.
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
- At that check, the config SMB share contained no usable `home-assistant.log`
  (only an empty `.fault` file), and no HA API URL was verified. No OCPP wire
  trace or Home Assistant supervisor/container logs were available from SMB.
  Installed HA OCPP 0.12.3 can create its own `TxProfile` for active transactions
  and `TxDefaultProfile` for future ones (`custom_components/ocpp/ocppv16.py`);
  competition is **one possible** explanation, not a confirmed diagnosis.
  Avoid another send, generic clear, or resuming a competing controller until
  existing profiles and measured current can be investigated safely. Ask for
  the user's HA browser URL to check API reachability, or consult HA Settings >
  System > Logs. Do not assume `GetCompositeSchedule` lists stored profiles.

## Tests, build, and next steps

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
  and loaded, normally via Marketplace + restart. The current HA share was
  observed at 2.5.1; its old backend will not provide the preview field.
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
- Tests: `tests/test_morek_schedule.py` and `frontend/test/morek-view.test.ts`.
  Run the Python tests on Linux/Python 3.14 with project test dependencies, and
  add integration tests for alias resolution, WebSocket access and OCPP responses.
- On the next HA check: confirm the **installed** manifest is 2.5.2, restart HA
  after updating, refresh the browser, open the Morek details panel and capture
  configured ID, resolved ID, connector, and any refusal. If identified, use
  **Refresh from Morek** only, which does not install a profile. Compare later
  sent vs effective schedules and actual current during an authorized session.
- When modifying the card, bump the manifest version, run `npm run build` from
  `frontend/`, and commit the built bundle in `custom_components/spotnav/www/`.
  A push to `main` is not an HA deployment: Marketplace checks custom forks on
  its own schedule, downloads an offered update, and HA must load the new code.
