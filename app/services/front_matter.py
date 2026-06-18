"""Front matter: an intro chapter (ch00) read by the narrator.

Announces the title, author, an optional short author bio (web, opt-in) and the
table of contents. Built as a curated chapter so it renders like any other.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.schemas.script import Chapter, LineItem, LineType
from app.services import book_meta, research_service
from app.services.line_planner import NARRATOR_ID

logger = logging.getLogger(__name__)


class _Bio(BaseModel):
    bio: str


def author_bio(author: str, book_title: str = "", year_hint: str = "") -> str:
    """A short German author bio, written by gemma from web search results.

    Mentions what the author is known for and, if derivable, roughly how old
    they were when they wrote this book. Best-effort: "" if web/LLM unavailable.
    """
    if not author:
        return ""
    results = research_service.search(f"{author} Autor Biografie bekannt für geboren", 5)
    results += research_service.search(f"{book_title} {author} erschienen Jahr", 2)
    results += research_service.search(f"{author} interessante Fakten Kuriositäten Trivia", 2)
    # A writing-style quirk is often the best, most characteristic fun fact
    # (e.g. doorstopper length, gratuitous sex scenes, info dumps, cliffhangers).
    results += research_service.search(f"{author} Schreibstil Eigenheit Kritik berüchtigt", 2)
    results += research_service.search(f"{author} writing style criticism known notorious for", 3)
    if not results:
        return ""
    ctx = "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)
    prompt = (
        "Du schreibst eine kurze deutsche Autoren-Info für die Einleitung eines "
        "Hörbuchs. 3 bis 4 ganze Sätze. Nenne, wofür der Autor bekannt ist (Genre, "
        "bekannteste Werke). Wenn aus den Quellen ableitbar, erwähne grob, wie alt "
        "der Autor beim Schreiben dieses Buches war. Schließe mit EINEM lockeren, "
        "augenzwinkernden Fakt. AM BESTEN eine charakteristische Eigenheit seines "
        "SCHREIBSTILS, für die er bekannt oder berüchtigt ist (z.B. extrem lange "
        "Romane, ausschweifende Erotik, ausufernde technische Erklärungen, fiese "
        "Cliffhanger) — falls die Quellen so etwas hergeben; sonst ein anderer "
        "lockerer Fakt (Hobby, Werdegang, Kuriosität). Formuliere die Eigenheit "
        "geistreich und wohlwollend, nicht abwertend. NUR Fakten aus den Quellen, "
        "nichts erfinden. Keine Anrede, kein Markdown, keine Quellenangaben.\n"
        f"Autor: {author}\nBuch: {book_title}{year_hint}\nQuellen:\n{ctx}\n"
        'Gib JSON {"bio": "..."} zurück.'
    )
    try:
        from app.services import ollama_service
        return ollama_service.generate_json(prompt, _Bio).bio.strip()
    except Exception:  # noqa: BLE001
        logger.warning("author bio unavailable", exc_info=True)
        return ""


def build(project, infos: list[dict]) -> Chapter:
    """Return the ch00 front-matter chapter (narrator only)."""
    m = book_meta.parse_meta(project)
    texts: list[str] = [f"{m['title']}."]
    if m["subtitle"]:
        texts.append(f"{m['subtitle']}.")
    if m["author"]:
        texts.append(f"Von {m['author']}.")
    bio = author_bio(m["author"], m["title"])
    if bio:
        texts.append(bio)

    lines = [
        LineItem(line_id=f"ch00_l{i:04d}", chapter_id="ch00", index=i,
                 type=LineType.narration, speaker_id=NARRATOR_ID, text=t)
        for i, t in enumerate(texts, start=1)
    ]
    return Chapter(chapter_id="ch00", number=0, title="Vorwort",
                   text="", lines=lines, curated=True)
