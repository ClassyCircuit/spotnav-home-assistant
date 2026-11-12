"""Exercise actual sidebar registration with mocked HA boundaries, without HA startup."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest import TestCase, main
from unittest.mock import AsyncMock, Mock, patch

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("sidebar_test_package")
package.__path__ = [str(root / "custom_components" / "spotnav")]
sys.modules[package.__name__] = package
card = types.ModuleType("sidebar_test_package.card_asset")
card.async_manifest_version = AsyncMock(return_value="2.5.35")
sys.modules[card.__name__] = card
spec = importlib.util.spec_from_file_location("sidebar_test_package.sidebar", root / "custom_components" / "spotnav" / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)


class RegistrationTest(TestCase):
    def test_registration_reload_and_shutdown(self):
        hass = types.SimpleNamespace(data={}, http=types.SimpleNamespace(async_register_static_paths=AsyncMock()))
        async def executor(fn): return fn()
        hass.async_add_executor_job = executor
        register = AsyncMock()
        remove = Mock()
        async def run():
            with patch.object(sidebar.panel_custom, "async_register_panel", register), patch.object(sidebar.frontend, "async_remove_panel", remove):
                await sidebar.async_setup_sidebar(hass)
                await sidebar.async_setup_sidebar(hass)
                self.assertEqual(register.await_count, 1)
                self.assertEqual(hass.http.async_register_static_paths.await_count, 1)
                sidebar.async_remove_sidebar(hass)
                sidebar.async_remove_sidebar(hass)
                self.assertEqual(remove.call_count, 1)
                await sidebar.async_setup_sidebar(hass)
                self.assertEqual(register.await_count, 2)
                self.assertEqual(hass.http.async_register_static_paths.await_count, 1)
        asyncio.run(run())

    def test_missing_asset(self):
        hass = types.SimpleNamespace(data={}, http=types.SimpleNamespace(async_register_static_paths=AsyncMock()))
        async def missing(fn): return False
        hass.async_add_executor_job = missing
        with self.assertRaises(FileNotFoundError): asyncio.run(sidebar.async_setup_sidebar(hass))


if __name__ == "__main__": main()
