The smallest ordinary-start extraction is complete; admission is not wired. Requested-current selection is now a read-only helper, and in-memory attempt evidence distinguishes possible phase/current preparation from an adapter start that was not attempted, not executed, executed or left unknown.
This is a partial refactor, not a full preparation/dispatch/outcome split. Existing session and retry semantics remain unchanged: after an interrupted adapter call, a session feed may still report “not executed” even though the new evidence says the outcome is unknown. That must be resolved before starts can safely be gated.
Changed files

- custom_components/spotnav/execution/controller.py
- tests/test_start_preparation.py and tests/test_window_start_retry.py
- docs/morek-execution-audit.md
- custom_components/spotnav/manifest.json and www/spotnav-card.js — version 2.5.12 and rebuild
  Checks
- 9 controller-level characterization cases passed using the real controller with a minimal standalone HA fixture and mocked charger calls; this was not the full HA test environment.
- The full start-preparation, reservation, retry and controller pytest invocation failed before collection on Windows because fcntl is unavailable.
- Ruff, Python compilation, frontend build, check-dist and git diff --check passed.
  The audit documents the first possible physical write, required lock order and remaining outcome work. No live command, HA change, activation, deployment, restart, commit or push occurred. A2.2 and exclusive ownership remain incomplete.
