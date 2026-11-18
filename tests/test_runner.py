"""The test runner on machines that lack some of what the tests need.

Each case runs tests/run.py as its own process with a PATH that leaves programs
out, and a temp folder of its own so it doesn't wait for the lock of the run
that started it.
"""

import os
import subprocess
import sys
import unittest

from . import procs, run

HOST = "any"


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = procs.runtime_dir(self)

    def path_without(self, *left_out: str) -> str:
        """A folder with a link to every program on PATH but left_out."""
        folder = os.path.join(self.tmp, "bin")
        os.mkdir(folder)
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            try:
                names = os.listdir(directory)
            except OSError:
                continue
            for name in names:
                target = os.path.join(directory, name)
                link = os.path.join(folder, name)
                if (name in left_out or os.path.lexists(link) or not os.path.isfile(target)
                        or not os.access(target, os.X_OK)):
                    continue
                os.symlink(target, link)
        return folder

    def run_tests(self, path: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PATH=path, TMPDIR=self.tmp)
        env.pop("WAYLAND_DISPLAY", None)
        return subprocess.run([sys.executable, "-m", "tests.run", *args], env=env, cwd=procs.ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    def test_portable_module_runs_without_strace(self) -> None:
        r = self.run_tests(self.path_without("strace"), "tests.test_version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("test: 2 tests in 1 modules for hosts any", r.stdout)

    def test_default_run_without_strace_takes_the_portable_modules(self) -> None:
        r = self.run_tests(self.path_without("strace"), "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        listed = r.stdout.splitlines()
        for module in ("tests.test_cli", "tests.test_coverage_gate", "tests.test_instance", "tests.test_version"):
            self.assertIn(module, listed)
        self.assertNotIn("tests.test_instance_race", listed)
        self.assertIn("test: not run here: tests.test_instance_race needs the any host and strace; missing: strace",
                      r.stderr)

    def test_race_module_without_strace_fails_and_says_why(self) -> None:
        r = self.run_tests(self.path_without("strace"), "tests.test_instance_race")
        self.assertEqual(r.returncode, 1)
        self.assertIn("test: tests.test_instance_race needs the any host and strace; missing here: strace", r.stderr)
        self.assertNotIn(" tests in ", r.stdout)

    def test_portal_module_names_the_programs_it_runs(self) -> None:
        r = self.run_tests(self.path_without("prlimit", "dbus-update-activation-environment"), "--list")
        line = next((x for x in r.stderr.splitlines()
                     if x.startswith("test: not run here: tests.test_portal_files ")), "")
        self.assertIn("needs the kde-session host and prlimit and dbus-update-activation-environment; missing: ", line)
        self.assertTrue(line.endswith(", prlimit, dbus-update-activation-environment"), line)

    def test_name_pid_without_busctl_is_none(self) -> None:
        r = subprocess.run([sys.executable, "-c",
                            "from tests import run; print(run.name_pid('--user', 'org.freedesktop.DBus'))"],
                           env=dict(os.environ, PATH=self.path_without("busctl")), cwd=procs.ROOT,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, "None\n"), r.stderr)

    def test_run_with_nothing_to_run_fails(self) -> None:
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        r = self.run_tests(empty)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("test: no tests to run on this machine", r.stderr)


# Opens /dev/null until the limit is reached, closes FREE of them and waits for stdin to close.
HOLD_FILES = """
import os, sys
held = []
try:
    while True:
        held.append(os.open("/dev/null", os.O_RDONLY))
except OSError:
    pass
for fd in held[-FREE:]:
    os.close(fd)
print("ready", flush=True)
sys.stdin.read()
"""

class PortalFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = procs.runtime_dir(self)

    def child(self, args: list[str], env: dict[str, str]) -> subprocess.Popen[str]:
        proc = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait, 10)
        assert proc.stdin is not None and proc.stdout is not None
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stdin.close)
        self.assertEqual(proc.stdout.readline().strip(), "ready")
        return proc

    def test_open_files_reads_a_real_process(self) -> None:
        code = HOLD_FILES.replace("FREE", "5")
        proc = self.child(["prlimit", "--nofile=40", sys.executable, "-I", "-c", code], dict(os.environ))
        self.assertEqual(run.open_files(proc.pid), (35, 40))
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(10)
        self.assertIsNone(run.open_files(proc.pid))

    def test_entry_only_when_too_few_are_free(self) -> None:
        self.assertEqual(run.PORTAL_FREE_FDS, 64)
        for count, limit in ((960, 1024), (0, 64), (1047, 16384)):
            self.assertEqual(run.portal_files_missing(count, limit), [], (count, limit))
        restart = "restart it with: systemctl --user restart xdg-desktop-portal)"
        self.assertEqual(run.portal_files_missing(961, 1024),
                         [f"xdg-desktop-portal with free file descriptors (961 of 1,024 open; {restart}"])
        self.assertEqual(run.portal_files_missing(1022, 1024),
                         [f"xdg-desktop-portal with free file descriptors (1,022 of 1,024 open; {restart}"])
        self.assertEqual(run.portal_files_missing(16330, 16384),
                         [f"xdg-desktop-portal with free file descriptors (16,330 of 16,384 open; {restart}"])


if __name__ == "__main__":
    unittest.main()
