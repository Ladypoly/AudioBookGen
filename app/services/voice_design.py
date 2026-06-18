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
    "child": "a small child's voice, bright and high-pitched, light and little",
    "teen": "a youthful adolescent voice, fairly high and bright, still young",
    "young_adult": "a youthful adult voice, clear and fresh",
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

    age = _AGE.get(char.age_band.value, "an")
    gender = _GENDER.get(char.gender_guess.value, "person")
    if char.age_band.value in ("child", "teen"):
        gender = {"male": "boy", "female": "girl"}.get(char.gender_guess.value, gender)
    traits = ", ".join(char.vocal_traits[:6]) or char.voice_hint or "natural, clear"
    accent = CONFIG.tts.design_accent
    age_acoustic = _AGE_ACOUSTIC.get(char.age_band.value, "an adult voice")

    parts = [
        f"The voice of {age} {gender} with a {accent} accent.",
        # Age is stated acoustically AND first, because it is the hardest
        # attribute for the model to honour.
        f"Age and timbre: {age_acoustic}.",
        f"Vocal qualities: {traits}.",
    ]
    if char.context:
        parts.append(f"Character: {char.context}")
    if char.personality_notes:
        parts.append(char.personality_notes)
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
    comfy_service.run_workflow(
        CONFIG.comfy.voicedesign_workflow, replacements, out_path, on_step=on_step,
        timeout=CONFIG.comfy.tts_timeout_s,
    )
    return out_path
