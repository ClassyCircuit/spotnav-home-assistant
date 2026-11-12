# Shared dashboard source (5.4a)

`dashboard.js` exports `mountDashboard(root, adapter)`. The preview in
`../prototype/dashboard.js` calls this exact function; it does not have its own
layout or chart. `styles.css` and `dark.css` are the shared styles. Bundle these
and the imported Web Awesome and ECharts modules locally; preserve the notices
in `THIRD-PARTY-NOTICES.txt` and the dependency license/notice files copied by
`../prototype/build.mjs`. System fonts are used; no remote font is required.

The adapter is required, not discovered globally:

```js
const dashboard = mountDashboard(root, { model, format, actions });
dashboard.update({ model: nextModel, format, actions });
dashboard.dispose();
```

`update` still remounts the view, but experimentally restores edited field values,
dialog visibility, identified focus and chart zoom. This is not yet a production-safe
incremental update: the dialog is actually closed and reopened, text selection and
arbitrary nested scroll positions are not preserved, and revision/identity safety is
the host's responsibility. Set `draftKey` to a stable charger-and-revision identity;
changing it clears drafts. This has not been integrated with a real settings save.
`dispose` disconnects observers, removes listeners,
disposes ECharts and clears the root. Mounting again on the same root disposes
the previous instance. The host owns subscriptions, async requests, permissions,
revision checks, errors, and their cleanup. Updates are not atomic backend reads.

## View model

See `../prototype/sample-adapter.js` for a complete *fictional* example. Supply
validated values; omitted data is unknown/unavailable, never a sample default.
Host-supplied display strings and formatter results are treated as text. No
field accepts HTML. The current presentation is English. The fixture uses EUR/cents;
live hosts must set `format.currency` to an authoritative ISO currency or `null`.
An optional `model.totals` supplies backend totals instead of summing windows.
The sample chart and its price units are still EUR/cents-specific and must not be
used with live data until 5.4c replaces those assumptions.

- `windows`: array of `{start,end,energy,cost,centsPerKwh,projectedSoc,control}`;
  `null`/missing means unavailable, `[]` means known empty. Times are numeric
  hours on the same axis as prices; energy is wall kWh, cost EUR, price c/kWh.
  `control: 'minimum-exception'` adds the exception label. The host supplies
  projections and plan values; the UI is not a planner. `assumptions` contains
  `startingSoc`, `capacityKwh`, `efficiency`; invalid values render unknown.
- `vehicle`: `{status,detail,power,policy,soc,stale,lowSocWarning}`. Power is a
  separately sourced display string, never inferred from a plan. `settings` has
  `{target,minimum,cap,readyBy}`; `cap` is EUR/kWh for the editor. `untilDeadline`
  and `targetNote` are display strings. The host is responsible for freshness,
  status, feasibility and price-basis interpretation. Invalid numeric SOC and
  energy estimates do not become zero.
- `chart`: `{prices,now,deadline,horizon,cap,bands,comparison}`; `prices` are
  `{start,end,cents}` intervals and `horizon` is `[start,end]`. Three strictly
  increasing numerical `bands` are explicit host-supplied visual thresholds,
  never universal price judgments. Invalid/missing price intervals are gaps;
  missing chart prerequisites show unavailable. `comparison: true` adds the
  old bar view for local comparison; default is the chosen stepped area.
- `history` is optional: title/subtitle/session/sent/outside/coverage/note are
  display strings; `readings` are `{time,kw}` with `kw: null` for gaps, and
  `sentHistory` is `{start,end}`. Both are independently sourced, not inferred
  from the proposal. Missing history renders unavailable. `axis` may supply
  positive `interval` and `max` for a known scale.
- `evidence` contains text fields `status`, `context`, `proposal`, `sent`,
  `readback`, `measurement`, `dispatch`. Missing evidence displays Unknown.
  ACK, effective readback and measured flow remain distinct. Diagnostic
  send/refresh buttons are intentionally disabled in this foundation.
- `insights`, if available, has `intro`, `blocks` (`title`, `value`, `status`,
  `detail`, `extra`), `caution`, and `method`; otherwise it is unavailable.
  `warning` optionally has `title` and `detail`. `labels` supplies host-specific
  context and explanatory strings; see the sample adapter. `sample: true` adds
  SAMPLE tags. `scenarios` is an optional `{label,selected,options,note}` picker.
- `format.time` and `format.day` are required functions. To show a chart, also
  supply `date`, `days`, `priceGaps`, `stepSegments`, `stepPoints`, `snapRange`,
  `initialRange`, and `timeTicks`; optional `tooltipDate` includes the desired
  year/timezone. These functions are trusted host code, not backend strings.
  Output used in HTML tooltips is escaped; labels in overlays use `textContent`.
  See the sample helpers for their current signatures, but **do not use their
  fixed fictional dates, quarter-hour boundaries or 24-hour-day logic for live
  prices**. The host must ensure coherent, ordered intervals and source-aware
  calendar/timezone/DST formatting.
- `actions.selectScenario(value)` is optional. `actions.save(rawStrings)` only
  runs if both the callback and `model.canSave === true` are supplied. The host
  must authorize, validate, check revisions and handle failures; raw form values
  are not settings validation. The sample adapter provides no save action.

The 5.4b1 HA sidebar in `../sidebar/` uses this same entry point and a separate
read-only real adapter. It isolates the bundled styles in a shadow root; previously
registered `wa-*` components take precedence and mixed versions are unverified.
5.4b2 must connect guarded controls and replace the remount update lifecycle.
The shared styles currently include global `:root` and `body` rules. 5.4c must
implement source-boundary navigation, actual price/timezone/DST handling,
published availability, and real chart data; this sample hour-axis chart is not
proof of those behaviors. Chart viewport restoration is experimental. Physical touch,
actual HA mobile app and theme behavior remain unverified.
