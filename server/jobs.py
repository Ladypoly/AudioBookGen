"""Async job runner + WebSocket progress hub.

Replaces the old `app/workers/*` QThread layer. A job is any blocking pipeline
call (extraction, render, voice design, …) run in a worker thread. Progress is
published as JSON events to every connected `/ws/jobs` client, so the React
queue strip updates live.

Design notes:
- The pipeline services are synchronous and GPU-serialized (one ComfyUI at a
  time), so jobs run on a small thread pool and heavy GPU work additionally
  honours `comfy_launcher.RENDER_LOCK` inside the services themselves.
- Events are fanned out through an asyncio queue per client; the runner is
  thread-safe via `loop.call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobState(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class Job:
    id: str
    kind: str
    title: str
    state: JobState = JobState.pending
    progress: float = 0.0          # 0..1 (-1 == indeterminate)
    detail: str = ""
    result: Any = None
    error: str | None = None
    meta: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state.value,
            "progress": self.progress,
            "detail": self.detail,
            "error": self.error,
            "meta": self.meta,
        }


class JobContext:
    """Handed to a job function so it can report progress and check for cancel.

    A job function has signature `fn(ctx: JobContext) -> Any`. Use
    `ctx.progress(done, total, detail)` for determinate progress or
    `ctx.busy(detail)` for indeterminate, and check `ctx.cancelled` in loops.
    """

    def __init__(self, manager: "JobManager", job: Job) -> None:
        self._m = manager
        self._job = job

    @property
    def job(self) -> Job:
        return self._job

    @property
    def cancelled(self) -> bool:
        return self._job.id in self._m._cancel

    def progress(self, done: int | float, total: int | float, detail: str = "") -> None:
        frac = (done / total) if total else 0.0
        self._job.progress = max(0.0, min(1.0, frac))
        if detail:
            self._job.detail = detail
        self._m._emit(self._job)

    def busy(self, detail: str = "") -> None:
        self._job.progress = -1.0
        if detail:
            self._job.detail = detail
        self._m._emit(self._job)

    def step(self, detail: str) -> None:
        self._job.detail = detail
        self._m._emit(self._job)

    def set_step(self, key: str, detail: str = "") -> None:
        """Advance the named pipeline step (drives the extraction popup's
        per-step animation). Resets progress to indeterminate for the new step."""
        self._job.meta["step"] = key
        self._job.progress = -1.0
        if detail:
            self._job.detail = detail
        self._m._emit(self._job)

    def update_meta(self, **kwargs) -> None:
        self._job.meta.update(kwargs)
        self._m._emit(self._job)


class JobManager:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._cancel: set[str] = set()
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # --- websocket fan-out ---------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        # send a snapshot of current jobs so a late client is in sync
        for job in self._jobs.values():
            q.put_nowait({"type": "job", "job": job.public()})
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    def _emit(self, job: Job) -> None:
        payload = {"type": "job", "job": job.public()}
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._broadcast, payload)

    def _broadcast(self, payload: dict) -> None:
        for q in list(self._clients):
            try:
                q.put_nowait(payload)
            except Exception:  # noqa: BLE001
                pass

    # --- job lifecycle -------------------------------------------------------
    def submit(self, kind: str, title: str, fn: Callable[[JobContext], Any],
               meta: dict | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, meta=meta or {})
        self._jobs[job.id] = job
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[JobContext], Any]) -> None:
        ctx = JobContext(self, job)
        job.state = JobState.running
        self._emit(job)
        try:
            job.result = fn(ctx)
            job.state = JobState.cancelled if job.id in self._cancel else JobState.done
            job.progress = 1.0
        except Exception as exc:  # noqa: BLE001
            job.state = JobState.failed
            job.error = str(exc)
            logger.error("Job %s (%s) failed: %s\n%s", job.id, job.kind, exc,
                         traceback.format_exc())
        finally:
            self._cancel.discard(job.id)
            self._emit(job)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.state in (JobState.pending, JobState.running):
            self._cancel.add(job_id)
            return True
        return False

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        return [j.public() for j in self._jobs.values()]


# Module-global manager used by routers.
MANAGER = JobManager()
