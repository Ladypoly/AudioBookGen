"""Run the voice-sample optimize pipeline off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.services import voice_optimize

logger = logging.getLogger(__name__)


class VoiceOptimizeWorker(QThread):
    finished_ok = Signal(dict)   # {out, done, skipped}
    failed = Signal(str)

    def __init__(self, in_path: str, separate: bool, denoise: bool, enhance: bool,
                 out_path: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._in = in_path
        self._sep = separate
        self._den = denoise
        self._enh = enhance
        self._out = out_path

    def run(self) -> None:  # noqa: D102
        try:
            res = voice_optimize.optimize(
                self._in, self._out, separate=self._sep,
                denoise=self._den, enhance=self._enh)
            self.finished_ok.emit(res)
        except Exception as err:  # noqa: BLE001
            logger.exception("voice optimize failed")
            self.failed.emit(str(err))
