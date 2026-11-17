"""Power calls over D-Bus: the Inhibit portal for keeping awake, logind for suspend."""

import itertools
import time
from typing import Optional

from PyQt6.QtCore import QMetaType
from PyQt6.QtDBus import QDBus, QDBusArgument, QDBusConnection, QDBusMessage

from .state import BackendError

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"

# org.freedesktop.portal.Inhibit flags: 4 is suspend, 8 is idle.
INHIBIT_SUSPEND_IDLE = 4 | 8
TIMEOUT_MS = 10_000
# The portal answers Inhibit before its backend has set up the request. A Close
# sent in that gap fails with UnknownObject and the block still goes in, so
# release() tries again for this long.
RELEASE_RETRY_S = 2.0
UNKNOWN_OBJECT = "org.freedesktop.DBus.Error.UnknownObject"

_tokens = itertools.count(1)


def _error(reply: QDBusMessage) -> Optional[BackendError]:
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        return BackendError(reply.errorMessage() or reply.errorName())
    return None


def _call(bus: QDBusConnection, msg: QDBusMessage) -> list[object]:
    reply = bus.call(msg, QDBus.CallMode.Block, TIMEOUT_MS)
    error = _error(reply)
    if error:
        raise error
    return reply.arguments()


# PyQt6's type hints have these static factories return typing.Self, which
# Pyright reads as unknown, so the three helpers below give them their type.
def _session_bus() -> QDBusConnection:
    return QDBusConnection.sessionBus()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def _system_bus() -> QDBusConnection:
    return QDBusConnection.systemBus()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def _method_call(service: str, path: str, interface: str, method: str) -> QDBusMessage:
    return QDBusMessage.createMethodCall(service, path, interface, method)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


class DBusBackend:
    def __init__(self) -> None:
        self._session = _session_bus()
        self._system = _system_bus()

    def inhibit(self, reason: str) -> str:
        msg = _method_call(PORTAL, PORTAL_PATH, "org.freedesktop.portal.Inhibit", "Inhibit")
        flags = QDBusArgument()
        flags.add(INHIBIT_SUSPEND_IDLE, QMetaType.Type.UInt.value)
        options = {"reason": reason, "handle_token": f"sleep_control_{next(_tokens)}"}
        msg.setArguments(["", flags, options])
        # The reply is (o): xdg-desktop-portal answers Inhibit through GDBus, which
        # checks every reply against the method's out signature. PyQt hands the
        # object path over as a str.
        return str(_call(self._session, msg)[0])

    def release(self, handle: str) -> None:
        msg = _method_call(PORTAL, handle, "org.freedesktop.portal.Request", "Close")
        deadline = time.monotonic() + RELEASE_RETRY_S
        while True:
            reply = self._session.call(msg, QDBus.CallMode.Block, TIMEOUT_MS)
            error = _error(reply)
            if not error:
                return
            if reply.errorName() != UNKNOWN_OBJECT or time.monotonic() > deadline:
                raise error
            time.sleep(0.02)

    def suspend(self) -> None:
        msg = _method_call(LOGIN1, LOGIN1_PATH, "org.freedesktop.login1.Manager", "Suspend")
        msg.setArguments([False])
        _call(self._system, msg)

    def can_suspend(self) -> str:
        msg = _method_call(LOGIN1, LOGIN1_PATH, "org.freedesktop.login1.Manager", "CanSuspend")
        args = _call(self._system, msg)
        return str(args[0]) if args else ""
