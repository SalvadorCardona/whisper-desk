"""Insertion du texte à l'emplacement du curseur.

Sous Wayland, un client ne peut pas « taper » dans la fenêtre d'un autre : le
protocole virtual-keyboard (utilisé par wtype) n'est pas implémenté par GNOME.
On passe donc par un clavier virtuel noyau (/dev/uinput) qui envoie un simple
raccourci de collage — le texte, lui, transite par le presse-papiers.

C'est aussi la seule méthode indépendante de la disposition clavier : envoyer
les touches d'un texte accentué supposerait de connaître la carte XKB active
(ici AZERTY), alors que Ctrl+V occupe la même touche partout.
"""

from __future__ import annotations

import fcntl
import logging
import os
import struct
import time
from typing import Iterable

logger = logging.getLogger("linux-whisper.inject")

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
}

# udev ne pose ID_INPUT_KEYBOARD (et libinput ne voit donc un clavier) que si le
# périphérique déclare toute la plage Échap → D. Un device à 7 touches est classé
# « power-switch » et purement et simplement ignoré par le compositeur.
DECLARED_KEYS = range(1, 128)

# Délai laissé au compositeur pour prendre en compte le nouveau périphérique.
DEVICE_SETTLE_SECONDS = 0.6


class VirtualKeyboard:
    """Clavier virtuel créé une fois, gardé ouvert tant que le daemon vit."""

    def __init__(self, name: str = "linux-whisper virtual keyboard"):
        self.name = name
        self._fd: int | None = None

    @property
    def available(self) -> bool:
        return os.access(UINPUT_DEVICE, os.W_OK)

    def open(self) -> bool:
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
            setup = struct.pack("<4H80sI", 0x03, 0x1D6B, 0x0001, 0x0001, self.name.encode()[:79], 0)
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as error:
            logger.warning("Clavier virtuel indisponible : %s", error)
            return False
        self._fd = fd
        time.sleep(DEVICE_SETTLE_SECONDS)
        return True

    def close(self) -> None:
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
        if not self.open():
            return False
        codes = [KEY_CODES[key] for key in keys if key in KEY_CODES]
        if not codes:
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


def parse_shortcut(shortcut: str) -> list[str]:
    """« ctrl+v », « shift+insert » -> liste de touches connues."""
    keys = [part.strip().lower() for part in shortcut.split("+") if part.strip()]
    return [key for key in keys if key in KEY_CODES]
