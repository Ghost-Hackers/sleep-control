"""The app inside a Flatpak sandbox: the paths that only run there."""

import os
import signal
import subprocess
import time
import unittest

from . import procs
from .sandbox import Sandbox

HOST = "flatpak"


class FlatpakTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sandbox = Sandbox()

    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)

    def test_instance_in_the_sandbox(self) -> None:
        # Inside the sandbox the window and tray icons come from /app/share/sleep-control/icons.
        log = open(os.path.join(self.runtime, "sandbox.log"), "w+")
        self.addCleanup(log.close)
        proc = subprocess.Popen(self.sandbox.command(self.runtime, "--background"), stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT)
        self.addCleanup(proc.wait, 15)
        deadline = time.monotonic() + 30
        while not os.path.exists(procs.sock(self.runtime)):
            if proc.poll() is not None:
                log.seek(0)
                self.fail(f"the sandbox ended with {proc.returncode}: {log.read()[-2000:]}")
            self.assertLess(time.monotonic(), deadline, "the instance in the sandbox didn't listen")
            time.sleep(0.1)
        self.assertEqual(procs.answer(self.runtime, b"status\n"), b"ok Sleep is allowed\n")
        self.assertEqual(procs.answer(self.runtime, b"show\n"), b"ok Sleep is allowed\n")
        (pid,) = procs.app_pids(self.runtime)
        self.assertTrue(os.path.exists(f"/proc/{pid}/root/.flatpak-info"), "the instance isn't in a sandbox")
        os.kill(pid, signal.SIGTERM)
        self.assertEqual(proc.wait(15), 0)

    def test_on_asks_the_flatpak_portal_to_start_the_instance(self) -> None:
        # The sandbox's app ID isn't installed, so the spawned instance never comes up and
        # the command gives up after 15 s. A refused Spawn would say "can't start" instead.
        started = time.monotonic()
        r = subprocess.run(self.sandbox.command(self.runtime, "on"), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Sleep Control didn't start", r.stderr)
        self.assertGreaterEqual(time.monotonic() - started, 15)
        self.assertEqual(procs.app_pids(self.runtime), [])


if __name__ == "__main__":
    unittest.main()
