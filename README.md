# whisper-desk

**Offline voice dictation for Linux, WSL and macOS.** You press `Super + J`, a small overlay
appears — a microphone and an equalizer dancing to your voice — and the text
**is typed straight where your cursor is**, sentence after sentence, while
you speak.

Each bar tracks a frequency band, from lows on the left to highs on the right: you
see the voice, not just its volume. The scale is in decibels and the fall is slower
than the rise, like a VU meter — silence leaves the bars at rest, an ordinary voice
sits in the middle of the range.

<p align="center">
  <img src="docs/overlay-listening.png" alt="Overlay while listening" width="336">
  &nbsp;&nbsp;
  <img src="docs/overlay-working.png" alt="Overlay while transcribing" width="336">
</p>

No data leaves the machine: transcription runs on your GPU (or your CPU)
with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

---

## Installation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/whisper-desk/main/install.sh | sh
```

That's all. The script recognises the host — Linux, WSL or macOS — and adapts every step:

1. checks the system dependencies (microphone, clipboard, notifications, GTK) and offers
   to install them, with `apt` or `brew` as appropriate;
2. creates an isolated Python environment and installs faster-whisper in it — plus the
   CUDA libraries if an NVIDIA card is detected;
3. installs the `whisper-desk` command in `~/.local/bin`;
4. enables the user service — **systemd** on Linux and WSL, **launchd** on macOS —
   started automatically at login;
5. registers the global shortcut with the host's shortcut manager.

The Whisper model (a few hundred MB) is downloaded the first time the service starts.

Running the same command again **updates** the installation: the code is replaced, the
service restarted, and your configuration and models are kept.

### What each host uses

| | Linux | WSL | macOS |
|---|---|---|---|
| **microphone capture** | `arecord` (ALSA) | `parec` (PulseAudio/WSLg) | `rec` (sox) or `ffmpeg` |
| **clipboard** | `wl-copy` / `xclip` | `clip.exe` | `pbcopy` |
| **paste keystroke** | `/dev/uinput` | SendKeys (PowerShell) | System Events (`osascript`) |
| **global shortcut** | GNOME (`gsettings`) | Start menu shortcut | `skhd`, or by hand |
| **service** | systemd | systemd, otherwise on demand | launchd |
| **notifications** | `notify-send` | `notify-send` (WSLg) | `osascript` |

None of these choices are set in stone: `backend`, `keyboard` and `paste_shortcut` can be
forced in the configuration.

> **Requirements** — a microphone, and depending on the host:
>
> - **Linux**: GNOME (Wayland or X11), `systemd` in the user session.
> - **WSL**: WSL 2 with WSLg (Windows 11, or an up-to-date Windows 10) for the microphone,
>   and Windows interoperability enabled. Text is inserted into **Windows** windows.
> - **macOS**: 12 or newer. The first paste asks for accessibility permission
>   (System Settings → Privacy & Security → Accessibility), and the first dictation asks
>   for microphone permission.
>
> An NVIDIA GPU is a bonus, not a requirement; on macOS transcription runs on the CPU,
> since CTranslate2 does not use Metal.

### Check that everything is in place

```sh
whisper-desk doctor
```

---

## Usage

| Gesture | Effect |
|---|---|
| `Super + J` | starts listening — the overlay appears |
| a short pause (~0.6 s) | the sentence is transcribed and **inserted at the cursor**, listening continues |
| 2 s of silence | end of dictation |
| `Super + J` (again) | stops listening immediately |

The default shortcut follows the host: `Super + J` on Linux and macOS (`Cmd + J`),
`Ctrl + Alt + J` on WSL — Windows reserves the Windows key for itself.

The text is inserted into the focused application: editor, browser, chat client,
search box. Your clipboard is handed back untouched at the end of the dictation.

### From the command line

```sh
whisper-desk record     # dictate and write the text to standard output
whisper-desk toggle     # same as the keyboard shortcut
whisper-desk status     # daemon state, loaded model, GPU or CPU
whisper-desk doctor     # full diagnostic
whisper-desk config     # open the configuration in $EDITOR
whisper-desk reload     # reload the configuration without restarting
whisper-desk quit       # stop the daemon
```

---

## Configuration

Everything is configurable in **`~/.config/whisper-desk/config.toml`**:

```toml
[hotkey]
binding = "auto"              # "auto", or <Ctrl>/<Alt>/<Shift>/<Super> + a key

[model]
name = "auto"                 # auto | tiny | base | small | medium | large-v3 | large-v3-turbo
device = "auto"               # auto | cuda | cpu
language = "fr"               # ISO code, or "auto" for detection
initial_prompt = ""           # vocabulary to favour (proper nouns, jargon)

[recording]
backend = "auto"              # auto | arecord | parec | rec | sox | ffmpeg
streaming = true              # insertion as you go, sentence by sentence
segment_silence_seconds = 0.6 # pause that splits a sentence
silence_seconds = 2.0         # silence that ends the dictation
max_seconds = 120

[output]
mode = "cursor"               # cursor | clipboard | stdout — combinable: "cursor+stdout"
paste_shortcut = "auto"       # "shift+insert" if you mostly dictate in a terminal
keyboard = "auto"             # auto | uinput | windows | applescript | none
restore_clipboard = true      # hands your original clipboard back at the end
notify = false
history = true                # log in ~/.local/state/whisper-desk/history.log

[overlay]
enabled = true
accent = "#e46212"
position = "bottom-center"    # bottom-center | top-center | center
margin = 96
```

After a change:

```sh
whisper-desk reload            # for everything but the shortcut
whisper-desk hotkey install    # to apply a new shortcut
```

### Choosing a model

| Model | VRAM | Speed | Quality |
|---|---|---|---|
| `small` | ~1 GB | very fast | decent — default without a GPU |
| `medium` | ~2.5 GB | fast | good |
| `large-v3-turbo` | ~2 GB | fast | excellent — **default with a GPU** |
| `large-v3` | ~4.5 GB | slower | the best |

To shorten the delay between the end of a sentence and its insertion even further, lower
`beam_size` to `1` in `[model]`.

---

## How it works

```
Super + J  ─→  whisper-desk toggle  ─→  Unix socket  ─→  daemon (model in memory)
                                                              │
                              X11 overlay ←── audio level ────┤
                                                              │
 mic capture ─→ silence detection ─→ sentence ─→ faster-whisper ─→ text
                                                              │
                          clipboard + Ctrl+V (simulated keystroke) ─→ cursor
```

The daemon keeps the model loaded at all times, and transcribes one sentence while the
microphone is already recording the next. Only the two ends of that chain — capture and
keystroke — change from one host to another; the rest is shared.

Three Wayland constraints shaped this architecture:

- **A client cannot type into another client's window.** The `virtual-keyboard`
  protocol (the one `wtype` uses) is not implemented by GNOME. So we go through a
  kernel virtual keyboard (`/dev/uinput`, reachable without privileges thanks to the ACL
  set by systemd) that sends a plain paste shortcut.
- **Sending the text key by key would mean knowing the active XKB layout.**
  On an AZERTY keyboard, accents and half the letters would land on the wrong key; the
  paste shortcut, on the other hand, sits on the same physical key everywhere. The text
  therefore travels through the clipboard, which is restored afterwards.
- **A Wayland window can neither refuse focus nor position itself.** A Wayland overlay
  would catch the paste instead of your application. The overlay is therefore an X11
  client (via Xwayland) of type `NOTIFICATION`: never focused, and positionable.

The two other hosts follow the same idea with their own tools: on WSL, the keystroke goes
to Windows through `SendKeys` (a Linux virtual keyboard would only reach WSLg windows);
on macOS, it goes through System Events, which is what earns the program the accessibility
permission prompt.

---

## Troubleshooting

`whisper-desk doctor` starts by naming the detected host, then checks one by one the
pieces it uses: it is the first thing to try for everything below.

**The shortcut does nothing**
```sh
whisper-desk status                      # is the daemon answering?
whisper-desk hotkey show                 # is the shortcut registered?
journalctl --user -u whisper-desk -f     # the logs (systemd)
tail -f ~/.local/state/whisper-desk/daemon.log   # the logs (launchd, or a direct daemon)
```

**The text is not inserted but stays in the clipboard** — the simulated keystroke did not
get through. `whisper-desk doctor` says which one is at fault:

- **Linux** — `/dev/uinput` must be writable. In a local session, systemd grants you
  access automatically; over SSH or in a remote session, it does not.
- **macOS** — allow accessibility for the terminal (or for `whisper-desk`) in
  System Settings → Privacy & Security → Accessibility, then restart the daemon.
- **WSL** — `powershell.exe` must be reachable from WSL (interoperability enabled), and
  the target window must be a Windows window in the foreground.

**I dictate in a terminal and get `^V`** — `Ctrl+V` is not paste there. Set
`paste_shortcut = "shift+insert"` in `[output]`, then run `whisper-desk reload`.

**Sentences are cut too early / too late** — adjust `segment_silence_seconds`
(splitting) and `silence_seconds` (end of dictation) in `[recording]`.

**The overlay opens but nothing is written** — nine times out of ten, the default
microphone is the wrong one (an empty jack socket often stays the default source, and
returns nothing but silence). `whisper-desk doctor` measures the level actually captured:

```sh
whisper-desk doctor          # "the microphone picks up sound" must be ticked
wpctl status                  # lists the sources; spot the real microphone
wpctl set-default <id>        # switch to it
```

The daemon now warns you with a notification when a dictation captured no sound at all,
and logs the measured peak:

```sh
journalctl --user -u whisper-desk | grep "peak"
```

**My voice is not loud enough** — raise the source gain (`wpctl set-volume <id> 1.0`),
or set the threshold by hand with `threshold = 400` (instead of `"auto"`) in `[recording]`.

**WSL: no sound arrives** — WSLg provides audio through PulseAudio; install
`pulseaudio-utils` (for `parec`), check that the microphone is allowed on the Windows side
(Settings → Privacy → Microphone) and that `pactl list sources short` does list an
`RDPSource` source.

**macOS: no sound arrives** — the first capture asks for microphone permission for the
terminal that starts the daemon; accept it, then check the default input in
System Settings → Sound. To pick another input with `ffmpeg`, list the indexes
(`ffmpeg -f avfoundation -list_devices true -i ""`) and put the number in
`device` with `backend = "ffmpeg"`.

**macOS: I don't want skhd for the shortcut** — create a Quick Action
(Automator → Run Shell Script, `~/.local/bin/whisper-desk toggle`) and assign it
a shortcut in System Settings → Keyboard → Keyboard Shortcuts → Services.

**Transcription runs on the CPU even though I have a GPU** — `whisper-desk status`
reports the selected device, and `journalctl --user -u whisper-desk` the reason for the
fallback (often missing CUDA libraries or not enough VRAM).

---

## Uninstalling

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/whisper-desk/main/uninstall.sh | sh
```

Add `WD_PURGE=1` to remove the configuration and the history as well. Downloaded models
stay in `~/.cache/huggingface`.

---

## Development

```sh
git clone https://github.com/SalvadorCardona/whisper-desk
cd whisper-desk
WD_SRC="$PWD" sh install.sh     # installs from the local clone, without network access
```

### Tests

The suite depends on the standard library alone — no virtual environment, no model
to download:

```sh
python3 -m unittest discover -s tests -t .
```

It covers what can be checked without a microphone or a display server: sound level
measurement, sentence splitting, end of recording, configuration merging, output modes,
driving the listening window, and the choice of host-specific tools — the `WD_HOST`
environment variable (`linux`, `wsl`, `macos`) forces detection, which makes it possible
to test all three from any of them.

| File | Role |
|---|---|
| `src/whisper_desk/daemon.py` | service, Unix socket, listening and transcription in parallel |
| `src/whisper_desk/host.py` | host detection, PowerShell bridge under WSL |
| `src/whisper_desk/capture.py` | choice of capture tool (`arecord`, `parec`, `rec`, `ffmpeg`) |
| `src/whisper_desk/recorder.py` | silence detection, splitting into sentences |
| `src/whisper_desk/transcriber.py` | faster-whisper, GPU/CPU selection |
| `src/whisper_desk/inject.py` | simulated keystroke: `uinput`, SendKeys, System Events |
| `src/whisper_desk/output.py` | insertion at the cursor, clipboard, notifications |
| `src/whisper_desk/overlay.py` | X11 overlay (separate process) |
| `src/whisper_desk/hotkey.py` | global shortcut: GNOME, Start menu, `skhd` |
| `src/whisper_desk/service.py` | daemon startup: systemd, launchd or direct |
| `tests/` | `unittest` suite, no external dependency |
| `install.sh` | installation and updates |

## License

MIT

## Author

Written and maintained by [Salvador Cardona, developer](https://cardona.digital) — thirteen
years of web development, and the other projects at the same address.
