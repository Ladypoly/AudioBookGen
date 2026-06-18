"""Background worker for a short voice preview (Higgs, German, emotion-varied).

Engine-agnostic via the TTS registry. Saves the rendered preview to a stable
path so it can be reused instead of re-rendered.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.core.config import CONFIG
from app.schemas.voice import Voice
from app.services import comfy_launcher, ollama_service
from app.services.tts import preview, registry
from app.services.tts.base import TTSRequest

logger = logging.getLogger(__name__)


class TTSPreviewWorker(QThread):
    step = Signal(int, int)       # progress value, max
    started_work = Signal()       # render lock acquired -> generating now (not queued)
    finished_ok = Signal(str)     # audio path
    failed = Signal(str)          # error message

    def __init__(
        self,
        voice: Voice | None,
        out_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._voice = voice
        self._out = out_path

    def run(self) -> None:  # noqa: D102
        try:
            with comfy_launcher.RENDER_LOCK:           # one render at a time (queue)
                self.started_work.emit()
                ollama_service.unload()                # free VRAM for the TTS model
                comfy_launcher.ensure_stage("tts")     # lean ComfyUI: tts_audio_suite
                engine = registry.get_engine()
                stem = self._voice.voice_id if self._voice else "default"
                out = self._out or (Path(CONFIG.tts.library_dir) / "previews" / f"{stem}.mp3")
                # emotion-varied, already Higgs-tagged -> delivery=None (pass-through)
                engine.synthesize(
                    TTSRequest(text=preview.build_emotional_preview(),
                               voice=self._voice, delivery=None, out_path=out),
                    on_step=lambda v, m: self.step.emit(v, m),
                )
            self.finished_ok.emit(str(out))
        except Exception as err:  # noqa: BLE001
            logger.exception("TTS preview failed")
            self.failed.emit(str(err))
