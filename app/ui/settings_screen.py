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

from app.services import demo_service, settings_service
from app.ui.waveform_widget import WaveformWidget
from app.workers.demo_worker import DemoGenerateWorker, DemoRemixWorker
from app.workers.models_worker import ModelsWorker

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

        # --- the remaining config sections below -----------------------------
        for section, fields in by_section.items():
            col.addWidget(_section_box(section, fields))

        # Demo player.
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self._on_pos)
        self._player.playbackStateChanged.connect(self._on_state)
        self.wave.seek_requested.connect(self._seek)
        self._cur_src = ""

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
        self._cur_src = str(path)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        if keep_pos:
            self._player.setPosition(pos)

    # --- demo playback ------------------------------------------------------
    def _set_src(self, path: str) -> None:
        if self._cur_src != path:
            self._cur_src = path
            self._player.setSource(QUrl.fromLocalFile(path))

    def _toggle_play(self) -> None:
        path = str(demo_service.demo_audio_path())
        if not Path(path).exists():
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            return
        self._player.setLoops(QMediaPlayer.Loops.Once)
        self._set_src(path)
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
