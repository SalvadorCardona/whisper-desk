"""Enregistrement du raccourci global (GNOME / gsettings)."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = f"{SCHEMA}.custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
SLOT = "linux-whisper"
KEY_PATH = f"{BASE_PATH}/{SLOT}/"


class UnsupportedDesktop(RuntimeError):
    pass


def _gsettings(*args: str) -> str:
    result = subprocess.run(
        ["gsettings", *args], check=True, capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def is_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("DESKTOP_SESSION", "")
    return "GNOME" in desktop.upper() or "UNITY" in desktop.upper()


def _ensure_available() -> None:
    if not shutil.which("gsettings"):
        raise UnsupportedDesktop("gsettings introuvable")
    if not is_gnome():
        raise UnsupportedDesktop(
            f"bureau non géré ({os.environ.get('XDG_CURRENT_DESKTOP', 'inconnu')})"
        )


def _bindings() -> list[str]:
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    if raw in ("@as []", "[]", ""):
        return []
    return [item.strip().strip("'\"") for item in raw.strip("[]").split(",") if item.strip()]


def _write_bindings(paths: list[str]) -> None:
    serialized = "[" + ", ".join(f"'{path}'" for path in paths) + "]"
    _gsettings("set", SCHEMA, "custom-keybindings", serialized)


def install(config: dict[str, Any], command: str) -> str:
    """Crée ou met à jour le raccourci. Retourne la combinaison installée."""
    _ensure_available()
    settings = config["hotkey"]
    binding = str(settings["binding"])

    paths = _bindings()
    if KEY_PATH not in paths:
        paths.append(KEY_PATH)
        _write_bindings(paths)

    target = f"{CUSTOM_SCHEMA}:{KEY_PATH}"
    _gsettings("set", target, "name", str(settings["name"]))
    _gsettings("set", target, "command", command)
    _gsettings("set", target, "binding", binding)
    return binding


def remove() -> None:
    _ensure_available()
    paths = [path for path in _bindings() if path != KEY_PATH]
    _write_bindings(paths)


def show() -> dict[str, str]:
    _ensure_available()
    if KEY_PATH not in _bindings():
        return {}
    target = f"{CUSTOM_SCHEMA}:{KEY_PATH}"
    return {
        "name": _gsettings("get", target, "name").strip("'"),
        "command": _gsettings("get", target, "command").strip("'"),
        "binding": _gsettings("get", target, "binding").strip("'"),
    }
