"""Rough token-cost estimates for LLM tasks.

Uses the active model's pricing (USD per 1M tokens) — non-zero only for the
cloud backend; local Ollama/LM Studio are free. Token counts are estimated from
character counts (~4 chars/token), so figures are ballpark, not billing-grade.
"""

from __future__ import annotations

import logging

from app.core.config import CONFIG
from app.services import ollama_service

logger = logging.getLogger(__name__)

_price_cache: dict[tuple, tuple[float, float]] = {}


def tokens_for_chars(chars: int) -> int:
    return max(1, int(chars / 4))


def active_pricing() -> tuple[float, float]:
    """(prompt, completion) USD per 1M tokens for the active model. (0,0) = free."""
    cfg = CONFIG.ollama
    if ollama_service.use_ollama_proto():
        return (0.0, 0.0)                      # local Ollama — free
    base, key, model = ollama_service.openai_target()
    ck = (base, model)
    if ck in _price_cache:
        return _price_cache[ck]
    try:
        priced = ollama_service.list_openai_models_priced(base, key)
        m = next((x for x in priced if x["id"] == model), None)
        res = (float((m or {}).get("prompt") or 0.0), float((m or {}).get("completion") or 0.0))
    except Exception:  # noqa: BLE001
        res = (0.0, 0.0)
    _price_cache[ck] = res
    return res


def estimate(in_tokens: int, out_tokens: int) -> dict:
    prompt_pm, completion_pm = active_pricing()
    usd = in_tokens / 1_000_000 * prompt_pm + out_tokens / 1_000_000 * completion_pm
    return {
        "usd": round(usd, 4),
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "free": prompt_pm == 0 and completion_pm == 0,
        "model": ollama_service.openai_target()[2] if not ollama_service.use_ollama_proto() else CONFIG.ollama.model,
    }


def estimate_for_text(chars: int, *, in_mult: float = 1.0, out_ratio: float = 0.3) -> dict:
    """Estimate a task that reads `chars` of text. `in_mult` accounts for repeated
    passes/overlap; `out_ratio` is output tokens as a fraction of input."""
    in_tok = int(tokens_for_chars(chars) * in_mult)
    return estimate(in_tok, int(in_tok * out_ratio))
