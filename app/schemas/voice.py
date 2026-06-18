"""Voice + delivery schemas.

Delivery is enum-locked to Higgs Audio v3's exact control vocabulary (PLAN
Appendix A.1) so the TagBuilder can only ever emit valid tokens.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Emotion(str, Enum):
    elation = "elation"
    amusement = "amusement"
    enthusiasm = "enthusiasm"
    determination = "determination"
    pride = "pride"
    contentment = "contentment"
    affection = "affection"
    relief = "relief"
    contemplation = "contemplation"
    confusion = "confusion"
    surprise = "surprise"
    awe = "awe"
    longing = "longing"
    anger = "anger"
    fear = "fear"
    disgust = "disgust"
    bitterness = "bitterness"
    sadness = "sadness"
    shame = "shame"
    helplessness = "helplessness"
    # 'arousal' exists in the model but is intentionally excluded for this product.


class Style(str, Enum):
    singing = "singing"
    shouting = "shouting"
    whispering = "whispering"


class Prosody(str, Enum):
    speed_very_slow = "speed_very_slow"
    speed_slow = "speed_slow"
    speed_fast = "speed_fast"
    speed_very_fast = "speed_very_fast"
    pitch_low = "pitch_low"
    pitch_high = "pitch_high"
    pause = "pause"
    long_pause = "long_pause"
    expressive_high = "expressive_high"
    expressive_low = "expressive_low"


class Nonverbal(str, Enum):
    """SFX tokens; each renders with matching onomatopoeia inline."""

    cough = "cough"
    laughter = "laughter"
    crying = "crying"
    screaming = "screaming"
    burping = "burping"
    humming = "humming"
    sigh = "sigh"
    sniff = "sniff"
    sneeze = "sneeze"


class Delivery(BaseModel):
    """Expressive delivery metadata for one spoken line (engine-agnostic).

    The TagBuilder converts this into the target engine's syntax centrally, so
    the rest of the app never hardcodes Higgs tokens."""

    emotion: Emotion | None = None
    style: Style | None = None
    prosody: list[Prosody] = Field(default_factory=list)
    nonverbal: list[Nonverbal] = Field(default_factory=list)
    pre_pause_ms: int = 0
    post_pause_ms: int = 0


class Voice(BaseModel):
    """A reusable voice reference for cloning (Higgs zero-shot)."""

    voice_id: str
    name: str
    # Reference audio file (absolute path in the app's store).
    ref_audio_path: str
    # Transcript of the reference clip (improves cloning fidelity; optional for
    # the TTS-Audio-Suite node which can work without it).
    ref_text: str = ""
    tags: list[str] = Field(default_factory=list)
    gender: str = "unknown"
    age: str = "unknown"
    archived: bool = False
