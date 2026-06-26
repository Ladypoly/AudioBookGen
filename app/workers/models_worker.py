"""Fetch available LLM models off the UI thread (for the Settings dropdowns)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from app.services import ollama_service


class ModelsWorker(QThread):
    loaded = Signal(list)   # list[str]

    def __init__(self, backend: str, base_url: str, api_key: str = "",
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._base_url = base_url
        self._api_key = api_key

    def run(self) -> None:  # noqa: D102
        if self._backend == "openai":
            models = ollama_service.list_openai_models(self._base_url, self._api_key)
        else:
            models = ollama_service.list_ollama_models(self._base_url)
        self.loaded.emit(models)


class PricedModelsWorker(QThread):
    """Fetch OpenAI/OpenRouter models WITH pricing off the UI thread.
    Emits list[{id, prompt, completion}] (prices are USD per 1M tokens)."""

    loaded = Signal(list)

    def __init__(self, base_url: str, api_key: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._base_url = base_url
        self._api_key = api_key

    def run(self) -> None:  # noqa: D102
        self.loaded.emit(
            ollama_service.list_openai_models_priced(self._base_url, self._api_key))


class MaxCtxWorker(QThread):
    """Fetch a model's max context window off the UI thread (for the ctx-cap
    dropdown). Emits (model, max_ctx); max_ctx is 0 if unknown."""

    loaded = Signal(str, int)

    def __init__(self, base_url: str, model: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._base_url = base_url
        self._model = model

    def run(self) -> None:  # noqa: D102
        mx = ollama_service.model_max_ctx(self._base_url, self._model) or 0
        self.loaded.emit(self._model, mx)
