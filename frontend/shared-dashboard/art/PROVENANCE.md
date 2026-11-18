# Hero artwork provenance (Stage 20.2b)

Both images derive from the **user-supplied design prototype**
`samples/spotnav-ui-handoff/demo/spotnav-pulse-v4-interactive.html` (the Pulse v4 interactive mock-up). No other source,
download or generator was used by this repository's tooling.

| File | What it is | Derivation |
| --- | --- | --- |
| `bmw-morek-scene.webp` (1800×675) | White 2022-style BMW iX3 plugged into a wall-mounted Morek charger, cable visibly connected. No text, SOC or other value is baked in. | Byte-identical to the **first** embedded WebP of the prototype (`neo-car-photo`; sha256 prefix `b5a0591e45fe4866`, 107 674 bytes). Not re-encoded. |
| `bmw-neutral.webp` (930×635) | The same car without charger, port or cable, used for unplugged / unknown / stale states. | A **crop** (x 0–930, y 40–675) of the scene above, re-encoded as WebP (mean pixel difference to the source crop ≈ 1.4 of 255). No retouching. |

The prototype's other two embedded WebPs (856×265) have a battery value ("64%") baked in and are **not used**.

## Rights

The prototype's images look like generated/illustrative artwork. Their origin and licence could **not be verified from this
repository**: they were supplied by the project owner as part of the design handoff, and the design document calls the asset
"illustrative" and lists its safety to ship as an open question. Shipping them is therefore **the owner's decision**: confirm
they may be distributed with the integration, or replace both files (CSS uses `background-size: cover`, so other dimensions work).

## Honesty rules

The images are decorative only (`role="img"` with a text description). The cable picture is used only for a fresh connected
report; unplugged, unknown and stale states use the neutral crop. Nothing animates and no image implies power flow. If an image
fails to load, the gradient background and all text remain.
