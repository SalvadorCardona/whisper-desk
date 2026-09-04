"""Level measurement, frame slicing, end of recording."""

from __future__ import annotations

import array
import contextlib
import math
import unittest
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import capture, recorder, spectrum
from whisper_desk.recorder import (
    CHUNK_BYTES,
    MIN_SEGMENT_CHUNKS,
    Recorder,
    _rms,
    visual_level,
)


def tone(amplitude: int, samples: int = 1600) -> bytes:
    """An s16le sine wave of the given amplitude."""
    values = array.array(
        "h", (int(amplitude * math.sin(index / 8.0)) for index in range(samples))
    )
    return values.tobytes()


def constant(value: int, samples: int = 1600) -> bytes:
    return array.array("h", [value] * samples).tobytes()


class RmsTest(unittest.TestCase):
    def test_silence_is_zero(self):
        self.assertEqual(_rms(constant(0)), 0.0)

    def test_empty_buffer(self):
        self.assertEqual(_rms(b""), 0.0)

    def test_an_orphan_byte_is_ignored(self):
        """A truncated read must not blow the measurement up."""
        self.assertEqual(_rms(constant(1000) + b"\x00"), 1000.0)

    def test_constant_signal(self):
        self.assertAlmostEqual(_rms(constant(-1200)), 1200.0, places=6)

    def test_a_sine_is_amplitude_over_root_two(self):
        self.assertAlmostEqual(_rms(tone(10000)), 10000 / math.sqrt(2), delta=60)

    def test_grows_with_the_volume(self):
        self.assertLess(_rms(tone(500)), _rms(tone(5000)))


class VisualLevelTest(unittest.TestCase):
    def test_below_the_threshold_nothing_moves(self):
        self.assertEqual(visual_level(100.0, 200.0), 0.0)
        self.assertEqual(visual_level(200.0, 200.0), 0.0)

    def test_zero_and_degenerate_threshold(self):
        self.assertEqual(visual_level(0.0, 200.0), 0.0)
        self.assertEqual(visual_level(500.0, 0.0), 0.0)

    def test_upper_bound(self):
        self.assertEqual(visual_level(32767.0, 1.0), 1.0)

    def test_monotonic_growth(self):
        levels = [visual_level(level, 200.0) for level in (200, 400, 800, 1600, 3200)]
        self.assertEqual(levels, sorted(levels))

    def test_ordinary_speech_sits_in_the_middle_of_the_range(self):
        """A common voice must be visible: neither crushed at the bottom nor saturated."""
        self.assertTrue(0.25 < visual_level(2000.0, 200.0) < 0.95)


class SliceTest(unittest.TestCase):
    def frames(self, count: int) -> list[bytes]:
        return [constant(1000) for _ in range(count)]

    def test_too_short_to_be_a_sentence(self):
        self.assertEqual(Recorder._slice(self.frames(MIN_SEGMENT_CHUNKS - 1), 0, 0.0), b"")

    def test_without_trailing_silence_everything_is_kept(self):
        segment = Recorder._slice(self.frames(20), 0, 0.0)
        self.assertEqual(len(segment), 20 * CHUNK_BYTES)

    def test_offset_start(self):
        segment = Recorder._slice(self.frames(20), 15, 0.0)
        self.assertEqual(len(segment), 5 * CHUNK_BYTES)

    def test_trailing_silence_trimmed_with_a_margin(self):
        # 2 s of silence announced, 0.3 s of margin kept: 17 frames removed.
        segment = Recorder._slice(self.frames(30), 0, 2.0)
        self.assertEqual(len(segment), 13 * CHUNK_BYTES)

    def test_a_margin_shorter_than_the_silence_trims_nothing(self):
        segment = Recorder._slice(self.frames(20), 0, 0.2)
        self.assertEqual(len(segment), 20 * CHUNK_BYTES)


class FakeStdout:
    """Serves prerecorded frames, then cuts the microphone as the user would."""

    def __init__(self, chunks: list[bytes], on_exhausted=None):
        self.chunks = list(chunks)
        self.on_exhausted = on_exhausted
        self.closed = False

    def read(self, _size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if not self.chunks and self.on_exhausted is not None:
            # The user presses the shortcut again during the last frame.
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


@contextlib.contextmanager
def fake_capture(process: "FakeProcess"):
    """Replaces the capture tool by a stream played back from memory.

    The command built is not the subject here (test_capture covers that):
    short-circuiting it avoids requiring arecord on the test machine.
    """
    with mock.patch.object(recorder.subprocess, "Popen", lambda *a, **k: process), \
            mock.patch.object(
                recorder.capture, "build",
                lambda *a, **k: capture.Capture("fake", ["fake"]),
            ):
        yield


class RecordTest(unittest.TestCase):
    """A manual stop must not eat the end of the dictation."""

    def config(self, **overrides):
        settings = {
            "device": "default",
            "max_seconds": 0,
            "streaming": True,
            "segment_silence_seconds": 5.0,
            "silence_seconds": 2.0,
            "start_timeout_seconds": 0,
            "threshold": 300,
            "backend": "auto",
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
        with fake_capture(process):
            tail = instance.record()
        return instance, tail, segments

    def test_a_manual_stop_keeps_all_the_speech(self):
        instance, tail, segments = self.run_recorder([tone(9000)] * 20, stop_at_end=True)
        self.assertEqual(instance.reason, "stopped")
        self.assertEqual(segments, [])
        self.assertEqual(len(tail), 20 * CHUNK_BYTES)

    def test_the_end_of_the_stream_keeps_all_the_speech(self):
        instance, tail, _ = self.run_recorder([tone(9000)] * 20, stop_at_end=False)
        self.assertEqual(instance.reason, "eof")
        self.assertEqual(len(tail), 20 * CHUNK_BYTES)

    def test_without_speech_nothing_is_returned(self):
        instance, tail, segments = self.run_recorder([constant(5)] * 20, stop_at_end=True)
        self.assertEqual(tail, b"")
        self.assertEqual(segments, [])
        self.assertLess(instance.peak, recorder.SILENT_INPUT_PEAK)

    def test_the_peak_tells_a_mute_microphone_from_silence(self):
        instance, _, _ = self.run_recorder([constant(400)] * 20, stop_at_end=True)
        self.assertGreater(instance.peak, recorder.SILENT_INPUT_PEAK)

    def listen(self, bands: int):
        """Records twelve frames of voice and returns what the overlay saw."""
        measures: list[tuple[float, list[float]]] = []
        instance = Recorder(
            self.config(),
            on_level=lambda level, spectrum: measures.append((level, spectrum)),
            on_segment=lambda _s: None,
            bands=bands,
        )
        stdout = FakeStdout([tone(9000)] * 12, on_exhausted=instance.stop)
        with fake_capture(FakeProcess(stdout)):
            instance.record()
        return measures

    def test_the_levels_reach_the_overlay(self):
        levels = [level for level, _bands in self.listen(bands=0)]
        self.assertTrue(levels)
        self.assertTrue(all(0.0 <= level <= 1.0 for level in levels))
        self.assertGreater(max(levels), 0.0)

    def test_without_an_equalizer_no_band_is_computed(self):
        self.assertTrue(all(not bands for _level, bands in self.listen(bands=0)))

    @unittest.skipUnless(spectrum.numpy is not None, "numpy missing")
    def test_the_equalizer_gets_one_value_per_bar(self):
        spectra = [bands for _level, bands in self.listen(bands=12) if bands]
        self.assertTrue(spectra)
        self.assertTrue(all(len(bands) == 12 for bands in spectra))
        self.assertTrue(all(0.0 <= value <= 1.0 for bands in spectra for value in bands))


if __name__ == "__main__":
    unittest.main()
