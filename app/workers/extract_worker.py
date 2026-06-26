"""Background worker for character extraction.

Runs the PDF -> chunk -> map-reduce pipeline off the Qt UI thread so the
interface stays responsive during long LLM jobs.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.core.config import CONFIG
from app.schemas.characters import Character
from app.services import (
    afterword,
    chapter_service,
    character_service,
    front_matter,
    portrait_service,
    project_service,
    research_service,
    story_service,
    style_service,
)

logger = logging.getLogger(__name__)


class ExtractWorker(QThread):
    """Loads a PDF and extracts the character registry, emitting progress."""

    progress = Signal(int, int, str)          # done, total, label
    partial = Signal(list)                    # provisional list[Character]
    style_ready = Signal(str)                 # style bible summary for the UI
    finished_ok = Signal(list)                # final list[Character]
    failed = Signal(str)                      # error message

    def __init__(self, pdf_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def _build_index(self, project, content_chapters: list) -> None:
        """Add ch00 front matter + a Nachwort and write the chapters index."""
        ordered = list(content_chapters)
        if CONFIG.extraction.front_matter:
            fm = front_matter.build(
                project, [{"number": c.number, "title": c.title,
                           "chapter_id": c.chapter_id} for c in content_chapters])
            chapter_service.save_chapter(project, fm)
            ordered = [fm, *ordered]
        if CONFIG.extraction.afterword:
            aw = afterword.build(
                project, number=(content_chapters[-1].number + 1) if content_chapters else 1)
            if aw is not None:
                chapter_service.save_chapter(project, aw)
                ordered.append(aw)
        chapter_service.save_index(project, ordered)

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        try:
            from app.services import comfy_launcher
            comfy_launcher.release_pool()   # free the extra render instances' VRAM
            comfy_launcher.free_vram()      # and unload the base instance's models
            self.progress.emit(0, 0, "Reading PDF…")
            project = project_service.open_project(self._pdf_path)
            project_service.save_source(project, self._pdf_path)

            # Chapter-centric extraction: detect -> rolling summaries + mentions
            # -> roster -> heuristic plan + LLM speaker refine (story_service).
            characters, content_chapters = story_service.extract_story(
                project,
                progress=lambda d, t, label: self.progress.emit(d, t, label),
                is_cancelled=self._is_cancelled,
                partial=lambda chars: self.partial.emit(chars),
            )
            if self._cancelled:
                self.failed.emit("Cancelled.")
                return
            if not content_chapters:
                self.failed.emit("No extractable text found in PDF.")
                return

            # Optional online research (spoiler-filtered) for looks/voice + style.
            web_style_ctx = ""
            if CONFIG.extraction.web_search:
                characters = character_service.enrich_with_web(
                    characters,
                    project.title,
                    progress=lambda d, t, label: self.progress.emit(d, t, label),
                )
                self.progress.emit(0, 0, "Researching book style online")
                web_style_ctx = research_service.style_context(project.title)

            # Style bible from the opening chapters (LLM still loaded).
            self.progress.emit(0, 0, "Building style bible")
            sample = "\n".join(c.text for c in content_chapters[:2])[:12000]
            bible = style_service.generate_style_bible(
                project.title, sample, web_context=web_style_ctx
            )
            portrait_service.set_style_bible(bible)
            self.style_ready.emit(f"{bible.genre} · {bible.art_style}")

            # Per-character portrait prompts while the LLM is still loaded.
            characters = character_service.write_portrait_prompts(
                characters,
                bible,
                progress=lambda d, t, label: self.progress.emit(d, t, label),
            )

            # Persist characters + style bible (afterword reads the style genre).
            project_service.save_characters(project, characters)
            project_service.save_style_bible(project, bible)

            # Front matter + afterword + the chapters index (so the Chapters
            # screen shows the curated storyboards straight after import).
            self.progress.emit(0, 0, "Building intro / outro chapters")
            self._build_index(project, content_chapters)

            self.finished_ok.emit(characters)
        except Exception as err:  # surfaced to the UI, never crash the thread
            logger.exception("Extraction failed")
            self.failed.emit(str(err))
