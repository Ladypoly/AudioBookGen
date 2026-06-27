"""First-run setup: detect backends, set the ComfyUI path, install the node."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import comfy_service, ollama_service, settings_service, setup_service
from server.jobs import MANAGER

router = APIRouter(prefix="/api/setup", tags=["setup"])

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="setup")


@router.get("/status")
async def status() -> dict:
    """ComfyUI/node detection + a live Ollama/ComfyUI health probe."""
    loop = asyncio.get_running_loop()
    ollama, comfy = await asyncio.gather(
        loop.run_in_executor(_pool, ollama_service.health_check),
        loop.run_in_executor(_pool, comfy_service.health_check),
    )
    st = setup_service.status()
    st["ollama"] = bool(ollama)
    st["comfy_running"] = bool(comfy)
    return st


class DirBody(BaseModel):
    path: str


@router.post("/comfy-dir")
def set_comfy_dir(body: DirBody) -> dict:
    """Validate a ComfyUI portable folder and persist it to settings."""
    if not setup_service.validate_comfy_dir(body.path):
        raise HTTPException(
            400, "Not a ComfyUI portable folder (need ComfyUI/main.py and python_embeded/python.exe).")
    settings_service.save({"comfy.comfy_dir": body.path})
    return setup_service.status()


@router.post("/install-node")
def install_node() -> dict:
    """Kick off the (background) node clone + pip install; stream via /ws/jobs."""
    job = MANAGER.submit("setup", f"Install {setup_service.NODE_NAME}",
                         setup_service.install_node, meta={"kind": "node_install"})
    return {"job_id": job.id}
