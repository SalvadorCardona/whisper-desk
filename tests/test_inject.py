"""Paste shortcut: parsing, per-host resolution, per-backend translation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import context  # noqa: F401
from .context import forced_host

from whisper_desk import host, inject


class DefaultShortcutTest(unittest.TestCase):
    def test_macos_pastes_with_command(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.default_shortcut(), "super+v")

    def test_linux_pastes_with_shift_insert(self):
        """Ctrl+V types ^V in a terminal; Shift+Insert pastes there too."""
        with forced_host(host.LINUX):
            self.assertEqual(inject.default_shortcut(), "shift+insert")

    def test_wsl_pastes_with_ctrl(self):
        with forced_host(host.WSL):
            self.assertEqual(inject.default_shortcut(), "ctrl+v")

    def test_auto_is_resolved_per_host(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.resolve_shortcut("auto"), ["super", "v"])
        with forced_host(host.LINUX):
            self.assertEqual(inject.resolve_shortcut("auto"), ["shift", "insert"])

    def test_an_explicit_shortcut_is_honoured(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.resolve_shortcut("shift+insert"), ["shift", "insert"])

    def test_an_unreadable_shortcut_falls_back_on_the_default(self):
        with forced_host(host.WSL):
            self.assertEqual(inject.resolve_shortcut("hyper+thing"), ["ctrl", "v"])


class ParseTest(unittest.TestCase):
    def test_synonyms_map_to_one_key(self):
        self.assertEqual(inject.parse_shortcut("cmd+v"), ["super", "v"])
        self.assertEqual(inject.parse_shortcut("command+v"), ["super", "v"])
        self.assertEqual(inject.parse_shortcut("control+v"), ["ctrl", "v"])
        self.assertEqual(inject.parse_shortcut("option+v"), ["alt", "v"])

    def test_duplicates_disappear(self):
        self.assertEqual(inject.parse_shortcut("ctrl+control+v"), ["ctrl", "v"])

    def test_separating_the_modifiers(self):
        self.assertEqual(
            inject.split_shortcut(["ctrl", "shift", "insert"]), (["ctrl", "shift"], "insert")
        )
        self.assertEqual(inject.split_shortcut(["ctrl"]), (["ctrl"], None))


class SendKeysTest(unittest.TestCase):
    def test_common_paste(self):
        self.assertEqual(inject.sendkeys_sequence(["ctrl", "v"]), "^v")

    def test_named_key(self):
        self.assertEqual(inject.sendkeys_sequence(["shift", "insert"]), "+{INS}")

    def test_several_modifiers(self):
        self.assertEqual(inject.sendkeys_sequence(["ctrl", "shift", "v"]), "^+v")

    def test_the_windows_key_cannot_be_simulated(self):
        self.assertIsNone(inject.sendkeys_sequence(["super", "v"]))

    def test_without_a_final_key(self):
        self.assertIsNone(inject.sendkeys_sequence(["ctrl"]))


class AppleScriptTest(unittest.TestCase):
    def test_common_paste(self):
        self.assertEqual(
            inject.applescript_command(["super", "v"]),
            'tell application "System Events" to keystroke "v" using {command down}',
        )

    def test_a_key_without_a_character_goes_through_its_code(self):
        self.assertIn("key code 36", inject.applescript_command(["enter"]))

    def test_without_a_modifier(self):
        self.assertNotIn("using", inject.applescript_command(["v"]))

    def test_without_a_final_key(self):
        self.assertIsNone(inject.applescript_command(["ctrl"]))


class BackendChoiceTest(unittest.TestCase):
    def test_each_host_has_its_keyboard(self):
        expectations = {host.LINUX: "uinput", host.WSL: "windows", host.MACOS: "applescript"}
        for name, expected in expectations.items():
            with forced_host(name):
                self.assertEqual(inject.preferences()[0], expected)

    def test_an_explicit_choice_wins(self):
        with forced_host(host.LINUX):
            self.assertEqual(inject.keyboard("none").name, "none")

    def test_an_unknown_keyboard_falls_back_on_automatic(self):
        with forced_host(host.MACOS), self.assertLogs(inject.logger, "WARNING"):
            self.assertEqual(inject.keyboard("magic-keyboard").name, "applescript")

    def test_wsl_falls_back_on_uinput_when_windows_is_out(self):
        with forced_host(host.WSL), \
                mock.patch.object(inject.SendKeysKeyboard, "available", False), \
                mock.patch.object(inject.UinputKeyboard, "available", True):
            self.assertEqual(inject.keyboard().name, "uinput")

    def test_with_nothing_available_the_first_choice_is_returned(self):
        """Its hint will say what to install."""
        with forced_host(host.WSL), \
                mock.patch.object(inject.SendKeysKeyboard, "available", False), \
                mock.patch.object(inject.UinputKeyboard, "available", False):
            keyboard = inject.keyboard()
            self.assertEqual(keyboard.name, "windows")
            self.assertTrue(keyboard.hint)

    def test_the_silent_keyboard_presses_nothing(self):
        self.assertFalse(inject.NullKeyboard().press(["ctrl", "v"]))

    def test_linux_falls_back_on_gnome_when_uinput_is_closed(self):
        """/dev/uinput belongs to root by default: GNOME's remote desktop takes over."""
        with forced_host(host.LINUX), \
                mock.patch.object(inject.UinputKeyboard, "available", False), \
                mock.patch.object(inject.MutterKeyboard, "available", True):
            self.assertEqual(inject.keyboard().name, "mutter")

    def test_uinput_stays_first_when_it_is_writable(self):
        with forced_host(host.LINUX), \
                mock.patch.object(inject.UinputKeyboard, "available", True), \
                mock.patch.object(inject.MutterKeyboard, "available", True):
            self.assertEqual(inject.keyboard().name, "uinput")


class MutterAvailabilityTest(unittest.TestCase):
    def available(self, desktop: str) -> bool:
        with mock.patch.dict(inject.os.environ, {"XDG_CURRENT_DESKTOP": desktop}), \
                mock.patch.object(inject, "gio_available", lambda: True):
            return inject.MutterKeyboard().available

    def test_gnome_and_its_flavours(self):
        self.assertTrue(self.available("GNOME"))
        self.assertTrue(self.available("ubuntu:GNOME"))

    def test_not_outside_gnome(self):
        self.assertFalse(self.available("KDE"))
        self.assertFalse(self.available(""))


# Stands in for mutter_keyboard.py: the same line protocol, without D-Bus.
FAKE_HELPER = """
import sys
mode = sys.argv[1]
if mode == "refuse":
    print("error No such interface", flush=True)
    raise SystemExit(1)
print("ready", flush=True)
for line in sys.stdin:
    with open(sys.argv[2], "a") as log:
        log.write(line)
    print("ok" if mode == "ready" else "error Session stopped", flush=True)
"""


class MutterKeyboardTest(unittest.TestCase):
    """The keyboard talks to its helper process line by line."""

    def keyboard(self, mode: str) -> inject.MutterKeyboard:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        helper = directory / "helper.py"
        helper.write_text(FAKE_HELPER)
        self.log = directory / "keys.log"
        self.enterContext(mock.patch.object(
            inject, "system_python", lambda: sys.executable))
        self.enterContext(mock.patch.object(inject, "MUTTER_HELPER", helper))
        self.enterContext(mock.patch.object(inject.MutterKeyboard, "available", True))
        keyboard = inject.MutterKeyboard()
        # The fake helper reads its mode and log path from its command line.
        original = inject.subprocess.Popen
        self.enterContext(mock.patch.object(
            inject.subprocess, "Popen",
            lambda command, **kwargs: original([*command, mode, str(self.log)], **kwargs)))
        self.addCleanup(keyboard.close)
        return keyboard

    def test_the_paste_is_sent_as_evdev_keycodes(self):
        keyboard = self.keyboard("ready")
        self.assertTrue(keyboard.press(["shift", "insert"]))
        self.assertTrue(keyboard.press(["ctrl", "v"]))
        keyboard.close()
        self.assertEqual(self.log.read_text().splitlines(), ["42 110", "29 47"])

    def test_a_refused_session_is_a_failure(self):
        keyboard = self.keyboard("refuse")
        with self.assertLogs(inject.logger, "WARNING") as logs:
            self.assertFalse(keyboard.press(["ctrl", "v"]))
        self.assertIn("No such interface", logs.output[0])

    def test_a_refused_keystroke_is_a_failure(self):
        keyboard = self.keyboard("stopped")
        with self.assertLogs(inject.logger, "WARNING"):
            self.assertFalse(keyboard.press(["ctrl", "v"]))


if __name__ == "__main__":
    unittest.main()
