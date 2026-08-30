"""Modes de sortie, journal d'historique, presse-papiers par hôte."""

from __future__ import annotations

import codecs
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import context  # noqa: F401
from .context import forced_host

from linux_whisper import config as config_module
from linux_whisper import host
from linux_whisper import output
from linux_whisper.inject import parse_shortcut


def with_mode(mode: str) -> dict:
    return {"output": {"mode": mode}}


class ModesTest(unittest.TestCase):
    def test_mode_simple(self):
        self.assertEqual(output.modes(with_mode("cursor")), {"cursor"})

    def test_modes_combines(self):
        self.assertEqual(output.modes(with_mode("cursor+stdout")), {"cursor", "stdout"})

    def test_espaces_ignorees(self):
        self.assertEqual(output.modes(with_mode(" cursor + stdout ")), {"cursor", "stdout"})

    def test_type_reste_un_synonyme_de_cursor(self):
        self.assertEqual(output.modes(with_mode("type")), {"cursor"})
        self.assertEqual(output.modes(with_mode("type+clipboard")), {"cursor", "clipboard"})

    def test_mode_vide(self):
        self.assertEqual(output.modes(with_mode("")), set())

    def test_le_defaut_du_projet_insere_au_curseur(self):
        self.assertIn("cursor", output.modes(config_module.load(Path("/inexistant"))))


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = config_module.STATE_DIR
        config_module.STATE_DIR = Path(self.directory.name) / "state"
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(setattr, config_module, "STATE_DIR", self.previous)

    def lines(self) -> list[str]:
        return (config_module.STATE_DIR / "history.log").read_text(
            encoding="utf-8"
        ).splitlines()

    def test_une_ligne_par_transcription(self):
        output.log_history("bonjour")
        output.log_history("au revoir")
        self.assertEqual([line.split("\t", 1)[1] for line in self.lines()],
                         ["bonjour", "au revoir"])

    def test_l_espace_de_liaison_ne_survit_pas_au_journal(self):
        """Les phrases suivantes arrivent en « " suite" » pour l'insertion."""
        output.log_history(" suite de la phrase")
        self.assertEqual(self.lines()[0].split("\t", 1)[1], "suite de la phrase")

    def test_rien_a_journaliser(self):
        output.log_history("   ")
        self.assertFalse((config_module.STATE_DIR / "history.log").exists())

    def test_horodatage_present(self):
        output.log_history("test")
        stamp, text = self.lines()[0].split("\t", 1)
        self.assertEqual(text, "test")
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class ShortcutTest(unittest.TestCase):
    def test_collage_par_defaut(self):
        self.assertEqual(parse_shortcut("ctrl+v"), ["ctrl", "v"])

    def test_variante_terminal(self):
        self.assertEqual(parse_shortcut("shift+insert"), ["shift", "insert"])

    def test_casse_et_espaces(self):
        self.assertEqual(parse_shortcut(" Ctrl + V "), ["ctrl", "v"])

    def test_touches_inconnues_ecartees(self):
        self.assertEqual(parse_shortcut("hyper+ctrl+v"), ["ctrl", "v"])

    def test_raccourci_vide(self):
        self.assertEqual(parse_shortcut(""), [])
        self.assertEqual(parse_shortcut("++"), [])


class ClipboardTest(unittest.TestCase):
    """Le presse-papiers passe par l'outil de l'hôte, sans jamais tout tenter."""

    def copy_with(self, host_name: str, present: tuple[str, ...], text: str = "l'été"):
        calls: list[tuple[list[str], bytes | None]] = []
        with forced_host(host_name), \
                mock.patch.object(
                    output.shutil, "which",
                    lambda name: f"/usr/bin/{name}" if name in present else None), \
                mock.patch.object(
                    output, "_run",
                    lambda command, data=None: calls.append((command, data)) or True):
            copied = output.Clipboard().set(text)
        return copied, calls

    def test_wayland_avant_x11(self):
        _, calls = self.copy_with(host.LINUX, ("wl-copy", "xclip"))
        self.assertEqual(len(calls), 1)
        self.assertIn("wl-copy", calls[0][0][0])

    def test_x11_quand_wayland_manque(self):
        _, calls = self.copy_with(host.LINUX, ("xclip",))
        self.assertIn("xclip", calls[0][0][0])
        self.assertEqual(calls[0][1], "l'été".encode())

    def test_macos_utilise_pbcopy(self):
        _, calls = self.copy_with(host.MACOS, ("pbcopy", "wl-copy"))
        self.assertIn("pbcopy", calls[0][0][0])

    def test_wsl_passe_par_windows_avant_les_outils_linux(self):
        _, calls = self.copy_with(host.WSL, ("clip.exe", "wl-copy"))
        self.assertIn("clip.exe", calls[0][0][0])

    def test_clip_exe_recoit_de_l_utf16_avec_sa_marque(self):
        """Sans marque d'ordre, clip.exe lit l'UTF-8 comme du texte natif : accents perdus."""
        _, calls = self.copy_with(host.WSL, ("clip.exe",))
        data = calls[0][1]
        self.assertTrue(data.startswith(codecs.BOM_UTF16_LE))
        self.assertEqual(data[len(codecs.BOM_UTF16_LE):].decode("utf-16-le"), "l'été")

    def test_l_overlay_prend_le_relais(self):
        overlay = mock.Mock()
        overlay.copy.return_value = True
        with forced_host(host.LINUX), \
                mock.patch.object(output.shutil, "which", lambda name: None):
            self.assertTrue(output.Clipboard(overlay).set("bonjour"))
        overlay.copy.assert_called_once_with("bonjour")

    def test_sauvegarde_puis_restitution(self):
        with forced_host(host.MACOS), \
                mock.patch.dict(output.GETTERS, {host.MACOS: (lambda: "avant",)}), \
                mock.patch.object(output.Clipboard, "set") as setter:
            clipboard = output.Clipboard()
            clipboard.save()
            clipboard.save()          # deux dictées d'affilée ne doivent pas écraser
            clipboard.restore()
        setter.assert_called_once_with("avant")

    def test_l_outil_annonce_par_le_diagnostic(self):
        with forced_host(host.MACOS), \
                mock.patch.object(
                    output.shutil, "which", lambda name: "/bin/pbcopy" if name == "pbcopy" else None):
            self.assertEqual(output.clipboard_tool(), "pbcopy")
        with forced_host(host.LINUX), mock.patch.object(output.shutil, "which", lambda name: None):
            self.assertIsNone(output.clipboard_tool())

    def test_chaque_hote_a_lecteurs_et_ecrivains(self):
        for name in (host.LINUX, host.WSL, host.MACOS):
            self.assertTrue(output.SETTERS[name])
            self.assertTrue(output.GETTERS[name])
            self.assertTrue(output.CLIPBOARD_TOOLS[name])


class AppleScriptStringTest(unittest.TestCase):
    def test_guillemets_et_backslash(self):
        self.assertEqual(output._applescript_string('a"b\\c'), '"a\\"b\\\\c"')


if __name__ == "__main__":
    unittest.main()
