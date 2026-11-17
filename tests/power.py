"""Reads the session's power state: PowerDevil's inhibitions and logind.

The KDE portal hands an Inhibit request to PowerDevil, which lists it with the
caller's app ID and the reason. On Wayland Qt registers the app ID with the
portal, so an installed copy and one from the source tree look the same. The
tests count the change against what was held when they started instead, which
leaves an installed copy that keeps the machine awake alone. PowerDevil applies
a new inhibition after about five seconds and drops a released one at once.
"""

import contextlib
import json
import subprocess
import time

from sleep_control.state import REASON

LIST = ["busctl", "--user", "--json=short", "call", "org.kde.Solid.PowerManagement",
        "/org/kde/Solid/PowerManagement/PolicyAgent", "org.kde.Solid.PowerManagement.PolicyAgent",
        "ListInhibitions"]
LOGIN1 = ["busctl", "--system", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
          "org.freedesktop.login1.Manager"]
TEST_LOCK = "sleep-control-tests"


def inhibitions() -> list:
    out = subprocess.run(LIST, capture_output=True, text=True, check=True, timeout=10).stdout
    return [tuple(entry) for entry in json.loads(out)["data"][0]]


def held() -> int:
    """Inhibitions in PowerDevil with Sleep Control's reason."""
    return sum(1 for _app, reason in inhibitions() if reason == REASON)


class Blocks:
    """Sleep Control's inhibitions taken since this object was made."""

    def __init__(self):
        self.base = held()

    def now(self) -> int:
        return held() - self.base

    def wait(self, count: int, timeout: float = 15.0) -> int:
        """Waits until now() equals count. Returns the last value seen."""
        deadline = time.monotonic() + timeout
        seen = self.now()
        while seen != count and time.monotonic() < deadline:
            time.sleep(0.25)
            seen = self.now()
        return seen


def can_suspend() -> str:
    out = subprocess.run(LOGIN1 + ["CanSuspend"], capture_output=True, text=True, check=True, timeout=10).stdout
    return out.split(None, 1)[1].strip().strip('"')


def lock_names() -> list:
    out = subprocess.run(["systemd-inhibit", "--list", "--no-pager", "--no-legend"],
                         capture_output=True, text=True, check=True, timeout=10).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]


@contextlib.contextmanager
def sleep_blocked():
    """Holds a logind block lock on sleep for the test's own use.

    Since systemd 257 logind refuses Suspend() while any block lock on sleep is
    held, the caller's own included, unless the caller passes
    SD_LOGIND_SKIP_INHIBITORS (the app never does). So the app's real suspend
    call can run and is refused. The test stops before that call unless logind
    reports "inhibited" while this lock is held.
    """
    holder = subprocess.Popen(["systemd-inhibit", "--what=sleep", "--mode=block", f"--who={TEST_LOCK}",
                               "--why=sleep-control tests check that suspend is refused", "sleep", "300"])
    try:
        deadline = time.monotonic() + 10
        while TEST_LOCK not in lock_names():
            if time.monotonic() > deadline or holder.poll() is not None:
                raise AssertionError("could not take the test's sleep lock")
            time.sleep(0.1)
        state = can_suspend()
        if state != "inhibited":
            raise AssertionError(f"logind says CanSuspend={state!r} under the test's lock; not calling suspend")
        yield
    finally:
        holder.terminate()
        holder.wait(10)


DENIED = "Operation denied due to active block inhibitor"
