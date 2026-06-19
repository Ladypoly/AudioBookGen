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


def tag_chapter_mp3(path: str | Path, project, number: int, chapter_title: str,
                    lyrics: str = "") -> None:
    """Write audiobook ID3 tags onto a chapter MP3.

    Which tags are written (plus full-text lyrics + embedded cover) is governed
    by CONFIG.export, so the user controls exactly what lands in the metadata.
    """
    from mutagen.id3 import (
        APIC, COMM, ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK, USLT,
        ID3NoHeaderError,
    )

    from app.core.config import CONFIG
    exp = CONFIG.export
    m = parse_meta(project)
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()

    if exp.tag_title:
        tags.setall("TIT2", [TIT2(encoding=3, text=f"{number}. {chapter_title}")])
    if exp.tag_album:
        tags.setall("TALB", [TALB(encoding=3, text=m["title"])])
    if exp.tag_artist:
        tags.setall("TPE1", [TPE1(encoding=3, text=m["author"])])
    if exp.tag_albumartist:
        tags.setall("TPE2", [TPE2(encoding=3, text=m["author"])])
    if exp.tag_track:
        tags.setall("TRCK", [TRCK(encoding=3, text=str(number))])
    if exp.tag_genre:
        tags.setall("TCON", [TCON(encoding=3, text=exp.genre)])
    if exp.tag_comment and exp.comment:
        tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=exp.comment)])
    if exp.tag_lyrics and lyrics:                 # full chapter prose
        tags.setall("USLT", [USLT(encoding=3, lang="ger", desc="", text=lyrics)])
    if exp.embed_cover:
        cover = project.root / "cover.png"
        if cover.exists():
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime="image/png", type=3,
                          desc="Cover", data=cover.read_bytes()))
    tags.save(str(path))
