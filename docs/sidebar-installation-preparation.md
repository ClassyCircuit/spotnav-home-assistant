# SpotNav Enhanced sidebar: future installation preparation

This is preparation for a **future separately approved** installation, not an
installation record or permission to deploy, restart Home Assistant, or operate a
charger. Stage 5.4c has a local price binding but remains incomplete pending the
contract and browser checks listed in the development handoff.
Automatic Morek dispatch remains unarmed. Actual HA and physical touch are unverified.

The integration registers one installation-wide `SpotNav Enhanced` custom sidebar
panel when the domain is set up. It serves its versioned JavaScript and CSS locally
from `/spotnav-sidebar/`; the existing Lovelace card and user dashboards are not
replaced by panel registration. The release build embeds ECharts and Web Awesome
in the panel bundle and ships their applicable licenses and notices in
`custom_components/spotnav/www/sidebar/`. No CDN is needed for these assets.

Before any future update, review the release, back up the existing integration and
HA configuration using the user's normal process, and obtain specific approval for
the chosen installation method and any restart. After approval, install the complete
reviewed integration release, including its matching `www/sidebar/` assets, using
the user's preferred supported integration update process. Do not copy only the
panel bundle onto a different backend version. Do not replace user Lovelace views
or remove the existing card. Restart only if separately approved and required by
the update process; then verify the loaded integration version and sidebar in HA.

Begin any separately approved live validation with read-only checks: choose a
charger, verify price availability and units against the configured source, and
check proposal and health labels. The dashboard and Morek status are separate
observations. An accepted schedule or effective readback is not evidence of
physical charging. Settings changes, Morek fetch/send/clear, charging actions,
and hardware tests each require their own appropriate approval and interlocks;
opening the panel must not trigger them. If the panel or source is unavailable,
retain the existing card and investigate rather than replacing user dashboards.
