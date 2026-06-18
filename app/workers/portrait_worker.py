"""Background worker for single-character portrait generation."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.services import comfy_launcher, ollama_service, portrait_service

logger = logging.getLogger(__name__)


class PortraitWorker(QThread):
    step = Signal(str, int, int)     # character_id, value, max
    finished_ok = Signal(str, str)   # character_id, image_path
    failed = Signal(str, str)        # character_id, error message

    def __init__(self, character: Character, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._char = character

    def run(self) -> None:  # noqa: D102
        try:
            ollama_service.unload()              # free VRAM for the image model
            comfy_launcher.ensure_stage("image")  # lean ComfyUI for this stage
            path = portrait_service.generate_portrait(
                self._char,
                on_step=lambda v, m: self.step.emit(self._char.character_id, v, m),
            )
            self.finished_ok.emit(self._char.character_id, str(path))
        except Exception as err:
            logger.exception("Portrait generation failed")
            self.failed.emit(self._char.character_id, str(err))
