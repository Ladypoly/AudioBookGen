"""Series Style Bible generation (spoiler-safe).

One Ollama call derives a single illustration style for the whole book from its
title + a short atmosphere sample. Applied identically to every portrait/cover.
"""

from __future__ import annotations

import logging

from app.core import prompts
from app.schemas.style import StyleBible
from app.services import ollama_service

logger = logging.getLogger(__name__)

# Sample length fed to the style pass — enough for tone, small enough to be fast.
_SAMPLE_CHARS = 3000


def generate_style_bible(
    book_title: str, sample_text: str, web_context: str = ""
) -> StyleBible:
    prompt = prompts.render(
        "style_bible_prompt",
        book_title=book_title,
        sample_text=sample_text[:_SAMPLE_CHARS],
        web_context=web_context[:2000],
    )
    try:
        bible = ollama_service.generate_json(prompt, StyleBible)
        logger.info("Style bible: %s / %s", bible.genre, bible.art_style)
        return bible
    except ollama_service.OllamaError as err:
        logger.error("Style bible generation failed, using default: %s", err)
        return StyleBible()
