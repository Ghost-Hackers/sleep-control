"""tests/e2e/run.sh before it touches the app: its arguments and its check for a running instance.

Each case runs the script in a process namespace of its own, so an instance the developer has open
is neither seen nor signalled.
"""

import os
import subprocess
import sys
import unittest

from . import procs

HOST = "flatpak"
NEEDS = ("unshare",)

SCRIPT = os.path.join(procs.ROOT, "tests", "e2e", "run.sh")
NAMESPACE = ["unshare", "--user", "--map-current-user", "--pid", "--fork", "--mount-proc"]

# Starts the app from this checkout ($1 is its interpreter), runs the script, and says if the app is still there.
WITH_AN_INSTANCE = r"""
XDG_RUNTIME_DIR=$2 PYTHONPATH=src QT_QPA_PLATFORM=offscreen dbus-run-session -- "$1" -m sleep_control >/dev/null 2>&1 &
pid=""
for _ in $(seq 1 100); do
  for p in $(pgrep -x python3); do
    if tr '\0' ' ' <"/proc/$p/cmdline" | grep -q -- '-m sleep_control'; then pid=$p; fi
  done
  [ -n "$pid" ] && break
  sleep 0.2
done
[ -n "$pid" ] || { echo "no instance"; exit 1; }
bash tests/e2e/run.sh
echo "rc $?"
sleep 1
if kill -0 "$pid" 2>/dev/null; then echo "instance alive"; else echo "instance gone"; fi
kill -TERM "$pid" 2>/dev/null
"""


class BeforeTheAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = procs.runtime_dir(self)

    def run_inside(self, *command: str) -> subprocess.CompletedProcess[str]:
        """Runs command in the namespace, away from the session bus and the installed app."""
        env = dict(os.environ, HOME=self.tmp, XDG_RUNTIME_DIR=self.tmp,
                   DBUS_SESSION_BUS_ADDRESS=f"unix:path={self.tmp}/none")
        return subprocess.run([*NAMESPACE, *command], env=env, cwd=procs.ROOT, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)

    def test_refusal_leaves_a_running_instance_alone(self) -> None:
        # The script looks for processes named python3.
        python3 = os.path.join(os.path.dirname(sys.executable), "python3")
        r = self.run_inside("bash", "-c", WITH_AN_INSTANCE, "bash", python3, self.tmp)
        self.assertIn("A Sleep Control instance is running. Quit it first; this script starts its own.", r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["rc 2", "instance alive"], r.stderr)

    def test_arguments_are_checked_before_anything_runs(self) -> None:
        usage = "usage: tests/e2e/run.sh [--reinstall <bundle>]\n"
        missing = os.path.join(self.tmp, "missing.flatpak")
        cases = ((("--reinstal", "x"), usage), (("--reinstall",), usage), (("--reinstall", "a", "b"), usage),
                 (("x",), usage), (("",), usage),
                 (("--reinstall", missing), f"tests/e2e/run.sh: no bundle file at {missing}\n"))
        for args, message in cases:
            with self.subTest(args=args):
                r = self.run_inside("bash", "tests/e2e/run.sh", *args)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", message))


if __name__ == "__main__":
    unittest.main()
