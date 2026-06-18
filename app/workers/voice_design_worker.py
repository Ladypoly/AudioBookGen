"""Background worker that designs a voice from a character profile."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.services import comfy_launcher, ollama_service, project_service, voice_design

logger = logging.getLogger(__name__)


class VoiceDesignWorker(QThread):
    step = Signal(int, int)        # progress value, max
    started_work = Signal()        # render lock acquired -> generating now (not queued)
    finished_ok = Signal(str)      # saved voice sample path
    failed = Signal(str)           # error

    def __init__(self, character: Character, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._char = character

    def run(self) -> None:  # noqa: D102
        try:
            with comfy_launcher.RENDER_LOCK:        # one render at a time (queue)
                self.started_work.emit()
                ollama_service.unload()             # free VRAM
                comfy_launcher.ensure_stage("tts")  # tts_audio_suite (Qwen3 designer)
                proj = project_service.active()
                base = proj.voices_dir if proj is not None else Path("voices")
                out = base / f"{self._char.character_id}.mp3"
                voice_design.design_voice(
                    self._char, out, on_step=lambda v, m: self.step.emit(v, m)
                )
            self.finished_ok.emit(str(out))
        except Exception as err:  # noqa: BLE001
            logger.exception("Voice design failed")
            self.failed.emit(str(err))
