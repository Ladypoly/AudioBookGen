"""Voice library + assignment.

A shared library of reusable voice references (one WAV/MP3 + metadata each),
persisted as JSON. Characters reference a voice by id (Character.assigned_voice_id).
Kept separate from the TTS engine so the library is reusable across engines.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from app.core.config import CONFIG
from app.schemas.voice import Voice

logger = logging.getLogger(__name__)


def _library_dir() -> Path:
    d = CONFIG.tts.library_dir
    (d / "samples").mkdir(parents=True, exist_ok=True)
    return d


def _registry_file() -> Path:
    return _library_dir() / "voices.json"


def _slug(name: str) -> str:
    s = name.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "voice"


def list_voices() -> list[Voice]:
    f = _registry_file()
    if not f.exists():
        return []
    return [Voice.model_validate(v) for v in json.loads(f.read_text(encoding="utf-8"))]


def _save_all(voices: list[Voice]) -> None:
    _registry_file().write_text(
        json.dumps([v.model_dump() for v in voices], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_voice(voice_id: str) -> Voice | None:
    return next((v for v in list_voices() if v.voice_id == voice_id), None)


def import_voice(
    audio_path: str | Path,
    name: str,
    ref_text: str = "",
    tags: list[str] | None = None,
    gender: str = "unknown",
    age: str = "unknown",
) -> Voice:
    """Copy a reference clip into the library and register it."""
    src = Path(audio_path)
    if not src.exists():
        raise FileNotFoundError(src)
    voices = list_voices()
    vid = base = _slug(name)
    i = 1
    existing = {v.voice_id for v in voices}
    while vid in existing:
        i += 1
        vid = f"{base}_{i}"
    dst = _library_dir() / "samples" / f"{vid}{src.suffix.lower()}"
    shutil.copy2(src, dst)
    voice = Voice(
        voice_id=vid, name=name, ref_audio_path=str(dst), ref_text=ref_text,
        tags=tags or [], gender=gender, age=age,
    )
    voices.append(voice)
    _save_all(voices)
    logger.info("Imported voice %s -> %s", name, dst)
    return voice


def update_voice(voice: Voice) -> None:
    voices = [voice if v.voice_id == voice.voice_id else v for v in list_voices()]
    _save_all(voices)


def archive_voice(voice_id: str) -> None:
    voices = list_voices()
    for v in voices:
        if v.voice_id == voice_id:
            v.archived = True
    _save_all(voices)
