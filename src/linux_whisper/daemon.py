"""Daemon : garde le modèle en mémoire et exécute les dictées à la demande.

Protocole : une requête JSON par ligne sur une socket Unix, une réponse JSON
par ligne. Commandes : toggle, record, stop, status, reload, quit.
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

logger = logging.getLogger("linux-whisper.daemon")


def socket_path() -> Path:
    """La socket du daemon, dans le dossier d'exécution de l'hôte.

    XDG_RUNTIME_DIR sous Linux, TMPDIR (privé) sous macOS ; à défaut /tmp, qui
    est partagé — on y ajoute donc l'identifiant de l'utilisateur.
    """
    base = config_module.RUNTIME_DIR
    if base == Path("/tmp"):
        return base / f"linux-whisper-{os.getuid()}.sock"
    return base / "linux-whisper.sock"


class Session:
    """Une dictée : écoute, transcription phrase par phrase, insertion.

    L'écoute et la transcription tournent dans deux fils séparés : le modèle
    travaille sur la phrase précédente pendant que le micro continue d'enregistrer.
    """

    def __init__(self, service: "Service", capture: bool):
        self.service = service
        self.capture = capture          # True -> le texte est renvoyé au client
        self.done = threading.Event()
        self.recording_over = threading.Event()
        self.text = ""
        self.error: str | None = None
        self.parts: list[str] = []
        self.queue: queue.Queue[bytes | None] = queue.Queue()
        self.overlay = OverlayProcess(service.config)
        self.recorder = Recorder(
            service.config, on_level=self._on_level, on_segment=self.queue.put
        )
        self.writer: output.CursorWriter | None = None

    def _on_level(self, level: float) -> None:
        self.overlay.set_level(level)

    def run(self) -> None:
        try:
            self.overlay.start()
            if not self.capture and "cursor" in output.modes(self.service.config):
                self.writer = output.CursorWriter(self.service.config, self.overlay)
                # Pendant que l'utilisateur parle, on prépare le clavier virtuel.
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
            # Un outil à installer, pas un bogue : inutile d'étaler une trace.
            self.error = str(error)
            logger.error("Capture impossible : %s", error)
            output.notify("linux-whisper : micro inutilisable", str(error))
        except Exception as error:  # le daemon ne doit jamais mourir sur une dictée
            self.error = str(error)
            logger.exception("Dictée en échec")
            output.notify("linux-whisper", f"Erreur : {error}")
        finally:
            if self.writer:
                self.writer.close()
            self.overlay.stop()
            self.service.finish(self)
            self.done.set()

    def _report_silence(self) -> None:
        """Une dictée vide : distinguer le silence de l'utilisateur du micro muet."""
        peak = self.recorder.peak
        device = self.service.config["recording"]["device"]
        if peak < SILENT_INPUT_PEAK:
            logger.warning(
                "Aucun son capté sur le micro « %s » via %s (pic %.0f) — périphérique "
                "muet ou mauvaise source par défaut ; voir « linux-whisper doctor ».",
                device, self.recorder.backend or "?", peak,
            )
            output.notify(
                "linux-whisper : micro muet",
                f"Aucun son n'arrive du périphérique « {device} ».",
            )
        else:
            logger.info(
                "Aucune parole détectée (%s, pic %.0f).", self.recorder.reason, peak
            )

    def _transcribe_loop(self) -> None:
        """Transcrit les phrases dans l'ordre, au fur et à mesure de leur arrivée."""
        while True:
            segment = self.queue.get()
            if segment is None:
                return
            if not self.recording_over.is_set():
                self.overlay.set_state("working")
            try:
                text = self.service.transcriber.transcribe(segment)
            except Exception as error:
                self.error = str(error)
                logger.exception("Transcription en échec")
                continue
            finally:
                if not self.recording_over.is_set():
                    self.overlay.set_state("listening")
            if not text:
                continue
            # Les phrases suivantes sont séparées par une espace de l'insertion précédente.
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

    # -- commandes ---------------------------------------------------------
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
                return {"error": f"occupé ({self.state})"}
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
                return {"error": f"occupé ({self.state})"}
            self.config = config_module.load()
            self.transcriber = Transcriber(self.config)
            if self.config["model"]["preload"]:
                threading.Thread(target=self._preload, daemon=True).start()
            return {"reloaded": True}

    # -- interne -----------------------------------------------------------
    def _start(self, capture: bool) -> Session:
        session = Session(self, capture)
        self.session = session
        self.state = "recording"
        threading.Thread(target=session.run, daemon=True).start()
        return session

    def finish(self, session: Session) -> None:
        """Rend le service disponible, sous le même verrou que les commandes."""
        with self.lock:
            if self.session is session:
                self.session = None
            self.state = "idle"

    def _preload(self) -> None:
        try:
            self.transcriber.load()
        except Exception:
            logger.exception("Préchargement du modèle impossible")


class Handler(socketserver.StreamRequestHandler):
    service: Service

    def handle(self) -> None:
        for raw in self.rfile:
            try:
                request = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._reply({"error": "JSON invalide"})
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
            self._reply(handler() if handler else {"error": f"commande inconnue : {command}"})

    def _reply(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.wfile.flush()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_alive(path: Path) -> bool:
    """Vrai si une socket existante répond encore."""
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
    # Le téléchargement du modèle est bavard : on ne garde que les avertissements.
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    config = config_module.load()
    path = socket_path()

    if path.exists():
        if _is_alive(path):
            logger.error("Un daemon tourne déjà sur %s", path)
            return 1
        path.unlink()

    service = Service(config)
    handler = type("BoundHandler", (Handler,), {"service": service})
    server = Server(str(path), handler)
    os.chmod(path, 0o600)

    if config["model"]["preload"]:
        threading.Thread(target=service._preload, daemon=True).start()

    logger.info("À l'écoute sur %s (%s)", path, host.label())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
    return 0
