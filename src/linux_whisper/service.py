"""Démarrage du daemon : systemd, launchd, ou lancement direct.

Aucun de ces gestionnaires n'est disponible partout — systemd n'existe pas sur
macOS et pas toujours sous WSL, launchd n'existe que sur macOS. Le lancement
direct est le filet de sécurité : un simple processus détaché, qui marche
partout et suffit à ce que le premier raccourci fonctionne.
"""

from __future__ import annotations

import logging
import os
import subprocess
import shutil
import sys
from pathlib import Path

from . import config as config_module
from . import host

logger = logging.getLogger("linux-whisper.service")

SYSTEMD = "systemd"
LAUNCHD = "launchd"
DIRECT = "direct"

UNIT = "linux-whisper.service"
LAUNCH_LABEL = "fr.linuxwhisper.daemon"

UNIT_PATH = Path.home() / ".config/systemd/user" / UNIT
AGENT_PATH = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_LABEL}.plist"
LOG_PATH = config_module.STATE_DIR / "daemon.log"


def has_systemd() -> bool:
    """systemd présent *et* actif : sous WSL sans systemd, systemctl existe mais échoue."""
    return bool(shutil.which("systemctl")) and Path("/run/systemd/system").is_dir()


def manager() -> str:
    if has_systemd():
        return SYSTEMD
    if host.is_macos() and shutil.which("launchctl"):
        return LAUNCHD
    return DIRECT


def _launchctl(*args: str) -> bool:
    try:
        return subprocess.run(
            ["launchctl", *args], capture_output=True, timeout=15
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _domain_target() -> str:
    return f"gui/{os.getuid()}/{LAUNCH_LABEL}"


def start() -> bool:
    """Démarre le daemon par le meilleur moyen disponible."""
    current = manager()
    if current == SYSTEMD:
        try:
            subprocess.run(
                ["systemctl", "--user", "start", UNIT],
                check=True, capture_output=True, timeout=15,
            )
            return True
        except (OSError, subprocess.SubprocessError) as error:
            logger.debug("systemd n'a pas démarré le service (%s) — lancement direct.", error)
    elif current == LAUNCHD:
        if _launchctl("kickstart", "-k", _domain_target()) or _launchctl("start", LAUNCH_LABEL):
            return True
        logger.debug("launchd n'a pas démarré l'agent — lancement direct.")
    return start_directly()


def start_directly() -> bool:
    """Lance « linux-whisper daemon » en processus détaché, sans gestionnaire.

    Le même interpréteur et le même environnement que le client : c'est le
    lanceur installé qui a posé PYTHONPATH et les bibliothèques CUDA.
    """
    try:
        config_module.STATE_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_PATH.open("a", encoding="utf-8")
    except OSError:
        log = None
    try:
        subprocess.Popen(
            [sys.executable, "-m", "linux_whisper", "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log else subprocess.DEVNULL,
            start_new_session=True,   # survit à la fin du client
            cwd=str(Path.home()),
        )
        return True
    except OSError as error:
        logger.warning("Démarrage direct du daemon impossible : %s", error)
        return False
    finally:
        if log is not None:
            log.close()


def status() -> str:
    """« active », « inactive », ou la raison pour laquelle on ne sait pas."""
    current = manager()
    if current == SYSTEMD:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", UNIT],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return "inconnu"
        return result.stdout.strip() or "inconnu"
    if current == LAUNCHD:
        if not AGENT_PATH.exists():
            return "non installé"
        return "active" if _launchctl("list", LAUNCH_LABEL) else "inactive"
    return "sans gestionnaire (lancement à la demande)"


def hint() -> str:
    """Comment démarrer le daemon à la main, sur cet hôte."""
    return {
        SYSTEMD: f"systemctl --user start {UNIT}",
        LAUNCHD: f"launchctl start {LAUNCH_LABEL}",
        DIRECT: "linux-whisper daemon &",
    }[manager()]
