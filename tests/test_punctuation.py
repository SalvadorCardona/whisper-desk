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

    def test_a_negation_with_pas_still_ends_on_a_full_stop(self):
        self.assertEqual(punctuation.apply("Je ne viens pas demain point"),
                         "Je ne viens pas demain.")


class EnclosingTest(unittest.TestCase):
    """Quotes and brackets said aloud become the marks they name."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(punctuation.apply(said), written)

    def test_french_quotes(self):
        self.check("Il m'a dit ouvrez les guillemets pas question fermez les guillemets point",
                   "Il m'a dit « pas question ».")
        self.check("Il a écrit j'ouvre les guillemets à demain je ferme les guillemets",
                   "Il a écrit « à demain »")
        self.check("Le mot guillemets ouvrants urgent guillemets fermants revient souvent",
                   "Le mot « urgent » revient souvent")

    def test_french_brackets(self):
        self.check("Tu viens ouvrez la parenthèse ou pas fermez la parenthèse point d'interrogation",
                   "Tu viens (ou pas) ?")
        self.check("Le budget parenthèse ouvrante hors taxes parenthèse fermante est validé",
                   "Le budget (hors taxes) est validé")

    def test_english_quotes_and_brackets(self):
        self.check("He said open quote I'll be back close quote period",
                   'He said "I\'ll be back".')
        self.check("The word open quotes urgent end quote comes back", 'The word "urgent" comes back')
        self.check("Call me open paren after six close paren tomorrow",
                   "Call me (after six) tomorrow")
        self.check("The fee left parenthesis tax included right parenthesis is paid",
                   "The fee (tax included) is paid")

    def test_whisper_own_punctuation_around_the_words_gives_way(self):
        self.check("Il m'a dit, ouvrez les guillemets, pas question, fermez les guillemets.",
                   "Il m'a dit « pas question ».")
        self.check("He said, open quote, I'll be back. Close quote.", 'He said "I\'ll be back".')

    def test_whisper_own_quotes_give_way_to_those_said(self):
        self.check("Le client écrit « Ouvrez les guillemets merci » pour tout fermer les guillemets.",
                   "Le client écrit « merci pour tout ».")

    def test_a_pause_heard_between_the_words(self):
        self.check("She wrote open, quote, see you soon, close, quote, period.",
                   'She wrote "see you soon".')

    def test_parenthese_ouvrant_as_whisper_hears_it(self):
        self.check("Le titre parenthèse ouvrant version 2 parenthèse fermant est bon.",
                   "Le titre (version 2) est bon.")

    def test_a_question_heard_before_the_closing_mark_is_quoted(self):
        self.check("Il a demandé ouvrez les guillemets tu viens ? Fermez les guillemets.",
                   "Il a demandé « tu viens ? »")

    def test_a_mark_said_after_the_closing_one_wins(self):
        self.check("Il a dit ouvrez les guillemets oui fermez les guillemets. Virgule, puis il est parti.",
                   "Il a dit « oui », puis il est parti.")

    def test_what_is_quoted_first_takes_a_capital(self):
        self.check("Ouvrez les guillemets bonjour fermez les guillemets", "« Bonjour »")
        self.check("Fin point ouvrez les guillemets bonjour fermez les guillemets",
                   "Fin. « Bonjour »")

    def test_a_closing_mark_alone_in_its_sentence(self):
        self.check("Close quote.", '"')
        self.check("Fermez la parenthèse.", ")")
        self.check("Ouvrez les guillemets.", "« ")

    def test_the_words_said_as_words_stay(self):
        for said in ("Send me a quote.", "He is a quote unquote expert.", "Put it in brackets.",
                     "La parenthèse est fermée.", "Il faut ouvrir la porte.",
                     "Soit dit entre parenthèses, c'est faux.", "Mettez-le entre guillemets.",
                     "It is an open question.", "We are close to the end."):
            with self.subTest(said):
                self.assertEqual(punctuation.apply(said), said)


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

    def test_a_quote_or_a_bracket_said_after_a_pause(self):
        self.assertEqual(punctuation.join(["Il a dit « ", "Pas question.", " »"]),
                         "Il a dit « Pas question. »")
        self.assertEqual(punctuation.join(['He said "', "No way.", '"', "Then he left."]),
                         'He said "No way." Then he left.')
        self.assertEqual(punctuation.join(["Rappelle-moi (", "demain", ")", "merci."]),
                         "Rappelle-moi (demain) merci.")


if __name__ == "__main__":
    unittest.main()
