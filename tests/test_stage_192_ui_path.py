"""Stage 19.2/19.9a review: the sidebar's Resume on a legacy ambiguous record, from the status the real backend
reports to the guarded send. Real status handler, real manual-action handler, real AutoExecutor owned route, real
CommandAdmission/ownership/ledger stores; HA, OCPP and the wire are mocked boundaries. Nothing here proves charger
behavior or physical charging."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.spotnav.api import manual_action, morek_schedule
from custom_components.spotnav.execution import morek_worker
from .test_morek_worker import drain
from .test_stage_192_recovery import _legacy, _real_unknown

FIXTURE = Path(__file__).parent / "fixtures" / "morek" / "legacy_unknown_paused_status.json"


class Connection:
    def __init__(self, admin=True):
        self.user = SimpleNamespace(is_admin=admin)
        self.results, self.errors = [], []

    def send_result(self, _id, result):
        self.results.append(result)

    def send_error(self, _id, code, message):
        self.errors.append(code)


async def _status(w):
    connection = Connection()
    await morek_schedule.websocket_morek_schedule.__wrapped__(
        w.hass, connection, {"id": 1, "type": "spotnav/morek_schedule", "api_version": morek_schedule.API_VERSION,
                             "charger_id": "test", "action": "status"})
    assert not connection.errors, connection.errors
    result = connection.results[-1]
    return result["schedule"] if "schedule" in result else result


def _consumed(status):
    """Exactly the fields the sidebar's Resume gating reads."""
    return {"recorded_owner": status["ownership"]["recorded_owner"],
            "completion_authorized": status["ownership"]["completion_authorized"],
            "outcomes_uncertain": status["outcomes"]["uncertain"],
            "intent": status["schedule_pause"]["intent"], "resume_recoverable": status["schedule_pause"]["resume_recoverable"],
            "resume_pending": status["schedule_pause"]["resume_pending"],
            "unknown_recovery_ambiguous": status["reconciliation"]["unknown_recovery"].get("ambiguous")}


@pytest.mark.allow_loop_io
@pytest.mark.asyncio
async def test_real_status_for_the_legacy_ticketless_record_matches_the_panel_contract(monkeypatch, tmp_path):
    w, _ = await _real_unknown(monkeypatch, tmp_path)
    w.admission._completion_tickets.clear()  # noqa: SLF001 - HA restarted: no ownership ticket
    status = await _status(w)
    assert _consumed(status) == json.loads(FIXTURE.read_text())["consumed"]
