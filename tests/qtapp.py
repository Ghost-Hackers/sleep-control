"""The test process's one QApplication. tools/test.sh renders it offscreen."""

from PyQt6.QtWidgets import QApplication


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication(["sleep-control-tests"])
