"""Reversible iOS 27 capability gating without changing the original .ui layout."""
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QWidget


class QueryAvailability:
    # Whole pages whose destinations are outside worse_query containers.
    BLOCKED_PAGES = (
        ("featureFlagsPageBtn", "featureFlagsPageContent"),
        ("statusBarPageBtn", "statusBarPageContent"),
        ("internalOptionsPageBtn", "internalOptionsPageContent"),
        ("liquidGlassPageBtn", "liquidGlassPageContent"),
        ("daemonsPageBtn", "daemonsPageContent"),
        ("advancedPageBtn", "advancedOptionsPageContent"),
        ("passcodePageBtn", "passcodeThemesPage"),
    )
    RESTORE_ONLY = ("skipSetupChk", "supervisionChk", "supervisionOrganization",
                    "trustStoreChk", "rebuildSBApplicationStateDBChk", "bookrestoreWidget")

    def __init__(self, ui):
        self.ui = ui
        self.saved = {}

    def remember(self, widget):
        if widget not in self.saved:
            # isEnabled() also reflects disabled parents. Preserve the explicit
            # flag instead, so restoring a child cannot leave it stuck disabled.
            self.saved[widget] = (not widget.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled),
                                  widget.isHidden(), widget.toolTip(), widget.styleSheet())

    def block(self, widget, reason, show=False):
        self.remember(widget)
        widget.setEnabled(False)
        widget.setToolTip(reason)
        widget.setStyleSheet(self.saved[widget][3] + "\nQWidget:disabled { color: #777777; }")
        if show:
            widget.show()

    def restore(self):
        for widget, (enabled, hidden, tooltip, style) in self.saved.items():
            widget.setEnabled(enabled)
            widget.setVisible(not hidden)
            widget.setToolTip(tooltip)
            widget.setStyleSheet(style)
        self.saved.clear()

    def apply(self, device):
        self.restore()
        if device is None or not device.has_worse_query():
            return
        reason = QCoreApplication.tr("Unavailable on iOS 27.0–27.2: worse_query cannot write this feature's target files.")
        for button, content in self.BLOCKED_PAGES:
            self.block(getattr(self.ui, button), reason, show=True)
            self.block(getattr(self.ui, content), reason)
        # SpringBoard is mixed: the SystemGroup footnote remains editable.
        for widget in self.ui.springboardOptionsPageContent.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if widget.objectName() not in ("footnoteLbl", "footnoteTxt", "footnoteLine"):
                self.block(widget, reason)
        self.block(self.ui.rdarFixChk, reason, show=True)
        self.block(self.ui.enableiPadOSChk, QCoreApplication.tr(
            "Unavailable on iOS 27.0–27.2: the original iPadOS option also modifies CacheData, which this bridge does not support."
        ), show=True)
        for name in self.RESTORE_ONLY:
            self.block(getattr(self.ui, name), QCoreApplication.tr(
                "Unavailable on iOS 27.0–27.2: this option requires the old backup-restore transport."
            ))
        self.block(self.ui.resetPBDrp, QCoreApplication.tr(
            "Unavailable on iOS 27.0–27.2: PosterBoard directory reset is not implemented by the container bridge."
        ))
        # Keep the MG-only AI alternative available; only its legacy controls
        # are disabled (the page chooses whether to display those controls).
        for name in ("euEnablerContent", "createEligFolderContent", "eligFileChk", "aiEnablerSpoofContent"):
            self.block(getattr(self.ui, name), reason)
