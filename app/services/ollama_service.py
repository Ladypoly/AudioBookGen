"""Ollama HTTP client.

Thin, synchronous client around the local Ollama /api/generate endpoint with
JSON-mode output, retries, and pydantic validation. Designed to be called
from a background worker thread (not the Qt UI thread).
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import CONFIG

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CORRECTION_SUFFIX = (
    "\n\nYour previous response was not valid JSON of the required shape. "
    "Return ONLY a single valid JSON object, no prose, no markdown."
)


class OllamaError(RuntimeError):
    """Raised when Ollama cannot return a valid, schema-conforming response."""


def use_ollama_proto() -> bool:
    """True when the active backend speaks Ollama's native /api protocol.

    Everything else (LM Studio, cloud APIs) speaks OpenAI /v1. Legacy values
    ("ollama"/"openai") are still understood for backward compatibility."""
    cfg = CONFIG.ollama
    if cfg.backend in ("local", "ollama"):
        return getattr(cfg, "local_provider", "ollama") == "ollama" or cfg.backend == "ollama"
    return False


def openai_target() -> tuple[str, str, str]:
    """(base_url, api_key, model) for the OpenAI-compatible call path.

    Local LM Studio uses the local URL + model and no key; cloud uses the API
    URL/key/model."""
    cfg = CONFIG.ollama
    if cfg.backend == "local":              # lmstudio (ollama handled by proto)
        return cfg.base_url, "", cfg.model
    return cfg.api_base_url, cfg.api_key, cfg.api_model


def list_ollama_models(base_url: str) -> list[str]:
    """Installed Ollama models (GET /api/tags). [] on failure (e.g. Ollama not
    running) — logged as a single quiet line, never a stack trace."""
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{base_url.rstrip('/')}/api/tags")
            r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception as err:  # noqa: BLE001
        logger.info("Ollama models unavailable at %s (%s)", base_url, type(err).__name__)
        return []


_CTX_CACHE: dict[str, int] = {}


def model_max_ctx(base_url: str, model: str) -> int | None:
    """The model's max context window (POST /api/show -> model_info). None on
    failure. The key is architecture-prefixed (gemma2.context_length,
    llama.context_length, …) so we match any key ending in .context_length."""
    try:
        with httpx.Client(timeout=8.0) as c:
            r = c.post(f"{base_url.rstrip('/')}/api/show", json={"model": model})
            r.raise_for_status()
        info = r.json().get("model_info", {})
        for k, v in info.items():
            if k.endswith(".context_length") and isinstance(v, int):
                return v
    except Exception as err:  # noqa: BLE001
        logger.info("context length for %s unavailable (%s)", model, type(err).__name__)
    return None


def resolve_num_ctx() -> int:
    """Effective num_ctx: the model's real max (clamped to ctx_cap) when
    auto_ctx is on, else the manual num_ctx. Cached per model.

    The cap guards VRAM: Ollama allocates the whole KV cache up front, so a
    128k/1M window would spill to CPU (very slow) on a normal GPU."""
    cfg = CONFIG.ollama
    if not use_ollama_proto() or not cfg.auto_ctx:
        return cfg.num_ctx
    key = cfg.model
    if key not in _CTX_CACHE:
        mx = model_max_ctx(cfg.base_url, cfg.model)
        _CTX_CACHE[key] = min(mx, cfg.ctx_cap) if mx else cfg.num_ctx
        logger.info("num_ctx for %s = %d (model max %s, cap %d)",
                    key, _CTX_CACHE[key], mx, cfg.ctx_cap)
    return _CTX_CACHE[key]


def list_openai_models(base_url: str, api_key: str) -> list[str]:
    """Models from an OpenAI-compatible API (GET /models). [] on failure."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{base_url.rstrip('/')}/models", headers=headers)
            r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))
    except Exception as err:  # noqa: BLE001
        logger.info("API models unavailable at %s (%s)", base_url, type(err).__name__)
        return []


def list_openai_models_priced(base_url: str, api_key: str) -> list[dict]:
    """Models with pricing (OpenRouter exposes a `pricing` block per model).

    Returns [{id, prompt, completion}] where prompt/completion are USD per
    MILLION tokens (None when the API gives no pricing, e.g. vLLM/LM Studio)."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{base_url.rstrip('/')}/models", headers=headers)
            r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as err:  # noqa: BLE001
        logger.info("API models unavailable at %s (%s)", base_url, type(err).__name__)
        return []

    def _per_m(v) -> float | None:
        try:
            return float(v) * 1_000_000          # USD/token -> USD/1M tokens
        except (TypeError, ValueError):
            return None

    out = []
    for m in data:
        pricing = m.get("pricing") or {}
        out.append({
            "id": m["id"],
            "prompt": _per_m(pricing.get("prompt")),
            "completion": _per_m(pricing.get("completion")),
        })
    return sorted(out, key=lambda d: d["id"])


def _post_openai(prompt: str, schema_dict: dict) -> str:
    """Call an OpenAI-compatible chat API (OpenRouter, vLLM, LM Studio, …) with
    JSON-schema structured output."""
    cfg = CONFIG.ollama
    base_url, api_key, model = openai_target()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg.temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "result", "strict": True, "schema": schema_dict},
        },
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=cfg.request_timeout_s) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _post_generate(prompt: str, fmt: object, num_predict: int | None = None) -> str:
    if not use_ollama_proto():
        return _post_openai(prompt, fmt)   # fmt is schema.model_json_schema()
    cfg = CONFIG.ollama
    payload = {
        "model": cfg.model,
        "prompt": prompt,
        # Structured outputs: a JSON schema constrains decoding to valid,
        # enum-conforming JSON (far more reliable than format:"json").
        "format": fmt,
        "stream": False,
        "keep_alive": cfg.keep_alive,
        "options": {
            "temperature": cfg.temperature,
            "repeat_penalty": cfg.repeat_penalty,
            "repeat_last_n": cfg.repeat_last_n,
            "num_ctx": resolve_num_ctx(),
            "num_predict": num_predict or cfg.num_predict,
        },
    }
    url = f"{cfg.base_url.rstrip('/')}/api/generate"
    with httpx.Client(timeout=cfg.request_timeout_s) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data.get("response", "")


def generate_json(prompt: str, schema: type[T], num_predict: int | None = None) -> T:
    """Call Ollama with schema-constrained output and validate against `schema`.

    Retries with a corrective suffix on transport errors or validation
    failures, up to CONFIG.ollama.max_retries extra attempts. `num_predict`
    overrides the output-token budget (needed for multi-chapter batch calls).
    """
    cfg = CONFIG.ollama
    last_err: Exception | None = None
    attempt_prompt = prompt
    fmt = schema.model_json_schema()

    for attempt in range(cfg.max_retries + 1):
        try:
            raw = _post_generate(attempt_prompt, fmt, num_predict)
            obj = json.loads(raw)
            return schema.model_validate(obj)
        except (httpx.HTTPError, json.JSONDecodeError, ValidationError) as err:
            last_err = err
            logger.warning(
                "Ollama attempt %d/%d failed: %s",
                attempt + 1,
                cfg.max_retries + 1,
                err,
            )
            attempt_prompt = prompt + _CORRECTION_SUFFIX

    raise OllamaError(f"Ollama failed after retries: {last_err}") from last_err


def unload() -> bool:
    """Ask Ollama to evict the model from VRAM (keep_alive=0).

    Call before launching ComfyUI image jobs so the 26B LLM is not resident
    alongside Ideogram on a 24 GB GPU (PLAN: memory-safe scheduler).
    """
    cfg = CONFIG.ollama
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(
                f"{cfg.base_url.rstrip('/')}/api/generate",
                json={"model": cfg.model, "keep_alive": 0},
            ).raise_for_status()
        return True
    except httpx.HTTPError as err:
        logger.warning("Ollama unload failed: %s", err)
        return False


def health_check() -> bool:
    """True if the active LLM backend responds (Ollama /api/tags, else /models)."""
    cfg = CONFIG.ollama
    try:
        if use_ollama_proto():
            url = f"{cfg.base_url.rstrip('/')}/api/tags"
            headers: dict = {}
        else:
            base_url, api_key, _ = openai_target()
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(timeout=5.0) as client:
            client.get(url, headers=headers).raise_for_status()
        return True
    except httpx.HTTPError:
        return False
