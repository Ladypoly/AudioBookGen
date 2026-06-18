"""Prompt-file loader.

Prompts live as versioned .txt files in prompts/ (never embedded in code).
Leading lines beginning with '#' are treated as metadata/comments and stripped
from the active prompt body.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import CONFIG


def _strip_comment_header(text: str) -> str:
    lines = text.splitlines()
    body: list[str] = []
    in_header = True
    for line in lines:
        if in_header and line.startswith("#"):
            continue
        in_header = False
        body.append(line)
    return "\n".join(body).strip()


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a prompt body by file name (with or without .txt suffix)."""
    fname = name if name.endswith(".txt") else f"{name}.txt"
    path: Path = CONFIG.prompts_dir / fname
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return _strip_comment_header(path.read_text(encoding="utf-8"))


def render(name: str, **kwargs: str) -> str:
    """Load a prompt and substitute {placeholder} fields.

    Uses str.replace (not str.format) so literal JSON braces in the prompt
    body are left untouched.
    """
    body = load_prompt(name)
    for key, value in kwargs.items():
        body = body.replace("{" + key + "}", value)
    return body
