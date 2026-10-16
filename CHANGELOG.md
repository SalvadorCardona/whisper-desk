# Changelog

## Unreleased

### Added

- **Snippets** (Wispr Flow's *snippets*): say a cue, its saved text is inserted
  instead. `[snippets]` in `config.toml` — `"ma signature" = "Bien à vous,\nSalva"` —
  then `whisper-desk reload`. A cue said alone gives the text exactly as saved, without
  the full stop Whisper puts after it; inside a sentence, the punctuation around it
  stays. Case, accents, punctuation and hyphens do not count ("e-mail" for "email",
  "stand-up" for "standup"); whole words only, the longest cue first. The history keeps
  the expanded text; the model's context keeps what was said.
- `bench/snippets/`: 18 cues and 8 close control sentences, their snippets and synthetic
  recordings. Cues expanded / word error rate against the expected text, before → after:
  - written sentences: 18/18, 71.3 % → 0.0 %; controls untouched;
  - faster-whisper `small` (CPU, int8): 18/18, 72.3 % → 2.0 %; controls untouched;
  - faster-whisper `large-v3-turbo` (CUDA, float16): 16/18, 71.3 % → 8.9 % — two short
    cues said alone misheard ("by signature"); controls untouched.
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
