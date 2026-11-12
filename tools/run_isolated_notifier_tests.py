"""Run real notifier/planner/event tests without the platform-specific HA pytest plugin."""

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

raise SystemExit(pytest.main([
    "-q", "--noconftest", "-p", "pytest_asyncio.plugin",
    "tests/test_isolated_proposal_notifications.py", *sys.argv[1:],
]))
