"""ComfyUI process manager — lean, per-stage launches.

Brings up ComfyUI with ONLY the custom nodes a stage needs, so the 24 GB GPU
is never shared between the LLM and a render backend, and ComfyUI never loads
~100 unused extensions (PLAN: memory-safe scheduler).

Builds the launch command directly (rather than calling the .bat) so the
tracked process IS the server and can be terminated cleanly.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

import httpx

from app.core.config import CONFIG
from app.services import comfy_service

logger = logging.getLogger(__name__)


class LauncherError(RuntimeError):
    pass


# Serializes single (card-triggered) renders so concurrent "Generate" clicks
# queue one at a time instead of racing stage management on one ComfyUI.
RENDER_LOCK = threading.Lock()

_process: subprocess.Popen | None = None
_current_stage: str | None = None
_pool: list[subprocess.Popen] = []
_pool_urls: list[str] = []


def _base_port() -> int:
    return int(CONFIG.comfy.base_url.rsplit(":", 1)[-1])


def _url(port: int) -> str:
    host = CONFIG.comfy.base_url.rsplit(":", 1)[0]
    return f"{host}:{port}"


def _build_command(stage_name: str, port: int) -> list[str]:
    cfg = CONFIG.comfy
    stage = cfg.stages[stage_name]
    py = cfg.comfy_dir / "python_embeded" / "python.exe"
    main = cfg.comfy_dir / "ComfyUI" / "main.py"
    if not py.exists():
        raise LauncherError(f"ComfyUI python not found: {py}")
    cmd = [
        str(py), "-s", str(main),
        "--windows-standalone-build",
        "--listen", "127.0.0.1",
        "--port", str(port),
        "--cache-classic",
        "--disable-auto-launch",   # don't pop open the browser UI
        "--disable-all-custom-nodes",
    ]
    if stage.whitelist:
        cmd += ["--whitelist-custom-nodes", *stage.whitelist]
    if stage.sage_attention:
        cmd.append("--use-sage-attention")
    return cmd


def _spawn(stage_name: str, port: int) -> subprocess.Popen:
    cfg = CONFIG.comfy
    cmd = _build_command(stage_name, port)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    logger.info("Launching ComfyUI headless stage=%s port=%d", stage_name, port)
    return subprocess.Popen(cmd, cwd=str(cfg.comfy_dir), creationflags=flags)


def is_running() -> bool:
    return comfy_service.health_check()


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def stop() -> None:
    """Terminate all ComfyUI processes this app started, then sweep the ports to
    catch any orphaned/externally-started instance too."""
    global _process, _current_stage, _pool, _pool_urls
    procs = [p for p in ([_process] + _pool) if p is not None]
    if procs:
        logger.info("Stopping %d ComfyUI process(es) (stage=%s)", len(procs), _current_stage)
    for p in procs:
        _terminate(p)
    _process = None
    _pool = []
    _pool_urls = []
    _current_stage = None
    # Belt-and-suspenders: kill whatever still holds any pool port.
    for i in range(max(1, CONFIG.comfy.parallel)):
        _kill_on_port(_base_port() + i)


# Ensure ComfyUI is stopped even if the app exits without a clean closeEvent.
import atexit  # noqa: E402

atexit.register(stop)


# One persistent ComfyUI serves every stage: it's launched once (with
# tts_audio_suite whitelisted) and stays up for the app's lifetime, so there's
# no per-stage relaunch/boot cost. The whitelist covers TTS (tts_audio_suite)
# while Stable-Audio and Z-Image are core nodes.
_UNIVERSAL_STAGE = "tts"


def start(wait: bool = False) -> None:
    """Launch the single persistent ComfyUI (call once at app startup). With
    wait=False it returns immediately; the first render waits for health."""
    _ensure_single(wait=wait)


def _ensure_single(wait: bool = True) -> None:
    global _process, _current_stage
    cfg = CONFIG.comfy
    if not cfg.manage_process:
        if wait and not is_running():
            raise LauncherError("ComfyUI is not running and manage_process is off.")
        return
    if _process is not None and _process.poll() is None:        # already launched
        if wait and not is_running():
            _wait_until_healthy(_url(_base_port()), _process)
        return
    _kill_on_port(_base_port())
    logger.info("Launching persistent ComfyUI (whitelist=%s)", _UNIVERSAL_STAGE)
    _process = _spawn(_UNIVERSAL_STAGE, _base_port())
    _current_stage = _UNIVERSAL_STAGE
    if wait:
        _wait_until_healthy(_url(_base_port()), _process)


def ensure_stage(stage_name: str) -> None:
    """Ensure the single persistent ComfyUI is up and healthy. The stage name is
    informational now — one instance serves them all (no relaunch/switch)."""
    _ensure_single(wait=True)


def ensure_pool(stage_name: str, n: int | None = None) -> list[str]:
    """Render in parallel across `n` instances: the persistent base plus (n-1)
    extra ones (ports base+1…). Returns all URLs. The extras stay up (reused by
    the next batch); release_pool() stops them to free VRAM (e.g. before the LLM)."""
    global _pool, _pool_urls
    cfg = CONFIG.comfy
    n = n or cfg.parallel
    _ensure_single(wait=True)
    base = _base_port()
    urls = [_url(base)]
    if n <= 1 or not cfg.manage_process:
        return urls
    if len(_pool_urls) == n - 1 and all(comfy_service.health_check(u) for u in _pool_urls):
        return urls + list(_pool_urls)
    release_pool()
    extras, extra_urls = [], []
    for i in range(1, n):
        port = base + i
        _kill_on_port(port)
        extras.append(_spawn(_UNIVERSAL_STAGE, port))
        extra_urls.append(_url(port))
    for proc, url in zip(extras, extra_urls):
        _wait_until_healthy(url, proc)
    _pool, _pool_urls = extras, extra_urls
    logger.info("ComfyUI render pool ready: %d instances", n)
    return urls + extra_urls


def release_pool() -> None:
    """Stop the extra pool instances (keep the persistent base running)."""
    global _pool, _pool_urls
    if _pool:
        logger.info("Releasing %d extra ComfyUI instance(s)", len(_pool))
    for p in _pool:
        _terminate(p)
    for i in range(1, max(2, CONFIG.comfy.parallel)):
        _kill_on_port(_base_port() + i)
    _pool, _pool_urls = [], []


def free_vram() -> None:
    """Ask ComfyUI to unload its models and free VRAM — call before a VRAM-heavy
    Ollama step so the persistent instance doesn't starve it."""
    if not CONFIG.comfy.manage_process or _process is None:
        return
    try:
        with httpx.Client(timeout=15.0) as client:
            client.post(_url(_base_port()) + "/free",
                        json={"unload_models": True, "free_memory": True})
        logger.info("Asked ComfyUI to free VRAM")
    except Exception:  # noqa: BLE001
        logger.debug("ComfyUI /free failed", exc_info=True)


def _kill_on_port(port: int) -> None:
    """Kill whatever process is listening on a ComfyUI port (Windows)."""
    if sys.platform != "win32":
        return
    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="replace"
    ).stdout
    # Locale-independent: a listening socket has local addr ...:<port> and a
    # foreign addr of 0.0.0.0:0 (the state word is localized, e.g. "ABHÖREN").
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[2] == "0.0.0.0:0":
            pids.add(parts[-1])
    for pid in pids:
        if pid != "0":
            subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
    if pids:
        time.sleep(2)


def _wait_until_healthy(url: str, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + CONFIG.comfy.startup_timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise LauncherError("ComfyUI process exited during startup.")
        try:
            with httpx.Client(timeout=3.0) as client:
                client.get(f"{url.rstrip('/')}/system_stats").raise_for_status()
            logger.info("ComfyUI ready: %s", url)
            return
        except httpx.HTTPError:
            time.sleep(1.5)
    raise LauncherError(f"ComfyUI did not become healthy: {url}")
