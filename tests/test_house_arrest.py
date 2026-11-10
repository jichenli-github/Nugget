"""Use the installed pymobiledevice3 API signature, rather than replacing its class.

Only the network factory result is faked: autospec catches wrong keyword arguments
and the async assertion catches an omitted await before any device is contacted.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import src.gui.main_window
from src.devicemanagement.device_manager import DeviceManager
from pymobiledevice3.services.house_arrest import HouseArrestService
from test_worse_query import device, FakeAFC


class HouseArrestRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pocket_poster_uses_async_factory_and_closes_connection(self):
        manager = DeviceManager.__new__(DeviceManager)
        manager.data_singleton = SimpleNamespace(current_device=device())
        lockdown = SimpleNamespace(close=AsyncMock())
        afc = FakeAFC()
        afc.push = AsyncMock()
        ips = SimpleNamespace(get_apps=AsyncMock(return_value={
            "custom.poster": {"CFBundleExecutable": "Pocket Poster", "CFBundleIdentifier": "custom.poster"}
        }))
        ips_context = AsyncMock()
        ips_context.__aenter__.return_value = ips
        with patch("src.devicemanagement.device_manager.create_using_usbmux", new=AsyncMock(return_value=lockdown)), \
                patch("src.devicemanagement.device_manager.InstallationProxyService", return_value=ips_context), \
                patch.object(HouseArrestService, "create", autospec=True, return_value=afc) as create:
            await manager._send_app_hashes_afc({"com.apple.PosterBoard": "test-container-uuid"})
        create.assert_awaited_once_with(lockdown=lockdown, bundle_id="custom.poster", documents_only=True)
        afc.push.assert_awaited_once()
        self.assertEqual(afc.push.await_args.args[1], "/Documents/NuggetPosterBoardHash")
        lockdown.close.assert_awaited_once()
