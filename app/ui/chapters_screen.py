"""Chapters screen: list chapters, render each to audio, play the result."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import chapter_service, pdf_service, project_service
from app.ui.audio_util import play_audio
from app.workers.ambience_worker import AmbienceWorker
from app.workers.chapter_render_worker import ChapterRenderWorker
from app.workers.render_all_worker import RenderAllWorker

logger = logging.getLogger(__name__)


class ChapterRow(QFrame):
    def __init__(self, info: dict, screen: "ChaptersScreen") -> None:
        super().__init__()
        self.setObjectName("Card")
        self._info = info
        self._screen = screen
        self._worker: ChapterRenderWorker | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        self.title = QLabel(f"{info['number']}. {info['title']}")
        self.title.setObjectName("CardName")
        top.addWidget(self.title, stretch=1)
        self.render_btn = QPushButton("Render")
        self.render_btn.setObjectName("Ghost")
        self.render_btn.clicked.connect(self._render)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setObjectName("Ghost")
        self.play_btn.clicked.connect(self._play)
        top.addWidget(self.render_btn)
        top.addWidget(self.play_btn)
        lay.addLayout(top)

        self.status = QLabel("")
        self.status.setObjectName("Subtle")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self._refresh_state()

    def _rendered_file(self):
        proj = project_service.active()
        if proj is None:
            return None
        p = proj.chapter_audio_dir / f"{self._info['chapter_id']}.mp3"
        return p if p.exists() else None

    def _refresh_state(self) -> None:
        """Green when the chapter is already rendered, neutral otherwise."""
        if self._rendered_file() is not None:
            self.title.setStyleSheet("color: #4ade80; font-weight: 600;")
            self.status.setText("✓ rendered")
            self.status.setStyleSheet("color: #4ade80;")
            self.play_btn.setEnabled(True)
        else:
            self.title.setStyleSheet("")
            self.status.setText(f"{self._info['lines']} lines" if self._info.get("lines") else "not rendered")
            self.status.setStyleSheet("")
            self.play_btn.setEnabled(False)

    def _render(self) -> None:
        proj = project_service.active()
        if proj is None:
            return
        if self._rendered_file() is not None:        # confirm overwrite
            r = QMessageBox.question(
                self, "Re-render chapter",
                f"'{self._info['number']}. {self._info['title']}' is already rendered.\n"
                "Render again and overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        chapter = chapter_service.load_chapter(proj, self._info["chapter_id"])
        if chapter is None:
            self.status.setText("chapter data missing")
            return
        self.render_btn.setEnabled(False)
        self.play_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        # Complete the chapter: reuse existing line clips + scene audio, render
        # only what's missing, then re-mix. (Fast re-mix when nothing changed —
        # e.g. after tweaking ambience/pause/master settings.)
        self._worker = ChapterRenderWorker(
            chapter, self._screen.characters, force=False, test=False, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_progress(self, done: int, total: int, speaker: str) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"Rendering line {done}/{total} — {speaker}")

    def _on_done(self, chapter_id: str, path: str) -> None:
        self.render_btn.setEnabled(True)
        self.bar.setVisible(False)
        if path:
            self._info["audio_path"] = path
        self._refresh_state()

    def _on_fail(self, msg: str) -> None:
        self.render_btn.setEnabled(True)
        self.bar.setVisible(False)
        self.status.setText(f"Failed: {msg}")
        self.status.setStyleSheet("color: #f87171;")

    def _play(self) -> None:
        f = self._rendered_file()
        if f is not None:
            play_audio(str(f))

    # --- batch (produce / render-all) progress -------------------------------
    def batch_active(self) -> None:
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText("rendering…")
        self.status.setStyleSheet("color: #f4db7d;")
        self.title.setStyleSheet("color: #f4db7d; font-weight: 600;")

    def batch_line(self, done: int, total: int) -> None:
        self.bar.setVisible(True)
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.status.setText(f"line {done}/{total}")

    def batch_done(self) -> None:
        self.bar.setVisible(False)
        self._refresh_state()


class ChaptersScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.characters: list = []
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Chapters")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        bar = QHBoxLayout()
        self.detect_btn = QPushButton("Detect chapters")
        self.detect_btn.clicked.connect(self._detect)
        self.produce_btn = QPushButton("Produce chapters")
        self.produce_btn.setToolTip("Everything: music + ambience + SFX, then render every chapter to a tagged MP3 (voices must be done on the Characters tab)")
        self.produce_btn.clicked.connect(self._produce_all)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.force_check = QCheckBox("Regenerate (overwrite)")
        self.force_check.setToolTip("Overwrite existing audiobook audio (scene audio + chapter renders). Voices are not touched — do those on the Characters tab.")
        bar.addWidget(self.detect_btn)
        bar.addWidget(self.produce_btn)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.force_check)
        self.toolbar_status = QLabel("")
        self.toolbar_status.setObjectName("Subtle")
        bar.addWidget(self.toolbar_status)
        bar.addStretch(1)
        root.addLayout(bar)

        # overall progress for produce / render-all (hidden until running)
        self.overall_bar = QProgressBar()
        self.overall_bar.setObjectName("OverallBar")
        self.overall_bar.setVisible(False)
        self.overall_bar.setFormat("%v / %m chapters")
        root.addWidget(self.overall_bar)

        self._rows: dict = {}
        self._active_row = None

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.vbox = QVBoxLayout(self.host)
        self.vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, stretch=1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        while self.vbox.count():
            w = self.vbox.takeAt(0).widget()
            if w:
                w.deleteLater()
        proj = project_service.active()
        if proj is None:
            self.vbox.addWidget(self._hint("Open a project from the Dashboard first."))
            return
        self.characters = project_service.load_characters(proj)
        index = chapter_service.load_index(proj)
        if not index:
            self.vbox.addWidget(self._hint("No chapters yet — click 'Detect chapters'."))
            return
        self._rows = {}
        for info in index:
            row = ChapterRow(info, self)
            self._rows[info["chapter_id"]] = row
            self.vbox.addWidget(row)

    # --- audiobook pipeline: scene audio -> render all -----------------------
    # Voices are a prerequisite done on the Characters tab. Chapters only
    # produces audiobook audio (scene audio + chapter renders).

    def _produce_all(self) -> None:
        proj = project_service.active()
        if proj is None:
            return
        index = chapter_service.load_index(proj)
        if not index:
            self.toolbar_status.setText("Detect chapters first.")
            return
        self.characters = project_service.load_characters(proj)
        if not any(c.voice_sample for c in self.characters):
            self.toolbar_status.setText(
                "No voices yet — run 'Generate all voices' on the Characters tab first.")
            return
        self._produce_index = index
        self._producing = True
        self._produce_cancelled = False
        self._force_run = self.force_check.isChecked()
        self._qc = (0, 0)
        self.produce_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self._produce_scene()

    def _produce_scene(self) -> None:
        if self._produce_cancelled:
            return self._on_produce_done()
        proj = project_service.active()
        need = self._force_run or any(
            not proj.ambience_path(i["chapter_id"]).exists()
            or not proj.music_path(i["chapter_id"]).exists()
            for i in self._produce_index)
        if not need:
            return self._produce_render()
        self.toolbar_status.setText("Producing — ambience + SFX + music…")
        w = AmbienceWorker(self._produce_index, self.characters, self._force_run, self)
        self._active_batch = w
        w.progress.connect(lambda d, t, _l: self.toolbar_status.setText(f"Producing — scene audio {d}/{t}"))
        w.finished_all.connect(self._produce_render)
        w.start()

    def _produce_render(self) -> None:
        if self._produce_cancelled:
            return self._on_produce_done()
        self.toolbar_status.setText("Producing — rendering chapters…")
        self.overall_bar.setVisible(True)
        self.overall_bar.setRange(0, len(self._produce_index))
        self.overall_bar.setValue(0)
        w = RenderAllWorker(self._produce_index, self.characters,
                            force=self._force_run, parent=self)
        self._active_batch = w
        w.chapter_progress.connect(self._on_overall_progress)
        w.chapter_started.connect(self._on_chapter_started)
        w.line_progress.connect(self._on_line_progress)
        w.chapter_done.connect(self._on_chapter_done)
        w.qc.connect(lambda ch, ln: setattr(self, "_qc", (ch, ln)))
        w.finished_all.connect(self._on_produce_done)
        w.start()

    def _on_overall_progress(self, done: int, total: int, label: str) -> None:
        self.overall_bar.setRange(0, total)
        self.overall_bar.setValue(done)
        self.toolbar_status.setText(f"Rendering {done}/{total} — {label}")

    def _on_chapter_started(self, chapter_id: str) -> None:
        row = self._rows.get(chapter_id)
        self._active_row = row
        if row is not None:
            row.batch_active()

    def _on_line_progress(self, done: int, total: int) -> None:
        if self._active_row is not None:
            self._active_row.batch_line(done, total)

    def _on_chapter_done(self, chapter_id: str, _path: str) -> None:
        row = self._rows.get(chapter_id)
        if row is not None:
            row.batch_done()

    def _on_produce_done(self) -> None:
        self._producing = False
        self._active_batch = None
        self._active_row = None
        self.cancel_btn.setVisible(False)
        self.overall_bar.setVisible(False)
        self.produce_btn.setEnabled(True)
        if getattr(self, "_produce_cancelled", False):
            self.toolbar_status.setText("Production cancelled.")
        else:
            ch, ln = getattr(self, "_qc", (0, 0))
            qc = f" — {ln} lines failed in {ch} chapters" if ln else " — no failures"
            self.toolbar_status.setText(f"Done{qc}. Each chapter is a tagged MP3 in mixes/chapters.")
        self.refresh()

    def _cancel_batch(self) -> None:
        if getattr(self, "_producing", False):
            self._produce_cancelled = True   # stop the pipeline chain too
        w = getattr(self, "_active_batch", None)
        if w is not None:
            w.cancel()
            self.toolbar_status.setText("Cancelling…")

    def _detect(self) -> None:
        proj = project_service.active()
        if proj is None:
            return
        text = pdf_service.extract_text(proj.source_pdf)
        import app.services.pdf_service as p
        from app.services import afterword, front_matter
        from app.core.config import CONFIG
        chapters = chapter_service.detect_chapters(p._normalize(text))
        for c in chapters:
            chapter_service.save_chapter(proj, c)
        ordered = list(chapters)
        # front matter (title/author/short bio), read by the narrator
        if CONFIG.extraction.front_matter:
            fm = front_matter.build(
                proj, [{"number": c.number, "title": c.title, "chapter_id": c.chapter_id}
                       for c in chapters])
            chapter_service.save_chapter(proj, fm)
            ordered = [fm, *ordered]
        # afterword with similar-book recommendations (web), if available
        if CONFIG.extraction.afterword:
            aw = afterword.build(proj, number=(chapters[-1].number + 1) if chapters else 1)
            if aw is not None:
                chapter_service.save_chapter(proj, aw)
                ordered.append(aw)
        chapter_service.save_index(proj, ordered)
        self.refresh()

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Subtle")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl
