# 5.4b2 verification matrix (mock boundaries)

| Case | Evidence / remaining gap |
| --- | --- |
| Settings success, invalid, denial, rejection, conflict | `test/sidebar.test.ts` actual mounted panel |
| Settings malformed, reconcile failure, stalled write and late completion | `test/sidebar.test.ts`; timeout leaves draft/conflict, no retry while request pending |
| Settings permission loss and charger switch during save | `test/sidebar.test.ts`; late responses ignored |
| Settings disconnect and return during save | `test/sidebar.test.ts`; unknown outcome and late completion remain blocked |
| Settings teardown during save | same-element and replacement-panel cases retain unknown outcome and block retry/reload until settlement; explicit reload required |
| Pause/Resume explicit admission, stale input, rejection, duplicate action | `test/sidebar.test.ts`; mock browser exercises both |
| Pause/Resume fresh matching confirmation | `test/sidebar.test.ts` rejects pre-dispatch timestamps |
| Pause/Resume timeout, permission change and charger switch | parameterized actual-panel cases cover both action timeouts and shared lifecycle guards; both actions require fresh matching confirmation |
| Send/Clear confirmation, cancellation, admin, preview/permission change, uncertainty, fetch | `test/sidebar.test.ts`; built-panel browser mocks Send/Clear |
| Send identity/dashboard/status/charger mutation during confirmation | parameterized `test/sidebar.test.ts` refuses dispatch |
| Clear identity, permission or support change during confirmation; backend refusal and timeout | actual-panel cases refuse stale dispatch, display rejection or unknown, do not automatically retry, and target only profile 42001; backend interlocks unchanged |
| Timed-out Send | `test/sidebar.test.ts`, unknown outcome and no automatic retry |
| Independent periodic refresh, stuck status, switch, reconnect, pending status across action and dashboard across permission change | `test/sidebar.test.ts` verifies single-flight and rejection of stale results |
| Dialog/chart identity, zoom, selection and scroll | `prototype/shared-browser-check.mjs`, desktop and emulated mobile |
| Sidebar simultaneous dialog/draft/critical warning, debug button focus, save/conflict and charger switch | actual panel tests and built-panel `sidebar/browser-check.mjs`, including delayed old response during switch |
| No implicit charger operation | actual panel tests and mock browser request assertions |

5.4b2 is complete for local implementation and the bounded mocked verification above,
pending coordinator review. No mock demonstrates actual HA, physical touch, or charging.
