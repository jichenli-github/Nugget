import copy
import plistlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src.gui.main_window
from PySide6.QtWidgets import QApplication, QMainWindow
from src.gui.pages.tools.eligibility import EligibilityPage
from src.qt.mainwindow_ui import Ui_Nugget
from src.tweaks.mobilegestalt_region_tweak import MobileGestaltRegionTweak
from src.tweaks.tweaks import tweaks, TweakID
from src.exceptions.nugget_exception import NuggetException
from src.restore.restore import FileToRestore
from src.restore import worse_query as query
from test_worse_query import device


class RegionBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.source = {"CacheUUID": "unchanged", "CacheData": b"unchanged", "CacheExtra": {
            MobileGestaltRegionTweak.REGION_CODE: "CH",
            "zHeENZu+wbg7PUprwNwBWg": "CH/A",
            "yK+xavymRGZ3xWc1tb8XDg": "CH/A", "other": 42}}

    def test_code_only_keeps_both_sales_fields_and_cache_data(self):
        tweak = MobileGestaltRegionTweak()
        tweak.set_regions("LL")
        result = tweak.apply_tweak(copy.deepcopy(self.source))
        self.assertEqual(result["CacheExtra"][tweak.REGION_CODE], "LL")
        for key in tweak.SALES_KEYS:
            self.assertEqual(result["CacheExtra"][key], "CH/A")
        self.assertEqual(result["CacheData"], self.source["CacheData"])
        self.assertEqual(result["CacheExtra"]["other"], 42)

    def test_sales_default_and_independent_code_precedence(self):
        for code, sales, expected in (("", "ZA", "ZA"), ("LL", "ZA", "LL")):
            tweak = MobileGestaltRegionTweak()
            tweak.set_regions(code, sales)
            result = tweak.apply_tweak(copy.deepcopy(self.source))["CacheExtra"]
            self.assertEqual(result[tweak.REGION_CODE], expected)
            for key in tweak.SALES_KEYS:
                self.assertEqual(result[key], "ZA/A")

    def test_sales_updates_present_keys_only_or_adds_modern_key(self):
        tweak = MobileGestaltRegionTweak()
        tweak.set_regions(sales_region="J")
        for existing in ({}, {tweak.SALES_KEYS[0]: "CH/A"}, {tweak.SALES_KEYS[1]: "CH/A"}):
            source = {"CacheExtra": dict(existing)}
            result = tweak.apply_tweak(source)["CacheExtra"]
            for key in existing or {tweak.SALES_KEYS[0]: ""}:
                self.assertEqual(result[key], "J/A")
            self.assertEqual(len(result), len(existing or {"": ""}) + 1)

    def test_keep_current_is_noop_and_invalid_selection_fails(self):
        tweak = MobileGestaltRegionTweak()
        self.assertEqual(tweak.apply_tweak(copy.deepcopy(self.source)), self.source)
        tweak.set_regions("LL")
        tweak.set_regions()
        self.assertFalse(tweak.enabled)
        self.assertEqual(tweak.apply_tweak(copy.deepcopy(self.source)), self.source)
        with self.assertRaises(NuggetException):
            tweak.set_regions("US")  # MG uses LL, not the ISO US code.


class AIPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state = patch.dict(tweaks, {}, clear=True)
        self.state.start()
        self.addCleanup(self.state.stop)
        self.native_window = QMainWindow()
        self.ui = Ui_Nugget()
        self.ui.setupUi(self.native_window)
        self.original_text = self.ui.enableAIChk.text()
        self.manager = SimpleNamespace(data_singleton=SimpleNamespace(current_device=device()),
                                       pref_manager=SimpleNamespace(show_all_spoofable_models=True))
        self.page = EligibilityPage(SimpleNamespace(device_manager=self.manager), self.ui)
        self.page.load()
        self.addCleanup(self.native_window.close)

    def test_ai_and_region_generate_only_mga_operation(self):
        self.ui.enableAIChk.setChecked(True)
        self.page.ai_region_code.setCurrentIndex(self.page.ai_region_code.findData("LL"))
        self.assertTrue(tweaks[TweakID.AIGestalt].enabled)
        self.assertTrue(tweaks[TweakID.AIRegion].enabled)
        self.assertFalse(tweaks[TweakID.AIEligibility].enabled)
        self.assertFalse(tweaks[TweakID.AIFeatureFlags].enabled)
        self.assertFalse(tweaks[TweakID.AIFeatureFlagsUI].enabled)
        self.assertFalse(tweaks[TweakID.EUEnabler].enabled)
        self.assertTrue(self.ui.aiEnablerContent.isHidden())
        self.assertFalse(self.ui.enableAIChk.isHidden())
        self.assertFalse(self.page.ai_region_widget.isHidden())
        source = {"CacheExtra": {"zHeENZu+wbg7PUprwNwBWg": "CH/A"}}
        for key in (TweakID.AIGestalt, TweakID.AIRegion):
            source = tweaks[key].apply_tweak(source)
        request = query.make_request(FileToRestore(plistlib.dumps(source), query.MGA_RELATIVE_PATH, domain=query.MGA_DOMAIN), "build", "27.2")
        self.assertEqual(len(request["files"]), 1)
        extra = plistlib.loads(request["files"][0]["contents"])["CacheExtra"]
        self.assertEqual(extra["A62OafQ85EJAiiqKn4agtg"], 1)
        self.assertEqual(extra[MobileGestaltRegionTweak.REGION_CODE], "LL")
        self.assertEqual(extra["zHeENZu+wbg7PUprwNwBWg"], "CH/A")

    def test_switching_to_legacy_restores_ui_and_disables_region_preset(self):
        self.page.ai_region_code.setCurrentIndex(1)
        self.manager.data_singleton.current_device = device("26.1")
        self.page.configure_for_device()
        self.assertTrue(self.page.ai_region_widget.isHidden())
        self.assertEqual(self.ui.enableAIChk.text(), self.original_text)
        self.assertFalse(tweaks[TweakID.AIRegion].enabled)
        self.ui.eligFileChk.setChecked(True)
        self.assertTrue(tweaks[TweakID.AIEligibility].enabled)
        self.assertTrue(tweaks[TweakID.AIFeatureFlags].enabled)
        self.ui.enableAIChk.setChecked(True)
        self.assertFalse(self.ui.aiEnablerContent.isHidden())

    def test_reentering_query_mode_clears_hidden_legacy_eligibility(self):
        self.manager.data_singleton.current_device = device("26.1")
        self.page.configure_for_device()
        self.ui.eligFileChk.setChecked(True)
        self.ui.euEnablerEnabledChk.setChecked(True)
        self.manager.data_singleton.current_device = device()
        self.page.configure_for_device()
        self.assertFalse(self.ui.eligFileChk.isChecked())
        self.assertTrue(self.ui.euEnablerContent.isHidden())
        for key in (TweakID.EUEnabler, TweakID.AIEligibility, TweakID.AIFeatureFlags, TweakID.AIFeatureFlagsUI):
            self.assertFalse(tweaks[key].enabled)
