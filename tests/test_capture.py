"""Choix de l'outil de capture et commandes construites, hôte par hôte."""

from __future__ import annotations

import unittest
from unittest import mock

from . import context  # noqa: F401
from .context import forced_host

from whisper_desk import capture, host


def only_installed(*names: str):
    """Fait comme si seuls ces outils étaient présents sur la machine."""
    return mock.patch.object(capture, "installed", lambda name: name in names)


class ChoiceTest(unittest.TestCase):
    def test_chaque_hote_a_son_premier_choix(self):
        attendus = {host.LINUX: "arecord", host.WSL: "parec", host.MACOS: "rec"}
        for name, expected in attendus.items():
            with forced_host(name):
                self.assertEqual(capture.recommended(), expected)

    def test_on_prend_le_premier_installe(self):
        with forced_host(host.LINUX), only_installed("ffmpeg", "parec"):
            self.assertEqual(capture.choose(), "parec")

    def test_le_choix_explicite_prime(self):
        with forced_host(host.LINUX), only_installed("arecord", "ffmpeg"):
            self.assertEqual(capture.choose("ffmpeg"), "ffmpeg")

    def test_le_choix_explicite_doit_etre_installe(self):
        with forced_host(host.LINUX), only_installed("arecord"):
            with self.assertRaises(capture.CaptureUnavailable):
                capture.choose("ffmpeg")

    def test_backend_inconnu(self):
        with forced_host(host.LINUX), only_installed("arecord"):
            with self.assertRaises(capture.CaptureUnavailable):
                capture.choose("mon-micro")

    def test_rien_d_installe_dit_quoi_installer(self):
        with forced_host(host.MACOS), only_installed():
            with self.assertRaises(capture.CaptureUnavailable) as raised:
                capture.choose()
            self.assertIn("sox", str(raised.exception))

    def test_wsl_prefere_pulseaudio(self):
        """WSLg ne transporte l'audio que par PulseAudio."""
        with forced_host(host.WSL), only_installed("arecord", "parec"):
            self.assertEqual(capture.choose(), "parec")


class CommandTest(unittest.TestCase):
    def build(self, backend: str, device: str = "default"):
        with only_installed(backend):
            return capture.build(device, 16000, 1, backend)

    def test_arecord(self):
        source = self.build("arecord")
        self.assertEqual(source.command[0], "arecord")
        self.assertIn("S16_LE", source.command)
        self.assertEqual(source.command[-1], "-")

    def test_arecord_prend_le_peripherique(self):
        self.assertIn("hw:1,0", self.build("arecord", "hw:1,0").command)

    def test_parec_sans_peripherique_par_defaut(self):
        source = self.build("parec")
        self.assertNotIn("-d", source.command)
        self.assertIn("--format=s16le", source.command)

    def test_parec_avec_peripherique(self):
        command = self.build("parec", "RDPSource").command
        self.assertEqual(command[command.index("-d") + 1], "RDPSource")

    def test_ffmpeg_utilise_avfoundation_sur_macos(self):
        with forced_host(host.MACOS):
            command = self.build("ffmpeg").command
            self.assertIn("avfoundation", command)
            self.assertEqual(command[command.index("-i") + 1], ":0")

    def test_ffmpeg_prend_l_index_du_peripherique(self):
        with forced_host(host.MACOS):
            command = self.build("ffmpeg", "2").command
            self.assertEqual(command[command.index("-i") + 1], ":2")

    def test_ffmpeg_utilise_pulse_ailleurs(self):
        with forced_host(host.LINUX):
            self.assertIn("pulse", self.build("ffmpeg").command)

    def test_sox_passe_le_peripherique_par_l_environnement(self):
        """rec ne prend pas de périphérique en argument : il lit AUDIODEV."""
        self.assertEqual(self.build("rec").env, {})
        self.assertEqual(self.build("rec", "Micro USB").env, {"AUDIODEV": "Micro USB"})

    def test_sox_lit_le_peripherique_audio(self):
        self.assertIn("-d", self.build("sox").command)

    def test_toutes_les_commandes_demandent_16_khz_mono(self):
        for backend in capture.BUILDERS:
            with self.subTest(backend=backend):
                joined = " ".join(self.build(backend).command)
                self.assertIn("16000", joined)

    def test_toutes_les_commandes_ecrivent_sur_la_sortie_standard(self):
        """« - » pour la plupart ; parec écrit sur stdout sans qu'on le demande."""
        for backend in capture.BUILDERS:
            with self.subTest(backend=backend):
                command = self.build(backend).command
                self.assertTrue(command[-1] == "-" or backend == "parec", command)

    def test_chaque_backend_a_son_paquet(self):
        self.assertEqual(set(capture.BUILDERS), set(capture.PACKAGES))

    def test_chaque_hote_ne_cite_que_des_backends_connus(self):
        for names in capture.PREFERENCES.values():
            self.assertLessEqual(set(names), set(capture.BUILDERS))


if __name__ == "__main__":
    unittest.main()
