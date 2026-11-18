# Paste this into the implementation LLM's task

You are implementing a UI/UX redesign of the SpotNav Enhanced Home Assistant sidebar **Overview only**. You have access to the production repository and must work against its **current** source code, tests and backend contracts.

Read `SPOTNAV_UI_UX_DESIGN.md`, `README.md`, and examine `demo/spotnav-pulse-v4-interactive.html` and the accompanying visual references. The prototype is an **unchanged fictional-data design demo**. It is a visual and interaction reference only; never copy its invented scheduling behavior or mock data into production. `source-audit/spotnav-ui-source-audit-2026.md` is from an older source snapshot, so treat it as an investigation aid rather than the current truth.

Primary goals:

1. Rebuild the real Overview as editable, data-bound DOM UI, closely following the polished midnight-blue / white-BMW design without screenshot-slice shortcuts; keep icon, typography, card geometry, battery, chart and action hierarchy coherent.
2. Add a prominent, visually refined **Planned charging windows** section directly below the price chart, showing **all** validated proposed windows, durations and optional backend-supported energy/prices/costs. Synchronize row and chart selection; never replan when selecting a window. Use responsive rows/cards on mobile. Follow Section 7 of the design file.
3. Keep the right-side strategy, price perspective, charging system, freshness and recent-charging summaries legible and technically honest.
4. Preserve latest current backend scheduling, Morek/OCPP logic, action guards, retry policies, ownership, confirmation/unknown-outcome behavior, settings permissions and value units. Reuse the current APIs and semantic decoders. Many scheduling bugs have already been fixed—do not reintroduce them by backporting assumptions from the historical audit or demo.
5. Do not redesign other screens in this pass. Preserve navigation and working existing controls.

Before editing, read current `AGENTS.md`, current roadmap/safety docs, host-panel/shared-renderer code, the exact handlers/serializers and the relevant tests. State any material discrepancy between the design/reference and actual current backend semantics. Prefer an honest unavailable/provisional UI to invented data.

Implement in small, reviewable steps; add unit/browser tests for selected windows, completeness, DST, partial/unavailable data, freshness, permissions and safety-invariant preservation. Run current project build/validation commands. Provide a short implementation report, test results, before/after screenshots and a list of intentionally deferred items.

**Non-goals:** new charging optimizer, Morek profile manipulation, retries, heuristic schedule fixes, backend schema redesign, screenshot hotspots, duplicate Home Assistant navigation.
