"""Keep downloaded model weights inside the project (models/) instead of the
user's home cache, so the app stays self-contained and portable.

Most libraries honour env vars (TORCH_HOME, HF_HOME, XDG_CACHE_HOME); VoiceFixer
hard-codes ~/.cache/voicefixer with no override, so we junction that into the
project (migrating any existing download). Call setup() at the very top of
startup, before torch / the optimizer libs are imported.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

MODELS_DIR = PROJECT_ROOT / "models"


def setup() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    # Env-controlled caches (read at import time by each library).
    os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "torch"))           # demucs/torchaudio hub
    os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(MODELS_DIR / "huggingface" / "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(MODELS_DIR / "huggingface"))
    os.environ.setdefault("XDG_CACHE_HOME", str(MODELS_DIR / "cache"))       # *nix libs (~/.cache)
    os.environ.setdefault("DEEPFILTERNET_MODEL_DIR", str(MODELS_DIR / "deepfilternet"))
    _redirect_voicefixer()


def _redirect_voicefixer() -> None:
    """Point ~/.cache/voicefixer at models/voicefixer via a Windows junction
    (no admin needed) or a symlink, migrating an existing download first."""
    target = MODELS_DIR / "voicefixer"
    target.mkdir(parents=True, exist_ok=True)
    link = Path(os.path.expanduser("~")) / ".cache" / "voicefixer"
    try:
        if link.exists() and os.path.realpath(link) == os.path.realpath(target):
            return                                   # already redirected
        if link.exists():                            # migrate prior download
            for item in link.iterdir():
                dest = target / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            try:
                link.rmdir()
            except OSError:
                logger.info("voicefixer cache not empty; leaving in place")
                return
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True)
        else:
            link.symlink_to(target, target_is_directory=True)
        logger.info("voicefixer cache -> %s", target)
    except Exception:  # noqa: BLE001
        logger.warning("could not redirect voicefixer cache", exc_info=True)
