"""Mesure du niveau, découpage des trames, fin d'enregistrement."""

from __future__ import annotations

import array
import math
import unittest

from . import context  # noqa: F401  (ajoute src/ au chemin d'import)

from linux_whisper import recorder
from linux_whisper.recorder import (
    CHUNK_BYTES,
    MIN_SEGMENT_CHUNKS,
    Recorder,
    _rms,
    visual_level,
)


def tone(amplitude: int, samples: int = 1600) -> bytes:
    """Une sinusoïde s16le d'amplitude donnée."""
    values = array.array(
        "h", (int(amplitude * math.sin(index / 8.0)) for index in range(samples))
    )
    return values.tobytes()


def constant(value: int, samples: int = 1600) -> bytes:
    return array.array("h", [value] * samples).tobytes()


class RmsTest(unittest.TestCase):
    def test_silence_vaut_zero(self):
        self.assertEqual(_rms(constant(0)), 0.0)

    def test_buffer_vide(self):
        self.assertEqual(_rms(b""), 0.0)

    def test_octet_orphelin_ignore(self):
        """Une lecture tronquée ne doit pas faire exploser la mesure."""
        self.assertEqual(_rms(constant(1000) + b"\x00"), 1000.0)

    def test_signal_constant(self):
        self.assertAlmostEqual(_rms(constant(-1200)), 1200.0, places=6)

    def test_sinusoide_vaut_amplitude_sur_racine_de_deux(self):
        self.assertAlmostEqual(_rms(tone(10000)), 10000 / math.sqrt(2), delta=60)

    def test_croit_avec_le_volume(self):
        self.assertLess(_rms(tone(500)), _rms(tone(5000)))


class VisualLevelTest(unittest.TestCase):
    def test_sous_le_seuil_rien_ne_bouge(self):
        self.assertEqual(visual_level(100.0, 200.0), 0.0)
        self.assertEqual(visual_level(200.0, 200.0), 0.0)

    def test_zero_et_seuil_degenere(self):
        self.assertEqual(visual_level(0.0, 200.0), 0.0)
        self.assertEqual(visual_level(500.0, 0.0), 0.0)

    def test_borne_haute(self):
        self.assertEqual(visual_level(32767.0, 1.0), 1.0)

    def test_croissance_monotone(self):
        levels = [visual_level(level, 200.0) for level in (200, 400, 800, 1600, 3200)]
        self.assertEqual(levels, sorted(levels))

    def test_parole_ordinaire_occupe_le_milieu_de_la_course(self):
        """Une voix courante doit se voir : ni écrasée en bas, ni saturée."""
        self.assertTrue(0.25 < visual_level(2000.0, 200.0) < 0.95)


class SliceTest(unittest.TestCase):
    def frames(self, count: int) -> list[bytes]:
        return [constant(1000) for _ in range(count)]

    def test_trop_court_pour_etre_une_phrase(self):
        self.assertEqual(Recorder._slice(self.frames(MIN_SEGMENT_CHUNKS - 1), 0, 0.0), b"")

    def test_sans_queue_de_silence_tout_est_garde(self):
        segment = Recorder._slice(self.frames(20), 0, 0.0)
        self.assertEqual(len(segment), 20 * CHUNK_BYTES)

    def test_depart_decale(self):
        segment = Recorder._slice(self.frames(20), 15, 0.0)
        self.assertEqual(len(segment), 5 * CHUNK_BYTES)

    def test_queue_de_silence_rognee_avec_une_marge(self):
        # 2 s de silence annoncées, 0,3 s de marge gardée : 17 trames retirées.
        segment = Recorder._slice(self.frames(30), 0, 2.0)
        self.assertEqual(len(segment), 13 * CHUNK_BYTES)

    def test_marge_plus_courte_que_le_silence_ne_rogne_rien(self):
        segment = Recorder._slice(self.frames(20), 0, 0.2)
        self.assertEqual(len(segment), 20 * CHUNK_BYTES)


class FakeStdout:
    """Sert des trames préenregistrées, puis coupe le micro comme le ferait l'utilisateur."""

    def __init__(self, chunks: list[bytes], on_exhausted=None):
        self.chunks = list(chunks)
        self.on_exhausted = on_exhausted
        self.closed = False

    def read(self, _size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if not self.chunks and self.on_exhausted is not None:
            # L'utilisateur rappuie sur le raccourci pendant la dernière trame.
            self.on_exhausted()
            self.on_exhausted = None
        return chunk

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdout: FakeStdout):
        self.stdout = stdout
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.terminated = True


class RecordTest(unittest.TestCase):
    """L'arrêt manuel ne doit pas manger la fin de la dictée."""

    def config(self, **overrides):
        settings = {
            "device": "default",
            "max_seconds": 0,
            "streaming": True,
            "segment_silence_seconds": 5.0,
            "silence_seconds": 2.0,
            "start_timeout_seconds": 0,
            "threshold": 300,
        }
        settings.update(overrides)
        return {"recording": settings}

    def run_recorder(self, chunks: list[bytes], stop_at_end: bool, **overrides):
        segments: list[bytes] = []
        instance = Recorder(
            self.config(**overrides), on_segment=segments.append
        )
        stdout = FakeStdout(chunks, on_exhausted=instance.stop if stop_at_end else None)
        process = FakeProcess(stdout)
        original = recorder.subprocess.Popen
        recorder.subprocess.Popen = lambda *a, **k: process
        try:
            tail = instance.record()
        finally:
            recorder.subprocess.Popen = original
        return instance, tail, segments

    def test_arret_manuel_garde_toute_la_parole(self):
        instance, tail, segments = self.run_recorder([tone(9000)] * 20, stop_at_end=True)
        self.assertEqual(instance.reason, "stopped")
        self.assertEqual(segments, [])
        self.assertEqual(len(tail), 20 * CHUNK_BYTES)

    def test_fin_de_flux_garde_toute_la_parole(self):
        instance, tail, _ = self.run_recorder([tone(9000)] * 20, stop_at_end=False)
        self.assertEqual(instance.reason, "eof")
        self.assertEqual(len(tail), 20 * CHUNK_BYTES)

    def test_sans_parole_rien_n_est_renvoye(self):
        instance, tail, segments = self.run_recorder([constant(5)] * 20, stop_at_end=True)
        self.assertEqual(tail, b"")
        self.assertEqual(segments, [])
        self.assertLess(instance.peak, recorder.SILENT_INPUT_PEAK)

    def test_le_pic_distingue_le_micro_muet_du_silence(self):
        instance, _, _ = self.run_recorder([constant(400)] * 20, stop_at_end=True)
        self.assertGreater(instance.peak, recorder.SILENT_INPUT_PEAK)

    def test_les_niveaux_remontent_a_l_overlay(self):
        levels: list[float] = []
        instance = Recorder(self.config(), on_level=levels.append, on_segment=lambda _s: None)
        stdout = FakeStdout([tone(9000)] * 12, on_exhausted=instance.stop)
        original = recorder.subprocess.Popen
        recorder.subprocess.Popen = lambda *a, **k: FakeProcess(stdout)
        try:
            instance.record()
        finally:
            recorder.subprocess.Popen = original
        self.assertTrue(levels)
        self.assertTrue(all(0.0 <= level <= 1.0 for level in levels))
        self.assertGreater(max(levels), 0.0)


if __name__ == "__main__":
    unittest.main()
