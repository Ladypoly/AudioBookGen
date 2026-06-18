"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.core import model_cache
from app.services import comfy_launcher, settings_service
from app.ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    model_cache.setup()                    # keep model weights in models/ (before torch)
    settings_service.load_and_apply()      # user settings onto CONFIG
    app = QApplication(sys.argv)
    app.setApplicationName("Book2AudioDrama")
    try:
        comfy_launcher.start()             # one persistent ComfyUI, booting in the bg
    except Exception:                      # noqa: BLE001
        logging.getLogger(__name__).warning("ComfyUI autostart failed", exc_info=True)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
