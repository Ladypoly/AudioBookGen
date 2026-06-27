"""Audio-drama script schemas: chapters and per-line items.

A Chapter holds the raw prose; line planning turns it into ordered LineItems
(narration / dialogue) with a speaker and expressive delivery, which the TTS
engine renders one line at a time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.voice import Delivery


class LineType(str, Enum):
    narration = "narration"
    dialogue = "dialogue"
    thought = "thought"  # internal monologue


class SfxCue(BaseModel):
    """A discrete sound effect tied to a line.

    Placement keeps SFX off the speakers: 'over' lays it low under the line's
    own clip; 'gap' plays it in the pause after the line.

    A cue is either generated (from `prompt` via Stable Audio) or supplied by
    the user as a file (`audio_path` set, `custom=True`) — a dropped clip is
    used directly and never regenerated."""

    prompt: str                       # English Stable-Audio description (or a label for custom clips)
    length_s: float = 3.0
    gain_db: float = -7.0
    placement: str = "over"           # "over" line clip | "gap" after it
    position: float = 0.25            # 0..1 offset into the clip for "over"
    # User-supplied clip (drag-and-drop). When set, used as-is.
    audio_path: str | None = None
    custom: bool = False
    fade_in_ms: int = 0
    fade_out_ms: int = 0


class LineItem(BaseModel):
    line_id: str
    chapter_id: str
    index: int
    type: LineType = LineType.narration
    # character_id of the speaker (narrator for narration/thought-by-narrator).
    speaker_id: str = "erz_hler"
    text: str
    delivery: Delivery = Field(default_factory=Delivery)
    sfx: list[SfxCue] = Field(default_factory=list)
    # Semitone pitch shift applied to this line's clip at mix time. Used to vary
    # the two shared default voices across many unnamed one-off speakers.
    pitch_semitones: float = 0.0
    # When a line is split by the tag editor, the parts share an `origin` (the
    # source line id) and `origin_text` (the full original sentence) so that
    # clearing all tags can re-merge them back into the original line.
    origin: str | None = None
    origin_text: str = ""
    # Set once rendered.
    audio_path: str | None = None


class SpeakerLine(BaseModel):
    """One corrected speaker attribution for a dialogue line (by line index)."""

    index: int
    speaker_id: str


class SpeakerRefineResult(BaseModel):
    """Pass B output: corrected speaker_id per dialogue line index. Only the
    lines the model wants to change need appear; unlisted lines keep the
    heuristic guess."""

    lines: list[SpeakerLine] = Field(default_factory=list)


class Chapter(BaseModel):
    chapter_id: str
    number: int
    title: str
    text: str = ""               # raw prose (stored in analysis/, not the UI)
    # Short editor-facing blurb shown at the top of the chapter.
    summary: str = ""            # 1-2 sentences: what happens
    location: str = ""           # where the chapter plays (setting)
    lines: list[LineItem] = Field(default_factory=list)
    audio_path: str | None = None  # assembled chapter audio
    # When True the line plan was authored by a Claude agent (higher-quality
    # speaker attribution) and must NOT be overwritten by the heuristic planner.
    curated: bool = False
