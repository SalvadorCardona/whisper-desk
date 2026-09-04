"""Inserting text where the cursor is: sending a paste shortcut.

The text itself travels through the clipboard, and only Ctrl+V is simulated.
That is the only method independent from the keyboard layout: typing accented
text would mean knowing the active layout (AZERTY here), whereas the paste key
sits in the same place everywhere.

Three ways of sending that shortcut, one per host:

* Linux — kernel virtual keyboard (/dev/uinput). Under Wayland, a client cannot
  "type" into another client's window: the virtual-keyboard protocol (the one
  wtype uses) is not implemented by GNOME; going through the kernel sidesteps
  the question, and works just as well under X11.
* WSL — Windows SendKeys, through PowerShell: the windows you dictate into are
  Windows ones, which a Linux virtual keyboard would never reach.
* macOS — System Events "keystroke" (osascript), which asks the application for
  accessibility permission.
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

# struct input_event, in native sizes and alignment (24 bytes on 64-bit).
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

# Names accepted in the configuration for one and the same key.
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

# udev only sets ID_INPUT_KEYBOARD (and libinput therefore only sees a keyboard)
# if the device declares the whole Esc → D range. A 7-key device is classified
# as a "power-switch" and plainly ignored by the compositor.
DECLARED_KEYS = range(1, 128)

# Time left to the compositor to take the new device into account.
DEVICE_SETTLE_SECONDS = 0.6


def parse_shortcut(shortcut: str) -> list[str]:
    """Parses "ctrl+v" or "Cmd + V" into a list of known canonical keys."""
    keys = []
    for part in shortcut.split("+"):
        key = part.strip().lower()
        key = ALIASES.get(key, key)
        if key in KEY_CODES and key not in keys:
            keys.append(key)
    return keys


def default_shortcut() -> str:
    """The host's paste shortcut, when the configuration says "auto"."""
    return "super+v" if host.is_macos() else "ctrl+v"


def resolve_shortcut(configured: str) -> list[str]:
    """Resolves "auto" then splits; falls back on the default if nothing is readable."""
    configured = (configured or "").strip()
    if not configured or configured.lower() == "auto":
        configured = default_shortcut()
    return parse_shortcut(configured) or parse_shortcut(default_shortcut())


def split_shortcut(keys: Iterable[str]) -> tuple[list[str], str | None]:
    """Separates the modifiers from the final key."""
    modifiers = [key for key in keys if key in MODIFIERS]
    others = [key for key in keys if key not in MODIFIERS]
    return modifiers, others[-1] if others else None


class Keyboard:
    """The contract shared by the three ways of sending a shortcut."""

    name = "none"
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
    """Kernel virtual keyboard, created once and kept open as long as the daemon lives."""

    name = "uinput"
    hint = f"{UINPUT_DEVICE} must be writable (input group)"

    def __init__(self, name: str = "whisper-desk virtual keyboard"):
        self.device_name = name
        self._fd: int | None = None
        # prepare() opens the keyboard in one thread while the user speaks, and
        # write() uses it from another: the lock makes the second wait until the
        # settle delay is over, otherwise the first paste goes to a device the
        # compositor has not seen yet.
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return os.access(UINPUT_DEVICE, os.W_OK)

    def open(self) -> bool:
        with self._lock:
            if self._fd is not None:
                return True
            if not self.available:
                logger.warning("%s is not writable: insertion impossible.", UINPUT_DEVICE)
                return False
            try:
                fd = os.open(UINPUT_DEVICE, os.O_WRONLY | os.O_NONBLOCK)
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
                for code in DECLARED_KEYS:
                    fcntl.ioctl(fd, UI_SET_KEYBIT, code)
                # struct uinput_setup: input_id (bustype, vendor, product, version), name[80], ff_effects_max
                setup = struct.pack(
                    "<4H80sI", 0x03, 0x1D6B, 0x0001, 0x0001, self.device_name.encode()[:79], 0
                )
                fcntl.ioctl(fd, UI_DEV_SETUP, setup)
                fcntl.ioctl(fd, UI_DEV_CREATE)
            except OSError as error:
                logger.warning("Virtual keyboard unavailable: %s", error)
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
        # struct input_event: timeval (2 × native long), type, code, value.
        # Native sizes are mandatory: "<l" would be 4 bytes, the kernel expects 8.
        os.write(self._fd, struct.pack(EVENT_FORMAT, 0, 0, event_type, code, value))

    def _sync(self) -> None:
        self._emit(EV_SYN, SYN_REPORT, 0)

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        """Presses then releases a combination, e.g. ("ctrl", "v")."""
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
                logger.warning("Cannot send keys: %s", error)
                self.close()
                return False
        return True


# SendKeys: "^" Ctrl, "%" Alt, "+" Shift. No Windows key — it is reserved by the
# system, which is also why the global shortcut under WSL is taken on Ctrl+Alt.
SENDKEYS_MODIFIERS = {"ctrl": "^", "alt": "%", "shift": "+"}
SENDKEYS_KEYS = {"insert": "{INS}", "enter": "{ENTER}", "space": " ", "tab": "{TAB}"}


def sendkeys_sequence(keys: Iterable[str]) -> str | None:
    """Translates a canonical combination into a SendKeys sequence, or None if impossible."""
    modifiers, key = split_shortcut(keys)
    if key is None or "super" in modifiers:
        return None
    prefix = "".join(SENDKEYS_MODIFIERS[modifier] for modifier in modifiers)
    return prefix + SENDKEYS_KEYS.get(key, key)


class SendKeysKeyboard(Keyboard):
    """Keystrokes on the Windows side, for the windows dictated into from WSL."""

    name = "windows"
    hint = "Windows interoperability (powershell.exe) must be reachable from WSL"

    @property
    def available(self) -> bool:
        return host.has_windows_interop()

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        sequence = sendkeys_sequence(keys)
        if sequence is None:
            logger.warning(
                "Paste shortcut unusable under Windows (the Windows key cannot be "
                "simulated) — prefer 'ctrl+v'."
            )
            return False
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            f"[System.Windows.Forms.SendKeys]::SendWait({host.powershell_literal(sequence)})"
        )
        return host.run_powershell(script) is not None


# System Events names the modifiers, and designates by a code the keys that
# write nothing.
APPLESCRIPT_MODIFIERS = {
    "ctrl": "control down",
    "alt": "option down",
    "shift": "shift down",
    "super": "command down",
}
APPLESCRIPT_KEY_CODES = {"enter": 36, "tab": 48, "space": 49, "insert": 114}


def applescript_command(keys: Iterable[str]) -> str | None:
    """Translates a canonical combination into an AppleScript order, or None if impossible."""
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
    """Keystrokes through System Events — subject to accessibility permission."""

    name = "applescript"
    hint = (
        "System Settings → Privacy & Security → Accessibility: "
        "allow the terminal (or whisper-desk) to control the computer"
    )

    @property
    def available(self) -> bool:
        return bool(shutil.which("osascript"))

    def press(self, keys: Iterable[str], hold: float = 0.02) -> bool:
        script = applescript_command(keys)
        if script is None:
            logger.warning("Paste shortcut cannot be translated into AppleScript.")
            return False
        try:
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("osascript unavailable: %s", error)
            return False
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            logger.warning("Keystroke refused by macOS: %s — %s", message[:160], self.hint)
            return False
        return True


class NullKeyboard(Keyboard):
    """No keystroke at all: the text stays in the clipboard."""

    name = "none"
    hint = "insertion at the cursor is disabled"

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
    # The target windows are Windows ones; uinput only serves WSLg.
    host.WSL: ("windows", "uinput"),
    host.MACOS: ("applescript",),
}


def preferences() -> tuple[str, ...]:
    return PREFERENCES[host.name()]


def keyboard(preferred: str = "auto") -> Keyboard:
    """The virtual keyboard suited to the host, or the one the configuration asks for."""
    preferred = (preferred or "auto").strip().lower()
    if preferred not in ("", "auto"):
        backend = BACKENDS.get(preferred)
        if backend is None:
            logger.warning(
                "Unknown keyboard '%s' (known: %s) — choosing automatically.",
                preferred, ", ".join(sorted(BACKENDS)),
            )
        else:
            return backend()

    candidates = preferences()
    for candidate in candidates:
        instance = BACKENDS[candidate]()
        if instance.available:
            return instance
    # Nothing is ready: return the first choice, whose failure will say what to install.
    return BACKENDS[candidates[0]]()
