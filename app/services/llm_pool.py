"""Bounded-concurrency map for the per-chapter LLM passes.

Extraction makes one (or more) LLM call per chapter, all independent — so they
run concurrently against Ollama (which serves OLLAMA_NUM_PARALLEL requests at
once). The current per-phase model override (a contextvar set via
ollama_service.use_model) is propagated into the worker threads via
copy_context, and shared-state merging happens back on the calling thread via
the on_complete callback (so callers don't need their own locks).
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import logging
from typing import Callable, Iterable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    items: Iterable[T],
    fn: Callable[[T], R],
    concurrency: int = 1,
    *,
    on_complete: Callable[[int, R], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[R | None]:
    """Run `fn` over `items` with up to `concurrency` workers, returning results
    in input order (None for an item that raised or was skipped).

    `on_complete(index, result)` is called ON THE CALLING THREAD as each item
    finishes — use it for progress + merging shared state safely.
    """
    work = list(items)
    total = len(work)
    results: list[R | None] = [None] * total

    # Sequential path = exact previous behaviour (and the safe default).
    if concurrency <= 1 or total <= 1:
        for i, it in enumerate(work):
            if is_cancelled and is_cancelled():
                break
            try:
                results[i] = fn(it)
            except Exception:  # noqa: BLE001
                logger.exception("parallel_map item %d failed", i)
            if on_complete:
                on_complete(i, results[i])
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures: dict[concurrent.futures.Future, int] = {}
        for i, it in enumerate(work):
            if is_cancelled and is_cancelled():
                break
            ctx = contextvars.copy_context()      # carry the per-phase model into the worker
            futures[ex.submit(ctx.run, fn, it)] = i
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:  # noqa: BLE001
                logger.exception("parallel_map item %d failed", i)
                results[i] = None
            if on_complete:                        # back on the calling thread
                on_complete(i, results[i])
    return results
