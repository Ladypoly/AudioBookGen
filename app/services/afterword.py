"""Afterword: a closing chapter recommending similar books, read by the narrator.

Recommendations are found via web search and written into clean German prose by
gemma. Best-effort: returns None if web/LLM are unavailable.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.schemas.script import Chapter, LineItem, LineType
from app.services import book_meta, line_planner, project_service, research_service
from app.services.line_planner import NARRATOR_ID

logger = logging.getLogger(__name__)


class _Afterword(BaseModel):
    text: str


def build(project, number: int) -> Chapter | None:
    """Return a 'Nachwort' chapter with book recommendations, or None."""
    m = book_meta.parse_meta(project)
    bible = project_service.load_style_bible(project)
    genre = getattr(bible, "genre", "") if bible else ""

    results = research_service.search(
        f"Bücher ähnlich wie {m['title']} {m['author']} Empfehlungen", 4)
    if genre:
        results += research_service.search(
            f"{genre} Buchempfehlungen ähnlich {m['author']}", 3)
    if not results:
        return None
    ctx = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)

    prompt = (
        "Du schreibst ein kurzes deutsches Nachwort für ein Hörbuch. Empfiehl dem "
        "Hörer 2 bis 3 ähnliche Bücher mit je einem kurzen Satz, worum es geht und "
        "warum es passt. Beginne sinngemäß mit \"Wenn Ihnen dieses Buch gefallen "
        'hat, könnten Ihnen auch diese gefallen". Natürliche, gesprochene Sätze.\n'
        "WICHTIG: Empfiehl AUSSCHLIESSLICH Bücher, deren Titel UND Autor wörtlich "
        "in den Quellen unten vorkommen. Erfinde NIEMALS Titel. Bist du unsicher, "
        "empfiehl lieber nur ein oder zwei Bücher. Kein Markdown, keine Links.\n"
        f"Dieses Buch: {m['title']} von {m['author']} (Genre: {genre or 'unbekannt'}).\n"
        f"Quellen:\n{ctx}\n"
        'Gib JSON {"text": "..."} zurück.'
    )
    try:
        from app.services import ollama_service
        text = ollama_service.generate_json(prompt, _Afterword).text.strip()
    except Exception:  # noqa: BLE001
        logger.warning("afterword unavailable", exc_info=True)
        return None
    if not text:
        return None

    units = line_planner.to_units(text)
    lines = [
        LineItem(line_id=f"ch{number:02d}_l{i:04d}", chapter_id=f"ch{number:02d}",
                 index=i, type=LineType.narration, speaker_id=NARRATOR_ID, text=u)
        for i, u in enumerate(units, start=1)
    ]
    return Chapter(chapter_id=f"ch{number:02d}", number=number, title="Nachwort",
                   text="", lines=lines, curated=True)
