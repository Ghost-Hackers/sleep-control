"""The test runner on machines that lack some of what the tests need.

Each case runs tests/run.py as its own process with a PATH that leaves programs
out, and a temp folder of its own so it doesn't wait for the lock of the run
that started it.
"""

import os
import subprocess
import sys
import unittest

from . import procs

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

    def test_run_with_nothing_to_run_fails(self) -> None:
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        r = self.run_tests(empty)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("test: no tests to run on this machine", r.stderr)


if __name__ == "__main__":
    unittest.main()
