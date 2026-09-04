"""Offline transcription through faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("whisper-desk.transcriber")

GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"
# Context handed back to the model from one sentence to the next: enough to keep
# the thread of a dictation split as you go, too short for it to start inventing.
CONTEXT_CHARS = 220
# Above this, the model itself judges that it heard nothing spoken.
NO_SPEECH_LIMIT = 0.6
# Whisper learned on subtitles: when it hears nothing, it spits their credits
# back out. The sentence alone is not damning — "thank you" does get dictated —
# but paired with a high no_speech_prob, it is filler. The list stays in the
# languages Whisper actually emits these in.
FILLERS = frozenset({
    "sous-titres réalisés par la communauté d'amara.org",
    "sous-titres réalisés par l'amara.org",
    "sous-titrage société radio-canada",
    "sous-titrage st' 501",
    "merci d'avoir regardé cette vidéo",
    "merci d'avoir regardé la vidéo",
    "abonnez-vous",
    "n'oubliez pas de vous abonner",
    "à la prochaine",
    "merci",
    "merci beaucoup",
    "au revoir",
    "thank you",
    "thanks for watching",
    "you",
})


def _normalise(text: str) -> str:
    """The text reduced to what makes it comparable: no case, no punctuation."""
    return text.strip().strip(""" .!?…«»"'-–—""").lower()


def is_filler(text: str, no_speech_prob: float) -> bool:
    """Is this sentence a hallucinated credit line rather than a dictation?"""
    normalised = _normalise(text)
    if "amara.org" in normalised or "sous-titrage" in normalised:
        # Nobody dictates that: no need to wait for the model's opinion.
        return True
    return no_speech_prob >= NO_SPEECH_LIMIT and normalised in FILLERS


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
    """Loads the model once and for all and keeps it in memory."""

    def __init__(self, config: dict[str, Any]):
        self.config = config["model"]
        self._model = None
        # Target values, known even before the model is loaded.
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
        except Exception as error:  # no CUDA, not enough VRAM, broken driver...
            if device != "cuda":
                raise
            logger.warning("Cannot load on CUDA (%s) — falling back to the CPU.", error)
            name = CPU_MODEL if self.config["name"] == "auto" else name
            device, compute_type = "cpu", "int8"
            self._model = WhisperModel(name, device=device, compute_type=compute_type)

        self.model_name, self.device, self.compute_type = name, device, compute_type
        logger.info("Model %s loaded on %s (%s).", name, device, compute_type)

    def prompt(self, context: str = "") -> str | None:
        """The user's vocabulary, extended by what they have just dictated.

        An isolated sentence has no context at all: "some pictures of blocks"
        after "we should add" transcribes far better when the model knows what
        came before.
        """
        parts = [str(self.config["initial_prompt"]).strip()]
        if self.config["context"]:
            parts.append(context.strip()[-CONTEXT_CHARS:])
        return " ".join(part for part in parts if part) or None

    def transcribe(self, pcm: bytes, context: str = "") -> str:
        """s16le 16 kHz mono PCM -> text."""
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
            initial_prompt=self.prompt(context),
            # Domain terms, pushed into the decoder prompt: without them,
            # "repos GitHub" comes back as "ripos" and "in Chrome" as "Inchrom".
            hotwords=str(self.config["vocabulary"]).strip() or None,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        kept = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            if is_filler(text, segment.no_speech_prob):
                logger.debug("Hallucination dropped: %r (no_speech=%.2f)",
                             text, segment.no_speech_prob)
                continue
            kept.append(text)
        return " ".join(kept).strip()
