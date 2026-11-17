"""A Flatpak sandbox from the manifest's SDK, runtime and BaseApp, without building the app.

Code and icons are bound in from the repo. The sandbox uses an app ID that is never
installed, so a portal Spawn can't start an installed copy.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field

from sleep_control import APP_ID

from .procs import ROOT

SANDBOX_ID = "io.github.ghost_hackers.sleep_control_tests"
MANIFEST = os.path.join(ROOT, "packaging", "flatpak", f"{APP_ID}.yml")
LAUNCHER = os.path.join(ROOT, "packaging", "flatpak", "sleep-control.sh")


# Starts coverage, then runs the runtime's own sitecustomize, which this one hides
# (it puts /app's site-packages, and with it PyQt6, on the path).
SITECUSTOMIZE = """\
import importlib, os, sys
import coverage
coverage.process_startup()
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != here]
del sys.modules["sitecustomize"]
try:
    importlib.import_module("sitecustomize")
except ModuleNotFoundError:
    pass
"""


@dataclass
class Manifest:
    values: dict[str, str] = field(default_factory=dict[str, str])
    finish_args: list[str] = field(default_factory=list[str])

    def __getitem__(self, key: str) -> str:
        return self.values[key]


def manifest() -> Manifest:
    """The manifest's top-level values and its finish-args (a plain YAML subset)."""
    found = Manifest()
    in_finish_args = False
    with open(MANIFEST) as f:
        for line in f:
            if in_finish_args and line.startswith("  - "):
                found.finish_args.append(line[4:].strip())
                continue
            in_finish_args = line.startswith("finish-args:")
            key, _, value = line.partition(":")
            if line[:1].isalpha() and value.strip():
                found.values[key] = value.strip().strip("'\"")
    return found


def refs() -> list[str]:
    m = manifest()
    return [f"{m['sdk']}//{m['runtime-version']}", f"{m['runtime']}//{m['runtime-version']}",
            f"{m['base']}//{m['base-version']}"]


def missing() -> list[str]:
    """What this machine lacks to run the sandbox."""
    if not shutil.which("flatpak"):
        return ["flatpak"]
    return [r for r in refs()
            if subprocess.run(["flatpak", "info", r], capture_output=True, timeout=30).returncode != 0]


class Sandbox:
    """Build folder under ~/.cache/sleep-control-tests, one per BaseApp commit (about 700 MB)."""

    def __init__(self) -> None:
        m = manifest()
        base = f"{m['base']}//{m['base-version']}"
        commit = subprocess.run(["flatpak", "info", "--show-commit", base], capture_output=True, text=True,
                                check=True, timeout=30).stdout.strip()
        cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                             "sleep-control-tests")
        self.folder = os.path.join(cache, f"sandbox-{commit[:12]}")
        self.build = os.path.join(self.folder, "build")
        if not os.path.exists(os.path.join(self.build, "metadata")):
            os.makedirs(cache, exist_ok=True)
            for old in os.listdir(cache):
                shutil.rmtree(os.path.join(cache, old), ignore_errors=True)
            partial = self.folder + ".partial"
            subprocess.run(["flatpak", "build-init", f"--base={m['base']}", f"--base-version={m['base-version']}",
                            os.path.join(partial, "build"), SANDBOX_ID, m["sdk"], m["runtime"],
                            m["runtime-version"]], check=True, capture_output=True, timeout=300)
            os.rename(partial, self.folder)
        self.site = os.path.join(self.folder, "site")
        os.makedirs(self.site, exist_ok=True)
        self.args = list(m.finish_args)

    def command(self, runtime: str, *args: str) -> list[str]:
        """`flatpak build` running the launcher with args, on runtime as XDG_RUNTIME_DIR."""
        cmd = ["flatpak", "build", *self.args, f"--filesystem={ROOT}:ro", f"--filesystem={runtime}",
               f"--bind-mount=/app/bin/sleep-control={LAUNCHER}",
               f"--bind-mount=/app/share/sleep-control/icons={ROOT}/data/icons",
               f"--env=XDG_RUNTIME_DIR={runtime}", "--env=QT_QPA_PLATFORM=offscreen"]
        rcfile = os.environ.get("COVERAGE_PROCESS_START")
        if rcfile:
            cmd += self._coverage(rcfile) + [f"--env=PYTHONPATH={self.site}:{ROOT}/src"]
        else:
            cmd.append(f"--env=PYTHONPATH={ROOT}/src")
        return cmd + [self.build, "/app/bin/sleep-control", *args]

    def _coverage(self, rcfile: str) -> list[str]:
        # Under --coverage, measure the sandbox. The C tracer is built for the host's Python.
        import coverage
        package = os.path.dirname(coverage.__file__)
        link = os.path.join(self.site, "coverage")
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(package, link)
        with open(os.path.join(self.site, "sitecustomize.py"), "w") as f:
            f.write(SITECUSTOMIZE)
        data_file = os.path.abspath(os.environ["COVERAGE_FILE"])
        return [f"--filesystem={self.site}:ro", f"--filesystem={package}:ro",
                f"--filesystem={os.path.dirname(data_file)}", "--env=COVERAGE_CORE=pytrace",
                f"--env=COVERAGE_PROCESS_START={rcfile}", f"--env=COVERAGE_FILE={data_file}"]
