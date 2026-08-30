"""Capture micro via arecord + détection de silence (VAD par énergie)."""

from __future__ import annotations

import array
import math
import subprocess
import sys
import threading
import time
from typing import Any, Callable

RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_SAMPLES = 1600           # 100 ms
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH
CHUNKS_PER_SECOND = RATE / CHUNK_SAMPLES
NOISE_CHUNKS = 4               # 400 ms de bruit de fond pour calibrer le seuil
MIN_THRESHOLD = 180.0
MIN_SEGMENT_CHUNKS = 4         # en deçà de 400 ms, ce n'est pas une phrase
SILENT_INPUT_PEAK = 30.0       # sous ce pic, l'entrée est muette, pas discrète
# Marge gardée après la dernière voix, pour ne pas couper une fin de mot.
TRIM_MARGIN_SECONDS = 0.3
# Dynamique affichée par l'overlay, du seuil de parole au cri.
LEVEL_RANGE_DB = 36.0


def _rms(chunk: bytes) -> float:
    """RMS d'un buffer PCM s16le, sans dépendre de numpy."""
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % SAMPLE_WIDTH])
    if not samples:
        return 0.0
    if sys.byteorder == "big":
        samples.byteswap()
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def visual_level(level: float, threshold: float) -> float:
    """RMS -> 0..1 pour l'overlay, en décibels au-dessus du seuil de parole.

    L'œil suit l'oreille : une échelle linéaire écrase la parole ordinaire tout
    en bas de la jauge et sature sur les pics. En décibels, le silence reste à
    zéro et toute la course sert à ce qui s'entend vraiment.
    """
    if level <= 0.0 or threshold <= 0.0:
        return 0.0
    decibels = 20.0 * math.log10(level / threshold)
    return max(0.0, min(decibels / LEVEL_RANGE_DB, 1.0))


class Recorder:
    """Enregistre jusqu'au silence, à l'appel de stop(), ou jusqu'au maximum."""

    def __init__(
        self,
        config: dict[str, Any],
        on_level: Callable[[float], None] | None = None,
        on_segment: Callable[[bytes], None] | None = None,
    ):
        self.config = config["recording"]
        self.on_level = on_level
        # Renseigné en mode « au fil de l'eau » : appelé à chaque phrase terminée.
        self.on_segment = on_segment
        self._stop = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self.reason = "unknown"
        # Niveau maximal rencontré : sert à distinguer « il n'a rien dit »
        # de « le micro ne capte rien du tout ».
        self.peak = 0.0

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
        streaming = bool(self.config["streaming"]) and self.on_segment is not None
        segment_silence = float(self.config["segment_silence_seconds"])

        started = time.monotonic()
        speaking = False
        spoke_once = False
        last_voice = started
        segment_start = 0        # index de départ de la phrase en cours

        try:
            while not self._stop.is_set():
                chunk = self._process.stdout.read(CHUNK_BYTES)
                if not chunk:
                    self.reason = "eof"
                    break
                frames.append(chunk)
                now = time.monotonic()
                level = _rms(chunk)
                self.peak = max(self.peak, level)

                if threshold is None:
                    noise.append(level)
                    if len(noise) >= NOISE_CHUNKS:
                        floor = sum(noise) / len(noise)
                        threshold = max(floor * 3.5, MIN_THRESHOLD)
                    if self.on_level:
                        self.on_level(0.0)
                    continue

                if self.on_level:
                    self.on_level(visual_level(level, threshold))

                if level >= threshold:
                    speaking = True
                    spoke_once = True
                    last_voice = now

                # Une petite pause termine une phrase : on l'envoie sans cesser d'écouter.
                if streaming and speaking and now - last_voice > segment_silence:
                    segment = self._slice(frames, segment_start, segment_silence)
                    segment_start = len(frames)
                    speaking = False
                    if segment:
                        self.on_segment(segment)
                    continue

                if not spoke_once and start_timeout and now - started > start_timeout:
                    self.reason = "no-speech"
                    break
                if spoke_once and silence_seconds and now - last_voice > silence_seconds:
                    self.reason = "silence"
                    break
                if max_seconds and now - started > max_seconds:
                    self.reason = "max-duration"
                    break
            else:
                self.reason = "stopped"
        finally:
            self._terminate()

        if not spoke_once:
            return b""
        # On ne rogne la fin que si l'écoute s'est arrêtée sur un silence : à
        # l'arrêt manuel, l'utilisateur vient de parler et couper ici lui
        # mangerait sa dernière seconde et demie.
        trailing = silence_seconds if self.reason == "silence" else 0.0
        if streaming:
            # Le reste éventuel après la dernière pause.
            return self._slice(frames, segment_start, trailing)
        return self._slice(frames, 0, trailing)

    @staticmethod
    def _slice(frames: list[bytes], start: int, trailing_silence: float) -> bytes:
        """Extrait les trames depuis `start`, sans la queue de silence."""
        chunks = frames[start:]
        if trailing_silence > TRIM_MARGIN_SECONDS:
            drop = int((trailing_silence - TRIM_MARGIN_SECONDS) * CHUNKS_PER_SECOND)
            chunks = chunks[: max(len(chunks) - drop, 0)]
        if len(chunks) < MIN_SEGMENT_CHUNKS:
            return b""
        return b"".join(chunks)

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
