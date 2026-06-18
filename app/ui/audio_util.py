"""Tiny audio playback helper (OS default player, no extra deps)."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def play_audio(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:  # noqa: BLE001
        logger.exception("Could not play %s", path)
