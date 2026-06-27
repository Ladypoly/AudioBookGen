"""Extraction job — the web/job-runner port of app/workers/extract_worker.py.

Same pipeline (detect chapters -> cast -> optional web -> style bible ->
portrait prompts -> chapters index), but progress is reported through a
JobContext and streamed over /ws/jobs instead of Qt signals. The canonical
STEPS list drives the per-step animation in the New-AudioDrama popup.
"""

from __future__ import annotations

import logging

from app.core.config import CONFIG
from app.services import (
    afterword,
    chapter_service,
    character_service,
    comfy_launcher,
    front_matter,
    portrait_service,
    project_service,
    research_service,
    story_service,
    style_service,
)
from server.jobs import JobContext

logger = logging.getLogger(__name__)

# (key, human label) — the frontend maps each key to an animated .webp.
STEPS = [
    ("prepare", "Preparing"),
    ("cast", "Reading the book & extracting the cast"),
    ("research", "Researching online"),
    ("style", "Designing the visual style"),
    ("portraits", "Writing portrait prompts"),
    ("voicelines", "Writing character intro lines"),
    ("finalize", "Assembling chapters"),
    ("done", "Done"),
]


def _write_sample_lines(characters, language: str, progress, is_cancelled) -> None:
    """LLM-write each active character's spoken self-introduction (the voice
    sample text) now, so voice design later is just TTS — no LLM round-trip."""
    from app.services import voice_design
    actives = [c for c in characters if c.active]
    total = len(actives)
    for i, c in enumerate(actives):
        if is_cancelled():
            break
        progress(i, total, f"Intro line · {c.display_name}")
        if not c.sample_line:
            try:
                c.sample_line = voice_design.compose_intro_text(c, language)
            except Exception:  # noqa: BLE001
                logger.warning("sample line failed for %s", c.display_name, exc_info=True)
    progress(total, total, "Intro lines ready")


def _build_index(project, content_chapters: list) -> None:
    ordered = list(content_chapters)
    if CONFIG.extraction.front_matter:
        fm = front_matter.build(
            project, [{"number": c.number, "title": c.title, "chapter_id": c.chapter_id}
                      for c in content_chapters])
        chapter_service.save_chapter(project, fm)
        ordered = [fm, *ordered]
    if CONFIG.extraction.afterword:
        aw = afterword.build(
            project, number=(content_chapters[-1].number + 1) if content_chapters else 1)
        if aw is not None:
            chapter_service.save_chapter(project, aw)
            ordered.append(aw)
    chapter_service.save_index(project, ordered)


def run_extraction(ctx: JobContext, project) -> dict:
    """Run the full extraction pipeline for an already-created project."""
    project_service.set_active(project)
    ctx.update_meta(steps=[{"key": k, "label": v} for k, v in STEPS],
                    project_id=project.root.name)

    ctx.set_step("prepare", "Freeing GPU memory…")
    comfy_launcher.release_pool()
    comfy_launcher.free_vram()

    # rough token-cost estimate for the whole extraction (multi-pass over the book)
    try:
        from app.services import cost_service, pdf_service
        chars = len(pdf_service.extract_text(project.source_pdf))
        ctx.update_meta(est=cost_service.estimate_for_text(chars, in_mult=1.4, out_ratio=0.25))
    except Exception:  # noqa: BLE001
        pass

    ctx.set_step("cast", "Reading the book…")

    def progress(done: int, total: int, label: str) -> None:
        # story_service emits fine-grained labels during the cast pass.
        ctx.progress(done, total, label)

    characters, content_chapters = story_service.extract_story(
        project,
        progress=progress,
        is_cancelled=lambda: ctx.cancelled,
        partial=lambda chars: ctx.update_meta(cast_count=len(chars)),
    )
    if ctx.cancelled:
        raise RuntimeError("Cancelled")
    if not content_chapters:
        raise RuntimeError("No extractable text found in the book file.")

    web_style_ctx = ""
    if CONFIG.extraction.web_search:
        ctx.set_step("research", "Enriching characters online…")
        characters = character_service.enrich_with_web(
            characters, project.title, progress=progress)
        web_style_ctx = research_service.style_context(project.title)

    ctx.set_step("style", "Designing the visual style…")
    sample = "\n".join(c.text for c in content_chapters[:2])[:12000]
    bible = style_service.generate_style_bible(
        project.title, sample, web_context=web_style_ctx)
    portrait_service.set_style_bible(bible)

    ctx.set_step("portraits", "Writing portrait prompts…")
    characters = character_service.write_portrait_prompts(
        characters, bible, progress=progress)

    ctx.set_step("voicelines", "Writing character intro lines…")
    _write_sample_lines(characters, CONFIG.tts.language, progress,
                        lambda: ctx.cancelled)

    project_service.save_characters(project, characters)
    project_service.save_style_bible(project, bible)

    ctx.set_step("finalize", "Assembling chapters…")
    _build_index(project, content_chapters)

    ctx.set_step("done", f"{len(characters)} characters, {len(content_chapters)} chapters")
    return {"project_id": project.root.name,
            "characters": len(characters),
            "chapters": len(content_chapters)}
