"""Transcription hors-ligne via faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("linux-whisper.transcriber")

GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"
# Contexte repassé au modèle d'une phrase à la suivante : assez pour tenir le fil
# d'une dictée découpée au fil de l'eau, trop court pour qu'il se mette à broder.
CONTEXT_CHARS = 220
# Au-delà, le modèle juge lui-même qu'il n'a rien entendu de parlé.
NO_SPEECH_LIMIT = 0.6
# Whisper a appris sur des sous-titres : quand il n'entend rien, il en recrache
# les génériques. La phrase seule ne condamne pas — « merci » se dicte — mais
# accompagnée d'un no_speech_prob élevé, c'est du remplissage.
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
    """Le texte réduit à ce qui permet de le comparer : sans casse ni ponctuation."""
    return text.strip().strip(""" .!?…«»"'-–—""").lower()


def is_filler(text: str, no_speech_prob: float) -> bool:
    """Cette phrase est-elle un générique halluciné plutôt qu'une dictée ?"""
    normalised = _normalise(text)
    if "amara.org" in normalised or "sous-titrage" in normalised:
        # Personne ne dicte ça : inutile d'attendre l'avis du modèle.
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

    def prompt(self, context: str = "") -> str | None:
        """Vocabulaire de l'utilisateur, prolongé par ce qu'il vient de dicter.

        Une phrase isolée n'a aucun contexte : « des images de blocs » après
        « il faudrait rajouter » se transcrit bien mieux quand le modèle sait
        ce qui précède.
        """
        parts = [str(self.config["initial_prompt"]).strip()]
        if self.config["context"]:
            parts.append(context.strip()[-CONTEXT_CHARS:])
        return " ".join(part for part in parts if part) or None

    def transcribe(self, pcm: bytes, context: str = "") -> str:
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
            initial_prompt=self.prompt(context),
            # Les termes du métier, poussés dans le prompt du décodeur : sans eux,
            # « repos GitHub » revient en « ripos » et « in Chrome » en « Inchrom ».
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
                logger.debug("Hallucination écartée : %r (no_speech=%.2f)",
                             text, segment.no_speech_prob)
                continue
            kept.append(text)
        return " ".join(kept).strip()
