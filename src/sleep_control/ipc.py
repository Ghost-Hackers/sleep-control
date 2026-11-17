"""One running instance per session, reached over a Unix socket.

The socket lives in $XDG_RUNTIME_DIR/app/<app id>/, which Flatpak shares between
every sandbox of this app and nobody else. A request is one line with a command,
the answer is one line starting with "ok " or "error ".

The instance holds a lock on a file next to the socket for as long as it runs. The
kernel drops it when the process ends, however it ends, so a socket whose lock is
free was left behind, and one whose lock is held belongs to a live instance even
when that instance is too busy to answer.
"""

import errno
import fcntl
import os
import socket
import traceback
from typing import Callable, Optional

from . import APP_ID

COMMANDS = ("on", "off", "now", "status", "show")
MAX_LINE = 64


class AlreadyRunning(Exception):
    """Another instance owns the socket."""


class NotRunning(Exception):
    """No instance answers on the socket."""


def default_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "app", APP_ID, "control.sock")


def _read_line(conn: socket.socket) -> str:
    data = b""
    while b"\n" not in data and len(data) <= MAX_LINE:
        chunk = conn.recv(MAX_LINE)
        if not chunk:
            break
        data += chunk
    return data.split(b"\n", 1)[0].decode("utf-8", "replace").strip()


def request(path: str, command: str, timeout: float = 30.0) -> str:
    """Sends one command to the running instance and returns its answer line."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(path)
        conn.sendall(command.encode() + b"\n")
        answer = _read_line(conn)
    except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError) as err:
        # No instance, a socket left by one that died, or one that died before answering.
        raise NotRunning(path) from err
    finally:
        conn.close()
    if not answer:
        raise NotRunning(path)
    return answer


def _lock(path: str) -> int:
    """Locks path for as long as the returned descriptor stays open."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise AlreadyRunning(path) from None
    return fd


class Server:
    """Listens on the socket. handle(command) returns the answer line."""

    def __init__(self, path: str, handle: Callable[[str], str]) -> None:
        self.path = path
        self._handle = handle
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        self._lock = _lock(path + ".lock")
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._bind()
        except BaseException:
            self._sock.close()
            os.close(self._lock)
            raise
        self._sock.listen(8)
        self._sock.setblocking(False)

    def _bind(self) -> None:
        old = os.umask(0o177)
        try:
            try:
                self._sock.bind(self.path)
                return
            except OSError as err:
                if err.errno != errno.EADDRINUSE:
                    raise
            # The lock is ours, so the instance that made this socket is gone.
            os.unlink(self.path)
            self._sock.bind(self.path)
        finally:
            os.umask(old)

    def fileno(self) -> int:
        return self._sock.fileno()

    def serve_pending(self) -> None:
        """Answers every waiting client. Call when the socket is readable."""
        while True:
            try:
                conn, _ = self._sock.accept()
            except (BlockingIOError, InterruptedError):
                return
            with conn:
                conn.setblocking(True)
                conn.settimeout(2.0)
                try:
                    command = _read_line(conn)
                    answer = self._answer(command)
                    conn.sendall(answer.encode("utf-8", "replace") + b"\n")
                except OSError:
                    continue

    def _answer(self, command: str) -> str:
        if command not in COMMANDS:
            return f"error unknown command: {command[:MAX_LINE]!r}"
        try:
            return self._handle(command)
        except Exception as e:  # a bad command must not take the instance down
            traceback.print_exc()
            return f"error {type(e).__name__}: {e}"

    def close(self) -> None:
        self._sock.close()
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except OSError:
            pass
        # Last, so no newcomer takes the socket over while it is still in use.
        os.close(self._lock)


def try_listen(path: str, handle: Callable[[str], str]) -> Optional[Server]:
    """Returns a Server, or None when another instance already listens."""
    try:
        return Server(path, handle)
    except AlreadyRunning:
        return None
