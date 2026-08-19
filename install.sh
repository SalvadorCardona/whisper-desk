#!/bin/sh
# Installation de linux-whisper.
#
#   curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/linux-whisper/main/install.sh | sh
#
# Variables d'environnement acceptées :
#   LW_REPO   dépôt source           (défaut : SalvadorCardona/linux-whisper)
#   LW_REF    branche ou tag         (défaut : main)
#   LW_SRC    dossier local à copier  (installation depuis un clone, sans réseau)
#   LW_NO_SERVICE=1   n'installe pas le service systemd
#   LW_NO_HOTKEY=1    n'installe pas le raccourci clavier
set -eu

LW_REPO="${LW_REPO:-SalvadorCardona/linux-whisper}"
LW_REF="${LW_REF:-main}"

APP_DIR="$HOME/.local/share/linux-whisper/app"
VENV_DIR="$HOME/.local/share/linux-whisper/venv"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/linux-whisper"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/linux-whisper"
CONFIG="$CONFIG_DIR/config.toml"
UNIT_DIR="$HOME/.config/systemd/user"

BOLD=""; DIM=""; GREEN=""; YELLOW=""; RESET=""
if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m'); RESET=$(printf '\033[0m')
fi

say()  { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$1"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '%serreur:%s %s\n' "$BOLD" "$RESET" "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 1. dépendances système -------------------------------------------------
say "Vérification des dépendances système"
MISSING=""
have arecord      || MISSING="$MISSING alsa-utils"
have notify-send  || MISSING="$MISSING libnotify-bin"
if ! have wl-copy && ! have xclip && ! have xsel; then MISSING="$MISSING wl-clipboard"; fi
if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
    MISSING="$MISSING python3-gi gir1.2-gtk-4.0"
fi

if [ -n "$MISSING" ]; then
    if have apt-get; then
        warn "paquets manquants :$MISSING"
        INSTALLED=0
        if (exec 3</dev/tty) 2>/dev/null; then
            printf '    Les installer avec sudo apt ? [O/n] '
            read -r answer </dev/tty || answer="n"
            case "$answer" in
                ""|o|O|y|Y|oui|yes)
                    # shellcheck disable=SC2086
                    sudo apt-get update && sudo apt-get install -y $MISSING && INSTALLED=1
                    ;;
            esac
        fi
        [ "$INSTALLED" = 1 ] || warn "à installer :${BOLD} sudo apt install$MISSING${RESET}"
    else
        warn "paquets manquants (équivalents à installer) :$MISSING"
    fi
else
    ok "micro, presse-papiers, notifications et GTK4 disponibles"
fi

# --- 2. récupération des sources -------------------------------------------
mkdir -p "$APP_DIR" "$BIN_DIR" "$CONFIG_DIR"
if [ -n "${LW_SRC:-}" ]; then
    say "Copie des sources depuis $LW_SRC"
    [ -d "$LW_SRC/src/linux_whisper" ] || die "$LW_SRC ne contient pas src/linux_whisper"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR"
    tar -C "$LW_SRC" --exclude='.git' --exclude='__pycache__' -cf - . | tar -C "$APP_DIR" -xf -
else
    say "Téléchargement de $LW_REPO ($LW_REF)"
    have curl || die "curl est requis"
    have tar  || die "tar est requis"
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT INT TERM
    curl -fsSL "https://codeload.github.com/$LW_REPO/tar.gz/refs/heads/$LW_REF" -o "$TMP/src.tar.gz" \
        || die "téléchargement impossible (dépôt privé ou branche inexistante ?)"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR"
    tar -xzf "$TMP/src.tar.gz" -C "$APP_DIR" --strip-components=1
fi
ok "sources dans $APP_DIR"

# --- 3. environnement Python isolé -----------------------------------------
if ! have uv; then
    say "Installation de uv (gestionnaire d'environnements Python)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "installation de uv impossible"
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
[ -x "$UV" ] || die "uv introuvable après installation"
ok "uv : $UV"

if [ -x "$VENV_DIR/bin/python" ]; then
    say "Mise à jour de l'environnement Python existant"
else
    say "Création de l'environnement Python (3.12)"
fi
"$UV" venv --python 3.12 --allow-existing "$VENV_DIR" >/dev/null \
    || die "création de l'environnement Python impossible"
say "Installation de faster-whisper"
VIRTUAL_ENV="$VENV_DIR"; export VIRTUAL_ENV
"$UV" pip install --quiet faster-whisper || die "installation de faster-whisper impossible"
ok "faster-whisper installé"

if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
    say "GPU NVIDIA détecté — ajout des bibliothèques CUDA"
    "$UV" pip install --quiet "nvidia-cublas-cu12" "nvidia-cudnn-cu12>=9,<10" \
        && ok "cuBLAS + cuDNN installés" \
        || warn "CUDA non installé — la transcription tournera sur le CPU"
else
    warn "pas de GPU NVIDIA — transcription sur CPU (modèle « small » par défaut)"
fi

# --- 4. exécutable ----------------------------------------------------------
SYSTEM_PYTHON="$(command -v python3 || echo /usr/bin/python3)"
sed -e "s|@APP_DIR@|$APP_DIR|g" \
    -e "s|@VENV@|$VENV_DIR|g" \
    -e "s|@SYSTEM_PYTHON@|$SYSTEM_PYTHON|g" \
    "$APP_DIR/bin/linux-whisper.in" > "$BIN"
chmod +x "$BIN"
ok "commande installée : $BIN"

# --- 5. configuration -------------------------------------------------------
if [ -f "$CONFIG" ]; then
    ok "configuration existante conservée : $CONFIG"
else
    cp "$APP_DIR/config.example.toml" "$CONFIG"
    ok "configuration créée : $CONFIG"
fi

# --- 6. service utilisateur (démarrage automatique) -------------------------
if [ "${LW_NO_SERVICE:-0}" != "1" ] && have systemctl; then
    say "Installation du service (démarrage à l'ouverture de session)"
    mkdir -p "$UNIT_DIR"
    sed -e "s|@BIN@|$BIN|g" "$APP_DIR/systemd/linux-whisper.service.in" \
        > "$UNIT_DIR/linux-whisper.service"
    systemctl --user daemon-reload
    systemctl --user enable linux-whisper.service >/dev/null 2>&1 || warn "enable a échoué"
    systemctl --user restart linux-whisper.service >/dev/null 2>&1 || warn "démarrage différé à la prochaine session"
    ok "service linux-whisper.service activé"
fi

# --- 7. raccourci clavier ---------------------------------------------------
if [ "${LW_NO_HOTKEY:-0}" != "1" ]; then
    say "Installation du raccourci clavier"
    "$BIN" hotkey install || warn "raccourci à créer à la main sur « $BIN toggle »"
fi

# --- 8. résumé --------------------------------------------------------------
BINDING=$(grep -E '^\s*binding' "$CONFIG" | head -1 | cut -d'"' -f2)
printf '\n%sinstallation terminée.%s\n\n' "$BOLD" "$RESET"
printf '  Appuyez sur %s%s%s, parlez, puis marquez un silence :\n' "$BOLD" "${BINDING:-<Super>j}" "$RESET"
printf '  le texte est transcrit hors-ligne et copié dans le presse-papiers.\n\n'
printf '  %sconfiguration%s  %s\n' "$DIM" "$RESET" "$CONFIG"
printf '  %sdiagnostic%s     linux-whisper doctor\n' "$DIM" "$RESET"
printf '  %sdictée CLI%s     linux-whisper record\n\n' "$DIM" "$RESET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) printf '  %s!%s ajoutez %s à votre PATH : echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.bashrc\n\n' "$YELLOW" "$RESET" "$BIN_DIR" ;;
esac
printf '  %sLe modèle se télécharge au premier démarrage (quelques centaines de Mo).%s\n\n' "$DIM" "$RESET"
