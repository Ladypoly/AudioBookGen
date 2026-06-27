"""Book metadata: parse author/title from the project title, tag chapter MP3s.

The project title comes from the source PDF name, conventionally
"Lastname, First - Title - Subtitle".
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_title_string(raw: str) -> dict:
    """Split a "Lastname, First - Title - Subtitle" string into parts."""
    parts = [p.strip() for p in raw.split(" - ") if p.strip()]
    author = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else (parts[0] if parts else raw)
    subtitle = " - ".join(parts[2:]) if len(parts) > 2 else ""
    if "," in author:                       # "Hamilton, Peter F." -> "Peter F. Hamilton"
        last, first = (x.strip() for x in author.split(",", 1))
        author = f"{first} {last}".strip()
    return {"author": author, "title": title, "subtitle": subtitle}


def parse_meta(project) -> dict:
    """Author/title/subtitle for a project — prefers stored metadata, falls
    back to parsing the (filename-derived) project title."""
    stored = {}
    try:
        import json
        data = json.loads((project.root / "project.json").read_text(encoding="utf-8"))
        stored = {k: data.get(k, "") for k in ("author", "title", "subtitle")}
    except Exception:  # noqa: BLE001
        pass
    base = parse_title_string(project.title)
    return {
        "author": stored.get("author") or base["author"],
        "title": stored.get("title") or base["title"],
        "subtitle": stored.get("subtitle") or base["subtitle"],
    }


def extract_file_metadata(src_path: str | Path) -> dict:
    """Pull title/author/subtitle + (optional) cover from a book file.

    Returns {title, author, subtitle, has_cover}. Embedded metadata wins;
    missing fields fall back to parsing the filename. `has_cover` indicates a
    cover image could be extracted (the caller renders it separately).
    """
    path = Path(src_path)
    ext = path.suffix.lower()
    meta = {"title": "", "author": "", "subtitle": ""}
    try:
        if ext == ".pdf":
            meta.update(_meta_pdf(path))
        elif ext == ".epub":
            meta.update(_meta_epub(path))
        elif ext in (".docx", ".doc"):
            meta.update(_meta_docx(path))
    except Exception:  # noqa: BLE001
        logger.warning("metadata extraction failed for %s", path, exc_info=True)

    fallback = parse_title_string(path.stem)
    title = meta.get("title") or fallback["title"]
    author = meta.get("author") or fallback["author"]
    subtitle = meta.get("subtitle") or fallback["subtitle"]
    from app.services import pdf_service
    has_cover = ext in (".pdf", ".epub") and _probe_cover(path, pdf_service)
    return {"title": title, "author": author, "subtitle": subtitle, "has_cover": has_cover}


def _probe_cover(path: Path, pdf_service) -> bool:
    if path.suffix.lower() == ".pdf":
        return True   # PDFs always render a first-page cover
    # EPUB: report whether an embedded cover exists without writing it twice.
    try:
        from ebooklib import ITEM_COVER, ITEM_IMAGE, epub
        book = epub.read_epub(str(path))
        if any(True for _ in book.get_items_of_type(ITEM_COVER)):
            return True
        return any("cover" in (i.get_name() or "").lower()
                   for i in book.get_items_of_type(ITEM_IMAGE))
    except Exception:  # noqa: BLE001
        return False


def _meta_pdf(path: Path) -> dict:
    import fitz
    with fitz.open(path) as doc:
        md = doc.metadata or {}
    return {"title": (md.get("title") or "").strip(),
            "author": (md.get("author") or "").strip()}


def _meta_epub(path: Path) -> dict:
    from ebooklib import epub
    book = epub.read_epub(str(path))
    title = book.get_metadata("DC", "title")
    author = book.get_metadata("DC", "creator")
    return {"title": (title[0][0].strip() if title else ""),
            "author": (author[0][0].strip() if author else "")}


def _meta_docx(path: Path) -> dict:
    import docx
    cp = docx.Document(str(path)).core_properties
    return {"title": (cp.title or "").strip(), "author": (cp.author or "").strip()}


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
