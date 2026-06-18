"""PDF text extraction + chunking.

First-slice scope: extract plain text from a (text-based) PDF and split it
into overlapping chunks for the LLM map pass. OCR / header-footer cleanup
land later (PLAN section "Text import and cleanup details").
"""

from __future__ import annotations

from pathlib import Path

import fitz  # pymupdf

from app.core.config import CONFIG


def extract_text(pdf_path: str | Path) -> str:
    """Extract concatenated page text from a PDF."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def render_cover(pdf_path: str | Path, out_path: str | Path, max_width: int = 480) -> bool:
    """Render the PDF's first page to a PNG (the book cover). Best-effort."""
    try:
        src = Path(pdf_path)
        if not src.exists():
            return False
        with fitz.open(src) as doc:
            if doc.page_count == 0:
                return False
            page = doc[0]
            zoom = max(0.5, max_width / max(1.0, page.rect.width))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(out_path))
        return True
    except Exception:  # noqa: BLE001
        return False


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
