"""Book metadata: parse author/title from the project title, tag chapter MP3s.

The project title comes from the source PDF name, conventionally
"Lastname, First - Title - Subtitle".
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_meta(project) -> dict:
    parts = [p.strip() for p in project.title.split(" - ") if p.strip()]
    author = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else (parts[0] if parts else project.title)
    subtitle = " - ".join(parts[2:]) if len(parts) > 2 else ""
    if "," in author:                       # "Hamilton, Peter F." -> "Peter F. Hamilton"
        last, first = (x.strip() for x in author.split(",", 1))
        author = f"{first} {last}".strip()
    return {"author": author, "title": title, "subtitle": subtitle}


def tag_chapter_mp3(path: str | Path, project, number: int, chapter_title: str) -> None:
    """Write audiobook ID3 tags onto a chapter MP3."""
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp3 import EasyMP3

    m = parse_meta(project)
    try:
        audio = EasyMP3(str(path))
    except ID3NoHeaderError:
        audio = EasyMP3()
        audio.filename = str(path)
    if audio.tags is None:
        audio.add_tags()
    audio["album"] = m["title"]
    audio["artist"] = m["author"]
    audio["albumartist"] = m["author"]
    audio["title"] = f"{number}. {chapter_title}"
    audio["tracknumber"] = str(number)
    audio["genre"] = "Audiobook"
    audio.save()
