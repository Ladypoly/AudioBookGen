"""Online research via DuckDuckGo (opt-in).

Lightweight HTML-endpoint search — no API key, no extra heavy deps. Returns
result snippets (title + text) which are fed, spoiler-filtered, into the style
bible and character enrichment passes. Breaks the local-only default, so it is
only called when the user enables web search for a run.
"""

from __future__ import annotations

import html
import logging
import re

import httpx

from app.core.config import CONFIG

logger = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AudioBookGen/1.0"}

_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.S)
_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text)).strip()


def search(query: str, max_results: int | None = None) -> list[dict[str, str]]:
    """Return [{title, snippet}] for a query, or [] on any failure."""
    max_results = max_results or CONFIG.extraction.web_results
    try:
        with httpx.Client(timeout=20.0, headers=_HEADERS, follow_redirects=True) as c:
            resp = c.post(_DDG_URL, data={"q": query})
            resp.raise_for_status()
        titles = [_clean(t) for t in _TITLE.findall(resp.text)]
        snippets = [_clean(s) for s in _SNIPPET.findall(resp.text)]
        out: list[dict[str, str]] = []
        for t, s in zip(titles, snippets):
            if s:
                out.append({"title": t, "snippet": s})
            if len(out) >= max_results:
                break
        return out
    except httpx.HTTPError as err:
        logger.warning("Web search failed for %r: %s", query, err)
        return []


def _block(results: list[dict[str, str]]) -> str:
    return "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)


def style_context(book_title: str) -> str:
    """Web context for the style bible: genre, setting, cover aesthetic."""
    results: list[dict[str, str]] = []
    for q in (
        f"{book_title} novel genre setting",
        f"{book_title} book cover art style",
    ):
        results += search(q, max_results=4)
    return _block(results)


def character_context(book_title: str, character_name: str) -> str:
    """Web context for one character's appearance/voice (spoiler-filtered later)."""
    results = search(f"{character_name} {book_title} character appearance description", 4)
    return _block(results)
