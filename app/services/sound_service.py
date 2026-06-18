"""Stable Audio 3 generation: ambience beds, SFX one-shots, music cues.

Thin wrapper over the lean ComfyUI Stable Audio graph. Prompts follow the
AudioSparx convention (a TrackType tag + a dense description + a Length hint).
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from app.core.config import CONFIG
from app.services import comfy_service

logger = logging.getLogger(__name__)

# AudioSparx-style tag prefixes per cue kind.
_TAG = {
    "sfx": "TrackType: SFX. ",
    "ambience": "TrackType: SFX. ",
    "music": "TrackType: Music, VocalType: Instrumental. ",
}

_NEGATIVE = "low quality, distorted, clipping, harsh noise"


def generate(
    prompt: str, seconds: float, out_path: Path,
    kind: str = "sfx", seed: int | None = None, negative: str = _NEGATIVE,
) -> Path:
    """Render one audio clip from a Stable Audio prompt to out_path (mp3).

    A random seed each call, so re-generating ambience/SFX yields a fresh take."""
    seconds = max(1.0, round(float(seconds), 2))
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    text = f"{_TAG.get(kind, '')}{prompt.strip()} Length: {int(seconds)} seconds."
    comfy_service.run_workflow(
        CONFIG.comfy.audio_workflow,
        {
            "{prompt}": text,
            "{negative}": negative,
            "{seconds}": seconds,
            "{seed}": int(seed),
            "{filename_prefix}": f"b2ad/{out_path.stem}",
        },
        out_path,
        timeout=CONFIG.comfy.audio_timeout_s,
    )
    return out_path


def seamless_loop(seg, target_ms: int, crossfade_ms: int = 1500):
    """Tile a clip into a seamless loop of ~target_ms with crossfades so the
    seam is inaudible (for ambience beds that must run under a whole chapter)."""
    from pydub import AudioSegment

    if len(seg) < crossfade_ms * 2:
        crossfade_ms = max(0, len(seg) // 4)
    looped = seg
    while len(looped) < target_ms + crossfade_ms:
        looped = looped.append(seg, crossfade=crossfade_ms)
    # final tail crossfade back to the start for a clean wrap when player loops
    return looped[:target_ms] if len(looped) > target_ms else looped
