# SpotNav Enhanced / Morek development handoff

Last updated: 2026-11-18. This file is a **public-repository handoff**, not a place for
passwords, access tokens, HA configuration exports, logs, or private household information.
Re-check the live system and Git state before acting; observations below may become stale.

## Current handoff and approved direction

**Stage 19.2 NOT IMPLEMENTED; local drafts 2.5.181-2.5.184 withdrawn (2026-11-18; code is back to committed 19.1, manifest 2.5.180; no HA/charger/deploy/commit).** The drafts tried to send a replacement for an ambiguous upload. Each version either relied on an unproven ordering assumption (2.5.181/182), held every differing write including a person's Stop/Pause for an unbounded time (2.5.183), or replaced the hold with an arbitrary 3600 s expiry plus an unguarded Stop/Pause bypass (2.5.184). A single hardware trial cannot prove a universal bound, and a bypass lets an old write later override newer intent while claiming recovery. All were removed rather than ship worse behavior; production 19.1 behavior (an uncertain upload keeps the latch and returns `upload_uncertain`; no blind resend) is unchanged. **Concrete technical blocker.** A replacement is safe only if an older in-flight `SetChargingProfile` provably cannot be applied after a newer one. Evidence available: the HA OCPP integration requires `ocpp>=2.1.0` (repo handoff, 2026-11-13 note; the installed `ocpp` version was never confirmed and `manifest.json` here has `requirements: []`); the repo records HA OCPP 0.12.3 as installed at one point. Public `mobilityhouse/ocpp` `ChargePoint.call` (read from public source, not the installed copy) writes the frame, then waits `response_timeout` and raises `TimeoutError`, so a timeout means the frame was handed to the websocket, not withheld, and a late answer is dropped as an unknown unique id. Whether the Morek handles frames strictly in order, drops frames of a closed connection, or can stall a queue is device behavior with no observation; the OCPP 1.6 text was not re-read. Nothing available gives a delivery/order boundary, so no ordering is proven and no hold exit can be justified without an arbitrary number. **Retained:** nothing in code (no independently useful focused change was separable). The abandoned work is kept for reference only: `docs/archive/stage-19-2-abandoned-2.5.184.patch` and `docs/archive/stage-19-2-abandoned-test.py.txt` (not collected by tests, never apply as-is). **What would unblock it:** a user-directed hardware observation of delayed/replaced frames, or a protocol-level proof that closes an in-flight request (for example connection-scoped delivery evidence). Status 19.2: PARTIAL = blocked; 19.1 is the effective behavior. Any statement below about 2.5.181-2.5.184 describes withdrawn drafts.


**Stage 19.3 PARTIAL (non-sending parts only), implemented locally, coordinator review pending (2026-11-18, manifest 2.5.187; mocked/isolated tests only; no HA/charger/deploy/commit; 19.2 is NOT implemented, so 19.3's `resolve`/ambiguous-record parts are NOT done and an unknown write is still never retried).** Existing worker and timers only; no new scheduler or store. **(a) Slow pace (`api/morek_schedule.py`):** `SLOW_RETRY_DELAYS = (1800, 3600, 7200, 14400)` s (non-decreasing, ≥ the last fast delay 900, last repeats = 4 h ceiling). Definite rejection of a still-current intent: `rejection_retry_at` continues after the two fast delays (5, 15 min) with the slow delays by `rejections` count (count and attempt time are already durable in the ledger attempt, so it survives restart; a changed plan has a new fingerprint and restarts at 0); each retry is still the normal guarded `_send_profile_shared` run (Stop/Pause/ownership/identity/admission, same-fingerprint check). Blocker re-evaluation: `blocker_retry_delay` no longer ends at the 12-run cap; runs ≥ `BLOCKER_RETRY_LIMIT` use the slow delays (`blocker_retry.phase` fast/slow; `exhausted` stays in the status but is always false). The pace persists as `retry_state.pace` {code, phase, attempts, next_at}; after a restart the same blocker continues at its persisted attempt count instead of the fast phase (the restart itself still causes one immediate guarded evaluation, as before; a different or cleared blocker starts fresh). The pace never applies to `upload_uncertain`/ambiguous records or to person-actionable blockers (not in `TRANSIENT_BLOCKERS`). **(b) No spam:** a slow-phase rejected re-send is a counted repeat of the same decision (decision key ignores the attempt id once `rejections > 2`), so no log line per slow retry; one line per *changed* decision as before; no notification or banner change. **(c) Durable observations:** bounded (`RETRY_OBSERVATION_CAP` = 8, newest wins, a repeat of a code increments `count`) list in the existing outcome record's additive key `retry_state` {version, pace, observations[{code, evidence (`none`/`pre_wire_marker`/`ack`), basis `observed`, who (system/vehicle/person), next (`automatic_recheck`/`person_action`), count, first_at, last_at}]}, codes from `DECISION_BLOCKERS` only (no payloads/ids/prices). Flushed by `async_flush_retry_state` only under the schedule lock (never interleaves with a send), debounced (5 s, at most one write a minute), never creates, repairs or overwrites a missing/foreign/unreadable record; a failed write is visible as `reconciliation.recovery.persistence` (own failure code or exception class name) and retried every 5 min, never silent, never triggers a send. Read-side: `reconciliation.recovery.observations` and `.persistence` (additive; the card needed no change, `npm run build` + `check-dist` pass at 2.5.187). Stored state is whitelist-sanitized on load (`sanitize_retry_state`). **Named existing-assertion changes (Stage 19 amendment):** `test_stage_95_recovery` (delay list no longer ends in `None`; offline test now expects the slow phase and a live timer), `test_stage_145_fresh_inputs_recovery` (third rejection → 1800 s slow retry, status `exhausted` false, retries continue), `test_stage_145_progress_recovery` (a third rejection re-arms after restart), `test_stage_152_link_monitor` (the cap hands over to the slow pace). **Tests:** new `tests/test_stage_193_paced_retries.py` (7) plus touched files, run individually with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`: `193` 7, `95` 14, `145_fresh` 11, `145_progress` 32, `152` 13, `191` 28, `194` 12, `195` 9, `196` 32, `197` 19, `morek_schedule` 106, `morek_readiness` 38, `morek_outcomes` 3 passed; `test_morek_worker` 142 passed, 1 failed (`test_real_planner_publications_drive_worker_without_browser`: missing `Europe/Stockholm` tz data here, the failure already recorded). **Not done / unverified:** timer-initiated guarded resolution of an unknown schedule (needs 19.2); observations for session-start blockers and 19.7's blocker table; no timer pace for ownership/identity blockers (person-actionable, by design); the restart-time first evaluation is immediate; retry state is not saved while no outcome record exists yet; no real HA `Store`, restart or charger observation; whether a charger tolerates a 30 min–4 h retry of a rejected profile is unobserved. **Review fixes (manifest 2.5.188):** `async_flush_retry_state` now takes the physical-connector admission lock, then the schedule lock (never *waiting* on the schedule lock while holding the connector lock, because the manual path takes them the other way; a busy schedule lock skips the round and re-arms in 5 s), so its read-modify-write of the outcome record cannot lose an uncertainty flag, Stop or ACK written by the send/session paths. `_mark_state_dirty` no longer returns early because of a still-running flush task: a `_flushing` flag makes the flush re-arm itself in `finally` (slow 300 s after a failure, normal debounce after a concurrent change). After a restart the blocker timer keeps the persisted `next_at` (never later than a full step, never an early send; the one start-up evaluation is unchanged). Tests: `tests/test_stage_193_paced_retries.py` (connector-lock race, pending wire with unknown result, reverse lock order without deadlock, fake-clock re-arm after active/failed flush, restart pacing). Mocked boundaries only; no live action.

**Stage 19.7 addendum — switch unavailable after startup (manifest 2.5.189, local, mocked/isolated tests only; no HA/charger/deploy/commit; 19.7 stays PARTIAL, 19.2 blocked).** Previously only a switch edge *to available* started `initialize_and_reconcile` in `_async_setup_ownership_metadata`, so a switch that became unavailable while OCPP stayed connected left the worker `_suspended` and the lifecycle barrier in place until the switch returned. Now an edge to unavailable also starts it when `_morek_upload_link` (local read: exactly one connected OCPP 1.6 supported Morek) is true at the edge **and** again right before the release (a vanished link, an unreadable link, or a newer edge leaves barrier and suspension untouched until an availability edge). The barrier is still released only by the unchanged `async_restore_reconnect`/`async_release_lifecycle_barrier` verification (current durable `morek_schedule` owner, ticket, ledger, identity, no Stop/draining/quiescing); generation/ticket invalidation on the edge is unchanged, so no ordinary write passes the barrier. In `migrate` mode the live-link trigger does **not** run `ensure` (no ownership migration/initialization/handover on the unavailable edge; a legacy or unsettled owner simply fails the release and stays blocked). The worker then resumes via `resume_after_availability_change(generation, switch_available=False)`: `_suspended` clears and a trigger runs, but `session.reconnect()` and the checker's `availability_return` are skipped; start, session, verification, status `online` stay behind the switch (`_available`), uploads use `_upload_available`. Not changed: Stop/Pause/protection/identity/ownership, ambiguous-upload latch. **Tests:** new `tests/test_stage_197_lifecycle.py` (5: live link resumes uploads only; no link stays suspended; link lost before release stays suspended and the switch's later return resumes fully; unreadable link is not permission; worker resume skips session/checker without the switch and ignores a stale generation); `test_stage_23_lifecycle` (236), `test_ownership_lifecycle` (1), `test_stage_197_blockers` (19) pass, run individually with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`. `npm run build` and `check-dist` pass at 2.5.189 (assets rebuilt for the version only). **Limits / not done:** the migrate-mode release with a real settled owner on the unavailable edge is not exercised by a new test (only that a legacy owner stays blocked, via the existing 23 test); whether a connected-link read at the moment the switch drops proves the connection is stable is unobserved on hardware; post-send verification still needs the switch. **Still NOT done for 19.7:** the full blocker table (wording + recovery test per blocker; only the existing `DECISION_BLOCKERS`/`TRANSIENT_BLOCKERS` mapping, e.g. `charger_unavailable`/`morek_offline` → `wait_for_charger_connection`, exists), observations for session-start and 19.7 blockers (19.3 stores only `DECISION_BLOCKERS` codes), storage-failure-before-marker slow-pace retry and after-marker ambiguity wording tests, and anything needing 19.2. Do not mark 19.7 complete.

**Stage 19.7 addendum review fix — link return without a switch event (manifest 2.5.190, local, mocked/isolated tests only; no HA/charger/deploy/commit; 19.7 stays PARTIAL).** Problem: the unavailable-edge release task returned when the link was down at either check, and nothing re-ran it if OCPP later reconnected while the switch stayed unavailable (no switch edge), leaving `_suspended` and the lifecycle barrier forever. Now each unavailable edge records one guarded wait (`link_pending`: epoch, worker generation, barrier revision, `armed`, `running`, `released`) in `_async_setup_ownership_metadata`, driven by the existing `MorekLinkMonitor` through a new `add_listener` hook called after every local link reading (its 30 s poll and pokes); no new timer or read loop. One guarded attempt runs per observed link-live reading after the link was seen not live (`armed`): a stable live link is exactly one attempt, a refused one (legacy/unsettled owner, uncertain ledger, Stop, identity) is retried only after a drop and return, never per poll. The attempt (`_release_on_link`) re-checks the edge epoch and the link after every await and again synchronously right before `resume_after_availability_change(generation, switch_available=False)`, so a link lost during `async_restore_reconnect`/`async_release_lifecycle_barrier` leaves the worker suspended (the worker's own `_upload_available` at dispatch is unchanged and still re-reads the link). `released` is decided by the admission state (barrier deleted at the same lifecycle revision; only the verified release deletes it, and the restore's reconfirmation can already do so), so a barrier released just before the link dropped is not re-verified and resumes on the return only if no newer barrier/revision intervened. The resume now happens only after a verified release in migrate mode (before, the worker resumed even when the release failed; its uploads were still blocked by admission). A newer switch edge, unload or Stop supersedes the wait (epoch/generation/ticket checks; unload removes the listener). The migrate-mode live-link path still never runs `ensure`/migration/handover; the uncertain latch, Stop/Pause, identity and ownership checks are unchanged. Tests (`tests/test_stage_197_lifecycle.py`, 14; real `MorekLinkMonitor`, real `CommandAdmission`, real ownership/outcome files, real `_morek_upload_link`): link down then up with no switch event resumes once and no spam; settled owner in migrate mode is released on the link's return (barrier gone, ticket current, uploads-only resume); legacy owner and uncertain ledger stay blocked with exactly one attempt per link return; link drop during the restore step and during the release step does not resume until it returns (and does not re-release); Stop during admission blocks release and resume; a newer switch edge supersedes the wait and the stale generation; unload cancels it. The late-revalidation test fails without the final check (mutation-verified). Also run individually: `test_stage_23_lifecycle` 236, `test_ownership_lifecycle` 1, `test_stage_197_blockers` 19, `test_stage_152_link_monitor` 13, `test_morek_worker -k "available or suspend or resume"` 22 passed; `npm run build` and `check-dist` pass at 2.5.190 (assets rebuilt for the version only). **Limits:** not exercised on a real HA/OCPP link; the wait ends at the first successful resume, so a later link loss relies on the worker's per-dispatch link check, not a new suspension; the monitor's poll (30 s) bounds the delay after a link return; a link that never passes `_morek_upload_link` (e.g. unsupported identity) never resumes without a switch edge, by design.

**Stage 19.7 addendum — paced re-evaluation while the link stays up (manifest 2.5.191, local, mocked/isolated tests only; no HA/charger/deploy/commit; 19.7 stays PARTIAL).** Problem: the link-wait made one guarded attempt per link return, so a transient refusal (outcome ledger briefly unreadable/uncertain, ticket not yet available) with the link staying up could strand the suspended worker and the lifecycle barrier. Now every attempt in `_try_link_release` (`__init__.py`) schedules the next one on the *existing* `MorekLinkMonitor` readings (30 s poll/pokes via `add_listener`; no new timer): `retry_at` = now + 60 s, doubling per attempt to a 600 s cap (`_link_retry_clock` = `time.monotonic`, patchable). Polls inside the window do nothing; a link drop-and-return still earns an immediate attempt. Success, a newer switch edge/epoch, or unload sets `link_pending = None`, which ends the pacing; a vanished link just re-arms. Only the unchanged guarded verification runs (restore/recover/release, then the uploads-only resume); migration/initialization never runs here in `migrate` mode; no charger call. `CommandAdmission.async_restore_reconnect` previously popped the in-process reconnect candidate after *any* failed reconfirmation, so a transiently refused attempt could never be retried; it now keeps the candidate only for `profile_outcome_unavailable`/`ownership_unavailable`/`reconfirmation_unavailable` (still revision- and generation-checked on every use, and a person Stop still pops it and revokes the ticket). **A person Stop stays permanent by design:** it revokes the completion ticket and bumps the generation, so lifting the Stop does not re-grant authority and the retries stay refused until a new handover (tested). Tests (`tests/test_stage_197_lifecycle.py`, 18 pass under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`): transient unreadable ledger refuses, polls inside the window do nothing, then releases once and resumes exactly once with no `station.call`; a persistent uncertain ledger backs off (gaps non-decreasing, ≥60 s, ≤ cap+poll, far fewer than one per poll) and stays blocked; Stop never undone; new epoch and unload stop the pacing. `test_command_admission.py::test_admission_is_reused_at_shared_boundaries_not_profile_writer` fails at HEAD too (its allow-list lacks `morek_session.py`/`morek_checker.py`); not caused or fixed here. Unverified: real HA timing, installed behavior, physical charging.

**Stage 19.7 PARTIAL (independent parts only), implemented locally, coordinator review pending (2026-11-18, manifest 2.5.186; mocked/isolated tests only; no HA/charger/deploy/commit; 19.2 and 19.3 are NOT implemented and not assumed).** **Audit/fix 1 — poisoned outcome ledger (`execution/morek_outcomes.py`):** any failed or cancelled write set `poisoned` until HA restart, so a transient disk error blocked every later send/read as `outcome_storage_uncertain`. `MorekOutcomes` now clears the poison itself, on the next `read()`/`write()`, only through `_recover`, and the ledger now serializes itself: one non-reentrant `asyncio.Lock` (a leaf lock: the critical section only awaits the executor and HA's own Store write lock; public `read`/`write` take it once and call `_write_locked`/`_read_disk`, so no recursion and no admission-lock inversion) covers recovery, the poison/late-write fields and the write, so two readers cannot both recover and a recovery cannot clear a poison that a newer failed write set meanwhile; a caller cancelled while waiting holds nothing. Recovery's rule: two equal valid rereads of the file; and, when a write's executor job may still land (a cancellation, or a failed/mismatching verification read after the save), only if the disk equals the exact record that write carried **and** differs from the record known on disk before it (an equal record could be a not-yet-run job overwriting a later write; an unknown prior also never recovers). **Completed failure vs still running, from the installed HA 2026.9.2 `Store.async_save` source (read, not run against a live HA):** it awaits `_async_handle_write_data` → `_write_lock` → `await hass.async_add_executor_job(...)`. A non-cancellation exception out of `async_save` is raised before any job starts or by the finished job (nothing in flight), so verified rereads suffice. `WriteError`/`SerializationError` are caught and only logged, so `async_save` then returns normally with nothing written; the verification reread mismatches, which the ledger treats as a possible late write and so stays poisoned (conservative, until restart) because a normal return cannot be told apart from the next case. While HA is `stopping`, `async_save` stores the data and returns without writing; it lands at the final-write event, i.e. later. `CancelledError` only cancels the awaiter; whether the executor job already started or can still run was **not** proven, so it is treated as possibly landing. An invalid, unsupported or unreadable file is **never** reinitialized or overwritten (that could hide a dispatched write); it stays `outcome_storage_invalid`. `write()` previously swallowed an unreadable pre-save read and went on to overwrite, contradicting this; it now raises `OutcomeUnavailable` before any save (not a failed save, so no poison), and only a genuinely missing file (reads as `None`) may be initialized. Dispatch safety is unchanged because recovery reads the markers: a post-wire failed ack write leaves `wire_intent` + `uncertain` on disk (stays ambiguous); a failed pre-wire write leaves `pre_wire` (the existing 19.1 read-side proof applies). Status `ledger.recovery` ∈ none/recovered/late_write_unproven/storage_still_invalid/storage_changing (attribute only; no status field or banner added). **Audit/fix 2 — misleading switch:** `charger_available()` is the transaction-bound charge-control switch alone, so a switch that is unavailable at setup with OCPP online blocked reconcile and dispatch as `charger_unavailable`. `MorekScheduleWorker._upload_available()` = switch available OR `upload_link()` (exactly one connected OCPP 1.6 physical Morek and supported identity, a local read); it replaces `_available()` ONLY at the worker's reconcile gate and dispatch `validate()`. Start/session, `_verification_current`, status `online` and the lifecycle suspension keep the switch-only gate. Identity, ticket, generation, Stop/Pause, protection and admission checks are untouched. **Not fixed (blocked, honest):** a switch that *changes* to unavailable still sets `_suspended` and a lifecycle barrier, resumed only when the switch returns (`control_available` in `__init__.py`); lifting that needs a design for what evidence ends the barrier while OCPP stays online (ownership/reconnect semantics), so uploads after that edge still wait for the switch. Post-send verification also still needs the switch (it reports not verified, never matched). **Not done:** the full blocker table (wording + recovery tests per blocker), slow-pace retry and durable observations (need 19.3), ordering/ambiguous resolution (19.2), any ownership/identity relaxation or automatic ownership transfer. Production-link wiring: the worker's `upload_link` closure now calls module-level `spotnav._morek_upload_link(hass, target)` (same logic, extracted so it is testable); tested against the real `_identity_status`/`_charge_point`/`classify_morek_identity` with a fake `hass.data['ocpp']` (connected, not-ok status, non-1.6, missing, foreign, ambiguous, wrong connector, no target) feeding a real worker. The closure's one-line call inside `_async_setup_auto_preview` (full setup) is not itself exercised. Tests: new `tests/test_stage_197_blockers.py` (19: adds concurrent-reader single recovery, recovery-vs-newer-failed-write interleaving (both verified to fail without the lock), cancelled waiter, cancelled executor read, five invalid-file and one unreadable-file write refusals, missing-file initialization, production link), plus `test_morek_outcomes` (3), `test_stage_191_upload_outcome` (28) and `test_morek_worker -k available` (6) passed, run individually with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`. Not run: broad suites, HA-fixture/browser tests, anything live; the real HA `Store` cancellation behavior is unobserved. `npm run build` and `check-dist` pass at 2.5.186. Wider run: `test_morek_*` and `test_stage_19*` 470 passed, 1 failed (`test_morek_worker::test_real_planner_publications_drive_worker_without_browser`: 'Europe/Stockholm' unknown timezone, no tz database on this Windows box; fails identically on the stashed baseline). Rollback: none needed (no stored format change).

**Stage 19.6 PARTIAL, implemented locally, coordinator review pending (2026-11-18, manifest 2.5.184; mocked/isolated tests only; no HA/charger/deploy/commit; 19.2 still unresolved, its latch untouched and not assumed).** **Audit (`execution/morek_session.py`):** before this change any stored session-start record in `pending` or `unknown` blocked every later start for every token (`previous_start_may_have_applied`), including after a confirmed reboot (15.5 minted a `boot:` token that then hit this return) and after a full unplug/plug-in. `pending` was written before the ownership recheck and the OCPP call with no way to tell a crash before the call from one after it. **Changes:** (1) attempt record gains `dispatch`: `pre_wire` (with the existing record-first write), `wire_intent` (new durable write strictly before `start_transaction`, re-validated afterwards; a Stop in that window aborts before dispatch), `resolved` (accepted/rejected). A `pending` record still `pre_wire` is provably undispatched and is released (`aborted_before_dispatch`, `proof: no_wire_intent_marker`, attempt not counted); legacy `pending` without the field, `wire_intent` and `unknown` are ambiguous. (2) `_resolve_observed`/`_observed_session`: a fresh HA-stamped Charging/SuspendedEV/SuspendedEVSE report postdating the request, or a fresh positive transaction id whose `changed_at` postdates it, marks the record `observed` (state, `resolution{by,was,at}`); shown as `session_observed` (observed, not inferred as the request's success); runs on an active-status edge while an earlier request may be unresolved and inside the Preparing evaluation; records only, no send, no admission ticket (schedule lock as the start run). (3) **Review correction (same 2.5.183):** the first draft superseded an ambiguous record on a genuine new plug-in (fresh Preparing + affirmative no transaction), an `unplug:` token or a confirmed boot token. **Removed:** none of these orders the old request against the new evidence (an old frame may be delivered or queued and applied later; for the boot case the request may have been written to the new socket before the boot signal was noted), and no evidence shows the charger rejects a duplicate start. An ambiguous record now blocks every later token (`uncertain` / `previous_start_may_have_applied`, additive `session_start_recovery.who_acts=person`), the bounded evidence re-check and `session_start_history` were removed; only provable pre-dispatch (`pre_wire`) release and affirmative observation (`observed`) remain. The late-delivery case resolves as `observed` and sends nothing. **Locking:** `_resolve_observed` wrote the connector-wide ledger under only the schedule lock; it now takes the connector admission lock first and the schedule lock inside **only if the schedule lock is idle** (no `locked()`/waiters; never a blocking wait: the manual path holds the schedule lock and then asks for the connector lock, so waiting would deadlock). **Review fix (2.5.184):** a busy schedule lock skips the observation, leaves `_resolve_pending` set and arms a bounded retrigger (`RESOLVE_RETRY_DELAY_S`, at most `SESSION_RETRY_LIMIT` consecutive skips, cancelled on close); the record stays ambiguous meanwhile and nothing is sent or retried. Real-lock regression `test_busy_schedule_lock_with_manual_waiting_for_connector_does_not_deadlock` (fails without the skip). The rest: re-reads the record and re-checks closed/quiescing/draining/person-Stop/identity after each await, and a person Stop or changed record leaves it untouched. (4) Status: additive `readiness.session_start_recovery` {class none|proven_not_dispatched|ambiguous|ambiguous_superseded|resolved, evidence, reason, who_acts}; the visible state stays `uncertain`/`previous_start_may_have_applied` while ambiguous (never charging/failed/not started); an eligible token with missing evidence arms the existing bounded recheck (12 runs, never sends). Stop/Pause/legacy pause/protection/identity/ownership/`validate()` run before any of this and still win; still at most one start per token. Manifest 2.5.183 (rollback hazard: an older build reads `observed`/`dispatch` as an invalid record and stays `uncertain`). **Limits:** recovery from an ambiguous start remains unsolved (needs an ordering proof or user-directed hardware observation); observation depends on HA stamping the status/transaction sensors (unverified); the boot counter is unverified (R5); no UI wording changed; nothing proven on hardware. **Tests:** new `tests/test_stage_196_start_recovery.py` (32 after the lock-order fix) and the superseded `test_pending_or_unknown_earlier_request_is_preserved_and_never_retried` in `test_stage_155_boot_start.py` replaced by three cases (no boot evidence, confirmed reboot and request after the boot signal all stay preserved); run individually with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`: 196 (31, incl. race tests that fail without the connector lock), 155 (35), `test_morek_session` (41), `test_morek_session_activation` (28), `test_stage_94_logs` (20), 191 (28), 195 (9), 153 (40) passed. Not run: `test_morek_worker`, `test_morek_schedule`, Stage 14 files, full suites, HA-fixture and browser tests. `npm run build` and `check-dist` pass at 2.5.183.

**Stage 19.5 PARTIAL, implemented locally, coordinator review pending (2026-11-18, manifest 2.5.182; mocked/isolated tests only; no HA/charger/deploy/commit; 19.2 still unresolved and not assumed).** Audit of planner holds: fallbacks that already plan are the preserved uncapped proposal under stale prices, trusted estimates for stale SOC (17.2), learned kWh/percent for unknown capacity (17.3), labelled `progress_unknown` (17.1), partial published plans (16), buy-before-publication / charging-without-prices, and a best-effort run for a short deadline. Gap closed: 11 planner reasons reached the banner as generic 'plan is being recalculated' with no who-acts; `api/morek_schedule.EXTRA_PLANNING_HOLDS` (separate from the 17.6 `PLANNING_HOLDS`, so its tests are unmodified) names them, and `decision_blocker` consults both. Person-owned (`adjust_planning_settings`): settings_missing, fiscal_value_missing, minimum_above_target, price_policy_unavailable, solar_execution_unavailable, deadline_too_short; system wait-for-prices: price_data_invalid, insufficient_price_horizon, publication_pending, waiting_for_history; `check_logs`: unexpected_failure. Banner shows person holds as needing attention (existing text); no frontend source changed, only the rebuilt assets carry the new version. Not implemented, no invented inputs: any default plan for unknown SOC/capacity/departure. Stability (real worker, `setup(active=True)`): observation reads, equal publications, SOC drift under 5 min send nothing; horizon extension sends once carrying the window, an equal repeat sends nothing; a planner hold clears nothing. Note: a mixed SOC+publication burst is strict (14.3) by design. No confirmed bypass; thresholds untouched. **Limits:** resolve/late response (19.2 blocked) and slow retry (19.3 absent) are not testable; the fallback table's 'plans' rows cite existing test files, not new real-planner cases. Tests: new `tests/test_stage_195_fallbacks_stability.py` 9 passed; `test_stage_176` 19, `142` 22, `143` 22, `194` 12, `146` 15 passed, run individually with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -p pytest_asyncio.plugin --noconftest` on Windows. Not run: full suites, `test_morek_worker` whole, HA-fixture files (no `fcntl`; known Windows plugin/loop-guard limits), browser tests. `npm run build` and `check-dist` pass at 2.5.182.
**Stage 19.4 implemented locally, coordinator review pending (2026-11-18, manifest 2.5.181; mocked/isolated tests only; no HA/charger/deploy/commit; independent of the blocked 19.2).** **Audit:** `_proposed_profile` → `profile_for(proposal.shown_periods, …)` already puts every known planned window through its end into the wire profile (three windows, seven transitions, final 0 A; the hardware limits `MOREK_MAX_BLOCKS=3`, `MAX_PERIODS=8`, 48 h are unchanged); a fourth window is refused (`too_many_blocks`), never truncated; a partial-price day sends only the published part (Stage 16); a later publication extends through the normal compared reconcile (`same_effective_schedule` treats an equal republication as equal). No production code change was needed for (a); new tests pin it. The existing readback already required coverage through the last stop plus one hour (`coverage_too_short` otherwise) and the existing 15.3 reconnect check and one-shot verification remain the only readers (no polling added). **Gap fixed (b):** a shorter readback produced only `coverage_too_short` with no statement about the span it did cover. `_compare_remaining` is now a wrapper over the unchanged `_compare_remaining_core` and adds `coverage_state` (`matches`, `matches_covered_span`, `differs`, `not_verifiable`), `covered_until`, `plan_end`; `_covered_span_state` compares only transitions at least the 90 s tolerance before the reported end and never sets `matched`, so every gate that reads `matched`/`reason` (session-start evidence, Healthy check, repair, dedup) behaves as before. `_guard_coverage_state` (status time) demotes the claim to `not_verifiable` for a readback not associated with the comparison, a superseded/stale/interrupted comparison, or a span whose covered end has passed; the HA-restart and offline-readback paths also reset it. **(c):** status gains `reconciliation.horizon` from `schedule_horizon` (state, `plan_end`, `windows`, `ack`, `coverage_state`, `covered_until`, `plan_ended`, `physical_charging` fixed `unknown`). Card (`morek-view.ts`) says "Limits matched only until …; the sent plan ends …. Not verified for the whole plan, and not proof of charging" (or differed / not verifiable). Sidebar `schedule-check.js` link-lost note now appends the last-known sent schedule's end, the last-read class, that continued use depends on the charger's own clock, settings and authorization and its own protections, that it is not a guarantee, and that SpotNav cannot start or change anything while the connection is down; unusable/absent horizon leaves the old text. **Limits:** nothing here resolves an ambiguous upload or relaxes the 19.1 latch/Stop/Pause/protection rules (19.2 stays blocked); no claim about the charger's clock/firmware, whether a retained profile survives an HA outage or reboot, or physical charging; the horizon fields describe the *last sent* profile, not a guarantee. **Tests:** new `tests/test_stage_194_horizon.py` (10) and `frontend/test/horizon-offline.test.ts` (7); run with stub `fcntl`/`resource`, socket guard patched out (Windows harness): `test_morek_schedule`, `test_stage_153_schedule_check`, `test_stage_194_horizon` 156 passed; frontend `horizon-offline`, `schedule-check`, `morek-view` 59 passed; Stage 14 regression subset (141–146 incl. 145 progress, `test_morek_worker`, 161, 162, 191, 95, `test_morek_start_schedule_evidence`): 398 passed, 0 failed, 72 teardown errors in `test_morek_worker.py` (45) and `test_stage_162_safe_dispatch.py` (27), all the repo's loop-I/O guard (`Path.read_text` on the loop from `execution_ownership.py:30`, a Windows harness limit, not from this change; not re-verified on stashed source here). Not run: `test_morek_schedule`'s siblings `test_morek_session*`, `test_stage_103_partial` (known harness failures per the 19.1 entry), full suite, browser tests. `npm run build` and `check-dist` passed. Unverified: installed behavior, HA-fixture tests, browser tests. **Review correction (2026-11-18, same manifest 2.5.181):** `covered_until` for `matches_covered_span` previously equalled the readback's reported end although `_covered_span_state` never compared the final 90 s tolerance margin, so a mismatching transition inside that margin was claimed as matching. Now `_compare_remaining` reports `covered_until = coverage_end − tolerance` for a span match (`coverage_end` itself is unchanged and still the read's reach), `_guard_coverage_state` expires a span claim at that compared end (not the reported end), and the card/sidebar word the boundary as compared-only-until. A readback shorter than the margin remains `not_verifiable`. Sidebar offline text no longer says a schedule "runs until"/"matched" when the charger's answer was not `accepted`: it says the charger did not confirm accepting it, it may not be installed, and when it was planned to end. New tests: trailing-margin mismatch, short/expired span, rejected/unknown/faulted ack. Targeted: `test_stage_194_horizon` + `test_morek_schedule` 118 passed (Windows, stub `enable_custom_integrations`, HA plugin not loadable: no `fcntl`); frontend `horizon-offline` 7 passed, full vitest run completed; build and `check-dist` passed. Still unverified: installed behavior, HA-fixture tests, browser tests.
**Stage 19.1 implemented locally, coordinator review pending (2026-11-18, manifest 2.5.180; mocked/isolated tests only; no HA/charger/deploy/commit).** `_send_profile_shared` now classifies every upload attempt from durable markers (`attempt.dispatch_class`): `pre_wire` (written with the existing record-first write), `wire_intent` (a NEW second durable write made strictly **before** `point.call`, so it only ever means "the call may have begun"; its absence after a restart proves by write ordering that no call was made), `resolved` (ACK/rejection) and `not_sent` (a proof code in `attempt.not_sent_proof`). The roadmap's "wire-started after handoff" form was **not** justifiable (a marker written after the call object is handed over can be lost by a crash while the call proceeds), so the before-call intent marker is used and presence stays ambiguous. Proof codes: `validation_after_persistence`, `validation_before_dispatch` (incl. a Stop during the intent write), `ledger_changed`, `durable_check_failed`, `durable_check_refused` (each releases the latch and returns the new non-sending result `upload_not_sent`; the next normal trigger sends once; no rejection count, no repair-budget entry), and read-side `no_wire_intent_marker` (cancellation/crash before the intent write). **Review fix (2.5.180): the read-side release now runs through the REAL production entry.** `CommandAdmission.async_execute("owned_profile")` refused every `uncertain` ledger (`profile_outcome_unavailable`) before `_send_profile_shared` ran, and after a restart `async_reconfirm_completed`/`async_recover_after_restart` (the only way to get a ticket) and the lifecycle-barrier release refused it too, so the release could not happen in production. New `CommandAdmission._async_read_outcome_recovering` replaces the ledger read at those three gates (all under the physical connector lock): when `upload_outcome_class` says `not_sent_provable` it records the proof through `_release_not_sent` (fresh re-read, edits only that exact still-`pre_wire` attempt) and re-reads. It does NOT release a legacy record, `wire_intent`, an uncertain removal, an entry-id mismatch, an attempt in flight (`spotnav_morek_sending`), a person Stop, a draining/quiescing connector, or while the entry's schedule lock is held or has waiters (never waited on: the manual path takes schedule-lock then connector-lock); a changed/unreadable record keeps the latch. The release grants no authority and sends nothing: ticket, lifecycle, generation, identity, Stop and ownership checks still decide every later write, and after a restart a ticket still needs the existing dispatch/recovery-proof reconfirmation. **Automatic reevaluation:** `upload_not_sent` is now in `TRANSIENT_BLOCKERS`, so the worker's existing bounded blocker timer (60/180/600/900 s, at most 12 timer runs per episode, events still re-evaluate) re-runs the guarded read-and-compare path; the admission-side recovery needs no timer because the same run continues into the guarded send. Limits: the 12-run bound then stops timers (a later event/trigger still re-evaluates); a restart whose ledger lacks both dispatch evidence and the recovery proof still ends at `restart_dispatch_evidence_unavailable` (unchanged, not 19.1's to loosen). `ledger_changed` never overwrites a changed ledger: the release re-reads the current record and edits only this exact still-pre-wire attempt, otherwise the latch stays. If the proof cannot be recorded (storage unreadable/poisoned) the latch stays and the result remains `upload_uncertain`. Ambiguous (still blocking, never auto-retried): timeout, any exception or cancellation from `point.call` (the `ocpp` package is not installed here, so its `call` source could NOT be inspected and no pre-transmit exception is assumed), a failed/interrupted ACK write, a restart after the intent marker, a failed intent-marker write, and every legacy record without `dispatch_class` (never silently released on upgrade). The OCPP request object is now built before the intent marker so an import/construction error is provably pre-wire. Status: additive `reconciliation.upload_outcome` (`class` not_sent_provable|ambiguous|not_sent|resolved|none, `proof`, `basis` inferred|observed, `reason`); decision event `upload_not_sent` (action blocked, intent none, ack `not_sent`, blocker `wait_for_next_automatic_attempt`); manual send refuses with `upload_not_sent`. No resolution of ambiguous records (19.2), no timer, no UI change, no `clear_profile`. Tests: new `tests/test_stage_191_upload_outcome.py` (28 cases: 16 original, plus real-admission cancellation→release→one guarded send, restart through `async_recover_after_restart`→release→send, 8 altered/concurrent never-release variants, a changed-between-proof-and-write race, and the bounded `upload_not_sent` re-evaluation; the real-admission cases fail with the admission change reverted); run on Windows with stub `fcntl`/`resource` modules and the socket guard lifted, the 306 teardown errors in worker/lifecycle/ownership files are only the repo's loop-I/O guard (`Path.read_text` on the loop) and are identical without this change; isolated run of `test_morek_worker/outcomes/schedule`, Stage 141–146, 153, 154a/b, 62, 95 and the rest of the Stage 14 list passed (484 passed); the 8 failures in `test_morek_session.py`, `test_morek_session_activation.py` and `test_stage_103_partial.py` fail identically on the unmodified source (verified by stashing the change; harness limits). `npm run build` and `check-dist` passed. Unverified: installed behavior, charger/OCPP library transmit semantics, HA-fixture (`fcntl`) tests, browser tests.

**Stage 8 complete locally, coordinator-reviewed (2026-11-16, manifest 2.5.178).** All five substages were delegated to fresh Claude medium agents, reviewed, and committed/pushed separately. Root's final checks: 71 focused savings/cost/history/panel tests, build, check-dist and prototype build passed. A malformed reference-source list now becomes an invalid savings block rather than throwing while rendering. Current-month summaries show read time, refresh on repaint no more than once per five minutes, and retain explicitly last-read figures after failure until Retry. Costs are spot-only; savings compare the same priced energy with full HA-local delivery-day averages. Unknown placement, missing reference prices and unknown historical providers remain explicit limitations. No deployment, HA/charger calls, browser/mobile/dark visual check or physical validation. No unstarted feature work remains in the active roadmap; §9 still records outstanding local reviews and user-owned checks. This closure supersedes implementation-time pending-review and older next-stage wording below. The original Stage 16.2 stash remains untouched.

**Stage 8.3b implemented locally, root review pending (2026-11-16, manifest 2.5.178).** Frontend only: savings/summary cards, read time and one bounded current-month refresh; see "Stage 8.3b" at the end. Stage 8 stays open until root review.

**Stage 8.3a coordinator-reviewed, 2.5.177 (2026-11-16).** Root reran 101 focused savings/cost/contract/history tests successfully. Reference prices require a contiguous full HA-local day from held memory snapshots; old stored day averages are not proof. Savings actual/reference use the same comparable subset, and percentages use summed amounts. Recorded-slice provider provenance remains unknown; retained-source mismatches are excluded. No live verification. Next: 8.3b final UI. Pending-review notes below are superseded.

**Stage 8.2b coordinator-reviewed, 2.5.176 (2026-11-16).** Root reran 53 focused cost/history/panel tests and check-dist successfully. Day, session and month amounts use backend spot-only major-currency values; fiscal and forecast totals stay separate. Month reads are bounded and context-bound. No visual/live validation. Next: 8.3a savings backend. Implementation-time pending-review notes below are superseded.

**Stage 8.2a coordinator-reviewed, 2.5.175 (2026-11-16).** Root reran 78 focused spot-cost, history, session-contract, summary and costing tests successfully. Spot-only fields are additive; legacy fiscal and start-day buckets remain compatible. Placed cost/priced energy sums by delivery day; energy without time placement cannot be split across days and remains separately unallocated. Historical provider labels are not recorded. No live verification. Next: 8.2b display. This supersedes implementation-time pending-review wording below.

**Stage 8.2a implemented locally, root review pending (2026-11-16, manifest 2.5.175).** Backend only; spot-only cost, see "Stage 8.2a" at the end. 8.2b/8.3 not started.

**Stage 8.1 coordinator-reviewed, 2.5.174 (2026-11-16).** Root reran 95 focused history/day/chart-track tests and check-dist successfully after the retention correction. The raw window uses only oldest_by_kind; old plans/capture marks do not prove raw readings. Session-only metadata remains usable when the history read fails, and pending chart reads make no success claim. Implementation-time pending-review wording below is superseded. No live or visual verification; next is 8.2a spot-only costs.

**Stage 7 complete locally, coordinator-reviewed (2026-11-16, manifest 2.5.173).** All seven substages were implemented by fresh Claude delegates, reviewed and committed/pushed separately. The detailed implementation-time entries below retain their original pending-review wording; this closure supersedes it. Final 7.5 review checked request/context binding, explicit retries, unit conversion, unknown data and separate absolute/relative classifications. Root reran the 35 new model/panel tests (passed), `npm run prototype:build` and `npm run check-dist` (passed). No browser or live validation, HA/charger calls or deployment. The agent reported two failures in the unchanged prototype vehicle-evidence tests without baselining them; those remain unexplained and were not used as acceptance evidence. Stage 8 is the next unstarted feature queue, only on request; costs default to spot-only and savings use delivery-day average spot prices. The old Stage 16.2 stash remains untouched.

**Stage 7.1 implemented locally, review pending (2026-11-16, manifest 2.5.167; no HA/charger/deploy/commit).** Backend: `spotnav/get_price_days` (`api/price_calendar.py`, registered in `__init__.py`; named so it does not clash with the webhook's `api/price_days.py`), `available` (≤ 400 held display days, newest first) and `range` (≤ 8 days, rows in the dashboard's `published_intervals` shape from the shared `published_rows` builder, per-day provenance). Memory-only reads (`PriceRepository.held_days` is new and in-memory, `day_snapshot`, `archive_reachable`); no fetch/refresh/write/file scan. Today is the price area's calendar. A held day with an unusable FX rate is `intervals: null, reason: no_price_rate` (found by test: `chart_intervals` raises) and invalid geometry `invalid_intervals`; neither fails the page nor becomes zero. UI: `shared-dashboard/price-days.js` (state machine, request tokens on charger/generation/area/currency, response validation, explicit retry, no hidden loop, merge by instant: identical duplicates dropped, conflicts/overlaps refuse the page), `price-nav-view.js` (buttons with visible disabled reasons, partial label, bounded Earlier picker), `sidebar/price-chart.js` takes a `view` (range intent + `viewKey`) so `charts.js` keeps the user's zoom on routine refreshes and resets it only on a new `viewKey`; `panel.js`/`adapter.js` wire it; the preview uses the same state machine with `prototype/price-days-fixture.js` in backend shapes. Default view stays the dashboard's today/tomorrow feed; only the tiny availability read happens automatically. Tests: `tests/test_stage_71_price_days.py` (23, real `PriceRepository`, hass-free: `python tools/run_isolated_logs_tests.py tests/test_stage_71_price_days.py`), `frontend/test/price-days-nav.test.ts` (23) and `price-days-panel.test.ts` (1, real panel with mocked echarts/WebSocket); also green: `price-bands`, `sidebar-price-chart`, `charge-session-panel` (its read allowlist was already missing `get_market_options`/`get_entity_config`, so it failed before this change; both and `get_price_days` were added), `charge-now`, `charge-now-layout`, `live-charging`, `dark-theme`, prototype `sample`/`daily-sample`/`boundaries`, `tools/test_published_intervals.py`; ruff and `tsc` clean; `npm run build` and `check-dist` current at 2.5.167. **Not run:** full pytest/vitest, the HA-fixture suite, browser/Playwright (visuals, touch and the real `ECharts` canvas unverified), anything live. Limits: `All loaded days` is the current page (≤ 8 days) plus today/tomorrow, never the repository; the preview's axis is the sample's hour axis; `prototype/sample.js` `day()` now says "Earlier" before yesterday; sidebar strings are English literals like the neighbouring cards (no i18n keys added). Not done on purpose: 7.2+ and Stage 8; Stage 7 stays open.
**Stage 7.2 implemented locally, review pending (2026-11-16, manifest 2.5.168; fixtures and mocked ECharts only; no HA/provider/charger/deploy/commit).** Reproduced with fixtures and fixed only what failed: (1) **explicit Today** had `range = null`, i.e. the rolling `now−1h → horizon end` window that can include tomorrow; `price-days.js` now marks explicit Today/Tomorrow/All/day choices (`selection.explicit`, a per-choice sequence in `viewKey`), so explicit Today = the local calendar day (`localDaySpan`, 23/25 h correct), Tomorrow = tomorrow, All = the merged page; the **default view keeps the old rolling horizon** and the default key `today::0` is unchanged; pressing the same button again resets the zoom, routine refreshes still keep it. (2) **Tick labels:** `charts.js` decided "date label" by `h % 24 === 0`, which is always true for millisecond ticks, so every tick carried a date; `price-chart.js` now supplies `tickLabel` (date only at local midnight) and zone-aware `timeTicks` (multi-hour steps on local wall hours, so a 24 h step is local midnight instead of 01:00/02:00; hourly ticks stay elapsed so the repeated 25 h-day hour keeps its two offsets; a non-existent spring-forward hour is skipped). The preview sample keeps its hour-unit fallback. (3) `days()` stopped after 5 days, so a 10-day paged view lost its day cells/midnight lines; limit 16. (4) `renderItem` drew a stray vertical joint at the plot's left edge when the interval's start boundary was off screen (real `clipPointsByRect` clamps instead of clipping); now drawn only when the boundary is on screen. (5) markPoint (LOW/HIGH pins) was hoverable and reached the interval tooltip formatter with a numeric `value`; pins are `silent` and the formatter returns `''` for a non-interval value. (6) a clamped user zoom after a refresh is now snapped to interval boundaries. Verified no defect (kept as fixtures): hourly→quarter-hour inside one horizon (contiguous joints, unknown hour never bridged, snap inside the 15-minute region), negative values below zero and a spike clipped at the plot edge with the real `echarts.graphic` clip helpers, EUR→cents exactly once, tooltip for negative/gap/unsafe unit, the 18.4 axis (−10…30 with a negative) and band colours, resize (chart.resize + tick redraw only; range and options untouched; zero requests), reset action. Tests: `frontend/test/price-chart-interaction.test.ts` (15 cases, real `charts.js`/`price-chart.js`/`price-days.js`, ECharts mocked except `graphic`, Stockholm and Riga DST dates); with `price-bands`, `price-days-nav`, `price-days-panel`, `sidebar-price-chart`, `dark-theme` 56 vitest cases green in 2.7 s; build and `check-dist` current at 2.5.168. **Not run:** full vitest/pytest, browser/Playwright, the real canvas (clipping/tooltip hit-testing, touch, orientation, dark/mobile visuals), anything live. No backend, planning or price-coverage change. Stage 7.3a onward still open.
**Stage 7.3a implemented locally, mock review pending (2026-11-16, manifest 2.5.169; fixtures/mocks only; no HA/provider/charger/deploy/commit).** Backend (additive, API v1): `charging_history` now returns `truncated` (`{truncated, cut, limit}` per capped list, plus `price_slices` and per-session `price_slices_truncated/_cut`; gaps, restarts and sessions are counted before the cut, which they were not before), `retention.oldest_by_kind` (new `ChargingEvidenceStore.oldest_by_kind`: earliest retained sample per kind, gap rows excluded), `retention.digest_days` and `retention.limits`; blocks that start before the retained power rows add the reason `block_starts_before_retained_power` (verdicts unchanged). Session reconciliation, capture, price and progress code untouched. Client: `getChargingHistory` (`src/api.ts`, one HA-local `date`), `shared-dashboard/history-day.js` (request state machine bound to charger, generation/permission epoch, zone, day and sequence; no automatic retry; today re-read at most every 5 min, a past day never, a failed refresh keeps the earlier read; selectable range today−62 days; validation then a plain display model) and `history-view.js` (nav, loading/unavailable/error/permission/invalid, full / partial raw / plans-without-power / digest-only / none / legacy-integration states, truncation banner, sent-plan blocks with known/unknown spans and version ids, flow with bounded/open edges, flow-versus-plan rows, energy bases side by side and never summed with `null` shown as Unavailable, sessions with reconciliation state and unplaced/unassigned late energy as separate lines that never certify a total). Wired in `sidebar/panel.js` (`historyView`, `historyNav`; asks nothing while `hass.config.time_zone` is unknown) and `dashboard.js` (read-only nav events); the preview uses the same state machine and renderer with `prototype/history-day-fixture.js` (nine days, each one backend situation). The old placeholder chart remains in the preview only (the `readings`/`sentHistory` mapping cannot show trustworthy flow); the live card never draws it. English literals (like the neighbouring cards), no i18n keys. Tests: `tests/test_stage_73a_history_signals.py` (10, real store/builder, > 200 rows, plans older than power rows, wire shape pinned by `tests/fixtures/history/answer_shape.json`), `frontend/test/history-day.test.ts` (24) and `history-day-panel.test.ts` (3, real panel); `sidebar.test.ts`'s read allowlists were already missing `get_price_days` (3 tests failed before) and now include both reads. Also green: `test_stage_63_history`, `test_stage_158_late_reconciliation`, 10 neighbouring vitest files (227), sidebar/charge-now/live suites, prototype `sample`/`daily-sample`/`boundaries`, `tsc`, ruff, `npm run build`, `check-dist`, `prototype:build`. **Not run:** full pytest/vitest, the HA-fixture suite, browser/Playwright (layout, dark/mobile, the real date input), anything live. Limits: the HA zone comes from `hass.config.time_zone` (the integration's zone) and the day's zone is stated whenever it differs from the price market's; the preview's day axis is UTC; retention is not extended (about 3 days of measured detail, digests appear about a day after a day ends); no tracks on the price axis (7.3b), no cost or day review (8.x). Stage 7 stays open.


**Stage 7.3b implemented locally, mock review pending (2026-11-16, manifest 2.5.170; fixtures/mocks only; no HA/provider/charger/deploy/commit).** Four tracks under the shared price chart, one tiling of the chart horizon each so no moment is ever blank: `shared-dashboard/chart-tracks.js` (pure `buildTracks`, `tile`; higher layer wins, two different spans in one layer become unknown). **Proposal** = the current `windows` only (null when the plan is stale/absent → unknown; past time hatched; `minimum-exception` and reserve minutes marked when already labelled). **Sent** = `history.tracks.sent` (backend `planned_blocks` with each span's own version id; `unknown_plan_spans` and anything after `intent_uncertain_after` unknown; digest-only days draw `sent-summary`; everything outside the loaded day is `unloaded`, i.e. unknown). **Effective** = `sidebar/effective-track.js` from the existing Morek status: only a fresh status read AND a fresh `effective.fetched_at` with coverage still running; remaining period only, clipped to now, label is the reported value+unit (A), never kW; `differs` only when the verification belongs to that readback (`limits_or_transitions_differ`); history never supplies it. **Measured** = backend flow intervals (`first_sample`–`last_sample`, open edges marked), `outside_plan` / `plan_unknown` / `no_plan_evidence` spans from the backend, no-flow only from a `no_flow_observed` block verdict or when coverage says the whole window was measured and trusted, gaps and the pre-oldest-power part unknown (a gap row without `to` is one 60 s tick), nothing after now (`future`), earlier flow marked stale when the refresh failed, no detailed flow for plan-only/digest-only/empty days. The numeric spans come from `historyTracks` in `history-day.js` (absolute ms from the raw answer, clipped to the loaded day window; no display strings parsed). The renderer is DOM lanes in `charts.js` (`data-track-lanes`, reconcile skips them like the chart) positioned with the chart's own `convertToPixel`, so zoom/pan/resize/`finished` keep them aligned; no series, grid or y axis was touched (asserted). `format.toAxis` converts ms to axis units (live: identity; preview: sample hours), the preview has a fictional `effectiveTrack`. Palette is its own (blue/violet/cyan, magenta outline = outside plan or reported difference), hatch = unknown. Not linked: the price day selector and the history day selector stay independent (no request on price navigation; alignment is by instant only, the lane note states the loaded history day and zone). Tests: `frontend/test/chart-tracks.test.ts` (27 cases) plus the neighbouring chart/history/price files (110 vitest cases), `tsc`, `npm run build`, `check-dist`, `prototype:build`. **Not run:** full vitest/pytest, browser/Playwright (real canvas/DOM layout, touch, mobile and dark visuals unverified), anything live; English literals, no i18n keys. No backend change. Stage 7 stays open (7.4a next).
**7.3b review correction (2026-11-16, still manifest 2.5.170, review pending):** (1) proposal spans are clamped to start at now, so a window straddling now no longer paints its past; (2) the whole-day quiet fallback needs zero backend intervals, outside-plan rows and isolated samples plus coverage that fills the whole window (trusted_seconds >= window_seconds), so observed flow is no longer overlaid by no-flow into a conflict; (3) effective-track fails closed (unknown) on any malformed, duplicate, out-of-order, negative or out-of-schedule period instead of stretching the last valid limit, and spans are clamped to the schedule and now. Tests added to chart-tracks.test.ts; Stage 7 is not done.

**Stage 7.4a implemented locally, mock review pending (2026-11-16, manifest 2.5.171; no HA/provider/charger/deploy/commit).** Backend only. **Source inventory:** `PriceRepository.day_snapshot` (memory) per display day in the price area's zone; the actual basis is each held day's `PriceDocument.pieces()` intervals (`eur_per_kwh` x `planning.planner.document_rate` for the area currency = raw spot, major unit/kWh), their real resolution (15/60 min, 23/25 h days), `DaySnapshot.state` and provenance (provider labels). `price_history.py` is only the backfill (28-day window, a year only for ENTSO-E; Nord Pool about two months), so a 30-day baseline is often below 30 held days; `price_profile.py` holds weekday-hour medians in EUR (not actual prices, unusable as a baseline); `market_observation.py` is a subscription. `planner.cheapest_slots` selects non-contiguous charging slots with period caps, so it is **not** reused. New: `pricing/price_insights.py` (pure: `clean_rows`, `build_baseline`/`Baseline.percentile`, `live_timeline`, `cheapest_window` + `_best_in_run`, `live_insights`; exact `Fraction` integral over the candidate starts = interval start/end, boundary minus length, run edges; ties earliest) and `api/price_insights.py` (`spotnav/get_price_insights`, mode `live`, registered in `__init__.py`; `docs/api.md` "Live price insights" has the wire contract). Rules: trailing 30 completed days, >= 7 fully held days or `baseline_too_short`; exclusions counted by reason (`not_held`, `partial`, `invalid_prices`, `conflicting_duplicate`, `overlap`, `no_price_rate`); duration-weighted percentile (strictly cheaper + half equal), no rank field, no cheap/expensive label; the baseline never blocks the window; only `ready`/`incomplete` live days are trusted (a `stale` current day gives current unknown `day_stale`; a past day is not stale for age); the window mean is compared with the baseline's *interval* prices (stated in `assumptions`). Prices are quantised to 9 decimals only for equality. Tests: `tests/test_stage_74a_price_insights.py` (34: 14 pure and 20 through the registered handler with a real repository, hass-free, every fetch/persist path patched to fail): `python tools/run_isolated_logs_tests.py tests/test_stage_74a_price_insights.py` (1.6 s). Also green: `test_stage_71_price_days.py` (23), ruff on touched Python, `npm run build` and `check-dist` at 2.5.171. **Not run:** full pytest/vitest, HA-fixture suite, browser, anything live. Limits: no UI (7.5); at most 32 `day_snapshot` calls per request (no cache); no `rank` field; monthly statistics are 7.4b. Stage 7 continues with 7.4b.
**Stage 7.4b implemented locally, mock review pending (2026-11-16, manifest 2.5.172; no HA/provider/charger/deploy/commit).** Backend only; mode `monthly` of the same `spotnav/get_price_insights` command (API v1, no new command/store, live wire unchanged). **Method:** `pricing/price_insights.monthly_insights` (pure, reuses `_full_day`/`clean_rows`) + `api/price_insights.monthly_answer`. `month` = strict `YYYY-MM` (absent = current month; non-string/other shapes, a `month` in live mode and `duration_minutes` in monthly mode are `spotnav_invalid_insight_request`; future and months whose first day is older than `HISTORY_KEEP_DAYS` are refused, bound inclusive), in the price area's zone, one `day_snapshot` per day (`_day_input` now accepts a snapshot, so provenance reuses it; <= 31 days). Past month = all calendar days, exact elapsed seconds (23/25 h); current month = completed days only (today/future excluded, `scope` `completed_days_to_date`, `calendar_complete` false, `as_of_day`; first day of the month -> `no_completed_days`, `valid_ratio` null). Complete day = 7.4a rule; `days_partial` and `coverage.seconds_partial` are reported apart and never enter the population; exclusion reasons counted incl. `no_price_rate` (no conversion guess). >= 7 complete days or `statistics: null` + `too_few_complete_days` with coverage. Statistics are duration-weighted (mean, min, max, p10/p50/p90 = lower weighted quantile `weighted_quantile`, `negative_share` = time strictly < 0, percent) with no re-binning. `comparable` = {meets_minimum, minimum_days, days_complete}; with `currency`/`basis`/`scope` on each answer, 7.5 decides month-to-month comparability (no second month read here, no forecast, no bands/classification, no hour-of-day profile, no cost). `docs/api.md` "Monthly price statistics". **Tests:** `tests/test_stage_74b_monthly_insights.py` (43: 9 pure, 34 through the registered handler with a real repository, every fetch/persist path patched to fail; partial month 6 vs 7 days, current month/today excluded, month-start zero-expected, Stockholm Mar/Oct and Riga DST, mixed 15/60 min, partial/conflict/duplicate/gap days, negative share, quantile edges, missing FX, invalid/future/out-of-retention months with the inclusive bound, one registration, live unaffected). `python tools/run_isolated_logs_tests.py tests/test_stage_74b_monthly_insights.py tests/test_stage_74a_price_insights.py tests/test_stage_71_price_days.py`: 100 passed in about 2.4 s (the 74a test that used mode `monthly` as an invalid example now uses `yearly`); ruff clean on touched Python (ruff format was not applied: the 7.4a files were already not format-clean); `npm run build` + `check-dist` at 2.5.172. **Not run:** full pytest/vitest, HA-fixture suite, browser, anything live. Limits: no UI (7.5 next); the whole month must lie within the 400-day bound (an older month is refused, not partially answered); a month is only as complete as the repository holds it (typically ~28 days back, a year on ENTSO-E), so an older/unfilled month is usually `unknown` with its coverage.

**Stage 7/8 roadmap refinement, coordinator reviewed (2026-11-16):** audited against source 2.5.166; no implementation in this change. Retained detailed evidence is about three days at full minute cadence, not a guaranteed seven; backend truncation/retention signals are assigned to 7.3a. Stage 18 absolute bands/dark/mobile rules are binding. Monthly methods are split into 7.4a/7.4b and dependencies corrected. The user settled D1 as spot-only default costs and D2 as day-average spot savings; both gates are removed. Stage 8 must allocate calendar-day energy/cost from placed intervals (session-start-day buckets keep their existing meaning), never price unplaced late energy, and use the same priced kWh for savings. Existing configured-fiscal totals remain separate/compatible; no historical tariff engine is required for spot-only display. No retention extension; no remaining product-choice blocker. Next task 7.1; all feature checkboxes stay open. Docs-only checks: diff/link consistency, no build or tests required.


**Stage 18 complete locally (2.5.166):** four substages implemented by separate Claude medium delegates, coordinator-reviewed and committed/pushed in order: dark UI, Charge Now/mobile layout, sole-car identification default, absolute price bands. No deployment. Visual checks covered shared mobile preview only; dark/Charge Now host/debug and chart appearance remain unverified in a browser. Stage 7/8 remain future features.

**2026-11-16 — Stage 7/8 audit and readiness pass (docs only; source reading at manifest 2.5.166, HEAD `f0bb93a3`; no code, version, test, HA access, deployment, commit or push; coordinator review and the user's D1/D2 answers pending).** Rewrote Stage 7/8 in `docs/charging-dashboard-roadmap-active.md` from current source instead of the 2.5.128 claims. Findings that change the plan: (1) the chart feed carries today/tomorrow only (`_held_documents`); past days exist only in `PriceRepository` (≤ 400 files, in practice ≈ 28 days plus a year only from range providers), so 7.1 gets one small read command `spotnav/get_price_days` and bounded 8-day pages, never a 400-day load; (2) `get_charging_history` truncates eight lists at 200 rows with only `plans_truncated` as a signal and `retention.oldest_evidence` can predate pruned power rows, so 7.3a first adds additive `truncated`, `retention.oldest_by_kind` and `retention.digest_days`; (3) real raw retention is the 4320-row count cap (**3 days at the 60 s tick, not 7**), digests ≤ 62 days appear about a day after the day ends, sessions 730 days without placement; (4) sessions are bucketed by start day in `get_sessions` but by time overlap in history, so totals use the buckets and a midnight session is counted once; (5) cost is made at read time from stored kWh × raw spot slices and the *current* fiscal settings, only plan versions (≤ 7 days) and digests (62 days, fiscal only) keep an older tariff, so 8.2a's `plan_snapshot` basis is bounded and everything else is a labelled `current_settings` estimate (existing basis names `current_settings`/`stored` kept); (6) the session record has no plug-in time, which D2's second option would need; (7) `price_history.py` is the backfill, the 28-day profile is `price_profile.py`. Queue re-cut: 7.4 → 7.4a (live methods + one `spotnav/get_price_insights` command) / 7.4b (monthly mode); 7.5 needs both; 8.1 needs 7.1 and 7.3b; 8.2b needs 8.1; 8.3b needs 8.2b, 8.3a, 7.5; 31 items, 8 of them ready now. **8.2a (D1) and 8.3a (D2) are gated and unanswered; D3 preserves current retention and is not a blocker.** Stage 18.4 absolute bands, the Stage 15.8 unplaced-energy rule and the Stage 17 `progress_unknown` rule are written into the Stage 7/8 binding constraints; relative insights never recolour or reclassify the chart. Nothing is implemented or marked done.

**2026-11-16 — Stage 18.3 sole-car default (manifest 2.5.165; local mocked; coordinator review pending; no HA access, charger command, deployment, commit or push).** **Root cause:** the planner, authorization, card and Morek readiness already resolve the car through `resolve_target_vehicle` (vehicles/vehicle_discovery.py), which returns the sole eligible car for an unset/stale stored id. The repeated "Which car is plugged in? <car> / Guest car" question came from `VehicleIdentifier` (vehicles/identification.py): a one-car charger still asked once its car was "ruled out" by its own entities (a cloud plug sensor saying "not plugged" or a position away, an identification elsewhere) or by the camera's "none of these" - exactly the stale reports a cloud car gives. **Fix:** a one-car charger is now decided in `_begin` like the zero-car case (`SKIPPED_ONLY_CANDIDATE`, method `only_candidate`, no session, no `_refresh` of the car, no state subscriptions/timers, no camera query, no notification, no settings write; `claims()` stays true). The old `single`/`ruled_out`/`_evaluate_single` paths were removed. **Priority at a plug-in:** identification off -> manual; zero cars -> only_candidate/unknown; a person's recent choice (<= `RECENT_CHOICE_S`) -> manual; exactly one eligible car -> that car; two or more -> existing guarded evidence/camera/question. Resolver order is unchanged: explicit guest -> no vehicle; stored id still among the charger's eligible cars -> it; else exactly one eligible car -> it; else unknown. A guest car stays a person's choice (`async_answer(GUEST)` still works at a one-car charger from the card/app); removed/stale stored ids never resurrect a car. SOC source freshness, report-time provenance, identity/generation checks and Pause/Stop/ownership guards are untouched (the sole-car fallback names the vehicle only; a reading stamped for another vehicle is still refused in `live_vehicle_facts`). User docs (`docs/vehicle-identification.md`, `docs/api.md`) corrected. **Tests:** new `tests/test_stage_183_sole_car_default.py` (9, ~1.6 s; real resolver and real `VehicleIdentifier` on a fake hass; verified failing on the old code): one/zero/two cars, stale and removed stored ids, explicit guest, configured explicit choice, restart trigger, ruled-out evidence with `automatic` and `ask`, no re-read, only history stored, two cars still ask. `test_camera_rule` 24 passed. `tests/test_guest_car.py` one-car cases (4 tests) were rewritten to the new rule but need the HA pytest plugin and **cannot run on this Windows machine** (unverified). Ruff clean on touched files; `npm run build` and `check-dist` pass at 2.5.165 (frontend unchanged). **Unrun:** HA-fixture identification/guest suites, frontend suites, browser, anything live. Not verified on the user's installation.

**2026-11-16 — Stage 16 missing-tomorrow audit after the 12 intervening commits (manifest 2.5.162, HEAD `e31463df`; tests only, no production, version or card change; no HA access, charger command or deployment; coordinator reviewed).** Question: does an uncapped daily ready-by already passed today, rolled to tomorrow 08:00 with NordPool tomorrow unpublished and today valid, plan the cheapest known full or partial charge today? **Yes — already implemented and committed:** 16.1 `9100d227` (published-only planning: `published_first`, partial portion, part-elapsed current interval, reserve on priced rows, history wait only when it clearly favours unpublished hours, flat/absent/inconclusive history never vetoes; capped/non-Morek unchanged), 16.2 `08254d2e` (one `AutoPlannerController.morek_price_blocker` for automatic and manual admission across `ready`/`waiting_for_tomorrow`/`degraded`; tomorrow not `ready`+`listed` is ignored, stale/gapped/unlisted/non-finite used data still blocks; partial indicator), 17.1 `d9ec44cc` (unknown progress plans from the reading, `progress_unknown`; the old blanket `target_progress_uncertain` refusal is retired and was not restored), 17.2–17.6 and 17.5's per-day FX rule. The older preserved draft (`stash@{0}`, helper `_price_state_admits`/`_periods_covered`, `test_stage_162_degraded_admission.py`) is superseded: its admission matrix, coverage-hole, changed-evidence and manual-parity cases are covered by `tests/test_stage_162_safe_dispatch.py` (the stricter ready/provenance behaviour of the old draft was not required and not ported); the stash is left intact. **Two coverage gaps were found and closed with tests only (no real defect surfaced):** `tests/test_stage_162_safe_dispatch.py::test_tomorrow_publishing_during_a_healthy_active_window_never_opens_a_gap_in_it` (2 cases; real controller/planner/guarded worker: today-only plan sent once, time moves into the sent window with fresh `charging` evidence, tomorrow publishes slightly cheaper or much cheaper; the active window stays first on the wire at 16 A from offset 0 and `continuity.preserved` is true, one resend, identical publication/SOC sends nothing) and `tests/test_stage_161_published_only.py::test_measured_register_energy_with_a_delayed_soc_shrinks_the_published_plan_once` (a partial published plan whose SOC reading is delayed subtracts the metered session energy exactly once; a fresh reading rebases without rebuying). Fast checks run one file at a time (manual harness, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`): `test_stage_162_safe_dispatch` 27, `test_stage_161_published_only` 13, `test_stage_144_interruption_policy` 50, `test_stage_145_progress_recovery` 32, `test_stage_175_fx_freshness` 6, `test_stage_176_blockers_recovery` 19 passed; `test_stage_141_current_interval` 2 failed/7 passed on the zone-prewarm harness limit (“'Europe/Stockholm' is not a known timezone”, unmodified file, unrelated to this audit). Unrun: frontend suites, the HA-fixture suite, anything live. Root review ran the two Stage 16 files together: 40 passed in 27.30 s; touched-test ruff passed. Build and check-dist passed after resolving the Windows line-ending issue described below. Source-only: installed behaviour and physical charging are unverified.

**Build reproducibility correction (2026-11-16):** the initial check-dist failure was exactly 2,551 CRLF bytes in the Windows checkout of the generated card, not stale source. Rebuilding produced the identical Git content and passed check-dist; no integration/card content changed, so manifest stays 2.5.162. A targeted `.gitattributes` rule pins generated `custom_components/spotnav/www/**` to LF to keep fresh Windows checkouts byte-identical to build output. The older superseded draft remains preserved in its named stash; do not apply it over current source.

**Stage 16 authorized (2026-11-14):** close the uncapped Morek partial-price-horizon gap without
reimplementing Stage 15. Missing tomorrow alone must not veto a full or partial cheapest-known plan;
keep the real ready-by, existing history comparison, caps, progress, reserve and Stage 14 stability.
The active roadmap defines 16.1 planning and 16.2 guarded price admission/UI, ahead of later feature
work. Each gets a fresh Claude Sonnet 5.5 medium delegate, focused fast checks, coordinator review and
commit/push. No HA operations or deployment are authorized by this implementation stage.

**Stage 13.3 practical plan and charger parameters implemented locally (2.5.161, 2026-11-15; committed `416529c3`; see the entry at the end).** **Stage 13.2 (2.5.159) is committed (`7e352562`):** market and charging-cost settings in the sidebar. **Stage 13.1 (2.5.158) is committed (`d81c3fd8`):** an advanced “vehicle sources & properties” section in the shared sidebar UI (see the entry at the end; 2.5.157 adds a read-only vehicle-properties block, a server-side expected-selection guard and a replan on a real selection change). Stages 16 and 17.1–17.6 are committed and pushed (HEAD `35f5ae5f` at the start of 13.1). Mocked checks only; not installed, deployed or live-verified.

**Stage 15 implementation complete locally (2.5.143, 2026-11-14):** all 15 implementation substages were delegated separately, coordinator-reviewed and committed/pushed in sequence. Focused mocked checks and required builds passed; detailed entries retain harness failures and unrun checks. No deployment, live charger commands or physical validation were performed. Next feature work is Stage 13, then 7 and 8 when requested; E1/E2 and user-owned 5.1/5.8 remain. Late unbound meter rises remain unassigned, and learning falls back to defaults when proof is missing.

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

### 2026-11-16 — Stage 18.2 Charge Now layout and full-width mobile cards (2.5.164; local mocked; review pending; no HA/charger action)

- **Charge Now:** `#charge-controls` is now one card (grid): collapsible `#charge-options` (flat, no second box) holding a wrapping `.cn-fields` row
  (duration, custom end, replace button), then `.cn-actions` with the main `#charge-now` button, then status/notice text. All ids, handlers, confirmations,
  permission/stale/unknown logic untouched (markup order only; no nested form). Host-bar inline Charge Now CSS moved to shared `dark.css`.
- **`#charge-session>*`/`#schedule-check>*` generic boxes removed** (they boxed the title/detail children of sections that panel.js already styles inline).
- **Mobile (<=800px, dark.css):** `.shell` side padding 0 (masthead keeps 16px), `.panel`/alert/Charge Now card/log viewer lose side borders and radius, host-bar Charge Now card
  cancels the bar's 16px padding, dialog width 100vw-16px. Internal padding, vertical gaps and safe-area handling kept; desktop `.shell` max-width/padding unchanged.
- **Tests:** new `test/charge-now-layout.test.ts` (5 structural: ids/no form/single button, wrapping card CSS, no hard-coded host styles, mobile gutter rules, desktop width kept);
  with `dark-theme.test.ts` and `charge-now.test.ts` 28 pass. `npm run build`, `check-dist` pass.
- **Visual:** local preview (shared dashboard, iframes 320/375/430): every `.panel` spans left 0 to content width, no horizontal overflow. The sidebar host bar
  Charge Now card and the log viewer could **not** be visually inspected (sidebar browser fixture server would not start), so those pixels are unverified. No full suite, Playwright or HA.

### 2026-11-16 — Stage 18.4 absolute price bands and stable chart scale (2.5.166; local mocked; review pending; no HA/charger action)

- **Change:** new `shared-dashboard/price-bands.js` (one source for cutoffs, colours, axis extent). EUR c/kWh: `<8` Cheap green, `8–<15` Normal yellow, `15–25` Medium
  orange (exactly 25 orange), `>25` Expensive red; negatives green. `shared-dashboard/charts.js` (shared by live sidebar and preview) now draws the stepped area from
  the existing custom series (translucent fill to 0 + solid top edge + vertical joint, each coloured by that interval's own price; no visualMap/gradient, so exact
  boundaries are exact) and removed the separate line series. Y axis is numeric from the whole horizon (and soft cap), not the zoom: min `min(0, floor10(low))`,
  max `max(30, ceil10(high))`, interval 10, so a 1–3 c day stays low and spikes/negatives are not clipped. Tooltip adds the band name. Legend (`dashboard.js`) lists the
  numeric ranges/unit and states display only, not a charging limit. Bar mode uses the same colours.
- **Other currencies:** classification applies only when the chart unit is exactly `c/kWh` (the existing `priceUnit`/`displayPrice` EUR conversion). SEK/NOK/unknown
  stay neutral blue with a zero-baseline whole-data axis and a legend saying no trusted conversion exists; nothing is converted or fetched. The preview's old
  `bands:[30,45,60]`, `labels.bands` and the live `bands:null` were removed; the preview sample is EUR so it classifies identically to live.
- **Unchanged:** price basis/provenance text, zoom/pan/pinch, snapping, gap/DST handling, proposal overlays, pins, soft-cap and Now lines, resize.
- **Tests:** `test/price-bands.test.ts` (7; drives the real `mountCharts` with echarts mocked: 8/15/25 boundaries, 1–3 c axis 0..30, negative/spike extent, refresh keeps extent, missing not zero, SEK neutral, cap in extent), `test/sidebar-price-chart.test.ts` (12 together), `dark-theme` + `bundle` (26 with the first two), `shared-dashboard/boundaries` + `prototype/sample` node tests (11), `tsc --noEmit`, `npm run build`, `npm run check-dist`.
- **Unrun / limits:** **no browser/visual inspection was done (visual result unverified)** — the look of the coloured stepped area, vertical joints, legend wrapping and dark theme is unchecked; echarts is mocked in tests. No full suites, Playwright, HA-fixture tests or installed behaviour. 18.1/18.2 visual limits above still apply. The vertical joint uses the newer interval's colour; the first visible interval at a zoom edge has no joint.

### 2026-11-16 — Stage 18.1 dark theme across owned UI (2.5.163; local mocked; review pending; no HA/charger action)

- **Cause:** in the sidebar shadow root the Web Awesome `.wa-dark` palette never matched (the class is on the host) and dark.css only restyled
  individual controls, so Charge Now details, plan `wa-input`/`wa-details`, native buttons/inputs, the Morek debug panel buttons and the log viewer fell
  back to light defaults.
- **Change:** `frontend/shared-dashboard/dark.css` (shared by sidebar, shared dashboard and preview) now sets dark WA surface/text/form/neutral tokens and a
  small own token set, `color-scheme:dark` native control defaults via zero-specificity `:where()` rules (button/input/select/textarea/option, disabled,
  readonly, placeholder, focus-visible), `wa-details`/`wa-input`/dialog parts, `pre/code`, Charge Now `#charge-options`, session/schedule notes and the
  `#log-viewer` (`.log-lines` etc.). `scripts/sidebar-bundle.mjs` rewrites `.wa-dark` to `:host(.wa-dark)` so the full WA dark palette reaches the shadow root.
  Existing more-specific rules (advanced sections, banners, warn/error borders, status colours) are untouched.
- **Covered surfaces:** live sidebar host bar/Charge Now/auto controls/banners, plan controls, vehicle/market-cost/plan-charger/notification advanced
  sections, Morek evidence + debug panel, log viewer, proposal dialog, shared dashboard and preview (same dark.css). No writes, permissions or action semantics changed.
- **Intentionally not changed:** the legacy Lovelace card (`card-styles.ts`/`visual-styles.ts`) uses Home Assistant theme variables; its light hex values are
  only fallbacks when no HA theme exists, so it follows HA's own theme. Charge Now geometry/mobile width (18.2), vehicle default (18.3), chart bands (18.4) untouched.
- **Tests:** `test/dark-theme.test.ts` (5: control states, WA parts/log viewer/Charge Now coverage, status colours kept, contrast ratios, bundle host scoping),
  `test/log-viewer.test.ts` + `test/bundle.test.ts` (28 together), `node --test shared-dashboard/boundaries.test.mjs`, `tsc --noEmit`, `npm run build`, `npm run check-dist`.
- **Unrun / limits:** no browser/visual inspection was done (**visual result unverified**), full suites, Playwright, HA-fixture tests, installed behaviour.
  `#charge-session>*`/`#schedule-check>*` get a generic dark box; expect pixel polish in 18.2.

### 2026-11-14 — Stage 15.10 Morek behind-plan check and power-learner feed (2.5.143; local mocked; **coordinator reviewed**; no live HA/charger action)

- **What changed.** The existing 60 s Morek capture tick (`AutoPlannerController._async_capture_tick`, Morek-owned and known plugged in only)
  now also calls `_async_morek_behind`: the existing `PlanWatch` and `PowerSampler` run against the **acknowledged active window**
  (`morek_schedule.behind_window`, pure and fail-closed: settled record, latest attempt is the accepted acknowledged one, no Pause
  intent, no live Charge Now, routine profile, fixed-time window) through one read-only seam (`__init__._morek_progress`: record,
  `spotnav_morek_sending`, `MorekLinkMonitor.status()`, `_live_measurements`, `measured_flow`). A confirmed behind (PlanWatch's own
  `BEHIND_KWH`/`CONFIRM_S`/`REPLAN_EVERY_S` backoff/window-end rule, no new threshold) makes **one** `async_recalculate()` with no cause (a
  strict `recalc` publication to the guarded worker, no price/cap trigger, active window continued, equal schedule deduplicated). No
  `_arm_watch`, no executor/legacy start or stop, no second sender.
- **Facts required (otherwise unknown, never behind):** acknowledged window; link `up` and the same `(connection_id, since)` as the previous
  tick; identified car equals the planned car's facts; fresh energy register reading; register time credible (`_register_time_credible`:
  newest retained row not flagged, received within `CAPTURE_REPLAY_S`, no recorded gap in `MAX_STEP_S`; no evidence store = not credible);
  measured flow `charging` (fresh power/current, never nominal amps, never SOC); not guest, not paused/person-Stop, not held by SpotNav,
  not tapering, car not ending, past `START_GRACE_S` of the window, window current equal to the planned current. A tick failing any of
  these hands PlanWatch a `None` reading (it re-bases on the next good one) and ends the power stretch.
- **Power learner.** Unchanged `PowerSampler`/`LearnedPowerStore`/trust rules (`TRUST_MINUTES`, `TRUST_SESSIONS`, bounds); the learned cap
  is bounded by the planned power so it can only **lengthen** time; no shortening and no new constant.
- **Stability.** `_frozen_learned_cap` holds the figure the accepted plan used (`_power_freeze`, key = subject, wiring, plug-in) while the
  acknowledged window is open, so routine SOC updates never see the power input (`_morek_input_evidence`, planner request,
  `vehicle_update_wait`) move, however many clean minutes are collected. The live figure applies when no window is open (next plug-in or
  planning decision), when the freeze key changes, and on a confirmed-behind replan (`_async_replan_morek_behind` drops the hold first).
  No explicit recalculation is made when a window ends; the next natural planning decision reads the live figure. Unplug, a foreign
  owner, a guest or the 15.11 reset (`async_reset_learning` clears the hold, the link key and the sampler) drop the Morek state
  (`_morek_behind_reset`, only if the Morek look ever ran, so legacy chargers keep their own watch and sampler).
- **Tests:** `tests/test_stage_1510_behind_power.py` (26: slow charge one bounded replan and PlanWatch backoff, healthy charge plus new
  samples nothing and the held figure, confirmed behind applies the live figure, 14 doubtful/held matrices yielding no replan and no
  sample, link gap/replay, current mismatch/grace, lengthen-only, reset, wrong owner, failing seam, `behind_window` and
  `_register_time_credible` units). Run with `python tools/run_isolated_logs_tests.py tests/test_stage_1510_behind_power.py`. Also passed,
  one file at a time: 159a (18), 159b (70), 1511 (20), `test_plan_watch` (34), 142 (22), 143 (22), 144 (50), 145_progress (13),
  `test_morek_worker`, `test_morek_schedule`. `npm run build`/`check-dist` current at 2.5.143 (no card change); ruff clean on touched files.
  `tests/test_learned_power.py`: its `hass`-fixture tests error here as before (HA plugin cannot load on Windows). Not run: 141/145_fresh/146,
  `test_morek_session*`, `test_stage_95_recovery`, `test_stage_103_partial`, full suites, browser.
- **Review correction (2.5.143, root review pending).** (1) End judgement: `PlanWatch._judge_end` still falls back to the last held reading after `END_WAIT_S` (legacy behaviour untouched). The Morek wrapper now builds one `proof` (not guest/paused/sending, known connected with a plug-in, unbroken link, planned car, fresh credible register reading) and passes the reading to the watch only under it, window or not; an ended window with no proof past `END_WAIT_S`, or from another plug-in, is dropped unjudged (`PlanWatch.ended_end`/`discard_ended`, two new helpers, no change to `check`). A healthy end with fresh proof is judged by the existing rule. (2) Held figure: an absent window (pending/uncertain write, unknown or down link, unreachable record, Charge Now) no longer clears `_morek_window_end`/`_power_freeze`; they are kept until the known end passes, a person's Stop/paused executor/guest/known unplug/new plug-in, a reset or a confirmed behind (`_morek_session`; a momentarily unknown plug-in keeps the freeze key). Tests added in `test_stage_1510_behind_power.py` (36 total; end without proof x7, healthy end, unknown progress holds the cap, release rules); 159a (18) passed; `test_plan_watch` passes, `test_charge_behind_plan` has 4 `hass`-fixture errors as before. Limit: whether a Charge Now/Pause that leaves no window within the known end should release the figure is not distinguished (it is kept; harmless, same plug-in and wiring only). Unverified on hardware.
- **Final focused correction (2.5.143, root review pending).** `behind_window` was factored onto `_settled_profile`; new pure `behind_settled(record, now)` returns the acknowledged attempt id of a settled routine record (not uncertain, latest accepted attempt == ack id, routine, no Pause/live Charge Now) whether or not a window is open, and `_morek_progress` carries it as `settled`. The wrapper's `proof` (mid and end) now requires it, so an unknown record (uncertain, pending, Pause, Charge Now, unreadable seam) never lets a fresh register/live link judge an ended window or sample power; the ended judgement is dropped after `END_WAIT_S` and the freeze is preserved. A newer accepted intent (settled id differs from the watched window's `_morek_ack`) drops the old end unjudged. The previous plug-in is compared before the new window overwrites `_morek_session`; a positive change resets the Morek watch (`_morek_behind_reset`); an unknown plug-in is not a change. Legacy `PlanWatch` semantics untouched. Tests: 6 added to `test_stage_1510_behind_power.py` (31 total), run with the `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ... --noconftest` form with 159a: 60 passed in 2.6 s; ruff and `check-dist` clean; no build needed (no card change). No HA, commit, push or deploy.
- **Limits.** Whether the real controller's `held_by_spotnav` inputs (`setpoint_current_a`, `requested_current_a`, `car_ended_at`,
  `charge_progress`) are meaningful under Morek ownership is inferred, not proven: a stale value only makes the feature inert (fail
  closed). The link monitor's `since`/`connection_id` and OCPP `status` are unverified on hardware; a link drop shorter than the 30 s poll
  that keeps the same point object is not detectable. `plan.proposal.power_kw`/`need_met_at` are used only to lower the expectation
  (min). An infeasible target is reported by the existing planner (`short_of_deadline`), never promised by this code. No physical-charging
  proof; nothing installed or live-verified; no HA, charger, deploy, commit or push.

Coordinator review: end-of-window unknowns, settled-intent/plug-in binding and power-freeze corrections checked. Independent final focused tests: 89 passed in 2.68 s (15.10, PlanWatch, 14.5 progress). An additional 14.2/14.3/14.4 selection ran slowly and was stopped under the fast-only rule, so that final combined rerun is incomplete. Build and check-dist passed at 2.5.143. No live verification.

### 2026-11-14 — Stage 15.11 learned-estimate display and administrator reset (2.5.142; local mocked; **coordinator reviewed**; no live HA/charger action)

- **Display:** `plan.proposal.learning` (additive; absent without a learned-energy store or car, so older clients and the strict dashboard decoders are unaffected): `source` `default`/`learned`, `mode` `morek`/`legacy`, used/default kWh per percent, `valid_samples` (promoted votes that fit today's battery), `agreeing_samples` (within 10% of their median, so an outlier is valid but not agreeing), `needed_to_lengthen` 3 / `needed_to_shorten` 5 (legacy: 3/3), `clamped`, need kWh with and without the learned figure, `rejections` by reason and `effect_minutes`. The effect is computed in the backend (`(need − default need) ÷ plan power × 60`, whole minutes, positive = longer; 0 for the default; `null` when the level, target, battery or plan power is unknown). It does not model the minimum-SOC floor or the 15.1 time reserve (that stays separate), so it is "about". `shared-dashboard/learning-model.js` decodes strictly (malformed/absent → "unknown"); a stale observation states no effect. Rejection reasons are also in the diagnostics (`learned_energy.rejections`, now with `agreeing`/`valid`). The preview sample uses a fictional block through the same decoder. Reads never write (the existing `learned()` read-time revalidation is unchanged).
- **Reset:** `spotnav/morek_schedule` `reset_learning` (administrator checked before the charger lookup or any mutation; unknown/unloaded charger and missing planner refused). `AutoPlannerController.async_reset_learning` (one at a time) resets the samplers' register history/restart mark and calls `LearnedEnergyStore.async_reset` / `LearnedPowerStore.async_reset`: memory is cleared first (samples, captures, promotions, rejections, stretch starts, open plug-ins; no second store, no new controller), then the stored file is removed through the store's own `async_remove`; a failed removal queues the empty state to overwrite the file and is reported as `false`. Session history, profiles and outcomes are untouched; `PlanWatch` anchors are not learned data and are left alone. Replanning is the existing evidence round: `MorekScheduleWorker.note_learned_reset()` → one `async_recalculate("learned_reset")` → one `recalc` trigger and the usual compared reconcile (equal schedule sends nothing, active window protected, Pause/Stop/uncertainty guards unchanged); a charger without a worker gets one direct `async_recalculate`. Sidebar: "Reset learned estimates" button beside "Recalculate & sync schedule" (admin, fresh status, not busy/dirty/uncertain, confirmation); the notice reports done / partial / unconfirmed from the backend answer only.
- **Honest limits:** the reset mid-charge changes the figure at once (the 15.9b freeze applies to promotion, not to an explicit reset), so one compared reconcile may follow; a capture tick running during the reset can start a genuinely new stretch afterwards; the legacy power learner is cleared too although Morek does not feed it yet; the effect minutes are an estimate; an older backend shows "unknown"; strings are English copies in all nine language files (the existing sidebar practice); no browser run.
- **Tests:** `tests/test_stage_1511_learning_display_reset.py` (16: default/learned/outlier/shorten/clamp/fallback/missing fields, backend effect, reset clears store+file+samplers and survives a restart, pending stretch not resurrected, failed removal reported, power reset, sessions untouched, non-admin zero effects, one evidence round, no-worker replan, unknown charger/planner) and `frontend/shared-dashboard/learning-model.test.mjs` (4) pass; 159a (18) and 159b (70) rerun pass; ruff, `npm run build`, `check-dist`, `tsc --noEmit` clean at 2.5.142; i18n parity and reserve-display vitest files pass. Not run: other Stage 14 ◆ files, full suites, browser. `tests/test_dashboard_api.py` and `frontend/test/contract-fixtures.test.ts` were not run (no key was added to the dashboard top level or the strict `soc` block). No HA, charger, deploy, commit or push.
- **Review correction (2.5.142, local mocked):** the displayed need/default and `effect_minutes` now use the planner's own policy: with a soft price cap `AutoPlannerController.learning_estimate(capped=, minimum_percent=)` calls `capped_vehicle_energy` (so minimum==target shows 0 effect; near-floor effect is bounded; unknown level/policy stays `null`); a manual energy driver (`manual=True`) reports `applies:false`, no needs, effect 0 (learned figure not used). Panel: the `reset_learning` response is guarded (connection, generation, permission epoch, admin, charger) **before** `learningNotice` is written, the failure notice is permission-guarded, and `stopObservations` (charger change/disconnect) clears the notice. The backend reset that already ran is not undone or retried. Tests: +4 in `test_stage_1511_learning_display_reset.py` (41 passed with `test_capped_vehicle_energy.py`), new `frontend/test/sidebar-learning-reset.test.ts` (7, real panel, mocked WS). Build, check-dist, tsc, ruff pass. No broad suites, HA or charger action.

Coordinator review: minimum-floor display and charger/permission-bound reset notices corrected. Independent fast runs: 41 backend cases passed (1.92 s), 7 real-panel reset cases passed (5.25 s). No live verification.

### 2026-11-14 — Stage 15.9b capture promotion, quality rules, asymmetric trust and clamp (2.5.141; local mocked; **coordinator reviewed**; no live HA/charger action)

- **What landed:** captures now influence a plan only after promotion. `LearnedEnergyStore.evaluate()` revalidates every capture of an *ended* plug-in with `metadata_reason` (recorded provenance) and then the store's `checker`, which the production `AutoPlannerController` installs as `_prove_capture` (retained session and evidence records now; the capture-time `late_energy` snapshot is never proof, only an `unplaced`/`uncertain` snapshot is an extra rejection). Proven ids are persisted per car (`promoted`; also `rejected` reasons and `rejection_counts`, read as untrusted). The figure comes from `_promoted_learned`; no new store, ML, temperature bucket, per-sample step limit or UI.
- **Rules (constants in `learned_energy.py`):** rise ≥ 15 points, end ≤ 90%, vehicle-timestamp SOC basis only, positive consistent energy that `fits` the battery, same register entity/phases/voltage (±5 V)/capacity (±0.05 kWh) as the capture, no gap/restart/held/paused/unposted look and ≥ 2 looks, no `late_energy` unplaced/uncertain; the proof needs every overlapping session to exist, belong to this car, be `consistent` with no unplaced energy and (first promotion only) closed and `final`, plus (first promotion only) evidence rows with no gap/`link_down`/capture restart/replayed-or-flagged register row inside the stretch, rows not older than 3 days. Votes: one per plug-in, newest 9 ended, ≤ 120 days. Trust: ≥ 3 agreeing within 10% of the median; a figure below the default (`capacity ÷ efficiency ÷ 100`) needs ≥ 5; clamp −10%/+25% of the default (the `fits` bounds already keep a figure within about 0.9–1.29× default, so the clamp is a second guard). Applied through the existing `with_learned`/`target_need`, so it precedes the 15.1 time reserve. `capped_vehicle_energy` now takes the larger of the learned and default minimum-SOC wall energy, so a shortening figure cannot weaken the minimum-SOC need (also true for legacy shortening).
- **Timing:** promotion runs when the capture plug-in ends (`set_capture_open` change, or `_arm_capture` seeing an affirmative unplug, which also covers a restart with no tick left). While that car's plug-in is open nothing is re-evaluated, so the figure, `_morek_input_evidence`, replans and sends do not change mid-charge (the rejection/promoted diagnostics are `compare=False`). A later conflicting record revokes at the next planning read with the plug-in closed; a stored promotion is believed only after this process proves it again (first read after restart), failing closed to the default. A change at a plug-in's end is one input-evidence difference (one compared reconcile; equal schedule sends nothing).
- **Combination with legacy samples (review fix):** Morek schedule-owned planning reads only currently validated promoted captures or the default (`LearnedEnergyStore.learned(..., morek=True)`); the legacy samples are never read for it, so 3 legacy shortening samples + 4 promoted shortening = default until 5 promoted agree, and missing proof = default. Non-Morek (Auto) learning keeps the legacy samples under their old constants (10 points, last 5, no clamp) and ignores captures. The use mode is chosen by `AutoPlannerController._morek_learning()` from the last `_morek_owned()` answer (the plan calculation asks before it reads a figure; a charger with ownership wired but never asked is treated as Morek, i.e. default, not legacy), never by whether captures exist; it is in `_morek_input_evidence` and reaches the dashboard/estimate readers through `learned_energy()`. Limit: a synchronous reader between an ownership change and the next plan calculation sees the previous answer.
- **Review fixes also:** `capped_vehicle_energy` raises the requested target need to at least the protected minimum need (the minimum is never clipped down to a shortened target), so equal minimum/target (e.g. 80/80 at SOC 50/79) and near-target minimums stay a valid `PlanRequest`; default and lengthening results are unchanged. `_prove_capture` (first promotion) now needs rows of the capture's own register entity reaching both ends of the stretch (within the recorder's `MAX_POWER_GAP_S`) with no hole longer than that, gap rows are matched over their whole `r`..`r2` span, and a lone row is `evidence_gap`. Flags the recorder never kept are unknown, not clean.
- **Honest limits:** (1) unknown evidence (no session store, no evidence rows, no checker, an exception) rejects and keeps the default; at startup, if the session store is not yet available, promotions are revoked and re-proven at the next safe read (an extra replan is possible). (2) Pending 15.8 records (`late_pending`) delay promotion until final (~6 h) and are counted once. (3) Evidence rows older than 3 days make a first promotion impossible (`evidence_expired`). (4) `not_charging` looks are not a rejection (scheduled off periods are normal); safety-stop/protection signals are still not recorded. (5) Replay detection is the evidence row's receipt-vs-observed lag (> 180 s) or its `q` flags, a heuristic. (6) None of this is proven on the installed charger; the checks use fakes.
- **Tests:** `tests/test_stage_159b_promotion.py` (4 vs 5 agreeing, clamps, outlier, one vote per plug-in/age/last 9/duplicate ids, malformed store records, metadata/rule matrix, unknown-late and missing-proof rejection, future/estimated SOC, capacity/vehicle change, restart and late-bad revocation, post-end promotion with an active plug-in frozen, `_prove_capture` session/evidence/wiring matrix, end-to-end through the capture tick and unplug, minimum-SOC floor). Review-fix rerun (one file at a time): 159b (70, incl. equal/near-target minimum, Morek-vs-legacy and evidence-coverage cases), 159a (18), `test_capped_vehicle_energy` (21), 145_progress (13), 158 (20) passed; ruff, `npm run build` and `check-dist` clean at 2.5.141; the other files below were not re-run after the fix. Run with `python tools/run_isolated_logs_tests.py <file>` (one file at a time). Passed: 159b, 159a, 145_progress, 158 (107 together); Stage 14 ◆ files 141/142/143/144/145_fresh/146, `test_morek_worker` (142), `test_morek_schedule` (106), `test_stage_95_recovery`, `test_stage_103_partial`, `test_capped_vehicle_energy`. Failing before and after this change (unchanged counts, verified by stash): `test_morek_session.py` (6), `test_morek_session_activation.py` (1), `test_capped_auto_execution_isolated.py` (1). `tests/test_learned_energy.py`: 18 non-`hass` tests pass, the `hass`-fixture ones cannot run here. Not run: full suites, browser. `npm run build`/`check-dist` current at 2.5.141 (no card change); ruff clean. No HA, charger, deploy, commit or push. Note: `tools/run_isolated_planning_tests.py` ignores file arguments and runs the whole list; it was started by mistake for a few seconds and stopped by timeout, no result used.

Coordinator review: minimum-equals-target validity, Morek-only trust/fallback and retained endpoint coverage corrected. Independent promotion/capped-energy tests: 91 passed in 2.36 s. No live verification.

### 2026-11-14 — Stage 15.9a capture-only energy learner on the Morek path (2.5.140; local mocked; **coordinator reviewed**; no live HA/charger action)

- **What landed:** a bounded 60 s tick on `AutoPlannerController` (`_arm_capture` → `_on_capture_due` (`@callback`) → `_async_capture_tick` → `_capture_energy`) feeds the **existing** `LearnedEnergyStore` through a second `EnergySampler` (`observe_capture`) and writes `Capture` records (`origin: morek_capture`, `CAPTURE_VERSION` 1) in a separate per-car `captures` list plus a separate `capture` stretch start (`capture_anchor`/`capture_open`). The legacy `observe`, `anchor`, `open`, `samples`, `learned()` and `_check_plan` path are unchanged. No new store, power learner, PlanWatch, UI, replan, resend or trigger. The tick arms only from `_publish` (every plug-in, ownership or settings change publishes) and only while the controller knows a car is connected; one appointment; re-armed only while Morek-owned; cancelled in `async_shutdown`.
- **Controller facts under Morek ownership (inspected, not live-proven):** `ChargingController` has no Morek logic and subscribes to the charger's entities unconditionally (`_async_progress_state_changed` → `_observe_connection`), so `known_connected`, `plugged_in_since`/`plugged_in_for_count`, `charging` and `energy_register_entity_id` keep updating under Morek ownership. The capture uses `plugged_in_for_count` only (not `plugged_in_at`, which is persisted and may belong to a car that left unseen); `plug_in_basis` is `watched` (`plugged_in_since`) or `found_connected` (after a restart/gap) and a change of it restarts the stretch. The Morek session coordinator's token and the evidence store's register rows are **not** used. Not proven: that an installed charger reports these facts the same way under Morek ownership (no hardware run); the tests use a fake controller.
- **Rules:** vehicle must equal the identified car (`resolved_vehicle_id`); non-estimated, fresh level; endpoint time is the car's own report time (`soc_report_at` with `vehicle_timestamp`), never arrival (a vehicle level stamped only `last_updated` makes no endpoint; the charger's own level is read live); register paired by the existing interpolation/held rule, with its basis recorded; register entity must be known. A change of car, source, capacity, register entity, phases, voltage or plug-in basis, a register decrease, a guest car or a non-Morek owner **discards** the stretch (no capture). Same bounds (`fits`) as legacy; out-of-bounds captures are dropped and counted (`captures_discarded`).
- **Provenance stored per capture (`meta`) for 15.9b:** soc source/basis/start/end and report times, register entity/start/end/basis, capacity, phases, voltage, plug-in basis, `late_energy` (`clean` only when every overlapping session is `consistent`; `unplaced`/`uncertain` as 15.8 says; otherwise `unknown` — an unevaluated or absent session, or an `uncertain` 15.8 record with `unplaced_late_kwh` `None`, is never clean), `quality` counters (looks, gaps, max gap s, restarts, not-charging, held, paused, unposted-register looks) and a recomputed `missing` list. Retention: 12 per car, 120 days. Reads are untrusted: wrong/absent `origin`, malformed `quality` or version drops the capture; a tagged record in the legacy `samples` list is dropped (legacy `EnergySample.from_stored` rejects any `origin` key); missing metadata is allowed but listed in `missing` for 15.9b to reject.
- **Planning ignores captures:** `learned()`, `_learned_energy_for`, `_morek_input_evidence` and `target_need` read only `samples`; asserted equal with 30 odd captures present. Not asserted byte-for-byte through a full `_compute_plan` run (only the learned figure and need the planner reads).
- **Known limits:** (1) `held`/`paused` come from `_held_by_spotnav`, the timed pause and a person's Stop; a safety-stop or protection signal beyond those is **not** recorded. (2) `late_energy` is a snapshot at capture time; 15.8 can still change a session later, so 15.9b must revalidate. (3) The restart counter marks the first look of a process that finds a stored stretch, not an OCPP/charger restart. (4) A capture needs ≥10 points of rise, as the legacy sampler. (5) The tick only runs while HA is up and a car is known connected.
- **Tests:** `tests/test_stage_159a_energy_capture.py` (18, production controller path with fake charging controller, real sampler/store, no `hass` fixture): capture with two measured levels and provenance, wrong owner (no sampler, stretch cleared, not re-armed, re-armed on publication), unplugged/unknown/no-store arms nothing, estimated/arrival-stamped levels, late cloud report by report time, guest/capacity/phases/vehicle/source discard, unidentified car, pause/hold/gap/not-charging counters, restart/unload (one appointment, no duplicate capture, late callback inert), error swallowed with no replan or PlanWatch, late-energy classification, load/migration of old files and round trip, fail-closed origin/quality/tagged samples, `missing` recomputation, retention, planner input identical with captures. Run with `python tools/run_isolated_logs_tests.py tests/test_stage_159a_energy_capture.py`. Also run: `test_stage_145_progress_recovery.py` (13) and `test_stage_158_late_reconciliation.py` (20) passed. `tests/test_learned_energy.py`: its 18 non-`hass` tests pass; its other tests error on `fixture 'hass' not found` (the HA pytest plugin cannot load on Windows here), so the existing learner integration tests are **not** re-verified. Not run: the other Stage 14 ◆ files, full suites, browser. `npm run build` and `check-dist` current at 2.5.140; ruff clean on touched files. No HA, charger, deploy, commit or push.

Coordinator review: capture-only storage isolation, metadata and timer lifecycle checked; independent capture/progress test run: 31 passed in 2.19 s. Captures cannot affect planning before 15.9b. No live verification.

### 2026-11-14 — Stage 15.8 late cumulative-register reconciliation (2.5.139; local mocked; coordinator reviewed; no live HA/charger action)

- **Seam:** the real `SessionRecorder` (production path, now given `evidence=lambda: evidence_for(hass)` in `__init__._async_start_session_recorder`) keeps a **register pair** on each register-measured session (`register_pair`: reading at open, last reading taken, entity, `broke` reason, `closed_at`) and, on every `evaluate`, runs `_reconcile_late` over the charger's newest finished sessions that are not yet `final`. New pure module `sessions/reconcile.py`; additive stored fields `register_pair` and `late_reconciliation` on `ChargeSession` (existing stores, no new storage; `SessionStore.set_late` replaces the session object like a migration; `late_pending`/`all_sessions` are reads). Invalid additive blocks are dropped on load, never the session.
- **Rule (corrected before commit):** the only accepted association proof is the recorder's own `register_pair`: open and close readings both taken by the recorder inside the session, from one entity, with no `broke` (reset/identity change). total = pair close − pair open versus placed = `session.energy_kwh` (unchanged; 14.5/cost/timeline untouched). States: `consistent` (|diff| ≤ 0.01), `reconciled` (pair total above placed → `unplaced_late_kwh`, `placement: unknown`, reasons `restart`/`gap`/`link_down` from evidence rows between start and close, else `unattributed`), `inconsistent` (`total_below_placed`), `skipped` (`register_reset`, `identity`, `source_not_register`), `unknown` (missing open/close, `ambiguous_association`; never zero), `uncertain` (`late_register_unassigned`: no total, no unplaced figure). **Late register samples are never proof:** an evidence row carries only entity, observed time and HA receipt time (no session, transaction or connector binding), so a settled counter, the 6 h window, a gap/restart/`link_down` or the absence of a next session row does not show the energy is this car's (it can be a buffered replay, another car, or a charge SpotNav never opened or dropped under `MIN_ENERGY_KWH`). A same-entity, unflagged rise above the recorder's close reading (received after the close, inside 6 h, more than 120 s before the next session's start, stopping at the first decrease) is exposed only as `unassigned_register_kwh` (observed register difference, certified for no session) and makes the record `uncertain`. Nothing unproven is stored as a total, so a record is recomputed (not frozen) while not `final`; `final` once 6 h passed or a later session exists. Idempotent across repeats, duplicates and restart (pair and record persist).
- **Overnight 20.9 case:** a register that reads 20.9 kWh above the open value after a recorded 0.103 kWh session **cannot be attributed automatically** with the APIs available (evidence rows have no transaction/connector/session id and the recorder had no reading while the energy flowed): history shows `uncertain`, `total_kwh: null`, `unassigned_register_kwh: 20.797`, `energy_kwh` 0.103 unchanged. Attributing it needs an affirmative per-charge source (e.g. an OCPP transaction id or meter value carried with the register sample), which does not exist in the evidence store; not built.
- **Exposure:** `get_charging_history` session rows gain `reconciliation` (`state`, `reason`, `placed_kwh`, `total_kwh`, `unplaced_late_kwh`, `placement`, `placement_reasons`, `final`, `quality`, open/close readings, `unassigned_register_kwh`, `provenance` with `when_delivered: unknown` and a not-certified note); older/unevaluated sessions read `unknown`, never zero. `ChargeSession.unplaced_late_kwh` is non-null only for a pair-proven `reconciled` record (an `uncertain` session yields `None`: a 15.9 learner must treat it as unknown, not as clean). Nothing is placed in the flow timeline, priced, or counted as power/progress; no send, replan or trigger; no OCPP traffic.
- **Material limits (not hidden by the mocks):** (1) The recorder pair covers only what the recorder read while the session was open; energy delivered while no reading was taken and after the close stays unassigned/uncertain. (2) Late evidence is receipt-timed and one row per 60 s capture tick; retained ~3–7 days. (3) A late rise after the 6 h window or after the next session started is not reported against the earlier session. (4) `link_down` appears only as a placement reason for in-session unplaced energy, from existing evidence gap rows (`g == "link_down"`). (5) Whether the installed charger/HA replays registers is unverified. (6) The evidence store lacks any session/transaction binding, so no late value can currently be certified.
- **Tests:** `tests/test_stage_158_late_reconciliation.py` (20: overnight 20.9 unassigned, unrecorded later car with no next row, gap/restart/link_down not proof, provisional total withdrawn on conflict, in-session pair remainder with reasons, idempotence/duplicates/restart, identity, in-session reset, decrease after close, next-session bound, window/quality, final not re-evaluated, unknown not zero, inconsistent, ambiguity, untrusted/older record loading, no worker/charger path) run with `python tools/run_isolated_logs_tests.py tests/test_stage_158_late_reconciliation.py`; `test_stage_63_history.py` (19) also passed after the correction; earlier passes of `test_stage_145_progress_recovery.py` (13) and `test_stage_62_evidence.py` (20) predate it and are not re-run. `npm run build` and `check-dist` current at 2.5.139; ruff clean on touched files. **Not run:** `tests/test_session_recorder.py` and other `hass`-fixture session files (the HA pytest plugin cannot load on Windows here; they fail on `fixture 'hass' not found` with or without this change), the other mandatory ◆ Stage 14 files, browser, full suites; so the substage is not called regression-verified. No HA, charger, deploy, commit or push.

Coordinator review: late energy attribution made conservative; receipt-time-only rises stay unassigned/uncertain rather than certified session totals. Independent reconciliation/progress check: 33 passed in 1.95 s. Original progress/cost inputs unchanged; no live verification.

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

### 2026-11-14 — Stage 16.1 published-only full and partial planning (2.5.144; local mocked; **coordinator reviewed**; no live HA/charger action)

- Seam: `AutoPlannerController._plan_departure_by_history` / `_daily_by_history` gain `published_first` (true only for an uncapped Morek schedule-owned plan, passed from `plan_request`). With it, missing future prices alone no longer force the implicit wait: the cheapest published placement (`known`) is installed as a provisional plan unless (a) `history_wait.evaluate` says `wait` (unpublished hours clearly cheaper by the existing rule, then the old guarded wait/`price_wait` behaviour), or (b) the implicit rule says `buy_now`/`guarantee` (new helper `_urgent_purchase`; keeps the old urgency and arms the same wake). No/flat/dearer/inconclusive history is no veto. `gap.short` (real deadline cannot be met) still takes the old best-effort unpriced path.
- Partial: new pure `planner.plan_published_portion(request, gap)` plans every published whole slot plus the published rest of the current interval (`calculate_plan` with `window_end=gap.missing_from`, `requested_kwh` = published capacity), then restores `requested_kwh` to the real remaining need. The real departure is untouched; `policy_shortfall_kwh = need - delivered` (existing line), no `short_of_deadline`, nothing unpublished is priced or zero-priced. `None` when no published time is usable (then the old wait stands).
- Reserve: `with_time_reserve` previously ran only when `wait_facts` was empty, so history facts skipped it. A private `_PUBLISHED_ONLY` marker (popped before the snapshot) now lets Morek published-only plans, including the dated-departure `known` returns, get the reserve; purchases before publication (`buy_now`/`guarantee`) still skip it. The reserve stays after the need and uses only published horizon rows, so baseline fields/cost/progress are unchanged and a partial plan that already uses every published slot has `no_eligible_time` reserve. The 14.5 measured-progress need (`_energy_for`) is untouched, so recalculations after SOC/publication shrink the need rather than re-buying.
- Not changed: capped planning, legacy/non-Morek wait policy, dedup/active-window logic, settings, stores, UI. A degraded aggregate price state still blocks dispatch until 16.2.
- Tests: new `tests/test_stage_161_published_only.py` (12, real controller/planner/history/price_wait; full vs cheaper-later, current interval, partial late plug-in, repeated recalculation, no published price, clear/flat/dearer history, non-Morek, urgency, reserve, deadline just past the published end). `test_stage_141_current_interval.py` first Stage 14.1 uncapped-wait test rewritten for the new behaviour (provisional plan). `test_stage_103_partial.py` fixture gets an `async_profile` stub (the real path now asks for history). Passed with the `--noconftest` recipe (plus a zone-prewarm plugin): 16.1 (12), 14.1 (9), 14.2 (22), 14.3 (22), 14.4 (50), 14.5 progress/fresh inputs (13+11), 14.6 evidence (15), 15.1a reserve (79 passed), capped vehicle energy (21), 10.3 partial (8 passed).
- Known/pre-existing failures (identical without the change): `test_stage_103_partial::test_uncapped_necessary_purchase_passes_real_morek_path` (worker reason `plan_inputs_changed`, harness) and `test_stage_151a_time_reserve::test_dashboard_exposes_baseline_and_allowance_separately`. Not run (need the HA `fcntl` plugin/fixtures): `test_daily_history`, `test_publication_time` HA-fixture cases, `test_auto_controller`. DST is not exercised at controller level (the portion uses absolute time through the existing planner). `ruff` clean on touched files; `npm run build` and `check-dist` current at 2.5.144 (no source change in the card; build regenerated `www/spotnav-card.js` and `www/sidebar/panel.js` for the version).
- Limits: source-only; no HA/charger/deployment. Whether the installed dispatch accepts the provisional plan waits for 16.2.
- Root review: added a synchronous fixture-zone resolution matching production pre-resolution (the first isolated async test otherwise hit the known cold-zone setup issue). The new 16.1 file and 14.5 progress file passed together: 25 tests in 2.25 s. Touched-file ruff and `check-dist` passed. Dated Morek departures use the same published-only rule; other chargers retain their existing policy. No broad tests or hardware operations.

### 2026-11-14 — Planning resilience: unknown measured progress plans from the reading (2.5.146; local mocked; no live HA/charger action)

- Symptom: live 2.5.144 showed `planning_unavailable` / `target_progress_uncertain` right after a reserve save. `vehicle_update_wait.measured_progress` flagged any measured session that began before a stale (>300 s) reading or the plug-in and reached past it, or any measured session for no car, as `uncertain`. A just-closed identified session has no final late reconciliation for up to six hours, so waiting for proof can hold the plan that long. A first attempt (2.5.145: tolerate only a *proven* total up to 0.25 kWh) did not solve this and was **removed** (no threshold, `_proven_total_kwh` or `ambiguous_kwh` remains).
- Behaviour now: `Progress` is `(kwh, unknown)`. `kwh` is unchanged: identified sessions of this car that began at or after the reading, counted once. `unknown` is set for energy that overlaps the reading and cannot be attributed (no car recorded, a straddling or open charge on a reading older than 300 s, or non-finite/negative energy). Sessions are disjoint, so subtracting `kwh` and ignoring the unknown part cannot double-count. `_progress_adjusted` no longer returns a hold: it returns `(need, minimum, unknown)` where need/minimum are reduced only by the known energy; known energy that covers the need still waits for the car's level (`waiting_for_vehicle_update`). `_EnergyResolution.progress_unknown` is stamped by `_compute_plan` onto every snapshot of the calculation (`AutoSnapshot.progress_unknown`, part of `meaningful_key`), exposed as `plan.proposal.projection.progress_unknown` and drawn by the sidebar adapter in the existing projection note (never as measured). `target_progress_uncertain` stays in the reason literal/maps only so older stored values validate; it is no longer produced.
- Honest limits: the unattributed energy is not estimated, so the need can be **overstated**. With a minimum SOC the cap exception is sized from the reading and is *not* reduced by unknown energy, so it can plan above-cap energy the car may already hold (identical to pre-14.5 behaviour, now flagged). The car's own limit (the user's agreed 80 % assumption) ends the charge; SpotNav does not guarantee it. A newer reading rebases (`unknown` clears); a session that finalises without a new reading does **not** itself trigger a replan (no session-store trigger exists for target plans), so the flag persists until the next replan trigger (reading, price, settings). Readings that are for no car, for another car, from the future or older than one already planned from still hold the plan (`target_soc_stale`, Stage 14.5); identity is never guessed.
- Upload admission: `morek_plan_blocker` evidence does not include sessions, so an unknown-progress plan is admitted, uploaded once through the same guarded worker path, and not re-sent when an equal plan is recalculated. Pause/Stop, connector identity, electrical protection and an uncertain dispatched outcome block it exactly as for any plan (tested with the real controller and worker). Nothing in dispatch/ownership code changed.
- Tests: `tests/test_stage_145_progress_recovery.py` (24 passed, isolated harness): pure matrix; real controller live-like just-closed unreconciled identified session (reserve 20 %, capped and uncapped: plans, unreduced need, `progress_unknown`, dashboard projection flag, later reading rebases, session before a newer reading is not ambiguous); known + unknown energy counted once; minimum-exception need not reduced by unknown and reduced once by known; active open session with an active window; identity/stale guards separate; real worker: admitted, uploaded once, no churn on equal replan or rebase, person Stop blocks, uncertain outcome blocks a changed plan. Also passed one file at a time: `test_morek_worker` 142 (1 skipped), `test_stage_145_fresh_inputs_recovery` 11, `test_stage_142_active_continuity` 22, `test_stage_143_recalculation_triggers` 22, `test_review_vehicle_update_wait` 2, `test_plan_car_ended_rules` 29, frontend `sidebar.test.ts` 90. `test_plan_details_isolated` fails identically without this change (fixture lacks `soc`). Ruff clean; `npm run build` / `check-dist` pass at 2.5.146. Unrun: full suites, browser, HA-fixture tests. Live behaviour unverified.

- Correction (2.5.146, review finding): `vehicle_update_wait.valid_energy_kwh` is now the single validity rule (real finite non-bool number, never negative). `measured_delivery_since` and `auto_controller._session_energy_since` count only valid positive energy (previously `+inf` passed `> 0`, so one corrupt post-reading session could give infinite known progress and a false `waiting_for_vehicle_update` or a zero need); `measured_progress` uses the same helper, so a matching invalid session is skipped in `kwh` and flags `unknown`, beside valid sessions that still count once. `decide_vehicle_update_wait` ignores invalid energy. Tests: `test_stage_145_progress_recovery.py` (inf/-inf/NaN/negative/bool/str/None, valid plus invalid, other car ignored, controller path never waits nor hides valid progress). Run isolated harness; no HA, charger, commit or push.

### 2026-11-14 — Stage 17 planned: planner resilience (docs only; no source change, no commit by the planner)

- Planning entry only; the active roadmap now holds Stage 17 (17.1–17.6) and the strict queue 17.1 → 16.2 → 17.2 → 17.3 → 17.4 → 17.5 → 17.6. Source basis: manifest 2.5.146, HEAD `d9ec44cc`, working tree clean before this edit.
- Correction of status: the 2.5.146 progress-uncertainty fallback is **committed and pushed** (`d9ec44cc`), not uncommitted; it is implemented with mocked checks and its coordinator review is pending (17.1). Stage 16.1 is done and reviewed (2.5.144); Stage 16.2 is pending and keeps its scope.
- Source facts found while planning (reading only, nothing executed): capped planning refuses any energy-derived SOC estimate (`capped_vehicle_energy`, `morek_plan_blocker` `vehicle_input_stale`) while the uncapped Morek path accepts one; `_morek_input_evidence` holds the running `soc_percent`, so a moving estimate would make pre-wire checks read `plan_inputs_changed` unless evidence uses the anchor identity (17.2); the capped path checks capacity before the learned-figure fallback that the uncapped path already has through `with_learned` (17.3); `AutoPlannerController._on_sessions_changed` ignores target plans, so a `progress_unknown` plan is not replanned on session finalization (17.4); `morek_schedule` evidence `inputs` carries `soc_estimated` but not `progress_unknown` (17.1 candidate); ECB tables are used up to 7 days before the day and retried with existing backoff, the planner refuses `missing_fx_rate` (17.5).
- Not run: any test, build or live check. No HA, charger or deployment action. Risks are listed in the roadmap Stage 17 entries (estimate trust constants, estimate-evidence churn, finalization may not change an unattributable straddle).

### 2026-11-14 — Stage 17.1 review and finish of the 2.5.146 progress-uncertainty fallback (2.5.147; local mocked; no live HA/charger action)

- Reviewed `d9ec44cc` against its handoff entry; no behaviour change to attribution, identity, admission, dispatch or Stage 14 thresholds. One confirmed gap fixed: `api/morek_schedule._planning_inputs` and `decision_event`'s `inputs` now carry `progress_unknown` (additive; a calculation failure still gives the plain `{plan_state: unknown, uncertain: true}` record), so a plan sent from an unknown-progress calculation is visible in decision/status evidence and is never presented as measured.
- Verified, no code change: (b) `progress_unknown` in `meaningful_key` only re-renders state listeners once on a flip (new tests: one delivery, no repeat, no recalculation; the existing worker test shows a flip with the same schedule uploads nothing; the notifier uses the plan fingerprint and publication listener, not the key); (c) no UI/banner/status text treats `target_progress_uncertain` as an active hold (legacy literal and decision-blocker map entry stay for old stored values); (d) pinned by test: with a soft cap and minimum SOC the above-cap exception never exceeds the minimum need worked out from the reading (documented limit: unattributed energy is not subtracted, so it can be overstated) nor the target need, and the plan is flagged.
- Tests: `test_stage_145_progress_recovery.py` 32 passed (3 new), isolated harness (`python tools/run_isolated_logs_tests.py <file>`, one at a time). Also passed: `test_morek_worker` 142 (1 skipped), `test_morek_schedule` 106, `test_stage_145_fresh_inputs_recovery` 11, `test_stage_142_active_continuity` 22, `test_stage_143_recalculation_triggers` 22, `test_review_vehicle_update_wait` 2, `test_plan_car_ended_rules` 29, frontend `sidebar.test.ts` 90. Manifest 2.5.147 (backend change; card artifacts rebuilt only for the embedded version); `npm run build` and `check-dist` pass; ruff clean on touched files.
- Not run: `test_plan_details_isolated`, `test_stage_103_partial`, `test_stage_151a_time_reserve` (known pre-existing failures, not re-baselined here), full suites, browser/Playwright, HA-fixture tests (`fcntl` plugin). Live behaviour unverified; mocked checks never prove physical charging. Not committed or pushed by the implementer; coordinator review pending.

### 2026-11-14 — Stage 16.2 safe dispatch, publication continuity and partial-plan UI (2.5.148; local mocked; no live HA/charger action)

- Admission: `AutoPlannerController.morek_price_blocker(snapshot, now)` is the **one** price-admission judgement (evidence equal to the calculation's, aggregate `ready`/`waiting_for_tomorrow`, or `degraded` **only** with today `ready` + `listed` + a document, and every `shown_periods` minute including reserve inside contiguous finite intervals of a `ready`+`listed` day). `morek_plan_blocker` now delegates to it (previously inline, `degraded` always blocked). Manual `api/morek_schedule._validated_proposal(hass, entry_id, now=None)` calls it for a `degraded` aggregate (before: always `prices_stale_or_unavailable`); a degraded state with no proposal now reports `no_current_plan`. Manual `ready`/`waiting_for_tomorrow` keeps its earlier checks (the automatic worker path also runs the coverage check for them); this is a deliberate narrow scope, not a second coverage rule.
- Continuity: an uncapped Morek-owned calculation drops a tomorrow document that is not `ready`+`listed` (stale/invalid/failed), so a stale cheap tomorrow is never planned on (the plan stays dispatchable from valid today data and is marked partial through the existing `price_coverage_end`). Today's own state is still the existing `_price_data_gate`. No other planning change; capped and non-Morek unchanged.
- Existing mechanisms reused, only proven by tests: tomorrow arriving changes the price evidence → recalculation → worker compare (an equal schedule sends nothing; a different one sends once); identical SOC/publication sends nothing; stale/gapped/unlisted/unusable-state used prices still block (`prices_stale_or_unavailable`/`price_coverage_unavailable`); a price change after calculation is `price_inputs_changed`.
- UI: `price_policy` gains additive `price_state` and `tomorrow_pending`; the sidebar adapter and `daily-overview.ts` prepend "Planned using available published prices; tomorrow's prices are pending or unusable, so this plan may change when they arrive." to the existing "Provisional: …" text (which still shows the unresolved kWh and says future prices/readiness are unknown). No claim of completion, future knowledge or flow. Frontend `validate.ts` decodes the flag.
- Tests: new `tests/test_stage_162_safe_dispatch.py` (9; real controller + worker + admission path); frontend `partial-policy.test.ts` (+1); isolated harness `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin --noconftest -c /dev/null -o asyncio_mode=auto`. Also passed: `test_stage_161_published_only` 12, `test_morek_schedule` 106, `test_stage_142_active_continuity` 22, `test_stage_143_recalculation_triggers` 22, `test_stage_145_progress_recovery` 32, `test_stage_145_fresh_inputs_recovery` 11, `test_planner_price_policy_guard` 29, `test_morek_worker` 142 passed + 1 failed; frontend `sidebar.test.ts` + `partial-policy.test.ts` 92. `npm run build`, `check-dist` and ruff clean.
- Pre-existing, identical without the change: `test_stage_103_partial::…real_morek_path` (`plan_inputs_changed`), `test_morek_worker::test_real_planner_publications_drive_worker_without_browser`, `test_stage_141_current_interval` 2 cold-timezone failures, `test_stage_13_reactive` (hangs), `test_price_policy_settings` (`hass` fixture). Test note: the first recalculation flips the lazily loaded learning flag in the evidence, so the new tests warm it with one recalculation.
- Not run: full suites, browser/Playwright, HA-fixture tests, live HA/charger/deployment; whether the installed price manager reports `degraded` with these authorities as read here is unverified. Mocks never prove physical charging.

- **Stage 16.2 review correction (uncommitted).** `_validated_proposal` now calls the planner's `morek_price_blocker` for `ready`, `waiting_for_tomorrow` and `degraded` alike (evidence unchanged + coverage by ready/listed finite intervals); a planner without the judge refuses. Uncapped Morek planning uses only `ready`+`listed` days, else `waiting_for_prices/no_prices_yet` (the `or documents` fallback is removed). Fakes in `tests/test_morek_schedule.py` and `tests/test_morek_worker.py` gained a `morek_price_blocker` stand-in. New real-planner tests in `tests/test_stage_162_safe_dispatch.py` (25 pass): ready/waiting changed evidence, stale/unlisted/gapped/non-finite/area-stale, manual-vs-auto parity, blind planner, no usable today. Passed: `test_morek_schedule.py` + `test_stage_162_safe_dispatch.py` (131) with the isolated `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ... --noconftest` form; ruff clean. **Follow-up checks:** worker tests in short chunks: 140 passed, 3 failed with missing Europe/Stockholm timezone data; two failures reproduced on the baseline and the third had the same error. `test_stage_13_reactive.py` was not run again. `npm run build` and `npm run check-dist` passed at 2.5.148. No HA, charger, commit or push.

### 2026-11-14 — Stage 17.2 stale SOC with trustworthy estimates (2.5.149; local mocked; no live HA/charger action; coordinator-reviewed, committed and pushed)

- **Rule (one judgement, in `planning/auto_controller.py`).** `estimate_trusted(facts)` is used by the capped energy resolver
  (`capped_vehicle_energy`), the capped `_energy_for` basis and `morek_plan_blocker` (guarded admission). An energy-derived estimate is
  trusted only when: this car (`vehicle_id`), an anchor reading (`anchor_percent` 0–100, `anchor_at`), a known positive capacity,
  register-measured `delivered_kwh` > 0 and ≤ `ESTIMATE_MAX_DELIVERED_KWH` (40), no register reset (`register_reset`), and anchor age
  (`soc_age_s`) ≤ `ESTIMATE_MAX_ANCHOR_AGE_S` (12 h). Both constants are named and are the delegate's choice.
  `capped_planning_facts(facts)`: actual reading → as is; trusted estimate → as is; untrusted estimate → its **anchor reading as an actual
  level** (12.8 behaviour, never worse; `_progress_adjusted` then subtracts attributed measured progress as for any actual reading);
  estimate with no anchor → `target_soc_stale`.
- **Provenance.** `SocReading` (and `LiveVehicleFacts`) gained `anchor_percent`, `anchor_at`, `delivered_kwh`, `register_reset`, set only by
  `resolve_soc` for an estimate. A register that fell back and kept counting leaves a carried estimate that is flagged `register_reset` and
  therefore not trusted (the spec's “no reset/gap/backwards”; a backwards register already leaves no estimate). No new SOC source, wake or
  learner change; the minimum-SOC protection floor (`min_soc_floor`) and the uncapped Morek path are untouched.
- **Churn guard.** For a capped plan whose level is estimated, `_morek_input_evidence` identifies the level by anchor (vehicle, anchor
  percent, `anchor_at`, entity, estimated flag) plus `estimate_trusted`, not by the running `soc_percent`; register ticks therefore neither
  produce `plan_inputs_changed` nor a resend. A new anchor (fresh reading), a trust flip or a cleared label do change it. Uncapped evidence is
  unchanged. Not done: a pure passage of time that expires trust (12 h) has no input change, so it is noticed at the next recalculation or
  pre-wire check (`plan_inputs_changed`), not by a timer.
- **Tests (isolated harness, one file at a time):** new `tests/test_stage_172_stale_soc.py` (12): trust-rule matrix and fallback basis, capped
  energy shrinks target and minimum from one trusted figure, `resolve_soc` provenance and reset flag, real controller (trusted estimate plans
  and is labelled; untrusted estimate plans from the anchor; no anchor / unknown car / other car / missing capacity hold), evidence drift vs
  anchor/trust, blocker, and real worker (dispatch once, drift neither resends nor blocks; fallback dispatches once). Reruns passed:
  `test_capped_vehicle_energy` 21, 145_fresh 11 (one `SimpleNamespace` reading mock gained the new fields), 145_progress 32, 146 15, 142 22,
  143 22, 162 25, `test_stage_95_recovery` 14, `test_review_vehicle_update_wait` 2, `test_plan_car_ended_rules` 29,
  `test_soc_dashboard_provenance_isolated` 6, `test_review_soc_anchor` 3, `test_morek_worker` selected `-k "soc or vehicle or evidence or
  last_known or unchanged"` 14. Ruff clean; `npm run build` and `check-dist` pass at 2.5.149.
- **Unrun/limits:** `test_morek_worker` whole file (72 passed before the 25 s limit, no failure seen), `test_stage_13_reactive` whole file
  (timed out at 25 s with no output), `test_min_soc_floor`/`test_soc_anchor_register`/`test_soc_lagging_register`/`test_soc_report_time_baseline`
  (`hass`-fixture cases cannot run on this Windows harness; their non-`hass` cases passed), `test_target_soc` (needs `offline_relay`), full
  suites, browser. Estimates are never claimed to be physical charging; live behavior unverified; not installed.

### 2026-11-14 — Stage 17.3 missing-capacity fallback for the capped path (2.5.151; local mocked; no live HA/charger action; coordinator-reviewed, committed and pushed)

- **Rule (`planning/auto_controller.py`, `capped_vehicle_energy`).** An unknown capacity (`None`, `<= 0`, non-finite, bool or non-number) is treated as *missing*, never used, never guessed. With a trusted learned figure (`learned.use_kwh_per_percent`) the capped need is worked out through the existing `target_need` → `with_learned` (battery size ≡ ratio × 100 × `CHARGE_EFFICIENCY`, so wall kWh = points × learned wall kWh/%; units and efficiency identical to the uncapped path). Target semantics (rounded stored target, car limit via `effective_target_soc_percent`, `minimum_above_target`) and minimum-SOC arithmetic (`target_kwh × (minimum − soc)/(target − soc)`) are unchanged; the "learned may lengthen the minimum, never shorten it below the default's" comparison needs a default figure, so it is skipped only when no capacity exists (the learned figure then stands for both needs; documented, nothing invented). With neither capacity nor a trusted figure the result is the existing `target_capacity_unknown` (status line `target_soc_unknown` with `missing: ["capacity"]` — the who-acts sentence — and the dashboard `soc.missing` keeps listing `capacity`). `_energy_for` also sanitizes the capacity it records.
- **Labelling (additive).** `AutoSnapshot.projection_capacity_unknown` (set when no capacity and the ratio came from learning; part of `meaningful_key`), dashboard `proposal.projection.capacity_unknown`, decision/status `inputs.capacity_unknown`, and a sidebar `projectionNote` sentence ("Battery capacity is unknown … estimate from the car's own learned energy per percent, not from a stated capacity"). `learning_estimate` no longer blanks the learned need when only the default is unknown (`default_need_kwh` stays `null`, so no effect minutes are claimed). Dashboard `soc.efficiency`/`need_kwh` already used `target_need` (consistent with the plan); `soc.capacity_kwh` stays `null`.
- **Recovery.** No new trigger. A stored capacity (`update_vehicle` → `_recalculate_planners_for`), a reported capacity (next reading/recalculation after the 5-minute `FACTS_CACHE_S`), or a changed learned figure alters `_morek_input_evidence` (capacity and the learned value are already in it), so a pre-wire check reads `plan_inputs_changed` and the existing recalculation/worker-compare path sends once; an equal schedule sends nothing. Identity (`_capped_input_problem`, `_notification_vehicle`), freshness, Pause/Stop, price and outcome guards are untouched; `morek_plan_blocker` gained no rule.
- **Limits / risks (important).** (1) **Morek-owned plans (revised in 2.5.151):** `LearnedEnergyStore.learned(morek=True)` with no/invalid capacity now revalidates captures without the changed-size check and, if proven votes exist, uses the newest vote's *recorded* capacity as `reference_capacity_kwh` (votes recorded with another size are ignored; a capture previously refuted as `capacity_changed` by a known size stays refuted; an invalid capacity is treated as missing, not as a conflict). Vote counts, spread, 4-cannot-shorten/5-can and the clamp are unchanged, applied against that reference. Evidence is only what the stored captures and their retained records prove; with none, or with too few/disagreeing/other-car/gap/uncertain records, the plan still holds as `target_capacity_unknown` (not all missing capacity is recoverable). `capped_vehicle_energy` uses the reference as the default for the never-shorten minimum-SOC floor. (2) A learned figure with neither a capacity nor a recorded reference (legacy samples) has no default to protect the minimum-SOC need, so with a real minimum need it holds as `target_capacity_unknown` instead of planning (2.5.151); with no minimum, or one already met, it plans. (3) New learned data arriving after a session closes does not itself trigger a recalculation (17.4 owns that). (4) Not installed; estimates are not physical charging.
- **Tests (fast, one file at a time; Windows form `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`).** New `tests/test_stage_173_missing_capacity.py` (18): resolver matrix (arithmetic 44/12 kWh with and without capacity, car limit, minimum met/above target, invalid capacities, unchanged known-capacity behaviour incl. never-shorten floor, level/staleness precedence), learner rules unchanged (2 of 3 samples and 2-agreeing not trusted, Morek needs capacity), real controller with a real `LearnedEnergyStore` (hold, untrusted hold, plan + label + notification key, recovery on capacity, other-car and invalid-level holds, NaN capacity, uncapped energy step unchanged), blocker/evidence, learning block vs plan, `_planning_inputs`/status wording, and the real Morek worker (hold sends nothing; trusted figure sends once; unchanged input resends nothing). Reruns passed: `test_capped_vehicle_energy` 21, 172 12, 145_progress 32, 145_fresh 11, 162 25, 142 22, 143 22, 159b 70, `test_review_vehicle_update_wait` 2, `test_status_compose` 178 (+1 pre-existing `hass`-fixture error), frontend `sidebar.test.ts` 90. Ruff clean; `npm run build` and `check-dist` pass at 2.5.150.
- **Unrun / pre-existing:** `test_stage_13_reactive` whole file (`FF.FF` then a 25 s timeout, identical with 17.3 stashed), `test_capped_auto_execution_isolated::test_saved_capped_settings_reach_real_calculation_and_preview` (fails identically with 17.3 stashed), `hass`-fixture files (`test_target_soc`, `test_auto_controller`, `test_soc_first_state`: cannot load the HA plugin on Windows), `test_morek_worker` whole file, full suites, browser. No HA, charger, deploy, commit or push.
- **2.5.151 verification (fast, one file at a time):** `test_stage_173_missing_capacity` 21 (adds real-store Morek votes without capacity: trusted/clamp/asymmetric rules, rejects untrusted, too few, disagreeing, unproven identity, no checker, gap, uncertain, estimated time basis, other car, open plug-in, mixed sizes, refuted size; real controller recovery; real worker holds then sends once, nothing resent), `test_stage_159b_promotion` 70, `test_capped_vehicle_energy` 21, 172 12, 145_progress 32, 145_fresh 11, 142 22, 143 22, 146 15, `test_morek_schedule` 106, 95_recovery 14; ruff clean; `npm run build`/`check-dist` pass at 2.5.151. Unrun: `test_stage_144` (exceeds the 25 s cap), `test_learned_energy` (33 `hass`-fixture errors, 18 pass), `test_stage_103_partial::test_uncapped_necessary_purchase_passes_real_morek_path` fails identically with these planning changes stashed (pre-existing), full suites, browser. No HA, charger, deploy, commit or push.

### 2026-11-15 — Stage 17.4 automatic recovery on session finalization (2.5.152; local mocked; no live HA/charger action; coordinator-reviewed, committed and pushed)

- **What finalization can and cannot change (proved by tests).** `measured_progress` counts only identified sessions of this car that began at/after the reading; a charge that began before the reading and is read with an old (>300 s) reading, a charge with no car, or invalid energy is `unknown`, whether open or closed. So the close of an identified *later* session changes the known energy (open sample → final total; plan shrinks once, flag stays clear), while a straddling or car-less charge stays `progress_unknown` after it closes: nothing but a newer reading clears it. The 15.8 late-reconciliation record is not attribution proof and never changes `energy_kwh` (tested at the real `SessionStore`: `set_late` notifies, energy unchanged).
- **Code (`planning/auto_controller.py`).** `_progress_adjusted` records `ProgressWatch(session_id, unknown)` when an open session of this car (or of none) was counted/flagged; `_energy_for` clears it first (memory only: a restart has none until its first calculation, which recomputes the flag from the store). `_on_sessions_changed` (existing `SessionStore` listener; store `close` and `set_late`/`set_open` both already notify, so no store change) now calls `_note_finalization` for a target driver (the legacy non-target branch is unchanged). It acts only for a Morek-owned plan, when the watched session id is no longer open and is in the closed list, once per id (`_finalized_seen`, bounded), with no recovery task running, and not while Paused (`executor.paused`), person-Stopped (`held_off_by_person`) or with a pending send (`executor.pending`). It schedules one `async_recalculate(cause="session_finalized")`; the worker treats a non-`soc` cause as a strict recalc, so an equal schedule sends nothing and an active window keeps its Stage 14 protection. The listener sends nothing itself.
- **Reading request.** If that replan still reports `progress_unknown`, the car is asked once per closed id through the *existing* `_ask_reading` closure (`__init__.py`, now also given to the planner via `set_reading_asker`): same `soc_reader.notify_next_reading`, `async_ask_vehicle_update`, 60 s per-vehicle limiter and opt-in wake once per plug-in; no new wake, timer or listener class. The sidebar progress note now says only a newer reading corrects the plan ("waiting for the car's next level; a charge ending does not attribute this energy; the car is asked once where it offers a re-read") — it does not claim a reading was received.
- **Limits.** A charge that began after the last calculation and closed before the next has no watch, so it is picked up only by the existing triggers (reading, price, settings). A failed recalculation or ask is not retried by 17.4 itself: the next ordinary calculation (price/settings/reading/worker) recomputes from the store with the final energy; a failed ask is not repeated (the `_ask_reading` once-per-plug-in rules own that). `_morek_energy` is the last ownership answer. Not installed; nothing here proves physical charging.
- **Tests (fast, one file at a time, `python tools/run_isolated_logs_tests.py <file>`).** New `tests/test_stage_174_finalization_recovery.py` (12): identified later close → exactly one replan, plan shrinks by the final-minus-counted energy, no ask, repeats silent; straddle/no-car close → one replan, flag persists, one ask, no loop, newer reading clears; second session id is its own trigger; no watch / late reconciliation / non-Morek → nothing; restart; Stop/Pause/pending → no calculation or ask; failing asker swallowed; real `SessionStore` notifies on close and late record; real worker: replan sends nothing by itself and an equal schedule is not resent. Reruns passed: 145_progress 32, 145_fresh 11, 142 22, 143 22, 172 12, 173 21, 162 25, 146 15, `test_review_vehicle_update_wait` 2, `test_plan_car_ended_rules` 29, frontend `sidebar.test.ts` 90. Ruff clean; `npm run build`/`check-dist` pass at 2.5.152.
- **Unrun.** `test_stage_13_reactive` whole file and the other known-hanging/`hass`-fixture files, `test_morek_worker` whole file, full suites, browser, HA, charger, deployment. No commit or push.


### 2026-11-15 — Stage 17.4 correction (2.5.153; local mocked; no HA/hardware, no commit)

- **Preview is side-effect-free for the watch.** `_energy_for` clears `_progress_watch` and `_progress_adjusted` writes it only when `preview` is false (`preview` is now passed to `_progress_adjusted`). A preview can no longer erase or overwrite the live watch, so a close after a preview still triggers recovery.
- **Deferred, bounded retry of a held close.** `_note_finalization` still skips a close while a send is pending, Pause, person-Stop or another recovery runs, but now records the id in `_finalize_deferred` instead of losing it. `_retry_deferred_finalization` runs on two *existing* events, no timer or poll: `async_note_execution_change` (the executor's `_notify_change` after settlement/Resume/pause change) and the end of a running recovery. It re-checks the hold, acts once per closed id (`_finalized_seen`), sends nothing itself, and drops the deferral if a calculation made after the close already reset the watch (it counted the final energy), so settlement adds no extra calculation then.
- **Limitation (stated, not claimed complete).** Releasing a person's Stop has no verified execution-change event, so a close deferred by Stop is picked up by the next ordinary calculation/execution event, not at the instant Stop is released. A recalculation that fails, or an ask that fails, is not retried by this code: the next ordinary calculation recovers it; there is no repeated request. Dispatched-unknown commands are never retried by this code (it never sends).
- **Tests (`tests/test_stage_174_finalization_recovery.py`, now 18 incl. parametrized).** Preview neither erases nor writes the watch and a later close still recovers; close held by pending or Pause → no calculation, still-held retry silent, one calculation after release, never twice; person-Stop → no calculation or ask across repeated events; a calculation after the close drops the deferral; real Morek worker: close while pending → nothing, then settlement → one calculation and no extra send (an equal schedule is not resent). Windows form: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest <file>`; this file plus `test_stage_145_progress_recovery.py` pass (50 total). Ruff clean; `npm run build`/`check-dist` pass at 2.5.153. Not run: other suites, browser, HA, hardware.


## Stage 17.5 — exchange-rate freshness and truthful cap policy (manifest 2.5.154, local, coordinator-reviewed, committed and pushed)

- Implementation sub-agent. Source basis HEAD `7fadb671`, manifest 2.5.153 → 2.5.154. No HA, charger, deployment, commit or push.
- **One rate judgement:** new `pricing/rate_label.py` (`piece_rate`, `rate_usable`, `day_label`, `labels_for`; pure, no I/O). States
  `own` (table dated the day), `dated` (earlier table, age in days, ≤ `MAX_RATE_AGE` 7), `undated` (usable rate, no date; legacy
  documents still plan, labelled), `missing` (no rate, non-finite/≤0, table after the day or older than 7 days, other currency).
  `planner._rate_for` now uses it, so a stored/relayed document with a too-old or future table is `missing_fx_rate`, never converted.
- **Coverage (16.2 judgement, no second rule):** `AutoPlannerController._rate_covered` drops a day without a usable rate from the
  plan's documents (like an unpublished day); if none has a rate the documents are kept and the planner refuses `missing_fx_rate`.
  `morek_price_blocker` counts only rate-usable days as covering. EUR areas: `rate_usable` is always true, labels `None`.
- **Labelling:** `AutoSnapshot.fx_provenance` (display only, not in `meaningful_key`); `encode_price_policy` adds `fx`, `fx_state`,
  `fx_waiting`, `fx_note` (rate date, source, age; for a soft cap “the soft cap was compared with the price converted at that rate”;
  missing → “Waiting for the ECB exchange rate; it is asked for again automatically”). `validate.ts` passes `fx_note`;
  `daily-overview.ts` shows it. English `issue.planningUnavailable.missingFxRate` reworded; other languages not changed (still say the rate is missing).
- **Arrival replans once:** unchanged mechanism — the rebuilt document is different `morek_price_evidence`, so the old calculation
  cannot be sent (`price_inputs_changed`) and one recalculation plans; an unchanged repeat yields the same plan. No new retry, timer or FX source.
- **Tests:** `tests/test_stage_175_fx_freshness.py` (6 passed, ~4 s). Focused reruns, each under 25 s, run with
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest`: `test_planner` 61,
  `test_planner_price_policy_guard` 29, `test_stage_162_safe_dispatch` 25 (22 s), `test_stage_172_stale_soc` 12,
  `test_stage_173_missing_capacity` 21, `test_stage_174_finalization_recovery` 18, `test_relay_contract` 19, `test_session_costing` 12 — all pass.
  `test_fx_rates.py` (20 fixture errors, identical on the stashed baseline), `test_dashboard_api.py` and `test_auto_controller.py`
  need the HA conftest/plugin and cannot run here (not caused by this change). `ruff` clean on touched Python; `npm run build` and
  `npm run check-dist` pass (no frontend unit suite run).
- **Limits / unverified:** the cap decision itself is unchanged (the planner already compared the converted price); only its statement is new.
  No browser/Playwright, installed behaviour, real ECB cadence, or HA-plugin suites. A day left out for a missing rate is not retried here (the existing `FX_RETRY` rebuild does it).


## Stage 17.6 — clear blockers and end-to-end automatic recovery (manifest 2.5.155, local, coordinator-reviewed, committed and pushed)

- Implementation sub-agent. Source basis HEAD `4bb08550`, manifest 2.5.154 → 2.5.155. No HA, charger, deployment, commit or push; no browser.
- **Mismatch found and fixed.** With no plan the worker's reason is only `no_current_plan` / `prices_stale_or_unavailable` (from `_validated_proposal`), which the recovery banner worded as "The plan is being recalculated" or "Waiting for a fresh vehicle reading" even when the planner waited for a battery capacity (a person's setting), the ECB rate or prices. `target_soc_stale` fell to the generic "No charging plan could be calculated…" sentence.
- **One table:** `api/morek_schedule.PLANNING_HOLDS` (planner reason or blocker code → banner action, who acts, existing recovery trigger) for `target_soc_unknown`, `target_soc_stale`, `target_capacity_unknown`, `missing_fx_rate`, `no_prices_yet`, `no_published_prices`, `price_data_stale`, `plan_inputs_changed`, `price_inputs_changed`. `decision_blocker(reason, plan_reason=None)` refines only the generic no-plan reasons (`no_current_plan`, `planning_unavailable`, `prices_unavailable`, `prices_stale_or_unavailable`) by the planner's own reason from `_planning_inputs` (also in decision events); Stop/Pause/uncertain/Charge Now reasons are never re-labelled. Added keys are additive: `detail`, `who`, `recovery`.
- **Wording (existing surfaces only).** `recovery-banner.js`: `set_battery_capacity` ("enter it in Plan; the plan is then made and sent automatically"), `wait_for_exchange_rate` (automatic; "asked for again automatically"), a car-reports sentence for `who: vehicle`, suffix shows `detail`. Status: `issue.planningUnavailable.targetSocStale` in all 9 locales (non-English texts are my translations, not reviewed by a native speaker). No sentence claims charging, a guarantee or needs Refresh/Send.
- **Recovery (no new trigger, timer or retry).** Each hold's input arrival is already an evidence change → recalculation → worker compare; proven with the real controller + real worker (or real admission worker for prices/FX): hold sends nothing; input arrives; old calculation is refused; one recalculation; exactly one upload; an unchanged recalculation sends nothing.
- **Combined case:** capped plan, untrusted (register-reset) estimate → anchor reading as actual level, degraded aggregate with tomorrow unavailable (today listed), a straddling closed session → plans, `progress_unknown` flagged, level not estimated, admitted, one upload; after a simulated restart (memory watch cleared, new worker over the same durable record) the same plan is recomputed and nothing is resent. Person Stop with a recovered plan: nothing sent (`stale_generation`).
- **Tests (each <25 s, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -p no:cacheprovider --noconftest <file>`):** new `test_stage_176_blockers_recovery` 19; reruns passed `test_stage_175` 6, `174` 18, `173` 21, `172` 12, `test_morek_schedule` 106, `test_stage_146_decision_evidence` 15, `95_recovery` 14, `154a` 37, `154b` 36, `152_link_monitor` 13; vitest `recovery-banner`, `departure-shortfall`, `i18n-parity`, `sidebar`, `schedule-check` pass. Ruff clean on touched Python; `npm run build` and `check-dist` pass at 2.5.155.
- **Remaining limitations (truthful).** (1) Nothing is installed or live-verified; mocks never prove physical charging. (2) Not run: full suites, `test_morek_worker` whole file, `test_stage_13_reactive` (hangs), HA-fixture (`hass`) files, browser/Playwright. (3) Stale actual-reading expiry of an estimate (12 h) has no timer; it is noticed at the next recalculation/pre-wire check. (4) Releasing a person's Stop has no verified event for a finalization deferred by it (17.4). (5) A failed recalculation/reading request is not retried by Stage 17 code; the worker's bounded blocker timer (12 checks) and ordinary input events re-check, after which the banner says timed checks stopped. (6) A plan-less state that is healthy (`nothing_to_charge`/`already_at_target`) still reaches the worker as `no_current_plan` and the banner says "The plan is being recalculated" — not refined here (outside the listed holds). (7) A capacity hold is only recoverable by a stored/reported capacity or proven Morek votes (17.3); the person must act for the first.

### Stage 17.6 final correction (local, frontend only; same manifest, rebuilt assets)

- A healthy planner `nothing_to_charge` (worker reason `no_current_plan`, `reconciliation.inputs.plan_state`) no longer shows
  "The plan is being recalculated." The banner is now an `info` "Nothing to charge right now: the plan needs no charging, so no
  schedule is being sent. This describes the plan, not the charger's actual power." A genuine `plan_inputs_changed`
  recalculation keeps the old wording; Stop/connector, pause and unknown-outcome banners are unchanged and take precedence.
- The battery-capacity text no longer promises an unconditional send: the plan is made automatically and sent automatically
  only if the usual safety checks allow it.
- Tests: `frontend/test/recovery-banner.test.ts` (nothing_to_charge, recalculation, Stop precedence, capacity wording).
  Build and `check-dist` pass. Not installed or live-verified; no HA, hardware or commit.

## Stage 13.1 — vehicle sources and planning properties (manifest 2.5.158, local, coordinator review/commit pending)

- Implementation sub-agent. Source basis HEAD `35f5ae5f`, manifest 2.5.155 → 2.5.156. No HA, charger, deployment, commit or push; no browser; no subagents.
- **Reuse, no new backend:** `spotnav/get_entity_config` (admin-only read: per-vehicle `selected`/`source`/`candidates`), `spotnav/choose_vehicle_soc` (same discovery decision the `confirm_vehicle_soc` service records) and `spotnav/update_vehicle` (capacity / onboard phases with `expected` compare-and-set; the backend then recalculates planners for that car through its existing path). Dashboard `vehicles` rows supply capacity, `capacity_source` (`reported` = read-only, `stored` = entered), phases and the suggestion.
- **Files:** `frontend/sidebar/vehicle-sources.js` (pure model, write plans, signature), `frontend/shared-dashboard/vehicle-sources-view.js` (shared renderer), `dashboard.js` (card, own drafts `v:*`, own buttons — never part of the plan save), `reconcile.js` (keys), `dark.css`, `sidebar/panel.js` (read on refresh for admins, saves, conflicts), `prototype/sample-adapter.js` (fictional read-only sample), tests `frontend/test/vehicle-sources.test.ts` (22) and an allowlist line in `sidebar.test.ts`.
- **Behaviour:** opening/editing only reads (`get_entity_config`, refreshed when older than 45 s). The car shown is the person's pick, else the plan's saved car, else the only car — never a guess among several. Ambiguous sensors list candidates and keep “Choose a sensor…” selected. A saved choice that is no longer offered stays visible as “(no longer offered)”; an entity missing from HA or unavailable is flagged. The reading line shows value, source/age and a stale marker (the adapter's own judgement) and says “age unknown” for a car that is not the dashboard's SOC vehicle. Sensor save: no-op when unchanged, confirm when replacing/clearing a saved choice, a fresh re-read first (changed elsewhere → conflict, nothing written), then `choose_vehicle_soc`. Properties save: capacity 1–500 kWh (same bounds as the backend) or clear, phases 1/3, `expected` from the row the person saw. Conflict, refusal, response-unavailable, timeout and a permission change mid-save are distinct; the last three are unknown outcomes that block retries until an explicit reload (per-connection pending/unknown sets like settings saves). Plan save and Morek actions are blocked while a vehicle save is in flight; Stop/Pause/Charge Now are not.
- **Tests (each < 25 s):** `npx vitest run test/vehicle-sources.test.ts` 22 passed; reruns `sidebar` 90, `sidebar-learning-reset` 7, `sidebar-price-chart` 5, `recovery-banner` 9; `node --test` `shared-dashboard/boundaries`, `plan-view`, `prototype/sample` 14 passed. `npm run build` and `npm run check-dist` pass at 2.5.156.
- **Unrun:** full vitest/pytest suites, `tsc` type-check, browser/Playwright (the preview/sidebar rendering was only exercised in jsdom), HA-fixture tests (`fcntl`), installed behaviour. Not verified: how a real vehicle integration exposes candidates/capacity, whether choosing a sensor replans immediately, mobile layout.
- **Limits:** (1) an ambiguous-sensor car has no dashboard row, so capacity/phases appear after a sensor is chosen; (2) a vehicle-reported capacity cannot be overridden and a stored value under it is not shown; (3) the sensor write has no backend compare-and-set — the guard is the client re-read, so a race between read and write is not excluded; (4) English text only (the sidebar host's own convention, no i18n keys added); (5) other cars' readings have no age, so they are labelled stale/age unknown; (6) a non-administrator sees only the permission notice.

### 13.1 corrections (manifest 2.5.157)

Implementation sub-agent; no HA, charger, deployment, commit or push; no browser; no subagents. Supersedes limits (1)–(3) above and the “no new backend” line (small backward-compatible backend additions below).

- **Properties without a sensor.** `get_entity_config` now also sends `config.vehicle_properties` (one row per choosable vehicle, `api/entity_config.py::_vehicle_property_rows`): `capacity_kwh`/`capacity_source` (effective: reported, else stored, else null), `reported_capacity_kwh`, `reported_known`, `stored_capacity_kwh`, `onboard_phases` (effective) and `stored_onboard_phases`. A car whose sensor is ambiguous or missing has no dashboard row, so its rows come from the stored properties; `reported_known: false` means nothing could be asked of the car, i.e. a vehicle-reported capacity is *unknown*, not absent (the soc reader is deliberately not called for such a car, because its facts cache would hide a capacity for a few minutes after a sensor is chosen). The key is optional in `frontend/src/entity-config.ts` (older backend → empty list → the UI says the values could not be read). The UI now shows reported vs stored (“not used while the vehicle reports one”) and missing truthfully, without a dashboard row.
- **`update_vehicle` for those cars.** The vehicle check is `soc_choices` (every choosable car, a superset of the old `resolve_target_vehicle(None)` list); with no dashboard row, compare-and-set uses the stored properties (effective phases = stored else 3, capacity = stored). Admin-only checks, validation and conflict codes are unchanged; the success answer's `vehicle` is `null` for such a car, which the old `decodeVehicleAnswer` rejects as malformed, so the sidebar uses the new `decodeVehicleWriteAnswer` (config + outcome only; card behaviour unchanged). Capacity/phases now follow the config read's freshness (90 s), not the dashboard's. The webhook `update_vehicle` shares the core and so also accepts those cars.
- **Server-side selection guard.** `spotnav/choose_vehicle_soc` accepts optional `expected_entity_id` (string: the sensor last seen chosen by a person; `null`: no personal choice). Absent → the old unconditional write (legacy callers, admin check, validation unchanged). Present and different from the saved choice at the write boundary → `spotnav_conflict` with the current config, nothing written; a non-string/empty value → `spotnav_invalid_value` (`invalid_expected`). Comparison, validation and the store write run under one `asyncio.Lock` (`repairs.soc_write_lock`, in `hass.data`), so two guarded writes cannot interleave across the store's awaits. 2.5.158: the `confirm_vehicle_soc` and `unconfirm_vehicle` services take the same lock around their own validate-and-write (otherwise unchanged, no replan, no new fields), so those three writers are serialized. The Repairs fix flow and the config flow's `resolve_vehicle` step still write the same decision without the lock (interactive, not covered), as do `dismiss`/`undismiss`; the protection is therefore not strict across every writer. The sidebar sends the choice it displayed (`null` for none/automatic) and no longer does its own pre-write re-read.
- **Replanning.** Nothing replanned on a selection change before. `async_set_vehicle_soc` now collects the chargers whose planned car is this one before *and* after the write and, only if the sensor actually in use changed (`selected_entity_id` before ≠ after), runs the existing `controller.async_recalculate()` for them (same helper `update_vehicle` uses). No command, wake or notification is sent by this code; a Morek owner then goes through the normal guarded reconciliation. An unchanged selection (e.g. the same sensor again) replans nothing. The `confirm_vehicle_soc` service was not changed and does not replan.
- **Tests.** Frontend (run, each <25 s): `vehicle-sources.test.ts` 27 passed (ambiguous/no-row properties, reported+stored, expected sent, conflict → one request/draft kept, null-vehicle answer, decoder); `sidebar.test.ts` + `contract-fixtures.test.ts` 233 passed; `entity-config`, `vehicle-card`, `vehicle-identification` 86 passed; `tsc --noEmit` clean. Python (written, **not run**: the HA test plugin needs `fcntl`, unavailable on Windows; files compile): `tests/test_vehicle_soc_command.py` +4 tests (guard conflict/legacy/malformed, two interleaved guarded writes → one winner and one conflict, replan on change but not on a no-op, properties listed and writable for an ambiguous car). The existing exact-equality assertion on `config["vehicles"]` is unaffected because properties are a separate key. `npm run build` and `npm run check-dist` pass at 2.5.157.
- **Limits now.** (1) The `hass`-fixture tests in `tests/test_vehicle_soc_command.py` still cannot run on Windows; the isolated `tests/test_vehicle_soc_guard_isolated.py` (7 pass, ~2 s, `python tools/run_isolated_logs_tests.py tests/test_vehicle_soc_guard_isolated.py`; HA boundaries faked, real `async_set_vehicle_soc`/`async_update_vehicle`/service handler; fails for the overlap and service-vs-guard cases when the lock is made per-call) covers overlap, conflict-no-write, legacy caller, replan once/no-op/clear, no-row compare-and-set and validation. No HA; real integrations' candidates/capacity not verified. (2) The guard compares only the saved choice, not the candidate list; the entity is still validated server-side. (3) Serialization covers the card command and the two services (2.5.158), not the Repairs fix flow, the config flow or dismiss. (4) Replan relies on `preview_for`/`planned car` resolution; whether a given Morek owner then re-uploads is the existing reconciliation's behaviour, unverified. (5) A backend older than 2.5.157 ignores `expected_entity_id` (unguarded) — the UI and backend ship together. (6) English-only text, no browser/Playwright run, not installed.

## Stage 13.2 — market and charging-cost settings (manifest 2.5.159, local, coordinator review/commit pending)

- **What:** a collapsed “Advanced: market & charging costs” card in the shared sidebar UI and the local preview (fictional, read-only
  sample). Pure model/plans in `frontend/sidebar/market-costs.js`, panel wiring in `frontend/sidebar/market-costs-panel.js`, renderer
  `frontend/shared-dashboard/market-costs-view.js`; small hooks in `sidebar/panel.js`, `shared-dashboard/dashboard.js` (drafts `m:`,
  `data-msetting`), `reconcile.js` and `dark.css`. **No backend change.**
- **Reuse:** `get_market_options` (read), `update_settings` via `marketReplacement` (area, VAT, energy tax, flat grid fee), `update_grid_tariff`
  via `storedBody`/`sameBody` (percentage of raw, high-load fee and window, demand components echoed unchanged), `choose_price_source`
  (confirmed; only with several entries). Writes are administrator-only; non-administrators see everything read-only.
- **Honesty rules enforced and tested:** provider and held-data state, saved vs selected area, raw published price vs configured variable cost,
  currency and units are separate facts; `unknown` is never zero; negative raw prices stay negative; an included component is locked and
  nothing is added for it; a suggestion is stored as “suggested” (never copied); no provider, area, entry or fee is changed silently;
  suggested high-load hours are only saved with the fee switched on; no historical tariff is invented.
- **Write outcomes:** unchanged/invalid sends nothing; `revision_conflict` writes nothing and blocks until reload (also marks the plan record stale);
  reconcile failure after a durable `update_settings` adopts the record and demands a reload; a refused code is “not saved”; a timeout, an
  unreadable or non-accepting answer, or a permission change mid-save is an unknown outcome that blocks saving until an explicit Reload. After
  any accepted write the panel waits for a fresh dashboard read (`costAwaitingRead`) before another change; tariff and price-entry writes also
  re-read the settings record because its wire revision includes the price entry's write counter.
- **Checks run (all mocked, each under 25 s):** `npx vitest run test/market-costs.test.ts` (35 pass: provider/area/currency, negative and unknown prices,
  fee basis and included locks, area change confirmation, tariff windows, permissions, stale data, conflicts, unknown outcomes, drafts, preview parity),
  `test/vehicle-sources.test.ts` (27), `test/sidebar.test.ts` (90; its three read-only-host whitelists now allow `get_market_options`),
  `test/market.test.ts` + `test/grid-tariff.test.ts` + `test/bundle.test.ts` (73 together), `node --test shared-dashboard/boundaries.test.mjs prototype/sample.test.mjs`
  (11), `npm run build`, `npm run check-dist`, `npm run prototype:build`.
- **Unrun / limits:** full frontend suite, browser/Playwright, HA-fixture Python tests, installed behaviour, a Morek owner's re-upload after a replan,
  i18n for this area (English text), per-charger preview of a shared price-entry change. Demand-charge components, the import target and Nord Pool key /
  provider setup remain in the old card. Not installed, deployed or live-verified; no HA, charger or hardware access was used.

## Stage 13.3 — practical plan and charger parameters (manifest 2.5.161, local, coordinator review/commit pending)

- **What:** a collapsed “Advanced: plan & charger parameters” card in the shared sidebar UI and the local preview (fictional, read-only
  sample): maximum charging periods, planned current, departure date and weekdays. Pure model/plans in `frontend/sidebar/plan-params.js`,
  panel wiring in `frontend/sidebar/plan-params-panel.js`, renderer `frontend/shared-dashboard/plan-params-view.js`; small hooks in
  `sidebar/panel.js`, `shared-dashboard/dashboard.js` (drafts `p:`, `data-psetting`), `reconcile.js`, `dark.css` (dark theme and ≤800 px rules) and
  `prototype/sample-adapter.js`. **No backend change, no new message.** Ready-by on/off/time, target, cap, minimum and reserve are not duplicated.
- **Reuse:** the existing `update_settings` replacement through the card's validators: `chargePeriodsReplacement`, `replacementFor('current')` with the
  charger's `current_range` (6–32 A default, labelled), `replacementFor('deadline')` with `departureDays` (today..+7 in the market calendar).
  Permissions follow the backend: periods administrator-only; current and departure for administrators or where `users_change_plan` is on.
- **Safety rules enforced and tested:** the current is never raised automatically (a raise asks first; a stored out-of-range value is kept and
  flagged, an untouched value is not re-judged); the planned current is described as a planning input, not load balancing or protection; Morek's
  3-window limit (`MOREK_MAX_BLOCKS`) is stated with the effective `min(cap, 3)` and ownership from fresh Morek status (else “not known”); a
  date needs ready-by on; a new date needs a known market zone, lies in today..+7 and, for today, a time still ahead; an empty weekday set is
  refused; unchanged or invalid sends nothing; only the owned fields change, built from the latest accepted record.
- **Write outcomes:** `revision_conflict` writes nothing and blocks until reload (marks the plan record stale); a reconcile failure after a durable
  save adopts the record and demands a reload; a refused code is “not saved”; a timeout, a non-accepting or unreadable answer or a permission
  change mid-save is an unknown outcome that blocks saving until an explicit Reload (shared `unknownSettingsWrites`/`pendingSettingsWrites` with
  the plan form); after an accepted write the panel waits for a fresh dashboard read (`paramAwaitingRead`) before another change.
- **Morek 16 A limitation (review fix, 2.5.161):** a Morek schedule is only sent at exactly 16 A (`_validated_proposal` and the worker refuse any other saved current with `current_must_be_16`). The planned-current block now says so. Ownership comes from fresh Morek status (`recorded_owner`): **owned** → the input is limited to 16 A, a saved non-16 value is shown with a warning and kept exactly as saved (never changed silently), and a save of any other value is refused client-side with no request; **unknown** (no/stale status, non-administrators, never loaded) is treated conservatively as possibly owned → the same warning, and saving a non-16 value asks for confirmation first; **not Morek-owned** → a neutral note only and normal saving. The charger's electrical range, raise confirmation, permissions and the backend's own validation are unchanged. No backend change: a non-panel client can still save another current, and the backend refusal remains the final guard. Tests: `test/plan-params.test.ts` (26: model, write plan, panel for owned/unknown/non-Morek, no silent change).
- **Bug fixed:** `departureDays().nextOccurrence` (`src/settings.ts`) used elapsed time since local midnight instead of the wall clock, one hour
  wrong on 23/25-hour days (also affected the old card's date-picker default); covered by `test/plan-params.test.ts`.
- **Checks run (mocked):** `npx vitest run test/plan-params.test.ts` (23, about 8 s: period options and Morek note, current range/nominal/out-of-range,
  weekday/date/deadline logic, both Stockholm clock changes, permissions, signatures, renderer/preview/dark-CSS parity; real panel: read-only open, saves
  with revision, raise confirmation, refusals, conflict, reconcile failure, unknown outcome and reload, non-admin, stale dashboard, drafts and concurrent
  change, permission change mid-save); together with `test/settings.test.ts` and `test/market-costs.test.ts` (185 pass, about 14 s);
  `test/vehicle-sources.test.ts` + `test/settings-editors.test.ts` (125 pass, about 20 s); `test/sidebar.test.ts` (90 pass but about 33 s, run separately);
  `npx tsc --noEmit`; `npm run build`; `npm run check-dist`.
- **Unrun / limits:** full frontend suite, browser/Playwright, HA-fixture Python tests (none needed, no backend change), installed behaviour, a Morek
  owner's re-upload after a replan, the plan's effective window count, i18n for this area. Not installed, deployed or live-verified; no HA, charger or
  hardware access was used.

## Stage 13.4 — notification settings and setup check (manifest 2.5.162, local, coordinator review/commit pending)

- **What:** a collapsed “Advanced: notifications & setup check” card in the shared sidebar UI and the local preview (fictional, read-only sample):
  per-charger HA mobile-app recipients, the eight events, and a compact setup check. Pure model/plans in `frontend/sidebar/notify-setup.js`, panel wiring in
  `frontend/sidebar/notify-setup-panel.js`, renderer `frontend/shared-dashboard/notify-setup-view.js`; small hooks in `sidebar/panel.js`, `shared-dashboard/dashboard.js`
  (drafts `n:`, `data-nsetting`, `data-goto` links), `reconcile.js`, `dark.css`, `prototype/sample-adapter.js`, `src/setup-checklist.ts` (new `setupRowText`), and
  `notifyBusy` in the plan-params/market panels' guards. **No backend change, no new message.**
- **Reuse:** `update_settings` through `notificationsReplacement` (url kept, events in backend order, administrator-only); `notifications.available` from the settings record;
  `phoneOptions`/`eventOptions`/`noRecipientsHint` from `src/notifications.ts`; dashboard `setup` rows via `setupRowsOf`/`setupRowText`; `prices.provider/state/interval_count`;
  `recoveryBanner` (9.5/17.6 wording) from fresh Morek status. Stale/missing status → “unknown”, not “nothing blocked”.
- **Rules:** a notification only says SpotNav noticed an event — never that a plan was sent or charging measured; saving sends nothing and does not wake the car;
  no phone/no event is stored and said to send nothing; a vanished chosen phone is kept (flagged) until unticked; unchanged/invalid saves send nothing; conflict, reconcile
  failure, refusal, timeout and permission change mid-save handled like 13.3 (unknown outcome blocks saving until Reload).
- **Checks run (mocked):** `npx vitest run test/notify-setup.test.ts` (24, about 8 s: model, diagnostics, write plan, renderer/preview parity, real panel: read-only open, save with revision,
  unchanged, missing phones, conflict, refusal, unknown outcome and reload, reconcile failure, non-admin, stale dashboard, drafts and concurrent change, permission change mid-save, link);
  `test/plan-params.test.ts` + `test/market-costs.test.ts` (61), `test/vehicle-sources.test.ts` + `test/notifications.test.ts` (41), `test/setup-checklist.test.ts` (20),
  `node --test shared-dashboard/boundaries.test.mjs prototype/sample.test.mjs` (11), `npx tsc --noEmit`, `npm run build`, `npm run check-dist`, `npm run prototype:build`.
- **Unrun / limits:** `test/sidebar.test.ts` (about 33 s), full frontend suite, browser/Playwright, HA-fixture Python tests (none needed), installed behaviour, i18n for this area,
  delivery of a notification to a phone (an available notify service is not proof of delivery), editing the tap-through url. Not installed, deployed or live-verified; no HA,
  charger or hardware access was used.


**Stage 18.1 coordinator review:** shared dark tokens and shadow-host palette scoping reviewed; 33 focused dark-theme/log-viewer/bundle tests and check-dist passed. No browser or installed visual verification. Layout work continues in 18.2; legacy card retains HA theme variables.


**18.2 coordinator review:** fixed `.cn-fields [hidden]` so grid labels cannot expose the custom-end input. 28 focused layout/dark/Charge Now tests passed (JSDOM CSS parsing warnings), build and check-dist passed. Mobile shared-preview widths were checked by the delegate; host Charge Now/debug and desktop remain visually unverified.


**18.3 coordinator review:** sole-car early resolution and removed single-car camera/question branches reviewed; explicit guest resolution is unchanged. New resolver/identifier and camera-rule tests passed together (33, 1.86 s), check-dist passed. Real-HA guest/identification suites remain unrun; no live validation.


**18.4 coordinator review:** absolute thresholds and fixed minimum 0–30 c/kWh axis reviewed. HIGH/LOW annotation colours now use the same absolute bands, avoiding a red marker for a cheap daily high. 33 focused price-band/sidebar-chart/bundle tests passed in 1.87 s; build/check-dist passed. All Stage 18 substages are locally reviewed; hardware and remaining visual limitations are unchanged.


**7.1 coordinator review:** bounded held-price API and context-bound shared navigation reviewed; 23 backend tests (2.13 s), 31 focused frontend tests (2.97 s) and check-dist passed. JSDOM CSS parsing warnings do not establish visual rendering. No provider/HA/hardware access; source-only. Continue 7.2.


**7.2 coordinator review:** navigation intent, zone-aware ticks and rendering guards reviewed. Rejected short non-interval tooltip arrays as well as numeric pins; added a focused assertion. Root rerun: 50 chart/nav/band tests passed in 2.72 s before this narrow guard, and the interaction file reran after it. Build/check-dist passed; real canvas/touch/visuals remain unverified.


**7.3a coordinator review:** strict response-zone matching added; a test fixture claiming Stockholm while returning a UTC day was corrected to match its declared calendar. Failed background history refresh now keeps explicitly stale prior data and offers Retry, with no timed retry after failure (supersedes the earlier five-minute retry note). 49 backend tests passed in 2.46 s, 27 focused frontend tests passed in 3.14 s, build/check-dist passed. No visual or installed validation.


**7.3b coordinator review complete:** verified proposal clipping to now, fully trusted quiet-day handling and malformed-readback rejection after corrections. 56 focused model/history tests passed in 1.96 s, check-dist passed. Initial delegate also ran typecheck/build; no canvas or browser/live validation. Stage 7 continues with 7.4a.


**7.4a coordinator review complete:** pure weighting/window-search and registered read path reviewed; 57 insight/calendar backend tests passed in 1.89 s, check-dist passed. Reads cover at most 32 distinct days (the provenance assembly re-reads their in-memory snapshots, so this is not a 32-call guarantee). No UI or live evidence; monthly statistics follow in 7.4b.


**7.4b coordinator review complete:** weighted statistics, complete-day population, current-month exclusion and strict month bounds reviewed. 100 monthly/live/calendar backend tests passed in 2.46 s, check-dist passed. Partial-day coverage is separate, not part of the price population; no provider or live access. Stage 7 continues with final UI task 7.5.


## Stage 7.5 — live price insights and monthly statistics UI (manifest 2.5.173, local, coordinator review pending)

- **What:** the shared "Price insights" card is now real in the sidebar and in the local preview (one state machine and one renderer for both). **No backend change, no new
  store, no new translation keys** (the view uses English literals like the history/evidence cards; `i18n-parity` unchanged and passing).
- **Files:** `frontend/shared-dashboard/price-insights.js` (new: answer validators `parseLive`/`parseMonthly`, `monthOptions`, `compareMonths`, `createPriceInsights` request state
  machine and display model), `shared-dashboard/insight-view.js` (renderer; same `intro`/`blocks`/`caution`/`method` plus `banners`, `lines`, `details`, `table`, controls),
  `dashboard.js` (binds `data-insight-duration|month|compare|compare-previous|retry` to `actions.insightNav`), `sidebar/panel.js` (`insightView`/`insightNav`, disposed with the
  history/price-day machines), `src/api.ts` + `src/types.ts` (`getPriceInsights`, `PRICE_INSIGHTS_API_VERSION`), `dark.css`/`styles.css`, preview `prototype/sample-adapter.js` +
  `prototype/insight-fixture.js` (backend-shaped answers from the chart's own sample rows; `?insights=missing` models a young installation). Removed the old JS-computed preview
  analytics (`prototype/insights.js`, `prototype/insight-view.js`).
- **Behaviour:** opening reads once `mode live` (duration 60) and once `mode monthly` (current month, no `month` field beyond the picker's own value). Further reads are explicit:
  window length 15..720 step 15 (one live read), month picker (current month back to the 400-day first-day bound, at most 14 options; one read, kept in memory), comparison
  (explicit second month or "previous", one more read). A live read is repeated at most every 5 minutes on a repaint, or once the read interval ended and a minute has passed;
  a failure stops everything until the user presses Retry (no timer). A failed refresh keeps the earlier read labelled "Price at last read" with the failure banner. The month
  cache holds at most the selected, compared and current months, is in memory only and is dropped on charger/permission epoch/area/currency change; a new local day clears it.
  Late answers are dropped by request token, context key, and (monthly) "no longer the selected/compared month"; a duration answer must equal the asked duration.
- **Display:** current price in raw major/kWh converted once by `displayPrice` (EUR to cents); the fixed absolute band (`priceBand`, EUR cents only; other currencies neutral, own unit)
  is one status line, the relative percentile ("Compared with N of the last 30 days: higher than about P% of that time") another line, never a cheap label from the rank. Best
  published window (default 60 min): start-end in the answer's zone, duration-weighted mean, explicit "not the charging plan", its percentile labelled as an assumption (mean versus
  interval prices). Monthly: "n of N days complete" (to-date wording for the current month), partial, excluded reasons in plain words, coverage, weighted mean, low/high,
  p10/p50/p90, share of time below zero; unknown months show the reason and counts, never a price. Month comparison is side by side only when both are known, meet the minimum and
  share area/currency/basis; no difference or percentage is calculated. Basis, coverage and the actual provider labels of the held files are shown; no provider is called NordPool.
- **Validation:** a wrong charger/area/currency/mode/basis/zone/duration or malformed top level makes the whole read `invalid` ("could not be understood"); a malformed block
  (current, window, comparison, baseline counts, percentile range, statistic ordering, coverage above 100 %, known status with too few days) becomes unknown on its own, never partial.
  Old backend (`unknown_command`), missing price area and permission refusals have their own text.
- **Checks run (mocked):** `npx vitest run test/price-insights.test.ts` (31: validators, EUR conversion and band boundaries, non-EUR neutral, null versus 0, negatives, comparison cases,
  month bounds, request bounds, 5-minute cadence, failure/Retry without a storm, stale charger/area/currency/epoch/duration/month answers, selection kept on refresh) and
  `test/price-insights-panel.test.ts` (4, real panel: open reads, repaint reads nothing, explicit duration/month/compare reads, refresh keeps choices, Retry, charger switch), plus
  `node --test prototype/insights.test.mjs` (2, preview fixtures through the same validators and renderer). Neighbours: `history-day-panel`, `price-days-panel`, `price-days-nav`,
  `charge-session-panel` (28), three named `sidebar.test.ts` tests, `bundle`, `i18n-parity`, `api`, `sidebar-price-chart` (38), `node --test` boundaries/sample/daily-sample (23 pass).
  Read allow-lists in four panel tests gained `spotnav/get_price_insights`. `npx tsc --noEmit`, `npm run build`, `npm run check-dist` pass. JSDOM CSS-parse warnings are unchanged noise.
- **Known pre-existing failures, not touched:** `prototype/vehicle-evidence.test.mjs` (2 tests, `vehicle-view.js`/`evidence-view.js` are unchanged by this stage).
- **Unrun / limits:** full vitest/pytest, `sidebar.test.ts` as a whole, browser/Playwright (`prototype/browser-check.mjs` text assertions were updated but not run), `npm run prototype:build`,
  real rendering of the selectors and table at mobile width, installed behaviour. No HA, provider or charger access. Stage 7 closes after root review; Stage 8 only on request.

## Stage 8.1 — day review, default yesterday (manifest 2.5.174, local, root review pending)

- **What:** the existing Stage 7.3a history panel is now the day review; no second card, no backend change, no new store/retention, no cost. **Files:** `shared-dashboard/history-day.js` (state machine, `parseRetention`/`retainedDayMap`, `reviewPriceTarget`, `requestDayPrices`, `priceReviewNote`), `history-view.js` (nav with a retained-day `<select>`, "Show this day on the price chart" button, banners), `price-days.js` (selection kind `review`), `chart-tracks.js` (past-day lane notes), `sidebar/panel.js`, preview `prototype/sample-adapter.js` + `history-day-fixture.js` (`fixtureSessionsRequest`; fixture `oldest_evidence` moved to 2026-10-30).
- **Behaviour:** the first view of a charger/permission/zone context is yesterday (HA-local), a provisional bootstrap (loading, then the backend's facts; an unlisted yesterday shows the explicit "not in the retained list / not "did not charge"" banner). Retained days = union of the raw window (local date of the earliest of `oldest_evidence`/`oldest_by_kind` up to today), `retention.digest_days`, and the days of one `spotnav/get_sessions` read (`limit 1`, only `days[].period` with sessions) — all clamped to today−62…today; options are tagged "retained rows / summary only / sessions only" and only they can be selected (also by the date control; prev/next walk the list). The list comes from the newest answer carrying the 7.3a signals; an older integration (no signals) or failed first read offers only the shown day with a note. A failed sessions read is stated and retried only by Retry. A chosen day survives refreshes; only context change returns to yesterday. Late answers (day, charger, permission epoch, dispose, sessions) are dropped by token. Digest-only days say "Summary only; no per-minute data and no prices"; zero sessions says the Morek recorder produced none (unverified), not that the car did not charge.
- **Prices:** choosing a day (or the explicit button; never the default) asks the 7.1 machine for the held market day(s): HA day span → market dates (`reviewPriceTarget`), page ends at the later market day before the market's today (today's part comes from the live feed), chart range = the HA day's own instants, tracks align by instant; unheld = "unknown, not zero", chart unchanged. Zones differing: the nav and note state both zones and that two market days are drawn. Past-day horizons draw no proposal/effective (notes say so). Read-only: only `get_charging_history`, `get_sessions` (limit 1), `get_price_days`.
- **Checks (mocked, fast):** `npx vitest run` on `history-day`(30), `history-day-panel`(4), `price-days-nav`(26 incl. review + preview parity), `chart-tracks`(33), `price-days-panel`, `price-insights(-panel)`, `charge-session-panel`, `sidebar-price-chart`, `dark-theme`, `bundle`, `i18n-parity`, `api` (173 passed together), three named `sidebar.test.ts` tests, `node --test` boundaries/insights/sample/daily-sample (15), `npx tsc --noEmit`, `npm run build`, `npm run check-dist`, `npm run prototype:build`. Read allow-lists in `sidebar.test.ts` and `price-insights-panel.test.ts` gained `spotnav/get_sessions`.
- **Root-review correction (2.5.174, root review still pending):** the raw window comes **only** from `retention.oldest_by_kind` (`oldest_evidence` also covers longer-lived plans/capture marks and cannot prove raw rows); an older plan timestamp never creates a raw day (regression test in `history-day.test.ts`). Days proven by the sessions read alone are still offered when the retention metadata is unavailable (note says so). The pending price note says "Requested ... changes only after the read succeeds" (plus "covers two market days" when it does), never "drawn". With the fixture's oldest power row at 2026-11-07, 11-04..11-01 and the old-integration 11-03 are no longer selectable: tests now build those backend answers directly (`buildHistoryModel`) or bootstrap yesterday. Rechecked: `history-day`, `history-day-panel`, `price-days-nav`, `chart-tracks` (95 passed), `price-insights-panel`, `bundle`, `i18n-parity`, `dark-theme` (33), `tsc --noEmit`, `npm run build`, `check-dist` (2.5.174). Not rerun: full suites, `sidebar.test.ts`, browser, HA.
- **Not run / limits:** full vitest/pytest, `sidebar.test.ts` as a whole, browser/Playwright, installed/live behaviour; session-only/older-than-raw days show sessions with unknown flow; `get_sessions.days` lists session start days only (a midnight-crossing session on a later day without other evidence is not offered by itself); the 62-day clamp follows `HISTORY_DAYS_BACK`; "retained rows" days inside the raw window can still be partial/empty (the day model says so). Costs, savings and plan-versus-month totals remain 8.2/8.3.

## Stage 8.2a — spot-only cost of placed energy (manifest 2.5.175, local, root review pending)

- **What:** one pure path in `sessions/costing.py` (`session_spot`, `SpotAllocation`, `spot_block`, `session_spot_row`) used by `ChargeSession.public` (`spot_cost` + `by_delivery_day`), `sessions/summary.py` (`delivery_*`, `DELIVERY_ACCOUNTING`), `api/sessions.py` (`get_sessions`: `delivery_accounting`, `delivery_days`, `delivery_month_summary`, `delivery_month_days`) and `sessions/history.py` (`spot_cost`, `spot_cost_in_window` per row, `window_spot_cost`). Contract: `docs/api.md` "Spot-only cost and delivery days". `price_slices`/`ChargeSession.priced` and every fiscal field are untouched; the spot path is a sibling reading only stored slices (no fee, tax, fetch, store, retention or recorder change). Preview fixture `history-day-fixture.js` and `tests/fixtures/{history/answer_shape,sessions/*}.json` gained the additive keys; no UI.
- **Rules as built:** amount = sum of kWh x raw EUR/kWh x stored rate; a euro price needs rate 1, other currencies need the rate date, else `untrusted_rate`. Unknown stays `null`. Delivery day = HA-local day; each slice split by elapsed overlap (23/25 h exact, one definition of local midnight), month = sum of days. Energy with no slice is unpriced only for a period containing the whole session, else `unallocated_kwh`. Late/unassigned register energy is reported (`unplaced_*`) and never priced. Currencies: most recent session's, rest counted in `currency_exclusions`. Duplicates counted once; overlapping/conflicting slices, slice energy above session energy, bad rows price nothing and are flagged; overlapping or open sessions never `complete`.
- **Checks (fast, hass-free):** `python tools/run_isolated_logs_tests.py tests/test_stage_82a_spot_cost.py` (20 new) with `test_session_contract`, `test_session_summary`, `test_session_costing`, `test_stage_73a_history_signals`, `test_stage_63_history` = 88 passed; frontend `history`, `card-history`, `history-day` vitest files 67 passed; ruff clean; `npm run build` and `check-dist` at 2.5.175. Not run: full suites, HA-fixture tests (`test_session_cache`, store tests need the hass fixture), browser, anything live.
- **Honest limits:** (1) the provider of historical slices was never stored: `price_source` is `null`/`not_recorded`, so nothing may be labelled Nord Pool from this data; (2) `retained_price_intervals` is implemented and tested in the pure function but **no live caller has genuinely placed spans without slices**, so live answers are `recorded_price_slices` or `unknown`; (3) legacy records with only a stored fiscal cost have no slices: spot unknown; (4) allocation inside a price interval is an estimate (slices carry no finer time); (5) history excludes open sessions, `get_sessions` day/month summaries exclude them too (the `open` row is flagged); (6) delivery summaries are computed per read over sessions touching the shown windows (no cache); (7) start-day legacy buckets were deliberately not given spot fields; (8) savings (8.3) and display (8.2b) not started.

## Stage 8.2b — spot-only cost display (manifest 2.5.176, local, root review pending)

- **What:** the 8.1 day review now shows the 8.2a spot-only cost for the shown day, each session and a month. Frontend only: no backend change, no new request type, store or retention. **Files:** `shared-dashboard/spot-cost.js` (new: `parseSpotCost` validator, `describeSpotCost` one formatter for session/day/month, `sessionCostLines`, `parseDeliveryMonth`, `monthCostModel`), `history-day.js` (`buildHistoryModel` adds `cost` + per-session `costLines`; `createHistoryDay` gains the month state machine and `selectMonth`), `history-view.js` ("Spot cost of this day" and "Spot cost by month" sections), `dashboard.js` (`data-history-month` binding), `sidebar/panel.js` (`requestSessions({month})` -> existing `getSessions(..., limit 1, month)`), preview `sample-adapter.js` + `history-day-fixture.js` (backend-shaped priced/partial/negative/midnight/old-backend blocks and months). No new CSS, no translation keys.
- **Behaviour:** day cost = backend `window_spot_cost` (must carry `local_day` equal to the shown day, else "not understood"). A session shows `spot_cost_in_window` ("Spot cost in this day") and, when it crosses local midnight or differs, the whole `spot_cost` explicitly labelled "not this day's cost". Month: the opening `get_sessions` read (already made by 8.1 for the retained-day list) also supplies the current month's `delivery_month_summary` + `delivery_month_days` (no extra request). Another month is one read on user choice (`month` param; months from `available_months`, at most 24 back); at most 3 other months are cached in memory; the current month needs no read; a new local month rereads once; a failed read waits for Retry. Answers are bound to charger/permission epoch/zone key, month sequence and the still-selected month; stale ones are dropped.
- **Display rules:** amounts are backend major-currency numbers (EUR, never cents) via `Intl`; `null` = "unknown", never zero; negative is shown with a net-credit note; partial says "Partial ... for X kWh priced; Y kWh unpriced. This is not a complete total"; no sessions = "not zero cost and not proof that nothing was charged". Basis (recorded slices/retained/mixed/unknown), "spot price only, no fees/taxes/margin", price source ("not recorded"/"unknown" or the backend's named source; never "Nord Pool" unless sent), allocation estimate, coverage, unpriced reasons, unplaced/late energy, unallocated crossing-edge energy and currency exclusions are separate lines, never added. Month note: the month's unpriced energy can exceed the days' because timeless energy belongs to no single day. Open charge: noted as excluded from the current month's closed summary (and "closed sessions only" under the day). Plan `model.totals` is untouched and the day note says it is a forecast on its own cost basis. Older backend (no `window_spot_cost` / no `delivery_*`): "does not report spot-only cost", fiscal `cost`/`month_summary` are never read or relabelled. All sums come from the backend; the UI adds nothing.
- **Checks (mocked, fast):** `npx vitest run test/spot-cost.test.ts` (15: formatter units/negative/zero/null/partial/no-sessions/exclusions/malformed, midnight day vs whole, old backend, same formatter day/month, month reads/cache/stale/Retry/new month, decodeSessions accepts additive keys), `test/history-day-panel.test.ts` (6, incl. real-panel month select reads once and no writes, old backend), plus `history-day`(32), `history`, `card-history`, `price-days-nav`, `bundle`, `i18n-parity`, `dark-theme`, `contract-fixtures` (285 passed together), `node --test` boundaries/insights/sample/daily-sample (15), `npx tsc --noEmit`, `npm run build`, `npm run check-dist`, `npm run prototype:build`. One 8.1 test's "no day sections when invalid" assertion was narrowed because the month section is independent of the day read.
- **Not run / limits:** full vitest/pytest, `sidebar.test.ts`, browser/Playwright, installed/live behaviour, mobile/dark rendering of the new blocks (they reuse `history-basis`/`history-list`/`history-banner` classes only). The provider of historical slices is not stored, so the UI says "source not recorded". The month's days list is the backend's `delivery_month_days` (only days with sessions shown). Savings/summary cards (8.3) not started. Older Stage 16.2 stash untouched.

## Stage 8.3a — day-average spot savings (manifest 2.5.177, local, root review pending)

- **What:** an additive `savings` block inside the 8.2a `spot_cost` blocks of `get_charging_history` (window, session, in-window) and `get_sessions` (`delivery_days`, `delivery_month_summary`, `delivery_month_days`); contract in `docs/api.md` "Day-average spot savings". One path: `ReferenceLookup`/`add_reference`/`_savings_block` in `sessions/costing.py` plus the live resolver `sessions/savings.py` (`DayAverageReference`), wired in `api/sessions.py` (`sessions_answer`, `charging_history_answer`). No frontend, store, fetch or retention change; fixtures not changed (additive; the contract tests pass). Legacy fiscal `reference_cost`/`savings`/start-day buckets untouched.
- **Full-day proof:** the stored `Slice.day_avg_eur` is ignored. The reference is the duration-weighted average of held `PriceRepository` snapshots (memory only) for the session's price area, rows cleaned with 7.4a `clean_rows` and required to cover the HA-local day contiguously (23/24/25 h; one or two display days). Currency must equal the area's; source labels come from the held files' provenance.
- **Checks (fast, hass-free):** `python tools/run_isolated_logs_tests.py tests/test_stage_83a_savings.py` (13, through `sessions_answer`/`charging_history_answer` with a real `PriceRepository`, fetch paths forbidden) with the 82a, session contract/summary/costing, 73a and 63 history tests = 101 passed; ruff clean; `npm run build` and `check-dist` at 2.5.177. Not run: full suites, browser, anything live.
- **Limits:** the provider of recorded slices is not stored, so the same-source guard only bites for retained prices; old days beyond the held ~28 are `reference_day_not_held` (unknown, not zero); `get_sessions` public rows and start-day buckets have no savings; per-read compute (day references memoised per request); today's own reference counts only when the whole local day is held; 8.3b display not started.

## Stage 8.3b — savings and summary cards (manifest 2.5.178, local, root review pending)

- **What:** frontend only; no backend, store, request type or timer. `shared-dashboard/spot-cost.js`: `parseSavings`/`describeSavings` (one formatter for session, day and month; amount, percentage, baseline, compared kWh, reference and actual cost all the backend's `spot_cost.savings`, nothing summed or recomputed), `sessionCostLines` adds savings lines only where the backend sent them, `monthCostModel` adds `savings` and a per-day savings detail. `history-day.js`: `savings` in the day model; month read time and the bounded current-month refresh. `history-view.js`: day and month show the existing spot-cost card and a savings card side by side (`data-spot-cost` / `data-spot-savings`, existing `history-energy`/`history-basis` classes, no CSS, no new colours). Preview: `history-day-fixture.js` gained backend-shaped savings (positive, negative with negative reference, zero reference, no reference, partial subset month, session-less day) and the preview uses the same renderer.
- **Display rules:** labelled "historical estimate ... not a supplier-bill saving and not the plan's forecast"; baseline = same compared energy at the delivery day's full-day average raw spot price, no fees/taxes. The savings `actual_cost` covers only the compared kWh; when the whole priced spot cost covers more energy the card says so ("never subtract one from the other") and never pairs the whole cost with the subset reference. Percentage only when the backend sends it and `reference_cost > 0`; otherwise "Percentage not meaningful ... not 0%". Negative savings show the sign and "costs more than the reference". No `savings` key (old backend) = "not reported (not zero)"; a malformed block (wrong basis/estimate, currency differing from the spot block, comparable kWh above priced kWh, amount without costs, unknown state) = "could not be understood"; no priced reference = "unknown". Excluded kWh/reasons/days (first five plus count), unpriced kWh, reference days/source ("unknown" unless the backend names held providers; never Nord Pool by assumption) and currency exclusions are separate lines. Plan `model.totals` untouched.
- **Freshness (within the existing month state machine):** the current-month summary shows "Read at HH:MM (Home Assistant time)". On a normal repaint (`sync`, no timer) while the current month is shown and the last read is at least 5 minutes old (`MONTH_REFRESH_MS`), exactly one silent `get_sessions` re-read happens; the old figures stay on screen meanwhile, no duplicate while pending. A failed or foreign/other-month refresh keeps the old result labelled as the last successful read, never retries by itself, and the existing Retry (now also shown for this state) reads once. Past cached months are read on selection only (note says so), never refreshed by time; switching back to the current month refreshes once if old. Answers stay bound to charger/permission epoch/zone key, the sessions sequence and the expected month; a month rollover still resets as before. Raw day selection/reads are independent. The refresh also refreshes the retained-day list from the same read.
- **Checks (mocked, fast):** new `test/savings-cost.test.ts` (positive/negative/zero/null, subset vs total, zero and negative reference, missing reference, old backend, malformed, currency exclusions, identical cost text, preview-fixture renderer, refresh bounds/failure stop/Retry/stale charger/foreign month/past month) and a real-panel test in `test/history-day-panel.test.ts` (7 pass with `spot-cost.test.ts`: 32 together); `history-day`, `history`, `card-history`, `price-days-nav`, `bundle`, `i18n-parity`, `dark-theme`, `contract-fixtures` (265 passed), `node --test` boundaries/insights/sample/daily-sample (15), `npx tsc --noEmit`, `npm run build`, `check-dist`, `npm run prototype:build`. Not run: full suites, `sidebar.test.ts`, browser/Playwright, pytest, deployed/live behaviour, mobile/dark visual check of the new card (it reuses existing history classes).
- **Limits:** new strings are English literals like the other shared sidebar history text (no translation keys; i18n parity unchanged); a month's day rows show savings as a detail line, not a separate card; session rows show only brief savings; the sessions-read refresh is bounded to one per five minutes per repaint; recorded-slice provider is still not stored, so the comparison cannot name a spot source for them. Older Stage 16.2 stash untouched.
