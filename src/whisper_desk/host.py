"""Host detection, and the bridge to Windows when running under WSL.

Three hosts are supported — native Linux, WSL (Linux inside Windows) and
macOS. The core of the program is shared between them; they only differ in
their external tools: microphone capture, clipboard, keystrokes,
notifications, service at startup.

Under WSL, the applications you dictate into are almost always Windows
windows: so we go through interoperability (`clip.exe`, `powershell.exe`)
rather than the Linux tools, which would only reach WSLg windows.
"""

from __future__ import annotations

import functools
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("whisper-desk.host")

LINUX = "linux"
MACOS = "macos"
WSL = "wsl"

# Fallback path if /mnt/c is not in the PATH (interop without a shared PATH).
POWERSHELL_FALLBACK = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
WSL_EXE_FALLBACK = "/mnt/c/Windows/System32/wsl.exe"


@functools.cache
def name() -> str:
    """Returns "linux", "wsl" or "macos". WD_HOST forces the value (tests, odd cases)."""
    forced = os.environ.get("WD_HOST", "").strip().lower()
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
    """Forgets the detected host — for the tests, which change environment."""
    name.cache_clear()
    powershell.cache_clear()


# -- Windows bridge (WSL) ----------------------------------------------------

@functools.cache
def powershell() -> str | None:
    """Path to powershell.exe, or None if Windows interop is missing."""
    if not is_wsl():
        return None
    found = shutil.which("powershell.exe")
    if found:
        return found
    return POWERSHELL_FALLBACK if os.access(POWERSHELL_FALLBACK, os.X_OK) else None


def has_windows_interop() -> bool:
    return powershell() is not None


def run_powershell(script: str, timeout: float = 20.0) -> str | None:
    """Runs a PowerShell script and returns its output, or None on failure.

    The output is forced to UTF-8: by default PowerShell writes in the console
    code page, which would mangle accented characters as they cross the border.
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
        logger.warning("PowerShell unreachable: %s", error)
        return None
    if result.returncode != 0:
        logger.warning(
            "PowerShell failed (%s): %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace").strip()[:200],
        )
        return None
    return result.stdout.decode("utf-8", "replace")


def powershell_literal(text: str) -> str:
    """A single-quoted PowerShell string, where only the quote is escaped."""
    return "'" + text.replace("'", "''") + "'"


def wsl_distro() -> str:
    return os.environ.get("WSL_DISTRO_NAME", "")


def wsl_exe() -> str:
    """wsl.exe as seen from Windows: it is what will call the program back."""
    return shutil.which("wsl.exe") or WSL_EXE_FALLBACK


def windows_path(path: Path | str) -> str | None:
    """Translates a Linux path into a Windows path (C:\\...) via wslpath."""
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
