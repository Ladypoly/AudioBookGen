"""Render every chapter to audio in one run (shared ComfyUI pool)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.services import (
    chapter_render, chapter_service, comfy_launcher, line_planner,
    ollama_service, project_service,
)

logger = logging.getLogger(__name__)


class RenderAllWorker(QThread):
    chapter_progress = Signal(int, int, str)   # chapter done, total, label (with ETA)
    chapter_started = Signal(str)              # chapter_id now rendering
    line_progress = Signal(int, int)           # line done, total (current chapter)
    chapter_done = Signal(str, str)            # chapter_id, audio path
    qc = Signal(int, int)                      # chapters with failures, failed lines
    finished_all = Signal()
    failed = Signal(str)

    def __init__(self, infos: list[dict], characters: list[Character],
                 force: bool = False, redo_voices_no_narrator: bool = False,
                 mix_only: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._infos = infos
        self._chars = characters
        self._force = force
        self._redo_no_narrator = redo_voices_no_narrator
        self._mix_only = mix_only
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        ollama_service.unload()
        proj = project_service.active()
        if proj is None:
            self.failed.emit("No active project")
            self.finished_all.emit()
            return

        urls = None                          # ComfyUI pool launched lazily, on
        total = len(self._infos)             # the first chapter that needs it
        start = time.monotonic()
        fail_lines = 0
        fail_chapters = 0
        for i, info in enumerate(self._infos, start=1):
            if self._cancelled:
                break
            ch = chapter_service.load_chapter(proj, info["chapter_id"])
            if ch is None:
                continue
            if not (ch.curated and ch.lines):
                ch.lines = line_planner.plan_chapter(ch, self._chars)
            line_planner.prepend_title(ch)      # narrator announces the title
            done = i - 1
            eta = ""
            if done > 0:
                rem = (time.monotonic() - start) / done * (total - done)
                eta = f" · ~{int(rem // 60)}m{int(rem % 60):02d}s left"
            self.chapter_progress.emit(done, total, f"{ch.chapter_id}: {ch.title}{eta}")
            self.chapter_started.emit(ch.chapter_id)
            try:
                out_dir = proj.line_audio_dir / ch.chapter_id
                final = proj.chapter_audio_dir / f"{ch.chapter_id}.mp3"

                # Continue (no force / no narrator-redo): a chapter that already
                # has its final mix AND every line clip is DONE — skip it whole,
                # don't waste time re-assembling existing chapters.
                if (not self._mix_only and not self._force
                        and not self._redo_no_narrator and final.exists()
                        and ch.lines and all(
                            (out_dir / f"{l.line_id}.mp3").exists() for l in ch.lines)):
                    self.chapter_done.emit(ch.chapter_id, str(final))
                    continue

                if self._mix_only:           # no generation — re-assemble existing
                    for ln in ch.lines:
                        clip = out_dir / f"{ln.line_id}.mp3"
                        if clip.exists():
                            ln.audio_path = str(clip)
                else:
                    if self._redo_no_narrator:   # re-render only non-narrator lines
                        for ln in ch.lines:
                            if ln.speaker_id != line_planner.NARRATOR_ID:
                                (out_dir / f"{ln.line_id}.mp3").unlink(missing_ok=True)
                    if urls is None:         # first chapter that actually renders
                        try:
                            urls = comfy_launcher.ensure_pool("tts")
                        except comfy_launcher.LauncherError as err:
                            self.failed.emit(f"ComfyUI launch failed: {err}")
                            self.finished_all.emit()
                            return
                    chapter_render.render_lines(
                        ch, self._chars,
                        progress=lambda d, t, _n: self.line_progress.emit(d, t),
                        is_cancelled=lambda: self._cancelled,
                        urls=urls, force=self._force,
                    )
                missing = sum(1 for l in ch.lines
                              if not (l.audio_path and Path(l.audio_path).exists()))
                if missing:
                    fail_lines += missing
                    fail_chapters += 1
                path = chapter_render.assemble(ch)
                chapter_service.save_chapter(proj, ch)
                self.chapter_done.emit(ch.chapter_id, path or "")
            except Exception as err:  # noqa: BLE001
                logger.exception("Render failed for %s", ch.chapter_id)
                self.failed.emit(f"{ch.chapter_id}: {err}")
                fail_chapters += 1
        self.qc.emit(fail_chapters, fail_lines)
        self.chapter_progress.emit(total, total, "Done")
        self.finished_all.emit()
