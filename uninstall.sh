#!/bin/sh
# Désinstallation complète de linux-whisper.
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/linux-whisper/main/uninstall.sh | sh
# Ajoutez LW_PURGE=1 pour supprimer aussi la configuration et l'historique.
set -eu

say() { printf '==> %s\n' "$1"; }

if command -v systemctl >/dev/null 2>&1; then
    say "Arrêt du service"
    systemctl --user disable --now linux-whisper.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/linux-whisper.service"
    systemctl --user daemon-reload || true
fi

if [ -x "$HOME/.local/bin/linux-whisper" ]; then
    say "Suppression du raccourci clavier"
    "$HOME/.local/bin/linux-whisper" hotkey remove >/dev/null 2>&1 || true
fi

say "Suppression des fichiers"
rm -f "$HOME/.local/bin/linux-whisper"
rm -rf "$HOME/.local/share/linux-whisper"

if [ "${LW_PURGE:-0}" = "1" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/linux-whisper"
    rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/linux-whisper"
    say "Configuration et historique supprimés"
else
    say "Configuration conservée (LW_PURGE=1 pour la supprimer)"
fi

printf '\nlinux-whisper est désinstallé.\n'
printf 'Les modèles Whisper restent dans ~/.cache/huggingface (rm -rf pour les enlever).\n'
