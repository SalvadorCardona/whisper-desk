"""Hesitations and stuttered words left out of the text."""

from __future__ import annotations

import unittest

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk.hesitations import apply


class SoundsTest(unittest.TestCase):
    def test_a_hesitation_inside_a_sentence_goes_with_its_commas(self):
        self.assertEqual(apply("Je pense, euh, qu'on devrait partir."),
                         "Je pense qu'on devrait partir.")
        self.assertEqual(apply("I was, uh, thinking about it."), "I was thinking about it.")

    def test_a_hesitation_without_commas(self):
        self.assertEqual(apply("Il faut hum vérifier les logs."), "Il faut vérifier les logs.")
        self.assertEqual(apply("Il est euh... parti."), "Il est parti.")
        self.assertEqual(apply("Il est… euh… parti."), "Il est… parti.")
        self.assertEqual(apply("Il est... euh... parti."), "Il est... parti.")

    def test_the_sentence_it_opened_starts_with_a_capital(self):
        self.assertEqual(apply("Euh, je pense que oui."), "Je pense que oui.")
        self.assertEqual(apply("J'ai fini. Euh, on y va ?"), "J'ai fini. On y va ?")
        self.assertEqual(apply("Um, let's start."), "Let's start.")

    def test_a_hesitation_at_the_end_leaves_the_full_stop(self):
        self.assertEqual(apply("C'est bon, euh."), "C'est bon.")

    def test_drawn_out_spellings(self):
        self.assertEqual(apply("Alors euuuh on y va."), "Alors on y va.")
        self.assertEqual(apply("Hmmm, ok."), "Ok.")
        self.assertEqual(apply("Ummm, sure, erm, why not."), "Sure why not.")

    def test_nothing_but_a_hesitation_gives_no_text(self):
        self.assertEqual(apply("Euh..."), "")
        self.assertEqual(apply("Hum."), "")

    def test_real_words_stay(self):
        for sentence in (
            "J'ai eu un appel.",
            "Ah, je vois.",
            "Oh, really?",
            "Ben arrive demain.",
            "Err on the side of caution.",
            "Bonjour M. Dupont.",
            "L'humour de Hume.",
            "Ça va ?",
        ):
            self.assertEqual(apply(sentence), sentence)


class RepeatsTest(unittest.TestCase):
    def test_a_stuttered_word_is_written_once(self):
        self.assertEqual(apply("Je je pense que le le projet avance."),
                         "Je pense que le projet avance.")
        self.assertEqual(apply("The the report is ready."), "The report is ready.")
        self.assertEqual(apply("C'est c'est prêt."), "C'est prêt.")

    def test_a_word_said_three_times(self):
        self.assertEqual(apply("I I I think so."), "I think so.")

    def test_a_restart_of_several_words(self):
        self.assertEqual(apply("On va, on va faire une pause."), "On va faire une pause.")
        self.assertEqual(apply("We could, we could meet tomorrow."), "We could meet tomorrow.")

    def test_doubles_the_language_means(self):
        for sentence in (
            "Nous nous voyons demain.",
            "Vous vous trompez.",
            "C'est très très bien.",
            "I think that that is fine.",
            "He had had enough.",
            "What it is is a bug.",
            "Bye bye.",
            "Mon numéro est le 06 12 12 34 56.",
            "Composez le douze douze.",
        ):
            self.assertEqual(apply(sentence), sentence)

    def test_a_name_is_no_repeat(self):
        self.assertEqual(apply("Il parle de De Gaulle."), "Il parle de De Gaulle.")

    def test_a_repeat_across_sentences_stays(self):
        self.assertEqual(apply("Oui. Oui, c'est ça."), "Oui. Oui, c'est ça.")
        self.assertEqual(apply("C'est fini. Fini."), "C'est fini. Fini.")


if __name__ == "__main__":
    unittest.main()
