"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog

from synthnvcontrol.logging_config import configure_logging
from synthnvcontrol.ui import MainWindow, StartupDialog


def main() -> int:
    configure_logging()
    logging.getLogger(__name__).info("starting SynthNVControl")
    app = QApplication(sys.argv)
    app.setApplicationName("SynthNV Control")
    dialog = StartupDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.target is None:
        return 0
    window = MainWindow(dialog.target)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
