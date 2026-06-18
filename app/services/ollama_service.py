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


def list_ollama_models(base_url: str) -> list[str]:
    """Installed Ollama models (GET /api/tags). [] on failure."""
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{base_url.rstrip('/')}/api/tags")
            r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:  # noqa: BLE001
        logger.warning("could not list Ollama models", exc_info=True)
        return []


def list_openai_models(base_url: str, api_key: str) -> list[str]:
    """Models from an OpenAI-compatible API (GET /models). [] on failure."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{base_url.rstrip('/')}/models", headers=headers)
            r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))
    except Exception:  # noqa: BLE001
        logger.warning("could not list API models", exc_info=True)
        return []


def _post_openai(prompt: str, schema_dict: dict) -> str:
    """Call an OpenAI-compatible chat API (OpenRouter, vLLM, LM Studio, …) with
    JSON-schema structured output."""
    cfg = CONFIG.ollama
    payload = {
        "model": cfg.api_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg.temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "result", "strict": True, "schema": schema_dict},
        },
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    url = f"{cfg.api_base_url.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=cfg.request_timeout_s) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _post_generate(prompt: str, fmt: object) -> str:
    if CONFIG.ollama.backend == "openai":
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
            "num_ctx": cfg.num_ctx,
            "num_predict": cfg.num_predict,
        },
    }
    url = f"{cfg.base_url.rstrip('/')}/api/generate"
    with httpx.Client(timeout=cfg.request_timeout_s) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data.get("response", "")


def generate_json(prompt: str, schema: type[T]) -> T:
    """Call Ollama with schema-constrained output and validate against `schema`.

    Retries with a corrective suffix on transport errors or validation
    failures, up to CONFIG.ollama.max_retries extra attempts.
    """
    cfg = CONFIG.ollama
    last_err: Exception | None = None
    attempt_prompt = prompt
    fmt = schema.model_json_schema()

    for attempt in range(cfg.max_retries + 1):
        try:
            raw = _post_generate(attempt_prompt, fmt)
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
    """Return True if the Ollama server responds to /api/tags."""
    cfg = CONFIG.ollama
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{cfg.base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
