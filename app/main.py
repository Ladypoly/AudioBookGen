"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.core import model_cache
from app.services import settings_service
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
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
