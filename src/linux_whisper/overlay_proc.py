"""Pilotage du processus overlay (GTK4, Python système)."""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("linux-whisper.overlay")

OVERLAY_SCRIPT = Path(__file__).with_name("overlay.py")


def system_python() -> str:
    """Le Python système : c'est lui qui a PyGObject, pas celui du venv."""
    return os.environ.get("LW_SYSTEM_PYTHON") or shutil.which("python3") or "/usr/bin/python3"


class OverlayProcess:
    """Fenêtre d'écoute lancée à la demande, pilotée par des lignes sur stdin."""

    def __init__(self, config: dict[str, Any]):
        self.config = config["overlay"]
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if not self.config["enabled"] or self._process is not None:
            return
        command = [
            system_python(),
            str(OVERLAY_SCRIPT),
            str(self.config["width"]),
            str(self.config["height"]),
            str(self.config["accent"]),
        ]
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as error:
            logger.warning("Overlay indisponible : %s", error)
            self._process = None
            return
        self._send("state listening")

    def set_state(self, state: str) -> None:
        self._send(f"state {state}")

    def set_level(self, level: float) -> None:
        self._send(f"level {level:.3f}")

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def copy(self, text: str) -> bool:
        """Copie via la fenêtre de l'overlay (seule à avoir le focus Wayland)."""
        if not self.alive:
            return False
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._send(f"copy {payload}")
        return self.alive

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.write(b"quit\n")
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            process.kill()

    def _send(self, line: str) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        try:
            process.stdin.write(f"{line}\n".encode())
            process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            self._process = None
