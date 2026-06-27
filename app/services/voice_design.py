"""Voice design provider — Qwen3 TTS voice designer (via ComfyUI).

Generates a brand-new voice from a character's profile (no reference sample
needed) using the VoiceDesign workflow, and saves the result as the character's
voice sample. Kept as its own module so other voice-design providers can be
added later behind the same `design_voice` call (PLAN: voice design providers).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

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


# Qwen3 voice-design is driven by free-form natural language; these cue maps
# turn the popup's visual selectors into descriptive phrases the model honours.
_PITCH = {
    "very_low": "a very low, deep pitch register",
    "low": "a low pitch register",
    "moderate": "",                  # default — no extra cue
    "high": "a high pitch register",
    "very_high": "a very high pitch register",
}
_SPEED = {
    "very_slow": "a very slow, deliberate speaking pace",
    "slow": "a slow speaking pace",
    "normal": "",
    "fast": "a fast speaking pace",
    "very_fast": "a very fast, rapid speaking pace",
}
_ENERGY = {
    "calm": "calm, relaxed energy",
    "soft": "soft, gentle energy",
    "moderate": "",
    "energetic": "high, lively energy",
    "intense": "intense, powerful energy",
}
_EMOTION = {
    "neutral": "",
    "happy": "a happy, warm tone",
    "sad": "a sad, melancholic tone",
    "angry": "an angry, forceful tone",
    "excited": "an excited, enthusiastic tone",
    "fearful": "a fearful, tense tone",
    "tender": "a tender, affectionate tone",
    "serious": "a serious, grave tone",
    "playful": "a playful, light-hearted tone",
}
_STYLE = {
    "normal": "",
    "narration": "a clear narration / storytelling delivery",
    "conversational": "a natural, conversational delivery",
    "whisper": "spoken softly in a whispering style",
    "soft": "a soft, gentle delivery",
    "dramatic": "a dramatic, expressive delivery",
    "authoritative": "a confident, authoritative delivery",
}


def compose_description(
    *, gender: str, age: str, accent: str, traits: str, context: str = "",
    pitch: str = "moderate", speed: str = "normal", energy: str = "moderate",
    emotion: str = "neutral", style: str = "normal",
    timbre: list[str] | None = None, language: str | None = None,
) -> str:
    """Build a Qwen3 voice-design instruct from explicit attributes.

    Qwen voice design takes free-form natural language controlling timbre,
    prosody, emotion, persona, gender, age, accent, pacing and energy — this
    composes all of those from the popup's selectors."""
    age_acoustic = _AGE_ACOUSTIC.get(age, "a mature adult voice")

    if age in ("child", "teen") and gender in ("male", "female"):
        kid = "boy" if gender == "male" else "girl"
        lead = f"A {'MALE' if gender == 'male' else 'FEMALE'} young person — a {kid}'s voice"
    elif gender == "male":
        lead = ("A MALE voice — a man, clearly masculine with a natural adult "
                "male pitch (a normal baritone, NOT an extreme deep bass)")
    elif gender == "female":
        lead = "A FEMALE voice — a woman, distinctly feminine, higher in pitch"
    else:
        lead = "A person's voice"
    reinforce = {"male": "Keep it unmistakably male and masculine.",
                 "female": "Keep it unmistakably female and feminine."}.get(gender, "")

    parts = [f"{lead}, with a {accent} accent.", f"Age: {age_acoustic}."]
    if language:
        parts.append(f"Speaking {language}.")
    if _PITCH.get(pitch):
        parts.append(f"Pitch: {_PITCH[pitch]}.")
    if _SPEED.get(speed):
        parts.append(f"Pace: {_SPEED[speed]}.")
    if _ENERGY.get(energy):
        parts.append(f"Energy: {_ENERGY[energy]}.")
    if _EMOTION.get(emotion):
        parts.append(f"Emotion: speaks with {_EMOTION[emotion]}.")
    if _STYLE.get(style):
        parts.append(f"Style: {_STYLE[style]}.")
    if timbre:
        parts.append(f"Timbre/texture: {', '.join(timbre)}.")
    parts.append(f"Vocal qualities: {traits}.")
    if context:
        parts.append(f"Character: {context[:200]}")
    if reinforce:
        parts.append(reinforce)
    parts.append("Natural, clear articulation, fitting the character.")
    return " ".join(parts)


def build_voice_description(char: Character) -> str:
    """The default Qwen3 instruct derived from a character's profile."""
    traits = ", ".join(char.vocal_traits[:6]) or char.voice_hint or "natural, clear"
    return compose_description(
        gender=char.gender_guess.value, age=char.age_band.value,
        accent=CONFIG.tts.design_accent, traits=traits, context=char.context)


class _Intro(BaseModel):
    text: str


def _intro_profile(char: Character) -> str:
    """A compact, spoiler-light character brief for the intro prompt, built from
    every field extraction populated (not just the 120-char context)."""
    who = " ".join(x for x in (char.age_band.value.replace("_", " "),
                               char.gender_guess.value) if x and x != "unknown")
    bits = [
        f"role: {char.role_importance.value}" if char.role_importance else "",
        f"is: {who}" if who else "",
        f"about: {char.context}" if char.context else "",
        f"personality: {char.personality_notes}" if char.personality_notes else "",
        f"appearance: {char.appearance_description}" if char.appearance_description else "",
        f"voice: {char.voice_hint or ', '.join(char.vocal_traits[:5])}"
        if (char.voice_hint or char.vocal_traits) else "",
        f"also called: {', '.join(char.aliases[:4])}" if char.aliases else "",
    ]
    return "; ".join(b for b in bits if b) or "unknown"


def compose_intro_text(char: Character, language: str) -> str:
    """LLM-written short, in-character self-introduction in `language`, including
    the character's name — the spoken text for the voice sample."""
    from app.services import ollama_service

    prompt = (
        f'Write a first-person self-introduction that the character '
        f'"{char.display_name}" would say out loud, in {language}. '
        f'It must be long enough to take at least 12 seconds to speak: '
        f'4-6 full sentences, about 55-85 words. Begin by stating the name '
        f'(e.g. "Hallo, ich bin {char.display_name} ..."), then a few things that '
        f'fit this person — what they do, how they carry themselves, how they '
        f'sound or feel. Make it feel personal to THEM, not generic, and varied '
        f'in sentence length so the voice sample shows range.\n'
        f'Character profile — {_intro_profile(char)}.\n'
        f'Do NOT reveal plot, spoilers, fate or relationships. Output only the '
        f'natural spoken words — no narration, no quotation marks, no stage directions.'
    )
    try:
        text = ollama_service.generate_json(prompt, _Intro, num_predict=320).text.strip()
        if len(text) >= 80:                       # ~6s+ of speech; reject too-short replies
            return text
    except Exception:  # noqa: BLE001
        logger.warning("intro LLM failed for %s; using template", char.display_name, exc_info=True)
    de = language.lower().startswith("german") or language.lower().startswith("deutsch")
    name = char.display_name
    voice = char.voice_hint or (", ".join(char.vocal_traits[:3]) if char.vocal_traits else "")
    if de:
        return (f"Hallo, ich bin {name}. Schön, dass du mir zuhörst. "
                f"Ich erzähle dir kurz ein wenig über mich, damit du meine Stimme "
                f"gut kennenlernen kannst. {('Man sagt, meine Stimme klinge ' + voice + '. ') if voice else ''}"
                f"Lass uns gemeinsam in diese Geschichte eintauchen — ich bin gespannt, "
                f"was uns auf den nächsten Seiten erwartet.")
    return (f"Hello, I'm {name}. Thanks for listening. Let me tell you a little about "
            f"myself so you get to know how my voice sounds. "
            f"{('People say my voice sounds ' + voice + '. ') if voice else ''}"
            f"Let's dive into this story together — I'm curious what waits for us "
            f"on the pages ahead.")


def render_intro_sample(char: Character, timbre_ref: Path, out_path: Path,
                        language: str, text: str | None = None, on_step=None) -> Path:
    """Speak an in-character intro (in `language`) with Higgs, cloning the just
    designed timbre. The result becomes the card's playable voice sample.
    Pass `text` to skip the LLM call (e.g. when it was composed earlier)."""
    from app.schemas.voice import Voice
    from app.services.tts import registry
    from app.services.tts.base import TTSRequest

    text = text or compose_intro_text(char, language)
    voice = Voice(voice_id=char.character_id, name=char.display_name,
                  ref_audio_path=str(timbre_ref), ref_text=CONFIG.tts.design_reference_text,
                  gender=char.gender_guess.value, age=char.age_band.value)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Intro sample for %s (%s): %s", char.display_name, language, text)
    registry.get_engine().synthesize(
        TTSRequest(text=text, voice=voice, out_path=out_path,
                   workflow=getattr(char, "tts_workflow", "") or None), on_step=on_step)
    return out_path


def design_voice(char: Character, out_path: Path, on_step=None,
                 description: str | None = None, language: str | None = None) -> Path:
    """Render a designed voice for `char` to out_path (an mp3).

    `description` overrides the auto-built instruct and `language` the design
    language (both from the editable voice-design popup)."""
    import random
    out_path.parent.mkdir(parents=True, exist_ok=True)
    description = description or build_voice_description(char)
    lang = language or CONFIG.tts.design_language
    # Superset of placeholders so any design workflow (Qwen / OmniVoice) fills
    # what it needs — OmniVoice puts the description in the engine "instruct"
    # ({voice_description}) and speaks {reference_text}; Qwen uses all of them.
    replacements: dict[str, object] = {
        "{voice_description}": description,
        "{reference_text}": CONFIG.tts.design_reference_text,
        "{character_name}": char.display_name,
        "{language}": lang,
        "{source_language}": lang,
        "{target_language}": "English",
        "{seed}": random.randint(0, 2**31 - 1),
        "{filename_prefix}": f"b2ad/{out_path.stem}",
    }
    logger.info("Designing voice for %s: %s", char.display_name, description)
    comfy_service.run_workflow(
        CONFIG.comfy.voicedesign_workflow, replacements, out_path, on_step=on_step,
        timeout=CONFIG.comfy.tts_timeout_s,
    )
    return out_path
