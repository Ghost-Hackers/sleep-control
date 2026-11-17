"""Answers the commands that come in over the control socket."""

from typing import Callable

from .state import BackendError, Controller, describe


def answer(controller: Controller, command: str, show: Callable[[], None],
           report: Callable[[str], None]) -> str:
    """Runs one command (status, show, on, off or now) and returns the answer line."""
    if command == "show":
        show()
    elif command != "status":
        action = {"on": controller.keep_awake, "off": controller.allow_sleep,
                  "now": controller.sleep_now}[command]
        try:
            action()
        except BackendError as e:
            report(str(e))
            return f"error {e}"
        report("")
        if command == "now":
            return "ok Suspending"
    return "ok " + describe(controller.awake)
