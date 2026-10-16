# whisper-desk vs Wispr Flow — gap tracker

[Wispr Flow](https://wisprflow.ai) is the reference for voice dictation. This file lists
its features and qualities, and where whisper-desk stands on each, so that each work
session can pick the most useful gap. Golden rule: whisper-desk stays 100 % offline —
a Wispr Flow feature that relies on the cloud is rebuilt locally (faster-whisper, rules,
a local model through Ollama) or marked *out of scope*. No telemetry, no account.

Sources: [wisprflow.ai/features](https://wisprflow.ai/features),
[Wispr Flow help center](https://docs.wisprflow.ai/) (read on 2026-10-15).

**Status**: done · partial · missing · out of scope.
**Effort**: S (a session) · M (a few sessions) · L (to split into several gaps).

## Quality

| Wispr Flow | whisper-desk | Status | Value | Effort |
|---|---|---|---|---|
| **Backtrack** — a correction said mid-sentence keeps only the corrected version | `backtrack.py`: "non, plutôt", "ou plutôt", "je veux dire", "no wait", "actually", "I mean", "or rather"… carried out by local rules; measured in `bench/backtrack/` | partial | high | S |
| **Filler removal** — "um", "uh", pauses | Whisper drops most hesitations by itself; nothing removes those it writes ("euh", "hum", repeated words) | partial | high | S |
| **Auto punctuation** — inferred from pauses and tone, spoken marks ("comma") | Whisper's own punctuation and capitals; spoken marks ("virgule", "à la ligne") not interpreted | partial | medium | S |
| **Numbered lists** — spoken enumerations become a formatted list | — | missing | medium | M |
| **Name spelling from context** | `vocabulary` (hotwords) and the context of the dictation fed back to the model | partial | high | — |
| **100+ languages** | every Whisper language; `language = "auto"` detects one language per sentence | done | medium | — |
| **Switching languages mid-dictation** (FR/EN) | detection per sentence with `auto`, but a fixed `language` forces one | partial | medium | M |
| **Whisper mode** — dictating very quietly | automatic silence threshold; no gain or model tuning for a whisper | missing | medium | M |
| **Latency** — "4× faster than typing" | sentence by sentence as you speak, model kept in memory, GPU when there is one; no measure yet | partial | high | M |

## Features

| Wispr Flow | whisper-desk | Status | Value | Effort |
|---|---|---|---|---|
| **Works in any app** | insertion at the cursor through the clipboard and a paste shortcut (uinput, Mutter, SendKeys, System Events) | done | — | — |
| **Personal dictionary**, fed by the words you correct | `vocabulary` in the settings window, filled by hand; no learning from corrections | partial | high | M |
| **Snippets** — a spoken cue inserts a longer text | `snippets.py`: `[snippets]` in `config.toml`, cue said alone or inside a sentence, case/accents/hyphens ignored, multi-line texts; measured in `bench/snippets/`. No editor in the settings window, plain text only (Wispr Flow keeps bold, links) | partial | high | S |
| **Styles** — tone adapted to the app (formal in docs, casual in chat) | — | missing | medium | L |
| **Command Mode** — select text, say how to rewrite it | — (would need a local model, e.g. Ollama) | missing | high | L |
| **Developer syntax** — camelCase, snake_case, CLI commands, file tagging in Cursor | — | missing | medium | M |
| **History** of dictations | `whisper-desk history` and its window: search, copy, insert again, purge | done | — | — |
| **Settings** | `whisper-desk settings`: language, model, microphone, shortcut, output, vocabulary, overlay | done | — | — |
| **Overlay** | X11 overlay: live level, sentence transcribed, states, cancel | done | — | — |
| **Usage dashboard** — words dictated, top apps | the history holds the data; no local statistics shown | missing | low | S |
| **Mobile apps, cross-device sync** | — | out of scope (account, cloud) | — | — |
| **Shared team dictionary and snippets** | — | out of scope (account, cloud) | — | — |
| **Notetaker** — meeting notes | — | out of scope for now (another product) | — | — |

## Done, by session

- 2026-10-15 — **Backtrack** (partial): corrections said aloud carried out by local rules,
  `model.corrections = true`. Measure (`bench/backtrack/`, 30 corrections + 16 controls):
  written sentences WER 81.3 % → 6.0 % (28/30 exact); faster-whisper `small` (CPU)
  86.7 % → 18.7 % (17/30); `large-v3-turbo` (GPU) 86.0 % → 20.7 % (19/30); no control
  sentence changed. Known limits: a correction split from its sentence by a long
  pause is not seen; replacing a phrase longer than three words without a repeated word
  to line up with is not attempted.
- 2026-10-16 — **Snippets** (partial): `[snippets]` in `config.toml`, a spoken cue is
  replaced by its saved text at insertion; the model's context and the history are kept
  straight (the context is what was said, the history what was typed). Measure
  (`bench/snippets/`, 18 cues + 8 close control sentences): written sentences 18/18
  expanded, WER 71.3 % → 0.0 %; faster-whisper `small` (CPU) 18/18 expanded, WER
  72.3 % → 2.0 % (17/18 exact, the 18th is "anytime" for "any time"); `large-v3-turbo`
  (GPU) 16/18 expanded, WER 71.3 % → 8.9 % — "My signature." heard "by signature.",
  "Mon lien de rendez-vous." heard "Moyen de rendez-vous"; no control sentence changed
  on any of them. Pushing the cues into the decoder as hotwords was tried and gained
  nothing (same two misses), so it was left out. Still missing: an editor in
  `whisper-desk settings`, rich text.
