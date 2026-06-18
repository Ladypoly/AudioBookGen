"""pip-install a package in the background (for on-demand optimizer models)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

from PySide6.QtCore import QObject, QThread, Signal

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

LOG_DIR = PROJECT_ROOT / "logs"


class InstallWorker(QThread):
    done = Signal(bool, str)   # success, short message (with log path on failure)

    def __init__(self, package: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._package = package

    def run(self) -> None:  # noqa: D102
        try:
            env = os.environ.copy()
            # DeepSpeed (pulled by resemble-enhance) tries to pre-compile CUDA
            # ops like async_io at install — which fails on Windows (no libaio).
            # Disable op pre-compile so the wheel installs; ops JIT later if used.
            env.setdefault("DS_BUILD_OPS", "0")
            env.setdefault("DS_BUILD_AIO", "0")
            env.setdefault("DS_BUILD_SPARSE_ATTN", "0")

            res = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "--no-warn-script-location", self._package],
                capture_output=True, text=True, env=env,
            )
            out = (res.stdout or "") + "\n" + (res.stderr or "")
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self._package)
            log = LOG_DIR / f"install_{safe}.log"
            log.write_text(out, encoding="utf-8", errors="replace")

            if res.returncode == 0:
                self.done.emit(True, "")
                return
            # Surface the most useful line, not a blind tail.
            errs = [l.strip() for l in out.splitlines()
                    if l.strip().startswith("ERROR") or "error:" in l.lower()]
            tail = errs[-1] if errs else out.strip()[-300:]
            self.done.emit(False, f"{tail}  ·  full log: {log}")
        except Exception as err:  # noqa: BLE001
            logger.exception("pip install %s failed", self._package)
            self.done.emit(False, str(err))
