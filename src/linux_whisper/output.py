"""Livraison du texte transcrit : insertion au curseur, presse-papiers, notifications."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config as config_module
from .inject import VirtualKeyboard, parse_shortcut
from .overlay_proc import system_python

logger = logging.getLogger("linux-whisper.output")

CLIPBOARD_HELPER = Path(__file__).with_name("clipboard_gtk.py")
# Laisse l'application cible réclamer les données de la sélection avant qu'on
# ne remette l'ancien presse-papiers : un collage X11 est asynchrone.
PASTE_SETTLE_SECONDS = 0.25
CLIPBOARD_SETTLE_SECONDS = 0.12


def _run(command: list[str], text_input: str | None = None) -> bool:
    try:
        # Pas de capture_output : wl-copy se détache pour servir la sélection et
        # hériterait des tubes, ce qui bloquerait l'attente jusqu'au délai maximum.
        subprocess.run(
            command,
            input=text_input.encode() if text_input is not None else None,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Échec de %s : %s", command[0], error)
        return False


def _capture(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, timeout=10)
        return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class Clipboard:
    """Presse-papiers, avec sauvegarde et restitution du contenu de l'utilisateur.

    Trois chemins, du plus fiable au plus débrouillard : les outils dédiés
    (wl-clipboard, xclip), puis la fenêtre de l'overlay — sous Wayland seul un
    client à fenêtre peut poser une sélection, et l'overlay en a une.
    """

    def __init__(self, overlay: Any = None):
        self.overlay = overlay
        self._saved: str | None = None
        self._has_saved = False

    def save(self) -> None:
        if self._has_saved:
            return
        self._has_saved = True
        if shutil.which("wl-paste"):
            self._saved = _capture(["wl-paste", "--no-newline"])
        elif shutil.which("xclip"):
            self._saved = _capture(["xclip", "-selection", "clipboard", "-o"])
        elif self.overlay is not None and self.overlay.save_clipboard():
            self._saved = None  # mémorisé côté overlay
        else:
            logger.debug("Presse-papiers non sauvegardé : aucun lecteur disponible.")

    def set(self, text: str) -> bool:
        if shutil.which("wl-copy"):
            return _run(["wl-copy", "--", text])
        if shutil.which("xclip"):
            return _run(["xclip", "-selection", "clipboard"], text)
        if shutil.which("xsel"):
            return _run(["xsel", "--clipboard", "--input"], text)
        if self.overlay is not None and self.overlay.copy(text):
            return True
        return _run([system_python(), str(CLIPBOARD_HELPER)], text)

    def restore(self) -> None:
        if not self._has_saved:
            return
        if self._saved is not None:
            self.set(self._saved)
        elif self.overlay is not None:
            self.overlay.restore_clipboard()
        self._has_saved = False
        self._saved = None


class CursorWriter:
    """Insère le texte là où se trouve le curseur, via un collage simulé.

    Envoyer le texte touche par touche supposerait de connaître la carte XKB
    active (AZERTY, accents, touches mortes) ; le raccourci de collage, lui,
    occupe la même touche physique sur toutes les dispositions.
    """

    def __init__(self, config: dict[str, Any], overlay: Any = None):
        self.settings = config["output"]
        self.clipboard = Clipboard(overlay)
        self.keyboard = VirtualKeyboard()
        self.shortcut = parse_shortcut(str(self.settings["paste_shortcut"])) or ["ctrl", "v"]

    def prepare(self) -> None:
        """Crée le clavier virtuel à l'avance : le compositeur met ~0,6 s à le voir."""
        self.keyboard.open()
        if self.settings["restore_clipboard"]:
            self.clipboard.save()

    def write(self, text: str) -> bool:
        if self.settings["restore_clipboard"]:
            self.clipboard.save()
        if not self.clipboard.set(text):
            logger.warning("Texte non copié : insertion impossible.")
            return False
        # wl-copy prend la propriété de la sélection dans un processus détaché :
        # coller trop tôt collerait le contenu précédent.
        time.sleep(CLIPBOARD_SETTLE_SECONDS)
        if not self.keyboard.press(self.shortcut):
            logger.warning(
                "Clavier virtuel indisponible : le texte reste dans le presse-papiers."
            )
            return False
        time.sleep(PASTE_SETTLE_SECONDS)
        return True

    def close(self) -> None:
        if self.settings["restore_clipboard"]:
            self.clipboard.restore()
        self.keyboard.close()


def copy(text: str, overlay: Any = None) -> bool:
    return Clipboard(overlay).set(text)


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


def modes(config: dict[str, Any]) -> set[str]:
    raw = str(config["output"]["mode"])
    found = {mode.strip() for mode in raw.split("+") if mode.strip()}
    # « type » reste accepté comme synonyme historique de « cursor ».
    return {"cursor" if mode == "type" else mode for mode in found}


def deliver(text: str, config: dict[str, Any], writer: CursorWriter | None = None,
            overlay: Any = None) -> None:
    """Applique les modes de sortie configurés au texte transcrit."""
    settings = config["output"]
    selected = modes(config)

    if "cursor" in selected and writer is not None:
        writer.write(text)
    if "clipboard" in selected:
        copy(text, overlay=overlay)
    if "stdout" in selected:
        print(text, flush=True)
    if settings["history"]:
        log_history(text)
    if settings["notify"]:
        preview = text if len(text) <= 140 else text[:139] + "…"
        notify("Transcription", preview)
