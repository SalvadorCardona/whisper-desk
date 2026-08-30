# linux-whisper

**Dictée vocale hors-ligne pour Linux, WSL et macOS.** Vous appuyez sur `Super + J`, un petit overlay
apparaît — un micro et trois points qui dansent au rythme de votre voix — et le texte
**s'écrit directement là où se trouve votre curseur**, phrase après phrase, pendant que
vous parlez.

Chaque point porte un instant différent de ce que capte le micro : l'onde traverse la
pilule au rythme réel de la parole, sur une échelle en décibels — le silence laisse les
points au repos, une voix ordinaire occupe le milieu de la course.

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

C'est tout. Le script reconnaît l'hôte — Linux, WSL ou macOS — et adapte chaque étape :

1. vérifie les dépendances système (micro, presse-papiers, notifications, GTK) et propose
   de les installer, avec `apt` ou `brew` selon le cas ;
2. crée un environnement Python isolé et y installe faster-whisper — plus les bibliothèques
   CUDA si une carte NVIDIA est détectée ;
3. installe la commande `linux-whisper` dans `~/.local/bin` ;
4. active le service utilisateur — **systemd** sous Linux et WSL, **launchd** sur macOS —
   démarré automatiquement à l'ouverture de session ;
5. enregistre le raccourci global auprès du gestionnaire de l'hôte.

Le modèle Whisper (quelques centaines de Mo) se télécharge au premier démarrage du service.

Relancer la même commande **met à jour** l'installation : le code est remplacé, le service
redémarré, et votre configuration comme vos modèles sont conservés.

### Ce que chaque hôte utilise

| | Linux | WSL | macOS |
|---|---|---|---|
| **capture micro** | `arecord` (ALSA) | `parec` (PulseAudio/WSLg) | `rec` (sox) ou `ffmpeg` |
| **presse-papiers** | `wl-copy` / `xclip` | `clip.exe` | `pbcopy` |
| **frappe du collage** | `/dev/uinput` | SendKeys (PowerShell) | System Events (`osascript`) |
| **raccourci global** | GNOME (`gsettings`) | raccourci du menu Démarrer | `skhd`, ou à la main |
| **service** | systemd | systemd, sinon à la demande | launchd |
| **notifications** | `notify-send` | `notify-send` (WSLg) | `osascript` |

Aucun de ces choix n'est figé : `backend`, `keyboard` et `paste_shortcut` se forcent dans
la configuration.

> **Prérequis** — un micro, et selon l'hôte :
>
> - **Linux** : GNOME (Wayland ou X11), `systemd` en session utilisateur.
> - **WSL** : WSL 2 avec WSLg (Windows 11, ou Windows 10 à jour) pour le micro, et
>   l'interopérabilité Windows active. Le texte s'insère dans les fenêtres **Windows**.
> - **macOS** : 12 ou plus récent. Le premier collage demande l'autorisation
>   d'accessibilité (Réglages Système → Confidentialité et sécurité → Accessibilité), et
>   la première dictée l'autorisation micro.
>
> Un GPU NVIDIA est un plus, pas une obligation ; sur macOS la transcription se fait sur
> le CPU, CTranslate2 n'utilisant pas Metal.

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

Le raccourci par défaut suit l'hôte : `Super + J` sous Linux et macOS (`Cmd + J`),
`Ctrl + Alt + J` sous WSL — Windows se réservant la touche Windows.

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
linux-whisper quit       # arrête le daemon
```

---

## Configuration

Tout est paramétrable dans **`~/.config/linux-whisper/config.toml`** :

```toml
[hotkey]
binding = "auto"              # "auto", ou <Ctrl>/<Alt>/<Shift>/<Super> + une touche

[model]
name = "auto"                 # auto | tiny | base | small | medium | large-v3 | large-v3-turbo
device = "auto"               # auto | cuda | cpu
language = "fr"               # code ISO, ou "auto" pour la détection
initial_prompt = ""           # vocabulaire à privilégier (noms propres, jargon)

[recording]
backend = "auto"              # auto | arecord | parec | rec | sox | ffmpeg
streaming = true              # insertion au fil de l'eau, phrase par phrase
segment_silence_seconds = 0.6 # pause qui découpe une phrase
silence_seconds = 2.0         # silence qui met fin à la dictée
max_seconds = 120

[output]
mode = "cursor"               # cursor | clipboard | stdout — combinables : "cursor+stdout"
paste_shortcut = "auto"       # "shift+insert" si vous dictez surtout en terminal
keyboard = "auto"             # auto | uinput | windows | applescript | none
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
 capture micro ─→ détection de silence ─→ phrase ─→ faster-whisper ─→ texte
                                                              │
                          presse-papiers + Ctrl+V (frappe simulée) ─→ curseur
```

Le daemon garde le modèle chargé en permanence, et transcrit une phrase pendant que le
micro enregistre déjà la suivante. Seules les deux extrémités de cette chaîne — la capture
et la frappe — changent d'un hôte à l'autre ; le reste est commun.

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

Les deux autres hôtes reprennent la même idée avec leurs propres outils : sous WSL, la
frappe part vers Windows par `SendKeys` (un clavier virtuel Linux ne toucherait que les
fenêtres WSLg) ; sur macOS, elle passe par System Events, ce qui vaut au programme la
demande d'autorisation d'accessibilité.

---

## Dépannage

`linux-whisper doctor` commence par nommer l'hôte détecté, puis vérifie une à une les
briques qu'il utilise : c'est le premier réflexe pour tout ce qui suit.

**Le raccourci ne fait rien**
```sh
linux-whisper status                      # le daemon répond-il ?
linux-whisper hotkey show                 # le raccourci est-il enregistré ?
journalctl --user -u linux-whisper -f     # les logs (systemd)
tail -f ~/.local/state/linux-whisper/daemon.log   # les logs (launchd, ou daemon direct)
```

**Le texte n'est pas inséré mais reste dans le presse-papiers** — la frappe simulée n'a pas
abouti. `linux-whisper doctor` dit laquelle est en cause :

- **Linux** — `/dev/uinput` doit être accessible en écriture. Sur une session locale,
  systemd vous en donne l'accès automatiquement ; en SSH ou en session distante, non.
- **macOS** — autorisez l'accessibilité pour le terminal (ou pour `linux-whisper`) dans
  Réglages Système → Confidentialité et sécurité → Accessibilité, puis relancez le daemon.
- **WSL** — `powershell.exe` doit être joignable depuis WSL (interopérabilité active), et
  la fenêtre visée doit être une fenêtre Windows au premier plan.

**Je dicte dans un terminal et j'obtiens `^V`** — `Ctrl+V` n'y est pas le collage. Mettez
`paste_shortcut = "shift+insert"` dans `[output]`, puis `linux-whisper reload`.

**Les phrases se coupent trop tôt / trop tard** — ajustez `segment_silence_seconds`
(découpage) et `silence_seconds` (fin de dictée) dans `[recording]`.

**L'overlay s'ouvre mais rien ne s'écrit** — neuf fois sur dix, le micro par défaut n'est
pas le bon (une prise jack vide reste souvent la source par défaut, et ne renvoie que du
silence). `linux-whisper doctor` mesure le niveau réellement capté :

```sh
linux-whisper doctor          # « le micro capte du son » doit être coché
wpctl status                  # liste les sources ; repérez le vrai micro
wpctl set-default <id>        # bascule dessus
```

Le daemon vous prévient désormais par une notification quand une dictée n'a capté aucun
son, et journalise le pic mesuré :

```sh
journalctl --user -u linux-whisper | grep "pic"
```

**Ma voix n'est pas assez forte** — montez le gain de la source (`wpctl set-volume <id> 1.0`),
ou fixez le seuil à la main avec `threshold = 400` (au lieu de `"auto"`) dans `[recording]`.

**WSL : aucun son n'arrive** — WSLg fournit l'audio par PulseAudio ; installez
`pulseaudio-utils` (pour `parec`), vérifiez que le micro est autorisé côté Windows
(Paramètres → Confidentialité → Microphone) et que `pactl list sources short` liste bien
une source `RDPSource`.

**macOS : aucun son n'arrive** — la première capture demande l'autorisation micro au
terminal qui lance le daemon ; acceptez-la, puis vérifiez l'entrée par défaut dans
Réglages Système → Son. Pour choisir une autre entrée avec `ffmpeg`, listez les index
(`ffmpeg -f avfoundation -list_devices true -i ""`) et mettez le numéro dans
`device` avec `backend = "ffmpeg"`.

**macOS : je ne veux pas de skhd pour le raccourci** — créez une opération rapide
(Automator → Exécuter un script shell, `~/.local/bin/linux-whisper toggle`) et attribuez-lui
un raccourci dans Réglages Système → Clavier → Raccourcis clavier → Services.

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

### Tests

La suite ne dépend que de la bibliothèque standard — ni environnement virtuel, ni modèle
à télécharger :

```sh
python3 -m unittest discover -s tests -t .
```

Elle couvre ce qui se vérifie sans micro ni serveur graphique : mesure du niveau sonore,
découpage des phrases, fin d'enregistrement, fusion de la configuration, modes de sortie,
pilotage de la fenêtre d'écoute, et le choix des outils propres à chaque hôte — la
variable `LW_HOST` (`linux`, `wsl`, `macos`) force la détection, ce qui permet de tester
les trois depuis n'importe lequel.

| Fichier | Rôle |
|---|---|
| `src/linux_whisper/daemon.py` | service, socket Unix, écoute et transcription en parallèle |
| `src/linux_whisper/host.py` | détection de l'hôte, passerelle PowerShell sous WSL |
| `src/linux_whisper/capture.py` | choix de l'outil de capture (`arecord`, `parec`, `rec`, `ffmpeg`) |
| `src/linux_whisper/recorder.py` | détection de silence, découpage en phrases |
| `src/linux_whisper/transcriber.py` | faster-whisper, choix GPU/CPU |
| `src/linux_whisper/inject.py` | frappe simulée : `uinput`, SendKeys, System Events |
| `src/linux_whisper/output.py` | insertion au curseur, presse-papiers, notifications |
| `src/linux_whisper/overlay.py` | overlay X11 (processus séparé) |
| `src/linux_whisper/hotkey.py` | raccourci global : GNOME, menu Démarrer, `skhd` |
| `src/linux_whisper/service.py` | démarrage du daemon : systemd, launchd ou direct |
| `tests/` | suite `unittest`, sans dépendance externe |
| `install.sh` | installation et mise à jour |

## Licence

MIT
