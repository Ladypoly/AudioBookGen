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


def ensure_stage(stage_name: str) -> None:
    """Guarantee ComfyUI is up for `stage_name`, restarting if the node set differs.

    No-op when manage_process is False (assumes the user launched the right
    workflow_launchers/*.bat) beyond a health check.
    """
    global _process, _current_stage
    cfg = CONFIG.comfy
    if stage_name not in cfg.stages:
        raise LauncherError(f"Unknown ComfyUI stage: {stage_name}")

    if not cfg.manage_process:
        if not is_running():
            raise LauncherError(
                f"ComfyUI is not running. Start workflow_launchers for the "
                f"'{stage_name}' stage, or enable manage_process."
            )
        return

    if _current_stage == stage_name and is_running():
        return

    stop()
    if is_running():
        _kill_on_port(_base_port())

    _process = _spawn(stage_name, _base_port())
    _current_stage = stage_name
    _wait_until_healthy(_url(_base_port()), _process)


def ensure_pool(stage_name: str, n: int | None = None) -> list[str]:
    """Launch `n` lean ComfyUI instances for a stage (ports base, base+1, …) and
    return their base URLs. Use with comfy_service.set_target() per worker thread
    to render in parallel. Falls back to the single managed instance when n<=1 or
    process management is off."""
    global _process, _current_stage, _pool, _pool_urls
    cfg = CONFIG.comfy
    n = n or cfg.parallel
    if n <= 1 or not cfg.manage_process:
        ensure_stage(stage_name)
        return [_url(_base_port())]

    if _current_stage == stage_name and len(_pool_urls) == n \
            and all(comfy_service.health_check(u) for u in _pool_urls):
        return list(_pool_urls)

    stop()
    base = _base_port()
    for i in range(n):
        _kill_on_port(base + i)
    procs, urls = [], []
    for i in range(n):
        port = base + i
        procs.append(_spawn(stage_name, port))
        urls.append(_url(port))
    for proc, url in zip(procs, urls):
        _wait_until_healthy(url, proc)
    _pool, _pool_urls, _current_stage = procs, urls, stage_name
    logger.info("ComfyUI pool ready: %s", urls)
    return list(urls)


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
