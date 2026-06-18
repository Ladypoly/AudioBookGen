"""A scrubbable audio waveform with a playhead.

Paints peaks from an audio file; click/drag seeks (emits a 0..1 position). Set
the playhead from a media player's position. Reloading after a remix shows the
effect of a settings change live.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class WaveformWidget(QWidget):
    seek_requested = Signal(float)   # 0..1
    hovered = Signal(float)          # 0..1 cursor position while hovering
    hover_off = Signal()             # cursor left the widget

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks: list[float] = []
        self._progress = 0.0
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    # --- data ---------------------------------------------------------------
    def set_audio(self, path: str | None) -> None:
        self._peaks = self._load_peaks(path) if path else []
        self._progress = 0.0
        self.update()

    def clear(self) -> None:
        self._peaks = []
        self._progress = 0.0
        self.update()

    def set_progress(self, frac: float) -> None:
        self._progress = max(0.0, min(1.0, frac))
        self.update()

    @staticmethod
    def _load_peaks(path: str, buckets: int = 1200) -> list[float]:
        try:
            import numpy as np
            from pydub import AudioSegment
            seg = AudioSegment.from_file(path).set_channels(1)
            samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
            if samples.size == 0:
                return []
            peak = float(np.max(np.abs(samples))) or 1.0
            samples /= peak
            n = min(buckets, samples.size)
            chunks = np.array_split(samples, n)
            return [float(np.sqrt(np.mean(c * c))) if c.size else 0.0 for c in chunks]
        except Exception:  # noqa: BLE001
            logger.warning("waveform load failed for %s", path, exc_info=True)
            return []

    # --- interaction --------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self._peaks and self.width() > 0:
            self.seek_requested.emit(max(0.0, min(1.0, e.position().x() / self.width())))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._peaks or self.width() <= 0:
            return
        frac = max(0.0, min(1.0, e.position().x() / self.width()))
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.seek_requested.emit(frac)
        self.hovered.emit(frac)

    def enterEvent(self, e) -> None:  # noqa: N802
        if self._peaks and self.width() > 0:
            self.hovered.emit(max(0.0, min(1.0, e.position().x() / self.width())))

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.hover_off.emit()

    # --- paint --------------------------------------------------------------
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h / 2
        p.fillRect(self.rect(), QColor("#0b1430"))
        if not self._peaks:
            p.setPen(QColor("#54607f"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "no demo yet — generate one")
            return

        n = len(self._peaks)
        play_x = self._progress * w
        for i, peak in enumerate(self._peaks):
            x = i / n * w
            amp = peak * (mid - 4)
            p.setPen(QColor("#4ade80") if x <= play_x else QColor("#6b78b8"))
            p.drawLine(QPointF(x, mid - amp), QPointF(x, mid + amp))
        # playhead
        p.setPen(QPen(QColor("#f4db7d"), 2))
        p.drawLine(QPointF(play_x, 0), QPointF(play_x, h))
