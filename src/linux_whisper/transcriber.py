"""Transcription hors-ligne via faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("linux-whisper.transcriber")

GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"


def has_nvidia_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        return subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, timeout=5
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Transcriber:
    """Charge le modèle une fois pour toutes et le garde en mémoire."""

    def __init__(self, config: dict[str, Any]):
        self.config = config["model"]
        self._model = None
        # Valeurs cibles, connues avant même le chargement du modèle.
        self.model_name, self.device, self.compute_type = self._resolve()

    def _resolve(self) -> tuple[str, str, str]:
        device = self.config["device"]
        if device == "auto":
            device = "cuda" if has_nvidia_gpu() else "cpu"

        name = self.config["name"]
        if name == "auto":
            name = GPU_MODEL if device == "cuda" else CPU_MODEL

        compute_type = self.config["compute_type"]
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        return name, device, compute_type

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        name, device, compute_type = self._resolve()
        try:
            self._model = WhisperModel(name, device=device, compute_type=compute_type)
        except Exception as error:  # CUDA absent, VRAM insuffisante, driver KO...
            if device != "cuda":
                raise
            logger.warning("Chargement CUDA impossible (%s) — repli sur le CPU.", error)
            name = CPU_MODEL if self.config["name"] == "auto" else name
            device, compute_type = "cpu", "int8"
            self._model = WhisperModel(name, device=device, compute_type=compute_type)

        self.model_name, self.device, self.compute_type = name, device, compute_type
        logger.info("Modèle %s chargé sur %s (%s).", name, device, compute_type)

    def transcribe(self, pcm: bytes) -> str:
        """PCM s16le 16 kHz mono -> texte."""
        if not pcm:
            return ""
        self.load()

        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        language = self.config["language"]
        segments, _info = self._model.transcribe(
            audio,
            language=None if language in ("", "auto") else language,
            beam_size=int(self.config["beam_size"]),
            initial_prompt=self.config["initial_prompt"] or None,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
