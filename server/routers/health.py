"""Backend health for the top status bar (Ollama + ComfyUI dots)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter

from app.services import comfy_service, ollama_service

router = APIRouter(prefix="/api/health", tags=["health"])

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health")


@router.get("")
async def health() -> dict:
    """Probe both backends concurrently. Each check has its own short timeout
    inside the service, so this never blocks the UI for long."""
    import asyncio

    loop = asyncio.get_running_loop()
    ollama, comfy = await asyncio.gather(
        loop.run_in_executor(_pool, ollama_service.health_check),
        loop.run_in_executor(_pool, comfy_service.health_check),
    )
    return {"ollama": bool(ollama), "comfy": bool(comfy)}


@router.post("/comfy/launch")
async def launch_comfy() -> dict:
    """Spawn the persistent headless ComfyUI (--disable-all-custom-nodes
    --whitelist-custom-nodes tts_audio_suite). Returns immediately; the status
    dot flips green once it's healthy. Triggered by clicking the red ComfyUI
    dot in the status bar."""
    import asyncio

    from app.services import comfy_launcher

    if comfy_service.health_check():
        return {"ok": True, "already_running": True}

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_pool, lambda: comfy_launcher.start(wait=False))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "launching": True}
