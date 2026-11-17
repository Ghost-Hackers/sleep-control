"""Test runner that knows which host each test module needs.

Every tests/test_*.py sets HOST to one of the names in HOSTS. With no module
names this runs every module the current host can run and lists the others.
Naming a module, or passing --all, runs it or fails when its host is missing.

    python -m tests.run [--all] [tests.test_x ...]
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

# "any": Linux with Python, PyQt6 and dbus-run-session, as on the CI runner.
# "kde-session": a logged-in KDE Plasma session on Wayland with the desktop portal,
# PowerDevil, the tray watcher and logind, as on the developer's machine.
# "flatpak": Flatpak with the SDK, runtime and PyQt BaseApp the Flatpak manifest
# names, and the Flatpak portal on the session bus.
HOSTS = ("any", "kde-session", "flatpak")

SESSION_NAMES = ("org.freedesktop.portal.Desktop", "org.kde.Solid.PowerManagement",
                 "org.kde.StatusNotifierWatcher")


def _has_name(bus: str, name: str) -> bool:
    if not shutil.which("busctl"):
        return False
    result = subprocess.run(["busctl", bus, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus", "NameHasOwner", "s", name],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "b true"


def missing_for(host: str) -> list:
    """What the current machine lacks for host. Empty when it can run it."""
    if host == "any":
        return [p for p in ("dbus-run-session", "dbus-daemon", "prlimit") if not shutil.which(p)]
    if host == "flatpak":
        from .sandbox import missing
        portal = [] if _has_name("--user", "org.freedesktop.portal.Flatpak") else ["org.freedesktop.portal.Flatpak"]
        return missing() + portal
    missing = [] if os.environ.get("WAYLAND_DISPLAY") else ["WAYLAND_DISPLAY"]
    missing += [p for p in ("dbus-daemon", "dbus-monitor", "dbus-send", "xdg-dbus-proxy") if not shutil.which(p)]
    missing += [n for n in SESSION_NAMES if not _has_name("--user", n)]
    if not _has_name("--system", "org.freedesktop.login1"):
        missing.append("org.freedesktop.login1")
    return missing


def modules() -> dict:
    """Maps each test module name to its HOST."""
    found = {}
    for path in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
        name = f"tests.{path.stem}"
        host = getattr(importlib.import_module(name), "HOST", None)
        if host not in HOSTS:
            raise SystemExit(f"test: {name} sets HOST to {host!r}, expected one of {', '.join(HOSTS)}")
        found[name] = host
    return found


def main(argv: list) -> int:
    run_all = "--all" in argv
    asked = [a for a in argv if a != "--all"]
    catalogue = modules()
    unknown = [m for m in asked if m not in catalogue]
    if unknown:
        print(f"test: no such test module: {', '.join(unknown)}", file=sys.stderr)
        return 2
    missing = {h: missing_for(h) for h in set(catalogue.values())}
    if asked or run_all:
        chosen = asked or list(catalogue)
        blocked = [m for m in chosen if missing[catalogue[m]]]
        if blocked:
            for m in blocked:
                host = catalogue[m]
                print(f"test: {m} needs the {host} host; missing here: {', '.join(missing[host])}", file=sys.stderr)
            return 1
    else:
        chosen = [m for m in catalogue if not missing[catalogue[m]]]
        other = [m for m in catalogue if m not in chosen]
        if other:
            print(f"test: not run on this host (needs another host): {' '.join(other)}", file=sys.stderr)
    # Session tests count the desktop's inhibitions, so two runs at once would see each other.
    lock = open(os.path.join(tempfile.gettempdir(), f"sleep-control-tests-{os.getuid()}.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    suite = unittest.defaultTestLoader.loadTestsFromNames(chosen)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    hosts = sorted({catalogue[m] for m in chosen})
    print(f"test: {result.testsRun} tests in {len(chosen)} modules for hosts {', '.join(hosts)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
