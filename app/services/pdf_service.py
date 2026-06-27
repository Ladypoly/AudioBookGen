"""Book text extraction + chunking.

Extracts plain text from a book file (PDF / EPUB / DOCX / TXT) and splits it
into overlapping chunks for the LLM map pass. OCR / header-footer cleanup land
later (PLAN section "Text import and cleanup details").

The module name is historical (PDF was the first format); `extract_text` and
`render_cover` now dispatch on the file extension.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # pymupdf

from app.core.config import CONFIG

logger = logging.getLogger(__name__)


def extract_text(src_path: str | Path) -> str:
    """Extract plain text from a book file, dispatching on its extension."""
    path = Path(src_path)
    if not path.exists():
        raise FileNotFoundError(f"Book file not found: {path}")
    ext = path.suffix.lower()
    if ext == ".epub":
        return _extract_epub(path)
    if ext in (".docx", ".doc"):
        return _extract_docx(path)
    if ext in (".txt", ".text", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    return _extract_pdf(path)            # default: PDF (also covers unknown text PDFs)


def _extract_pdf(path: Path) -> str:
    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def _extract_epub(path: Path) -> str:
    from ebooklib import ITEM_DOCUMENT, epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        parts.append(soup.get_text("\n"))
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


def render_cover(src_path: str | Path, out_path: str | Path, max_width: int = 480) -> bool:
    """Render/extract a cover PNG for the book. Best-effort.

    PDF -> first page; EPUB -> embedded cover image; TXT/DOCX -> no cover.
    """
    try:
        src = Path(src_path)
        if not src.exists():
            return False
        ext = src.suffix.lower()
        if ext == ".epub":
            return _cover_epub(src, out_path)
        if ext in (".txt", ".text", ".md", ".docx", ".doc"):
            return False
        return _cover_pdf(src, out_path, max_width)
    except Exception:  # noqa: BLE001
        logger.warning("cover render failed for %s", src_path, exc_info=True)
        return False


def _cover_pdf(src: Path, out_path: str | Path, max_width: int) -> bool:
    with fitz.open(src) as doc:
        if doc.page_count == 0:
            return False
        page = doc[0]
        zoom = max(0.5, max_width / max(1.0, page.rect.width))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
    return True


def _cover_epub(src: Path, out_path: str | Path) -> bool:
    from ebooklib import ITEM_COVER, ITEM_IMAGE, epub

    book = epub.read_epub(str(src))
    data: bytes | None = None
    # Prefer an explicit cover item; else the first image.
    for item in book.get_items_of_type(ITEM_COVER):
        data = item.get_content()
        break
    if data is None:
        for item in book.get_items_of_type(ITEM_IMAGE):
            name = (item.get_name() or "").lower()
            if "cover" in name:
                data = item.get_content()
                break
    if data is None:
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Normalise to PNG so the rest of the app can assume cover.png.
    try:
        import io
        from PIL import Image

        Image.open(io.BytesIO(data)).convert("RGB").save(out, "PNG")
    except Exception:  # noqa: BLE001 — PIL missing/odd image: write raw bytes
        out.write_bytes(data)
    return True


def _normalize(text: str) -> str:
    """Light cleanup: repair hyphenated line wraps, collapse blank runs."""
    # join words split across line breaks: "Hilf-\nreich" -> "Hilfreich"
    text = text.replace("-\n", "")
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        if not ln:
            blanks += 1
            if blanks <= 1:
                out.append("")
            continue
        blanks = 0
        out.append(ln)
    return "\n".join(out)


def chunk_text(
    text: str,
    chunk_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[str]:
    """Split text into overlapping character-window chunks.

    Tries to break on paragraph/sentence boundaries near the window edge so
    a chunk does not cut a sentence in half.
    """
    chunk_chars = chunk_chars or CONFIG.extraction.chunk_chars
    overlap_chars = overlap_chars or CONFIG.extraction.chunk_overlap_chars
    text = _normalize(text)
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_chars, n)
        if end < n:
            window = text[start:end]
            # prefer a paragraph break, then a sentence end, near the tail
            brk = window.rfind("\n\n")
            if brk < chunk_chars * 0.5:
                brk = max(window.rfind(". "), window.rfind("\n"))
            if brk > chunk_chars * 0.5:
                end = start + brk + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def load_chunks(pdf_path: str | Path) -> list[str]:
    """Convenience: extract + chunk in one call."""
    return chunk_text(extract_text(pdf_path))
