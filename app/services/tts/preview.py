"""Emotion-varied Higgs preview text.

Renders each configured segment with its own Higgs delivery (emotion/style) so
a single Hörprobe demonstrates the voice's emotional range.
"""

from __future__ import annotations

from app.core.config import CONFIG
from app.schemas.voice import Delivery, Emotion, Style
from app.services.tts import tag_builder


def build_emotional_preview() -> str:
    """Higgs-tagged preview text combining several emotions (pass as request
    text with delivery=None — it is already tagged)."""
    parts: list[str] = []
    for text, emo, sty in CONFIG.tts.preview_segments:
        delivery = Delivery(
            emotion=Emotion(emo) if emo else None,
            style=Style(sty) if sty else None,
        )
        parts.append(tag_builder.build_higgs_text(text, delivery))
    return " ".join(parts)
