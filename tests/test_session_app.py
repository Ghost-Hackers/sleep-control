"""The app in the desktop session: real portal, PowerDevil, tray and logind.

Each instance has its own runtime folder, so an installed copy that may be
running is never reached. Blocks are checked in PowerDevil's own list.
"""

import os
import signal
import time
import unittest

from . import power, procs
from .tray import Tray

HOST = "kde-session"
BLOCKED = "Sleep is blocked (kept awake)"
ALLOWED = "Sleep is allowed"
WATCHER = "org.kde.StatusNotifierWatcher"


class SessionAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = power.Blocks()

    def start(self) -> procs.App:
        runtime = procs.runtime_dir(self)
        app = procs.App(self, runtime, "--background", platform="wayland")
        app.wait_ready()
        return app

    def test_command_line_on_off_and_now(self) -> None:
        runtime = procs.runtime_dir(self)
        r = procs.cli(runtime, "on")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, BLOCKED + "\n", ""))
        self.assertEqual(len(procs.app_pids(runtime)), 1)
        r = procs.cli(runtime, "on")
        self.assertEqual((r.returncode, r.stdout), (0, BLOCKED + "\n"))
        self.assertEqual(self.blocks.wait(1), 1)
        self.assertEqual(self.blocks.wait(2, timeout=2), 1, "a second `on` took another inhibition")
        self.assertEqual(len(procs.app_pids(runtime)), 1)
        self.assertEqual(procs.cli(runtime, "status").stdout, BLOCKED + "\n")
        r = procs.cli(runtime, "off")
        self.assertEqual((r.returncode, r.stdout), (0, ALLOWED + "\n"))
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)
        procs.cli(runtime, "on")
        with power.sleep_blocked():
            r = procs.cli(runtime, "now")
        self.assertEqual(r.returncode, 1)
        self.assertIn(power.DENIED, r.stderr)
        self.assertEqual(procs.cli(runtime, "status").stdout, ALLOWED + "\n")
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)

    def test_now_without_an_instance_is_refused_by_logind(self) -> None:
        runtime = procs.runtime_dir(self)
        with power.sleep_blocked():
            r = procs.cli(runtime, "now")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"can't suspend: {power.DENIED}", r.stderr)

    def test_block_ends_with_the_process(self) -> None:
        killed, termed, quit_from_tray = self.start(), self.start(), self.start()
        menu = Tray(quit_from_tray.pid)
        for app in (killed, termed, quit_from_tray):
            self.assertEqual(procs.answer(app.runtime, b"on\n"), f"ok {BLOCKED}\n".encode())
        self.assertEqual(self.blocks.wait(3), 3)

        os.kill(killed.pid, signal.SIGKILL)
        killed.wait_exit()
        self.assertEqual(self.blocks.wait(2, timeout=5), 2, "SIGKILL left the block in place")

        os.kill(termed.pid, signal.SIGTERM)
        self.assertEqual(termed.wait_exit(), 0)
        self.assertEqual(self.blocks.wait(1, timeout=5), 1, "SIGTERM left the block in place")

        menu.click("Quit")
        self.assertEqual(quit_from_tray.wait_exit(), 0)
        self.assertEqual(self.blocks.wait(0, timeout=5), 0, "Quit left the block in place")
        self.assertFalse(os.path.exists(procs.sock(quit_from_tray.runtime)))

    def test_tray_menu_and_clicks(self) -> None:
        app = self.start()
        menu = Tray(app.pid)
        entries = menu.entries()
        self.assertEqual(entries[ALLOWED][1], False)
        for label in ("Allow sleep", "Keep awake", "Sleep now", "Show window", "Quit"):
            self.assertIn(label, entries)
        self.assertIn(ALLOWED, menu.tooltip())

        menu.click("Keep awake")
        self.assertEqual(procs.answer(app.runtime, b"status\n"), f"ok {BLOCKED}\n".encode())
        self.assertIn(BLOCKED, menu.entries())
        self.assertIn(BLOCKED, menu.tooltip())
        menu.click("Allow sleep")
        self.assertEqual(procs.answer(app.runtime, b"status\n"), f"ok {ALLOWED}\n".encode())

        # Left click shows the window, the next one hides it; a middle click does nothing.
        for secondary in (False, False, True):
            menu.activate(secondary)
            time.sleep(0.3)
        menu.click("Show window")
        self.assertEqual(procs.answer(app.runtime, b"show\n"), f"ok {ALLOWED}\n".encode())

        menu.click("Keep awake")
        with power.sleep_blocked():
            menu.click("Sleep now")
            self.assertEqual(procs.answer(app.runtime, b"status\n"), f"ok {ALLOWED}\n".encode())
        self.assertEqual(app.proc.poll(), None)
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)

    def test_tray_that_starts_after_the_app(self) -> None:
        # As at login, when the app can start before the panel: a bus with no tray watcher
        # yet, then Plasma's watcher comes up and the icon has to show up in it.
        runtime = procs.runtime_dir(self)
        bus = procs.PrivateBus(self, runtime)
        app = procs.App(self, runtime, "--background", platform="wayland", bus=bus.address)
        app.wait_ready()
        self.assertFalse(bus.has_name(WATCHER))
        procs.TrayWatcher(self, runtime, bus.address)
        bus.wait_name(WATCHER)
        menu = Tray(app.pid, bus=f"--address={bus.address}")
        self.assertIn(ALLOWED, menu.tooltip())
        self.assertIn("Show window", menu.entries())
        self.assertEqual(app.proc.poll(), None)


if __name__ == "__main__":
    unittest.main()
