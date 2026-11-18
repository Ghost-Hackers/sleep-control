"""The runner's bus name lookup, on a bus of the test's own."""

import subprocess
import sys
import unittest

from . import procs, run

HOST = "any"
NEEDS = ("busctl",)

# Owns NAME on the session bus until stdin closes.
OWN_NAME = """
import sys
from PyQt6.QtDBus import QDBusConnection
print("ready" if QDBusConnection.sessionBus().registerService("NAME") else "taken", flush=True)
sys.stdin.read()
"""


class NamePidTest(unittest.TestCase):
    def test_name_pid_on_a_private_bus(self) -> None:
        tmp = procs.runtime_dir(self)
        bus = procs.PrivateBus(self, tmp)
        flag = f"--address={bus.address}"
        name = "org.example.SleepControlTest"
        self.assertIsNone(run.name_pid(flag, name))
        owner = subprocess.Popen([sys.executable, "-c", OWN_NAME.replace("NAME", name)],
                                 env=procs.env(tmp, bus=bus.address), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(owner.wait, 10)
        assert owner.stdin is not None and owner.stdout is not None
        self.addCleanup(owner.stdout.close)
        self.addCleanup(owner.stdin.close)
        self.assertEqual(owner.stdout.readline().strip(), "ready")
        self.assertEqual(run.name_pid(flag, name), owner.pid)
        self.assertEqual(run.name_pid(flag, "org.freedesktop.DBus"), bus.proc.pid)


if __name__ == "__main__":
    unittest.main()
