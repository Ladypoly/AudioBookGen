"""Dashboard: recent projects + create/open."""

from __future__ import annotations

from pathlib import Path

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
    opened = Signal(str)         # source_pdf
    cover_changed = Signal()     # user set a custom cover -> refresh dashboard

    def __init__(self, info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(280)
        self._pdf = info.get("source_pdf", "")
        self._root = info.get("root", "")

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
        row = QHBoxLayout()
        btn = QPushButton("Open")
        btn.setObjectName("Primary")
        btn.clicked.connect(lambda: self.opened.emit(self._pdf))
        row.addWidget(btn, stretch=1)
        cover_btn = QPushButton("Cover…")
        cover_btn.setToolTip("Set a custom cover image for this book")
        cover_btn.clicked.connect(self._set_cover)
        row.addWidget(cover_btn)
        lay.addLayout(row)

    def _set_cover(self) -> None:
        if not self._root:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose cover image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        pix.save(str(Path(self._root) / "cover.png"), "PNG")   # normalise to PNG
        self.cover_changed.emit()


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
            card.cover_changed.connect(self.refresh)
            self.flow.addWidget(card)

    def _new(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose book PDF", "", "PDF files (*.pdf)"
        )
        if path:
            self.new_project.emit(path)
