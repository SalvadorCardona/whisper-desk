"""Error rate of the spoken punctuation corpus, before and after the marks are written.

    python3 bench/punctuation/measure.py              # on the written sentences
    python3 bench/punctuation/measure.py --audio      # through faster-whisper

Words and marks both count: "demain virgule" against "demain," is two errors,
a missing line break one. --audio needs the whisper-desk venv (whisper-desk's own
Python) and the recordings next to this file; the models are those already
downloaded. "Before" is the text whisper-desk wrote until now, corrections and
hesitations included; "after" adds the spoken punctuation.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from whisper_desk import backtrack, hesitations, punctuation  # noqa: E402


def corpus() -> list[dict[str, str]]:
    with (HERE / "corpus.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        row["expected"] = row["expected"].replace("\\n", "\n")
    return rows


def tokens(text: str) -> list[str]:
    return re.findall(r"[\w'’-]+|[,.;:!?«»()\"]|\n", text.lower())


def distance(reference: list[str], hypothesis: list[str]) -> int:
    row = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        previous, row[0] = row[0], i
        for j, hyp in enumerate(hypothesis, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ref != hyp))
    return row[-1]


def error_rate(pairs: list[tuple[str, str]]) -> float:
    errors = sum(distance(tokens(ref), tokens(hyp)) for ref, hyp in pairs)
    return errors / max(1, sum(len(tokens(ref)) for ref, _ in pairs))


def today(text: str) -> str:
    return hesitations.apply(backtrack.apply(text))


def transcripts(model: str, device: str) -> dict[str, str]:
    from faster_whisper import WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    whisper = WhisperModel(model, device=device, compute_type=compute)
    out = {}
    for row in corpus():
        segments, _ = whisper.transcribe(
            str(HERE / "audio" / f"{row['id']}.opus"), language=row["lang"],
            beam_size=5, vad_filter=True, condition_on_previous_text=False,
        )
        out[row["id"]] = " ".join(s.text.strip() for s in segments).strip()
    return out


def report(label: str, raw: dict[str, str], verbose: bool) -> None:
    rows = corpus()
    for group, keep in (("punctuation", lambda r: not r["id"].startswith("ctl")),
                        ("controls", lambda r: r["id"].startswith("ctl"))):
        chosen = [r for r in rows if keep(r)]
        before = [(r["expected"], today(raw[r["id"]])) for r in chosen]
        after = [(r["expected"], punctuation.apply(hyp)) for r, (_, hyp) in zip(chosen, before)]
        exact = sum(tokens(e) == tokens(h) for e, h in after)
        print(f"{label:<28} {group:<12} errors {error_rate(before):6.1%} -> "
              f"{error_rate(after):6.1%}   exact {exact}/{len(chosen)}")
        if verbose:
            for row, (expected, fixed) in zip(chosen, after):
                if tokens(expected) != tokens(fixed):
                    print(f"    {row['id']}: {raw[row['id']]!r} -> {fixed!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--models", default="small:cpu,large-v3-turbo:cuda")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    report("written sentences", {r["id"]: r["spoken"] for r in corpus()}, args.verbose)
    if args.audio:
        for spec in args.models.split(","):
            model, device = spec.split(":")
            report(f"{model} ({device})", transcripts(model, device), args.verbose)


if __name__ == "__main__":
    main()
