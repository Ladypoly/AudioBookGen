"""Chapter rendering / produce / export as background jobs.

Ports app/workers/chapter_render_worker.py + audiobook_export to the JobContext
model. GPU work (TTS / scene audio via ComfyUI) runs inside the existing
services; jobs just drive them and stream progress over /ws/jobs.
"""

from __future__ import annotations

import logging

from app.core.config import CONFIG
from app.services import (
    ambience, audiobook_export, chapter_render, chapter_service, comfy_launcher,
    line_planner, music_planner, ollama_service, project_service, sfx_planner,
    sound_service, timeline_service,
)
from server.jobs import JobContext

logger = logging.getLogger(__name__)

# Re-render modes -> flags (mirrors app/ui/chapters_screen.py _REDO_MODES).
REDO_MODES: dict[str, dict] = {
    "full": dict(redo_voices=True, redo_ambience=True, redo_sfx=True),
    "continue": dict(),
    "voices": dict(redo_voices=True),
    "voices_chars": dict(redo_voices_no_narrator=True),
    "ambience": dict(redo_ambience=True),
    "sfx": dict(redo_sfx=True),
    "mix": dict(mix_only=True),
}


def render_one(ctx: JobContext, chapter_id: str, *, force=False, redo_voices=False,
               redo_ambience=False, redo_sfx=False, redo_voices_no_narrator=False,
               mix_only=False) -> dict:
    """Render a single chapter to audio (scene audio + voices + assemble)."""
    proj = project_service.active()
    if proj is None:
        raise RuntimeError("No project open")
    ch = chapter_service.load_chapter(proj, chapter_id)
    if ch is None:
        raise RuntimeError(f"Chapter not found: {chapter_id}")
    chars = project_service.load_characters(proj)

    if not (ch.curated and ch.lines):
        ch.lines = line_planner.plan_chapter(ch, chars)
    line_planner.prepend_title(ch)
    force = force or redo_voices

    out_dir = proj.line_audio_dir / ch.chapter_id

    # Mix only: no generation, just re-assemble from existing clips.
    if mix_only:
        for ln in ch.lines:
            clip = out_dir / f"{ln.line_id}.mp3"
            if clip.exists():
                ln.audio_path = str(clip)
        path = chapter_render.assemble(ch)
        chapter_service.save_chapter(proj, ch)
        return {"chapter_id": ch.chapter_id, "audio": path or ""}

    # Scene audio (ambience bed + discrete SFX) if missing or re-requested.
    sfx_planner.annotate(ch.lines)
    if redo_ambience:
        proj.ambience_path(ch.chapter_id).unlink(missing_ok=True)
        proj.music_path(ch.chapter_id).unlink(missing_ok=True)
    need_amb = CONFIG.tts.ambience_enabled and not proj.ambience_path(ch.chapter_id).exists()
    need_mus = CONFIG.tts.music_enabled and not proj.music_path(ch.chapter_id).exists()
    need_sfx = CONFIG.tts.sfx_enabled and (redo_sfx or any(
        not proj.sfx_clip_path(c).exists() for c in sfx_planner.cues_for(ch)))
    if need_amb or need_mus or need_sfx:
        ctx.busy("Generating scene audio…")
        ollama_service.unload()
        comfy_launcher.ensure_stage("audio")
        if need_amb:
            prompt, secs = ambience.ambience_for_chapter(ch)
            sound_service.generate(prompt, secs, proj.ambience_path(ch.chapter_id), kind="ambience")
        if need_mus:
            prompt, secs = music_planner.music_for_chapter(ch)
            sound_service.generate(prompt, secs, proj.music_path(ch.chapter_id), kind="music")
        if need_sfx:
            sfx_planner.generate_chapter_sfx(proj, ch, force=redo_sfx)

    if redo_voices_no_narrator:
        for ln in ch.lines:
            if ln.speaker_id != line_planner.NARRATOR_ID:
                (out_dir / f"{ln.line_id}.mp3").unlink(missing_ok=True)

    all_present = bool(ch.lines) and all(
        (out_dir / f"{l.line_id}.mp3").exists() for l in ch.lines)

    if force or not all_present:
        ctx.progress(0, len(ch.lines), "Rendering voices…")
        ollama_service.unload()
        urls = comfy_launcher.ensure_pool("tts")
        chapter_render.render_lines(
            ch, chars,
            progress=lambda d, t, n: ctx.progress(d, t, f"line {d}/{t} — {n}"),
            is_cancelled=lambda: ctx.cancelled, urls=urls, force=force)
    else:
        ctx.busy("Re-assembling…")
        for l in ch.lines:
            l.audio_path = str(out_dir / f"{l.line_id}.mp3")

    path = chapter_render.assemble(ch)
    chapter_service.save_chapter(proj, ch)
    # refresh the WYSIWYG timeline from the freshly-rendered layout (real
    # clip durations), unless the user has hand-edited it.
    _refresh_timeline(ch)
    return {"chapter_id": ch.chapter_id, "audio": path or ""}


def _refresh_timeline(ch) -> None:
    """Re-derive the timeline after a render, preserving any user edits."""
    proj = project_service.active()
    existing = timeline_service.load_timeline(proj, ch.chapter_id)
    if existing and any(s.edited for s in existing.segments):
        return                           # keep a hand-edited timeline
    timeline_service.save_timeline(proj, timeline_service.derive_timeline(ch))


def assemble_timeline_job(chapter_id: str):
    """Re-export the chapter MP3 from its (edited) timeline — WYSIWYG, no GPU."""
    def run(ctx: JobContext) -> dict:
        proj = project_service.active()
        ch = chapter_service.load_chapter(proj, chapter_id)
        if ch is None:
            raise RuntimeError(f"Chapter not found: {chapter_id}")
        ctx.busy("Rendering from timeline…")
        path = timeline_service.assemble_timeline(ch)
        return {"chapter_id": chapter_id, "audio": path or ""}
    return run


def render_chapter_job(chapter_id: str, mode: str):
    flags = REDO_MODES.get(mode, {})

    def run(ctx: JobContext) -> dict:
        return render_one(ctx, chapter_id, **flags)
    return run


def produce_all_job(mode: str):
    flags = REDO_MODES.get(mode, {})

    def run(ctx: JobContext) -> dict:
        proj = project_service.active()
        if proj is None:
            raise RuntimeError("No project open")
        index = chapter_service.load_index(proj)
        done = 0
        for i, info in enumerate(index):
            if ctx.cancelled:
                break
            ctx.update_meta(chapter=info["title"])
            ctx.progress(i, len(index), f"{info['number']}. {info['title']}")
            try:
                render_one(ctx, info["chapter_id"], **flags)
                done += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("produce: chapter %s failed: %s", info["chapter_id"], exc)
        ctx.progress(len(index), len(index), f"{done}/{len(index)} chapters")
        return {"rendered": done, "total": len(index)}
    return run


def export_job(folder: str):
    def run(ctx: JobContext) -> dict:
        proj = project_service.active()
        if proj is None:
            raise RuntimeError("No project open")
        ctx.busy("Exporting audiobook…")
        out = audiobook_export.export_audiobook(
            proj, folder, on_step=lambda n: ctx.step(f"Exported {n} chapters"))
        return {"out": str(out)}
    return run
