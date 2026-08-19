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

BIN = str(Path.home() / ".local/bin/linux-whisper")


def _print_error(message: str) -> int:
    print(f"linux-whisper: {message}", file=sys.stderr)
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
            reply = send(command, timeout=30, autostart=command != "status")
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
        return _print_error(f"gsettings a échoué : {error}")


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
    print("Pensez à « linux-whisper reload » pour appliquer.")
    return 0


def _measure_microphone(device: str, seconds: float = 1.5) -> tuple[float, float]:
    """Écoute brièvement le micro et retourne (niveau moyen, pic)."""
    from .recorder import _rms

    try:
        raw = subprocess.run(
            ["arecord", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "1",
             "-t", "raw", "-d", str(int(seconds) or 1), "-q"],
            capture_output=True,
            timeout=seconds + 5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0.0, 0.0
    if not raw:
        return 0.0, 0.0
    chunks = [raw[i:i + 3200] for i in range(0, len(raw) - 3200, 3200)]
    levels = [_rms(chunk) for chunk in chunks] or [0.0]
    return sum(levels) / len(levels), max(levels)


def cmd_doctor(_args: argparse.Namespace) -> int:
    from . import hotkey
    from .daemon import socket_path
    from .overlay_proc import system_python
    from .transcriber import has_nvidia_gpu

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")

    config = config_module.load()
    print("Système")
    check("arecord (capture micro)", bool(shutil.which("arecord")), "paquet alsa-utils")
    level, peak = _measure_microphone(str(config["recording"]["device"]))
    check(
        f"le micro capte du son (« {config['recording']['device']} »)",
        peak > 30,
        f"niveau moyen {level:.0f}, pic {peak:.0f}"
        + ("" if peak > 30 else " — vérifiez la source par défaut : wpctl status"),
    )
    check(
        "presse-papiers",
        any(map(shutil.which, ("wl-copy", "xclip", "xsel"))),
        "paquet wl-clipboard",
    )
    check(
        "clavier virtuel (/dev/uinput)",
        os.access("/dev/uinput", os.W_OK),
        "sans lui, pas d'insertion au curseur",
    )
    check(
        "overlay sans vol de focus (X11/Xwayland)",
        bool(os.environ.get("DISPLAY")),
        "sinon l'overlay capterait le collage",
    )
    check("notify-send", bool(shutil.which("notify-send")), "paquet libnotify-bin")
    check("GPU NVIDIA", has_nvidia_gpu(), "sinon transcription sur CPU")

    overlay_ok = subprocess.run(
        [system_python(), "-c", "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk"],
        capture_output=True,
    ).returncode == 0
    check("overlay GTK3", overlay_ok, "paquets python3-gi + gir1.2-gtk-3.0")

    print("Configuration")
    check(f"fichier {config_module.CONFIG_PATH}", config_module.CONFIG_PATH.exists())
    print(
        f"    modèle={config['model']['name']} langue={config['model']['language']}"
        f" sortie={config['output']['mode']} raccourci-collage={config['output']['paste_shortcut']}"
        f" flux={'oui' if config['recording']['streaming'] else 'non'}"
    )

    print("Service")
    unit = subprocess.run(
        ["systemctl", "--user", "is-active", "linux-whisper.service"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    check("linux-whisper.service", unit == "active", unit or "non installé")
    check(f"socket {socket_path()}", socket_path().exists())

    print("Raccourci")
    try:
        current = hotkey.show()
        check("raccourci GNOME", bool(current), current.get("binding", "absent") if current else "absent")
    except hotkey.UnsupportedDesktop as error:
        check("raccourci GNOME", False, str(error))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linux-whisper",
        description="Dictée vocale hors-ligne : un raccourci, vous parlez, le texte est copié.",
    )
    parser.add_argument("--version", action="version", version=f"linux-whisper {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daemon", help="lance le service (géré par systemd)").set_defaults(func=cmd_daemon)
    sub.add_parser("toggle", help="démarre l'écoute, ou l'arrête si elle tourne").set_defaults(func=cmd_toggle)
    sub.add_parser("record", help="dictée synchrone, texte sur stdout").set_defaults(func=cmd_record)
    sub.add_parser("stop", help="arrête l'écoute en cours").set_defaults(func=cmd_simple("stop"))
    sub.add_parser("status", help="état du daemon").set_defaults(func=cmd_simple("status"))
    sub.add_parser("reload", help="recharge la configuration").set_defaults(func=cmd_simple("reload"))
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
