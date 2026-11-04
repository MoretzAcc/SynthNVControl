"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QDialog

from synthnvcontrol.ui import MainWindow, StartupDialog


def main() -> int:
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
