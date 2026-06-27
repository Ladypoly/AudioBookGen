"""FastAPI application entry point.

Run with:  python -m server.main   (or uvicorn server.main:app)

Binds the JobManager to the running loop, applies saved settings onto CONFIG,
and mounts the API routers. The React frontend (Vite dev server or the built
bundle inside Electron) talks to this over HTTP + WebSocket.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services import settings_service
from server.jobs import MANAGER
from server.routers import (
    chapters, characters, health, ingest, jobs, media, projects, settings, setup,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

app = FastAPI(title="AudioBookGen API", version="0.1.0")

# Local app: the frontend runs on a different origin in dev (Vite) and on
# file:// / app:// inside Electron, so allow all origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(characters.router)
app.include_router(chapters.router)
app.include_router(ingest.router)
app.include_router(projects.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(jobs.router)
app.include_router(setup.router)


@app.on_event("startup")
async def _startup() -> None:
    settings_service.load_and_apply()
    MANAGER.bind_loop(asyncio.get_running_loop())
    logger.info("AudioBookGen API ready")


@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
