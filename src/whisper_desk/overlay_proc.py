"""Driving the overlay process (GTK3, system Python)."""

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

logger = logging.getLogger("whisper-desk.overlay")

OVERLAY_SCRIPT = Path(__file__).with_name("overlay.py")


def system_python() -> str:
    """The system Python: it is the one with PyGObject, not the venv's."""
    return os.environ.get("WD_SYSTEM_PYTHON") or shutil.which("python3") or "/usr/bin/python3"


@functools.cache
def gtk_available() -> bool:
    """Does the system Python have PyGObject + GTK3?

    On macOS, and on a Linux without python3-gi, the answer is no: better to
    know it once than to launch a doomed process for every dictation.
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
    """Listening window launched on demand, driven by lines on stdin."""

    def __init__(self, config: dict[str, Any]):
        self.config = config["overlay"]
        self._process: subprocess.Popen[bytes] | None = None
        # Levels come from the recording thread, states from the dictation
        # thread: without a lock, two lines would interleave on the same pipe.
        self._lock = threading.Lock()
        self._broken = False

    def start(self) -> None:
        if not self.config["enabled"] or self._process is not None:
            return
        if not gtk_available():
            logger.debug("Overlay skipped: GTK3 missing from the system Python.")
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
            logger.warning("Overlay unavailable: %s", error)
            self._process = None
            return
        self._send("state listening")

    def set_state(self, state: str) -> None:
        self._send(f"state {state}")

    def set_level(self, level: float, bands: Sequence[float] = ()) -> None:
        """Overall volume, followed by the energy per band when it is known."""
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
        """Copies through the overlay window, which owns an X11 selection."""
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
                # Without a pipe, we cannot ask it to close: we force it.
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
            except subprocess.TimeoutExpired:  # SIGKILL pending: nothing more to do
                logger.warning("The overlay did not exit.")

    def _send(self, line: str) -> None:
        with self._lock:
            process = self._process
            if process is None or process.stdin is None or self._broken:
                return
            try:
                process.stdin.write(f"{line}\n".encode())
                process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                # The pipe is dead, but not necessarily the window: the process
                # is kept around so that stop() can still close it.
                self._broken = True
