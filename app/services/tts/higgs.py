"""Higgs Audio v3 TTS engine (via ComfyUI / TTS-Audio-Suite).

Implements TTSEngine. Builds Higgs tagged text from Delivery, makes the voice
reference audio available to ComfyUI, fills the Higgs workflow, and renders.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from app.core.config import CONFIG
from app.services import comfy_service
from app.services.tts import tag_builder
from app.services.tts.base import TTSRequest

logger = logging.getLogger(__name__)


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
            "{seed}": request.seed or self._seed(request.text),
        }
        comfy_service.run_workflow(
            CONFIG.comfy.tts_workflow, replacements, out, on_step=on_step,
            timeout=CONFIG.comfy.tts_timeout_s,
        )
        return out

    # --- helpers -------------------------------------------------------------

    def _ensure_reference(self, voice) -> str:
        """Higgs LoadAudio reads from ComfyUI's input/ folder. Copy the voice's
        reference there AS-IS (no re-encode — keep the exact format that works)
        under a stable per-voice name, always overwriting so the content is fresh."""
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
        # Higgs clones WAV references faithfully but DRIFTS (even flips gender)
        # on MP3 references — so decode non-WAV sources to PCM WAV. WAV sources
        # are copied byte-for-byte (don't touch what already works).
        if src.suffix.lower() == ".wav":
            shutil.copyfile(src, dst)
        else:
            from pydub import AudioSegment
            AudioSegment.from_file(src).export(dst, format="wav")
        return ref_name

    @staticmethod
    def _seed(text: str) -> int:
        return int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**31)
