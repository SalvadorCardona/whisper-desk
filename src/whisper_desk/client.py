"""Client for the daemon's socket."""

from __future__ import annotations

import json
import socket
import time
from typing import Any

from . import service
from .daemon import socket_path


class DaemonUnavailable(RuntimeError):
    pass


def _connect(timeout: float) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(str(socket_path()))
    return client


def send(command: str, timeout: float = 300.0, autostart: bool = True) -> dict[str, Any]:
    """Sends a command to the daemon, starting it if need be."""
    unreachable = DaemonUnavailable(
        f"daemon unreachable — run '{service.hint()}'"
    )
    try:
        client = _connect(timeout)
    except OSError:
        if not autostart or not _start_daemon():
            raise unreachable from None
        try:
            # The socket exists, but the daemon may have died right after.
            client = _connect(timeout)
        except OSError:
            raise unreachable from None

    try:
        client.sendall((json.dumps({"cmd": command}) + "\n").encode("utf-8"))
        with client.makefile("rb") as stream:
            raw = stream.readline()
    finally:
        client.close()

    if not raw:
        raise DaemonUnavailable("the daemon did not answer")
    return json.loads(raw.decode("utf-8"))


def _start_daemon() -> bool:
    """Starts the daemon (systemd, launchd or a detached process) then waits for the socket."""
    if not service.start():
        return False
    for _ in range(40):
        if socket_path().exists():
            return True
        time.sleep(0.25)
    return False
