# Changelog

## Unreleased

### Added

- **Usage statistics** (Wispr Flow's dashboard, worked out locally): `whisper-desk stats`
  reads the history and shows the words dictated today, over the last 7 days and in all,
  the dictations and the days with one, the current and longest streak of days in a row,
  the listening time, the pace in words per minute over the last 100 dictations — silence
  that ends a dictation included — and the time saved against typing the same words at 40
  words a minute. `--days N` keeps the last N days, `--json` hands the figures to a script
  or a status bar. Nothing new is recorded and nothing leaves the machine; dictations of
  the old `history.log`, which kept no listening time, count words but not the pace.
- **Quotes and brackets said aloud** (Wispr Flow's spoken punctuation, continued):
  *ouvrez les guillemets* … *fermez les guillemets* are written « … », *ouvrez la
  parenthèse* … *fermez la parenthèse* ( … ), *open quote* … *close quote* (or *end
  quote*, *quote* … *unquote*) "…" and *open paren* … *close paren* (or *parenthesis*)
  ( … ): "Il m'a dit ouvrez les guillemets je reviens demain fermez les guillemets" is
  written "Il m'a dit « je reviens demain »". The commas Whisper puts around the commands
  for the pause go, as do the « » it sometimes writes around them; a question or an
  exclamation said before the closing stays inside. The forms Whisper hears for the
  imperative (*ouvré*, *fermé*, *ouvrait*) count; the words said in a sentence stay words
  (*il est temps de fermer la parenthèse*, *on ferme la parenthèse*, *can I quote you*,
  *an open quote request*, *quote unquote*), unless their other half is said too. A quote
  opened before a pause closes in the next sentence without a stray space. Same switch
  as the rest of the spoken punctuation, `spoken_punctuation` in `[model]`.
- `bench/punctuation/`: 16 sentences with quotes or brackets and 8 control sentences
  added (44 + 22 in all). Error rate on words and marks on the 16 new sentences, before →
  after:
  - written sentences: 53.1 % → 0.0 %, 16/16 exact;
  - faster-whisper `small` (CPU, int8): 70.1 % → 35.4 %, 3/16 exact;
  - faster-whisper `large-v3-turbo` (CUDA, float16): 86.4 % → 18.4 %, 4/16 exact.
  The 28 earlier sentences and the 22 controls do not change. What remains is the
  transcription of the synthetic voices — *parenthèse* heard as "l'apparentaise",
  *paren* as "Perenn" — and the full stop Whisper ends each sentence with.
- **Punctuation said aloud** (Wispr Flow's spoken punctuation): *virgule*, *point*,
  *point d'interrogation*, *point d'exclamation*, *point-virgule*, *deux points*, *à la
  ligne*, *nouveau paragraphe* — and *comma*, *period*, *full stop*, *question mark*,
  *exclamation mark*, *semicolon*, *colon*, *new line*, *new paragraph* — are written as
  the mark or the line break they name: "Bonjour Marie virgule à la ligne merci point" is
  written "Bonjour Marie," then "Merci." on the next line. Whisper's own punctuation around
  the word gives way, French marks get their space, and a full stop or a line break
  capitalises what follows. The words said as words stay: after an article (*une
  virgule*, *le point*, *a new line of products*), in a number (*trois virgule cinq*),
  before what makes them a noun (*deux points d'avance*), and *point* or *period* anywhere
  a full stop cannot stand (*mon point de vue*, *a good point, let me think*). A mark said
  after a pause, alone in its sentence, is glued to the sentence before, and nothing is
  put in front of what follows a line break. Local rules (`punctuation.py`), applied last;
  `spoken_punctuation = false` in `[model]` keeps the words.
- `bench/punctuation/`: 28 sentences that say a mark or a line break and 14 control
  sentences, with synthetic recordings. Error rate on words and marks against the expected
  text, before → after:
  - written sentences: 33.6 % → 0.0 %, 28/28 exact; controls 0 % → 0 %;
  - faster-whisper `small` (CPU, int8): 51.0 % → 19.8 %, 11/28 exact; controls
    unchanged (7.0 %, transcription slips);
  - faster-whisper `large-v3-turbo` (CUDA, float16): 45.8 % → 9.9 %, 15/28 exact;
    controls unchanged (5.2 %).
  What remains is mostly the transcription: the commas Whisper adds on its own ("Hi,
  John,"), *comma* heard as "come a", *point-virgule* as a comma, *prêt virgule* as
  "pré-virgule".
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

### Changed

- The repository moved to `hermez-agency/whisper-desk`: the installation command, the
  README and the site point there. `whisper-desk update` on an installation made before
  the move reads the new home instead of `SalvadorCardona/whisper-desk`, and `install.sh`
  writes the new name in the fingerprint, even when called with the old one.
- **Developer syntax** (Wispr Flow writes variable names in their style): say the style,
  then the name — *camel case user name* is written `userName`, *pascal case payment
  service* `PaymentService`, *snake case created at* `created_at`, *kebab case* (or *dash
  case*) *user profile* `user-profile`, *constant case* (or *screaming snake case*) *max
  retries* `MAX_RETRIES`. The name runs until the sentence goes on: a mark, a word such as
  *et*, *dans*, *est*, *and*, *from*, *to*, *is*, or another style; *by* and *at* belong to
  it (`getUserById`, `created_at`). The forms Whisper writes are understood — apart
  (*Camel Case User ID*), glued (*camelCaseUserName*, *SnakeCaseParseDate*) or hyphenated
  (*constant-case-database-url*). The style named without a name after it (*on écrit en
  snake case*, *we use camel case for variables*) or after an article (*a constant case of
  bad luck*, *un kebab, case départ*) stays as words. Local rules (`casing.py`), applied
  after the spoken punctuation; `developer_syntax = false` in `[model]` keeps the words.
- `bench/casing/`: 24 sentences that say a name in a style and 12 control sentences, with
  synthetic recordings. Names written exactly as expected, before → after:
  - written sentences: 0/25 → 25/25, 24/24 sentences exact; controls unchanged;
  - faster-whisper `small` (CPU, int8): English 0/12 → 5/12; controls unchanged;
  - faster-whisper `large-v3-turbo` (CUDA, float16): English 0/12 → 7/12; controls
    unchanged.
  What remains is the transcription: Whisper mishears the words of the name (*use of
  settings* for *user settings*, *orth provider* for *auth provider*). The French
  recordings are no measure: the French synthetic voice cannot say English words, and
  Whisper hears none of the 13 names in them, before or after.
