"""Installation-wide, read-only shared dashboard panel and its local assets."""

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .card_asset import async_manifest_version

PANEL = "spotnav-enhanced"
ASSETS = Path(__file__).parent / "www" / "sidebar"


async def async_setup_sidebar(hass):
    """Register once per HA installation, not once per config entry.

    Domain setup persists for the lifetime of HA, including entry reload/unload.
    Consequently the static route and panel must not be removed per entry.
    """
    state = hass.data.setdefault("spotnav_sidebar_registration", {})
    if state.get("panel"):
        return
    if hass.http is None:
        return
    if not await hass.async_add_executor_job((ASSETS / "panel.js").is_file):
        raise FileNotFoundError("SpotNav sidebar bundle missing; run npm run build in frontend")
    if not await hass.async_add_executor_job((ASSETS / "panel.css").is_file):
        raise FileNotFoundError("SpotNav sidebar styles missing; run npm run build in frontend")
    if not state.get("assets"):
        await hass.http.async_register_static_paths([StaticPathConfig("/spotnav-sidebar", str(ASSETS), cache_headers=True)])
        state["assets"] = True
    version = await async_manifest_version(hass) or "unknown"
    await panel_custom.async_register_panel(
        hass, PANEL, "spotnav-enhanced-panel", sidebar_title="SpotNav Enhanced",
        sidebar_icon="mdi:ev-station", module_url=f"/spotnav-sidebar/panel.js?v={version}",
        require_admin=False, handle_safe_area=True,
    )
    state["panel"] = True


def async_remove_sidebar(hass):
    """Remove the panel at domain shutdown; static HTTP routes remain HA-owned."""
    state = hass.data.get("spotnav_sidebar_registration", {})
    if state.pop("panel", False):
        frontend.async_remove_panel(hass, PANEL, warn_if_unknown=False)
