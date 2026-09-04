"""Daemon: keeps the model in memory and runs dictations on demand.

Protocol: one JSON request per line on a Unix socket, one JSON response per
line. Commands: toggle, record, stop, status, reload, quit.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

from . import config as config_module
from . import host
from . import output
from .capture import CaptureUnavailable
from .overlay_proc import OverlayProcess
from .recorder import SILENT_INPUT_PEAK, Recorder
from .transcriber import Transcriber

logger = logging.getLogger("whisper-desk.daemon")


def socket_path() -> Path:
    """The daemon's socket, in the host's runtime directory.

    XDG_RUNTIME_DIR on Linux, TMPDIR (private) on macOS; failing that /tmp,
    which is shared — so the user id is appended there.
    """
    base = config_module.RUNTIME_DIR
    if base == Path("/tmp"):
        return base / f"whisper-desk-{os.getuid()}.sock"
    return base / "whisper-desk.sock"


class Session:
    """One dictation: listening, sentence-by-sentence transcription, insertion.

    Listening and transcription run in two separate threads: the model works on
    the previous sentence while the microphone keeps recording.
    """

    def __init__(self, service: "Service", capture: bool):
        self.service = service
        self.capture = capture          # True -> the text is returned to the client
        self.done = threading.Event()
        self.recording_over = threading.Event()
        self.text = ""
        self.error: str | None = None
        self.parts: list[str] = []
        self.queue: queue.Queue[bytes | None] = queue.Queue()
        self.overlay = OverlayProcess(service.config)
        self.recorder = Recorder(
            service.config,
            on_level=self._on_level,
            on_segment=self.queue.put,
            bands=self.overlay.bars,
        )
        self.writer: output.CursorWriter | None = None

    def _on_level(self, level: float, bands: list[float]) -> None:
        self.overlay.set_level(level, bands)

    def run(self) -> None:
        try:
            self.overlay.start()
            if not self.capture and "cursor" in output.modes(self.service.config):
                self.writer = output.CursorWriter(self.service.config, self.overlay)
                # While the user speaks, the virtual keyboard is being prepared.
                threading.Thread(target=self.writer.prepare, daemon=True).start()
            worker = threading.Thread(target=self._transcribe_loop, daemon=True)
            worker.start()

            tail = self.recorder.record()
            self.recording_over.set()
            if tail:
                self.queue.put(tail)
            self.queue.put(None)

            self.service.state = "working"
            self.overlay.set_state("working")
            worker.join()
            self.text = " ".join(self.parts)
            if not self.parts:
                self._report_silence()
        except CaptureUnavailable as error:
            # A tool to install, not a bug: no need to spread out a traceback.
            self.error = str(error)
            logger.error("Capture impossible: %s", error)
            output.notify("whisper-desk: unusable microphone", str(error))
        except Exception as error:  # the daemon must never die on a dictation
            self.error = str(error)
            logger.exception("Dictation failed")
            output.notify("whisper-desk", f"Error: {error}")
        finally:
            if self.writer:
                self.writer.close()
            self.overlay.stop()
            self.service.finish(self)
            self.done.set()

    def _report_silence(self) -> None:
        """An empty dictation: tell the user's silence apart from a mute microphone."""
        peak = self.recorder.peak
        device = self.service.config["recording"]["device"]
        if peak < SILENT_INPUT_PEAK:
            logger.warning(
                "No sound captured on microphone '%s' through %s (peak %.0f) — mute "
                "device or wrong default source; see 'whisper-desk doctor'.",
                device, self.recorder.backend or "?", peak,
            )
            output.notify(
                "whisper-desk: mute microphone",
                f"No sound is coming from device '{device}'.",
            )
        else:
            logger.info(
                "No speech detected (%s, peak %.0f).", self.recorder.reason, peak
            )

    def _transcribe_loop(self) -> None:
        """Transcribes the sentences in order, as they come in."""
        while True:
            segment = self.queue.get()
            if segment is None:
                return
            if not self.recording_over.is_set():
                self.overlay.set_state("working")
            try:
                text = self.service.transcriber.transcribe(segment, " ".join(self.parts))
            except Exception as error:
                self.error = str(error)
                logger.exception("Transcription failed")
                continue
            finally:
                if not self.recording_over.is_set():
                    self.overlay.set_state("listening")
            if not text:
                continue
            # Later sentences are separated from the previous insertion by a space.
            self.parts.append(text)
            if not self.capture:
                output.deliver(
                    text if len(self.parts) == 1 else f" {text}",
                    self.service.config,
                    writer=self.writer,
                    overlay=self.overlay,
                )

    def stop(self) -> None:
        self.recorder.stop()


class Service:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.transcriber = Transcriber(config)
        self.state = "idle"
        self.session: Session | None = None
        self.lock = threading.Lock()

    # -- commands ----------------------------------------------------------
    def toggle(self) -> dict[str, Any]:
        with self.lock:
            if self.state == "recording" and self.session:
                self.session.stop()
                return {"state": "working"}
            if self.state != "idle":
                return {"state": self.state, "ignored": True}
            self._start(capture=False)
            return {"state": "recording"}

    def record(self) -> dict[str, Any]:
        with self.lock:
            if self.state != "idle":
                return {"error": f"busy ({self.state})"}
            session = self._start(capture=True)
        session.done.wait()
        if session.error:
            return {"error": session.error}
        return {"text": session.text}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.session:
                self.session.stop()
                return {"state": "working"}
            return {"state": self.state}

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "host": host.name(),
            "model": self.transcriber.model_name,
            "device": self.transcriber.device,
            "compute_type": self.transcriber.compute_type,
            "loaded": self.transcriber.is_loaded,
        }

    def reload(self) -> dict[str, Any]:
        with self.lock:
            if self.state != "idle":
                return {"error": f"busy ({self.state})"}
            self.config = config_module.load()
            self.transcriber = Transcriber(self.config)
            if self.config["model"]["preload"]:
                threading.Thread(target=self._preload, daemon=True).start()
            return {"reloaded": True}

    # -- internals ---------------------------------------------------------
    def _start(self, capture: bool) -> Session:
        session = Session(self, capture)
        self.session = session
        self.state = "recording"
        threading.Thread(target=session.run, daemon=True).start()
        return session

    def finish(self, session: Session) -> None:
        """Makes the service available again, under the same lock as the commands."""
        with self.lock:
            if self.session is session:
                self.session = None
            self.state = "idle"

    def _preload(self) -> None:
        try:
            self.transcriber.load()
        except Exception:
            logger.exception("Cannot preload the model")


class Handler(socketserver.StreamRequestHandler):
    service: Service

    def handle(self) -> None:
        for raw in self.rfile:
            try:
                request = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._reply({"error": "invalid JSON"})
                continue
            command = request.get("cmd", "")
            handlers = {
                "toggle": self.service.toggle,
                "record": self.service.record,
                "stop": self.service.stop,
                "status": self.service.status,
                "reload": self.service.reload,
                "ping": lambda: {"pong": True},
            }
            if command == "quit":
                self._reply({"bye": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            handler = handlers.get(command)
            self._reply(handler() if handler else {"error": f"unknown command: {command}"})

    def _reply(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.wfile.flush()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_alive(path: Path) -> bool:
    """True if an existing socket still answers."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1.0)
    try:
        client.connect(str(path))
        client.sendall(b'{"cmd": "ping"}\n')
        return bool(client.recv(64))
    except OSError:
        return False
    finally:
        client.close()


def serve() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Downloading the model is chatty: only warnings are kept.
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = config_module.load()
    path = socket_path()

    if path.exists():
        if _is_alive(path):
            logger.error("A daemon is already running on %s", path)
            return 1
        path.unlink()

    service = Service(config)
    handler = type("BoundHandler", (Handler,), {"service": service})
    server = Server(str(path), handler)
    os.chmod(path, 0o600)

    if config["model"]["preload"]:
        threading.Thread(target=service._preload, daemon=True).start()

    logger.info("Listening on %s (%s)", path, host.label())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
    return 0
