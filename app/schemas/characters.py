"""Character extraction schemas (pydantic v2, enum-locked, spoiler-safe).

Single source of truth for: LLM output validation (map + reduce passes),
in-memory registry shape, and later DB rows / cache keys.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

# Bounded strings keep the grammar from allowing a runaway loop inside one
# value (abliterated models otherwise ramble until the token budget is gone).
ShortStr = Annotated[str, StringConstraints(max_length=40, strip_whitespace=True)]
NameStr = Annotated[str, StringConstraints(max_length=80, strip_whitespace=True)]


class GenderGuess(str, Enum):
    male = "male"
    female = "female"
    ambiguous = "ambiguous"
    unknown = "unknown"


class AgeBand(str, Enum):
    child = "child"
    teen = "teen"
    young_adult = "young_adult"
    adult = "adult"
    elderly = "elderly"
    unknown = "unknown"


class RoleImportance(str, Enum):
    """Derived from total mention count, NOT from LLM plot judgement."""

    narrator = "narrator"
    main = "main"
    secondary = "secondary"
    minor = "minor"
    crowd = "crowd"


# --- MAP pass (per chunk) ----------------------------------------------------


class CharacterMention(BaseModel):
    """One character as seen within a single text chunk."""

    surface_name: NameStr
    gender_guess: GenderGuess = GenderGuess.unknown
    age_band: AgeBand = AgeBand.unknown
    vocal_traits: list[ShortStr] = Field(default_factory=list, max_length=8)
    # Physical surface appearance for portrait generation (spoiler-safe):
    # hair, eyes, build, height, skin, clothing, distinguishing features.
    appearance_traits: list[ShortStr] = Field(default_factory=list, max_length=8)
    # One short, spoiler-safe phrase: who they are / role / where they appear in
    # this chunk (e.g. "the boy's father", "a waiter at the restaurant"). Drives
    # the context-aware description, portrait background and voice.
    context: Annotated[str, StringConstraints(max_length=120)] = ""
    mention_count: int = 1
    # How many lines of DIALOGUE this character speaks in the chunk. 0 = named
    # but silent. Used to keep only speaking roles (+ narrator) in the cast.
    spoken_lines: int = 0

    @field_validator("mention_count", "spoken_lines", mode="before")
    @classmethod
    def _clamp(cls, v: object) -> int:
        """The LLM sometimes emits absurd counts (80M) or negatives — clamp to
        a sane per-chunk range instead of trusting it."""
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, min(n, 100))


class MapResult(BaseModel):
    mentions: list[CharacterMention] = Field(default_factory=list)


# --- REDUCE pass (whole book) ------------------------------------------------


class RegistryCharacter(BaseModel):
    """A canonical character as returned by the reduce pass (pre role calc)."""

    display_name: str
    aliases: list[str] = Field(default_factory=list)
    gender_guess: GenderGuess = GenderGuess.unknown
    age_band: AgeBand = AgeBand.unknown
    voice_hint: str = ""
    personality_notes: str = ""
    vocal_traits: list[str] = Field(default_factory=list)
    appearance_traits: list[str] = Field(default_factory=list)
    # Consolidated neutral visual description used to build the portrait
    # image caption (no plot, no spoilers).
    appearance_description: str = ""
    # Narrative context: who this person is, where they appear, what they do
    # (their function/situation) — spoiler-light. Drives BOTH the voice-design
    # prompt and the portrait background/demeanor.
    context: str = ""
    # In-character self-introduction line (LLM-written at extraction, editable).
    # Spoken via TTS to produce the ~10s voice sample used as the clone reference.
    sample_line: str = ""
    # Per-character clone/TTS workflow override (filename in workflows/). Empty =
    # use the global default (comfy.tts_workflow). Lets the narrator run on a fast
    # no-emotion engine (OmniVoice) while expressive characters use Higgs.
    tts_workflow: str = ""
    total_mentions: int = 0
    spoken_lines: int = 0
    needs_review: bool = False


class ReduceResult(BaseModel):
    characters: list[RegistryCharacter] = Field(default_factory=list)


class WebEnrichment(BaseModel):
    """Spoiler-filtered looks/voice extracted from web snippets for one character."""

    appearance_description: str = ""
    voice_hint: str = ""
    appearance_traits: list[ShortStr] = Field(default_factory=list, max_length=8)
    vocal_traits: list[ShortStr] = Field(default_factory=list, max_length=8)


class PortraitPromptResult(BaseModel):
    """An LLM-written natural-language portrait prompt for one character."""

    prompt: str = ""


# --- Final registry entry (after role_importance assignment) -----------------


class CharacterVariant(BaseModel):
    """One age-stage of a character with its own look + voice.

    A character that appears at several ages (e.g. child vs adult) carries one
    variant per stage; the card shows slide-dots to switch between them. Empty
    `variants` means a single-age character (the base fields are used).
    """

    age_band: AgeBand = AgeBand.unknown
    label: str = ""                       # optional display label, e.g. "as a child"
    appearance_description: str = ""
    portrait_prompt: str = ""
    portrait_path: str | None = None
    voice_sample: str | None = None
    custom_voice: bool = False
    voice_hint: str = ""


class Character(RegistryCharacter):
    """Registry entry shown in the UI as a character card."""

    character_id: str
    role_importance: RoleImportance = RoleImportance.minor
    assigned_voice_id: str | None = None
    # Voice reference sample for this character, copied into the project folder
    # (projects/<book>/voices/<character_id>.<ext>). Set via drag-and-drop.
    voice_sample: str | None = None
    # True when voice_sample is a user-supplied clip (drag-dropped). Such voices
    # are cloned directly and never overwritten by voice design.
    custom_voice: bool = False
    notes_hidden_by_default: str = ""
    # LLM-written natural-language portrait prompt (per character; varied).
    portrait_prompt: str = ""
    # Local path to a generated portrait image, if any.
    portrait_path: str | None = None
    active: bool = True
    # Per-age-stage variants (slide-dots on the card). Empty = single-age.
    variants: list[CharacterVariant] = Field(default_factory=list)
