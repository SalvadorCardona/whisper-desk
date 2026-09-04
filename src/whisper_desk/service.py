"""Starting the daemon: systemd, launchd, or a direct launch.

None of these managers is available everywhere — systemd does not exist on
macOS and is not always there under WSL, launchd only exists on macOS. The
direct launch is the safety net: a plain detached process, which works
everywhere and is enough for the first shortcut to do something.
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

logger = logging.getLogger("whisper-desk.service")

SYSTEMD = "systemd"
LAUNCHD = "launchd"
DIRECT = "direct"

UNIT = "whisper-desk.service"
LAUNCH_LABEL = "fr.whisperdesk.daemon"

UNIT_PATH = Path.home() / ".config/systemd/user" / UNIT
AGENT_PATH = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_LABEL}.plist"
LOG_PATH = config_module.STATE_DIR / "daemon.log"


def has_systemd() -> bool:
    """systemd present *and* running: under WSL without systemd, systemctl exists but fails."""
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
    """Starts the daemon by the best means available."""
    current = manager()
    if current == SYSTEMD:
        try:
            subprocess.run(
                ["systemctl", "--user", "start", UNIT],
                check=True, capture_output=True, timeout=15,
            )
            return True
        except (OSError, subprocess.SubprocessError) as error:
            logger.debug("systemd did not start the service (%s) — launching directly.", error)
    elif current == LAUNCHD:
        if _launchctl("kickstart", "-k", _domain_target()) or _launchctl("start", LAUNCH_LABEL):
            return True
        logger.debug("launchd did not start the agent — launching directly.")
    return start_directly()


def start_directly() -> bool:
    """Launches "whisper-desk daemon" as a detached process, with no manager.

    The same interpreter and the same environment as the client: it is the
    installed launcher that set PYTHONPATH and the CUDA libraries.
    """
    try:
        config_module.STATE_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_PATH.open("a", encoding="utf-8")
    except OSError:
        log = None
    try:
        subprocess.Popen(
            [sys.executable, "-m", "whisper_desk", "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log else subprocess.DEVNULL,
            start_new_session=True,   # outlives the client
            cwd=str(Path.home()),
        )
        return True
    except OSError as error:
        logger.warning("Cannot start the daemon directly: %s", error)
        return False
    finally:
        if log is not None:
            log.close()


def status() -> str:
    """Returns "active", "inactive", or the reason why we cannot tell."""
    current = manager()
    if current == SYSTEMD:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", UNIT],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return result.stdout.strip() or "unknown"
    if current == LAUNCHD:
        if not AGENT_PATH.exists():
            return "not installed"
        return "active" if _launchctl("list", LAUNCH_LABEL) else "inactive"
    return "no manager (started on demand)"


def hint() -> str:
    """How to start the daemon by hand, on this host."""
    return {
        SYSTEMD: f"systemctl --user start {UNIT}",
        LAUNCHD: f"launchctl start {LAUNCH_LABEL}",
        DIRECT: "whisper-desk daemon &",
    }[manager()]
