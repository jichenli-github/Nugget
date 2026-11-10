from PySide6.QtWidgets import QWidget, QFormLayout, QComboBox, QLabel
from PySide6.QtCore import QCoreApplication
from ..page import Page
from src.tweaks.mobilegestalt_region_tweak import MobileGestaltRegionTweak
from src.qt.mainwindow_ui import Ui_Nugget

from src.tweaks.tweak_loader import load_eligibility
from src.tweaks.tweaks import tweaks, TweakID

class EligibilityPage(Page):
    def __init__(self, window, ui: Ui_Nugget):
        super().__init__()
        self.window = window
        self.ui = ui
        self.ai_region_widget = None
        self.original_ai_text = ui.enableAIChk.text()
        self.original_ai_tooltip = ui.enableAIChk.toolTip()
        self.original_title = ui.eligibilityLbl.text()

    def load_page(self):
        self.ui.euEnablerEnabledChk.toggled.connect(self.on_euEnablerEnabledChk_toggled)
        self.ui.methodChoiceDrp.activated.connect(self.on_methodChoiceDrp_activated)
        self.ui.regionCodeTxt.textEdited.connect(self.on_regionCodeTxt_textEdited)

        self.ui.createEligFolderChk.toggled.connect(self.on_createEligFolderChk_toggled)
        self.ui.enableAIChk.toggled.connect(self.on_enableAIChk_toggled)
        self.ui.eligFileChk.toggled.connect(self.on_eligFileChk_toggled)
        self.ui.languageTxt.hide() # to be removed later
        self.ui.languageLbl.hide() # to be removed later
        self.ui.languageTxt.textEdited.connect(self.on_languageTxt_textEdited)
        self.ui.spoofedModelDrp.activated.connect(self.on_spoofedModelDrp_activated)
        self.ui.spoofHardwareChk.toggled.connect(self.on_spoofHardwareChk_toggled)
        self.ui.spoofCPUChk.toggled.connect(self.on_spoofCPUChk_toggled)
        
        self.ui.aiEnablerContent.hide()

        load_eligibility(self.window.device_manager.data_singleton.current_device)
        self.configure_for_device()

    def query_mode(self):
        device = self.window.device_manager.data_singleton.current_device
        return device is not None and device.has_worse_query()

    def configure_for_device(self):
        query_mode = self.query_mode()
        if query_mode and self.ai_region_widget is None:
            self.ai_region_widget = QWidget(self.ui.euEnablerPageContent)
            form = QFormLayout(self.ai_region_widget)
            form.setContentsMargins(0, 5, 0, 5)
            self.ai_region_code = QComboBox(self.ai_region_widget)
            self.ai_sales_region = QComboBox(self.ai_region_widget)
            for combo in (self.ai_region_code, self.ai_sales_region):
                combo.setStyleSheet(self.ui.methodChoiceDrp.styleSheet())
            for label, code in MobileGestaltRegionTweak.REGIONS:
                self.ai_region_code.addItem(QCoreApplication.tr(label), code)
                self.ai_sales_region.addItem(QCoreApplication.tr(label), code)
            form.addRow(QCoreApplication.tr("Region code"), self.ai_region_code)
            form.addRow(QCoreApplication.tr("Sales region"), self.ai_sales_region)
            note = QLabel(QCoreApplication.tr(
                "Apple Intelligence activation attempt. Usually try the region code first; "
                "Keep current leaves that setting unchanged. Availability depends on the device, "
                "iOS and Apple services. This does not enable EU sideloading."
            ), self.ai_region_widget)
            note.setWordWrap(True)
            form.addRow(note)
            layout = self.ui.verticalLayout_16
            layout.insertWidget(layout.indexOf(self.ui.enableAIChk) + 1, self.ai_region_widget)
            self.ai_region_code.currentIndexChanged.connect(self.on_ai_regions_changed)
            self.ai_sales_region.currentIndexChanged.connect(self.on_ai_regions_changed)
        if self.ai_region_widget is not None:
            self.ai_region_widget.setVisible(query_mode)
            if not query_mode:
                self.ai_region_code.setCurrentIndex(0)
                self.ai_sales_region.setCurrentIndex(0)
        self.ui.enableAIChk.setText(QCoreApplication.tr("Apple Intelligence capability (MobileGestalt)") if query_mode else self.original_ai_text)
        self.ui.enableAIChk.setToolTip(QCoreApplication.tr("Sets the AI capability flag; actual availability requires device testing.") if query_mode else self.original_ai_tooltip)
        self.ui.eligibilityLbl.setText(QCoreApplication.tr("Apple Intelligence (MobileGestalt)") if query_mode else self.original_title)
        self.ui.aiEnablerContent.setVisible(not query_mode and self.ui.enableAIChk.isChecked())
        if query_mode:
            self.ui.enableAIChk.show()
            self.ui.euEnablerContent.hide()
            # Do not carry hidden legacy eligibility/feature-flag selections into
            # an otherwise valid MG-only AI request after changing devices.
            self.ui.euEnablerEnabledChk.setChecked(False)
            self.ui.eligFileChk.setChecked(False)
            self.ui.createEligFolderChk.setChecked(False)
            for key in (TweakID.EUEnabler, TweakID.AIEligibility, TweakID.AIFeatureFlags, TweakID.AIFeatureFlagsUI, TweakID.CreateBRFolders):
                if key in tweaks:
                    tweaks[key].set_enabled(False)

    def on_ai_regions_changed(self, _=None):
        if TweakID.AIRegion in tweaks:
            tweaks[TweakID.AIRegion].set_regions(
                self.ai_region_code.currentData() if self.query_mode() else "",
                self.ai_sales_region.currentData() if self.query_mode() else "",
            )

    ## ACTIONS
    def on_euEnablerEnabledChk_toggled(self, checked: bool):
        tweaks[TweakID.EUEnabler].set_enabled(checked)
    def on_methodChoiceDrp_activated(self, index: int):
        tweaks[TweakID.EUEnabler].set_selected_option(index)
    def on_regionCodeTxt_textEdited(self, text: str):
        tweaks[TweakID.EUEnabler].set_region_code(text)

    def on_enableAIChk_toggled(self, checked: bool):
        # tweaks[TweakID.AIEligibility].set_enabled(checked)
        tweaks[TweakID.AIGestalt].set_enabled(checked)
        # change the visibility of stuff
        if checked and not self.query_mode():
            self.ui.aiEnablerContent.show()
        else:
            self.ui.aiEnablerContent.hide()

    def on_createEligFolderChk_toggled(self, checked: bool):
        tweaks[TweakID.CreateBRFolders].set_enabled(checked)
        self.ui.createFFFolderChk.setChecked(checked)
    def on_eligFileChk_toggled(self, checked: bool):
        tweaks[TweakID.AIEligibility].set_enabled(checked)
        tweaks[TweakID.AIFeatureFlags].set_enabled(checked)
        tweaks[TweakID.AIFeatureFlagsUI].set_enabled(checked)
        if checked:
            self.ui.languageTxt.show()
            self.ui.languageLbl.show()
        else:
            self.ui.languageTxt.hide()
            self.ui.languageLbl.hide()

    def on_languageTxt_textEdited(self, text: str):
        tweaks[TweakID.AIEligibility].set_language_code(text)
    
    def on_spoofedModelDrp_activated(self, index: int):
        idx_to_apply = index
        if not self.window.device_manager.pref_manager.show_all_spoofable_models and not self.window.device_manager.get_current_device_model().startswith("iPhone"):
            # offset the index for ipads
            idx_to_apply += 6
        tweaks[TweakID.SpoofModel].set_selected_option(idx_to_apply, is_enabled=(index != 0))
        tweaks[TweakID.SpoofHardware].set_selected_option(idx_to_apply, is_enabled=(index != 0 and self.ui.spoofHardwareChk.isChecked()))
        tweaks[TweakID.SpoofCPU].set_selected_option(idx_to_apply, is_enabled=(index != 0 and self.ui.spoofCPUChk.isChecked()))
    def on_spoofHardwareChk_toggled(self, checked: bool):
        tweaks[TweakID.SpoofHardware].set_enabled(checked and tweaks[TweakID.SpoofHardware].selected_option != 0)
    def on_spoofCPUChk_toggled(self, checked: bool):
        tweaks[TweakID.SpoofCPU].set_enabled(checked and tweaks[TweakID.SpoofCPU].selected_option != 0)