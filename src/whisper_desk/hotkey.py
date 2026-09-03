"""Enregistrement du raccourci global, chez le gestionnaire de l'hôte.

Personne ne s'accorde sur la question : GNOME range les raccourcis dans
gsettings, Windows les attache à un raccourci du menu Démarrer, macOS n'expose
rien du tout — il faut y passer par un agent tiers (skhd) ou par la main de
l'utilisateur. Chaque hôte a donc son greffon, derrière la même interface.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from . import host

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = f"{SCHEMA}.custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
SLOT = "whisper-desk"
KEY_PATH = f"{BASE_PATH}/{SLOT}/"

SHORTCUT_NAME = "whisper-desk"
SKHD_CONFIG = os.path.expanduser("~/.config/skhd/skhdrc")
SKHD_MARK = "# whisper-desk"


class UnsupportedDesktop(RuntimeError):
    """Aucun moyen automatique d'installer le raccourci ici."""


# -- syntaxe des raccourcis ---------------------------------------------------

MODIFIER_NAMES = {
    "super": "super", "cmd": "super", "command": "super", "meta": "super",
    "win": "super", "windows": "super",
    "ctrl": "ctrl", "control": "ctrl", "primary": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
}
MODIFIER_ORDER = ("ctrl", "alt", "shift", "super")
GTK_MODIFIERS = {"ctrl": "<Ctrl>", "alt": "<Alt>", "shift": "<Shift>", "super": "<Super>"}


def parse_binding(binding: str) -> tuple[list[str], str]:
    """« <Ctrl><Alt>j » ou « ctrl+alt+j » -> (["ctrl", "alt"], "j")."""
    tokens: list[str] = []
    rest = binding.strip()
    while rest.startswith("<") and ">" in rest:
        end = rest.index(">")
        tokens.append(rest[1:end])
        rest = rest[end + 1:].strip()
    tokens += [part for part in rest.replace("+", " ").split() if part]

    modifiers: list[str] = []
    key = ""
    for token in tokens:
        canonical = MODIFIER_NAMES.get(token.lower())
        if canonical:
            if canonical not in modifiers:
                modifiers.append(canonical)
        else:
            key = token
    modifiers.sort(key=MODIFIER_ORDER.index)
    return modifiers, key.lower()


def format_gtk(modifiers: list[str], key: str) -> str:
    return "".join(GTK_MODIFIERS[modifier] for modifier in modifiers) + key


def default_binding() -> str:
    """Le raccourci proposé quand la configuration dit « auto ».

    Windows garde la touche Windows pour ses propres raccourcis, et n'accepte
    d'ailleurs que des combinaisons à base de Ctrl+Alt.
    """
    return "<Ctrl><Alt>j" if host.is_wsl() else "<Super>j"


def resolve_binding(config: dict[str, Any]) -> str:
    binding = str(config["hotkey"]["binding"]).strip()
    return default_binding() if not binding or binding.lower() == "auto" else binding


# -- GNOME --------------------------------------------------------------------

def _gsettings(*args: str) -> str:
    result = subprocess.run(
        ["gsettings", *args], check=True, capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def is_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("DESKTOP_SESSION", "")
    return "GNOME" in desktop.upper() or "UNITY" in desktop.upper()


def _bindings() -> list[str]:
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    if raw in ("@as []", "[]", ""):
        return []
    return [item.strip().strip("'\"") for item in raw.strip("[]").split(",") if item.strip()]


def _write_bindings(paths: list[str]) -> None:
    serialized = "[" + ", ".join(f"'{path}'" for path in paths) + "]"
    _gsettings("set", SCHEMA, "custom-keybindings", serialized)


class GnomeHotkey:
    """Raccourci personnalisé de GNOME, posé dans gsettings."""

    name = "GNOME"

    def check(self) -> None:
        if not shutil.which("gsettings"):
            raise UnsupportedDesktop("gsettings introuvable")
        if not is_gnome():
            raise UnsupportedDesktop(
                f"bureau non géré ({os.environ.get('XDG_CURRENT_DESKTOP', 'inconnu')})"
            )

    def install(self, binding: str, name: str, command: str) -> str:
        self.check()
        paths = _bindings()
        if KEY_PATH not in paths:
            paths.append(KEY_PATH)
            _write_bindings(paths)
        target = f"{CUSTOM_SCHEMA}:{KEY_PATH}"
        _gsettings("set", target, "name", name)
        _gsettings("set", target, "command", command)
        _gsettings("set", target, "binding", binding)
        return binding

    def remove(self) -> None:
        self.check()
        _write_bindings([path for path in _bindings() if path != KEY_PATH])

    def show(self) -> dict[str, str]:
        self.check()
        if KEY_PATH not in _bindings():
            return {}
        target = f"{CUSTOM_SCHEMA}:{KEY_PATH}"
        return {
            "name": _gsettings("get", target, "name").strip("'"),
            "command": _gsettings("get", target, "command").strip("'"),
            "binding": _gsettings("get", target, "binding").strip("'"),
        }


# -- Windows (WSL) ------------------------------------------------------------

# Windows n'accepte de raccourci global que sur un .lnk du menu Démarrer ou du
# bureau, et seulement en Ctrl+Alt (éventuellement complété par Maj).
WINDOWS_KEYS = {"space": "SPACE", "enter": "ENTER", "insert": "INS"}
LINK_NAME = "whisper-desk.lnk"
START_MENU = "$env:APPDATA + '\\Microsoft\\Windows\\Start Menu\\Programs\\" + LINK_NAME + "'"


def format_windows(modifiers: list[str], key: str) -> str:
    """« CTRL+ALT+J », ou lève UnsupportedDesktop si Windows n'en veut pas."""
    if "super" in modifiers:
        raise UnsupportedDesktop(
            "Windows se réserve la touche Windows : choisissez un raccourci "
            "en Ctrl+Alt, par exemple « <Ctrl><Alt>j »"
        )
    if "ctrl" not in modifiers or not ("alt" in modifiers or "shift" in modifiers):
        raise UnsupportedDesktop(
            "Windows n'accepte que les raccourcis Ctrl+Alt+touche (ou Ctrl+Maj+touche)"
        )
    if not key:
        raise UnsupportedDesktop("raccourci sans touche finale")
    names = {"ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT"}
    return "+".join(names[modifier] for modifier in modifiers) + "+" + WINDOWS_KEYS.get(
        key, key.upper()
    )


class WindowsHotkey:
    """Raccourci Windows attaché à un .lnk du menu Démarrer, qui rappelle WSL."""

    name = "Windows"

    def check(self) -> None:
        if not host.is_wsl():
            raise UnsupportedDesktop("hôte non WSL")
        if not host.has_windows_interop():
            raise UnsupportedDesktop(
                "interopérabilité Windows indisponible (powershell.exe introuvable)"
            )

    def _script(self, body: str) -> str:
        return f"$path = {START_MENU}; $shell = New-Object -ComObject WScript.Shell; {body}"

    def install(self, binding: str, name: str, command: str) -> str:
        self.check()
        hotkey = format_windows(*parse_binding(binding))
        distro = host.wsl_distro()
        arguments = (f"-d {distro} " if distro else "") + f"-e {command}"
        body = (
            "$link = $shell.CreateShortcut($path);"
            "$link.TargetPath = $env:SystemRoot + '\\System32\\wsl.exe';"
            f"$link.Arguments = {host.powershell_literal(arguments)};"
            f"$link.Description = {host.powershell_literal(name)};"
            "$link.WindowStyle = 7;"
            f"$link.Hotkey = {host.powershell_literal(hotkey)};"
            "$link.Save()"
        )
        if host.run_powershell(self._script(body)) is None:
            raise UnsupportedDesktop("création du raccourci Windows impossible")
        return hotkey

    def remove(self) -> None:
        self.check()
        host.run_powershell(
            self._script("if (Test-Path $path) { Remove-Item $path -Force }")
        )

    def show(self) -> dict[str, str]:
        self.check()
        body = (
            "if (-not (Test-Path $path)) { exit 0 };"
            "$link = $shell.CreateShortcut($path);"
            "$link.Hotkey; $link.Arguments; $link.Description"
        )
        output = host.run_powershell(self._script(body))
        if not output:
            return {}
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return {}
        return {
            "binding": lines[0],
            "command": lines[1] if len(lines) > 1 else "",
            "name": lines[2] if len(lines) > 2 else SHORTCUT_NAME,
        }


# -- macOS --------------------------------------------------------------------

SKHD_MODIFIERS = {"super": "cmd", "ctrl": "ctrl", "alt": "alt", "shift": "shift"}

MACOS_MANUAL = (
    "macOS n'expose pas de raccourci global en ligne de commande. Deux voies : "
    "« brew install skhd && skhd --start-service », puis relancer cette commande ; "
    "ou créer une opération rapide (Automator → Exécuter un script shell) et lui "
    "attribuer un raccourci dans Réglages Système → Clavier → Raccourcis clavier"
)


def format_skhd(modifiers: list[str], key: str) -> str:
    """« cmd - j », la syntaxe de skhd."""
    if not key:
        raise UnsupportedDesktop("raccourci sans touche finale")
    names = [SKHD_MODIFIERS[modifier] for modifier in modifiers]
    return (" + ".join(names) + " - " if names else "") + key


class SkhdHotkey:
    """Raccourci macOS confié à skhd, le seul agent scriptable courant."""

    name = "skhd"

    def check(self) -> None:
        if not shutil.which("skhd"):
            raise UnsupportedDesktop(MACOS_MANUAL)

    def _lines(self) -> list[str]:
        try:
            with open(SKHD_CONFIG, encoding="utf-8") as handle:
                return handle.read().splitlines()
        except OSError:
            return []

    def _without_ours(self) -> list[str]:
        """Retire notre ligne et son commentaire, pour réécrire proprement."""
        kept, skip_next = [], False
        for line in self._lines():
            if line.strip() == SKHD_MARK:
                skip_next = True
                continue
            if skip_next:
                skip_next = False
                if "whisper-desk" in line:
                    continue
            kept.append(line)
        return kept

    def _write(self, lines: list[str]) -> None:
        os.makedirs(os.path.dirname(SKHD_CONFIG), exist_ok=True)
        with open(SKHD_CONFIG, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip("\n") + "\n")

    def _reload(self) -> None:
        subprocess.run(["skhd", "--reload"], capture_output=True, timeout=10, check=False)

    def install(self, binding: str, name: str, command: str) -> str:
        self.check()
        shortcut = format_skhd(*parse_binding(binding))
        self._write(self._without_ours() + [SKHD_MARK, f"{shortcut} : {command}"])
        self._reload()
        return shortcut

    def remove(self) -> None:
        self.check()
        self._write(self._without_ours())
        self._reload()

    def show(self) -> dict[str, str]:
        self.check()
        lines = self._lines()
        for index, line in enumerate(lines):
            if line.strip() == SKHD_MARK and index + 1 < len(lines):
                shortcut, _, command = lines[index + 1].partition(":")
                return {
                    "name": SHORTCUT_NAME,
                    "binding": shortcut.strip(),
                    "command": command.strip(),
                }
        return {}


BACKENDS = {
    host.LINUX: GnomeHotkey,
    host.WSL: WindowsHotkey,
    host.MACOS: SkhdHotkey,
}


def backend():
    """Le greffon de raccourci de l'hôte courant."""
    return BACKENDS[host.name()]()


def install(config: dict[str, Any], command: str) -> str:
    """Crée ou met à jour le raccourci. Retourne la combinaison installée."""
    return backend().install(
        resolve_binding(config), str(config["hotkey"]["name"]), command
    )


def remove() -> None:
    backend().remove()


def show() -> dict[str, str]:
    return backend().show()
