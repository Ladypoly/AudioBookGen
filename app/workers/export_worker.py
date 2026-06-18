"""Background worker: export the book as an M4B with chapter marks."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.services import chapter_service, export_service, project_service

logger = logging.getLogger(__name__)


class ExportWorker(QThread):
    finished_ok = Signal(str)   # output path
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:  # noqa: D102
        try:
            proj = project_service.active()
            if proj is None:
                self.failed.emit("No active project")
                return
            infos = chapter_service.load_index(proj)
            out = export_service.export_m4b(proj, infos)
            self.finished_ok.emit(str(out))
        except Exception as err:  # noqa: BLE001
            logger.exception("M4B export failed")
            self.failed.emit(str(err))
