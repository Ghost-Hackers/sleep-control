"""The running instance: tray icon, window, and the control socket."""

import signal
import socket
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Callable, Optional

from PyQt6.QtCore import QSocketNotifier, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import APP_ID, APP_NAME, __version__, commands, ipc
from .backend import DBusBackend
from .state import BackendError, Controller, describe


def icon_dir() -> Path:
    installed = Path("/app/share/sleep-control/icons")
    if installed.is_dir():
        return installed
    return Path(__file__).resolve().parents[2] / "data" / "icons"


STATE_ICON_SIZE = 32
MARGIN = 16
# The Quit border is faint, so the bottom looks roomier than it is. Trim it to look even.
BOTTOM_MARGIN = 12
SPACING = 8
ICON_SIZES = (16, 22, 24, 32, 48, 64)


def tray_icon(icons: Path, name: str) -> QIcon:
    """Sizes up to 16 px use the simplified drawing, larger ones the full one."""
    icon = QIcon()
    for size in ICON_SIZES:
        path = icons / (f"{name}-16.svg" if size <= 16 else f"{name}.svg")
        icon.addPixmap(QIcon(str(path)).pixmap(size, size))
    return icon


class Window(QWidget):
    def __init__(self, ui: "Ui") -> None:
        super().__init__()
        self._ui = ui
        self.setWindowTitle(APP_NAME)
        self.state_icon = QLabel()
        self.state_icon.setFixedSize(STATE_ICON_SIZE, STATE_ICON_SIZE)
        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state_row = QHBoxLayout()
        state_row.setSpacing(10)
        state_row.addStretch(1)
        state_row.addWidget(self.state_icon)
        state_row.addWidget(self.state)
        state_row.addStretch(1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        actions = QHBoxLayout()
        actions.setSpacing(SPACING)
        self.action_buttons: list[QPushButton] = []
        for text, slot in (("Allow sleep", ui.allow_sleep), ("Keep awake", ui.keep_awake),
                           ("Sleep now", ui.sleep_now)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            self.action_buttons.append(button)
        self.quit_button = QPushButton("Quit")
        self.quit_button.clicked.connect(ui.quit)
        buttons = self.action_buttons + [self.quit_button]
        # One width for all four, wide enough that the three in a row also hold the state line.
        metrics = self.state.fontMetrics()
        state_width = STATE_ICON_SIZE + 10 + max(metrics.horizontalAdvance(describe(a)) for a in (True, False))
        row_width = max(state_width, 3 * max(b.sizeHint().width() for b in buttons) + 2 * SPACING)
        width = -(-(row_width - 2 * SPACING) // 3)
        for b in buttons:
            b.setFixedWidth(width)
        for b in self.action_buttons:
            actions.addWidget(b)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.quit_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, BOTTOM_MARGIN)
        layout.setSpacing(12)
        layout.addLayout(state_row)
        layout.addLayout(actions)
        layout.addWidget(self.error)
        layout.addWidget(line)
        layout.addLayout(footer)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:
        assert event is not None  # Qt always passes the event
        event.ignore()
        self.hide()
        self._ui.window_closed()


class Ui:
    def __init__(self, app: QApplication, controller: Controller) -> None:
        self.app = app
        self.controller = controller
        icons = icon_dir()
        self.icon_awake = tray_icon(icons, "tray-awake")
        self.icon_normal = tray_icon(icons, "tray-normal")
        self.window = Window(self)
        self.window.setWindowIcon(QIcon(str(icons / f"{APP_ID}.svg")))
        self.tray: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon()
            menu = QMenu()
            self.menu_state = QAction(menu)
            self.menu_state.setEnabled(False)
            menu.addAction(self.menu_state)
            menu.addSeparator()

            def add(text: str, slot: Callable[[], object]) -> None:
                action = QAction(text, menu)
                action.triggered.connect(slot)
                menu.addAction(action)

            for text, slot in (("Allow sleep", self.allow_sleep), ("Keep awake", self.keep_awake),
                               ("Sleep now", self.sleep_now)):
                add(text, slot)
            menu.addSeparator()
            add("Show window", self.show_window)
            add("Quit", self.quit)
            self._menu = menu
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._tray_activated)
        controller.on_change(lambda _awake: self.refresh())
        self.refresh()
        if self.tray:
            self.tray.show()

    def refresh(self) -> None:
        text = describe(self.controller.awake)
        self.window.state.setText(text)
        icon = self.icon_awake if self.controller.awake else self.icon_normal
        self.window.state_icon.setPixmap(icon.pixmap(STATE_ICON_SIZE, STATE_ICON_SIZE))
        if self.tray:
            self.tray.setIcon(icon)
            self.tray.setToolTip(f"{APP_NAME}: {text}")
            self.menu_state.setText(text)

    def _report(self, message: str) -> None:
        self.window.error.setText(message)
        self.window.error.setVisible(bool(message))
        if message and self.tray:
            self.tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning)

    def _do(self, action: Callable[[], object]) -> Optional[str]:
        try:
            action()
        except BackendError as e:
            self._report(str(e))
            return str(e)
        self._report("")
        return None

    def keep_awake(self) -> Optional[str]:
        return self._do(self.controller.keep_awake)

    def allow_sleep(self) -> Optional[str]:
        return self._do(self.controller.allow_sleep)

    def sleep_now(self) -> Optional[str]:
        return self._do(self.controller.sleep_now)

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def window_closed(self) -> None:
        # Without a tray icon nothing would be left to reach the app, unless it holds a block.
        if self.tray is None and not self.controller.awake:
            self.quit()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def quit(self) -> None:
        self.app.quit()

    def handle(self, command: str) -> str:
        return commands.answer(self.controller, command, self.show_window, self._report)


def _read_notifier(fd: int) -> QSocketNotifier:
    # PyQt6's type hints give the socket as sip.voidptr; PyQt takes the descriptor as an int.
    return QSocketNotifier(fd, QSocketNotifier.Type.Read)  # pyright: ignore[reportCallIssue, reportArgumentType]


def _quit_on_signals(app: QApplication) -> tuple[QSocketNotifier, socket.socket, socket.socket]:
    """SIGTERM, SIGINT and SIGHUP quit through the normal path, so the block is released.

    Keep the returned sockets open while the app runs.
    """
    reader, writer = socket.socketpair()
    reader.setblocking(False)
    writer.setblocking(False)
    signal.set_wakeup_fd(writer.fileno())
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda _sig, _frame: None)
    notifier = _read_notifier(reader.fileno())

    def wake() -> None:
        app.quit()
        reader.recv(64)  # the notifier only fires when there is something to read

    notifier.activated.connect(wake)
    return notifier, reader, writer


def _log_uncaught(kind: type[BaseException], value: BaseException, tb: Optional[TracebackType]) -> None:
    # PyQt aborts on an exception escaping a slot. Log it instead, so a held block isn't dropped.
    traceback.print_exception(kind, value, tb)


def run_app(path: str, show_window: bool) -> int:
    # A second launch hands over to the instance that is already running.
    try:
        ipc.request(path, "show" if show_window else "status", timeout=5.0)
        return 0
    except (ipc.NotRunning, OSError):
        pass

    sys.excepthook = _log_uncaught
    app = QApplication(sys.argv[:1])
    app.setApplicationName("sleep-control")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    controller = Controller(DBusBackend())
    ui = Ui(app, controller)
    server = ipc.try_listen(path, ui.handle)
    if server is None:
        # Lost a race with another launch: hand over to it.
        ipc.request(path, "show" if show_window else "status", timeout=5.0)
        return 0
    notifier = _read_notifier(server.fileno())
    notifier.activated.connect(server.serve_pending)
    signals = _quit_on_signals(app)

    def shut_down() -> None:
        try:
            controller.allow_sleep()
        except BackendError as e:
            print(f"sleep-control: {e}", file=sys.stderr)
        server.close()

    app.aboutToQuit.connect(shut_down)
    if show_window or ui.tray is None:
        ui.show_window()
    code = app.exec()
    del signals, notifier
    return code
