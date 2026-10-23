"""Usage statistics, read from the history: words, pace, streak, time saved."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from .history import Entry

# Wispr Flow pools its pace over the last 100 sessions: one long dictation
# months ago should not weigh on today's figure.
PACE_DICTATIONS = 100
# What dictating is compared with. An assumption, said as such in the
# report: an average typist on a computer keyboard.
TYPING_WORDS_PER_MINUTE = 40
# A word holds a letter or a digit: the « of a quote or a lone dash is not one.
_WORD = re.compile(r"\w")


def words(text: str) -> int:
    """Words as a reader counts them: "l'adresse" is one, "«" none."""
    return sum(1 for token in text.split() if _WORD.search(token))


@dataclass
class Usage:
    dictations: int
    words: int
    words_today: int
    words_last_7_days: int
    days_active: int
    current_streak: int             # days in a row, ending today or yesterday
    longest_streak: int
    listened_seconds: float         # over the dictations whose duration is known
    words_per_minute: float | None  # over the last PACE_DICTATIONS timed ones
    saved_seconds: float | None     # typing time minus listening time

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days with a dictation."""
    longest = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    # A streak is not broken before the day is over: yesterday's still counts
    # this morning, until a dictation today carries it on.
    current = 0
    day = today if today in days else today - timedelta(days=1)
    while day in days:
        current += 1
        day -= timedelta(days=1)
    return current, longest


def compute(entries: list[Entry], today: date, since: date | None = None) -> Usage:
    """The figures of these dictations, oldest first; only from `since` if given."""
    dated = [(entry, entry.when) for entry in entries]
    if since is not None:
        dated = [(entry, when) for entry, when in dated if when is not None and when.date() >= since]

    counts = [(entry, when, words(entry.text)) for entry, when in dated]
    days = {when.date() for _, when, _ in counts if when is not None}
    week = today - timedelta(days=6)
    current, longest = _streaks(days, today)

    # The listening time includes the silence that ends a dictation: the pace
    # is the user's speed with whisper-desk, not their speech rate alone.
    timed = [(entry.duration, count) for entry, _, count in counts
             if entry.duration is not None and entry.duration > 0]
    listened = sum(duration for duration, _ in timed)
    recent = timed[-PACE_DICTATIONS:]
    recent_seconds = sum(duration for duration, _ in recent)
    pace = sum(count for _, count in recent) * 60 / recent_seconds if recent_seconds else None
    timed_words = sum(count for _, count in timed)
    saved = timed_words * 60 / TYPING_WORDS_PER_MINUTE - listened if timed else None

    return Usage(
        dictations=len(counts),
        words=sum(count for _, _, count in counts),
        words_today=sum(count for _, when, count in counts if when and when.date() == today),
        words_last_7_days=sum(count for _, when, count in counts if when and when.date() >= week),
        days_active=len(days),
        current_streak=current,
        longest_streak=longest,
        listened_seconds=round(listened, 1),
        words_per_minute=round(pace, 1) if pace is not None else None,
        saved_seconds=round(saved, 1) if saved is not None else None,
    )


def _duration(seconds: float) -> str:
    """1 h 05 min, 12 min, 40 s: what a person reads at a glance."""
    seconds = int(round(abs(seconds)))
    if seconds >= 3600:
        return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"
    if seconds >= 60:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def _number(count: int) -> str:
    """12 213: thousands grouped the way both French and English readers take."""
    return f"{count:,}".replace(",", " ")


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def report(usage: Usage) -> list[str]:
    """The figures, one per line, for the terminal."""
    lines = [
        f"Words dictated      {_number(usage.words)}",
        f"Dictations          {_number(usage.dictations)}",
        f"Today               {_number(usage.words_today)} words",
        f"Last 7 days         {_number(usage.words_last_7_days)} words",
        f"Current streak      {_days(usage.current_streak)} (longest: {_days(usage.longest_streak)})",
        f"Days with dictation {usage.days_active}",
    ]
    if usage.words_per_minute is None:
        lines.append("Pace                - (no listening time recorded yet)")
        return lines
    lines += [
        f"Listening time      {_duration(usage.listened_seconds)}",
        f"Pace                {usage.words_per_minute:.0f} words per minute"
        f" (last {PACE_DICTATIONS} dictations, silences included)",
    ]
    saved = _duration(usage.saved_seconds) if usage.saved_seconds > 0 else "none yet"
    lines.append(f"Time saved          {saved}"
                 f" (against typing at {TYPING_WORDS_PER_MINUTE} words per minute)")
    return lines
