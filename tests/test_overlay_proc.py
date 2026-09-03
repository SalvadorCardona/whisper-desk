"""Pilotage de la fenêtre d'écoute : le tube peut casser, pas la fermeture."""

from __future__ import annotations

import threading
import unittest

from . import context  # noqa: F401

from whisper_desk.overlay_proc import OverlayProcess

CONFIG = {
    "overlay": {
        "enabled": True,
        "accent": "#e46212",
        "width": 232,
        "height": 64,
        "bars": 15,
        "position": "bottom-center",
        "margin": 96,
    }
}


class FakeStdin:
    def __init__(self, broken: bool = False):
        self.broken = broken
        self.lines: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.broken:
            raise BrokenPipeError("tube fermé")
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        if self.broken:
            raise BrokenPipeError("tube fermé")

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdin: FakeStdin, returncode=None):
        self.stdin = stdin
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def attached(stdin: FakeStdin) -> tuple[OverlayProcess, FakeProcess]:
    overlay = OverlayProcess(CONFIG)
    process = FakeProcess(stdin)
    overlay._process = process
    return overlay, process


class SendTest(unittest.TestCase):
    def test_une_commande_par_ligne(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_state("working")
        overlay.set_level(0.5)
        self.assertEqual(stdin.lines, [b"state working\n", b"level 0.500\n"])

    def test_l_equalizer_voyage_sur_la_meme_ligne_que_le_niveau(self):
        """Une écriture par mesure : deux lignes s'entrelaceraient sur le tube."""
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(0.5, [0.25, 0.75])
        self.assertEqual(stdin.lines, [b"level 0.500 0.250 0.750\n"])

    def test_le_nombre_de_barres_vient_de_la_configuration(self):
        self.assertEqual(OverlayProcess(CONFIG).bars, 15)

    def test_overlay_desactive_personne_ne_regarde_les_bandes(self):
        config = {"overlay": {**CONFIG["overlay"], "enabled": False}}
        self.assertEqual(OverlayProcess(config).bars, 0)

    def test_le_niveau_est_borne_a_trois_decimales(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(1 / 3)
        self.assertEqual(stdin.lines, [b"level 0.333\n"])

    def test_le_texte_copie_passe_en_base64_sur_une_ligne(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        self.assertTrue(overlay.copy("phrase avec espaces\net saut"))
        self.assertEqual(len(stdin.lines), 1)
        self.assertTrue(stdin.lines[0].startswith(b"copy "))
        self.assertEqual(stdin.lines[0].count(b"\n"), 1)


class BrokenPipeTest(unittest.TestCase):
    """Un tube cassé ne doit pas laisser la fenêtre orpheline à l'écran."""

    def test_l_ecriture_ratee_n_est_pas_fatale(self):
        overlay, _ = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)  # ne lève pas
        self.assertFalse(overlay.alive)

    def test_la_fenetre_est_quand_meme_fermee(self):
        overlay, process = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)
        overlay.stop()
        self.assertTrue(process.terminated or process.killed)

    def test_plus_rien_n_est_envoye_apres_la_casse(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.set_level(0.1)
        stdin.broken = True
        overlay.set_level(0.2)
        stdin.broken = False
        overlay.set_level(0.3)
        self.assertEqual(stdin.lines, [b"level 0.100\n"])

    def test_la_copie_echoue_franchement(self):
        overlay, _ = attached(FakeStdin(broken=True))
        overlay.set_level(0.5)
        self.assertFalse(overlay.copy("texte"))
        self.assertFalse(overlay.save_clipboard())
        self.assertFalse(overlay.restore_clipboard())


class StopTest(unittest.TestCase):
    def test_l_arret_demande_poliment_la_fermeture(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        overlay.stop()
        self.assertEqual(stdin.lines, [b"quit\n"])
        self.assertTrue(stdin.closed)

    def test_arret_idempotent(self):
        overlay, _ = attached(FakeStdin())
        overlay.stop()
        overlay.stop()  # ne lève pas
        self.assertFalse(overlay.alive)

    def test_un_process_mort_n_est_plus_vivant(self):
        overlay = OverlayProcess(CONFIG)
        overlay._process = FakeProcess(FakeStdin(), returncode=0)
        self.assertFalse(overlay.alive)


class ConcurrencyTest(unittest.TestCase):
    """Les niveaux viennent du fil micro, les états du fil de la dictée."""

    def test_les_lignes_ne_s_entrelacent_pas(self):
        stdin = FakeStdin()
        overlay, _ = attached(stdin)
        start = threading.Barrier(4)

        def spam(send):
            start.wait()
            for _ in range(200):
                send()

        threads = [
            threading.Thread(target=spam, args=(lambda: overlay.set_level(0.25),)),
            threading.Thread(target=spam, args=(lambda: overlay.set_state("listening"),)),
            threading.Thread(target=spam, args=(lambda: overlay.set_state("working"),)),
        ]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(len(stdin.lines), 600)
        self.assertEqual(
            set(stdin.lines),
            {b"level 0.250\n", b"state listening\n", b"state working\n"},
        )


if __name__ == "__main__":
    unittest.main()
