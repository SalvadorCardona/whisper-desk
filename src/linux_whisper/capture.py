"""Choix de l'outil de capture du micro selon l'hôte.

Le reste du programme ne veut qu'une chose : un flux PCM s16le mono sur la
sortie standard d'un processus. Plusieurs outils savent le produire, aucun
n'est présent partout — arecord vient d'ALSA (Linux), parec de PulseAudio
(seul chemin audio de WSLg), rec/sox et ffmpeg couvrent macOS.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Callable

from . import host


class CaptureUnavailable(RuntimeError):
    """Aucun outil de capture installé pour cet hôte."""


@dataclass(frozen=True)
class Capture:
    """Une commande prête à lancer, et les variables d'environnement qu'elle exige."""

    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)


def _default_device(device: str) -> bool:
    return device.strip().lower() in ("", "default", "auto")


def _arecord(device: str, rate: int, channels: int) -> Capture:
    return Capture("arecord", [
        "arecord",
        "-D", "default" if _default_device(device) else device,
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", str(channels),
        "-t", "raw",
        "-q",
        "-",
    ])


def _parec(device: str, rate: int, channels: int) -> Capture:
    command = [
        "parec",
        "--format=s16le",
        f"--rate={rate}",
        f"--channels={channels}",
        "--latency-msec=100",
    ]
    if not _default_device(device):
        command += ["-d", device]
    return Capture("parec", command)


def _ffmpeg(device: str, rate: int, channels: int) -> Capture:
    if host.is_macos():
        # avfoundation désigne les entrées par index : « :0 » est le micro par
        # défaut. « ffmpeg -f avfoundation -list_devices true -i "" » les liste.
        source = ":0" if _default_device(device) else (
            device if device.startswith(":") else f":{device}"
        )
        input_args = ["-f", "avfoundation", "-i", source]
    else:
        input_args = ["-f", "pulse", "-i", "default" if _default_device(device) else device]
    return Capture("ffmpeg", [
        "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-nostdin",
        *input_args,
        "-ar", str(rate), "-ac", str(channels), "-f", "s16le", "-",
    ])


def _sox(binary: str) -> Callable[[str, int, int], Capture]:
    def build(device: str, rate: int, channels: int) -> Capture:
        command = [binary, "-q"]
        if binary == "sox":
            command.append("-d")          # « -d » : entrée = périphérique audio
        command += [
            "-t", "raw", "-b", "16", "-e", "signed-integer", "-L",
            "-r", str(rate), "-c", str(channels), "-",
        ]
        # sox ne prend pas le périphérique en argument : il lit AUDIODEV.
        env = {} if _default_device(device) else {"AUDIODEV": device}
        return Capture(binary, command, env)

    return build


BUILDERS: dict[str, Callable[[str, int, int], Capture]] = {
    "arecord": _arecord,
    "parec": _parec,
    "ffmpeg": _ffmpeg,
    "rec": _sox("rec"),
    "sox": _sox("sox"),
}

# Du plus adapté au plus dépanneur, pour chaque hôte.
PREFERENCES: dict[str, tuple[str, ...]] = {
    host.LINUX: ("arecord", "parec", "ffmpeg", "rec", "sox"),
    # WSLg ne fournit que PulseAudio : arecord n'existe qu'avec le greffon ALSA.
    host.WSL: ("parec", "arecord", "ffmpeg", "rec", "sox"),
    host.MACOS: ("rec", "sox", "ffmpeg"),
}

# Paquets à installer, cités par le diagnostic et l'installeur.
PACKAGES: dict[str, str] = {
    "arecord": "alsa-utils",
    "parec": "pulseaudio-utils",
    "ffmpeg": "ffmpeg",
    "rec": "sox",
    "sox": "sox",
}


def preferences() -> tuple[str, ...]:
    return PREFERENCES[host.name()]


def installed(name: str) -> bool:
    return bool(shutil.which(name))


def available() -> list[str]:
    """Les backends utilisables ici, dans l'ordre de préférence de l'hôte."""
    return [name for name in preferences() if installed(name)]


def recommended() -> str:
    """Le backend à installer en priorité sur cet hôte."""
    return preferences()[0]


def choose(preferred: str = "auto") -> str:
    """Nom du backend à employer. Lève CaptureUnavailable si rien n'est installé."""
    preferred = (preferred or "auto").strip().lower()
    if preferred not in ("", "auto"):
        if preferred not in BUILDERS:
            raise CaptureUnavailable(
                f"backend de capture inconnu : « {preferred} » "
                f"(connus : {', '.join(sorted(BUILDERS))})"
            )
        if not installed(preferred):
            raise CaptureUnavailable(f"« {preferred} » n'est pas installé")
        return preferred

    usable = available()
    if usable:
        return usable[0]
    wanted = recommended()
    raise CaptureUnavailable(
        f"aucun outil de capture trouvé sur {host.label()} — installez "
        f"{PACKAGES[wanted]} (« {wanted} »)"
    )


def build(device: str, rate: int, channels: int, backend: str = "auto") -> Capture:
    """La commande de capture, prête pour Popen."""
    return BUILDERS[choose(backend)](device, rate, channels)
