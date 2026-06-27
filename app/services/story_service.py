"""Chapter-centric story extraction (the import backbone).

  detect  : split the book into chapters (chapter_service)
  Pass A  : per chapter -> clean character mentions via the dedicated, proven
            character_map_prompt (chunked at the size gemma handles well). This
            is the same extraction the old pipeline used, now chapter-aligned so
            a character that appears at different ages can be split per chapter.
  roster  : deterministic cards from the accumulated mentions (character_service)
  Pass B  : per chapter -> heuristic line plan (line_planner) + a small LLM pass
            that only CORRECTS dialogue speaker attribution. On any LLM failure
            the heuristic plan is kept as-is.

NB: an earlier version asked one prompt for BOTH a chapter summary and the
character mentions, optionally batching several chapters per call. gemma4 leaks
JSON structure into the name fields under that combined/batched load (garbled
cards) and the big calls are slower, so character extraction now uses the
dedicated mentions-only prompt, one modest chunk at a time.

Everything is written incrementally (<id>.mentions.json, <id>.json curated) so a
cancelled or crashed import resumes at the first unfinished chapter.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from app.schemas.characters import Character, CharacterMention
from app.schemas.script import Chapter, LineType
from app.services import (
    chapter_service,
    character_service,
    line_planner,
    ollama_service,
    pdf_service,
    project_service,
)
from app.services.line_planner import NARRATOR_ID

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]
CancelCb = Callable[[], bool]
PartialCb = Callable[[list[Character]], None]


# --- resume helpers (per-chapter mention cache) ------------------------------


def _mentions_file(project, chapter_id: str) -> Path:
    d = project.analysis_dir / "chapters"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{chapter_id}.mentions.json"


def _load_mentions(project, chapter_id: str) -> list[CharacterMention] | None:
    f = _mentions_file(project, chapter_id)
    if not f.exists():
        return None
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        return [CharacterMention.model_validate(m) for m in raw]
    except Exception:  # noqa: BLE001
        return None


def _save_mentions(project, chapter_id: str, mentions: list[CharacterMention]) -> None:
    _mentions_file(project, chapter_id).write_text(
        json.dumps([m.model_dump() for m in mentions], ensure_ascii=False, indent=2),
        encoding="utf-8")


# --- chapter detection (with a fallback so the pipeline never runs empty) -----


def detect(project) -> list[Chapter]:
    text = pdf_service.extract_text(project.source_pdf)
    norm = pdf_service._normalize(text)
    chapters = chapter_service.detect_chapters(norm)
    if not chapters:                       # no numbered headings -> one chapter
        chapters = [Chapter(chapter_id="ch01", number=1,
                            title=project.title, text=norm)]
    for c in chapters:                     # persist raw prose up front (resume)
        chapter_service.save_chapter(project, c)
    return chapters


# --- Pass A: clean character mentions per chapter ----------------------------


def extract_chapter_mentions(chapter: Chapter) -> list[CharacterMention]:
    """Run the proven mentions-only extraction over a chapter, chunked at the
    size gemma handles cleanly (so long chapters stay reliable)."""
    chunks = pdf_service.chunk_text(chapter.text) or [chapter.text]
    out: list[CharacterMention] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            out.extend(character_service.map_chunk(chunk))
        except ollama_service.OllamaError as err:
            logger.error("Mention extraction failed in %s: %s", chapter.chapter_id, err)
    return out


# --- Pass B: heuristic plan + LLM speaker refine -----------------------------


def _roster_block(characters: list[Character]) -> str:
    out = []
    for c in characters:
        al = f" [{', '.join(c.aliases)}]" if c.aliases else ""
        out.append(f"- {c.character_id} — {c.display_name}{al} — {c.gender_guess.value}")
    out.append("- erzaehler — Erzähler (narrator)")
    return "\n".join(out)


def refine_speakers(chapter: Chapter, characters: list[Character]) -> None:
    """Correct dialogue speaker_ids in place via one small LLM call (corrections
    only). Keeps the heuristic guess on any failure or for invalid lines."""
    from app.core import prompts
    from app.schemas.script import SpeakerRefineResult

    if not any(l.type == LineType.dialogue for l in chapter.lines):
        return
    valid = {c.character_id for c in characters} | {NARRATOR_ID}
    transcript = "\n".join(
        f"[{l.index}] SPEAKER={l.speaker_id} TYPE={l.type.value} : {l.text}"
        for l in chapter.lines)
    prompt = prompts.render(
        "speaker_refine_prompt",
        roster=_roster_block(characters),
        summary="(not available)", transcript=transcript)
    try:
        res = ollama_service.generate_json(prompt, SpeakerRefineResult)
    except ollama_service.OllamaError as err:
        logger.warning("Speaker refine failed for %s: %s", chapter.chapter_id, err)
        return
    by_index = {l.index: l for l in chapter.lines}
    fixed = 0
    for sl in res.lines:
        l = by_index.get(sl.index)
        if l is not None and l.type == LineType.dialogue and sl.speaker_id in valid:
            if l.speaker_id != sl.speaker_id:
                fixed += 1
            l.speaker_id = sl.speaker_id
    logger.info("Speaker refine %s: %d corrections", chapter.chapter_id, fixed)


# --- Orchestration -----------------------------------------------------------


def extract_story(
    project,
    progress: ProgressCb | None = None,
    is_cancelled: CancelCb | None = None,
    partial: PartialCb | None = None,
    timings: dict | None = None,
) -> tuple[list[Character], list[Chapter]]:
    """Run detect -> Pass A -> roster -> Pass B. Returns (characters, content
    chapters). Content chapters are saved as curated line plans; front matter,
    afterword, index, style bible and portraits are added by the caller."""
    import time
    from app.core.config import CONFIG
    from app.services import llm_pool

    chapters = detect(project)
    total = len(chapters)
    conc = CONFIG.ollama.llm_concurrency
    _t_a = time.monotonic()

    # --- Pass A: clean per-chapter character mentions (fast small model) ------
    all_mentions: list[CharacterMention] = []
    mentions_by_chapter: dict[str, list[CharacterMention]] = {}

    def _read_chapter(ch):
        cached = _load_mentions(project, ch.chapter_id)
        if cached is None:
            cached = extract_chapter_mentions(ch)
            _save_mentions(project, ch.chapter_id, cached)
        return ch.chapter_id, cached

    done_a = [0]

    def _merge_a(_i, res):           # runs on the calling thread → safe
        done_a[0] += 1
        if res:
            cid, cached = res
            all_mentions.extend(cached)
            mentions_by_chapter[cid] = cached
            if partial and all_mentions:
                partial(character_service.roster_from_mentions(all_mentions))
        if progress:
            progress(done_a[0], total, f"Reading characters {done_a[0]}/{total}")

    with ollama_service.use_model(CONFIG.ollama.extraction_model):
        llm_pool.parallel_map(chapters, _read_chapter, conc,
                              on_complete=_merge_a, is_cancelled=is_cancelled)
    if timings is not None:
        timings["pass_a"] = time.monotonic() - _t_a
        timings["mentions"] = len(all_mentions)

    # --- roster: clean cards (deterministic proper-name resolution) ----------
    if progress:
        progress(total, total, "Building character roster")
    characters = character_service.roster_from_mentions(all_mentions)
    project_service.save_analysis(
        project, all_mentions, character_service.group_mentions(all_mentions),
        characters)

    if is_cancelled and is_cancelled():
        return characters, chapters

    # --- Pass B: heuristic plan + LLM speaker refine (reasoning model) -------
    def _storyboard(ch):
        existing = chapter_service.load_chapter(project, ch.chapter_id)
        if existing is not None and existing.curated and existing.lines:
            return                                         # resume: already done
        # Resolve multi-age characters to the variant matching THIS chapter's
        # age, so e.g. "Anna" maps to the child or the adult Anna correctly.
        ch_chars = character_service.resolve_for_chapter(
            characters, mentions_by_chapter.get(ch.chapter_id, []))
        ch.lines = line_planner.plan_chapter(ch, ch_chars)
        refine_speakers(ch, ch_chars)
        ch.curated = True
        chapter_service.save_chapter(project, ch)

    done_b = [0]

    def _prog_b(_i, _res):
        done_b[0] += 1
        if progress:
            progress(done_b[0], total, f"Storyboard chapter {done_b[0]}/{total}")

    _t_b = time.monotonic()
    with ollama_service.use_model(CONFIG.ollama.refine_model):
        llm_pool.parallel_map(chapters, _storyboard, conc,
                              on_complete=_prog_b, is_cancelled=is_cancelled)
    if timings is not None:
        timings["pass_b"] = time.monotonic() - _t_b
    if progress:
        progress(total, total, "Story extracted")
    return characters, chapters
