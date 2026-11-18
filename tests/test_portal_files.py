"""The runner against a desktop portal of the test's own that runs short of file descriptors.

The test's bus starts the portal on the first call, next to KWin on a virtual screen.
The portal keeps a pidfd for every Inhibit caller. The session's own portal is not used.
"""

import os
import re
import subprocess
import sys
import time
import unittest

from . import procs, run

HOST = "kde-session"
NEEDS = ("prlimit", "dbus-update-activation-environment")


class PortalFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = procs.runtime_dir(self)
        self.env = procs.own_home(procs.env(self.tmp), os.path.join(self.tmp, "home"))
        os.makedirs(self.env["XDG_CONFIG_HOME"])
        bus = self.start(["dbus-daemon", "--session", "--nofork", "--print-address=1"], self.env, stdout=True)
        assert bus.stdout is not None
        self.addCleanup(bus.stdout.close)
        self.address = bus.stdout.readline().strip()
        self.env["DBUS_SESSION_BUS_ADDRESS"] = self.address
        self.start(["kwin_wayland", "--virtual", "--socket", "wayland-test", "--no-lockscreen",
                    "--no-global-shortcuts", "--no-kactivities"], self.env)
        self.wait_name("org.kde.KWin")
        self.env.update(WAYLAND_DISPLAY=os.path.join(self.tmp, "wayland-test"), XDG_CURRENT_DESKTOP="KDE",
                        QT_QPA_PLATFORM="wayland")
        subprocess.run(["dbus-update-activation-environment", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP",
                        "QT_QPA_PLATFORM"], env=self.env, check=True, timeout=10)

    def start(self, args: list[str], env: dict[str, str], stdout: bool = False) -> subprocess.Popen[str]:
        proc = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE if stdout else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.terminate)
        return proc

    def wait_name(self, name: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while run.name_pid(f"--address={self.address}", name) is None:
            if time.monotonic() > deadline:
                raise AssertionError(f"nothing took {name} on the test's bus within {timeout} s")
            time.sleep(0.1)

    def inhibit(self) -> None:
        """One Inhibit call from a process of its own, as each session test makes."""
        subprocess.run(["busctl", f"--address={self.address}", "call", "org.freedesktop.portal.Desktop",
                        "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Inhibit", "Inhibit",
                        "sua{sv}", "", "4", "0"], capture_output=True, check=True, timeout=30)

    def settled(self, pid: int) -> int:
        """How many files pid has open once the count holds still."""
        deadline = time.monotonic() + 20
        count = -1
        while True:
            time.sleep(0.2)
            now = len(os.listdir(f"/proc/{pid}/fd"))
            if now == count:
                return count
            if time.monotonic() > deadline:
                raise AssertionError(f"the portal's open files kept changing, last {count} then {now}")
            count = now

    def listed(self) -> str:
        r = subprocess.run([sys.executable, "-m", "tests.run", "--list"], env=dict(self.env, TMPDIR=self.tmp),
                           cwd=procs.ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        return r.stderr

    def test_runner_names_a_portal_out_of_descriptors(self) -> None:
        self.inhibit()
        portal = run.name_pid(f"--address={self.address}", run.PORTAL)
        assert portal is not None
        self.assertIn(portal, procs.pids_in(self.tmp))
        count = self.settled(portal)
        limit = count + run.PORTAL_FREE_FDS + 8
        subprocess.run(["prlimit", f"--pid={portal}", f"--nofile={limit}"], check=True, timeout=10)
        self.assertNotIn("xdg-desktop-portal with free file descriptors", self.listed())
        for _ in range(30):
            self.inhibit()
        listed = self.listed()
        entry = re.search(r"xdg-desktop-portal with free file descriptors \(([\d,]+) of ([\d,]+) open; "
                          r"restart it with: systemctl --user restart xdg-desktop-portal\)", listed)
        now = len(os.listdir(f"/proc/{portal}/fd"))
        assert entry is not None, f"{count} then {now} of {limit} open: {listed[-300:]}"
        self.assertEqual(entry.group(2), f"{limit:,}")
        self.assertGreater(int(entry.group(1).replace(",", "")), count)


if __name__ == "__main__":
    unittest.main()
