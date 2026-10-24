"""Usage statistics: words, speed and days in a row, from the history."""

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

NOW = datetime(2026, 10, 24, 18, 0, 0)


def entry(text: str, days_ago: int = 0, duration: float | None = None) -> Entry:
    when = NOW - timedelta(days=days_ago, hours=1)
    return Entry(date=when.isoformat(timespec="seconds"), text=text, duration=duration)


class CountWordsTest(unittest.TestCase):
    def test_marks_said_aloud_are_no_words(self):
        self.assertEqual(stats.count_words("Il m'a dit « je reviens demain » ?"), 6)

    def test_lines_and_names_count_once(self):
        self.assertEqual(stats.count_words("Bonjour Marie,\nmerci pour userName."), 5)


class ComputeTest(unittest.TestCase):
    def test_an_empty_history(self):
        usage = stats.compute([], now=NOW)
        self.assertEqual((usage.dictations, usage.words, usage.streak), (0, 0, 0))
        self.assertIsNone(usage.first)
        self.assertIsNone(usage.words_per_minute)

    def test_words_today_and_this_week(self):
        usage = stats.compute([
            entry("one two three", days_ago=10),
            entry("four five", days_ago=6),
            entry("six seven eight nine", days_ago=7),
            entry("ten", days_ago=0),
        ], now=NOW)
        self.assertEqual(usage.dictations, 4)
        self.assertEqual(usage.words, 10)
        self.assertEqual(usage.words_today, 1)
        self.assertEqual(usage.words_week, 3)
        self.assertEqual(usage.days, 4)
        self.assertEqual(usage.first, date(2026, 10, 14))

    def test_speed_only_counts_the_timed_dictations(self):
        usage = stats.compute([
            entry("a b c d e f g h i j", duration=4.0),
            entry("k l m n o p q r s t", duration=None),
            entry("u v w x y", duration=0.0),
            entry("z", duration=2.0),
        ], now=NOW)
        # 11 words in 6 seconds.
        self.assertEqual(usage.words_per_minute, 110)
        self.assertEqual(usage.listened, 6.0)

    def test_a_streak_reaching_yesterday_still_holds(self):
        entries = [entry("x", days_ago=days) for days in (1, 2, 3, 3, 5, 6, 7, 8, 9)]
        usage = stats.compute(entries, now=NOW)
        self.assertEqual((usage.streak, usage.best_streak), (3, 5))

    def test_a_streak_ends_after_a_whole_day_without_dictation(self):
        usage = stats.compute([entry("x", days_ago=2), entry("x", days_ago=3)], now=NOW)
        self.assertEqual((usage.streak, usage.best_streak), (0, 2))

    def test_a_dictation_today_carries_the_streak_on(self):
        usage = stats.compute([entry("x", days_ago=days) for days in (0, 1, 2)], now=NOW)
        self.assertEqual((usage.streak, usage.best_streak), (3, 3))

    def test_an_unreadable_date_still_counts_its_words(self):
        usage = stats.compute([Entry(date="?", text="lost date"), entry("kept")], now=NOW)
        self.assertEqual((usage.dictations, usage.words, usage.days), (2, 3, 1))


class ReportTest(unittest.TestCase):
    def test_the_lines(self):
        usage = stats.compute([
            entry("one two three four five six", days_ago=1, duration=3.0),
            entry("seven eight", duration=1.0),
        ], now=NOW)
        lines = stats.report(usage)
        self.assertEqual(lines[0], "Dictations  2 over 2 days, since 2026-10-23")
        self.assertEqual(lines[1], "Words       8 — 2 today, 8 these 7 days")
        self.assertEqual(lines[2], "Speed       120 words per minute, over 4 s of dictation")
        self.assertEqual(lines[3], "Streak      2 days in a row (best: 2 days)")

    def test_no_listening_time(self):
        lines = stats.report(stats.compute([entry("a b")], now=NOW))
        self.assertIn("no listening time recorded", lines[2])
        self.assertEqual(lines[3], "Streak      1 day in a row (best: 1 day)")

    def test_long_durations(self):
        self.assertEqual(stats._duration(5400 + 7 * 60), "1 h 37 min")
        self.assertEqual(stats._duration(125), "2 min")


class CommandTest(unittest.TestCase):
    """whisper-desk stats, on a history of its own."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (("STATE_DIR", Path(directory.name) / "state"),
                            ("CONFIG_PATH", Path(directory.name) / "config.toml")):
            patcher = mock.patch.object(config_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config_path = Path(directory.name) / "config.toml"

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["stats", *argv])
        return code, out.getvalue()

    def test_no_dictation_yet(self):
        self.assertEqual(self.run_cli(), (0, "No dictation yet.\n"))

    def test_the_history_switched_off_is_said(self):
        self.config_path.write_text("[output]\nhistory = false\n", encoding="utf-8")
        _code, out = self.run_cli()
        self.assertIn("history = false", out)

    def test_the_figures(self):
        history.append("Résumé de la réunion de lundi", duration=3.0)
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Words       6 — 6 today", out)
        self.assertIn("120 words per minute", out)
        self.assertIn("1 day in a row", out)

    def test_json(self):
        history.append("one two three", duration=1.5)
        _code, out = self.run_cli("--json")
        figures = json.loads(out)
        self.assertEqual((figures["words"], figures["words_per_minute"], figures["streak"]),
                         (3, 120, 1))
        self.assertEqual(figures["seconds"], 1.5)


if __name__ == "__main__":
    unittest.main()
