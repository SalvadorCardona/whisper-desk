"""Raccourci de collage : lecture, résolution par hôte, traduction par backend."""

from __future__ import annotations

import unittest
from unittest import mock

from . import context  # noqa: F401
from .context import forced_host

from whisper_desk import host, inject


class DefaultShortcutTest(unittest.TestCase):
    def test_macos_colle_avec_commande(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.default_shortcut(), "super+v")

    def test_ailleurs_c_est_ctrl(self):
        for name in (host.LINUX, host.WSL):
            with forced_host(name):
                self.assertEqual(inject.default_shortcut(), "ctrl+v")

    def test_auto_se_resout_selon_l_hote(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.resolve_shortcut("auto"), ["super", "v"])
        with forced_host(host.LINUX):
            self.assertEqual(inject.resolve_shortcut("auto"), ["ctrl", "v"])

    def test_un_raccourci_explicite_est_respecte(self):
        with forced_host(host.MACOS):
            self.assertEqual(inject.resolve_shortcut("shift+insert"), ["shift", "insert"])

    def test_un_raccourci_illisible_retombe_sur_le_defaut(self):
        with forced_host(host.LINUX):
            self.assertEqual(inject.resolve_shortcut("hyper+truc"), ["ctrl", "v"])


class ParseTest(unittest.TestCase):
    def test_les_synonymes_se_ramenent_a_une_touche(self):
        self.assertEqual(inject.parse_shortcut("cmd+v"), ["super", "v"])
        self.assertEqual(inject.parse_shortcut("command+v"), ["super", "v"])
        self.assertEqual(inject.parse_shortcut("control+v"), ["ctrl", "v"])
        self.assertEqual(inject.parse_shortcut("option+v"), ["alt", "v"])

    def test_les_doublons_disparaissent(self):
        self.assertEqual(inject.parse_shortcut("ctrl+control+v"), ["ctrl", "v"])

    def test_separation_des_modificateurs(self):
        self.assertEqual(
            inject.split_shortcut(["ctrl", "shift", "insert"]), (["ctrl", "shift"], "insert")
        )
        self.assertEqual(inject.split_shortcut(["ctrl"]), (["ctrl"], None))


class SendKeysTest(unittest.TestCase):
    def test_collage_courant(self):
        self.assertEqual(inject.sendkeys_sequence(["ctrl", "v"]), "^v")

    def test_touche_nommee(self):
        self.assertEqual(inject.sendkeys_sequence(["shift", "insert"]), "+{INS}")

    def test_plusieurs_modificateurs(self):
        self.assertEqual(inject.sendkeys_sequence(["ctrl", "shift", "v"]), "^+v")

    def test_la_touche_windows_n_est_pas_simulable(self):
        self.assertIsNone(inject.sendkeys_sequence(["super", "v"]))

    def test_sans_touche_finale(self):
        self.assertIsNone(inject.sendkeys_sequence(["ctrl"]))


class AppleScriptTest(unittest.TestCase):
    def test_collage_courant(self):
        self.assertEqual(
            inject.applescript_command(["super", "v"]),
            'tell application "System Events" to keystroke "v" using {command down}',
        )

    def test_touche_sans_caractere_passe_par_son_code(self):
        self.assertIn("key code 36", inject.applescript_command(["enter"]))

    def test_sans_modificateur(self):
        self.assertNotIn("using", inject.applescript_command(["v"]))

    def test_sans_touche_finale(self):
        self.assertIsNone(inject.applescript_command(["ctrl"]))


class BackendChoiceTest(unittest.TestCase):
    def test_chaque_hote_a_son_clavier(self):
        attendus = {host.LINUX: "uinput", host.WSL: "windows", host.MACOS: "applescript"}
        for name, expected in attendus.items():
            with forced_host(name):
                self.assertEqual(inject.preferences()[0], expected)

    def test_le_choix_explicite_prime(self):
        with forced_host(host.LINUX):
            self.assertEqual(inject.keyboard("none").name, "none")

    def test_un_clavier_inconnu_retombe_sur_l_automatique(self):
        with forced_host(host.MACOS), self.assertLogs(inject.logger, "WARNING"):
            self.assertEqual(inject.keyboard("clavier-magique").name, "applescript")

    def test_wsl_se_rabat_sur_uinput_si_windows_est_hors_jeu(self):
        with forced_host(host.WSL), \
                mock.patch.object(inject.SendKeysKeyboard, "available", False), \
                mock.patch.object(inject.UinputKeyboard, "available", True):
            self.assertEqual(inject.keyboard().name, "uinput")

    def test_sans_rien_de_disponible_on_rend_le_premier_choix(self):
        """Son message d'aide dira quoi installer."""
        with forced_host(host.WSL), \
                mock.patch.object(inject.SendKeysKeyboard, "available", False), \
                mock.patch.object(inject.UinputKeyboard, "available", False):
            keyboard = inject.keyboard()
            self.assertEqual(keyboard.name, "windows")
            self.assertTrue(keyboard.hint)

    def test_le_clavier_muet_ne_frappe_rien(self):
        self.assertFalse(inject.NullKeyboard().press(["ctrl", "v"]))


if __name__ == "__main__":
    unittest.main()
