"""Sequential batch portrait generation (VRAM-safe).

Frees the Ollama model from VRAM first, then renders one portrait at a time
through ComfyUI so the 24 GB GPU is never shared between the LLM and Ideogram,
and never runs two image jobs at once.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.services import comfy_launcher, ollama_service, portrait_service

logger = logging.getLogger(__name__)


class BatchPortraitWorker(QThread):
    progress = Signal(int, int, str)         # done, total, character display name
    step = Signal(int, int)                  # sampler value, max (current portrait)
    one_done = Signal(str, str)              # character_id, image_path
    finished_all = Signal()
    failed = Signal(str, str)                # character_id, error

    def __init__(self, characters: list[Character], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._chars = characters
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        ollama_service.unload()  # free VRAM for Ideogram
        try:
            comfy_launcher.ensure_stage("image")  # lean, core-only ComfyUI
        except comfy_launcher.LauncherError as err:
            self.failed.emit("", f"ComfyUI launch failed: {err}")
            self.finished_all.emit()
            return
        total = len(self._chars)
        for i, ch in enumerate(self._chars, start=1):
            if self._cancelled:
                break
            self.progress.emit(i - 1, total, ch.display_name)
            try:
                path = portrait_service.generate_portrait(
                    ch, on_step=lambda v, m: self.step.emit(v, m)
                )
                self.one_done.emit(ch.character_id, str(path))
            except Exception as err:
                logger.exception("Portrait failed for %s", ch.character_id)
                self.failed.emit(ch.character_id, str(err))
            self.progress.emit(i, total, ch.display_name)
        self.finished_all.emit()
