"""Insertion du texte à l'emplacement du curseur : envoi d'un raccourci de collage.

Le texte lui-même transite par le presse-papiers, et l'on simule seulement
Ctrl+V. C'est la seule méthode indépendante de la disposition clavier : taper
un texte accentué supposerait de connaître la carte active (ici AZERTY), alors
que la touche du collage est la même partout.

Trois façons d'envoyer ce raccourci, une par hôte :

* Linux — clavier virtuel noyau (/dev/uinput). Sous Wayland, un client ne peut
  pas « taper » dans la fenêtre d'un autre : le protocole virtual-keyboard
  (celui de wtype) n'est pas implémenté par GNOME ; passer par le noyau
  contourne la question, et marche aussi bien sous X11.
* WSL — SendKeys de Windows, via PowerShell : les fenêtres où l'on dicte sont
  celles de Windows, qu'un clavier virtuel Linux ne toucherait jamais.
* macOS — « keystroke » de System Events (osascript), qui demande à
  l'application l'autorisation d'accessibilité.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import struct
import subprocess
import threading
import time
from typing import Iterable

from . import host

logger = logging.getLogger("whisper-desk.inject")

UINPUT_DEVICE = "/dev/uinput"

# include/uapi/linux/uinput.h
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0

# struct input_event, en tailles et alignement natifs (24 octets en 64 bits).
EVENT_FORMAT = "@llHHi"

KEY_CODES = {
    "ctrl": 29,
    "shift": 42,
    "alt": 56,
    "super": 125,
    "v": 47,
    "insert": 110,
    "enter": 28,
    "space": 57,
    "tab": 15,
}

MODIFIERS = ("ctrl", "shift", "alt", "super")

# Noms acceptés dans la configuration pour une même touche.
ALIASES = {
    "control": "ctrl",
    "cmd": "super",
    "command": "super",
    "meta": "super",
    "win": "super",
    "windows": "super",
    "option": "alt",
    "opt": "alt",
    "return": "enter",
    "ins": "insert",
}

# udev ne pose ID_INPUT_KEYBOARD (et libinput ne voit donc un clavier) que si le
# périphérique déclare toute la plage Échap → D. Un device à 7 touches est classé
# « power-switch » et purement et simplement ignoré par le compositeur.
DECLARED_KEYS = range(1, 128)

# Délai laissé au compositeur pour prendre en compte le nouveau périphérique.
DEVICE_SETTLE_SECONDS = 0.6


def parse_shortcut(shortcut: str) -> list[str]:
    """« ctrl+v », « Cmd + V » -> liste de touches canoniques connues."""
    keys = []
    for part in shortcut.split("+"):
        key = part.strip().lower()
        key = ALIASES.get(key, key)
        if key in KEY_CODES and key not in keys:
            keys.append(key)
    return keys


def default_shortcut() -> str:
    """Le raccourci de collage de l'hôte, quand la configuration dit « auto »."""
    return "super+v" if host.is_macos() else "ctrl+v"


def resolve_shortcut(configured: str) -> list[str]:
    """Résout « auto » puis découpe ; retombe sur le défaut si rien n'est lisible."""
    configured = (configured or "").strip()
    if not configured or configured.lower() == "auto":
        configured = default_shortcut()
    return parse_shortcut(configured) or parse_shortcut(default_shortcut())


def split_shortcut(keys: Iterable[str]) -> tuple[list[str], str | None]:
    """Sépare les modificateurs de la touche finale."""
    modifiers = [key for key in keys if key in MODIFIERS]
    others = [key for key in keys if key not in MODIFIERS]
    return modifiers, others[-1] if others else None


class Keyboard:
    """Contrat commun aux trois façons d'envoyer un raccourci."""

    name = "aucun"
    hint = ""

    @property
    def available(self) -> bool:
        return False

    def open(self) -> bool:
        return self.available

    def close(self) -> None:
        pass

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        raise NotImplementedError


class UinputKeyboard(Keyboard):
    """Clavier virtuel noyau, créé une fois et gardé ouvert tant que le daemon vit."""

    name = "uinput"
    hint = f"{UINPUT_DEVICE} doit être accessible en écriture (groupe input)"

    def __init__(self, name: str = "whisper-desk virtual keyboard"):
        self.device_name = name
        self._fd: int | None = None
        # prepare() ouvre le clavier dans un fil pendant que l'utilisateur parle,
        # write() s'en sert depuis un autre : le verrou fait attendre le second
        # jusqu'au bout du délai de prise en compte, sinon le premier collage
        # part vers un périphérique que le compositeur n'a pas encore vu.
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return os.access(UINPUT_DEVICE, os.W_OK)

    def open(self) -> bool:
        with self._lock:
            if self._fd is not None:
                return True
            if not self.available:
                logger.warning("%s inaccessible en écriture : insertion impossible.", UINPUT_DEVICE)
                return False
            try:
                fd = os.open(UINPUT_DEVICE, os.O_WRONLY | os.O_NONBLOCK)
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
                for code in DECLARED_KEYS:
                    fcntl.ioctl(fd, UI_SET_KEYBIT, code)
                # struct uinput_setup : input_id (bustype, vendor, product, version), name[80], ff_effects_max
                setup = struct.pack(
                    "<4H80sI", 0x03, 0x1D6B, 0x0001, 0x0001, self.device_name.encode()[:79], 0
                )
                fcntl.ioctl(fd, UI_DEV_SETUP, setup)
                fcntl.ioctl(fd, UI_DEV_CREATE)
            except OSError as error:
                logger.warning("Clavier virtuel indisponible : %s", error)
                return False
            time.sleep(DEVICE_SETTLE_SECONDS)
            self._fd = fd
            return True

    def close(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
            if fd is None:
                return
            try:
                fcntl.ioctl(fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(fd)

    def _emit(self, event_type: int, code: int, value: int) -> None:
        assert self._fd is not None
        # struct input_event : timeval (2 × long natif), type, code, value.
        # Tailles natives obligatoires : « <l » ferait 4 octets, le noyau en attend 8.
        os.write(self._fd, struct.pack(EVENT_FORMAT, 0, 0, event_type, code, value))

    def _sync(self) -> None:
        self._emit(EV_SYN, SYN_REPORT, 0)

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        """Enfonce puis relâche une combinaison, ex. ("ctrl", "v")."""
        codes = [KEY_CODES[key] for key in keys if key in KEY_CODES]
        if not codes:
            return False
        with self._lock:
            if not self.open():
                return False
            try:
                for code in codes:
                    self._emit(EV_KEY, code, 1)
                self._sync()
                time.sleep(hold)
                for code in reversed(codes):
                    self._emit(EV_KEY, code, 0)
                self._sync()
            except OSError as error:
                logger.warning("Envoi de touches impossible : %s", error)
                self.close()
                return False
        return True


# SendKeys : « ^ » Ctrl, « % » Alt, « + » Maj. Pas de touche Windows — elle est
# réservée au système, et c'est aussi pour cela que le raccourci global de WSL
# se prend sur Ctrl+Alt.
SENDKEYS_MODIFIERS = {"ctrl": "^", "alt": "%", "shift": "+"}
SENDKEYS_KEYS = {"insert": "{INS}", "enter": "{ENTER}", "space": " ", "tab": "{TAB}"}


def sendkeys_sequence(keys: Iterable[str]) -> str | None:
    """Traduit une combinaison canonique en séquence SendKeys, ou None si impossible."""
    modifiers, key = split_shortcut(keys)
    if key is None or "super" in modifiers:
        return None
    prefix = "".join(SENDKEYS_MODIFIERS[modifier] for modifier in modifiers)
    return prefix + SENDKEYS_KEYS.get(key, key)


class SendKeysKeyboard(Keyboard):
    """Frappe côté Windows, pour les fenêtres où l'on dicte depuis WSL."""

    name = "windows"
    hint = "l'interopérabilité Windows (powershell.exe) doit être accessible depuis WSL"

    @property
    def available(self) -> bool:
        return host.has_windows_interop()

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        sequence = sendkeys_sequence(keys)
        if sequence is None:
            logger.warning(
                "Raccourci de collage inutilisable sous Windows (la touche Windows "
                "n'est pas simulable) — préférez « ctrl+v »."
            )
            return False
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            f"[System.Windows.Forms.SendKeys]::SendWait({host.powershell_literal(sequence)})"
        )
        return host.run_powershell(script) is not None


# System Events nomme les modificateurs, et désigne par un code les touches
# qui n'écrivent rien.
APPLESCRIPT_MODIFIERS = {
    "ctrl": "control down",
    "alt": "option down",
    "shift": "shift down",
    "super": "command down",
}
APPLESCRIPT_KEY_CODES = {"enter": 36, "tab": 48, "space": 49, "insert": 114}


def applescript_command(keys: Iterable[str]) -> str | None:
    """Traduit une combinaison canonique en ordre AppleScript, ou None si impossible."""
    modifiers, key = split_shortcut(keys)
    if key is None:
        return None
    if key in APPLESCRIPT_KEY_CODES:
        action = f"key code {APPLESCRIPT_KEY_CODES[key]}"
    elif len(key) == 1:
        action = f'keystroke "{key}"'
    else:
        return None
    if modifiers:
        using = ", ".join(APPLESCRIPT_MODIFIERS[modifier] for modifier in modifiers)
        action += f" using {{{using}}}"
    return f"tell application \"System Events\" to {action}"


class AppleScriptKeyboard(Keyboard):
    """Frappe via System Events — soumise à l'autorisation d'accessibilité."""

    name = "applescript"
    hint = (
        "Réglages Système → Confidentialité et sécurité → Accessibilité : "
        "autorisez le terminal (ou whisper-desk) à contrôler l'ordinateur"
    )

    @property
    def available(self) -> bool:
        return bool(shutil.which("osascript"))

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        script = applescript_command(keys)
        if script is None:
            logger.warning("Raccourci de collage intraduisible en AppleScript.")
            return False
        try:
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("osascript indisponible : %s", error)
            return False
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            logger.warning("Frappe refusée par macOS : %s — %s", message[:160], self.hint)
            return False
        return True


class NullKeyboard(Keyboard):
    """Aucune frappe : le texte reste dans le presse-papiers."""

    name = "none"
    hint = "insertion au curseur désactivée"

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        return False


BACKENDS: dict[str, type[Keyboard]] = {
    "uinput": UinputKeyboard,
    "windows": SendKeysKeyboard,
    "applescript": AppleScriptKeyboard,
    "none": NullKeyboard,
}

PREFERENCES: dict[str, tuple[str, ...]] = {
    host.LINUX: ("uinput",),
    # Les fenêtres visées sont celles de Windows ; uinput ne sert que pour WSLg.
    host.WSL: ("windows", "uinput"),
    host.MACOS: ("applescript",),
}


def preferences() -> tuple[str, ...]:
    return PREFERENCES[host.name()]


def keyboard(preferred: str = "auto") -> Keyboard:
    """Le clavier virtuel adapté à l'hôte, ou celui demandé par la configuration."""
    preferred = (preferred or "auto").strip().lower()
    if preferred not in ("", "auto"):
        backend = BACKENDS.get(preferred)
        if backend is None:
            logger.warning(
                "Clavier « %s » inconnu (connus : %s) — choix automatique.",
                preferred, ", ".join(sorted(BACKENDS)),
            )
        else:
            return backend()

    candidates = preferences()
    for candidate in candidates:
        instance = BACKENDS[candidate]()
        if instance.available:
            return instance
    # Rien n'est prêt : on rend le premier choix, dont l'échec dira quoi installer.
    return BACKENDS[candidates[0]]()
