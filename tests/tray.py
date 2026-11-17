"""Talks to an app's tray icon the way the Plasma panel does, over D-Bus.

Qt registers the icon with the session's StatusNotifierWatcher and exports its
menu over com.canonical.dbusmenu. The panel sends Activate on a left click,
SecondaryActivate on a middle click and a "clicked" Event for a menu entry.
"""

import json
import subprocess
import time
from typing import TypeIs


# busctl's JSON is read through these checks, so a reply of another shape fails
# with the reply in the message.
def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_dict(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _list(value: object) -> list[object]:
    if not _is_list(value):
        raise AssertionError(f"busctl gave {value!r} where a list belongs")
    return value


def _dict(value: object) -> dict[str, object]:
    if not _is_dict(value):
        raise AssertionError(f"busctl gave {value!r} where an object belongs")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"busctl gave {value!r} where a string belongs")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise AssertionError(f"busctl gave {value!r} where a number belongs")
    return value


def _busctl(bus: str, *args: str) -> object:
    """The reply's data: the out values of a call, the value of a property. bus is --user or --address=..."""
    # "--" keeps busctl from reading a negative argument as an option.
    out = subprocess.run(["busctl", bus, "--json=short", "--", *args], capture_output=True, text=True,
                         check=True, timeout=10).stdout
    return _dict(json.loads(out))["data"] if out.strip() else None


def _pid_of(bus: str, service: str) -> int:
    data = _busctl(bus, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                   "GetConnectionUnixProcessID", "s", service)
    return _int(_list(data)[0])


class Tray:
    def __init__(self, pid: int, timeout: float = 15.0, bus: str = "--user") -> None:
        """Finds the tray icon registered by process pid."""
        self.bus = bus
        deadline = time.monotonic() + timeout
        while True:
            for entry in self.registered():
                service, _, path = entry.partition("/")
                if _pid_of(bus, service) == pid:
                    self.service, self.path = service, "/" + path
                    self.menu = _str(_busctl(bus, "get-property", self.service, self.path,
                                             "org.kde.StatusNotifierItem", "Menu"))
                    return
            if time.monotonic() > deadline:
                raise AssertionError(f"no tray icon from pid {pid}")
            time.sleep(0.2)

    def registered(self) -> list[str]:
        data = _busctl(self.bus, "get-property", "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                       "org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems")
        return [_str(entry) for entry in _list(data)]

    def tooltip(self) -> str:
        data = _busctl(self.bus, "get-property", self.service, self.path, "org.kde.StatusNotifierItem", "ToolTip")
        return _str(_list(data)[2])

    def entries(self) -> dict[str, tuple[int, bool]]:
        """Menu labels (mnemonics removed) to entry IDs, plus each entry's enabled flag."""
        layout = _list(_busctl(self.bus, "call", self.service, self.menu, "com.canonical.dbusmenu", "GetLayout", "iias",
                               "0", "-1", "0"))[1]
        found: dict[str, tuple[int, bool]] = {}

        def prop(props: dict[str, object], name: str, default: object) -> object:
            # Each property is a variant: {"type": ..., "data": ...}.
            return _dict(props[name])["data"] if name in props else default

        def walk(node: object) -> None:
            ident, props, children = _list(node)
            props = _dict(props)
            label = _str(prop(props, "label", ""))
            if label:
                enabled = prop(props, "enabled", True)
                if not isinstance(enabled, bool):
                    raise AssertionError(f"busctl gave {enabled!r} for a menu entry's enabled flag")
                found[label.replace("&", "")] = (_int(ident), enabled)
            for child in _list(children):
                walk(_dict(child)["data"])

        walk(layout)
        return found

    def click(self, label: str) -> None:
        ident, enabled = self.entries()[label]
        if not enabled:
            raise AssertionError(f"menu entry {label!r} is disabled")
        _busctl(self.bus, "call", self.service, self.menu, "com.canonical.dbusmenu", "Event", "isvu",
                str(ident), "clicked", "i", "0", "0")

    def activate(self, secondary: bool = False) -> None:
        method = "SecondaryActivate" if secondary else "Activate"
        _busctl(self.bus, "call", self.service, self.path, "org.kde.StatusNotifierItem", method, "ii", "0", "0")
