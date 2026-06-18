"""TTS engine interface — the swap point for the speech backend.

Any engine (Higgs today, others later) implements TTSEngine. The rest of the
app talks only to this protocol, so changing engine = changing one config value
(see registry.get_engine). PLAN: "design so future engines can be swapped in".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.schemas.voice import Delivery, Voice


@dataclass
class TTSRequest:
    """Everything needed to render one spoken line, engine-agnostic."""

    text: str
    voice: Voice | None = None         # None -> engine default/neutral voice
    delivery: Delivery | None = None   # None -> neutral delivery
    seed: int = 0
    out_path: Path | None = None


class TTSEngine(Protocol):
    name: str

    def synthesize(self, request: TTSRequest, on_step=None) -> Path:
        """Render `request` to an audio file and return its path."""
        ...
