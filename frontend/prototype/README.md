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

In **Prices & plan**, switch between **A · Bars** and **B · Stepped area**;
both use the same fixture and plan. The slider provides an overview and drag
handles for the visible horizon; drag the chart to pan, scroll/pinch to zoom,
or use Zoom in and Reset overview. This comparison is temporary, not a proposal
for two final dashboards. Shading means selected proposal; prices at or below
the sample cap are potential opportunities, not automatically selected windows.
The sample displays yesterday, today and tomorrow until 12:00; a separate hour
today is missing. Grey bands mark missing prices, never zero. The last selected
window is a half-hour; negative costs represent a fictional negative tariff.

## Intended single HA Sections dashboard

Conceptually, one Sections view would put the overview, plan controls, charger
health and costs in a narrow left section, Prices & Plan and recent charging in
a wider right section. On mobile the same cards stack in the
prototype's document order: overview, prices, controls, Morek, history, costs.
This is a composition proposal, not installable YAML or a modification to any
existing view; final Sections column spans and HA behavior need in-HA validation.

## Components and assets

`@awesome.me/webawesome` **3.14.0**, the public Core npm package, declares the
MIT license (copyright Fonticons, Inc.); its license is copied into the local
build output. The prototype bundles selected button, input, badge and progress-bar
components and the package theme CSS with esbuild; no Pro package is used. The
build includes dependency license comments where provided. The package's icon
resolver can default to a remote Font Awesome host: this prototype avoids icon
components and its browser check verifies no off-origin requests. Do not assume
other Web Awesome controls are offline-safe without checking their assets.

For a future HA card, bundle selected modules and CSS locally into the distributed
card assets, retain the Web Awesome MIT license and audit/include all applicable
transitive licenses and any local icon/font notices. Do not use a CDN. HA custom
cards use shadow DOM, so theme CSS would need to be included in each card's shadow
root; inherited documented CSS custom properties can map HA theme colors to the
shared tokens. Do not reach into private HA or component DOM. Global element
registration/version collisions, light/dark theme mapping, and CSS isolation need
testing in a real HA instance before shipping. The standalone page only verifies
the components used here; dialogs, popovers, focus trapping, clipping, overlays,
touch interaction and HA's actual Sections layout remain unverified. Avoid
assuming those are compatible until separately tested.

The prototype pins Apache ECharts **6.1.0** (Apache-2.0), using a locally bundled
subset and Canvas renderer; its Apache LICENSE and NOTICE are copied to the build
output. ECharts depends on zrender **6.1.0** (BSD-3-Clause), whose license is also
copied. esbuild retains available dependency legal comments in the generated JS.
No chart resources come from a CDN. Future shipped cards must include these files
and audit all bundled transitive notices, and should load chart code only where
needed. The sample chart module is a starting point, not production Stage 7: it
uses a fixed sample hour axis, not real timestamps, timezone/DST handling or source
data. The custom renderer uses interval start/end for actual sample width, and
each stepped segment ends at its own interval end rather than joining gaps. The
fictional axis uses relative hours (24-hour days), not real calendar or DST logic.
The separate sample power chart holds each reading for at most 15 minutes for
display and leaves the explicit missing interval blank; the independent meter
counter fixture is not calculated from the curve or the plan.

## Browser regression check

With the local server above running, launch a Chromium-family browser in headless
mode with DevTools on port 9227 and a **separate temporary profile**, opening the
prototype URL. Run `node prototype/browser-check.mjs` from `frontend/`. The check
tests desktop and mobile sizing, order, horizontal overflow, both variants, chart
data boundaries, actual zoom/reset and mouse slider drag, negative-price mouse and
emulated-touch tooltips, library inputs, disabled charger actions, sample text,
local edits, disclosure and request origins; it saves four screenshots under the user's
temporary `opencode` folder. It sends an emulated touch event but does not validate
a real touchscreen, touch-drag/pinch, accessibility tree, actual HA shadow roots or dialogs. Run
`node --test prototype/sample.test.mjs` for sample arithmetic and missing inputs.
