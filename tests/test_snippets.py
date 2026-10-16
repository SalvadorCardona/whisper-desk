"""Snippets: the spoken cue gives way to the text saved for it."""

from __future__ import annotations

import csv
import logging
import tomllib
import unittest
from pathlib import Path

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk.snippets import expand

logging.getLogger("whisper-desk.snippets").setLevel(logging.CRITICAL)

BENCH = Path(__file__).resolve().parents[1] / "bench" / "snippets"

# The sentences stay in French where Whisper writes them so: accents, the
# hyphens of "e-mail", the capital it puts at the start of every sentence.
SNIPPETS = {
    "mon adresse mail": "salva@example.com",
    "mon adresse pro": "salva@animalink.io",
    "ma signature": "Bien à vous,\nSalva",
    "my calendar link": "https://cal.example.com/salva",
}


class ExpandTest(unittest.TestCase):
    def check(self, said: str, written: str) -> None:
        self.assertEqual(expand(said, SNIPPETS), written)

    def test_a_cue_said_on_its_own_is_the_saved_text_alone(self):
        """Whisper closes the sentence with a dot: no dot left after the text."""
        self.check("Ma signature.", "Bien à vous,\nSalva")
        self.check("My calendar link!", "https://cal.example.com/salva")

    def test_a_cue_inside_a_sentence(self):
        self.check(
            "Écris-moi à mon adresse mail, je réponds vite.",
            "Écris-moi à salva@example.com, je réponds vite.",
        )
        self.check(
            "Book a slot on my calendar link.",
            "Book a slot on https://cal.example.com/salva.",
        )

    def test_a_cue_after_another_sentence(self):
        self.check("Merci pour tout. Ma signature.", "Merci pour tout. Bien à vous,\nSalva")

    def test_case_accents_and_punctuation_do_not_count(self):
        self.check("MON ADRESSE MAIL.", "salva@example.com")
        self.check("Mon adresse, mail.", "salva@example.com")
        self.assertEqual(expand("Ma signature.", {"Ma Signature !": "S."}), "S.")
        self.assertEqual(expand("Mon numéro.", {"mon numero": "06"}), "06")
        self.assertEqual(expand("Mon numero.", {"mon numéro": "06"}), "06")

    def test_a_word_cut_in_two_by_the_model_still_matches(self):
        """Whisper writes "stand-up" or "e-mail" for the cues "standup", "email"."""
        cues = {"my standup update": "Done.", "my email": "a@b.c", "mon e-mail": "x@y.z"}
        self.assertEqual(expand("My stand-up update.", cues), "Done.")
        self.assertEqual(expand("Write to my e-mail now.", cues), "Write to a@b.c now.")
        self.assertEqual(expand("Mon email.", cues), "x@y.z")
        self.assertEqual(expand("Mon e mail.", cues), "x@y.z")

    def test_the_longest_cue_wins(self):
        self.check("Mon adresse pro.", "salva@animalink.io")

    def test_several_cues_in_one_sentence(self):
        self.check(
            "Mon adresse mail ou mon adresse pro.",
            "salva@example.com ou salva@animalink.io.",
        )

    def test_a_cue_is_whole_words_only(self):
        """"mon adresse mailing" is not "mon adresse mail" with "ing" hanging on."""
        self.check("Vérifie mon adresse mailing.", "Vérifie mon adresse mailing.")
        self.check("Ma signatures.", "Ma signatures.")

    def test_an_expansion_is_never_expanded_again(self):
        loop = {"un": "un deux", "deux": "trois"}
        self.assertEqual(expand("Un.", loop), "un deux")

    def test_regular_expression_characters_are_plain_text(self):
        self.assertEqual(expand("Mon C++ préféré.", {"c++": "x"}), "Mon x++ préféré.")
        self.assertEqual(expand("A.B.", {"(a)": "z"}), "z.B.")

    def test_nothing_to_expand(self):
        self.check("Une phrase ordinaire.", "Une phrase ordinaire.")
        self.assertEqual(expand("Ma signature.", {}), "Ma signature.")
        self.assertEqual(expand("", SNIPPETS), "")

    def test_an_empty_cue_or_expansion_is_ignored(self):
        broken = {"": "x", "...": "y", "ma signature": "", "mon adresse": 3}
        self.assertEqual(expand("Ma signature, mon adresse.", broken),
                         "Ma signature, mon adresse.")


class CorpusTest(unittest.TestCase):
    """The written sentences of bench/snippets/ come out as expected, all of them."""

    def test_the_corpus(self):
        with (BENCH / "snippets.toml").open("rb") as handle:
            saved = tomllib.load(handle)
        with (BENCH / "corpus.tsv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertGreater(len(rows), 20)
        for row in rows:
            with self.subTest(row["id"]):
                expected = row["expected"].replace("\\n", "\n")
                self.assertEqual(expand(row["spoken"], saved), expected)


if __name__ == "__main__":
    unittest.main()
