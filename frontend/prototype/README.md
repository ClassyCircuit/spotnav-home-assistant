# SpotNav Enhanced dashboard prototype

This is a local, sample-only design study, not a Home Assistant card. It has no
HA/OCPP client and cannot control charging. Inputs are editable in memory only;
the action buttons are disabled. Both ECharts visualizations use fictional data,
not actual prices or measurements. All times, values, responses and states are examples.

From `frontend/`, with Node and Python installed:

```sh
npm ci
npm run prototype:build
python -m http.server 8765 --bind 127.0.0.1
```

Open <http://127.0.0.1:8765/prototype/>. Stop the server with Ctrl+C. No HA
installation, deployment or restart is involved. `prototype/dist/` is generated
and ignored. To rebuild after editing, rerun the build command and reload.

The local **Sample scenario** selector reloads only this prototype with `?state=`:
`mismatch`, `waiting`, `charging`, `unavailable`, `infeasible`, `partial` or
`exception`. These are hand-authored illustrations, not a planner or measurements
from a charger. The exception adds a 15:00–15:30 above-cap sample window; the
infeasible example means the displayed illustrative proposal falls short, not proof
that all possible plans are infeasible. Inputs do not save settings or control charging.
The recent-session selector is disabled; its sent window and separately authored
sample readings demonstrate a 22:30–22:45 gap and 21:45 out-of-plan flow. Coverage
is 3 of 4 quarter-hour readings in the sent hour, not complete measurement history.

For local rendering checks, append `?plan=missing` (unavailable plan tariff and
efficiency), `?plan=invalid` (invalid plan values), or `?plan=long` (eight windows).
The missing-plan scenario deliberately leaves the separate chart price fixture intact;
it is not a claim that the plan has been priced from that chart. Controls remain inert.
The compact controls list shows each window and projected SOC; use “View full window
details” or the next-window control for the complete modal, also present in both charts.

The sample Price insights panel uses the chart fixture for current and upcoming prices,
and a separate synthetic hourly historical fixture joined to the chart's past. Its
30-day classification uses duration-weighted 25th/75th percentiles, with at least
90% duration coverage and 24 intervals required. The lowest known one-hour opportunity
searches starts at Now or source interval boundaries; it is not a proposed plan.
October 2026 averages available prices by interval duration and states coverage.
The expandable method explains dates, counts and limitations. Add `?insights=missing`
to mask the insight inputs for a missing-data example; the separate chart remains intact
and the scenario is labelled. These are fictional fixed-day samples, not live history,
market forecasts, charging costs or savings; same-weekday comparisons are not used.

Both **Prices & plan** alternatives appear together, sharing a fixture and plan;
this is a temporary comparison, not a proposal for two final cards. The overview
slider and chart dragging pan; ordinary wheel over a chart zooms, and the labelled
zoom/reset buttons are keyboard accessible. Wheel over the chart is consumed for
zoom, so scroll the page with the scrollbar, keyboard, or outside the chart.
The initial view starts 1.5 sample hours before Now; Full horizon reveals all available
prices. Viewport changes snap to sample interval boundaries; plan boundaries and Now
are not snapped. Labels are clock-anchored and adapt to width/zoom, with day context.
The band shows the fictional 2026 dates and midnight lines; missing price spans are
hatched and are never zero. Labels are shortened or omitted for very narrow day slices.
The plot consumes touch gestures; scroll outside it. Emulated pinch and taps worked in
headless Edge, but physical touch remains unverified. This fixed-day sample is not a
timezone/DST implementation.
The fictitious 08–10 Nov fixture is based on the supplied example hourly values;
as in the bar example, quarter-hour fluctuations are synthetic, not verified
Nord Pool data. EUR c/kWh is an illustrative variable-cost basis including fees
and taxes. Fixed 24-hour days are not real timezone/DST handling. All three days
are available in this sample, not a promise that future prices are always available.
The 30/45/60 c/kWh color bands are illustrative only. A 35 c/kWh soft cap,
low-price opportunities and green-gradient hand-authored proposal windows are
distinct concepts. A continuous window spans several prices and ends partway
through an interval; another starts after a real pause. The next-window button
opens the same complete plan in a native browser modal; outside click, Escape or Close
dismisses it. The plan also appears under the simulated controls. SOC after each window
is a cumulative estimate using the stated starting SOC, usable capacity and wall-to-battery
efficiency, not a measurement or guarantee.
The pale track above each plot also marks the exact proposal boundaries; the legend
identifies it separately from price colors.
It is not optimizer output. Negative and missing price fixtures are tested
separately, rather than represented as real prices.

## Intended single HA Sections dashboard

The local comparison puts overview and simulated controls side by side above two full-width price alternatives,
with other sample cards flowing below. On mobile the same cards stack.
This is a composition proposal, not installable YAML or a modification to any
existing view; final Sections column spans and HA behavior need in-HA validation.

## Components and assets

`@awesome.me/webawesome` **3.14.0**, the public Core npm package, declares the
MIT license (copyright Fonticons, Inc.); its license is copied into the local
build output. The prototype bundles selected button, input, badge and progress-bar
components and the package theme CSS with esbuild; no Pro package is used. The
build includes dependency license comments where provided. The package's icon
resolver can default to a remote Font Awesome host: this prototype avoids icon
components and uses an original inline geometric lightning SVG (project-authored,
no third-party icon license). Its browser check verifies no off-origin requests. Do not assume
other Web Awesome controls are offline-safe without checking their assets.

For a future HA card, bundle selected modules and CSS locally into the distributed
card assets, retain the Web Awesome MIT license and audit/include all applicable
transitive licenses and any local icon/font notices. Do not use a CDN. HA custom
cards use shadow DOM, so theme CSS would need to be included in each card's shadow
root; inherited documented CSS custom properties can map HA theme colors to the
shared tokens. Do not reach into private HA or component DOM. Global element
registration/version collisions, light/dark theme mapping, and CSS isolation need
testing in a real HA instance before shipping. This standalone study uses the
browser's native modal dialog, not a Web Awesome dialog; HA shadow-root behavior,
popovers, overlays, physical touch and HA's actual Sections layout remain unverified. Avoid
assuming those are compatible until separately tested.

The prototype pins Apache ECharts **6.1.0** (Apache-2.0), using a locally bundled
subset and Canvas renderer; its Apache LICENSE and NOTICE are copied to the build
output. ECharts depends on zrender **6.1.0** (BSD-3-Clause), whose license is also
copied. esbuild retains available dependency legal comments in the generated JS.
No chart resources come from a CDN. Future shipped cards must include these files
and audit all bundled transitive notices, and should load chart code only where
needed. The sample chart module is a starting point, not production Stage 7: it
uses a fixed sample hour axis, not real timestamps, timezone/DST handling or source
data. The custom bars use interval start/end; the line uses explicit horizontal
endpoints and null breaks rather than joining gaps. The
fictional axis uses relative hours (24-hour days), not real calendar or DST logic.
Production must use the configured local timezone and handle midnight and 23/25-hour
DST days, and verify actual historical and future publication availability first.
The separate sample power chart holds each reading for at most 15 minutes for
display and leaves the explicit missing interval blank; the independent meter
counter fixture is not calculated from the curve or the plan.

## Browser regression check

With the local server above running, launch a Chromium-family browser in headless
mode with DevTools on port 9227 and a **separate temporary profile**, opening the
prototype URL. Run `node prototype/browser-check.mjs` from `frontend/`. The check
tests desktop and mobile sizing, overflow, both variants, chart data endpoints,
mouse wheel, slider, zoom/reset, desktop hover, modal keyboard/close/focus,
simulated touch, disabled charger actions and request origins. It saves full-page,
individual-card, zoomed-card, modal and rendered edge-fixture screenshots under the user's
temporary `opencode` folder. The check reports whether emulated taps needed its
programmatic tooltip fallback; pinch emulation is not physical-touch validation.
It does not validate real touch, accessibility tree or actual HA shadow roots. Run
`node --test prototype/sample.test.mjs prototype/insights.test.mjs prototype/daily-sample.test.mjs`
for sample arithmetic, price insights, scenario and history checks.
