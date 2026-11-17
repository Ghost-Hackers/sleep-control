"""The command line as a separate process, with no instance running."""

import contextlib
import io
import os
import unittest

from sleep_control import __version__, cli, ipc

from . import procs

HOST = "any"


class ParseTest(unittest.TestCase):
    def test_actions(self) -> None:
        for arg in ("on", "off", "now", "status"):
            self.assertEqual(cli.parse([arg]), arg)
        self.assertEqual(cli.parse([]), cli.GUI)
        self.assertEqual(cli.parse(["--background"]), cli.BACKGROUND)
        self.assertEqual(cli.parse(["--version"]), cli.VERSION)
        self.assertEqual(cli.parse(["-V"]), cli.VERSION)
        for arg in ("-h", "--help", "help"):
            self.assertEqual(cli.parse([arg]), cli.HELP)

    def test_bad_input(self) -> None:
        for argv in (["menu"], ["ON"], ["on", "off"], [""], ["--on"]):
            with self.assertRaises(cli.UsageError, msg=argv):
                cli.parse(argv)

    def test_main_reads_sys_argv(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--version"]), 0)
        self.assertEqual(out.getvalue(), f"sleep-control {__version__}\n")


class NoInstanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = procs.runtime_dir(self)

    def test_usage_errors_exit_2(self) -> None:
        for args in (["bogus"], ["on", "off"]):
            r = procs.cli(self.runtime, *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage:", r.stderr)
        self.assertIn("unknown action: bogus", procs.cli(self.runtime, "bogus").stderr)

    def test_version_and_help(self) -> None:
        r = procs.cli(self.runtime, "--version")
        self.assertEqual((r.returncode, r.stdout), (0, f"sleep-control {__version__}\n"))
        r = procs.cli(self.runtime, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, cli.USAGE)

    def test_status_and_off_answer_allowed(self) -> None:
        for action in ("status", "off"):
            r = procs.cli(self.runtime, action)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "Sleep is allowed\n", ""), action)

    def test_socket_folder_without_access_is_reported(self) -> None:
        folder = os.path.dirname(procs.sock(self.runtime))
        os.makedirs(folder, mode=0o700)
        os.chmod(folder, 0)
        self.addCleanup(os.chmod, folder, 0o700)
        r = procs.cli(self.runtime, "status")
        self.assertEqual(r.returncode, 1)
        self.assertIn("can't reach the running instance: [Errno 13] Permission denied", r.stderr)

    def test_default_path_is_in_the_app_folder(self) -> None:
        r = procs.cli(self.runtime, "status")
        self.assertEqual(r.returncode, 0)
        code = "from sleep_control import ipc; print(ipc.default_path())"
        import subprocess
        import sys
        out = subprocess.run([sys.executable, "-c", code], env=procs.env(self.runtime), capture_output=True,
                             text=True, check=True).stdout.strip()
        self.assertEqual(out, procs.sock(self.runtime))
        self.assertTrue(ipc.default_path().endswith("/control.sock"))


if __name__ == "__main__":
    unittest.main()
