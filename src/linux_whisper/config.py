"""Chargement de la configuration utilisateur (~/.config/linux-whisper/config.toml)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "linux-whisper"
CONFIG_PATH = CONFIG_DIR / "config.toml"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "linux-whisper"
DATA_DIR = Path.home() / ".local/share/linux-whisper"

DEFAULTS: dict[str, Any] = {
    "hotkey": {
        # Raccourci global enregistré dans GNOME. Syntaxe GTK : <Super>, <Ctrl>, <Alt>, <Shift>.
        "binding": "<Super>j",
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
        "device": "default",       # périphérique ALSA
        "max_seconds": 120,
        # Arrêt automatique après ce silence (secondes). 0 = désactivé.
        "silence_seconds": 1.6,
        # Abandon si rien n'est dit dans ce délai après l'appui.
        "start_timeout_seconds": 8,
        # "auto" ou un entier (RMS 0-32767).
        "threshold": "auto",
    },
    "output": {
        # clipboard | type | stdout | none  (combinables : "clipboard+type")
        "mode": "clipboard",
        # Colle automatiquement après la copie (nécessite wtype ou ydotool).
        "paste": False,
        "notify": True,
        # Journalise chaque transcription dans ~/.local/state/linux-whisper/history.log
        "history": True,
    },
    "overlay": {
        "enabled": True,
        "accent": "#e46212",
        # Taille de la pilule en pixels.
        "width": 168,
        "height": 64,
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
