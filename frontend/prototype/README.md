# SpotNav Enhanced dashboard prototype

This is a local, sample-only design study, not a Home Assistant card. It has no
HA/OCPP client and cannot control charging. Inputs are editable in memory only;
the action buttons are disabled. The bar chart is a non-interactive illustration,
not ECharts or actual prices. All times, values, responses and states are examples.

From `frontend/`, with Node and Python installed:

```sh
npm ci
npm run prototype:build
python -m http.server 8765 --bind 127.0.0.1
```

Open <http://127.0.0.1:8765/prototype/>. Stop the server with Ctrl+C. No HA
installation, deployment or restart is involved. `prototype/dist/` is generated
and ignored. To rebuild after editing, rerun the build command and reload.

## Intended single HA Sections dashboard

Conceptually, one Sections view would put the overview, plan controls and Morek
status in a narrow left section, Prices & Plan in a wider right section, then
recent charging and costs/savings below. On mobile the same cards stack in the
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
assuming those are compatible until separately tested. ECharts remains future
work and is not installed or bundled here.

## Browser regression check

With the local server above running, launch a Chromium-family browser in headless
mode with DevTools on port 9227 and a **separate temporary profile**, opening the
prototype URL. Run `node prototype/browser-check.mjs` from `frontend/`. The check
tests desktop and mobile sizing, order, horizontal overflow, rendered library
inputs, disabled actions, sample text, local edits and request origins; it saves
screenshots under the user's temporary `opencode` folder. This does not exercise
a real touchscreen, accessibility tree, actual HA shadow roots or dialogs.
