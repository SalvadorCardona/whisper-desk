"""Spoken punctuation: "virgule", "à la ligne", "ouvrez les guillemets" become their mark."""

from __future__ import annotations

import re

# Spoken words -> (mark, language). The language sets the spacing: French puts
# a space before "?", "!", ":" and ";", as Whisper does when it writes French.
_COMMANDS: dict[str, tuple[str, str]] = {
    "virgule": (",", "fr"),
    "point": (".", "fr"),
    # "des œufs point." comes back "des œufs points.", the plural heard in the liaison.
    "points": (".", "fr"),
    "point d'interrogation": ("?", "fr"),
    "point d'exclamation": ("!", "fr"),
    "point-virgule": (";", "fr"),
    "deux-points": (":", "fr"),
    "à la ligne": ("\n", "fr"),
    "retour à la ligne": ("\n", "fr"),
    "nouvelle ligne": ("\n", "fr"),
    "nouveau paragraphe": ("\n\n", "fr"),
    "comma": (",", "en"),
    "period": (".", "en"),
    "full stop": (".", "en"),
    "question mark": ("?", "en"),
    "exclamation mark": ("!", "en"),
    "exclamation point": ("!", "en"),
    "semicolon": (";", "en"),
    "colon": (":", "en"),
    "new line": ("\n", "en"),
    "newline": ("\n", "en"),
    "new paragraph": ("\n\n", "en"),
}
# Quotes and brackets said aloud -> (mark, opens, language). French quotes are
# « », with the space French puts inside them; English ones are straight, as a
# keyboard types them. Bare "quote", "bracket", "unquote" and "entre
# guillemets" are left out: they are ordinary words ("send me a quote", "a quote
# unquote expert", "soit dit entre parenthèses").
_ENCLOSING: dict[str, tuple[str, bool, str]] = {}
# Whisper hears "parenthèse ouvrante" as "parenthèse ouvrant" as often as not.
for _side, _opens in (("ouvrant", True), ("fermant", False)):
    for _ending in ("", "e", "s", "es"):
        _ENCLOSING[f"guillemet {_side}{_ending}"] = ("«»"[not _opens], _opens, "fr")
        _ENCLOSING[f"guillemets {_side}{_ending}"] = ("«»"[not _opens], _opens, "fr")
        _ENCLOSING[f"parenthèse {_side}{_ending}"] = ("()"[not _opens], _opens, "fr")
for _verb, _opens in (("ouvrez", True), ("ouvre", True), ("ouvrir", True), ("j'ouvre", True),
                      ("on ouvre", True), ("fermez", False), ("ferme", False), ("fermer", False),
                      ("je ferme", False), ("on ferme", False)):
    for _what, _marks in (("les guillemets", "«»"), ("le guillemet", "«»"),
                          ("la parenthèse", "()"), ("les parenthèses", "()")):
        _ENCLOSING[f"{_verb} {_what}"] = (_marks[not _opens], _opens, "fr")
for _noun in ("quote", "quotes"):
    _ENCLOSING[f"open {_noun}"] = ('"', True, "en")
    _ENCLOSING[f"close {_noun}"] = _ENCLOSING[f"end {_noun}"] = ('"', False, "en")
for _noun in ("paren", "parens", "parenthesis", "parentheses"):
    _ENCLOSING[f"open {_noun}"] = _ENCLOSING[f"left {_noun}"] = ("(", True, "en")
    _ENCLOSING[f"close {_noun}"] = _ENCLOSING[f"right {_noun}"] = (")", False, "en")
_COMMANDS.update({phrase: (mark, language) for phrase, (mark, _, language) in _ENCLOSING.items()})
# Words that are also ordinary words: "mon point de vue", "the trial period".
# They are a mark only where a full stop can stand — at the end of what was
# said, before Whisper's own full stop, a capital or another mark. A comma
# after them is Whisper hearing the word go on ("a good point, let me think"),
# unless it set the word apart on both sides: "and eggs, period, then".
_AMBIGUOUS = {"point", "points", "period"}
# A colon or a line break comes before words, but not before these:
# "deux points d'avance", "colon cancer", "la ligne de départ", "a new line of".
_NOUN_AFTER = {"de", "d", "en", "sur", "of", "cancer", "in", "for"}
_NOUN_AFTER_CHECKED = {"deux-points", "colon", "à la ligne", "nouvelle ligne", "new line"}
# A word in front that makes the command a noun: "une virgule", "le point",
# "a new line of products", "the grace period", "à point", "marqué deux points".
_NOUN_BEFORE = {
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "au", "aux", "à",
    "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa",
    "ses", "notre", "nos", "votre", "vos", "leur", "leurs", "quel", "quelle", "chaque",
    "aucun", "aucune", "bon", "mauvais", "seul", "même", "dernier", "premier", "par",
    "sur", "pêche", "marqué", "gagné", "perdu",
    "the", "a", "an", "this", "that", "these", "those", "my", "your", "his", "her",
    "its", "our", "their", "each", "every", "no", "any", "some", "same", "one",
    "trial", "grace", "waiting", "notice", "cooling", "billing", "time", "whole",
    "short", "long", "good", "bad", "oxford", "serial",
}
# Before a quote or a bracket said aloud, only an article makes it a noun:
# "the close quote", "les guillemets ouvrants"; "the short one close paren" is a mark.
_ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "the", "a", "an"}
_NUMBERS = {
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "zero", "one", "two", "three", "four", "five", "seven", "eight", "nine",
}
# "trois points", "plusieurs points": a count, not a full stop.
_COUNTS = _NUMBERS | {"dix", "vingt", "cent", "mille", "plusieurs", "quelques", "nombreux"}
_MARKS = ",.;:!?…"


def _spoken(phrase: str) -> str:
    """The phrase as Whisper may write it: "point-virgule" or "point virgule"."""
    words = re.split(r"[\s'-]+", phrase)
    joints = re.findall(r"[\s'-]+", phrase)
    # "open, quote": Whisper hears a pause between the words of a quote or a bracket.
    space = r",?[\s-]+" if phrase in _ENCLOSING else r"[\s-]+"
    out = re.escape(words[0])
    for joint, word in zip(joints, words[1:]):
        out += r"['’]\s*" if "'" in joint else space
        out += re.escape(word)
    return out


_KEYS = {re.sub(r"[\s,'’-]+", " ", phrase): phrase for phrase in _COMMANDS}
_COMMAND = re.compile(
    rf"(?P<before>[\s{_MARKS}]*)(?<![\w'’])"
    rf"(?P<command>{'|'.join(_spoken(p) for p in sorted(_COMMANDS, key=len, reverse=True))})"
    rf"(?![\w'’-])(?P<after>[\s{_MARKS}]*)",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w+")


def _phrase(match: re.Match[str]) -> str:
    return _KEYS[re.sub(r"[\s,'’-]+", " ", match["command"].lower())]


def _word_before(text: str, index: int) -> str:
    words = _WORD.findall(text[:index])
    return words[-1].lower() if words else ""


def _word_after(text: str, index: int) -> str:
    found = _WORD.search(text, index)
    return found[0].lower() if found else ""


def _meant(text: str, match: re.Match[str]) -> bool:
    """Whether the words name a mark rather than say something."""
    phrase = _phrase(match)
    # Whisper glues a comma it did not understand to the word before:
    # "prêt virgule" comes back "pré-virgule". Other commands stay out of
    # words like "rond-point".
    glued = text[:match.start("command")].lower()
    if glued.endswith("-") and (phrase != "virgule" or glued.endswith("point-")):
        return False
    # Whisper's own punctuation between the word before and the command is a
    # pause: what comes before cannot make it a noun.
    nouns = _ARTICLES if phrase in _ENCLOSING else _NOUN_BEFORE
    if not match["before"].strip() and _word_before(text, match.start()) in nouns:
        return False
    # "trois virgule cinq" is a number.
    if _COMMANDS[phrase][0] == "," and (
        _word_before(text, match.start()) in _NUMBERS or _word_before(text, match.start()).isdigit()
    ) and (_word_after(text, match.end()) in _NUMBERS or _word_after(text, match.end()).isdigit()):
        return False
    if (phrase in _NOUN_AFTER_CHECKED and not match["after"].strip()
            and _word_after(text, match.end()) in _NOUN_AFTER):
        return False
    # "Il ne viendra point": the old negation, when no "pas" took its place.
    if phrase == "point":
        near = [w.lower() for w in _WORD.findall(text[:match.start()])[-4:]]
        if ("ne" in near or "n" in near) and not {"pas", "plus", "jamais", "rien"} & set(near):
            return False
    if phrase == "points" and (_word_before(text, match.start()) in _COUNTS
                               or _word_before(text, match.start()).isdigit()):
        return False
    if phrase in _AMBIGUOUS:
        rest = text[match.end():]
        if not rest or any(c in ".?!…" for c in match["after"]):
            return True
        if match["before"].strip() and match["after"].strip():
            return True
        if match["after"].strip() or not rest[0].isupper() or _word_after(text, match.end()) == "i":
            follower = _COMMAND.match(text, match.end() - len(match["after"]))
            return bool(follower and not follower["before"].strip() and _meant(text, follower))
    return True


def _cased(chunk: str, case: str) -> str:
    found = re.search(r"\w+", chunk)
    if not case or not found:
        return chunk
    word = found[0]
    if case == "upper":
        word = word[0].upper() + word[1:]
    # Whisper capitalised it after a full stop the command stood in for; "I"
    # and acronyms keep their capitals.
    elif word != "I" and not (len(word) > 1 and word.isupper()):
        word = word[0].lower() + word[1:]
    return chunk[:found.start()] + word + chunk[found.end():]


def _enclose(out: str, text: str, match: re.Match[str], case: str) -> tuple[str, str]:
    """The text so far with the quote or bracket said aloud, and the case of what follows."""
    mark, opens, language = _ENCLOSING[_phrase(match)]
    out = out.rstrip(" ")
    if opens:
        # Whisper's punctuation before an opening mark is the pause taken to say it.
        if out and out[-1] not in "\n(«" and not _opened_quote(out):
            out += " "
        out += mark + (" " if mark == "«" else "")
        if not out.rstrip(' «("') or out.rstrip(' «("').endswith("\n"):
            case = "upper"
        return out, case
    # A question or an exclamation Whisper heard before the closing mark is
    # quoted; any other sentence end it heard goes after the mark, unless a
    # mark said right after takes its place.
    before, after = match["before"].strip(), match["after"].strip()
    spaced = " " if language == "fr" else ""
    # Said after a pause, alone in its sentence, or after a mark that ends the
    # quote: Whisper's full stop is no end.
    ended = not out or out[-1] in ".?!…"
    inside = before[-1:] if before[-1:] in ("?", "!") else ""
    if inside:
        out += (spaced if out[-1:] not in "«(\"" else "") + inside
    out += (" " if mark == "»" else "") + mark
    ending = "" if inside or ended else next((c for c in before + after if c in ".?!…"), "")
    follower = _COMMAND.match(text, match.end() - len(match["after"]))
    if ending and not (follower and _meant(text, follower)):
        out += (spaced if ending in "?!" else "") + ending
    if match.end() < len(text):
        out += " "
    return out, ""


def _opened_quote(text: str) -> bool:
    """Whether the text ends on a straight quote that opens a quotation."""
    return text.endswith('"') and text.count('"') % 2 == 1


def apply(text: str) -> str:
    """The text with each punctuation said aloud turned into its mark."""
    # Whisper often puts quotes of its own around "ouvrez les guillemets" and
    # what follows; the quotes said aloud take their place.
    if any(_phrase(m) in _ENCLOSING and _ENCLOSING[_phrase(m)][0] in '«»"' and _meant(text, m)
           for m in _COMMAND.finditer(text)):
        text = re.sub(r" {2,}", " ", re.sub(r'[«»“”"]', "", text)).strip()
    out = ""
    case = ""
    position = 0
    search = 0
    while (match := _COMMAND.search(text, search)) is not None:
        if not _meant(text, match):
            search = match.start("command") + 1
            continue
        chunk = text[position:match.start()]
        out += _cased(chunk, case)
        phrase = _phrase(match)
        # The capital owed after a full stop said goes to the first word quoted.
        if phrase not in _ENCLOSING or not _ENCLOSING[phrase][1] or _WORD.search(chunk):
            case = ""
        mark, language = _COMMANDS[phrase]
        before = match["before"].strip()
        after = match["after"].strip()
        spaced = " " if language == "fr" else ""
        if phrase in _ENCLOSING:
            out, case = _enclose(out, text, match, case)
        elif mark.startswith("\n"):
            # The sentence before keeps its end; when Whisper put it after the
            # command ("demain à la ligne."), it goes back to its sentence.
            ending = match["before"].rstrip() if before else ""
            if not ending and out and out.rstrip()[-1:] not in _MARKS and after[:1] in (".", "?", "!"):
                ending = (spaced if after[0] in "?!" else "") + after[0]
            out = out.rstrip(" ") + ending + mark
            case = "upper"
        else:
            out = re.sub(r"(?<=\w)-$", "", out.rstrip(" "))  # "Marie-Virgule"
            out += (spaced if mark in "?!:;" else "") + mark
            if match.end() < len(text):
                out += " "
            if mark in ".?!":
                case = "upper"
            elif any(c in ".?!" for c in before + after):
                case = "lower"
        position = search = match.end()
    return out + _cased(text[position:], case)


def separator(before: str, after: str) -> str:
    """What goes between a sentence already inserted and the next one.

    A sentence that opens on a mark ("Virgule." said after a pause) or follows a
    line break is glued to what came before, and so is one that closes a quote
    or a bracket, or follows the opening one.
    """
    if not before or not after or before[-1].isspace() or after[0].isspace():
        return ""
    if after[0] in _MARKS + ")" or before[-1] == "(" or _opened_quote(before):
        return ""
    if after[0] == '"' and before.count('"') % 2:
        return ""
    return " "


def join(parts: list[str]) -> str:
    """The sentences of a dictation, as they were inserted one after the other."""
    text = ""
    for part in parts:
        text += separator(text, part) + part
    return text
