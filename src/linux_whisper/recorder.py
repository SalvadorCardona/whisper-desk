"""Capture micro via arecord + détection de silence (VAD par énergie)."""

from __future__ import annotations

import math
import subprocess
import threading
import time
from typing import Any, Callable

RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_SAMPLES = 1600           # 100 ms
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH
NOISE_CHUNKS = 4               # 400 ms de bruit de fond pour calibrer le seuil
MIN_THRESHOLD = 180.0


def _rms(chunk: bytes) -> float:
    """RMS d'un buffer PCM s16le, sans dépendre de numpy."""
    count = len(chunk) // 2
    if count == 0:
        return 0.0
    total = 0
    for index in range(0, count * 2, 2):
        value = chunk[index] | (chunk[index + 1] << 8)
        if value >= 0x8000:
            value -= 0x10000
        total += value * value
    return math.sqrt(total / count)


class Recorder:
    """Enregistre jusqu'au silence, à l'appel de stop(), ou jusqu'au maximum."""

    def __init__(self, config: dict[str, Any], on_level: Callable[[float], None] | None = None):
        self.config = config["recording"]
        self.on_level = on_level
        self._stop = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self.reason = "unknown"

    def stop(self) -> None:
        self._stop.set()

    def record(self) -> bytes:
        """Bloque jusqu'à la fin de la capture et retourne le PCM brut (s16le 16 kHz mono)."""
        command = [
            "arecord",
            "-D", str(self.config["device"]),
            "-f", "S16_LE",
            "-r", str(RATE),
            "-c", str(CHANNELS),
            "-t", "raw",
            "-q",
            "-",
        ]
        self._process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
        assert self._process.stdout is not None

        frames: list[bytes] = []
        noise: list[float] = []
        configured = self.config["threshold"]
        threshold = None if configured == "auto" else max(float(configured), 1.0)

        silence_seconds = float(self.config["silence_seconds"])
        start_timeout = float(self.config["start_timeout_seconds"])
        max_seconds = float(self.config["max_seconds"])

        started = time.monotonic()
        speaking = False
        last_voice = started

        try:
            while not self._stop.is_set():
                chunk = self._process.stdout.read(CHUNK_BYTES)
                if not chunk:
                    self.reason = "eof"
                    break
                frames.append(chunk)
                now = time.monotonic()
                level = _rms(chunk)

                if threshold is None:
                    noise.append(level)
                    if len(noise) >= NOISE_CHUNKS:
                        floor = sum(noise) / len(noise)
                        threshold = max(floor * 3.5, MIN_THRESHOLD)
                    if self.on_level:
                        self.on_level(0.0)
                    continue

                if self.on_level:
                    self.on_level(min(level / (threshold * 4.0), 1.0))

                if level >= threshold:
                    speaking = True
                    last_voice = now

                if not speaking and start_timeout and now - started > start_timeout:
                    self.reason = "no-speech"
                    break
                if speaking and silence_seconds and now - last_voice > silence_seconds:
                    self.reason = "silence"
                    break
                if max_seconds and now - started > max_seconds:
                    self.reason = "max-duration"
                    break
            else:
                self.reason = "stopped"
        finally:
            self._terminate()

        if not speaking:
            return b""
        # On coupe la queue de silence, en gardant 300 ms de marge.
        if self.reason == "silence" and silence_seconds:
            keep = max(len(frames) - int((silence_seconds - 0.3) * 10), 1)
            frames = frames[:keep]
        return b"".join(frames)

    def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.stdout:
            process.stdout.close()
