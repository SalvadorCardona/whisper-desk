"""Raccourci global : syntaxe des combinaisons, et traduction pour chaque hôte."""

from __future__ import annotations

import unittest

from . import context  # noqa: F401
from .context import forced_host

from whisper_desk import host, hotkey


class ParseTest(unittest.TestCase):
    def test_syntaxe_gtk(self):
        self.assertEqual(hotkey.parse_binding("<Super>j"), (["super"], "j"))

    def test_plusieurs_modificateurs(self):
        self.assertEqual(hotkey.parse_binding("<Ctrl><Alt>j"), (["ctrl", "alt"], "j"))

    def test_syntaxe_a_plus(self):
        self.assertEqual(hotkey.parse_binding("ctrl+alt+j"), (["ctrl", "alt"], "j"))

    def test_synonymes(self):
        self.assertEqual(hotkey.parse_binding("cmd+j"), (["super"], "j"))
        self.assertEqual(hotkey.parse_binding("<Primary><Option>j"), (["ctrl", "alt"], "j"))

    def test_touche_nommee(self):
        self.assertEqual(hotkey.parse_binding("<Ctrl><Alt>space"), (["ctrl", "alt"], "space"))

    def test_l_ordre_des_modificateurs_est_normalise(self):
        self.assertEqual(
            hotkey.parse_binding("<Alt><Ctrl>j"), hotkey.parse_binding("<Ctrl><Alt>j")
        )

    def test_aller_retour_gtk(self):
        self.assertEqual(hotkey.format_gtk(*hotkey.parse_binding("<Ctrl><Alt>j")), "<Ctrl><Alt>j")


class DefaultBindingTest(unittest.TestCase):
    def test_wsl_evite_la_touche_windows(self):
        with forced_host(host.WSL):
            self.assertEqual(hotkey.default_binding(), "<Ctrl><Alt>j")

    def test_ailleurs_c_est_super(self):
        for name in (host.LINUX, host.MACOS):
            with forced_host(name):
                self.assertEqual(hotkey.default_binding(), "<Super>j")

    def test_auto_se_resout(self):
        with forced_host(host.LINUX):
            self.assertEqual(hotkey.resolve_binding({"hotkey": {"binding": "auto"}}), "<Super>j")

    def test_un_raccourci_explicite_est_respecte(self):
        with forced_host(host.WSL):
            self.assertEqual(
                hotkey.resolve_binding({"hotkey": {"binding": "<Super><Shift>d"}}),
                "<Super><Shift>d",
            )


class WindowsFormatTest(unittest.TestCase):
    def test_combinaison_acceptee(self):
        self.assertEqual(hotkey.format_windows(["ctrl", "alt"], "j"), "CTRL+ALT+J")

    def test_ctrl_maj_aussi(self):
        self.assertEqual(hotkey.format_windows(["ctrl", "shift"], "k"), "CTRL+SHIFT+K")

    def test_touche_nommee(self):
        self.assertEqual(hotkey.format_windows(["ctrl", "alt"], "space"), "CTRL+ALT+SPACE")

    def test_la_touche_windows_est_refusee(self):
        with self.assertRaises(hotkey.UnsupportedDesktop) as raised:
            hotkey.format_windows(["super"], "j")
        self.assertIn("Ctrl+Alt", str(raised.exception))

    def test_ctrl_seul_est_refuse(self):
        with self.assertRaises(hotkey.UnsupportedDesktop):
            hotkey.format_windows(["ctrl"], "j")

    def test_sans_touche_finale(self):
        with self.assertRaises(hotkey.UnsupportedDesktop):
            hotkey.format_windows(["ctrl", "alt"], "")


class SkhdFormatTest(unittest.TestCase):
    def test_commande_seule(self):
        self.assertEqual(hotkey.format_skhd(["super"], "j"), "cmd - j")

    def test_plusieurs_modificateurs(self):
        self.assertEqual(hotkey.format_skhd(["ctrl", "alt"], "j"), "ctrl + alt - j")

    def test_sans_modificateur(self):
        self.assertEqual(hotkey.format_skhd([], "f13"), "f13")

    def test_sans_touche_finale(self):
        with self.assertRaises(hotkey.UnsupportedDesktop):
            hotkey.format_skhd(["super"], "")


class BackendTest(unittest.TestCase):
    def test_chaque_hote_a_son_greffon(self):
        attendus = {host.LINUX: "GNOME", host.WSL: "Windows", host.MACOS: "skhd"}
        for name, expected in attendus.items():
            with forced_host(name):
                self.assertEqual(hotkey.backend().name, expected)

    def test_hors_wsl_le_greffon_windows_refuse(self):
        with forced_host(host.LINUX):
            with self.assertRaises(hotkey.UnsupportedDesktop):
                hotkey.WindowsHotkey().check()


if __name__ == "__main__":
    unittest.main()
