# linux-whisper

**Dictée vocale hors-ligne pour Linux.** Vous appuyez sur `Super + J`, un petit overlay
apparaît — un micro et trois points qui dansent au rythme de votre voix — vous parlez,
vous vous taisez : le texte est transcrit **en local** et copié dans le presse-papiers.

<p align="center">
  <img src="docs/overlay-listening.png" alt="Overlay pendant l'écoute" width="336">
  &nbsp;&nbsp;
  <img src="docs/overlay-working.png" alt="Overlay pendant la transcription" width="336">
</p>

Aucune donnée ne quitte la machine : la transcription tourne sur votre GPU (ou votre CPU)
avec [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

---

## Installation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/linux-whisper/main/install.sh | sh
```

C'est tout. Le script :

1. vérifie les dépendances système (micro, presse-papiers, notifications, GTK4) et propose
   de les installer ;
2. crée un environnement Python isolé et y installe faster-whisper — plus les bibliothèques
   CUDA si une carte NVIDIA est détectée ;
3. installe la commande `linux-whisper` dans `~/.local/bin` ;
4. active le service utilisateur systemd, **démarré automatiquement à l'ouverture de session** ;
5. enregistre le raccourci `Super + J` dans GNOME.

Le modèle Whisper (quelques centaines de Mo) se télécharge au premier démarrage du service.

> **Prérequis** — Linux avec GNOME (Wayland ou X11), `systemd` en session utilisateur,
> un micro. Un GPU NVIDIA est un plus, pas une obligation.

### Vérifier que tout est en place

```sh
linux-whisper doctor
```

---

## Utilisation

| Geste | Effet |
|---|---|
| `Super + J` | démarre l'écoute — l'overlay apparaît |
| silence de ~1,6 s | arrête l'écoute et lance la transcription |
| `Super + J` (à nouveau) | arrête l'écoute immédiatement, sans attendre le silence |

Le texte transcrit est copié dans le presse-papiers, avec une notification. Il ne reste
qu'à faire `Ctrl + V`.

### En ligne de commande

```sh
linux-whisper record     # dicte et écrit le texte sur la sortie standard
linux-whisper toggle     # équivalent du raccourci clavier
linux-whisper status     # état du daemon, modèle chargé, GPU ou CPU
linux-whisper doctor     # diagnostic complet
linux-whisper config     # ouvre la configuration dans $EDITOR
linux-whisper reload     # recharge la configuration sans redémarrer
```

`linux-whisper record` est pratique dans un terminal ou dans un agent :
la transcription part sur `stdout`, prête à être redirigée.

---

## Configuration

Tout est paramétrable dans **`~/.config/linux-whisper/config.toml`** :

```toml
[hotkey]
binding = "<Super>j"          # <Ctrl>, <Alt>, <Shift>, <Super> + une touche

[model]
name = "auto"                 # auto | tiny | base | small | medium | large-v3 | large-v3-turbo
device = "auto"               # auto | cuda | cpu
language = "fr"               # code ISO, ou "auto" pour la détection
initial_prompt = ""           # vocabulaire à privilégier (noms propres, jargon)

[recording]
silence_seconds = 1.6         # arrêt automatique après ce silence ; 0 = désactivé
max_seconds = 120

[output]
mode = "clipboard"            # clipboard | type | stdout | none — combinables : "clipboard+type"
paste = false                 # colle tout seul (nécessite wtype ou ydotool)
notify = true
history = true                # journal dans ~/.local/state/linux-whisper/history.log

[overlay]
enabled = true
accent = "#e46212"
```

Après modification :

```sh
linux-whisper reload            # pour tout sauf le raccourci
linux-whisper hotkey install    # pour appliquer un nouveau raccourci
```

### Choisir son modèle

| Modèle | VRAM | Vitesse | Qualité |
|---|---|---|---|
| `small` | ~1 Go | très rapide | correcte — défaut sans GPU |
| `medium` | ~2,5 Go | rapide | bonne |
| `large-v3-turbo` | ~2 Go | rapide | excellente — **défaut avec GPU** |
| `large-v3` | ~4,5 Go | plus lent | la meilleure |

---

## Comment ça marche

```
Super + J  ─→  linux-whisper toggle  ─→  socket Unix  ─→  daemon (modèle en mémoire)
                                                              │
                              overlay GTK4 ←── niveau audio ───┤
                                                              │
                              arecord ─→ détection de silence ─┤
                                                              │
                              faster-whisper ─→ texte ─→ presse-papiers + notification
```

Le daemon garde le modèle chargé en permanence : la transcription démarre sans délai
d'initialisation. L'overlay est un processus séparé, lancé avec le Python système —
c'est aussi lui qui pose le texte dans le presse-papiers, car sous Wayland seule une
fenêtre focalisée en a le droit.

---

## Dépannage

**Le raccourci ne fait rien**
```sh
systemctl --user status linux-whisper     # le service tourne-t-il ?
journalctl --user -u linux-whisper -f     # les logs, en direct
linux-whisper hotkey show                 # le raccourci est-il enregistré ?
```

**Rien n'est transcrit** — vérifiez le micro et son volume :
```sh
arecord -d 3 -f S16_LE -r 16000 /tmp/test.wav && aplay /tmp/test.wav
```
Un micro trop faible n'atteint jamais le seuil de détection : fixez-le à la main avec
`threshold = 400` (au lieu de `"auto"`) dans `[recording]`.

**La transcription tourne sur le CPU alors que j'ai un GPU** — `linux-whisper status`
indique le périphérique retenu, et `journalctl --user -u linux-whisper` la raison du repli
(souvent des bibliothèques CUDA absentes ou une VRAM insuffisante).

**Le presse-papiers reste vide** — installez `wl-clipboard` (`sudo apt install wl-clipboard`) ;
c'est le chemin le plus fiable, le repli GTK n'étant utilisé qu'à défaut.

---

## Désinstallation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/linux-whisper/main/uninstall.sh | sh
```

Ajoutez `LW_PURGE=1` pour supprimer aussi la configuration et l'historique. Les modèles
téléchargés restent dans `~/.cache/huggingface`.

---

## Développement

```sh
git clone https://github.com/SalvadorCardona/linux-whisper
cd linux-whisper
LW_SRC="$PWD" sh install.sh     # installe depuis le clone local, sans réseau
```

Structure :

| Fichier | Rôle |
|---|---|
| `src/linux_whisper/daemon.py` | service, socket Unix, machine à états |
| `src/linux_whisper/recorder.py` | capture `arecord` + détection de silence |
| `src/linux_whisper/transcriber.py` | faster-whisper, choix GPU/CPU |
| `src/linux_whisper/overlay.py` | overlay GTK4 (processus séparé) |
| `src/linux_whisper/output.py` | presse-papiers, frappe clavier, notifications |
| `src/linux_whisper/hotkey.py` | raccourci global via `gsettings` |
| `install.sh` | installation complète |

## Licence

MIT
