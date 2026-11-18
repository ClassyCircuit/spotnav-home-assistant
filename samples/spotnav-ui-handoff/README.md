# SpotNav Enhanced — UI/UX Implementation Handoff

**Purpose:** Give an implementation LLM enough context to rebuild the real SpotNav Enhanced **Overview** with the approved high-fidelity look while preserving the **current working backend** and existing non-Overview screens.

## Start here

1. Read [`SPOTNAV_UI_UX_DESIGN.md`](SPOTNAV_UI_UX_DESIGN.md) **completely**. This is the primary design handoff and acceptance specification (~8,100 words).
2. Open [`demo/spotnav-pulse-v4-interactive.html`](demo/spotnav-pulse-v4-interactive.html) in a browser. It is an **unchanged, self-contained fictional-data prototype**. Study visual style, information hierarchy, chart interactions, edit drawer, and responsive behavior. **Do not paste its simulation logic into production.**
3. Review [`reference/spotnav-pulse-v4-desktop.png`](reference/spotnav-pulse-v4-desktop.png) and [`reference/spotnav-pulse-v4-mobile.png`](reference/spotnav-pulse-v4-mobile.png) for the actual interactive prototype appearance. [`reference/approved-overview-concept.png`](reference/approved-overview-concept.png) documents the brighter, polished visual target; it is not a functional screenshot.
4. Treat [`source-audit/spotnav-ui-source-audit-2026.md`](source-audit/spotnav-ui-source-audit-2026.md) as an **old navigation map to the backend**, not as the latest scheduling logic or authoritative schema. The code and tests in the target repository supersede it.
5. Read [`IMPLEMENTER_START_PROMPT.md`](IMPLEMENTER_START_PROMPT.md) for a ready-to-paste instruction to an agent who has access to the real repository.

## Explicit requests and constraints

- **Do not edit the included v4 demo.** It is packaged byte-for-byte unchanged.
- Implement real UI components and charts, **not screenshot slices/hotspot overlays**.
- Preserve current backend scheduling, OCPP/Morek ownership, retries, admission guards, costs, price handling, permissions and write results. These have evolved since the older audit.
- In this phase, **redesign the Overview only**; keep existing Explore, History, Settings and unrelated HA pages working.
- **Add a beautiful `Planned charging windows` section on the Overview:** list *all* proposed windows with start/end, duration and optional valid forecast values, linked to the price chart. Detailed design in Section 7.
- Don't confuse proposed, sent/ACK, readback, transaction and measured flow; don't turn `unknown` into zero.
- The HTML demo contains **fictional** information and simulated actions. It cannot charge a vehicle.

## Package contents

```
spotnav-ui-handoff/
├── README.md
├── IMPLEMENTER_START_PROMPT.md
├── SPOTNAV_UI_UX_DESIGN.md
├── demo/
│   └── spotnav-pulse-v4-interactive.html
├── reference/
│   ├── spotnav-pulse-v4-desktop.png
│   ├── spotnav-pulse-v4-mobile.png
│   └── approved-overview-concept.png
└── source-audit/
    └── spotnav-ui-source-audit-2026.md
```

**Success:** The live HA sidebar Overview looks and feels like the approved visual direction, gains a practical planned-window list, and remains exactly as safe and correct as the latest production charging implementation.
