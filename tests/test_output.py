"""Modes de sortie, journal d'historique, raccourci de collage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import context  # noqa: F401

from linux_whisper import config as config_module
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


if __name__ == "__main__":
    unittest.main()
