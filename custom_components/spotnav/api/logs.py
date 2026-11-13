"""The SpotNav log viewer's command, `spotnav/get_logs` (administrators only).

What it reads: SpotNav's own bounded log buffer (`log_buffer.py`), a handler on the `custom_components.spotnav`
logger tree inside Home Assistant Core's logging, already kept for the debug bundle. It is not a separate store and
not an app/container log: SpotNav is an integration, so Home Assistant has no per-integration log of its own.
Nothing is enabled or raised: no level is changed and no OCPP or websocket logger is touched.

Retention and limits, reported to the viewer: INFO and above since the start (300 records), DEBUG only when
DEBUG is enabled for SpotNav (200), WARNING and above of the last 24 hours also from before a restart (500). Older
records, and everything from other integrations, are only in Home Assistant's own log (Settings > System > Logs, or
`home-assistant.log`).

"Live" is polling: the viewer asks again with the `latest_seq` it received as `after_seq`; there is no push stream.
A changed `boot_id` (Home Assistant restarted) means the numbering restarted and the viewer loads afresh.

Permission: an administrator only (`spotnav_not_admin` otherwise, no records). Every record is scrubbed with the debug
bundle's `Scrubber` (secrets, webhook paths, bearer tokens, e-mail addresses, user names, the home location).
"""

from __future__ import annotations

from typing import Any, Final

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback, HomeAssistant

from ..const import DOMAIN
from ..debug_bundle import _scrubber, redact_bundle
from ..log_buffer import (
    LEVELS,
    MAX_DEBUG_RECORDS,
    MAX_QUERY_RECORDS,
    MAX_QUERY_TEXT,
    MAX_RECORDS,
    MAX_WARNINGS,
    WARNINGS_S,
)
from ..runtime import domain_data
from .common import ERROR_NOT_ADMIN, is_admin, send_unsupported_version

LOGS_API_VERSION: Final = 1
ERROR_INVALID_FILTER: Final = "spotnav_logs_invalid_filter"
ERROR_UNAVAILABLE: Final = "spotnav_logs_unavailable"

#: What the viewer must say about the source (never claim more than this).
RETENTION: Final = {
    "source": "spotnav_log_buffer",
    "streaming": False,
    "info_records": MAX_RECORDS,
    "debug_records": MAX_DEBUG_RECORDS,
    "warning_records": MAX_WARNINGS,
    "warning_retention_s": WARNINGS_S,
    "fallback": "Settings > System > Logs (Home Assistant Core log) for older records and other integrations",
}


def _answer(**fields: Any) -> dict[str, Any]:
    return {
        "api_version": LOGS_API_VERSION,
        "ok": False,
        "error": None,
        "boot_id": None,
        "latest_seq": 0,
        "entries": [],
        "matched": 0,
        "truncated": False,
        "restarted": False,
        "retention": RETENTION,
        **fields,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "spotnav/get_logs",
        vol.Optional("api_version"): object,
        vol.Optional("level"): object,
        vol.Optional("text"): object,
        vol.Optional("after_seq"): object,
        vol.Optional("boot_id"): object,
        vol.Optional("limit"): object,
    }
)
@websocket_api.async_response
async def websocket_get_logs(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Recent SpotNav log records, filtered and scrubbed, for administrators (module docstring)."""
    version = msg.get("api_version")
    if type(version) is not int or version != LOGS_API_VERSION:
        send_unsupported_version(connection, msg, LOGS_API_VERSION)
        return
    if not is_admin(connection):
        connection.send_result(msg["id"], _answer(error=ERROR_NOT_ADMIN))
        return
    level, text, after_seq, limit = msg.get("level", "INFO"), msg.get("text", ""), msg.get("after_seq", 0), msg.get("limit", 200)
    if (
        level not in LEVELS
        or not isinstance(text, str)
        or len(text) > MAX_QUERY_TEXT
        or type(after_seq) is not int
        or after_seq < 0
        or type(limit) is not int
        or not 1 <= limit <= MAX_QUERY_RECORDS
        or not isinstance(msg.get("boot_id", ""), str)
    ):
        connection.send_result(msg["id"], _answer(error=ERROR_INVALID_FILTER))
        return
    buffer = getattr(domain_data(hass), "log_buffer", None)
    if buffer is None:
        connection.send_result(msg["id"], _answer(error=ERROR_UNAVAILABLE))
        return
    if msg.get("boot_id") not in (None, "", buffer.boot_id):
        after_seq = 0  # Home Assistant restarted since the viewer's last answer: its counter means nothing now
    result = buffer.query(level=level, text=text, after_seq=after_seq, limit=limit)
    scrubber = await _scrubber(hass, hass.config_entries.async_entries(DOMAIN))
    entries = redact_bundle(result["entries"], scrubber)
    connection.send_result(
        msg["id"],
        _answer(
            ok=True,
            boot_id=buffer.boot_id,
            latest_seq=result["latest_seq"],
            entries=entries,
            matched=result["matched"],
            truncated=result["truncated"],
            restarted=msg.get("boot_id") not in (None, "", buffer.boot_id),
        ),
    )


@callback
def async_setup_logs_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_get_logs)
