"""The running instance and its control socket, as separate processes.

Every app here runs offscreen on a session bus of its own (dbus-run-session
with a bus that starts no services), so there is no desktop portal and no tray. That is a real setup the app has to
cope with, and it is the same on the CI runner and on a desktop.
"""

import errno
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import unittest

from . import procs

HOST = "any"
NO_PORTAL = "org.freedesktop.portal.Desktop"


class InstanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)
        self.sock = procs.sock(self.runtime)

    def start(self, *args: str) -> procs.App:
        app = procs.App(self, self.runtime, *args, private_bus=True)
        app.wait_ready()
        return app

    def ask(self, command: bytes) -> bytes:
        return procs.answer(self.runtime, command)

    def test_answers_on_a_private_socket(self) -> None:
        self.start("--background")
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")
        self.assertEqual(self.ask(b"show\n"), b"ok Sleep is allowed\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.sock).st_mode) & 0o077, 0)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.sock)).st_mode), 0o700)
        r = procs.cli(self.runtime, "status")
        self.assertEqual((r.returncode, r.stdout), (0, "Sleep is allowed\n"))

    def test_without_a_portal_on_and_now_fail_and_say_why(self) -> None:
        self.start("--background")
        answer = self.ask(b"on\n").decode()
        self.assertTrue(answer.startswith("error ") and NO_PORTAL in answer, answer)
        r = procs.cli(self.runtime, "on")
        self.assertEqual(r.returncode, 1)
        self.assertIn(NO_PORTAL, r.stderr)
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")
        self.assertEqual(self.ask(b"off\n"), b"ok Sleep is allowed\n")

    def test_refuses_unknown_empty_and_oversized_commands(self) -> None:
        self.start("--background")
        for command in (b"rm -rf /\n", b"\n", b"x" * 60 + b"\n", b"\xff\xfe\n", b"on now\n"):
            self.assertTrue(self.ask(command).startswith(b"error unknown command"), command)
        # The instance reads a bounded line and hangs up on the rest, while the
        # client is still sending (broken pipe) or reading (reset).
        with self.assertRaises((ConnectionResetError, BrokenPipeError)):
            self.ask(b"x" * 100_000 + b"\n")
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")

    def test_clients_that_hang_up_or_stay_silent_do_not_stop_it(self) -> None:
        self.start("--background")
        for _ in range(3):
            rude = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            rude.connect(self.sock)
            rude.close()
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        silent.connect(self.sock)
        time.sleep(2.5)  # the instance gives up on a client after 2 s
        silent.close()
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")

    def test_second_launch_hands_over(self) -> None:
        first = self.start("--background")
        for args in (["--background"], []):
            r = procs.cli(self.runtime, *args, timeout=20)
            self.assertEqual(r.returncode, 0, args)
        self.assertEqual(first.proc.poll(), None)
        self.assertEqual(len(procs.app_pids(self.runtime)), 1)

    def test_launches_at_the_same_time_leave_one_instance(self) -> None:
        apps = [procs.App(self, self.runtime, "--background", private_bus=True) for _ in range(4)]
        codes = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and len(codes) < 3:
            codes = [a.proc.poll() for a in apps if a.proc.poll() is not None]
            time.sleep(0.1)
        self.assertEqual(codes, [0, 0, 0])
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")

    def test_window_launch_without_a_tray_shows_the_window(self) -> None:
        app = self.start()
        self.assertEqual(self.ask(b"show\n"), b"ok Sleep is allowed\n")
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)

    def test_signals_quit_cleanly_and_remove_the_socket(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                app = self.start("--background")
                os.kill(app.pid, sig)
                self.assertEqual(app.wait_exit(), 0)
                self.assertFalse(os.path.exists(self.sock))

    def test_socket_left_by_a_killed_instance_is_taken_over(self) -> None:
        app = self.start("--background")
        os.kill(app.pid, signal.SIGKILL)
        app.wait_exit()
        self.assertTrue(os.path.exists(self.sock))
        r = procs.cli(self.runtime, "status")
        self.assertEqual((r.returncode, r.stdout), (0, "Sleep is allowed\n"))
        self.start("--background")
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")

    def test_socket_removed_or_locked_before_quit(self) -> None:
        app = self.start("--background")
        os.unlink(self.sock)
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)
        app = self.start("--background")
        folder = os.path.dirname(self.sock)
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)
        self.assertTrue(os.path.exists(self.sock))

    def test_instance_that_dies_mid_request(self) -> None:
        app = self.start("--background")
        os.kill(app.pid, signal.SIGSTOP)
        cli = subprocess.Popen([sys.executable, "-m", "sleep_control", "status"], env=procs.env(self.runtime),
                               cwd=procs.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        os.kill(app.pid, signal.SIGKILL)
        out, err = cli.communicate(timeout=30)
        self.assertEqual((cli.returncode, out, err), (0, "Sleep is allowed\n", ""))

    def test_stuck_instance_keeps_its_socket(self) -> None:
        # A stopped instance takes connections but never answers, like one whose Qt
        # thread waits on a slow portal call. A new launch must not take its place.
        first = self.start("--background")
        inode = os.stat(self.sock).st_ino
        os.kill(first.pid, signal.SIGSTOP)
        try:
            second = procs.App(self, self.runtime, "--background", private_bus=True)
            self.assertEqual(second.wait_exit(timeout=30), 1, second.output())
            self.assertIn("can't reach the running instance", second.output())
            self.assertEqual(os.stat(self.sock).st_ino, inode)
            self.assertEqual(procs.app_pids(self.runtime), [first.pid])
        finally:
            os.kill(first.pid, signal.SIGCONT)
        self.assertEqual(self.ask(b"status\n"), b"ok Sleep is allowed\n")

    def test_unwritable_app_folder(self) -> None:
        folder = os.path.dirname(self.sock)
        os.makedirs(folder, mode=0o700)
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        app = procs.App(self, self.runtime, "--background", private_bus=True)
        self.assertEqual(app.wait_exit(), 1)
        self.assertIn("PermissionError", app.output())
        started = time.monotonic()
        r = procs.private_cli(self.runtime, "on")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Sleep Control didn't start", r.stderr)
        self.assertLess(time.monotonic() - started, 10, "the command waited for an instance that had exited")

    def test_app_folder_made_read_only_after_a_run(self) -> None:
        # The lock file stays when an instance quits, so the lock still opens and binding the socket fails.
        app = self.start("--background")
        os.kill(app.pid, signal.SIGTERM)
        self.assertEqual(app.wait_exit(), 0)
        self.assertTrue(os.path.exists(self.sock + ".lock"))
        folder = os.path.dirname(self.sock)
        os.chmod(folder, 0o500)
        self.addCleanup(os.chmod, folder, 0o700)
        app = procs.App(self, self.runtime, "--background", private_bus=True)
        self.assertEqual(app.wait_exit(), 1)
        self.assertIn("PermissionError", app.output())
        os.chmod(folder, 0o700)
        self.start("--background")

    def test_instance_that_never_answers(self) -> None:
        # The instance connects to the session bus before it listens, so with the bus
        # daemon stopped it stays alive without ever answering.
        bus = procs.PrivateBus(self, self.runtime)
        bus.stop()
        started = time.monotonic()
        r = subprocess.run([sys.executable, "-m", "sleep_control", "on"], env=procs.env(self.runtime, bus=bus.address),
                           cwd=procs.ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        waited = time.monotonic() - started
        self.assertEqual(r.returncode, 1)
        self.assertIn("Sleep Control didn't start", r.stderr)
        self.assertGreaterEqual(waited, 15, "the command gave up before its 15 s wait")
        waiting = [p for p in procs.pids_in(self.runtime) if b"--background" in _cmdline(p)]
        self.assertEqual(len(waiting), 1, "the instance should still be waiting for the bus")
        os.kill(waiting[0], signal.SIGKILL)
        self.assertTrue(procs.wait_gone(waiting))

    def test_starting_the_instance_fails(self) -> None:
        # RLIMIT_NPROC 0: the kernel refuses every new process of this user, so the
        # command line can't start an instance.
        r = subprocess.run(["prlimit", "--nproc=0", "--", sys.executable, "-m", "sleep_control", "on"],
                           env=procs.env(self.runtime), cwd=procs.ROOT, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"can't start Sleep Control: [Errno {errno.EAGAIN}]", r.stderr)
        self.assertEqual(procs.app_pids(self.runtime), [])

    def test_on_without_an_instance_starts_one(self) -> None:
        r = procs.private_cli(self.runtime, "on")
        self.assertEqual(r.returncode, 1)
        self.assertIn(NO_PORTAL, r.stderr)
        self.assertTrue(any(b"--background" in _cmdline(p) for p in procs.pids_in(self.runtime)))


def _cmdline(pid: int) -> bytes:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read()
    except OSError:
        return b""


if __name__ == "__main__":
    unittest.main()
