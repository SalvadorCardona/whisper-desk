"""Reconnaissance de l'hôte et échappement des chaînes PowerShell."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from . import context  # noqa: F401  (ajoute src/ au chemin d'import)
from .context import forced_host

from whisper_desk import host


class DetectionTest(unittest.TestCase):
    def test_les_trois_hotes_se_forcent(self):
        for name in (host.LINUX, host.WSL, host.MACOS):
            with forced_host(name):
                self.assertEqual(host.name(), name)

    def test_un_hote_inconnu_est_ignore(self):
        with forced_host("plan9"):
            self.assertIn(host.name(), (host.LINUX, host.WSL, host.MACOS))

    def test_les_predicats_s_excluent(self):
        with forced_host(host.MACOS):
            self.assertTrue(host.is_macos())
            self.assertFalse(host.is_linux())
            self.assertFalse(host.is_wsl())

    def test_darwin_est_macos(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WD_HOST", None)
            host.reset()
            with mock.patch.object(host.platform, "system", return_value="Darwin"):
                self.assertEqual(host.name(), host.MACOS)
        host.reset()

    def test_un_noyau_microsoft_est_wsl(self):
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False):
            os.environ.pop("WD_HOST", None)
            host.reset()
            with mock.patch.object(host.platform, "system", return_value="Linux"):
                self.assertEqual(host.name(), host.WSL)
        host.reset()

    def test_powershell_reste_hors_de_portee_ailleurs(self):
        for name in (host.LINUX, host.MACOS):
            with forced_host(name):
                self.assertIsNone(host.powershell())
                self.assertFalse(host.has_windows_interop())


class PowerShellLiteralTest(unittest.TestCase):
    def test_texte_simple(self):
        self.assertEqual(host.powershell_literal("ctrl+v"), "'ctrl+v'")

    def test_l_apostrophe_se_double(self):
        self.assertEqual(host.powershell_literal("l'été"), "'l''été'")

    def test_le_reste_ne_s_echappe_pas(self):
        """Entre apostrophes, PowerShell ne développe ni $ ni backslash."""
        self.assertEqual(host.powershell_literal('$env:X\\n"'), '\'$env:X\\n"\'')


if __name__ == "__main__":
    unittest.main()
