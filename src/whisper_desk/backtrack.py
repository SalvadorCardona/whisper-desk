"""Mid-sentence corrections: "Tuesday, no, Wednesday rather" keeps Wednesday."""

from __future__ import annotations

import re

# A correction marker only counts after a pause the model wrote down as
# punctuation: "plutôt" or "actually" in the flow of a sentence is no
# correction ("c'est plutôt bien", "I actually think").
_BOUNDARY = r"(?:[,;:]|\.\.\.|…|—|–|-)"

# Strong markers say "replace what I just said" with no doubt: when nothing in
# the correction points at what it replaces, the same number of words is.
_STRONG = (
    r"(?:non|ah non|euh non|enfin non)\s*[,.]?\s*(?:plutôt|pardon|je veux dire|attends|en fait)"
    r"|ou plutôt|enfin non"
    r"|(?:no|oh no)\s*[,.]?\s*(?:wait|actually|I mean|sorry)"
    r"|or rather|make that|scratch that"
)
# Weak markers are also everyday words ("pardon, je n'avais pas vu"): they
# only rewrite when the correction can be lined up with what it replaces.
_WEAK = r"non|pardon|je veux dire|no|sorry|actually|I mean"

_MARKER = re.compile(
    rf"(?P<cut>{_BOUNDARY}\s*|\s+)"
    rf"(?P<marker>{_STRONG}|{_WEAK})"
    r"\s*[,:]?\s+",
    re.IGNORECASE,
)
# These are never words of the sentence itself: Whisper often leaves out the
# comma in front of them ("la version 2 ou plutôt la version 3").
_UNPAUSED = re.compile(r"ou plutôt|or rather", re.IGNORECASE)
# The strong markers may also open a new sentence: "Mardi. Non, plutôt mercredi."
_SENTENCE_END = re.compile(r"[.!?…]\s*$")

_WEEKDAYS = {
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}
_MONTHS = {
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
    "septembre", "octobre", "novembre", "décembre",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}
_NUMBERS = {
    "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "vingt", "trente", "cent", "mille",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "hundred", "thousand",
}
# A blind replacement takes the determiner along: "ce soir, non, plutôt
# demain" leaves no "ce" hanging in front of "demain".
_DETERMINERS = {
    "le", "la", "les", "un", "une", "des", "du", "ce", "cet", "cette", "ces",
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
    "the", "a", "an", "this", "that", "these", "those", "my", "your",
}
# Beyond this many words, replacing "the same number of words" is a guess.
_MAX_BLIND = 3
# Never more corrections than this in one sentence: each one shortens the text,
# the bound only guards against a pattern that would not.
_MAX_PASSES = 8


def _bare(word: str) -> str:
    return word.strip(""".,;:!?…«»"'()[]—–-""").lower()


def _kind(word: str) -> str | None:
    """Words that stand for one another: a day for a day, a number for a number."""
    bare = _bare(word)
    if bare in _WEEKDAYS:
        return "weekday"
    if bare in _MONTHS:
        return "month"
    if re.fullmatch(r"\d+([.,:h]\d*)?(h|am|pm|%|€|\$)?", bare) or bare in _NUMBERS:
        return "number"
    return None


def _anchor(before: list[str], after: list[str]) -> int | None:
    """Where in `before` the correction `after` starts over, if it says so."""
    first = _bare(after[0])
    for index in range(len(before) - 1, -1, -1):
        if _bare(before[index]) == first:
            return index
    kind = _kind(after[0])
    if kind is not None:
        for index in range(len(before) - 1, -1, -1):
            if _kind(before[index]) == kind:
                return index
    return None


def _sentence_start(text: str) -> int:
    """Start of the sentence the end of `text` belongs to."""
    match = None
    for match in re.finditer(r"[.!?…]+\s+", text):
        pass
    return match.end() if match else 0


def _correct_once(text: str) -> str | None:
    for match in _MARKER.finditer(text):
        head = text[: match.start()]
        strong = re.fullmatch(_STRONG, match["marker"], re.IGNORECASE) is not None
        if (not match["cut"].strip() and not _SENTENCE_END.search(head)
                and not _UNPAUSED.fullmatch(match["marker"])):
            continue  # no pause before it: an ordinary word of the sentence
        if _SENTENCE_END.search(head):
            if not strong:
                continue  # "Tu viens ? Non, tu restes." is an answer, not a correction
            head = _SENTENCE_END.sub("", head)
        start = _sentence_start(head)
        before = head[start:].split()
        rest = text[match.end():]
        # The correction runs to the end of its sentence.
        end = re.search(r"[.!?…](\s|$)", rest)
        tail_at = end.start() if end else len(rest)
        after = rest[:tail_at].split()
        if not before or not after:
            continue
        cut = _anchor(before, after)
        if cut is None:
            if not strong or len(after) > _MAX_BLIND or len(after) >= len(before):
                continue
            cut = len(before) - len(after)
            if (cut > 1 and _bare(before[cut - 1]) in _DETERMINERS
                    and _bare(after[0]) not in _DETERMINERS):
                cut -= 1
        kept = before[:cut] + after
        if cut == 0:
            kept[0] = kept[0][:1].upper() + kept[0][1:]
        return head[:start] + " ".join(kept) + rest[tail_at:]
    return None


def apply(text: str) -> str:
    """The text with the corrections said aloud carried out."""
    for _ in range(_MAX_PASSES):
        corrected = _correct_once(text)
        if corrected is None:
            break
        text = corrected
    return text
