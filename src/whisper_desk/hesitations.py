"""Hesitations: "euh", "um" and the words said twice are left out of the text."""

from __future__ import annotations

import re

# Only sounds that are never a word: "eu" (past participle of avoir), "ah",
# "oh", "ben" (a first name) or "err" (a verb) stay.
_SOUND = (
    r"e+u+h+m*|h+e+u+h*|h+u+m+|h+m+|m+h+|m{2,}"
    r"|u+h+m*|u+m+|e+r+m+|er"
)
# The commas or the ellipsis around a hesitation are the pause it filled: they
# go with it. "Je pense, euh, qu'on devrait" is "Je pense qu'on devrait".
_HESITATION = re.compile(
    rf"(?:\s*,)?\s*(?<![\w'’-])(?:{_SOUND})(?![\w'’-])(?:\s*(?:,|\.\.\.|…))?",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w[\w'’-]*")
# What may stand between a word and its repetition: a stutter, not a new sentence.
_STUTTER_GAP = re.compile(r"\s*(?:,|\.\.\.|…|-|—)?\s+")
# Words the language doubles on purpose: "nous nous voyons", "that that is",
# "had had", "très très bien", "bye bye", numbers ("douze douze" in a phone number)
# but "un", far more often the article said twice than the number.
_DOUBLED_ON_PURPOSE = {
    "nous", "vous", "très", "si", "oui", "non", "bon", "bye", "tout",
    "that", "had", "is", "very", "so", "yes", "no", "bye-bye",
    "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
    "onze", "douze", "treize", "quatorze", "quinze", "seize", "vingt", "trente",
    "quarante", "cinquante", "soixante", "cent", "mille",
    "one", "two", "three", "four", "five", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand",
}
# "on va, on va faire": a restart rarely runs longer than this.
_MAX_REPEAT = 3
_CAPITAL_HERE = "\x00"


def _drop_sounds(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        before = text[: match.start()].rstrip()
        # "Euh, je pense" opened the sentence: what follows now opens it. An
        # ellipsis is a pause inside the sentence, not its end.
        if not before or (before[-1] in ".!?" and not before.endswith("...")):
            return " " + _CAPITAL_HERE
        return " "

    text = _HESITATION.sub(replace, text)
    text = re.sub(rf"{_CAPITAL_HERE}\s*(\w)", lambda m: m[1].upper(), text)
    text = text.replace(_CAPITAL_HERE, "")
    text = re.sub(r"\s+", " ", text)
    # "C'est bon, euh." leaves a space in front of the full stop; French's own
    # spaces before "?" and "!" are not touched.
    return re.sub(r"\s+([,.…])", r"\1", text).strip()


def _same(first: list[re.Match[str]], second: list[re.Match[str]]) -> bool:
    if [w[0].lower() for w in first] != [w[0].lower() for w in second]:
        return False
    if len(first) == 1:
        word = first[0][0].lower()
        if word in _DOUBLED_ON_PURPOSE or word.isdigit():
            return False
    # "parle de De Gaulle": a capital that comes out of nowhere is a name.
    return not (second[0][0][:1].isupper() and not first[0][0][:1].isupper())


def _drop_repeat_once(text: str) -> str | None:
    words = list(_WORD.finditer(text))
    for size in range(_MAX_REPEAT, 0, -1):
        for index in range(len(words) - 2 * size + 1):
            first = words[index:index + size]
            second = words[index + size:index + 2 * size]
            if not _STUTTER_GAP.fullmatch(text[first[-1].end():second[0].start()]):
                continue
            inner = [text[a.end():b.start()] for a, b in zip(first, first[1:])]
            if any(not gap.isspace() for gap in inner):
                continue
            if _same(first, second):
                return text[: first[-1].end()] + text[second[-1].end():]
    return None


def apply(text: str) -> str:
    """The text without its hesitations and stuttered words."""
    text = _drop_sounds(text)
    if not re.search(r"\w", text):
        return ""  # nothing but a hesitation was said
    while (shorter := _drop_repeat_once(text)) is not None:
        text = shorter
    return text
