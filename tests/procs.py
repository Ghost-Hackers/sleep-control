"""Starts the app and the command line as separate processes.

Each test gets its own runtime folder, passed as XDG_RUNTIME_DIR, so the control
socket lives there and the tests never reach an installed copy that may be
running. Wayland and the session bus are given as full paths, because both are
normally found relative to XDG_RUNTIME_DIR.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Sequence

from sleep_control import APP_ID, APP_NAME

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")


def runtime_dir(test: unittest.TestCase) -> str:
    """A private runtime folder; on cleanup every process using it is stopped."""
    path = tempfile.mkdtemp(prefix="sc-test-")
    os.chmod(path, 0o700)
    test.addCleanup(shutil.rmtree, path, ignore_errors=True)
    test.addCleanup(stop_all, path)
    return path


def sock(runtime: str) -> str:
    return os.path.join(runtime, "app", APP_ID, "control.sock")


def env(runtime: str, platform: str = "offscreen", bus: str = "", wayland: str = "") -> dict[str, str]:
    """The environment for an app or command line process in runtime, on the given session bus address
    and Wayland display."""
    session_runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    e = dict(os.environ)
    e["XDG_RUNTIME_DIR"] = runtime
    e["PYTHONPATH"] = SRC
    e["QT_QPA_PLATFORM"] = platform
    e.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={session_runtime}/bus")
    if bus:
        e["DBUS_SESSION_BUS_ADDRESS"] = bus
    display = e.get("WAYLAND_DISPLAY")
    if display and not os.path.isabs(display):
        e["WAYLAND_DISPLAY"] = os.path.join(session_runtime, display)
    if wayland:
        e["WAYLAND_DISPLAY"] = wayland
    return e


def cli(runtime: str, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Runs `python -m sleep_control args` and returns its result."""
    return subprocess.run([sys.executable, "-m", "sleep_control", *args], env=env(runtime), cwd=ROOT,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def pids_in(runtime: str) -> list[int]:
    """Processes of this user whose XDG_RUNTIME_DIR is runtime."""
    want = f"XDG_RUNTIME_DIR={runtime}".encode()
    found: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open(f"/proc/{entry}/environ", "rb") as f:
                if want in f.read().split(b"\0"):
                    found.append(int(entry))
        except OSError:
            continue
    return found


def state(pid: int) -> str:
    """The process state letter from /proc, or "" when it is gone."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except OSError:
        return ""


def lock_holder(runtime: str) -> int:
    """The process holding the instance lock in runtime, from /proc/locks, or 0."""
    try:
        inode = os.stat(sock(runtime) + ".lock").st_ino
    except FileNotFoundError:
        return 0
    with open("/proc/locks") as f:
        for line in f:
            # 1: FLOCK  ADVISORY  WRITE 1234 00:2a:5678 0 EOF
            fields = line.split()
            if fields[1:4] == ["FLOCK", "ADVISORY", "WRITE"] and fields[5].endswith(f":{inode}"):
                return int(fields[4])
    return 0


def gone(pid: int) -> bool:
    return state(pid) in ("", "Z")


def wait_gone(pids: Sequence[int], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(gone(p) for p in pids):
            return True
        time.sleep(0.05)
    return all(gone(p) for p in pids)


def stop_all(runtime: str) -> None:
    """SIGTERM for every process in runtime (the app quits cleanly on it), then SIGKILL for stragglers."""
    pids = pids_in(runtime)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if wait_gone(pids):
            return


def answer(runtime: str, command: bytes, timeout: float = 10.0) -> bytes:
    """Sends raw bytes on the control socket and returns everything the instance sends back."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(sock(runtime))
        conn.sendall(command)
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        return data


BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={runtime}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def bus_config(runtime: str) -> str:
    """A session bus configuration that starts no services: no portal, no tray watcher."""
    config = os.path.join(runtime, "bus.conf")
    if not os.path.exists(config):
        with open(config, "w") as f:
            f.write(BUS_CONFIG.format(runtime=runtime))
    return config


def private_bus_cmd(runtime: str) -> list[str]:
    """dbus-run-session with a session bus that starts no services (see bus_config)."""
    return ["dbus-run-session", f"--config-file={bus_config(runtime)}", "--"]


class PrivateBus:
    """A session bus daemon of the test's own, with bus_config. SIGSTOP makes the whole bus stop answering."""

    def __init__(self, test: unittest.TestCase, runtime: str) -> None:
        self.proc = subprocess.Popen(["dbus-daemon", f"--config-file={bus_config(runtime)}", "--nofork",
                                      "--print-address=1"], env=env(runtime), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        assert self.proc.stdout is not None
        self.stdout = self.proc.stdout
        test.addCleanup(self._end)
        self.address = self.stdout.readline().strip()

    def _end(self) -> None:
        self.proc.send_signal(signal.SIGCONT)
        self.proc.terminate()
        self.proc.wait(10)
        self.stdout.close()

    def stop(self) -> None:
        self.proc.send_signal(signal.SIGSTOP)

    def has_name(self, name: str) -> bool:
        result = subprocess.run(["busctl", f"--address={self.address}", "call", "org.freedesktop.DBus",
                                 "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", name],
                                capture_output=True, text=True, timeout=10)
        return result.stdout.strip() == "b true"

    def wait_name(self, name: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.has_name(name):
            if time.monotonic() > deadline:
                raise AssertionError(f"nothing took {name} on the private bus within {timeout} s")
            time.sleep(0.1)


KDED_MODULES = ("/usr/lib/qt6/plugins/kf6/kded", "/usr/lib64/qt6/plugins/kf6/kded",
                "/usr/lib/x86_64-linux-gnu/qt6/plugins/kf6/kded")
WATCHER = "statusnotifierwatcher"


def kded_modules() -> str:
    """The folder of kded6's modules if it has Plasma's tray watcher, else ""."""
    return next((d for d in KDED_MODULES if os.path.exists(os.path.join(d, WATCHER + ".so"))), "")


def own_home(e: dict[str, str], home: str) -> dict[str, str]:
    """e with home and every XDG data folder inside home, and no display to reach the desktop through."""
    for name in ("WAYLAND_DISPLAY", "DISPLAY"):
        e.pop(name, None)
    e.update(HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"), XDG_CACHE_HOME=os.path.join(home, ".cache"),
             XDG_DATA_HOME=os.path.join(home, ".local", "share"),
             XDG_STATE_HOME=os.path.join(home, ".local", "state"))
    return e


class TrayWatcher:
    """Plasma's StatusNotifierWatcher, the kded6 module, on a private bus.

    kded6 runs every other module turned off and with its own home and config
    folders, so it writes nothing outside runtime and doesn't touch the desktop.
    """

    def __init__(self, test: unittest.TestCase, runtime: str, bus: str) -> None:
        home = os.path.join(runtime, "kded-home")
        config = os.path.join(home, ".config")
        os.makedirs(config)
        modules = sorted(f.removesuffix(".so") for f in os.listdir(kded_modules()) if f.endswith(".so"))
        # kded6 still reads its settings from kded5rc.
        with open(os.path.join(config, "kded5rc"), "w") as f:
            f.write("[General]\nCheckSycoca=false\n")
            for m in modules:
                f.write(f"\n[Module-{m}]\nautoload={'true' if m == WATCHER else 'false'}\n")
        e = own_home(env(runtime, bus=bus), home)
        self.log = open(os.path.join(runtime, "kded.log"), "w")
        test.addCleanup(self.log.close)
        self.proc = subprocess.Popen(["kded6"], env=e, cwd=home, stdin=subprocess.DEVNULL, stdout=self.log,
                                     stderr=subprocess.STDOUT)
        test.addCleanup(self._end)

    def _end(self) -> None:
        self.proc.terminate()
        self.proc.wait(10)


class Desktop:
    """KWin on a virtual screen and a private bus: a Wayland desktop of the test's own, with no tray.

    Like TrayWatcher it has its own home and config folders, so the real desktop
    is never touched. windows() lists the app's windows that KWin shows.
    """

    def __init__(self, test: unittest.TestCase, runtime: str) -> None:
        self.bus = PrivateBus(test, runtime)
        home = os.path.join(runtime, "kwin-home")
        os.makedirs(os.path.join(home, ".config"))
        self.display = os.path.join(runtime, "wayland-test")
        self.log = open(os.path.join(runtime, "kwin.log"), "w")
        test.addCleanup(self.log.close)
        self.proc = subprocess.Popen(["kwin_wayland", "--virtual", "--socket", "wayland-test", "--no-lockscreen",
                                      "--no-global-shortcuts", "--no-kactivities"],
                                     env=own_home(env(runtime, bus=self.bus.address), home), cwd=home,
                                     stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        test.addCleanup(self._end)
        self.bus.wait_name("org.kde.KWin")

    def _end(self) -> None:
        self.proc.terminate()
        self.proc.wait(10)

    def windows(self) -> list[str]:
        """Titles of the windows KWin has for the app."""
        out = subprocess.run(["busctl", f"--address={self.bus.address}", "--json=short", "call", "org.kde.KWin",
                              "/WindowsRunner", "org.kde.krunner1", "Match", "s", APP_NAME],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        matches: list[list[object]] = json.loads(out)["data"][0]
        return [str(m[1]) for m in matches]

    def wait_window(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while self.windows() != [APP_NAME]:
            if time.monotonic() > deadline:
                raise AssertionError(f"no {APP_NAME} window within {timeout} s: {self.windows()}")
            time.sleep(0.1)

    def no_window_for(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.windows():
                raise AssertionError(f"a window showed up: {self.windows()}")
            time.sleep(0.1)


# The app stops itself (SIGSTOP) right after it takes the instance lock and before
# it makes the socket, the first flock() of the process. SIGCONT lets it go on.
STOP_AFTER_LOCK = ("strace", "-qq", "-o", "/dev/null", "-e", "trace=flock", "-e",
                   "inject=flock:signal=SIGSTOP:when=1")


def private_cli(runtime: str, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Runs the command line on a private session bus (see private_bus_cmd)."""
    return subprocess.run(private_bus_cmd(runtime) + [sys.executable, "-m", "sleep_control", *args],
                          env=env(runtime), cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=timeout)


def app_pids(runtime: str) -> list[int]:
    """The app's own Python processes in runtime."""
    found: list[int] = []
    for pid in pids_in(runtime):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
        except OSError:
            continue
        if b"sleep_control" in cmd and os.path.basename(cmd[0]) not in (b"dbus-run-session", b"strace"):
            found.append(pid)
    return found


class App:
    """One app process, `python -m sleep_control args`, optionally on a private session bus."""

    def __init__(self, test: unittest.TestCase, runtime: str, *args: str, platform: str = "offscreen",
                 private_bus: bool = False, bus: str = "", wayland: str = "", stop_after_lock: bool = False) -> None:
        self.runtime = runtime
        self.log = open(os.path.join(runtime, f"app-{len(os.listdir(runtime))}.log"), "w+")
        test.addCleanup(self.log.close)
        cmd = [sys.executable, "-m", "sleep_control", *args]
        if stop_after_lock:
            cmd = [*STOP_AFTER_LOCK, *cmd]
        if private_bus:
            cmd = private_bus_cmd(runtime) + cmd
        self.proc = subprocess.Popen(cmd, env=env(runtime, platform, bus, wayland), cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        test.addCleanup(self._reap)

    def _reap(self) -> None:
        if self.proc.poll() is None:
            stop_all(self.runtime)
        self.proc.wait(10)

    @property
    def pid(self) -> int:
        """The Python process of the app (not dbus-run-session)."""
        children = [p for p in app_pids(self.runtime) if self.proc.pid in (p, _parent(p), _parent(_parent(p)))]
        if not children:
            raise AssertionError("the app process isn't running")
        return children[0]

    def wait_ready(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"the app exited with {self.proc.returncode}: {self.output()}")
            try:
                if answer(self.runtime, b"status\n", timeout=2).startswith(b"ok "):
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise AssertionError(f"the app didn't answer within {timeout} s: {self.output()}")

    def wait_stopped(self, timeout: float = 20.0) -> None:
        """Waits until an app started with stop_after_lock holds the lock and stands still."""
        deadline = time.monotonic() + timeout
        while not (app_pids(self.runtime) and lock_holder(self.runtime) == self.pid
                   and state(self.pid) in ("T", "t")):
            if time.monotonic() > deadline or self.proc.poll() is not None:
                raise AssertionError(f"the app didn't stop after taking the lock: {self.output()}")
            time.sleep(0.05)

    def wait_exit(self, timeout: float = 15.0) -> int:
        return self.proc.wait(timeout)

    def output(self) -> str:
        self.log.flush()
        self.log.seek(0)
        return self.log.read()[-2000:]


def _parent(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except OSError:
        return 0
