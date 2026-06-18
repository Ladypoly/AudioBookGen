"""Main application window: left sidebar nav + stacked content area."""

from __future__ import annotations

import logging

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services import comfy_launcher
from app.ui.chapters_screen import ChaptersScreen
from app.ui.characters_screen import CharactersScreen
from app.ui.dashboard_screen import DashboardScreen
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import DARK_QSS

logger = logging.getLogger(__name__)

_NAV_ITEMS = ["Dashboard", "Characters", "Chapters", "Settings"]


class _Placeholder(QWidget):
    def __init__(self, name: str) -> None:
        super().__init__()
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        lay = QVBoxLayout(self)
        lbl = QLabel(f"{name}\n(coming soon)")
        lbl.setObjectName("Subtle")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Book2AudioDrama")
        self.resize(1180, 760)
        self.setStyleSheet(DARK_QSS)

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(158)
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(0, 12, 0, 12)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        for name in _NAV_ITEMS:
            QListWidgetItem(name, self.nav)
        self.nav.currentRowChanged.connect(self._switch)
        side_lay.addWidget(self.nav)
        layout.addWidget(sidebar)

        # content stack
        self.stack = QStackedWidget()
        self.dashboard = DashboardScreen()
        self.characters = CharactersScreen()
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.characters)
        self.stack.addWidget(ChaptersScreen())
        self.stack.addWidget(SettingsScreen())
        layout.addWidget(self.stack, stretch=1)

        # dashboard -> open/create a project in the Characters screen
        self.dashboard.open_project.connect(self._open_in_characters)
        self.dashboard.new_project.connect(self._open_in_characters)

        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)  # open Dashboard

    def _open_in_characters(self, pdf_path: str) -> None:
        if pdf_path:
            self.characters.open_pdf(pdf_path)
        self.nav.setCurrentRow(1)

    def _switch(self, row: int) -> None:
        if row >= 0:
            self.stack.setCurrentIndex(row)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop any ComfyUI instance we launched when the app closes."""
        try:
            comfy_launcher.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to stop ComfyUI on close")
        super().closeEvent(event)
