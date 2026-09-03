"""Niveaux de voix pour l'overlay : le volume global, et l'énergie par bande.

Un equalizer a besoin de savoir *où* se trouve l'énergie, pas seulement combien
il y en a : on découpe donc chaque tranche de 100 ms en bandes de fréquence,
réparties en octaves — l'oreille entend en octaves, pas en hertz.

numpy arrive avec le modèle (faster-whisper en dépend). S'il manquait, `bands`
rend une liste vide et l'overlay se rabat sur le seul volume global.
"""

from __future__ import annotations

import math

try:
    import numpy
except ImportError:  # pragma: no cover - numpy vient avec faster-whisper
    numpy = None  # type: ignore[assignment]

# Dynamique affichée par l'overlay, du seuil de parole au cri.
LEVEL_RANGE_DB = 36.0
# La voix utile : le fondamental d'une voix grave part vers 80 Hz, les
# fricatives portent jusqu'à quelques kHz. Au-delà, la barre resterait morte.
LOW_HZ = 80.0
HIGH_HZ = 6000.0
# Les aigus portent bien moins d'énergie que les graves : sans ce relèvement
# progressif, la moitié droite de l'equalizer ne bougerait jamais.
TILT_DB = 14.0
MIN_SAMPLES = 256


def visual_level(level: float, threshold: float, gain_db: float = 0.0) -> float:
    """RMS -> 0..1 pour l'overlay, en décibels au-dessus du seuil de parole.

    L'œil suit l'oreille : une échelle linéaire écrase la parole ordinaire tout
    en bas de la jauge et sature sur les pics. En décibels, le silence reste à
    zéro et toute la course sert à ce qui s'entend vraiment.
    """
    if level <= 0.0 or threshold <= 0.0:
        return 0.0
    decibels = 20.0 * math.log10(level / threshold) + gain_db
    return max(0.0, min(decibels / LEVEL_RANGE_DB, 1.0))


def band_edges(count: int, rate: int, size: int) -> list[int]:
    """Bornes des bandes, en indices de bins FFT, réparties en octaves."""
    hz_per_bin = rate / size
    ratio = HIGH_HZ / LOW_HZ
    edges = [int(LOW_HZ * ratio ** (index / count) / hz_per_bin) for index in range(count + 1)]
    # Deux bandes ne peuvent pas partager le même bin : en bas du spectre, la
    # résolution de la FFT est trop grossière pour l'échelle logarithmique.
    for index in range(1, len(edges)):
        edges[index] = max(edges[index], edges[index - 1] + 1)
    return edges


def bands(chunk: bytes, count: int, rate: int, level: float, threshold: float) -> list[float]:
    """Énergie par bande d'un buffer PCM s16le, chacune ramenée en 0..1."""
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
        # Part d'énergie ramenée à l'échelle du RMS global : une bande qui porte
        # sa part d'un signal réparti uniformément retrouve exactement le niveau
        # global, et sa barre monte comme le ferait le VU-mètre.
        band_rms = level * math.sqrt(share * count)
        values.append(visual_level(band_rms, threshold, TILT_DB * index / max(count - 1, 1)))
    return values
