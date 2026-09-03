"""Prompt glissant, vocabulaire, et tri des hallucinations de Whisper."""

from __future__ import annotations

import unittest
from unittest import mock

from . import context  # noqa: F401  (ajoute src/ au chemin d'import)

from linux_whisper.transcriber import CONTEXT_CHARS, Transcriber, is_filler

try:
    import numpy
except ImportError:  # la CI n'installe que la bibliothèque standard
    numpy = None

# transcribe() convertit le PCM en flottants avec numpy avant d'appeler le
# modèle : sans lui, seules les fonctions pures restent testables.
requires_numpy = unittest.skipUnless(numpy is not None, "numpy absent")


def settings(**overrides):
    model = {
        "name": "small",
        "device": "cpu",
        "compute_type": "int8",
        "language": "fr",
        "beam_size": 5,
        "initial_prompt": "",
        "vocabulary": "",
        "context": True,
        "preload": False,
    }
    model.update(overrides)
    return {"model": model}


class Segment:
    """Ce que faster-whisper rend, réduit à ce que le tri regarde."""

    def __init__(self, text: str, no_speech_prob: float = 0.0):
        self.text = text
        self.no_speech_prob = no_speech_prob


class FillerTest(unittest.TestCase):
    def test_le_generique_de_sous_titres_ne_vient_jamais_du_micro(self):
        self.assertTrue(is_filler("Sous-titres réalisés par la communauté d'Amara.org", 0.0))
        self.assertTrue(is_filler("Sous-titrage Société Radio-Canada", 0.1))

    def test_un_merci_sur_du_silence_est_une_hallucination(self):
        self.assertTrue(is_filler("Merci.", 0.9))

    def test_un_merci_reellement_prononce_est_garde(self):
        """Le même mot, mais le modèle a bien entendu quelqu'un parler."""
        self.assertFalse(is_filler("Merci.", 0.1))

    def test_la_ponctuation_et_la_casse_ne_sauvent_pas_le_remplissage(self):
        self.assertTrue(is_filler("  « MERCI ! »  ", 0.8))

    def test_une_vraie_phrase_reste_meme_sur_un_no_speech_eleve(self):
        self.assertFalse(is_filler("il faudrait rajouter des images de blocs", 0.99))


class PromptTest(unittest.TestCase):
    def test_sans_rien_le_prompt_reste_vide(self):
        self.assertIsNone(Transcriber(settings()).prompt())

    def test_le_vocabulaire_de_l_utilisateur_ouvre_le_prompt(self):
        transcriber = Transcriber(settings(initial_prompt="Dictée technique."))
        self.assertEqual(transcriber.prompt(), "Dictée technique.")

    def test_le_contexte_prolonge_la_phrase_d_amorce(self):
        transcriber = Transcriber(settings(initial_prompt="Dictée technique."))
        self.assertEqual(
            transcriber.prompt("il faudrait rajouter"),
            "Dictée technique. il faudrait rajouter",
        )

    def test_le_contexte_est_borne_aux_derniers_caracteres(self):
        """Le modèle doit tenir le fil, pas relire toute la dictée."""
        transcriber = Transcriber(settings())
        prompt = transcriber.prompt("mot " * 400)
        self.assertLessEqual(len(prompt), CONTEXT_CHARS)

    def test_contexte_desactive_le_prompt_ignore_ce_qui_precede(self):
        transcriber = Transcriber(settings(context=False))
        self.assertIsNone(transcriber.prompt("il faudrait rajouter"))


class TranscribeTest(unittest.TestCase):
    def transcribe(self, segments, pcm=b"\x01\x02" * 800, context="", **overrides):
        transcriber = Transcriber(settings(**overrides))
        model = mock.Mock()
        model.transcribe.return_value = (iter(segments), None)
        transcriber._model = model
        text = transcriber.transcribe(pcm, context)
        return text, model.transcribe.call_args.kwargs

    @requires_numpy
    def test_les_phrases_sont_recollees(self):
        text, _ = self.transcribe([Segment("Première phrase."), Segment("Et la suite.")])
        self.assertEqual(text, "Première phrase. Et la suite.")

    @requires_numpy
    def test_l_hallucination_est_ecartee_du_texte_rendu(self):
        text, _ = self.transcribe([
            Segment("il faudrait rajouter"),
            Segment("Merci.", no_speech_prob=0.95),
        ])
        self.assertEqual(text, "il faudrait rajouter")

    @requires_numpy
    def test_le_vocabulaire_part_en_hotwords(self):
        _, kwargs = self.transcribe([Segment("texte")], vocabulary="OpenRouter, repos GitHub")
        self.assertEqual(kwargs["hotwords"], "OpenRouter, repos GitHub")

    @requires_numpy
    def test_sans_vocabulaire_aucun_hotword_n_est_impose(self):
        _, kwargs = self.transcribe([Segment("texte")])
        self.assertIsNone(kwargs["hotwords"])

    @requires_numpy
    def test_le_contexte_atteint_bien_le_modele(self):
        _, kwargs = self.transcribe([Segment("des images")], context="il faudrait rajouter")
        self.assertEqual(kwargs["initial_prompt"], "il faudrait rajouter")

    def test_sans_son_le_modele_n_est_pas_derange(self):
        transcriber = Transcriber(settings())
        transcriber._model = mock.Mock()
        self.assertEqual(transcriber.transcribe(b""), "")
        transcriber._model.transcribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
