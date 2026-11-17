"""The window on a Wayland desktop with no tray: KWin on a virtual screen.

KWin, the app and every command run on a private bus and runtime folder of the
test, so nothing here reaches the real desktop or an installed copy.
"""

import os
import signal
import unittest

from . import procs

HOST = "kde-session"


class DesktopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)
        self.desktop = procs.Desktop(self, self.runtime)

    def app(self, *args: str, stop_after_lock: bool = False) -> procs.App:
        return procs.App(self, self.runtime, *args, platform="wayland", bus=self.desktop.bus.address,
                         wayland=self.desktop.display, stop_after_lock=stop_after_lock)

    def test_launch_without_a_tray_opens_the_window(self) -> None:
        app = self.app()
        app.wait_ready()
        self.desktop.wait_window()
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)

    def test_background_launch_without_a_tray_stays_hidden(self) -> None:
        # What `on` starts. It holds the block with no window; the launcher brings the window up.
        app = self.app("--background")
        app.wait_ready()
        self.desktop.no_window_for(2.0)
        launch = self.app()
        self.assertEqual(launch.wait_exit(timeout=30), 0, launch.output())
        self.desktop.wait_window()
        self.assertEqual(procs.app_pids(self.runtime), [app.pid])

    def test_window_launch_that_loses_the_race_still_opens_the_window(self) -> None:
        # A launch from the menu while `on` starts the app: the other instance has
        # the lock but no socket yet.
        first = self.app("--background", stop_after_lock=True)
        first.wait_stopped()
        launch = self.app()
        try:
            self.desktop.no_window_for(1.0)
            self.assertIsNone(launch.proc.poll(), launch.output())
        finally:
            os.kill(first.pid, signal.SIGCONT)
        self.assertEqual(launch.wait_exit(timeout=30), 0, launch.output())
        self.desktop.wait_window()
        self.assertEqual(procs.app_pids(self.runtime), [first.pid])


if __name__ == "__main__":
    unittest.main()
