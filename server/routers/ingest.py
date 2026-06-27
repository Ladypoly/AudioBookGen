"""New-AudioDrama ingestion flow.

Three steps back the dialog:
  1. inspect  — stage the chosen file, extract title/author + a cover preview.
  2. cover    — (optional) replace the staged cover with a user image.
  3. create   — build the project with confirmed metadata and start extraction.

Staging lives under <projects_root>/.staging/<token>/ so the cover preview can
be served via /api/media before the project exists.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import CONFIG
from app.services import book_meta, pdf_service, project_service
from server.extraction import run_extraction
from server.jobs import MANAGER

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

SUPPORTED = {".pdf", ".epub", ".txt", ".docx", ".doc", ".md"}


def _staging() -> Path:
    d = CONFIG.projects_root / ".staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _media_url(p: Path) -> str:
    rel = p.resolve().relative_to(CONFIG.projects_root.resolve())
    return "/api/media/" + "/".join(rel.parts)


def _inspect_staged(token: str, source: Path) -> dict:
    meta = book_meta.extract_file_metadata(source)
    stage = source.parent
    cover = stage / "cover.png"
    pdf_service.render_cover(str(source), cover)
    (stage / "meta.json").write_text(
        json.dumps({"source": str(source), **meta}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {
        "token": token,
        "title": meta["title"],
        "author": meta["author"],
        "subtitle": meta["subtitle"],
        "cover": _media_url(cover) if cover.exists() else None,
        "filename": source.name,
    }


class InspectPathBody(BaseModel):
    path: str


@router.post("/inspect-path")
def inspect_path(body: InspectPathBody) -> dict:
    """Electron path: stage a file already on disk (native dialog gave a path)."""
    src = Path(body.path)
    if not src.exists():
        raise HTTPException(404, f"File not found: {src}")
    if src.suffix.lower() not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type: {src.suffix}")
    token = uuid.uuid4().hex[:12]
    stage = _staging() / token
    stage.mkdir(parents=True, exist_ok=True)
    staged = stage / src.name
    shutil.copy2(src, staged)
    return _inspect_staged(token, staged)


@router.post("/inspect")
async def inspect_upload(file: UploadFile = File(...)) -> dict:
    """Browser path: stage an uploaded file."""
    name = file.filename or "book"
    if Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type: {name}")
    token = uuid.uuid4().hex[:12]
    stage = _staging() / token
    stage.mkdir(parents=True, exist_ok=True)
    staged = stage / name
    with staged.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return _inspect_staged(token, staged)


@router.post("/{token}/cover")
async def replace_cover(token: str, file: UploadFile = File(...)) -> dict:
    """Replace the staged cover with a user-supplied image."""
    stage = _staging() / token
    if not stage.exists():
        raise HTTPException(404, "Unknown ingest token")
    cover = stage / "cover.png"
    try:
        import io
        from PIL import Image
        Image.open(io.BytesIO(await file.read())).convert("RGB").save(cover, "PNG")
    except Exception:
        await file.seek(0)
        with cover.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    return {"cover": _media_url(cover)}


class CreateBody(BaseModel):
    token: str
    title: str
    author: str = ""
    subtitle: str = ""


@router.post("/create")
def create(body: CreateBody) -> dict:
    """Create the project from confirmed metadata and start extraction."""
    stage = _staging() / body.token
    meta_file = stage / "meta.json"
    if not meta_file.exists():
        raise HTTPException(404, "Unknown ingest token")
    info = json.loads(meta_file.read_text(encoding="utf-8"))
    source = Path(info["source"])
    cover = stage / "cover.png"

    project = project_service.create_project(
        source, title=body.title, author=body.author, subtitle=body.subtitle,
        cover_src=str(cover) if cover.exists() else None,
    )
    job = MANAGER.submit(
        "extraction", f"Extracting · {body.title}",
        lambda ctx: run_extraction(ctx, project),
        meta={"project_id": project.root.name},
    )
    # best-effort: clear staging now that the source is copied into the project
    shutil.rmtree(stage, ignore_errors=True)
    return {"project_id": project.root.name, "job_id": job.id}
