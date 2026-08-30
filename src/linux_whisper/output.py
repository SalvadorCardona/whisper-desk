"""Livraison du texte transcrit : insertion au curseur, presse-papiers, notifications."""

from __future__ import annotations

import base64
import codecs
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config as config_module
from . import host
from .inject import keyboard, resolve_shortcut
from .overlay_proc import system_python

logger = logging.getLogger("linux-whisper.output")

CLIPBOARD_HELPER = Path(__file__).with_name("clipboard_gtk.py")
# Laisse l'application cible réclamer les données de la sélection avant qu'on
# ne remette l'ancien presse-papiers : un collage X11 est asynchrone.
PASTE_SETTLE_SECONDS = 0.25
CLIPBOARD_SETTLE_SECONDS = 0.12


def _run(command: list[str], data: bytes | None = None) -> bool:
    try:
        # Pas de capture_output : wl-copy se détache pour servir la sélection et
        # hériterait des tubes, ce qui bloquerait l'attente jusqu'au délai maximum.
        subprocess.run(
            command,
            input=data,
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


# -- presse-papiers, un chemin par hôte --------------------------------------
#
# Chaque fonction retourne False si son outil n'est pas là, pour laisser la
# suivante tenter sa chance ; les lecteurs retournent None de la même façon.


def _set_wayland(text: str) -> bool:
    return bool(shutil.which("wl-copy")) and _run(["wl-copy", "--", text])


def _set_xclip(text: str) -> bool:
    return bool(shutil.which("xclip")) and _run(
        ["xclip", "-selection", "clipboard"], text.encode()
    )


def _set_xsel(text: str) -> bool:
    return bool(shutil.which("xsel")) and _run(
        ["xsel", "--clipboard", "--input"], text.encode()
    )


def _set_macos(text: str) -> bool:
    return bool(shutil.which("pbcopy")) and _run(["pbcopy"], text.encode())


def _set_windows(text: str) -> bool:
    """clip.exe reconnaît l'UTF-16LE à sa marque d'ordre : sans elle, les accents tombent."""
    clip = shutil.which("clip.exe")
    if clip and _run([clip], codecs.BOM_UTF16_LE + text.encode("utf-16-le")):
        return True
    if not host.has_windows_interop():
        return False
    # Repli sans clip.exe : le texte voyage en base64, pur ASCII, donc à l'abri
    # des pages de codes de la console Windows.
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = (
        "Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{payload}')))"
    )
    return host.run_powershell(script) is not None


def _get_wayland() -> str | None:
    return _capture(["wl-paste", "--no-newline"]) if shutil.which("wl-paste") else None


def _get_xclip() -> str | None:
    return _capture(["xclip", "-selection", "clipboard", "-o"]) if shutil.which("xclip") else None


def _get_xsel() -> str | None:
    return _capture(["xsel", "--clipboard", "--output"]) if shutil.which("xsel") else None


def _get_macos() -> str | None:
    return _capture(["pbpaste"]) if shutil.which("pbpaste") else None


def _get_windows() -> str | None:
    text = host.run_powershell("Get-Clipboard -Raw")
    if text is None:
        return None
    # Get-Clipboard ajoute une fin de ligne, et Windows sépare en CRLF.
    return text.replace("\r\n", "\n").rstrip("\n")


SETTERS: dict[str, tuple[Callable[[str], bool], ...]] = {
    host.LINUX: (_set_wayland, _set_xclip, _set_xsel),
    host.WSL: (_set_windows, _set_wayland, _set_xclip, _set_xsel),
    host.MACOS: (_set_macos,),
}

GETTERS: dict[str, tuple[Callable[[], str | None], ...]] = {
    host.LINUX: (_get_wayland, _get_xclip, _get_xsel),
    host.WSL: (_get_windows, _get_wayland, _get_xclip, _get_xsel),
    host.MACOS: (_get_macos,),
}

# Outils à installer, cités par le diagnostic et l'installeur.
CLIPBOARD_TOOLS: dict[str, tuple[str, ...]] = {
    host.LINUX: ("wl-copy", "xclip", "xsel"),
    host.WSL: ("clip.exe", "wl-copy", "xclip", "xsel"),
    host.MACOS: ("pbcopy",),
}


def clipboard_tool() -> str | None:
    """Le premier outil de presse-papiers présent, pour le diagnostic."""
    for tool in CLIPBOARD_TOOLS[host.name()]:
        if shutil.which(tool):
            return tool
    return None


class Clipboard:
    """Presse-papiers, avec sauvegarde et restitution du contenu de l'utilisateur.

    Du plus fiable au plus débrouillard : les outils de l'hôte (wl-clipboard,
    xclip, pbcopy, clip.exe), puis la fenêtre de l'overlay — sous Wayland seul
    un client à fenêtre peut poser une sélection, et l'overlay en a une.
    """

    def __init__(self, overlay: Any = None):
        self.overlay = overlay
        self._saved: str | None = None
        self._has_saved = False

    def save(self) -> None:
        if self._has_saved:
            return
        self._has_saved = True
        for getter in GETTERS[host.name()]:
            saved = getter()
            if saved is not None:
                self._saved = saved
                return
        if self.overlay is not None and self.overlay.save_clipboard():
            self._saved = None  # mémorisé côté overlay
            return
        logger.debug("Presse-papiers non sauvegardé : aucun lecteur disponible.")

    def set(self, text: str) -> bool:
        for setter in SETTERS[host.name()]:
            if setter(text):
                return True
        if self.overlay is not None and self.overlay.copy(text):
            return True
        return _run([system_python(), str(CLIPBOARD_HELPER)], text.encode())

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
        self.keyboard = keyboard(str(self.settings["keyboard"]))
        self.shortcut = resolve_shortcut(str(self.settings["paste_shortcut"]))

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


def _applescript_string(text: str) -> str:
    """Chaîne AppleScript : seuls le backslash et le guillemet s'échappent."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(summary: str, body: str = "") -> None:
    """Notification de bureau, quand l'hôte sait en afficher une."""
    if shutil.which("notify-send"):
        _run([
            "notify-send",
            "--app-name=linux-whisper",
            "--icon=audio-input-microphone-symbolic",
            "--expire-time=3000",
            summary,
            body,
        ])
        return
    if host.is_macos() and shutil.which("osascript"):
        script = (
            f"display notification {_applescript_string(body)} "
            f"with title {_applescript_string(summary)}"
        )
        _run(["osascript", "-e", script])
        return
    logger.debug("Notification ignorée : aucun afficheur disponible.")


def log_history(text: str) -> None:
    # Les phrases suivantes arrivent précédées d'une espace de liaison, qui n'a
    # pas de sens une fois la ligne isolée dans le journal.
    entry = text.strip()
    if not entry:
        return
    try:
        config_module.STATE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with (config_module.STATE_DIR / "history.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\t{entry}\n")
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
