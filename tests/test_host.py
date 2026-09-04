"""Host detection and escaping of PowerShell strings."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)
from .context import forced_host

from whisper_desk import host


class DetectionTest(unittest.TestCase):
    def test_all_three_hosts_can_be_forced(self):
        for name in (host.LINUX, host.WSL, host.MACOS):
            with forced_host(name):
                self.assertEqual(host.name(), name)

    def test_an_unknown_host_is_ignored(self):
        with forced_host("plan9"):
            self.assertIn(host.name(), (host.LINUX, host.WSL, host.MACOS))

    def test_the_predicates_are_exclusive(self):
        with forced_host(host.MACOS):
            self.assertTrue(host.is_macos())
            self.assertFalse(host.is_linux())
            self.assertFalse(host.is_wsl())

    def test_darwin_is_macos(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WD_HOST", None)
            host.reset()
            with mock.patch.object(host.platform, "system", return_value="Darwin"):
                self.assertEqual(host.name(), host.MACOS)
        host.reset()

    def test_a_microsoft_kernel_is_wsl(self):
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False):
            os.environ.pop("WD_HOST", None)
            host.reset()
            with mock.patch.object(host.platform, "system", return_value="Linux"):
                self.assertEqual(host.name(), host.WSL)
        host.reset()

    def test_powershell_stays_out_of_reach_elsewhere(self):
        for name in (host.LINUX, host.MACOS):
            with forced_host(name):
                self.assertIsNone(host.powershell())
                self.assertFalse(host.has_windows_interop())


class PowerShellLiteralTest(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(host.powershell_literal("ctrl+v"), "'ctrl+v'")

    def test_the_quote_is_doubled(self):
        self.assertEqual(host.powershell_literal("l'été"), "'l''été'")

    def test_the_rest_is_not_escaped(self):
        """Between single quotes, PowerShell expands neither $ nor backslashes."""
        self.assertEqual(host.powershell_literal('$env:X\\n"'), '\'$env:X\\n"\'')


if __name__ == "__main__":
    unittest.main()
