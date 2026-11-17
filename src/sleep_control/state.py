"""The keep-awake state. The D-Bus calls live in backend.py."""

from typing import Callable, List, Optional, Protocol

REASON = "Kept awake with Sleep Control"


class BackendError(Exception):
    """A power call failed. The message is shown to the user as is."""


class PowerBackend(Protocol):
    def inhibit(self, reason: str) -> str:
        """Blocks suspend and idle. Returns a handle for release()."""

    def release(self, handle: str) -> None:
        """Ends the block taken by inhibit()."""

    def suspend(self) -> None:
        """Suspends the machine now."""


class Controller:
    """Holds at most one inhibit at a time and tells listeners when it changes."""

    def __init__(self, backend: PowerBackend):
        self._backend = backend
        self._handle: Optional[str] = None
        self._listeners: List[Callable[[bool], None]] = []

    @property
    def awake(self) -> bool:
        return self._handle is not None

    def on_change(self, listener: Callable[[bool], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in self._listeners:
            listener(self.awake)

    def keep_awake(self) -> None:
        if self._handle is not None:
            return
        self._handle = self._backend.inhibit(REASON)
        self._changed()

    def allow_sleep(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            self._backend.release(handle)
        finally:
            self._changed()

    def sleep_now(self) -> None:
        self.allow_sleep()
        self._backend.suspend()

    def describe(self) -> str:
        return describe(self.awake)


def describe(awake: bool) -> str:
    return "Sleep is blocked (kept awake)" if awake else "Sleep is allowed"
