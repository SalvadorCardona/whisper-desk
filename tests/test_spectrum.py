"""Splitting sound into bands: the equalizer must show where the voice sits."""

from __future__ import annotations

import array
import math
import unittest
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import spectrum
from whisper_desk.spectrum import band_edges, bands, visual_level

# The suite must run on the standard library alone, as it does in CI: without
# numpy, `bands` returns an empty list and there is no spectrum left to measure.
requires_numpy = unittest.skipUnless(spectrum.numpy is not None, "numpy missing")

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
    def test_the_edges_are_increasing(self):
        edges = band_edges(15, RATE, SAMPLES)
        self.assertEqual(len(edges), 16)
        self.assertTrue(all(b > a for a, b in zip(edges, edges[1:])))

    def test_the_bands_widen_towards_the_highs(self):
        """Octave scale: the last band covers more than the first."""
        edges = band_edges(12, RATE, SAMPLES)
        self.assertGreater(edges[-1] - edges[-2], edges[1] - edges[0])


class BandsTest(unittest.TestCase):
    @requires_numpy
    def test_a_low_sound_lights_up_the_left(self):
        self.assertLess(peak_band(sine(160)), 4)

    @requires_numpy
    def test_a_high_sound_lights_up_the_right(self):
        self.assertGreater(peak_band(sine(4000)), 7)

    @requires_numpy
    def test_lows_and_highs_do_not_land_in_the_same_band(self):
        self.assertLess(peak_band(sine(160)), peak_band(sine(4000)))

    @requires_numpy
    def test_every_value_stays_within_the_gauge(self):
        values = bands(sine(300, amplitude=32000), 15, RATE, 22000.0, 200.0)
        self.assertEqual(len(values), 15)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))

    def test_silence_gives_nothing(self):
        self.assertEqual(bands(sine(300), 12, RATE, 0.0, 200.0), [])
        self.assertEqual(bands(b"\x00" * 3200, 12, RATE, 100.0, 200.0), [])

    def test_without_bars_nothing_is_computed(self):
        self.assertEqual(bands(sine(300), 0, RATE, 5600.0, 200.0), [])

    def test_a_frame_that_is_too_short_is_ignored(self):
        """A truncated read is not worth an FFT: better to say nothing."""
        self.assertEqual(bands(sine(300, samples=64), 12, RATE, 5600.0, 200.0), [])

    def test_without_numpy_the_overlay_falls_back_on_the_volume(self):
        with mock.patch.object(spectrum, "numpy", None):
            self.assertEqual(bands(sine(300), 12, RATE, 5600.0, 200.0), [])


class VisualLevelGainTest(unittest.TestCase):
    def test_the_high_frequency_tilt_raises_the_bar(self):
        self.assertGreater(
            visual_level(400.0, 200.0, gain_db=12.0), visual_level(400.0, 200.0)
        )

    def test_the_tilt_does_not_wake_silence_up(self):
        self.assertEqual(visual_level(0.0, 200.0, gain_db=12.0), 0.0)


if __name__ == "__main__":
    unittest.main()
