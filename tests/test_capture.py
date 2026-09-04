"""Choice of the capture tool and the commands built, host by host."""

from __future__ import annotations

import unittest
from unittest import mock

from . import context  # noqa: F401
from .context import forced_host

from whisper_desk import capture, host


def only_installed(*names: str):
    """Pretends that only these tools are present on the machine."""
    return mock.patch.object(capture, "installed", lambda name: name in names)


class ChoiceTest(unittest.TestCase):
    def test_each_host_has_its_first_choice(self):
        expectations = {host.LINUX: "arecord", host.WSL: "parec", host.MACOS: "rec"}
        for name, expected in expectations.items():
            with forced_host(name):
                self.assertEqual(capture.recommended(), expected)

    def test_the_first_installed_one_is_taken(self):
        with forced_host(host.LINUX), only_installed("ffmpeg", "parec"):
            self.assertEqual(capture.choose(), "parec")

    def test_an_explicit_choice_wins(self):
        with forced_host(host.LINUX), only_installed("arecord", "ffmpeg"):
            self.assertEqual(capture.choose("ffmpeg"), "ffmpeg")

    def test_an_explicit_choice_must_be_installed(self):
        with forced_host(host.LINUX), only_installed("arecord"):
            with self.assertRaises(capture.CaptureUnavailable):
                capture.choose("ffmpeg")

    def test_unknown_backend(self):
        with forced_host(host.LINUX), only_installed("arecord"):
            with self.assertRaises(capture.CaptureUnavailable):
                capture.choose("my-microphone")

    def test_nothing_installed_says_what_to_install(self):
        with forced_host(host.MACOS), only_installed():
            with self.assertRaises(capture.CaptureUnavailable) as raised:
                capture.choose()
            self.assertIn("sox", str(raised.exception))

    def test_wsl_prefers_pulseaudio(self):
        """WSLg only carries audio through PulseAudio."""
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

    def test_arecord_takes_the_device(self):
        self.assertIn("hw:1,0", self.build("arecord", "hw:1,0").command)

    def test_parec_without_a_device_by_default(self):
        source = self.build("parec")
        self.assertNotIn("-d", source.command)
        self.assertIn("--format=s16le", source.command)

    def test_parec_with_a_device(self):
        command = self.build("parec", "RDPSource").command
        self.assertEqual(command[command.index("-d") + 1], "RDPSource")

    def test_ffmpeg_uses_avfoundation_on_macos(self):
        with forced_host(host.MACOS):
            command = self.build("ffmpeg").command
            self.assertIn("avfoundation", command)
            self.assertEqual(command[command.index("-i") + 1], ":0")

    def test_ffmpeg_takes_the_device_index(self):
        with forced_host(host.MACOS):
            command = self.build("ffmpeg", "2").command
            self.assertEqual(command[command.index("-i") + 1], ":2")

    def test_ffmpeg_uses_pulse_elsewhere(self):
        with forced_host(host.LINUX):
            self.assertIn("pulse", self.build("ffmpeg").command)

    def test_sox_passes_the_device_through_the_environment(self):
        """rec does not take a device as an argument: it reads AUDIODEV."""
        self.assertEqual(self.build("rec").env, {})
        self.assertEqual(self.build("rec", "USB Mic").env, {"AUDIODEV": "USB Mic"})

    def test_sox_reads_the_audio_device(self):
        self.assertIn("-d", self.build("sox").command)

    def test_every_command_asks_for_16_khz_mono(self):
        for backend in capture.BUILDERS:
            with self.subTest(backend=backend):
                joined = " ".join(self.build(backend).command)
                self.assertIn("16000", joined)

    def test_every_command_writes_to_standard_output(self):
        """Most of them end with "-"; parec writes to stdout without being asked."""
        for backend in capture.BUILDERS:
            with self.subTest(backend=backend):
                command = self.build(backend).command
                self.assertTrue(command[-1] == "-" or backend == "parec", command)

    def test_every_backend_has_its_package(self):
        self.assertEqual(set(capture.BUILDERS), set(capture.PACKAGES))

    def test_every_host_only_quotes_known_backends(self):
        for names in capture.PREFERENCES.values():
            self.assertLessEqual(set(names), set(capture.BUILDERS))


if __name__ == "__main__":
    unittest.main()
