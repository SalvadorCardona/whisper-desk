"""Usage statistics drawn from the history: words, speed, days in a row.

Wispr Flow counts on its servers; here the history already holds every
dictation, so the figures are worked out from it on the spot, and nothing is
stored besides. What the history no longer holds — purged, deleted, or never
written with `history = false` — is not counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .history import Entry

# A mark said aloud ("?", "«", "—") stands alone between spaces, and is no word.
WORD = re.compile(r"\w")
WEEK = 7


@dataclass
class Usage:
    dictations: int = 0
    words: int = 0
    words_today: int = 0
    words_week: int = 0             # today and the six days before
    days: int = 0                   # days with at least one dictation
    first: date | None = None
    listened: float = 0.0           # seconds, over the dictations that recorded it
    timed_words: int = 0            # the words of those dictations
    streak: int = 0                 # days in a row, up to today or yesterday
    best_streak: int = 0

    @property
    def words_per_minute(self) -> int | None:
        if self.listened <= 0 or not self.timed_words:
            return None
        return round(self.timed_words / (self.listened / 60))


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if WORD.search(token))


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """The current run of days, and the longest one.

    A run that reached yesterday still holds: the day is not over, and a
    first dictation in the evening carries it on.
    """
    best = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    current = run if previous is not None and today - previous <= timedelta(days=1) else 0
    return current, best


def compute(entries: list[Entry], now: datetime | None = None) -> Usage:
    today = (now or datetime.now()).date()
    week_start = today - timedelta(days=WEEK - 1)
    usage = Usage()
    days: set[date] = set()
    for entry in entries:
        words = count_words(entry.text)
        usage.dictations += 1
        usage.words += words
        if entry.duration is not None and entry.duration > 0:
            usage.listened += entry.duration
            usage.timed_words += words
        when = entry.when
        if when is None:
            continue
        day = when.date()
        days.add(day)
        if day == today:
            usage.words_today += words
        if week_start <= day <= today:
            usage.words_week += words
    usage.days = len(days)
    usage.first = min(days) if days else None
    usage.streak, usage.best_streak = _streaks(days, today)
    return usage


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return f"{round(seconds)} s"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def report(usage: Usage) -> list[str]:
    """The figures as `whisper-desk stats` prints them, one line each."""
    since = f", since {usage.first.isoformat()}" if usage.first else ""
    lines = [
        f"Dictations  {usage.dictations:,} over {_days(usage.days)}{since}",
        f"Words       {usage.words:,} — {usage.words_today:,} today, "
        f"{usage.words_week:,} these {WEEK} days",
    ]
    speed = usage.words_per_minute
    if speed is None:
        lines.append("Speed       — (no listening time recorded)")
    else:
        lines.append(f"Speed       {speed:,} words per minute, "
                     f"over {_duration(usage.listened)} of dictation")
    lines.append(f"Streak      {_days(usage.streak)} in a row (best: {_days(usage.best_streak)})")
    return lines


def as_dict(usage: Usage) -> dict:
    """The same figures for a script or a status bar."""
    return {
        "dictations": usage.dictations,
        "words": usage.words,
        "words_today": usage.words_today,
        "words_week": usage.words_week,
        "days": usage.days,
        "first": usage.first.isoformat() if usage.first else None,
        "seconds": round(usage.listened, 1),
        "words_per_minute": usage.words_per_minute,
        "streak": usage.streak,
        "best_streak": usage.best_streak,
    }
