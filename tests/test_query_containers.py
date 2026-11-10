"""Exercise actual Nugget outputs against the new path/transport boundary."""
import plistlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import src.gui.main_window
from src.restore import worse_query as query
from src.restore.restore import FileToRestore
from src.exceptions.nugget_exception import NuggetException
from src.tweaks.basic_plist_locations import FileLocation
from src.devicemanagement.device_manager import DeviceManager
from test_worse_query import device, mga, FakeAFC, transport


class ContainerPlanTests(unittest.TestCase):
    def test_supported_domain_families_and_raw_systemgroup(self):
        for domain in ("AppDomain-com.apple.PosterBoard", "AppDomain-com.apple.Maps",
                       "AppDomainGroup-group.example", "AppDomainPlugin-com.example.widget",
                       "SysContainerDomain-com.apple.PosterBoard", query.MGA_DOMAIN):
            with self.subTest(domain=domain):
                entry = query.make_request(FileToRestore(b"payload", "/Library/data", domain=domain), "build", "27.2")["files"][0]
                self.assertEqual((entry["domain"], entry["path"]), (domain, "Library/data"))
        for path in (FileLocation.mga.value, "/private" + FileLocation.mga.value):
            self.assertEqual(query.destination(FileToRestore(b"", path)), (query.MGA_DOMAIN, query.MGA_RELATIVE_PATH))

    def test_rejects_escape_and_ambiguous_paths(self):
        for domain, path in (("AppDomain-../test", "Library/file"), ("AppDomain-.foo", "Library/file"),
                ("AppDomain-com.example", "../file"), ("AppDomain-com.example", "Library/../file"),
                ("AppDomain-com.example", "Library//file"), ("AppDomain-com.example", "Library/./file"),
                ("AppDomain-com.example", "Library\\file"), ("AppDomain-com.example", "Library/\x00file"),
                ("AppDomain-", "file"), ("AppDomain-com.example", "/")):
            with self.subTest(domain=domain, path=path), self.assertRaises(NuggetException):
                query.make_request(FileToRestore(b"", path, domain=domain), "build", "27.2")

    def test_raw_app_container_paths_are_bounded(self):
        uuid = "11223344-5566-7788-99AA-BBCCDDEEFF00"
        for kind in ("Application", "InternalDaemon", "PluginKitPlugin"):
            path = f"/var/mobile/Containers/Data/{kind}/{uuid}/Library/test"
            self.assertEqual(query.destination(FileToRestore(b"", path)),
                             (f"ContainerPathDomain-{kind}-{uuid}", "Library/test"))
        for domain in ("ContainerPathDomain-Application-no-uuid", "ContainerPathDomain-root-" + uuid):
            with self.assertRaises(NuggetException):
                query.destination(FileToRestore(b"", "Library/file", domain=domain))

    def test_all_unreachable_original_tweak_locations_are_rejected(self):
        # Exact target paths from the original implementation, not a UI inventory.
        for location in FileLocation:
            if location in (FileLocation.mga, FileLocation.footnote):
                continue
            with self.subTest(location=location), self.assertRaises(NuggetException):
                query.destination(FileToRestore(b"", location.value))
        for domain in ("HomeDomain", "ManagedPreferencesDomain", "DatabaseDomain", "SystemPreferencesDomain",
                       "RootDomain", "ProtectedDomain", "ConfigProfileDomain", "SysContainerDomain-../../escape"):
            with self.subTest(domain=domain), self.assertRaises(NuggetException):
                query.make_request(FileToRestore(b"", "Library/file", domain=domain), "build", "27.2")

    def test_footnote_merges_only_its_plist(self):
        domain = "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles"
        for file in (FileToRestore(plistlib.dumps({"LockScreenFootnote": "Example"}), FileLocation.footnote.value),
                     FileToRestore(plistlib.dumps({"LockScreenFootnote": "Example"}),
                                   "Library/ConfigurationProfiles/SharedDeviceConfiguration.plist", domain=domain)):
            self.assertEqual(query.make_request(file, "build", "27.2")["files"][0]["operation"], "merge_plist")
        file = FileToRestore(b"", "Library/other.plist", domain=domain)
        self.assertEqual(query.make_request(file, "build", "27.2")["files"][0]["operation"], "write")

    def test_mga_baseline_is_sent_and_counted_in_payload_limit(self):
        file = mga()
        baseline = plistlib.dumps({"CacheExtra": {"example": False}})
        file.query_baseline = baseline
        request = query.make_request(file, "build", "27.2")
        self.assertEqual(request["files"][0]["baseline"], baseline)
        with patch.object(query, "MAX_BYTES", len(file.contents)), self.assertRaises(NuggetException):
            query.make_request(file, "build", "27.2")
        file.query_baseline = b"bad baseline"
        with self.assertRaises(NuggetException):
            query.make_request(file, "build", "27.2")

    def test_duplicate_raw_and_domain_mga_cannot_bypass_detection(self):
        with self.assertRaises(NuggetException):
            query.make_request([mga(), mga(domain=query.MGA_DOMAIN, path=query.MGA_RELATIVE_PATH)], "build", "27.2")

    def test_app_metadata_is_a_hint_not_a_destination_override(self):
        domain = "AppDomain-com.apple.PosterBoard"
        file = FileToRestore(b"data", "Library/test", domain=domain)
        request = query.make_request(file, "build", "27.2", {"com.apple.PosterBoard": {"Container": "/malicious/hint"}})
        entry = request["files"][0]
        self.assertEqual(entry["domain"], domain)
        self.assertEqual(entry["path"], "Library/test")
        self.assertEqual(entry["containerHint"], "/malicious/hint")  # The device validates hint root and xattr.

    def test_empty_oversized_and_bad_mixed_batches_never_publish(self):
        for files in ([], [mga()] * 4097, [mga(), FileToRestore(b"", "/var/db/eligibilityd/eligibility.plist")]):
            with self.assertRaises(NuggetException):
                query.make_request(files, "build", "27.2")
        with patch.object(query, "MAX_BYTES", 1), self.assertRaises(NuggetException):
            query.make_request(mga(), "build", "27.2")


class ContainerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_posterboard_outputs_are_one_companion_batch(self):
        from src.tweaks.posterboard.posterboard_tweak import PosterboardTweak
        tweak = PosterboardTweak()
        from tempfile import TemporaryDirectory
        from pathlib import Path
        files = []
        with TemporaryDirectory() as folder:
            descriptor = Path(folder) / "asset.ca"
            descriptor.mkdir()
            (descriptor / "main.caml").write_bytes(b"<caml/>")
            tweak.recursive_add(files, folder, "/Library/Application Support/PRBPosterExtensionDataStore/61", True)
            self.assertTrue(files)
            request = query.make_request(files, "build", "27.2")
        self.assertTrue(all(entry["domain"] == "AppDomain-com.apple.PosterBoard" for entry in request["files"]))

    async def test_invalid_selection_never_discovers_or_uploads(self):
        with patch.object(query, "InstallationProxyService") as discover, self.assertRaises(NuggetException):
            await query.perform_worse_query([mga(), FileToRestore(b"", "/var/db/test")], device(), None, lambda _: None)
        discover.assert_not_called()

    async def test_metadata_discovery_and_protocol2_batch(self):
        app = FileToRestore(b"wallpaper", "Library/test", domain="AppDomain-com.apple.PosterBoard")
        afc = FakeAFC()
        with transport(afc):
            await query.perform_worse_query([mga(), app], device(), None, lambda _: None)
        self.assertEqual(afc.published["protocol"], 2)
        self.assertEqual(len(afc.published["files"]), 2)

    async def test_ios27_app_only_never_calls_old_restore(self):
        manager = DeviceManager.__new__(DeviceManager)
        manager.data_singleton = SimpleNamespace(current_device=device())
        manager.pref_manager = SimpleNamespace(auto_reboot=False)
        files = [FileToRestore(b"wallpaper", "Library/test", domain="AppDomain-com.apple.PosterBoard")]
        with patch("src.devicemanagement.device_manager.create_using_usbmux", new=AsyncMock(return_value=FakeAFC())), \
                patch("src.devicemanagement.device_manager.perform_worse_query", new=AsyncMock()) as native, \
                patch("src.devicemanagement.device_manager.restore_files", new=AsyncMock()) as restore, \
                patch("src.devicemanagement.device_manager.perform_bookrestore", new=AsyncMock()) as book, \
                patch("src.devicemanagement.device_manager.tweaks"):
            await manager.start_restore(files, False)
        self.assertEqual(native.await_args.args[0], files)
        restore.assert_not_awaited()
        book.assert_not_awaited()

    async def test_no_restore_setup_helpers_on_ios27(self):
        manager = DeviceManager.__new__(DeviceManager)
        manager.data_singleton = SimpleNamespace(current_device=device())
        manager.pref_manager = SimpleNamespace(skip_setup=True, rebuild_sb_application_state_db=True)
        files = []
        with patch("src.devicemanagement.device_manager.create_using_usbmux", new=AsyncMock()) as connect:
            manager.add_rebuild_sb_application_state_db(files)
            await manager.add_skip_setup(files, True)
        self.assertEqual(files, [])
        connect.assert_not_called()
