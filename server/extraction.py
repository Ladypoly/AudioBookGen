"""Extraction job — the web/job-runner port of app/workers/extract_worker.py.

Same pipeline (detect chapters -> cast -> optional web -> style bible ->
portrait prompts -> chapters index), but progress is reported through a
JobContext and streamed over /ws/jobs instead of Qt signals. The canonical
STEPS list drives the per-step animation in the New-AudioDrama popup.
"""

from __future__ import annotations

import json
import logging
import time

from app.core.config import CONFIG
from app.services import (
    afterword,
    chapter_service,
    character_service,
    comfy_launcher,
    front_matter,
    ollama_service,
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
    from app.core.config import CONFIG
    from app.services import llm_pool, voice_design
    actives = [c for c in characters if c.active and not c.sample_line]
    total = len(actives)
    if not total:
        return

    def _one(c):
        try:
            c.sample_line = voice_design.compose_intro_text(c, language)
        except Exception:  # noqa: BLE001
            logger.warning("sample line failed for %s", c.display_name, exc_info=True)

    done = [0]

    def _prog(_i, _r):
        done[0] += 1
        progress(done[0], total, f"Intro line {done[0]}/{total}")

    llm_pool.parallel_map(actives, _one, CONFIG.ollama.llm_concurrency,
                          on_complete=_prog, is_cancelled=is_cancelled)
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

    # --- timing for the import report ---
    cfg = CONFIG.ollama
    eff = lambda m: m or cfg.model     # effective model for a phase
    t_start = time.monotonic()
    marks: list[tuple[str, float]] = []

    def step(key: str, label: str) -> None:
        marks.append((key, time.monotonic()))
        ctx.set_step(key, label)

    step("prepare", "Freeing GPU memory…")
    comfy_launcher.release_pool()
    comfy_launcher.free_vram()

    # rough token-cost estimate for the whole extraction (multi-pass over the book)
    try:
        from app.services import cost_service, pdf_service
        chars = len(pdf_service.extract_text(project.source_pdf))
        ctx.update_meta(est=cost_service.estimate_for_text(chars, in_mult=1.4, out_ratio=0.25))
    except Exception:  # noqa: BLE001
        pass

    step("cast", "Reading the book…")

    def progress(done: int, total: int, label: str) -> None:
        # story_service emits fine-grained labels during the cast pass.
        ctx.progress(done, total, label)

    pass_timings: dict = {}
    characters, content_chapters = story_service.extract_story(
        project,
        progress=progress,
        is_cancelled=lambda: ctx.cancelled,
        partial=lambda chars: ctx.update_meta(cast_count=len(chars)),
        timings=pass_timings,
    )
    if ctx.cancelled:
        raise RuntimeError("Cancelled")
    if not content_chapters:
        raise RuntimeError("No extractable text found in the book file.")

    web_style_ctx = ""
    if CONFIG.extraction.web_search:
        step("research", "Enriching characters online…")
        characters = character_service.enrich_with_web(
            characters, project.title, progress=progress)
        web_style_ctx = research_service.style_context(project.title)

    with ollama_service.use_model(CONFIG.ollama.prompt_model):
        step("style", "Designing the visual style…")
        sample = "\n".join(c.text for c in content_chapters[:2])[:12000]
        bible = style_service.generate_style_bible(
            project.title, sample, web_context=web_style_ctx)
        portrait_service.set_style_bible(bible)

        step("portraits", "Writing portrait prompts…")
        characters = character_service.write_portrait_prompts(
            characters, bible, progress=progress)

        step("voicelines", "Writing character intro lines…")
        _write_sample_lines(characters, CONFIG.tts.language, progress,
                            lambda: ctx.cancelled)

    project_service.save_characters(project, characters)
    project_service.save_style_bible(project, bible)

    step("finalize", "Assembling chapters…")
    _build_index(project, content_chapters)

    marks.append(("done", time.monotonic()))
    report = _build_report(project, marks, pass_timings, characters, content_chapters)
    ctx.update_meta(report=report)

    ctx.set_step("done", f"{len(characters)} characters · {len(content_chapters)} chapters "
                         f"· {report['total_seconds']}s")
    return {"project_id": project.root.name,
            "characters": len(characters),
            "chapters": len(content_chapters),
            "report": report}


def _build_report(project, marks, pass_timings, characters, content_chapters) -> dict:
    """Assemble + persist a per-run import report (phase timings, models, counts)
    so different model setups can be compared across runs."""
    cfg = CONFIG.ollama
    eff = lambda m: m or cfg.model
    durations = {marks[i][0]: round(marks[i + 1][1] - marks[i][1], 1)
                 for i in range(len(marks) - 1)}

    phases = [{"name": "Prepare", "seconds": durations.get("prepare", 0), "model": "—"}]
    if "pass_a" in pass_timings:
        phases.append({"name": "Read cast (Pass A)", "seconds": round(pass_timings["pass_a"], 1),
                       "model": eff(cfg.extraction_model)})
    if "pass_b" in pass_timings:
        phases.append({"name": "Storyboard (Pass B)", "seconds": round(pass_timings["pass_b"], 1),
                       "model": eff(cfg.refine_model)})
    for key, name, model in [
        ("research", "Web research", eff(cfg.prompt_model)),
        ("style", "Style bible", eff(cfg.prompt_model)),
        ("portraits", "Portrait prompts", eff(cfg.prompt_model)),
        ("voicelines", "Intro lines", eff(cfg.prompt_model)),
        ("finalize", "Assemble", "—"),
    ]:
        if key in durations:
            phases.append({"name": name, "seconds": durations[key], "model": model})

    report = {
        "title": project.title,
        "total_seconds": round(marks[-1][1] - marks[0][1], 1),
        "concurrency": cfg.llm_concurrency,
        "thinking_disabled": cfg.disable_thinking,
        "counts": {"chapters": len(content_chapters), "characters": len(characters),
                   "mentions": pass_timings.get("mentions", 0)},
        "models": {"extraction": eff(cfg.extraction_model), "refine": eff(cfg.refine_model),
                   "prompt": eff(cfg.prompt_model)},
        "phases": phases,
    }

    # Persist a history of runs so model setups can be compared later.
    try:
        path = project.analysis_dir / "import_reports.json"
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        history.append(report)
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("could not save import report", exc_info=True)
    return report
