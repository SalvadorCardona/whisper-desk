"""Names said in a style written in that style."""

from __future__ import annotations

import unittest

from . import context  # noqa: F401  (adds src/ to the import path)

from whisper_desk import casing


class StylesTest(unittest.TestCase):
    """Each style joins the words its own way."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(casing.apply(said), written)

    def test_each_style(self):
        self.check("Rename camel case user name", "Rename userName")
        self.check("The class is pascal case invoice generator", "The class is InvoiceGenerator")
        self.check("Add the column snake case created at", "Add the column created_at")
        self.check("Name the folder kebab case user settings", "Name the folder user-settings")
        self.check("Name the folder dash case user settings", "Name the folder user-settings")
        self.check("Set constant case max retries", "Set MAX_RETRIES")
        self.check("Set screaming snake case max retries", "Set MAX_RETRIES")

    def test_the_case_whisper_wrote_is_left_out(self):
        self.check("Set constant case API base URL", "Set API_BASE_URL")
        self.check("Rename Camel Case User ID", "Rename userId")
        self.check("The class is Paschal Case Invoice Generator", "The class is InvoiceGenerator")

    def test_numbers_are_part_of_the_name(self):
        self.check("Call camel case get user 2", "Call getUser2")


class ExtentTest(unittest.TestCase):
    """The name runs until the sentence goes on."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(casing.apply(said), written)

    def test_a_mark_ends_the_name(self):
        self.check("On garde pascal case user repository, pas l'autre",
                   "On garde UserRepository, pas l'autre")
        self.check("The variable is constant case database url.", "The variable is DATABASE_URL.")

    def test_a_word_of_the_sentence_ends_the_name(self):
        self.check("Le champ camel case first name est obligatoire",
                   "Le champ firstName est obligatoire")
        self.check("Ajoute la colonne snake case created at dans la table",
                   "Ajoute la colonne created_at dans la table")
        self.check("Call camel case fetch orders and wait for the result",
                   "Call fetchOrders and wait for the result")
        self.check("Import camel case use effect from React", "Import useEffect from React")

    def test_by_and_at_belong_to_the_name(self):
        self.check("Crée camel case get user by id qui renvoie l'utilisateur",
                   "Crée getUserById qui renvoie l'utilisateur")

    def test_another_style_ends_the_name(self):
        self.check("Appelle snake case send email snake case log event",
                   "Appelle send_email log_event")
        self.check("Appelle snake case send email puis camel case log event",
                   "Appelle send_email puis logEvent")


class WhisperFormsTest(unittest.TestCase):
    """The ways Whisper writes the command."""

    def check(self, said: str, written: str) -> None:
        self.assertEqual(casing.apply(said), written)

    def test_glued_to_the_name(self):
        self.check("Rename the variable camelCaseUserName.", "Rename the variable userName.")
        self.check("The function SnakeCaseParseDate returns a string.",
                   "The function parse_date returns a string.")

    def test_glued_command_then_the_name(self):
        self.check("Import CamelCase Use Effect from React.", "Import useEffect from React.")
        self.check("Call camelCase, fetch orders, and wait.", "Call fetchOrders, and wait.")

    def test_hyphenated(self):
        self.check("The variable is constant-case-database-url.", "The variable is DATABASE_URL.")
        self.check("Use snake-case user id as the key", "Use user_id as the key")

    def test_a_comma_inside_the_command(self):
        self.check("Ajoute la colonne snake, case created at", "Ajoute la colonne created_at")


class WordsKeptTest(unittest.TestCase):
    """The same words said as words stay."""

    def keeps(self, said: str) -> None:
        self.assertEqual(casing.apply(said), said)

    def test_a_style_named_not_used(self):
        self.keeps("Toutes nos colonnes sont en snake case.")
        self.keeps("We use camel case for variables and snake case for columns.")
        self.keeps("We use CamelCase for variables, then SnakeCase for columns.")
        self.keeps("Is it camel case?")

    def test_a_determiner_makes_it_a_noun(self):
        self.keeps("On a mangé un kebab, case départ pour tout le monde")
        self.keeps("That is a constant case of bad luck.")
        self.keeps("The Pascal case convention is common in C sharp.")

    def test_no_style_no_change(self):
        self.keeps("J'ai rangé le serpent dans une case du vivarium.")
        self.keeps("The snake hid in a case under the bed.")
        self.keeps("Blaise Pascal wrote about probability.")
        self.keeps("Le kebab est bon.")
        self.keeps("A showcase of snakes.")

    def test_inside_a_word(self):
        self.keeps("The supersnake case files.")


if __name__ == "__main__":
    unittest.main()
