"""ComfyUI HTTP client.

Generic client around the ComfyUI API: load a workflow-graph template, fill
{placeholders}, queue it, poll for completion, and download the output image.
Used for portraits now; the same pattern serves TTS/SFX/cover render later.

Workflow templates live in workflows/ as ComfyUI graph JSON with text
{placeholders}. They are user-adaptable to whatever node set is installed,
so no graph is hardcoded in business logic (PLAN: ComfyWorkflowManager).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from app.core.config import CONFIG

logger = logging.getLogger(__name__)

# Per-thread ComfyUI target, so a parallel render pool can point each worker
# thread at its own instance (port). Falls back to the configured base_url.
_local = threading.local()


def set_target(base_url: str | None) -> None:
    _local.base_url = base_url


def _target() -> str:
    return (getattr(_local, "base_url", None) or CONFIG.comfy.base_url).rstrip("/")


class ComfyError(RuntimeError):
    pass


def health_check(base_url: str | None = None) -> bool:
    base = (base_url or CONFIG.comfy.base_url).rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(f"{base}/system_stats").raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def _dump_graph(template_name: str, graph: dict) -> None:
    """Save the exact filled workflow we POST, so it can be loaded straight into
    ComfyUI (API format) to compare against a hand-run."""
    try:
        out = CONFIG.projects_root.parent / "logs" / f"last_{Path(template_name).stem}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _load_template(name: str) -> dict:
    path: Path = CONFIG.workflows_dir / name
    if not path.exists():
        raise ComfyError(
            f"ComfyUI workflow template not found: {path}. "
            "Create it from your ComfyUI graph (Save API Format) and add "
            "{placeholders} for the fields you want to fill."
        )
    graph = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(graph, dict) or not all(
        isinstance(v, dict) and "class_type" in v for v in graph.values()
    ):
        raise ComfyError(
            f"{path} is not an API-format workflow. In ComfyUI enable Dev mode "
            "and use 'Save (API Format)' — the UI export (with nodes/links/"
            "subgraphs) cannot be submitted to /prompt."
        )
    return graph


def _fill(template: dict, replacements: dict[str, object]) -> dict:
    """Substitute {placeholder} tokens throughout the graph, preserving types.

    A value that is exactly a placeholder token (e.g. "{seed}") is replaced by
    the raw typed value (int stays int). Tokens embedded inside a longer string
    are replaced textually.
    """

    def walk(obj: object) -> object:
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str):
            if obj in replacements:
                return replacements[obj]
            for token, value in replacements.items():
                if token in obj:
                    obj = obj.replace(token, str(value))
            return obj
        return obj

    return walk(template)  # type: ignore[return-value]


def run_workflow(
    template_name: str,
    replacements: dict[str, object],
    out_path: Path,
    on_step: Callable[[int, int], None] | None = None,
    timeout: float | None = None,
) -> Path:
    """Queue a workflow, wait for it, and save the first output file to out_path.

    `on_step(value, max)` is called with live sampler progress from ComfyUI's
    WebSocket. `timeout` bounds the whole render (a stuck render aborts so a
    batch can continue) — defaults to CONFIG.comfy.request_timeout_s.
    """
    timeout = timeout or CONFIG.comfy.request_timeout_s
    base = _target()
    client_id = uuid.uuid4().hex
    graph = _fill(_load_template(template_name), replacements)
    _dump_graph(template_name, graph)   # save exactly what we send, for debugging

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{base}/prompt", json={"prompt": graph, "client_id": client_id}
        )
        if resp.status_code >= 400:
            raise ComfyError(f"ComfyUI rejected the workflow ({resp.status_code}): {resp.text}")
        prompt_id = resp.json()["prompt_id"]

        if on_step is not None and not _wait_via_ws(base, client_id, prompt_id, on_step, timeout):
            _await_done(client, base, prompt_id, timeout)  # ws failed -> poll
        elif on_step is None:
            _await_done(client, base, prompt_id, timeout)

        image_info = _history_image(client, base, prompt_id)
        img = client.get(f"{base}/view", params=image_info)
        img.raise_for_status()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img.content)
    logger.info("ComfyUI output saved: %s", out_path)
    _cleanup_comfy_output(image_info)   # don't leave a copy in ComfyUI/output
    return out_path


def _cleanup_comfy_output(info: dict) -> None:
    """Delete the file ComfyUI wrote to its own output/ — we already copied it
    into the project, so the ComfyUI copy is just clutter. Best-effort."""
    try:
        name = info.get("filename")
        if not name or info.get("type") not in (None, "output"):
            return
        out = (CONFIG.comfy.comfy_dir / "ComfyUI" / "output"
               / info.get("subfolder", "") / name)
        if out.exists():
            out.unlink()
            # remove the now-empty b2ad/ subfolder if applicable
            parent = out.parent
            if parent.name and not any(parent.iterdir()):
                parent.rmdir()
    except Exception:  # noqa: BLE001
        logger.debug("ComfyUI output cleanup skipped", exc_info=True)


def _wait_via_ws(base: str, client_id: str, prompt_id: str, on_step, timeout: float) -> bool:
    """Stream sampler progress over the ComfyUI WebSocket. Returns False on error
    so the caller can fall back to history polling. Bounded by a wall-clock
    deadline so a stuck render can't block forever."""
    try:
        import websocket  # websocket-client
    except ImportError:
        return False
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
    try:
        ws = websocket.WebSocket()
        ws.settimeout(min(timeout, 30.0))  # per-recv timeout
        ws.connect(f"{ws_url}/ws?clientId={client_id}")
    except Exception as err:  # noqa: BLE001
        logger.debug("WS connect failed: %s", err)
        return False
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                raise ComfyError(f"Render exceeded {timeout:.0f}s (prompt {prompt_id})")
            msg = ws.recv()
            if not isinstance(msg, str):
                continue  # binary preview frame
            data = json.loads(msg)
            mtype, payload = data.get("type"), data.get("data", {})
            if mtype == "progress":
                on_step(int(payload.get("value", 0)), int(payload.get("max", 0)))
            elif mtype == "executing" and payload.get("node") is None \
                    and payload.get("prompt_id") == prompt_id:
                return True
    except ComfyError:
        raise
    except Exception as err:  # noqa: BLE001
        logger.debug("WS recv ended: %s", err)
        return False
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass


def _await_done(client: httpx.Client, base: str, prompt_id: str, timeout: float) -> None:
    """Poll /history until the prompt has outputs (fallback when WS is unused)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hist = client.get(f"{base}/history/{prompt_id}")
        hist.raise_for_status()
        data = hist.json().get(prompt_id)
        if data and data.get("outputs"):
            return
        time.sleep(CONFIG.comfy.poll_interval_s)
    raise ComfyError(f"ComfyUI timed out waiting for prompt {prompt_id}")


def _history_image(client: httpx.Client, base: str, prompt_id: str) -> dict:
    """Read the first output file's view params from /history (image OR audio)."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        hist = client.get(f"{base}/history/{prompt_id}")
        hist.raise_for_status()
        data = hist.json().get(prompt_id)
        if data:
            for node_out in data.get("outputs", {}).values():
                files = node_out.get("images") or node_out.get("audio")
                if files:
                    f = files[0]
                    return {
                        "filename": f["filename"],
                        "subfolder": f.get("subfolder", ""),
                        "type": f.get("type", "output"),
                    }
            # finished but no media -> surface any ComfyUI execution error
            status = data.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False:
                for m in status.get("messages", []):
                    if m and m[0] == "execution_error":
                        raise ComfyError(f"ComfyUI execution error: {m[1]}")
                raise ComfyError(f"ComfyUI produced no output (status: {status})")
        time.sleep(0.5)
    raise ComfyError(f"No output file for prompt {prompt_id}")
