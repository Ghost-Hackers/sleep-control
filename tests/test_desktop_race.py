"""A window launch that loses the start race on a Wayland desktop with no tray.

KWin, the app and every command run on a private bus and runtime folder of the
test, as in test_desktop. strace stops the first app right after it takes the
instance lock (procs.STOP_AFTER_LOCK).
"""

import os
import signal
import unittest

from . import procs

HOST = "kde-session"
NEEDS = ("strace",)


class DesktopRaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)
        self.desktop = procs.Desktop(self, self.runtime)

    def app(self, *args: str, stop_after_lock: bool = False) -> procs.App:
        return procs.App(self, self.runtime, *args, platform="wayland", bus=self.desktop.bus.address,
                         wayland=self.desktop.display, stop_after_lock=stop_after_lock)

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
