"""Run focused actual-module planning tests without the HA pytest plugin.

Requires pytest and Home Assistant's Python dependencies. This is *not* a Home
Assistant integration test: the integration package bootstrap and HA transports
are bypassed, and the selected tests use mocked boundaries. Full HA tests must
still run on a supported host. Accepts optional pytest arguments after the suite.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
sys.path.insert(0, str(ROOT))
package = types.ModuleType("custom_components.spotnav")
package.__path__ = [str(ROOT / "custom_components" / "spotnav")]
package.__package__ = "custom_components.spotnav"
sys.modules[package.__name__] = package

from custom_components.spotnav import time_zones  # noqa: E402
import pytest  # noqa: E402

# Real HA resolves the catalogue's zones off the event loop at startup.
for zone in (
    "Europe/Stockholm", "Europe/Berlin", "Europe/London", "Europe/Lisbon", "Europe/Oslo",
    "Europe/Helsinki", "Europe/Paris", "Europe/Copenhagen", "Europe/Brussels", "Europe/Madrid",
):
    time_zones.zone(zone)

tests = [
    "tests/test_stage_22_guards.py",
    "tests/test_execution_ownership.py",
    "tests/test_command_admission.py",
    "tests/test_stage_21_ownership.py",
    "tests/test_stage_13_reactive.py",
    "tests/test_capped_auto_execution_isolated.py",
    "tests/test_morek_schedule.py",
    "tests/test_morek_worker.py",
    "tests/test_morek_outcomes.py",
    "tests/test_planner.py",
    "tests/test_planner_invariants.py",
    "tests/test_planner_deadline_dst.py",
    "tests/test_planner_price_policy_guard.py",
    "tests/test_planner_price_cap_comparison.py",
    "tests/test_planner_minimum_energy.py",
    "tests/test_price_policy_settings.py",
]
os.chdir(ROOT)
raise SystemExit(pytest.main([
    "-q", "--noconftest", "-p", "pytest_asyncio.plugin",
    "--deselect=tests/test_price_policy_settings.py::test_store_api_partial_revision_and_vehicle_resolution",
    *tests, *sys.argv[1:],
]))
