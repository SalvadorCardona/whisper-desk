"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from . import config as config_module
from . import host

BIN = str(Path.home() / ".local/bin/whisper-desk")


def _print_error(message: str) -> int:
    print(f"whisper-desk: {message}", file=sys.stderr)
    return 1


def cmd_daemon(_args: argparse.Namespace) -> int:
    from .daemon import serve

    return serve()


def cmd_toggle(_args: argparse.Namespace) -> int:
    from .client import DaemonUnavailable, send

    try:
        reply = send("toggle", timeout=20)
    except DaemonUnavailable as error:
        return _print_error(str(error))
    print(reply.get("state", reply))
    return 0


def cmd_record(_args: argparse.Namespace) -> int:
    """Dictée synchrone : le texte transcrit part sur stdout."""
    from .client import DaemonUnavailable, send

    try:
        reply = send("record")
    except DaemonUnavailable as error:
        return _print_error(str(error))
    if "error" in reply:
        return _print_error(reply["error"])
    text = reply.get("text", "")
    if text:
        print(text)
    return 0


def cmd_simple(command: str):
    def run(_args: argparse.Namespace) -> int:
        from .client import DaemonUnavailable, send

        try:
            # Interroger ou arrêter le daemon ne doit pas le faire naître.
            reply = send(command, timeout=30, autostart=command not in ("status", "quit"))
        except DaemonUnavailable as error:
            return _print_error(str(error))
        print(json.dumps(reply, ensure_ascii=False))
        return 0

    return run


def cmd_hotkey(args: argparse.Namespace) -> int:
    from . import hotkey

    config = config_module.load()
    try:
        if args.hotkey_action == "remove":
            hotkey.remove()
            print("Raccourci supprimé.")
            return 0
        if args.hotkey_action == "show":
            current = hotkey.show()
            print(json.dumps(current, ensure_ascii=False, indent=2) if current else "Aucun raccourci installé.")
            return 0
        binding = hotkey.install(config, f"{BIN} toggle")
        print(f"Raccourci installé : {binding} → {BIN} toggle")
        return 0
    except hotkey.UnsupportedDesktop as error:
        return _print_error(
            f"{error}. Créez le raccourci à la main sur la commande « {BIN} toggle »."
        )
    except (OSError, subprocess.SubprocessError) as error:
        return _print_error(f"l'installation du raccourci a échoué : {error}")


def cmd_config(args: argparse.Namespace) -> int:
    path = config_module.CONFIG_PATH
    if args.config_action == "path":
        print(path)
        return 0
    if args.config_action == "show":
        print(json.dumps(config_module.load(), ensure_ascii=False, indent=2))
        return 0
    if not path.exists():
        return _print_error(f"{path} est absent — relancez l'installation.")
    editor = os.environ.get("EDITOR") or shutil.which("nano") or "vi"
    subprocess.run([editor, str(path)], check=False)
    print("Pensez à « whisper-desk reload » pour appliquer.")
    return 0


def _measure_microphone(config: dict, seconds: int = 2) -> tuple[float, float]:
    """Écoute brièvement le micro et retourne (niveau moyen, pic).

    Passe par le même backend de capture que la dictée : ce que mesure le
    diagnostic est exactement ce qu'entendra le daemon.
    """
    import threading

    from . import capture
    from .recorder import CHANNELS, CHUNK_BYTES, RATE, SAMPLE_WIDTH, _rms

    settings = config["recording"]
    try:
        source = capture.build(
            str(settings["device"]), RATE, CHANNELS, str(settings["backend"])
        )
    except capture.CaptureUnavailable:
        return 0.0, 0.0

    try:
        process = subprocess.Popen(
            source.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env={**os.environ, **source.env} if source.env else None,
        )
    except OSError:
        return 0.0, 0.0

    # Un micro absent ne rend rien du tout : la lecture bloquerait sans ce garde-fou.
    watchdog = threading.Timer(seconds + 5, process.kill)
    watchdog.start()
    wanted = int(RATE * SAMPLE_WIDTH * seconds)
    raw = b""
    try:
        assert process.stdout is not None
        while len(raw) < wanted:
            chunk = process.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            raw += chunk
    except OSError:
        pass
    finally:
        watchdog.cancel()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.stdout:
            process.stdout.close()

    if not raw:
        return 0.0, 0.0
    levels = [
        _rms(raw[start:start + CHUNK_BYTES])
        for start in range(0, len(raw), CHUNK_BYTES)
    ] or [0.0]
    return sum(levels) / len(levels), max(levels)


def cmd_doctor(_args: argparse.Namespace) -> int:
    from . import capture, hotkey, inject, output, service
    from .daemon import socket_path
    from .overlay_proc import system_python
    from .recorder import SILENT_INPUT_PEAK
    from .transcriber import has_nvidia_gpu

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")

    config = config_module.load()
    settings = config["recording"]

    print(f"Système — {host.label()}")
    usable = capture.available()
    check(
        "capture du micro",
        bool(usable),
        ", ".join(usable) if usable
        else f"installez {capture.PACKAGES[capture.recommended()]}",
    )
    level, peak = _measure_microphone(config)
    audible = peak > SILENT_INPUT_PEAK
    check(
        f"le micro capte du son (« {settings['device']} »)",
        audible,
        f"niveau moyen {level:.0f}, pic {peak:.0f}"
        + ("" if audible else f" — {_microphone_hint()}"),
    )
    tool = output.clipboard_tool()
    check(
        "presse-papiers",
        bool(tool),
        tool or f"installez {' ou '.join(output.CLIPBOARD_TOOLS[host.name()])}",
    )
    keyboard = inject.keyboard(str(config["output"]["keyboard"]))
    check(
        f"frappe du collage ({keyboard.name})",
        keyboard.available,
        keyboard.hint if not keyboard.available else "",
    )
    check(
        "notifications",
        bool(shutil.which("notify-send"))
        or (host.is_macos() and bool(shutil.which("osascript"))),
        "osascript" if host.is_macos() else "paquet libnotify-bin",
    )
    if host.is_macos():
        check("GPU NVIDIA", False, "transcription sur CPU (int8) — normal sur macOS")
    else:
        check("GPU NVIDIA", has_nvidia_gpu(), "sinon transcription sur CPU")

    if config["overlay"]["enabled"]:
        check(
            "overlay sans vol de focus (X11/Xwayland)",
            bool(os.environ.get("DISPLAY")),
            "sinon l'overlay capterait le collage",
        )
        overlay_ok = subprocess.run(
            [system_python(), "-c",
             "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk"],
            capture_output=True,
        ).returncode == 0
        check("overlay GTK3", overlay_ok, _overlay_hint())

    print("Configuration")
    check(f"fichier {config_module.CONFIG_PATH}", config_module.CONFIG_PATH.exists())
    print(
        f"    modèle={config['model']['name']} langue={config['model']['language']}"
        f" sortie={config['output']['mode']}"
        f" collage={'+'.join(inject.resolve_shortcut(str(config['output']['paste_shortcut'])))}"
        f" flux={'oui' if settings['streaming'] else 'non'}"
    )

    print("Service")
    state = service.status()
    check(f"daemon ({service.manager()})", state == "active", state)
    check(f"socket {socket_path()}", socket_path().exists())

    print("Raccourci")
    try:
        current = hotkey.show()
        check(
            f"raccourci {hotkey.backend().name}",
            bool(current),
            current.get("binding", "absent") if current else "absent",
        )
    except hotkey.UnsupportedDesktop as error:
        check("raccourci global", False, str(error))
    return 0


def _microphone_hint() -> str:
    if host.is_macos():
        return (
            "vérifiez l'entrée par défaut (Réglages Système → Son) et "
            "l'autorisation micro du terminal"
        )
    if host.is_wsl():
        return "WSLg doit être à jour, et le micro autorisé côté Windows"
    return "vérifiez la source par défaut : wpctl status"


def _overlay_hint() -> str:
    if host.is_macos():
        return "brew install pygobject3 gtk+3, ou overlay.enabled = false"
    return "paquets python3-gi + gir1.2-gtk-3.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whisper-desk",
        description="Dictée vocale hors-ligne : un raccourci, vous parlez, le texte est copié.",
    )
    parser.add_argument("--version", action="version", version=f"whisper-desk {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daemon", help="lance le service (géré par systemd)").set_defaults(func=cmd_daemon)
    sub.add_parser("toggle", help="démarre l'écoute, ou l'arrête si elle tourne").set_defaults(func=cmd_toggle)
    sub.add_parser("record", help="dictée synchrone, texte sur stdout").set_defaults(func=cmd_record)
    sub.add_parser("stop", help="arrête l'écoute en cours").set_defaults(func=cmd_simple("stop"))
    sub.add_parser("status", help="état du daemon").set_defaults(func=cmd_simple("status"))
    sub.add_parser("reload", help="recharge la configuration").set_defaults(func=cmd_simple("reload"))
    sub.add_parser("quit", help="arrête le daemon").set_defaults(func=cmd_simple("quit"))
    sub.add_parser("doctor", help="diagnostic de l'installation").set_defaults(func=cmd_doctor)

    hotkey_parser = sub.add_parser("hotkey", help="gère le raccourci global")
    hotkey_parser.add_argument(
        "hotkey_action", nargs="?", default="install", choices=("install", "remove", "show")
    )
    hotkey_parser.set_defaults(func=cmd_hotkey)

    config_parser = sub.add_parser("config", help="configuration utilisateur")
    config_parser.add_argument(
        "config_action", nargs="?", default="edit", choices=("edit", "path", "show")
    )
    config_parser.set_defaults(func=cmd_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
