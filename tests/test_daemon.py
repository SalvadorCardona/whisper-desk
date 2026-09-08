"""The shortcut as a real toggle: it starts, it stops, and it cuts things off.

In a shared office, a neighbour's voice keeps the microphone busy: the silence
that ends a dictation never comes. Pressing the shortcut again must always
answer — first by stopping the listening, then by dropping what the model was
still chewing on, rather than typing the room's conversation at the cursor.
"""

from __future__ import annotations

import contextlib
import threading
import time
import unittest
from unittest import mock

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import daemon

# Long enough for a thread to get going, short enough for a stuck test to fail.
TIMEOUT = 5.0

CONFIG = {
    # "clipboard" keeps the virtual keyboard out of the way: what is under test
    # is what reaches the output, not how it is typed.
    "output": {"mode": "clipboard", "history": False, "notify": False},
    "recording": {"device": "default"},
    "overlay": {"enabled": False},
    "model": {},
}


def wait_until(predicate, timeout: float = TIMEOUT) -> bool:
    """Waits for a state reached by another thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeOverlay:
    """The listening window, reduced to what the dictation asks of it."""

    def __init__(self, *_args, **_kwargs):
        self.bars = 0
        self.states: list[str] = []
        self.stopped = False

    def start(self) -> None:
        pass

    def set_state(self, state: str) -> None:
        self.states.append(state)

    def set_level(self, level: float, bands=()) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True


class FakeRecorder:
    """Hands over the sentences the test gives it, then waits for the shortcut."""

    def __init__(self, segments=(), tail: bytes = b""):
        self.segments = list(segments)
        self.tail = tail
        self.on_segment = None
        self.listening = threading.Event()
        self.stopped = threading.Event()
        self.peak = 1000.0
        self.reason = "stopped"
        self.backend = "fake"

    def stop(self) -> None:
        self.stopped.set()

    def record(self) -> bytes:
        for segment in self.segments:
            self.on_segment(segment)
        self.listening.set()
        self.stopped.wait(TIMEOUT)
        return self.tail


class FakeTranscriber:
    """One text per segment, held inside the model as long as the test wants."""

    def __init__(self):
        self.model_name, self.device, self.compute_type = "fake", "cpu", "int8"
        self.is_loaded = True
        self.entered = threading.Event()    # a segment has reached the model
        self.release = threading.Event()    # ... and may leave it
        self.release.set()
        self.seen: list[bytes] = []

    def transcribe(self, pcm: bytes, context: str = "") -> str:
        self.seen.append(pcm)
        self.entered.set()
        self.release.wait(TIMEOUT)
        return pcm.decode()


class ToggleTest(unittest.TestCase):
    def setUp(self):
        self.recorder = FakeRecorder([b"a sentence"])
        self.transcriber = FakeTranscriber()
        self.delivered: list[str] = []

    @contextlib.contextmanager
    def service(self):
        """A daemon whose microphone, model and window belong to the test."""
        def build_recorder(*_args, **kwargs):
            self.recorder.on_segment = kwargs["on_segment"]
            return self.recorder

        with mock.patch.object(daemon, "Recorder", build_recorder), \
                mock.patch.object(daemon, "OverlayProcess", FakeOverlay), \
                mock.patch.object(daemon, "Transcriber", lambda *a, **k: self.transcriber), \
                mock.patch.object(
                    daemon.output, "deliver",
                    lambda text, *a, **k: self.delivered.append(text),
                ), \
                mock.patch.object(daemon.output, "notify", lambda *a, **k: None):
            service = daemon.Service(CONFIG)
            try:
                yield service
            finally:
                # Whatever the test did, no thread is left hanging.
                self.recorder.stop()
                self.transcriber.release.set()
                session = service.session
                if session is not None:
                    session.done.wait(TIMEOUT)

    def listening(self, service) -> None:
        """Starts a dictation and waits for the microphone to be open."""
        service.toggle()
        self.assertTrue(self.recorder.listening.wait(TIMEOUT))

    def transcribing(self, service) -> None:
        """Stops the listening while a sentence is still inside the model."""
        self.transcriber.release.clear()
        self.listening(service)
        self.assertTrue(self.transcriber.entered.wait(TIMEOUT))
        service.toggle()
        self.assertTrue(wait_until(lambda: service.state == "working"))

    # -- the two first presses, unchanged -----------------------------------
    def test_the_first_press_starts_the_listening(self):
        with self.service() as service:
            self.assertEqual(service.toggle(), {"state": "recording"})
            self.assertEqual(service.state, "recording")

    def test_the_second_press_stops_the_listening(self):
        with self.service() as service:
            self.listening(service)
            self.assertEqual(service.toggle(), {"state": "working"})
            self.assertTrue(self.recorder.stopped.is_set())

    def test_an_ordinary_dictation_still_delivers_its_text(self):
        with self.service() as service:
            self.listening(service)
            service.toggle()
            self.assertTrue(wait_until(lambda: service.session is None))
        self.assertEqual(self.delivered, ["a sentence"])

    # -- the press that cuts the transcription off ---------------------------
    def test_a_press_while_transcribing_cuts_the_dictation_off(self):
        with self.service() as service:
            self.transcribing(service)
            self.assertEqual(service.toggle(), {"state": "cancelled"})
            self.transcriber.release.set()
            self.assertTrue(wait_until(lambda: service.session is None))
        self.assertEqual(self.delivered, [])

    def test_the_sentences_still_queued_are_dropped(self):
        self.recorder.segments[:] = [b"first", b"second", b"third"]
        with self.service() as service:
            self.transcribing(service)
            service.toggle()
            self.transcriber.release.set()
            self.assertTrue(wait_until(lambda: service.session is None))
        # The one already inside the model could not be interrupted; the
        # others never reached it, and none of them was typed.
        self.assertEqual(self.transcriber.seen, [b"first"])
        self.assertEqual(self.delivered, [])

    def test_the_window_closes_without_waiting_for_the_model(self):
        """The shortcut must be seen to answer, model busy or not."""
        with self.service() as service:
            self.transcribing(service)
            overlay = service.session.overlay
            service.toggle()
            self.assertTrue(overlay.stopped)

    def test_the_shortcut_is_never_ignored(self):
        with self.service() as service:
            self.transcribing(service)
            self.assertNotIn("ignored", service.toggle())

    def test_a_new_dictation_can_start_right_after(self):
        with self.service() as service:
            self.transcribing(service)
            service.toggle()
            self.transcriber.release.set()
            self.assertTrue(wait_until(lambda: service.state == "idle"))
            self.assertEqual(service.toggle(), {"state": "recording"})

    def test_a_cut_dictation_says_nothing_about_the_microphone(self):
        """No sentence is not the same as no sound: no mute-microphone warning."""
        with self.service() as service, \
                mock.patch.object(daemon.output, "notify") as notify:
            self.transcribing(service)
            service.toggle()
            self.transcriber.release.set()
            self.assertTrue(wait_until(lambda: service.session is None))
            notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
