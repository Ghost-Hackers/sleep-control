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
NEEDS = ("unshare", "ostree")

APP = "io.github.ghost_hackers.sleep-control"
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

    def run_inside(self, *command: str, path: str = "") -> subprocess.CompletedProcess[str]:
        """Runs command in the namespace, away from the session bus and the installed app."""
        env = dict(os.environ, HOME=self.tmp, XDG_RUNTIME_DIR=self.tmp,
                   DBUS_SESSION_BUS_ADDRESS=f"unix:path={self.tmp}/none")
        if path:
            env["PATH"] = path
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

    def test_the_run_needs_powerdevil(self) -> None:
        # The instance runs in a runtime folder of its own, so it isn't the app's and the script goes on to PowerDevil.
        other = os.path.join(self.tmp, "other")
        os.mkdir(other, 0o700)
        r = self.run_inside("bash", "-c", WITH_AN_INSTANCE, "bash", sys.executable, other, "-m", "sleep_control")
        message = "tests/e2e/run.sh: PowerDevil doesn't answer on the session bus\n"
        self.assertEqual((r.stdout.splitlines(), r.stderr), (["rc 2", "instance alive"], message))

    def bundle(self, name: str, arch: str, runtime: str) -> str:
        """A bundle file of an empty app with this app's id, built for arch and asking for runtime."""
        tree = os.path.join(self.tmp, f"{name}.tree")
        os.makedirs(os.path.join(tree, "files"))
        with open(os.path.join(tree, "metadata"), "w") as f:
            f.write(f"[Application]\nname={APP}\nruntime={runtime}\n")
        repo = os.path.join(self.tmp, f"{name}.repo")
        path = os.path.join(self.tmp, f"{name}.flatpak")
        for command in (["ostree", "init", f"--repo={repo}", "--mode=archive-z2"],
                        ["ostree", "commit", f"--repo={repo}", f"--branch=app/{APP}/{arch}/master",
                         f"--tree=dir={tree}", "--subject=test"],
                        ["flatpak", "build-bundle", f"--arch={arch}", repo, path, APP, "master"]):
            subprocess.run(command, check=True, capture_output=True)
        return path

    def test_reinstall_needs_a_bundle_that_can_put_the_app_back(self) -> None:
        arch = subprocess.run(["flatpak", "--supported-arches"], check=True, capture_output=True,
                              text=True).stdout.split()[0]
        # The namespace's home folder is empty, so only the system installation's runtimes are found there.
        runtimes = subprocess.run(["flatpak", "list", "--system", "--runtime", "--columns=ref"], check=True,
                                  capture_output=True, text=True).stdout.split()
        self.assertTrue(runtimes, "needs a runtime installed system-wide")
        other_arch = self.bundle("other-arch", "sparc", runtimes[0])
        no_runtime = self.bundle("no-runtime", arch, f"org.example.None/{arch}/1")
        good = self.bundle("good", arch, runtimes[0])
        cases = ((other_arch, f"{other_arch} is built for sparc, which this machine doesn't run"),
                 (no_runtime, f"{no_runtime} needs the runtime org.example.None/{arch}/1, which is not installed"),
                 (good, f"--reinstall needs {APP} installed with flatpak install --user"))
        for path, message in cases:
            with self.subTest(bundle=os.path.basename(path)):
                r = self.run_inside("bash", "tests/e2e/run.sh", "--reinstall", path)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", f"tests/e2e/run.sh: {message}\n"))

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

    def test_reinstall_without_ostree_says_so(self) -> None:
        # A PATH with a link to every program but ostree.
        folder = os.path.join(self.tmp, "bin")
        os.mkdir(folder)
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                target = os.path.join(directory, name)
                link = os.path.join(folder, name)
                if name != "ostree" and not os.path.lexists(link) and os.access(target, os.X_OK):
                    os.symlink(target, link)
        bundle = os.path.join(self.tmp, "any.flatpak")
        open(bundle, "w").close()
        r = self.run_inside("bash", "tests/e2e/run.sh", "--reinstall", bundle, path=folder)
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (2, "", "tests/e2e/run.sh: --reinstall needs ostree to check the bundle\n"))


if __name__ == "__main__":
    unittest.main()
