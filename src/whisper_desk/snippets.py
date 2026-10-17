"""Snippets: a spoken cue ("mon adresse") is replaced by the text saved for it."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("whisper-desk.snippets")

# Whisper writes a cue its own way: "Mon adresse.", "mon, adresse", "MON ADRESSE".
# Only the words count — punctuation and spacing between them are free.
_WORD = re.compile(r"\w+")
_SENTENCE_MARK = re.compile(r"[.!?…]$")


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD.findall(text)]


def cue_key(text: str) -> str:
    """What a cue comes down to: two cues with the same key are the same cue."""
    return " ".join(_words(text))


class Snippets:
    """The cues of a [snippets] section, compiled into one pattern."""

    def __init__(self, table: dict[str, Any]):
        self.expansions: dict[str, str] = {}
        for cue, expansion in table.items():
            if not isinstance(expansion, str):
                logger.warning("Snippet %r ignored: its text is not a string.", cue)
                continue
            key, expansion = cue_key(cue), expansion.strip()
            # A cue made of punctuation alone would match everywhere; an empty
            # text is how a snippet is switched off without losing its cue.
            if key and expansion:
                self.expansions[key] = expansion
        # The longest cue first: "mon adresse pro" wins over "mon adresse".
        cues = sorted(self.expansions, key=lambda k: (-len(k.split()), -len(k)))
        alternatives = [r"\W+".join(map(re.escape, cue.split())) for cue in cues]
        # A cue never touches a letter, a digit or an underscore, nor the "'t"
        # of a contraction: "can" is not in "can't".
        self.pattern = re.compile(
            rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)(?!['’]t\b)",
            re.IGNORECASE,
        ) if alternatives else None

    def apply(self, text: str) -> str:
        """The text with every cue replaced by its snippet."""
        if self.pattern is None:
            return text
        # Said on its own, the cue is the whole sentence: its capital and its
        # final full stop are Whisper's, the snippet is written as saved.
        alone = self.expansions.get(cue_key(text))
        if alone is not None:
            return alone

        out, last = [], 0
        for match in self.pattern.finditer(text):
            out.append(text[last:match.start()])
            expansion = self.expansions[cue_key(match.group())]
            rest = text[match.end():]
            # "à mon adresse." with a snippet that already ends on a full stop
            # would end on two.
            if _SENTENCE_MARK.search(expansion) and rest[:1] == expansion[-1]:
                expansion = expansion[:-1]
            out.append(expansion)
            last = match.end()
        out.append(text[last:])
        return "".join(out)


def apply(text: str, table: dict[str, Any]) -> str:
    """The text with the snippets of `table` (cue -> text) expanded."""
    return Snippets(table).apply(text)
