"""The test process's one QApplication. tools/test.sh renders it offscreen."""

from PyQt6.QtWidgets import QApplication


def qt_app() -> QApplication:
    # PyQt6's type hints have the static instance() return typing.Self, which Pyright reads as unknown.
    app = QApplication.instance()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if isinstance(app, QApplication):
        return app
    return QApplication(["sleep-control-tests"])
