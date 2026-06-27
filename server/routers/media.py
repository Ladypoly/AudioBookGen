"""Serve project media files (covers, portraits, audio) to the browser.

Read-only and path-traversal-safe: only files inside CONFIG.projects_root are
served. Audio clips, portraits and covers load directly via `/api/media/<rel>`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import CONFIG

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{rel_path:path}")
def media(rel_path: str) -> FileResponse:
    root = CONFIG.projects_root.resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target)
