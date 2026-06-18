"""Preview Hörprobe text.

The preview doubles as the clone reference for the audiobook, so it must be a
clean, neutral German sample: emotion/style tags distort the timbre and make a
poor reference. We keep the varied sentences (so a human can still judge the
voice) but render them as PLAIN text — no Higgs emotion/style tags.
"""

from __future__ import annotations

from app.core.config import CONFIG


def build_emotional_preview() -> str:
    """Plain German preview text — the sentences from preview_segments without
    any emotion/style tags (those would distort the clone reference)."""
    return " ".join(text for text, _emo, _sty in CONFIG.tts.preview_segments)
