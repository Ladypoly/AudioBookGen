"""Dashboard: recent projects + create/open."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import project_service
from app.ui.flow_layout import FlowLayout


class ProjectCard(QFrame):
    opened = Signal(str)  # source_pdf

    def __init__(self, info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(280)
        self._pdf = info.get("source_pdf", "")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        cover = info.get("cover", "")
        if cover:
            pix = QPixmap(cover)
            if not pix.isNull():
                pix = pix.scaledToWidth(248, Qt.TransformationMode.SmoothTransformation)
                if pix.height() > 230:
                    pix = pix.scaledToHeight(230, Qt.TransformationMode.SmoothTransformation)
                img = QLabel()
                img.setObjectName("CoverImg")
                img.setPixmap(pix)
                img.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(img)

        name = QLabel(info["title"])
        name.setObjectName("CardName")
        name.setWordWrap(True)
        lay.addWidget(name)
        meta = QLabel(f"{info['character_count']} characters")
        meta.setObjectName("Subtle")
        lay.addWidget(meta)
        btn = QPushButton("Open")
        btn.setObjectName("Primary")
        btn.clicked.connect(lambda: self.opened.emit(self._pdf))
        lay.addWidget(btn)


class DashboardScreen(QWidget):
    open_project = Signal(str)  # source_pdf
    new_project = Signal(str)   # chosen pdf

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Book2AudioDrama")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        bar = QHBoxLayout()
        new_btn = QPushButton("New project (choose PDF)…")
        new_btn.setObjectName("Primary")
        new_btn.clicked.connect(self._new)
        bar.addWidget(new_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        sub = QLabel("Recent projects")
        sub.setObjectName("Subtle")
        root.addWidget(sub)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.flow = FlowLayout(self.host, margin=4, spacing=16)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, stretch=1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            if w:
                w.deleteLater()
        projects = project_service.list_projects()
        if not projects:
            lbl = QLabel("No projects yet — create one from a PDF.")
            lbl.setObjectName("Subtle")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.flow.addWidget(lbl)
            return
        for info in projects:
            card = ProjectCard(info)
            card.opened.connect(self.open_project.emit)
            self.flow.addWidget(card)

    def _new(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose book PDF", "", "PDF files (*.pdf)"
        )
        if path:
            self.new_project.emit(path)
