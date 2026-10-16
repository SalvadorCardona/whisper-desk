"""Snippets: a spoken cue replaced by the text saved for it."""

from __future__ import annotations

import unittest

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import snippets
from whisper_desk.snippets import Snippets

TABLE = {
    "mon adresse": "12 rue des Lilas, 75011 Paris",
    "mon adresse pro": "4 place du Marché, 69002 Lyon",
    "my calendar link": "https://cal.com/salva/30min",
    "ma signature": "Bien à vous,\nSalvador",
    "can": "CAN bus",
}


def expand(text: str) -> str:
    return snippets.apply(text, TABLE)


class AloneTest(unittest.TestCase):
    """Said on its own, the cue gives the snippet exactly as saved."""

    def test_whisper_capital_and_full_stop_are_dropped(self):
        self.assertEqual(expand("Mon adresse."), "12 rue des Lilas, 75011 Paris")

    def test_spacing_and_punctuation_between_words_do_not_matter(self):
        self.assertEqual(expand("  My, calendar link !"), "https://cal.com/salva/30min")

    def test_a_multiline_snippet_keeps_its_lines(self):
        self.assertEqual(expand("Ma signature."), "Bien à vous,\nSalvador")


class InSentenceTest(unittest.TestCase):
    """Inside a sentence, the cue alone is replaced, the rest stays."""

    def test_the_cue_is_replaced_in_place(self):
        self.assertEqual(
            expand("Envoie le colis à mon adresse, merci."),
            "Envoie le colis à 12 rue des Lilas, 75011 Paris, merci.",
        )

    def test_case_is_ignored(self):
        self.assertEqual(
            expand("Book a slot: My Calendar Link."),
            "Book a slot: https://cal.com/salva/30min.",
        )

    def test_whisper_punctuation_inside_the_cue_is_ignored(self):
        self.assertEqual(expand("Voici mon, adresse."), "Voici 12 rue des Lilas, 75011 Paris.")

    def test_the_longest_cue_wins(self):
        self.assertEqual(
            expand("Livre-le à mon adresse pro."), "Livre-le à 4 place du Marché, 69002 Lyon."
        )

    def test_every_cue_of_the_sentence_is_replaced(self):
        self.assertEqual(
            expand("Mon adresse ou mon adresse pro"),
            "12 rue des Lilas, 75011 Paris ou 4 place du Marché, 69002 Lyon",
        )

    def test_a_snippet_ending_on_a_full_stop_does_not_double_it(self):
        self.assertEqual(
            snippets.apply("Voici ma signature.", {"ma signature": "Salvador."}),
            "Voici Salvador.",
        )


class BoundaryTest(unittest.TestCase):
    """A cue is a whole word or nothing."""

    def test_not_inside_a_longer_word(self):
        self.assertEqual(expand("Mon adresses sont fausses."), "Mon adresses sont fausses.")
        self.assertEqual(expand("A scan of it."), "A scan of it.")

    def test_not_inside_a_contraction(self):
        self.assertEqual(expand("I can't come."), "I can't come.")

    def test_a_possessive_still_expands(self):
        self.assertEqual(expand("The can's lid."), "The CAN bus's lid.")

    def test_nothing_to_do_without_a_cue(self):
        self.assertEqual(expand("Rien à remplacer ici."), "Rien à remplacer ici.")


class TableTest(unittest.TestCase):
    """What the [snippets] section may hold."""

    def test_no_snippet_at_all(self):
        self.assertEqual(snippets.apply("Mon adresse.", {}), "Mon adresse.")

    def test_an_empty_text_switches_the_snippet_off(self):
        self.assertEqual(snippets.apply("Mon adresse.", {"mon adresse": "  "}), "Mon adresse.")

    def test_a_cue_without_words_is_ignored(self):
        self.assertEqual(snippets.apply("Oui ! Non.", {"!": "bang"}), "Oui ! Non.")

    def test_a_text_that_is_not_a_string_is_ignored(self):
        with self.assertLogs("whisper-desk.snippets", "WARNING"):
            table = Snippets({"mon adresse": 12, "ma ville": "Paris"})
        self.assertEqual(table.apply("Mon adresse à ma ville."), "Mon adresse à Paris.")

    def test_the_text_is_trimmed_as_in_toml_multiline_strings(self):
        self.assertEqual(snippets.apply("Ma ville.", {"ma ville": "\nParis\n"}), "Paris")

    def test_only_the_words_of_a_cue_count(self):
        # Punctuation in a cue is neither a pattern nor a word to say.
        self.assertEqual(snippets.apply("Voir mon site.", {"(mon) site.*": "cardona.digital"}),
                         "Voir cardona.digital.")


if __name__ == "__main__":
    unittest.main()
