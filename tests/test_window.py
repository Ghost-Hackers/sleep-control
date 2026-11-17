"""The window in this process, rendered offscreen, with the real D-Bus backend.

Offscreen Qt has no tray, so these also cover the app without a tray icon.
"""

import unittest
from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget

from sleep_control import app as app_module
from sleep_control.backend import DBusBackend
from sleep_control.state import Controller

from . import power
from .qtapp import qt_app

HOST = "kde-session"


class WindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.qt = qt_app()
        self.blocks = power.Blocks()
        self.controller = Controller(DBusBackend())
        self.addCleanup(self.controller.allow_sleep)
        self.ui = app_module.Ui(self.qt, self.controller)
        self.addCleanup(self.ui.window.deleteLater)
        self.assertIsNone(self.ui.tray)

    def quits(self, action: Callable[[], object]) -> bool:
        """Runs action inside the Qt event loop. True when it made the app quit."""
        QTimer.singleShot(0, action)
        QTimer.singleShot(1000, lambda: self.qt.exit(1))
        return self.qt.exec() == 0

    def shown(self) -> app_module.Window:
        self.ui.show_window()
        self.qt.processEvents()
        return self.ui.window

    def click(self, text: str) -> None:
        buttons = {b.text(): b for b in self.ui.window.action_buttons + [self.ui.window.quit_button]}
        buttons[text].click()
        self.qt.processEvents()

    def gaps(self, w: QWidget) -> dict[str, int]:
        """Pixels between the window edge and the first drawn pixel on each side."""
        image = w.grab().toImage()
        bg = image.pixelColor(0, 0).rgb()
        drawn = [(x, y) for y in range(image.height()) for x in range(image.width())
                 if image.pixelColor(x, y).rgb() != bg]
        xs, ys = [p[0] for p in drawn], [p[1] for p in drawn]
        return {"top": min(ys), "bottom": image.height() - 1 - max(ys),
                "left": min(xs), "right": image.width() - 1 - max(xs)}

    def test_layout(self) -> None:
        for awake in (False, True):
            with self.subTest(awake=awake):
                (self.controller.keep_awake if awake else self.controller.allow_sleep)()
                w = self.shown()
                first, _, last = w.action_buttons
                quit_button = w.quit_button
                widths = {b.width() for b in w.action_buttons + [quit_button]}
                self.assertEqual(len(widths), 1, widths)
                left = first.geometry().left()
                right = w.width() - 1 - last.geometry().right()
                self.assertLessEqual(abs(left - right), 1)
                self.assertEqual(left, app_module.MARGIN)
                self.assertEqual(quit_button.geometry().right(), last.geometry().right())
                group_left = w.state_icon.geometry().left()
                group_right = w.state.geometry().right()
                self.assertLessEqual(abs((group_left + group_right) / 2 - w.width() / 2), 2)
                self.assertEqual(w.height(), w.sizeHint().height())
                gaps = self.gaps(w)
                self.assertLessEqual(abs(gaps["left"] - gaps["right"]), 1, gaps)
                self.assertIn(gaps["top"], (app_module.MARGIN, app_module.MARGIN + 1), gaps)
                self.assertLessEqual(abs(gaps["bottom"] - app_module.BOTTOM_MARGIN), 1, gaps)

    def test_tray_icons_have_every_size(self) -> None:
        for icon in (self.ui.icon_awake, self.ui.icon_normal):
            for size in (16, 22, 32):
                self.assertFalse(icon.pixmap(size, size).isNull())

    def test_tray_icons_share_box(self) -> None:
        def box(icon: QIcon, size: int, body: bool) -> tuple[int, int]:
            image = icon.pixmap(size, size).toImage()
            rows: list[int] = []
            for y in range(size):
                for x in range(size):
                    c = image.pixelColor(x, y)
                    if (c.alpha() > 200 and c.lightnessF() < 0.85) if body else c.alpha() > 0:
                        rows.append(y)
            return min(rows), max(rows)

        for size in (16, 22, 32):
            for body in (False, True):
                with self.subTest(size=size, body=body):
                    top_a, bottom_a = box(self.ui.icon_awake, size, body)
                    top_n, bottom_n = box(self.ui.icon_normal, size, body)
                    self.assertLessEqual(abs(bottom_a - bottom_n), 1)
                    self.assertLessEqual(abs((bottom_a - top_a) - (bottom_n - top_n)), 2)

    def test_buttons_take_and_release_the_block(self) -> None:
        w = self.shown()
        self.click("Keep awake")
        self.assertEqual(w.state.text(), "Sleep is blocked (kept awake)")
        self.assertEqual(self.blocks.wait(1), 1)
        self.click("Allow sleep")
        self.assertEqual(w.state.text(), "Sleep is allowed")
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)
        self.assertTrue(w.error.isHidden())

    def test_sleep_now_shows_the_refusal(self) -> None:
        w = self.shown()
        self.click("Keep awake")
        with power.sleep_blocked():
            self.click("Sleep now")
        self.assertFalse(w.error.isHidden())
        self.assertIn(power.DENIED, w.error.text())
        self.assertEqual(w.state.text(), "Sleep is allowed")
        self.click("Keep awake")
        self.assertTrue(w.error.isHidden())

    def test_closing_while_allowed_quits_without_a_tray(self) -> None:
        w = self.shown()
        self.assertTrue(self.quits(w.close))
        self.assertFalse(w.isVisible())

    def test_closing_while_awake_keeps_running_without_a_tray(self) -> None:
        w = self.shown()
        self.click("Keep awake")
        self.assertFalse(self.quits(w.close))
        self.assertFalse(w.isVisible())
        self.assertTrue(self.controller.awake)

    def test_quit_button(self) -> None:
        self.shown()
        self.assertTrue(self.quits(lambda: self.click("Quit")))


if __name__ == "__main__":
    unittest.main()
