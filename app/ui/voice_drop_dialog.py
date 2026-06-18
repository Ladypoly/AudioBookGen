"""Popup shown when a voice sample is dropped on a character: apply the sample
as-is, optimize it (denoise + loudness-match, then apply automatically), or
cancel.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.workers.voice_optimize_worker import VoiceOptimizeWorker

logger = logging.getLogger(__name__)


class VoiceDropDialog(QDialog):
    def __init__(self, src_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign voice")
        self.setMinimumWidth(380)
        self._src = str(src_path)
        self._chosen = ""
        self._worker = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Assign voice from <b>{Path(self._src).name}</b>?"))
        self._status = QLabel("")
        self._status.setObjectName("Subtle")
        lay.addWidget(self._status)

        btns = QHBoxLayout()
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.clicked.connect(self._apply)
        self._btn_opt = QPushButton("Optimize")
        self._btn_opt.setToolTip("Denoise + match loudness, then apply automatically")
        self._btn_opt.clicked.connect(self._optimize)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for b in (self._btn_apply, self._btn_opt, cancel):
            btns.addWidget(b)
        lay.addLayout(btns)

    def result_path(self) -> str:
        return self._chosen

    def _apply(self) -> None:
        self._chosen = self._src
        self.accept()

    def _optimize(self) -> None:
        self._btn_apply.setEnabled(False)
        self._btn_opt.setEnabled(False)
        self._status.setText("Optimizing… (denoise + normalize)")
        self._worker = VoiceOptimizeWorker(self._src, False, True, False, parent=self)
        self._worker.finished_ok.connect(self._done)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _done(self, res: dict) -> None:
        out = res.get("out", "")
        if out and Path(out).exists():
            self._chosen = out          # auto-apply the optimized file
            self.accept()
        else:
            self._fail("no output")

    def _fail(self, msg: str) -> None:
        self._btn_apply.setEnabled(True)
        self._btn_opt.setEnabled(True)
        self._status.setText(f"Optimize failed: {msg[:160]}")
