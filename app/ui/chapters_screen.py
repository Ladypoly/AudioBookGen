"""Chapters screen: list chapters, render each to audio, play the result."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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

_NARRATOR_ID = "erzaehler"
_SPK_PALETTE = ["#3aa0ff", "#f783ac", "#63e6be", "#ffa94d", "#b794f6",
                "#74c0fc", "#ffd43b", "#ff8787", "#69db7c", "#e599f7"]


def _speaker_color(sid: str) -> str:
    if sid == _NARRATOR_ID:
        return "#9aa3b2"                       # narrator = neutral grey
    import hashlib
    h = int(hashlib.md5(sid.encode()).hexdigest(), 16)
    return _SPK_PALETTE[h % len(_SPK_PALETTE)]


def _delivery_html(delivery) -> str:
    """Colour-coded emotion / style / prosody / nonverbal chips for one line."""
    import html as _html
    if delivery is None:
        return ""
    chips: list[tuple[str, str]] = []
    if getattr(delivery, "emotion", None):
        chips.append((delivery.emotion.value, "#ffa94d"))      # emotion = amber
    if getattr(delivery, "style", None):
        chips.append((delivery.style.value, "#b794f6"))        # style = purple
    for p in getattr(delivery, "prosody", None) or []:
        chips.append((p.value, "#63e6be"))                     # prosody = teal
    for nv in getattr(delivery, "nonverbal", None) or []:
        chips.append((nv.value, "#f783ac"))                    # nonverbal = pink
    return "".join(f"<span style='color:{c};font-size:11px'> ·{_html.escape(t)}</span>"
                   for t, c in chips)


# Re-render modes -> ChapterRenderWorker flags (shared by a chapter card and the
# 'Produce chapters' bulk dialog).
_REDO_MODES = {
    "full": dict(redo_voices=True, redo_ambience=True, redo_sfx=True),
    "continue": dict(),                      # generate only what's missing
    "voices": dict(redo_voices=True),
    "voices_chars": dict(redo_voices_no_narrator=True),
    "ambience": dict(redo_ambience=True),
    "sfx": dict(redo_sfx=True),
    "mix": dict(mix_only=True),              # just re-assemble, no generation
}
_MODE_ORDER = [("full", "Full — regenerate everything (overwrite)"),
               ("continue", "Continue — generate only what's missing"),
               ("voices", "Voices only (regenerate all)"),
               ("voices_chars", "Character voices only (no narrator)"),
               ("ambience", "Ambience only"),
               ("sfx", "SFX only"),
               ("mix", "Mix only (just re-assemble)")]


def _ask_render_mode(parent, title: str, text: str):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    btns = {key: box.addButton(label, QMessageBox.ButtonRole.AcceptRole)
            for key, label in _MODE_ORDER}
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    return next((k for k, b in btns.items() if b is clicked), None)


class ChapterRow(QFrame):
    render_finished = Signal()   # this row's queued render completed (ok or fail)

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
        self.expand_btn = QPushButton("▸")
        self.expand_btn.setObjectName("Ghost")
        self.expand_btn.setFixedWidth(28)
        self.expand_btn.setToolTip("Show the chapter script")
        self.expand_btn.clicked.connect(self._toggle_script)
        top.addWidget(self.expand_btn)
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

        # collapsible script view (built lazily on first expand)
        self.script = QLabel()
        self.script.setObjectName("Subtle")
        self.script.setWordWrap(True)
        self.script.setTextFormat(Qt.TextFormat.RichText)
        self.script.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.script.setVisible(False)
        lay.addWidget(self.script)
        self._script_built = False

        self._refresh_state()

    # --- collapsible script ---------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._toggle_script()
        super().mousePressEvent(event)

    def _toggle_script(self) -> None:
        if not self._script_built:
            self._build_script()
            self._script_built = True
        show = not self.script.isVisible()
        self.script.setVisible(show)
        self.expand_btn.setText("▾" if show else "▸")

    def _build_script(self) -> None:
        proj = project_service.active()
        chapter = (chapter_service.load_chapter(proj, self._info["chapter_id"])
                   if proj is not None else None)
        if chapter is None or not chapter.lines:
            self.script.setText("<i>No script yet — produce chapters first.</i>")
            return
        self.script.setText(self._script_html(chapter))

    def _script_html(self, chapter) -> str:
        import html as _html

        from app.core.config import CONFIG
        from app.services import ambience, music_planner
        names = {c.character_id: c.display_name for c in self._screen.characters}
        rows = ["<div style='line-height:148%'>"]
        amb = ambience.ambience_for_chapter(chapter)[0]
        rows.append(f"<div style='color:#27c498'><b>AMBIENCE</b> · {_html.escape(amb)}</div>")
        if CONFIG.tts.music_enabled:
            mus = music_planner.music_for_chapter(chapter)[0]
            rows.append(f"<div style='color:#9DAAF2'><b>MUSIC</b> · {_html.escape(mus)}</div>")
        # colour legend
        rows.append(
            "<div style='font-size:11px;margin-top:3px'>"
            "<span style='color:#ffa94d'>emotion</span> &nbsp;"
            "<span style='color:#b794f6'>style</span> &nbsp;"
            "<span style='color:#63e6be'>prosody</span> &nbsp;"
            "<span style='color:#f783ac'>nonverbal</span> &nbsp;"
            "<span style='color:#f4db7d'>SFX</span></div>")
        rows.append("<div style='color:#2e3650'>──────────</div>")
        for line in chapter.lines:
            sid = line.speaker_id
            col = _speaker_color(sid)
            who = _html.escape(names.get(sid, sid))
            tag = "" if line.type.value == "dialogue" else \
                f" <span style='color:#5b6376'>({line.type.value})</span>"
            rows.append(
                f"<div style='margin:4px 0'>"
                f"<span style='color:{col};font-weight:700'>{who}</span>{tag} "
                f"<span style='color:#c9d2e3'>{_html.escape(line.text)}</span>"
                f"{_delivery_html(line.delivery)}</div>")
            for cue in line.sfx:
                rows.append(
                    f"<div style='color:#f4db7d;margin:0 0 4px 1.6em'>"
                    f"SFX <i>{cue.placement}</i> · {_html.escape(cue.prompt)}</div>")
        rows.append("</div>")
        return "".join(rows)

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
        """Button click: pick a mode if already rendered, then queue the job so
        clicking Render on several chapters runs them one at a time."""
        if project_service.active() is None:
            return
        flags: dict = {}
        if self._rendered_file() is not None:
            mode = _ask_render_mode(
                self, "Re-render chapter",
                f"'{self._info['number']}. {self._info['title']}' is already "
                "rendered.\nWhat do you want to redo?")
            if mode is None:                 # cancel
                return
            flags = _REDO_MODES[mode]
        self.render_btn.setEnabled(False)
        self.status.setText("queued…")
        self.status.setStyleSheet("color: #f4db7d;")
        self._screen.enqueue_render(self, flags)

    def start_render(self, flags: dict) -> None:
        """Actually run the render (called by the screen's queue when it's our
        turn). Emits render_finished when done so the queue advances."""
        proj = project_service.active()
        chapter = chapter_service.load_chapter(proj, self._info["chapter_id"]) \
            if proj is not None else None
        if chapter is None:
            self.status.setText("chapter data missing")
            self.render_btn.setEnabled(True)
            self.render_finished.emit()
            return
        self.play_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self._worker = ChapterRenderWorker(
            chapter, self._screen.characters, parent=self, **flags)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_progress(self, done: int, total: int, speaker: str) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"Rendering line {done}/{total} — {speaker}")
        self.status.setStyleSheet("color: #3a6df0;")

    def _on_done(self, chapter_id: str, path: str) -> None:
        self.render_btn.setEnabled(True)
        self.bar.setVisible(False)
        if path:
            self._info["audio_path"] = path
        self._refresh_state()
        self.render_finished.emit()

    def _on_fail(self, msg: str) -> None:
        self.render_btn.setEnabled(True)
        self.bar.setVisible(False)
        self.status.setText(f"Failed: {msg}")
        self.status.setStyleSheet("color: #f87171;")
        self.render_finished.emit()

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
        bar.addWidget(self.detect_btn)
        bar.addWidget(self.produce_btn)
        bar.addWidget(self.cancel_btn)
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
        self._render_queue: list = []      # (row, flags) pending manual renders
        self._render_active = None         # the row currently rendering

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

    # --- manual per-chapter render queue -------------------------------------
    def enqueue_render(self, row: "ChapterRow", flags: dict) -> None:
        """Queue a single-chapter render so several Render clicks (each with its
        own mode) run one after another instead of all at once. Queued by
        chapter_id so a refresh() that rebuilds rows can't leave stale refs."""
        self._render_queue.append((row._info["chapter_id"], flags))
        self._pump_render_queue()

    def _pump_render_queue(self) -> None:
        if self._render_active is not None or getattr(self, "_producing", False):
            return
        while self._render_queue:
            cid, flags = self._render_queue.pop(0)
            row = self._rows.get(cid)
            if row is None:
                continue
            self._render_active = cid
            row.render_finished.connect(self._on_queued_render_done)
            row.start_render(flags)
            return

    def _on_queued_render_done(self) -> None:
        row = self._rows.get(self._render_active) if self._render_active else None
        if row is not None:
            try:
                row.render_finished.disconnect(self._on_queued_render_done)
            except (RuntimeError, TypeError):
                pass
        self._render_active = None
        self._pump_render_queue()

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
        mode = _ask_render_mode(
            self, "Produce chapters",
            "(Re)produce ALL chapters — what to do?\n(e.g. 'Character voices only' "
            "if you just changed a speaker, 'Mix only' to re-mix.)")
        if mode is None:
            return
        self._produce_index = index
        self._producing = True
        self._produce_cancelled = False
        # mode -> phase flags
        self._scene_force = mode in ("full", "ambience", "sfx")
        self._render_force = mode in ("full", "voices")
        self._render_no_narr = mode == "voices_chars"
        self._mix_only = mode == "mix"
        self._qc = (0, 0)
        self.produce_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self._produce_scene()

    def _produce_scene(self) -> None:
        if self._produce_cancelled:
            return self._on_produce_done()
        if self._mix_only:                  # no generation — straight to re-mix
            return self._produce_render()
        proj = project_service.active()
        need = self._scene_force or any(
            not proj.ambience_path(i["chapter_id"]).exists()
            or not proj.music_path(i["chapter_id"]).exists()
            for i in self._produce_index)
        if not need:
            return self._produce_render()
        self.toolbar_status.setText("Producing — ambience + SFX + music…")
        w = AmbienceWorker(self._produce_index, self.characters, self._scene_force, self)
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
                            force=self._render_force,
                            redo_voices_no_narrator=self._render_no_narr,
                            mix_only=self._mix_only, parent=self)
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
        self._pump_render_queue()   # run any manual renders queued during produce

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
