# Changelog

## Unreleased

### Added

- **Snippets in the settings window** (Wispr Flow edits its snippets in the app): a
  **Snippets** list in `whisper-desk settings` shows each cue with its text, and
  **Add…**, **Edit…** and **Remove** change them without opening `config.toml` — the text
  may hold several lines. **Save** rewrites only the `[snippets]` section, its comments
  and the rest of the file kept, and the daemon takes the change at once. Two cues
  whisper-desk would hear the same (*Mon adresse.* and *mon adresse*), a text without a
  cue, or a cue made of punctuation alone are refused with a message, and nothing is
  written.
- **Hesitations left out** (Wispr Flow's *filler removal*): the *euh*, *heu*, *hum*,
  *hmm*, *um*, *uh*, *erm* Whisper writes down go, with the commas of the pause around
  them, and a word or a run of up to three words said twice in a row is written once —
  "Je je pense, euh, qu'on devrait" is written "Je pense qu'on devrait", "We could, we
  could meet" is written "We could meet". Words that only look like hesitations (*eu*,
  *ah*, *Ben*, *err*) and the doubles the language means (*nous nous*, *très très*,
  *that that*, *had had*, numbers) stay. Local rules (`hesitations.py`), applied after
  the corrections said aloud; `hesitations = false` in `[model]` turns them off.
- `bench/hesitations/`: 26 sentences with a hesitation or a stuttered word and 14 control
  sentences, with synthetic recordings. Word error rate against the expected text,
  before → after:
  - written sentences: 19.7 % → 0.0 %, 26/26 exact; controls 0 % → 0 %;
  - faster-whisper `small` (CPU, int8): 15.7 % → 5.6 %, 17/26 exact; controls
    unchanged (5.9 %, transcription slips);
  - faster-whisper `large-v3-turbo` (CUDA, float16): 13.5 % → 3.4 %, 20/26 exact;
    controls unchanged (3.5 %).
  What remains is mostly the synthetic voice: its *euh* comes back as "A", "« E »" or
  "O", which no rule can tell from a word.
- **Snippets** (Wispr Flow's *snippets*): a cue said aloud is replaced by the text saved
  for it in the `[snippets]` section of `config.toml` — "mon adresse perso" types the
  address, "ma signature" a signature on several lines. Alone, the cue gives the text
  exactly as saved; inside a sentence, only the cue is replaced. Case, punctuation and
  spacing do not matter, a cue never matches inside a longer word, the longest cue wins.
  Applied locally after the transcription (`snippets.py`); the model's context keeps
  the words that were said, not the text that replaced them.
- `bench/snippets/`: 20 sentences that say a cue and 10 control sentences that come
  close, with synthetic recordings. Sentences whose snippets all reach the text, before →
  after: written sentences 0/20 → 20/20; faster-whisper `small` (CPU) 0/20 → 18/20;
  `large-v3-turbo` (CUDA) 0/20 → 18/20, 20/20 with the cues also in the decoder
  (`--hotwords`, as `vocabulary` does). Controls changed for nothing: 0/10 everywhere.
- **Corrections said aloud are carried out** (Wispr Flow's *backtrack*): "On se voit
  mardi, non, plutôt mercredi" is written "On se voit mercredi.", "Let's meet at 2,
  actually 3" is written "Let's meet at 3." Local rules (`backtrack.py`), French and
  English, no language model; `corrections = false` in `[model]` turns them off.
- `bench/backtrack/`: a reproducible measure — 30 corrections and 16 control sentences,
  their expected text and synthetic recordings. Word error rate against the expected
  text, before → after:
  - written sentences: 81.3 % → 6.0 %, 28/30 exact; controls 0 % → 0 %;
  - faster-whisper `small` (CPU, int8): 86.7 % → 18.7 %, 17/30 exact; controls
    2.7 % → 2.7 % (transcription slips, left as they were);
  - faster-whisper `large-v3-turbo` (CUDA, float16): 86.0 % → 20.7 %, 19/30 exact;
    controls untouched.
  What remains is mostly the transcription itself ("14h" for "14 heures", "Mais le titre"
  for "Mets le titre"), not the corrections.
- `docs/wispr-flow-gap.md`: the features and qualities of Wispr Flow, and where
  whisper-desk stands on each.
