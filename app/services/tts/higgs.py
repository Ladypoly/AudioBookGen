"""Higgs Audio v3 TTS engine (via ComfyUI / TTS-Audio-Suite).

Implements TTSEngine. Builds Higgs tagged text from Delivery, makes the voice
reference audio available to ComfyUI, fills the Higgs workflow, and renders.
"""

from __future__ import annotations

import logging
import random
import shutil
import threading
from pathlib import Path

from app.core.config import CONFIG
from app.services import comfy_service
from app.services.tts import tag_builder
from app.services.tts.base import TTSRequest

logger = logging.getLogger(__name__)

# Cache of prepared (decoded-to-WAV + pitch-checked) reference BYTES, keyed by
# (voice, source file). Avoids re-decoding the same clip for a chapter's 100
# lines. The bytes are written to input/ under a UNIQUE name per render —
# ComfyUI's LoadAudio caches by filename, so a stable name would make it reuse a
# stale clip — and the caller deletes that file after the render.
_PREP_CACHE: dict = {}
_PREP_LOCK = threading.Lock()


class HiggsTTSEngine:
    name = "higgs_v3"

    def synthesize(self, request: TTSRequest, on_step=None) -> Path:
        text = tag_builder.build_higgs_text(request.text, request.delivery)
        ref_name, ref_path = self._ensure_reference(request.voice)
        out = request.out_path or (CONFIG.comfy.comfy_dir / "tts_out.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)

        replacements: dict[str, object] = {
            "{tts_text}": text,
            "{reference_audio}": ref_name,
            "{filename_prefix}": f"b2ad/{out.stem}",
            "{seed}": request.seed or random.randint(0, 2**31 - 1),
        }
        try:
            comfy_service.run_workflow(
                CONFIG.comfy.tts_workflow, replacements, out, on_step=on_step,
                timeout=CONFIG.comfy.tts_timeout_s,
            )
        finally:
            if ref_path is not None:                    # don't leave clutter in input/
                try:
                    ref_path.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
        return out

    # --- helpers -------------------------------------------------------------

    # Higgs can't clone an extremely deep voice — below ~this Hz it drifts up
    # (even into a female voice). So if a reference is deeper, pitch it up to
    # the target before cloning.
    _PITCH_FLOOR_HZ = 105.0
    _PITCH_TARGET_HZ = 115.0

    def _ensure_reference(self, voice):
        """Write a clone-ready reference into ComfyUI's input/ under a UNIQUE
        name and return (filename, path). The caller deletes the file after the
        render. Returns (default_name, None) when there's no usable voice ref."""
        if voice is None or not voice.ref_audio_path:
            return CONFIG.comfy.default_reference_audio, None
        src = Path(voice.ref_audio_path)
        if not src.exists():
            logger.warning("Voice ref missing: %s -> default", src)
            return CONFIG.comfy.default_reference_audio, None
        data = self._prepared_bytes(voice, src)
        if not data:
            return CONFIG.comfy.default_reference_audio, None
        import uuid
        input_dir = CONFIG.comfy.comfy_dir / "ComfyUI" / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        ref_name = f"ref_{voice.voice_id}_{uuid.uuid4().hex[:8]}.wav"
        dst = input_dir / ref_name
        dst.write_bytes(data)
        return ref_name, dst

    def _prepared_bytes(self, voice, src: Path):
        """Reference decoded to PCM WAV (Higgs drifts on MP3 refs) and a too-deep
        clip pitch-lifted — as raw bytes, cached per (voice, file)."""
        try:
            key = (voice.voice_id, str(src), src.stat().st_mtime)
        except OSError:
            key = None
        if key is not None:
            with _PREP_LOCK:
                if key in _PREP_CACHE:
                    return _PREP_CACHE[key]
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "ref.wav"
        try:
            if src.suffix.lower() == ".wav":
                shutil.copyfile(src, tmp)
            else:
                from pydub import AudioSegment
                AudioSegment.from_file(src).export(tmp, format="wav")
            self._normalize_pitch(tmp, voice)
            data = tmp.read_bytes()
        except Exception:  # noqa: BLE001
            logger.exception("Reference prep failed: %s", src)
            return None
        finally:
            try:
                tmp.unlink(missing_ok=True)
                tmp.parent.rmdir()
            except Exception:  # noqa: BLE001
                pass
        if key is not None:
            with _PREP_LOCK:
                _PREP_CACHE[key] = data
        return data

    def _normalize_pitch(self, dst: Path, voice) -> None:
        """ONLY rescue a reference too deep for Higgs to clone (< ~105 Hz, where
        it drifts up into a female voice). Everything else is left exactly as-is
        — pitch-shifting also moves formants and degrades the voice, so we never
        touch a reference Higgs can already clone faithfully."""
        try:
            import math

            import librosa
            import numpy as np
            import soundfile as sf
            y, sr = librosa.load(str(dst), sr=None, mono=True)
            f0, _, _ = librosa.pyin(y, fmin=55, fmax=420, sr=sr)
            f0 = f0[~np.isnan(f0)]
            if f0.size == 0:
                return
            med = float(np.median(f0))
            if not (0 < med < self._PITCH_FLOOR_HZ):   # clonable as-is → leave it
                return
            steps = 12.0 * math.log2(self._PITCH_TARGET_HZ / med)
            shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=steps)
            sf.write(str(dst), shifted, sr)
            logger.info("Lifted too-deep reference %.0fHz -> ~%.0fHz (+%.1f st)",
                        med, self._PITCH_TARGET_HZ, steps)
        except Exception:  # noqa: BLE001
            logger.warning("pitch lift skipped", exc_info=True)
