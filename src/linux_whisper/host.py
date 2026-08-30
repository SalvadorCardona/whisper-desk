"""Reconnaissance de l'hôte, et passerelle vers Windows quand on tourne sous WSL.

Trois hôtes sont gérés — Linux natif, WSL (Linux à l'intérieur de Windows) et
macOS. Le cœur du programme leur est commun ; ils ne diffèrent que par leurs
outils externes : capture du micro, presse-papiers, frappe clavier,
notifications, service au démarrage.

Sous WSL, les applications où l'on dicte sont presque toujours des fenêtres
Windows : on passe donc par l'interopérabilité (`clip.exe`, `powershell.exe`)
plutôt que par les outils Linux, qui ne toucheraient que les fenêtres WSLg.
"""

from __future__ import annotations

import functools
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("linux-whisper.host")

LINUX = "linux"
MACOS = "macos"
WSL = "wsl"

# Chemin de secours si /mnt/c n'est pas dans le PATH (interop sans PATH partagé).
POWERSHELL_FALLBACK = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
WSL_EXE_FALLBACK = "/mnt/c/Windows/System32/wsl.exe"


@functools.cache
def name() -> str:
    """« linux », « wsl » ou « macos ». LW_HOST force la valeur (tests, cas tordus)."""
    forced = os.environ.get("LW_HOST", "").strip().lower()
    if forced in (LINUX, MACOS, WSL):
        return forced
    if platform.system() == "Darwin":
        return MACOS
    if _inside_windows():
        return WSL
    return LINUX


def _inside_windows() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text()
    except OSError:
        return False
    return "microsoft" in release.lower()


def is_linux() -> bool:
    return name() == LINUX


def is_macos() -> bool:
    return name() == MACOS


def is_wsl() -> bool:
    return name() == WSL


def label() -> str:
    return {LINUX: "Linux", MACOS: "macOS", WSL: "WSL (Windows)"}[name()]


def reset() -> None:
    """Oublie l'hôte détecté — pour les tests, qui changent d'environnement."""
    name.cache_clear()
    powershell.cache_clear()


# -- passerelle Windows (WSL) -----------------------------------------------

@functools.cache
def powershell() -> str | None:
    """Chemin de powershell.exe, ou None si l'interop Windows est absente."""
    if not is_wsl():
        return None
    found = shutil.which("powershell.exe")
    if found:
        return found
    return POWERSHELL_FALLBACK if os.access(POWERSHELL_FALLBACK, os.X_OK) else None


def has_windows_interop() -> bool:
    return powershell() is not None


def run_powershell(script: str, timeout: float = 20.0) -> str | None:
    """Exécute un script PowerShell et retourne sa sortie, ou None en cas d'échec.

    La sortie est forcée en UTF-8 : par défaut PowerShell écrit dans la page de
    codes de la console, ce qui hacherait les accents au passage de la frontière.
    """
    shell = powershell()
    if shell is None:
        return None
    command = [
        shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script,
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("PowerShell injoignable : %s", error)
        return None
    if result.returncode != 0:
        logger.warning(
            "PowerShell a échoué (%s) : %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip()[:200],
        )
        return None
    return result.stdout.decode("utf-8", "replace")


def powershell_literal(text: str) -> str:
    """Chaîne PowerShell entre apostrophes, où seule l'apostrophe s'échappe."""
    return "'" + text.replace("'", "''") + "'"


def wsl_distro() -> str:
    return os.environ.get("WSL_DISTRO_NAME", "")


def wsl_exe() -> str:
    """Le wsl.exe vu depuis Windows : c'est lui qui rappellera le programme."""
    return shutil.which("wsl.exe") or WSL_EXE_FALLBACK


def windows_path(path: Path | str) -> str | None:
    """Traduit un chemin Linux en chemin Windows (C:\\...) via wslpath."""
    if not is_wsl():
        return None
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(path)], capture_output=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip() or None
