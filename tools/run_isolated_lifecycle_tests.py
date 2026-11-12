"""Run lifecycle tests with the real integration modules and mocked HA I/O, not HA itself."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pytest  # noqa: E402

raise SystemExit(pytest.main([
    "-q", "--noconftest", "-p", "pytest_asyncio.plugin",
    "tests/test_ownership_lifecycle.py", "tests/test_stage_23_lifecycle.py", *sys.argv[1:],
]))
