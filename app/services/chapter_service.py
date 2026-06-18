"""Chapter detection + persistence.

Splits the cleaned book text into chapters on numbered headings
("1. Magische Erinnerungen"). Chapters + their line plans live under the
project's analysis/chapters/ folder.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.schemas.script import Chapter, LineItem, LineType

logger = logging.getLogger(__name__)


def ingest_agent_plan(project, chapter_id: str, agent_lines: list[dict],
                      valid_speaker_ids: set[str]) -> Chapter | None:
    """Turn an agent-authored line list into a curated chapter plan.

    Each agent line is {type, speaker, text, emotion?, style?, prosody?,
    nonverbal?, sfx?}. `sfx` is a list of context-specific cues
    {prompt, placement, length_s?, gain_db?} (or a plain English string).
    Unknown speakers fall back to the narrator. Marks the chapter `curated`."""
    from app.schemas.script import SfxCue
    from app.services import line_planner

    nar = line_planner.NARRATOR_ID
    ch = load_chapter(project, chapter_id)
    if ch is None:
        return None
    lines: list[LineItem] = []
    n = 0
    for al in agent_lines:
        text = (al.get("text") or "").strip()
        if not text:
            continue
        try:
            typ = LineType(al.get("type", "narration"))
        except ValueError:
            typ = LineType.narration
        sp = al.get("speaker") or nar
        if typ is LineType.narration or sp not in valid_speaker_ids:
            sp = nar if typ is LineType.narration or sp not in valid_speaker_ids else sp
        n += 1
        cues: list[SfxCue] = []
        for it in (al.get("sfx") or []):
            if isinstance(it, str) and it.strip():
                cues.append(SfxCue(prompt=it.strip()))
            elif isinstance(it, dict) and (it.get("prompt") or "").strip():
                place = it.get("placement")
                cues.append(SfxCue(
                    prompt=it["prompt"].strip(),
                    placement=place if place in ("over", "gap") else "over",
                    length_s=float(it.get("length_s", 3.0)),
                    gain_db=float(it.get("gain_db", -7.0)),
                ))
        lines.append(LineItem(
            line_id=f"{chapter_id}_l{n:04d}", chapter_id=chapter_id, index=n,
            type=typ, speaker_id=sp, text=text, sfx=cues,
            delivery=line_planner.delivery_from_agent(
                text, al.get("emotion"), al.get("style"),
                al.get("prosody"), al.get("nonverbal")),
        ))
    ch.lines = lines
    ch.curated = True
    ch.audio_path = None
    save_chapter(project, ch)
    return ch

# A heading line like "12. Ein anstrengender Tag im Büro".
_HEADING = re.compile(r"^\s*(\d{1,3})\.\s+([A-ZÄÖÜ].{2,60})\s*$")


def detect_chapters(text: str) -> list[Chapter]:
    """Split cleaned book text into chapters on numbered headings."""
    lines = text.splitlines()
    marks: list[tuple[int, int, str]] = []  # (line_index, number, title)
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if m:
            marks.append((i, int(m.group(1)), m.group(2).strip()))

    # Keep only a monotonically increasing run (1,2,3,...) to drop false hits.
    cleaned: list[tuple[int, int, str]] = []
    expect = 1
    for idx, num, title in marks:
        if num == expect:
            cleaned.append((idx, num, title))
            expect += 1
    if not cleaned:
        return []

    chapters: list[Chapter] = []
    for k, (idx, num, title) in enumerate(cleaned):
        start = idx + 1
        end = cleaned[k + 1][0] if k + 1 < len(cleaned) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        chapters.append(Chapter(
            chapter_id=f"ch{num:02d}", number=num, title=title, text=body,
        ))
    return chapters


# --- persistence (project analysis/chapters/) --------------------------------


def _dir(project) -> Path:
    d = project.analysis_dir / "chapters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_chapter(project, chapter: Chapter) -> None:
    (_dir(project) / f"{chapter.chapter_id}.json").write_text(
        chapter.model_dump_json(indent=2), encoding="utf-8"
    )


def save_index(project, chapters: list[Chapter]) -> None:
    """A light index (no prose) for the chapters screen."""
    idx = [{"chapter_id": c.chapter_id, "number": c.number, "title": c.title,
            "lines": len(c.lines), "audio_path": c.audio_path} for c in chapters]
    (_dir(project) / "index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_chapter(project, chapter_id: str) -> Chapter | None:
    f = _dir(project) / f"{chapter_id}.json"
    if not f.exists():
        return None
    return Chapter.model_validate_json(f.read_text(encoding="utf-8"))


def load_index(project) -> list[dict]:
    f = _dir(project) / "index.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))
