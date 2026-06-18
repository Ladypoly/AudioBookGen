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
