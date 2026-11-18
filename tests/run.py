"""Test runner that knows which host each test module needs.

Every tests/test_*.py sets HOST to one of the names in HOSTS, and NEEDS to the
programs it uses beyond what its host has, if any. With no module names this
runs every module the current machine can run and lists the others with what
they miss. Naming a module, or passing --all, runs it or fails when something it
needs is missing. --list prints the modules a run would take and stops. A run
that has no tests to run fails.

    python -m tests.run [--all] [--list] [tests.test_x ...]
"""

import fcntl
import importlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from typing import Optional, cast

# "any": Linux with Python, PyQt6, dbus-run-session, dbus-daemon and prlimit, as on the CI runner.
# "kde-session": a logged-in KDE Plasma session on Wayland with the desktop portal,
# PowerDevil, the tray watcher, kded6, kwin_wayland and logind, as on the developer's machine.
# "flatpak": Flatpak with the SDK, runtime and PyQt BaseApp the Flatpak manifest
# names, and the Flatpak portal on the session bus.
HOSTS = ("any", "kde-session", "flatpak")

PORTAL = "org.freedesktop.portal.Desktop"
SESSION_NAMES = (PORTAL, "org.kde.Solid.PowerManagement", "org.kde.StatusNotifierWatcher")

# A full session run leaves about 8 descriptors open in the portal.
PORTAL_FREE_FDS = 64


def _has_name(bus: str, name: str) -> bool:
    if not shutil.which("busctl"):
        return False
    result = subprocess.run(["busctl", bus, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus", "NameHasOwner", "s", name],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "b true"


def name_pid(bus: str, name: str) -> Optional[int]:
    """The pid of the process that owns name on bus (a busctl bus option), or None when nobody does."""
    if not shutil.which("busctl"):
        return None
    result = subprocess.run(["busctl", bus, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", name],
                            capture_output=True, text=True, timeout=10)
    return int(result.stdout.split()[1]) if result.returncode == 0 else None


def open_files(pid: int) -> Optional[tuple[int, int]]:
    """How many files pid has open and its soft limit on them, or None when /proc doesn't say."""
    try:
        count = len(os.listdir(f"/proc/{pid}/fd"))
        with open(f"/proc/{pid}/limits") as f:
            limit = next(int(line.split()[3]) for line in f if line.startswith("Max open files"))
    except OSError:
        return None
    return count, limit


def portal_files_missing(count: int, limit: int) -> list[str]:
    """The missing_for entry for a portal with count of limit files open, if that leaves too few free."""
    if limit - count >= PORTAL_FREE_FDS:
        return []
    return [f"xdg-desktop-portal with free file descriptors ({count:,} of {limit:,} open; "
            "restart it with: systemctl --user restart xdg-desktop-portal)"]


def missing_for(host: str) -> list[str]:
    """What the current machine lacks for host. Empty when it can run it."""
    if host == "any":
        return [p for p in ("dbus-run-session", "dbus-daemon", "prlimit") if not shutil.which(p)]
    if host == "flatpak":
        # tests/sandbox.py comes with the Flatpak tests, so it is looked up by name.
        sandbox_missing: Callable[[], list[str]] = importlib.import_module(".sandbox", __package__).missing
        portal = [] if _has_name("--user", "org.freedesktop.portal.Flatpak") else ["org.freedesktop.portal.Flatpak"]
        return sandbox_missing() + portal
    missing: list[str] = [] if os.environ.get("WAYLAND_DISPLAY") else ["WAYLAND_DISPLAY"]
    missing += [p for p in ("dbus-daemon", "dbus-monitor", "dbus-send", "xdg-dbus-proxy", "kwin_wayland")
                if not shutil.which(p)]
    from .procs import kded_modules
    if not kded_modules():
        missing.append("kded6 with Plasma's statusnotifierwatcher module")
    missing += [n for n in SESSION_NAMES if not _has_name("--user", n)]
    portal = name_pid("--user", PORTAL)
    files = open_files(portal) if portal else None
    if files:
        missing += portal_files_missing(*files)
    if not _has_name("--system", "org.freedesktop.login1"):
        missing.append("org.freedesktop.login1")
    return missing


def _programs(value: object) -> Optional[tuple[str, ...]]:
    """value as a tuple of program names, or None when it is anything else."""
    if not isinstance(value, tuple):
        return None
    items = cast("tuple[object, ...]", value)
    names = tuple(p for p in items if isinstance(p, str))
    return names if len(names) == len(items) else None


def modules() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Maps each test module name to its HOST and the programs in its NEEDS."""
    found: dict[str, tuple[str, tuple[str, ...]]] = {}
    for path in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
        name = f"tests.{path.stem}"
        module = importlib.import_module(name)
        host: object = getattr(module, "HOST", None)
        if not isinstance(host, str) or host not in HOSTS:
            raise SystemExit(f"test: {name} sets HOST to {host!r}, expected one of {', '.join(HOSTS)}")
        raw: object = getattr(module, "NEEDS", ())
        needs = _programs(raw)
        if needs is None:
            raise SystemExit(f"test: {name} sets NEEDS to {raw!r}, expected a tuple of program names")
        found[name] = (host, needs)
    return found


def main(argv: list[str]) -> int:
    run_all = "--all" in argv
    list_only = "--list" in argv
    asked = [a for a in argv if a not in ("--all", "--list")]
    catalogue = modules()
    unknown = [m for m in asked if m not in catalogue]
    if unknown:
        print(f"test: no such test module: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if list_only:
        return _run(catalogue, asked, run_all, list_only)
    # Session tests count the desktop's inhibitions, so two runs at once would see each other.
    # The host checks run after the lock is taken, so they see the portal as it is when the run starts.
    with open(os.path.join(tempfile.gettempdir(), f"sleep-control-tests-{os.getuid()}.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run(catalogue, asked, run_all, list_only)


def _run(catalogue: dict[str, tuple[str, tuple[str, ...]]], asked: list[str], run_all: bool, list_only: bool) -> int:
    """Checks the hosts, then lists or runs the chosen modules."""
    host_missing = {h: missing_for(h) for h in {host for host, _ in catalogue.values()}}
    missing = {m: host_missing[host] + [p for p in needs if not shutil.which(p)]
               for m, (host, needs) in catalogue.items()}

    def needs(m: str) -> str:
        host, programs = catalogue[m]
        return f"the {host} host" + "".join(f" and {p}" for p in programs)

    if asked or run_all:
        chosen = asked or list(catalogue)
        blocked = [m for m in chosen if missing[m]]
        if blocked:
            for m in blocked:
                print(f"test: {m} needs {needs(m)}; missing here: {', '.join(missing[m])}", file=sys.stderr)
            return 1
    else:
        chosen = [m for m in catalogue if not missing[m]]
        for m in catalogue:
            if missing[m]:
                print(f"test: not run here: {m} needs {needs(m)}; missing: {', '.join(missing[m])}",
                      file=sys.stderr)
    suite = unittest.defaultTestLoader.loadTestsFromNames(chosen)
    hosts = ", ".join(sorted({catalogue[m][0] for m in chosen}))
    if not suite.countTestCases():
        print("test: no tests to run on this machine", file=sys.stderr)
        return 1
    if list_only:
        print("\n".join(chosen))
        print(f"test: would run {suite.countTestCases()} tests in {len(chosen)} modules for hosts {hosts}")
        return 0
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"test: {result.testsRun} tests in {len(chosen)} modules for hosts {hosts}")
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
