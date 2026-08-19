"""Livraison du texte transcrit : presse-papiers, frappe clavier, notification, historique."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config as config_module
from .overlay_proc import system_python

logger = logging.getLogger("linux-whisper.output")


def _run(command: list[str], text_input: str | None = None) -> bool:
    try:
        subprocess.run(
            command,
            input=text_input.encode() if text_input is not None else None,
            check=True,
            capture_output=True,
            timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Échec de %s : %s", command[0], error)
        return False


CLIPBOARD_HELPER = Path(__file__).with_name("clipboard_gtk.py")


def copy(text: str, overlay: Any = None) -> bool:
    """Copie le texte, en essayant les outils du système avant le repli GTK."""
    if shutil.which("wl-copy"):
        return _run(["wl-copy", "--", text])
    if shutil.which("xclip"):
        return _run(["xclip", "-selection", "clipboard"], text)
    if shutil.which("xsel"):
        return _run(["xsel", "--clipboard", "--input"], text)
    # Sans outil dédié : sous Wayland seul un client à fenêtre focalisée peut
    # poser une sélection — l'overlay est déjà à l'écran, il fait le travail.
    if overlay is not None and overlay.copy(text):
        time.sleep(1.2)
        return True
    return _run([system_python(), str(CLIPBOARD_HELPER)], text)


def type_text(text: str) -> bool:
    if shutil.which("wtype"):
        return _run(["wtype", "--", text])
    if shutil.which("ydotool"):
        return _run(["ydotool", "type", "--", text])
    if shutil.which("xdotool"):
        return _run(["xdotool", "type", "--clearmodifiers", "--", text])
    logger.warning("Aucun outil de frappe clavier (installez wtype ou ydotool).")
    return False


def paste() -> bool:
    if shutil.which("wtype"):
        return _run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])
    if shutil.which("ydotool"):
        return _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
    if shutil.which("xdotool"):
        return _run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
    return False


def notify(summary: str, body: str = "") -> None:
    if not shutil.which("notify-send"):
        return
    _run([
        "notify-send",
        "--app-name=linux-whisper",
        "--icon=audio-input-microphone-symbolic",
        "--expire-time=3000",
        summary,
        body,
    ])


def log_history(text: str) -> None:
    try:
        config_module.STATE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with (config_module.STATE_DIR / "history.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\t{text}\n")
    except OSError as error:
        logger.warning("Historique non écrit : %s", error)


def deliver(text: str, config: dict[str, Any], overlay: Any = None) -> None:
    """Applique les modes de sortie configurés au texte transcrit."""
    settings = config["output"]
    modes = {mode.strip() for mode in str(settings["mode"]).split("+") if mode.strip()}

    if "clipboard" in modes:
        copy(text, overlay=overlay)
        if settings["paste"]:
            paste()
    if "type" in modes:
        type_text(text)
    if "stdout" in modes:
        print(text, flush=True)
    if settings["history"]:
        log_history(text)
    if settings["notify"]:
        preview = text if len(text) <= 140 else text[:139] + "…"
        notify("Transcription copiée" if "clipboard" in modes else "Transcription", preview)
