"""Short editor-facing chapter brief: a 1-2 sentence summary + the setting.

Used for the header shown above a chapter in the editor. One small LLM call per
chapter, cached on the Chapter (summary/location).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.services import ollama_service

logger = logging.getLogger(__name__)


class ChapterBrief(BaseModel):
    summary: str = ""
    location: str = ""


_PROMPT = """You write a tiny editor note for one audiobook chapter.

Return JSON with:
- "summary": ONE short sentence (max 22 words) describing what happens in this chapter.
- "location": the place/setting where it happens (a few words, e.g. "a London office", "an airfield at an airshow"). If unclear, give your best guess from the text.

Keep it factual and concise. Chapter title: {title}

Chapter text (may be truncated):
{text}
"""


def generate_brief(chapter) -> ChapterBrief:
    text = (chapter.text or "")[:6000]
    if not text.strip():
        # Fall back to the dialogue/narration if raw prose isn't stored.
        text = " ".join(l.text for l in chapter.lines)[:6000]
    prompt = _PROMPT.format(title=chapter.title, text=text)
    # Let LLM errors propagate so the job fails visibly (e.g. a bad API key)
    # instead of silently producing an empty summary.
    return ollama_service.generate_json(prompt, ChapterBrief, num_predict=200)
