"""Render a chapter to audio: one Higgs line per LineItem, then assemble.

Each line is spoken by its assigned character's voice (narration by the
narrator). Line clips are concatenated with pauses into a chapter mix.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.schemas.characters import Character
from app.schemas.script import Chapter, LineItem, LineType
from app.schemas.voice import Voice
from app.services import project_service, render_pool
from app.services.tts import registry
from app.services.tts.base import TTSRequest

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]
CancelCb = Callable[[], bool]

def _voice_for(speaker_id: str, by_id: dict[str, Character], proj) -> Voice | None:
    c = by_id.get(speaker_id)
    if not c:
        return None  # engine falls back to the default reference
    if c.custom_voice and c.voice_sample:
        # User-supplied clip — clone it directly, no preview indirection.
        ref = c.voice_sample
    else:
        # Prefer the native-German Higgs Hörprobe as the clone reference: the
        # Qwen voice_sample is *English* speech, so cloning it makes German
        # sound accented. The preview is already German in this timbre.
        preview = proj.preview_path(c.character_id)
        ref = str(preview) if preview.exists() else c.voice_sample
    if ref:
        return Voice(voice_id=c.character_id, name=c.display_name, ref_audio_path=ref,
                     gender=c.gender_guess.value, age=c.age_band.value)
    return None


def render_lines(
    chapter: Chapter, characters: list[Character],
    progress: ProgressCb | None = None, is_cancelled: CancelCb | None = None,
    urls: list[str] | None = None, force: bool = False,
) -> Chapter:
    """Render every line of the chapter to an audio clip.

    If `urls` (a ComfyUI pool) is given, lines render in parallel across them;
    otherwise sequentially against the default target. `force` re-renders even
    lines that already have a clip (e.g. after a voice/quality change)."""
    proj = project_service.active()
    by_id = {c.character_id: c for c in characters}
    engine = registry.get_engine()
    out_dir = proj.line_audio_dir / chapter.chapter_id
    out_dir.mkdir(parents=True, exist_ok=True)

    def render_one(line: LineItem) -> None:
        out = out_dir / f"{line.line_id}.mp3"
        if out.exists() and not force:   # resume: skip already-rendered lines
            line.audio_path = str(out)
            return
        try:
            engine.synthesize(TTSRequest(
                text=line.text, voice=_voice_for(line.speaker_id, by_id, proj),
                delivery=line.delivery, out_path=out,
            ))
            line.audio_path = str(out)
        except Exception:  # noqa: BLE001
            logger.exception("Line render failed: %s", line.line_id)

    total = len(chapter.lines)
    if urls and len(urls) > 1:
        render_pool.map_over_pool(
            urls, chapter.lines, render_one,
            on_done=(lambda d, t: progress(d, t, "")) if progress else None,
            is_cancelled=is_cancelled,
        )
    else:
        for i, line in enumerate(chapter.lines, start=1):
            if is_cancelled and is_cancelled():
                break
            if progress:
                who = by_id.get(line.speaker_id)
                progress(i - 1, total, who.display_name if who else line.speaker_id)
            render_one(line)
    return chapter


def _master(path: Path, lufs: float, tp: float) -> None:
    """Normalise a finished mix to a target loudness with true-peak limiting
    (ffmpeg loudnorm), in place. No-op if ffmpeg is unavailable."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        return
    tmp = path.with_name(path.stem + ".norm.mp3")
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-af", f"loudnorm=I={lufs}:TP={tp}:LRA=11",
        "-c:a", "libmp3lame", "-b:a", "192k", str(tmp),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        logger.warning("Mastering failed for %s: %s", path.name, res.stderr[-300:])
        tmp.unlink(missing_ok=True)


def build_chapter_mix(chapter: Chapter, load=None):
    """Build the full chapter mix in memory (clips + gaps + ambience + SFX +
    optional music) and return the AudioSegment — NO mastering/export. `load`
    decodes a path to an AudioSegment (override with a cache for a live mix)."""
    from pydub import AudioSegment
    if load is None:
        load = AudioSegment.from_file

    proj = project_service.active()
    rendered = [l for l in chapter.lines if l.audio_path and Path(l.audio_path).exists()]
    if not rendered:
        return None

    from app.core.config import CONFIG
    from app.services import sfx_planner
    from app.services.line_planner import NARRATOR_ID
    gap_same = CONFIG.tts.chapter_gap_same_ms
    gap_turn = CONFIG.tts.chapter_gap_turn_ms
    gap_narr = CONFIG.tts.chapter_gap_narrator_ms

    def _gap(cur: str, prev: str | None) -> int:
        if cur == prev:
            return gap_same
        if NARRATOR_ID in (cur, prev):   # narrator <-> a character
            return gap_narr
        return gap_turn                  # character <-> different character

    # Discrete SFX cues (narration only) — generated separately; overlay any
    # whose clip exists. Annotation is deterministic so it matches generation.
    sfx_planner.annotate(chapter.lines)
    _sfx_cache: dict = {}

    def _sfx(cue):
        if not CONFIG.tts.sfx_enabled:
            return None
        p = proj.sfx_clip_path(cue)
        if not p.exists():
            return None
        if p not in _sfx_cache:
            _sfx_cache[p] = load(p)
        return _sfx_cache[p].apply_gain(cue.gain_db)

    def _clip(line) -> "AudioSegment":
        """Render a line's clip with its 'over' SFX overlaid."""
        c = load(line.audio_path)
        for cue in line.sfx:
            if cue.placement == "over":
                s = _sfx(cue)
                if s is not None:
                    c = c.overlay(s, position=int(max(0, min(len(c) - 1, cue.position * len(c)))))
        return c

    # Chapter structure: the narrator's title line plays DRY first; then the
    # ambience fades in for ~2 s to paint the scene; then it ducks to the bed
    # level and the content lines start. No intro music.
    amb_file = proj.ambience_path(chapter.chapter_id)
    has_amb = amb_file.exists() and CONFIG.tts.ambience_enabled
    title_line = rendered[0] if (
        chapter.number > 0 and rendered[0].line_id.endswith("_l0000")) else None
    body_lines = rendered[1:] if title_line else rendered

    body = AudioSegment.silent(duration=CONFIG.tts.ambience_establish_ms if has_amb else 300)
    prev_speaker: str | None = None
    for line in body_lines:
        body += AudioSegment.silent(duration=_gap(line.speaker_id, prev_speaker))
        if line.delivery and line.delivery.pre_pause_ms:
            body += AudioSegment.silent(duration=line.delivery.pre_pause_ms)
        body += _clip(line)
        if line.delivery and line.delivery.post_pause_ms:
            body += AudioSegment.silent(duration=line.delivery.post_pause_ms)
        for cue in line.sfx:           # "gap": play in the pause after the line
            if cue.placement == "gap":
                s = _sfx(cue)
                if s is not None:
                    body += s + AudioSegment.silent(duration=180)
        prev_speaker = line.speaker_id
    body += AudioSegment.silent(duration=400)

    # Ambience over the body: fade in to the establish level over ~2 s, then
    # ramp down to the background bed level as the speakers begin.
    if has_amb:
        try:
            from app.services import sound_service
            raw = sound_service.seamless_loop(load(amb_file), len(body))
            bed_db = CONFIG.tts.ambience_gain_db
            swell_db = CONFIG.tts.ambience_establish_gain_db
            est = CONFIG.tts.ambience_establish_ms
            trans = 1200
            if len(raw) > est + trans:
                head = raw[:est].apply_gain(swell_db).fade_in(est)
                mid = raw[est:est + trans].fade(
                    from_gain=swell_db, to_gain=bed_db, start=0, duration=trans)
                tail = raw[est + trans:].apply_gain(bed_db)
                bed = (head + mid + tail).fade_out(1500)
            else:
                bed = raw.apply_gain(bed_db).fade_in(800).fade_out(1500)
            body = body.overlay(bed)
            logger.info("Ambience fade-in+duck for %s", chapter.chapter_id)
        except Exception:  # noqa: BLE001
            logger.exception("Ambience overlay failed for %s", chapter.chapter_id)

    # Title (dry) → short beat → ambience-scene body.
    if title_line is not None:
        mix = _clip(title_line) + AudioSegment.silent(duration=550) + body
    else:
        mix = body

    # Optional intro music (off by default; a Settings toggle).
    if CONFIG.tts.music_enabled:
        music_file = proj.music_path(chapter.chapter_id)
        if music_file.exists():
            try:
                intro = (load(music_file)
                         .apply_gain(CONFIG.tts.music_gain_db).fade_in(500).fade_out(2200))
                mix = intro + AudioSegment.silent(duration=350) + mix
            except Exception:  # noqa: BLE001
                logger.exception("Music intro failed for %s", chapter.chapter_id)
    return mix


def assemble(chapter: Chapter, suffix: str = "") -> str | None:
    """Build the chapter mix, master it and export a tagged MP3. Returns path."""
    from app.core.config import CONFIG
    from app.services import book_meta
    proj = project_service.active()
    mix = build_chapter_mix(chapter)
    if mix is None:
        return None
    proj.chapter_audio_dir.mkdir(parents=True, exist_ok=True)
    out = proj.chapter_audio_dir / f"{chapter.chapter_id}{suffix}.mp3"
    mix.export(out, format="mp3", bitrate=CONFIG.tts.mp3_bitrate)
    if CONFIG.tts.master_enabled:
        _master(out, CONFIG.tts.master_lufs, CONFIG.tts.master_tp)
    if not suffix:                       # tag the real chapter file (not _test)
        try:
            book_meta.tag_chapter_mp3(out, proj, chapter.number, chapter.title)
        except Exception:  # noqa: BLE001
            logger.exception("Tagging failed for %s", chapter.chapter_id)
    chapter.audio_path = str(out)
    logger.info("Assembled chapter %s -> %s (%.1fs)", chapter.chapter_id, out, len(mix) / 1000)
    return str(out)


def render_chapter(
    chapter: Chapter, characters: list[Character],
    progress: ProgressCb | None = None, is_cancelled: CancelCb | None = None,
    urls: list[str] | None = None, force: bool = False,
) -> Chapter:
    render_lines(chapter, characters, progress, is_cancelled, urls=urls, force=force)
    assemble(chapter)
    return chapter
