"""Jobs: list/cancel + the `/ws/jobs` progress stream for the queue strip."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.jobs import MANAGER

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs")
def list_jobs() -> list[dict]:
    return MANAGER.list()


@router.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    return {"ok": MANAGER.cancel(job_id)}


@router.websocket("/ws/jobs")
async def ws_jobs(ws: WebSocket) -> None:
    await ws.accept()
    q = MANAGER.subscribe()
    try:
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        MANAGER.unsubscribe(q)
