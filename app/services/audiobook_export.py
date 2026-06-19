"""Export the finished audiobook as a clean folder: <dest>/<Title>/ with one
tagged MP3 per chapter (proper track names) + the cover.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from app.services import book_meta, chapter_service

logger = logging.getLogger(__name__)


def _safe(name: str) -> str:
    """Filesystem-safe name (Windows-illegal chars removed, trimmed)."""
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip().rstrip(".")
    return name or "Untitled"


def export_audiobook(project, dest_root: str | Path, on_step=None) -> Path:
    """Copy every rendered chapter into <dest_root>/<Title>/ with proper names,
    tags and an embedded cover. Returns the created folder."""
    meta = book_meta.parse_meta(project)
    title = meta["title"] or project.title
    out_dir = Path(dest_root) / _safe(title)
    out_dir.mkdir(parents=True, exist_ok=True)

    cover_src = project.root / "cover.png"
    if not cover_src.exists() and project.source_pdf:   # render it on demand
        try:
            from app.services import pdf_service
            pdf_service.render_cover(project.source_pdf, cover_src)
        except Exception:  # noqa: BLE001
            logger.debug("cover render failed", exc_info=True)
    cover_bytes = cover_src.read_bytes() if cover_src.exists() else None
    if cover_bytes:
        (out_dir / "cover.png").write_bytes(cover_bytes)

    index = chapter_service.load_index(project)
    n = 0
    for info in index:
        src = project.chapter_audio_dir / f"{info['chapter_id']}.mp3"
        if not src.exists():
            continue
        n += 1
        num = int(info.get("number", n))
        dst = out_dir / f"{num:02d} - {_safe(info['title'])}.mp3"
        shutil.copy2(src, dst)
        ch = chapter_service.load_chapter(project, info["chapter_id"])
        # tag_chapter_mp3 writes tags + lyrics + embedded cover per CONFIG.export
        book_meta.tag_chapter_mp3(dst, project, num, info["title"],
                                  lyrics=ch.text if ch else "")
        if on_step:
            on_step(n)
    logger.info("Exported %d chapters to %s", n, out_dir)
    return out_dir
