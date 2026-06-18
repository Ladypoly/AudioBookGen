"""TTS engine registry — pick the speech backend by name (config-driven).

Add a new engine by implementing TTSEngine and registering it here; switching
engines is then a single config value (CONFIG.tts.engine).
"""

from __future__ import annotations

from app.services.tts.base import TTSEngine
from app.services.tts.higgs import HiggsTTSEngine

_ENGINES: dict[str, TTSEngine] = {
    HiggsTTSEngine.name: HiggsTTSEngine(),
}


def get_engine(name: str | None = None) -> TTSEngine:
    from app.core.config import CONFIG

    key = name or CONFIG.tts.engine
    if key not in _ENGINES:
        raise ValueError(f"Unknown TTS engine: {key} (have {list(_ENGINES)})")
    return _ENGINES[key]
