"""Talking to the daemon — and telling a dead one from a wedged one.

The distinction is what the shortcut hangs on: a daemon that is not there is
started, whereas one that took the order and never answered still holds the
microphone and the window, and has to be put down.
"""

from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import client

# Long enough for the connection to go through, short enough not to slow the suite.
TIMEOUT = 0.5


class SendTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "whisper-desk.sock"
        patch = mock.patch.object(client, "socket_path", lambda: self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def listen(self) -> socket.socket:
        """A socket that accepts the connection and answers nothing: a wedged daemon."""
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(self.path))
        server.listen(1)
        return server

    def test_no_socket_at_all(self):
        with self.assertRaises(client.DaemonUnavailable) as raised:
            client.send("toggle", timeout=TIMEOUT, autostart=False)
        self.assertNotIsInstance(raised.exception, client.DaemonSilent)

    def test_a_daemon_that_does_not_answer(self):
        self.listen()
        with self.assertRaises(client.DaemonSilent):
            client.send("toggle", timeout=TIMEOUT, autostart=False)

    def test_a_daemon_that_hangs_up_without_a_word(self):
        """A daemon dying mid-order is as mute as a wedged one."""
        server = self.listen()
        hang_up = threading.Thread(target=lambda: server.accept()[0].close(), daemon=True)
        hang_up.start()
        with self.assertRaises(client.DaemonSilent):
            client.send("toggle", timeout=TIMEOUT, autostart=False)
        hang_up.join(TIMEOUT)


if __name__ == "__main__":
    unittest.main()
