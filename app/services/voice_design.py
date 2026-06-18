"""Voice design provider — Qwen3 TTS voice designer (via ComfyUI).

Generates a brand-new voice from a character's profile (no reference sample
needed) using the VoiceDesign workflow, and saves the result as the character's
voice sample. Kept as its own module so other voice-design providers can be
added later behind the same `design_voice` call (PLAN: voice design providers).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import CONFIG
from app.schemas.characters import Character
from app.services import comfy_service

logger = logging.getLogger(__name__)

# Qwen3 designer works in English; it only shapes the voice timbre. The German
# pronunciation is produced later by Higgs cloning this sample.
_AGE = {
    "child": "a child", "teen": "a teenage", "young_adult": "a young",
    "adult": "an adult", "elderly": "an elderly", "unknown": "an",
}
_GENDER = {"male": "man", "female": "woman", "ambiguous": "person", "unknown": "person"}

# Explicit acoustic age cues — Qwen's age control is weak without them
# (e.g. "elderly" alone does not sound old; the tremor/thin/slow cues do).
_AGE_ACOUSTIC = {
    "child": "a young child's voice, around 8 years old, bright and high-pitched, light and little",
    "teen": ("a teenager around 16 years old — youthful but clearly PAST childhood; "
             "the voice has already broken/matured, definitely NOT a small child"),
    "young_adult": ("a fully grown young adult in their twenties — a mature, "
                    "grown-up adult voice, NOT a teenager and NOT a child"),
    "adult": "a mature adult voice in their prime",
    "elderly": ("a distinctly aged, elderly voice — thin and quavering with a "
                "noticeable tremor, breathy and frail, slow and careful in pace, "
                "clearly sounding very old"),
    "unknown": "an adult voice",
}


def build_voice_description(char: Character) -> str:
    """Structured English voice-design instruct for Qwen3 (English/Chinese only).

    Follows Qwen's attribute style (gender / age / accent / texture / context)
    so the timbre fits the character's role. The book is British → British
    English accent. Higgs later clones this timbre to speak German."""
    from app.core.config import CONFIG

    g = char.gender_guess.value
    ageb = char.age_band.value
    accent = CONFIG.tts.design_accent
    age_acoustic = _AGE_ACOUSTIC.get(ageb, "a mature adult voice")
    traits = ", ".join(char.vocal_traits[:6]) or char.voice_hint or "natural, clear"

    # Gender is the attribute Qwen drifts on most, so state it FIRST, in caps,
    # with the pitch register, and reinforce it at the end.
    if ageb in ("child", "teen") and g in ("male", "female"):
        kid = "boy" if g == "male" else "girl"
        lead = (f"A {'MALE' if g == 'male' else 'FEMALE'} young person — a {kid}'s voice")
    elif g == "male":
        # Clearly male, but a NORMAL male pitch — an extreme deep bass (~90 Hz)
        # can't be cloned by Higgs and drifts up into a female-sounding voice.
        lead = ("A MALE voice — a man, clearly masculine with a natural adult "
                "male pitch (a normal baritone, NOT an extreme deep bass)")
    elif g == "female":
        lead = "A FEMALE voice — a woman, distinctly feminine, higher in pitch"
    else:
        lead = "A person's voice"
    reinforce = {"male": "Keep it unmistakably male and masculine.",
                 "female": "Keep it unmistakably female and feminine."}.get(g, "")

    parts = [
        f"{lead}, with a {accent} accent.",
        f"Age: {age_acoustic}.",
        f"Vocal qualities: {traits}.",
    ]
    if char.context:
        parts.append(f"Character: {char.context[:200]}")
    if reinforce:
        parts.append(reinforce)
    parts.append("Natural, clear articulation, fitting the character.")
    return " ".join(parts)


def design_voice(char: Character, out_path: Path, on_step=None) -> Path:
    """Render a designed voice for `char` to out_path (an mp3)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    description = build_voice_description(char)
    replacements: dict[str, object] = {
        "{voice_description}": description,
        "{reference_text}": CONFIG.tts.design_reference_text,
        "{character_name}": char.display_name,
        "{language}": CONFIG.tts.design_language,
        "{filename_prefix}": f"b2ad/{out_path.stem}",
    }
    logger.info("Designing voice for %s: %s", char.display_name, description)
    # Higgs clones faithfully only when the timbre sits in its range; a too-deep
    # male design (< ~118 Hz) makes the later clone drift up (even to a female
    # voice). Qwen varies per run (temperature), so re-roll a too-deep one.
    male = char.gender_guess.value == "male"
    for attempt in range(3):
        comfy_service.run_workflow(
            CONFIG.comfy.voicedesign_workflow, replacements, out_path, on_step=on_step,
            timeout=CONFIG.comfy.tts_timeout_s,
        )
        if not male:
            break
        med = _median_pitch(out_path)
        if med is None or med >= 118.0:
            break
        logger.info("Voice design too deep for %s (%.0f Hz) — re-rolling (%d/3)",
                    char.display_name, med, attempt + 1)
    return out_path


def _median_pitch(path: Path) -> float | None:
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(str(path), sr=16000, mono=True, duration=10)
        f0, _, _ = librosa.pyin(y, fmin=55, fmax=400, sr=sr)
        f0 = f0[~np.isnan(f0)]
        return float(np.median(f0)) if f0.size else None
    except Exception:  # noqa: BLE001
        return None
