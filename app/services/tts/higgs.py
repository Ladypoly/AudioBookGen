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
        workflow = request.workflow or CONFIG.comfy.tts_workflow
        style = tag_builder.tag_style_for_workflow(workflow)
        text = tag_builder.build_text(request.text, request.delivery, style)
        ref_name, ref_path = self._ensure_reference(request.voice)
        out = request.out_path or (CONFIG.comfy.comfy_dir / "tts_out.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)

        # Superset of placeholders so any clone workflow (Higgs / OmniVoice) fills
        # what it needs. OmniVoice's CharacterVoicesNode wants the reference
        # clip's transcript ({reference_text}); Higgs ignores the extra key.
        replacements: dict[str, object] = {
            "{tts_text}": text,
            "{text}": text,
            "{reference_audio}": ref_name,
            "{reference_text}": (request.voice.ref_text if request.voice else "") or "",
            "{filename_prefix}": f"b2ad/{out.stem}",
            "{seed}": request.seed or random.randint(0, 2**31 - 1),
        }
        try:
            comfy_service.run_workflow(
                workflow, replacements, out, on_step=on_step,
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
        """Reference decoded to PCM WAV (Higgs drifts on MP3 refs) — exactly as-is
        otherwise (no pitch-shifting; it moves formants and degrades the voice).
        Cached per (voice, file). A too-deep timbre is prevented upstream by the
        voice-design re-roll, not patched here."""
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
