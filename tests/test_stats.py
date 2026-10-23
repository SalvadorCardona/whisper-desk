"""Usage statistics: words, pace, streaks and time saved, from the history."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from . import context  # noqa: F401

from whisper_desk import __main__ as cli
from whisper_desk import config as config_module
from whisper_desk import history, stats
from whisper_desk.history import Entry

TODAY = date(2026, 10, 23)


def entry(days_ago: int, text: str, duration: float | None = 6.0, hour: int = 10) -> Entry:
    when = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).replace(hour=hour)
    return Entry(date=when.isoformat(timespec="seconds"), text=text, duration=duration)


class WordsTest(unittest.TestCase):
    def test_a_word_holds_a_letter_or_a_digit(self):
        self.assertEqual(stats.words("Il m'a dit « je reviens » — à 18 h."), 8)

    def test_an_elision_or_a_compound_is_one_word(self):
        self.assertEqual(stats.words("l'adresse d'arrivée est-elle bonne ?"), 4)

    def test_line_breaks_separate_words(self):
        self.assertEqual(stats.words("Bonjour,\n\nmerci"), 2)


class ComputeTest(unittest.TestCase):
    def test_nothing_yet(self):
        usage = stats.compute([], TODAY)
        self.assertEqual((usage.dictations, usage.words, usage.current_streak), (0, 0, 0))
        self.assertIsNone(usage.words_per_minute)
        self.assertIsNone(usage.saved_seconds)

    def test_words_today_and_over_the_last_seven_days(self):
        usage = stats.compute([
            entry(10, "one two three"),
            entry(6, "four five"),
            entry(1, "six"),
            entry(0, "seven eight"),
        ], TODAY)
        self.assertEqual(usage.dictations, 4)
        self.assertEqual(usage.words, 8)
        self.assertEqual(usage.words_today, 2)
        self.assertEqual(usage.words_last_7_days, 5)
        self.assertEqual(usage.days_active, 4)

    def test_the_pace_is_words_over_listening_time(self):
        # 30 words in 12 seconds of listening: 150 words per minute.
        usage = stats.compute([entry(0, " ".join(["mot"] * 10), 4.0),
                               entry(0, " ".join(["mot"] * 20), 8.0)], TODAY)
        self.assertEqual(usage.listened_seconds, 12.0)
        self.assertEqual(usage.words_per_minute, 150.0)

    def test_the_pace_follows_the_latest_dictations(self):
        slow = [entry(30, "mot", 60.0)] * 50
        fast = [entry(0, " ".join(["mot"] * 10), 4.0)] * stats.PACE_DICTATIONS
        usage = stats.compute(slow + fast, TODAY)
        self.assertEqual(usage.words_per_minute, 150.0)

    def test_dictations_without_a_duration_count_words_but_not_the_pace(self):
        # The history.log of earlier versions kept no listening time.
        usage = stats.compute([entry(2, "un deux trois", None), entry(0, "quatre cinq", 2.0)], TODAY)
        self.assertEqual(usage.words, 5)
        self.assertEqual(usage.words_per_minute, 60.0)
        self.assertEqual(usage.listened_seconds, 2.0)

    def test_only_the_legacy_log_gives_no_pace(self):
        usage = stats.compute([entry(0, "un deux", None)], TODAY)
        self.assertIsNone(usage.words_per_minute)
        self.assertIsNone(usage.saved_seconds)

    def test_time_saved_against_typing(self):
        # 80 words take two minutes at 40 words per minute; said in 30 seconds.
        usage = stats.compute([entry(0, " ".join(["mot"] * 80), 30.0)], TODAY)
        self.assertEqual(usage.saved_seconds, 90.0)

    def test_since_keeps_the_latest_days_only(self):
        usage = stats.compute([entry(40, "old words here"), entry(3, "recent")], TODAY,
                              since=TODAY - timedelta(days=6))
        self.assertEqual((usage.dictations, usage.words), (1, 1))

    def test_an_unreadable_date_counts_words_but_no_day(self):
        usage = stats.compute([Entry(date="?", text="deux mots")], TODAY)
        self.assertEqual((usage.words, usage.days_active, usage.current_streak), (2, 0, 0))


class StreakTest(unittest.TestCase):
    def streaks(self, *days_ago: int) -> tuple[int, int]:
        usage = stats.compute([entry(days, "mot") for days in sorted(days_ago, reverse=True)], TODAY)
        return usage.current_streak, usage.longest_streak

    def test_days_in_a_row_up_to_today(self):
        self.assertEqual(self.streaks(0, 1, 2), (3, 3))

    def test_yesterday_still_counts_before_today_s_first_dictation(self):
        self.assertEqual(self.streaks(1, 2), (2, 2))

    def test_a_missed_day_breaks_it(self):
        self.assertEqual(self.streaks(2, 3, 4, 5), (0, 4))

    def test_the_longest_streak_is_kept_after_a_break(self):
        self.assertEqual(self.streaks(0, 5, 6, 7, 8), (1, 4))

    def test_several_dictations_a_day_count_one_day(self):
        usage = stats.compute([entry(0, "a", hour=9), entry(0, "b", hour=18)], TODAY)
        self.assertEqual((usage.current_streak, usage.days_active), (1, 1))


class ReportTest(unittest.TestCase):
    def test_the_figures_a_person_reads(self):
        usage = stats.compute([entry(1, " ".join(["mot"] * 1200), 300.0),
                               entry(0, " ".join(["mot"] * 300), 120.0)], TODAY)
        text = "\n".join(stats.report(usage))
        self.assertIn("Words dictated      1 500", text)
        self.assertIn("Current streak      2 days (longest: 2 days)", text)
        self.assertIn("Listening time      7 min", text)
        self.assertIn("Pace                214 words per minute", text)
        # 1500 words typed at 40 a minute: 37 min 30 s, against 7 min said.
        self.assertIn("Time saved          30 min", text)

    def test_no_pace_without_listening_time(self):
        text = "\n".join(stats.report(stats.compute([entry(0, "mot", None)], TODAY)))
        self.assertIn("no listening time recorded yet", text)
        self.assertNotIn("Time saved", text)

    def test_a_slow_dictation_saves_no_time(self):
        text = "\n".join(stats.report(stats.compute([entry(0, "un mot", 60.0)], TODAY)))
        self.assertIn("Time saved          none yet", text)

    def test_hours(self):
        self.assertEqual(stats._duration(3900), "1 h 05 min")


class CommandTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(config_module, "STATE_DIR", Path(directory.name) / "state")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(list(argv)), 0)
        return out.getvalue()

    def test_no_dictation_yet(self):
        self.assertEqual(self.run_cli("stats"), "No dictation yet.\n")

    def test_the_report(self):
        history.append("bonjour à tous", duration=3.0)
        out = self.run_cli("stats")
        self.assertIn("Words dictated      3", out)
        self.assertIn("Today               3 words", out)

    def test_json_for_a_status_bar(self):
        history.append("bonjour à tous", duration=3.0)
        figures = json.loads(self.run_cli("stats", "--json"))
        self.assertEqual(figures["words"], 3)
        self.assertEqual(figures["words_per_minute"], 60.0)
        self.assertEqual(figures["current_streak"], 1)

    def test_days_leaves_the_older_dictations_out(self):
        history.append("il y a longtemps", duration=3.0, now=datetime.now() - timedelta(days=30))
        self.assertEqual(self.run_cli("stats", "--days", "7"), "No dictation in the last 7 days.\n")
        self.assertIn("Words dictated      4", self.run_cli("stats", "--days", "31"))


if __name__ == "__main__":
    unittest.main()
