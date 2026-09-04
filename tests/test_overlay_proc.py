"""Driving the listening window: the pipe may break, the closing may not."""

from __future__ import annotations

import threading
import unittest

from . import context  # noqa: F401

from whisper_desk.overlay_proc import OverlayProcess

CONFIG = {
    "overlay": {
        "enabled": True,
        "accent": "#e46212",
        "width": 232,
        "height": 64,
        "bars": 15,
        "position": "bottom-center",
        "margin": 96,
    }
}


class FakeStdin:
    def __init__(self, broken: bool = False):
        self.broken = broken
        self.lines: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.broken:
            raise BrokenPipeError("pipe closed")
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        if self.broken:
            raise BrokenPipeError("pipe closed")

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdin: FakeStdin, returncode=None):
        self.stdin = stdin
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def attached(stdin: FakeStdin) -> tuple[OverlayProcess, FakeProcess]:
    overlay = OverlayProcess(CONFIG)
    process = FakeProcess(stdin)
    overlay._process = process
    return overlay, process


class SendTest(unittest.TestCase):
    def test_one_command_per_line(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_state("working")
        overlay.set_level(0.5)
        self.assertEqual(stdin.lines, [b"state working\n", b"level 0.500\n"])

    def test_the_equalizer_travels_on_the_same_line_as_the_level(self):
        """One write per measurement: two lines would interleave on the pipe."""
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(0.5, [0.25, 0.75])
        self.assertEqual(stdin.lines, [b"level 0.500 0.250 0.750\n"])

    def test_the_number_of_bars_comes_from_the_configuration(self):
        self.assertEqual(OverlayProcess(CONFIG).bars, 15)

    def test_overlay_disabled_means_nobody_watches_the_bands(self):
        config = {"overlay": {**CONFIG["overlay"], "enabled": False}}
        self.assertEqual(OverlayProcess(config).bars, 0)

    def test_the_level_is_capped_to_three_decimals(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(1 / 3)
        self.assertEqual(stdin.lines, [b"level 0.333\n"])

    def test_the_copied_text_travels_as_base64_on_one_line(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        self.assertTrue(overlay.copy("sentence with spaces\nand a line break"))
        self.assertEqual(len(stdin.lines), 1)
        self.assertTrue(stdin.lines[0].startswith(b"copy "))
        self.assertEqual(stdin.lines[0].count(b"\n"), 1)


class BrokenPipeTest(unittest.TestCase):
    """A broken pipe must not leave the window orphaned on screen."""

    def test_a_failed_write_is_not_fatal(self):
        overlay, _ = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)  # does not raise
        self.assertFalse(overlay.alive)

    def test_the_window_is_closed_anyway(self):
        overlay, process = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)
        overlay.stop()
        self.assertTrue(process.terminated or process.killed)

    def test_nothing_more_is_sent_after_the_break(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(0.1)
        stdin.broken = True
        overlay.set_level(0.2)
        stdin.broken = False
        overlay.set_level(0.3)
        self.assertEqual(stdin.lines, [b"level 0.100\n"])

    def test_the_copy_fails_outright(self):
        overlay, _ = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)
        self.assertFalse(overlay.copy("text"))
        self.assertFalse(overlay.save_clipboard())
        self.assertFalse(overlay.restore_clipboard())


class StopTest(unittest.TestCase):
    def test_stopping_asks_politely_for_the_closing(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.stop()
        self.assertEqual(stdin.lines, [b"quit\n"])
        self.assertTrue(stdin.closed)

    def test_stopping_is_idempotent(self):
        overlay, _ = attached(FakeStdin())
        overlay.stop()
        overlay.stop()  # does not raise
        self.assertFalse(overlay.alive)

    def test_a_dead_process_is_no_longer_alive(self):
        overlay = OverlayProcess(CONFIG)
        overlay._process = FakeProcess(FakeStdin(), returncode=0)
        self.assertFalse(overlay.alive)


class ConcurrencyTest(unittest.TestCase):
    """Levels come from the microphone thread, states from the dictation thread."""

    def test_the_lines_do_not_interleave(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        start = threading.Barrier(4)

        def spam(send):
            start.wait()
            for _ in range(200):
                send()

        threads = [
            threading.Thread(target=spam, args=(lambda: overlay.set_level(0.25),)),
            threading.Thread(target=spam, args=(lambda: overlay.set_state("listening"),)),
            threading.Thread(target=spam, args=(lambda: overlay.set_state("working"),)),
        ]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(stdin.lines), 600)
        self.assertEqual(
            set(stdin.lines),
            {b"level 0.250\n", b"state listening\n", b"state working\n"},
        )


if __name__ == "__main__":
    unittest.main()
