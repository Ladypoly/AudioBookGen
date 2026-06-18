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

# Target median-pitch range (Hz) per (gender, age). The reference is nudged into
# this band before cloning so Qwen's unstable pitch can't make a man sound like
# a woman (or a bass too deep for Higgs to clone). Male lows stay >= the ~105 Hz
# clonable floor. Unknown/ambiguous gender -> no clamp (just the floor).
_PITCH_RANGES = {
    ("male", "child"): (200, 300),
    ("male", "teen"): (120, 185),
    ("male", "young_adult"): (108, 150),
    ("male", "adult"): (108, 150),
    ("male", "elderly"): (112, 165),
    ("female", "child"): (220, 320),
    ("female", "teen"): (190, 285),
    ("female", "young_adult"): (172, 262),
    ("female", "adult"): (165, 255),
    ("female", "elderly"): (160, 245),
}


def _pitch_range(gender: str, age: str):
    return _PITCH_RANGES.get((gender, age)) or _PITCH_RANGES.get((gender, "adult"))


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
        """Nudge the reference's median pitch into the band expected for this
        voice's gender/age (and never below Higgs' clonable floor), so cloning
        keeps the right voice instead of drifting up into a female sound."""
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
            if med <= 0:
                return
            rng = _pitch_range(getattr(voice, "gender", "unknown"),
                               getattr(voice, "age", "unknown"))
            if rng:
                low = max(rng[0], self._PITCH_FLOOR_HZ)
                high = rng[1]
                if med < low:
                    target = low * 1.05
                elif med > high:
                    target = high * 0.96
                else:
                    return
            elif med < self._PITCH_FLOOR_HZ:           # no range: just rescue too-deep
                target = self._PITCH_TARGET_HZ
            else:
                return
            steps = max(-7.0, min(7.0, 12.0 * math.log2(target / med)))
            shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=steps)
            sf.write(str(dst), shifted, sr)
            logger.info("Pitch-normalised reference %.0fHz -> ~%.0fHz (%+.1f st)",
                        med, target, steps)
        except Exception:  # noqa: BLE001
            logger.warning("pitch normalise skipped", exc_info=True)
