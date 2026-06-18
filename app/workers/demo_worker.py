"""Workers for the Settings demo: full generation vs. fast remix."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.services import demo_service

logger = logging.getLogger(__name__)


class DemoGenerateWorker(QThread):
    """Render the demo clips (voices + ambience + SFX + music) — heavy."""
    finished_ok = Signal(str)   # demo audio path
    failed = Signal(str)

    def __init__(self, voices: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._voices = voices

    def run(self) -> None:  # noqa: D102
        try:
            # always make the music clip so the demo can toggle it live
            path = demo_service.generate(self._voices, with_music=True)
            self.finished_ok.emit(path)
        except Exception as err:  # noqa: BLE001
            logger.exception("demo generation failed")
            self.failed.emit(str(err))


class DemoRemixWorker(QThread):
    """Re-assemble the demo from existing clips with current settings — fast."""
    finished_ok = Signal(str)
    failed = Signal(str)

    def run(self) -> None:  # noqa: D102
        try:
            self.finished_ok.emit(demo_service.remix())
        except Exception as err:  # noqa: BLE001
            logger.exception("demo remix failed")
            self.failed.emit(str(err))
