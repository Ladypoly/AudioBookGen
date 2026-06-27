"""Chapter timeline: the WYSIWYG edit model.

A timeline places every audio element on an absolute ms grid across four lanes
(narrator / characters / ambience / sfx). It is derived from a rendered chapter
(real clip durations + the same layout as the procedural mix), then edited in
the timeline editor. The authoritative export is built from this model, so what
the editor shows is exactly what renders.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Lane names. Editor stacks them bottom-to-top: narrator, speaker(characters),
# ambience, sfx, music.
LANE_NARRATOR = "narrator"
LANE_CHARACTERS = "characters"
LANE_AMBIENCE = "ambience"
LANE_SFX = "sfx"
LANE_MUSIC = "music"
LANES = [LANE_NARRATOR, LANE_CHARACTERS, LANE_AMBIENCE, LANE_SFX, LANE_MUSIC]


class TimelineSegment(BaseModel):
    id: str
    kind: str                         # "voice" | "ambience" | "sfx"
    lane: str
    start_ms: float
    duration_ms: float
    gain_db: float = 0.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0

    # --- source references ---
    line_id: str | None = None        # voice: the LineItem this came from
    speaker_id: str | None = None
    text: str = ""                    # voice: the spoken text (shown on the clip)
    audio_path: str | None = None     # resolved clip path (line clip / ambience / sfx file)
    prompt: str = ""                  # sfx / ambience generation prompt
    pitch_semitones: float = 0.0
    custom: bool = False              # user-supplied clip (never regenerated)
    # True when the duration is an estimate (clip not rendered yet).
    estimated: bool = False
    # True once the user has moved/edited this segment (kept on re-derive).
    edited: bool = False


class Timeline(BaseModel):
    chapter_id: str
    version: int = 1
    duration_ms: float = 0.0
    lanes: list[str] = Field(default_factory=lambda: list(LANES))
    segments: list[TimelineSegment] = Field(default_factory=list)
