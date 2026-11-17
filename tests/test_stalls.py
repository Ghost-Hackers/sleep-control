"""The instance when the session bus or the desktop portal stops answering or goes away.

The bus daemon, the portal and the bus proxy here are processes the test starts
itself, so it can stop them with SIGSTOP or end them without touching the
desktop session's own bus and portal. The portal is the session's own program
(found through its D-Bus service file), started on a private bus.
"""

import os
import select
import signal
import subprocess
import sys
import time
import unittest
from typing import IO

from . import power, procs

HOST = "kde-session"
PORTAL = "org.freedesktop.portal.Desktop"
BLOCKED = "Sleep is blocked (kept awake)"
PROBE = "io.github.ghost_hackers.SleepControlTests"


def portal_program() -> str:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for folder in dirs.split(":"):
        try:
            with open(os.path.join(folder, "dbus-1", "services", f"{PORTAL}.service")) as f:
                for line in f:
                    if line.startswith("Exec="):
                        return line.split("=", 1)[1].split()[0]
        except OSError:
            continue
    raise AssertionError(f"no D-Bus service file for {PORTAL}")


def read_until(stream: IO[str], text: str, timeout: float = 30.0) -> bool:
    """Reads lines until one holds text. False when none did within timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([stream], [], [], max(0.0, deadline - time.monotonic()))
        if ready:
            line = stream.readline()
            if not line:
                break
            if text in line:
                return True
    return False


def end(proc: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
    """Continues a process the test stopped, then ends it."""
    proc.send_signal(signal.SIGCONT)
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(10)


def _cmdline(pid: int) -> bytes:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read()
    except OSError:
        return b""


class StallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)

    def test_instance_killed_while_it_waits_for_the_portal(self) -> None:
        # The command line starts an instance, which answers its status check and
        # then waits for the stopped portal while handling `on`. Killed there, it
        # closes the connection without an answer, and the command line reports
        # that the instance didn't start.
        bus = procs.PrivateBus(self, self.runtime)
        env = procs.env(self.runtime, bus=bus.address)
        portal = subprocess.Popen([portal_program()], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.addCleanup(end, portal)
        bus.wait_name(PORTAL)
        os.kill(portal.pid, signal.SIGSTOP)
        monitor = subprocess.Popen(["dbus-monitor", "--address", bus.address, "--monitor",
                                    "type='method_call',interface='org.freedesktop.portal.Inhibit'",
                                    f"type='signal',interface='{PROBE}'"],
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        assert monitor.stdout is not None
        self.addCleanup(monitor.stdout.close)
        self.addCleanup(end, monitor)
        # The monitor is in place once it shows a signal sent after it started.
        for _ in range(100):
            subprocess.run(["dbus-send", f"--address={bus.address}", "--type=signal", "/", f"{PROBE}.Ready"],
                           env=env, check=True, timeout=10)
            if read_until(monitor.stdout, "member=Ready", timeout=0.2):
                break
        else:
            self.fail("dbus-monitor didn't start")
        cli = subprocess.Popen([sys.executable, "-m", "sleep_control", "on"], env=env, cwd=procs.ROOT,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertTrue(read_until(monitor.stdout, "member=Inhibit"), "the instance never called the portal")
        waiting = [p for p in procs.pids_in(self.runtime) if b"--background" in _cmdline(p)]
        self.assertEqual(len(waiting), 1)
        os.kill(waiting[0], signal.SIGKILL)
        out, err = cli.communicate(timeout=30)
        self.assertEqual((cli.returncode, out), (1, ""))
        self.assertIn("Sleep Control didn't start", err)

    def test_bus_connection_lost_while_awake(self) -> None:
        # The instance reaches the session bus through an xdg-dbus-proxy of the
        # test's own. When the proxy ends, the portal drops the block with the
        # connection, and the instance can't release it on quit any more.
        blocks = power.Blocks()
        proxy_path = os.path.join(self.runtime, "bus-proxy")
        session = procs.env(self.runtime)["DBUS_SESSION_BUS_ADDRESS"]
        proxy = subprocess.Popen(["xdg-dbus-proxy", session, proxy_path], env=procs.env(self.runtime),
                                 stdin=subprocess.DEVNULL)
        self.addCleanup(end, proxy)
        deadline = time.monotonic() + 10
        while not os.path.exists(proxy_path) and time.monotonic() < deadline:
            time.sleep(0.05)
        app = procs.App(self, self.runtime, "--background", bus=f"unix:path={proxy_path}")
        app.wait_ready()
        self.assertEqual(procs.answer(self.runtime, b"on\n"), f"ok {BLOCKED}\n".encode())
        self.assertEqual(blocks.wait(1), 1)
        end(proxy)
        self.assertEqual(blocks.wait(0), 0, "the portal kept the block of a connection that closed")
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)
        self.assertRegex(app.output(), r"sleep-control: .*(onnect|Disconnected)")


if __name__ == "__main__":
    unittest.main()
