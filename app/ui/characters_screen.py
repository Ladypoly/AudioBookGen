"""Characters screen: load a PDF, extract characters (live), render cards.

Flow matches the VRAM constraint: text extraction (Ollama) runs first and
streams provisional cards as it reads; portraits (Ideogram) are a separate
phase that frees the LLM from VRAM before rendering.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.schemas.characters import Character
from app.services import portrait_service, project_service
from app.ui.ascii_art import READING_CAT
from app.ui.character_card import CharacterCard
from app.ui.flow_layout import FlowLayout
from app.ui.loading_panel import LoadingPanel
from app.workers.batch_portrait_worker import BatchPortraitWorker
from app.workers.batch_voice_worker import BatchVoiceWorker
from app.workers.extract_worker import ExtractWorker

logger = logging.getLogger(__name__)

_STEPS = ["Reading PDF", "Reading text", "Merging", "Research", "Style", "Done"]


class CharactersScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: ExtractWorker | None = None
        self._batch: BatchPortraitWorker | None = None
        self._pdf_path: str | None = None
        self._characters: list[Character] = []
        self._batch_label = ""
        self._build_ui()

    # --- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Characters")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        subtitle = QLabel(
            "Extract the cast from a book PDF. Spoiler-safe: only names, "
            "roles, and voice hints are shown. Portraits render after reading."
        )
        subtitle.setObjectName("Subtle")
        root.addWidget(subtitle)

        # action bar — a wrapping flow layout so the window can be made narrow
        bar_host = QWidget()
        bar = FlowLayout(bar_host, margin=0, spacing=8)
        self.portraits_btn = QPushButton("Generate all portraits")
        self.portraits_btn.setEnabled(False)
        self.portraits_btn.clicked.connect(self._start_portraits)
        self.voices_btn = QPushButton("Generate all voices")
        self.voices_btn.setEnabled(False)
        self.voices_btn.clicked.connect(self._start_voices)
        self.reextract_btn = QPushButton("Re-extract")
        self.reextract_btn.setToolTip("Re-run character extraction for this book.")
        self.reextract_btn.setEnabled(False)
        self.reextract_btn.clicked.connect(self._start_extraction)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)
        for b in (self.portraits_btn, self.voices_btn, self.reextract_btn,
                  self.cancel_btn):
            bar.addWidget(b)
        root.addWidget(bar_host)

        self.path_label = QLabel("")
        self.path_label.setObjectName("Subtle")
        self.path_label.setWordWrap(True)
        root.addWidget(self.path_label)

        # animated loading panel (hidden when idle)
        self.loading = LoadingPanel(_STEPS)
        self.loading.hide()
        root.addWidget(self.loading)

        self.status = QLabel("")
        self.status.setObjectName("Subtle")
        root.addWidget(self.status)

        # cards scroll area (responsive flow layout, dark-blue backdrop)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("CardsScroll")
        self.cards_host = QWidget()
        self.cards_host.setObjectName("CardsHost")
        self.grid = FlowLayout(self.cards_host, margin=12, spacing=16)
        self.scroll.setWidget(self.cards_host)
        root.addWidget(self.scroll, stretch=1)
        self._show_empty("No characters yet.")

    # --- actions -------------------------------------------------------------

    def open_pdf(self, path: str) -> None:
        """Open an existing project (load its saved characters)."""
        self._pdf_path = path
        self.path_label.setText(path)
        self.reextract_btn.setEnabled(True)
        self._load_existing(path)

    def start_new(self, path: str) -> None:
        """New project: create it and immediately run extraction with progress."""
        self._pdf_path = path
        self.path_label.setText(path)
        self.reextract_btn.setEnabled(True)
        project_service.open_project(path)     # create folder + make active
        self._start_extraction()

    def _load_existing(self, path: str) -> None:
        """Reopen a previously-extracted book from its project folder."""
        project = project_service.open_project(path)
        saved = project_service.load_characters(project)
        bible = project_service.load_style_bible(project)
        if bible is not None:
            portrait_service.set_style_bible(bible)
        if saved:
            self._characters = saved
            self._render_cards(saved)
            self.portraits_btn.setEnabled(True)
            self.voices_btn.setEnabled(True)
            extra = f" · style: {bible.genre}" if bible else ""
            self.status.setText(
                f"Loaded saved project — {len(saved)} characters{extra}. "
                "Re-extract to refresh, or generate portraits."
            )
        else:
            self.status.setText("New book — extract to begin.")

    def _start_extraction(self) -> None:
        if not self._pdf_path:
            return
        self._clear_cards()
        self._characters = []
        self._set_running(True)
        self.loading.start(READING_CAT)
        self.loading.set_active_step("Reading PDF")
        self.loading.set_progress(0, 0)
        self._worker = ExtractWorker(self._pdf_path, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.partial.connect(self._on_partial)
        self._worker.style_ready.connect(
            lambda s: self.status.setText(f"Style: {s}")
        )
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _start_portraits(self) -> None:
        if not self._characters:
            return
        self.portraits_btn.setEnabled(False)
        self.status.setText("Freeing VRAM, then rendering portraits…")
        self._batch = BatchPortraitWorker(self._characters, self)
        self._batch.progress.connect(self._on_batch_progress)
        self._batch.step.connect(
            lambda v, m: self.status.setText(f"{self._batch_label} — sampling {v}/{m}")
        )
        self._batch.one_done.connect(self._on_portrait_done)
        self._batch.finished_all.connect(self._on_portraits_done)
        self._batch.start()

    def _start_voices(self) -> None:
        if not self._characters:
            return
        self.voices_btn.setEnabled(False)
        self.portraits_btn.setEnabled(False)
        self.status.setText("Freeing VRAM, then designing voices…")
        self._vbatch = BatchVoiceWorker(self._characters, self)
        self._vbatch.progress.connect(self._on_voice_progress)
        self._vbatch.failed.connect(
            lambda cid, msg: logger.warning("voice failed %s: %s", cid, msg)
        )
        self._vbatch.finished_all.connect(self._on_voices_done)
        self._vbatch.start()

    def _on_voice_progress(self, done: int, total: int, label: str) -> None:
        self.status.setText(f"{label} {done}/{total}")

    def _on_voices_done(self) -> None:
        self.voices_btn.setEnabled(True)
        self.portraits_btn.setEnabled(True)
        self._render_cards(self._characters)  # refresh cards to show assigned voices
        self.status.setText("Voices done.")

    def _on_batch_progress(self, done: int, total: int, name: str) -> None:
        self._batch_label = f"Portrait {done}/{total}: {name}"
        self.status.setText(self._batch_label)

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.loading.set_substatus("Cancelling…")

    # --- worker signal handlers ---------------------------------------------

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self.loading.set_progress(done, total)
        self.loading.set_substatus(label)
        if label.startswith("Reading chunk") or label.startswith("Read chunk"):
            self.loading.set_active_step("Reading text")
        elif label.startswith("Merging"):
            self.loading.set_active_step("Merging")
        elif label.startswith("Researching"):
            self.loading.set_active_step("Research")
        elif label.startswith("Building style") or label.startswith("Writing portrait"):
            self.loading.set_active_step("Style")

    def _on_partial(self, characters: list) -> None:
        self._render_cards(characters)
        self.status.setText(f"Reading… {len(characters)} characters so far")

    def _on_finished(self, characters: list) -> None:
        self._characters = characters
        self.loading.set_active_step("Done")
        self.loading.finish()
        self._set_running(False)
        self._render_cards(characters)
        self.portraits_btn.setEnabled(bool(characters))
        self.voices_btn.setEnabled(bool(characters))
        self.status.setText(
            f"Done — {len(characters)} characters. "
            "Generate portraits/voices when ready (frees the LLM from VRAM first)."
        )

    def _on_failed(self, message: str) -> None:
        self.loading.finish()
        self._set_running(False)
        self.status.setText(f"Failed: {message}")
        if message != "Cancelled.":
            QMessageBox.warning(self, "Extraction failed", message)

    def _on_portrait_done(self, cid: str, path: str) -> None:
        for c in self._characters:
            if c.character_id == cid:
                c.portrait_path = path
                break
        self._render_cards(self._characters)

    def _on_portraits_done(self) -> None:
        self.portraits_btn.setEnabled(True)
        # persist portrait paths back into the project registry
        proj = project_service.active()
        if proj is not None and self._characters:
            project_service.save_characters(proj, self._characters)
        self.status.setText("Portraits done.")

    # --- helpers -------------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        self.cancel_btn.setVisible(running)
        self.reextract_btn.setEnabled(not running and self._pdf_path is not None)
        if running:
            self.portraits_btn.setEnabled(False)
            self.voices_btn.setEnabled(False)

    def _clear_cards(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _show_empty(self, text: str) -> None:
        self._clear_cards()
        lbl = QLabel(text)
        lbl.setObjectName("Subtle")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(lbl)

    def _render_cards(self, characters: list[Character]) -> None:
        self._clear_cards()
        if not characters:
            self._show_empty("No characters detected.")
            return
        for ch in characters:
            card = CharacterCard(ch)
            card.voice_assigned.connect(self._on_voice_assigned)
            self.grid.addWidget(card)

    def _on_voice_assigned(self, character_id: str, _sample_path: str) -> None:
        # the card already set character.voice_sample on the shared object;
        # just persist the registry.
        proj = project_service.active()
        if proj is not None and self._characters:
            project_service.save_characters(proj, self._characters)
