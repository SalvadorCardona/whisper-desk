"""Punctuation said aloud written as its mark."""

from __future__ import annotations

import unittest

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import punctuation


class MarksTest(unittest.TestCase):
    """A punctuation said aloud becomes its mark."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(punctuation.apply(said), written)

    def test_french_marks(self):
        self.check("Je viens demain virgule puis je pars point",
                   "Je viens demain, puis je pars.")
        self.check("Tu viens point d'interrogation", "Tu viens ?")
        self.check("Super point d’exclamation", "Super !")
        self.check("Le serveur est tombé point-virgule on relance",
                   "Le serveur est tombé ; on relance")
        self.check("Le serveur est tombé point virgule on relance",
                   "Le serveur est tombé ; on relance")
        self.check("Voici la liste deux points le pain", "Voici la liste : le pain")

    def test_english_marks(self):
        self.check("I will come comma but late period", "I will come, but late.")
        self.check("Did you get it question mark", "Did you get it?")
        self.check("Great exclamation point", "Great!")
        self.check("It failed semicolon we retry full stop", "It failed; we retry.")
        self.check("Three things colon milk", "Three things: milk")

    def test_whisper_own_punctuation_around_the_word_gives_way(self):
        self.check("Je viens demain, virgule, puis je pars. Point.",
                   "Je viens demain, puis je pars.")
        self.check("We need milk, comma, bread, and eggs, period.",
                   "We need milk, bread, and eggs.")

    def test_a_full_stop_said_capitalises_what_follows(self):
        self.check("On se voit à midi point Ensuite on mange point d'interrogation",
                   "On se voit à midi. Ensuite on mange ?")

    def test_a_comma_said_where_whisper_ended_the_sentence(self):
        self.check("Hello comma. How are you?", "Hello, how are you?")

    def test_line_breaks(self):
        self.check("Bonjour Marie virgule à la ligne merci point",
                   "Bonjour Marie,\nMerci.")
        self.check("Fin. Nouveau paragraphe. Ensuite", "Fin.\n\nEnsuite")
        self.check("Hi John comma new line thanks", "Hi John,\nThanks")
        self.check("Thanks new paragraph best", "Thanks\n\nBest")

    def test_the_sentence_end_whisper_put_after_a_line_break_goes_back(self):
        self.check("Bonjour à la ligne. Je voulais te dire merci.",
                   "Bonjour.\nJe voulais te dire merci.")

    def test_a_sentence_that_is_only_a_mark(self):
        self.check("Virgule.", ",")
        self.check("Point d'interrogation.", " ?")
        self.check("Question mark.", "?")
        self.check("À la ligne.", "\n")

    def test_a_comma_whisper_glued_to_the_word_before(self):
        self.check("Bonjour Marie-Virgule à la ligne merci.", "Bonjour Marie,\nMerci.")

    def test_points_heard_for_point(self):
        self.check("Il faut des oeufs points.", "Il faut des oeufs.")


class QuotesTest(unittest.TestCase):
    """Quotes and brackets said aloud open and close around what is said between."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(punctuation.apply(said), written)

    def test_french_quotes_and_brackets(self):
        self.check("Il m'a dit ouvrez les guillemets je reviens demain fermez les guillemets",
                   "Il m'a dit « je reviens demain »")
        self.check("La réunion ouvrez la parenthèse celle de lundi fermez la parenthèse est annulée",
                   "La réunion (celle de lundi) est annulée")
        self.check("On part ouvre la parenthèse si tout va bien ferme la parenthèse point",
                   "On part (si tout va bien).")

    def test_english_quotes_and_brackets(self):
        self.check("She said open quote I will be late close quote period",
                   'She said "I will be late".')
        self.check("The file is called open quote notes end quote", 'The file is called "notes"')
        self.check("We leave at ten open paren if all goes well close paren",
                   "We leave at ten (if all goes well)")
        self.check("He calls it quote a detail unquote comma but it matters",
                   'He calls it "a detail", but it matters')

    def test_with_the_other_marks_said(self):
        self.check("Elle a répondu deux points ouvrez les guillemets pas question fermez les "
                   "guillemets point", "Elle a répondu : « pas question ».")
        self.check("Il appelle ça ouvre les guillemets un détail ferme les guillemets virgule "
                   "mais c'est important", "Il appelle ça « un détail », mais c'est important")
        self.check("Il a crié ouvrez les guillemets au secours point d'exclamation fermez les "
                   "guillemets", "Il a crié « au secours ! »")
        self.check("She asked open quote are you coming question mark close quote",
                   'She asked "are you coming?"')

    def test_whisper_own_pauses_around_the_commands_go(self):
        self.check("Il m'a dit, ouvrez les guillemets, je reviens demain, fermez les guillemets.",
                   "Il m'a dit « je reviens demain ».")
        self.check("The meeting, open parenthesis, the one on Monday, close parenthesis, is off.",
                   "The meeting (the one on Monday) is off.")
        self.check("She said, open, quote, I will be late, close, quote.", 'She said "I will be late".')

    def test_whisper_own_quotes_around_the_command_go(self):
        self.check("Le titre est « Ouvrez les guillemets rapport annuel fermez les guillemets ».",
                   "Le titre est « rapport annuel ».")

    def test_a_command_heard_as_another_form_of_the_verb(self):
        self.check("Le titre est ouvré les guillemets rapport fermé les guillemets",
                   "Le titre est « rapport »")

    def test_what_follows_an_opening_at_the_start_takes_a_capital(self):
        self.check("Ouvrez la parenthèse à confirmer fermez la parenthèse", "(À confirmer)")
        self.check("Open parenthesis to be confirmed close parenthesis", "(To be confirmed)")

    def test_a_command_alone(self):
        self.check("Ouvrez les guillemets.", "« ")
        self.check("Fermez la parenthèse.", ").")
        self.check("Close quote.", '".')

    def test_the_other_half_makes_the_command_meant(self):
        self.check("The title is open quote Draft close quote", 'The title is "Draft"')


class WordsTest(unittest.TestCase):
    """The same words, said as words, stay words."""

    def check(self, said: str) -> None:
        self.assertEqual(punctuation.apply(said), said)

    def test_after_a_determiner(self):
        for said in ("Il manque une virgule.", "On fait le point.", "Put a question mark here.",
                     "C'est la nouvelle ligne de métro.", "We launched a new line of products.",
                     "You missed a comma.", "The trial period.", "C'est un bon point."):
            with self.subTest(said):
                self.check(said)

    def test_in_the_middle_of_a_sentence(self):
        for said in ("C'est mon point de vue.", "Point de départ demain.",
                     "That is a good point, let me think.", "The period ends tomorrow."):
            with self.subTest(said):
                self.check(said)

    def test_a_count_or_a_noun_after(self):
        for said in ("Il a marqué deux points.", "On a deux points d'avance.",
                     "Il a marqué trois points.", "He had colon cancer.",
                     "La ligne de départ est à la ligne de fond."):
            with self.subTest(said):
                self.check(said)

    def test_numbers(self):
        self.check("Le taux est de trois virgule cinq.")
        self.check("It is one comma five.")

    def test_words_that_hold_a_command(self):
        for said in ("On prend le rond-point.", "Le rond-point. Ensuite", "Il a pointé la carte.",
                     "Il ne viendra point.", "Un point-virgule manque."):
            with self.subTest(said):
                self.check(said)

    def test_quotes_and_brackets_said_as_words(self):
        for said in ("Il est temps de fermer la parenthèse.", "On ferme la parenthèse et on avance.",
                     "Elle a refermé la parenthèse.", "Il manque une parenthèse fermante.",
                     "We have an open quote request.", "Can I quote you on that?",
                     "The store is open, quote me if you want.", "He was, quote unquote, busy.",
                     "Il faut ouvrir les guillemets."):
            with self.subTest(said):
                self.check(said)

    def test_a_negation_with_pas_still_ends_on_a_full_stop(self):
        self.assertEqual(punctuation.apply("Je ne viens pas demain point"),
                         "Je ne viens pas demain.")


class JoinTest(unittest.TestCase):
    """The sentences of a dictation, as they reach the cursor one after another."""

    def test_sentences_are_separated_by_a_space(self):
        self.assertEqual(punctuation.join(["Hello.", "How are you?"]), "Hello. How are you?")

    def test_a_mark_opens_a_sentence_glued_to_the_one_before(self):
        self.assertEqual(punctuation.join(["Je viens demain", ",", "puis je pars."]),
                         "Je viens demain, puis je pars.")
        self.assertEqual(punctuation.join(["Tu viens", " ?"]), "Tu viens ?")

    def test_no_space_around_a_line_break(self):
        self.assertEqual(punctuation.join(["Bonjour,\n", "Merci."]), "Bonjour,\nMerci.")
        self.assertEqual(punctuation.join(["Bonjour.", "\nMerci."]), "Bonjour.\nMerci.")

    def test_no_space_inside_quotes_and_brackets(self):
        self.assertEqual(punctuation.join(["Il a dit « ", "je reviens", " »."]),
                         "Il a dit « je reviens ».")
        self.assertEqual(punctuation.join(["La réunion (", "celle de lundi", ") est annulée."]),
                         "La réunion (celle de lundi) est annulée.")
        self.assertEqual(punctuation.join(['She said "', 'I will', '".']), 'She said "I will".')


if __name__ == "__main__":
    unittest.main()
