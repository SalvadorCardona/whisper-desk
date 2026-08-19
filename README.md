# linux-whisper

**Dictée vocale hors-ligne pour Linux.** Vous appuyez sur `Super + J`, un petit overlay
apparaît — un micro et trois points qui dansent au rythme de votre voix — et le texte
**s'écrit directement là où se trouve votre curseur**, phrase après phrase, pendant que
vous parlez.

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

1. vérifie les dépendances système (micro, presse-papiers, notifications, GTK) et propose
   de les installer ;
2. crée un environnement Python isolé et y installe faster-whisper — plus les bibliothèques
   CUDA si une carte NVIDIA est détectée ;
3. installe la commande `linux-whisper` dans `~/.local/bin` ;
4. active le service utilisateur systemd, **démarré automatiquement à l'ouverture de session** ;
5. enregistre le raccourci `Super + J` dans GNOME.

Le modèle Whisper (quelques centaines de Mo) se télécharge au premier démarrage du service.

Relancer la même commande **met à jour** l'installation : le code est remplacé, le service
redémarré, et votre configuration comme vos modèles sont conservés.

> **Prérequis** — Linux avec GNOME (Wayland ou X11), `systemd` en session utilisateur, un
> micro. Un GPU NVIDIA est un plus, pas une obligation.

### Vérifier que tout est en place

```sh
linux-whisper doctor
```

---

## Utilisation

| Geste | Effet |
|---|---|
| `Super + J` | démarre l'écoute — l'overlay apparaît |
| une petite pause (~0,6 s) | la phrase est transcrite et **insérée au curseur**, l'écoute continue |
| un silence de 2 s | fin de la dictée |
| `Super + J` (à nouveau) | arrête l'écoute immédiatement |

Le texte s'insère dans l'application qui a le focus : éditeur, navigateur, messagerie,
champ de recherche. Votre presse-papiers est rendu intact à la fin de la dictée.

### En ligne de commande

```sh
linux-whisper record     # dicte et écrit le texte sur la sortie standard
linux-whisper toggle     # équivalent du raccourci clavier
linux-whisper status     # état du daemon, modèle chargé, GPU ou CPU
linux-whisper doctor     # diagnostic complet
linux-whisper config     # ouvre la configuration dans $EDITOR
linux-whisper reload     # recharge la configuration sans redémarrer
```

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
streaming = true              # insertion au fil de l'eau, phrase par phrase
segment_silence_seconds = 0.6 # pause qui découpe une phrase
silence_seconds = 2.0         # silence qui met fin à la dictée
max_seconds = 120

[output]
mode = "cursor"               # cursor | clipboard | stdout — combinables : "cursor+stdout"
paste_shortcut = "ctrl+v"     # "shift+insert" si vous dictez surtout en terminal
restore_clipboard = true      # rend votre presse-papiers d'origine à la fin
notify = false
history = true                # journal dans ~/.local/state/linux-whisper/history.log

[overlay]
enabled = true
accent = "#e46212"
position = "bottom-center"    # bottom-center | top-center | center
margin = 96
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

Pour raccourcir encore le délai entre la fin d'une phrase et son insertion, baissez
`beam_size` à `1` dans `[model]`.

---

## Comment ça marche

```
Super + J  ─→  linux-whisper toggle  ─→  socket Unix  ─→  daemon (modèle en mémoire)
                                                              │
                              overlay X11 ←── niveau audio ────┤
                                                              │
     arecord ─→ détection de silence ─→ phrase ─→ faster-whisper ─→ texte
                                                              │
                        presse-papiers + Ctrl+V (clavier virtuel) ─→ curseur
```

Le daemon garde le modèle chargé en permanence, et transcrit une phrase pendant que le
micro enregistre déjà la suivante.

Trois contraintes de Wayland ont façonné cette architecture :

- **Un client ne peut pas taper dans la fenêtre d'un autre.** Le protocole
  `virtual-keyboard` (celui de `wtype`) n'est pas implémenté par GNOME. On passe donc par
  un clavier virtuel du noyau (`/dev/uinput`, accessible sans privilèges grâce à l'ACL
  posée par systemd) qui envoie un simple raccourci de collage.
- **Envoyer le texte touche par touche supposerait de connaître la carte XKB active.**
  Sur un clavier AZERTY, les accents et la moitié des lettres tomberaient à côté ; le
  raccourci de collage, lui, occupe la même touche physique partout. Le texte transite
  donc par le presse-papiers, qui est restauré ensuite.
- **Une fenêtre Wayland ne peut ni refuser le focus ni se positionner.** Un overlay
  Wayland capterait le collage à la place de votre application. L'overlay est donc un
  client X11 (via Xwayland) de type `NOTIFICATION` : jamais focalisé, et positionnable.

---

## Dépannage

**Le raccourci ne fait rien**
```sh
systemctl --user status linux-whisper     # le service tourne-t-il ?
journalctl --user -u linux-whisper -f     # les logs, en direct
linux-whisper hotkey show                 # le raccourci est-il enregistré ?
```

**Le texte n'est pas inséré mais reste dans le presse-papiers** — le clavier virtuel n'a
pas pu être créé. Vérifiez `linux-whisper doctor` : `/dev/uinput` doit être accessible en
écriture. Sur une session locale, systemd vous en donne l'accès automatiquement ; en SSH
ou en session distante, ce n'est pas le cas.

**Je dicte dans un terminal et j'obtiens `^V`** — `Ctrl+V` n'y est pas le collage. Mettez
`paste_shortcut = "shift+insert"` dans `[output]`, puis `linux-whisper reload`.

**Les phrases se coupent trop tôt / trop tard** — ajustez `segment_silence_seconds`
(découpage) et `silence_seconds` (fin de dictée) dans `[recording]`.

**Rien n'est transcrit** — vérifiez le micro et son volume :
```sh
arecord -d 3 -f S16_LE -r 16000 /tmp/test.wav && aplay /tmp/test.wav
```
Un micro trop faible n'atteint jamais le seuil de détection : fixez-le à la main avec
`threshold = 400` (au lieu de `"auto"`) dans `[recording]`.

**La transcription tourne sur le CPU alors que j'ai un GPU** — `linux-whisper status`
indique le périphérique retenu, et `journalctl --user -u linux-whisper` la raison du repli
(souvent des bibliothèques CUDA absentes ou une VRAM insuffisante).

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

| Fichier | Rôle |
|---|---|
| `src/linux_whisper/daemon.py` | service, socket Unix, écoute et transcription en parallèle |
| `src/linux_whisper/recorder.py` | capture `arecord`, détection de silence, découpage en phrases |
| `src/linux_whisper/transcriber.py` | faster-whisper, choix GPU/CPU |
| `src/linux_whisper/inject.py` | clavier virtuel `/dev/uinput` |
| `src/linux_whisper/output.py` | insertion au curseur, presse-papiers, notifications |
| `src/linux_whisper/overlay.py` | overlay X11 (processus séparé) |
| `src/linux_whisper/hotkey.py` | raccourci global via `gsettings` |
| `install.sh` | installation et mise à jour |

## Licence

MIT
