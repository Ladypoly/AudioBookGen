"""Settings: read/write CONFIG values, grouped by section for the UI.

Reuses `app/services/settings_service.py` verbatim (FIELDS / current / save).
The UI renders a left-nav of sections; this exposes the grouping + each field's
kind/choices so the frontend can build the right input per field.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import ollama_service, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Provider presets: id -> (label, default base URL).
LOCAL_PROVIDERS = {
    "ollama": ("Ollama", "http://localhost:11434"),
    "lmstudio": ("LM Studio", "http://localhost:1234/v1"),
}
CLOUD_PROVIDERS = {
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1"),
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com/v1"),
    "groq": ("Groq", "https://api.groq.com/openai/v1"),
    "together": ("Together", "https://api.together.xyz/v1"),
    "custom": ("Custom…", ""),
}


def _price_tier(prompt, completion) -> str:
    """cheap / medium / expensive from USD per 1M tokens (uses the dearer side)."""
    vals = [v for v in (prompt, completion) if isinstance(v, (int, float))]
    if not vals:
        return "unknown"
    price = max(vals)
    if price < 1.0:
        return "cheap"
    if price <= 10.0:
        return "medium"
    return "expensive"


@router.get("/providers")
def providers() -> dict:
    return {
        "local": [{"id": k, "label": v[0], "base_url": v[1]} for k, v in LOCAL_PROVIDERS.items()],
        "cloud": [{"id": k, "label": v[0], "base_url": v[1]} for k, v in CLOUD_PROVIDERS.items()],
    }


@router.get("/local-models")
def local_models(provider: str = "ollama", url: str = "http://localhost:11434") -> list[str]:
    if provider == "lmstudio":
        return ollama_service.list_openai_models(url, "")
    return ollama_service.list_ollama_models(url)


@router.get("/cloud-models")
def cloud_models(base_url: str, api_key: str = "") -> list[dict]:
    priced = ollama_service.list_openai_models_priced(base_url, api_key)
    if priced:
        return [{**m, "tier": _price_tier(m.get("prompt"), m.get("completion"))} for m in priced]
    # No pricing block (OpenAI/Groq/LM Studio) — return ids only.
    return [{"id": mid, "prompt": None, "completion": None, "tier": "unknown"}
            for mid in ollama_service.list_openai_models(base_url, api_key)]


class SaveBody(BaseModel):
    values: dict


def _jsonable(v):
    return str(v) if isinstance(v, Path) else v


def _workflow_files() -> list[str]:
    """Available ComfyUI workflow templates (for the workflow dropdowns)."""
    from app.core.config import CONFIG
    try:
        return sorted(p.name for p in CONFIG.workflows_dir.glob("*.json"))
    except OSError:
        return []


@router.get("/workflows")
def workflows() -> dict:
    """Available workflow templates + the current default clone/TTS workflow
    (for the per-character engine override dropdown)."""
    from app.core.config import CONFIG
    return {"workflows": _workflow_files(), "default_tts": CONFIG.comfy.tts_workflow}


@router.get("/schema")
def schema() -> dict:
    """Sections (ordered) with their fields and current values, for the UI."""
    values = settings_service.current()
    workflows = _workflow_files()
    sections: dict[str, list] = {}
    order: list[str] = []
    for section, label, path, kind, choices in settings_service.FIELDS:
        if section not in sections:
            sections[section] = []
            order.append(section)
        # "workflow" fields become dropdowns of the available template files.
        eff_choices = workflows if kind == "workflow" else choices
        eff_kind = "choice" if kind == "workflow" else kind
        sections[section].append({
            "label": label,
            "path": path,
            "kind": eff_kind,
            "choices": eff_choices,
            "value": _jsonable(values.get(path)),
        })
    return {"sections": [{"name": s, "fields": sections[s]} for s in order]}


@router.get("")
def get() -> dict:
    return {k: _jsonable(v) for k, v in settings_service.current().items()}


@router.post("")
def save(body: SaveBody) -> dict:
    settings_service.save(body.values)
    return {"ok": True}
