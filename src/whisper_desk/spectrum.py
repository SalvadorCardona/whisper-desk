"""Voice levels for the overlay: overall volume, and energy per band.

An equalizer needs to know *where* the energy is, not just how much of it there
is: so each 100 ms slice is split into frequency bands, spread over octaves —
the ear hears in octaves, not in hertz.

numpy comes with the model (faster-whisper depends on it). Were it missing,
`bands` returns an empty list and the overlay falls back on overall volume alone.
"""

from __future__ import annotations

import math

try:
    import numpy
except ImportError:  # pragma: no cover - numpy comes with faster-whisper
    numpy = None  # type: ignore[assignment]

# Dynamic range shown by the overlay, from the speech threshold to a shout.
LEVEL_RANGE_DB = 36.0
# The useful voice range: the fundamental of a deep voice goes down to 80 Hz,
# fricatives reach a few kHz. Beyond that, the bar would stay dead.
LOW_HZ = 80.0
HIGH_HZ = 6000.0
# Highs carry far less energy than lows: without this progressive tilt, the
# right half of the equalizer would never move.
TILT_DB = 14.0
MIN_SAMPLES = 256


def visual_level(level: float, threshold: float, gain_db: float = 0.0) -> float:
    """RMS -> 0..1 for the overlay, in decibels above the speech threshold.

    The eye follows the ear: a linear scale crushes ordinary speech at the very
    bottom of the gauge and saturates on peaks. In decibels, silence stays at
    zero and the whole range serves what can actually be heard.
    """
    if level <= 0.0 or threshold <= 0.0:
        return 0.0
    decibels = 20.0 * math.log10(level / threshold) + gain_db
    return max(0.0, min(decibels / LEVEL_RANGE_DB, 1.0))


def band_edges(count: int, rate: int, size: int) -> list[int]:
    """Band boundaries, as FFT bin indexes, spread over octaves."""
    hz_per_bin = rate / size
    ratio = HIGH_HZ / LOW_HZ
    edges = [int(LOW_HZ * ratio ** (index / count) / hz_per_bin) for index in range(count + 1)]
    # Two bands cannot share the same bin: at the bottom of the spectrum, the
    # FFT resolution is too coarse for the logarithmic scale.
    for index in range(1, len(edges)):
        edges[index] = max(edges[index], edges[index - 1] + 1)
    return edges


def bands(chunk: bytes, count: int, rate: int, level: float, threshold: float) -> list[float]:
    """Energy per band of an s16le PCM buffer, each one mapped to 0..1."""
    if numpy is None or count <= 0 or level <= 0.0 or threshold <= 0.0:
        return []
    samples = numpy.frombuffer(chunk[: len(chunk) - len(chunk) % 2], dtype="<i2")
    if samples.size < MIN_SAMPLES:
        return []
    spectrum = numpy.abs(numpy.fft.rfft(samples * numpy.hanning(samples.size)))
    power = spectrum * spectrum
    total = float(power.sum())
    if total <= 0.0:
        return []

    edges = band_edges(count, rate, samples.size)
    values = []
    for index in range(count):
        share = float(power[edges[index] : edges[index + 1]].sum()) / total
        # Energy share brought back to the scale of the overall RMS: a band
        # carrying its share of a uniformly spread signal lands exactly on the
        # overall level, and its bar rises the way the VU meter would.
        band_rms = level * math.sqrt(share * count)
        values.append(visual_level(band_rms, threshold, TILT_DB * index / max(count - 1, 1)))
    return values
