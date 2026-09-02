"""Chargement de la configuration utilisateur (~/.config/linux-whisper/config.toml)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def _runtime_dir() -> Path:
    """Dossier des sockets : XDG sous Linux, TMPDIR privé sous macOS, /tmp sinon."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime)
    tmp = os.environ.get("TMPDIR")
    return Path(tmp) if tmp else Path("/tmp")


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "linux-whisper"
CONFIG_PATH = CONFIG_DIR / "config.toml"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "linux-whisper"
DATA_DIR = Path.home() / ".local/share/linux-whisper"
RUNTIME_DIR = _runtime_dir()

DEFAULTS: dict[str, Any] = {
    "hotkey": {
        # Raccourci global. Syntaxe GTK : <Super>, <Ctrl>, <Alt>, <Shift>.
        # "auto" -> <Super>j, sauf sous WSL où Windows réserve la touche Windows
        # aux raccourcis système : <Ctrl><Alt>j.
        "binding": "auto",
        "name": "linux-whisper",
        # "toggle" : 1er appui = écoute, 2e appui = transcription.
        "action": "toggle",
    },
    "model": {
        # "auto" -> large-v3-turbo si GPU NVIDIA, sinon small.
        "name": "auto",
        "device": "auto",          # auto | cuda | cpu
        "compute_type": "auto",    # auto | float16 | int8_float16 | int8
        "language": "fr",          # code ISO, ou "auto" pour détection
        "beam_size": 5,
        "initial_prompt": "",
        # Chargé au démarrage du daemon : la première dictée est instantanée.
        "preload": True,
    },
    "recording": {
        "device": "default",       # périphérique du backend de capture
        # auto | arecord | parec | rec | sox | ffmpeg
        "backend": "auto",
        "max_seconds": 120,
        # Dictée au fil de l'eau : chaque phrase est transcrite et insérée
        # dès que vous marquez une petite pause, sans arrêter l'écoute.
        "streaming": True,
        "segment_silence_seconds": 0.6,
        # Silence qui met fin à la dictée (secondes). 0 = désactivé.
        "silence_seconds": 2.0,
        # Abandon si rien n'est dit dans ce délai après l'appui.
        "start_timeout_seconds": 8,
        # "auto" ou un entier (RMS 0-32767).
        "threshold": "auto",
    },
    "output": {
        # cursor | clipboard | stdout | none  (combinables : "cursor+stdout")
        "mode": "cursor",
        # Raccourci de collage envoyé au clavier virtuel pour insérer le texte.
        # "auto" -> cmd+v sur macOS, ctrl+v ailleurs ; « shift+insert » si vous
        # dictez surtout dans un terminal.
        "paste_shortcut": "auto",
        # Comment la frappe du raccourci de collage est envoyée.
        # auto | uinput (Linux) | windows (WSL) | applescript (macOS) | none
        "keyboard": "auto",
        # Remet votre presse-papiers d'origine à la fin de la dictée.
        "restore_clipboard": True,
        "notify": False,
        # Journalise chaque transcription dans ~/.local/state/linux-whisper/history.log
        "history": True,
    },
    "overlay": {
        "enabled": True,
        "accent": "#e46212",
        # Taille de la pilule en pixels.
        "width": 232,
        "height": 64,
        # Nombre de barres de l'equalizer.
        "bars": 15,
        # bottom-center | top-center | center
        "position": "bottom-center",
        # Distance au bord de l'écran, en pixels.
        "margin": 96,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = {k: (v.copy() if isinstance(v, dict) else v) for k, v in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path: Path | None = None) -> dict[str, Any]:
    """Retourne la config fusionnée avec les valeurs par défaut."""
    path = path or CONFIG_PATH
    if not path.exists():
        return _merge(DEFAULTS, {})
    with path.open("rb") as handle:
        user = tomllib.load(handle)
    return _merge(DEFAULTS, user)
