"""Client de la socket du daemon."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from typing import Any

from .daemon import socket_path


class DaemonUnavailable(RuntimeError):
    pass


def _connect(timeout: float) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(str(socket_path()))
    return client


def send(command: str, timeout: float = 300.0, autostart: bool = True) -> dict[str, Any]:
    """Envoie une commande au daemon, en le démarrant au besoin."""
    unreachable = DaemonUnavailable(
        "daemon injoignable — lancez « systemctl --user start linux-whisper »"
    )
    try:
        client = _connect(timeout)
    except OSError:
        if not autostart or not _start_daemon():
            raise unreachable from None
        try:
            # La socket existe, mais le daemon peut avoir échoué juste après.
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
        raise DaemonUnavailable("le daemon n'a pas répondu")
    return json.loads(raw.decode("utf-8"))


def _start_daemon() -> bool:
    """Démarre le service systemd utilisateur puis attend la socket."""
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "linux-whisper.service"],
            check=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for _ in range(40):
        if socket_path().exists():
            return True
        time.sleep(0.25)
    return False
