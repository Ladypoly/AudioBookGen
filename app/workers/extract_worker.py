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
    character_service,
    pdf_service,
    portrait_service,
    project_service,
    research_service,
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

    def run(self) -> None:  # noqa: D102 (QThread entry point)
        try:
            self.progress.emit(0, 0, "Reading PDF…")
            project = project_service.open_project(self._pdf_path)
            project_service.save_source(project, self._pdf_path)
            chunks = pdf_service.load_chunks(self._pdf_path)
            if not chunks:
                self.failed.emit("No extractable text found in PDF.")
                return

            characters: list[Character] = character_service.extract_characters(
                chunks,
                progress=lambda d, t, label: self.progress.emit(d, t, label),
                is_cancelled=self._is_cancelled,
                partial=lambda chars: self.partial.emit(chars),
                project=project,
            )
            if self._cancelled:
                self.failed.emit("Cancelled.")
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

            # Style bible while the LLM is still loaded (before portraits unload it).
            self.progress.emit(len(chunks), len(chunks), "Building style bible")
            sample = "\n".join(chunks[:2])
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

            # Persist everything into the book's project folder.
            project_service.save_characters(project, characters)
            project_service.save_style_bible(project, bible)

            self.finished_ok.emit(characters)
        except Exception as err:  # surfaced to the UI, never crash the thread
            logger.exception("Extraction failed")
            self.failed.emit(str(err))
