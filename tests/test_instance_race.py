"""Two launches at the same time: one gets the instance lock, the other has to wait or take over.

strace stops the first app right after it takes the lock (procs.STOP_AFTER_LOCK),
which holds the race open for as long as the test needs.
"""

import os
import signal
import time
import unittest

from . import procs

HOST = "any"
NEEDS = ("strace",)


class InstanceRaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)

    def stopped_after_lock(self) -> procs.App:
        """An instance that has taken the lock but has no socket yet, as in a race of two launches."""
        app = procs.App(self, self.runtime, "--background", private_bus=True, stop_after_lock=True)
        app.wait_stopped()
        return app

    def test_launch_that_loses_the_race_waits_for_the_winner(self) -> None:
        first = self.stopped_after_lock()
        second = procs.App(self, self.runtime, private_bus=True)
        try:
            time.sleep(1.0)
            self.assertIsNone(second.proc.poll(), second.output())
        finally:
            os.kill(first.pid, signal.SIGCONT)
        self.assertEqual(second.wait_exit(timeout=30), 0, second.output())
        self.assertEqual(procs.app_pids(self.runtime), [first.pid])

    def test_launch_that_loses_the_race_to_a_stuck_instance_fails(self) -> None:
        first = self.stopped_after_lock()
        try:
            second = procs.App(self, self.runtime, private_bus=True)
            self.assertEqual(second.wait_exit(timeout=30), 1, second.output())
            self.assertIn("another instance is starting and doesn't answer", second.output())
        finally:
            os.kill(first.pid, signal.SIGCONT)
        first.wait_ready()
        self.assertEqual(procs.app_pids(self.runtime), [first.pid])

    def test_launch_that_loses_the_race_to_one_that_dies_takes_over(self) -> None:
        first = self.stopped_after_lock()
        second = procs.App(self, self.runtime, "--background", private_bus=True)
        time.sleep(1.0)
        pid = first.pid
        os.kill(pid, signal.SIGKILL)
        second.wait_ready()
        self.assertEqual(procs.app_pids(self.runtime), [second.pid])
        self.assertNotEqual(second.pid, pid)


if __name__ == "__main__":
    unittest.main()
