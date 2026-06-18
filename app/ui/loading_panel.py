"""Animated loading panel: ASCII cat + multi-step progress.

Reusable for any long job. Shows a cycling ASCII animation, a stepper of named
phases, a progress bar, and a sub-status line. Hidden when idle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


class CatAnimation(QLabel):
    """A QLabel that cycles through ASCII frames on a timer."""

    def __init__(self, frames: list[str], interval_ms: int = 350) -> None:
        super().__init__()
        self._frames = frames
        self._i = 0
        self.setFont(QFont("Consolas", 11))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color:#9daaf2;")
        self.setText(frames[0])
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def set_frames(self, frames: list[str]) -> None:
        self._frames = frames
        self._i = 0
        self.setText(frames[0])

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._i = (self._i + 1) % len(self._frames)
        self.setText(self._frames[self._i])


class LoadingPanel(QFrame):
    """Cat animation + step chips + progress bar + sub-status."""

    def __init__(self, steps: list[str]) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._steps = steps
        self._step_labels: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        from app.ui.ascii_art import READING_CAT

        self.cat = CatAnimation(READING_CAT)
        root.addWidget(self.cat)

        # step chips
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch(1)
        for i, name in enumerate(steps):
            lbl = QLabel(f"{name}")
            lbl.setObjectName("Chip")
            self._step_labels.append(lbl)
            chips.addWidget(lbl)
            if i < len(steps) - 1:
                arrow = QLabel("→")
                arrow.setObjectName("Subtle")
                chips.addWidget(arrow)
        chips.addStretch(1)
        root.addLayout(chips)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)

        self.substatus = QLabel("")
        self.substatus.setObjectName("Subtle")
        self.substatus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.substatus)

    # --- control --------------------------------------------------------------

    def start(self, frames: list[str] | None = None) -> None:
        if frames is not None:
            self.cat.set_frames(frames)
        self.cat.start()
        self.show()

    def finish(self) -> None:
        self.cat.stop()
        self.hide()

    def set_active_step(self, name: str) -> None:
        for lbl in self._step_labels:
            active = lbl.text() == name
            lbl.setStyleSheet(
                "background:#3a6df0;color:#fff;border-radius:9px;padding:2px 9px;"
                if active
                else ""
            )

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)  # indeterminate

    def set_substatus(self, text: str) -> None:
        self.substatus.setText(text)
