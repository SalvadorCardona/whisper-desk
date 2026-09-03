"""Fusion de la configuration utilisateur avec les valeurs par défaut."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import context  # noqa: F401

from whisper_desk import config as config_module


class MergeTest(unittest.TestCase):
    def test_les_cles_absentes_gardent_le_defaut(self):
        merged = config_module._merge({"a": 1, "b": 2}, {"b": 3})
        self.assertEqual(merged, {"a": 1, "b": 3})

    def test_fusion_en_profondeur(self):
        merged = config_module._merge(
            {"model": {"name": "auto", "language": "fr"}}, {"model": {"language": "en"}}
        )
        self.assertEqual(merged, {"model": {"name": "auto", "language": "en"}})

    def test_le_defaut_n_est_pas_modifie(self):
        base = {"model": {"language": "fr"}}
        config_module._merge(base, {"model": {"language": "en"}})
        self.assertEqual(base, {"model": {"language": "fr"}})


class LoadTest(unittest.TestCase):
    def write(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_fichier_absent(self):
        config = config_module.load(Path("/inexistant/config.toml"))
        self.assertEqual(config, config_module.DEFAULTS)
        self.assertIsNot(config["model"], config_module.DEFAULTS["model"])

    def test_surcharge_partielle(self):
        config = config_module.load(self.write('[model]\nlanguage = "en"\n'))
        self.assertEqual(config["model"]["language"], "en")
        self.assertEqual(config["model"]["name"], config_module.DEFAULTS["model"]["name"])
        self.assertEqual(config["overlay"], config_module.DEFAULTS["overlay"])

    def test_toutes_les_sections_attendues_sont_la(self):
        config = config_module.load(Path("/inexistant"))
        self.assertEqual(
            set(config), {"hotkey", "model", "recording", "output", "overlay"}
        )

    def test_les_cles_lues_par_le_code_existent(self):
        """Le code indexe la config sans .get() : une clé manquante planterait."""
        config = config_module.load(Path("/inexistant"))
        attendues = {
            "recording": {
                "device", "backend", "max_seconds", "streaming",
                "segment_silence_seconds", "silence_seconds",
                "start_timeout_seconds", "threshold",
            },
            "output": {
                "mode", "paste_shortcut", "keyboard", "restore_clipboard",
                "notify", "history",
            },
            "overlay": {"enabled", "accent", "width", "height", "position", "margin"},
            "model": {
                "name", "device", "compute_type", "language", "beam_size",
                "initial_prompt", "preload",
            },
            "hotkey": {"binding", "name", "action"},
        }
        for section, keys in attendues.items():
            self.assertLessEqual(keys, set(config[section]), section)


if __name__ == "__main__":
    unittest.main()
