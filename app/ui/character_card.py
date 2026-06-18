"""Character card widget.

Spoiler-safe by default: shows only name, role, gender, age, voice hint and
vocal-trait chips. Any text flagged hidden sits behind a Reveal button.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.schemas.characters import Character
from app.schemas.voice import Voice
from app.services import portrait_service
from app.ui.audio_util import play_audio
from app.ui.theme import ROLE_COLORS
from app.workers.portrait_worker import PortraitWorker
from app.workers.tts_preview_worker import TTSPreviewWorker
from app.workers.voice_design_worker import VoiceDesignWorker

_AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}

_PORTRAIT_W = 252
_PORTRAIT_H = 336  # 3:4, matches the generated portrait aspect ratio


def _chip(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Chip")
    return lbl


def _flow(chips: list[QLabel]) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for c in chips:
        lay.addWidget(c)
    lay.addStretch(1)
    return box


class CharacterCard(QFrame):
    voice_assigned = Signal(str, str)  # character_id, voice_id

    def __init__(self, character: Character, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._char = character
        self.setFixedWidth(284)
        self.setAcceptDrops(True)  # drop an audio file to assign a voice

        self._portrait_worker: PortraitWorker | None = None
        self._tts_worker: TTSPreviewWorker | None = None
        self._design_worker: VoiceDesignWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # --- portrait ---
        self.portrait = QLabel()
        self.portrait.setFixedSize(_PORTRAIT_W, _PORTRAIT_H)
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setObjectName("PortraitSlot")
        self.portrait.setText("no portrait")
        root.addWidget(self.portrait)

        self.portrait_btn = QPushButton("Generate portrait")
        self.portrait_btn.setObjectName("Ghost")
        self.portrait_btn.clicked.connect(self._generate_portrait)
        root.addWidget(self.portrait_btn)
        self._load_existing_portrait()

        # --- identity ---
        header = QHBoxLayout()
        name = QLabel(character.display_name)
        name.setObjectName("CardName")
        name.setWordWrap(True)
        header.addWidget(name, stretch=1)
        header.addWidget(self._role_badge(character.role_importance.value), 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        meta = QLabel(
            f"{character.gender_guess.value} · {character.age_band.value} · "
            f"{character.total_mentions} mentions"
        )
        meta.setObjectName("Subtle")
        root.addWidget(meta)

        if character.appearance_description:
            look = QLabel(character.appearance_description)
            look.setWordWrap(True)
            look.setObjectName("Subtle")
            root.addWidget(look)

        if character.vocal_traits:
            root.addWidget(_flow([_chip(t) for t in character.vocal_traits[:5]]))

        # --- voice section ---
        root.addWidget(self._divider())
        vhead = QLabel("VOICE")
        vhead.setObjectName("SectionHead")
        root.addWidget(vhead)
        if character.voice_hint:
            vh = QLabel(character.voice_hint)
            vh.setObjectName("Subtle")
            vh.setWordWrap(True)
            root.addWidget(vh)

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.errorOccurred.connect(self._on_player_error)
        self._preview_path: str | None = self._saved_preview()

        vrow = QHBoxLayout()
        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.setFixedWidth(36)
        self.play_btn.setToolTip("Play a short voice sample")
        self.play_btn.clicked.connect(self._toggle_play)
        self.voice_name_lbl = QLabel()
        self.voice_name_lbl.setObjectName("Subtle")
        self.gen_voice_btn = QPushButton("Generate")
        self.gen_voice_btn.setObjectName("Ghost")
        self.gen_voice_btn.setToolTip("Design a voice from this character's profile (Qwen3)")
        self.gen_voice_btn.clicked.connect(self._generate_voice)
        vrow.addWidget(self.play_btn)
        vrow.addWidget(self.voice_name_lbl, stretch=1)
        vrow.addWidget(self.gen_voice_btn)
        root.addLayout(vrow)

        self.drop_hint = QLabel("drop an audio file here to set the voice")
        self.drop_hint.setObjectName("DropHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.drop_hint)
        self._update_voice_label()
        self._autoplay = False
        self._refresh_state()

    # --- card status colour --------------------------------------------------
    _STATE_BORDER = {
        "queued": "#f4db7d",       # waiting in the render queue
        "generating": "#3a6df0",   # actively generating
        "complete": "#4ade80",     # voice ready
        "incomplete": "#2e3650",   # no voice yet
    }

    def _set_state(self, state: str) -> None:
        self._state = state
        colour = self._STATE_BORDER.get(state, "#2e3650")
        width = 2 if state in ("queued", "generating", "complete") else 1
        self.setStyleSheet(f"QFrame#Card {{ border: {width}px solid {colour}; }}")

    def _refresh_state(self) -> None:
        self._set_state("complete" if self._char.voice_sample else "incomplete")

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

        # aliases
        if character.aliases:
            al = QLabel("aka " + ", ".join(character.aliases))
            al.setObjectName("Subtle")
            al.setWordWrap(True)
            root.addWidget(al)

        if character.needs_review:
            warn = QLabel("⚠ needs review")
            warn.setStyleSheet("color: #f0b23a;")
            root.addWidget(warn)

        # spoiler-safe hidden notes behind a reveal button
        if character.notes_hidden_by_default:
            self._hidden = QLabel(character.notes_hidden_by_default)
            self._hidden.setObjectName("Subtle")
            self._hidden.setWordWrap(True)
            self._hidden.setVisible(False)
            reveal = QPushButton("Reveal details")
            reveal.clicked.connect(self._toggle_hidden)
            self._reveal_btn = reveal
            root.addWidget(reveal)
            root.addWidget(self._hidden)

    # --- drag & drop voice ---------------------------------------------------

    def _dropped_audio(self, event) -> Path | None:
        md = event.mimeData()
        if not md.hasUrls():
            return None
        for url in md.urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in _AUDIO_EXTS:
                return p
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._dropped_audio(event):
            event.acceptProposedAction()
            self.drop_hint.setText("⤓ release to assign voice")
            self.setStyleSheet("QFrame#Card { border: 1px solid #3a6df0; }")

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._update_voice_label()
        self._set_state(getattr(self, "_state", "incomplete"))   # restore status colour

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setStyleSheet("")
        path = self._dropped_audio(event)
        if not path:
            return
        from app.services import project_service
        from app.ui.voice_drop_dialog import VoiceDropDialog

        # Ask: apply the dropped sample as-is, or optimize + preview first.
        dlg = VoiceDropDialog(str(path), self)
        if not dlg.exec():
            return
        chosen = dlg.result_path()
        if not chosen:
            return
        path = Path(chosen)

        # Release any file the player holds (Windows locks it, which otherwise
        # makes the copy fail with "could not save voice").
        self._stop_player()

        proj = project_service.active()
        try:
            if proj is not None:
                dest = project_service.import_character_voice(
                    proj, self._char.character_id, path
                )
                # A custom voice must win over an old auto-generated Hörprobe:
                # drop the cached preview so rendering clones the custom sample.
                proj.preview_path(self._char.character_id).unlink(missing_ok=True)
            else:  # no project open — keep the original path
                dest = str(path)
        except Exception as err:  # noqa: BLE001
            self.drop_hint.setText(f"⚠ could not save voice: {err}")
            return
        self._char.voice_sample = dest
        self._char.custom_voice = True
        self._preview_path = None  # force re-render with the new voice
        self._update_voice_label()
        self.voice_assigned.emit(self._char.character_id, dest)
        event.acceptProposedAction()
        self._start_preview_render(play=False)   # render German preview, no auto-play

    def _stop_player(self) -> None:
        from PySide6.QtCore import QUrl
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:  # noqa: BLE001
            pass

    # --- voice ---------------------------------------------------------------

    def _update_voice_label(self) -> None:
        if self._char.voice_sample:
            self.voice_name_lbl.setText(f"🔊 {Path(self._char.voice_sample).name}")
            self.drop_hint.setText("drop another file to replace")
        else:
            self.voice_name_lbl.setText("no voice assigned")
            self.drop_hint.setText("drop an audio file here to set the voice")

    def _voice_for_preview(self):
        if not self._char.voice_sample:
            return None
        return Voice(
            voice_id=self._char.character_id,
            name=self._char.display_name,
            ref_audio_path=self._char.voice_sample,
            gender=self._char.gender_guess.value,
            age=self._char.age_band.value,
        )

    def _saved_preview(self) -> str | None:
        """Reuse a previously rendered Hörprobe instead of re-generating it."""
        from app.services import project_service

        proj = project_service.active()
        if proj is None:
            return None
        p = proj.preview_path(self._char.character_id)
        return str(p) if p.exists() else None

    def _preview_out_path(self):
        from app.services import project_service

        proj = project_service.active()
        return proj.preview_path(self._char.character_id) if proj is not None else None

    def _generate_voice(self) -> None:
        self.gen_voice_btn.setEnabled(False)
        self.gen_voice_btn.setText("…")
        self._set_state("queued")
        self._design_worker = VoiceDesignWorker(self._char, self)
        self._design_worker.started_work.connect(lambda: self._set_state("generating"))
        self._design_worker.step.connect(
            lambda v, m: self.gen_voice_btn.setText(f"{v}/{m}")
        )
        self._design_worker.finished_ok.connect(self._voice_designed)
        self._design_worker.failed.connect(self._voice_design_failed)
        self._design_worker.start()

    def _voice_designed(self, path: str) -> None:
        self.gen_voice_btn.setEnabled(True)
        self.gen_voice_btn.setText("Generate")
        self._char.voice_sample = path
        # The Qwen sample is English (timbre only); render the German Higgs
        # preview now so it's ready — but DON'T auto-play it.
        self._preview_path = None
        self._update_voice_label()
        self.voice_assigned.emit(self._char.character_id, path)
        self._start_preview_render(play=False)

    def _voice_design_failed(self, _msg: str) -> None:
        self.gen_voice_btn.setEnabled(True)
        self.gen_voice_btn.setText("Generate")
        self.gen_voice_btn.setToolTip("Voice design failed — check ComfyUI / TTS stage")
        self._refresh_state()

    def _start_preview_render(self, play: bool) -> None:
        """Render the German Higgs preview. play=True auditions it on completion."""
        self._autoplay = play
        self.play_btn.setEnabled(False)
        self._set_state("queued")
        self.voice_name_lbl.setText("preview queued…")
        self._tts_worker = TTSPreviewWorker(
            self._voice_for_preview(), out_path=self._preview_out_path(), parent=self
        )
        self._tts_worker.started_work.connect(self._on_render_started)
        self._tts_worker.step.connect(
            lambda v, m: self.voice_name_lbl.setText(f"rendering {v}/{m}…")
        )
        self._tts_worker.finished_ok.connect(self._render_done)
        self._tts_worker.failed.connect(self._render_fail)
        self._tts_worker.start()

    def _on_render_started(self) -> None:
        self._set_state("generating")
        self.voice_name_lbl.setText("rendering preview…")

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
            return
        if self._preview_path and Path(self._preview_path).exists():
            self._play_file(self._preview_path)
            return
        self._start_preview_render(play=True)   # render then play (user pressed play)

    def _render_done(self, path: str) -> None:
        self.play_btn.setEnabled(True)
        self._preview_path = path
        self._update_voice_label()
        self._set_state("complete")
        if self._autoplay:
            self._play_file(path)
        self._autoplay = False

    def _render_fail(self, _msg: str) -> None:
        self.play_btn.setEnabled(True)
        self.voice_name_lbl.setText("preview failed — check ComfyUI")
        self._refresh_state()

    def _play_file(self, path: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _on_playback_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        icon = QStyle.StandardPixmap.SP_MediaStop if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play_btn.setIcon(self.style().standardIcon(icon))

    def _on_player_error(self, _error, msg: str) -> None:
        # QMediaPlayer can't always decode mp3 (missing codec) — fall back to the
        # OS default player so preview still works.
        if self._preview_path:
            play_audio(self._preview_path)

    # --- portrait ------------------------------------------------------------

    def _load_existing_portrait(self) -> None:
        path = self._char.portrait_path or str(portrait_service.portrait_path(self._char))
        from pathlib import Path

        if Path(path).exists():
            self._set_portrait(path)

    def _set_portrait(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            return
        self.portrait.setPixmap(
            pix.scaled(
                _PORTRAIT_W,
                _PORTRAIT_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._char.portrait_path = path

    def _generate_portrait(self) -> None:
        self.portrait_btn.setEnabled(False)
        self.portrait_btn.setText("Generating…")
        self._portrait_worker = PortraitWorker(self._char, self)
        self._portrait_worker.step.connect(
            lambda _cid, v, m: self.portrait_btn.setText(f"Sampling {v}/{m}…")
        )
        self._portrait_worker.finished_ok.connect(self._on_portrait_done)
        self._portrait_worker.failed.connect(self._on_portrait_failed)
        self._portrait_worker.start()

    def _on_portrait_done(self, _cid: str, path: str) -> None:
        self._set_portrait(path)
        self.portrait_btn.setEnabled(True)
        self.portrait_btn.setText("Regenerate portrait")

    def _on_portrait_failed(self, _cid: str, message: str) -> None:
        self.portrait_btn.setEnabled(True)
        self.portrait_btn.setText("Generate portrait")
        self.portrait.setText("portrait failed")
        self.portrait.setToolTip(message)

    def _toggle_hidden(self) -> None:
        shown = not self._hidden.isVisible()
        self._hidden.setVisible(shown)
        self._reveal_btn.setText("Hide details" if shown else "Reveal details")

    @staticmethod
    def _role_badge(role: str) -> QLabel:
        badge = QLabel(role.upper())
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = ROLE_COLORS.get(role, "#9aa3b2")
        badge.setStyleSheet(f"background: {color};")
        return badge
