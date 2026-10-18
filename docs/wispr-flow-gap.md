# whisper-desk vs Wispr Flow — gap tracker

[Wispr Flow](https://wisprflow.ai) is the reference for voice dictation. This file lists
its features and qualities, and where whisper-desk stands on each, so that each work
session can pick the most useful gap. Golden rule: whisper-desk stays 100 % offline —
a Wispr Flow feature that relies on the cloud is rebuilt locally (faster-whisper, rules,
a local model through Ollama) or marked *out of scope*. No telemetry, no account.

Sources: [wisprflow.ai/features](https://wisprflow.ai/features),
[Wispr Flow help center](https://docs.wisprflow.ai/) (read on 2026-10-15),
[Create and use snippets](https://docs.wisprflow.ai/articles/5784437944-create-and-use-snippets)
(read on 2026-10-16); filler removal, "Remove fillers" on the features page (read on
2026-10-16); spoken punctuation, "Auto punctuation" on the features page (read on
2026-10-18).

**Status**: done · partial · missing · out of scope.
**Effort**: S (a session) · M (a few sessions) · L (to split into several gaps).

## Quality

| Wispr Flow | whisper-desk | Status | Value | Effort |
|---|---|---|---|---|
| **Backtrack** — a correction said mid-sentence keeps only the corrected version | `backtrack.py`: "non, plutôt", "ou plutôt", "je veux dire", "no wait", "actually", "I mean", "or rather"… carried out by local rules; measured in `bench/backtrack/` | partial | high | S |
| **Filler removal** — "um", "uh", pauses | Whisper drops most hesitations by itself; `hesitations.py` removes those it writes ("euh", "hum", "um", "uh", "erm") and words or runs of up to three words said twice in a row, keeping intended doubles; measured in `bench/hesitations/`. A hesitation Whisper mishears as a word ("A", "« E »") stays | done | high | S |
| **Auto punctuation** — inferred from pauses and tone, spoken marks ("comma") | Whisper's own punctuation and capitals; spoken marks and line breaks ("virgule", "point d'interrogation", "à la ligne", "comma", "new paragraph") written by `punctuation.py`, measured in `bench/punctuation/` (in PR). No quotes or brackets said aloud yet | partial | medium | S |
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
| **Snippets** — a spoken cue inserts a longer text | `[snippets]` in `config.toml`, `snippets.py`: alone or inside a sentence, case and punctuation ignored, longest cue wins, multi-line texts; measured in `bench/snippets/`; edited in the settings window too (#25). No rich text (bold, links) | partial | high | S |
| **Styles** — tone adapted to the app (formal in docs, casual in chat) | — | missing | medium | L |
| **Command Mode** — select text, say how to rewrite it | — (would need a local model, e.g. Ollama) | missing | high | L |
| **Developer syntax** — camelCase, snake_case, CLI commands, file tagging in Cursor | — | missing | medium | M |
| **History** of dictations | `whisper-desk history` and its window: search, copy, insert again, purge | done | — | — |
| **Settings** | `whisper-desk settings`: language, model, microphone, shortcut, output, vocabulary, snippets, overlay | done | — | — |
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
- 2026-10-16 — **Snippets** (partial): a cue said aloud is replaced by its text,
  `[snippets]` in `config.toml`, with Wispr Flow's matching rules (cue alone → the text
  as saved; inside a sentence: case and adjacent punctuation ignored, word boundaries,
  longest cue wins). Measure (`bench/snippets/`, 20 sentences with a cue + 10 controls),
  sentences whose snippets all reach the text: written 20/20; `small` (CPU) 18/20;
  `large-v3-turbo` (GPU) 18/20, 20/20 with the cues pushed into the decoder; 0/10
  control changed. Left to do: an editor in the settings window, rich-text snippets.
- 2026-10-16 — **Filler removal** (done): hesitations Whisper writes ("euh", "hum", "um",
  "uh", "erm") and stuttered words or restarts ("je je", "we could, we could") left out by
  local rules, `model.hesitations = true`; intended doubles kept ("nous nous", "had had",
  "très très", numbers). Measure (`bench/hesitations/`, 26 sentences + 14 controls): written
  sentences WER 19.7 % → 0.0 % (26/26 exact); `small` (CPU) 15.7 % → 5.6 % (17/26);
  `large-v3-turbo` (GPU) 13.5 % → 3.4 % (20/26); no control sentence changed. What remains
  comes from the synthetic voice, whose "euh" Whisper hears as "A" or "« E »".
- 2026-10-17 — **Snippets in the settings window** (merged, #25): a Snippets list in
  `whisper-desk settings`, with Add…, Edit… (multi-line text) and Remove. Save rewrites
  only the `[snippets]` section — the cues that went are removed from the file, its
  comments kept — and reloads the daemon; two cues heard the same, a text without a cue
  or a cue without a word are refused. A feature, no quality measure: 25 new tests
  (TOML section rewrite, settings controller). Left to do on snippets: rich text.
- 2026-10-18 — **Spoken punctuation** (in PR): *virgule*, *point*, *point d'interrogation*,
  *deux points*, *à la ligne*, *nouveau paragraphe*, *comma*, *period*, *question mark*,
  *new line*… written as marks and line breaks by local rules, `model.spoken_punctuation =
  true`; the same words said as words stay (after an article, in a number, *point* or
  *period* where no full stop can stand). Sentences said after a pause join without a
  stray space. Measure (`bench/punctuation/`, 28 sentences + 14 controls, error rate on
  words and marks): written sentences 33.6 % → 0.0 % (28/28 exact); `small` (CPU)
  51.0 % → 19.8 % (11/28); `large-v3-turbo` (GPU) 45.8 % → 9.9 % (15/28); no control
  sentence changed. What remains is the transcription (Whisper's own commas, "come a"
  for *comma*). Left to do: quotes and brackets said aloud.
