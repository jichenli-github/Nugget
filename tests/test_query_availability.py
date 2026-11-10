import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from tempfile import TemporaryDirectory

import src.gui.main_window
from PySide6.QtWidgets import QApplication, QMainWindow, QComboBox, QCheckBox, QRadioButton, QSlider
from src.qt.mainwindow_ui import Ui_Nugget
from src.gui.query_availability import QueryAvailability
from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.pages.tools.springboard import SpringboardPage
from src.devicemanagement.device_manager import DeviceManager
from src.restore.worse_query import supports_query_tweak, supports_query_template
from src.tweaks.tweak_classes import BasicPlistTweak, FeatureFlagTweak, MobileGestaltTweak, MobileGestaltCacheDataTweak
from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.eligibility_tweak import BookRestoreFileTweak
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.tweaks.tweaks import tweaks, TweakID
from test_worse_query import device


class AvailabilityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.ui = Ui_Nugget()
        self.ui.setupUi(self.window)
        self.ui.resetPBDrp = QComboBox(self.ui.pbPagePicker)
        for _, name in QueryAvailability.BLOCKED_PAGES:
            getattr(self.ui, name).setEnabled(True)
        self.ui.springboardOptionsPageContent.setEnabled(True)
        self.ui.gestaltPageContent.setEnabled(True)
        self.ui.euEnablerPageContent.setEnabled(True)
        self.policy = QueryAvailability(self.ui)
        self.addCleanup(self.window.close)

    def test_27_range_disables_all_unsupported_pages_and_settings(self):
        for version in ("27.0", "27.1", "27.2"):
            self.policy.apply(device(version))
            for button, content in self.policy.BLOCKED_PAGES:
                self.assertFalse(getattr(self.ui, button).isEnabled(), button)
                self.assertFalse(getattr(self.ui, content).isEnabled(), content)
                self.assertFalse(getattr(self.ui, button).isHidden(), button)
                self.assertIn("27.0", getattr(self.ui, button).toolTip())
            for name in self.policy.RESTORE_ONLY + ("resetPBDrp", "rdarFixChk", "enableiPadOSChk"):
                self.assertFalse(getattr(self.ui, name).isEnabled(), name)
            for name in ("footnoteTxt", "enableAIChk", "gestaltPageContent", "chooseGestaltBtn", "importTemplatesBtn"):
                self.assertTrue(getattr(self.ui, name).isEnabled(), name)

    def test_dynamic_springboard_radios_inherit_disablement(self):
        with patch.dict(tweaks, {}, clear=True):
            SpringboardPage(self.ui).load()
            self.policy.apply(device())
            for cls in (QRadioButton, QCheckBox, QSlider):
                for control in self.ui.springboardOptionsPageContent.findChildren(cls):
                    self.assertFalse(control.isEnabled(), control.objectName())
            self.assertTrue(self.ui.footnoteTxt.isEnabled())

    def test_gestalt_page_load_does_not_poison_legacy_enabled_state(self):
        from src.gui.pages.tools.gestalt import GestaltPage
        holder = SimpleNamespace(ui=self.ui, window=SimpleNamespace(
            device_manager=SimpleNamespace(data_singleton=SimpleNamespace(current_device=device()))))
        GestaltPage.set_rdar_fix_label(holder)
        self.policy.apply(device())
        self.assertFalse(self.ui.rdarFixChk.isEnabled())
        self.policy.apply(device("26.1"))
        self.assertTrue(self.ui.rdarFixChk.isEnabled())

    def test_disabled_checkbox_does_not_emit_click(self):
        observed = []
        self.ui.rdarFixChk.clicked.connect(observed.append)
        self.policy.apply(device())
        self.ui.rdarFixChk.click()
        self.assertEqual(observed, [])

    def test_legacy_and_disconnect_restore_original_state_not_blanket_enable(self):
        self.ui.supervisionOrganization.setEnabled(False)
        self.ui.rdarFixChk.setToolTip("Original tooltip")
        original_style = self.ui.rdarFixChk.styleSheet()
        for next_device in (device("26.1"), None):
            self.policy.apply(device())
            self.policy.apply(device())  # Refreshing must not capture disabled state as the baseline.
            self.policy.apply(next_device)
            self.assertTrue(self.ui.rdarFixChk.isEnabled())
            self.assertEqual(self.ui.rdarFixChk.toolTip(), "Original tooltip")
            self.assertEqual(self.ui.rdarFixChk.styleSheet(), original_style)
            self.assertFalse(self.ui.supervisionOrganization.isEnabled())
            self.assertTrue(self.ui.internalOptionsPageBtn.isEnabled())

    def test_unsupported_template_controls_grey_but_delete_remains_usable(self):
        import json
        import zipfile
        from pathlib import Path
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton
        from src.tweaks.posterboard.template_file import TemplateFile
        with TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.batter"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("config.json", json.dumps({"options": [], "domain": "HomeDomain",
                    "format_version": 2, "title": "Legacy template", "author": "Test"}))
            template = TemplateFile(str(path), device_version="27.0")
            owner = QWidget()
            layout = QVBoxLayout(owner)
            state = SimpleNamespace(templates=[template])
            host = SimpleNamespace(device_manager=SimpleNamespace(data_singleton=SimpleNamespace(current_device=device())))
            rows = {}
            template.create_ui(host, state, rows, layout)
            self.assertFalse(template._query_options.isEnabled())
            self.assertFalse(template._query_title.isEnabled())
            self.assertTrue(any(button.isEnabled() for button in rows[template].findChildren(QToolButton)))
            template.update_query_availability(device("26.1"))
            self.assertTrue(template._query_options.isEnabled())
            self.assertTrue(template._query_title.isEnabled())
            owner.close()

    def test_reset_dialog_shows_unsupported_pages_disabled(self):
        manager = SimpleNamespace(data_singleton=SimpleNamespace(current_device=device()), get_current_device_version=lambda: "27.1")
        dialog = ResetDialog(manager)
        checkboxes = dialog.findChildren(QCheckBox)
        self.assertEqual(len(checkboxes), 7)
        self.assertEqual([c.text() for c in checkboxes if c.isEnabled()], ["Mobile Gestalt"])
        dialog.close()


class AvailabilityRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_unsupported_selection_ignored_without_changing_legacy_state(self):
        flag = FeatureFlagTweak(flag_category="Example", flag_names=["flag"])
        flag.set_enabled(True)
        flag.apply_tweak = Mock(side_effect=AssertionError("Disabled flag must not run"))
        footnote = BasicPlistTweak(FileLocation.footnote, "LockScreenFootnote", value="Hello")
        footnote.set_enabled(True)
        manager = DeviceManager.__new__(DeviceManager)
        manager.data_singleton = SimpleNamespace(current_device=device(), gestalt_path=None)
        manager.pref_manager = SimpleNamespace(allow_risky_tweaks=False)
        manager.start_restore = AsyncMock(return_value=SimpleNamespace(txt="Success"))
        folders = BookRestoreFileTweak()
        folders.set_enabled(True)
        selected = {TweakID.ClockAnim: flag, TweakID.LockScreenFootnote: footnote, TweakID.CreateBRFolders: folders}
        with patch.dict(tweaks, selected, clear=True):
            await manager._apply_changes()
        flag.apply_tweak.assert_not_called()
        self.assertTrue(flag.enabled)
        files = manager.start_restore.await_args.args[0]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].domain, "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles")

    async def test_template_targets_are_classified_and_disabled_ones_not_extracted(self):
        supported = SimpleNamespace(domain="AppDomain-com.apple.PosterBoard", change_bundle_id=False)
        unsupported = SimpleNamespace(domain="HomeDomain", change_bundle_id=False, extract=Mock())
        self.assertTrue(supports_query_template(supported))
        self.assertFalse(supports_query_template(unsupported))
        template_tweak = TemplatesTweak()
        template_tweak.templates = [unsupported]
        for version in ("27.0", "27.2"):
            with TemporaryDirectory() as folder:
                template_tweak.apply_tweak([], folder, [], version, False)
        unsupported.extract.assert_not_called()
        with TemporaryDirectory() as folder:
            template_tweak.apply_tweak([], folder, [], "26.1", False)
        unsupported.extract.assert_called_once()

    def test_only_writable_builtin_locations_and_mg_remain_supported(self):
        for location in FileLocation:
            self.assertEqual(supports_query_tweak(BasicPlistTweak(location, "key")),
                             location in (FileLocation.footnote, FileLocation.mga), location)
        self.assertTrue(supports_query_tweak(MobileGestaltTweak("key")))
        self.assertFalse(supports_query_tweak(MobileGestaltTweak("key"), TweakID.iPadOS))
        self.assertFalse(supports_query_tweak(MobileGestaltCacheDataTweak(0, 10)))
