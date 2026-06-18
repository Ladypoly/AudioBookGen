"""Generate scene audio (ambience beds + discrete SFX) for chapters via Stable
Audio, spread over the parallel ComfyUI audio pool."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.services import (
    ambience, chapter_service, comfy_launcher, line_planner, music_planner,
    ollama_service, project_service, render_pool, sfx_planner, sound_service,
)

logger = logging.getLogger(__name__)


class AmbienceWorker(QThread):
    progress = Signal(int, int, str)   # done, total, label
    finished_all = Signal()
    failed = Signal(str)

    def __init__(self, chapter_infos: list[dict], characters: list | None = None,
                 force: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._infos = chapter_infos
        self._chars = characters or []
        self._force = force
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        ollama_service.unload()
        try:
            urls = comfy_launcher.ensure_pool("audio")
        except comfy_launcher.LauncherError as err:
            self.failed.emit(f"ComfyUI launch failed: {err}")
            self.finished_all.emit()
            return

        proj = project_service.active()
        if proj is None:
            self.failed.emit("No active project")
            self.finished_all.emit()
            return

        def gen(info: dict) -> None:
            from app.core.config import CONFIG
            ch = chapter_service.load_chapter(proj, info["chapter_id"])
            if ch is None:
                return
            # ambience bed
            amb = proj.ambience_path(ch.chapter_id)
            if CONFIG.tts.ambience_enabled and (self._force or not amb.exists()):
                prompt, secs = ambience.ambience_for_chapter(ch)
                sound_service.generate(prompt, secs, amb, kind="ambience")
            # intro music cue
            mus = proj.music_path(ch.chapter_id)
            if CONFIG.tts.music_enabled and (self._force or not mus.exists()):
                prompt, secs = music_planner.music_for_chapter(ch)
                sound_service.generate(prompt, secs, mus, kind="music")
            # discrete SFX (needs the line plan to find sound events)
            if CONFIG.tts.sfx_enabled:
                if not (ch.curated and ch.lines):
                    ch.lines = line_planner.plan_chapter(ch, self._chars)
                sfx_planner.annotate(ch.lines)
                sfx_planner.generate_chapter_sfx(proj, ch, force=self._force)

        render_pool.map_over_pool(
            urls, self._infos, gen,
            on_done=lambda d, t: self.progress.emit(d, t, "Scene audio"),
            is_cancelled=lambda: self._cancelled,
        )
        self.finished_all.emit()
