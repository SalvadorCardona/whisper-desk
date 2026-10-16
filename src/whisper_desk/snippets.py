"""Snippets: a spoken cue ("ma signature") inserts a longer saved text."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Mapping

logger = logging.getLogger("whisper-desk.snippets")

# What the model may write between two words of a cue said aloud: a comma or a
# hyphen it put there must not break the match.
_GAP = r"[\s,;:'’\-]*"
# ... and inside a word: the cue "standup" comes back "stand-up", "email"
# comes back "e-mail" or "e mail".
_SPLIT = r"[\s\-]?"
_WORD = re.compile(r"\w+")
# The punctuation Whisper closes a sentence with: a cue said on its own is a
# sentence for the model, and "Ma signature." would leave a dot after the text.
_SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")
_SENTENCE_START = re.compile(r"(?:^|[.!?…]\s+)\s*$")


def _fold(char: str) -> str:
    """One character, its accent dropped: indices stay those of the text."""
    return unicodedata.normalize("NFD", char)[0]


def _folded(text: str) -> str:
    return "".join(_fold(char) for char in text)


def _pattern(triggers: list[str]) -> re.Pattern[str] | None:
    alternatives = []
    for trigger in triggers:
        words = _WORD.findall(_folded(trigger))
        if words:
            alternatives.append(_GAP.join(
                _SPLIT.join(re.escape(char) for char in word) for word in words
            ))
    if not alternatives:
        return None
    # The longest cue first: "mon adresse pro" before "mon adresse".
    alternatives.sort(key=len, reverse=True)
    return re.compile(rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)", re.IGNORECASE)


def _key(text: str) -> str:
    """The cue reduced to its letters: case, accents and spacing do not count."""
    return "".join(_WORD.findall(_folded(text).lower()))


def _lookup(snippets: Mapping[str, str]) -> dict[str, str]:
    """Expansions by cue."""
    table = {}
    for trigger, expansion in snippets.items():
        key = _key(str(trigger))
        if not key or not isinstance(expansion, str) or not expansion:
            logger.warning("Snippet %r ignored: an empty cue or expansion.", trigger)
            continue
        table[key] = expansion
    return table


def expand(text: str, snippets: Mapping[str, str]) -> str:
    """The text with every spoken cue replaced by its saved expansion."""
    table = _lookup(snippets)
    pattern = _pattern([str(cue) for cue in snippets if _key(str(cue)) in table])
    if not text or pattern is None:
        return text
    pieces = []
    position = 0
    # One pass over the text as dictated: an expansion is never expanded again.
    for match in pattern.finditer(_folded(text)):
        expansion = table[_key(match.group())]
        end = match.end()
        closing = _SENTENCE_END.match(text, end)
        if closing and _SENTENCE_START.search(text[: match.start()]):
            # The cue was a sentence of its own: the text stands as it was saved.
            end = closing.end()
        pieces.append(text[position:match.start()])
        pieces.append(expansion)
        position = end
    pieces.append(text[position:])
    return "".join(pieces)

