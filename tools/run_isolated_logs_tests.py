"""Run the Stage 9.4 log-viewer tests without the platform-specific HA pytest plugin (no `fcntl` on Windows)."""

import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
package = types.ModuleType("custom_components.spotnav")
package.__path__ = [str(ROOT / "custom_components" / "spotnav")]
package.__package__ = "custom_components.spotnav"
sys.modules[package.__name__] = package

import pytest  # noqa: E402


class _ResolvedZones:
    """`--noconftest` skips tests/conftest.py's zone prewarm; do the same here (needs the `tzdata` package)."""

    @pytest.fixture(autouse=True)
    def resolved_time_zones(self):
        from custom_components.spotnav import time_zones

        time_zones.clear()
        for name in ("Europe/Berlin", "Europe/Brussels", "Europe/Copenhagen", "Europe/Helsinki", "Europe/Lisbon",
                     "Europe/London", "Europe/Madrid", "Europe/Oslo", "Europe/Paris", "Europe/Stockholm"):
            time_zones.zone(name)
        yield

raise SystemExit(pytest.main([
    "-q", "--noconftest", "-p", "pytest_asyncio.plugin", "-o", "asyncio_mode=auto", "-p", "no:cacheprovider",
    *(sys.argv[1:] or ["tests/test_stage_94_logs.py"]),
], plugins=[_ResolvedZones()]))
