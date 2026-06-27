"""Per-book project storage.

Each imported book gets its own folder under projects_root holding everything:
the source reference, the character registry, the style bible, and rendered
portraits. Re-importing the same book reopens the existing folder (so results
and portraits survive restarts). Mirrors the PLAN on-disk layout.

    projects/<book-slug>/
      project.json          metadata (title, source path)
      registry/characters.json
      style/style_bible.json
      renders/portraits/<character_id>.png
      source/               (where the book reference lives)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import CONFIG
from app.schemas.characters import Character
from app.schemas.style import StyleBible

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s[:80] or "book").strip("-")


@dataclass
class Project:
    title: str
    root: Path
    source_pdf: str          # path to the source book file (any supported format)
    author: str = ""

    @property
    def registry_file(self) -> Path:
        return self.root / "registry" / "characters.json"

    @property
    def style_file(self) -> Path:
        return self.root / "style" / "style_bible.json"

    @property
    def portraits_dir(self) -> Path:
        return self.root / "renders" / "portraits"

    @property
    def voices_dir(self) -> Path:
        return self.root / "voices"

    @property
    def line_audio_dir(self) -> Path:
        return self.root / "renders" / "tts"

    @property
    def chapter_audio_dir(self) -> Path:
        return self.root / "mixes" / "chapters"

    @property
    def ambience_dir(self) -> Path:
        return self.root / "mixes" / "ambience"

    def ambience_path(self, chapter_id: str) -> Path:
        return self.ambience_dir / f"{chapter_id}.mp3"

    @property
    def music_dir(self) -> Path:
        return self.root / "mixes" / "music"

    def music_path(self, chapter_id: str) -> Path:
        return self.music_dir / f"{chapter_id}.mp3"

    @property
    def sfx_dir(self) -> Path:
        return self.root / "mixes" / "sfx"

    def sfx_clip_path(self, cue) -> Path:
        """Content-addressed SFX clip path (shared across chapters)."""
        import hashlib
        h = hashlib.md5(f"{cue.prompt}|{cue.length_s}".encode()).hexdigest()[:16]
        return self.sfx_dir / f"{h}.mp3"

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    def portrait_path(self, character: Character) -> Path:
        return self.portraits_dir / f"{character.character_id}.png"

    def voice_sample_path(self, character_id: str, suffix: str = ".mp3") -> Path:
        """Qwen-designed timbre reference for a character."""
        return self.voices_dir / f"{character_id}{suffix}"

    def preview_path(self, character_id: str) -> Path:
        """Cached Higgs German Hörprobe (reused instead of re-rendering)."""
        return self.voices_dir / f"{character_id}_preview.mp3"


# Module-global active project so render services can find the right folder.
_active: Project | None = None


def active() -> Project | None:
    return _active


def set_active(project: Project | None) -> None:
    global _active
    _active = project


def list_projects() -> list[dict]:
    """Summaries of all stored projects for the dashboard."""
    root = CONFIG.projects_root
    if not root.exists():
        return []
    out: list[dict] = []
    for meta in sorted(root.glob("*/project.json")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reg = meta.parent / "registry" / "characters.json"
        count = 0
        if reg.exists():
            try:
                count = len(json.loads(reg.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                count = 0
        cover = meta.parent / "cover.png"
        src_pdf = data.get("source_file") or data.get("source_pdf", "")
        if not cover.exists() and src_pdf:
            from app.services import pdf_service
            pdf_service.render_cover(src_pdf, cover)   # cached on first view
        out.append({
            "title": data.get("title", meta.parent.name),
            "author": data.get("author", ""),
            "source_pdf": src_pdf,
            "root": str(meta.parent),
            "character_count": count,
            "cover": str(cover) if cover.exists() else "",
        })
    return out


def open_project(pdf_path: str | Path) -> Project:
    """Create (or reopen) the project folder for a book and make it active."""
    global _active
    pdf = Path(pdf_path)
    title = pdf.stem
    root = CONFIG.projects_root / _slug(title)
    for sub in ("registry", "style", "renders/portraits", "source", "analysis"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    meta = root / "project.json"
    author = ""
    if not meta.exists():
        meta.write_text(
            json.dumps({"title": title, "source_file": str(pdf)}, indent=2),
            encoding="utf-8",
        )
    else:                                    # reopen: carry stored title/author
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            title = data.get("title", title)
            author = data.get("author", "")
        except (OSError, json.JSONDecodeError):
            pass
    _active = Project(title=title, root=root, source_pdf=str(pdf), author=author)
    logger.info("Project active: %s", root)
    return _active


def project_id_for(title: str) -> str:
    """The folder name (slug) a project with this title would use."""
    return _slug(title)


def activate(project_id: str) -> Project:
    """Make an existing project active by its folder id (no slug re-derivation).

    Unlike open_project (which derives the folder from a source path), this opens
    the exact folder, so projects whose title-slug differs from the source
    filename are reopened correctly.
    """
    global _active
    root = CONFIG.projects_root / project_id
    meta = root / "project.json"
    if not meta.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    data = json.loads(meta.read_text(encoding="utf-8"))
    _active = Project(
        title=data.get("title", project_id),
        root=root,
        source_pdf=data.get("source_file") or data.get("source_pdf", ""),
        author=data.get("author", ""),
    )
    logger.info("Project active: %s", root)
    return _active


def create_project(src_path: str | Path, title: str, author: str = "",
                   subtitle: str = "", cover_src: str | Path | None = None) -> Project:
    """Create a project from a chosen book file with user-confirmed metadata.

    Copies the source into source/, writes project.json (title/author/subtitle/
    source_file), and sets cover.png from `cover_src` (a user-supplied image) or
    by rendering/extracting the book's own cover. Makes the project active.
    """
    global _active
    import shutil

    src = Path(src_path)
    slug = _slug(title or src.stem)
    root = CONFIG.projects_root / slug
    for sub in ("registry", "style", "renders/portraits", "source", "analysis"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    # keep the original next to the project so re-detect works after restarts
    src_dst = root / "source" / src.name
    if src.exists() and not src_dst.exists():
        shutil.copy2(src, src_dst)

    (root / "project.json").write_text(
        json.dumps({
            "title": title or src.stem,
            "author": author,
            "subtitle": subtitle,
            "source_file": str(src_dst if src_dst.exists() else src),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cover = root / "cover.png"
    if cover_src:
        try:
            from PIL import Image
            Image.open(cover_src).convert("RGB").save(cover, "PNG")
        except Exception:  # noqa: BLE001
            shutil.copy2(cover_src, cover)
    elif not cover.exists():
        from app.services import pdf_service
        pdf_service.render_cover(str(src_dst if src_dst.exists() else src), cover)

    _active = Project(title=title or src.stem, root=root,
                      source_pdf=str(src_dst if src_dst.exists() else src), author=author)
    logger.info("Project created: %s", root)
    return _active


def update_meta(project_id: str, *, title: str | None = None,
                author: str | None = None, subtitle: str | None = None) -> dict:
    """Edit project.json fields (the folder id / slug stays stable so media URLs
    and references don't break). Returns the updated metadata."""
    root = CONFIG.projects_root / project_id
    meta = root / "project.json"
    if not meta.exists():
        raise FileNotFoundError(project_id)
    data = json.loads(meta.read_text(encoding="utf-8"))
    if title is not None:
        data["title"] = title
    if author is not None:
        data["author"] = author
    if subtitle is not None:
        data["subtitle"] = subtitle
    meta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if _active is not None and _active.root.name == project_id:   # keep active in sync
        _active.title = data.get("title", _active.title)
        _active.author = data.get("author", _active.author)
    return data


def set_cover(project_id: str, image_src: str | Path) -> Path:
    """Replace a project's cover.png from a user-supplied image."""
    import shutil

    root = CONFIG.projects_root / project_id
    if not (root / "project.json").exists():
        raise FileNotFoundError(project_id)
    cover = root / "cover.png"
    try:
        from PIL import Image
        Image.open(image_src).convert("RGB").save(cover, "PNG")
    except Exception:  # noqa: BLE001
        shutil.copy2(image_src, cover)
    return cover


def delete_project(project_id: str) -> None:
    """Permanently remove a project folder. Clears it as active if needed."""
    import shutil

    root = CONFIG.projects_root / project_id
    if not root.exists():
        raise FileNotFoundError(project_id)
    if _active is not None and _active.root.name == project_id:
        set_active(None)
    shutil.rmtree(root, ignore_errors=True)


def duplicate_project(project_id: str) -> str:
    """Copy a project folder to a new unique slug (title gets a "(copy)" suffix).
    Returns the new project id."""
    import shutil

    root = CONFIG.projects_root / project_id
    meta_path = root / "project.json"
    if not meta_path.exists():
        raise FileNotFoundError(project_id)
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    base = data.get("title", project_id)
    title = f"{base} (copy)"
    slug = _slug(title)
    n = 2
    while (CONFIG.projects_root / slug).exists():
        title = f"{base} (copy {n})"
        slug = _slug(title)
        n += 1
    dst = CONFIG.projects_root / slug
    shutil.copytree(root, dst)
    data["title"] = title
    (dst / "project.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return slug


def import_character_voice(project: Project, character_id: str, src_audio: str | Path) -> str:
    """Copy a voice sample into the project's voices/ folder for a character.
    Returns the destination path (stored on Character.voice_sample)."""
    import shutil

    src = Path(src_audio)
    if not src.exists():
        raise FileNotFoundError(src)
    project.voices_dir.mkdir(parents=True, exist_ok=True)
    dst = project.voices_dir / f"{character_id}{src.suffix.lower()}"
    if src.resolve() == dst.resolve():
        return str(dst)                       # already imported — nothing to do
    shutil.copy2(src, dst)
    logger.info("Voice for %s -> %s", character_id, dst)
    return str(dst)


def save_source(project: Project, pdf_path: str | Path) -> None:
    """Copy the source PDF into the project's source/ folder."""
    import shutil

    src = Path(pdf_path)
    dst = project.source_dir / src.name
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)


def save_analysis(project, mentions, grouped, characters) -> None:
    """Persist intermediate analysis (raw mentions, grouped candidates, final
    registry) into analysis/ — useful for QC, re-merge, and reproducibility."""
    a = project.analysis_dir
    a.mkdir(parents=True, exist_ok=True)
    (a / "mentions.json").write_text(
        json.dumps([m.model_dump() for m in mentions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (a / "grouped.json").write_text(
        json.dumps([g.model_dump() for g in grouped], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (a / "registry.json").write_text(
        json.dumps([c.model_dump() for c in characters], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- characters --------------------------------------------------------------


def save_characters(project: Project, characters: list[Character]) -> None:
    data = [c.model_dump() for c in characters]
    project.registry_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_characters(project: Project) -> list[Character]:
    if not project.registry_file.exists():
        return []
    raw = json.loads(project.registry_file.read_text(encoding="utf-8"))
    return [Character.model_validate(d) for d in raw]


# --- style bible -------------------------------------------------------------


def save_style_bible(project: Project, bible: StyleBible) -> None:
    project.style_file.write_text(
        bible.model_dump_json(indent=2), encoding="utf-8"
    )


def load_style_bible(project: Project) -> StyleBible | None:
    if not project.style_file.exists():
        return None
    return StyleBible.model_validate_json(project.style_file.read_text(encoding="utf-8"))
