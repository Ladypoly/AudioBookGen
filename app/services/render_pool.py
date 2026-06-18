"""Distribute render jobs across several ComfyUI instances.

One worker thread per instance, each pinned to its URL via comfy_service's
thread-local target, pulling items from a shared queue — so each instance keeps
its model resident and renders run truly in parallel.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any

from app.services import comfy_service

logger = logging.getLogger(__name__)


def map_over_pool(
    urls: list[str],
    items: list[Any],
    fn: Callable[[Any], None],
    on_done: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Run `fn(item)` for every item, spread across the ComfyUI `urls`.

    `fn` runs on a worker thread already pointed at one instance (via
    comfy_service thread-local). `on_done(done, total)` fires after each item.
    """
    work: Queue = Queue()
    for it in items:
        work.put(it)
    total = len(items)
    lock = threading.Lock()
    counter = {"done": 0}

    def worker(url: str) -> None:
        comfy_service.set_target(url)
        try:
            while True:
                if is_cancelled and is_cancelled():
                    return
                try:
                    item = work.get_nowait()
                except Empty:
                    return
                try:
                    fn(item)
                except Exception:  # noqa: BLE001
                    logger.exception("pool job failed")
                with lock:
                    counter["done"] += 1
                    if on_done:
                        on_done(counter["done"], total)
        finally:
            comfy_service.set_target(None)

    threads = [threading.Thread(target=worker, args=(u,), daemon=True) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
