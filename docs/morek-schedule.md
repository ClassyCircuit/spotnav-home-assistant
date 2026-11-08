# Morek schedule experiment (manual)

This is an **opt-in diagnostic**, not a replacement for SpotNav's normal charger
control. The panel is opened with **Morek schedule details** below the SpotNav card.
It reads and writes through the *existing* Home Assistant OCPP connection; it
does not start another OCPP server. Only an administrator can send or fetch.

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
updates. No charger hardware test has yet confirmed this code on Morek.
