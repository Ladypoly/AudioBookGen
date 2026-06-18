"""User settings: edit CONFIG values from the UI, persist them to JSON.

A flat schema maps each editable setting to a dotted path on CONFIG. Settings
load on startup and apply onto CONFIG; the Settings screen reads/writes them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import CONFIG, PROJECT_ROOT

logger = logging.getLogger(__name__)

SETTINGS_FILE = PROJECT_ROOT / "settings.json"

# (section, label, CONFIG dotted-path, kind, choices)
FIELDS: list[tuple] = [
    ("LLM", "Backend", "ollama.backend", "choice", ["ollama", "openai"]),
    ("LLM", "Ollama URL", "ollama.base_url", "str", None),
    ("LLM", "Ollama model", "ollama.model", "str", None),
    ("LLM", "API base URL (OpenRouter/vLLM/…)", "ollama.api_base_url", "str", None),
    ("LLM", "API key", "ollama.api_key", "password", None),
    ("LLM", "API model", "ollama.api_model", "str", None),
    ("LLM", "Temperature", "ollama.temperature", "float", None),

    ("ComfyUI", "ComfyUI install dir", "comfy.comfy_dir", "path", None),
    ("ComfyUI", "ComfyUI URL", "comfy.base_url", "str", None),
    ("ComfyUI", "Parallel instances", "comfy.parallel", "int", None),
    ("ComfyUI", "App manages ComfyUI", "comfy.manage_process", "bool", None),

    ("Workflows", "Portrait workflow", "comfy.portrait_workflow", "str", None),
    ("Workflows", "Voice-design workflow", "comfy.voicedesign_workflow", "str", None),
    ("Workflows", "TTS workflow", "comfy.tts_workflow", "str", None),
    ("Workflows", "SFX/Audio workflow", "comfy.audio_workflow", "str", None),

    ("Audio / Mix", "Gap — same speaker (ms)", "tts.chapter_gap_same_ms", "int", None),
    ("Audio / Mix", "Gap — speaker change (ms)", "tts.chapter_gap_turn_ms", "int", None),
    ("Audio / Mix", "Gap — narrator↔dialogue (ms)", "tts.chapter_gap_narrator_ms", "int", None),
    ("Audio / Mix", "Ambience level (dB)", "tts.ambience_gain_db", "float", None),
    ("Audio / Mix", "Ambience establish level (dB)", "tts.ambience_establish_gain_db", "float", None),
    ("Audio / Mix", "Ambience establish time (ms)", "tts.ambience_establish_ms", "int", None),
    ("Audio / Mix", "Master loudness (LUFS)", "tts.master_lufs", "float", None),
    ("Audio / Mix", "Master true-peak (dBTP)", "tts.master_tp", "float", None),
    ("Audio / Mix", "Mastering on", "tts.master_enabled", "bool", None),
    ("Audio / Mix", "Ambience on", "tts.ambience_enabled", "bool", None),
    ("Audio / Mix", "SFX on", "tts.sfx_enabled", "bool", None),
    ("Audio / Mix", "Intro music on", "tts.music_enabled", "bool", None),
    ("Audio / Mix", "Music level (dB)", "tts.music_gain_db", "float", None),
    ("Audio / Mix", "Music length (s)", "tts.music_seconds", "float", None),

    ("Voice", "Design accent", "tts.design_accent", "choice",
     ["British English", "American English", "Australian English", "Irish English",
      "Scottish English", "Canadian English", "neutral English"]),
    ("Voice", "Design language", "tts.design_language", "choice", ["English", "Chinese"]),
    ("Voice", "Optimize loudness target (LUFS)", "tts.voice_norm_lufs", "float", None),
    ("Voice", "Optimize true-peak (dBTP)", "tts.voice_norm_tp", "float", None),

    ("Export", "MP3 bitrate", "tts.mp3_bitrate", "choice",
     ["96k", "128k", "160k", "192k", "256k", "320k"]),

    ("Extraction", "Web search (bio/afterword/enrich)", "extraction.web_search", "bool", None),
    ("Extraction", "Front matter (Vorwort)", "extraction.front_matter", "bool", None),
    ("Extraction", "Afterword (Nachwort)", "extraction.afterword", "bool", None),
    ("Extraction", "Chunk size (chars)", "extraction.chunk_chars", "int", None),
    ("Extraction", "Chunk overlap (chars)", "extraction.chunk_overlap_chars", "int", None),
    ("Extraction", "Web results", "extraction.web_results", "int", None),
    ("Extraction", "Enrich top-N online", "extraction.web_enrich_top_n", "int", None),

    ("Portrait", "Art style", "portrait_style.art_style", "str", None),
    ("Portrait", "Negative prompt", "portrait_style.negative_prompt", "str", None),
    ("Portrait", "Width", "portrait_style.width", "int", None),
    ("Portrait", "Height", "portrait_style.height", "int", None),

    ("Performance", "ComfyUI startup timeout (s)", "comfy.startup_timeout_s", "float", None),
    ("Performance", "Render timeout (s)", "comfy.request_timeout_s", "float", None),
    ("Performance", "TTS timeout (s)", "comfy.tts_timeout_s", "float", None),
    ("Performance", "Audio/SFX timeout (s)", "comfy.audio_timeout_s", "float", None),
    ("Performance", "LLM request timeout (s)", "ollama.request_timeout_s", "float", None),
    ("Performance", "LLM context (num_ctx)", "ollama.num_ctx", "int", None),
    ("Performance", "LLM max tokens (num_predict)", "ollama.num_predict", "int", None),
]


def _get(path: str):
    obj = CONFIG
    for p in path.split("."):
        obj = getattr(obj, p)
    return obj


def _set(path: str, value) -> None:
    obj = CONFIG
    parts = path.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    cur = getattr(obj, parts[-1])
    if isinstance(cur, bool):
        value = bool(value)
    elif isinstance(cur, Path):
        value = Path(value)
    elif isinstance(cur, int) and not isinstance(cur, bool):
        value = int(value)
    elif isinstance(cur, float):
        value = float(value)
    setattr(obj, parts[-1], value)


def current() -> dict:
    """All editable settings as {path: value}."""
    return {f[2]: _get(f[2]) for f in FIELDS}


def load_and_apply() -> None:
    """Apply saved settings onto CONFIG (call once at startup)."""
    if not SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("settings.json unreadable", exc_info=True)
        return
    for path, val in data.items():
        try:
            _set(path, val)
        except Exception:  # noqa: BLE001
            logger.debug("skip setting %s", path, exc_info=True)


def save(values: dict) -> None:
    """Apply {path: value} onto CONFIG and persist every editable field."""
    for path, val in values.items():
        _set(path, val)
    data = {f[2]: (str(_get(f[2])) if isinstance(_get(f[2]), Path) else _get(f[2]))
            for f in FIELDS}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("settings saved (%d fields)", len(data))
