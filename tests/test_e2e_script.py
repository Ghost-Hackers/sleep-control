"""tests/e2e/run.sh before it touches the app: its arguments and its check for a running instance.

Each case runs the script in a process namespace of its own, so an instance the developer has open
is neither seen nor signalled.
"""

import os
import socket
import subprocess
import sys
import unittest

from . import procs

HOST = "flatpak"
NEEDS = ("unshare",)

SCRIPT = os.path.join(procs.ROOT, "tests", "e2e", "run.sh")
NAMESPACE = ["unshare", "--user", "--map-current-user", "--pid", "--fork", "--mount-proc"]

# Starts the app from this checkout ($1 is its interpreter, the rest are its arguments) in the runtime folder $2, runs
# the script, and says if the app is still there.
WITH_AN_INSTANCE = r"""
python=$1 runtime=$2
shift 2
XDG_RUNTIME_DIR=$runtime PYTHONPATH=src QT_QPA_PLATFORM=offscreen dbus-run-session -- "$python" "$@" >/dev/null 2>&1 &
pid=0
for _ in $(seq 1 100); do
  pid=$("$python" -c 'import sys; from tests import procs; print(procs.lock_holder(sys.argv[1]))' "$runtime")
  [ "$pid" != 0 ] && break
  sleep 0.2
done
[ "$pid" != 0 ] || { echo "no instance"; exit 1; }
bash tests/e2e/run.sh
echo "rc $?"
sleep 1
if kill -0 "$pid" 2>/dev/null; then echo "instance alive"; else echo "instance gone"; fi
kill -TERM "$pid" 2>/dev/null
"""

# Runs the script ($1 is the bus address), starts an instance once the script is past its instance check and waits
# on the session bus, then sends the signal ($2) to the script's process group, as Ctrl-C or a closed terminal does.
INTERRUPTED = r"""
import os, signal, subprocess, sys, time
from tests import procs

runtime = os.environ["XDG_RUNTIME_DIR"]
script = subprocess.Popen(["bash", "tests/e2e/run.sh"], env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=sys.argv[1]),
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, process_group=0)
def waiting_on_the_bus():
    for p in os.listdir("/proc"):
        try:
            if p.isdigit() and open(f"/proc/{p}/comm").read() == "busctl\n":
                return True
        except OSError:
            pass
    return False
deadline = time.monotonic() + 20
while not waiting_on_the_bus() and time.monotonic() < deadline:
    time.sleep(0.1)
app = subprocess.Popen(["dbus-run-session", "--", sys.executable, "-m", "sleep_control"],
                       env=dict(os.environ, PYTHONPATH="src", QT_QPA_PLATFORM="offscreen"),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       start_new_session=True)
while not procs.lock_holder(runtime) and time.monotonic() < deadline:
    time.sleep(0.1)
pid = procs.lock_holder(runtime)
os.killpg(script.pid, getattr(signal, sys.argv[2]))
print("rc", script.wait(timeout=60))
time.sleep(1)
print("instance alive" if pid and procs.lock_holder(runtime) == pid else "instance gone")
os.killpg(app.pid, signal.SIGTERM)
app.wait(timeout=10)
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
        # The sandbox runs the app as python3, a source checkout may run it as python.
        for name in ("python3", "python"):
            with self.subTest(interpreter=name):
                python = os.path.join(os.path.dirname(sys.executable), name)
                r = self.run_inside("bash", "-c", WITH_AN_INSTANCE, "bash", python, self.tmp, "-m", "sleep_control")
                self.assertIn("A Sleep Control instance is running. Quit it first; this script starts its own.",
                              r.stderr)
                self.assertEqual(r.stdout.splitlines(), ["rc 2", "instance alive"], r.stderr)

    def test_the_instance_is_found_by_its_lock(self) -> None:
        # Started without "-m sleep_control" on its command line, the instance still holds the lock.
        start = "import runpy; runpy.run_module('sleep_control', run_name='__main__', alter_sys=True)"
        r = self.run_inside("bash", "-c", WITH_AN_INSTANCE, "bash", sys.executable, self.tmp, "-c", start)
        self.assertIn("A Sleep Control instance is running. Quit it first; this script starts its own.", r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["rc 2", "instance alive"], r.stderr)

    def test_an_interrupt_stops_the_run_and_leaves_an_instance_alone(self) -> None:
        # The bus takes the connection and never answers, so busctl waits in the run for 90 seconds.
        bus = os.path.join(self.tmp, "bus")
        listener = socket.socket(socket.AF_UNIX)
        self.addCleanup(listener.close)
        listener.bind(bus)
        listener.listen(16)
        tmpdir = os.path.join(self.tmp, "tmpdir")
        os.mkdir(tmpdir)
        for name, status in (("SIGINT", 130), ("SIGTERM", 143), ("SIGHUP", 129)):
            with self.subTest(signal=name):
                r = self.run_inside("env", f"TMPDIR={tmpdir}", sys.executable, "-c", INTERRUPTED, f"unix:path={bus}",
                                    name)
                self.assertEqual(r.stdout.splitlines(), [f"rc {status}", "instance alive"], r.stderr)
                self.assertEqual(os.listdir(tmpdir), [])

    def test_arguments_are_checked_before_anything_runs(self) -> None:
        usage = "usage: tests/e2e/run.sh [--reinstall <bundle>]\n"
        missing = os.path.join(self.tmp, "missing.flatpak")
        empty = os.path.join(self.tmp, "empty.flatpak")
        text = os.path.join(self.tmp, "text.flatpak")
        open(empty, "w").close()
        with open(text, "w") as f:
            f.write("not a bundle\n")
        other = "is not a Flatpak bundle of io.github.ghost_hackers.sleep-control\n"
        cases = ((("--reinstal", "x"), usage), (("--reinstall",), usage), (("--reinstall", "a", "b"), usage),
                 (("x",), usage), (("",), usage),
                 (("--reinstall", missing), f"tests/e2e/run.sh: no bundle file at {missing}\n"),
                 (("--reinstall", empty), f"tests/e2e/run.sh: {empty} {other}"),
                 (("--reinstall", text), f"tests/e2e/run.sh: {text} {other}"))
        for args, message in cases:
            with self.subTest(args=args):
                r = self.run_inside("bash", "tests/e2e/run.sh", *args)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", message))


if __name__ == "__main__":
    unittest.main()
