#!/bin/sh
# Désinstallation complète de whisper-desk (Linux, WSL et macOS).
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/whisper-desk/main/uninstall.sh | sh
# Ajoutez WD_PURGE=1 pour supprimer aussi la configuration et l'historique.
set -eu

AGENT_LABEL="fr.whisperdesk.daemon"
AGENT="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"

say() { printf '==> %s\n' "$1"; }

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    say "Arrêt du service"
    systemctl --user disable --now whisper-desk.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/whisper-desk.service"
    systemctl --user daemon-reload || true
fi

if command -v launchctl >/dev/null 2>&1 && [ -f "$AGENT" ]; then
    say "Arrêt de l'agent launchd"
    launchctl bootout "gui/$(id -u)/$AGENT_LABEL" >/dev/null 2>&1 \
        || launchctl unload -w "$AGENT" >/dev/null 2>&1 || true
    rm -f "$AGENT"
fi

if [ -x "$HOME/.local/bin/whisper-desk" ]; then
    say "Arrêt du daemon et suppression du raccourci clavier"
    "$HOME/.local/bin/whisper-desk" quit >/dev/null 2>&1 || true
    "$HOME/.local/bin/whisper-desk" hotkey remove >/dev/null 2>&1 || true
fi

say "Suppression des fichiers"
rm -f "$HOME/.local/bin/whisper-desk"
rm -rf "$HOME/.local/share/whisper-desk"

if [ "${WD_PURGE:-0}" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/whisper-desk"
    rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/whisper-desk"
    say "Configuration et historique supprimés"
else
    say "Configuration conservée (WD_PURGE=1 pour la supprimer)"
fi

printf '\nwhisper-desk est désinstallé.\n'
printf 'Les modèles Whisper restent dans ~/.cache/huggingface (rm -rf pour les enlever).\n'
