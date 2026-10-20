"""Developer syntax: "camel case user name" is written userName, "snake case created at" created_at."""

from __future__ import annotations

import re

# Spoken style -> how the words are joined. "Paschal" is how Whisper often
# writes "pascal" in English; "dash case" is another name for kebab case.
_STYLES: dict[str, str] = {
    "camel": "camel",
    "pascal": "pascal",
    "paschal": "pascal",
    "snake": "snake",
    "kebab": "kebab",
    "kebap": "kebab",
    "dash": "kebab",
    "constant": "constant",
    "screaming snake": "constant",
    "upper snake": "constant",
}
_NAMES = "|".join(
    re.sub(r"\s+", r"[\\s-]+", name) for name in sorted(_STYLES, key=len, reverse=True)
)
# Whisper writes the command apart ("camel case user name"), glued to what
# follows ("camelCaseUserName", "SnakeCaseParseDate") or hyphenated
# ("constant-case-database-url"). A comma right after it is the pause the
# speaker took before the name.
_COMMAND = re.compile(
    rf"(?<![\w'’-])(?P<name>(?i:{_NAMES}))[\s,_-]*(?i:case)"
    r"(?P<glued>(?:[A-Z][a-z]*|[0-9]+)+)?(?![\w'’])(?:\s*,(?=\s))?"
)
_NEXT_WORD = re.compile(r"[\s_-]+(?P<word>[^\W_]+)(?![\w'’])")
_GLUED_WORD = re.compile(r"[A-Z][a-z]*|[0-9]+")
# A word in front that makes the command a noun: "un kebab, case départ",
# "a constant case of bad luck", "the pascal case convention".
_NOUN_BEFORE = {
    "le", "la", "les", "l", "un", "une", "des", "du", "ce", "cet", "cette", "mon", "ma",
    "the", "a", "an", "this", "that", "my", "your", "our", "their", "its",
}
# Where the name ends: the words that go on with the sentence. "Le champ camel
# case first name est obligatoire", "call camel case fetch orders and wait".
# "by" and "at" stay in: "get user by id", "created at".
_STOP = {
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "au", "aux", "à",
    "et", "ou", "mais", "donc", "car", "puis", "avec", "sans", "dans", "sur", "sous",
    "pour", "par", "en", "vers", "depuis", "entre", "comme", "qui", "que", "qu",
    "quand", "si", "ne", "est", "sont", "était", "sera", "vaut", "renvoie", "retourne",
    "prend", "contient", "doit", "fait", "a", "ont",
    "the", "an", "and", "or", "but", "so", "then", "with", "without", "in", "into",
    "on", "from", "to", "for", "of", "as", "that", "which", "who", "when", "if",
    "is", "are", "was", "were", "be", "will", "would", "should", "must", "can",
    "could", "returns", "takes", "has", "have", "does", "do", "it", "this",
}


def _identifier(words: list[str], style: str) -> str:
    words = [word.lower() for word in words]
    if style == "camel":
        return words[0] + "".join(word.capitalize() for word in words[1:])
    if style == "pascal":
        return "".join(word.capitalize() for word in words)
    if style == "snake":
        return "_".join(words)
    if style == "kebab":
        return "-".join(words)
    return "_".join(word.upper() for word in words)


def _style(match: re.Match[str]) -> str:
    return _STYLES[re.sub(r"[\s-]+", " ", match["name"].lower())]


def _word_before(text: str, index: int) -> str:
    words = re.findall(r"\w+", text[:index])
    return words[-1].lower() if words else ""


def apply(text: str) -> str:
    """The text with each name said in a style written in that style."""
    search = 0
    while (match := _COMMAND.search(text, search)) is not None:
        search = match.start() + 1
        words = _GLUED_WORD.findall(match["glued"] or "")
        if not words and _word_before(text, match.start()) in _NOUN_BEFORE:
            continue
        end = match.end()
        while (following := _NEXT_WORD.match(text, end)) is not None:
            word = following["word"]
            if word.lower() in _STOP or _COMMAND.match(text, following.start("word")):
                break
            words.append(word)
            end = following.end()
        if not words:
            continue  # "on écrit en snake case": the style named, not used
        name = _identifier(words, _style(match))
        text = text[:match.start()] + name + text[end:]
        search = match.start() + len(name)
    return text
