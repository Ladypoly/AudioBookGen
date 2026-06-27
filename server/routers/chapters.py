"""Chapters: list, script view, editable text (re-plan), render / produce / export."""

from __future__ import annotations

from pathlib import Path

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import CONFIG
from app.schemas.script import LineItem, LineType, SfxCue
from app.schemas.timeline import (
    LANE_AMBIENCE, LANE_SFX, Timeline, TimelineSegment,
)
from app.schemas.voice import Emotion, Style
from app.services import (
    ambience, chapter_service, line_planner, music_planner, project_service,
    timeline_service,
)
from server.jobs import MANAGER
from server import rendering

router = APIRouter(prefix="/api/chapters", tags=["chapters"])


def _proj():
    proj = project_service.active()
    if proj is None:
        raise HTTPException(409, "No project open")
    return proj


def _media_url(p: str | Path | None, bust: bool = False) -> str | None:
    if not p:
        return None
    pth = Path(p)
    try:
        rel = pth.resolve().relative_to(CONFIG.projects_root.resolve())
    except (ValueError, OSError):
        return None
    url = "/api/media/" + "/".join(rel.parts)
    if bust:
        # Append the file mtime so re-rendered/regenerated audio gets a fresh
        # URL — otherwise the browser serves the cached old clip and edits are
        # inaudible / waveforms stale.
        try:
            url += f"?v={int(pth.stat().st_mtime)}"
        except OSError:
            pass
    return url


@router.get("")
def list_chapters() -> list[dict]:
    proj = _proj()
    index = chapter_service.load_index(proj)
    out = []
    for info in index:
        audio = proj.chapter_audio_dir / f"{info['chapter_id']}.mp3"
        out.append({
            "chapter_id": info["chapter_id"],
            "number": info.get("number"),
            "title": info.get("title", ""),
            "lines": info.get("lines", 0),
            "rendered": audio.exists(),
            "audio_url": _media_url(audio, bust=True) if audio.exists() else None,
        })
    return out


@router.get("/{cid}")
def get_chapter(cid: str) -> dict:
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, f"Chapter not found: {cid}")
    names = {c.character_id: c.display_name for c in project_service.load_characters(proj)}

    lines = []
    for ln in ch.lines:
        d = ln.model_dump(mode="json")
        d["speaker_name"] = names.get(ln.speaker_id, ln.speaker_id)
        lines.append(d)

    amb_prompt = ambience.ambience_for_chapter(ch)[0] if ch.lines else ""
    mus_prompt = music_planner.music_for_chapter(ch)[0] if (ch.lines and CONFIG.tts.music_enabled) else ""
    audio = proj.chapter_audio_dir / f"{ch.chapter_id}.mp3"
    return {
        "chapter_id": ch.chapter_id,
        "number": ch.number,
        "title": ch.title,
        "text": ch.text,
        "summary": ch.summary,
        "location": ch.location,
        "curated": ch.curated,
        "lines": lines,
        "ambience": amb_prompt,
        "music": mus_prompt,
        "rendered": audio.exists(),
        "audio_url": _media_url(audio, bust=True) if audio.exists() else None,
    }


class TextBody(BaseModel):
    text: str


@router.put("/{cid}/text")
def update_text(cid: str, body: TextBody) -> dict:
    """Save edited chapter prose and re-plan the line script from it."""
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, f"Chapter not found: {cid}")
    chars = project_service.load_characters(proj)
    ch.text = body.text
    ch.lines = line_planner.plan_chapter(ch, chars)
    ch.curated = False               # heuristic plan again (user edited the text)
    ch.audio_path = None
    chapter_service.save_chapter(proj, ch)
    # keep the index line-count fresh
    index = chapter_service.load_index(proj)
    for info in index:
        if info["chapter_id"] == cid:
            info["lines"] = len(ch.lines)
    _save_index_raw(proj, index)
    return get_chapter(cid)


def _save_index_raw(proj, index: list[dict]) -> None:
    import json
    (proj.analysis_dir / "chapters" / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# --- script tag editor: tag a span / split a line ---------------------------


class TagBody(BaseModel):
    line_id: str
    start: int = 0
    end: int = -1                     # -1 => end of the line (whole line)
    emotion: str | None = None        # null clears
    style: str | None = None
    speaker_id: str | None = None     # null keeps the line's speaker
    pitch_semitones: float = 0.0


def _apply_tags(line: LineItem, *, emotion, style, speaker_id, pitch) -> None:
    line.delivery.emotion = Emotion(emotion) if emotion else None
    line.delivery.style = Style(style) if style else None
    line.pitch_semitones = pitch
    if speaker_id is not None:
        line.speaker_id = speaker_id
        line.type = (LineType.narration if speaker_id == line_planner.NARRATOR_ID
                     else LineType.dialogue)


@router.post("/{cid}/lines/tag")
def tag_span(cid: str, body: TagBody) -> dict:
    """Tag a (sub)span of a line with an emotion/style/speaker. A partial span
    splits the line so the selected words render as their own segment."""
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, f"Chapter not found: {cid}")
    try:
        if body.emotion:
            Emotion(body.emotion)
        if body.style:
            Style(body.style)
    except ValueError as e:
        raise HTTPException(400, f"Invalid tag: {e}")

    if body.speaker_id:                  # lazily create a default one-off voice
        from server.routers.characters import ensure_default_character
        ensure_default_character(proj, body.speaker_id)

    idx = next((i for i, l in enumerate(ch.lines) if l.line_id == body.line_id), None)
    if idx is None:
        raise HTTPException(404, "Line not found")
    line = ch.lines[idx]
    text = line.text
    start = max(0, body.start)
    end = len(text) if body.end < 0 else min(body.end, len(text))

    origin = line.origin or line.line_id
    origin_text = line.origin_text or line.text

    def _new(part_text: str, tagged: bool) -> LineItem:
        nl = line.model_copy(deep=True)
        nl.line_id = f"{line.line_id}_{uuid.uuid4().hex[:4]}"
        nl.text = part_text.strip()
        nl.audio_path = None
        nl.sfx = []                    # SFX stay on the first part only (added below)
        nl.origin = origin
        nl.origin_text = origin_text
        if tagged:
            _apply_tags(nl, emotion=body.emotion, style=body.style,
                        speaker_id=body.speaker_id, pitch=body.pitch_semitones)
        return nl

    whole = start <= 0 and end >= len(text)
    if whole:
        _apply_tags(line, emotion=body.emotion, style=body.style,
                    speaker_id=body.speaker_id, pitch=body.pitch_semitones)
        line.audio_path = None
    else:
        parts: list[LineItem] = []
        before, mid, after = text[:start], text[start:end], text[end:]
        if before.strip():
            parts.append(_new(before, tagged=False))
        if parts:                       # keep this line's SFX on the first part
            parts[0].sfx = line.sfx
        else:
            line_first = _new(mid, tagged=True)
            line_first.sfx = line.sfx
            parts.append(line_first)
            mid = ""                    # consumed
        if mid.strip():
            parts.append(_new(mid, tagged=True))
        if after.strip():
            parts.append(_new(after, tagged=False))
        ch.lines[idx:idx + 1] = parts

    ch.lines = _merge_origins(ch.lines)
    for n, l in enumerate(ch.lines, start=1):
        l.index = n
    ch.curated = True
    ch.audio_path = None
    chapter_service.save_chapter(proj, ch)
    _bump_index(proj, cid, len(ch.lines))
    return get_chapter(cid)


def _is_plain(l: LineItem) -> bool:
    d = l.delivery
    return (d.emotion is None and d.style is None and not d.prosody
            and not d.nonverbal and not l.pitch_semitones)


def _merge_origins(lines: list[LineItem]) -> list[LineItem]:
    """Collapse consecutive split-parts of the same origin back into the
    original line once they are all untagged again (revert after clearing)."""
    out: list[LineItem] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.origin and _is_plain(l):
            j = i
            grp: list[LineItem] = []
            while (j < len(lines) and lines[j].origin == l.origin
                   and _is_plain(lines[j]) and lines[j].speaker_id == l.speaker_id
                   and lines[j].type == l.type):
                grp.append(lines[j])
                j += 1
            if len(grp) > 1:
                merged = grp[0]
                merged.text = merged.origin_text or " ".join(g.text for g in grp)
                merged.audio_path = None
                merged.sfx = [c for g in grp for c in g.sfx]
                out.append(merged)
                i = j
                continue
        out.append(l)
        i += 1
    return out


# --- SFX cues on a line ------------------------------------------------------


def _find_line(ch, line_id: str) -> LineItem:
    for l in ch.lines:
        if l.line_id == line_id:
            return l
    raise HTTPException(404, "Line not found")


class SfxBody(BaseModel):
    prompt: str
    placement: str = "over"
    position: float = 0.25
    length_s: float = 3.0
    gain_db: float = -7.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0


@router.post("/{cid}/lines/{line_id}/sfx")
def add_sfx(cid: str, line_id: str, body: SfxBody) -> dict:
    """Add a generated SFX cue (rendered from the prompt at produce time)."""
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, "Chapter not found")
    line = _find_line(ch, line_id)
    line.sfx.append(SfxCue(
        prompt=body.prompt, placement=body.placement if body.placement in ("over", "gap") else "over",
        position=body.position, length_s=body.length_s, gain_db=body.gain_db,
        fade_in_ms=body.fade_in_ms, fade_out_ms=body.fade_out_ms))
    ch.curated = True
    chapter_service.save_chapter(proj, ch)
    return get_chapter(cid)


@router.post("/{cid}/lines/{line_id}/sfx-file")
async def add_sfx_file(cid: str, line_id: str, file: UploadFile = File(...),
                       placement: str = Form("over"), position: float = Form(0.25),
                       gain_db: float = Form(-7.0)) -> dict:
    """Add a user-supplied SFX clip (used as-is, never generated)."""
    import shutil
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, "Chapter not found")
    line = _find_line(ch, line_id)
    ext = (file.filename or "sfx.wav").rsplit(".", 1)[-1].lower()
    proj.sfx_dir.mkdir(parents=True, exist_ok=True)
    dst = proj.sfx_dir / f"custom_{uuid.uuid4().hex[:10]}.{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    line.sfx.append(SfxCue(prompt=file.filename or "custom sfx", custom=True,
                           audio_path=str(dst),
                           placement=placement if placement in ("over", "gap") else "over",
                           position=position, gain_db=gain_db))
    ch.curated = True
    chapter_service.save_chapter(proj, ch)
    return get_chapter(cid)


@router.delete("/{cid}/lines/{line_id}/sfx/{idx}")
def remove_sfx(cid: str, line_id: str, idx: int) -> dict:
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, "Chapter not found")
    line = _find_line(ch, line_id)
    if 0 <= idx < len(line.sfx):
        line.sfx.pop(idx)
        chapter_service.save_chapter(proj, ch)
    return get_chapter(cid)


def _bump_index(proj, cid: str, n: int) -> None:
    index = chapter_service.load_index(proj)
    for info in index:
        if info["chapter_id"] == cid:
            info["lines"] = n
    _save_index_raw(proj, index)


# --- timeline (WYSIWYG edit model) ------------------------------------------


def _serialize_timeline(tl: Timeline) -> dict:
    d = tl.model_dump(mode="json")
    for seg in d["segments"]:
        seg["audio_url"] = _media_url(seg.get("audio_path"), bust=True)
    return d


@router.get("/{cid}/timeline")
def get_timeline(cid: str) -> dict:
    proj = _proj()
    ch = chapter_service.load_chapter(proj, cid)
    if ch is None:
        raise HTTPException(404, f"Chapter not found: {cid}")
    return _serialize_timeline(timeline_service.get_or_derive(ch))


@router.put("/{cid}/timeline")
def put_timeline(cid: str, body: Timeline) -> dict:
    proj = _proj()
    if body.chapter_id != cid:
        body.chapter_id = cid
    timeline_service.save_timeline(proj, body)
    return _serialize_timeline(body)


@router.post("/{cid}/timeline/render")
def render_timeline(cid: str) -> dict:
    proj = _proj()
    job = MANAGER.submit("render", f"Timeline render · {cid}",
                         rendering.assemble_timeline_job(cid),
                         meta={"project_id": proj.root.name, "chapter_id": cid})
    return {"job_id": job.id}


_LANE_KIND = {"ambience": "ambience", "sfx": "sfx", "music": "music"}


class AddSegBody(BaseModel):
    kind: str                          # "ambience" | "sfx" | "music"
    lane: str
    start_ms: float
    duration_ms: float = 3000.0
    prompt: str = ""
    gain_db: float = -7.0


@router.post("/{cid}/timeline/segment")
def add_segment(cid: str, body: AddSegBody) -> dict:
    """Add an ambience/sfx/music segment to the timeline (audio generated via
    the regenerate endpoint)."""
    import uuid
    proj = _proj()
    tl = timeline_service.get_or_derive(chapter_service.load_chapter(proj, cid))
    seg = TimelineSegment(
        id=f"{body.kind[0]}_{uuid.uuid4().hex[:6]}", kind=body.kind, lane=body.lane,
        start_ms=body.start_ms, duration_ms=body.duration_ms, prompt=body.prompt,
        gain_db=body.gain_db, edited=True)
    tl.segments.append(seg)
    timeline_service.save_timeline(proj, tl)
    return _serialize_timeline(tl)


@router.delete("/{cid}/timeline/segment/{seg_id}")
def delete_segment(cid: str, seg_id: str) -> dict:
    proj = _proj()
    tl = timeline_service.get_or_derive(chapter_service.load_chapter(proj, cid))
    tl.segments = [s for s in tl.segments if s.id != seg_id]
    timeline_service.save_timeline(proj, tl)
    return _serialize_timeline(tl)


class RegenSegBody(BaseModel):
    prompt: str | None = None
    duration_ms: float | None = None


@router.post("/{cid}/timeline/segment/{seg_id}/regenerate")
def regenerate_segment(cid: str, seg_id: str, body: RegenSegBody) -> dict:
    """(Re)generate the audio for an ambience/sfx/music segment from its prompt."""
    proj = _proj()

    def run(ctx) -> dict:
        from app.services import sound_service, comfy_launcher, ollama_service
        p = project_service.active()
        tl = timeline_service.load_timeline(p, cid)
        seg = next((s for s in tl.segments if s.id == seg_id), None) if tl else None
        if seg is None:
            raise RuntimeError("Segment not found")
        if body.prompt is not None:
            seg.prompt = body.prompt
        if body.duration_ms is not None:
            seg.duration_ms = body.duration_ms
        kind = _LANE_KIND.get(seg.kind, "sfx")
        out = p.root / "mixes" / "timeline"
        out.mkdir(parents=True, exist_ok=True)
        out_file = out / f"{cid}_{seg_id}.mp3"
        # Serialize generation: only one timeline clip renders at a time, so
        # concurrent "Generate" presses queue cleanly and never share the GPU.
        ctx.busy("Queued…")
        with comfy_launcher.RENDER_LOCK:
            ctx.busy(f"Generating {kind}…")
            ollama_service.unload()
            comfy_launcher.ensure_stage("audio")
            sound_service.generate(
                seg.prompt, max(1.0, seg.duration_ms / 1000.0), out_file, kind=kind,
                on_step=lambda v, m: ctx.progress(v, m, f"Generating {kind}… {v}/{m}"),
            )
        seg.audio_path = str(out_file)
        seg.custom = False
        seg.estimated = False
        timeline_service.save_timeline(p, tl)
        return {"chapter_id": cid, "segment": seg_id, "audio": str(out_file)}

    job = MANAGER.submit("audio", f"Generate {seg_id}", run,
                         meta={"project_id": proj.root.name, "chapter_id": cid, "segment_id": seg_id})
    return {"job_id": job.id}


class RenderBody(BaseModel):
    mode: str = "continue"


@router.post("/{cid}/render")
def render_chapter(cid: str, body: RenderBody) -> dict:
    proj = _proj()
    job = MANAGER.submit("render", f"Render · {cid}",
                         rendering.render_chapter_job(cid, body.mode),
                         meta={"project_id": proj.root.name, "chapter_id": cid})
    return {"job_id": job.id}


@router.post("/{cid}/summarize")
def summarize(cid: str) -> dict:
    """Generate the chapter summary + location (one LLM call) as a job."""
    proj = _proj()

    def run(ctx) -> dict:
        from app.services import chapter_brief
        p = project_service.active()
        ch = chapter_service.load_chapter(p, cid)
        if ch is None:
            raise RuntimeError(f"Chapter not found: {cid}")
        from app.services import cost_service
        chars = len(ch.text or " ".join(l.text for l in ch.lines))
        ctx.update_meta(est=cost_service.estimate_for_text(chars, in_mult=1.0, out_ratio=0.08))
        ctx.busy("Summarizing chapter…")
        brief = chapter_brief.generate_brief(ch)
        ch.summary = brief.summary
        ch.location = brief.location
        chapter_service.save_chapter(p, ch)
        return {"chapter_id": cid, "summary": ch.summary, "location": ch.location}

    job = MANAGER.submit("summary", f"Summarize · {cid}", run,
                         meta={"project_id": proj.root.name, "chapter_id": cid})
    return {"job_id": job.id}


@router.post("/produce")
def produce(body: RenderBody) -> dict:
    proj = _proj()
    job = MANAGER.submit("produce", "Produce chapters",
                         rendering.produce_all_job(body.mode),
                         meta={"project_id": proj.root.name})
    return {"job_id": job.id}


class ExportBody(BaseModel):
    folder: str


@router.post("/export")
def export(body: ExportBody) -> dict:
    proj = _proj()
    if not body.folder:
        raise HTTPException(400, "No export folder given")
    job = MANAGER.submit("export", "Export audiobook",
                         rendering.export_job(body.folder),
                         meta={"project_id": proj.root.name})
    return {"job_id": job.id}
