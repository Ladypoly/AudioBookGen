"""Background worker that renders one chapter to audio."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.schemas.characters import Character
from app.schemas.script import Chapter
from app.services import (
    ambience, chapter_render, chapter_service, comfy_launcher, line_planner,
    music_planner, ollama_service, project_service, sfx_planner, sound_service,
)

logger = logging.getLogger(__name__)


class ChapterRenderWorker(QThread):
    progress = Signal(int, int, str)   # line done, total, speaker
    finished_ok = Signal(str, str)     # chapter_id, audio path
    failed = Signal(str)               # error

    def __init__(self, chapter: Chapter, characters: list[Character],
                 force: bool = False, test: bool = False,
                 redo_voices: bool = False, redo_ambience: bool = False,
                 redo_sfx: bool = False, redo_voices_no_narrator: bool = False,
                 mix_only: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._chapter = chapter
        self._chars = characters
        self._force = force
        self._test = test
        self._redo_voices = redo_voices
        self._redo_ambience = redo_ambience
        self._redo_sfx = redo_sfx
        self._redo_voices_no_narrator = redo_voices_no_narrator
        self._mix_only = mix_only
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        try:
            from pathlib import Path

            from app.services import project_service as ps
            ch = self._chapter
            # Use an agent-curated plan as-is; otherwise (re)plan heuristically
            # from text (deterministic + instant, so it never goes stale).
            if not (ch.curated and ch.lines):
                ch.lines = line_planner.plan_chapter(ch, self._chars)
            line_planner.prepend_title(ch)      # narrator announces the title
            if self._test:  # only the first pages (narrator + a few dialogues)
                ch.lines = line_planner.test_slice(ch.lines)
            # voices re-render when forced (test, full, or "voices only")
            force = self._force or self._test or self._redo_voices
            proj0 = ps.active()

            # Mix only: no generation at all — point lines at existing clips and
            # re-assemble (fast; e.g. after tweaking pauses/levels).
            if self._mix_only and proj0 is not None:
                out_dir = proj0.line_audio_dir / ch.chapter_id
                for ln in ch.lines:
                    clip = out_dir / f"{ln.line_id}.mp3"
                    if clip.exists():
                        ln.audio_path = str(clip)
                path = chapter_render.assemble(ch)
                chapter_service.save_chapter(proj0, ch)
                self.finished_ok.emit(ch.chapter_id, path or "")
                return

            # A chapter render is self-contained: generate its scene audio
            # (ambience bed + discrete SFX) if missing OR explicitly re-requested.
            if proj0 is not None:
                from app.core.config import CONFIG
                sfx_planner.annotate(ch.lines)
                if self._redo_ambience:   # force regen by clearing the old files
                    proj0.ambience_path(ch.chapter_id).unlink(missing_ok=True)
                    proj0.music_path(ch.chapter_id).unlink(missing_ok=True)
                need_amb = (CONFIG.tts.ambience_enabled
                            and not proj0.ambience_path(ch.chapter_id).exists())
                need_mus = (CONFIG.tts.music_enabled
                            and not proj0.music_path(ch.chapter_id).exists())
                need_sfx = CONFIG.tts.sfx_enabled and (self._redo_sfx or any(
                    not proj0.sfx_clip_path(c).exists() for c in sfx_planner.cues_for(ch)))
                if need_amb or need_mus or need_sfx:
                    self.progress.emit(0, 0, "Generating scene audio")
                    ollama_service.unload()
                    comfy_launcher.ensure_stage("audio")
                    if need_amb:
                        prompt, secs = ambience.ambience_for_chapter(ch)
                        sound_service.generate(prompt, secs,
                                               proj0.ambience_path(ch.chapter_id),
                                               kind="ambience")
                    if need_mus:
                        prompt, secs = music_planner.music_for_chapter(ch)
                        sound_service.generate(prompt, secs,
                                               proj0.music_path(ch.chapter_id),
                                               kind="music")
                    if need_sfx:
                        sfx_planner.generate_chapter_sfx(proj0, ch, force=self._redo_sfx)

            # Reload characters from the registry so voice references (custom
            # flag / sample) are current, not whatever was on screen earlier.
            if proj0 is not None:
                fresh = project_service.load_characters(proj0)
                if fresh:
                    self._chars = fresh

            out_dir = proj0.line_audio_dir / ch.chapter_id if proj0 else None
            # "Character voices (no narrator)": drop non-narrator clips so they
            # re-render (cloning the current character previews) while the
            # narrator's lines are kept untouched.
            if self._redo_voices_no_narrator and out_dir is not None:
                for ln in ch.lines:
                    if ln.speaker_id != line_planner.NARRATOR_ID:
                        (out_dir / f"{ln.line_id}.mp3").unlink(missing_ok=True)

            # If every clip already exists and we're not forcing, this is a pure
            # re-assemble (e.g. tuning pauses) — skip the slow ComfyUI launch.
            all_present = bool(ch.lines) and out_dir is not None and all(
                (out_dir / f"{l.line_id}.mp3").exists() for l in ch.lines)

            if force or not all_present:
                ollama_service.unload()
                urls = comfy_launcher.ensure_pool("tts")
                chapter_render.render_lines(
                    ch, self._chars,
                    progress=lambda d, t, n: self.progress.emit(d, t, n),
                    is_cancelled=lambda: self._cancelled,
                    urls=urls, force=force,
                )
            else:
                self.progress.emit(0, 0, "Re-assembling")
                for l in ch.lines:  # point lines at their existing clips
                    l.audio_path = str(out_dir / f"{l.line_id}.mp3")

            path = chapter_render.assemble(ch, suffix="_test" if self._test else "")
            proj = project_service.active()
            if proj is not None and not self._test:  # don't persist a slice
                chapter_service.save_chapter(proj, ch)
            self.finished_ok.emit(ch.chapter_id, path or "")
        except Exception as err:  # noqa: BLE001
            logger.exception("Chapter render failed")
            self.failed.emit(str(err))
