"""Projects: list, open, and report the active project.

Project identity for the API is the on-disk folder name (slug) under
CONFIG.projects_root. Covers/portraits/audio are referenced as `/api/media/...`
URLs (served by the media router) so the browser can load them directly.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import CONFIG
from app.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _media_url(abs_path: str | Path) -> str | None:
    """Map an absolute path under projects_root to a /api/media/<rel> URL.
    Appends the file mtime so an edited cover isn't served stale from cache."""
    if not abs_path:
        return None
    p = Path(abs_path)
    try:
        rel = p.resolve().relative_to(CONFIG.projects_root.resolve())
    except (ValueError, OSError):
        return None
    url = "/api/media/" + "/".join(rel.parts)
    try:
        url += f"?v={int(p.stat().st_mtime)}"
    except OSError:
        pass
    return url


def _summary(info: dict) -> dict:
    root = Path(info["root"])
    return {
        "id": root.name,
        "title": info.get("title", root.name),
        "author": info.get("author", ""),
        "character_count": info.get("character_count", 0),
        "cover": _media_url(info.get("cover", "")),
    }


@router.get("")
def list_projects() -> list[dict]:
    return [_summary(p) for p in project_service.list_projects()]


@router.get("/active")
def active() -> dict:
    proj = project_service.active()
    if proj is None:
        return {"active": None}
    return {"active": {"id": proj.root.name, "title": proj.title}}


@router.post("/{project_id}/open")
def open_project(project_id: str) -> dict:
    try:
        proj = project_service.activate(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"id": proj.root.name, "title": proj.title, "author": proj.author}


class MetaBody(BaseModel):
    title: str | None = None
    author: str | None = None
    subtitle: str | None = None


def _summary_for(project_id: str) -> dict:
    for info in project_service.list_projects():
        if Path(info["root"]).name == project_id:
            return _summary(info)
    raise HTTPException(404, f"Project not found: {project_id}")


@router.put("/{project_id}")
def update_project(project_id: str, body: MetaBody) -> dict:
    """Edit title / author / subtitle (the folder id stays the same)."""
    try:
        project_service.update_meta(
            project_id, title=body.title, author=body.author, subtitle=body.subtitle)
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")
    return _summary_for(project_id)


@router.post("/{project_id}/cover")
async def set_cover(project_id: str, file: UploadFile = File(...)) -> dict:
    """Replace the project cover from an uploaded image."""
    import tempfile

    suffix = Path(file.filename or "cover.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        project_service.set_cover(project_id, tmp_path)
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return _summary_for(project_id)


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict:
    try:
        project_service.delete_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")
    return {"ok": True}


@router.post("/{project_id}/duplicate")
def duplicate_project(project_id: str) -> dict:
    try:
        new_id = project_service.duplicate_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project not found: {project_id}")
    return _summary_for(new_id)
