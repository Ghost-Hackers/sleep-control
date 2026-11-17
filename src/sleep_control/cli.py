"""Command line: parse the action and pass it to the running instance."""

import os
import subprocess
import sys
import time
from typing import List, Optional, Sequence

from . import APP_NAME, __version__, ipc
from .state import BackendError, describe

USAGE = """\
usage: sleep-control [on|off|now|status|--version]
  on        keep awake (blocks idle sleep and suspend)
  off       allow sleep again
  now       allow sleep and suspend right away
  status    print whether sleep is blocked
  (none)    open the Sleep Control window
"""

GUI = "gui"            # no action: open the window
BACKGROUND = "background"  # start the app with the tray icon only
VERSION = "version"
HELP = "help"


class UsageError(Exception):
    pass


def parse(argv: Sequence[str]) -> str:
    if not argv:
        return GUI
    if len(argv) > 1:
        raise UsageError(f"expected one action, got {len(argv)}")
    arg = argv[0]
    if arg in ("on", "off", "now", "status"):
        return arg
    if arg == "--background":
        return BACKGROUND
    if arg in ("--version", "-V"):
        return VERSION
    if arg in ("-h", "--help", "help"):
        return HELP
    raise UsageError(f"unknown action: {arg}")


def in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def start_background() -> Optional[subprocess.Popen[bytes]]:
    """Starts an instance that outlives this command.

    Inside Flatpak everything in this sandbox ends with this process, so the
    instance goes into a new sandbox of the same app through the Flatpak portal.
    The portal call returns at once; flatpak-spawn would stay around to wait.
    Outside Flatpak the instance is a child in its own session, returned so the
    caller can tell when it exits early.
    """
    if in_flatpak():
        cmd = ["gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Flatpak",
               "--object-path", "/org/freedesktop/portal/Flatpak",
               "--method", "org.freedesktop.portal.Flatpak.Spawn",
               "b'/'", "[b'/app/bin/sleep-control', b'--background']",
               "@a{uh} {}", "@a{ss} {}", "uint32 0", "@a{sv} {}"]
        subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=15, check=True)
        return None
    return subprocess.Popen([sys.executable, "-m", "sleep_control", "--background"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def wait_for_instance(path: str, proc: Optional[subprocess.Popen[bytes]], timeout: float = 15.0) -> bool:
    """Waits until an instance answers. Gives up early when proc has exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ipc.request(path, "status", timeout=2.0)
            return True
        except (ipc.NotRunning, OSError):
            if proc is not None and proc.poll() is not None:
                return False
            time.sleep(0.1)
    return False


def _send(path: str, action: str) -> Optional[int]:
    """Passes the action to the running instance. Returns None when none listens."""
    try:
        answer = ipc.request(path, action)
    except ipc.NotRunning:
        return None
    except OSError as e:
        print(f"sleep-control: can't reach the running instance: {e}", file=sys.stderr)
        return 1
    kind, _, text = answer.partition(" ")
    if kind == "ok":
        print(text)
        return 0
    print(f"sleep-control: {text or answer}", file=sys.stderr)
    return 1


def run(action: str, path: str) -> int:
    """Runs a terminal action against the running instance. Returns the exit code."""
    code = _send(path, action)
    if code is not None:
        return code
    if action in ("status", "off"):
        print(describe(False))
        return 0
    if action == "now":
        from .backend import DBusBackend
        try:
            DBusBackend().suspend()
        except BackendError as e:
            print(f"sleep-control: can't suspend: {e}", file=sys.stderr)
            return 1
        print("Suspending")
        return 0
    # on: nothing holds the block yet, so start an instance to hold it.
    try:
        proc = start_background()
    except (OSError, subprocess.SubprocessError) as e:
        print(f"sleep-control: can't start {APP_NAME}: {e}", file=sys.stderr)
        return 1
    if wait_for_instance(path, proc):
        code = _send(path, action)
        if code is not None:
            return code
    print(f"sleep-control: {APP_NAME} didn't start", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        action = parse(argv)
    except UsageError as e:
        print(f"sleep-control: {e}", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2
    if action == VERSION:
        print(f"sleep-control {__version__}")
        return 0
    if action == HELP:
        print(USAGE, end="")
        return 0
    path = ipc.default_path()
    if action in (GUI, BACKGROUND):
        from .app import run_app
        return run_app(path, show_window=(action == GUI))
    return run(action, path)
