"""Starting the daemon: systemd, launchd, or a direct launch.

None of these managers is available everywhere — systemd does not exist on
macOS and is not always there under WSL, launchd only exists on macOS. The
direct launch is the safety net: a plain detached process, which works
everywhere and is enough for the first shortcut to do something.
"""

from __future__ import annotations

import logging
import os
import signal
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

# How a daemon started without a manager shows up in the process table.
DAEMON_PATTERN = "whisper_desk daemon"

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


def force_stop() -> bool:
    """Puts the daemon down whatever it is doing, and with it the open dictation.

    The way out when the daemon no longer answers on its socket: its window
    would otherwise stay on screen and its microphone open, with no shortcut
    left to close them. The next dictation starts a fresh daemon.
    """
    current = manager()
    if current == SYSTEMD:
        try:
            # The whole unit, children included: the overlay is one of them.
            subprocess.run(
                ["systemctl", "--user", "kill", "--signal=SIGKILL", UNIT],
                check=True, capture_output=True, timeout=15,
            )
            return True
        except (OSError, subprocess.SubprocessError) as error:
            logger.debug("systemd did not kill the service (%s) — killing directly.", error)
    elif current == LAUNCHD and _launchctl("kill", "SIGKILL", _domain_target()):
        return True
    return kill_directly()


def kill_directly() -> bool:
    """Kills the running daemons, and the dictation their process group holds.

    start_directly() gives the daemon a session of its own, so its group holds
    the whole dictation — the overlay included, which would otherwise survive
    its parent. A daemon started by hand shares the group of the current
    shell: there, it alone is killed.
    """
    killed = False
    for pid in _daemon_pids():
        try:
            group = os.getpgid(pid)
            if group == os.getpgrp():
                os.kill(pid, signal.SIGKILL)
            else:
                os.killpg(group, signal.SIGKILL)
            killed = True
        except OSError as error:
            logger.debug("Cannot kill the daemon %d: %s", pid, error)
    return killed


def _daemon_pids() -> list[int]:
    """The daemons of the current user, seen from the process table."""
    try:
        result = subprocess.run(
            ["pgrep", "-u", str(os.getuid()), "-f", DAEMON_PATTERN],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.debug("pgrep unavailable: %s", error)
        return []
    return [int(line) for line in result.stdout.split() if line.isdigit()]


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
