"""Background worker: export the finished audiobook to a folder."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.services import audiobook_export, project_service

logger = logging.getLogger(__name__)


class AudiobookExportWorker(QThread):
    progress = Signal(int)       # chapters exported so far
    finished_ok = Signal(str)    # output folder
    failed = Signal(str)

    def __init__(self, dest_root: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dest = dest_root

    def run(self) -> None:  # noqa: D102
        try:
            proj = project_service.active()
            if proj is None:
                self.failed.emit("No active project")
                return
            out = audiobook_export.export_audiobook(
                proj, self._dest, on_step=lambda n: self.progress.emit(n))
            self.finished_ok.emit(str(out))
        except Exception as err:  # noqa: BLE001
            logger.exception("audiobook export failed")
            self.failed.emit(str(err))
