"""Derive / persist / render the chapter timeline (the WYSIWYG edit model).

`derive_timeline` walks a chapter the same way the procedural mix does, but with
real clip durations, producing absolute ms placements across the four lanes.
`build_from_timeline` renders the authoritative mix straight from those
placements, so the editor and the export agree.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.core.config import CONFIG
from app.schemas.script import Chapter
from app.schemas.timeline import (
    LANE_AMBIENCE, LANE_CHARACTERS, LANE_NARRATOR, LANE_SFX, Timeline, TimelineSegment,
)
from app.services import project_service

logger = logging.getLogger(__name__)

_ms_cache: dict[str, float] = {}


def _audio_ms(path: Path) -> float:
    key = f"{path}:{path.stat().st_mtime if path.exists() else 0}"
    if key in _ms_cache:
        return _ms_cache[key]
    try:
        from pydub import AudioSegment
        ms = float(len(AudioSegment.from_file(path)))
    except Exception:  # noqa: BLE001
        ms = 0.0
    _ms_cache[key] = ms
    return ms


def _estimate_ms(text: str) -> float:
    """Rough spoken duration for an un-rendered line (~14 chars/s, German)."""
    return max(600.0, len(text) / 14.0 * 1000.0)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def timeline_path(project, chapter_id: str) -> Path:
    return project.analysis_dir / "chapters" / f"{chapter_id}.timeline.json"


def load_timeline(project, chapter_id: str) -> Timeline | None:
    p = timeline_path(project, chapter_id)
    if not p.exists():
        return None
    try:
        return Timeline.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("bad timeline.json for %s", chapter_id, exc_info=True)
        return None


def save_timeline(project, timeline: Timeline) -> None:
    timeline_path(project, timeline.chapter_id).write_text(
        timeline.model_dump_json(indent=2), encoding="utf-8")


def derive_timeline(chapter: Chapter) -> Timeline:
    """Build a timeline from the chapter using the same layout as the mix."""
    from app.services import line_planner, sfx_planner

    proj = project_service.active()
    gap_same = CONFIG.tts.chapter_gap_same_ms
    gap_turn = CONFIG.tts.chapter_gap_turn_ms
    gap_narr = CONFIG.tts.chapter_gap_narrator_ms
    NARR = line_planner.NARRATOR_ID

    def _gap(cur: str, prev: str | None) -> int:
        if prev is None:
            return 0
        if cur == prev:
            return gap_same
        if NARR in (cur, prev):
            return gap_narr
        return gap_turn

    clip_dir = proj.line_audio_dir / chapter.chapter_id

    def _clip(line):
        p = clip_dir / f"{line.line_id}.mp3"
        if p.exists():
            return _audio_ms(p), str(p), False
        return _estimate_ms(line.text), None, True

    sfx_planner.annotate(chapter.lines)
    lines = chapter.lines
    title = (lines[0] if lines and chapter.number > 0
             and lines[0].line_id.endswith("_l0000") else None)
    body_lines = lines[1:] if title else lines

    segs: list[TimelineSegment] = []
    body_start = 0.0
    if title is not None:
        tdur, tpath, test = _clip(title)
        segs.append(TimelineSegment(
            id=_new_id("v"), kind="voice", lane=LANE_NARRATOR, start_ms=0.0,
            duration_ms=tdur, line_id=title.line_id, speaker_id=title.speaker_id,
            text=title.text, audio_path=tpath, estimated=test))
        body_start = tdur + 550.0

    has_amb = (proj.ambience_path(chapter.chapter_id).exists()
               and CONFIG.tts.ambience_enabled)
    cursor = body_start + (CONFIG.tts.ambience_establish_ms if has_amb else 300.0)
    prev: str | None = None

    def _sfx_ms(cue) -> tuple[float, str | None]:
        if cue.custom and cue.audio_path and Path(cue.audio_path).exists():
            return _audio_ms(Path(cue.audio_path)), cue.audio_path
        p = proj.sfx_clip_path(cue)
        return cue.length_s * 1000.0, (str(p) if p.exists() else None)

    for line in body_lines:
        cursor += _gap(line.speaker_id, prev)
        cursor += line.delivery.pre_pause_ms or 0
        cdur, cpath, est = _clip(line)
        lane = LANE_NARRATOR if line.speaker_id == NARR else LANE_CHARACTERS
        start = cursor
        segs.append(TimelineSegment(
            id=_new_id("v"), kind="voice", lane=lane, start_ms=start,
            duration_ms=cdur, line_id=line.line_id, speaker_id=line.speaker_id,
            text=line.text, audio_path=cpath, pitch_semitones=line.pitch_semitones,
            estimated=est))
        for cue in line.sfx:
            if cue.placement == "over":
                sdur, spath = _sfx_ms(cue)
                segs.append(TimelineSegment(
                    id=_new_id("s"), kind="sfx", lane=LANE_SFX,
                    start_ms=start + cue.position * cdur, duration_ms=sdur,
                    gain_db=cue.gain_db, fade_in_ms=cue.fade_in_ms,
                    fade_out_ms=cue.fade_out_ms, prompt=cue.prompt,
                    audio_path=spath, custom=cue.custom, line_id=line.line_id))
        cursor += cdur
        cursor += line.delivery.post_pause_ms or 0
        for cue in line.sfx:
            if cue.placement == "gap":
                sdur, spath = _sfx_ms(cue)
                segs.append(TimelineSegment(
                    id=_new_id("s"), kind="sfx", lane=LANE_SFX, start_ms=cursor,
                    duration_ms=sdur, gain_db=cue.gain_db, fade_in_ms=cue.fade_in_ms,
                    fade_out_ms=cue.fade_out_ms, prompt=cue.prompt,
                    audio_path=spath, custom=cue.custom, line_id=line.line_id))
                cursor += sdur + 180
        prev = line.speaker_id

    cursor += 400.0
    if has_amb:
        from app.services import ambience
        segs.append(TimelineSegment(
            id=_new_id("a"), kind="ambience", lane=LANE_AMBIENCE,
            start_ms=body_start, duration_ms=cursor - body_start,
            gain_db=CONFIG.tts.ambience_gain_db, fade_in_ms=1200, fade_out_ms=1500,
            prompt=ambience.ambience_for_chapter(chapter)[0],
            audio_path=str(proj.ambience_path(chapter.chapter_id))))

    return Timeline(chapter_id=chapter.chapter_id, duration_ms=cursor, segments=segs)


def get_or_derive(chapter: Chapter) -> Timeline:
    """Return the saved timeline, or derive + persist one if none exists yet."""
    proj = project_service.active()
    tl = load_timeline(proj, chapter.chapter_id)
    if tl is None:
        tl = derive_timeline(chapter)
        save_timeline(proj, tl)
    return tl


def assemble_timeline(chapter: Chapter, timeline: Timeline | None = None) -> str | None:
    """Render + master + export the chapter MP3 straight from its timeline."""
    from app.services import chapter_render
    if timeline is None:
        timeline = get_or_derive(chapter)
    return chapter_render.export_mix(chapter, build_from_timeline(timeline))


def build_from_timeline(timeline: Timeline, load=None):
    """Render the chapter mix straight from the timeline placements (WYSIWYG)."""
    from pydub import AudioSegment
    from app.services import sound_service
    if load is None:
        load = AudioSegment.from_file

    total = int(max([timeline.duration_ms] + [s.start_ms + s.duration_ms for s in timeline.segments] or [0]))
    if total <= 0:
        return None
    mix = AudioSegment.silent(duration=total)

    def _pitch(seg_audio, semitones: float):
        if not semitones:
            return seg_audio
        factor = 2.0 ** (semitones / 12.0)
        shifted = seg_audio._spawn(seg_audio.raw_data,
                                   overrides={"frame_rate": int(seg_audio.frame_rate * factor)})
        return shifted.set_frame_rate(seg_audio.frame_rate)

    for seg in sorted(timeline.segments, key=lambda s: s.start_ms):
        if not seg.audio_path or not Path(seg.audio_path).exists():
            continue
        try:
            clip = load(seg.audio_path)
        except Exception:  # noqa: BLE001
            logger.warning("timeline: cannot load %s", seg.audio_path, exc_info=True)
            continue
        if seg.kind == "ambience":
            clip = sound_service.seamless_loop(clip, int(seg.duration_ms))
        if seg.kind == "voice" and seg.pitch_semitones:
            clip = _pitch(clip, seg.pitch_semitones)
        if seg.gain_db:
            clip = clip.apply_gain(seg.gain_db)
        if seg.fade_in_ms:
            clip = clip.fade_in(int(seg.fade_in_ms))
        if seg.fade_out_ms:
            clip = clip.fade_out(int(seg.fade_out_ms))
        mix = mix.overlay(clip, position=int(max(0, seg.start_ms)))
    return mix
