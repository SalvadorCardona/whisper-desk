"""What runs here, what runs upstream, and how to go from one to the other.

The installation in ~/.local/share/whisper-desk/app is a copy without .git:
the only thing that says which code runs there is the fingerprint install.sh
leaves beside it. Everything starts from that file — the comparison with
GitHub as much as the update itself.

The update is install.sh, replayed. Nothing is rebuilt here: the script
already knows how to fetch the sources, bring the environment up to date,
rewrite the command and the service. The only care needed is not to run it
from the directory it begins by wiping.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config as config_module

APP_DIR = config_module.DATA_DIR / "app"
VERSION_PATH = APP_DIR / ".whisper-desk-version"

DEFAULT_REPO = "SalvadorCardona/whisper-desk"
DEFAULT_REF = "main"
COMMIT_API = "https://api.github.com/repos/{repo}/commits/{ref}"
INSTALL_URL = "https://raw.githubusercontent.com/{repo}/{ref}/install.sh"

# Long enough to be unambiguous, short enough to be read out loud.
SHORT = 7
# The network is never allowed to hold the diagnostic up.
DOCTOR_TIMEOUT = 3.0


class UpstreamUnreachable(RuntimeError):
    """Upstream could not be asked: no network, private repository, unknown ref."""


# -- the local fingerprint ---------------------------------------------------

def read_fingerprint(path: Path | None = None) -> dict[str, str]:
    """Reads the key=value fingerprint. An installation without one returns {}."""
    path = path or VERSION_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    fingerprint: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value and value != "unknown":
            fingerprint[key.strip()] = value
    return fingerprint


def repo(fingerprint: dict[str, str]) -> str:
    return fingerprint.get("repo", DEFAULT_REPO)


def ref(fingerprint: dict[str, str]) -> str:
    return fingerprint.get("ref", DEFAULT_REF)


def commit(fingerprint: dict[str, str]) -> str:
    return fingerprint.get("commit", "")


def short(sha: str) -> str:
    return sha[:SHORT]


def describe(fingerprint: dict[str, str]) -> str:
    """The version in one breath: main @ 60e53b1 (2026-09-11)."""
    local = commit(fingerprint)
    if not local:
        return "unknown version"
    described = f"{ref(fingerprint)} @ {short(local)}"
    date = fingerprint.get("date", "")
    return f"{described} ({date[:10]})" if date else described


# -- the upstream commit -----------------------------------------------------

def latest_commit(repository: str, reference: str, timeout: float = 10.0) -> dict[str, str]:
    """The last commit of a ref on GitHub: {"commit": sha, "date": ISO date}.

    Raises UpstreamUnreachable — and nothing else — whatever goes wrong: a
    machine offline, a private repository and a ref that no longer exists all
    deserve a sentence, not a traceback.
    """
    # Imported here: every invocation of the command would otherwise pay for
    # urllib, including the shortcut, where milliseconds are felt.
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        COMMIT_API.format(repo=repository, ref=reference),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "whisper-desk",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # 404 and 422 are the two ways GitHub says "not here": an unknown
        # repository, or a ref it has never heard of. 401/403 cover a private
        # repository and the rate limit.
        if error.code in (401, 403, 404, 422):
            raise UpstreamUnreachable(
                f"{repository}@{reference} out of reach (HTTP {error.code}) — "
                "private repository, nonexistent branch, or GitHub rate limit"
            ) from None
        raise UpstreamUnreachable(f"GitHub answered HTTP {error.code}") from None
    except (OSError, TimeoutError) as error:   # URLError is an OSError
        reason = getattr(error, "reason", error)
        raise UpstreamUnreachable(f"GitHub unreachable ({reason}) — offline?") from None
    except (ValueError, UnicodeDecodeError):
        raise UpstreamUnreachable("GitHub did not answer with a commit") from None

    sha = str(payload.get("sha", "")) if isinstance(payload, dict) else ""
    if not sha:
        raise UpstreamUnreachable(f"{repository}@{reference}: no commit in the answer")
    date = ""
    if isinstance(payload.get("commit"), dict):
        committer = payload["commit"].get("committer")
        if isinstance(committer, dict):
            date = str(committer.get("date", ""))
    return {"commit": sha, "date": date}


# -- the local clone, when the installation came from one --------------------

def local_source(fingerprint: dict[str, str]) -> Path | None:
    """The clone the installation was copied from, if it is still usable."""
    if fingerprint.get("origin") != "local":
        return None
    raw = fingerprint.get("src")
    if not raw:
        return None
    source = Path(raw)
    if (source / "src/whisper_desk").is_dir() and (source / "install.sh").is_file():
        return source
    return None


def source_commit(source: Path) -> str:
    """HEAD of the clone, or "" if it is not a git repository."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# -- replaying the installation ----------------------------------------------

def hotkey_installed() -> bool:
    """True if a shortcut is already registered.

    An update must not rewrite a binding the user has made their own: the
    shortcut is installed once, on the first installation.
    """
    from . import hotkey

    try:
        return bool(hotkey.show())
    except (hotkey.UnsupportedDesktop, OSError, subprocess.SubprocessError):
        return False


def install_env(fingerprint: dict[str, str], keep_hotkey: bool) -> dict[str, str]:
    """The environment install.sh expects to redo exactly this installation."""
    env = dict(os.environ)
    env["WD_REPO"] = repo(fingerprint)
    env["WD_REF"] = ref(fingerprint)
    source = local_source(fingerprint)
    if source is None:
        env.pop("WD_SRC", None)
    else:
        env["WD_SRC"] = str(source)
    if keep_hotkey:
        env["WD_NO_HOTKEY"] = "1"
    else:
        env.pop("WD_NO_HOTKEY", None)
    return env


def fetch_install_script(fingerprint: dict[str, str], destination: Path) -> Path:
    """Puts install.sh outside APP_DIR and returns its path.

    install.sh starts by wiping APP_DIR: run from there, the update would saw
    off the branch it is sitting on.
    """
    import urllib.error
    import urllib.request

    script = destination / "install.sh"
    source = local_source(fingerprint)
    if source is not None:
        shutil.copyfile(source / "install.sh", script)
        return script

    url = INSTALL_URL.format(repo=repo(fingerprint), ref=ref(fingerprint))
    request = urllib.request.Request(url, headers={"User-Agent": "whisper-desk"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            script.write_bytes(response.read())
    except urllib.error.HTTPError as error:
        raise UpstreamUnreachable(
            f"{url} out of reach (HTTP {error.code}) — private repository "
            "or nonexistent branch"
        ) from None
    except (OSError, TimeoutError) as error:
        raise UpstreamUnreachable(f"cannot download install.sh ({error})") from None
    return script


def run_install(fingerprint: dict[str, str], keep_hotkey: bool) -> int:
    """Runs install.sh from a temporary copy and returns its exit code."""
    with tempfile.TemporaryDirectory(prefix="whisper-desk-update-") as tmp:
        script = fetch_install_script(fingerprint, Path(tmp))
        result = subprocess.run(
            ["sh", str(script)], env=install_env(fingerprint, keep_hotkey),
            cwd=str(Path.home()),
        )
    return result.returncode
