"""Settings screen: edit LLM / ComfyUI / workflow / audio settings, plus a demo
mode that renders a ~1-minute Hörspiel and shows it as a scrubbable waveform
which updates live as you tweak the mix settings.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.services import demo_service, settings_service, voice_optimize
from app.ui.waveform_widget import WaveformWidget
from app.workers.demo_worker import DemoGenerateWorker, DemoRemixWorker
from app.workers.install_worker import InstallWorker
from app.workers.models_worker import ModelsWorker
from app.workers.voice_optimize_worker import VoiceOptimizeWorker


class _DropLineEdit(QLineEdit):
    """A line edit that accepts a dropped audio file path."""

    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            self.setText(urls[0].toLocalFile())

logger = logging.getLogger(__name__)

_MIX_SECTION = "Audio / Mix"


class SettingsScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widgets: dict[str, tuple] = {}     # path -> (widget, kind)
        self._voice_edits: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Settings")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(host)
        root.addWidget(scroll, stretch=1)

        by_section: dict[str, list] = defaultdict(list)
        for f in settings_service.FIELDS:
            by_section[f[0]].append(f)

        def _section_box(section, fields):
            box = QGroupBox(section)
            form = QFormLayout(box)
            for _sec, label, path, kind, choices in fields:
                w = self._make_widget(kind, settings_service._get(path), choices)
                self._widgets[path] = (w, kind)
                if section == _MIX_SECTION:
                    self._connect_live(w, kind, path)
                form.addRow(label, w)
            return box

        # --- top block: Audio/Mix controls beside the live demo waveform -----
        mix_box = _section_box(_MIX_SECTION, by_section.pop(_MIX_SECTION, []))
        demo_box = self._demo_box()
        top = QHBoxLayout()
        top.addWidget(mix_box, 4)
        top.addWidget(demo_box, 6)
        col.addLayout(top)

        save = QPushButton("Save settings")
        save.clicked.connect(self._save)
        col.addWidget(save)

        # --- LLM (custom: backend-conditional + model dropdowns) -------------
        by_section.pop("LLM", None)
        col.addWidget(self._llm_box())

        # --- voice optimize debug panel --------------------------------------
        col.addWidget(self._optimize_box())

        # --- the remaining config sections below -----------------------------
        for section, fields in by_section.items():
            col.addWidget(_section_box(section, fields))

        # media player for the demo
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self._on_pos)
        self._player.playbackStateChanged.connect(self._on_state)
        self.wave.seek_requested.connect(self._seek)

        # second player for the optimize debug panel (original vs optimized)
        self._opt_player = QMediaPlayer(self)
        self._opt_aout = QAudioOutput(self)
        self._opt_player.setAudioOutput(self._opt_aout)
        self._opt_player.positionChanged.connect(self._on_opt_pos)
        self._opt_player.durationChanged.connect(self._on_opt_duration)
        self._opt_player.playbackStateChanged.connect(self._opt_update_buttons)
        self._opt_out_path = ""
        self._opt_cur = None             # 'in' | 'out' currently loaded
        self._opt_pending_frac = None
        self._opt_worker = None

        # debounce for live remix
        self._remix_timer = QTimer(self)
        self._remix_timer.setSingleShot(True)
        self._remix_timer.setInterval(180)     # fast: live in-memory remix
        self._remix_timer.timeout.connect(self._start_remix)
        self._remix_worker = None
        self._gen_worker = None

        self._load_default_voices()
        self._refresh_demo_audio()
        # Demo clips persist on disk — if the preview WAV is missing but the
        # clips are there (e.g. after a restart), rebuild it cheaply.
        if not demo_service.demo_audio_path().exists() and demo_service.has_clips():
            self.demo_status.setText("Restoring demo from saved clips…")
            self._start_remix()

    # --- demo panel ---------------------------------------------------------
    def _demo_box(self) -> QGroupBox:
        box = QGroupBox("Demo — 1-minute Hörspiel (tune pauses, levels, ambience live)")
        lay = QVBoxLayout(box)

        # voice pickers
        for sid, label in (("erzaehler", "Erzähler"), ("char1", "Charakter 1"),
                           ("char2", "Charakter 2")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label + ":"))
            edit = QLineEdit()
            edit.setPlaceholderText("voice reference (.wav/.mp3) — drop a sample or browse")
            self._voice_edits[sid] = edit
            row.addWidget(edit, stretch=1)
            browse = QPushButton("…")
            browse.setFixedWidth(34)
            browse.clicked.connect(lambda _=False, e=edit: self._pick_voice(e))
            row.addWidget(browse)
            lay.addLayout(row)

        # example text (read-only preview)
        sample = "  ·  ".join(f"[{sp}] {txt[:24]}…" for _t, sp, txt, *_ in demo_service.DEMO_SCRIPT[:4])
        hint = QLabel("Beispielszene (Hafen): Erzähler + Charakter 1 + Charakter 2, "
                      "mit Ambience und SFX.\n" + sample)
        hint.setObjectName("Subtle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        ctl = QHBoxLayout()
        self.gen_btn = QPushButton("Generate demo")
        self.gen_btn.clicked.connect(self._generate)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)
        self.demo_status = QLabel("")
        self.demo_status.setObjectName("Subtle")
        ctl.addWidget(self.gen_btn)
        ctl.addWidget(self.play_btn)
        ctl.addWidget(self.demo_status, stretch=1)
        lay.addLayout(ctl)

        self.wave = WaveformWidget()
        lay.addWidget(self.wave)
        return box

    # --- LLM section (backend-conditional + model dropdowns) ----------------
    def _llm_box(self):
        from PySide6.QtWidgets import QGroupBox
        g = settings_service._get
        box = QGroupBox("LLM")
        form = QFormLayout(box)
        self._llm_form = form

        backend = QComboBox()
        backend.addItems(["ollama", "openai"])
        backend.setCurrentText(str(g("ollama.backend")))
        self._widgets["ollama.backend"] = (backend, "choice")
        form.addRow("Backend", backend)

        o_url = QLineEdit(str(g("ollama.base_url")))
        self._widgets["ollama.base_url"] = (o_url, "str")
        form.addRow("Ollama URL", o_url)
        o_row, _ = self._model_row("ollama.model", "ollama", lambda: o_url.text(), lambda: "")
        form.addRow("Ollama model", o_row)

        a_url = QLineEdit(str(g("ollama.api_base_url")))
        self._widgets["ollama.api_base_url"] = (a_url, "str")
        form.addRow("API base URL", a_url)
        a_key = QLineEdit(str(g("ollama.api_key")))
        a_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._widgets["ollama.api_key"] = (a_key, "password")
        form.addRow("API key", a_key)
        a_row, _ = self._model_row("ollama.api_model", "openai",
                                   lambda: a_url.text(), lambda: a_key.text())
        form.addRow("API model", a_row)

        temp = QDoubleSpinBox()
        temp.setRange(0.0, 2.0)
        temp.setSingleStep(0.05)
        temp.setDecimals(2)
        temp.setValue(float(g("ollama.temperature")))
        self._widgets["ollama.temperature"] = (temp, "float")
        form.addRow("Temperature", temp)

        self._llm_ollama = [o_url, o_row]
        self._llm_openai = [a_url, a_key, a_row]
        backend.currentTextChanged.connect(self._update_llm_visibility)
        self._update_llm_visibility(backend.currentText())
        return box

    def _model_row(self, path, backend, get_url, get_key):
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox()
        combo.setEditable(True)
        combo.setCurrentText(str(settings_service._get(path)))
        self._widgets[path] = (combo, "choice")
        btn = QPushButton("↻")
        btn.setFixedWidth(34)
        btn.setToolTip("Load available models")
        btn.clicked.connect(lambda: self._fetch_models(combo, backend, get_url(), get_key()))
        h.addWidget(combo, 1)
        h.addWidget(btn)
        return container, combo

    def _fetch_models(self, combo, backend, url, key) -> None:
        self._models_worker = ModelsWorker(backend, url, key, self)
        self._models_worker.loaded.connect(lambda models: self._populate_combo(combo, models))
        self._models_worker.start()

    @staticmethod
    def _populate_combo(combo, models) -> None:
        cur = combo.currentText()
        combo.clear()
        combo.addItems(models)
        if cur and cur not in models:
            combo.insertItem(0, cur)
        combo.setCurrentText(cur)

    def _update_llm_visibility(self, backend: str) -> None:
        for w in self._llm_ollama:
            self._llm_form.setRowVisible(w, backend == "ollama")
        for w in self._llm_openai:
            self._llm_form.setRowVisible(w, backend == "openai")

    # --- voice optimize debug panel -----------------------------------------
    def _optimize_box(self):
        avail = voice_optimize.available()
        box = QGroupBox("Optimize voice sample (debug)")
        lay = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Input:"))
        self._opt_in = _DropLineEdit()
        self._opt_in.setPlaceholderText("drop an audio file here, or browse…")
        self._opt_in.textChanged.connect(self._opt_input_changed)
        row.addWidget(self._opt_in, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(34)
        browse.clicked.connect(self._opt_pick)
        row.addWidget(browse)
        lay.addLayout(row)

        opts = QHBoxLayout()
        self._opt_sep = QCheckBox("Separate (Demucs)")
        self._opt_den = QCheckBox("Denoise (DeepFilterNet)")
        self._opt_enh = QCheckBox("Enhance (VoiceFixer)")
        # checkbox -> (availability key, pip package, base label)
        self._opt_libs = {
            self._opt_sep: ("separate (demucs)", "demucs", "Separate (Demucs)"),
            self._opt_den: ("denoise (deepfilternet)", "deepfilternet", "Denoise (DeepFilterNet)"),
            self._opt_enh: ("enhance (voicefixer)", "voicefixer", "Enhance (VoiceFixer)"),
        }
        self._install_worker = None
        for cb, (key, pkg, base) in self._opt_libs.items():
            if avail[key]:
                cb.setChecked(cb is self._opt_den)   # denoise on by default
                cb.setToolTip("installed")
            else:                                    # checking it auto-installs
                cb.setText(base + "  ·  click to install")
                cb.setToolTip(f"Not installed — check to auto-install (pip install {pkg})")
            cb.toggled.connect(lambda checked, c=cb: self._opt_lib_toggled(c, checked))
            opts.addWidget(cb)
        opts.addStretch(1)
        lay.addLayout(opts)

        note = QLabel("Always: trim silence + loudness-normalize (LUFS) so every "
                      "voice ends up equally loud and clear.")
        note.setObjectName("Subtle")
        note.setWordWrap(True)
        lay.addWidget(note)

        act = QHBoxLayout()
        self._opt_btn = QPushButton("Optimize + export")
        self._opt_btn.clicked.connect(self._run_optimize)
        self._opt_status = QLabel("")
        self._opt_status.setObjectName("Subtle")
        act.addWidget(self._opt_btn)
        act.addWidget(self._opt_status, 1)
        lay.addLayout(act)

        grid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Original"))
        self._opt_wave_in = WaveformWidget()
        self._opt_wave_in.seek_requested.connect(self._opt_seek)
        left.addWidget(self._opt_wave_in)
        self._opt_play_in = QPushButton("▶ original")
        self._opt_play_in.clicked.connect(lambda: self._opt_toggle("in"))
        left.addWidget(self._opt_play_in)
        right = QVBoxLayout()
        right.addWidget(QLabel("Optimized"))
        self._opt_wave_out = WaveformWidget()
        self._opt_wave_out.seek_requested.connect(self._opt_seek)
        right.addWidget(self._opt_wave_out)
        self._opt_play_out = QPushButton("▶ optimized")
        self._opt_play_out.setEnabled(False)
        self._opt_play_out.clicked.connect(lambda: self._opt_toggle("out"))
        right.addWidget(self._opt_play_out)
        grid.addLayout(left)
        grid.addLayout(right)
        lay.addLayout(grid)
        return box

    def _opt_lib_toggled(self, cb, checked: bool) -> None:
        """Checking a not-installed optimizer auto-installs it via pip."""
        if not checked:
            return
        key, pkg, base = self._opt_libs[cb]
        if voice_optimize.available()[key]:
            return                                    # already installed
        if self._install_worker is not None and self._install_worker.isRunning():
            self._opt_status.setText("An install is already running…")
            cb.setChecked(False)
            return
        cb.setEnabled(False)
        cb.setText(base + f"  ·  installing {pkg}…")
        self._opt_status.setText(f"Installing {pkg} … (may take a few minutes)")
        self._install_worker = InstallWorker(pkg, self)
        self._install_worker.done.connect(
            lambda ok, msg, c=cb: self._on_install_done(c, ok, msg))
        self._install_worker.start()

    def _on_install_done(self, cb, ok: bool, msg: str) -> None:
        import importlib
        importlib.invalidate_caches()
        key, pkg, base = self._opt_libs[cb]
        cb.setEnabled(True)
        if ok and voice_optimize.available()[key]:
            cb.setText(base)
            cb.setToolTip("installed")
            cb.setChecked(True)
            self._opt_status.setText(f"Installed {pkg} ✓ — ready to use.")
        else:
            cb.setChecked(False)
            cb.setText(base + "  ·  install failed")
            self._opt_status.setText(f"Install failed for {pkg}: {msg[:200]}")

    def _opt_pick(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Audio", "",
                                           "Audio (*.wav *.mp3 *.ogg *.flac)")
        if f:
            self._opt_in.setText(f)

    def _opt_input_changed(self, path: str) -> None:
        self._opt_wave_in.set_audio(path if path and Path(path).exists() else None)

    def _run_optimize(self) -> None:
        path = self._opt_in.text().strip()
        if not path or not Path(path).exists():
            self._opt_status.setText("pick an input file first")
            return
        self._save()                          # persist LUFS target etc.
        self._opt_btn.setEnabled(False)
        self._opt_status.setText("Optimizing…")
        self._opt_worker = VoiceOptimizeWorker(
            path, self._opt_sep.isChecked(), self._opt_den.isChecked(),
            self._opt_enh.isChecked(), parent=self)
        self._opt_worker.finished_ok.connect(self._on_optimized)
        self._opt_worker.failed.connect(self._on_opt_failed)
        self._opt_worker.start()

    def _on_optimized(self, res: dict) -> None:
        self._opt_btn.setEnabled(True)
        self._opt_out_path = res.get("out", "")
        done = ", ".join(res.get("done", []))
        skip = ", ".join(res.get("skipped", []))
        msg = f"Done: {done}." + (f"  Skipped: {skip}." if skip else "")
        self._opt_status.setText(msg + f"  →  {self._opt_out_path}")
        if self._opt_out_path and Path(self._opt_out_path).exists():
            self._opt_wave_out.set_audio(self._opt_out_path)
            self._opt_play_out.setEnabled(True)

    def _on_opt_failed(self, msg: str) -> None:
        self._opt_btn.setEnabled(True)
        self._opt_status.setText(f"Failed: {msg}")

    def _opt_toggle(self, which: str) -> None:
        path = self._opt_in.text().strip() if which == "in" else self._opt_out_path
        if not path or not Path(path).exists():
            return
        playing = self._opt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self._opt_cur == which:               # same source: pause/resume
            self._opt_player.pause() if playing else self._opt_player.play()
            return
        # switch to the other source, keep the same position (synced timelines)
        self._opt_pending_frac = self._opt_fraction()
        self._opt_cur = which
        self._opt_player.setSource(QUrl.fromLocalFile(path))
        self._opt_player.play()

    def _opt_fraction(self) -> float:
        dur = self._opt_player.duration()
        return (self._opt_player.position() / dur) if dur else 0.0

    def _on_opt_duration(self, dur: int) -> None:
        if self._opt_pending_frac is not None and dur:
            self._opt_player.setPosition(int(self._opt_pending_frac * dur))
            self._opt_pending_frac = None

    def _on_opt_pos(self, ms: int) -> None:
        dur = self._opt_player.duration() or 1
        frac = ms / dur
        self._opt_wave_in.set_progress(frac)     # both timelines stay synced
        self._opt_wave_out.set_progress(frac)

    def _opt_update_buttons(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._opt_play_in.setText(
            ("⏸ " if playing and self._opt_cur == "in" else "▶ ") + "original")
        self._opt_play_out.setText(
            ("⏸ " if playing and self._opt_cur == "out" else "▶ ") + "optimized")

    def _opt_seek(self, frac: float) -> None:
        dur = self._opt_player.duration()
        if dur:
            self._opt_player.setPosition(int(frac * dur))

    # --- widget helpers -----------------------------------------------------
    @staticmethod
    def _make_widget(kind: str, value, choices):
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
        elif kind == "int":
            w = QSpinBox()
            w.setRange(-100000, 1000000)
            w.setValue(int(value))
        elif kind == "float":
            w = QDoubleSpinBox()
            w.setRange(-1000.0, 1000000.0)
            w.setDecimals(2)
            w.setValue(float(value))
        elif kind == "choice":
            w = QComboBox()
            w.addItems(choices or [])
            w.setCurrentText(str(value))
        elif kind == "path":
            w = QLineEdit(str(value))
        else:  # str, password
            w = QLineEdit(str(value))
            if kind == "password":
                w.setEchoMode(QLineEdit.EchoMode.Password)
        return w

    @staticmethod
    def _value(w, kind):
        if kind == "bool":
            return w.isChecked()
        if kind == "int":
            return w.value()
        if kind == "float":
            return w.value()
        if kind == "choice":
            return w.currentText()
        return w.text()

    def _connect_live(self, w, kind, path) -> None:
        if kind in ("int", "float"):
            w.valueChanged.connect(lambda *_: self._mix_changed(path, kind, w))
        elif kind == "bool":
            w.toggled.connect(lambda *_: self._mix_changed(path, kind, w))
        else:
            w.editingFinished.connect(lambda: self._mix_changed(path, kind, w))

    def _mix_changed(self, path, kind, w) -> None:
        # apply immediately so a remix reflects it, then debounce the remix
        try:
            settings_service._set(path, self._value(w, kind))
        except Exception:  # noqa: BLE001
            return
        if demo_service.demo_audio_path().exists():
            self._remix_timer.start()

    # --- actions ------------------------------------------------------------
    def _save(self) -> None:
        values = {p: self._value(w, k) for p, (w, k) in self._widgets.items()}
        settings_service.save(values)
        self.demo_status.setText("Settings saved.")

    def _pick_voice(self, edit: QLineEdit) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Voice sample", "",
                                           "Audio (*.wav *.mp3 *.ogg *.flac)")
        if f:
            edit.setText(f)

    def _load_default_voices(self) -> None:
        for sid, path in demo_service.default_voices().items():
            if sid in self._voice_edits and not self._voice_edits[sid].text():
                self._voice_edits[sid].setText(path)

    def _voices(self) -> dict:
        return {sid: e.text().strip() for sid, e in self._voice_edits.items() if e.text().strip()}

    def _generate(self) -> None:
        # persist current settings first so the demo uses them
        self._save()
        self.gen_btn.setEnabled(False)
        self.demo_status.setText("Generating demo (voices + ambience + SFX)…")
        self._gen_worker = DemoGenerateWorker(self._voices(), self)
        self._gen_worker.finished_ok.connect(self._on_generated)
        self._gen_worker.failed.connect(lambda m: self._fail(m))
        self._gen_worker.start()

    def _on_generated(self, path: str) -> None:
        self.gen_btn.setEnabled(True)
        self.demo_status.setText("Demo ready — tweak Audio/Mix to hear changes live.")
        self._refresh_demo_audio()

    def _fail(self, msg: str) -> None:
        self.gen_btn.setEnabled(True)
        self.demo_status.setText(f"Failed: {msg}")

    def _start_remix(self) -> None:
        if self._remix_worker is not None and self._remix_worker.isRunning():
            self._remix_timer.start()   # try again shortly
            return
        self.demo_status.setText("Re-mixing…")
        self._remix_worker = DemoRemixWorker(self)
        self._remix_worker.finished_ok.connect(self._on_remixed)
        self._remix_worker.failed.connect(lambda m: self._fail(m))
        self._remix_worker.start()

    def _on_remixed(self, path: str) -> None:
        self.demo_status.setText("Updated.")
        self._refresh_demo_audio(keep_pos=True)

    def _refresh_demo_audio(self, keep_pos: bool = False) -> None:
        path = demo_service.demo_audio_path()
        if not path.exists():
            self.wave.clear()
            self.play_btn.setEnabled(False)
            return
        pos = self._player.position()
        self.wave.set_audio(str(path))
        self.play_btn.setEnabled(True)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        if keep_pos:
            self._player.setPosition(pos)

    # --- playback -----------------------------------------------------------
    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸ Pause" if playing else "▶ Play")

    def _on_pos(self, ms: int) -> None:
        dur = self._player.duration() or 1
        self.wave.set_progress(ms / dur)

    def _seek(self, frac: float) -> None:
        dur = self._player.duration()
        if dur:
            self._player.setPosition(int(frac * dur))
