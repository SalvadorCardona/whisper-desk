"""Découpage du son en bandes : l'equalizer doit montrer où passe la voix."""

from __future__ import annotations

import array
import math
import unittest
from unittest import mock

from . import context  # noqa: F401  (ajoute src/ au chemin d'import)

from linux_whisper import spectrum
from linux_whisper.spectrum import band_edges, bands, visual_level

RATE = 16000
SAMPLES = 1600


def sine(hertz: float, amplitude: int = 8000, samples: int = SAMPLES) -> bytes:
    values = array.array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * hertz * index / RATE))
            for index in range(samples)
        ),
    )
    return values.tobytes()


def peak_band(chunk: bytes, count: int = 12, level: float = 5600.0) -> int:
    return max(range(count), key=bands(chunk, count, RATE, level, 200.0).__getitem__)


class BandEdgesTest(unittest.TestCase):
    def test_les_bornes_sont_croissantes(self):
        edges = band_edges(15, RATE, SAMPLES)
        self.assertEqual(len(edges), 16)
        self.assertTrue(all(b > a for a, b in zip(edges, edges[1:])))

    def test_les_bandes_s_elargissent_vers_les_aigus(self):
        """Échelle en octaves : la dernière bande couvre plus que la première."""
        edges = band_edges(12, RATE, SAMPLES)
        self.assertGreater(edges[-1] - edges[-2], edges[1] - edges[0])


class BandsTest(unittest.TestCase):
    def test_un_son_grave_allume_la_gauche(self):
        self.assertLess(peak_band(sine(160)), 4)

    def test_un_son_aigu_allume_la_droite(self):
        self.assertGreater(peak_band(sine(4000)), 7)

    def test_le_grave_et_l_aigu_ne_tombent_pas_dans_la_meme_bande(self):
        self.assertLess(peak_band(sine(160)), peak_band(sine(4000)))

    def test_toutes_les_valeurs_restent_dans_la_jauge(self):
        values = bands(sine(300, amplitude=32000), 15, RATE, 22000.0, 200.0)
        self.assertEqual(len(values), 15)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))

    def test_le_silence_ne_donne_rien(self):
        self.assertEqual(bands(sine(300), 12, RATE, 0.0, 200.0), [])
        self.assertEqual(bands(b"\x00" * 3200, 12, RATE, 100.0, 200.0), [])

    def test_sans_barres_rien_n_est_calcule(self):
        self.assertEqual(bands(sine(300), 0, RATE, 5600.0, 200.0), [])

    def test_une_trame_trop_courte_est_ignoree(self):
        """Une lecture tronquée ne vaut pas une FFT : mieux vaut ne rien dire."""
        self.assertEqual(bands(sine(300, samples=64), 12, RATE, 5600.0, 200.0), [])

    def test_sans_numpy_l_overlay_se_rabat_sur_le_volume(self):
        with mock.patch.object(spectrum, "numpy", None):
            self.assertEqual(bands(sine(300), 12, RATE, 5600.0, 200.0), [])


class VisualLevelGainTest(unittest.TestCase):
    def test_le_relevement_des_aigus_remonte_la_barre(self):
        self.assertGreater(
            visual_level(400.0, 200.0, gain_db=12.0), visual_level(400.0, 200.0)
        )

    def test_le_relevement_ne_reveille_pas_le_silence(self):
        self.assertEqual(visual_level(0.0, 200.0, gain_db=12.0), 0.0)


if __name__ == "__main__":
    unittest.main()
