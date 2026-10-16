"""Corrections said aloud, carried out — and ordinary sentences left alone."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk.backtrack import apply

CORPUS = Path(__file__).resolve().parents[1] / "bench" / "backtrack" / "corpus.tsv"
# Sentences of the corpus the rules still get wrong: the measure counts them,
# the test makes sure the list only ever shrinks.
KNOWN_MISSES = {"fr15", "fr19"}


class CorrectionTest(unittest.TestCase):
    # The sample sentences are dictations: they stay in the language spoken.

    def test_a_weekday_replaces_the_weekday(self):
        self.assertEqual(apply("On se voit mardi, non, plutôt mercredi."), "On se voit mercredi.")

    def test_a_number_replaces_the_number(self):
        self.assertEqual(apply("Let's meet at 2, actually 3."), "Let's meet at 3.")

    def test_the_correction_starts_over_from_the_repeated_word(self):
        self.assertEqual(
            apply("Envoie le dossier à Paul, non, je veux dire à Marie."),
            "Envoie le dossier à Marie.",
        )

    def test_a_strong_marker_replaces_as_many_words(self):
        self.assertEqual(apply("Le chat est noir, non, plutôt gris."), "Le chat est gris.")

    def test_the_determiner_goes_with_the_word_it_announced(self):
        self.assertEqual(
            apply("On déploie en production ce soir, non, plutôt demain."),
            "On déploie en production demain.",
        )

    def test_a_correction_may_open_a_new_sentence(self):
        self.assertEqual(apply("On se voit mardi. Non, plutôt mercredi."), "On se voit mercredi.")

    def test_the_text_after_the_correction_is_kept(self):
        self.assertEqual(
            apply("Le chat est noir, non, plutôt gris. Il dort."),
            "Le chat est gris. Il dort.",
        )

    def test_the_sentences_before_are_left_alone(self):
        self.assertEqual(
            apply("Bonjour. On se voit mardi, non, plutôt mercredi."),
            "Bonjour. On se voit mercredi.",
        )

    def test_or_rather_needs_no_pause(self):
        self.assertEqual(
            apply("Il faut livrer la version 2 ou plutôt la version 3."),
            "Il faut livrer la version 3.",
        )

    def test_two_corrections_in_a_row(self):
        self.assertEqual(
            apply("Je pars lundi, non, plutôt mardi, non, plutôt jeudi."),
            "Je pars jeudi.",
        )


class LeftAloneTest(unittest.TestCase):
    def test_without_a_pause_the_marker_is_a_word_of_the_sentence(self):
        for text in ("C'est plutôt une bonne nouvelle.", "I actually think so."):
            self.assertEqual(apply(text), text)

    def test_an_answer_is_not_a_correction(self):
        for text in ("Tu viens ? Non, je reste.", "Pardon, je n'avais pas vu."):
            self.assertEqual(apply(text), text)

    def test_a_weak_marker_needs_something_to_line_up_with(self):
        text = "Il a dit non, et il est parti."
        self.assertEqual(apply(text), text)

    def test_an_empty_text_stays_empty(self):
        self.assertEqual(apply(""), "")


class CorpusTest(unittest.TestCase):
    """The sentences of the measure, written out, give the expected text."""

    def test_the_corpus(self):
        with CORPUS.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        for row in rows:
            if row["id"] in KNOWN_MISSES:
                continue
            with self.subTest(row["id"]):
                self.assertEqual(apply(row["spoken"]), row["expected"])

    def test_the_known_misses_are_still_missed(self):
        """A rule that fixes one of them: take it off the list."""
        with CORPUS.open(encoding="utf-8") as handle:
            rows = {row["id"]: row for row in csv.DictReader(handle, delimiter="\t")}
        for name in KNOWN_MISSES:
            with self.subTest(name):
                self.assertNotEqual(apply(rows[name]["spoken"]), rows[name]["expected"])


if __name__ == "__main__":
    unittest.main()
