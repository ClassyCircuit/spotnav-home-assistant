# Morek schedule experiment (manual)

This is an **opt-in diagnostic**, not a replacement for SpotNav's normal charger
control. The panel is opened with **Morek schedule details** below the SpotNav card.
It reads and writes through the *existing* Home Assistant OCPP connection; it
does not start another OCPP server. Only an administrator can send, fetch, or remove the test profile.

## First test

1. Check that Morek is connected to HA OCPP on connector 1. Ensure no other
   controller is sending start/stop or current-limit commands. Do not disable
   household load protection for this test.
2. Set SpotNav's plan current to **16 A** and charge periods to **3** or fewer. Choose a plan whose first
   charging window is still in the future, within the next 48 hours. A plan
   that stops early after reaching an energy target cannot be sent: a stored
   charger schedule cannot perform that target-based stop.
3. Pause SpotNav Auto **Until I resume**. The Send button refuses to run without
   this pause, because SpotNav's usual timer-based control is still present.
   Open **Morek schedule details** to see **Preview — calculated, NOT sent**.
   This shows the proposed 0/16 A transitions and why Send is disabled, if applicable.
   It is distinct from the Plan settings popup, the last sent profile, and the
   charger effective readback. **Recalculate preview** reads the latest plan without
   contacting Morek. Send recalculates with the current clock, so the precise
   start timestamp can differ from the preview. The server checks that the
   absolute charging windows and settings revision still match the preview;
   otherwise Send refuses without uploading. Review again before confirming.
4. Open **Morek schedule details** and press **Send current plan**. The panel
   shows the exact 0/16 A transitions sent, the charger reply, and the time.
5. Press **Refresh from Morek** at any time, even before sending. It shows the
   effective current limits reported by `GetCompositeSchedule`, not a list of
   installed profile IDs. Compare them with the Sent rows; **NOT verified**
   means they differ or the read failed. Watch actual charger measurements at
    the transitions as a separate check.

### Readback verification (2.5.6+)

Send keeps the real schedule at **stack level 1** and checks it immediately.
If the upload was Accepted but readback differs or is unavailable, SpotNav
schedules up to three additional **read-only** checks, approximately 30, 75 and
120 seconds after the initial check (charger response time can add delay).
No automatic resend, clear, priority escalation, start/stop or Auto resume occurs.
These short-lived checks belong to that upload, independent of whether the panel
is open. A new Send, removal request or integration unload cancels them. HA
restarts do not silently resume them; use Refresh from Morek if interrupted.

**Awaiting follow-up readback — NOT verified** does not mean the requested limits
are active. After the last unsuccessful check, the mismatch remains visible and
a warning is logged. Manual Refresh can still verify a later matching response.

The panel exposes Morek's actual reported duration, schedule start and units.
Verification requires that reported coverage reaches one hour past the final
stop; a missing duration is **not** assumed to equal the requested duration.
Matching transitions may differ by up to **90 seconds**: the maximum observed
drift and tolerance are displayed, and a drifting match is labelled **NOT exact**.
This tolerance is not a correction of Morek's clock or a guarantee of precise
switching. Neither Accepted nor a matching readback proves physical charging.

## Selective cleanup (2.5.5+)

Profile `42001` contains the **real calculated SpotNav schedule**. A subsequent
Send replaces that same profile; cleanup is not required between updates.
Removal is for withdrawing SpotNav's schedule, not a prerequisite for each Send.
Other profiles can coexist and affect the effective limits.

Use **Remove SpotNav schedule** (called **Remove test profile 42001** in 2.5.5),
then confirm the warning. This sends OCPP 1.6
`ClearChargingProfile` with **only `id: 42001`** to the verified Morek connection;
it never sends an empty request or calls HA's generic `ocpp.clear_profile`.
No other profile IDs are deliberately removed. Removing the limit can increase
the effective current allowed by other profiles. Auto stays paused as configured.

The panel keeps the last Sent rows as history and separately records the cleanup
request time and reply, then automatically fetches fresh effective limits. An
`Accepted` reply acknowledges removal; `Unknown` or a timeout is not confirmation
of removal. A timeout may still have taken effect. Composite readback is not an
inventory proving profile 42001 absent. Inspect the readback before resuming any
controller. Cleanup is a separate manual action, not automatic after Send.

If the car is unplugged, an upload/readback test cannot demonstrate transitions
in a live charging transaction or measure physical charging. An effective 16 A
limit does not mean 16 A is flowing. Recheck whether it is still unplugged before
a later hardware test; do not assume its state remains unchanged.

The record of the last request and readback survives HA restarts; its timestamps
show how old it is. Sending does **not** authorize a new transaction, adjust
SpotNav's manual overrides, remove other OCPP profiles, automatically follow
replans, or clear the final 0 A limit. Resume SpotNav Auto only after deciding
how to handle the test profile: its live start/stop controller otherwise conflicts
with a stored profile. A reported `Accepted` is not proof the car will charge.
This diagnostic is limited to OCPP station ID `3020002509120029`, connector 1.
HA OCPP may name the charger with an alias. The panel shows both SpotNav's
configured OCPP ID and the physical ID resolved by HA OCPP; an alias is accepted
only when it resolves to that exact station. If it is not resolved, verify the
charger is connected and SpotNav's OCPP connector identity is configured.

This integration calls HA OCPP's connected ChargePoint through its internal
Python API because `ocpp.set_charge_rate` does not expose the charger reply and
HA OCPP has no `GetCompositeSchedule` action. That API can change with HA OCPP
updates. A user test on 2026-11-08 received an Accepted upload but a mismatching
16 A effective readback. Neither the sent schedule's operation nor selective
cleanup has yet been verified in a physical charging session.
