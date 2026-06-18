"""Batch voice generation for the whole cast, across a parallel ComfyUI pool.

Two phases so each model loads once per instance:
  Phase A — Qwen3 designs a timbre sample for every character.
  Phase B — Higgs renders an emotion-varied German Hörprobe for every character.
Work is spread over CONFIG.comfy.parallel instances (each ~10 GB VRAM).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.schemas.voice import Voice
from app.services import (
    comfy_launcher, ollama_service, project_service, render_pool, voice_design,
)
from app.services.tts import preview, registry
from app.services.tts.base import TTSRequest

logger = logging.getLogger(__name__)


class BatchVoiceWorker(QThread):
    progress = Signal(int, int, str)   # done, total, label
    one_done = Signal(str, str)        # character_id, voice_sample path
    finished_all = Signal()
    failed = Signal(str, str)          # character_id, error

    def __init__(self, characters: list[Character], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._chars = characters
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        ollama_service.unload()
        try:
            urls = comfy_launcher.ensure_pool("tts")
        except comfy_launcher.LauncherError as err:
            self.failed.emit("", f"ComfyUI launch failed: {err}")
            self.finished_all.emit()
            return

        proj = project_service.active()
        if proj is None:
            self.failed.emit("", "No active project")
            self.finished_all.emit()
            return

        cancelled = lambda: self._cancelled  # noqa: E731

        # Never regenerate over a user-supplied custom voice.
        targets = [c for c in self._chars if not c.custom_voice]

        # --- Phase A: Qwen voice design (timbre) for all --------------------
        def design(ch: Character) -> None:
            ref = proj.voice_sample_path(ch.character_id)
            voice_design.design_voice(ch, ref)
            ch.voice_sample = str(ref)
            self.one_done.emit(ch.character_id, str(ref))

        render_pool.map_over_pool(
            urls, targets, design,
            on_done=lambda d, t: self.progress.emit(d, t, "Designing voices"),
            is_cancelled=cancelled,
        )
        project_service.save_characters(proj, self._chars)

        # --- Phase B: Higgs emotion-varied Hörprobe for all -----------------
        engine = registry.get_engine()
        text = preview.build_emotional_preview()
        with_voice = [c for c in targets if c.voice_sample]

        def hoerprobe(ch: Character) -> None:
            v = Voice(voice_id=ch.character_id, name=ch.display_name,
                      ref_audio_path=ch.voice_sample)
            engine.synthesize(TTSRequest(
                text=text, voice=v, delivery=None,
                out_path=proj.preview_path(ch.character_id),
            ))

        render_pool.map_over_pool(
            urls, with_voice, hoerprobe,
            on_done=lambda d, t: self.progress.emit(d, t, "Hörproben"),
            is_cancelled=cancelled,
        )
        self.finished_all.emit()
