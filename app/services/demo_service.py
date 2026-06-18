"""Demo mode: a ~1-minute example Hörspiel for tuning the mix.

Generates the raw clips once (3 voices + ambience + SFX + optional music), then
remix() re-assembles them with the current settings (pauses, levels, ambience
envelope, mastering) in a second or two — so the waveform reflects setting
changes live, without regenerating anything.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import CONFIG, PROJECT_ROOT
from app.schemas.characters import AgeBand, Character, GenderGuess, RoleImportance
from app.schemas.script import Chapter, LineItem, LineType, SfxCue
from app.services import (
    chapter_render, comfy_launcher, line_planner, ollama_service, project_service,
    sfx_planner, sound_service,
)

logger = logging.getLogger(__name__)

DEMO_DIR = PROJECT_ROOT / "demo"
SPEAKERS = ("erzaehler", "char1", "char2")

DEMO_AMBIENCE = ("Calm harbour at dawn, gentle water lapping against a wooden dock, "
                 "distant seagulls, soft sea breeze, faint creaking mooring ropes")
DEMO_MUSIC = ("Warm reflective intro with soft felt piano and a gentle string pad, "
              "calm and a touch melancholic. BPM: 70")

# (type, speaker, text, emotion, style, [sfx (prompt, placement, length)])
DEMO_SCRIPT = [
    ("narration", "erzaehler", "Der Hafen erwachte im ersten Morgenlicht, grau und still.", "", "", []),
    ("narration", "erzaehler", "Weit draußen auf dem Wasser tutete ein Schiff durch den Nebel.", "", "",
     [("a distant ship foghorn echoing over calm water", "gap", 3.0)]),
    ("dialogue", "char1", "Bist du sicher, dass das Schiff heute überhaupt noch anlegt?", "", "", []),
    ("dialogue", "char2", "So sicher, wie die Möwen über unseren Köpfen kreisen.", "amusement", "", []),
    ("narration", "erzaehler", "Langsame Schritte hallten über die nassen Planken des Stegs.", "", "",
     [("slow footsteps on a wet wooden dock, close", "over", 4.0)]),
    ("dialogue", "char1", "Dann warten wir eben. So wie immer.", "contentment", "", []),
    ("dialogue", "char2", "Warte... hörst du das auch?", "fear", "whispering", []),
    ("narration", "erzaehler", "Aus dem Nebel schälte sich langsam ein gewaltiger, dunkler Schiffsrumpf.", "", "", []),
]


def demo_project() -> project_service.Project:
    return project_service.Project(title="Demo", root=DEMO_DIR, source_pdf="")


def _characters(voices: dict[str, str]) -> list[Character]:
    meta = {
        "erzaehler": (GenderGuess.ambiguous, RoleImportance.narrator, "Erzähler"),
        "char1": (GenderGuess.male, RoleImportance.main, "Charakter 1"),
        "char2": (GenderGuess.female, RoleImportance.main, "Charakter 2"),
    }
    out = []
    for sid in SPEAKERS:
        g, role, name = meta[sid]
        out.append(Character(
            character_id=sid, display_name=name, gender_guess=g, age_band=AgeBand.adult,
            role_importance=role, voice_sample=voices.get(sid) or None,
            custom_voice=bool(voices.get(sid))))
    return out


def _chapter() -> Chapter:
    lines = []
    for i, (typ, sp, text, emo, sty, sfx) in enumerate(DEMO_SCRIPT, start=1):
        cues = [SfxCue(prompt=p, placement=pl, length_s=ln) for p, pl, ln in sfx]
        lines.append(LineItem(
            line_id=f"demo_l{i:04d}", chapter_id="demo", index=i,
            type=LineType(typ), speaker_id=sp, text=text, sfx=cues,
            delivery=line_planner.delivery_from_agent(text, emo or None, sty or None)))
    return Chapter(chapter_id="demo", number=1, title="Demo", curated=True, lines=lines)


def demo_audio_path() -> Path:
    # WAV preview — fast to (re)export and decode for the live waveform.
    return DEMO_DIR / "mixes" / "chapters" / "demo_preview.wav"


# Decoded-clip cache so a live re-mix doesn't re-read clips from disk.
_clip_cache: dict = {}


def _seg(path):
    from pydub import AudioSegment
    key = str(path)
    if key not in _clip_cache:
        _clip_cache[key] = AudioSegment.from_file(key)
    return _clip_cache[key]


def _export_preview(ch) -> str:
    """Build the demo mix in memory (cached clips, NO mastering) and write a WAV.
    This is the fast path for live setting tweaks."""
    mix = chapter_render.build_chapter_mix(ch, load=_seg)
    if mix is None:
        return ""
    out = demo_audio_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    mix.export(out, format="wav")
    return str(out)


def has_clips() -> bool:
    """True if the demo line clips exist on disk (survive app restarts)."""
    out_dir = demo_project().line_audio_dir / "demo"
    return any((out_dir / f"{l.line_id}.mp3").exists() for l in _chapter().lines)


def default_voices() -> dict[str, str]:
    """Best-effort defaults: reuse a project's narrator + a male + a female voice."""
    out: dict[str, str] = {}
    for proj in project_service.list_projects():
        root = Path(proj["root"]) if isinstance(proj, dict) else None
        if not root:
            continue
        vdir = root / "voices"
        nar = vdir / "erzaehler_preview.mp3"
        if nar.exists():
            out["erzaehler"] = str(nar)
        # any two other previews as char1/char2
        previews = sorted(p for p in vdir.glob("*_preview.mp3") if "erzaehler" not in p.name)
        if previews:
            out.setdefault("char1", str(previews[0]))
        if len(previews) > 1:
            out.setdefault("char2", str(previews[1]))
        if len(out) >= 3:
            break
    return out


def generate(voices: dict[str, str], with_music: bool | None = None) -> str:
    """Render the demo clips (voices + ambience + SFX + music) then remix.
    Heavy — runs ComfyUI stages. Returns the demo audio path."""
    proj = demo_project()
    chars = _characters(voices)
    ch = _chapter()
    sfx_planner.annotate(ch.lines)
    prev = project_service.active()
    project_service.set_active(proj)
    try:
        ollama_service.unload()
        # scene audio (audio stage)
        comfy_launcher.ensure_stage("audio")
        if not proj.ambience_path("demo").exists():
            sound_service.generate(DEMO_AMBIENCE, 30.0, proj.ambience_path("demo"), kind="ambience")
        if (with_music if with_music is not None else CONFIG.tts.music_enabled) \
                and not proj.music_path("demo").exists():
            sound_service.generate(DEMO_MUSIC, CONFIG.tts.music_seconds,
                                   proj.music_path("demo"), kind="music")
        sfx_planner.generate_chapter_sfx(proj, ch)
        # voice lines (tts stage)
        comfy_launcher.ensure_stage("tts")
        chapter_render.render_lines(ch, chars, force=True)
        comfy_launcher.stop()
        _clip_cache.clear()              # fresh clips → drop stale cache
        for line in ch.lines:
            clip = proj.line_audio_dir / "demo" / f"{line.line_id}.mp3"
            if clip.exists():
                line.audio_path = str(clip)
        return _export_preview(ch)
    finally:
        project_service.set_active(prev)


def remix() -> str:
    """Fast in-memory live mix from cached clips (no re-rendering, no master)."""
    proj = demo_project()
    ch = _chapter()
    out_dir = proj.line_audio_dir / "demo"
    for line in ch.lines:
        clip = out_dir / f"{line.line_id}.mp3"
        if clip.exists():
            line.audio_path = str(clip)
    prev = project_service.active()
    project_service.set_active(proj)
    try:
        return _export_preview(ch)
    finally:
        project_service.set_active(prev)
