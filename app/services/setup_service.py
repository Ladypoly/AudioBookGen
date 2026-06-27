"""First-run environment setup: detect Ollama / ComfyUI and install the
`tts_audio_suite` custom node.

The packaged app ships the sidecar + frontend, but the GPU backends (Ollama,
ComfyUI portable + the tts_audio_suite node) are external. This service powers
the first-run wizard: validate the ComfyUI path, check whether the node is
present, and (one click) clone + pip-install it into the portable ComfyUI.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import CONFIG

logger = logging.getLogger(__name__)

NODE_NAME = "tts_audio_suite"               # folder name == --whitelist-custom-nodes name
NODE_REPO = "https://github.com/diodiogod/TTS-Audio-Suite"


def comfy_root() -> Path:
    return Path(CONFIG.comfy.comfy_dir)


def validate_comfy_dir(path: str | Path) -> bool:
    """A ComfyUI portable folder has ComfyUI/main.py + python_embeded/python.exe."""
    p = Path(path)
    return (p / "ComfyUI" / "main.py").exists() and (p / "python_embeded" / "python.exe").exists()


def node_dir(root: Path | None = None) -> Path:
    root = root or comfy_root()
    return root / "ComfyUI" / "custom_nodes" / NODE_NAME


def git_available() -> bool:
    return shutil.which("git") is not None


def status() -> dict:
    root = comfy_root()
    valid = validate_comfy_dir(root)
    return {
        "comfy_dir": str(root),
        "comfy_dir_valid": valid,
        "node_installed": valid and node_dir(root).exists(),
        "git_available": git_available(),
        "node_repo": NODE_REPO,
    }


def _stream(cmd: list[str], emit, ctx, cwd: str | None = None) -> None:
    """Run a command, streaming merged stdout/stderr line-by-line to `emit`.
    Raises on a non-zero exit so the job fails with a clear message."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace", creationflags=flags,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if ctx.cancelled:
            proc.kill()
            raise RuntimeError("Cancelled")
        emit(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"`{cmd[0]} …` failed (exit {proc.returncode}). See the log above.")


def install_node(ctx) -> dict:
    """Clone (or update) tts_audio_suite into the portable ComfyUI and pip-install
    its requirements with the embedded Python. Streams a live log via job meta."""
    root = comfy_root()
    if not validate_comfy_dir(root):
        raise RuntimeError(f"ComfyUI not found at {root}. Set the ComfyUI folder first.")
    if not git_available():
        raise RuntimeError("git is not installed or not on PATH. Install Git for Windows, then retry.")

    target = node_dir(root)
    py = root / "python_embeded" / "python.exe"
    log: list[str] = []

    def emit(line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        log.append(line)
        if len(log) > 300:
            del log[0]
        ctx.update_meta(log=list(log))     # streamed to the wizard
        ctx.step(line[:140])

    if target.exists():
        ctx.busy("Updating tts_audio_suite…")
        emit(f"Node already present at {target} — pulling latest.")
        _stream(["git", "-C", str(target), "pull", "--ff-only"], emit, ctx)
    else:
        ctx.busy("Cloning TTS-Audio-Suite…")
        target.parent.mkdir(parents=True, exist_ok=True)
        _stream(["git", "clone", "--depth", "1", NODE_REPO, str(target)], emit, ctx)

    req = target / "requirements.txt"
    if req.exists():
        ctx.busy("Installing node dependencies (this can take several minutes)…")
        _stream([str(py), "-m", "pip", "install", "-r", str(req)], emit, ctx, cwd=str(target))
    else:
        emit("No requirements.txt in the node — skipping dependency install.")

    emit("Done. Restart ComfyUI (or the app) so the node loads.")
    return {"installed": True, "path": str(target)}
