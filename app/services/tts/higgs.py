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

# Prepared-reference cache: a reference is decoded + pitch-checked once per
# (voice, source file), not for every line of a chapter. Guarded for the
# parallel render pool.
_REF_CACHE: dict = {}
_REF_LOCK = threading.Lock()


class HiggsTTSEngine:
    name = "higgs_v3"

    def synthesize(self, request: TTSRequest, on_step=None) -> Path:
        text = tag_builder.build_higgs_text(request.text, request.delivery)
        ref_name = self._ensure_reference(request.voice)
        out = request.out_path or (CONFIG.comfy.comfy_dir / "tts_out.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)

        replacements: dict[str, object] = {
            "{tts_text}": text,
            "{reference_audio}": ref_name,
            "{filename_prefix}": f"b2ad/{out.stem}",
            "{seed}": request.seed or random.randint(0, 2**31 - 1),
        }
        comfy_service.run_workflow(
            CONFIG.comfy.tts_workflow, replacements, out, on_step=on_step,
            timeout=CONFIG.comfy.tts_timeout_s,
        )
        return out

    # --- helpers -------------------------------------------------------------

    # Higgs can't clone an extremely deep voice — below ~this Hz it drifts up
    # (even into a female voice). So if a reference is deeper, pitch it up to
    # the target before cloning.
    _PITCH_FLOOR_HZ = 105.0
    _PITCH_TARGET_HZ = 115.0

    def _ensure_reference(self, voice) -> str:
        """Put a clone-ready reference into ComfyUI's input/ and return its name.
        Non-WAV sources are decoded to PCM WAV (Higgs drifts on MP3 refs), and a
        too-deep reference is pitch-lifted so Higgs can actually clone it.
        Prepared once per (voice, file) — cached so a chapter's 100 lines don't
        re-analyse the same clip."""
        if voice is None or not voice.ref_audio_path:
            return CONFIG.comfy.default_reference_audio
        src = Path(voice.ref_audio_path)
        if not src.exists():
            logger.warning("Voice ref missing: %s -> default", src)
            return CONFIG.comfy.default_reference_audio
        input_dir = CONFIG.comfy.comfy_dir / "ComfyUI" / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        ref_name = f"ref_{voice.voice_id}.wav"
        dst = input_dir / ref_name
        try:
            key = (voice.voice_id, str(src), src.stat().st_mtime)
        except OSError:
            key = None
        with _REF_LOCK:
            if key is not None and _REF_CACHE.get(key) and dst.exists():
                return ref_name
            if src.suffix.lower() == ".wav":
                shutil.copyfile(src, dst)
            else:
                from pydub import AudioSegment
                AudioSegment.from_file(src).export(dst, format="wav")
            self._normalize_pitch(dst, voice)
            if key is not None:
                _REF_CACHE[key] = True
        return ref_name

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
