"""Pilotage du processus overlay (GTK3, Python système)."""

from __future__ import annotations

import base64
import functools
import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger("linux-whisper.overlay")

OVERLAY_SCRIPT = Path(__file__).with_name("overlay.py")


def system_python() -> str:
    """Le Python système : c'est lui qui a PyGObject, pas celui du venv."""
    return os.environ.get("LW_SYSTEM_PYTHON") or shutil.which("python3") or "/usr/bin/python3"


@functools.cache
def gtk_available() -> bool:
    """Le Python système a-t-il PyGObject + GTK3 ?

    Sur macOS, et sur un Linux sans python3-gi, la réponse est non : mieux vaut
    le savoir une fois que lancer un processus condamné à chaque dictée.
    """
    try:
        return subprocess.run(
            [system_python(), "-c",
             "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk"],
            capture_output=True,
            timeout=20,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class OverlayProcess:
    """Fenêtre d'écoute lancée à la demande, pilotée par des lignes sur stdin."""

    def __init__(self, config: dict[str, Any]):
        self.config = config["overlay"]
        self._process: subprocess.Popen[bytes] | None = None
        # Les niveaux arrivent du fil d'enregistrement, les états du fil de la
        # dictée : sans verrou, deux lignes s'entrelaceraient sur le même tube.
        self._lock = threading.Lock()
        self._broken = False

    def start(self) -> None:
        if not self.config["enabled"] or self._process is not None:
            return
        if not gtk_available():
            logger.debug("Overlay ignoré : GTK3 absent du Python système.")
            return
        command = [
            system_python(),
            str(OVERLAY_SCRIPT),
            str(self.config["width"]),
            str(self.config["height"]),
            str(self.config["accent"]),
            str(self.config["position"]),
            str(self.config["margin"]),
            str(self.config["bars"]),
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

    def set_level(self, level: float, bands: Sequence[float] = ()) -> None:
        """Volume global, suivi de l'énergie par bande quand elle est connue."""
        spectrum = "".join(f" {band:.3f}" for band in bands)
        self._send(f"level {level:.3f}{spectrum}")

    @property
    def bars(self) -> int:
        return int(self.config["bars"]) if self.config["enabled"] else 0

    @property
    def alive(self) -> bool:
        return (
            self._process is not None
            and not self._broken
            and self._process.poll() is None
        )

    def copy(self, text: str) -> bool:
        """Copie via la fenêtre de l'overlay, qui possède une sélection X11."""
        if not self.alive:
            return False
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._send(f"copy {payload}")
        return self.alive

    def save_clipboard(self) -> bool:
        if not self.alive:
            return False
        self._send("saveclip")
        return self.alive

    def restore_clipboard(self) -> bool:
        if not self.alive:
            return False
        self._send("restoreclip")
        return self.alive

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            broken, self._broken = self._broken, False
        if process is None:
            return
        try:
            if broken or process.stdin is None:
                # Sans tube, impossible de demander la fermeture : on l'impose.
                process.terminate()
            else:
                process.stdin.write(b"quit\n")
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:  # SIGKILL en attente : rien de plus à faire
                logger.warning("L'overlay ne s'est pas terminé.")

    def _send(self, line: str) -> None:
        with self._lock:
            process = self._process
            if process is None or process.stdin is None or self._broken:
                return
            try:
                process.stdin.write(f"{line}\n".encode())
                process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                # Le tube est mort, mais pas forcément la fenêtre : on garde le
                # process sous la main pour que stop() puisse encore la fermer.
                self._broken = True
